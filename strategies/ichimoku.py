"""
Ichimoku Cloud — Japanse technische analyse gebruikt door professionele traders.

Componenten:
  Tenkan-sen  (9):  korte termijn momentum
  Kijun-sen   (26): middellange termijn trend
  Senkou A    (26): voorste wolk lijn A
  Senkou B    (52): voorste wolk lijn B
  Chikou Span (26): momentum bevestiging
"""
import pandas as pd
import numpy as np
from dataclasses import dataclass


@dataclass
class IchimokuSignal:
    action: int
    confidence: float
    reason: str
    above_cloud: bool
    cloud_thickness: float


class IchimokuStrategy:
    def __init__(self, tenkan: int = 9, kijun: int = 26, senkou_b: int = 52):
        self.tenkan = tenkan
        self.kijun = kijun
        self.senkou_b = senkou_b

    def signal(self, df: pd.DataFrame) -> IchimokuSignal:
        if len(df) < self.senkou_b + self.kijun + 5:
            return IchimokuSignal(0, 0.0, "te weinig data", False, 0.0)

        high = df["high"]
        low  = df["low"]
        close = df["close"]

        # Berekeningen
        tenkan = self._midpoint(high, low, self.tenkan)
        kijun  = self._midpoint(high, low, self.kijun)
        senkou_a = ((tenkan + kijun) / 2).shift(self.kijun)
        senkou_b = self._midpoint(high, low, self.senkou_b).shift(self.kijun)
        chikou  = close.shift(-self.kijun)

        # Huidige waarden
        price    = close.iloc[-1]
        t        = tenkan.iloc[-1]
        k        = kijun.iloc[-1]
        sa       = senkou_a.iloc[-1]
        sb       = senkou_b.iloc[-1]
        cloud_top = max(sa, sb)
        cloud_bot = min(sa, sb)

        if any(pd.isna([t, k, sa, sb])):
            return IchimokuSignal(0, 0.0, "berekening mislukt", False, 0.0)

        above_cloud = price > cloud_top
        below_cloud = price < cloud_bot
        in_cloud    = cloud_bot <= price <= cloud_top
        cloud_thick = abs(sa - sb) / price

        bullish_signals = 0
        bearish_signals = 0

        # TK Cross
        if t > k:
            bullish_signals += 1
        else:
            bearish_signals += 1

        # Prijs vs cloud
        if above_cloud:
            bullish_signals += 2
        elif below_cloud:
            bearish_signals += 2

        # Kleur van de wolk (toekomst)
        future_sa = senkou_a.iloc[-self.kijun // 2] if len(senkou_a) > self.kijun // 2 else sa
        future_sb = senkou_b.iloc[-self.kijun // 2] if len(senkou_b) > self.kijun // 2 else sb
        if not pd.isna(future_sa) and not pd.isna(future_sb):
            if future_sa > future_sb:
                bullish_signals += 1
            else:
                bearish_signals += 1

        # TK cross boven de wolk = sterk signaal
        if t > k and above_cloud:
            return IchimokuSignal(1, 0.80, f"Bullish TK cross boven wolk — prijs={price:.2f}", True, cloud_thick)
        if t < k and below_cloud:
            return IchimokuSignal(-1, 0.80, f"Bearish TK cross onder wolk — prijs={price:.2f}", False, cloud_thick)

        # Zwakkere signalen
        if bullish_signals > bearish_signals + 1:
            conf = min(bullish_signals / 5, 0.65)
            return IchimokuSignal(1, conf, f"Ichimoku bullish ({bullish_signals} signalen)", above_cloud, cloud_thick)
        if bearish_signals > bullish_signals + 1:
            conf = min(bearish_signals / 5, 0.65)
            return IchimokuSignal(-1, conf, f"Ichimoku bearish ({bearish_signals} signalen)", False, cloud_thick)

        return IchimokuSignal(0, 0.1, "Ichimoku neutraal / in de wolk", above_cloud, cloud_thick)

    def _midpoint(self, high: pd.Series, low: pd.Series, period: int) -> pd.Series:
        return (high.rolling(period).max() + low.rolling(period).min()) / 2
