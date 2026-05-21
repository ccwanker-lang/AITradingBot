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
        """Hertraint het LSTM model op gecombineerde data van alle symbolen."""
        try:
            import pandas as pd
            from data.features import add_all_features, get_feature_columns

            self.logger.info("LSTM hertraining gestart...")
            # 90 dagen per symbool: genoeg patronen, beheersbare trainingstijd op Pi
            days = min(self.config.backtest_lookback_days, 90)
            symbols = getattr(self.config, "symbols", [self.config.symbol])

            frames = []
            for sym in symbols:
                try:
                    df_sym = self.fetcher.fetch_historical(sym, self.config.timeframe, days=days)
                    df_sym = add_all_features(df_sym)
                    frames.append(df_sym)
                    self.logger.info(f"LSTM data geladen: {sym} ({len(df_sym)} kaarsen)")
                except Exception as e:
                    self.logger.warning(f"LSTM data overgeslagen voor {sym}: {e}")

            if not frames:
                return 0.0

            # Reset index zodat de gecombineerde DataFrame geen dubbele indices heeft
            df = pd.concat(frames, ignore_index=True)
            feature_cols = get_feature_columns(df)
            # 25 epochs + batch 128: 3× sneller dan 50 epochs + batch 64 op Raspberry Pi
            acc = lstm_predictor.train(df, feature_cols, epochs=25, batch_size=128)
            self.logger.info(f"LSTM hertraining klaar — validatie accuraatheid: {acc:.1%} ({len(df)} samples, {len(symbols)} symbolen)")
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
            import pandas as pd
            symbols = getattr(self.config, "symbols", [self.config.symbol])
            frames = []
            for sym in symbols:
                try:
                    df_sym = self.fetcher.fetch_historical(sym, self.config.timeframe, days=90)
                    df_sym = add_all_features(df_sym)
                    frames.append(df_sym)
                except Exception:
                    pass
            df = pd.concat(frames, ignore_index=True) if frames else self.fetcher.fetch_historical(
                self.config.symbol, self.config.timeframe, days=365)
            if not frames:
                df = add_all_features(df)
            feature_cols = get_feature_columns(df)

            # Gebruik het echte kapitaal — eerder was 10k hardcoded maar bot handelt met 1k
            actual_capital = getattr(self.config, "initial_capital", 1000.0)

            def make_env():
                return CryptoTradingEnv(df, feature_cols, initial_capital=actual_capital)

            env = DummyVecEnv([make_env])
            model_path = Path(self.config.model_path)

            def _new_ppo_model():
                return PPO(
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

            existing = model_path.with_suffix(".zip")
            if existing.exists():
                try:
                    model = PPO.load(str(model_path), env=env)
                    self.logger.info("Bestaand RL model geladen voor hertraining")
                except Exception:
                    # Actie-ruimte gewijzigd (bijv. 3→4 acties) — nieuw model bouwen
                    existing.unlink()
                    self.logger.info("RL model incompatibel (actie-ruimte gewijzigd) — nieuw model")
                    model = _new_ppo_model()
            else:
                model = _new_ppo_model()

            # Verhoogd van 200k naar 500k — PPO heeft meer stappen nodig voor crypto
            model.learn(total_timesteps=500_000)
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
