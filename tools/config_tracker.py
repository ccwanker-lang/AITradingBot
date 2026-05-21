#!/usr/bin/env python3
"""
Config Change Tracker — bijhoudt alle parameterwijzigingen + performance.

Gebruik:
    python tools/config_tracker.py snapshot "omschrijving"
    python tools/config_tracker.py list
    python tools/config_tracker.py diff 3 5
    python tools/config_tracker.py show 3
    python tools/config_tracker.py revert 3
"""
import os
import re
import sys
import json
from datetime import datetime
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent
HISTORY_FILE = BASE_DIR / "logs" / "config_history.json"

try:
    from rich.console import Console
    from rich.table import Table
    from rich import box
    console = Console()
    RICH = True
except ImportError:
    RICH = False
    class _FakeConsole:
        def print(self, *a, **kw): print(*a)
    console = _FakeConsole()


# ── Lees .env params ──────────────────────────────────────────────────────────

def _read_env() -> dict:
    env_path = BASE_DIR / ".env"
    params = {}
    if not env_path.exists():
        return params
    for line in env_path.read_text().splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        k, _, v = line.partition("=")
        k = k.strip()
        v = v.strip()
        if k in (
            "MIN_CONFIDENCE", "ATR_SL_MULT", "ATR_TP_MULT",
            "RL_WEIGHT", "LSTM_WEIGHT", "MAX_DRAWDOWN",
            "RETRAIN_HOURS", "CAPITAL",
        ):
            try:
                params[k] = float(v)
            except ValueError:
                params[k] = v
    return params


# ── Lees hardcoded code-params via regex ──────────────────────────────────────

def _read_code_params() -> dict:
    params = {}

    # signals.py — LSTM drempel
    sig = BASE_DIR / "strategies" / "signals.py"
    if sig.exists():
        text = sig.read_text()
        m = re.search(r"lstm_confidence\s*<\s*([\d.]+)", text)
        if m:
            params["lstm_threshold"] = float(m.group(1))

        # _REGIME_THRESHOLD dict
        m = re.search(r"_REGIME_THRESHOLD\s*=\s*\{([^}]+)\}", text, re.DOTALL)
        if m:
            for entry in re.finditer(r'"(\w+)"\s*:\s*([\d.]+)', m.group(1)):
                params[f"threshold_{entry.group(1)}"] = float(entry.group(2))

        # min_samples in AdaptiveWeightTracker
        m = re.search(r"min_samples\s*=\s*(\d+)", text)
        if m:
            params["adaptive_min_samples"] = int(m.group(1))

        # boldness in ConfidenceBrain
        m = re.search(r"boldness\s*=\s*([\d.]+)", text)
        if m:
            params["boldness"] = float(m.group(1))

        # counter_trend_filter aanwezig?
        params["counter_trend_filter"] = (
            "regime == \"bear_trend\" and action > 0" in text
            or "bear_trend" in text and "weighted = 0.0" in text
        )

    # bot.py — confluence min_agreeing voor bear_trend
    bot = BASE_DIR / "bot.py"
    if bot.exists():
        text = bot.read_text()
        m = re.search(r'_min_agreeing\s*=\s*2\s+if\s+regime\.regime\.value\s+in\s+\(([^)]+)\)', text)
        if m:
            params["confluence_min2_regimes"] = m.group(1).strip()

    return params


# ── Bereken performance uit trades.json + state.json ─────────────────────────

def _calc_performance() -> dict:
    perf = {
        "win_rate": None,
        "profit_factor": None,
        "closed_trades": 0,
        "open_positions": 0,
        "portfolio_value": None,
        "pnl_pct": None,
    }

    # Trades (gesloten) — zelfde logica als logger.py win_rate_final
    trades_path = BASE_DIR / "logs" / "trades.json"
    if trades_path.exists():
        try:
            trades = json.loads(trades_path.read_text())
        except Exception:
            trades = []

        # Finale exits only (sell/cover) — één telling per trade-entry
        finals = [t for t in trades if t.get("type") in ("sell", "cover") and "pnl_pct" in t]
        # Incl. partial TPs voor gecombineerde WR
        all_exits = [t for t in trades if t.get("type") in ("sell", "cover", "partial_tp1", "partial_tp2") and "pnl_pct" in t]

        perf["closed_trades"] = len(finals)
        if finals:
            pnls = [t["pnl_pct"] for t in finals]
            wins_f = [p for p in pnls if p > 0]
            losses_f = [p for p in pnls if p < 0]
            perf["win_rate"] = round(len(wins_f) / len(finals) * 100, 1)

            all_pnls = [t["pnl_pct"] for t in all_exits]
            wins_a = [p for p in all_pnls if p > 0]
            perf["win_rate_combined"] = round(len(wins_a) / len(all_exits) * 100, 1) if all_exits else None

            total_win = sum(p for p in pnls if p > 0)
            total_loss = abs(sum(losses_f)) if losses_f else 0
            perf["profit_factor"] = (
                round(total_win / total_loss, 3) if total_loss > 0 else None
            )

    # State (portfolio waarde)
    state_path = BASE_DIR / "logs" / "state.json"
    if state_path.exists():
        try:
            state = json.loads(state_path.read_text())
            port = state.get("portfolio", {})
            perf["portfolio_value"] = round(port.get("total_value", 0), 2)
            perf["pnl_pct"] = round(port.get("pnl_pct", 0) * 100, 2)
            perf["open_positions"] = port.get("open_positions", 0)
        except Exception:
            pass

    return perf


