"""Centrale configuratie voor de Monster Crypto Bot."""
import os
from dataclasses import dataclass, field
from typing import List

try:
    from dotenv import load_dotenv
    load_dotenv()
except ImportError:
    pass


@dataclass
class Config:
    # ── Trading ────────────────────────────────────────────────────
    symbol: str = "BTC/USDT"
    symbols: List[str] = field(default_factory=lambda: ["BTC/USDT", "ETH/USDT", "SOL/USDT"])
    timeframe: str = "1h"
    interval_seconds: int = 60

    # ── Kapitaal ───────────────────────────────────────────────────
    initial_capital: float = 1000.0

    # ── Exchange ───────────────────────────────────────────────────
    exchange_id: str = "binance"
    api_key: str = ""
    api_secret: str = ""

    # ── AI Modellen ────────────────────────────────────────────────
    model_path: str = "models/crypto_ppo"
    lstm_path: str = "models/lstm_predictor.pt"

    # ── Signaalgewichten ───────────────────────────────────────────
    rl_weight: float = 0.30
    lstm_weight: float = 0.20
    # Resterende 0.50 gaat naar traditionele strategieën

    # ── Risico ────────────────────────────────────────────────────
    max_drawdown_stop: float = 0.15
    max_position_pct: float = 0.90
    min_confidence: float = 0.28
    kelly_fraction: float = 0.25
    atr_sl_multiplier: float = 2.0    # Stop-loss op 2x ATR
    atr_tp_multiplier: float = 4.0    # Take-profit op 4x ATR (2:1 R/R)
    trailing_stop_pct: float = 0.05   # 5% trailing stop

    # ── Handelsmodus ──────────────────────────────────────────────
    paper_trading: bool = True
    multi_asset: bool = True

    # ── Telegram ──────────────────────────────────────────────────
    telegram_token: str = ""
    telegram_chat_id: str = ""

    # ── Auto-hertraining ──────────────────────────────────────────
    retrain_interval_hours: int = 24
    min_trades_for_retrain: int = 50

    # ── Backtesting ───────────────────────────────────────────────
    backtest_lookback_days: int = 365

    @classmethod
    def from_env(cls) -> "Config":
        return cls(
            symbol=os.getenv("SYMBOL", "BTC/USDT"),
            symbols=os.getenv("SYMBOLS", "BTC/USDT,ETH/USDT,SOL/USDT").split(","),
            timeframe=os.getenv("TIMEFRAME", "1h"),
            interval_seconds=int(os.getenv("INTERVAL", "60")),
            initial_capital=float(os.getenv("CAPITAL", "1000")),
            api_key=os.getenv("BINANCE_API_KEY", ""),
            api_secret=os.getenv("BINANCE_API_SECRET", ""),
            model_path=os.getenv("MODEL_PATH", "models/crypto_ppo"),
            lstm_path=os.getenv("LSTM_PATH", "models/lstm_predictor.pt"),
            paper_trading=os.getenv("LIVE", "").lower() != "true",
            multi_asset=os.getenv("MULTI_ASSET", "true").lower() == "true",
            telegram_token=os.getenv("TELEGRAM_TOKEN", ""),
            telegram_chat_id=os.getenv("TELEGRAM_CHAT_ID", ""),
            retrain_interval_hours=int(os.getenv("RETRAIN_HOURS", "24")),
            max_drawdown_stop=float(os.getenv("MAX_DRAWDOWN", "0.15")),
        )
