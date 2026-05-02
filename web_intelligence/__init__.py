"""
NEXUS Web Intelligence package.

Safe web fetching, news sentiment analysis, market data aggregation,
and chart pattern detection. Integrates with NexusCore and profit_engine.

Quick start:
    from web_intelligence import WebIntelligence, NewsItem

    wi = WebIntelligence()
    wi.start()

    # Analyze a news headline
    result = wi.analyze_news_item(NewsItem(title="Bitcoin surges past $100k"))
    print(result.sentiment, result.score)

    # Detect patterns from OHLC bars
    patterns = wi.detect_patterns("BTC", bars=my_bars)

    # Wire to profit_engine
    from profit_engine import ProfitEngine
    pe = ProfitEngine()
    wi.on_pattern(lambda sym, sigs: pe.process_snapshot(...))
"""

# Rules & violations (always imported first — no internal deps)
from .web_rules import (
    DomainPolicy,
    WebPolicy,
    WebRules,
    WebRulesViolation,
)

# HTTP fetcher
from .fetcher import (
    FetchConfig,
    FetchResult,
    Fetcher,
)

# News analysis
from .news_analyzer import (
    NewsAnalyzer,
    NewsItem,
    Sentiment,
    SentimentResult,
)

# Market data
from .market_data import (
    MarketDataFeed,
    MarketDataStore,
    Normalizer,
    OHLCAggregator,
    OHLCBar,
    TimeFrame,
    Tick,
    DataValidator,
)

# Pattern detection
from .pattern_detector import (
    PatternDetector,
    PatternSignal,
    PatternType,
)

# Facade
from .web_intelligence import (
    IntelligenceReport,
    WebIntelligence,
    WebIntelligenceConfig,
)

__all__ = [
    # Rules
    "DomainPolicy", "WebPolicy", "WebRules", "WebRulesViolation",
    # Fetcher
    "FetchConfig", "FetchResult", "Fetcher",
    # News
    "NewsAnalyzer", "NewsItem", "Sentiment", "SentimentResult",
    # Market data
    "MarketDataFeed", "MarketDataStore", "Normalizer",
    "OHLCAggregator", "OHLCBar", "TimeFrame", "Tick", "DataValidator",
    # Patterns
    "PatternDetector", "PatternSignal", "PatternType",
    # Facade
    "IntelligenceReport", "WebIntelligence", "WebIntelligenceConfig",
]
