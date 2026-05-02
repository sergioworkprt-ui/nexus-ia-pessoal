"""
NEXUS Web Intelligence — News Analyzer
Keyword-based headline sentiment scoring, risk detection, and market impact
estimation. Zero external dependencies — no NLP libraries required.
"""

from __future__ import annotations

import re
import statistics
from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from typing import Any, Dict, List, Optional, Set, Tuple


# ---------------------------------------------------------------------------
# Sentiment & risk word lists (finance-domain)
# ---------------------------------------------------------------------------

_BULLISH_WORDS: Dict[str, float] = {
    # Strong positive signals
    "surge": 0.9, "rally": 0.8, "breakout": 0.8, "soar": 0.9, "spike": 0.7,
    "record high": 0.9, "all-time high": 0.9, "beat expectations": 0.8,
    "upgrade": 0.7, "outperform": 0.7, "buy": 0.6, "strong buy": 0.9,
    "profit": 0.6, "growth": 0.6, "expansion": 0.6, "revenue beat": 0.8,
    "earnings beat": 0.8, "positive": 0.5, "gain": 0.6, "rise": 0.5,
    "recovery": 0.6, "rebound": 0.7, "bullish": 0.8, "optimistic": 0.6,
    "acquisition": 0.5, "partnership": 0.5, "deal": 0.5, "merger": 0.5,
    "dividend": 0.5, "buyback": 0.6, "share repurchase": 0.6,
}

_BEARISH_WORDS: Dict[str, float] = {
    # Strong negative signals
    "crash": 0.9, "plunge": 0.9, "collapse": 0.9, "plummet": 0.9,
    "sell-off": 0.8, "selloff": 0.8, "bear": 0.7, "bearish": 0.8,
    "decline": 0.6, "fall": 0.5, "drop": 0.6, "slump": 0.7,
    "miss expectations": 0.8, "earnings miss": 0.8, "revenue miss": 0.8,
    "downgrade": 0.7, "underperform": 0.7, "sell": 0.6, "strong sell": 0.9,
    "loss": 0.6, "deficit": 0.6, "contraction": 0.6, "recession": 0.8,
    "layoffs": 0.7, "job cuts": 0.7, "restructuring": 0.5,
    "warning": 0.6, "concern": 0.5, "risk": 0.4, "uncertainty": 0.5,
    "inflation": 0.5, "rate hike": 0.6, "tightening": 0.5,
}

_RISK_WORDS: Dict[str, float] = {
    # High-impact risk flags — these elevate risk_score regardless of sentiment
    "fraud": 1.0, "scandal": 0.9, "investigation": 0.8, "sec probe": 1.0,
    "bankruptcy": 1.0, "insolvency": 1.0, "default": 0.9,
    "lawsuit": 0.7, "litigation": 0.7, "settlement": 0.6,
    "hack": 0.8, "breach": 0.8, "cyberattack": 0.9,
    "recall": 0.7, "fine": 0.6, "penalty": 0.6, "sanctions": 0.8,
    "delisting": 0.9, "halt": 0.7, "suspended": 0.7,
    "short seller": 0.7, "short attack": 0.8,
    "restatement": 0.8, "accounting irregularities": 1.0,
}

_NEGATION_WORDS: Set[str] = {
    "not", "no", "never", "neither", "nor", "without", "barely",
    "hardly", "scarcely", "seldom", "rarely",
}

_INTENSIFIERS: Dict[str, float] = {
    "very": 1.3, "extremely": 1.5, "highly": 1.3, "massively": 1.5,
    "significantly": 1.3, "sharply": 1.3, "dramatically": 1.4,
    "slightly": 0.7, "marginally": 0.6, "somewhat": 0.8,
}


# ---------------------------------------------------------------------------
# Data structures
# ---------------------------------------------------------------------------

class Sentiment(str, Enum):
    BULLISH = "bullish"
    BEARISH = "bearish"
    NEUTRAL = "neutral"


@dataclass
class NewsItem:
    """A single news article or headline for analysis."""
    title:      str
    content:    str           = ""
    source:     str           = "unknown"
    url:        str           = ""
    published:  str           = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())
    symbols:    List[str]     = field(default_factory=list)
    metadata:   Dict[str, Any] = field(default_factory=dict)

    def full_text(self) -> str:
        return f"{self.title} {self.content}".strip()


