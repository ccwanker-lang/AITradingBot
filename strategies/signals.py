"""
Strategie signalen — EMA, Bollinger, RSI, MACD, Breakout, SMC, S/R, Ichimoku.
Adaptieve gewichten: strategieën die presteren krijgen meer gewicht.
"""
import numpy as np
import pandas as pd
from dataclasses import dataclass, field
from collections import deque


@dataclass
class Signal:
    action: int       # +1 buy, -1 sell, 0 hold
    confidence: float # 0.0 - 1.0
    name: str
    reason: str


class EMACrossStrategy:
    def __init__(self, fast: int = 9, slow: int = 21):
        self.fast = fast
        self.slow = slow

    def signal(self, df: pd.DataFrame) -> Signal:
        fc, sc = f"ema_{self.fast}", f"ema_{self.slow}"
        if fc not in df.columns or sc not in df.columns:
            return Signal(0, 0.0, "EMA_Cross", "kolommen ontbreken")

        cur = df[fc].iloc[-1] - df[sc].iloc[-1]
        prv = df[fc].iloc[-2] - df[sc].iloc[-2]
        strength = abs(cur) / (df["close"].iloc[-1] + 1e-8)

        if cur > 0 and prv <= 0:
            return Signal(1, min(strength * 60, 0.95), "EMA_Cross",
                          f"EMA{self.fast} kruist boven EMA{self.slow}")
        if cur < 0 and prv >= 0:
            return Signal(-1, min(strength * 60, 0.95), "EMA_Cross",
                          f"EMA{self.fast} kruist onder EMA{self.slow}")
        if cur > 0:
            return Signal(1, min(strength * 35, 0.55), "EMA_Cross", "Bullish trend")
        return Signal(-1, min(strength * 35, 0.55), "EMA_Cross", "Bearish trend")


class BollingerMeanReversionStrategy:
    def signal(self, df: pd.DataFrame) -> Signal:
        if "bb_pct" not in df.columns:
            return Signal(0, 0.0, "Bollinger", "kolommen ontbreken")

        bb_pct = df["bb_pct"].iloc[-1]
        rsi = df["rsi_14"].iloc[-1] if "rsi_14" in df.columns else 50
        bb_width = df.get("bb_width", pd.Series([0.04])).iloc[-1]
        is_squeeze = bb_width < df["bb_width"].quantile(0.2) if "bb_width" in df.columns else False

        if bb_pct < 0.05 and rsi < 35:
            conf = (1 - bb_pct) * (1 - rsi / 100) * (1.3 if is_squeeze else 1.0)
            return Signal(1, min(conf, 1.0), "Bollinger",
                          f"Oversold: BB={bb_pct:.2f} RSI={rsi:.0f}")
        if bb_pct > 0.95 and rsi > 65:
            conf = bb_pct * (rsi / 100) * (1.3 if is_squeeze else 1.0)
            return Signal(-1, min(conf, 1.0), "Bollinger",
                          f"Overbought: BB={bb_pct:.2f} RSI={rsi:.0f}")
        return Signal(0, 0.2, "Bollinger", "Neutrale zone")


