"""
Training Script — train de RL agent (PPO) op historische crypto data.

Gebruik:
    python train.py --symbol BTC/USDT --timeframe 1h --episodes 500

De agent leert van miljoenen historische prijs-momenten en optimaliseert
zijn strategie via Proximal Policy Optimization (PPO).
"""
import os
import argparse
import numpy as np
import pandas as pd
import ccxt
from datetime import datetime
from stable_baselines3 import PPO
from stable_baselines3.common.vec_env import DummyVecEnv, VecNormalize
from stable_baselines3.common.callbacks import EvalCallback, CheckpointCallback
from stable_baselines3.common.monitor import Monitor

import sys
sys.path.append(os.path.dirname(os.path.dirname(__file__)))
from data.features import add_all_features, get_feature_columns
from agent.environment import CryptoTradingEnv


def download_data(symbol: str, timeframe: str, limit: int = 5000) -> pd.DataFrame:
    """Download historische OHLCV data van Binance."""
    print(f"Data downloaden: {symbol} {timeframe} ({limit} kaarsen)...")
    exchange = ccxt.binance({"enableRateLimit": True})

    ohlcv = exchange.fetch_ohlcv(symbol, timeframe, limit=limit)
    df = pd.DataFrame(ohlcv, columns=["timestamp", "open", "high", "low", "close", "volume"])
    df["timestamp"] = pd.to_datetime(df["timestamp"], unit="ms")
    df.set_index("timestamp", inplace=True)
    print(f"  {len(df)} kaarsen gedownload ({df.index[0]} → {df.index[-1]})")
    return df


def prepare_data(df: pd.DataFrame) -> tuple[pd.DataFrame, list[str]]:
    """Voeg features toe en geef de feature kolommen terug."""
    print("Features berekenen...")
    df_features = add_all_features(df)
    feature_cols = get_feature_columns(df_features)
    print(f"  {len(feature_cols)} features berekend, {len(df_features)} rijen")
    return df_features, feature_cols


def make_env(df, feature_cols, **env_kwargs):
    """Factory functie voor gymnasium environment."""
    def _init():
        env = CryptoTradingEnv(df, feature_cols, **env_kwargs)
        return Monitor(env)
    return _init


def train(
    symbol: str = "BTC/USDT",
    timeframe: str = "1h",
    total_timesteps: int = 500_000,
    model_path: str = "models/crypto_ppo",
):
    os.makedirs("models", exist_ok=True)
    os.makedirs("logs", exist_ok=True)

    # ── Data ──────────────────────────────────────────────────────
    df = download_data(symbol, timeframe, limit=5000)
    df_features, feature_cols = prepare_data(df)

    # Train/eval split (80/20)
    split = int(len(df_features) * 0.8)
    df_train = df_features.iloc[:split].reset_index(drop=True)
    df_eval = df_features.iloc[split:].reset_index(drop=True)

    env_kwargs = dict(
        initial_capital=10_000.0,
        transaction_fee=0.001,
        window_size=20,
    )

    # ── Environments ──────────────────────────────────────────────
    print("\nEnvironments aanmaken...")
    train_env = DummyVecEnv([make_env(df_train, feature_cols, **env_kwargs)])
    train_env = VecNormalize(train_env, norm_obs=True, norm_reward=True, clip_obs=10.0)

    eval_env = DummyVecEnv([make_env(df_eval, feature_cols, **env_kwargs)])
    eval_env = VecNormalize(eval_env, norm_obs=True, norm_reward=False, clip_obs=10.0, training=False)

    # ── PPO Agent ─────────────────────────────────────────────────
    print("\nPPO agent aanmaken...")
    model = PPO(
        "MlpPolicy",
        train_env,
        verbose=1,
        learning_rate=3e-4,
        n_steps=2048,
        batch_size=64,
        n_epochs=10,
        gamma=0.99,
        gae_lambda=0.95,
        clip_range=0.2,
        ent_coef=0.01,           # Entropie bonus → meer exploratie
        vf_coef=0.5,
        max_grad_norm=0.5,
        policy_kwargs=dict(
            net_arch=[256, 256, 128],  # 3 lagen neuraal netwerk
        ),
        tensorboard_log="logs/",
    )

    # ── Callbacks ─────────────────────────────────────────────────
    callbacks = [
        EvalCallback(
            eval_env,
            best_model_save_path=f"{model_path}_best",
            log_path="logs/eval",
            eval_freq=10_000,
            n_eval_episodes=3,
            deterministic=True,
        ),
        CheckpointCallback(
            save_freq=50_000,
            save_path="models/checkpoints/",
            name_prefix="ppo_crypto",
        ),
    ]

    # ── Training ──────────────────────────────────────────────────
    print(f"\nTraining gestart: {total_timesteps:,} stappen...")
    print("=" * 60)
    model.train(total_timesteps=total_timesteps, callback=callbacks)

    # ── Opslaan ───────────────────────────────────────────────────
    model.save(model_path)
    train_env.save(f"{model_path}_vec_normalize.pkl")
    print(f"\nModel opgeslagen: {model_path}")

    return model, train_env, feature_cols


def backtest(model_path: str, df: pd.DataFrame, feature_cols: list[str]) -> dict:
    """Voer een backtest uit op het getrainde model."""
    from stable_baselines3.common.vec_env import VecNormalize
    import pickle

    env = CryptoTradingEnv(df, feature_cols, initial_capital=10_000)
    obs, _ = env.reset()

    try:
        model = PPO.load(model_path)
        print("Model geladen voor backtest")
    except Exception as e:
        print(f"Kon model niet laden: {e}")
        return {}

    done = False
    total_reward = 0
    step = 0

    while not done:
        action, _ = model.predict(obs, deterministic=True)
        obs, reward, done, truncated, info = env.step(int(action))
        total_reward += reward
        step += 1
        if done or truncated:
            break

    final_value = info.get("portfolio_value", 10_000)
    stats = env.get_trade_stats()
    stats["total_return"] = (final_value - 10_000) / 10_000
    stats["total_reward"] = total_reward
    stats["steps"] = step

    print("\n── Backtest Resultaten ──────────────────────────────")
    print(f"  Totaal rendement:  {stats['total_return']:+.2%}")
    print(f"  Totaal trades:     {stats.get('total_trades', 0)}")
    print(f"  Win rate:          {stats.get('win_rate', 0):.1%}")
    print(f"  Profit factor:     {stats.get('profit_factor', 0):.2f}")
    print(f"  Avg win:           {stats.get('avg_win', 0):+.2%}")
    print(f"  Avg loss:          {stats.get('avg_loss', 0):+.2%}")
    print("=" * 52)

    return stats


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Train crypto RL bot")
    parser.add_argument("--symbol", default="BTC/USDT")
    parser.add_argument("--timeframe", default="1h")
    parser.add_argument("--steps", type=int, default=500_000)
    parser.add_argument("--model", default="models/crypto_ppo")
    parser.add_argument("--backtest-only", action="store_true")
    args = parser.parse_args()

    if args.backtest_only:
        df = download_data(args.symbol, args.timeframe, limit=1000)
        df_features, feature_cols = prepare_data(df)
        backtest(args.model, df_features, feature_cols)
    else:
        model, env, feature_cols = train(
            symbol=args.symbol,
            timeframe=args.timeframe,
            total_timesteps=args.steps,
            model_path=args.model,
        )
