from typing import List, Dict
from nexus.services.logger.logger import get_logger

log = get_logger("ml")


class MLModule:
    def __init__(self):
        self._cache: Dict[str, float] = {}
        self._predictions: List[Dict] = []

    def sentiment(self, text: str) -> float:
        if text in self._cache:
            return self._cache[text]
        try:
            from textblob import TextBlob
            score = float(TextBlob(text).sentiment.polarity)
        except ImportError:
            score = 0.0
        self._cache[text] = score
        return score

    def classify_news(self, headline: str) -> str:
        s = self.sentiment(headline)
        if s > 0.2:
            return "bullish"
        if s < -0.2:
            return "bearish"
        return "neutral"

    def predict_trend(self, prices: List[float], window: int = 5) -> str:
        if len(prices) < window:
            return "insufficient_data"
        ma = sum(prices[-window:]) / window
        last = prices[-1]
        if last > ma * 1.01:
            return "uptrend"
        if last < ma * 0.99:
            return "downtrend"
        return "sideways"

    def status(self) -> Dict:
        return {"cache_size": len(self._cache), "predictions": len(self._predictions)}
