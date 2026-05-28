"""
Vault Diagnostics Agent — The Overseer's Eye
=============================================
Draait autonoom elke cycle en schrijft per symbool een diagnose naar
logs/vault_diagnostics.json. Het dashboard leest dit bestand live.

Status-waarden:
  ok           → alles groen, bot kan handelen
  position     → positie open, bot beheert hem
  warning      → iets vereist aandacht (confidence/volume te laag)
  blocked      → hard geblokkeerd (circuit breaker / geen kapitaal / cooldown)
  stale        → data ouder dan 120 seconden → bot reageert niet
  rsi_zone     → RSI zone filter (Filter 1d) beschermde bot tegen te late entry

Gebruik:
  Als standalone script:  python tools/vault_diagnostics.py
  Als importeerbaar:      from tools.vault_diagnostics import run_diagnostics
"""
from __future__ import annotations

import json
import os
import time
from datetime import datetime
from pathlib import Path

# ── Pad configuratie ────────────────────────────────────────────────────────
_BASE          = Path(__file__).parent.parent
_LOG_DIR       = _BASE / "logs"
_STATE_FILE    = _LOG_DIR / "state.json"
_BOT_STATE     = _LOG_DIR / "bot_state.json"
_HEAL_FILE     = _LOG_DIR / "heal_proposal.json"
_TRADES_FILE   = _LOG_DIR / "trades.json"
_ENV_FILE      = _BASE / ".env"
_OUT_FILE      = _LOG_DIR / "vault_diagnostics.json"

# ── Constanten ──────────────────────────────────────────────────────────────
MIN_FREE_CAPITAL   = 15.0
STALE_THRESHOLD_S  = 120
SL_COOLDOWN_S      = 14400
MAX_RSI_LOG        = 500   # Maximale entries in RSI zone block log

# Filter 1d activatietijdstip (2026-05-27 18:27 UTC ≈ lokale tijd)
FILTER_1D_ACTIVE_SINCE = "2026-05-27T18:27:00"

# ── Trefwoorden per blokkade-categorie ─────────────────────────────────────
_BLOCK_KEYWORDS = {
    "rsi_zone":    ["rsi-zone", "ranging rsi-zone", "bovenkant range", "onderkant range"],
    "confluence":  ["confluence", "technische strategie", "agreeing"],
    "sl_cooldown": ["sl cooldown", "cooldown", "wachten"],
    "volume":      ["volume te laag", "volume"],
    "rsi":         ["rsi oversold", "rsi overbought", "rsi"],
    "regime":      ["geblokkeerd", "bull_trend", "bear_trend", "ranging correlatie"],
    "edge":        ["edge", "negatieve edge", "grade c"],
    "noise":       ["noisy", "noise", "bb squeeze"],
    "stat_arb":    ["statarb veto", "divergentie"],
    "bos":         ["bos veto", "marketstructure blokkeert"],
    "local_ext":   ["lokaal hoogtepunt", "lokaal dieptepunt"],
    "correlation": ["correlatie-limiet", "correlatie-lock"],
    "low_score":   ["score", "drempel", "vs drempel", "threshold"],
    "macro":       ["1d én 4h", "macro", "4h trend", "4h bullish", "4h bearish"],
    "ranging":     ["ranging skip", "geen edge in ranging"],
}

_BADGE_MAP = {
    "rsi_zone":    ("🛡️",  "RSI Zone Filter"),
    "confluence":  ("⚠️",  "Confluence te laag"),
    "sl_cooldown": ("⏳",  "SL Cooldown actief"),
    "volume":      ("📊",  "Volume te laag"),
    "rsi":         ("📉",  "RSI extremen"),
    "regime":      ("🚦",  "Regime blokkeert"),
    "edge":        ("🎯",  "Negatieve edge"),
    "noise":       ("📡",  "Markt te noisy"),
    "stat_arb":    ("⚖️",  "StatArb veto"),
    "bos":         ("🏗️",  "BOS blokkeert"),
    "local_ext":   ("📍",  "Lokaal extremum"),
    "correlation": ("🔗",  "Correlatie-lock"),
    "low_score":   ("📊",  "Signaal te zwak"),
    "macro":       ("🌐",  "Macro filter"),
    "ranging":     ("⏸️",  "Ranging skip"),
    "unknown":     ("❓",  "Wachten op signaal"),
}


