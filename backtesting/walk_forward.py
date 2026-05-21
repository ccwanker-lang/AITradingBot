"""
Walk-Forward Testing — valideert dat strategieparameters niet overfit zijn op
in-sample data. Traint op eerste X% van de data, test op de rest.

Methode:
  - Enkelvoudige split:  train 60%, test 40%
  - Rolling windows:     meerdere train/test vensters verschuiven in de tijd

Minimum vereisten out-of-sample:
  Sharpe  > 1.0
  Sortino > 1.5
  Expectancy > 0 (positieve verwachte waarde)
  Win rate > 40%

Gebruik:
    from backtesting.walk_forward import WalkForwardTester
    tester = WalkForwardTester()
    result = tester.run_single(df, signal_fn)
    print(result)
"""
from __future__ import annotations

import numpy as np
import pandas as pd
from dataclasses import dataclass
from typing import Callable, Optional

from backtesting.engine import BacktestEngine, BacktestResult


TRAIN_RATIO  = 0.60
MIN_ROWS     = 300   # minimum kaarsen voor betrouwbare test
SHARPE_MIN   = 1.0
SORTINO_MIN  = 1.5
WINRATE_MIN  = 0.40
EXP_MIN      = 0.0


@dataclass
class WalkForwardResult:
    # In-sample
    is_return:   float
    is_sharpe:   float
    is_sortino:  float
    is_win_rate: float
    is_trades:   int

    # Out-of-sample
    oos_return:   float
    oos_sharpe:   float
    oos_sortino:  float
    oos_win_rate: float
    oos_trades:   int
    oos_max_dd:   float
    oos_expectancy: float

    # Validatie
    passes_sharpe:   bool
    passes_sortino:  bool
    passes_win_rate: bool
    passes_exp:      bool

    # Metadata
    train_rows: int
    test_rows:  int
    label:      str = ""

    @property
    def passes_all(self) -> bool:
        return (self.passes_sharpe and self.passes_sortino
                and self.passes_win_rate and self.passes_exp)

    def __str__(self) -> str:
        ok  = "OK"
        nok = "FAIL"
        lines = [
            "=" * 54,
            f"  WALK-FORWARD TEST  {self.label}",
            "=" * 54,
            f"  Data split: {self.train_rows} kaarsen train / {self.test_rows} kaarsen test",
            "",
            "  IN-SAMPLE (TRAIN):",
            f"    Return:      {self.is_return:+.2%}",
            f"    Sharpe:      {self.is_sharpe:.2f}",
            f"    Sortino:     {self.is_sortino:.2f}",
            f"    Win rate:    {self.is_win_rate:.1%}",
            f"    Trades:      {self.is_trades}",
            "",
            "  OUT-OF-SAMPLE (TEST):",
            f"    Return:      {self.oos_return:+.2%}",
            f"    Sharpe:      {self.oos_sharpe:.2f}  [{ok if self.passes_sharpe else nok}] (min {SHARPE_MIN})",
            f"    Sortino:     {self.oos_sortino:.2f}  [{ok if self.passes_sortino else nok}] (min {SORTINO_MIN})",
            f"    Win rate:    {self.oos_win_rate:.1%}  [{ok if self.passes_win_rate else nok}] (min {WINRATE_MIN:.0%})",
            f"    Expectancy:  {self.oos_expectancy:+.4f}  [{ok if self.passes_exp else nok}] (min {EXP_MIN})",
            f"    Max DD:      {self.oos_max_dd:.2%}",
            f"    Trades:      {self.oos_trades}",
            "",
            f"  UITKOMST: {'GESLAAGD' if self.passes_all else 'GEZAKT -- strategie mogelijk overfit'}",
            "=" * 54,
        ]
        return "\n".join(lines)

    def to_dict(self) -> dict:
        return {
            "in_sample": {
                "return":   round(self.is_return,   4),
                "sharpe":   round(self.is_sharpe,   3),
                "sortino":  round(self.is_sortino,  3),
                "win_rate": round(self.is_win_rate, 4),
                "trades":   self.is_trades,
            },
            "out_of_sample": {
                "return":     round(self.oos_return,     4),
                "sharpe":     round(self.oos_sharpe,     3),
                "sortino":    round(self.oos_sortino,    3),
                "win_rate":   round(self.oos_win_rate,   4),
                "expectancy": round(self.oos_expectancy, 6),
                "max_dd":     round(self.oos_max_dd,     4),
                "trades":     self.oos_trades,
            },
            "validation": {
                "passes_sharpe":   self.passes_sharpe,
                "passes_sortino":  self.passes_sortino,
                "passes_win_rate": self.passes_win_rate,
                "passes_exp":      self.passes_exp,
                "passes_all":      self.passes_all,
            },
            "train_rows": self.train_rows,
            "test_rows":  self.test_rows,
            "label":      self.label,
        }


