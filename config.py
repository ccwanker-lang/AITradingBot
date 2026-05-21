"""Centrale configuratie voor de Monster Crypto Bot."""
import os
from dataclasses import dataclass, field
from typing import List

try:
    from dotenv import load_dotenv
    load_dotenv()
except ImportError:
    pass


# ── Profielen: Conservative / Balanced / Aggressive ─────────────────────
# Expliciete .env waarden overschrijven het profiel altijd.
PROFILES: dict = {
    "conservative": {
        "min_confidence":     0.40,   # hogere drempel → minder maar betere trades
        "max_drawdown_stop":  0.05,   # stop bij 5% verlies
        "kelly_fraction":     0.15,   # kleine posities
        "atr_sl_multiplier":  2.5,    # bredere SL → minder valse stops
        "atr_tp_multiplier":  5.0,    # hogere TP → grotere winstpotentieel
        "trailing_stop_pct":  0.04,
        "only_a_setups":      True,   # alleen A+/A grade
        "max_position_pct":   0.50,   # max 50% van portfolio per trade
    },
    "balanced": {
        "min_confidence":     0.32,
        "max_drawdown_stop":  0.10,
        "kelly_fraction":     0.25,
        "atr_sl_multiplier":  2.0,
        "atr_tp_multiplier":  4.0,
        "trailing_stop_pct":  0.05,
        "only_a_setups":      False,
        "max_position_pct":   0.90,
    },
    "aggressive": {
        "min_confidence":     0.25,   # lagere drempel → meer trades
        "max_drawdown_stop":  0.15,   # accepteer meer risico
        "kelly_fraction":     0.35,   # grotere posities
        "atr_sl_multiplier":  1.5,    # kleinere SL → meer frequente stops
        "atr_tp_multiplier":  3.0,
        "trailing_stop_pct":  0.06,
        "only_a_setups":      False,
        "max_position_pct":   0.90,
    },
}


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
    min_confidence: float = 0.32
    kelly_fraction: float = 0.25
    atr_sl_multiplier: float = 2.0    # Stop-loss op 2x ATR
    atr_tp_multiplier: float = 4.0    # Take-profit op 4x ATR (2:1 R/R)
    trailing_stop_pct: float = 0.05   # 5% trailing stop

    # ── Handelsmodus ──────────────────────────────────────────────
    paper_trading: bool = True
    multi_asset: bool = True

    # ── Profiel ────────────────────────────────────────────────────
    profile: str = "balanced"   # conservative / balanced / aggressive
    only_a_setups: bool = False  # Conservative: alleen A+/A grade

    # ── Telegram ──────────────────────────────────────────────────
    telegram_token: str = ""
    telegram_chat_id: str = ""

    # ── Auto-hertraining ──────────────────────────────────────────
    retrain_interval_hours: int = 24
    min_trades_for_retrain: int = 50

    # ── Kosten ────────────────────────────────────────────────────
    trading_fee: float = 0.001   # 0.1% per trade (Binance taker fee)

    # ── Backtesting ───────────────────────────────────────────────
    backtest_lookback_days: int = 365

    @classmethod
    def from_env(cls) -> "Config":
        profile_name = os.getenv("PROFILE", "balanced").lower()
        pvals        = PROFILES.get(profile_name, PROFILES["balanced"])

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
            # Profiel-defaults, overschrijfbaar via .env
            max_drawdown_stop=float(os.getenv("MAX_DRAWDOWN",  str(pvals["max_drawdown_stop"]))),
            min_confidence=float(os.getenv("MIN_CONFIDENCE",   str(pvals["min_confidence"]))),
            kelly_fraction=float(os.getenv("KELLY_FRACTION",   str(pvals["kelly_fraction"]))),
            atr_sl_multiplier=float(os.getenv("ATR_SL_MULT",   str(pvals["atr_sl_multiplier"]))),
            atr_tp_multiplier=float(os.getenv("ATR_TP_MULT",   str(pvals["atr_tp_multiplier"]))),
            trailing_stop_pct=float(os.getenv("TRAILING_STOP_PCT", str(pvals["trailing_stop_pct"]))),
            max_position_pct=float(os.getenv("MAX_POSITION_PCT",   str(pvals["max_position_pct"]))),
            rl_weight=float(os.getenv("RL_WEIGHT", "0.30")),
            lstm_weight=float(os.getenv("LSTM_WEIGHT", "0.20")),
            trading_fee=float(os.getenv("TRADING_FEE", "0.001")),
            profile=profile_name,
            only_a_setups=pvals.get("only_a_setups", False),
        )

    def profile_summary(self) -> str:
        return (
            f"Profiel: {self.profile.upper()}"
            f" | Min conf: {self.min_confidence:.2f}"
            f" | Max DD: {self.max_drawdown_stop:.0%}"
            f" | Kelly: {self.kelly_fraction:.0%}"
            f" | SL/TP: {self.atr_sl_multiplier:.1f}×/{self.atr_tp_multiplier:.1f}×ATR"
            + (" | Alleen A-setups" if self.only_a_setups else "")
        )
