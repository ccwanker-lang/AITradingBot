"""
Analyse-script voor het check commando — wordt aangeroepen door Claude tijdens diagnose.
Geen multiline -c nodig: venv/bin/python tools/check_analysis.py [analyse_naam]
"""
import json
import sys
from pathlib import Path
from collections import Counter

TRADES_FILE = Path("logs/trades.json")


def regime_analyse():
    trades = json.loads(TRADES_FILE.read_text())
    close_types = {"sell", "cover", "partial_tp1", "TIME-EXIT"}
    closed = [t for t in trades if t.get("type") in close_types]

    has_regime = sum(1 for t in closed if t.get("regime"))
    no_regime = [t for t in closed if not t.get("regime")]

    print(f"Closed trade events: {len(closed)}")
    print(f"  Met regime-veld: {has_regime}")
    print(f"  Zonder regime-veld: {len(no_regime)}")
    print(f"  Types zonder regime: {dict(Counter(t.get('type') for t in no_regime))}")

    if no_regime:
        t = no_regime[0]
        safe = {k: v for k, v in t.items() if k not in ("entry_reasons", "last_signals")}
        print(f"\nEerste trade zonder regime: {json.dumps(safe, indent=2, default=str)[:600]}")


def confidence_analyse():
    trades = json.loads(TRADES_FILE.read_text())
    buckets = {
        "<0.35": [], "0.35-0.45": [], "0.45-0.55": [],
        "0.55-0.70": [], ">=0.70": [],
    }
    close_types = {"sell", "cover"}
    closed = [t for t in trades if t.get("type") in close_types and "pnl_pct" in t]

    for t in closed:
        conf = t.get("confidence", 0)
        pnl = t.get("pnl_pct", 0)
        if conf < 0.35:
            buckets["<0.35"].append(pnl)
        elif conf < 0.45:
            buckets["0.35-0.45"].append(pnl)
        elif conf < 0.55:
            buckets["0.45-0.55"].append(pnl)
        elif conf < 0.70:
            buckets["0.55-0.70"].append(pnl)
        else:
            buckets[">=0.70"].append(pnl)

    print(f"{'Bucket':<12} {'N':>4} {'WR':>6} {'AvgPnL':>8}")
    print("-" * 35)
    for label, pnls in buckets.items():
        if not pnls:
            continue
        wr = sum(1 for p in pnls if p > 0) / len(pnls)
        avg = sum(pnls) / len(pnls)
        print(f"{label:<12} {len(pnls):>4} {wr:>6.0%} {avg:>+8.3%}")


def short_analyse():
    trades = json.loads(TRADES_FILE.read_text())
    close_types = {"sell", "cover"}
    closed = [t for t in trades if t.get("type") in close_types and "pnl_pct" in t]

    longs = [t for t in closed if t.get("direction", 1) == 1]
    shorts = [t for t in closed if t.get("direction", 1) == -1]

    for label, grp in [("LONG", longs), ("SHORT", shorts)]:
        if not grp:
            continue
        wr = sum(1 for t in grp if t["pnl_pct"] > 0) / len(grp)
        avg = sum(t["pnl_pct"] for t in grp) / len(grp)
        print(f"{label}: n={len(grp)}, WR={wr:.0%}, AvgPnL={avg:+.3%}")
        # Top exit redenen
        exits = Counter(t.get("reason", "?") for t in grp if t["pnl_pct"] < 0)
        print(f"  Verliezen: {dict(exits)}")


def overview():
    trades = json.loads(TRADES_FILE.read_text())
    print(f"Totaal records: {len(trades)}")
    print(f"Types: {dict(Counter(t.get('type') for t in trades))}")


ANALYSES = {
    "regime": regime_analyse,
    "confidence": confidence_analyse,
    "short": short_analyse,
    "overview": overview,
}

if __name__ == "__main__":
    naam = sys.argv[1] if len(sys.argv) > 1 else "overview"
    fn = ANALYSES.get(naam)
    if fn:
        fn()
    else:
        print(f"Onbekende analyse: {naam}. Kies uit: {list(ANALYSES.keys())}")
