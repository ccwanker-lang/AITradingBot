#!/usr/bin/env python3
"""
Check Report — genereert een volledig diagnostisch rapport voor de check-diagnose.
Wordt automatisch aangeroepen door Claude tijdens een 'check' commando.

Gebruik: venv/bin/python tools/check_report.py
"""
import json
import re
import subprocess
from collections import defaultdict, Counter
from datetime import datetime, timedelta
from pathlib import Path

BASE = Path(__file__).resolve().parent.parent
LOG  = BASE / "logs"

try:
    from rich.console import Console
    from rich.table import Table
    from rich.panel import Panel
    from rich import box
    console = Console()
    RICH = True
except ImportError:
    RICH = False
    class _C:
        def print(self, *a, **kw): print(*a)
        def rule(self, *a, **kw): print("─"*60)
    console = _C()

# ── Helpers ───────────────────────────────────────────────────────────────────

def _load(path, default=None):
    try:
        return json.loads(Path(path).read_text())
    except Exception:
        return default

def _pct(v): return f"{v*100:.1f}%"
def _col(v, good=0.0, warn=0.0):
    if not RICH: return str(v)
    if isinstance(v, float):
        if v >= good: return f"[green]{v}[/green]"
        if v >= warn: return f"[yellow]{v}[/yellow]"
        return f"[red]{v}[/red]"
    return str(v)


# ── 1. Processstatus ──────────────────────────────────────────────────────────

def section_process():
    console.rule("[bold cyan]1. PROCESSSTATUS[/bold cyan]")
    try:
        out = subprocess.check_output(
            ["sudo", "systemctl", "is-active", "cryptobot.service"],
            stderr=subprocess.DEVNULL, text=True
        ).strip()
        status = "[green]ACTIEF[/green]" if out == "active" else f"[red]{out}[/red]"
    except Exception:
        status = "[yellow]onbekend (geen systemctl)[/yellow]"
    console.print(f"  Bot service:      {status}")

    # Training actief?
    try:
        out = subprocess.check_output(["pgrep", "-fa", "bot.py.*train"], text=True).strip()
        if out:
            console.print(f"  Training:         [yellow]ACTIEF[/yellow] — {out[:80]}")
        else:
            console.print("  Training:         [dim]niet actief[/dim]")
    except Exception:
        pass

    # Recentste log-fout
    today = datetime.now().strftime("%Y%m%d")
    log_path = LOG / f"bot_{today}.log"
    if not log_path.exists():
        log_path = LOG / "bot_service.log"
    if log_path.exists():
        lines = log_path.read_text(errors="replace").splitlines()
        errors = [l for l in lines if "FOUT" in l or "ERROR" in l or "error" in l.lower()]
        console.print(f"  Fouten vandaag:   [{'red' if errors else 'green'}]{len(errors)}[/]")
        if errors:
            console.print(f"  Laatste fout:     [red]{errors[-1][-120:]}[/red]")

    # State.json versheid
    state = _load(LOG / "state.json", {})
    lu = state.get("last_update", "")
    if lu:
        try:
            age = (datetime.now() - datetime.fromisoformat(lu)).total_seconds()
            col = "green" if age < 300 else "yellow" if age < 900 else "red"
            console.print(f"  Laatste update:   [{col}]{lu[:19]} ({int(age)}s geleden)[/{col}]")
        except Exception:
            console.print(f"  Laatste update:   {lu}")


# ── 2. Portfolio & drawdown ───────────────────────────────────────────────────

