"""
Anomalie detectie — herkent pump & dump, crashes en abnormale marktomstandigheden.
Gebaseerd op Z-score statistieken en volume/prijs patronen.
"""
import numpy as np
import pandas as pd
from dataclasses import dataclass
from enum import Enum


class AnomalyType(str, Enum):
    NORMAL = "normaal"
    PUMP = "pump"
    DUMP = "dump"
    HIGH_VOL = "hoge_volatiliteit"
    CRASH = "crash"
    SQUEEZE = "squeeze"  # Bollinger squeeze = naderende explosie


@dataclass
class AnomalyResult:
    type: AnomalyType
    severity: float      # 0.0 - 1.0
    should_trade: bool   # False = bot pauzeert
    details: str


class AnomalyDetector:
    def __init__(self, z_threshold: float = 2.5, volume_spike: float = 4.0):
        self.z_threshold = z_threshold
        self.volume_spike = volume_spike

    def detect(self, df: pd.DataFrame) -> AnomalyResult:
        if len(df) < 30:
            return AnomalyResult(AnomalyType.NORMAL, 0.0, True, "te weinig data")

        close = df["close"]
        volume = df["volume"]

        # ── Prijs Z-score ──────────────────────────────────────────
        returns = close.pct_change().dropna()
        recent_return = returns.iloc[-1]
        rolling_mean = returns.rolling(50).mean().iloc[-1]
        rolling_std = returns.rolling(50).std().iloc[-1]
        price_z = (recent_return - rolling_mean) / (rolling_std + 1e-8)

        # ── Volume spike ───────────────────────────────────────────
        vol_ratio = volume.iloc[-1] / (volume.rolling(20).mean().iloc[-1] + 1e-8)

        # ── Volatiliteit ───────────────────────────────────────────
        recent_vol = returns.rolling(10).std().iloc[-1]
        normal_vol = returns.rolling(50).std().iloc[-1]
        vol_ratio_std = recent_vol / (normal_vol + 1e-8)

        # ── Bollinger squeeze ──────────────────────────────────────
        bb_width = df.get("bb_width", pd.Series([0.05] * len(df))).iloc[-1]
        is_squeeze = bb_width < 0.02  # Zeer smalle bands

        # ── Crash detectie (3 rode kaarsen + hoog volume) ──────────
        last_3 = close.iloc[-4:-1]
        three_down = all(close.iloc[-4 + i] > close.iloc[-3 + i] for i in range(3))

        # ── Beslissing ─────────────────────────────────────────────
        if price_z > self.z_threshold and vol_ratio > self.volume_spike:
            severity = min(price_z / 5.0, 1.0)
            return AnomalyResult(
                AnomalyType.PUMP, severity, False,
                f"Prijs Z={price_z:.1f}, Volume {vol_ratio:.1f}x — PUMP gedetecteerd, pauze"
            )

        if price_z < -self.z_threshold and vol_ratio > self.volume_spike:
            severity = min(abs(price_z) / 5.0, 1.0)
            return AnomalyResult(
                AnomalyType.DUMP, severity, False,
                f"Prijs Z={price_z:.1f}, Volume {vol_ratio:.1f}x — DUMP gedetecteerd, pauze"
            )

        if three_down and vol_ratio > 2.0 and recent_return < -0.03:
            return AnomalyResult(
                AnomalyType.CRASH, 0.8, False,
                f"Crash patroon: 3 dalende kaarsen + volume spike {vol_ratio:.1f}x"
            )

        if vol_ratio_std > 3.0:
            return AnomalyResult(
                AnomalyType.HIGH_VOL, min(vol_ratio_std / 5, 1.0), True,
                f"Hoge volatiliteit: {vol_ratio_std:.1f}x normaal — voorzichtiger handelen"
            )

        if is_squeeze:
            return AnomalyResult(
                AnomalyType.SQUEEZE, 0.5, True,
                "Bollinger squeeze — grote move op komst, wacht op bevestiging"
            )

        return AnomalyResult(AnomalyType.NORMAL, 0.0, True, "Normale marktomstandigheden")
