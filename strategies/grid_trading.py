"""
Grid Trading — verdient geld in zijwaartse markten.
Koopt automatisch bij dips en verkoopt bij stijgingen binnen een range.
"""
import numpy as np
import pandas as pd
from dataclasses import dataclass


@dataclass
class GridSignal:
    action: int
    confidence: float
    grid_level: float
    reason: str


class GridTradingStrategy:
    """
    Werkt alleen in RANGING regime.
    Verdeelt de range in niveaus en genereert koop/verkoopsignalen.
    """

    def __init__(self, grid_levels: int = 6, lookback: int = 50):
        self.grid_levels = grid_levels
        self.lookback = lookback
        self._last_buy_level: float | None = None

    def signal(self, df: pd.DataFrame) -> GridSignal:
        if len(df) < self.lookback:
            return GridSignal(0, 0.0, 0.0, "te weinig data")

        recent = df.iloc[-self.lookback:]
        current = float(df["close"].iloc[-1])
        bb_width = df["bb_width"].iloc[-1] if "bb_width" in df.columns else 0.05

        # Grid trading alleen in lage volatiliteit
        if bb_width > 0.06:
            return GridSignal(0, 0.0, current, "te hoge volatiliteit voor grid")

        high = float(recent["high"].max())
        low  = float(recent["low"].min())
        rng  = high - low

        if rng / current < 0.01:  # Range te klein
            return GridSignal(0, 0.0, current, "range te smal")

        # Bereken grid niveaus
        step = rng / self.grid_levels
        levels = [low + i * step for i in range(self.grid_levels + 1)]

        # Vind dichtstbijzijnde grid niveau
        nearest = min(levels, key=lambda l: abs(l - current))
        dist_pct = abs(current - nearest) / current

        if dist_pct > 0.003:
            return GridSignal(0, 0.1, nearest, f"Wacht op grid niveau {nearest:.2f}")

        level_idx = levels.index(nearest)

        # Onderin de range = kopen
        if level_idx <= self.grid_levels // 3:
            conf = 0.55 + (1 - level_idx / self.grid_levels) * 0.25
            self._last_buy_level = nearest
            return GridSignal(1, conf, nearest,
                f"Grid BUY op niveau {level_idx+1}/{self.grid_levels} @ {nearest:.2f}")

        # Boverin de range = verkopen (als we eerder gekocht hebben)
        if level_idx >= self.grid_levels * 2 // 3:
            if self._last_buy_level and nearest > self._last_buy_level * 1.005:
                conf = 0.55 + (level_idx / self.grid_levels) * 0.25
                return GridSignal(-1, conf, nearest,
                    f"Grid SELL op niveau {level_idx+1}/{self.grid_levels} @ {nearest:.2f}")

        return GridSignal(0, 0.1, nearest, f"Grid neutraal @ niveau {level_idx+1}")
