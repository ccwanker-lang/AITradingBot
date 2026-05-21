"""
Automatische check via Telegram — stuurt samenvatting van bot prestaties.
Draait via cron elke 3 dagen.
"""
import json
import os
import sys
import requests
from datetime import datetime, timedelta
from pathlib import Path

ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(ROOT))

from dotenv import load_dotenv
load_dotenv(ROOT / ".env")

TOKEN   = os.getenv("TELEGRAM_TOKEN", "")
CHAT_ID = os.getenv("TELEGRAM_CHAT_ID", "")


def send(text: str):
    if not TOKEN or not CHAT_ID:
        print("Geen Telegram credentials gevonden.")
        return
    requests.post(
        f"https://api.telegram.org/bot{TOKEN}/sendMessage",
        json={"chat_id": CHAT_ID, "text": text, "parse_mode": "HTML"},
        timeout=10,
    )


def load_trades() -> list:
    path = ROOT / "logs" / "trades.json"
    if not path.exists():
        return []
    return json.loads(path.read_text())


def calc_stats(trades: list) -> dict:
    exits = [t for t in trades if t.get("type") in ("sell", "cover") and "pnl_pct" in t]
    if not exits:
        return {}

    wins   = [t for t in exits if t["pnl_pct"] > 0]
    losses = [t for t in exits if t["pnl_pct"] <= 0]
    wr     = len(wins) / len(exits) * 100

    avg_win  = sum(t["pnl_pct"] for t in wins)  / max(len(wins), 1) * 100
    avg_loss = sum(t["pnl_pct"] for t in losses) / max(len(losses), 1) * 100
    pf = abs(avg_win * len(wins)) / max(abs(avg_loss * len(losses)), 0.0001)

    # TP1 rate
    tp1_hits = sum(1 for t in trades if t.get("type") == "partial_tp1")
    tp1_rate = tp1_hits / max(len(exits), 1) * 100

    # Recente 10
    recent = exits[-10:]
    recent_wr = sum(1 for t in recent if t["pnl_pct"] > 0) / max(len(recent), 1) * 100

    # Huidige streak
    streak = 0
    for t in reversed(exits):
        if streak == 0:
            streak = 1 if t["pnl_pct"] > 0 else -1
        elif streak > 0 and t["pnl_pct"] > 0:
            streak += 1
        elif streak < 0 and t["pnl_pct"] <= 0:
            streak -= 1
        else:
            break

    # Trades afgelopen 3 dagen
    cutoff = (datetime.now() - timedelta(days=3)).isoformat()
    recent_3d = [t for t in exits if t.get("timestamp", "") >= cutoff]

    return {
        "total":     len(exits),
        "wr":        round(wr, 1),
        "recent_wr": round(recent_wr, 1),
        "pf":        round(pf, 3),
        "tp1_rate":  round(tp1_rate, 1),
        "avg_win":   round(avg_win, 2),
        "avg_loss":  round(avg_loss, 2),
        "streak":    streak,
        "new_3d":    len(recent_3d),
    }


def load_portfolio() -> dict:
    path = ROOT / "logs" / "performance.json"
    if not path.exists():
        return {}
    try:
        return json.loads(path.read_text())
    except Exception:
        return {}


def load_state() -> dict:
    path = ROOT / "logs" / "state.json"
    if not path.exists():
        return {}
    try:
        return json.loads(path.read_text())
    except Exception:
        return {}


def build_message(stats: dict, portfolio: dict, state: dict) -> str:
    now = datetime.now().strftime("%d %b %Y %H:%M")

    portfolio_val = portfolio.get("portfolio_value", state.get("portfolio_value", 0))
    initial       = portfolio.get("initial_capital", 1000)
    pnl_pct       = (portfolio_val - initial) / initial * 100 if initial else 0
    drawdown      = state.get("drawdown", portfolio.get("max_drawdown", 0)) * 100
    open_pos      = len(state.get("positions", {}))

    wr        = stats.get("wr", 0)
    recent_wr = stats.get("recent_wr", 0)
    pf        = stats.get("pf", 0)
    tp1_rate  = stats.get("tp1_rate", 0)
    streak    = stats.get("streak", 0)
    new_3d    = stats.get("new_3d", 0)
    total     = stats.get("total", 0)

    # Beoordelingen
    wr_ok  = "✅" if wr >= 45 else "⚠️"
    pf_ok  = "✅" if pf >= 1.5 else "⚠️"
    tp1_ok = "✅" if tp1_rate >= 35 else "⚠️"

    streak_str = f"+{streak} wins op rij" if streak > 0 else f"{abs(streak)} losses op rij"
    streak_icon = "🔥" if streak >= 3 else ("😬" if streak <= -3 else "➡️")

    lines = [
        f"<b>📊 Auto-Check — {now}</b>",
        "",
        f"<b>Portfolio:</b> ${portfolio_val:,.2f}  ({pnl_pct:+.2f}%)",
        f"<b>Drawdown:</b> {drawdown:.1f}%  |  Open posities: {open_pos}",
        "",
        f"<b>Win Rate:</b> {wr_ok} {wr:.1f}%  (recent: {recent_wr:.1f}%)",
        f"<b>Profit Factor:</b> {pf_ok} {pf:.3f}  (target ≥1.5)",
        f"<b>TP1 rate:</b> {tp1_ok} {tp1_rate:.1f}%  (target >35%)",
        f"<b>Gem. win:</b> +{stats.get('avg_win', 0):.2f}%  |  Gem. verlies: {stats.get('avg_loss', 0):.2f}%",
        "",
        f"<b>Trades totaal:</b> {total}  |  Afgelopen 3d: {new_3d}",
        f"{streak_icon} Streak: {streak_str}",
        "",
    ]

    # Oordeel
    issues = []
    if wr < 45:
        issues.append(f"⚠️ WR {wr:.1f}% onder target (45%)")
    if pf < 1.5:
        issues.append(f"⚠️ PF {pf:.3f} onder target (1.5)")
    if tp1_rate < 35:
        issues.append(f"⚠️ TP1 rate {tp1_rate:.1f}% — eerste target wordt zelden bereikt")
    if streak <= -4:
        issues.append(f"🚨 {abs(streak)} verliesgevende trades op rij — controleer bot!")

    if issues:
        lines.append("<b>Aandachtspunten:</b>")
        lines.extend(issues)
    else:
        lines.append("✅ Alles ziet er goed uit — geen actie nodig.")

    lines.append("")
    lines.append("Typ <b>check</b> in Claude Code voor volledige diagnose.")

    return "\n".join(lines)


def main():
    trades    = load_trades()
    stats     = calc_stats(trades)
    portfolio = load_portfolio()
    state     = load_state()

    if not stats:
        send("⚠️ Auto-check: geen trades gevonden in logs.")
        return

    msg = build_message(stats, portfolio, state)
    send(msg)
    print("Check verstuurd naar Telegram.")


if __name__ == "__main__":
    main()