@dataclass
class SentimentResult:
    """Outcome of analyzing a single NewsItem."""
    item:          NewsItem
    sentiment:     Sentiment
    score:         float          # -1.0 (max bearish) to +1.0 (max bullish)
    confidence:    float          # 0.0 – 1.0
    risk_score:    float          # 0.0 – 1.0 (independent of sentiment direction)
    risk_flags:    List[str]      # specific risk keywords detected
    bullish_words: List[str]
    bearish_words: List[str]
    impact:        float          # 0.0 – 1.0 estimated market impact
    analyzed_at:   str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())

    def is_high_risk(self, threshold: float = 0.6) -> bool:
        return self.risk_score >= threshold

    def is_actionable(self, min_confidence: float = 0.4, min_impact: float = 0.3) -> bool:
        return (self.confidence >= min_confidence and
                self.impact >= min_impact and
                self.sentiment != Sentiment.NEUTRAL)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "title":       self.item.title,
            "source":      self.item.source,
            "sentiment":   self.sentiment.value,
            "score":       round(self.score, 4),
            "confidence":  round(self.confidence, 4),
            "risk_score":  round(self.risk_score, 4),
            "risk_flags":  self.risk_flags,
            "impact":      round(self.impact, 4),
            "analyzed_at": self.analyzed_at,
        }


# ---------------------------------------------------------------------------
# Source credibility weights
# ---------------------------------------------------------------------------

_SOURCE_WEIGHTS: Dict[str, float] = {
    "bloomberg":     1.0,
    "reuters":       1.0,
    "ft.com":        0.95,
    "wsj":           0.95,
    "cnbc":          0.85,
    "marketwatch":   0.80,
    "seeking alpha": 0.65,
    "yahoo finance": 0.70,
    "twitter":       0.40,
    "reddit":        0.35,
    "unknown":       0.50,
}


# ---------------------------------------------------------------------------
# News Analyzer
# ---------------------------------------------------------------------------

