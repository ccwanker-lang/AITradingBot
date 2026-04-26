"""
Scalping strategie — snel instappen op momentum signalen.
Werkt het beste op kortere timeframes (5m, 15m).
"""
import pandas as pd
import numpy as np
from dataclasses import dataclass


@dataclass
class ScalpSignal:
    action: int        # +1 buy, -1 sell, 0 hold
    confidence: float
    reason: str


class ScalpingStrategy:
    """
    Combineert:
    - Volume spike (plotselinge interesse)
    - RSI momentum (richting bevestiging)
    - EMA stack (trend filter)
    - Prijs boven/onder VWAP
    """

    def __init__(self, rsi_period: int = 7, vol_spike_threshold: float = 2.0):
        self.rsi_period = rsi_period
        self.vol_spike_threshold = vol_spike_threshold

    def signal(self, df: pd.DataFrame) -> ScalpSignal:
        if len(df) < 30:
            return ScalpSignal(0, 0.0, "te weinig data")

        required = ["rsi_7", "volume_ratio", "ema_9", "ema_21", "vwap", "close"]
        if not all(c in df.columns for c in required):
            return ScalpSignal(0, 0.0, "kolommen ontbreken")

        close = df["close"].iloc[-1]
        rsi = df["rsi_7"].iloc[-1]
        rsi_prev = df["rsi_7"].iloc[-2]
        vol_ratio = df["volume_ratio"].iloc[-1]
        ema9 = df["ema_9"].iloc[-1]
        ema21 = df["ema_21"].iloc[-1]
        vwap = df["vwap"].iloc[-1]

        # Trend filter — alleen handelen in richting van trend
        bullish_trend = ema9 > ema21 and close > vwap
        bearish_trend = ema9 < ema21 and close < vwap

        volume_spike = vol_ratio > self.vol_spike_threshold

        # ── Bullish scalp ──────────────────────────────────────────
        if bullish_trend and volume_spike and 30 < rsi < 60 and rsi > rsi_prev:
            conf = min((vol_ratio / 3) * ((60 - rsi) / 30), 1.0)
            return ScalpSignal(1, conf, f"Bullish scalp: RSI={rsi:.0f} Vol={vol_ratio:.1f}x")

        # ── Bearish scalp ──────────────────────────────────────────
        if bearish_trend and volume_spike and 40 < rsi < 70 and rsi < rsi_prev:
            conf = min((vol_ratio / 3) * ((rsi - 40) / 30), 1.0)
            return ScalpSignal(-1, conf, f"Bearish scalp: RSI={rsi:.0f} Vol={vol_ratio:.1f}x")

        # ── RSI extreme met volume ─────────────────────────────────
        if rsi < 20 and volume_spike and rsi > rsi_prev:
            return ScalpSignal(1, 0.75, f"RSI extreme oversold + volume: {rsi:.0f}")

        if rsi > 80 and volume_spike and rsi < rsi_prev:
            return ScalpSignal(-1, 0.75, f"RSI extreme overbought + volume: {rsi:.0f}")

        return ScalpSignal(0, 0.0, "geen scalp signaal")


class MultiTimeframeScalper:
    """Bevestigt scalp signalen op meerdere timeframes."""

    def __init__(self):
        self.strategy = ScalpingStrategy()

    def signal(self, df_fast: pd.DataFrame, df_slow: pd.DataFrame) -> ScalpSignal:
        fast = self.strategy.signal(df_fast)
        slow = self.strategy.signal(df_slow)

        # Beide timeframes moeten overeenstemmen
        if fast.action == slow.action and fast.action != 0:
            combined_conf = (fast.confidence + slow.confidence) / 2 * 1.2
            return ScalpSignal(
                fast.action,
                min(combined_conf, 1.0),
                f"MTF bevestigd: {fast.reason}",
            )

        # Alleen snel signaal, lager vertrouwen
        if fast.action != 0:
            return ScalpSignal(fast.action, fast.confidence * 0.6, f"Alleen snel TF: {fast.reason}")

        return ScalpSignal(0, 0.0, "geen MTF bevestiging")