@dataclass
class RollingWalkForwardResult:
    windows:     list
    pass_rate:   float
    avg_oos_sharpe:   float
    avg_oos_sortino:  float
    avg_oos_return:   float
    avg_oos_win_rate: float
    robust:      bool

    def __str__(self) -> str:
        lines = [
            "=" * 54,
            "  ROLLING WALK-FORWARD OVERZICHT",
            "=" * 54,
            f"  Vensters:           {len(self.windows)}",
            f"  Geslaagd:           {sum(1 for w in self.windows if w.passes_all)} / {len(self.windows)}",
            f"  Slagingspercentage: {self.pass_rate:.0%}",
            "",
            f"  Gem. OOS Sharpe:    {self.avg_oos_sharpe:.2f}",
            f"  Gem. OOS Sortino:   {self.avg_oos_sortino:.2f}",
            f"  Gem. OOS Return:    {self.avg_oos_return:+.2%}",
            f"  Gem. OOS Win rate:  {self.avg_oos_win_rate:.1%}",
            "",
            f"  ROBUUSTHEID: {'ROBUUST' if self.robust else 'NIET ROBUUST -- overfitting risico'}",
            "=" * 54,
        ]
        for i, w in enumerate(self.windows):
            status = "OK" if w.passes_all else "FAIL"
            lines.append(
                f"  Venster {i+1}: [{status}]  Sharpe={w.oos_sharpe:.2f}  WR={w.oos_win_rate:.0%}"
            )
        return "\n".join(lines)


class WalkForwardTester:
    def __init__(
        self,
        train_ratio:     float = TRAIN_RATIO,
        initial_capital: float = 1000.0,
        atr_sl_mult:     float = 2.0,
        atr_tp_mult:     float = 4.0,
    ):
        self.train_ratio = train_ratio
        self.engine = BacktestEngine(
            initial_capital=initial_capital,
            atr_sl_mult=atr_sl_mult,
            atr_tp_mult=atr_tp_mult,
        )

    def run_single(
        self,
        df: pd.DataFrame,
        signal_fn: Callable[[pd.DataFrame], dict],
        label: str = "",
    ) -> Optional[WalkForwardResult]:
        if len(df) < MIN_ROWS:
            return None

        split    = int(len(df) * self.train_ratio)
        df_train = df.iloc[:split].copy()
        df_test  = df.iloc[split:].copy()

        is_result  = self.engine.run(df_train, signal_fn)
        oos_result = self.engine.run(df_test,  signal_fn)
        oos_exp    = self._expectancy(oos_result)

        return WalkForwardResult(
            is_return    = is_result.total_return,
            is_sharpe    = is_result.sharpe_ratio,
            is_sortino   = is_result.sortino_ratio,
            is_win_rate  = is_result.win_rate,
            is_trades    = is_result.total_trades,
            oos_return   = oos_result.total_return,
            oos_sharpe   = oos_result.sharpe_ratio,
            oos_sortino  = oos_result.sortino_ratio,
            oos_win_rate = oos_result.win_rate,
            oos_trades   = oos_result.total_trades,
            oos_max_dd   = oos_result.max_drawdown,
            oos_expectancy = oos_exp,
            passes_sharpe   = oos_result.sharpe_ratio   >= SHARPE_MIN,
            passes_sortino  = oos_result.sortino_ratio  >= SORTINO_MIN,
            passes_win_rate = oos_result.win_rate        >= WINRATE_MIN,
            passes_exp      = oos_exp                   >  EXP_MIN,
            train_rows      = len(df_train),
            test_rows       = len(df_test),
            label           = label,
        )

    def run_rolling(
        self,
        df: pd.DataFrame,
        signal_fn: Callable[[pd.DataFrame], dict],
        n_windows: int = 5,
    ) -> Optional[RollingWalkForwardResult]:
        """
        Schuift train/test venster n_windows keer over de data.
        """
        if len(df) < MIN_ROWS * 2:
            return None

        window_size = len(df) // n_windows
        results = []

        for i in range(n_windows):
            start = i * window_size
            end   = min(start + window_size * 2, len(df))
            chunk = df.iloc[start:end]
            if len(chunk) < MIN_ROWS:
                continue
            label = f"venster {i+1} ({start}..{end})"
            r = self.run_single(chunk, signal_fn, label=label)
            if r:
                results.append(r)

        if not results:
            return None

        pass_rate = sum(1 for r in results if r.passes_all) / len(results)
        return RollingWalkForwardResult(
            windows          = results,
            pass_rate        = pass_rate,
            avg_oos_sharpe   = float(np.mean([r.oos_sharpe   for r in results])),
            avg_oos_sortino  = float(np.mean([r.oos_sortino  for r in results])),
            avg_oos_return   = float(np.mean([r.oos_return   for r in results])),
            avg_oos_win_rate = float(np.mean([r.oos_win_rate for r in results])),
            robust           = pass_rate >= 0.60,
        )

    @staticmethod
    def _expectancy(result: BacktestResult) -> float:
        trades = result.trades
        if not trades:
            return 0.0
        pnls   = [t["pnl_pct"] for t in trades]
        wins   = [p for p in pnls if p > 0]
        losses = [p for p in pnls if p < 0]
        wr     = len(wins) / len(pnls)
        avg_w  = float(np.mean(wins))   if wins   else 0.0
        avg_l  = float(np.mean(losses)) if losses else 0.0
        return wr * avg_w + (1 - wr) * avg_l
