#!/usr/bin/env python3
"""
Self-Healing Agent — Telegram-gestuurde Proposal Engine.

Draait 2x/dag via cron (07:00 en 19:00). Detecteert win rate killers,
stelt één fix voor via Telegram, en bewaakt rollback na goedkeuring.
Past NOOIT automatisch iets aan zonder /approve_heal goedkeuring.

Cron:
  0 7,19 * * * /home/pi/crypto_bot/venv/bin/python /home/pi/crypto_bot/tools/self_healer.py >> /home/pi/crypto_bot/logs/self_healer.log 2>&1
"""
import json
import os
import sys
import urllib.request
from collections import defaultdict
from datetime import datetime, timedelta
from pathlib import Path

BASE = Path(__file__).parent.parent
LOGS = BASE / "logs"
sys.path.insert(0, str(BASE))

try:
    from dotenv import load_dotenv
    load_dotenv(BASE / ".env")
except ImportError:
    pass

TOKEN   = os.getenv("TELEGRAM_TOKEN", "")
CHAT_ID = os.getenv("TELEGRAM_CHAT_ID", "")

# ── Bestanden ──────────────────────────────────────────────────────────────
PROPOSAL_FILE  = LOGS / "heal_proposal.json"
HEAL_CFG_FILE  = LOGS / "heal_config.json"
TRADES_FILE    = LOGS / "trades.json"
STATE_FILE     = LOGS / "state.json"

# ══════════════════════════════════════════════════════════════════════════
# PARAMETER BOUNDS — nooit overschreden door de healer
# ══════════════════════════════════════════════════════════════════════════
BOUNDS: dict = {
    "confluence_ranging": {
        "label":    "Confluence drempel (ranging)",
        "min": 2,   "max": 4,   "step": 1,
        "default":  3,          # hardcoded in bot.py na fix 2026-05-21
        "regime":   "ranging",
        "unit":     " strategen",
        "fix_dir":  +1,         # verhogen = betere WR (minder, betere trades)
    },
    "ranging_tp2_mult": {
        "label":    "TP2 multiplier (ranging)",
        "min": 1.5, "max": 2.5, "step": 0.25,
        "default":  2.0,        # hardcoded in bot.py na fix 2026-05-21
        "regime":   "ranging",
        "unit":     "x ATR",
        "fix_dir":  -1,         # verlagen = targets dichter bij = hogere TP1-rate
    },
    "min_confidence": {
        "label":    "MIN_CONFIDENCE",
        "min": 0.35,"max": 0.58,"step": 0.02,
        "default":  None,       # gelezen uit .env
        "regime":   None,       # geldt voor alle regimes
        "unit":     "",
        "fix_dir":  +1,
    },
}

MIN_N          = 10     # Minimaal n trades per regime voor statistische geldigheid (was 20 — verlaagd 2026-05-25 voor snellere feedbackloop, 3-4 dagen i.p.v. 7)
WR_KILL        = 0.38   # Onder 38% WR = win rate killer
TP1_KILL       = 0.25   # Onder 25% TP1-rate = targets te ver
GLOBAL_WR_KILL = 0.40   # Globale WR-drempel voor MIN_CONFIDENCE fix
GLOBAL_N_MIN   = 30     # Minimaal n closed voor globale fix
COOLDOWN_HOURS = 72     # Min uren tussen twee goedgekeurde changes
PROPOSAL_TTL_H = 12     # Voorstel vervalt na 12 uur (volgende run)
ROLLBACK_PP    = 0.05   # WR moet ≥5pp dalen voor automatische rollback


# ── Hulpfuncties ──────────────────────────────────────────────────────────

def load_json(path, default):
    try:
        return json.loads(Path(path).read_text())
    except Exception:
        return default


def save_json(path, data):
    Path(path).write_text(json.dumps(data, indent=2, default=str))


