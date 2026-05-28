#!/usr/bin/env python3
"""Dagelijkse bot health check — stuurt Telegram alert als er iets mis is."""
import json
import os
import subprocess
import time
import urllib.request
from pathlib import Path
from datetime import datetime

BASE = Path(__file__).parent.parent
LOGS = BASE / "logs"

try:
    from dotenv import load_dotenv
    load_dotenv(BASE / ".env")
except ImportError:
    pass

TOKEN = os.getenv("TELEGRAM_TOKEN", "")
CHAT_ID = os.getenv("TELEGRAM_CHAT_ID", "")


def send_telegram(msg: str):
    if not TOKEN or not CHAT_ID:
        return
    url = f"https://api.telegram.org/bot{TOKEN}/sendMessage"
    data = json.dumps({"chat_id": CHAT_ID, "text": msg, "parse_mode": "HTML"}).encode()
    req = urllib.request.Request(url, data, {"Content-Type": "application/json"})
    try:
        urllib.request.urlopen(req, timeout=10)
    except Exception as e:
        print(f"Telegram fout: {e}")


def load_json(path, default):
    try:
        return json.loads(Path(path).read_text())
    except Exception:
        return default


def check_bot():
    problemen = []
    info = []

    # 1 — Bot actief?
    result = subprocess.run(["pgrep", "-f", "bot.py"], capture_output=True)
    bot_actief = result.returncode == 0
    if not bot_actief:
        problemen.append("🔴 <b>BOT GESTOPT</b> — bot.py draait niet meer!")
    else:
        info.append("✅ Bot actief")

    # 2 — State lezen
    state = load_json(LOGS / "bot_state.json", {})
    portfolio_pnl = None

    # 3 — Performance
    try:
        trades = load_json(LOGS / "trades.json", [])
        closed = [t for t in trades if t.get("type") in ("sell", "cover")]
        if closed:
            pnls = [t.get("pnl_pct", 0) for t in closed]
            wins = [p for p in pnls if p > 0]
            wr = len(wins) / len(pnls) if pnls else 0
            pf_wins = sum(p for p in pnls if p > 0)
            pf_loss = abs(sum(p for p in pnls if p < 0))
            pf = pf_wins / pf_loss if pf_loss > 0 else 99
            info.append(f"📊 WR: {wr:.0%} | PF: {pf:.2f} | Trades: {len(closed)}")

            # Verliesreeks
            recent = [t.get("pnl_pct", 0) for t in closed[-5:]]
            streak = sum(1 for p in recent if p < 0)
            if streak >= 5:
                problemen.append(f"⚠️ <b>Verliesreeks: {streak} op rij</b> — mogelijk systeem-probleem")
    except Exception:
        pass

    # 4 — Engine state (portfolio, daily SL)
    engine = load_json(LOGS / "engine_state.json", {})
    daily_sl = state.get("daily_sl_count", engine.get("daily_sl_count", 0))
    if daily_sl >= 3:
        problemen.append(f"🛑 <b>Daily SL limiet bereikt ({daily_sl}/3)</b> — bot handelt niet meer vandaag")
    elif daily_sl >= 2:
        info.append(f"⚠️ Daily SL: {daily_sl}/3 (nog 1 stop dan blokkade)")

    # 5 — Drawdown
    perf_state = load_json(LOGS / "state.json", {})
    portfolio = perf_state.get("portfolio", {})
    dd = portfolio.get("drawdown", 0)
    pnl_pct = portfolio.get("pnl_pct", 0)
    portfolio_val = portfolio.get("total_value", 0)
    if dd > 0.10:
        problemen.append(f"📉 <b>Hoge drawdown: {dd:.1%}</b> — boven 10% drempel")
    info.append(f"💰 Portfolio: ${portfolio_val:.2f} ({pnl_pct:+.1%})")

    # 6 — LSTM accuracy
    try:
        perf = load_json(LOGS / "performance.json", {})
        lstm_acc = None
        if isinstance(perf, dict):
            lstm_acc = perf.get("lstm_val_acc")
        if lstm_acc and lstm_acc < 0.35:
            problemen.append(f"🤖 <b>LSTM val_acc: {lstm_acc:.1%}</b> — bijna random, hertrainen aanbevolen")
    except Exception:
        pass

    # 7 — Bot vastgelopen? (laatste update ouder dan 5 min)
    try:
        state_file = LOGS / "state.json"
        if state_file.exists():
            age = time.time() - state_file.stat().st_mtime
            if age > 300:
                problemen.append(f"⏰ <b>Bot reageert niet</b> — state.json is {age/60:.0f} min oud")
    except Exception:
        pass

    # 8 — Inactiviteitscheck: laatste trade > 8 uur geleden?
    # Detecteert wanneer filters (ranging_skip etc.) de bot stilleggen.
    try:
        perf_list = load_json(LOGS / "performance.json", [])
        trades_raw = load_json(LOGS / "trades.json", [])
        # Zoek de meest recente trade (entry of exit)
        last_trade_time = None
        for t in trades_raw:
            for ts_key in ("open_time", "close_time", "timestamp"):
                ts = t.get(ts_key)
                if ts:
                    try:
                        import re
                        ts_clean = re.sub(r"\.\d+$", "", str(ts).replace("Z", ""))
                        from datetime import datetime as _dt
                        dt = _dt.fromisoformat(ts_clean)
                        if last_trade_time is None or dt > last_trade_time:
                            last_trade_time = dt
                    except Exception:
                        pass
        # Ook uit engine_state kijken
        engine_raw = load_json(LOGS / "engine_state.json", {})
        for ts_key in ("last_trade_time", "last_entry_time"):
            ts = engine_raw.get(ts_key)
            if ts:
                try:
                    import re
                    ts_clean = re.sub(r"\.\d+$", "", str(ts).replace("Z", ""))
                    from datetime import datetime as _dt
                    dt = _dt.fromisoformat(ts_clean)
                    if last_trade_time is None or dt > last_trade_time:
                        last_trade_time = dt
                except Exception:
                    pass
        if last_trade_time:
            from datetime import datetime as _dt
            inactief_uur = (_dt.now() - last_trade_time).total_seconds() / 3600
            if inactief_uur > 24:
                problemen.append(
                    f"😴 <b>Bot inactief: {inactief_uur:.0f}u geen trades</b> — "
                    f"filters blokkeren mogelijk alle entries (ranging_skip?)"
                )
            elif inactief_uur > 8:
                info.append(
                    f"⚠️ Geen trade in {inactief_uur:.0f}u — mogelijke filter-blokkade"
                )
    except Exception:
        pass

    return problemen, info


def main():
    problemen, info = check_bot()
    now = datetime.now().strftime("%d-%m-%Y %H:%M")

    if problemen:
        msg = f"🚨 <b>Monster Bot Alert — {now}</b>\n\n"
        msg += "\n".join(problemen)
        msg += "\n\n" + "\n".join(info)
        msg += "\n\n<i>Verbind met Pi om te fixen: sudo journalctl -u cryptobot -n 50</i>"
        send_telegram(msg)
        print(f"ALERT verstuurd: {len(problemen)} probleem/problemen")
    else:
        msg = f"✅ <b>Monster Bot OK — {now}</b>\n\n"
        msg += "\n".join(info)
        send_telegram(msg)
        print("Alles OK — dagrapport verstuurd")


if __name__ == "__main__":
    main()