class RSIMomentumStrategy:
    def __init__(self, oversold: int = 30, overbought: int = 70):
        self.oversold = oversold
        self.overbought = overbought

    def signal(self, df: pd.DataFrame) -> Signal:
        if "rsi_14" not in df.columns or len(df) < 6:
            return Signal(0, 0.0, "RSI", "kolommen ontbreken")

        rsi = df["rsi_14"].iloc[-1]
        rsi_prev = df["rsi_14"].iloc[-2]

        price_higher = df["close"].iloc[-1] > df["close"].iloc[-5]
        rsi_lower = rsi < df["rsi_14"].iloc[-5]
        bearish_div = price_higher and rsi_lower

        price_lower = df["close"].iloc[-1] < df["close"].iloc[-5]
        rsi_higher = rsi > df["rsi_14"].iloc[-5]
        bullish_div = price_lower and rsi_higher

        if rsi < self.oversold and rsi > rsi_prev:
            conf = (self.oversold - rsi) / self.oversold * (1.4 if bullish_div else 1.0)
            return Signal(1, min(conf, 1.0), "RSI",
                          f"Oversold recovery: {rsi:.0f}" + (" +div" if bullish_div else ""))
        if rsi > self.overbought and rsi < rsi_prev:
            conf = (rsi - self.overbought) / (100 - self.overbought) * (1.4 if bearish_div else 1.0)
            return Signal(-1, min(conf, 1.0), "RSI",
                          f"Overbought pullback: {rsi:.0f}" + (" +div" if bearish_div else ""))
        return Signal(0, 0.1, "RSI", f"RSI neutraal: {rsi:.0f}")


class MACDStrategy:
    def signal(self, df: pd.DataFrame) -> Signal:
        if "macd_diff" not in df.columns:
            return Signal(0, 0.0, "MACD", "kolommen ontbreken")

        hist = df["macd_diff"].iloc[-1]
        hist_prev = df["macd_diff"].iloc[-2]
        change = hist - hist_prev

        if hist > 0 and hist_prev <= 0:
            return Signal(1, 0.75, "MACD", "MACD bullish crossover")
        if hist < 0 and hist_prev >= 0:
            return Signal(-1, 0.75, "MACD", "MACD bearish crossover")
        if hist > 0 and change > 0:
            return Signal(1, min(abs(change) * 120, 0.80), "MACD", "MACD histogram groeit")
        if hist < 0 and change < 0:
            return Signal(-1, min(abs(change) * 120, 0.80), "MACD", "MACD histogram daalt")
        return Signal(0, 0.1, "MACD", "MACD onduidelijk")


class BreakoutStrategy:
    def __init__(self, lookback: int = 20):
        self.lookback = lookback

    def signal(self, df: pd.DataFrame) -> Signal:
        if len(df) < self.lookback + 2:
            return Signal(0, 0.0, "Breakout", "te weinig data")

        recent = df.iloc[-(self.lookback + 1):-1]
        resistance = recent["high"].max()
        support = recent["low"].min()
        close = df["close"].iloc[-1]
        vol_ratio = df["volume_ratio"].iloc[-1] if "volume_ratio" in df.columns else 1.0
        atr = df["atr_14"].iloc[-1] if "atr_14" in df.columns else (resistance - support) * 0.1

        if close > resistance + atr * 0.1 and vol_ratio > 1.5:
            conf = min((close - resistance) / atr * vol_ratio * 0.3, 1.0)
            return Signal(1, conf, "Breakout",
                          f"Uitbraak boven {resistance:.2f} Vol={vol_ratio:.1f}x")
        if close < support - atr * 0.1 and vol_ratio > 1.5:
            conf = min((support - close) / atr * vol_ratio * 0.3, 1.0)
            return Signal(-1, conf, "Breakout",
                          f"Uitbraak onder {support:.2f} Vol={vol_ratio:.1f}x")
        return Signal(0, 0.1, "Breakout", "Consolidatie")