def section_portfolio():
    console.rule("[bold cyan]2. PORTFOLIO & RISICO[/bold cyan]")
    state = _load(LOG / "state.json", {})
    pf = state.get("portfolio", {})
    if not pf:
        console.print("  [yellow]Geen portfolio data[/yellow]")
        return

    val   = pf.get("total_value", 0)
    pnl   = pf.get("pnl_pct", 0)
    dd    = pf.get("drawdown", 0)
    free  = pf.get("free_capital", 0)
    open_ = pf.get("open_positions", 0)
    tot   = pf.get("total_trades", 0)

    dd_col  = "green" if dd < 0.05 else "yellow" if dd < 0.10 else "red"
    pnl_col = "green" if pnl >= 0 else "red"

    console.print(f"  Portfolio:        ${val:.2f}  PnL: [{pnl_col}]{pnl*100:+.2f}%[/{pnl_col}]")
    console.print(f"  Drawdown:         [{dd_col}]{dd*100:.2f}%[/{dd_col}]  (max 15%)")
    console.print(f"  Vrij kapitaal:    ${free:.2f}  ({free/val*100:.0f}%)")
    console.print(f"  Open posities:    {open_}  |  Totaal events: {tot}")

    # Open posities detail
    positions = state.get("positions", {})
    for sym, pos in positions.items():
        pnl_p = pos.get("pnl_pct", 0)
        pc = "green" if pnl_p >= 0 else "red"
        partial = "✓partial" if pos.get("partial_closed") else ""
        console.print(
            f"    {sym}: [{pc}]{pnl_p*100:+.2f}%[/{pc}]  "
            f"entry={pos.get('entry_price',0):.2f}  "
            f"SL={pos.get('stop_loss',0):.2f}  {partial}"
        )


# ── 3. Win rate analyse ───────────────────────────────────────────────────────

def section_winrate():
    console.rule("[bold cyan]3. WIN RATE ANALYSE[/bold cyan]")
    trades = _load(LOG / "trades.json", [])
    if not trades:
        console.print("  [yellow]Geen trades[/yellow]")
        return

    # Exit events
    finals   = [t for t in trades if t.get("type") in ("sell","cover") and "pnl_pct" in t]
    partials = [t for t in trades if t.get("type") in ("partial_tp1","partial_tp2") and "pnl_pct" in t]
    all_ex   = finals + partials

    if not finals:
        console.print("  [yellow]Nog geen gesloten trades[/yellow]")
        return

    # Officiële per-entry WR (partial + finale gecombineerd)
    events_by_sym = defaultdict(list)
    for t in trades:
        if t.get("symbol"):
            events_by_sym[t["symbol"]].append(t)

    per_entry = []
    for sym, evs in events_by_sym.items():
        pending_entry = None
        pending_partial = None
        for t in evs:
            typ = t.get("type")
            if typ in ("buy","short"):
                pending_entry = t
                pending_partial = None
            elif typ == "partial_tp1":
                pending_partial = t.get("pnl_pct", 0)
            elif typ in ("sell","cover"):
                fn = t.get("pnl_pct", 0)
                combined = (pending_partial + fn) / 2 if pending_partial is not None else fn
                per_entry.append({
                    "sym": sym,
                    "pnl": combined,
                    "conf": (pending_entry or {}).get("confidence", 0),
                    "regime": t.get("regime") or (pending_entry or {}).get("regime","?"),
                    "direction": "LONG" if typ == "sell" else "SHORT",
                    "had_partial": pending_partial is not None,
                    "reason": t.get("reason",""),
                    "ts": t.get("timestamp",""),
                    "grade": t.get("setup_grade") or (pending_entry or {}).get("setup_grade","?"),
                })
                pending_partial = None

    wins = [r for r in per_entry if r["pnl"] > 0]
    wr   = len(wins) / len(per_entry)
    pf_w = sum(r["pnl"] for r in wins)
    pf_l = abs(sum(r["pnl"] for r in per_entry if r["pnl"] < 0))
    pf   = pf_w / pf_l if pf_l > 0 else float("inf")

    wr_col = "green" if wr >= 0.50 else "yellow" if wr >= 0.40 else "red"
    pf_col = "green" if pf >= 1.5 else "yellow" if pf >= 1.0 else "red"

    console.print(f"  Officiële WR:     [{wr_col}]{wr*100:.1f}%[/{wr_col}]  ({len(wins)}W / {len(per_entry)-len(wins)}L / {len(per_entry)} trades)")
    console.print(f"  Profit Factor:    [{pf_col}]{pf:.3f}[/{pf_col}]")
    avg_w = sum(r["pnl"] for r in wins)/len(wins) if wins else 0
    losses_list = [r for r in per_entry if r["pnl"] < 0]
    avg_l = sum(r["pnl"] for r in losses_list)/len(losses_list) if losses_list else 0
    console.print(f"  Gem. win:         [green]{avg_w*100:+.3f}%[/green]  |  Gem. verlies: [red]{avg_l*100:+.3f}%[/red]")
    console.print(f"  R/R ratio:        {abs(avg_w/avg_l):.2f}:1" if avg_l != 0 else "")

    # TP1 reach rate
    tp1_rate = sum(1 for r in per_entry if r["had_partial"]) / len(per_entry)
    tp1_col = "green" if tp1_rate >= 0.40 else "yellow" if tp1_rate >= 0.25 else "red"
    console.print(f"  TP1 bereikt:      [{tp1_col}]{tp1_rate*100:.0f}%[/{tp1_col}]  ({sum(1 for r in per_entry if r['had_partial'])}/{len(per_entry)} trades)")

    # Recent trend: laatste 10 vs alles
    if len(per_entry) >= 10:
        rec = per_entry[-10:]
        rec_wr = sum(1 for r in rec if r["pnl"] > 0) / 10
        rec_col = "green" if rec_wr >= 0.5 else "yellow" if rec_wr >= 0.4 else "red"
        trend = "↑" if rec_wr > wr else "↓"
        console.print(f"  Recente trend:    [{rec_col}]{rec_wr*100:.0f}% (laatste 10) {trend}[/{rec_col}]")

    # Per regime
    console.print()
    console.print("  [bold]Per regime:[/bold]")
    by_reg = defaultdict(list)
    for r in per_entry:
        by_reg[r["regime"]].append(r)
    for reg, recs in sorted(by_reg.items(), key=lambda x: -len(x[1])):
        rw = sum(1 for r in recs if r["pnl"] > 0)
        rwr = rw / len(recs)
        rc = "green" if rwr >= 0.5 else "yellow" if rwr >= 0.4 else "red"
        console.print(f"    {reg:15s}  [{rc}]{rwr*100:.0f}%[/{rc}]  ({rw}W/{len(recs)-rw}L  n={len(recs)})")

    # Per symbool
    console.print()
    console.print("  [bold]Per symbool:[/bold]")
    by_sym = defaultdict(list)
    for r in per_entry:
        by_sym[r["sym"]].append(r)
    for sym, recs in sorted(by_sym.items()):
        rw = sum(1 for r in recs if r["pnl"] > 0)
        rwr = rw / len(recs)
        rc = "green" if rwr >= 0.5 else "yellow" if rwr >= 0.4 else "red"
        console.print(f"    {sym:12s}  [{rc}]{rwr*100:.0f}%[/{rc}]  ({rw}W/{len(recs)-rw}L  n={len(recs)})")

    # Per richting
    console.print()
    console.print("  [bold]Per richting:[/bold]")
    by_dir = defaultdict(list)
    for r in per_entry:
        by_dir[r["direction"]].append(r)
    for d, recs in by_dir.items():
        rw = sum(1 for r in recs if r["pnl"] > 0)
        rwr = rw / len(recs)
        rc = "green" if rwr >= 0.5 else "yellow" if rwr >= 0.4 else "red"
        console.print(f"    {d:6s}  [{rc}]{rwr*100:.0f}%[/{rc}]  ({rw}W/{len(recs)-rw}L  n={len(recs)})")

    # Exit redenen
    console.print()
    console.print("  [bold]Exit redenen (verliezen):[/bold]")
    reason_cnt = Counter(r["reason"] for r in per_entry if r["pnl"] <= 0)
    for reason, cnt in reason_cnt.most_common():
        console.print(f"    {reason:25s}  {cnt}x")

    return per_entry  # geef terug voor volgende secties