# ── History lezen/schrijven ───────────────────────────────────────────────────

def _load_history() -> list:
    if not HISTORY_FILE.exists():
        return []
    try:
        return json.loads(HISTORY_FILE.read_text())
    except Exception:
        return []


def _save_history(history: list) -> None:
    HISTORY_FILE.parent.mkdir(parents=True, exist_ok=True)
    HISTORY_FILE.write_text(json.dumps(history, indent=2, ensure_ascii=False))


# ── Commando's ────────────────────────────────────────────────────────────────

def cmd_snapshot(label: str = "") -> None:
    history = _load_history()
    snap = {
        "id": len(history) + 1,
        "timestamp": datetime.now().isoformat(timespec="seconds"),
        "label": label or "handmatige snapshot",
        "env_params": _read_env(),
        "code_params": _read_code_params(),
        "performance": _calc_performance(),
    }
    history.append(snap)
    _save_history(history)
    console.print(f"[green]Snapshot #{snap['id']} opgeslagen:[/green] {snap['label']}")
    _print_snap_summary(snap)


def _print_snap_summary(snap: dict) -> None:
    p = snap["performance"]
    e = snap["env_params"]
    wr = f"{p['win_rate']}%" if p["win_rate"] is not None else "n/b"
    pf = str(p["profit_factor"]) if p["profit_factor"] is not None else "n/b"
    val = f"€{p['portfolio_value']}" if p["portfolio_value"] is not None else "n/b"
    pnl = f"{p['pnl_pct']}%" if p["pnl_pct"] is not None else "n/b"
    console.print(
        f"  WR: [bold]{wr}[/bold]  PF: [bold]{pf}[/bold]  "
        f"Trades: {p['closed_trades']}  Portfolio: {val} ({pnl})"
    )
    console.print(
        f"  MIN_CONF={e.get('MIN_CONFIDENCE','?')}  "
        f"SL/TP={e.get('ATR_SL_MULT','?')}×/{e.get('ATR_TP_MULT','?')}×  "
        f"RL={e.get('RL_WEIGHT','?')}  LSTM={e.get('LSTM_WEIGHT','?')}"
    )


def cmd_list() -> None:
    history = _load_history()
    if not history:
        console.print("[yellow]Geen snapshots gevonden. Run eerst: python tools/config_tracker.py snapshot[/yellow]")
        return

    if RICH:
        t = Table(title="Config Wijzigingen Geschiedenis", box=box.ROUNDED, show_lines=True)
        t.add_column("#", style="bold cyan", width=4)
        t.add_column("Datum", width=18)
        t.add_column("Label", width=30)
        t.add_column("WR%", justify="right", width=7)
        t.add_column("PF", justify="right", width=6)
        t.add_column("Trades", justify="right", width=7)
        t.add_column("Portfolio", justify="right", width=10)
        t.add_column("PnL%", justify="right", width=7)
        t.add_column("MIN_CONF", justify="right", width=9)
        t.add_column("SL/TP", justify="right", width=9)

        for s in history:
            p = s["performance"]
            e = s["env_params"]
            wr = f"{p['win_rate']}%" if p.get("win_rate") is not None else "-"
            pf = str(p.get("profit_factor") or "-")
            val = f"{p['portfolio_value']:.1f}" if p.get("portfolio_value") else "-"
            pnl = f"{p['pnl_pct']}%" if p.get("pnl_pct") is not None else "-"
            sl = e.get("ATR_SL_MULT", "?")
            tp = e.get("ATR_TP_MULT", "?")
            wr_color = "green" if p.get("win_rate", 0) >= 50 else "yellow" if p.get("win_rate", 0) >= 40 else "red"
            ts = s["timestamp"][:16].replace("T", " ")
            t.add_row(
                str(s["id"]),
                ts,
                s["label"][:30],
                f"[{wr_color}]{wr}[/{wr_color}]",
                pf,
                str(p.get("closed_trades", 0)),
                val,
                pnl,
                str(e.get("MIN_CONFIDENCE", "?")),
                f"{sl}×/{tp}×",
            )
        console.print(t)
    else:
        for s in history:
            p = s["performance"]
            print(f"#{s['id']} {s['timestamp'][:16]} | {s['label'][:28]} | "
                  f"WR={p.get('win_rate')}% PF={p.get('profit_factor')} "
                  f"trades={p.get('closed_trades')} val={p.get('portfolio_value')}")

    console.print(f"\n[dim]Gebruik 'diff X Y' om twee snapshots te vergelijken, 'show N' voor details[/dim]")