def _read_json(path: Path, default=None):
    if default is None:
        default = {}
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return default


def _read_env_value(key: str, default: str = "") -> str:
    try:
        for line in _ENV_FILE.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if line.startswith(f"{key}="):
                return line.split("=", 1)[1].strip().strip('"').strip("'")
    except Exception:
        pass
    return default


def _classify_no_trade_reason(reason: str) -> str:
    if not reason:
        return "unknown"
    low = reason.lower()
    # rsi_zone heeft prioriteit boven generieke rsi-check
    for cat in ["rsi_zone", "confluence", "sl_cooldown", "volume", "rsi",
                "regime", "edge", "noise", "stat_arb", "bos", "local_ext",
                "correlation", "low_score", "macro", "ranging"]:
        keywords = _BLOCK_KEYWORDS.get(cat, [])
        if any(kw in low for kw in keywords):
            return cat
    return "unknown"


def _state_age_seconds(state: dict) -> float:
    lu = state.get("last_update", "")
    if not lu:
        return 999.0
    try:
        ts = datetime.fromisoformat(lu).timestamp()
        return time.time() - ts
    except Exception:
        return 999.0


# ── RSI Zone Block Log (persistent) ────────────────────────────────────────

def _load_rsi_zone_log() -> list:
    """Laad de bestaande RSI zone block log uit vault_diagnostics.json."""
    existing = _read_json(_OUT_FILE, {})
    log = existing.get("_rsi_zone_log", {}).get("events", [])
    if isinstance(log, list):
        return log
    return []


def _append_rsi_zone_blocks(
    rsi_log: list,
    symbol: str,
    reason: str,
    now: float,
) -> list:
    """Voeg een nieuwe RSI zone block toe aan de log (geen duplicaten binnen 5min)."""
    # Voorkom duplicaten: als hetzelfde symbool in de laatste 5 min al gelogd is, skip
    recent_syms = {
        e["symbol"] for e in rsi_log
        if now - e.get("ts", 0) < 300
    }
    if symbol in recent_syms:
        return rsi_log

    entry = {
        "symbol":    symbol,
        "ts":        now,
        "ts_str":    datetime.fromtimestamp(now).strftime("%Y-%m-%d %H:%M"),
        "reason":    reason,
    }
    rsi_log.append(entry)
    # Houd maximum MAX_RSI_LOG entries bij
    return rsi_log[-MAX_RSI_LOG:]


def _build_rsi_zone_summary(rsi_log: list, now: float) -> dict:
    """Bereken statistieken over de RSI zone block log."""
    total  = len(rsi_log)
    last1h = sum(1 for e in rsi_log if now - e.get("ts", 0) < 3600)
    last24h = sum(1 for e in rsi_log if now - e.get("ts", 0) < 86400)

    # Per symbool
    by_sym = {}
    for e in rsi_log:
        sym = e.get("symbol", "?")
        by_sym[sym] = by_sym.get(sym, 0) + 1

    return {
        "total":        total,
        "last_1h":      last1h,
        "last_24h":     last24h,
        "by_symbol":    by_sym,
        "events":       rsi_log,   # Volledige log
        "description":  (
            f"Filter 1d beschermde bot {total}× tegen te late entry in ranging "
            f"({last24h} in laatste 24u, {last1h} in laatste uur)"
        ),
    }


# ── Filter 1d Effectiviteits-tracker ───────────────────────────────────────

