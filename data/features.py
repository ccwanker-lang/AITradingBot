"""
Feature Engineering — berekent alle technische indicatoren
die echte traders gebruiken als input voor de AI.
"""
import numpy as np
import pandas as pd
from ta.trend import EMAIndicator, MACD, ADXIndicator
from ta.momentum import RSIIndicator, StochasticOscillator
from ta.volatility import BollingerBands, AverageTrueRange
from ta.volume import OnBalanceVolumeIndicator, VolumeWeightedAveragePrice


def add_all_features(df: pd.DataFrame) -> pd.DataFrame:
    """
    Voeg alle technische features toe aan een OHLCV dataframe.
    Verwacht kolommen: open, high, low, close, volume
    """
    df = df.copy()
    close = df["close"]
    high = df["high"]
    low = df["low"]
    volume = df["volume"]

    # ── Trend indicatoren ──────────────────────────────────────────
    for period in [9, 21, 50, 200]:
        df[f"ema_{period}"] = EMAIndicator(close, window=period).ema_indicator()

    macd = MACD(close)
    df["macd"] = macd.macd()
    df["macd_signal"] = macd.macd_signal()
    df["macd_diff"] = macd.macd_diff()

    # ── Momentum indicatoren ───────────────────────────────────────
    df["rsi_14"] = RSIIndicator(close, window=14).rsi()
    df["rsi_7"] = RSIIndicator(close, window=7).rsi()

    stoch = StochasticOscillator(high, low, close)
    df["stoch_k"] = stoch.stoch()
    df["stoch_d"] = stoch.stoch_signal()

    # ── Volatiliteit indicatoren ───────────────────────────────────
    bb = BollingerBands(close, window=20)
    df["bb_high"] = bb.bollinger_hband()
    df["bb_low"] = bb.bollinger_lband()
    df["bb_mid"] = bb.bollinger_mavg()
    df["bb_width"] = (df["bb_high"] - df["bb_low"]) / df["bb_mid"]
    df["bb_pct"] = bb.bollinger_pband()  # positie binnen de banden (0-1)

    df["atr_14"] = AverageTrueRange(high, low, close, window=14).average_true_range()

    # ── Trendsterkte ───────────────────────────────────────────────
    adx = ADXIndicator(high, low, close, window=14)
    df["adx_14"]    = adx.adx()
    df["adx_pos"]   = adx.adx_pos()   # +DI
    df["adx_neg"]   = adx.adx_neg()   # -DI

    # ── Volume indicatoren ─────────────────────────────────────────
    df["obv"] = OnBalanceVolumeIndicator(close, volume).on_balance_volume()
    df["vwap"] = VolumeWeightedAveragePrice(high, low, close, volume).volume_weighted_average_price()
    df["volume_sma"] = volume.rolling(20).mean()
    df["volume_ratio"] = volume / df["volume_sma"]

    # ── Prijs features ─────────────────────────────────────────────
    df["returns_1"] = close.pct_change(1)
    df["returns_5"] = close.pct_change(5)
    df["returns_10"] = close.pct_change(10)
    df["high_low_ratio"] = (high - low) / close
    df["close_open_ratio"] = (close - df["open"]) / df["open"]

    # ── Trend sterkte ──────────────────────────────────────────────
    df["ema_9_21_cross"] = (df["ema_9"] - df["ema_21"]) / df["ema_21"]
    df["price_vs_ema200"] = (close - df["ema_200"]) / df["ema_200"]
    df["price_vs_vwap"] = (close - df["vwap"]) / df["vwap"]

    # ── Genormaliseerde features (z-score over rolling window) ─────
    feature_cols = [c for c in df.columns if c not in ["open", "high", "low", "close", "volume"]]
    for col in feature_cols:
        roll_mean = df[col].rolling(100, min_periods=10).mean()
        roll_std = df[col].rolling(100, min_periods=10).std()
        df[f"{col}_norm"] = (df[col] - roll_mean) / (roll_std + 1e-8)

    df.dropna(inplace=True)
    return df


def get_feature_columns(df: pd.DataFrame) -> list[str]:
    """Geeft de genormaliseerde feature kolommen terug (input voor de AI)."""
    return [c for c in df.columns if c.endswith("_norm")]
