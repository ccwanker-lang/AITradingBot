#!/usr/bin/env python3
"""
Auto-optimizer: detecteert het grootste probleem en stuurt een Telegram-aanbeveling.
Past NIETS automatisch aan — stuurt alleen een bericht met wat je zou moeten doen.
Veilige uitzonderingen: LSTM uitschakelen als val_acc < 33% (bijna random).
"""
import json
import os
import re
import time
import urllib.request
from datetime import datetime
from pathlib import Path

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


def get_env(key, default):
    try:
        return float(os.getenv(key, str(default)))
    except ValueError:
        return default


def analyse():
    problemen = []

    trades = load_json(LOGS / "trades.json", [])
    closed = [t for t in trades if t.get("type") in ("sell", "cover")]

    if len(closed) < 15:
        return []  # Te weinig data

    pnls = [t.get("pnl_pct", 0) for t in closed]
    wins = [p for p in pnls if p > 0]
    wr = len(wins) / len(pnls) if pnls else 0
    pf_w = sum(p for p in pnls if p > 0)
    pf_l = abs(sum(p for p in pnls if p < 0))
    pf = pf_w / pf_l if pf_l > 0 else 99

    # 1 — Verliesreeks
    recent_pnls = [t.get("pnl_pct", 0) for t in closed[-8:]]
    streak = 0
    for p in reversed(recent_pnls):
        if p < 0:
            streak += 1
        else:
            break
    if streak >= 6:
        problemen.append({
            "prioriteit": 1,
            "probleem": f"Verliesreeks van {streak} op rij",
            "aanbeveling": "Verlaag MIN_CONFIDENCE tijdelijk naar 0.40 — signalen zijn te zwak",
            "actie": f"MIN_CONFIDENCE verlagen naar 0.40 (nu: {os.getenv('MIN_CONFIDENCE','?')})"
        })

    # 2 — LSTM bijna random
    perf = load_json(LOGS / "performance.json", {})
    lstm_acc = perf.get("lstm_val_acc") if isinstance(perf, dict) else None
    lstm_weight = get_env("LSTM_WEIGHT", 0.0)
    if lstm_acc and lstm_acc < 0.335 and lstm_weight > 0:
        # Dit is veilig om automatisch te doen
        env_file = BASE / ".env"
        if env_file.exists():
            content = env_file.read_text()
            content = re.sub(r"LSTM_WEIGHT=[\d.]+", "LSTM_WEIGHT=0.00", content)
            env_file.write_text(content)
        problemen.append({
            "prioriteit": 1,
            "probleem": f"LSTM val_acc {lstm_acc:.1%} is bijna random (33.3%)",
            "aanbeveling": "LSTM_WEIGHT automatisch op 0.00 gezet — herstart bot",
            "actie": "✅ Al gedaan — LSTM_WEIGHT=0.00",
            "auto_applied": True
        })

    # 3 — TP1 reach rate laag
    # partial_tp1 records zijn aparte entries (type=="partial_tp1"), niet exit_reason in sell trades
    all_entries = load_json(LOGS / "trades.json", [])
    tp1_hits = len([t for t in all_entries if t.get("type") == "partial_tp1"])
    tp1_rate = tp1_hits / len(closed) if closed else 0
    if tp1_rate < 0.20 and len(closed) >= 20:
        problemen.append({
            "prioriteit": 2,
            "probleem": f"TP1 bereikt slechts {tp1_rate:.0%} van de trades",
            "aanbeveling": "Verlaag ATR_TP_MULT van 5.0 naar 4.0 — doelen zijn te ver",
            "actie": f"ATR_TP_MULT verlagen naar 4.0 (nu: {os.getenv('ATR_TP_MULT','?')})"
        })

    # 4 — Win rate te laag
    if wr < 0.38 and pf < 1.0 and len(closed) >= 20:
        problemen.append({
            "prioriteit": 2,
            "probleem": f"WR {wr:.0%} én PF {pf:.2f} beide slecht",
            "aanbeveling": "Verhoog MIN_CONFIDENCE naar 0.50 — filters zijn te los",
            "actie": f"MIN_CONFIDENCE verhogen naar 0.50 (nu: {os.getenv('MIN_CONFIDENCE','?')})"
        })

    # 5 — Drawdown hoog
    state = load_json(LOGS / "state.json", {})
    dd = state.get("portfolio", {}).get("drawdown", 0)
    if dd > 0.10:
        problemen.append({
            "prioriteit": 1,
            "probleem": f"Drawdown {dd:.1%} boven 10%",
            "aanbeveling": "Verklein KELLY_FRACTION naar 0.15 — posities te groot",
            "actie": f"KELLY_FRACTION verlagen naar 0.15"
        })

    problemen.sort(key=lambda x: x["prioriteit"])
    return problemen


def main():
    print(f"Auto-optimizer gestart: {datetime.now().strftime('%Y-%m-%d %H:%M')}")

    problemen = analyse()

    if not problemen:
        print("Geen problemen gedetecteerd")
        return

    top = problemen[0]
    auto = top.get("auto_applied", False)

    if auto:
        msg = (
            f"🔧 <b>Auto-optimizer — fix toegepast</b>\n\n"
            f"⚠️ <b>Probleem:</b> {top['probleem']}\n\n"
            f"✅ <b>Actie:</b> {top['actie']}\n\n"
            f"<i>Herstart de bot om de wijziging te activeren:\n"
            f"kill $(pgrep -f bot.py) && nohup venv/bin/python bot.py &gt; logs/bot_service.log 2&gt;&amp;1 &amp;</i>"
        )
    else:
        msg = (
            f"💡 <b>Auto-optimizer — aanbeveling</b>\n\n"
            f"⚠️ <b>Probleem:</b> {top['probleem']}\n\n"
            f"🔧 <b>Aanbeveling:</b> {top['aanbeveling']}\n\n"
            f"<b>Actie:</b> <code>{top['actie']}</code>\n\n"
            f"<i>Pas dit aan in .env en herstart de bot.</i>"
        )

    if len(problemen) > 1:
        msg += f"\n\n<i>+{len(problemen)-1} andere problemen — open Claude voor volledige analyse</i>"

    send_telegram(msg)
    print(f"Probleem gevonden: {top['probleem']}")


if __name__ == "__main__":
    main()
