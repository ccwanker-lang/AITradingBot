#!/usr/bin/env python3
"""Auto-trainer: hertraint LSTM/RL als kwaliteit te laag is."""
import json
import os
import subprocess
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
MIN_TRADES_FOR_RETRAIN = 30
LSTM_ACC_THRESHOLD = 0.38
RL_MAX_AGE_HOURS = 96


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


def get_closed_trade_count():
    trades = load_json(LOGS / "trades.json", [])
    return len([t for t in trades if t.get("type") in ("sell", "cover")])


def get_lstm_val_acc():
    perf = load_json(LOGS / "performance.json", {})
    if isinstance(perf, dict):
        return perf.get("lstm_val_acc")
    return None


def get_rl_model_age_hours():
    model = BASE / "models" / "crypto_ppo.zip"
    if not model.exists():
        return 999
    age = time.time() - model.stat().st_mtime
    return age / 3600


def retrain_needed():
    reasons = []

    closed = get_closed_trade_count()
    if closed < MIN_TRADES_FOR_RETRAIN:
        print(f"Te weinig trades ({closed}/{MIN_TRADES_FOR_RETRAIN}) — geen hertraining")
        return False, []

    lstm_acc = get_lstm_val_acc()
    if lstm_acc and lstm_acc < LSTM_ACC_THRESHOLD:
        reasons.append(f"LSTM val_acc {lstm_acc:.1%} < {LSTM_ACC_THRESHOLD:.0%}")

    rl_age = get_rl_model_age_hours()
    if rl_age > RL_MAX_AGE_HOURS:
        reasons.append(f"RL model {rl_age:.0f}u oud (max {RL_MAX_AGE_HOURS}u)")

    return len(reasons) > 0, reasons


def run_training():
    log_file = LOGS / f"training_{datetime.now().strftime('%Y%m%d_%H%M')}.log"
    print(f"Training starten, log: {log_file}")

    result = subprocess.run(
        [str(BASE / "venv/bin/python"), str(BASE / "bot.py"), "--train"],
        capture_output=True,
        text=True,
        cwd=str(BASE),
        timeout=1800,  # 30 minuten max
    )

    log_file.write_text(result.stdout + "\n" + result.stderr)

    if result.returncode == 0:
        # Nieuwe val_acc uitlezen
        new_acc = get_lstm_val_acc()
        return True, new_acc
    else:
        return False, None


def main():
    print(f"Auto-trainer gestart: {datetime.now().strftime('%Y-%m-%d %H:%M')}")

    needed, reasons = retrain_needed()

    if not needed:
        print("Hertraining niet nodig")
        return

    print(f"Hertraining nodig: {', '.join(reasons)}")
    send_telegram(
        f"🤖 <b>Auto-trainer gestart</b>\n\n"
        f"Redenen:\n" + "\n".join(f"• {r}" for r in reasons) +
        f"\n\n⏳ Duurt ~20 minuten..."
    )

    success, new_acc = run_training()

    if success:
        msg = f"✅ <b>Training voltooid</b>\n\n"
        if new_acc:
            msg += f"LSTM val_acc: {new_acc:.1%}\n"
        msg += f"RL model: bijgewerkt\n"
        msg += f"Bot herstart aanbevolen: herstart bot om nieuwe modellen te laden"
        send_telegram(msg)
        print(f"Training succesvol. Nieuwe LSTM acc: {new_acc}")
    else:
        send_telegram("❌ <b>Training mislukt</b>\n\nCheck logs/training_*.log voor details")
        print("Training mislukt")


if __name__ == "__main__":
    main()
