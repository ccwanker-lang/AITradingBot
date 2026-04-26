"""Order book analyse — detecteer whale orders en bid/ask onbalans."""
import ccxt
import numpy as np


class OrderBookAnalyzer:
    def __init__(self, exchange: ccxt.Exchange):
        self.exchange = exchange

    def analyze(self, symbol: str, depth: int = 20) -> dict:
        try:
            ob = self.exchange.fetch_order_book(symbol, limit=depth)
        except Exception:
            return self._empty_result()

        bids = np.array(ob["bids"][:depth]) if ob["bids"] else np.zeros((1, 2))
        asks = np.array(ob["asks"][:depth]) if ob["asks"] else np.zeros((1, 2))

        bid_volume = float(bids[:, 1].sum()) if len(bids) > 0 else 0
        ask_volume = float(asks[:, 1].sum()) if len(asks) > 0 else 0
        total = bid_volume + ask_volume + 1e-8

        # Imbalans: +1 = veel kopers, -1 = veel verkopers
        imbalance = (bid_volume - ask_volume) / total

        # Whale detectie — orders die groter zijn dan 3x gemiddelde
        avg_bid = float(bids[:, 1].mean()) if len(bids) > 0 else 0
        avg_ask = float(asks[:, 1].mean()) if len(asks) > 0 else 0
        whale_bids = int((bids[:, 1] > avg_bid * 3).sum()) if len(bids) > 0 else 0
        whale_asks = int((asks[:, 1] > avg_ask * 3).sum()) if len(asks) > 0 else 0

        # Spread
        best_bid = float(bids[0, 0]) if len(bids) > 0 else 0
        best_ask = float(asks[0, 0]) if len(asks) > 0 else 0
        spread_pct = (best_ask - best_bid) / (best_bid + 1e-8) if best_bid > 0 else 0

        # Signaal afleiden
        if imbalance > 0.20 and whale_bids > whale_asks:
            signal = 1   # Koop druk
        elif imbalance < -0.20 and whale_asks > whale_bids:
            signal = -1  # Verkoop druk
        else:
            signal = 0

        return {
            "imbalance": imbalance,
            "bid_volume": bid_volume,
            "ask_volume": ask_volume,
            "whale_bids": whale_bids,
            "whale_asks": whale_asks,
            "spread_pct": spread_pct,
            "signal": signal,
            "confidence": min(abs(imbalance) * 1.5, 1.0),
        }

    def _empty_result(self) -> dict:
        return {
            "imbalance": 0.0, "bid_volume": 0.0, "ask_volume": 0.0,
            "whale_bids": 0, "whale_asks": 0, "spread_pct": 0.0,
            "signal": 0, "confidence": 0.0,
        }
