"""
Funding Rate + Open Interest analyse.
Alleen in crypto beschikbaar — enorme voorsprong op andere markten.

Funding Rate:
  Hoog positief (>0.1%)  = iedereen long → prijs gaat DALEN om stops te raken
  Hoog negatief (<-0.05%) = iedereen short → prijs gaat STIJGEN om stops te raken

Open Interest:
  Stijgend OI + stijgende prijs = sterke trend
  Dalend OI + dalende prijs = liquidaties, trend versterkt
  Stijgend OI + dalende prijs = bears in controle
"""
import time
import requests
from dataclasses import dataclass


@dataclass
class FundingSignal:
    action: int          # +1 long, -1 short, 0 neutraal
    confidence: float
    funding_rate: float  # Huidige funding rate
    open_interest: float # Open Interest in USD
    reason: str


class FundingRateAnalyzer:
    BINANCE_FUTURES = "https://fapi.binance.com"

    def __init__(self):
        self._cache: dict[str, tuple[FundingSignal, float]] = {}
        self._cache_ttl = 300  # 5 minuten

    def analyze(self, symbol: str) -> FundingSignal:
        cached, ts = self._cache.get(symbol, (None, 0))
        if cached and (time.time() - ts) < self._cache_ttl:
            return cached

        futures_symbol = symbol.replace("/", "").replace("USDT", "USDT")
        result = self._fetch(futures_symbol)
        self._cache[symbol] = (result, time.time())
        return result

    def _fetch(self, symbol: str) -> FundingSignal:
        try:
            # Funding rate
            fr_r = requests.get(
                f"{self.BINANCE_FUTURES}/fapi/v1/fundingRate",
                params={"symbol": symbol, "limit": 3},
                timeout=5,
            ).json()
            funding = float(fr_r[-1]["fundingRate"]) if fr_r else 0.0

            # Open Interest
            oi_r = requests.get(
                f"{self.BINANCE_FUTURES}/fapi/v1/openInterest",
                params={"symbol": symbol},
                timeout=5,
            ).json()
            open_interest = float(oi_r.get("openInterest", 0))

            return self._interpret(funding, open_interest, symbol)
        except Exception:
            return FundingSignal(0, 0.0, 0.0, 0.0, "futures data niet beschikbaar")

    def _interpret(self, funding: float, oi: float, symbol: str) -> FundingSignal:
        # Drempelwaarden aangepast naar realistische Binance funding rates:
        # Typische BTC funding is 0.01-0.03% per 8u — oude drempel (0.1%) was nooit actief

        # Hoog positieve funding = iedereen long = short kans
        if funding > 0.0003:  # >0.03% (was 0.1% — nooit bereikt)
            conf = min(funding / 0.001, 0.90)
            return FundingSignal(-1, conf, funding, oi,
                f"Hoge funding {funding:.4%} — markt overlonged, short kans")

        # Hoog negatieve funding = iedereen short = long kans
        if funding < -0.0001:  # <-0.01% (was -0.05% — zelden bereikt)
            conf = min(abs(funding) / 0.0005, 0.85)
            return FundingSignal(1, conf, funding, oi,
                f"Negatieve funding {funding:.4%} — markt overshorted, long kans")

        # Neutrale funding
        if abs(funding) < 0.0001:
            return FundingSignal(0, 0.2, funding, oi,
                f"Neutrale funding {funding:.4%}")

        return FundingSignal(0, 0.1, funding, oi,
            f"Funding {funding:.4%} — geen sterk signaal")
