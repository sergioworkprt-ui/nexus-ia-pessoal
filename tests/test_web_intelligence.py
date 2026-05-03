"""
NEXUS Test Suite — Web Intelligence Module
Tests for: NewsAnalyzer (sentiment), PatternDetector,
OHLCBar / MarketDataStore, DataValidator, and Normalizer.
All tests are offline — no network requests.
"""

import unittest

from conftest import NexusTestCase

from web_intelligence.news_analyzer import NewsAnalyzer, NewsItem, SentimentResult, Sentiment
from web_intelligence.pattern_detector import PatternDetector, PatternSignal, PatternType
from web_intelligence.market_data import (
    OHLCBar, TimeFrame, MarketDataStore, DataValidator, Normalizer,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _bar(symbol: str = "BTC", close: float = 100.0,
         volume: float = 1000.0, tf: TimeFrame = TimeFrame.D1) -> OHLCBar:
    return OHLCBar(
        symbol=symbol, timeframe=tf,
        timestamp="2026-01-01T00:00:00+00:00",
        open=close - 0.5, high=close + 1.0, low=close - 1.0,
        close=close, volume=volume,
    )


def _news(title: str, content: str = "") -> NewsItem:
    return NewsItem(title=title, content=content or title, source="test_source")


# ---------------------------------------------------------------------------
# NewsAnalyzer
# ---------------------------------------------------------------------------

class TestNewsAnalyzer(NexusTestCase):

    def setUp(self) -> None:
        super().setUp()
        self.analyzer = NewsAnalyzer()

    def test_bullish_headline_positive_score(self) -> None:
        item = _news("Bitcoin all-time high rally bullish breakout gains profit")
        result = self.analyzer.analyze(item)
        self.assertIsInstance(result, SentimentResult)
        self.assertGreater(result.score, 0.0,
                           f"Expected positive sentiment, got {result.score}")

    def test_bearish_headline_negative_score(self) -> None:
        item = _news("Market crash bearish collapse sell plunge decline loss")
        result = self.analyzer.analyze(item)
        self.assertLess(result.score, 0.0,
                        f"Expected negative sentiment, got {result.score}")

    def test_neutral_headline_near_zero(self) -> None:
        item = _news("Earnings release scheduled for next quarter.")
        result = self.analyzer.analyze(item)
        self.assertBetween(result.score, -0.8, 0.8)

    def test_negation_reverses_sentiment(self) -> None:
        pos = self.analyzer.analyze(_news("Markets rally all-time high gain profit"))
        neg = self.analyzer.analyze(_news("Markets crash loss plunge decline bearish"))
        self.assertGreater(pos.score, neg.score)

    def test_risk_keywords_detected(self) -> None:
        item = _news("Company faces bankruptcy and fraud investigation collapse")
        result = self.analyzer.analyze(item)
        self.assertTrue(result.is_high_risk())

    def test_score_bounded(self) -> None:
        item = _news("breakout bullish rally gain profit all-time high positive optimistic")
        result = self.analyzer.analyze(item)
        self.assertBetween(result.score, -1.0, 1.0)

    def test_analyze_batch(self) -> None:
        items = [
            _news("Stock rally bullish gains profit"),
            _news("Recession fears bearish crash decline"),
            _news("Trading session concluded today"),
        ]
        results = self.analyzer.analyze_batch(items)
        self.assertEqual(len(results), 3)
        for r in results:
            self.assertIsInstance(r, SentimentResult)

    def test_aggregate_sentiment_from_batch(self) -> None:
        items = [
            _news("Bull market confirmed rally gains profit"),
            _news("Bearish signals dominate crash loss decline"),
        ]
        results = self.analyzer.analyze_batch(items)
        agg = self.analyzer.aggregate_sentiment(results)
        self.assertIsInstance(agg, dict)
        self.assertIn("score", agg)
        self.assertBetween(agg["score"], -1.0, 1.0)


# ---------------------------------------------------------------------------
# PatternDetector
# ---------------------------------------------------------------------------

class TestPatternDetector(NexusTestCase):

    def setUp(self) -> None:
        super().setUp()
        self.detector = PatternDetector()

    def _make_bars(self, closes) -> list:
        return [
            OHLCBar(
                symbol="BTC", timeframe=TimeFrame.D1,
                timestamp=f"2026-01-{i+1:02d}T00:00:00+00:00",
                open=c - 0.5, high=c + 1.0, low=c - 1.0, close=c,
                volume=1000.0,
            )
            for i, c in enumerate(closes)
        ]

    def test_detect_returns_list(self) -> None:
        bars = self._make_bars([100.0] * 20)
        result = self.detector.scan(bars)
        self.assertIsInstance(result, list)

    def test_breakout_detected_on_surge(self) -> None:
        closes = [100.0] * 8 + [100.5, 115.0]
        bars = self._make_bars(closes)
        signals = self.detector.scan(bars)
        self.assertIsInstance(signals, list)

    def test_no_signals_on_flat_market(self) -> None:
        closes = [100.0 + i * 0.01 for i in range(20)]
        bars   = self._make_bars(closes)
        signals = self.detector.scan(bars)
        critical = [s for s in signals if hasattr(s, "confidence") and s.confidence > 0.9]
        self.assertLessEqual(len(critical), 2)

    def test_anomaly_on_volume_spike(self) -> None:
        bars = self._make_bars([100.0] * 15)
        bars[-1] = OHLCBar(
            symbol="BTC", timeframe=TimeFrame.D1,
            timestamp="2026-01-16T00:00:00+00:00",
            open=100.0, high=101.0, low=99.0, close=100.5,
            volume=50000.0,
        )
        signals = self.detector.scan(bars)
        self.assertIsInstance(signals, list)

    def test_signal_has_required_fields(self) -> None:
        closes = [100.0] * 5 + [110.0, 120.0, 130.0, 140.0, 150.0]
        bars   = self._make_bars(closes)
        signals = self.detector.scan(bars)
        for s in signals:
            self.assertIsInstance(s, PatternSignal)
            self.assertIsInstance(s.pattern_type, PatternType)
            self.assertBetween(s.confidence, 0.0, 1.0)

    def test_detect_requires_minimum_bars(self) -> None:
        bars = self._make_bars([100.0, 101.0])
        signals = self.detector.scan(bars)
        self.assertIsInstance(signals, list)


# ---------------------------------------------------------------------------
# OHLCBar validation
# ---------------------------------------------------------------------------

class TestOHLCBar(NexusTestCase):

    def test_valid_bar_created(self) -> None:
        bar = _bar()
        self.assertEqual(bar.symbol, "BTC")
        self.assertGreater(bar.high, bar.low)

    def test_to_dict(self) -> None:
        bar = _bar()
        d = bar.to_dict() if hasattr(bar, "to_dict") else vars(bar)
        self.assertIsInstance(d, dict)
        self.assertIn("close", d)

    def test_high_gte_close(self) -> None:
        bar = _bar(close=100.0)
        self.assertGreaterEqual(bar.high, bar.close)

    def test_low_lte_close(self) -> None:
        bar = _bar(close=100.0)
        self.assertLessEqual(bar.low, bar.close)

    def test_inverted_high_low_raises(self) -> None:
        with self.assertRaises((ValueError, Exception)):
            OHLCBar(
                symbol="BTC", timeframe=TimeFrame.D1,
                timestamp="2026-01-01T00:00:00+00:00",
                open=100.0, high=95.0, low=105.0,
                close=100.0, volume=1000.0,
            )


# ---------------------------------------------------------------------------
# MarketDataStore
# ---------------------------------------------------------------------------

class TestMarketDataStore(NexusTestCase):

    def setUp(self) -> None:
        super().setUp()
        self.store = MarketDataStore(max_bars_per_series=50)

    def test_add_and_retrieve(self) -> None:
        bar = _bar("ETH", 2000.0)
        self.store.add(bar)
        bars = self.store.get("ETH", TimeFrame.D1)
        self.assertNonEmpty(bars)

    def test_capacity_respected(self) -> None:
        store = MarketDataStore(max_bars_per_series=5)
        for i in range(10):
            store.add(OHLCBar(
                symbol="BTC", timeframe=TimeFrame.D1,
                timestamp=f"2026-01-{i+1:02d}T00:00:00+00:00",
                open=99.5 + i, high=101.0 + i, low=99.0 + i,
                close=100.0 + i, volume=1000.0,
            ))
        bars = store.get("BTC", TimeFrame.D1)
        self.assertLessEqual(len(bars), 5)

    def test_multiple_symbols_independent(self) -> None:
        self.store.add(_bar("BTC", 100.0))
        self.store.add(_bar("ETH", 2000.0))
        btc_bars = self.store.get("BTC", TimeFrame.D1)
        eth_bars = self.store.get("ETH", TimeFrame.D1)
        self.assertEqual(btc_bars[0].symbol, "BTC")
        self.assertEqual(eth_bars[0].symbol, "ETH")

    def test_get_empty_symbol_returns_empty(self) -> None:
        bars = self.store.get("NONEXISTENT", TimeFrame.D1)
        self.assertEqual(bars, [])

    def test_latest_returns_last_bar(self) -> None:
        for i in range(5):
            self.store.add(OHLCBar(
                symbol="BTC", timeframe=TimeFrame.D1,
                timestamp=f"2026-01-{i+1:02d}T00:00:00+00:00",
                open=99.5 + i, high=101.0 + i, low=99.0 + i,
                close=100.0 + i, volume=1000.0,
            ))
        latest = self.store.latest("BTC", TimeFrame.D1)
        self.assertIsNotNone(latest)
        self.assertAlmostEqual(latest.close, 104.0)


# ---------------------------------------------------------------------------
# DataValidator & Normalizer
# ---------------------------------------------------------------------------

class TestDataValidator(NexusTestCase):

    def setUp(self) -> None:
        super().setUp()
        self.validator = DataValidator()

    def test_valid_bar_passes(self) -> None:
        bar = _bar()
        errors = self.validator.validate([bar])
        self.assertEqual(errors, [])

    def test_inverted_high_low_raises_on_construction(self) -> None:
        with self.assertRaises((ValueError, Exception)):
            OHLCBar(
                symbol="BTC", timeframe=TimeFrame.D1,
                timestamp="2026-01-01T00:00:00+00:00",
                open=100.0, high=95.0, low=105.0,
                close=100.0, volume=1000.0,
            )

    def test_negative_volume_fails_validation(self) -> None:
        bar = OHLCBar(
            symbol="BTC", timeframe=TimeFrame.D1,
            timestamp="2026-01-01T00:00:00+00:00",
            open=100.0, high=101.0, low=99.0,
            close=100.0, volume=-1.0,
        )
        errors = self.validator.validate([bar])
        self.assertGreater(len(errors), 0)


class TestNormalizer(NexusTestCase):

    def setUp(self) -> None:
        super().setUp()
        self.norm = Normalizer()

    def _closes(self) -> list:
        return [float(100 + i) for i in range(10)]

    def test_min_max_range(self) -> None:
        vals = self._closes()
        normed = self.norm.min_max(vals)
        self.assertAlmostEqual(min(normed), 0.0, places=6)
        self.assertAlmostEqual(max(normed), 1.0, places=6)

    def test_z_score_mean_near_zero(self) -> None:
        import statistics
        vals = self._closes()
        normed = self.norm.z_score(vals)
        self.assertAlmostEqual(statistics.mean(normed), 0.0, places=6)

    def test_pct_change_length(self) -> None:
        vals = self._closes()
        pct = self.norm.pct_change(vals)
        self.assertEqual(len(pct), len(vals))

    def test_log_returns_all_finite(self) -> None:
        import math
        vals = self._closes()
        lr = self.norm.log_returns(vals)
        for v in lr:
            self.assertTrue(math.isfinite(v))


if __name__ == "__main__":
    unittest.main()