class NewsAnalyzer:
    """
    Scores news items for sentiment, risk, and estimated market impact.

    Algorithm:
    1. Tokenise text into lower-case n-grams (1 and 2 tokens)
    2. Score bullish / bearish word matches with intensity and negation modifiers
    3. Aggregate into a [-1, 1] sentiment score
    4. Separately score risk keywords (additive, independent of direction)
    5. Estimate impact from |score| × source_weight × risk amplification
    """

    def __init__(
        self,
        custom_bullish: Optional[Dict[str, float]] = None,
        custom_bearish: Optional[Dict[str, float]] = None,
        custom_risk:    Optional[Dict[str, float]] = None,
    ) -> None:
        self._bullish = {**_BULLISH_WORDS, **(custom_bullish or {})}
        self._bearish = {**_BEARISH_WORDS, **(custom_bearish or {})}
        self._risk    = {**_RISK_WORDS,    **(custom_risk    or {})}

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def analyze(self, item: NewsItem) -> SentimentResult:
        """Analyze a single NewsItem and return a SentimentResult."""
        text   = item.full_text().lower()
        tokens = self._tokenize(text)
        bigrams = self._bigrams(tokens)
        all_grams = tokens + bigrams

        bull_hits, bear_hits, risk_hits = self._scan(all_grams, tokens)

        raw_score  = self._aggregate_score(bull_hits, bear_hits)
        risk_score = min(1.0, sum(v for _, v in risk_hits) / max(len(risk_hits), 1) +
                        len(risk_hits) * 0.05)
        risk_score = min(1.0, risk_score)

        # High risk amplifies bearish signal
        if risk_hits and raw_score >= 0:
            raw_score *= max(0.0, 1.0 - risk_score * 0.5)

        confidence   = self._confidence(bull_hits, bear_hits, len(tokens))
        source_weight = self._source_weight(item.source)
        impact       = min(1.0, abs(raw_score) * source_weight *
                          (1.0 + risk_score * 0.3) * confidence)

        sentiment = (Sentiment.BULLISH if raw_score > 0.1
                     else Sentiment.BEARISH if raw_score < -0.1
                     else Sentiment.NEUTRAL)

        return SentimentResult(
            item=item,
            sentiment=sentiment,
            score=round(max(-1.0, min(1.0, raw_score)), 4),
            confidence=round(confidence, 4),
            risk_score=round(risk_score, 4),
            risk_flags=[w for w, _ in risk_hits],
            bullish_words=[w for w, _ in bull_hits],
            bearish_words=[w for w, _ in bear_hits],
            impact=round(impact, 4),
        )

    def analyze_batch(self, items: List[NewsItem]) -> List[SentimentResult]:
        return [self.analyze(item) for item in items]

    def score_headline(self, text: str, source: str = "unknown") -> SentimentResult:
        """Convenience: analyze a raw headline string."""
        return self.analyze(NewsItem(title=text, source=source))

    def aggregate_sentiment(self, results: List[SentimentResult]) -> Dict[str, Any]:
        """
        Roll up multiple SentimentResults into a single consensus signal.
        Weighted by confidence × impact.
        """
        if not results:
            return {"sentiment": Sentiment.NEUTRAL.value, "score": 0.0,
                    "confidence": 0.0, "items": 0}

        weights = [r.confidence * r.impact for r in results]
        total_w = sum(weights) or 1.0
        w_score = sum(r.score * w for r, w in zip(results, weights)) / total_w
        avg_risk = statistics.mean(r.risk_score for r in results)
        avg_conf = statistics.mean(r.confidence for r in results)

        sentiment = (Sentiment.BULLISH if w_score > 0.1
                     else Sentiment.BEARISH if w_score < -0.1
                     else Sentiment.NEUTRAL)

        return {
            "sentiment":  sentiment.value,
            "score":      round(w_score, 4),
            "confidence": round(avg_conf, 4),
            "risk_score": round(avg_risk, 4),
            "items":      len(results),
            "bullish":    sum(1 for r in results if r.sentiment == Sentiment.BULLISH),
            "bearish":    sum(1 for r in results if r.sentiment == Sentiment.BEARISH),
            "neutral":    sum(1 for r in results if r.sentiment == Sentiment.NEUTRAL),
            "high_risk":  sum(1 for r in results if r.is_high_risk()),
        }

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _scan(
        self, grams: List[str], tokens: List[str]
    ) -> Tuple[List[Tuple[str, float]], List[Tuple[str, float]], List[Tuple[str, float]]]:
        """Return (bullish_hits, bearish_hits, risk_hits) weighted lists."""
        bull: List[Tuple[str, float]] = []
        bear: List[Tuple[str, float]] = []
        risk: List[Tuple[str, float]] = []

        for i, gram in enumerate(grams):
            # Negation window: look 3 tokens back in unigrams
            negated   = self._is_negated(tokens, i) if " " not in gram else False
            intensify = self._intensifier(tokens, i) if " " not in gram else 1.0

            if gram in self._bullish:
                weight = self._bullish[gram] * intensify * (-1 if negated else 1)
                (bear if negated else bull).append((gram, abs(weight)))
            elif gram in self._bearish:
                weight = self._bearish[gram] * intensify * (-1 if negated else 1)
                (bull if negated else bear).append((gram, abs(weight)))

            if gram in self._risk:
                risk.append((gram, self._risk[gram]))

        return bull, bear, risk

    def _aggregate_score(
        self,
        bull: List[Tuple[str, float]],
        bear: List[Tuple[str, float]],
    ) -> float:
        total_bull = sum(v for _, v in bull)
        total_bear = sum(v for _, v in bear)
        total = total_bull + total_bear
        if total == 0:
            return 0.0
        return (total_bull - total_bear) / total

    def _confidence(
        self,
        bull: List[Tuple[str, float]],
        bear: List[Tuple[str, float]],
        n_tokens: int,
    ) -> float:
        hit_count = len(bull) + len(bear)
        if hit_count == 0 or n_tokens == 0:
            return 0.0
        density   = min(hit_count / max(n_tokens, 1) * 10, 1.0)
        dominance = abs(len(bull) - len(bear)) / max(hit_count, 1)
        return round((density * 0.4 + dominance * 0.6), 4)

    def _is_negated(self, tokens: List[str], idx: int) -> bool:
        window = tokens[max(0, idx - 3):idx]
        return any(w in _NEGATION_WORDS for w in window)

    def _intensifier(self, tokens: List[str], idx: int) -> float:
        if idx > 0:
            prev = tokens[idx - 1]
            if prev in _INTENSIFIERS:
                return _INTENSIFIERS[prev]
        return 1.0

    def _source_weight(self, source: str) -> float:
        src = source.lower()
        for key, weight in _SOURCE_WEIGHTS.items():
            if key in src:
                return weight
        return _SOURCE_WEIGHTS["unknown"]

    @staticmethod
    def _tokenize(text: str) -> List[str]:
        text = re.sub(r"[^\w\s\-]", " ", text)
        return [t for t in text.lower().split() if len(t) > 1]

    @staticmethod
    def _bigrams(tokens: List[str]) -> List[str]:
        return [f"{tokens[i]} {tokens[i+1]}" for i in range(len(tokens) - 1)]
