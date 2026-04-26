"""
Marktstructuur analyse — Higher Highs/Lows en Break of Structure detectie.
Fundament van price action trading gebruikt door alle professionele traders.

Patronen:
  HH + HL = Bullish structuur → koop op pullbacks
  LH + LL = Bearish structuur → short op rallies
  BOS      = Break of Structure → trendverandering signaal
  CHoCH    = Change of Character → vroeg trendkeerder signaal
"""
import numpy as np
import pandas as pd
from dataclasses import dataclass
from enum import Enum


class StructureType(str, Enum):
    BULLISH  = "bullish"
    BEARISH  = "bearish"
    NEUTRAL  = "neutraal"
    BOS_BULL = "bos_bullish"   # Break of Structure omhoog
    BOS_BEAR = "bos_bearish"   # Break of Structure omlaag
    CHOCH    = "choch"          # Change of Character


@dataclass
class MarketStructureSignal:
    action: int
    confidence: float
    structure: StructureType
    reason: str


class MarketStructureStrategy:
    def __init__(self, swing_lookback: int = 5, structure_lookback: int = 30):
        self.swing_lookback = swing_lookback
        self.structure_lookback = structure_lookback

    def signal(self, df: pd.DataFrame) -> MarketStructureSignal:
        if len(df) < self.structure_lookback + self.swing_lookback * 2:
            return MarketStructureSignal(0, 0.0, StructureType.NEUTRAL, "te weinig data")

        highs, lows = self._find_swings(df)
        if len(highs) < 3 or len(lows) < 3:
            return MarketStructureSignal(0, 0.1, StructureType.NEUTRAL, "te weinig swing punten")

        current = float(df["close"].iloc[-1])

        # ── Break of Structure check ───────────────────────────────
        last_high = highs[-1]
        last_low  = lows[-1]
        prev_high = highs[-2]
        prev_low  = lows[-2]

        # Bullish BOS: prijs breekt boven vorig swing high
        if current > prev_high and last_low > lows[-3]:
            return MarketStructureSignal(1, 0.85, StructureType.BOS_BULL,
                f"Bullish BOS — prijs brak boven {prev_high:.2f}")

        # Bearish BOS: prijs breekt onder vorig swing low
        if current < prev_low and last_high < highs[-3]:
            return MarketStructureSignal(-1, 0.85, StructureType.BOS_BEAR,
                f"Bearish BOS — prijs brak onder {prev_low:.2f}")

        # ── Change of Character ────────────────────────────────────
        # Bearish structuur maar eerste HH — vroeg keersignaal
        if (highs[-1] > highs[-2] and lows[-1] < lows[-2] and
                highs[-3] < highs[-2]):  # Was bearish
            return MarketStructureSignal(1, 0.70, StructureType.CHOCH,
                "CHoCH — eerste Higher High na bearish structuur")

        # ── Structuur bepalen ──────────────────────────────────────
        hh = highs[-1] > highs[-2] > highs[-3]  # Higher Highs
        hl = lows[-1]  > lows[-2]  > lows[-3]   # Higher Lows
        lh = highs[-1] < highs[-2] < highs[-3]  # Lower Highs
        ll = lows[-1]  < lows[-2]  < lows[-3]   # Lower Lows

        if hh and hl:
            # Bullish — koop op pullback naar HL zone
            hl_zone = lows[-1]
            if current <= hl_zone * 1.015:
                return MarketStructureSignal(1, 0.78, StructureType.BULLISH,
                    f"HH+HL structuur — pullback naar HL zone {hl_zone:.2f}")
            return MarketStructureSignal(1, 0.55, StructureType.BULLISH,
                "HH+HL bullish structuur bevestigd")

        if lh and ll:
            # Bearish — short op rally naar LH zone
            lh_zone = highs[-1]
            if current >= lh_zone * 0.985:
                return MarketStructureSignal(-1, 0.78, StructureType.BEARISH,
                    f"LH+LL structuur — rally naar LH zone {lh_zone:.2f}")
            return MarketStructureSignal(-1, 0.55, StructureType.BEARISH,
                "LH+LL bearish structuur bevestigd")

        return MarketStructureSignal(0, 0.1, StructureType.NEUTRAL,
            "Geen duidelijke marktstructuur")

    def _find_swings(self, df: pd.DataFrame) -> tuple[list, list]:
        n = self.swing_lookback
        highs, lows = [], []
        recent = df.iloc[-self.structure_lookback:]

        for i in range(n, len(recent) - n):
            h = recent["high"].iloc[i]
            l = recent["low"].iloc[i]
            if h == recent["high"].iloc[i-n:i+n+1].max():
                highs.append(float(h))
            if l == recent["low"].iloc[i-n:i+n+1].min():
                lows.append(float(l))

        return highs, lows
