"""
Monster Crypto Trading Environment — killer reward systeem.

Reward gebaseerd op:
- Sortino ratio (alleen neerwaartse volatiliteit bestraft)
- Trade kwaliteit (goed instappen wordt beloond)
- Win streak bonus
- Progressieve drawdown straf
- Anti-churn (te veel handelen bestraft)
"""
import numpy as np
import pandas as pd
import gymnasium as gym
from gymnasium import spaces
from typing import Optional


class CryptoTradingEnv(gym.Env):
    metadata = {"render_modes": ["human"]}

    def __init__(
        self,
        df: pd.DataFrame,
        feature_columns: list[str],
        initial_capital: float = 10_000.0,
        transaction_fee: float = 0.001,
        window_size: int = 20,
        max_position_pct: float = 0.95,
        reward_scaling: float = 100.0,
    ):
        super().__init__()

        self.df = df.reset_index(drop=True)
        self.feature_columns = feature_columns
        self.initial_capital = initial_capital
        self.transaction_fee = transaction_fee
        self.window_size = window_size
        self.max_position_pct = max_position_pct
        self.reward_scaling = reward_scaling

        n_features = len(feature_columns) * window_size + 6
        self.observation_space = spaces.Box(
            low=-np.inf, high=np.inf, shape=(n_features,), dtype=np.float32
        )
        self.action_space = spaces.Discrete(3)  # 0=hold, 1=buy, 2=sell
        self.reset()

    def reset(self, seed: Optional[int] = None, options: Optional[dict] = None):
        super().reset(seed=seed)
        self.current_step = self.window_size
        self.capital = self.initial_capital
        self.position = 0.0
        self.entry_price = 0.0
        self.peak_value = self.initial_capital
        self.trade_history: list[dict] = []
        self.returns_history: list[float] = []
        self.holding_steps = 0
        self.consecutive_wins = 0
        self.consecutive_losses = 0
        return self._get_observation(), {}

    def step(self, action: int):
        price = self._current_price()
        value_before = self._portfolio_value(price)
        reward = 0.0
        info = {}

        # ── Actie uitvoeren ────────────────────────────────────────
        if action == 1:  # BUY
            if self.position == 0:
                invest = self.capital * self.max_position_pct
                self.position = (invest * (1 - self.transaction_fee)) / price
                self.capital -= invest
                self.entry_price = price
                self.holding_steps = 0
                info["trade"] = f"BUY {self.position:.6f} @ {price:.2f}"
                # Kwaliteitsbonus voor kopen in oversold zone
                reward += self._entry_quality_reward(price, action=1)
            else:
                reward -= 0.5  # Dubbele buy = straf

        elif action == 2:  # SELL
            if self.position > 0:
                proceeds = self.position * price * (1 - self.transaction_fee)
                pnl = proceeds - (self.position * self.entry_price)
                pnl_pct = pnl / (self.position * self.entry_price + 1e-8)
                self.capital += proceeds
                self.trade_history.append({
                    "type": "sell",
                    "entry": self.entry_price,
                    "exit": price,
                    "pnl": pnl,
                    "pnl_pct": pnl_pct,
                    "holding_steps": self.holding_steps,
                })
                # Win streak tracking
                if pnl_pct > 0:
                    self.consecutive_wins += 1
                    self.consecutive_losses = 0
                else:
                    self.consecutive_losses += 1
                    self.consecutive_wins = 0
                self.position = 0.0
                self.entry_price = 0.0
                info["trade"] = f"SELL @ {price:.2f} | PnL: {pnl_pct:.2%}"
            else:
                reward -= 0.5  # Short-sell zonder positie

        # ── Stap vooruit ───────────────────────────────────────────
        self.current_step += 1
        if self.position > 0:
            self.holding_steps += 1

        new_price = self._current_price()
        value_after = self._portfolio_value(new_price)

        # ── Reward berekening ──────────────────────────────────────
        reward += self._compute_reward(value_before, value_after, new_price)

        # ── Episode check ──────────────────────────────────────────
        done = self.current_step >= len(self.df) - 1
        truncated = value_after < self.initial_capital * 0.50

        info.update({
            "portfolio_value": value_after,
            "drawdown": self._drawdown(value_after),
            "trade_stats": self.get_trade_stats(),
        })

        return self._get_observation(), reward, done, truncated, info

    def _compute_reward(self, value_before: float, value_after: float, price: float) -> float:
        step_return = (value_after - value_before) / (value_before + 1e-8)
        self.returns_history.append(step_return)
        reward = 0.0

        # 1. Directe return component
        reward += step_return * self.reward_scaling

        # 2. Sortino ratio (rollend) — only penalizes downside
        if len(self.returns_history) >= 30:
            recent = np.array(self.returns_history[-60:])
            mean_ret = np.mean(recent)
            downside_dev = np.sqrt(np.mean(np.minimum(recent, 0) ** 2) + 1e-8)
            sortino = mean_ret / downside_dev
            reward += sortino * self.reward_scaling * 0.4

        # 3. Drawdown straf (progressief — hoe groter, hoe zwaarder)
        dd = self._drawdown(value_after)
        if dd > 0.05:
            reward -= (dd ** 1.5) * 25

        # 4. Win streak bonus
        if self.consecutive_wins >= 3:
            reward += 0.3 * min(self.consecutive_wins - 2, 3)

        # 5. Loss streak penalty
        if self.consecutive_losses >= 3:
            reward -= 0.3 * min(self.consecutive_losses - 2, 3)

        # 6. Anti-churn: te veel trades in korte tijd
        if len(self.trade_history) >= 10:
            recent_trades = len([t for t in self.trade_history[-10:] if t.get("type") == "sell"])
            if recent_trades > 6:
                reward -= 0.05 * (recent_trades - 6)

        # 7. Straf voor stilstaan — positie houden zonder beweging
        if self.position > 0 and self.holding_steps > 80:
            if self.entry_price > 0:
                unrealized_pct = (price - self.entry_price) / self.entry_price
                if abs(unrealized_pct) < 0.005:  # Minder dan 0.5% move in 80 stappen
                    reward -= 0.002 * (self.holding_steps - 80)

        return reward

    def _entry_quality_reward(self, price: float, action: int) -> float:
        start = max(0, self.current_step - 20)
        recent = self.df["close"].iloc[start:self.current_step]
        if len(recent) < 5:
            return 0.0
        low = recent.min()
        high = recent.max()
        rng = high - low + 1e-8
        if action == 1:  # Kopen — beloon instappen dicht bij laagste punt
            quality = 1.0 - (price - low) / rng
            return quality * 0.4
        else:  # Verkopen — beloon instappen dicht bij hoogste punt
            quality = (price - low) / rng
            return quality * 0.4

    def _drawdown(self, value: float) -> float:
        if value > self.peak_value:
            self.peak_value = value
        return (self.peak_value - value) / (self.peak_value + 1e-8)

    def _current_price(self) -> float:
        idx = min(self.current_step, len(self.df) - 1)
        return float(self.df["close"].iloc[idx])

    def _portfolio_value(self, price: float) -> float:
        return self.capital + self.position * price

    def _get_observation(self) -> np.ndarray:
        start = max(0, self.current_step - self.window_size)
        window = self.df[self.feature_columns].iloc[start:self.current_step]

        if len(window) < self.window_size:
            pad = np.zeros((self.window_size - len(window), len(self.feature_columns)))
            window_arr = np.vstack([pad, window.values])
        else:
            window_arr = window.values

        features = window_arr.flatten().astype(np.float32)

        price = self._current_price()
        total = self._portfolio_value(price)
        pos_pct = (self.position * price) / (total + 1e-8)
        pnl_pct = (total - self.initial_capital) / self.initial_capital
        dd = self._drawdown(total)
        hold_norm = min(self.holding_steps / 100.0, 1.0)
        streak_norm = self.consecutive_wins / 5.0 - self.consecutive_losses / 5.0

        portfolio_feats = np.array(
            [pos_pct, pnl_pct, dd, hold_norm, streak_norm, float(self.position > 0)],
            dtype=np.float32,
        )
        obs = np.concatenate([features, portfolio_feats])
        return np.nan_to_num(obs, nan=0.0, posinf=1.0, neginf=-1.0)

    def get_trade_stats(self) -> dict:
        sells = [t for t in self.trade_history if "pnl_pct" in t]
        if not sells:
            return {"total_trades": 0}
        pnls = [t["pnl_pct"] for t in sells]
        wins = [p for p in pnls if p > 0]
        losses = [p for p in pnls if p < 0]
        return {
            "total_trades": len(sells),
            "win_rate": len(wins) / len(pnls),
            "avg_win": float(np.mean(wins)) if wins else 0,
            "avg_loss": float(np.mean(losses)) if losses else 0,
            "profit_factor": abs(sum(wins) / sum(losses)) if losses else float("inf"),
            "max_pnl": max(pnls),
            "min_pnl": min(pnls),
            "sortino": self._compute_sortino(),
        }

    def _compute_sortino(self) -> float:
        if len(self.returns_history) < 10:
            return 0.0
        r = np.array(self.returns_history)
        downside = np.sqrt(np.mean(np.minimum(r, 0) ** 2) + 1e-8)
        return float(np.mean(r) / downside)

    def render(self):
        price = self._current_price()
        value = self._portfolio_value(price)
        pnl = (value - self.initial_capital) / self.initial_capital
        print(f"Stap {self.current_step:4d} | Prijs: {price:10.2f} | "
              f"Waarde: {value:10.2f} | PnL: {pnl:+.2%} | Positie: {self.position:.6f}")