# ── 4. Confidence analyse ─────────────────────────────────────────────────────

def section_confidence(per_entry):
    console.rule("[bold cyan]4. CONFIDENCE ANALYSE[/bold cyan]")
    if not per_entry:
        return

    buckets = [(0.0,0.35),(0.35,0.45),(0.45,0.55),(0.55,0.70),(0.70,1.01)]
    labels  = ["<0.35","0.35–0.45","0.45–0.55","0.55–0.70","≥0.70"]

    if RICH:
        t = Table(box=box.SIMPLE, show_header=True)
        t.add_column("Confidence", style="cyan", width=12)
        t.add_column("Trades", justify="right", width=7)
        t.add_column("WR", justify="right", width=8)
        t.add_column("TP1%", justify="right", width=7)
        t.add_column("Gem PnL", justify="right", width=10)
        t.add_column("Oordeel", width=20)

        for (lo, hi), lbl in zip(buckets, labels):
            grp = [r for r in per_entry if lo <= r["conf"] < hi]
            if not grp:
                continue
            wins = [r for r in grp if r["pnl"] > 0]
            wr   = len(wins)/len(grp)
            tp1  = sum(1 for r in grp if r["had_partial"])/len(grp)
            avg  = sum(r["pnl"] for r in grp)/len(grp)
            wrc  = "green" if wr >= 0.5 else "yellow" if wr >= 0.4 else "red"
            verdict = ""
            if wr < 0.30: verdict = "[red]⚠ SLECHT — filter weg[/red]"
            elif wr < 0.40: verdict = "[yellow]~ ZWAK[/yellow]"
            elif wr < 0.50: verdict = "[yellow]OK[/yellow]"
            else: verdict = "[green]✓ GOED[/green]"
            t.add_row(lbl, str(len(grp)), f"[{wrc}]{wr*100:.0f}%[/{wrc}]",
                      f"{tp1*100:.0f}%", f"{avg*100:+.3f}%", verdict)
        console.print(t)
    else:
        for (lo, hi), lbl in zip(buckets, labels):
            grp = [r for r in per_entry if lo <= r["conf"] < hi]
            if grp:
                wins = sum(1 for r in grp if r["pnl"] > 0)
                print(f"  {lbl}: n={len(grp)} WR={wins/len(grp)*100:.0f}%")

    # Huidige MIN_CONFIDENCE
    min_conf = 0.35
    env_path = BASE / ".env"
    if env_path.exists():
        m = re.search(r"MIN_CONFIDENCE\s*=\s*([\d.]+)", env_path.read_text())
        if m:
            min_conf = float(m.group(1))
    console.print(f"\n  Huidige MIN_CONFIDENCE: [bold]{min_conf}[/bold]")

    # Aanbeveling
    trash = [r for r in per_entry if r["conf"] < min_conf]
    if trash:
        tw = sum(1 for r in trash if r["pnl"] > 0)
        console.print(f"  [yellow]⚠  {len(trash)} trades onder MIN_CONF hadden WR {tw/len(trash)*100:.0f}% — al gefilterd[/yellow]")


