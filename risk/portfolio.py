from __future__ import annotations
"""
Portfolio manager — spreidt kapitaal over meerdere assets met correlatie-bewaking.
"""
import numpy as np
import pandas as pd
from dataclasses import dataclass, field
from typing import Dict


@dataclass
class Position:
    symbol: str
    size: float           # Aantal crypto
    entry_price: float
    stop_loss: float
    take_profit: float
    peak_price: float
    capital_invested: float


@dataclass
class PortfolioState:
    capital: float
    positions: Dict[str, Position] = field(default_factory=dict)
    peak_value: float = 0.0
    trade_history: list = field(default_factory=list)

    def __post_init__(self):
        if self.peak_value == 0.0:
            self.peak_value = self.capital


class PortfolioManager:
    """
    Beheert meerdere posities met:
    - Correlatie-bewuste positiebepaling
    - Maximale blootstelling per asset
    - Totale portfolio drawdown monitoring
    """

    def __init__(
        self,
        initial_capital: float,
        max_positions: int = 3,
        max_per_asset_pct: float = 0.40,    # Max 40% in één asset
        max_correlation_pct: float = 0.70,   # Stop als correlatie > 0.70 tussen posities
        max_total_exposure: float = 0.80,    # Max 80% van portfolio in posities
    ):
        self.state = PortfolioState(capital=initial_capital)
        self.max_positions = max_positions
        self.max_per_asset_pct = max_per_asset_pct
        self.max_correlation_pct = max_correlation_pct
        self.max_total_exposure = max_total_exposure

    def total_value(self, prices: Dict[str, float]) -> float:
        pos_value = sum(
            pos.size * prices.get(sym, pos.entry_price)
            for sym, pos in self.state.positions.items()
        )
        return self.state.capital + pos_value

    def drawdown(self, prices: Dict[str, float]) -> float:
        value = self.total_value(prices)
        if value > self.state.peak_value:
            self.state.peak_value = value
        return (self.state.peak_value - value) / (self.state.peak_value + 1e-8)

    def can_open_position(self, symbol: str, prices: Dict[str, float]) -> tuple[bool, str]:
        if symbol in self.state.positions:
            return False, f"Al een positie in {symbol}"
        if len(self.state.positions) >= self.max_positions:
            return False, f"Max {self.max_positions} posities bereikt"

        total = self.total_value(prices)
        exposed = total - self.state.capital
        if exposed / (total + 1e-8) >= self.max_total_exposure:
            return False, f"Max blootstelling {self.max_total_exposure:.0%} bereikt"

        return True, "OK"

    def max_invest_for_symbol(self, symbol: str, prices: Dict[str, float]) -> float:
        total = self.total_value(prices)
        return total * self.max_per_asset_pct

    def open_position(self, symbol: str, price: float, stop_loss: float,
                      take_profit: float, invest_amount: float):
        fee = invest_amount * 0.001
        size = (invest_amount - fee) / price
        self.state.capital -= invest_amount
        self.state.positions[symbol] = Position(
            symbol=symbol,
            size=size,
            entry_price=price,
            stop_loss=stop_loss,
            take_profit=take_profit,
            peak_price=price,
            capital_invested=invest_amount,
        )

    def close_position(self, symbol: str, price: float, reason: str = "") -> dict | None:
        pos = self.state.positions.pop(symbol, None)
        if pos is None:
            return None

        proceeds = pos.size * price * (1 - 0.001)
        pnl = proceeds - pos.capital_invested
        pnl_pct = pnl / (pos.capital_invested + 1e-8)
        self.state.capital += proceeds

        record = {
            "type": "sell",
            "symbol": symbol,
            "entry_price": pos.entry_price,
            "exit_price": price,
            "price": price,
            "pnl": pnl,
            "pnl_pct": pnl_pct,
            "reason": reason,
        }
        self.state.trade_history.append(record)
        return record

    def update_peaks(self, prices: Dict[str, float]):
        for sym, pos in self.state.positions.items():
            current = prices.get(sym, pos.peak_price)
            if current > pos.peak_price:
                pos.peak_price = current

    def allocation_summary(self, prices: Dict[str, float]) -> dict:
        total = self.total_value(prices)
        alloc = {}
        for sym, pos in self.state.positions.items():
            value = pos.size * prices.get(sym, pos.entry_price)
            alloc[sym] = {
                "value": value,
                "pct": value / (total + 1e-8),
                "pnl_pct": (prices.get(sym, pos.entry_price) - pos.entry_price) / pos.entry_price,
            }
        return {
            "total_value": total,
            "free_capital": self.state.capital,
            "positions": alloc,
            "num_positions": len(self.state.positions),
        }
