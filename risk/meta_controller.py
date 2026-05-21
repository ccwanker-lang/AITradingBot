"""
Meta Controller — bot beoordeelt zijn eigen recente prestaties en schalt posities
automatisch terug tijdens slechte periodes. Gradueel (niet binair zoals circuit breaker).

Throttle-niveaus:
  1.00 = normaal
  0.75 = voorzichtig (slechte week)
  0.50 = defensief (verliesstreak of weekend)
  0.25 = minimaal (ernstige drawdown of negatieve expectancy)
  0.00 = pauze (wordt afgehandeld door circuit breaker, niet hier)
"""
from __future__ import annotations
import json
import time as _time
from collections import defaultdict
from datetime import datetime, timedelta
from pathlib import Path
from typing import Optional


class MetaController:
    def __init__(self, trades_path: str = "logs/trades.json"):
        self.trades_path = Path(trades_path)
        self._cache: Optional[dict] = None
        self._cache_ts: float = 0.0
        self._cache_ttl: float = 300.0  # 5 minuten cache

    # ── Public API ─────────────────────────────────────────────────

    def get_throttle(self) -> float:
        """
        Geeft positie-multiplier terug (0.25–1.0).
        Wordt vermenigvuldigd met position_pct voor elke trade.
        """
        return self._get_state()["throttle"]

    def get_state(self) -> dict:
        """Volledig meta-state voor dashboard/logging."""
        return self._get_state()

    def summary(self) -> str:
        s = self._get_state()
        lines = [
            f"Meta Controller | throttle={s['throttle']:.0%} | reden: {s['reason']}",
            f"  Recente WR (5d): {s['recent_win_rate_5d']:.0%} ({s['recent_trades_5d']} trades)",
            f"  Streak: {s['streak']} ({'wins' if s['streak'] > 0 else 'losses'})",
            f"  Sessie: {s['session']} | Weekend: {s['is_weekend']}",
        ]
        if s["best_hour"] is not None:
            lines.append(f"  Beste handelsuren: {s['best_hour']}u")
        return "\n".join(lines)

    # ── Interne logica ─────────────────────────────────────────────

    def _get_state(self) -> dict:
        now = _time.time()
        if self._cache is not None and (now - self._cache_ts) < self._cache_ttl:
            return self._cache
        self._cache = self._compute()
        self._cache_ts = now
        return self._cache

    def _load_closed(self) -> list[dict]:
        if not self.trades_path.exists():
            return []
        try:
            trades = json.loads(self.trades_path.read_text(encoding="utf-8"))
        except Exception:
            return []
        return [
            t for t in trades
            if t.get("type") in ("sell", "cover")
            and "pnl_pct" in t
            and "timestamp" in t
        ]

    def _compute(self) -> dict:
        closed = self._load_closed()
        now = datetime.now()
        is_weekend = now.weekday() >= 5
        hour = now.hour
        session = self._get_session(hour)

        # ── Recente prestaties ─────────────────────────────────────
        def stats_for_days(days: int) -> tuple[float, int]:
            cutoff = now - timedelta(days=days)
            recent = [t for t in closed if self._parse_ts(t["timestamp"]) >= cutoff]
            if not recent:
                return 0.5, 0
            pnls = [t["pnl_pct"] for t in recent]
            win_rate = sum(1 for p in pnls if p > 0) / len(pnls)
            return win_rate, len(recent)

        wr_3d, n_3d = stats_for_days(3)
        wr_5d, n_5d = stats_for_days(5)
        wr_10d, n_10d = stats_for_days(10)

        # ── Streak berekenen ──────────────────────────────────────
        streak = self._calc_streak(closed)

        # ── Trade clustering: beste uur van de dag ────────────────
        best_hour, hour_multiplier = self._best_trading_hour(closed, hour)

        # ── Throttle bepalen ──────────────────────────────────────
        throttle = 1.00
        reasons = []

        # Slechte recente win rate (alleen als genoeg data)
        if n_5d >= 5:
            if wr_5d < 0.30:
                throttle = min(throttle, 0.25)
                reasons.append(f"WR5d={wr_5d:.0%}<30%")
            elif wr_5d < 0.40:
                throttle = min(throttle, 0.50)
                reasons.append(f"WR5d={wr_5d:.0%}<40%")
            elif wr_5d < 0.48:
                throttle = min(throttle, 0.75)
                reasons.append(f"WR5d={wr_5d:.0%}<48%")

        # Verliesstreak
        if streak <= -4:
            throttle = min(throttle, 0.25)
            reasons.append(f"streak={streak}")
        elif streak <= -3:
            throttle = min(throttle, 0.50)
            reasons.append(f"streak={streak}")
        elif streak <= -2:
            throttle = min(throttle, 0.75)
            reasons.append(f"streak={streak}")

        # Weekend: crypto is 24/7 maar iets minder institutionele flow
        if is_weekend:
            throttle = min(throttle, 0.75)
            reasons.append("weekend")

        # Slechtste handelsuur
        if hour_multiplier < 0.70:
            throttle = min(throttle, round(throttle * hour_multiplier, 2))
            reasons.append(f"slecht_uur={hour}u")

        throttle = round(max(0.25, min(1.0, throttle)), 2)
        reason = " | ".join(reasons) if reasons else "normaal"

        return {
            "throttle": throttle,
            "reason": reason,
            "recent_win_rate_5d": round(wr_5d, 3),
            "recent_win_rate_3d": round(wr_3d, 3),
            "recent_win_rate_10d": round(wr_10d, 3),
            "recent_trades_5d": n_5d,
            "recent_trades_3d": n_3d,
            "is_weekend": is_weekend,
            "session": session,
            "streak": streak,
            "best_hour": best_hour,
            "hour_multiplier": round(hour_multiplier, 2),
        }

    def _calc_streak(self, closed: list[dict]) -> int:
        if not closed:
            return 0
        streak = 0
        for trade in reversed(closed):
            pnl = trade.get("pnl_pct", 0)
            if streak == 0:
                streak = 1 if pnl > 0 else -1
            elif streak > 0 and pnl > 0:
                streak += 1
            elif streak < 0 and pnl <= 0:
                streak -= 1
            else:
                break
        return streak

    def _best_trading_hour(self, closed: list[dict], current_hour: int) -> tuple[Optional[int], float]:
        if len(closed) < 20:
            return None, 1.0

        hour_stats: dict = defaultdict(lambda: {"wins": 0, "total": 0})
        for t in closed:
            ts = self._parse_ts(t.get("timestamp", ""))
            if ts is None:
                continue
            h = ts.hour
            hour_stats[h]["total"] += 1
            if t.get("pnl_pct", 0) > 0:
                hour_stats[h]["wins"] += 1

        qualified = {
            h: s["wins"] / s["total"]
            for h, s in hour_stats.items()
            if s["total"] >= 3
        }
        if not qualified:
            return None, 1.0

        best_hour = max(qualified, key=qualified.get)
        avg_wr = sum(qualified.values()) / len(qualified)

        if current_hour in qualified:
            hour_wr = qualified[current_hour]
            multiplier = max(0.5, min(1.2, hour_wr / max(avg_wr, 0.01)))
        else:
            multiplier = 1.0

        return best_hour, multiplier

    @staticmethod
    def _get_session(hour: int) -> str:
        if 0 <= hour < 8:
            return "aziatisch"
        elif 8 <= hour < 16:
            return "europees"
        return "amerikaans"

    @staticmethod
    def _parse_ts(ts_str: str) -> Optional[datetime]:
        if not ts_str:
            return None
        try:
            return datetime.fromisoformat(ts_str)
        except Exception:
            return None
