from __future__ import annotations
"""
Paper trading engine met:
- LONGS en SHORTS
- Echte SL/TP handhaving elke tick
- Partieel winst nemen (50% op TP1)
- Pyramiding (bijkopen op winnende positie)
"""
import json
import time as _time
from datetime import datetime
from dataclasses import dataclass, asdict, field
from pathlib import Path
from risk.manager import RiskManager


@dataclass
class Position:
    symbol: str
    direction: int        # +1 long, -1 short
    size: float
    entry_price: float
    stop_loss: float
    take_profit: float
    take_profit_2: float  # TP2 voor de resterende 50%
    peak_price: float
    capital_invested: float
    partial_closed: bool = False
    pyramid_count: int = 0
    entry_reasons: list = field(default_factory=list)
    opened_at: float = 0.0   # Unix timestamp — voor time-based exit
    regime: str = "ranging"
    setup_grade: str = "?"


class PaperEngine:
    def __init__(self, initial_capital: float, risk_manager: RiskManager, fee_rate: float = 0.001):
        self.risk = risk_manager
        self.initial_capital = initial_capital
        self.capital = initial_capital
        self.positions: dict[str, Position] = {}
        self.trade_history: list[dict] = []
        self.peak_value = initial_capital
        self.fee_rate = fee_rate

    # ── Tick update — elke cyclus aanroepen ───────────────────────
    def check_stops(self, prices: dict) -> list[dict]:
        closed = []
        for symbol in list(self.positions.keys()):
            pos = self.positions.get(symbol)
            if not pos:
                continue
            price = prices.get(symbol, pos.entry_price)

            # Peak bijwerken voor long
            if pos.direction == 1 and price > pos.peak_price:
                pos.peak_price = price
            elif pos.direction == -1 and price < pos.peak_price:
                pos.peak_price = price

            # ── Breakeven stop: SL naar entry zodra prijs halverwege TP1 ──
            if not pos.partial_closed and pos.opened_at > 0:
                halfway = (pos.entry_price + pos.take_profit) / 2
                if pos.direction == 1 and price >= halfway:
                    pos.stop_loss = max(pos.stop_loss, pos.entry_price)
                elif pos.direction == -1 and price <= halfway:
                    pos.stop_loss = min(pos.stop_loss, pos.entry_price)

            # ── Time-based exit: sluit stale trades na 24 uur ─────
            if pos.opened_at > 0:
                hours_open = (_time.time() - pos.opened_at) / 3600
                if hours_open > 24:
                    pnl_pct = ((price - pos.entry_price) / pos.entry_price) * pos.direction
                    if abs(pnl_pct) < 0.005:  # Minder dan 0.5% beweging → dood kapitaal
                        record = self._close_position(symbol, price, "TIME-EXIT")
                        if record:
                            closed.append(record)
                        continue

            # ── Partieel sluiten op TP1 (50%) ─────────────────────
            if not pos.partial_closed:
                if (pos.direction == 1 and price >= pos.take_profit) or \
                   (pos.direction == -1 and price <= pos.take_profit):
                    record = self._partial_close(symbol, price, 0.50, "TP1")
                    if record:
                        closed.append(record)
                    continue

            # ── Volledige sluitingen ───────────────────────────────
            should_close, reason = self._check_exit(pos, price)
            if should_close:
                record = self._close_position(symbol, price, reason)
                if record:
                    closed.append(record)

        return closed

    def _check_exit(self, pos: Position, price: float) -> tuple[bool, str]:
        if pos.direction == 1:  # Long
            if price <= pos.stop_loss:
                return True, "STOP-LOSS"
            if price >= pos.take_profit_2:
                return True, "TAKE-PROFIT-2"
            trail = self.risk.trailing_stop_price(pos.entry_price, pos.peak_price)
            if price <= trail and pos.partial_closed:
                return True, "TRAILING-STOP"
        else:  # Short
            if price >= pos.stop_loss:
                return True, "STOP-LOSS"
            if price <= pos.take_profit_2:
                return True, "TAKE-PROFIT-2"
            # Trailing voor short
            trail = pos.peak_price * (1 + self.risk.trailing_pct)
            if price >= trail and pos.partial_closed:
                return True, "TRAILING-STOP"
        return False, ""

    # ── Long kopen ─────────────────────────────────────────────────
    def buy(self, symbol: str, price: float, atr: float,
            confidence: float, prices: dict,
            entry_reasons: list = None, position_pct: float = 0.10,
            sl_mult: float = None, tp_mult: float = None,
            regime: str = "ranging", setup_grade: str = "?") -> dict | None:
        if symbol in self.positions:
            return self._try_pyramid(symbol, price, confidence, atr)

        total = self.total_value(prices)
        drawdown = self._drawdown(total)
        may, reason = self.risk.should_trade(confidence, drawdown, 1.0)
        if not may:
            return None

        invest = min(total * position_pct, self.capital * 0.95)
        if invest < price * 0.0001:
            return None

        _sl_m = sl_mult if sl_mult is not None else self.risk.atr_sl_mult
        _tp_m = tp_mult if tp_mult is not None else self.risk.atr_tp_mult

        # Fee-check: verwachte move moet minimaal 3× round-trip fee zijn
        # (2× fee = breakeven, 3× = minimale marge om de moeite waard te zijn)
        expected_move_pct = (atr * _tp_m) / price
        if expected_move_pct < self.fee_rate * 3:
            return None

        sl  = price - atr * _sl_m
        tp1 = price + (price - sl) * 1.2   # TP1 op 1.2R (vaker bereikt dan 1.5R)
        tp2 = price + atr * _tp_m
        if tp1 >= tp2:  # Fix: TP1 moet altijd VOOR TP2 liggen (bug in ranging met lage sl_m)
            tp1 = price + atr * (_tp_m * 0.45)

        self.capital -= invest
        self.positions[symbol] = Position(
            symbol=symbol, direction=1, size=(invest * (1 - self.fee_rate)) / price,
            entry_price=price, stop_loss=sl, take_profit=tp1, take_profit_2=tp2,
            peak_price=price, capital_invested=invest,
            entry_reasons=entry_reasons or [],
            opened_at=_time.time(),
            regime=regime, setup_grade=setup_grade,
        )
        return {"type": "buy", "symbol": symbol, "price": price,
                "invest": invest, "stop_loss": sl,
                "take_profit": tp1, "confidence": confidence,
                "entry_reasons": entry_reasons or [],
                "timestamp": datetime.now().isoformat()}

    # ── Short openen ────────────────────────────────────────────────
    def short(self, symbol: str, price: float, atr: float,
               confidence: float, prices: dict,
               entry_reasons: list = None, position_pct: float = 0.10,
               sl_mult: float = None, tp_mult: float = None,
               regime: str = "ranging", setup_grade: str = "?") -> dict | None:
        if symbol in self.positions:
            return None

        total = self.total_value(prices)
        drawdown = self._drawdown(total)
        may, _ = self.risk.should_trade(confidence, drawdown, -1.0)
        if not may:
            return None

        invest = min(total * position_pct, self.capital * 0.95)
        if invest < price * 0.0001:
            return None

        _sl_m = sl_mult if sl_mult is not None else self.risk.atr_sl_mult
        _tp_m = tp_mult if tp_mult is not None else self.risk.atr_tp_mult

        # Fee-check: zelfde drempel als long
        expected_move_pct = (atr * _tp_m) / price
        if expected_move_pct < self.fee_rate * 3:
            return None

        sl  = price + atr * _sl_m                    # SL boven entry voor short
        tp1 = price - (sl - price) * 1.2             # TP1 op 1.2R omlaag (vaker bereikt dan 1.5R)
        tp2 = price - atr * _tp_m                    # TP2 omlaag
        if tp1 <= tp2:  # Fix: voor short moet TP1 > TP2 (TP1 dichter bij entry)
            tp1 = price - atr * (_tp_m * 0.45)

        self.capital -= invest * 0.10  # Margin (10%)
        self.positions[symbol] = Position(
            symbol=symbol, direction=-1, size=(invest * (1 - self.fee_rate)) / price,
            entry_price=price, stop_loss=sl, take_profit=tp1, take_profit_2=tp2,
            peak_price=price, capital_invested=invest,
            entry_reasons=entry_reasons or [],
            opened_at=_time.time(),
            regime=regime, setup_grade=setup_grade,
        )
        return {"type": "short", "symbol": symbol, "price": price,
                "invest": invest, "stop_loss": sl,
                "take_profit": tp1, "confidence": confidence,
                "entry_reasons": entry_reasons or [],
                "timestamp": datetime.now().isoformat()}

    # ── Positie sluiten ─────────────────────────────────────────────
    def sell(self, symbol: str, price: float, reason: str = "signaal") -> dict | None:
        return self._close_position(symbol, price, reason)

    def _close_position(self, symbol: str, price: float, reason: str) -> dict | None:
        pos = self.positions.pop(symbol, None)
        if not pos:
            return None

        if pos.direction == 1:
            proceeds = pos.size * price * (1 - self.fee_rate)
            pnl = proceeds - pos.capital_invested
        else:  # Short
            pnl = (pos.entry_price - price) * pos.size * (1 - self.fee_rate)
            proceeds = pos.capital_invested * 0.10 + pnl  # Margin terug + winst

        pnl_pct = pnl / (pos.capital_invested + 1e-8)
        self.capital += max(proceeds, 0)
        record = {
            "type": "sell" if pos.direction == 1 else "cover",
            "symbol": symbol, "price": price,
            "pnl": pnl, "pnl_pct": pnl_pct,
            "reason": reason, "direction": pos.direction,
            "entry_reasons": pos.entry_reasons,
            "entry_price": pos.entry_price,
            "entry_timestamp": datetime.fromtimestamp(pos.opened_at).isoformat() if pos.opened_at else None,
            "invest": pos.capital_invested,
            "regime": pos.regime,
            "setup_grade": pos.setup_grade,
            "timestamp": datetime.now().isoformat(),
        }
        self.trade_history.append(record)
        return record

    def _partial_close(self, symbol: str, price: float,
                       pct: float, reason: str) -> dict | None:
        pos = self.positions.get(symbol)
        if not pos:
            return None

        close_size = pos.size * pct
        if pos.direction == 1:
            proceeds = close_size * price * (1 - self.fee_rate)
            pnl = proceeds - (close_size * pos.entry_price)
        else:
            margin_return = pos.capital_invested * 0.10 * pct
            pnl = (pos.entry_price - price) * close_size * (1 - self.fee_rate)
            proceeds = margin_return + pnl

        pnl_pct = pnl / ((close_size * pos.entry_price) + 1e-8)
        original_invest = pos.capital_invested
        self.capital += proceeds
        pos.size -= close_size
        pos.capital_invested *= (1 - pct)
        pos.partial_closed = True

        record = {
            "type": f"partial_{reason.lower()}",
            "symbol": symbol, "price": price,
            "pnl": pnl, "pnl_pct": pnl_pct,
            "reason": reason, "partial": True,
            "entry_price": pos.entry_price,
            "entry_timestamp": datetime.fromtimestamp(pos.opened_at).isoformat() if pos.opened_at else None,
            "invest": original_invest,
            "regime": pos.regime,
            "setup_grade": pos.setup_grade,
            "timestamp": datetime.now().isoformat(),
        }
        self.trade_history.append(record)
        return record

    def _try_pyramid(self, symbol: str, price: float, confidence: float,
                     atr: float = 0.0) -> dict | None:
        """Bijkopen op winnende positie (max 2x). Vereist 2× ATR winst."""
        pos = self.positions.get(symbol)
        if not pos or pos.pyramid_count >= 2:
            return None
        min_move = atr * 2.0 if atr > 0 else pos.entry_price * 0.02
        if pos.direction == 1 and price < pos.entry_price + min_move:
            return None  # Minimaal 2× ATR in winst voor pyramid
        if pos.direction == -1 and price > pos.entry_price - min_move:
            return None

        add_invest = pos.capital_invested * 0.25
        if add_invest > self.capital:
            return None

        self.capital -= add_invest
        pos.size += (add_invest * (1 - self.fee_rate)) / price
        pos.capital_invested += add_invest
        pos.pyramid_count += 1
        return {"type": "pyramid", "symbol": symbol, "price": price,
                "add_invest": add_invest, "pyramid_count": pos.pyramid_count,
                "timestamp": datetime.now().isoformat()}

    # ── Portfolio info ──────────────────────────────────────────────
    def total_value(self, prices: dict) -> float:
        pos_value = 0.0
        for sym, pos in self.positions.items():
            price = prices.get(sym, pos.entry_price)
            if pos.direction == 1:
                pos_value += pos.size * price
            else:
                pnl = (pos.entry_price - price) * pos.size
                pos_value += pos.capital_invested * 0.10 + pnl
        return self.capital + pos_value

    def _drawdown(self, total: float) -> float:
        if total > self.peak_value:
            self.peak_value = total
        return (self.peak_value - total) / (self.peak_value + 1e-8)

    def get_status(self, prices: dict) -> dict:
        total = self.total_value(prices)
        return {
            "total_value": total,
            "pnl_pct": (total - self.initial_capital) / self.initial_capital,
            "drawdown": self._drawdown(total),
            "free_capital": self.capital,
            "open_positions": len(self.positions),
            "total_trades": len(self.trade_history),
            "longs": sum(1 for p in self.positions.values() if p.direction == 1),
            "shorts": sum(1 for p in self.positions.values() if p.direction == -1),
        }

    # ── State opslaan / herstellen ─────────────────────────────────
    def save_state(self, path: Path):
        state = {
            "capital": self.capital,
            "peak_value": self.peak_value,
            "initial_capital": self.initial_capital,
            "trade_history": self.trade_history,
            "positions": {sym: asdict(pos) for sym, pos in self.positions.items()},
        }
        path.write_text(json.dumps(state, indent=2, ensure_ascii=False, default=str), encoding="utf-8")

    def load_state(self, path: Path):
        if not path.exists():
            return
        try:
            state = json.loads(path.read_text(encoding="utf-8"))
            self.capital = state.get("capital", self.capital)
            self.peak_value = state.get("peak_value", self.capital)
            self.initial_capital = state.get("initial_capital", self.initial_capital)
            self.trade_history = state.get("trade_history", [])
            known = {f.name for f in Position.__dataclass_fields__.values()}
            for sym, p in state.get("positions", {}).items():
                self.positions[sym] = Position(**{k: v for k, v in p.items() if k in known})
        except Exception:
            pass
