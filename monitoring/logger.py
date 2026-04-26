"""Logging systeem — slaat trades, metrics en events op."""
import json
import logging
import os
from datetime import datetime
from pathlib import Path


class BotLogger:
    def __init__(self, log_dir: str = "logs"):
        self.log_dir = Path(log_dir)
        self.log_dir.mkdir(exist_ok=True)

        log_file = self.log_dir / f"bot_{datetime.now().strftime('%Y%m%d')}.log"
        logging.basicConfig(
            level=logging.INFO,
            format="%(asctime)s | %(levelname)s | %(message)s",
            handlers=[
                logging.FileHandler(log_file, encoding="utf-8"),
                logging.StreamHandler(),
            ],
        )
        self.logger = logging.getLogger("monster_bot")

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
        trade["timestamp"] = datetime.now().isoformat()
        self.trades.append(trade)
        self._save_json(self.trade_file, self.trades)
        pnl = trade.get("pnl_pct", 0)
        self.logger.info(
            f"TRADE | {trade.get('symbol', '')} | {trade.get('type', '').upper()} "
            f"@ {trade.get('price', 0):.4f} | PnL: {pnl:+.2%}"
        )

    def log_performance(self, metrics: dict):
        metrics["timestamp"] = datetime.now().isoformat()
        self.performance.append(metrics)
        self._save_json(self.perf_file, self.performance)

    def log_anomaly(self, symbol: str, anomaly_type: str, details: str):
        self.logger.warning(f"ANOMALIE | {symbol} | {anomaly_type} | {details}")

    def log_error(self, context: str, error: Exception):
        self.logger.error(f"FOUT | {context} | {type(error).__name__}: {error}")

    def info(self, msg: str):
        self.logger.info(msg)

    def warning(self, msg: str):
        self.logger.warning(msg)

    def get_trade_summary(self) -> dict:
        if not self.trades:
            return {"total_trades": 0, "win_rate": 0, "avg_pnl": 0, "total_pnl": 0}
        sells = [t for t in self.trades if t.get("type") == "sell" and "pnl_pct" in t]
        if not sells:
            return {"total_trades": len(self.trades), "closed_trades": 0}
        pnls = [t["pnl_pct"] for t in sells]
        wins = [p for p in pnls if p > 0]
        return {
            "total_trades": len(self.trades),
            "closed_trades": len(sells),
            "win_rate": len(wins) / len(pnls),
            "avg_pnl": sum(pnls) / len(pnls),
            "best_trade": max(pnls),
            "worst_trade": min(pnls),
            "total_pnl": sum(pnls),
        }
