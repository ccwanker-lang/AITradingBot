"""
Risicobeheer — nu met echte SL/TP handhaving en trailing stop.
"""
import numpy as np


class RiskManager:
    def __init__(
        self,
        max_portfolio_risk: float = 0.02,
        max_drawdown_stop: float = 0.15,
        max_position_pct: float = 0.90,
        min_confidence: float = 0.28,
        kelly_fraction: float = 0.25,
        atr_sl_mult: float = 2.0,
        atr_tp_mult: float = 4.0,
        trailing_pct: float = 0.05,
    ):
        self.max_portfolio_risk = max_portfolio_risk
        self.max_drawdown_stop = max_drawdown_stop
        self.max_position_pct = max_position_pct
        self.min_confidence = min_confidence
        self.kelly_fraction = kelly_fraction
        self.atr_sl_mult = atr_sl_mult
        self.atr_tp_mult = atr_tp_mult
        self.trailing_pct = trailing_pct

    def position_size(
        self,
        portfolio_value: float,
        price: float,
        atr: float,
        confidence: float,
        win_rate: float = 0.55,
        avg_win_r: float = 2.0,   # Gemiddelde win in R veelvouden
        avg_loss_r: float = 1.0,  # Gemiddelde loss in R veelvouden
    ) -> float:
        """Kelly criterium + ATR-gebaseerde positiebepaling."""
        if atr <= 0 or confidence < self.min_confidence:
            return 0.0

        stop_loss_pct = (atr * self.atr_sl_mult) / price

        # Kelly berekening
        odds = avg_win_r / avg_loss_r
        kelly_f = (win_rate * odds - (1 - win_rate)) / odds
        kelly_f = max(0.0, min(kelly_f, 1.0)) * self.kelly_fraction

        # Risico-gebaseerde sizing
        risk_size = self.max_portfolio_risk / (stop_loss_pct + 1e-8)

        # Meest defensieve maat, geschaald met confidence
        position_pct = min(kelly_f, risk_size, self.max_position_pct) * confidence

        invest = portfolio_value * position_pct
        return invest / price if price > 0 else 0.0

    def should_trade(self, confidence: float, drawdown: float, signal_score: float) -> tuple[bool, str]:
        if drawdown >= self.max_drawdown_stop:
            return False, f"STOP: drawdown {drawdown:.1%} boven limiet {self.max_drawdown_stop:.1%}"
        if confidence < self.min_confidence:
            return False, f"Confidence {confidence:.2f} te laag (min {self.min_confidence:.2f})"
        if abs(signal_score) < 0.08:
            return False, "Signaal te zwak"
        return True, "OK"

    def stop_loss_price(self, entry_price: float, atr: float) -> float:
        return entry_price - atr * self.atr_sl_mult

    def take_profit_price(self, entry_price: float, atr: float) -> float:
        return entry_price + atr * self.atr_tp_mult

    def trailing_stop_price(self, entry_price: float, peak_price: float) -> float:
        """Trailing stop beweegt mee omhoog maar nooit omlaag."""
        trail = peak_price * (1 - self.trailing_pct)
        minimum = entry_price * 0.97  # Minimaal 3% onder entry
        return max(trail, minimum)

    def check_exits(
        self,
        current_price: float,
        entry_price: float,
        stop_loss: float,
        take_profit: float,
        peak_price: float,
    ) -> tuple[bool, str]:
        """
        Geeft (moet_sluiten, reden) terug.
        Roep dit ELKE tick aan voor open posities.
        """
        # Hard stop-loss
        if current_price <= stop_loss:
            return True, f"STOP-LOSS geraakt @ {current_price:.4f} (SL={stop_loss:.4f})"

        # Take-profit
        if current_price >= take_profit:
            return True, f"TAKE-PROFIT geraakt @ {current_price:.4f} (TP={take_profit:.4f})"

        # Trailing stop
        trail = self.trailing_stop_price(entry_price, peak_price)
        if current_price <= trail:
            return True, f"TRAILING STOP @ {current_price:.4f} (trail={trail:.4f})"

        return False, ""