class ConfidenceBrain:
    """
    Het eigen brein van de bot — zorgt dat hij ALTIJD een beslissing neemt.
    Hoe langer er niet gehandeld wordt, hoe meer risico hij durft te nemen.
    Heeft altijd een mening: bullish, bearish, of neutraal — nooit bevroren.
    """

    def __init__(self, boldness: float = 0.65, max_idle_hours: float = 8.0):
        self.boldness = boldness          # 0-1, hoe avontuurlijk
        self.max_idle_hours = max_idle_hours
        self._last_trade_time: float = 0
        self._trade_count: int = 0

    def on_trade_executed(self):
        import time
        self._last_trade_time = time.time()
        self._trade_count += 1

    def adjust(self, score: float, regime_hint: int = 0) -> tuple[int, float, float]:
        """
        Geeft (actie, confidence, drempel) terug.
        Verlaagt drempel naarmate er langer niet gehandeld is.
        Heeft altijd een mening gebaseerd op het sterkste signaal.
        """
        import time
        idle_hours = (time.time() - self._last_trade_time) / 3600 if self._last_trade_time else 0
        idle_factor = min(idle_hours / self.max_idle_hours, 1.0)

        # Drempel daalt bij lang niets doen (0.12 → 0.05)
        threshold = 0.12 * (1 - idle_factor * 0.60)

        # Boldness verhoogt effectieve score
        effective_score = score * (1 + self.boldness * 0.3)

        # Als score zwak maar er is al 6+ uur niet gehandeld:
        # neem de richting van regime als hint
        if abs(effective_score) < threshold * 1.5 and idle_hours > 6 and regime_hint != 0:
            effective_score += regime_hint * threshold * 0.8

        if effective_score > threshold:
            action = 1
        elif effective_score < -threshold:
            action = -1
        else:
            action = 0

        confidence = min(abs(effective_score) * 2.5, 1.0)
        return action, confidence, threshold


class AdaptiveWeightTracker:
    """Volgt prestaties per strategie en past gewichten automatisch aan."""

    def __init__(self, strategy_names: list[str], lookback: int = 40):
        self.lookback = lookback
        self.history: dict[str, deque] = {
            name: deque(maxlen=lookback) for name in strategy_names
        }

    def update(self, signals: dict[str, int], actual_return: float):
        for name, sig in signals.items():
            if name in self.history and sig != 0:
                correct = (sig * actual_return) > 0
                self.history[name].append(1.0 if correct else 0.0)

    def multiplier(self, name: str) -> float:
        hist = list(self.history.get(name, []))
        if len(hist) < 10:
            return 1.0
        accuracy = sum(hist) / len(hist)
        # 0.4 accuracy → 0.5x gewicht | 0.6 accuracy → 1.5x gewicht
        mult = 0.5 + (accuracy - 0.4) / 0.2
        return max(0.3, min(2.0, mult))


