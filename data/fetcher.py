"""Data ophalen van Binance — OHLCV met caching en herverbinding."""
import time
import ccxt
import pandas as pd
from datetime import datetime, timedelta
from typing import Optional


class DataFetcher:
    def __init__(self, exchange_id: str = "binance", api_key: str = "", api_secret: str = ""):
        cfg = {"enableRateLimit": True}
        if api_key:
            cfg.update({"apiKey": api_key, "secret": api_secret})
        self.exchange: ccxt.Exchange = getattr(ccxt, exchange_id)(cfg)

        self._cache: dict[str, tuple[pd.DataFrame, float]] = {}
        self._cache_ttl = 50  # seconden

    def fetch_ohlcv(self, symbol: str, timeframe: str = "1h", limit: int = 500) -> pd.DataFrame:
        cache_key = f"{symbol}:{timeframe}:{limit}"
        cached_df, cached_at = self._cache.get(cache_key, (None, 0))
        if cached_df is not None and (time.time() - cached_at) < self._cache_ttl:
            return cached_df

        for attempt in range(3):
            try:
                raw = self.exchange.fetch_ohlcv(symbol, timeframe, limit=limit)
                df = pd.DataFrame(raw, columns=["timestamp", "open", "high", "low", "close", "volume"])
                df["timestamp"] = pd.to_datetime(df["timestamp"], unit="ms")
                df.set_index("timestamp", inplace=True)
                df = df.astype(float)
                self._cache[cache_key] = (df, time.time())
                return df
            except ccxt.NetworkError:
                if attempt < 2:
                    time.sleep(5 * (attempt + 1))
            except Exception as e:
                raise RuntimeError(f"Datafout voor {symbol}: {e}") from e
        raise RuntimeError(f"Kan data niet ophalen voor {symbol} na 3 pogingen")

    def fetch_current_price(self, symbol: str) -> float:
        ticker = self.exchange.fetch_ticker(symbol)
        return float(ticker["last"])

    def fetch_multi(self, symbols: list[str], timeframe: str = "1h",
                    limit: int = 500) -> dict[str, pd.DataFrame]:
        result = {}
        for sym in symbols:
            try:
                result[sym] = self.fetch_ohlcv(sym, timeframe, limit)
                time.sleep(0.1)  # Rate limit respecteren
            except Exception:
                pass
        return result

    def fetch_historical(self, symbol: str, timeframe: str, days: int) -> pd.DataFrame:
        """Haal meerdere batches op voor lange historische periode."""
        all_candles = []
        since = self.exchange.parse8601(
            (datetime.utcnow() - timedelta(days=days)).strftime("%Y-%m-%dT%H:%M:%SZ")
        )
        while True:
            batch = self.exchange.fetch_ohlcv(symbol, timeframe, since=since, limit=1000)
            if not batch:
                break
            all_candles.extend(batch)
            since = batch[-1][0] + 1
            if len(batch) < 1000:
                break
            time.sleep(0.5)

        df = pd.DataFrame(all_candles, columns=["timestamp", "open", "high", "low", "close", "volume"])
        df["timestamp"] = pd.to_datetime(df["timestamp"], unit="ms")
        df.set_index("timestamp", inplace=True)
        df = df.astype(float)
        df = df[~df.index.duplicated(keep="last")]
        return df
