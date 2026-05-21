"""
Volume Profile — laat zien waar het meeste volume verhandeld is.
Dit zijn de ECHTE support/resistance zones waar instituten zitten.

Concepten:
  POC  — Point of Control: prijs met meest volume (magneet voor prijs)
  VAH  — Value Area High: 70% van volume zit hier onder
  VAL  — Value Area Low: 70% van volume zit hier boven
"""
import numpy as np
import pandas as pd
from dataclasses import dataclass


@dataclass
class VolumeProfileSignal:
    action: int
    confidence: float
    poc: float           # Point of Control
    vah: float           # Value Area High
    val: float           # Value Area Low
    reason: str


class VolumeProfileStrategy:
    def __init__(self, bins: int = 50, lookback: int = 500, value_area_pct: float = 0.70):
        self.bins = bins
        self.lookback = lookback
        self.value_area_pct = value_area_pct

    def signal(self, df: pd.DataFrame) -> VolumeProfileSignal:
        if len(df) < self.lookback:
            return VolumeProfileSignal(0, 0.0, 0.0, 0.0, 0.0, "te weinig data")

        recent = df.iloc[-self.lookback:]
        current = float(df["close"].iloc[-1])

        poc, vah, val = self._compute_profile(recent)

        dist_to_val = abs(current - val) / current
        dist_to_vah = abs(current - vah) / current
        dist_to_poc = abs(current - poc) / current

        # Prijs bij VAL (onderkant value area) = koopzone
        if current <= val * 1.005 and dist_to_val < 0.010:
            conf = min((0.012 - dist_to_val) / 0.012, 1.0) * 0.85
            return VolumeProfileSignal(1, conf, poc, vah, val,
                f"Prijs bij VAL {val:.2f} — institutionele koopzone")

        # Prijs bij VAH (bovenkant value area) = verkoopzone
        if current >= vah * 0.995 and dist_to_vah < 0.010:
            conf = min((0.012 - dist_to_vah) / 0.012, 1.0) * 0.85
            return VolumeProfileSignal(-1, conf, poc, vah, val,
                f"Prijs bij VAH {vah:.2f} — institutionele verkoopzone")

        # Prijs dicht bij POC = magneet, wacht op richting
        if dist_to_poc < 0.005:
            return VolumeProfileSignal(0, 0.3, poc, vah, val,
                f"Prijs bij POC {poc:.2f} — wacht op doorbraak")

        # Prijs boven VAH = bullish breakout
        if current > vah * 1.005:
            return VolumeProfileSignal(1, 0.60, poc, vah, val,
                f"Prijs boven VAH {vah:.2f} — bullish breakout")

        # Prijs onder VAL = bearish breakdown
        if current < val * 0.995:
            return VolumeProfileSignal(-1, 0.60, poc, vah, val,
                f"Prijs onder VAL {val:.2f} — bearish breakdown")

        return VolumeProfileSignal(0, 0.2, poc, vah, val,
            f"POC={poc:.2f} VAH={vah:.2f} VAL={val:.2f}")

    def _compute_profile(self, df: pd.DataFrame) -> tuple[float, float, float]:
        prices = ((df["high"] + df["low"] + df["close"]) / 3).values
        volumes = df["volume"].values
        price_min, price_max = prices.min(), prices.max()

        if price_max == price_min:
            return float(prices[-1]), float(price_max), float(price_min)

        edges = np.linspace(price_min, price_max, self.bins + 1)
        vol_at_price = np.zeros(self.bins)

        indices = np.clip(
            ((prices - price_min) / (price_max - price_min) * self.bins).astype(int),
            0, self.bins - 1,
        )
        np.add.at(vol_at_price, indices, volumes)

        # POC = midden van bin met meest volume
        poc_idx = vol_at_price.argmax()
        poc = (edges[poc_idx] + edges[poc_idx + 1]) / 2

        # Value Area: bins die samen 70% van volume bevatten rondom POC
        total_vol = vol_at_price.sum()
        target = total_vol * self.value_area_pct
        cumvol = vol_at_price[poc_idx]
        lo, hi = poc_idx, poc_idx

        while cumvol < target and (lo > 0 or hi < self.bins - 1):
            expand_lo = vol_at_price[lo - 1] if lo > 0 else 0
            expand_hi = vol_at_price[hi + 1] if hi < self.bins - 1 else 0
            if expand_lo >= expand_hi and lo > 0:
                lo -= 1
                cumvol += vol_at_price[lo]
            elif hi < self.bins - 1:
                hi += 1
                cumvol += vol_at_price[hi]
            else:
                break

        val = (edges[lo] + edges[lo + 1]) / 2
        vah = (edges[hi] + edges[hi + 1]) / 2
        return float(poc), float(vah), float(val)