def _calc_filter1d_stats() -> dict:
    """
    Meet de effectiviteit van Filter 1d (RSI zone filter in ranging).

    Vergelijkt:
    - Ranging trades NA activatie (2026-05-27T18:27) → WR van filtered entries
    - Baseline ranging WR vóór Filter 1d: 29% (n=45)
    """
    try:
        activation_ts = datetime.fromisoformat(FILTER_1D_ACTIVE_SINCE).timestamp()
        trades = _read_json(_TRADES_FILE, [])

        # Filter: exit trades (sell/cover) in ranging NA activatie
        ranging_exits_after = []
        for t in trades:
            if t.get("type") not in ("sell", "cover"):
                continue
            if t.get("regime", "") != "ranging":
                continue
            ts_str = t.get("timestamp", "")
            if not ts_str:
                continue
            try:
                ts = datetime.fromisoformat(ts_str[:19]).timestamp()
            except Exception:
                continue
            if ts >= activation_ts:
                ranging_exits_after.append(t)

        n = len(ranging_exits_after)
        if n == 0:
            return {
                "active_since":  FILTER_1D_ACTIVE_SINCE,
                "n_trades":      0,
                "n_wins":        0,
                "wr":            None,
                "avg_pnl":       None,
                "baseline_wr":   0.29,
                "baseline_n":    45,
                "status":        "Nog geen ranging trades na activatie",
                "improvement":   None,
            }

        wins    = [t for t in ranging_exits_after if t.get("pnl_pct", 0) > 0]
        pnls    = [t.get("pnl_pct", 0) for t in ranging_exits_after]
        wr      = len(wins) / n
        avg_pnl = sum(pnls) / n

        improvement = wr - 0.29  # Vs baseline 29%
        target_met  = wr >= 0.40  # Target: ≥40% WR

        return {
            "active_since":  FILTER_1D_ACTIVE_SINCE,
            "n_trades":      n,
            "n_wins":        len(wins),
            "wr":            round(wr, 4),
            "avg_pnl":       round(avg_pnl, 4),
            "baseline_wr":   0.29,
            "baseline_n":    45,
            "improvement":   round(improvement, 4),
            "target_wr":     0.40,
            "target_met":    target_met,
            "status": (
                f"WR {wr:.0%} ({len(wins)}W/{n-len(wins)}L, n={n}) "
                f"{'✅ TARGET BEREIKT' if target_met else '📊 vs baseline 29%'}"
                f" | gem PnL {avg_pnl:+.2%}"
            ),
        }

    except Exception as e:
        return {
            "active_since": FILTER_1D_ACTIVE_SINCE,
            "status":       f"Fout bij berekening: {e}",
            "baseline_wr":  0.29,
        }


# ── Hoofdfunctie ────────────────────────────────────────────────────────────

