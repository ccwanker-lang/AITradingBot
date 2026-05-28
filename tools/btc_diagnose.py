"""
BTC Diagnose — waarom tradt BTC nu niet?

Loopt door ELKE actieve filter met de huidige BTC waarden en laat precies
zien wat er moet veranderen voordat BTC weer een trade opent.

Gebruik:  venv/bin/python tools/btc_diagnose.py
"""
import json
import os
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

try:
    from dotenv import load_dotenv
    load_dotenv(ROOT / ".env")
except ImportError:
    pass

import warnings
warnings.filterwarnings("ignore")


# ── Hulpfuncties voor tabel ───────────────────────────────────────────────────
GREEN  = "\033[92m"
RED    = "\033[91m"
YELLOW = "\033[93m"
CYAN   = "\033[96m"
BOLD   = "\033[1m"
RESET  = "\033[0m"

def ok(msg=""):     return f"{GREEN}✅ PASS{RESET}  {msg}"
def fail(msg=""):   return f"{RED}❌ BLOCK{RESET} {msg}"
def warn(msg=""):   return f"{YELLOW}⚠  WARN{RESET}  {msg}"
def hdr(msg=""):    return f"{BOLD}{CYAN}{msg}{RESET}"

def row(label, status, value="", threshold="", note=""):
    label_w = 32
    return f"  {label:<{label_w}} {status:<50}  val={value:<18} thresh={threshold:<18} {note}"


# ── Data laden ────────────────────────────────────────────────────────────────
def load_state() -> dict:
    p = ROOT / "logs" / "state.json"
    with open(p) as f:
        return json.load(f)

def load_trades() -> list:
    p = ROOT / "logs" / "trades.json"
    with open(p) as f:
        return json.load(f)


# ── Live BTC data ophalen ────────────────────────────────────────────────────
def fetch_btc_data():
    from data.fetcher import DataFetcher
    from data.features import add_all_features
    from config import Config
    cfg = Config.from_env()
    fetcher = DataFetcher(cfg.exchange_id, cfg.api_key, cfg.api_secret)
    df_1h = fetcher.fetch_ohlcv("BTC/USDT", "1h", limit=200)
    df_4h = fetcher.fetch_ohlcv("BTC/USDT", "4h", limit=100)
    df_1d = fetcher.fetch_ohlcv("BTC/USDT", "1d", limit=50)
    df_1h = add_all_features(df_1h)
    df_4h = add_all_features(df_4h)
    df_1d = add_all_features(df_1d)
    return df_1h, df_4h, df_1d


