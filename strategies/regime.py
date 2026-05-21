"""
Marktregime detectie — de bot weet in welke markt hij zit en past zich aan.

Regimes:
  BULL_TREND   — stijgende trend, gebruik trend-following strategieën
  BEAR_TREND   — dalende trend, weinig kopen, snel verkopen
  RANGING      — zijwaartse markt, gebruik mean-reversion
  HIGH_VOL     — hoge volatiliteit, kleinere posities, bredere stops
  ACCUMULATION — lage volume/volatiliteit, grote move op komst
"""
import numpy as np
import pandas as pd
from dataclasses import dataclass
from enum import Enum


class Regime(str, Enum):
    BULL_TREND   = "bull_trend"
    BEAR_TREND   = "bear_trend"
    RANGING      = "ranging"
    HIGH_VOL     = "high_vol"
    ACCUMULATION = "accumulation"


@dataclass
class RegimeResult:
    regime: Regime
    strength: float        # 0.0 - 1.0
    position_mult: float   # Vermenigvuldigingsfactor voor positiegrootte
    sl_mult: float         # Stop-loss aanpassing (hoger = wijder)
    description: str


_REGIME_PARAMS = {
    Regime.BULL_TREND:   {"position_mult": 1.20, "sl_mult": 1.0},
    Regime.BEAR_TREND:   {"position_mult": 0.80, "sl_mult": 0.8},
    Regime.RANGING:      {"position_mult": 0.80, "sl_mult": 0.9},
    Regime.HIGH_VOL:     {"position_mult": 0.40, "sl_mult": 1.5},
    Regime.ACCUMULATION: {"position_mult": 0.70, "sl_mult": 0.8},
}


class RegimeDetector:
    def detect(self, df: pd.DataFrame) -> RegimeResult:
        if len(df) < 60:
            return self._default()

        close = df["close"]

        # ── ADX (trendsterkte) ─────────────────────────────────────
        adx = df["adx_14"].iloc[-1] if "adx_14" in df.columns else 20.0
        is_trending = adx > 25

        # ── EMA stack (richting) ───────────────────────────────────
        ema9   = df["ema_9"].iloc[-1]   if "ema_9"   in df.columns else close.iloc[-1]
        ema21  = df["ema_21"].iloc[-1]  if "ema_21"  in df.columns else close.iloc[-1]
        ema50  = df["ema_50"].iloc[-1]  if "ema_50"  in df.columns else close.iloc[-1]
        ema200 = df["ema_200"].iloc[-1] if "ema_200" in df.columns else close.iloc[-1]
        price  = close.iloc[-1]

        # EMA200 check losgekoppeld van bull_stack: BTC kan BULL_TREND tonen
        # ook als het historisch lager staat dan EMA200 (bijv. na een correctie).
        # Bear_stack: EMA-stack bearish is voldoende — eis op ema200 blokkeerde bear_trend
        # tijdens 10-15% correcties in een bull markt (price bleef boven ema200).
        bull_stack = ema9 > ema21 > ema50
        bear_stack = ema9 < ema21 < ema50

        # ── Volatiliteit ───────────────────────────────────────────
        atr = df["atr_14"].iloc[-1] if "atr_14" in df.columns else price * 0.02
        atr_pct = atr / price
        hist_atr = df["atr_14"].rolling(50).mean().iloc[-1] if "atr_14" in df.columns else atr
        high_vol = atr_pct > (hist_atr / price) * 2.5

        # ── Bollinger squeeze (accumulation) ──────────────────────
        bb_width = df["bb_width"].iloc[-1] if "bb_width" in df.columns else 0.05
        hist_bb  = df["bb_width"].rolling(50).mean().iloc[-1] if "bb_width" in df.columns else 0.05
        squeeze  = bb_width < hist_bb * 0.5

        # ── Volume ─────────────────────────────────────────────────
        vol_ratio = df["volume_ratio"].iloc[-1] if "volume_ratio" in df.columns else 1.0

        # ── Regime bepalen ─────────────────────────────────────────
        if high_vol:
            regime = Regime.HIGH_VOL
            strength = min(atr_pct / (hist_atr / price) / 3, 1.0)
            desc = f"Hoge volatiliteit — ATR {atr_pct:.1%} van prijs"

        elif squeeze and vol_ratio < 0.8:
            regime = Regime.ACCUMULATION
            strength = 1 - bb_width / hist_bb
            desc = "Bollinger squeeze — grote move verwacht"

        elif is_trending and bull_stack:
            regime = Regime.BULL_TREND
            strength = min(adx / 50, 1.0)
            desc = f"Bullish trend — ADX={adx:.0f}, EMA stack bullish"

        elif is_trending and bear_stack:
            regime = Regime.BEAR_TREND
            strength = min(adx / 50, 1.0)
            desc = f"Bearish trend — ADX={adx:.0f}, EMA stack bearish"

        else:
            regime = Regime.RANGING
            strength = 1 - adx / 25
            desc = f"Zijwaartse markt — ADX={adx:.0f}"

        params = _REGIME_PARAMS[regime]
        return RegimeResult(
            regime=regime,
            strength=float(strength),
            position_mult=params["position_mult"],
            sl_mult=params["sl_mult"],
            description=desc,
        )

    def _default(self) -> RegimeResult:
        return RegimeResult(Regime.RANGING, 0.5, 0.8, 1.0, "Te weinig data")
