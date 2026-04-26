"""
Smart Money Concepts (SMC) — ziet waar banken en instituten handelen.

Concepten:
  Order Blocks   — laatste bearish/bullish kaars voor een grote move
  Fair Value Gaps (FVG) — gaten in de prijs die opgevuld worden
  Liquidity Sweeps — prijs doorbreekt key level kort dan keert terug
"""
import numpy as np
import pandas as pd
from dataclasses import dataclass


@dataclass
class SMCSignal:
    action: int        # +1 buy, -1 sell, 0 hold
    confidence: float
    reason: str
    level: float       # Prijs niveau van het patroon


class SmartMoneyStrategy:
    def __init__(self, lookback: int = 50, fvg_min_size: float = 0.002):
        self.lookback = lookback
        self.fvg_min_size = fvg_min_size  # Minimale FVG grootte (0.2%)

    def signal(self, df: pd.DataFrame) -> SMCSignal:
        if len(df) < self.lookback + 5:
            return SMCSignal(0, 0.0, "te weinig data", 0.0)

        signals = []

        ob = self._check_order_block(df)
        if ob.action != 0:
            signals.append(ob)

        fvg = self._check_fvg(df)
        if fvg.action != 0:
            signals.append(fvg)

        liq = self._check_liquidity_sweep(df)
        if liq.action != 0:
            signals.append(liq)

        if not signals:
            return SMCSignal(0, 0.0, "geen SMC patroon", df["close"].iloc[-1])

        # Sterkste signaal teruggeven
        best = max(signals, key=lambda s: s.confidence)
        return best

    def _check_order_block(self, df: pd.DataFrame) -> SMCSignal:
        """
        Bullish Order Block: laatste bearish kaars voor sterke stijging.
        Bearish Order Block: laatste bullish kaars voor sterke daling.
        """
        close = df["close"]
        high  = df["high"]
        low   = df["low"]
        opens = df["open"]
        current = close.iloc[-1]

        # Zoek sterke moves in de laatste lookback kaarsen
        for i in range(len(df) - 5, max(len(df) - self.lookback, 5), -1):
            # Move na kaars i
            move = (close.iloc[i + 3] - close.iloc[i]) / close.iloc[i]

            if move > 0.02:  # Sterke stijging (2%+)
                # Order block = laatste bearish kaars voor de stijging
                if opens.iloc[i] > close.iloc[i]:  # Bearish kaars
                    ob_top = opens.iloc[i]
                    ob_bottom = close.iloc[i]
                    # Huidige prijs in order block zone?
                    if ob_bottom <= current <= ob_top:
                        conf = min(abs(move) * 10, 0.85)
                        return SMCSignal(1, conf, f"Bullish OB zone {ob_bottom:.2f}-{ob_top:.2f}", ob_bottom)

            elif move < -0.02:  # Sterke daling
                if opens.iloc[i] < close.iloc[i]:  # Bullish kaars
                    ob_top = close.iloc[i]
                    ob_bottom = opens.iloc[i]
                    if ob_bottom <= current <= ob_top:
                        conf = min(abs(move) * 10, 0.85)
                        return SMCSignal(-1, conf, f"Bearish OB zone {ob_bottom:.2f}-{ob_top:.2f}", ob_top)

        return SMCSignal(0, 0.0, "", 0.0)

    def _check_fvg(self, df: pd.DataFrame) -> SMCSignal:
        """
        Fair Value Gap: gat tussen kaars 1 high en kaars 3 low (bullish FVG).
        Prijs keert vaak terug om de gap te vullen.
        """
        current = df["close"].iloc[-1]

        for i in range(len(df) - 4, max(len(df) - 20, 2), -1):
            h1 = df["high"].iloc[i - 1]
            l3 = df["low"].iloc[i + 1]
            h3 = df["high"].iloc[i + 1]
            l1 = df["low"].iloc[i - 1]

            # Bullish FVG: gap omhoog (kaars 1 high < kaars 3 low)
            if l3 > h1 and (l3 - h1) / h1 > self.fvg_min_size:
                if h1 <= current <= l3:  # Prijs vult de gap
                    conf = min((l3 - h1) / h1 * 50, 0.80)
                    return SMCSignal(1, conf, f"Bullish FVG {h1:.2f}-{l3:.2f} wordt gevuld", h1)

            # Bearish FVG: gap omlaag
            if h3 < l1 and (l1 - h3) / l1 > self.fvg_min_size:
                if h3 <= current <= l1:
                    conf = min((l1 - h3) / l1 * 50, 0.80)
                    return SMCSignal(-1, conf, f"Bearish FVG {h3:.2f}-{l1:.2f} wordt gevuld", l1)

        return SMCSignal(0, 0.0, "", 0.0)

    def _check_liquidity_sweep(self, df: pd.DataFrame) -> SMCSignal:
        """
        Liquidity sweep: prijs doorbreekt even een key level dan keert snel terug.
        Instituties laten kleinere traders stoppen, dan gaan ze de andere kant op.
        """
        recent = df.iloc[-20:]
        current = df["close"].iloc[-1]
        prev_high = recent["high"].iloc[:-3].max()
        prev_low  = recent["low"].iloc[:-3].min()

        last_high = df["high"].iloc[-1]
        last_low  = df["low"].iloc[-1]
        last_close = df["close"].iloc[-1]
        last_open  = df["open"].iloc[-1]

        # Bullish sweep: kaars doorbreekt laagste punt maar sluit boven steun
        if last_low < prev_low and last_close > prev_low:
            conf = min((prev_low - last_low) / prev_low * 100, 0.80)
            return SMCSignal(1, conf, f"Bullish liquidity sweep onder {prev_low:.2f}", prev_low)

        # Bearish sweep: kaars doorbreekt hoogste punt maar sluit onder weerstand
        if last_high > prev_high and last_close < prev_high:
            conf = min((last_high - prev_high) / prev_high * 100, 0.80)
            return SMCSignal(-1, conf, f"Bearish liquidity sweep boven {prev_high:.2f}", prev_high)

        return SMCSignal(0, 0.0, "", 0.0)