# ── 5. Strategie gewichten ────────────────────────────────────────────────────

def section_strategies():
    console.rule("[bold cyan]5. STRATEGIE PRESTATIES[/bold cyan]")
    state = _load(LOG / "state.json", {})
    stats = state.get("strategy_stats", [])
    if not stats:
        console.print("  [dim]Nog geen strategie-data (wacht op eerste trades)[/dim]")
        return

    if RICH:
        t = Table(box=box.SIMPLE, show_header=True)
        t.add_column("Strategie", style="cyan", width=20)
        t.add_column("WR", justify="right", width=8)
        t.add_column("Gewicht", justify="right", width=9)
        t.add_column("Samples", justify="right", width=8)
        t.add_column("Status", width=15)

        for s in sorted(stats, key=lambda x: -(x.get("accuracy") or 0)):
            wr  = s.get("accuracy") or 0
            wt  = s.get("gewicht_mult") or 1.0
            n   = s.get("samples") or 0
            wrc = "green" if wr >= 0.5 else "yellow" if wr >= 0.4 else "red"
            wtc = "green" if wt >= 1.0 else "yellow" if wt >= 0.6 else "red"
            status = ""
            if n < 5:  status = "[dim]te weinig data[/dim]"
            elif wr < 0.35: status = "[red]⚠ slecht[/red]"
            elif wr >= 0.60: status = "[green]✓ sterk[/green]"
            t.add_row(
                s.get("naam", s.get("name","?")),
                f"[{wrc}]{wr*100:.0f}%[/{wrc}]",
                f"[{wtc}]{wt:.2f}x[/{wtc}]",
                str(n),
                status,
            )
        console.print(t)
    else:
        for s in stats:
            print(f"  {s.get('naam','?')}: WR={s.get('accuracy',0)*100:.0f}% weight={s.get('gewicht_mult',1.0):.2f}x")


# ── 6. Model gezondheid ───────────────────────────────────────────────────────

