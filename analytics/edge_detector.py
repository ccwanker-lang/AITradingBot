"""
Edge Detector — berekent expectancy per strategie, regime en combinatie.
Leest trades.json en bepaalt welke setups écht geld verdienen.
"""
from __future__ import annotations
import json
from collections import defaultdict
from pathlib import Path
from typing import Optional


class EdgeDetector:
    MIN_SAMPLES = 5  # minimum trades voor betrouwbare edge-score

    def __init__(self, trades_path: str = "logs/trades.json"):
        self.trades_path = Path(trades_path)
        self._cache: Optional[dict] = None
        self._cache_mtime: float = 0.0

    # ── Public API ─────────────────────────────────────────────────

    def get_edge(self) -> dict:
        """Geeft volledig edge-rapport terug (gecached tot trades.json wijzigt)."""
        mtime = self.trades_path.stat().st_mtime if self.trades_path.exists() else 0
        if self._cache is None or mtime != self._cache_mtime:
            self._cache = self._compute(self._load_closed_trades())
            self._cache_mtime = mtime
        return self._cache

    def strategy_expectancy(self, strategy_name: str) -> float:
        """Expectancy voor één strategie. 0.0 als te weinig data."""
        return self.get_edge().get("by_strategy", {}).get(strategy_name, {}).get("expectancy", 0.0)

    def regime_expectancy(self, strategy_name: str, regime: str) -> float:
        """Expectancy voor strategie binnen een specifiek regime."""
        key = f"{strategy_name}|{regime}"
        return self.get_edge().get("by_strategy_regime", {}).get(key, {}).get("expectancy", 0.0)

    def combo_expectancy(self, strategy_names: list[str]) -> float:
        """Gemiddelde expectancy voor een set strategieën die allemaal meestemden."""
        edge = self.get_edge().get("by_strategy", {})
        scores = [
            edge[n]["expectancy"]
            for n in strategy_names
            if n in edge and edge[n]["samples"] >= self.MIN_SAMPLES
        ]
        return sum(scores) / len(scores) if scores else 0.0

    def top_strategies(self, n: int = 5) -> list[dict]:
        """Top N strategieën op expectancy (min samples vereist)."""
        edge = self.get_edge().get("by_strategy", {})
        qualified = [
            {"naam": k, **v}
            for k, v in edge.items()
            if v["samples"] >= self.MIN_SAMPLES
        ]
        return sorted(qualified, key=lambda x: x["expectancy"], reverse=True)[:n]

    def worst_strategies(self, n: int = 5) -> list[dict]:
        """Bottom N strategieën — kandidaten voor tijdelijke uitschakeling."""
        edge = self.get_edge().get("by_strategy", {})
        qualified = [
            {"naam": k, **v}
            for k, v in edge.items()
            if v["samples"] >= self.MIN_SAMPLES
        ]
        return sorted(qualified, key=lambda x: x["expectancy"])[:n]

    def summary(self) -> str:
        """Leesbare samenvatting van de huidige edge-status."""
        edge = self.get_edge()
        lines = [f"Edge Detector — {edge['total_closed']} gesloten trades"]
        top = self.top_strategies(3)
        worst = self.worst_strategies(3)
        if top:
            lines.append("Beste setups: " + ", ".join(
                f"{s['naam']} ({s['expectancy']:+.3f}, {s['win_rate']:.0%} WR, n={s['samples']})"
                for s in top
            ))
        if worst:
            lines.append("Slechtste setups: " + ", ".join(
                f"{s['naam']} ({s['expectancy']:+.3f}, n={s['samples']})"
                for s in worst
            ))
        lines.append(f"Globale expectancy: {edge['global_expectancy']:+.4f}")
        return "\n".join(lines)

    # ── Interne berekeningen ───────────────────────────────────────

    def _load_closed_trades(self) -> list[dict]:
        if not self.trades_path.exists():
            return []
        try:
            trades = json.loads(self.trades_path.read_text(encoding="utf-8"))
        except Exception:
            return []
        return [
            t for t in trades
            if t.get("type") in ("sell", "cover", "partial_tp1", "partial_tp2")
            and "pnl_pct" in t
            and t.get("entry_reasons")
        ]

    def _compute(self, closed: list[dict]) -> dict:
        by_strategy: dict = defaultdict(lambda: {"wins": 0, "losses": 0, "pnl_sum": 0.0, "win_pnl": [], "loss_pnl": []})
        by_strategy_regime: dict = defaultdict(lambda: {"wins": 0, "losses": 0, "pnl_sum": 0.0})
        all_pnls: list[float] = []

        for trade in closed:
            pnl = trade.get("pnl_pct", 0.0)
            regime = trade.get("regime", "unknown")
            all_pnls.append(pnl)

            for reason in trade.get("entry_reasons", []):
                naam = reason.get("naam", "")
                actie = reason.get("actie", 0)
                direction = trade.get("direction", 0)

                # Telt mee als de strategie dezelfde richting adviseerde als de trade
                if actie == 0 or naam == "":
                    continue
                if actie != direction:
                    continue

                bucket = by_strategy[naam]
                if pnl > 0:
                    bucket["wins"] += 1
                    bucket["win_pnl"].append(pnl)
                else:
                    bucket["losses"] += 1
                    bucket["loss_pnl"].append(abs(pnl))
                bucket["pnl_sum"] += pnl

                reg_key = f"{naam}|{regime}"
                rb = by_strategy_regime[reg_key]
                if pnl > 0:
                    rb["wins"] += 1
                else:
                    rb["losses"] += 1
                rb["pnl_sum"] += pnl

        def _make_stats(b: dict) -> dict:
            total = b["wins"] + b["losses"]
            if total == 0:
                return {"samples": 0, "win_rate": 0.0, "expectancy": 0.0, "avg_win": 0.0, "avg_loss": 0.0}
            win_rate = b["wins"] / total
            avg_win = sum(b.get("win_pnl", [])) / len(b["win_pnl"]) if b.get("win_pnl") else 0.0
            avg_loss = sum(b.get("loss_pnl", [])) / len(b["loss_pnl"]) if b.get("loss_pnl") else 0.0
            expectancy = win_rate * avg_win - (1 - win_rate) * avg_loss
            return {
                "samples": total,
                "win_rate": round(win_rate, 3),
                "expectancy": round(expectancy, 4),
                "avg_win": round(avg_win, 4),
                "avg_loss": round(avg_loss, 4),
            }

        def _make_regime_stats(b: dict) -> dict:
            total = b["wins"] + b["losses"]
            if total == 0:
                return {"samples": 0, "win_rate": 0.0, "expectancy": 0.0}
            win_rate = b["wins"] / total
            avg_pnl = b["pnl_sum"] / total
            return {
                "samples": total,
                "win_rate": round(win_rate, 3),
                "expectancy": round(avg_pnl, 4),
            }

        strategy_stats = {k: _make_stats(v) for k, v in by_strategy.items()}
        regime_stats = {k: _make_regime_stats(v) for k, v in by_strategy_regime.items()}

        global_exp = sum(all_pnls) / len(all_pnls) if all_pnls else 0.0
        wins = [p for p in all_pnls if p > 0]
        global_wr = len(wins) / len(all_pnls) if all_pnls else 0.0

        return {
            "total_closed": len(closed),
            "global_win_rate": round(global_wr, 3),
            "global_expectancy": round(global_exp, 4),
            "by_strategy": strategy_stats,
            "by_strategy_regime": regime_stats,
        }