def send_telegram(msg: str):
    if not TOKEN or not CHAT_ID:
        print("Telegram niet geconfigureerd — bericht overgeslagen")
        return
    url  = f"https://api.telegram.org/bot{TOKEN}/sendMessage"
    body = json.dumps({"chat_id": CHAT_ID, "text": msg, "parse_mode": "HTML"}).encode()
    req  = urllib.request.Request(url, body, {"Content-Type": "application/json"})
    try:
        urllib.request.urlopen(req, timeout=10)
    except Exception as e:
        print(f"Telegram fout: {e}")


def get_current_values(heal_config: dict) -> dict:
    """Leest actieve parameterwaarden: heal_config override heeft prioriteit."""
    vals = {}
    for param, cfg in BOUNDS.items():
        if param in heal_config:
            vals[param] = heal_config[param]
        elif cfg["default"] is not None:
            vals[param] = cfg["default"]
        else:
            # Lees uit .env
            env_key = param.upper()
            try:
                vals[param] = float(os.getenv(env_key, "0.46"))
            except ValueError:
                vals[param] = cfg["min"]
    return vals


# ── Rollback controle ─────────────────────────────────────────────────────

def check_rollback(trades: list, heal_config: dict) -> list[dict]:
    """
    Controleer voor elke applied parameter of rollback nodig is.
    Criteria: ≥20 regime-trades NA de wijziging EN WR daalde ≥5pp.
    Retourneert lijst van rollback-acties.
    """
    meta     = heal_config.get("_meta", {})
    rollbacks = []

    for param, info in meta.items():
        if param not in BOUNDS:
            continue
        try:
            applied_at  = datetime.fromisoformat(info["applied_at"])
            regime      = info.get("regime")
            wr_before   = float(info["wr_at_application"])
            prev_value  = info["previous_value"]
        except (KeyError, ValueError):
            continue

        # Trades NA de wijziging in het betrokken regime
        def is_after(t):
            try:
                return datetime.fromisoformat(t["timestamp"]) > applied_at
            except Exception:
                return False

        if regime:
            after = [t for t in trades
                     if t.get("type") in ("sell", "cover")
                     and "pnl_pct" in t
                     and t.get("regime") == regime
                     and is_after(t)]
        else:
            after = [t for t in trades
                     if t.get("type") in ("sell", "cover")
                     and "pnl_pct" in t
                     and is_after(t)]

        if len(after) < MIN_N:
            print(f"  Rollback check {param}: slechts {len(after)}/{MIN_N} trades na wijziging — te vroeg")
            continue

        wins_after = sum(1 for t in after if t.get("pnl_pct", 0) > 0)
        wr_after   = wins_after / len(after)

        print(f"  Rollback check {param}: WR voor={wr_before:.1%}, na={wr_after:.1%} ({len(after)} trades)")

        if wr_after < wr_before - ROLLBACK_PP:
            rollbacks.append({
                "param":          param,
                "current_value":  heal_config.get(param),
                "restore_value":  prev_value,
                "wr_before":      wr_before,
                "wr_after":       wr_after,
                "n_trades":       len(after),
                "regime":         regime,
            })

    return rollbacks


def apply_rollbacks(rollbacks: list, heal_config: dict) -> dict:
    """Pas rollbacks toe in heal_config en retourneer bijgewerkte config."""
    for rb in rollbacks:
        param = rb["param"]
        heal_config[param] = rb["restore_value"]
        # Verwijder meta zodat rollback niet opnieuw triggert
        heal_config.get("_meta", {}).pop(param, None)
        print(f"  Rollback toegepast: {param} = {rb['current_value']} → {rb['restore_value']}")
    return heal_config


# ── Cooldown controle ─────────────────────────────────────────────────────

def check_cooldown(heal_config: dict) -> bool:
    """True als er nog een actieve cooldown is (te vroeg voor nieuw voorstel)."""
    meta = heal_config.get("_meta", {})
    for info in meta.values():
        try:
            applied_at = datetime.fromisoformat(info["applied_at"])
            if datetime.now() - applied_at < timedelta(hours=COOLDOWN_HOURS):
                remaining = timedelta(hours=COOLDOWN_HOURS) - (datetime.now() - applied_at)
                hours_left = int(remaining.total_seconds() / 3600)
                print(f"  Cooldown actief: {hours_left}u resterend na laatste wijziging")
                return True
        except (KeyError, ValueError):
            continue
    return False