def run_diagnostics() -> dict:
    """
    Hoofdfunctie: laad alle bronbestanden, bouw diagnostics per symbool
    en schrijf het resultaat naar vault_diagnostics.json.
    """
    now        = time.time()
    state      = _read_json(_STATE_FILE)
    bot_state  = _read_json(_BOT_STATE)
    heal       = _read_json(_HEAL_FILE)

    prices          = state.get("prices", {})
    positions       = state.get("positions", {})
    portfolio       = state.get("portfolio", {})
    regimes         = state.get("regimes", {})
    no_trade        = state.get("no_trade_reasons", {})
    state_age       = _state_age_seconds(state)

    free_capital    = portfolio.get("free_capital", 0.0)
    circuit_until   = float(bot_state.get("circuit_breaker_until", 0.0))
    daily_sl        = int(bot_state.get("daily_sl_count", 0))
    daily_sl_pause  = float(bot_state.get("daily_sl_pause_until", 0.0))
    last_sl_hit     = bot_state.get("last_sl_hit", {})

    min_conf        = float(_read_env_value("MIN_CONFIDENCE", "0.46"))

    heal_active     = heal.get("status") == "pending"
    heal_param      = heal.get("param", "")
    heal_reason     = heal.get("reason", "")

    circuit_active  = circuit_until > now
    daily_pause_act = daily_sl_pause > now
    stale_state     = state_age > STALE_THRESHOLD_S

    symbols = list(prices.keys()) or ["BTC/USDT", "ETH/USDT", "SOL/USDT"]
    output  = {}

    # ── RSI zone block log: laad bestaande log ──────────────────────────
    rsi_zone_log = _load_rsi_zone_log()
    new_rsi_blocks_this_run = []

    for sym in symbols:
        price   = prices.get(sym, 0.0)
        regime  = regimes.get(sym, {})
        reg_val = regime.get("regime", "unknown")
        reg_str = regime.get("strength", 0.0)
        has_pos = sym in positions
        ntr     = no_trade.get(sym, "")

        # ── Stap 1: Systeem-brede blokkeringen ─────────────────────────
        if stale_state:
            output[sym] = {
                "status": "stale",
                "badge":  "⚠️ VEROUDERDE DATA",
                "icon":   "⚠️",
                "label":  "VEROUDERDE DATA",
                "reason": f"Laatste update {state_age:.0f}s geleden (max {STALE_THRESHOLD_S}s)",
                "detail": "Bot reageert mogelijk niet — check cryptobot.service",
                "regime": reg_val, "strength": reg_str, "price": price,
                "ts":     now,
            }
            continue

        if circuit_active:
            remaining = int(circuit_until - now)
            output[sym] = {
                "status": "blocked",
                "badge":  "🔴 CIRCUIT BREAKER",
                "icon":   "🔴",
                "label":  "CIRCUIT BREAKER",
                "reason": f"Actief nog {remaining // 3600}u {(remaining % 3600) // 60}m",
                "detail": "Te veel dagverlies — bot pauzeert automatisch",
                "regime": reg_val, "strength": reg_str, "price": price,
                "ts":     now,
            }
            continue

        if daily_pause_act:
            remaining = int(daily_sl_pause - now)
            output[sym] = {
                "status": "blocked",
                "badge":  "⏸️ DAGPAUZE",
                "icon":   "⏸️",
                "label":  "DAGPAUZE",
                "reason": f"Daily SL teller: {daily_sl} — pauze nog {remaining // 60}m",
                "detail": "Te veel stop-losses vandaag — bot wacht op reset",
                "regime": reg_val, "strength": reg_str, "price": price,
                "ts":     now,
            }
            continue

        # ── Stap 2: Saldo te laag ────────────────────────────────────────
        if free_capital < MIN_FREE_CAPITAL:
            output[sym] = {
                "status": "blocked",
                "badge":  "🔴 SALDO TE LAAG",
                "icon":   "🔴",
                "label":  "SALDO TE LAAG",
                "reason": f"Vrij kapitaal: ${free_capital:.2f} (min ${MIN_FREE_CAPITAL:.0f})",
                "detail": "Onvoldoende kapitaal voor nieuwe posities",
                "regime": reg_val, "strength": reg_str, "price": price,
                "ts":     now,
            }
            continue

        # ── Stap 3: Open positie ─────────────────────────────────────────
        if has_pos:
            pos_data  = positions[sym]
            direction = pos_data.get("direction", 0)
            pnl_pct   = 0.0
            if price and pos_data.get("entry_price"):
                entry = pos_data["entry_price"]
                pnl_pct = ((price - entry) / entry) * direction * 100
            dir_label = "LONG 📈" if direction == 1 else "SHORT 📉"
            pnl_label = f"{pnl_pct:+.2f}%"
            pnl_icon  = "🟢" if pnl_pct >= 0 else "🔴"
            output[sym] = {
                "status": "position",
                "badge":  f"{pnl_icon} POSITIE OPEN ({dir_label})",
                "icon":   pnl_icon,
                "label":  f"POSITIE {dir_label}",
                "reason": f"PnL: {pnl_label} | Entry: ${pos_data.get('entry_price', 0):.2f}",
                "detail": f"SL: ${pos_data.get('stop_loss', 0):.2f} | TP: ${pos_data.get('take_profit', 0):.2f}",
                "regime": reg_val, "strength": reg_str, "price": price,
                "ts":     now,
            }
            continue

        # ── Stap 4: SL cooldown check (per symbool) ──────────────────────
        sl_info = last_sl_hit.get(sym)
        if sl_info and isinstance(sl_info, (list, tuple)) and len(sl_info) >= 2:
            sl_time, sl_dir = float(sl_info[0]), int(sl_info[1])
            remaining_cool  = SL_COOLDOWN_S - (now - sl_time)
            if remaining_cool > 0:
                dir_label = "long" if sl_dir == 1 else "short"
                output[sym] = {
                    "status": "warning",
                    "badge":  f"⏳ SL COOLDOWN ({dir_label})",
                    "icon":   "⏳",
                    "label":  "SL COOLDOWN",
                    "reason": f"{dir_label.upper()} SL cooldown — nog {remaining_cool / 3600:.1f}u",
                    "detail": "Tegengestelde richting is nog mogelijk",
                    "regime": reg_val, "strength": reg_str, "price": price,
                    "ts":     now,
                }
                continue

        # ── Stap 5: No-trade-reason analyse ─────────────────────────────
        if ntr:
            cat   = _classify_no_trade_reason(ntr)
            icon, lbl = _BADGE_MAP.get(cat, ("❓", "Onbekend"))

            # ── RSI Zone Filter speciale behandeling ──────────────────────
            if cat == "rsi_zone":
                # Persisteer dit event in de RSI zone block log
                rsi_zone_log = _append_rsi_zone_blocks(rsi_zone_log, sym, ntr, now)
                new_rsi_blocks_this_run.append(sym)

                output[sym] = {
                    "status": "rsi_zone",          # Eigen status voor dashboard
                    "badge":  f"🛡️ RSI ZONE FILTER",
                    "icon":   "🛡️",
                    "label":  "RSI ZONE FILTER",
                    "reason": ntr,
                    "detail": (
                        f"Filter 1d actief — bot koopt alleen onderin, short alleen bovenim range. "
                        f"MIN_CONF={min_conf} | Regime: {reg_val}"
                    ),
                    "regime":   reg_val, "strength": reg_str, "price": price,
                    "ts":       now,
                    "protected": True,  # Marker voor dashboard
                }
                continue

            # Alle andere no-trade-reasons
            output[sym] = {
                "status": "warning",
                "badge":  f"{icon} {lbl.upper()}",
                "icon":   icon,
                "label":  lbl.upper(),
                "reason": ntr,
                "detail": f"MIN_CONF={min_conf} | Regime: {reg_val} ({reg_str:.0%})",
                "regime": reg_val, "strength": reg_str, "price": price,
                "ts":     now,
            }
            continue

        # ── Stap 6: Alles in orde ────────────────────────────────────────
        output[sym] = {
            "status": "ok",
            "badge":  "✅ STAND-BY",
            "icon":   "✅",
            "label":  "STAND-BY",
            "reason": f"Klaar voor nieuwe signalen (vrij: ${free_capital:.0f})",
            "detail": f"Regime: {reg_val} ({reg_str:.0%}) | Prijs: ${price:,.2f}",
            "regime": reg_val, "strength": reg_str, "price": price,
            "ts":     now,
        }

    # ── Self-healer badge ────────────────────────────────────────────────
    if heal_active:
        output["_heal"] = {
            "status": "pending",
            "badge":  f"💊 HEAL PENDING: {heal_param}",
            "reason": heal_reason,
            "ts":     now,
        }

    # ── RSI Zone Block Log — schrijf samenvatting ────────────────────────
    output["_rsi_zone_log"] = _build_rsi_zone_summary(rsi_zone_log, now)

    # ── Filter 1d Effectiviteitsrapport ─────────────────────────────────
    output["_filter1d_stats"] = _calc_filter1d_stats()

    # ── Schrijf output ───────────────────────────────────────────────────
    _OUT_FILE.write_text(
        json.dumps(output, indent=2, ensure_ascii=False, default=str),
        encoding="utf-8",
    )

    return output