def section_models():
    console.rule("[bold cyan]6. MODEL GEZONDHEID[/bold cyan]")

    # Zoek meest recente training log
    train_logs = sorted(LOG.glob("training_*.log"), reverse=True)
    if train_logs:
        content = train_logs[0].read_text(errors="replace")
        # val_acc uit laatste epoch
        accs = re.findall(r"val_acc=([\d.]+)%", content)
        if accs:
            acc = float(accs[-1])
            col = "green" if acc >= 45 else "yellow" if acc >= 38 else "red"
            console.print(f"  LSTM val_acc:     [{col}]{acc:.1f}%[/{col}]  (random=33.3%, goed≥45%)")
            if acc < 38:
                console.print("    [red]⚠ LSTM onderscheidt nauwelijks beter dan random — hertrainen aanbevolen[/red]")
        ts = train_logs[0].stem.replace("training_","")
        console.print(f"  Laatste training: {ts[:8]} {ts[9:11]}:{ts[11:13]}")
    else:
        console.print("  [yellow]Geen trainingslog gevonden[/yellow]")

    # Model bestandsleeftijd
    for name, path in [("LSTM", BASE/"models"/"lstm_predictor.pt"), ("RL", BASE/"models"/"crypto_ppo.zip")]:
        if path.exists():
            age_h = (datetime.now() - datetime.fromtimestamp(path.stat().st_mtime)).total_seconds() / 3600
            col = "green" if age_h < 48 else "yellow" if age_h < 96 else "red"
            console.print(f"  {name} model:       [{col}]{age_h:.0f}u geleden bijgewerkt[/{col}]")
        else:
            console.print(f"  {name} model:       [red]NIET GEVONDEN[/red]")


# ── 7. Consecutive losses & drawdown trend ────────────────────────────────────

def section_risk_patterns():
    console.rule("[bold cyan]7. RISICOPATRONEN[/bold cyan]")
    trades = _load(LOG / "trades.json", [])
    finals = [t for t in trades if t.get("type") in ("sell","cover") and "pnl_pct" in t]
    if not finals:
        return

    pnls = [t["pnl_pct"] for t in finals]

    # Langste verliesreeks
    max_streak = 0
    cur_streak = 0
    for p in pnls:
        if p <= 0:
            cur_streak += 1
            max_streak = max(max_streak, cur_streak)
        else:
            cur_streak = 0
    streak_col = "green" if max_streak <= 3 else "yellow" if max_streak <= 5 else "red"
    console.print(f"  Max verliesreeks: [{streak_col}]{max_streak} op rij[/{streak_col}]")

    # Huidige verliesreeks
    cur = 0
    for p in reversed(pnls):
        if p <= 0: cur += 1
        else: break
    if cur > 0:
        cur_col = "yellow" if cur <= 2 else "red"
        console.print(f"  Huidige streak:   [{cur_col}]{cur} verlies op rij[/{cur_col}]")

    # Gem tijd tot SL hit — is ATR te krap?
    sl_exits = [t for t in finals if t.get("reason") == "STOP-LOSS"]
    if sl_exits:
        console.print(f"  SL exits:         {len(sl_exits)}/{len(finals)} ({len(sl_exits)/len(finals)*100:.0f}%)")
        sl_col = "yellow" if len(sl_exits)/len(finals) > 0.5 else "green"
        if len(sl_exits)/len(finals) > 0.6:
            console.print("    [red]⚠ Meer dan 60% eindigt in SL — ATR_SL_MULT mogelijk te krap[/red]")

    # Drawdown trend (laatste 10 performance punten)
    perf = _load(LOG / "performance.json", [])
    if len(perf) >= 20:
        recent_dd = [p.get("drawdown", 0) for p in perf[-10:]]
        older_dd  = [p.get("drawdown", 0) for p in perf[-20:-10]]
        avg_r = sum(recent_dd)/len(recent_dd)
        avg_o = sum(older_dd)/len(older_dd)
        if avg_r > avg_o * 1.2:
            console.print(f"  [red]⚠ Drawdown stijgt: {avg_o*100:.2f}% → {avg_r*100:.2f}% (recent)[/red]")
        else:
            console.print(f"  Drawdown trend:   [green]stabiel/dalend[/green] ({avg_r*100:.2f}% recent)")


# ── 8. Config snapshot vergelijking ──────────────────────────────────────────

