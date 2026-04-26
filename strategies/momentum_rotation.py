"""
Momentum Rotatie — switcht automatisch naar de best presterende coin.
Professionele fondsen doen dit ook: "ride the winners, cut the losers."
"""
import time
import pandas as pd
from dataclasses import dataclass


@dataclass
class RotationAdvice:
    best_symbol: str
    worst_symbol: str
    scores: dict[str, float]
    should_rotate: bool
    reason: str


class MomentumRotation:
    def __init__(self, lookback_hours: int = 168):  # 7 dagen
        self.lookback_hours = lookback_hours
        self._cache: tuple[RotationAdvice | None, float] = (None, 0)
        self._cache_ttl = 3600  # 1 uur

    def analyze(self, symbol_dfs: dict[str, pd.DataFrame]) -> RotationAdvice:
        cached, ts = self._cache
        if cached and (time.time() - ts) < self._cache_ttl:
            return cached

        scores = {}
        for symbol, df in symbol_dfs.items():
            if len(df) < 24:
                continue
            scores[symbol] = self._momentum_score(df)

        if not scores:
            return RotationAdvice("", "", {}, False, "geen data")

        best = max(scores, key=scores.get)
        worst = min(scores, key=scores.get)

        # Rotatie aanbevolen als verschil > 5%
        spread = scores[best] - scores[worst]
        should_rotate = spread > 0.05 and scores[best] > 0

        advice = RotationAdvice(
            best_symbol=best,
            worst_symbol=worst,
            scores=scores,
            should_rotate=should_rotate,
            reason=(f"Beste performer: {best} ({scores[best]:+.1%}) | "
                    f"Slechtste: {worst} ({scores[worst]:+.1%})"),
        )
        self._cache = (advice, time.time())
        return advice

    def _momentum_score(self, df: pd.DataFrame) -> float:
        close = df["close"]
        if len(close) < 2:
            return 0.0

        # Gewogen momentum: recente prestatie telt zwaarder
        ret_1d  = (close.iloc[-1] - close.iloc[-24]) / close.iloc[-24]  if len(close) >= 24  else 0
        ret_3d  = (close.iloc[-1] - close.iloc[-72]) / close.iloc[-72]  if len(close) >= 72  else 0
        ret_7d  = (close.iloc[-1] - close.iloc[-168]) / close.iloc[-168] if len(close) >= 168 else 0

        # RSI component
        rsi = df["rsi_14"].iloc[-1] if "rsi_14" in df.columns else 50
        rsi_score = (rsi - 50) / 100

        return ret_1d * 0.40 + ret_3d * 0.30 + ret_7d * 0.20 + rsi_score * 0.10
