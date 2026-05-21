"""
Monte Carlo Simulaties — berekent drawdown-distributie op basis van gesloten trades.

Geeft antwoord op: "wat is de kans op X% drawdown in de volgende N trades?"
Werkt met minimaal 10 closed trades. Meer trades = betrouwbaarder.

Gebruik:
    mc = MonteCarloSimulator()
    result = mc.run()
    print(mc.report())
"""
from __future__ import annotations

import json
import numpy as np
from dataclasses import dataclass
from pathlib import Path
from typing import Optional


MIN_TRADES = 10
DEFAULT_SIMULATIONS = 2000
DEFAULT_N_TRADES    = 100


@dataclass
class MonteCarloResult:
    n_real_trades:    int
    n_simulations:    int
    n_trades:         int

    # Drawdown distributie
    dd_p5:   float   # 5e percentiel max drawdown
    dd_p25:  float
    dd_p50:  float   # mediaan
    dd_p75:  float
    dd_p95:  float   # worst-case (95%)

    # Return distributie
    ret_p5:  float
    ret_p50: float
    ret_p95: float

    # Risico metrics
    prob_blow_up:    float   # kans op >15% drawdown
    prob_drawdown10: float   # kans op >10% drawdown
    prob_profitable: float   # kans op positief resultaat

    # Basis statistieken van echte trades
    real_win_rate:   float
    real_avg_win:    float
    real_avg_loss:   float
    real_expectancy: float

    def __str__(self) -> str:
        lines = [
            "=" * 50,
            "  MONTE CARLO SIMULATIE",
            "=" * 50,
            f"  Gebaseerd op:    {self.n_real_trades} echte trades",
            f"  Simulaties:      {self.n_simulations:,}× {self.n_trades} trades",
            "",
            "  DRAWDOWN DISTRIBUTIE:",
            f"  Beste 5%:        {self.dd_p5:.1%}",
            f"  Mediaan:         {self.dd_p50:.1%}",
            f"  Slechtste 5%:    {self.dd_p95:.1%}",
            "",
            "  RETURN DISTRIBUTIE:",
            f"  Pessimistisch:   {self.ret_p5:+.1%}",
            f"  Mediaan:         {self.ret_p50:+.1%}",
            f"  Optimistisch:    {self.ret_p95:+.1%}",
            "",
            "  RISICO:",
            f"  Kans >10% DD:    {self.prob_drawdown10:.1%}",
            f"  Kans >15% DD:    {self.prob_blow_up:.1%}",
            f"  Kans winstgevend:{self.prob_profitable:.1%}",
            "",
            "  TRADE STATISTIEKEN:",
            f"  Win rate:        {self.real_win_rate:.1%}",
            f"  Gem. winst:      {self.real_avg_win:+.2%}",
            f"  Gem. verlies:    {self.real_avg_loss:+.2%}",
            f"  Expectancy:      {self.real_expectancy:+.4f}",
            "=" * 50,
        ]
        return "\n".join(lines)

    def to_dict(self) -> dict:
        return {
            "n_real_trades":    self.n_real_trades,
            "n_simulations":    self.n_simulations,
            "n_trades":         self.n_trades,
            "dd_p5":            round(self.dd_p5, 4),
            "dd_p25":           round(self.dd_p25, 4),
            "dd_p50":           round(self.dd_p50, 4),
            "dd_p75":           round(self.dd_p75, 4),
            "dd_p95":           round(self.dd_p95, 4),
            "ret_p5":           round(self.ret_p5, 4),
            "ret_p50":          round(self.ret_p50, 4),
            "ret_p95":          round(self.ret_p95, 4),
            "prob_blow_up":     round(self.prob_blow_up, 4),
            "prob_drawdown10":  round(self.prob_drawdown10, 4),
            "prob_profitable":  round(self.prob_profitable, 4),
            "real_win_rate":    round(self.real_win_rate, 4),
            "real_avg_win":     round(self.real_avg_win, 4),
            "real_avg_loss":    round(self.real_avg_loss, 4),
            "real_expectancy":  round(self.real_expectancy, 6),
        }


class MonteCarloSimulator:
    def __init__(self, trades_path: str = "logs/trades.json"):
        self.trades_path = Path(trades_path)

    def _load_pnls(self) -> list[float]:
        if not self.trades_path.exists():
            return []
        try:
            trades = json.loads(self.trades_path.read_text(encoding="utf-8"))
        except Exception:
            return []
        return [
            float(t["pnl_pct"])
            for t in trades
            if t.get("type") in ("sell", "cover", "partial_tp1", "partial_tp2")
            and "pnl_pct" in t
        ]

    def run(
        self,
        n_simulations: int = DEFAULT_SIMULATIONS,
        n_trades:       int = DEFAULT_N_TRADES,
        blow_up_dd:     float = 0.15,
        seed:           Optional[int] = 42,
    ) -> Optional[MonteCarloResult]:
        pnls = self._load_pnls()
        if len(pnls) < MIN_TRADES:
            return None

        rng    = np.random.default_rng(seed)
        pnls_a = np.array(pnls)

        # Basis statistieken echte trades
        wins   = pnls_a[pnls_a > 0]
        losses = pnls_a[pnls_a < 0]
        win_rate    = len(wins) / len(pnls_a)
        avg_win     = float(np.mean(wins))  if len(wins)   > 0 else 0.0
        avg_loss    = float(np.mean(losses)) if len(losses) > 0 else 0.0
        expectancy  = win_rate * avg_win + (1 - win_rate) * avg_loss

        # Monte Carlo: sample met replacement
        samples = rng.choice(pnls_a, size=(n_simulations, n_trades), replace=True)

        # Equity curves: multiplicatief (compounding)
        equity = np.cumprod(1 + samples, axis=1)   # shape: (n_sim, n_trades)
        equity = np.hstack([np.ones((n_simulations, 1)), equity])

        # Max drawdown per simulatie
        rolling_max = np.maximum.accumulate(equity, axis=1)
        drawdowns   = (rolling_max - equity) / (rolling_max + 1e-8)
        max_dd      = drawdowns.max(axis=1)

        # Eindrendement per simulatie
        final_ret = equity[:, -1] - 1.0

        # Distributies
        dd_pcts = np.percentile(max_dd,    [5, 25, 50, 75, 95])
        ret_pcts = np.percentile(final_ret, [5, 50, 95])

        return MonteCarloResult(
            n_real_trades    = len(pnls),
            n_simulations    = n_simulations,
            n_trades         = n_trades,
            dd_p5            = float(dd_pcts[0]),
            dd_p25           = float(dd_pcts[1]),
            dd_p50           = float(dd_pcts[2]),
            dd_p75           = float(dd_pcts[3]),
            dd_p95           = float(dd_pcts[4]),
            ret_p5           = float(ret_pcts[0]),
            ret_p50          = float(ret_pcts[1]),
            ret_p95          = float(ret_pcts[2]),
            prob_blow_up     = float(np.mean(max_dd > blow_up_dd)),
            prob_drawdown10  = float(np.mean(max_dd > 0.10)),
            prob_profitable  = float(np.mean(final_ret > 0)),
            real_win_rate    = win_rate,
            real_avg_win     = avg_win,
            real_avg_loss    = avg_loss,
            real_expectancy  = expectancy,
        )

    def report(self, **kwargs) -> str:
        result = self.run(**kwargs)
        if result is None:
            return f"Onvoldoende data: minimaal {MIN_TRADES} closed trades nodig."
        return str(result)