class SignalCombiner:
    """
    Combineert alle signalen: traditionele strategieën + SMC + S/R + Ichimoku
    + RL + LSTM + sentiment + orderbook, met adaptieve gewichten.
    """

    def __init__(self, rl_weight: float = 0.30, lstm_weight: float = 0.20):
        self.rl_weight = rl_weight
        self.lstm_weight = lstm_weight
        self.strat_weight = 1.0 - rl_weight - lstm_weight

        from strategies.smart_money import SmartMoneyStrategy
        from strategies.support_resistance import SupportResistanceStrategy
        from strategies.ichimoku import IchimokuStrategy
        from strategies.wyckoff import WyckoffStrategy
        from strategies.volume_profile import VolumeProfileStrategy
        from strategies.market_structure import MarketStructureStrategy
        from strategies.grid_trading import GridTradingStrategy

        self.strategies = [
            (EMACrossStrategy(),               "EMA_Cross",      0.12),
            (BollingerMeanReversionStrategy(), "Bollinger",      0.10),
            (RSIMomentumStrategy(),            "RSI",            0.10),
            (MACDStrategy(),                   "MACD",           0.08),
            (BreakoutStrategy(),               "Breakout",       0.08),
            (SmartMoneyStrategy(),             "SMC",            0.12),
            (SupportResistanceStrategy(),      "SR",             0.08),
            (IchimokuStrategy(),               "Ichimoku",       0.07),
            (WyckoffStrategy(),                "Wyckoff",        0.10),
            (VolumeProfileStrategy(),          "VolumeProfile",  0.08),
            (MarketStructureStrategy(),        "MarketStructure",0.07),
        ]

        strategy_names = [name for _, name, _ in self.strategies]
        self.weight_tracker = AdaptiveWeightTracker(strategy_names)
        self.brain = ConfidenceBrain()

    def update_weights(self, last_signals: dict[str, int], actual_return: float):
        """Aanroepen na elke gesloten trade om gewichten bij te werken."""
        self.weight_tracker.update(last_signals, actual_return)

    def combine(
        self,
        df: pd.DataFrame,
        rl_action: int = 0,
        rl_confidence: float = 0.0,
        lstm_action: int = 0,
        lstm_confidence: float = 0.0,
        sentiment_score: float = 0.0,
        ob_signal: int = 0,
        ob_confidence: float = 0.0,
        regime_mult: float = 1.0,
    ) -> dict:
        total_score = 0.0
        details = []
        last_signals: dict[str, int] = {}

        # ── Strategieën met adaptieve gewichten ────────────────────
        for strategy, name, base_weight in self.strategies:
            try:
                sig = strategy.signal(df)
                action = sig.action if hasattr(sig, "action") else getattr(sig, "action", 0)
                confidence = sig.confidence if hasattr(sig, "confidence") else 0.0
                reason = sig.reason if hasattr(sig, "reason") else ""
            except Exception:
                action, confidence, reason = 0, 0.0, "fout"

            adapt_mult = self.weight_tracker.multiplier(name)
            weight = base_weight * adapt_mult
            weighted = action * confidence * weight * self.strat_weight
            total_score += weighted
            last_signals[name] = action
            details.append({
                "naam": name,
                "actie": action,
                "confidence": confidence,
                "bijdrage": weighted,
                "reden": reason,
                "gewicht_mult": round(adapt_mult, 2),
            })

        # ── RL Agent (30%) ─────────────────────────────────────────
        rl_score = rl_action * rl_confidence * self.rl_weight
        total_score += rl_score
        details.append({
            "naam": "RL_Agent", "actie": rl_action,
            "confidence": rl_confidence, "bijdrage": rl_score,
            "reden": "Reinforcement Learning",
        })

        # ── LSTM voorspeller (20%) ─────────────────────────────────
        lstm_score = lstm_action * lstm_confidence * self.lstm_weight
        total_score += lstm_score
        details.append({
            "naam": "LSTM", "actie": lstm_action,
            "confidence": lstm_confidence, "bijdrage": lstm_score,
            "reden": "LSTM prijsrichting voorspelling",
        })

        # ── Sentiment modifier (±15% aanpassing) ──────────────────
        # Sentiment versterkt het signaal maar beslist niet alleen
        if abs(sentiment_score) > 0.15:
            sentiment_boost = sentiment_score * 0.15
            total_score += sentiment_boost
            details.append({
                "naam": "Sentiment", "actie": int(np.sign(sentiment_score)),
                "confidence": abs(sentiment_score), "bijdrage": sentiment_boost,
                "reden": f"Fear & Greed + nieuws: {sentiment_score:+.2f}",
            })

        # ── Order book modifier ────────────────────────────────────
        if ob_confidence > 0.2:
            ob_boost = ob_signal * ob_confidence * 0.10
            total_score += ob_boost
            details.append({
                "naam": "OrderBook", "actie": ob_signal,
                "confidence": ob_confidence, "bijdrage": ob_boost,
                "reden": f"Bid/Ask onbalans: {ob_signal:+d}",
            })

        # ── Regime aanpassing ──────────────────────────────────────
        total_score *= regime_mult

        # ── Eigen brein — nooit bevriezen ──────────────────────────
        regime_hint = 1 if regime_mult > 1.0 else (-1 if regime_mult < 0.7 else 0)
        final_action, confidence, threshold = self.brain.adjust(total_score, regime_hint)

        if final_action != 0:
            self.brain.on_trade_executed()

        return {
            "actie": final_action,
            "score": total_score,
            "confidence": confidence,
            "threshold_used": threshold,
            "details": details,
            "last_signals": last_signals,
        }
