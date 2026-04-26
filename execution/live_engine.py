"""
Live trading engine via ccxt.
WAARSCHUWING: Test altijd eerst met paper trading!
"""
import ccxt
from datetime import datetime
from risk.manager import RiskManager


class LiveEngine:
    def __init__(self, exchange_id: str, api_key: str, api_secret: str,
                 risk_manager: RiskManager, initial_capital: float):
        self.exchange: ccxt.Exchange = getattr(ccxt, exchange_id)({
            "apiKey": api_key,
            "secret": api_secret,
            "enableRateLimit": True,
        })
        self.risk = risk_manager
        self.initial_capital = initial_capital
        self.open_orders: dict = {}  # symbol -> {sl_order, tp_order, size}

    def get_balance(self) -> float:
        balance = self.exchange.fetch_balance()
        return float(balance["USDT"]["free"])

    def get_portfolio_value(self, prices: dict) -> float:
        balance = self.exchange.fetch_balance()
        usdt = float(balance["USDT"]["total"])
        for symbol, price in prices.items():
            coin = symbol.split("/")[0]
            amount = float(balance.get(coin, {}).get("total", 0))
            usdt += amount * price
        return usdt

    def buy(self, symbol: str, price: float, atr: float, confidence: float) -> dict | None:
        try:
            usdt = self.get_balance()
            portfolio = self.get_portfolio_value({symbol: price})

            drawdown = (self.initial_capital - portfolio) / self.initial_capital
            may_trade, reason = self.risk.should_trade(confidence, drawdown, 1.0)
            if not may_trade:
                return None

            size = self.risk.position_size(portfolio, price, atr, confidence)
            invest = size * price
            invest = min(invest, usdt * 0.95)

            if invest < 10:  # Minimum $10
                return None

            order = self.exchange.create_market_buy_order(symbol, invest / price)
            sl = self.risk.stop_loss_price(price, atr)
            tp = self.risk.take_profit_price(price, atr)

            self.open_orders[symbol] = {
                "size": float(order["filled"]),
                "entry_price": price,
                "stop_loss": sl,
                "take_profit": tp,
                "peak_price": price,
            }

            return {
                "type": "buy", "symbol": symbol, "price": price,
                "size": float(order["filled"]), "stop_loss": sl, "take_profit": tp,
                "timestamp": datetime.now().isoformat(),
            }
        except Exception as e:
            raise RuntimeError(f"Live buy mislukt voor {symbol}: {e}") from e

    def sell(self, symbol: str, price: float, reason: str = "signaal") -> dict | None:
        order_info = self.open_orders.pop(symbol, None)
        if order_info is None:
            return None
        try:
            order = self.exchange.create_market_sell_order(symbol, order_info["size"])
            exit_price = float(order.get("average", price))
            pnl_pct = (exit_price - order_info["entry_price"]) / order_info["entry_price"]
            return {
                "type": "sell", "symbol": symbol, "price": exit_price,
                "pnl_pct": pnl_pct, "reason": reason,
                "timestamp": datetime.now().isoformat(),
            }
        except Exception as e:
            raise RuntimeError(f"Live sell mislukt voor {symbol}: {e}") from e

    def check_stops(self, prices: dict) -> list[dict]:
        """Controleer SL/TP voor open posities."""
        closed = []
        for symbol, info in list(self.open_orders.items()):
            price = prices.get(symbol, info["entry_price"])
            if price > info["peak_price"]:
                info["peak_price"] = price
            should_close, reason = self.risk.check_exits(
                price, info["entry_price"], info["stop_loss"],
                info["take_profit"], info["peak_price"]
            )
            if should_close:
                result = self.sell(symbol, price, reason)
                if result:
                    closed.append(result)
        return closed