# ── Probleemdetectie ──────────────────────────────────────────────────────

def detect_problems(trades: list, current_vals: dict) -> list[dict]:
    """
    Detecteer win rate killers in volgorde van prioriteit.
    Retourneert gesorteerde lijst, hoogste prioriteit eerst.
    """
    closed = [t for t in trades if t.get("type") in ("sell", "cover") and "pnl_pct" in t]
    problems = []

    # ── Prioriteit 1: Ranging WR < 38% ────────────────────────────────
    ranging_closed = [t for t in closed if t.get("regime") == "ranging"]
    if len(ranging_closed) >= MIN_N:
        recent = ranging_closed[-MIN_N:]
        wins   = sum(1 for t in recent if t.get("pnl_pct", 0) > 0)
        wr     = wins / len(recent)

        if wr < WR_KILL:
            # TP1-rate meten voor ranging (partials tellen mee)
            ranging_all = [t for t in trades
                           if t.get("regime") == "ranging"
                           and t.get("type") in ("sell", "cover", "partial_tp1")]
            tp1_count = sum(1 for t in ranging_all if t.get("type") == "partial_tp1")
            exit_count = sum(1 for t in ranging_all if t.get("type") in ("sell", "cover"))
            tp1_rate = tp1_count / (exit_count + tp1_count + 1e-9)

            # Kies welke fix: confluence of TP2
            conf_val = current_vals.get("confluence_ranging", 3)
            tp2_val  = current_vals.get("ranging_tp2_mult", 2.0)
            conf_b   = BOUNDS["confluence_ranging"]
            tp2_b    = BOUNDS["ranging_tp2_mult"]

            # Als TP1-rate ook laag: fix TP2 eerst (targets te ver)
            if tp1_rate < TP1_KILL and tp2_val > tp2_b["min"]:
                new_tp2 = round(tp2_val - tp2_b["step"], 2)
                problems.append({
                    "priority":      1,
                    "param":         "ranging_tp2_mult",
                    "regime":        "ranging",
                    "current_value": tp2_val,
                    "proposed_value": new_tp2,
                    "wr":            wr,
                    "n_trades":      len(recent),
                    "tp1_rate":      tp1_rate,
                    "reason": (
                        f"Ranging WR {wr:.0%} (n={len(recent)}) + "
                        f"TP1-rate {tp1_rate:.0%} — targets te ver van entry"
                    ),
                })
            elif conf_val < conf_b["max"]:
                new_conf = int(conf_val + conf_b["step"])
                problems.append({
                    "priority":      1,
                    "param":         "confluence_ranging",
                    "regime":        "ranging",
                    "current_value": conf_val,
                    "proposed_value": new_conf,
                    "wr":            wr,
                    "n_trades":      len(recent),
                    "tp1_rate":      tp1_rate,
                    "reason": (
                        f"Ranging WR {wr:.0%} (n={len(recent)}) — "
                        f"te veel entries op slechte setups"
                    ),
                })

    # ── Prioriteit 2: Globale WR < 40% ────────────────────────────────
    if len(closed) >= GLOBAL_N_MIN:
        recent_global = closed[-GLOBAL_N_MIN:]
        wins_g = sum(1 for t in recent_global if t.get("pnl_pct", 0) > 0)
        wr_g   = wins_g / len(recent_global)

        if wr_g < GLOBAL_WR_KILL:
            mc_val = current_vals.get("min_confidence", 0.46)
            mc_b   = BOUNDS["min_confidence"]
            if mc_val < mc_b["max"]:
                new_mc = round(mc_val + mc_b["step"], 2)
                problems.append({
                    "priority":       2,
                    "param":          "min_confidence",
                    "regime":         None,
                    "current_value":  mc_val,
                    "proposed_value": new_mc,
                    "wr":             wr_g,
                    "n_trades":       len(recent_global),
                    "tp1_rate":       None,
                    "reason": (
                        f"Globale WR {wr_g:.0%} (n={len(recent_global)}) — "
                        f"signaaldrempel te laag"
                    ),
                })

    problems.sort(key=lambda x: x["priority"])
    return problems