# ── Filters checken ──────────────────────────────────────────────────────────
def run_diagnosis():
    print()
    print(hdr("=" * 70))
    print(hdr(f"  BTC/USDT DIAGNOSE — {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}"))
    print(hdr("=" * 70))
    print()

    # ── Laatste BTC trades ────────────────────────────────────────────────
    trades = load_trades()
    btc_trades = [t for t in trades if t.get("symbol") == "BTC/USDT"]
    btc_entries = [t for t in btc_trades if t.get("type") in ("buy", "short")]
    btc_closed  = [t for t in btc_trades if t.get("type") in ("sell", "cover") and "pnl_pct" in t]

    print(hdr("1. LAATSTE BTC TRADES"))
    print(f"  Totaal BTC trades in log : {len(btc_trades)}")
    if btc_entries:
        last = btc_entries[-1]
        entry_ts = last.get("timestamp", "?")[:16]
        try:
            from datetime import datetime as dt
            entry_dt = dt.fromisoformat(last.get("timestamp",""))
            age_h = (dt.now() - entry_dt).total_seconds() / 3600
            age_str = f"({age_h:.1f} uur geleden)"
        except Exception:
            age_str = ""
        print(f"  Laatste entry            : {last.get('type','?').upper()} @ {last.get('price',0):,.2f}  {entry_ts}  {age_str}")
        print(f"  Regime bij entry         : {last.get('regime','?')}")
    else:
        print(f"  {warn('Geen BTC entries gevonden')}")

    if btc_closed:
        wins  = [t for t in btc_closed if t.get("pnl_pct",0) > 0]
        losses= [t for t in btc_closed if t.get("pnl_pct",0) <= 0]
        wr    = len(wins) / len(btc_closed) * 100
        print(f"  Gesloten trades          : {len(btc_closed)}  WR={wr:.0f}%  ({len(wins)}W/{len(losses)}L)")
        last_7_closed = btc_closed[-7:]
        pnls = [t.get("pnl_pct",0)*100 for t in last_7_closed]
        print(f"  Laatste 7 PnL            : {', '.join(f'{p:+.2f}%' for p in pnls)}")
    print()

    # ── State laden ───────────────────────────────────────────────────────
    print(hdr("2. HUIDIGE BOT STATE"))
    state    = load_state()
    btc_sig  = {d["naam"]: d for d in state.get("current_signals", {}).get("BTC/USDT", [])}
    btc_reg  = state.get("regimes", {}).get("BTC/USDT", {})
    no_trade = state.get("no_trade_reasons", {}).get("BTC/USDT", "geen")
    portfolio= state.get("portfolio", {})
    meta     = state.get("meta", {})

    regime_val  = btc_reg.get("regime", "?")
    strength    = btc_reg.get("strength", 0)
    portfolio_v = portfolio.get("total_value", 1000)
    drawdown    = portfolio.get("drawdown", 0)
    streak      = meta.get("streak", 0)
    throttle    = meta.get("throttle", 1.0)

    print(f"  Huidig regime            : {regime_val} ({strength:.0%})")
    print(f"  Portfolio                : ${portfolio_v:,.2f}  DD={drawdown:.1%}")
    print(f"  Throttle                 : {throttle:.0%}  streak={streak}")
    print(f"  Huidige no_trade reden   : {no_trade}")
    print()

    # ── Live data ophalen ─────────────────────────────────────────────────
    print(hdr("3. LIVE DATA OPHALEN..."))
    try:
        df_1h, df_4h, df_1d = fetch_btc_data()
        price  = float(df_1h["close"].iloc[-1])
        atr    = float(df_1h["atr_14"].iloc[-1]) if "atr_14" in df_1h.columns else price * 0.02
        rsi_1h = float(df_1h["rsi_14"].iloc[-1]) if "rsi_14" in df_1h.columns else 50.0
        rsi_1d = float(df_1d["rsi_14"].iloc[-1]) if "rsi_14" in df_1d.columns else 50.0
        ema9_1h  = float(df_1h["ema_9"].iloc[-1])  if "ema_9"  in df_1h.columns else 0
        ema21_1h = float(df_1h["ema_21"].iloc[-1]) if "ema_21" in df_1h.columns else 0
        ema9_4h  = float(df_4h["ema_9"].iloc[-1])  if "ema_9"  in df_4h.columns else 0
        ema21_4h = float(df_4h["ema_21"].iloc[-1]) if "ema_21" in df_4h.columns else 0
        adx_4h   = float(df_4h["adx_14"].iloc[-1]) if "adx_14" in df_4h.columns else 20.0
        vol_ratio_now = float(df_1h["volume_ratio"].iloc[-4:-1].mean()) if "volume_ratio" in df_1h.columns and len(df_1h) >= 4 else 1.0
        local_low_10  = float(df_1h["low"].iloc[-10:].min())
        local_high_10 = float(df_1h["high"].iloc[-10:].max())
        bb_width      = float(df_1h["bb_width"].iloc[-1]) if "bb_width" in df_1h.columns else 0.05
        tf_trend      = 1 if ema9_4h > ema21_4h else -1
        trend_1d_ema9  = float(df_1d["ema_9"].iloc[-1])  if "ema_9"  in df_1d.columns else 0
        trend_1d_ema21 = float(df_1d["ema_21"].iloc[-1]) if "ema_21" in df_1d.columns else 0
        trend_1d_val   = 1 if trend_1d_ema9 > trend_1d_ema21 else -1
        print(f"  Prijs        : ${price:,.2f}")
        print(f"  ATR (1h)     : ${atr:.2f}  ({atr/price*100:.2f}%)")
        print(f"  RSI 1h       : {rsi_1h:.1f}")
        print(f"  RSI 1d       : {rsi_1d:.1f}")
        print(f"  4h EMA trend : {'BULLISH' if tf_trend == 1 else 'BEARISH'} (ema9={ema9_4h:,.0f} vs ema21={ema21_4h:,.0f})")
        print(f"  1d EMA trend : {'BULLISH' if trend_1d_val == 1 else 'BEARISH'} (ema9={trend_1d_ema9:,.0f} vs ema21={trend_1d_ema21:,.0f})")
        print(f"  ADX 4h       : {adx_4h:.1f}")
        print(f"  Vol ratio    : {vol_ratio_now:.2f}x")
        print(f"  Local low 10k: ${local_low_10:,.2f} (prijs {(price/local_low_10-1)*100:.2f}% boven)")
        print()
        live_ok = True
    except Exception as exc:
        print(f"  {warn(f'Live data ophalen mislukt: {exc}')}")
        print(f"  Gebruik state.json-waarden als fallback")
        live_ok = False
        price  = state.get("prices", {}).get("BTC/USDT", 73000)
        rsi_1h = 30.0  # fallback vanuit no_trade reason
        tf_trend = -1
        trend_1d_val = -1
        atr = price * 0.02
        vol_ratio_now = 1.0
        local_low_10 = price * 0.99
        bb_width = 0.05
        adx_4h = 40.0
        print()

    # ── Signaalscores uit state.json ──────────────────────────────────────
    print(hdr("4. SIGNALEN (vanuit state.json)"))
    tech_strats = ["EMA_Cross","Bollinger","RSI","MACD","Breakout",
                   "SMC","SR","Ichimoku","Wyckoff","VolumeProfile","MarketStructure","Grid"]
    action_short = sum(1 for s in tech_strats
                       if btc_sig.get(s, {}).get("actie") == -1)
    action_long  = sum(1 for s in tech_strats
                       if btc_sig.get(s, {}).get("actie") == 1)
    action_none  = sum(1 for s in tech_strats
                       if btc_sig.get(s, {}).get("actie") == 0)

    for name in tech_strats + ["RL_Agent", "LSTM", "Sentiment", "OrderBook"]:
        sig = btc_sig.get(name, {})
        act = sig.get("actie", 0)
        conf = sig.get("confidence", 0)
        reden = sig.get("reden", "—")[:60]
        sym = "🔻" if act == -1 else ("🔺" if act == 1 else "⬛")
        print(f"  {sym} {name:<18} actie={act:+d}  conf={conf:.3f}  {reden}")

    assumed_action = -1 if action_short > action_long else (1 if action_long > action_short else 0)
    print(f"\n  Meeste overeenstemming: {'SHORT' if assumed_action==-1 else 'LONG' if assumed_action==1 else 'NEUTRAAL'}")
    print(f"  Short votes: {action_short}  Long votes: {action_long}  Neutraal: {action_none}")
    print()

    # ── Filter-voor-filter diagnose ───────────────────────────────────────
    print(hdr("5. FILTER DIAGNOSE — BTC/USDT SHORT"))
    print(f"  {'Filter':<35} {'Status':<55} {'Waarde':<20} {'Drempel':<20}")
    print("  " + "─" * 130)

    results = []  # (naam, passed, detail)

    def add(naam, passed, val="", thresh="", note=""):
        results.append((naam, passed, val, thresh, note))

    # ── Pre-filter: score boven drempel? ──────────────────────────────────
    btc_score_raw = 0.0
    for sig in state.get("current_signals", {}).get("BTC/USDT", []):
        btc_score_raw += sig.get("bijdrage", 0)
    add("Score vs drempel",
        abs(btc_score_raw) > 0.10,
        f"{btc_score_raw:+.4f}", ">0.10 (bear_trend)")

    # ── StatArb veto ──────────────────────────────────────────────────────
    add("StatArb veto", True, "n/a", "conf>0.65 + ander signaal",
        "(kan niet bepalen zonder live run)")

    # ── 4h MTF filter ─────────────────────────────────────────────────────
    mtf_ok = (assumed_action == 0) or (assumed_action == tf_trend) or (regime_val in ("accumulation","ranging"))
    add("4h MTF filter",
        mtf_ok,
        f"1h={'SHORT' if assumed_action==-1 else 'LONG'} 4h={'BEAR' if tf_trend==-1 else 'BULL'}",
        "1h==4h richting (of MR-setup)")

    # ── Filter 1: Regime richting ─────────────────────────────────────────
    f1_ok = not (assumed_action == 1 and regime_val == "bear_trend")
    add("F1 Regime richting",
        f1_ok,
        f"actie={'SHORT'if assumed_action==-1 else 'LONG'} regime={regime_val}",
        "Geen longs in bear_trend")

    # ── Filter 1b: 1D macro ───────────────────────────────────────────────
    f1b_ok = not (trend_1d_val == -1 and tf_trend == -1 and assumed_action == 1)
    add("F1b 1D macro filter",
        f1b_ok,
        f"1d={'BEAR'if trend_1d_val==-1 else 'BULL'} 4h={'BEAR'if tf_trend==-1 else 'BULL'}",
        "Geen longs als 1D+4h bearish")

    # ── Filter 1c: Ranging skip ───────────────────────────────────────────
    is_bb_squeeze = bb_width < 0.015
    f1c_ok = (regime_val != "ranging") or is_bb_squeeze
    add("F1c Ranging skip",
        f1c_ok,
        f"regime={regime_val} bb_w={bb_width:.4f}",
        "Skip ranging tenzij BB squeeze")

    # ── Filter 2: SL cooldown ─────────────────────────────────────────────
    add("F2 SL cooldown",
        True,
        "geen actieve cooldown (aanname)",
        "4u na SL-hit",
        "(check logs voor zekerheid)")

    # ── Filter 3: BOS veto ────────────────────────────────────────────────
    ms_sig = btc_sig.get("MarketStructure", {})
    ms_action = ms_sig.get("actie", 0)
    ms_conf   = ms_sig.get("confidence", 0)
    f3_ok = not (ms_conf >= 0.70 and ms_action != 0 and ms_action != assumed_action)
    add("F3 BOS veto",
        f3_ok,
        f"MS actie={ms_action} conf={ms_conf:.2f}",
        "MS conf≥0.70 en zelfde richting")

    # ── Filter 4: Confluence ──────────────────────────────────────────────
    agreeing = action_short if assumed_action == -1 else action_long
    min_agree = 3  # shorts in bear_trend = 3
    f4_ok = agreeing >= min_agree
    add("F4 Confluence",
        f4_ok,
        f"{agreeing}/{min_agree} strategieën eens",
        f"≥{min_agree} voor SHORT bear_trend")

    # ── Filter 5: RSI extremen ────────────────────────────────────────────
    strong_bear = regime_val == "bear_trend" and strength >= 0.85
    rsi_thresh  = 28 if regime_val == "bear_trend" else 35  # na onze fix vandaag
    f5_ok = not (assumed_action == -1 and rsi_1h < rsi_thresh)
    add("F5 RSI extremen",
        f5_ok,
        f"RSI={rsi_1h:.1f}",
        f">{rsi_thresh} voor short (bear_trend fix)")

    # ── Filter 5b: Lokaal dieptepunt ─────────────────────────────────────
    local_pct = 0.0 if (regime_val == "bear_trend" and strength >= 0.95) else (0.005 if strong_bear else 0.015)
    dist_from_low = (price / local_low_10 - 1) if local_low_10 > 0 else 1.0
    f5b_ok = not (assumed_action == -1 and price < local_low_10 * (1 + local_pct))
    add("F5b Lokaal dieptepunt",
        f5b_ok,
        f"prijs {dist_from_low:.2%} boven low ${local_low_10:,.2f}",
        f">={local_pct:.1%} boven low (strength={strength:.0%})")

    # ── Filter 6: Volume ──────────────────────────────────────────────────
    vol_min = 0.30 if strong_bear else 0.50
    f6_ok = vol_ratio_now >= vol_min
    add("F6 Volume",
        f6_ok,
        f"vol_ratio={vol_ratio_now:.2f}x",
        f"≥{vol_min:.2f}x")

    # ── Filter 7: Consecutive losses ─────────────────────────────────────
    last_3_pnl = [t.get("pnl_pct", 0) for t in btc_closed[-3:]] if len(btc_closed) >= 3 else []
    f7_ok = not (len(last_3_pnl) == 3 and all(p < 0 for p in last_3_pnl))
    add("F7 Verliesstreak bescherming",
        f7_ok,
        f"laatste 3: {', '.join(f'{p*100:+.1f}%' for p in last_3_pnl) if last_3_pnl else 'te weinig data'}",
        "<3 op rij negatief")

    # ── Filter 8: Noise index ─────────────────────────────────────────────
    noise = 0
    if adx_4h < 15 and regime_val not in ("ranging", "accumulation"):
        noise += 1
    if vol_ratio_now < 0.40:
        noise += 1
    f8_ok = noise < 2
    add("F8 Noise index",
        f8_ok,
        f"noise={noise}/3 (adx={adx_4h:.0f} vol={vol_ratio_now:.2f})",
        "<2 ruis-indicatoren")

    # ── Correlatie ────────────────────────────────────────────────────────
    open_pos = state.get("positions", {})
    same_dir = sum(1 for p in open_pos.values() if p.get("direction") == (-1 if assumed_action == -1 else 1))
    corr_ok  = same_dir < 2
    add("Correlatie-limiet",
        corr_ok,
        f"{same_dir} posities zelfde richting",
        "<2 gelijktijdig")

    # ── Tabel afdrukken ───────────────────────────────────────────────────
    blocked_filters = []
    for naam, passed, val, thresh, note in results:
        status = ok() if passed else fail()
        print(f"  {naam:<35} {status:<50} val={val:<25} thresh={thresh:<25} {note}")
        if not passed:
            blocked_filters.append(naam)

    # ── Samenvatting ──────────────────────────────────────────────────────
    print()
    print(hdr("6. SAMENVATTING"))
    if not blocked_filters:
        print(f"  {ok('Alle filters PASS')} — BTC kan nu handelen als score boven drempel komt")
        print(f"  Score nu: {btc_score_raw:+.4f}  |  Drempel: ~0.10")
    else:
        print(f"  {RED}{BOLD}{len(blocked_filters)} filter(s) blokkeren BTC:{RESET}")
        for f in blocked_filters:
            print(f"    ❌ {f}")

    print()
    print(hdr("7. WAT MOET VERANDEREN VOOR BTC HANDELT"))

    conditions = []

    if not f4_ok:
        need = min_agree - agreeing
        conditions.append(
            f"  → Confluence: {need} extra strategie(ën) moeten SHORT worden "
            f"({agreeing}/{min_agree} nu, mankeert {need})"
        )

    if not f5_ok:
        conditions.append(
            f"  → RSI: moet stijgen van {rsi_1h:.1f} naar >{rsi_thresh} "
            f"(nog {rsi_thresh - rsi_1h:.1f} punten nodig)"
        )

    if not f5b_ok:
        need_price = local_low_10 * (1 + local_pct)
        conditions.append(
            f"  → Prijs: moet stijgen van ${price:,.2f} naar >${need_price:,.2f} "
            f"(nog ${need_price - price:,.2f} = {(need_price/price - 1)*100:.2f}%)"
        )

    if not f6_ok:
        conditions.append(
            f"  → Volume: moet stijgen van {vol_ratio_now:.2f}x naar ≥{vol_min:.2f}x gemiddeld"
        )

    if not f4_ok or not (abs(btc_score_raw) > 0.10):
        conditions.append(
            f"  → Score: {btc_score_raw:+.4f} moet naar >0.10 (nog {0.10 - abs(btc_score_raw):.4f} nodig)"
        )

    if not conditions:
        print(f"  {ok('Geen condities — BTC kan direct handelen (score te laag)')}")
    else:
        for c in conditions:
            print(c)

    print()
    print(hdr("=" * 70))
    print()


if __name__ == "__main__":
    run_diagnosis()