def section_config_history():
    console.rule("[bold cyan]8. CONFIG GESCHIEDENIS[/bold cyan]")
    hist_path = LOG / "config_history.json"
    if not hist_path.exists():
        console.print("  [dim]Nog geen config snapshots (gebruik tools/config_tracker.py snapshot)[/dim]")
        return

    history = _load(hist_path, [])
    if len(history) < 2:
        console.print(f"  {len(history)} snapshot(s) aanwezig — te weinig voor vergelijking")
        return

    console.print(f"  {len(history)} snapshots opgeslagen\n")
    if RICH:
        t = Table(box=box.SIMPLE, show_header=True)
        t.add_column("#", width=4)
        t.add_column("Datum", width=17)
        t.add_column("Label", width=35)
        t.add_column("WR", width=8)
        t.add_column("PF", width=7)
        t.add_column("MIN_CONF", width=9)
        for s in history[-6:]:  # toon laatste 6
            p = s["performance"]
            e = s["env_params"]
            wr = f"{p['win_rate']}%" if p.get("win_rate") is not None else "-"
            wrc = "green" if (p.get("win_rate") or 0) >= 50 else "yellow" if (p.get("win_rate") or 0) >= 40 else "red"
            t.add_row(
                str(s["id"]),
                s["timestamp"][:16].replace("T"," "),
                s["label"][:35],
                f"[{wrc}]{wr}[/{wrc}]",
                str(p.get("profit_factor") or "-"),
                str(e.get("MIN_CONFIDENCE","?")),
            )
        console.print(t)


# ── 9. Code sanity checks ─────────────────────────────────────────────────────

def section_code_checks():
    console.rule("[bold cyan]9. CODE SANITY CHECKS[/bold cyan]")
    issues = []

    # Check TP1/TP2 bug in paper_engine.py
    pe = BASE / "execution" / "paper_engine.py"
    if pe.exists():
        text = pe.read_text()
        if "if tp1 >= tp2" in text and "tp_m * 0.45" in text:
            console.print("  [green]✓ TP1>TP2 fix aanwezig in paper_engine.py[/green]")
        else:
            issues.append("HOOG: TP1>TP2 bug ontbreekt in paper_engine.py — partial close triggert nooit in ranging")

    # Check counter-trend filter
    sig = BASE / "strategies" / "signals.py"
    if sig.exists():
        text = sig.read_text()
        if 'regime == "bear_trend" and action > 0' in text:
            console.print("  [green]✓ Counter-trend filter actief in signals.py[/green]")
        else:
            issues.append("HOOG: Counter-trend filter ontbreekt — lange/korte signalen annuleren each other in trending regime")

        # LSTM threshold
        m = re.search(r"lstm_confidence\s*<\s*([\d.]+)", text)
        if m:
            lt = float(m.group(1))
            col = "yellow" if lt > 0.42 else "green"
            console.print(f"  [{col}]LSTM drempel: {lt}[/{col}]  (aanbevolen 0.36–0.42)")
            if lt > 0.44:
                issues.append(f"MEDIUM: LSTM drempel {lt} mogelijk te hoog — LSTM geeft 0 signalen")

    # Check bear_trend confluence
    bot = BASE / "bot.py"
    if bot.exists():
        text = bot.read_text()
        if '"bear_trend"' in text and "_min_agreeing = 2" in text:
            m = re.search(r'_min_agreeing\s*=\s*2\s+if.*?"bear_trend"', text)
            if m:
                console.print("  [green]✓ Bear_trend confluence=2 actief in bot.py[/green]")
            else:
                issues.append("MEDIUM: bear_trend vereist mogelijk 3 strategies ipv 2 — shorts worden geblokkeerd")

    if issues:
        console.print()
        for iss in issues:
            col = "red" if iss.startswith("HOOG") else "yellow"
            console.print(f"  [{col}]⚠ {iss}[/{col}]")
    else:
        console.print("  [green]Geen code-issues gevonden[/green]")


# ── Main ───────────────────────────────────────────────────────────────────────

def main():
    console.print(Panel.fit(
        "[bold green]Monster Bot — Volledig Check Rapport[/bold green]\n"
        f"[dim]{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}[/dim]",
        border_style="green"
    ))

    section_process()
    console.print()
    section_portfolio()
    console.print()
    per_entry = section_winrate()
    console.print()
    section_confidence(per_entry or [])
    console.print()
    section_strategies()
    console.print()
    section_models()
    console.print()
    section_risk_patterns()
    console.print()
    section_config_history()
    console.print()
    section_code_checks()

    console.print()
    console.print(Panel.fit(
        "[bold]Rapport klaar.[/bold] Claude analyseert nu de code voor bugs en win rate killers.",
        border_style="dim"
    ))


if __name__ == "__main__":
    main()
