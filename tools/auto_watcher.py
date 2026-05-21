#!/usr/bin/env python3
"""
Auto-watcher: monitort live signalen en stuurt Telegram-alert bij sterke setup (4+ confluences).
Runs via cron elke 15 minuten. Stuur GEEN alert als er niks interessants is.
"""
import json
import os
import urllib.request
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path

BASE = Path(__file__).parent.parent
LOGS = BASE / "logs"
MIN_CONFLUENCES = 4
MIN_CONFIDENCE = 0.40  # Alert drempel iets onder bot-drempel zodat we vroeg waarschuwen

try:
    from dotenv import load_dotenv
    load_dotenv(BASE / ".env")
except ImportError:
    pass

TOKEN = os.getenv("TELEGRAM_TOKEN", "")
CHAT_ID = os.getenv("TELEGRAM_CHAT_ID", "")
BOT_MIN_CONF = float(os.getenv("MIN_CONFIDENCE", "0.46"))


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


def get_open_symbols():
    state = load_json(LOGS / "state.json", {})
    positions = state.get("positions", {})
    return set(positions.keys())


def analyse_signals():
    perf_data = load_json(LOGS / "performance.json", [])
    if not isinstance(perf_data, list) or not perf_data:
        return []

    # Groepeer per symbool, pak meest recente entry
    per_symbol = defaultdict(list)
    for entry in perf_data:
        sym = entry.get("symbol", "")
        if sym:
            per_symbol[sym].append(entry)

    open_symbols = get_open_symbols()
    alerts = []

    for sym in ["BTC/USDT", "ETH/USDT", "SOL/USDT"]:
        entries = per_symbol.get(sym, [])
        if not entries:
            continue

        latest = entries[-1]
        ts = latest.get("timestamp", "")[:16]
        conf = latest.get("confidence", 0)
        regime = latest.get("regime", "onbekend")
        signal = latest.get("signal", 0)
        reasons = latest.get("entry_reasons", [])

        if not isinstance(reasons, list):
            reasons = []

        n_confluences = len(reasons)

        # Bepaal richting
        if signal > 0:
            richting = "LONG"
            richting_emoji = "📈"
        elif signal < 0:
            richting = "SHORT"
            richting_emoji = "📉"
        else:
            richting = "NEUTRAAL"
            richting_emoji = "➡️"

        # Alleen alerteren bij sterke setups
        if n_confluences < MIN_CONFLUENCES:
            continue
        if abs(signal) < 0.1:
            continue

        # Bouw confluences lijst
        conf_lines = []
        for r in reasons[:6]:
            if isinstance(r, dict):
                naam = r.get("naam", str(r))
                score = r.get("score", None)
                if score is not None:
                    conf_lines.append(f"✓ {naam} ({score:.2f})")
                else:
                    conf_lines.append(f"✓ {naam}")
            else:
                conf_lines.append(f"✓ {str(r)}")

        # Regime leesbaar maken
        regime_labels = {
            "bull_trend": "Bull Trend 🐂",
            "bear_trend": "Bear Trend 🐻",
            "ranging": "Ranging ↔️",
            "high_vol": "Hoge Vol ⚡",
            "accumulation": "Accumulatie 📦",
        }
        regime_label = regime_labels.get(regime, regime)

        has_position = sym in open_symbols
        positie_note = "\n<i>⚠️ Bot heeft al open positie in dit symbool</i>" if has_position else ""

        # Confidence vs drempel
        conf_vs_threshold = f"{conf:.3f}"
        if conf >= BOT_MIN_CONF:
            conf_vs_threshold += f" ✅ (boven drempel {BOT_MIN_CONF})"
        else:
            delta = BOT_MIN_CONF - conf
            conf_vs_threshold += f" ⏳ (nog {delta:.3f} onder drempel {BOT_MIN_CONF})"

        alerts.append({
            "sym": sym,
            "richting": richting,
            "richting_emoji": richting_emoji,
            "regime": regime_label,
            "conf": conf,
            "conf_str": conf_vs_threshold,
            "n_conf": n_confluences,
            "conf_lines": conf_lines,
            "ts": ts,
            "positie_note": positie_note,
        })

    return alerts


def build_message(alerts):
    if not alerts:
        return None

    now = datetime.now(timezone.utc).strftime("%H:%M UTC")
    parts = []

    for a in alerts:
        conf_block = "\n".join(a["conf_lines"])
        msg = (
            f"⚡ <b>Setup Alert — {a['sym']}</b> [{now}]\n\n"
            f"📊 <b>Regime:</b> {a['regime']}\n"
            f"{a['richting_emoji']} <b>Richting:</b> {a['richting']}\n"
            f"🔥 <b>Confluences:</b> {a['n_conf']} aanwezig\n"
            f"🎯 <b>Confidence:</b> {a['conf_str']}\n\n"
            f"<b>Actieve signalen:</b>\n{conf_block}"
            f"{a['positie_note']}\n\n"
            f"<i>Bot kijkt naar entry — nog niet gehandeld</i>"
        )
        parts.append(msg)

    return "\n\n---\n\n".join(parts)


def main():
    now_str = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
    print(f"Auto-watcher gestart: {now_str}")

    alerts = analyse_signals()

    if not alerts:
        print("Geen sterke setups gevonden (< 4 confluences of neutraal signaal)")
        return

    msg = build_message(alerts)
    if msg:
        send_telegram(msg)
        syms = [a["sym"] for a in alerts]
        print(f"Alert verstuurd voor: {', '.join(syms)}")
    else:
        print("Geen bericht verstuurd")


if __name__ == "__main__":
    main()