# ── Proposal schrijven + sturen ───────────────────────────────────────────

def write_proposal(proposal: dict):
    proposal["timestamp"]  = datetime.now().isoformat()
    proposal["expires_at"] = (datetime.now() + timedelta(hours=PROPOSAL_TTL_H)).isoformat()
    proposal["status"]     = "pending"
    save_json(PROPOSAL_FILE, proposal)
    print(f"  Proposal geschreven: {PROPOSAL_FILE}")


def send_proposal_telegram(proposal: dict):
    from datetime import date
    b    = BOUNDS[proposal["param"]]
    reg  = f" ({proposal['regime']})" if proposal["regime"] else ""
    tp1s = f"\n  TP1-rate: <b>{proposal['tp1_rate']:.0%}</b>" if proposal.get("tp1_rate") is not None else ""

    # Activatiepoort status bepalen
    ACTIVATION_DATE   = date(2026, 5, 27)
    ACTIVATION_TRADES = 62
    today             = date.today()

    trades_raw = load_json(TRADES_FILE, [])
    closed_count = len([t for t in trades_raw
                        if t.get("type") in ("sell", "cover") and "pnl_pct" in t])
    date_ok   = today >= ACTIVATION_DATE
    trades_ok = closed_count >= ACTIVATION_TRADES

    if date_ok and trades_ok:
        lock_line = "🔓 <b>Poort open</b> — /approve_heal is actief\n\n"
        approve_line = f"✅ <code>/approve_heal</code> — toepassen\n"
    else:
        days_left = max(0, (ACTIVATION_DATE - today).days)
        lock_line = (
            f"🔒 <b>Geblokkeerd tot 27 mei + {ACTIVATION_TRADES} trades</b>\n"
            f"  Datum: {'✅' if date_ok else f'⏳ nog {days_left} dag(en)'}\n"
            f"  Trades: {'✅' if trades_ok else f'⏳ {closed_count}/{ACTIVATION_TRADES}'}\n\n"
        )
        approve_line = f"⏳ <code>/approve_heal</code> — actief na 27 mei + {ACTIVATION_TRADES} trades\n"

    msg = (
        f"⚕️ <b>Self-Healer — Win Rate Killer Gedetecteerd</b>\n\n"
        f"📊 Analyse:\n"
        f"  Regime: <b>{proposal['regime'] or 'globaal'}</b>\n"
        f"  Win Rate: <b>{proposal['wr']:.0%}</b> (n={proposal['n_trades']} trades){tp1s}\n"
        f"  Probleem: {proposal['reason']}\n\n"
        f"🔧 Voorgestelde fix:\n"
        f"  Parameter: <b>{b['label']}{reg}</b>\n"
        f"  Huidig: <b>{proposal['current_value']}{b['unit']}</b>\n"
        f"  Voorstel: <b>{proposal['proposed_value']}{b['unit']}</b>\n"
        f"  Grenzen: [{b['min']}{b['unit']} — {b['max']}{b['unit']}]\n\n"
        f"{lock_line}"
        f"⏱ Timeout: {PROPOSAL_TTL_H}u (volgende run overschrijft)\n\n"
        f"{approve_line}"
        f"❌ <code>/reject_heal</code>  — overslaan\n"
        f"ℹ️ <code>/heal_status</code>  — huidige overrides bekijken"
    )
    send_telegram(msg)