def cmd_show(n: int) -> None:
    history = _load_history()
    snap = _get_snap(history, n)
    if not snap:
        return

    console.print(f"\n[bold cyan]Snapshot #{snap['id']}[/bold cyan] — {snap['timestamp']}")
    console.print(f"[bold]{snap['label']}[/bold]\n")

    if RICH:
        t = Table(box=box.MINIMAL_DOUBLE_HEAD, show_header=True)
        t.add_column("Parameter", style="cyan")
        t.add_column("Waarde", style="white")
        t.add_column("Categorie", style="dim")

        for k, v in snap["env_params"].items():
            t.add_row(k, str(v), ".env")
        for k, v in snap["code_params"].items():
            t.add_row(k, str(v), "code")
        for k, v in snap["performance"].items():
            if v is not None:
                t.add_row(k, str(v), "performance")
        console.print(t)
    else:
        print("ENV:", json.dumps(snap["env_params"], indent=2))
        print("CODE:", json.dumps(snap["code_params"], indent=2))
        print("PERF:", json.dumps(snap["performance"], indent=2))


def cmd_diff(a: int, b: int) -> None:
    history = _load_history()
    snap_a = _get_snap(history, a)
    snap_b = _get_snap(history, b)
    if not snap_a or not snap_b:
        return

    console.print(f"\n[bold]Vergelijking: Snapshot #{a} → #{b}[/bold]")
    console.print(f"  #{a}: {snap_a['timestamp'][:16]} — {snap_a['label']}")
    console.print(f"  #{b}: {snap_b['timestamp'][:16]} — {snap_b['label']}\n")

    # Combineer alle params
    all_keys_env = sorted(set(snap_a["env_params"]) | set(snap_b["env_params"]))
    all_keys_code = sorted(set(snap_a.get("code_params", {})) | set(snap_b.get("code_params", {})))
    all_keys_perf = sorted(set(snap_a["performance"]) | set(snap_b["performance"]))

    if RICH:
        t = Table(box=box.ROUNDED, show_lines=False)
        t.add_column("Parameter", style="cyan", width=35)
        t.add_column(f"#{a}", justify="right", width=20)
        t.add_column(f"#{b}", justify="right", width=20)
        t.add_column("Δ", width=12)

        changed_any = False

        def add_section(label, keys, d_a, d_b):
            nonlocal changed_any
            section_added = False
            for k in keys:
                va = d_a.get(k)
                vb = d_b.get(k)
                if va == vb:
                    continue
                if not section_added:
                    t.add_row(f"[bold yellow]── {label} ──[/bold yellow]", "", "", "")
                    section_added = True
                changed_any = True
                # Delta berekening
                delta = ""
                try:
                    fa, fb = float(va), float(vb)
                    d = fb - fa
                    delta = f"[green]+{d:.4g}[/green]" if d > 0 else f"[red]{d:.4g}[/red]"
                except (TypeError, ValueError):
                    delta = "±"
                t.add_row(k, str(va) if va is not None else "-", str(vb) if vb is not None else "-", delta)

        add_section(".env instellingen", all_keys_env, snap_a["env_params"], snap_b["env_params"])
        add_section("code parameters", all_keys_code, snap_a.get("code_params", {}), snap_b.get("code_params", {}))
        add_section("performance", all_keys_perf, snap_a["performance"], snap_b["performance"])

        if not changed_any:
            console.print("[green]Geen verschillen gevonden tussen deze twee snapshots.[/green]")
        else:
            console.print(t)
            _print_performance_delta(snap_a, snap_b)
    else:
        for k in all_keys_env:
            va = snap_a["env_params"].get(k)
            vb = snap_b["env_params"].get(k)
            if va != vb:
                print(f"{k}: {va} → {vb}")


