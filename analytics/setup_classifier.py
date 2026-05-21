"""
Setup Classifier — bepaalt A+/A/B/C grade inclusief historische edge-score.
Vervangt de inline grading in bot.py met een uitbreidbaar systeem.
"""
from __future__ import annotations
from analytics.edge_detector import EdgeDetector


class SetupClassifier:
    # Positie-percentages per grade
    GRADE_PCT = {"A+": 0.15, "A": 0.12, "B": 0.08, "C": 0.05}

    # Max positie per regime
    REGIME_CAP = {
        "bull_trend": 0.18, "bear_trend": 0.13,
        "ranging": 0.13, "high_vol": 0.06, "accumulation": 0.15,
    }

    # Technische strategie-namen (geen AI of sentiment)
    TECH_NAMES = {
        "EMA_Cross", "Bollinger", "RSI", "MACD", "Breakout",
        "SMC", "SR", "Ichimoku", "Wyckoff", "VolumeProfile",
        "MarketStructure", "Grid",
    }

    def __init__(self, trades_path: str = "logs/trades.json"):
        self.edge = EdgeDetector(trades_path)

    def classify(
        self,
        signal: dict,
        action: int,
        confidence: float,
        regime_value: str,
        regime_strength: float,
        vol_ratio: float,
    ) -> dict:
        """
        Geeft setup-grade, positie-pct en kwaliteitsscore terug.

        Returns:
            {
                "grade": "A+" | "A" | "B" | "C",
                "position_pct": float,
                "quality_pts": int,
                "agreeing_count": int,
                "edge_score": float,
                "edge_positive": bool,
                "skip": bool,  # True als C-setup zonder edge
            }
        """
        details = signal.get("details", [])

        # ── 1. Hoeveel technische strategieën zijn het eens ─────────
        agreeing_count = sum(
            1 for d in details
            if d.get("naam") in self.TECH_NAMES and d.get("actie") == action
        )

        # ── 2. Edge-score: gemiddelde expectancy van meestemmende strategieën ─
        agreeing_names = [
            d["naam"] for d in details
            if d.get("naam") in self.TECH_NAMES and d.get("actie") == action
        ]
        edge_score = self.edge.combo_expectancy(agreeing_names)
        edge_per_regime = max(
            (self.edge.regime_expectancy(n, regime_value) for n in agreeing_names),
            default=0.0,
        )
        # Gecombineerde edge: 60% algemeen + 40% regime-specifiek (indien beschikbaar)
        if edge_per_regime != 0.0:
            combined_edge = 0.6 * edge_score + 0.4 * edge_per_regime
        else:
            combined_edge = edge_score

        edge_positive = combined_edge > 0.001  # positieve verwachte waarde

        # ── 3. Kwaliteitspunten (0-5 schaal) ────────────────────────
        quality_pts = (
            (1 if agreeing_count >= 5   else 0)   # brede confluence
            + (1 if regime_strength >= 0.60 else 0)  # sterk regime
            + (1 if confidence >= 0.50      else 0)  # hoge zekerheid
            + (1 if vol_ratio >= 1.20       else 0)  # volume bevestiging
            + (1 if edge_positive           else 0)  # bewezen edge (historisch)
        )

        # ── 4. Grade bepalen ─────────────────────────────────────────
        # A+: alle 5 punten óf 4 punten inclusief bewezen edge
        # A:  ≥3 punten
        # B:  ≥2 punten
        # C:  <2 punten
        if quality_pts == 5 or (quality_pts >= 4 and edge_positive):
            grade = "A+"
        elif quality_pts >= 3:
            grade = "A"
        elif quality_pts >= 2:
            grade = "B"
        else:
            grade = "C"

        # ── 5. Skip-logica: C-setup met negatieve edge → niet traden ─
        # Alleen actief als er genoeg data is (≥5 samples per strategie)
        edge_data = self.edge.get_edge()
        has_reliable_edge = any(
            edge_data["by_strategy"].get(n, {}).get("samples", 0) >= EdgeDetector.MIN_SAMPLES
            for n in agreeing_names
        )
        skip = (grade == "C") and has_reliable_edge and not edge_positive

        # ── 6. Positiebepaling ───────────────────────────────────────
        regime_cap = self.REGIME_CAP.get(regime_value, 0.10)
        position_pct = min(self.GRADE_PCT[grade], regime_cap)

        # Sample-gebaseerde cap: met weinig data is A+ positiegrootte te riskant.
        # A+ vereist bewezen edge — die hebben we pas bij 50+ closed trades.
        total_samples = sum(
            v.get("samples", 0) for v in edge_data["by_strategy"].values()
        )
        if total_samples < 20:
            position_pct = min(position_pct, self.GRADE_PCT["B"])   # max 8%
        elif total_samples < 50:
            position_pct = min(position_pct, self.GRADE_PCT["A"])   # max 12%

        return {
            "grade": grade,
            "position_pct": position_pct,
            "quality_pts": quality_pts,
            "agreeing_count": agreeing_count,
            "edge_score": round(combined_edge, 4),
            "edge_positive": edge_positive,
            "skip": skip,
        }

    def get_edge_summary(self) -> str:
        """Korte samenvatting voor logging/dashboard."""
        return self.edge.summary()
