"""
Auto-hertrainer — hertraint RL model en LSTM automatisch op nieuwe data.
"""
import os
import time
import threading
from datetime import datetime
from pathlib import Path


class ModelTrainer:
    def __init__(self, config, fetcher, logger):
        self.config = config
        self.fetcher = fetcher
        self.logger = logger
        self._lock = threading.Lock()
        self._training = False

    def train_lstm(self, lstm_predictor) -> float:
        """Hertraint het LSTM model op verse historische data."""
        try:
            from data.features import add_all_features, get_feature_columns

            self.logger.info("LSTM hertraining gestart...")
            df = self.fetcher.fetch_historical(
                self.config.symbol, self.config.timeframe,
                days=min(self.config.backtest_lookback_days, 365)
            )
            df = add_all_features(df)
            feature_cols = get_feature_columns(df)
            acc = lstm_predictor.train(df, feature_cols, epochs=40)
            self.logger.info(f"LSTM hertraining klaar — validatie accuraatheid: {acc:.1%}")
            return acc
        except Exception as e:
            self.logger.log_error("LSTM hertraining", e)
            return 0.0

    def train_rl(self) -> bool:
        """Hertraint het PPO RL model op historische data."""
        try:
            from stable_baselines3 import PPO
            from stable_baselines3.common.vec_env import DummyVecEnv
            from agent.environment import CryptoTradingEnv
            from data.features import add_all_features, get_feature_columns

            self.logger.info("RL hertraining gestart...")
            df = self.fetcher.fetch_historical(
                self.config.symbol, self.config.timeframe, days=365
            )
            df = add_all_features(df)
            feature_cols = get_feature_columns(df)

            def make_env():
                return CryptoTradingEnv(df, feature_cols, initial_capital=10_000.0)

            env = DummyVecEnv([make_env])
            model_path = Path(self.config.model_path)

            if model_path.with_suffix(".zip").exists():
                model = PPO.load(str(model_path), env=env)
                self.logger.info("Bestaand RL model geladen voor hertraining")
            else:
                model = PPO(
                    "MlpPolicy", env,
                    learning_rate=3e-4,
                    n_steps=2048,
                    batch_size=128,
                    n_epochs=10,
                    gamma=0.99,
                    gae_lambda=0.95,
                    clip_range=0.2,
                    ent_coef=0.01,
                    verbose=0,
                )

            model.learn(total_timesteps=200_000)
            model_path.parent.mkdir(exist_ok=True)
            model.save(str(model_path))
            self.logger.info(f"RL model opgeslagen naar {model_path}")
            return True

        except ImportError:
            self.logger.warning("stable-baselines3 niet beschikbaar — RL training overgeslagen")
            return False
        except Exception as e:
            self.logger.log_error("RL hertraining", e)
            return False

    def start_auto_retrain(self, lstm_predictor, interval_hours: int = 24):
        """Start een achtergrond thread die periodiek hertraint."""
        def _loop():
            while True:
                time.sleep(interval_hours * 3600)
                if not self._training:
                    with self._lock:
                        self._training = True
                        try:
                            self.logger.info("Auto-hertraining gestart...")
                            self.train_lstm(lstm_predictor)
                            self.train_rl()
                        finally:
                            self._training = False

        t = threading.Thread(target=_loop, daemon=True)
        t.start()
        self.logger.info(f"Auto-hertraining gepland elke {interval_hours} uur")
