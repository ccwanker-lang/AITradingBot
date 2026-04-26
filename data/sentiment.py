"""
Sentiment analyse — Fear & Greed Index + crypto nieuws.
Gebruikt gratis publieke API's, geen authenticatie nodig.
"""
import time
import requests


class SentimentAnalyzer:
    FEAR_GREED_URL = "https://api.alternative.me/fng/?limit=1"
    NEWS_URL = "https://min-api.cryptocompare.com/data/v2/news/?lang=EN&categories=BTC"

    def __init__(self):
        self._fear_cache: tuple[float, float] = (0.0, 0.0)  # (score, timestamp)
        self._news_cache: tuple[float, float] = (0.0, 0.0)
        self._cache_ttl = 3600  # 1 uur

    def get_fear_greed(self) -> dict:
        score, ts = self._fear_cache
        if time.time() - ts < self._cache_ttl:
            return {"score": score, "signal": self._score_to_signal(score)}

        try:
            r = requests.get(self.FEAR_GREED_URL, timeout=5)
            data = r.json()["data"][0]
            raw = int(data["value"])  # 0-100
            # Normaliseer naar -1..+1 (0=extreme fear → -1, 100=extreme greed → +1)
            score = (raw - 50) / 50.0
            self._fear_cache = (score, time.time())
        except Exception:
            score = 0.0

        return {
            "score": score,
            "signal": self._score_to_signal(score),
            "label": self._score_to_label(score),
        }

    def get_news_sentiment(self) -> dict:
        score, ts = self._news_cache
        if time.time() - ts < self._cache_ttl:
            return {"score": score, "signal": self._score_to_signal(score)}

        try:
            r = requests.get(self.NEWS_URL, timeout=5)
            articles = r.json().get("Data", [])[:20]

            positive_words = {
                "bull", "surge", "rally", "breakout", "ATH", "gain", "rise",
                "adoption", "buy", "bullish", "green", "record", "high", "up",
            }
            negative_words = {
                "bear", "crash", "drop", "sell", "dump", "hack", "ban", "loss",
                "fear", "bearish", "red", "low", "fall", "down", "scam",
            }

            total_score = 0.0
            for article in articles:
                text = (article.get("title", "") + " " + article.get("body", "")[:300]).lower()
                pos = sum(1 for w in positive_words if w in text)
                neg = sum(1 for w in negative_words if w in text)
                if pos + neg > 0:
                    total_score += (pos - neg) / (pos + neg)

            score = max(-1.0, min(1.0, total_score / max(len(articles), 1)))
            self._news_cache = (score, time.time())
        except Exception:
            score = 0.0

        return {
            "score": score,
            "signal": self._score_to_signal(score),
        }

    def combined_sentiment(self) -> dict:
        fg = self.get_fear_greed()
        news = self.get_news_sentiment()
        # Fear & Greed krijgt meer gewicht (betrouwbaarder)
        combined = fg["score"] * 0.65 + news["score"] * 0.35
        return {
            "score": combined,
            "signal": self._score_to_signal(combined),
            "fear_greed": fg["score"],
            "news": news["score"],
            "label": fg.get("label", "neutraal"),
        }

    def _score_to_signal(self, score: float) -> int:
        if score > 0.20:
            return 1
        if score < -0.20:
            return -1
        return 0

    def _score_to_label(self, score: float) -> str:
        if score > 0.60:
            return "Extreme Hebzucht"
        if score > 0.20:
            return "Hebzucht"
        if score < -0.60:
            return "Extreme Angst"
        if score < -0.20:
            return "Angst"
        return "Neutraal"
