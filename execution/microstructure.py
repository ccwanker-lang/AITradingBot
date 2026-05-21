"""
Microstructure Filter — voorkomt slechte entries bij te grote spread.
Past ook realistisch slippage toe op gesimuleerde entries.

Regels:
- Spread > MAX_SPREAD_ATR_PCT van ATR → entry geblokkeerd
- Entry prijs gecorrigeerd voor verwachte slippage
- Spread-data komt uit orderbook; fallback naar ATR-schatting
"""
from __future__ import annotations


MAX_SPREAD_ATR_PCT = 0.15   # blokkeer als spread > 15% van ATR
SLIPPAGE_PCT       = 0.0003  # 0.03% verwachte slippage per entry (Binance taker fee + impact)
MIN_SPREAD_PCT     = 0.0001  # minimale spread voor realisme (0.01%)


class MicrostructureFilter:

    def check_entry(
        self,
        price: float,
        atr: float,
        direction: int,        # +1 long, -1 short
        ob: dict | None = None,
    ) -> tuple[bool, float]:
        """
        Controleert of een entry verantwoord is op basis van spread.

        Returns:
            (allowed, adjusted_price)
            - allowed: False als spread te groot is
            - adjusted_price: prijs inclusief slippage
        """
        spread_pct = self._get_spread_pct(price, atr, ob)

        # Blokkeer als spread te groot is t.o.v. ATR
        atr_pct = atr / (price + 1e-8)
        if atr_pct > 0 and spread_pct > atr_pct * MAX_SPREAD_ATR_PCT:
            return False, price

        # Pas slippage toe: koop iets duurder, short iets goedkoper
        slippage = max(spread_pct / 2, SLIPPAGE_PCT)
        if direction == 1:   # long: betaal iets meer
            adjusted = price * (1 + slippage)
        else:                # short: ontvang iets minder
            adjusted = price * (1 - slippage)

        return True, round(adjusted, 8)

    def effective_spread_cost(self, price: float, atr: float, ob: dict | None = None) -> float:
        """Geeft totale spread+slippage kost als fraction van prijs terug."""
        spread_pct = self._get_spread_pct(price, atr, ob)
        return max(spread_pct / 2, SLIPPAGE_PCT)

    @staticmethod
    def _get_spread_pct(price: float, atr: float, ob: dict | None) -> float:
        """Haal spread op uit orderbook of schat via ATR."""
        if ob and ob.get("best_bid", 0) > 0 and ob.get("best_ask", 0) > 0:
            spread = ob["best_ask"] - ob["best_bid"]
            return spread / (ob["best_bid"] + 1e-8)
        # Fallback: schat spread als 10% van ATR (typisch voor liquid crypto)
        if atr > 0 and price > 0:
            return max(MIN_SPREAD_PCT, (atr * 0.10) / price)
        return SLIPPAGE_PCT
