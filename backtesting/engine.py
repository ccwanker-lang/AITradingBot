"""
Backtesting engine — test strategieën op historische data.
Berekent: Sharpe, Sortino, Max Drawdown, Win Rate, Profit Factor, Calmar ratio.
"""
import numpy as np
import pandas as pd
from dataclasses import dataclass
from typing import Callable


@dataclass
class BacktestResult:
    total_return: float
    annualized_return: float
    sharpe_ratio: float
    sortino_ratio: float
    max_drawdown: float
    calmar_ratio: float
    win_rate: float
    profit_factor: float
    total_trades: int
    avg_holding_candles: float
    equity_curve: list[float]
    trades: list[dict]

    def __str__(self) -> str:
        return (
            f"\n{'='*50}\n"
            f"  BACKTEST RESULTATEN\n"
            f"{'='*50}\n"
            f"  Totaal rendement:   {self.total_return:+.2%}\n"
            f"  Jaarlijks rendement:{self.annualized_return:+.2%}\n"
            f"  Sharpe ratio:       {self.sharpe_ratio:.2f}\n"
            f"  Sortino ratio:      {self.sortino_ratio:.2f}\n"
            f"  Max drawdown:       {self.max_drawdown:.2%}\n"
            f"  Calmar ratio:       {self.calmar_ratio:.2f}\n"
            f"  Win rate:           {self.win_rate:.1%}\n"
            f"  Profit factor:      {self.profit_factor:.2f}\n"
            f"  Aantal trades:      {self.total_trades}\n"
            f"  Gem. houdduur:      {self.avg_holding_candles:.1f} kaarsen\n"
            f"{'='*50}"
        )


class BacktestEngine:
    def __init__(self, initial_capital: float = 1000.0, fee_rate: float = 0.001,
                 atr_sl_mult: float = 2.0, atr_tp_mult: float = 4.0):
        self.initial_capital = initial_capital
        self.fee_rate = fee_rate
        self.atr_sl_mult = atr_sl_mult
        self.atr_tp_mult = atr_tp_mult

    def run(self, df: pd.DataFrame, signal_fn: Callable[[pd.DataFrame], dict]) -> BacktestResult:
        """
        signal_fn: functie die een df slice aanneemt en een dict teruggeeft
                   met 'actie' (+1/-1/0) en 'confidence' (0-1).
        """
        capital = self.initial_capital
        position = 0.0
        entry_price = 0.0
        entry_step = 0
        stop_loss = 0.0
        take_profit = 0.0
        peak_price = 0.0

        equity = [capital]
        trades = []
        min_window = 60  # Minimale history voor features

        for i in range(min_window, len(df)):
            slice_df = df.iloc[:i]
            current_price = float(df["close"].iloc[i])
            atr = float(df.get("atr_14", pd.Series([current_price * 0.02] * len(df))).iloc[i])

            # ── SL/TP check voor open positie ──────────────────────
            if position > 0:
                if current_price > peak_price:
                    peak_price = current_price

                close_reason = None
                if current_price <= stop_loss:
                    close_reason = "stop_loss"
                elif current_price >= take_profit:
                    close_reason = "take_profit"
                else:
                    trail = peak_price * 0.95
                    if current_price <= trail and current_price > entry_price:
                        close_reason = "trailing_stop"

                if close_reason:
                    proceeds = position * current_price * (1 - self.fee_rate)
                    pnl = proceeds - position * entry_price
                    pnl_pct = pnl / (position * entry_price + 1e-8)
                    capital += proceeds
                    trades.append({
                        "entry": entry_price, "exit": current_price,
                        "pnl_pct": pnl_pct, "holding": i - entry_step,
                        "reason": close_reason,
                    })
                    position = 0.0
                    equity.append(capital)
                    continue

            # ── Strategie signaal ──────────────────────────────────
            try:
                sig = signal_fn(slice_df)
                action = sig.get("actie", 0)
                confidence = sig.get("confidence", 0.0)
            except Exception:
                equity.append(capital + position * current_price)
                continue

            # ── Buy ────────────────────────────────────────────────
            if action == 1 and position == 0 and confidence > 0.25:
                invest = capital * min(0.90 * confidence, 0.90)
                fee = invest * self.fee_rate
                position = (invest - fee) / current_price
                capital -= invest
                entry_price = current_price
                entry_step = i
                peak_price = current_price
                stop_loss = current_price - atr * self.atr_sl_mult
                take_profit = current_price + atr * self.atr_tp_mult

            # ── Sell (signaal) ────────────────────────────────────
            elif action == -1 and position > 0:
                proceeds = position * current_price * (1 - self.fee_rate)
                pnl = proceeds - position * entry_price
                pnl_pct = pnl / (position * entry_price + 1e-8)
                capital += proceeds
                trades.append({
                    "entry": entry_price, "exit": current_price,
                    "pnl_pct": pnl_pct, "holding": i - entry_step,
                    "reason": "signaal",
                })
                position = 0.0

            equity.append(capital + position * current_price)

        # ── Metriek berekening ─────────────────────────────────────
        eq = np.array(equity)
        returns = np.diff(eq) / (eq[:-1] + 1e-8)
        total_return = (eq[-1] - eq[0]) / eq[0]

        n_years = len(df) / (365 * 24) if len(df) > 0 else 1
        annualized = (1 + total_return) ** (1 / max(n_years, 0.01)) - 1

        sharpe = (np.mean(returns) / (np.std(returns) + 1e-8)) * np.sqrt(8760)
        downside = np.sqrt(np.mean(np.minimum(returns, 0) ** 2) + 1e-8)
        sortino = (np.mean(returns) / downside) * np.sqrt(8760)

        # Max drawdown
        peak = np.maximum.accumulate(eq)
        drawdowns = (peak - eq) / (peak + 1e-8)
        max_dd = float(drawdowns.max())

        calmar = annualized / (max_dd + 1e-8)

        # Trade statistieken
        pnls = [t["pnl_pct"] for t in trades] if trades else [0]
        wins = [p for p in pnls if p > 0]
        losses = [p for p in pnls if p < 0]
        win_rate = len(wins) / len(pnls) if pnls else 0
        profit_factor = abs(sum(wins) / sum(losses)) if losses else float("inf")
        avg_hold = float(np.mean([t["holding"] for t in trades])) if trades else 0

        return BacktestResult(
            total_return=total_return,
            annualized_return=annualized,
            sharpe_ratio=float(sharpe),
            sortino_ratio=float(sortino),
            max_drawdown=max_dd,
            calmar_ratio=float(calmar),
            win_rate=win_rate,
            profit_factor=profit_factor,
            total_trades=len(trades),
            avg_holding_candles=avg_hold,
            equity_curve=eq.tolist(),
            trades=trades,
        )