def _print_performance_delta(snap_a: dict, snap_b: dict) -> None:
    pa = snap_a["performance"]
    pb = snap_b["performance"]
    wr_a = pa.get("win_rate")
    wr_b = pb.get("win_rate")
    pf_a = pa.get("profit_factor")
    pf_b = pb.get("profit_factor")

    parts = []
    if wr_a is not None and wr_b is not None:
        d = wr_b - wr_a
        col = "green" if d > 0 else "red"
        parts.append(f"WR [{col}]{'+' if d > 0 else ''}{d:.1f}%[/{col}] ({wr_a}% → {wr_b}%)")
    if pf_a is not None and pf_b is not None:
        d = pf_b - pf_a
        col = "green" if d > 0 else "red"
        parts.append(f"PF [{col}]{'+' if d > 0 else ''}{d:.3f}[/{col}] ({pf_a} → {pf_b})")
    if parts:
        console.print("\n[bold]Performance delta:[/bold] " + "  |  ".join(parts))


def cmd_revert(n: int) -> None:
    history = _load_history()
    snap = _get_snap(history, n)
    if not snap:
        return

    env_path = BASE_DIR / ".env"
    if not env_path.exists():
        console.print("[red].env niet gevonden[/red]")
        return

    env_params = snap["env_params"]
    code_params = snap.get("code_params", {})

    console.print(f"\n[bold yellow]Herstel naar Snapshot #{n}[/bold yellow]")
    console.print(f"  Datum: {snap['timestamp']}  |  {snap['label']}\n")

    console.print("[bold]Wijzigingen in .env:[/bold]")
    current_env = _read_env()
    changes = {}
    for k, v in env_params.items():
        curr = current_env.get(k)
        if curr != v:
            console.print(f"  {k}: [red]{curr}[/red] → [green]{v}[/green]")
            changes[k] = v
        else:
            console.print(f"  {k}: {v} [dim](ongewijzigd)[/dim]")

    if code_params:
        console.print("\n[bold yellow]Code parameters (handmatig aanpassen):[/bold yellow]")
        for k, v in code_params.items():
            console.print(f"  {k}: {v}")

    if not changes:
        console.print("\n[green].env is al identiek aan snapshot #{n}[/green]")
        return

    console.print(f"\n[bold]Weet je zeker dat je .env wilt herstellen naar snapshot #{n}?[/bold] (j/n): ", end="")
    try:
        antwoord = input().strip().lower()
    except (EOFError, KeyboardInterrupt):
        antwoord = "n"

    if antwoord != "j":
        console.print("[yellow]Geannuleerd.[/yellow]")
        return

    # Update .env
    env_text = env_path.read_text()
    for k, v in changes.items():
        # Vervang de waarde in .env (regels als KEY=VALUE of KEY=VALUE # comment)
        env_text = re.sub(
            rf"^({re.escape(k)}\s*=\s*)(.+)$",
            rf"\g<1>{v}",
            env_text,
            flags=re.MULTILINE,
        )
    env_path.write_text(env_text)

    # Sla snapshot op van de revert zelf
    new_label = f"revert naar snapshot #{n}: {snap['label'][:30]}"
    cmd_snapshot(new_label)

    console.print(f"\n[green].env hersteld. Herstart de bot om wijzigingen toe te passen:[/green]")
    console.print("[bold]sudo systemctl restart cryptobot.service[/bold]")


def _get_snap(history: list, n: int) -> dict | None:
    for s in history:
        if s["id"] == n:
            return s
    console.print(f"[red]Snapshot #{n} niet gevonden. Gebruik 'list' om alle snapshots te zien.[/red]")
    return None


# ── Public API voor bot.py ────────────────────────────────────────────────────

def auto_snapshot(label: str = "") -> None:
    """Roep dit aan vanuit bot.py bij elke herstart — faalt nooit."""
    try:
        if not label:
            label = "auto: bot herstart"
        cmd_snapshot(label)
    except Exception as e:
        pass  # nooit de bot laten crashen door tracker


# ── CLI entry point ───────────────────────────────────────────────────────────

def main():
    args = sys.argv[1:]
    if not args:
        print(__doc__)
        sys.exit(0)

    cmd = args[0].lower()

    if cmd == "snapshot":
        label = " ".join(args[1:]) if len(args) > 1 else ""
        cmd_snapshot(label)

    elif cmd == "list":
        cmd_list()

    elif cmd == "show":
        if len(args) < 2:
            console.print("[red]Gebruik: show N[/red]")
            sys.exit(1)
        cmd_show(int(args[1]))

    elif cmd == "diff":
        if len(args) < 3:
            console.print("[red]Gebruik: diff A B[/red]")
            sys.exit(1)
        cmd_diff(int(args[1]), int(args[2]))

    elif cmd == "revert":
        if len(args) < 2:
            console.print("[red]Gebruik: revert N[/red]")
            sys.exit(1)
        cmd_revert(int(args[1]))

    else:
        console.print(f"[red]Onbekend commando: {cmd}[/red]")
        print(__doc__)
        sys.exit(1)


if __name__ == "__main__":
    main()
