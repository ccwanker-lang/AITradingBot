"""
Wyckoff Methode — detecteert hoe grote spelers (banken/fondsen) de markt manipuleren.

Fases:
  Accumulation  — grote spelers kopen stilletjes op (voordat prijs stijgt)
  Distribution  — grote spelers verkopen stilletjes (voordat prijs daalt)
  Spring        — prijs doorbreekt support even om stops te raken, dan keert terug
  Upthrust      — prijs doorbreekt resistance even, dan keert terug omlaag
  SOS           — Sign of Strength: bevestiging van bullish move
  SOW           — Sign of Weakness: bevestiging van bearish move
"""
import numpy as np
import pandas as pd
from dataclasses import dataclass
from enum import Enum


class WyckoffPhase(str, Enum):
    ACCUMULATION = "accumulatie"
    DISTRIBUTION = "distributie"
    SPRING       = "spring"
    UPTHRUST     = "upthrust"
    MARKUP       = "markup"
    MARKDOWN     = "markdown"
    NEUTRAL      = "neutraal"


@dataclass
class WyckoffSignal:
    action: int
    confidence: float
    phase: WyckoffPhase
    reason: str


class WyckoffStrategy:
    def __init__(self, lookback: int = 200):
        self.lookback = lookback

    def signal(self, df: pd.DataFrame) -> WyckoffSignal:
        if len(df) < self.lookback:
            return WyckoffSignal(0, 0.0, WyckoffPhase.NEUTRAL, "te weinig data")

        recent = df.iloc[-self.lookback:]
        close  = recent["close"]
        volume = recent["volume"]
        high   = recent["high"]
        low    = recent["low"]

        vol_mean = volume.mean()
        price_range = close.max() - close.min()
        current = close.iloc[-1]

        # ── Spring detectie ────────────────────────────────────────
        # Prijs doorbreekt support + keert snel terug met hoog volume
        support = low.iloc[:-5].min()
        if (low.iloc[-3:].min() < support * 0.998 and
                close.iloc[-1] > support and
                volume.iloc[-3:].mean() > vol_mean * 1.8):
            return WyckoffSignal(1, 0.88, WyckoffPhase.SPRING,
                f"Spring gedetecteerd — prijs testte {support:.2f} en keert terug")

        # ── Upthrust detectie ──────────────────────────────────────
        resistance = high.iloc[:-5].max()
        if (high.iloc[-3:].max() > resistance * 1.002 and
                close.iloc[-1] < resistance and
                volume.iloc[-3:].mean() > vol_mean * 1.8):
            return WyckoffSignal(-1, 0.88, WyckoffPhase.UPTHRUST,
                f"Upthrust gedetecteerd — prijs testte {resistance:.2f} en keert terug")

        # ── Accumulatie detectie ───────────────────────────────────
        # Lage volatiliteit + afnemend volume + prijs in ONDERSTE helft van range
        price_vol = close.pct_change().std()
        recent_vol_trend = volume.iloc[-10:].mean() / volume.iloc[-30:-10].mean()
        in_trading_range = price_range / current < 0.08
        range_midpoint = (close.max() + close.min()) / 2

        if (in_trading_range and price_vol < 0.015 and
                recent_vol_trend < 0.85 and current > close.min() * 1.01
                and current <= range_midpoint):  # Prijs in onderste helft — échte accumulatie
            return WyckoffSignal(1, 0.65, WyckoffPhase.ACCUMULATION,
                "Accumulatie — lage vol, prijs consolideert boven steun")

        # ── Distributie detectie ───────────────────────────────────
        # Prijs moet in BOVENSTE helft van range zijn — anders is het geen distributie
        if (in_trading_range and price_vol < 0.015 and
                recent_vol_trend < 0.85 and current < close.max() * 0.99
                and current >= range_midpoint):  # Prijs in bovenste helft — échte distributie
            return WyckoffSignal(-1, 0.65, WyckoffPhase.DISTRIBUTION,
                "Distributie — lage vol, prijs consolideert onder weerstand")

        # ── Sign of Strength (SOS) ─────────────────────────────────
        recent_5 = close.iloc[-5:]
        if (recent_5.is_monotonic_increasing and
                volume.iloc[-5:].mean() > vol_mean * 1.5 and
                current > close.iloc[-self.lookback // 2:].mean()):
            return WyckoffSignal(1, 0.75, WyckoffPhase.MARKUP,
                "Sign of Strength — stijging met hoog volume")

        # ── Sign of Weakness (SOW) ─────────────────────────────────
        if (recent_5.is_monotonic_decreasing and
                volume.iloc[-5:].mean() > vol_mean * 1.5 and
                current < close.iloc[-self.lookback // 2:].mean()):
            return WyckoffSignal(-1, 0.75, WyckoffPhase.MARKDOWN,
                "Sign of Weakness — daling met hoog volume")

        return WyckoffSignal(0, 0.1, WyckoffPhase.NEUTRAL, "Geen duidelijke Wyckoff fase")
