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
        if len(df) < 2:
            return Signal(0, 0.0, "EMA_Cross", "te weinig data")

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
    def __init__(self, lookback: int = 100):
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
    Beslist op basis van gecombineerde score met vaste drempel.
    Geen decay meer — inactiviteit is geen reden om slechte trades te nemen.
    """

    def __init__(self, boldness: float = 0.55):
        self.boldness = boldness  # 0-1, hoe avontuurlijk (verlaagd van 0.65)

    def on_trade_executed(self):
        pass  # Niet meer nodig zonder idle-tracking

    def adjust(self, score: float, regime_hint: int = 0, threshold_override: float = 0.0) -> tuple[int, float, float]:
        """Geeft (actie, confidence, drempel) terug. Drempel is regime-afhankelijk."""
        threshold = threshold_override if threshold_override > 0 else 0.20

        effective_score = score * (1 + self.boldness * 0.3)

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

    def __init__(self, strategy_names: list[str], lookback: int = 150, min_samples: int = 5):
        self.lookback = lookback
        self.min_samples = min_samples  # was 10 — snellere aanpassing bij slechte prestaties
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
        if len(hist) < self.min_samples:
            return 1.0
        # Exponentieel gewogen: recente prestaties wegen zwaarder (decay 0.94 per trade).
        # Gemini/Copilot: na een regime-switch moet de tracker snel kunnen bijsturen.
        n = len(hist)
        weights = np.array([0.94 ** (n - 1 - i) for i in range(n)])
        weights /= weights.sum()
        accuracy = float(np.dot(hist, weights))
        mult = 0.5 + (accuracy - 0.4) / 0.2
        return max(0.3, min(2.0, mult))

    def save(self) -> dict:
        """Geeft de huidige history terug als serialiseerbaar dict."""
        return {name: list(dq) for name, dq in self.history.items()}

    def load(self, data: dict):
        """Herstelt history uit eerder opgeslagen dict."""
        for name, values in data.items():
            if name in self.history:
                self.history[name] = deque(values, maxlen=self.lookback)


# Regime-specifieke gewichtsmultipliers per strategie (fijn-afstemming binnen actieve set)
_REGIME_STRATEGY_WEIGHTS: dict[str, dict[str, float]] = {
    "bull_trend": {
        "EMA_Cross": 1.4, "MACD": 1.3, "Breakout": 1.3, "Ichimoku": 1.3,
        "MarketStructure": 1.3, "SMC": 1.1, "Wyckoff": 1.0, "SR": 1.0,
        "VolumeProfile": 1.0, "Bollinger": 1.0, "RSI": 1.0, "Grid": 1.0,
    },
    "bear_trend": {
        "EMA_Cross": 1.4, "MACD": 1.3, "Breakout": 1.3, "Ichimoku": 1.3,
        "MarketStructure": 1.3, "SMC": 1.1, "Wyckoff": 1.0, "SR": 1.0,
        "VolumeProfile": 1.0, "Bollinger": 1.0, "RSI": 1.0, "Grid": 1.0,
    },
    "ranging": {
        "Bollinger": 1.6, "RSI": 1.5, "Grid": 1.5, "SR": 1.4,
        "VolumeProfile": 1.3, "Wyckoff": 1.2, "SMC": 1.0,
        "EMA_Cross": 1.0, "MACD": 1.0, "Breakout": 1.0, "MarketStructure": 1.0, "Ichimoku": 1.0,
    },
    "high_vol": {
        "SR": 1.2, "VolumeProfile": 1.2, "Wyckoff": 1.1, "SMC": 1.0, "MarketStructure": 1.0,
        "Bollinger": 1.0, "RSI": 1.0, "EMA_Cross": 1.0, "MACD": 1.0, "Ichimoku": 1.0,
        "Breakout": 1.0, "Grid": 1.0,
    },
    "accumulation": {
        "Wyckoff": 1.6, "VolumeProfile": 1.4, "SMC": 1.3, "SR": 1.2,
        "Bollinger": 1.1, "RSI": 1.1, "MarketStructure": 1.0,
        "EMA_Cross": 1.0, "MACD": 1.0, "Breakout": 1.0, "Ichimoku": 1.0, "Grid": 1.0,
    },
}

# Welke strategieën ACTIEF zijn per regime — inactieve worden volledig uitgeschakeld.
# Gemini/ChatGPT/Copilot: trend-strategieën in ranging = ruis; mean-reversion in trend = verlies.
_REGIME_ACTIVE_STRATEGIES: dict[str, set[str]] = {
    "bull_trend":   {"EMA_Cross", "MACD", "Breakout", "MarketStructure", "SMC", "Ichimoku", "SR", "Wyckoff"},
    "bear_trend":   {"EMA_Cross", "MACD", "Breakout", "MarketStructure", "SMC", "Ichimoku", "SR", "Wyckoff"},
    "ranging":      {"Bollinger", "RSI", "SR", "Grid", "VolumeProfile", "Wyckoff", "SMC"},
    "high_vol":     {"SMC", "Wyckoff", "MarketStructure", "SR", "VolumeProfile"},
    "accumulation": {"Wyckoff", "VolumeProfile", "SMC", "SR", "Bollinger", "RSI", "MarketStructure"},
}

# Regime-specifieke AI-gewichten: in ranging werkt AI beter dan lagging indicatoren.
# In trending domineren technische strategieën. In high_vol is AI onbetrouwbaar.
_REGIME_AI_WEIGHTS: dict[str, tuple[float, float]] = {
    # (rl_weight, lstm_weight)
    "bull_trend":   (0.08, 0.12),   # Technisch domineert — indicatoren werken goed in trend
    "bear_trend":   (0.08, 0.12),
    "ranging":      (0.10, 0.20),   # AI heeft moeite in ranging — minder gewicht dan technische S/R
    "high_vol":     (0.05, 0.08),   # AI faalt in chaos — minimale bijdrage
    "accumulation": (0.12, 0.20),   # Gebalanceerd
}

# Dynamische confidence-drempel per regime
# Bear_trend: position_mult=0.50 halveert de score, dus drempel moet lager zodat
# shorts bij sterke bearish confluence (6 strategieën) alsnog getriggerd worden.
# Berekening: raw=-0.326 → ×0.50 → -0.163 → ×1.165 = -0.190 → drempel 0.13 ✓
_REGIME_THRESHOLD: dict[str, float] = {
    "bull_trend":   0.15,   # Trend = duidelijk richting, iets soepeler
    "bear_trend":   0.10,   # Counter-trend filter vergroot netto score; drempel omlaag
    "ranging":      0.09,   # Squeeze/ranging = zwakke signalen; confluence bewaakt kwaliteit
    "high_vol":     0.35,   # Chaos = alleen sterke confluence trades
    "accumulation": 0.09,   # Squeeze = signalen structureel zwakker; confluence bewaakt kwaliteit
}


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
            (EMACrossStrategy(),               "EMA_Cross",      0.11),
            (BollingerMeanReversionStrategy(), "Bollinger",      0.09),
            (RSIMomentumStrategy(),            "RSI",            0.09),
            (MACDStrategy(),                   "MACD",           0.08),
            (BreakoutStrategy(),               "Breakout",       0.08),
            (SmartMoneyStrategy(),             "SMC",            0.11),
            (SupportResistanceStrategy(),      "SR",             0.08),
            (IchimokuStrategy(),               "Ichimoku",       0.07),
            (WyckoffStrategy(),                "Wyckoff",        0.09),
            (VolumeProfileStrategy(),          "VolumeProfile",  0.08),
            (MarketStructureStrategy(),        "MarketStructure",0.07),
            (GridTradingStrategy(),            "Grid",           0.05),
        ]

        strategy_names = [name for _, name, _ in self.strategies]
        self.weight_tracker = AdaptiveWeightTracker(strategy_names)
        self.brain = ConfidenceBrain()

    def update_weights(self, last_signals: dict[str, int], actual_return: float):
        """Aanroepen na elke gesloten trade om gewichten bij te werken."""
        self.weight_tracker.update(last_signals, actual_return)

    def get_strategy_stats(self) -> list[dict]:
        """Geeft per strategie: naam, gewicht-multiplier, accuraatheid en sample-count."""
        stats = []
        for _, name, base_weight in self.strategies:
            hist = list(self.weight_tracker.history.get(name, []))
            accuracy = sum(hist) / len(hist) if hist else None
            stats.append({
                "naam": name,
                "base_weight": base_weight,
                "gewicht_mult": round(self.weight_tracker.multiplier(name), 2),
                "accuracy": round(accuracy, 3) if accuracy is not None else None,
                "samples": len(hist),
            })
        return stats

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
        regime: str = "ranging",
        stat_arb_action: int = 0,
        stat_arb_confidence: float = 0.0,
        stat_arb_reason: str = "",
    ) -> dict:
        total_score = 0.0
        details = []
        last_signals: dict[str, int] = {}
        _regime_wts    = _REGIME_STRATEGY_WEIGHTS.get(regime, {})
        _active_strats = _REGIME_ACTIVE_STRATEGIES.get(regime, None)  # None = alles actief

        # Regime-specifieke AI-gewichten — in ranging werkt AI beter dan indicatoren
        rl_w, lstm_w = _REGIME_AI_WEIGHTS.get(regime, (self.rl_weight, self.lstm_weight))
        # Als LSTM_WEIGHT=0.0 in config → volledig uitschakelen (ook regime-override)
        if self.lstm_weight == 0.0:
            lstm_w = 0.0
        strat_w = 1.0 - rl_w - lstm_w

        # ── Strategieën met adaptieve + regime-specifieke gewichten ─
        for strategy, name, base_weight in self.strategies:
            adapt_mult = self.weight_tracker.multiplier(name)

            # Inactieve strategieën worden volledig uitgeschakeld voor dit regime.
            # Ze verschijnen wel in details zodat het dashboard ze toont.
            if _active_strats is not None and name not in _active_strats:
                details.append({
                    "naam": name, "actie": 0, "confidence": 0.0,
                    "bijdrage": 0.0, "reden": "inactief in dit regime",
                    "gewicht_mult": round(adapt_mult, 2),
                })
                continue

            try:
                sig = strategy.signal(df)
                action = sig.action if hasattr(sig, "action") else 0
                confidence = sig.confidence if hasattr(sig, "confidence") else 0.0
                reason = sig.reason if hasattr(sig, "reason") else ""
            except Exception:
                action, confidence, reason = 0, 0.0, "fout"

            regime_w = _regime_wts.get(name, 1.0)
            weight = base_weight * adapt_mult * regime_w
            weighted = action * confidence * weight * strat_w
            # In trending regime: counter-trend bijdragen zijn ruis en worden gefilterd.
            # MACD bullish crossover in bear_trend blokkeert anders legitieme short-scores.
            if regime == "bear_trend" and action > 0:
                weighted = 0.0
            elif regime == "bull_trend" and action < 0:
                weighted = 0.0
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

        # ── RL Agent ───────────────────────────────────────────────
        rl_score = rl_action * rl_confidence * rl_w
        total_score += rl_score
        details.append({
            "naam": "RL_Agent", "actie": rl_action,
            "confidence": rl_confidence, "bijdrage": rl_score,
            "reden": f"Reinforcement Learning (gewicht {rl_w:.0%})",
        })

        # ── LSTM voorspeller ───────────────────────────────────────
        # Alleen bijdragen als LSTM voldoende zeker is — anders ruis
        # 3-klasse model: random baseline = 0.33, bruikbaar signaal vanaf ~0.42
        # In squeeze (accumulation/ranging): max confidence ~0.35-0.38 door lage variantie →
        # drempel verlaagd naar 0.35 zodat LSTM nog meepraat; bijdrage is max ±0.07, te klein om
        # alleen een trade te triggeren maar helpt als tie-breaker bij confluente signalen.
        _lstm_min_conf = 0.35 if regime in ("accumulation", "ranging") else 0.42
        if lstm_confidence < _lstm_min_conf:
            lstm_action = 0
            lstm_confidence = 0.0
        lstm_score = lstm_action * lstm_confidence * lstm_w
        total_score += lstm_score
        details.append({
            "naam": "LSTM", "actie": lstm_action,
            "confidence": lstm_confidence, "bijdrage": lstm_score,
            "reden": f"LSTM prijsrichting voorspelling (gewicht {lstm_w:.0%})",
        })

        # ── Sentiment modifier (±15% aanpassing) ──────────────────
        # Sentiment versterkt het signaal maar beslist niet alleen
        # In trending regime: counter-trend sentiment is ruis
        if abs(sentiment_score) > 0.15:
            sentiment_boost = sentiment_score * 0.15
            if (regime == "bear_trend" and sentiment_score > 0) or \
               (regime == "bull_trend" and sentiment_score < 0):
                sentiment_boost = 0.0
            total_score += sentiment_boost
            details.append({
                "naam": "Sentiment", "actie": int(np.sign(sentiment_score)),
                "confidence": abs(sentiment_score), "bijdrage": sentiment_boost,
                "reden": f"Fear & Greed + nieuws: {sentiment_score:+.2f}",
            })

        # ── Order book modifier ────────────────────────────────────
        # In trending regime: counter-trend order book ruis wordt gefilterd
        if ob_confidence > 0.2:
            ob_boost = ob_signal * ob_confidence * 0.10
            if (regime == "bear_trend" and ob_signal > 0) or \
               (regime == "bull_trend" and ob_signal < 0):
                ob_boost = 0.0
            total_score += ob_boost
            details.append({
                "naam": "OrderBook", "actie": ob_signal,
                "confidence": ob_confidence, "bijdrage": ob_boost,
                "reden": f"Bid/Ask onbalans: {ob_signal:+d}",
            })

        # ── StatArb modifier ──────────────────────────────────────
        # Alleen actief in ranging/accumulation/high_vol — niet in trending markten
        # (z-score "duur" in trend = gewoon trending up, geen mean-reversion verwacht)
        _stat_arb_active = regime in ("ranging", "accumulation", "high_vol")
        if _stat_arb_active and stat_arb_confidence > 0.30 and stat_arb_action != 0:
            sa_boost = stat_arb_action * stat_arb_confidence * 0.15
            total_score += sa_boost
            details.append({
                "naam": "StatArb",
                "actie": stat_arb_action,
                "confidence": stat_arb_confidence,
                "bijdrage": sa_boost,
                "reden": stat_arb_reason or f"Stat arbitrage paar-divergentie",
            })
        elif stat_arb_action != 0:
            details.append({
                "naam": "StatArb",
                "actie": stat_arb_action,
                "confidence": stat_arb_confidence,
                "bijdrage": 0.0,
                "reden": (stat_arb_reason or "") + " [inactief in trend-regime]",
            })

        # ── Eigen brein met regime-specifieke drempel ───────────────
        # regime_mult wordt NIET meer op de score toegepast — het halveert
        # de score vóór threshold-vergelijking terwijl het ook al positiebepaling halveert.
        # Dubbel effect: in ranging (-0.12 score) → ×0.80 → -0.096 < drempel 0.22 → nooit trade.
        # regime_mult gaat alleen nog naar risk/manager voor positiebepaling.
        regime_hint = 1 if regime_mult > 1.0 else (-1 if regime_mult < 0.7 else 0)
        regime_threshold = _REGIME_THRESHOLD.get(regime, 0.20)
        final_action, confidence, threshold = self.brain.adjust(total_score, regime_hint, regime_threshold)

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
