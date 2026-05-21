"""Logging systeem — slaat trades, metrics en events op."""
import json
import logging
from logging.handlers import TimedRotatingFileHandler
import os
import traceback
from collections import defaultdict
from datetime import datetime
from pathlib import Path


class BotLogger:
    def __init__(self, log_dir: str = "logs"):
        self.log_dir = Path(log_dir)
        self.log_dir.mkdir(exist_ok=True)

        log_file = self.log_dir / f"bot_{datetime.now().strftime('%Y%m%d')}.log"
        self.logger = logging.getLogger("monster_bot")
        if not self.logger.handlers:
            self.logger.setLevel(logging.INFO)
            self.logger.propagate = False
            fmt = logging.Formatter("%(asctime)s | %(levelname)s | %(message)s")
            # Roteert automatisch om middernacht naar een nieuw dagelijks bestand
            fh = TimedRotatingFileHandler(
                log_file, when="midnight", interval=1,
                backupCount=14, encoding="utf-8", utc=False,
            )
            fh.suffix = "%Y%m%d"
            fh.setFormatter(fmt)
            self.logger.addHandler(fh)
            # StreamHandler verwijderd — bot wordt gestart met stdout-redirect naar hetzelfde
            # logbestand, waardoor elke regel dubbel verscheen. FileHandler is voldoende.

        self.trade_file = self.log_dir / "trades.json"
        self.perf_file = self.log_dir / "performance.json"
        self.trades: list = self._load_json(self.trade_file)
        self.performance: list = self._load_json(self.perf_file)

    def _load_json(self, path: Path) -> list:
        if path.exists():
            try:
                return json.loads(path.read_text(encoding="utf-8"))
            except Exception:
                return []
        return []

    def _save_json(self, path: Path, data: list):
        path.write_text(json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8")

    def log_trade(self, trade: dict):
        if "timestamp" not in trade:  # niet overschrijven als engine het al zette
            trade["timestamp"] = datetime.now().isoformat()
        self.trades.append(trade)
        self.trades = self.trades[-3000:]
        self._save_json(self.trade_file, self.trades)
        pnl = trade.get("pnl_pct", 0)
        self.logger.info(
            f"TRADE | {trade.get('symbol', '')} | {trade.get('type', '').upper()} "
            f"@ {trade.get('price', 0):.4f} | PnL: {pnl:+.2%}"
        )

    def log_performance(self, metrics: dict):
        metrics["timestamp"] = datetime.now().isoformat()
        self.performance.append(metrics)
        self.performance = self.performance[-1440:]  # max 1440 entries (24 uur bij 1/min)
        self._save_json(self.perf_file, self.performance)

    def log_anomaly(self, symbol: str, anomaly_type, details: str):
        import time as _time
        type_str = anomaly_type.value if hasattr(anomaly_type, "value") else str(anomaly_type)
        key = f"{symbol}|{type_str}"
        if not hasattr(self, "_anomaly_cache"):
            self._anomaly_cache: dict = {}
        now = _time.time()
        last_ts = self._anomaly_cache.get(key, 0)
        if now - last_ts < 300:  # Max 1× per 5 minuten per anomalie-type per symbool
            return
        self._anomaly_cache[key] = now
        self.logger.warning(f"ANOMALIE | {symbol} | {type_str} | {details}")

    def log_error(self, context: str, error: Exception):
        tb = traceback.format_exc().strip()
        self.logger.error(f"FOUT | {context} | {type(error).__name__}: {error}\n{tb}")

    def info(self, msg: str):
        self.logger.info(msg)

    def warning(self, msg: str):
        self.logger.warning(msg)

    def get_trade_summary(self) -> dict:
        if not self.trades:
            return {"total_trades": 0, "win_rate": 0, "avg_pnl": 0, "total_pnl": 0}
        closed = [
            t for t in self.trades
            if t.get("type") in ("sell", "cover", "partial_tp1", "partial_tp2")
            and "pnl_pct" in t
        ]
        if not closed:
            return {"total_trades": len(self.trades), "closed_trades": 0}
        pnls = [t["pnl_pct"] for t in closed]
        wins = [p for p in pnls if p > 0]
        full_closed = [t for t in closed if t.get("type") in ("sell", "cover")]

        # Per-regime statistieken
        reg_data: dict = defaultdict(lambda: {"wins": 0, "total": 0, "pnl_sum": 0.0})
        grd_data: dict = defaultdict(lambda: {"wins": 0, "total": 0})
        for t in closed:
            reg = t.get("regime") or "ranging"
            reg_data[reg]["total"] += 1
            if t.get("pnl_pct", 0) > 0:
                reg_data[reg]["wins"] += 1
            reg_data[reg]["pnl_sum"] += t.get("pnl_pct", 0)
            grd = t.get("setup_grade", "?")
            grd_data[grd]["total"] += 1
            if t.get("pnl_pct", 0) > 0:
                grd_data[grd]["wins"] += 1

        regime_stats = {
            reg: {
                "win_rate": round(d["wins"] / d["total"], 3) if d["total"] else 0,
                "trades": d["total"],
                "avg_pnl": round(d["pnl_sum"] / d["total"], 4) if d["total"] else 0,
            }
            for reg, d in reg_data.items()
        }
        grade_stats = {
            grd: {
                "win_rate": round(d["wins"] / d["total"], 3) if d["total"] else 0,
                "trades": d["total"],
            }
            for grd, d in grd_data.items()
        }

        # Win rate op finale exits (sell/cover) — eerlijk beeld per entry
        full_pnls = [t["pnl_pct"] for t in full_closed]
        full_wins  = [p for p in full_pnls if p > 0]
        win_rate_final = len(full_wins) / len(full_pnls) if full_pnls else 0

        return {
            "total_trades": len(self.trades),
            "closed_trades": len(closed),
            "full_closed": len(full_closed),
            "win_rate": win_rate_final,          # per finale exit — eerlijk per trade
            "win_rate_with_partials": len(wins) / len(pnls),  # inclusief partial TPs
            "avg_pnl": sum(pnls) / len(pnls),
            "avg_pnl_final": sum(full_pnls) / len(full_pnls) if full_pnls else 0,
            "best_trade": max(pnls),
            "worst_trade": min(pnls),
            "total_pnl": sum(pnls),
            "regime_stats": regime_stats,
            "grade_stats": grade_stats,
        }

    def get_rolling_stats(self, n: int = 20) -> dict:
        """Win rate en gemiddeld PnL van de laatste N finale exits."""
        full_closed = [
            t for t in self.trades
            if t.get("type") in ("sell", "cover") and "pnl_pct" in t
        ]
        if not full_closed:
            return {"n": 0, "win_rate": 0.0, "avg_pnl": 0.0, "is_paused": False}
        recent = full_closed[-n:]
        pnls = [t["pnl_pct"] for t in recent]
        wins = sum(1 for p in pnls if p > 0)
        win_rate = wins / len(pnls) if pnls else 0.0
        losses = [p for p in pnls if p < 0]
        pf = (sum(p for p in pnls if p > 0) / abs(sum(losses))) if losses else float("inf")
        return {
            "n": len(pnls),
            "win_rate": round(win_rate, 3),
            "avg_pnl": round(sum(pnls) / len(pnls), 4),
            "profit_factor": round(pf, 2) if pf != float("inf") else 99.0,
            "is_paused": win_rate < 0.30 and len(pnls) >= 15,
        }
