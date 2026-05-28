"""
Filter Monitor — controleert actieve filters elke 15 minuten.
Stuurt Telegram alert ALLEEN als de situatie verandert (geen spam).
Standalone — past NIETS aan de bot aan.

Gebruik:
  python tools/filter_monitor.py          # loop (elke 15 min)
  python tools/filter_monitor.py --once   # eenmalige check + alert
  python tools/filter_monitor.py --test   # test-bericht zonder hash-check
"""
import hashlib
import json
import logging
import os
import sys
import time
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

try:
    from dotenv import load_dotenv
    load_dotenv(ROOT / ".env")
except ImportError:
    pass

import requests

# ── Logging ──────────────────────────────────────────────────────────────────
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(levelname)s | %(message)s",
    handlers=[
        logging.StreamHandler(),
        logging.FileHandler(ROOT / "logs" / "filter_monitor.log"),
    ],
)
log = logging.getLogger("filter_monitor")

# ── Configuratie ──────────────────────────────────────────────────────────────
TELEGRAM_TOKEN   = os.getenv("TELEGRAM_TOKEN", "")
TELEGRAM_CHAT_ID = os.getenv("TELEGRAM_CHAT_ID", "")
STATE_JSON       = ROOT / "logs" / "state.json"
ALERT_STATE_FILE = ROOT / "logs" / "filter_monitor_state.json"
INTERVAL_MINUTES = 15


# ── Telegram ──────────────────────────────────────────────────────────────────
def send_telegram(msg: str) -> bool:
    if not TELEGRAM_TOKEN or not TELEGRAM_CHAT_ID:
        log.warning("Telegram niet geconfigureerd — sla versturen over")
        return False
    try:
        resp = requests.post(
            f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage",
            json={"chat_id": TELEGRAM_CHAT_ID, "text": msg, "parse_mode": "HTML"},
            timeout=10,
        )
        if resp.status_code == 200:
            return True
        log.error(f"Telegram HTTP {resp.status_code}: {resp.text[:200]}")
        return False
    except Exception as exc:
        log.error(f"Telegram fout: {exc}")
        return False


# ── State lezen / opslaan ────────────────────────────────────────────────────
def load_bot_state() -> dict:
    try:
        with open(STATE_JSON) as f:
            return json.load(f)
    except Exception as exc:
        log.error(f"Kan {STATE_JSON} niet lezen: {exc}")
        return {}


def load_alert_state() -> dict:
    try:
        with open(ALERT_STATE_FILE) as f:
            return json.load(f)
    except Exception:
        return {}


def save_alert_state(data: dict):
    with open(ALERT_STATE_FILE, "w") as f:
        json.dump(data, f, indent=2)


def reasons_fingerprint(no_trade: dict, positions: dict) -> str:
    combined = {"blocked": no_trade, "open": list(sorted(positions.keys()))}
    return hashlib.md5(json.dumps(combined, sort_keys=True).encode()).hexdigest()


# ── Bericht bouwen ────────────────────────────────────────────────────────────
def build_alert(state: dict) -> str:
    now        = datetime.now().strftime("%d %b %H:%M")
    no_trade   = state.get("no_trade_reasons", {})
    regimes    = state.get("regimes", {})
    portfolio  = state.get("portfolio", {})
    positions  = state.get("positions", {})
    summary    = state.get("summary", {})
    meta       = state.get("meta", {})

    blocked  = {s: r for s, r in no_trade.items() if r}
    open_pos = list(positions.keys())
    free_sym = [s for s in regimes if s not in blocked and s not in open_pos]

    lines = [f"<b>🔍 Filter Monitor — {now}</b>\n"]

    # ── Geblokkeerde symbolen ──────────────────────────────────────────────
    if blocked:
        lines.append("<b>⛔ Geblokkeerd:</b>")
        for sym, reason in blocked.items():
            rinfo    = regimes.get(sym, {})
            regime   = rinfo.get("regime", "?")
            strength = rinfo.get("strength", 0)
            lines.append(
                f"  • <b>{sym}</b>  [{regime} {strength:.0%}]\n"
                f"    ↳ {reason}"
            )
        lines.append("")

    # ── Open posities ─────────────────────────────────────────────────────
    if open_pos:
        lines.append("<b>✅ Open posities:</b>")
        for sym in open_pos:
            pos     = positions[sym]
            dir_str = "LONG" if pos.get("direction", 1) == 1 else "SHORT"
            entry   = pos.get("entry_price", 0)
            sl      = pos.get("stop_loss", 0)
            lines.append(f"  • <b>{sym}</b>  {dir_str} @ {entry:,.2f}  SL={sl:,.2f}")
        lines.append("")

    # ── Wacht op signaal ──────────────────────────────────────────────────
    if free_sym:
        lines.append(f"<b>💤 Wacht op signaal:</b>  {', '.join(free_sym)}\n")

    # ── Samenvatting ──────────────────────────────────────────────────────
    total   = portfolio.get("total_value", 0)
    pnl_pct = portfolio.get("pnl_pct", 0) * 100
    dd      = portfolio.get("drawdown", 0) * 100
    wr      = summary.get("win_rate", 0) * 100
    wr_tp1  = summary.get("win_rate_with_partials", 0) * 100
    streak  = meta.get("streak", 0)
    throttle = meta.get("throttle", 1.0) * 100

    streak_str = f"  🔴 Verliesstreak: {abs(streak)}" if streak < -1 else ""
    throttle_str = f"  ⚡ Throttle: {throttle:.0f}%" if throttle < 90 else ""

    lines.append(
        f"<i>💰 ${total:,.2f} ({pnl_pct:+.2f}%)  DD: {dd:.1f}%  "
        f"WR: {wr:.0f}% ({wr_tp1:.0f}%+TP1)</i>"
    )
    if streak_str:
        lines.append(f"<i>{streak_str}</i>")
    if throttle_str:
        lines.append(f"<i>{throttle_str}</i>")

    return "\n".join(lines)


# ── Hoofd-logica ──────────────────────────────────────────────────────────────
def run_once(force: bool = False) -> bool:
    state = load_bot_state()
    if not state:
        log.warning("State leeg — bot waarschijnlijk nog niet gestart")
        return False

    no_trade  = state.get("no_trade_reasons", {})
    positions = state.get("positions", {})
    fp        = reasons_fingerprint(no_trade, positions)

    prev      = load_alert_state()
    last_fp   = prev.get("last_fingerprint", "")

    if fp == last_fp and not force:
        log.info(f"Geen verandering (fingerprint={fp[:8]}) — geen Telegram verstuurd")
        return False

    msg = build_alert(state)
    ok  = send_telegram(msg)

    if ok:
        save_alert_state({
            "last_fingerprint": fp,
            "last_sent":        datetime.now().isoformat(),
            "last_blocked":     list(no_trade.keys()),
        })
        log.info("Telegram alert verstuurd")
    return ok


def run_loop():
    log.info(f"Filter Monitor gestart — interval {INTERVAL_MINUTES} min")
    while True:
        try:
            run_once()
        except Exception as exc:
            log.exception(f"Onverwachte fout: {exc}")
        time.sleep(INTERVAL_MINUTES * 60)


# ── Entry point ───────────────────────────────────────────────────────────────
if __name__ == "__main__":
    args = sys.argv[1:]
    if "--test" in args:
        log.info("Test-modus: stuur bericht ongeacht hash")
        run_once(force=True)
    elif "--once" in args:
        run_once()
    else:
        run_loop()