def send_rollback_telegram(rollbacks: list):
    for rb in rollbacks:
        b = BOUNDS.get(rb["param"], {})
        msg = (
            f"🔄 <b>Self-Healer — Automatische Rollback</b>\n\n"
            f"⚠️ Wijziging heeft WR verslechterd:\n"
            f"  Parameter: <b>{b.get('label', rb['param'])}</b>\n"
            f"  Teruggedraaid: {rb['current_value']} → <b>{rb['restore_value']}</b>\n\n"
            f"📊 Bewijs ({rb['n_trades']} trades na wijziging):\n"
            f"  WR voor wijziging: {rb['wr_before']:.0%}\n"
            f"  WR na wijziging:   {rb['wr_after']:.0%} (−{rb['wr_before']-rb['wr_after']:.0%})\n\n"
            f"Bot draait nu weer op vorige instelling. Geen actie vereist."
        )
        send_telegram(msg)


# ── Main ──────────────────────────────────────────────────────────────────

def main():
    print(f"\n{'='*60}")
    print(f"Self-Healer run: {datetime.now().strftime('%Y-%m-%d %H:%M')}")
    print(f"{'='*60}")

    # ── Data laden ────────────────────────────────────────────────
    trades     = load_json(TRADES_FILE, [])
    heal_cfg   = load_json(HEAL_CFG_FILE, {})
    cur_vals   = get_current_values(heal_cfg)

    closed = [t for t in trades if t.get("type") in ("sell", "cover") and "pnl_pct" in t]
    print(f"  Gesloten trades: {len(closed)}")
    print(f"  Actieve heal overrides: {[k for k in heal_cfg if not k.startswith('_')]}")

    # ── 1. Rollback controle (altijd eerst) ───────────────────────
    if heal_cfg.get("_meta"):
        print("\n[1/4] Rollback controle...")
        rollbacks = check_rollback(trades, heal_cfg)
        if rollbacks:
            print(f"  {len(rollbacks)} rollback(s) noodzakelijk!")
            heal_cfg = apply_rollbacks(rollbacks, heal_cfg)
            save_json(HEAL_CFG_FILE, heal_cfg)
            send_rollback_telegram(rollbacks)
            # Na rollback: geen nieuw voorstel deze run
            print("  Rollback toegepast — geen nieuw voorstel deze run.")
            return
        else:
            print("  Geen rollback nodig.")
    else:
        print("\n[1/4] Geen actieve wijzigingen om te bewaken.")

    # ── 2. Cooldown controle ──────────────────────────────────────
    print("\n[2/4] Cooldown controle...")
    if check_cooldown(heal_cfg):
        print("  Cooldown actief — run beëindigd.")
        return

    # ── 3. Pending proposal check (voorkom dubbele voorstellen) ───
    print("\n[3/4] Pending proposal check...")
    existing = load_json(PROPOSAL_FILE, {})
    if existing.get("status") == "pending":
        try:
            expires = datetime.fromisoformat(existing["expires_at"])
            if datetime.now() < expires:
                remaining = int((expires - datetime.now()).total_seconds() / 3600)
                print(f"  Bestaand voorstel nog actief ({remaining}u resterend) — geen nieuw voorstel.")
                return
        except (KeyError, ValueError):
            pass
    print("  Geen lopend voorstel.")

    # ── 4. Probleemdetectie ───────────────────────────────────────
    print("\n[4/4] Probleemdetectie...")
    problems = detect_problems(trades, cur_vals)

    if not problems:
        print("  Geen win rate killers gevonden (alles binnen grenzen).")
        send_telegram(
            f"✅ <b>Self-Healer</b> — {datetime.now().strftime('%d/%m %H:%M')}\n"
            f"Geen win rate killers gedetecteerd. Bot presteert binnen grenzen."
        )
        return

    # Neem het hoogste prioriteitsprobleem
    top = problems[0]
    print(f"  Win rate killer gevonden: {top['param']} | {top['reason']}")

    write_proposal(top)
    send_proposal_telegram(top)
    print(f"  Voorstel verstuurd via Telegram.")


if __name__ == "__main__":
    main()
