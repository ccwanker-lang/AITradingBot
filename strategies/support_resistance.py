"""
Automatische Support & Resistance detectie.
Vindt swing highs/lows en clustert ze tot zones.
"""
import numpy as np
import pandas as pd
from dataclasses import dataclass


@dataclass
class SRSignal:
    action: int
    confidence: float
    reason: str
    nearest_support: float
    nearest_resistance: float


class SupportResistanceStrategy:
    def __init__(self, lookback: int = 500, zone_pct: float = 0.005, min_touches: int = 3):
        self.lookback = lookback
        self.zone_pct = zone_pct          # Levels binnen 0.5% worden samengevoegd
        self.min_touches = min_touches    # Minimaal 2 aanrakingen voor een geldig level

    def signal(self, df: pd.DataFrame) -> SRSignal:
        if len(df) < self.lookback:
            return SRSignal(0, 0.0, "te weinig data", 0.0, 0.0)

        recent = df.iloc[-self.lookback:]
        current = float(df["close"].iloc[-1])
        atr = float(df["atr_14"].iloc[-1]) if "atr_14" in df.columns else current * 0.02

        levels = self._find_levels(recent)
        if not levels:
            return SRSignal(0, 0.0, "geen S/R levels", current, current)

        supports    = sorted([l for l in levels if l < current], reverse=True)
        resistances = sorted([l for l in levels if l > current])

        nearest_sup = supports[0]    if supports    else current * 0.97
        nearest_res = resistances[0] if resistances else current * 1.03

        dist_to_sup = (current - nearest_sup) / current
        dist_to_res = (nearest_res - current) / current

        # Dicht bij support = koopkans
        if dist_to_sup < 0.008 and dist_to_res > dist_to_sup * 2:
            conf = min((0.01 - dist_to_sup) / 0.01, 1.0) * 0.85
            return SRSignal(1, conf,
                f"Prijs bij support {nearest_sup:.2f} ({dist_to_sup:.1%} weg)",
                nearest_sup, nearest_res)

        # Dicht bij resistance = verkoopkans
        if dist_to_res < 0.008 and dist_to_sup > dist_to_res * 2:
            conf = min((0.01 - dist_to_res) / 0.01, 1.0) * 0.85
            return SRSignal(-1, conf,
                f"Prijs bij resistance {nearest_res:.2f} ({dist_to_res:.1%} weg)",
                nearest_sup, nearest_res)

        return SRSignal(0, 0.1, f"S={nearest_sup:.2f} R={nearest_res:.2f}",
                        nearest_sup, nearest_res)

    def _find_levels(self, df: pd.DataFrame) -> list[float]:
        highs = df["high"].values
        lows  = df["low"].values
        levels = []

        # Swing highs
        for i in range(2, len(highs) - 2):
            if highs[i] == max(highs[i-2:i+3]):
                levels.append(highs[i])

        # Swing lows
        for i in range(2, len(lows) - 2):
            if lows[i] == min(lows[i-2:i+3]):
                levels.append(lows[i])

        return self._cluster(sorted(levels))

    def _cluster(self, levels: list[float]) -> list[float]:
        if not levels:
            return []
        clusters = []
        group = [levels[0]]

        for lvl in levels[1:]:
            if (lvl - group[0]) / group[0] < self.zone_pct:
                group.append(lvl)
            else:
                if len(group) >= self.min_touches:
                    clusters.append(float(np.mean(group)))
                group = [lvl]

        if len(group) >= self.min_touches:
            clusters.append(float(np.mean(group)))

        return clusters