# ── CLI modus ────────────────────────────────────────────────────────────────
if __name__ == "__main__":
    result = run_diagnostics()
    now = time.time()

    print(f"\n{'═' * 65}")
    print("  Vault Diagnostics — Overseer Rapport")
    print(f"  {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    print(f"{'═' * 65}")

    for sym, info in result.items():
        if sym.startswith("_"):
            continue
        badge  = info.get("badge", "")
        reason = info.get("reason", "")
        print(f"  {sym:<12}  {badge:<40}  {reason[:40]}")

    # RSI Zone Log samenvatting
    rsi_log = result.get("_rsi_zone_log", {})
    total_blocks = rsi_log.get("total", 0)
    last24h      = rsi_log.get("last_24h", 0)
    by_sym       = rsi_log.get("by_symbol", {})
    print(f"\n  🛡️  RSI Zone Filter (Filter 1d)")
    print(f"     Totaal geblokkeerd: {total_blocks}  |  Laatste 24u: {last24h}")
    if by_sym:
        print(f"     Per symbool: {by_sym}")

    # Filter 1d effectiviteit
    f1d = result.get("_filter1d_stats", {})
    print(f"\n  📊  Filter 1d Effectiviteit (baseline: 29% WR in ranging)")
    print(f"     {f1d.get('status', 'Geen data')}")

    if "_heal" in result:
        print(f"\n  {result['_heal']['badge']}")
        print(f"  Reden: {result['_heal']['reason']}")

    print(f"{'═' * 65}")
    print(f"  Output: {_OUT_FILE}\n")
