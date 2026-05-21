"""
Monster Crypto Trading Environment — long én short ondersteuning.

Acties:
  0 = wachten (hold)
  1 = long gaan (kopen)
  2 = short gaan (shorten)
  3 = positie sluiten (close)

Reward gebaseerd op:
  - Sortino ratio (alleen neerwaartse volatiliteit bestraft)
  - Instap- en uitstapkwaliteit (goed timen wordt beloond)
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
        initial_capital: float = 1_000.0,
        transaction_fee: float = 0.001,
        window_size: int = 20,
        max_position_pct: float = 0.80,
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

        # +8 portfolio features: pos_pct, pnl_pct, dd, hold_norm, streak_norm,
        #                         heeft_long, heeft_short, geen_positie
        n_features = len(feature_columns) * window_size + 8
        self.observation_space = spaces.Box(
            low=-np.inf, high=np.inf, shape=(n_features,), dtype=np.float32
        )
        self.action_space = spaces.Discrete(4)  # 0=hold, 1=long, 2=short, 3=close
        self.reset()

    def reset(self, seed: Optional[int] = None, options: Optional[dict] = None):
        super().reset(seed=seed)
        self.current_step = self.window_size
        self.capital = self.initial_capital
        self.position_size = 0.0    # Aantal crypto (altijd positief)
        self.position_dir = 0       # +1 = long, -1 = short, 0 = geen
        self.entry_price = 0.0
        self.margin = 0.0           # Gereserveerde marge voor short
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
        if action == 1:  # LONG
            if self.position_dir == 0:
                invest = self.capital * self.max_position_pct
                fee = invest * self.transaction_fee
                self.position_size = (invest - fee) / price
                self.capital -= invest
                self.position_dir = 1
                self.entry_price = price
                self.holding_steps = 0
                reward += self._entry_quality_reward(price, direction=1)
                info["trade"] = f"LONG {self.position_size:.6f} @ {price:.2f}"
            else:
                reward -= 0.5  # Al in een positie

        elif action == 2:  # SHORT
            if self.position_dir == 0:
                invest = self.capital * self.max_position_pct
                fee = invest * self.transaction_fee
                self.position_size = (invest - fee) / price
                self.capital -= invest
                self.margin = invest   # Marge gereserveerd voor short
                self.position_dir = -1
                self.entry_price = price
                self.holding_steps = 0
                reward += self._entry_quality_reward(price, direction=-1)
                info["trade"] = f"SHORT {self.position_size:.6f} @ {price:.2f}"
            else:
                reward -= 0.5  # Al in een positie

        elif action == 3:  # CLOSE
            if self.position_dir == 1:  # Sluit long
                proceeds = self.position_size * price * (1 - self.transaction_fee)
                pnl = proceeds - (self.position_size * self.entry_price)
                pnl_pct = pnl / (self.position_size * self.entry_price + 1e-8)
                self.capital += proceeds
                reward += self._exit_quality_reward(price, direction=1)
                self._record_trade(pnl, pnl_pct)
                info["trade"] = f"CLOSE LONG @ {price:.2f} | PnL: {pnl_pct:.2%}"
                self._reset_position()

            elif self.position_dir == -1:  # Sluit short (cover)
                # Koopprijs om short te sluiten
                cost = self.position_size * price * (1 + self.transaction_fee)
                # PnL = wat we kregen bij shorten - wat we nu terugbetalen
                pnl = self.position_size * (self.entry_price - price) - (
                    cost - self.position_size * price
                )
                pnl_pct = pnl / (self.margin + 1e-8)
                self.capital += self.margin + pnl
                reward += self._exit_quality_reward(price, direction=-1)
                self._record_trade(pnl, pnl_pct)
                info["trade"] = f"COVER SHORT @ {price:.2f} | PnL: {pnl_pct:.2%}"
                self._reset_position()
            else:
                reward -= 0.5  # Geen positie om te sluiten

        # ── Stap vooruit ───────────────────────────────────────────
        self.current_step += 1
        if self.position_dir != 0:
            self.holding_steps += 1

        new_price = self._current_price()
        value_after = self._portfolio_value(new_price)

        # ── Reward berekening ──────────────────────────────────────
        reward += self._compute_reward(value_before, value_after, new_price)

        # ── Episode check ──────────────────────────────────────────
        done = self.current_step >= len(self.df) - 1
        truncated = value_after < self.initial_capital * 0.50  # Gestopt bij -50%

        info.update({
            "portfolio_value": value_after,
            "drawdown": self._drawdown(value_after),
            "trade_stats": self.get_trade_stats(),
        })

        return self._get_observation(), reward, done, truncated, info

    def _reset_position(self):
        self.position_size = 0.0
        self.position_dir = 0
        self.entry_price = 0.0
        self.margin = 0.0
        self.holding_steps = 0

    def _record_trade(self, pnl: float, pnl_pct: float):
        self.trade_history.append({
            "pnl": pnl,
            "pnl_pct": pnl_pct,
            "holding_steps": self.holding_steps,
            "step": self.current_step,
        })
        if pnl_pct > 0:
            self.consecutive_wins += 1
            self.consecutive_losses = 0
        else:
            self.consecutive_losses += 1
            self.consecutive_wins = 0

    def _compute_reward(self, value_before: float, value_after: float, price: float) -> float:
        step_return = (value_after - value_before) / (value_before + 1e-8)
        self.returns_history.append(step_return)
        reward = 0.0

        # 1. Directe return
        reward += step_return * self.reward_scaling

        # 2. Sortino ratio (rollend) — alleen downside bestraft
        if len(self.returns_history) >= 30:
            recent = np.array(self.returns_history[-60:])
            mean_ret = np.mean(recent)
            downside_dev = np.sqrt(np.mean(np.minimum(recent, 0) ** 2) + 1e-8)
            sortino = mean_ret / downside_dev
            reward += sortino * self.reward_scaling * 0.4

        # 3. Drawdown straf (progressief)
        dd = self._drawdown(value_after)
        if dd > 0.05:
            reward -= (dd ** 1.5) * 25

        # 4. Win streak bonus
        if self.consecutive_wins >= 3:
            reward += 0.3 * min(self.consecutive_wins - 2, 3)

        # 5. Loss streak straf
        if self.consecutive_losses >= 3:
            reward -= 0.3 * min(self.consecutive_losses - 2, 3)

        # 6. Anti-churn: meer dan 4 trades in de laatste 20 stappen
        if len(self.trade_history) >= 4:
            recent_steps = self.current_step - 20
            recent_count = sum(1 for t in self.trade_history if t.get("step", 0) >= recent_steps)
            if recent_count > 4:
                reward -= 0.05 * (recent_count - 4)

        # 7. Straf voor stilstaan zonder beweging
        if self.position_dir != 0 and self.holding_steps > 80:
            if self.entry_price > 0:
                unrealized_pct = abs(price - self.entry_price) / self.entry_price
                if unrealized_pct < 0.005:
                    reward -= 0.002 * (self.holding_steps - 80)

        return reward

    def _entry_quality_reward(self, price: float, direction: int) -> float:
        """Beloon instappen op het juiste moment: long dicht bij low, short dicht bij high."""
        start = max(0, self.current_step - 20)
        recent = self.df["close"].iloc[start:self.current_step]
        if len(recent) < 5:
            return 0.0
        low = recent.min()
        high = recent.max()
        rng = high - low + 1e-8
        if direction == 1:   # Long: beloon instappen dicht bij laagste
            return (1.0 - (price - low) / rng) * 0.4
        else:                # Short: beloon instappen dicht bij hoogste
            return ((price - low) / rng) * 0.4

    def _exit_quality_reward(self, price: float, direction: int) -> float:
        """Beloon uitstappen op het juiste moment: long sluiten dicht bij high, short dicht bij low."""
        start = max(0, self.current_step - 20)
        recent = self.df["close"].iloc[start:self.current_step]
        if len(recent) < 5:
            return 0.0
        low = recent.min()
        high = recent.max()
        rng = high - low + 1e-8
        if direction == 1:   # Long sluiten: beloon uitstappen dicht bij hoogste
            return ((price - low) / rng) * 0.4
        else:                # Short sluiten: beloon uitstappen dicht bij laagste
            return (1.0 - (price - low) / rng) * 0.4

    def _drawdown(self, value: float) -> float:
        if value > self.peak_value:
            self.peak_value = value
        return (self.peak_value - value) / (self.peak_value + 1e-8)

    def _current_price(self) -> float:
        idx = min(self.current_step, len(self.df) - 1)
        return float(self.df["close"].iloc[idx])

    def _portfolio_value(self, price: float) -> float:
        if self.position_dir == 1:    # Long
            return self.capital + self.position_size * price
        elif self.position_dir == -1: # Short: marge + ongerealiseerde winst/verlies
            unrealized = self.position_size * (self.entry_price - price)
            return self.capital + self.margin + unrealized
        return self.capital

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
        pos_pct = (self.position_size * price) / (total + 1e-8) if self.position_dir != 0 else 0.0
        pnl_pct = (total - self.initial_capital) / self.initial_capital
        dd = self._drawdown(total)
        hold_norm = min(self.holding_steps / 100.0, 1.0)
        streak_norm = self.consecutive_wins / 5.0 - self.consecutive_losses / 5.0

        portfolio_feats = np.array([
            pos_pct,
            pnl_pct,
            dd,
            hold_norm,
            streak_norm,
            float(self.position_dir == 1),   # Heeft long positie
            float(self.position_dir == -1),  # Heeft short positie
            float(self.position_dir == 0),   # Geen positie (vrij)
        ], dtype=np.float32)

        obs = np.concatenate([features, portfolio_feats])
        return np.nan_to_num(obs, nan=0.0, posinf=1.0, neginf=-1.0)

    def get_trade_stats(self) -> dict:
        trades = [t for t in self.trade_history if "pnl_pct" in t]
        if not trades:
            return {"total_trades": 0}
        pnls = [t["pnl_pct"] for t in trades]
        wins = [p for p in pnls if p > 0]
        losses = [p for p in pnls if p < 0]
        return {
            "total_trades": len(trades),
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
        dir_label = {1: "LONG", -1: "SHORT", 0: "VRIJ"}.get(self.position_dir, "?")
        print(f"Stap {self.current_step:4d} | Prijs: {price:10.2f} | "
              f"Waarde: {value:10.2f} | PnL: {pnl:+.2%} | Positie: {dir_label}")
