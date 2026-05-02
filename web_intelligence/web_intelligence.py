"""
NEXUS Web Intelligence — Facade
Integrates fetcher, news analyzer, market data store, and pattern detector
into a single entry point. Provides hooks for the profit_engine and NexusCore.
"""

from __future__ import annotations

import threading
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Callable, Dict, List, Optional

from .fetcher import FetchConfig, FetchResult, Fetcher
from .market_data import (
    MarketDataStore, Normalizer, OHLCBar, OHLCAggregator, TimeFrame,
)
from .news_analyzer import NewsAnalyzer, NewsItem, SentimentResult
from .pattern_detector import PatternDetector, PatternSignal
from .web_rules import WebPolicy, WebRules, WebRulesViolation


# ---------------------------------------------------------------------------
# Intelligence report
# ---------------------------------------------------------------------------

@dataclass
class IntelligenceReport:
    """Aggregated output of a full web intelligence scan."""
    generated_at: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())
    symbols:      List[str] = field(default_factory=list)
    sentiment:    Dict[str, Any] = field(default_factory=dict)    # per symbol or global
    patterns:     List[Dict[str, Any]] = field(default_factory=list)
    news_items:   int = 0
    errors:       List[str] = field(default_factory=list)

    def summary(self) -> Dict[str, Any]:
        return {
            "generated_at": self.generated_at,
            "symbols":      self.symbols,
            "news_items":   self.news_items,
            "patterns":     len(self.patterns),
            "errors":       len(self.errors),
            "sentiment":    self.sentiment,
        }


# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------

@dataclass
class WebIntelligenceConfig:
    data_dir:           str   = "data/web_intelligence"
    max_bars_stored:    int   = 5_000
    fetch_timeout:      float = 15.0
    max_retries:        int   = 3
    rotate_user_agents: bool  = True
    pattern_min_bars:   int   = 30
    news_min_confidence: float = 0.3
    news_min_impact:    float  = 0.2


# ---------------------------------------------------------------------------
# WebIntelligence facade
# ---------------------------------------------------------------------------

class WebIntelligence:
    """
    Central intelligence hub for the NEXUS system.

    Responsibilities:
    - Safe HTTP fetching (via Fetcher + WebRules)
    - News sentiment and risk analysis
    - Market OHLC data storage and retrieval
    - Chart pattern detection
    - Signal hook dispatch to profit_engine

    Usage (standalone):
        wi = WebIntelligence()
        wi.start()
        result = wi.analyze_news_item(NewsItem(title="Bitcoin surges to new ATH"))
        patterns = wi.detect_patterns("BTC", bars)

    Usage (with NexusCore):
        from core import get_core
        wi = WebIntelligence.from_core(get_core())
        wi.start()
    """

    def __init__(
        self,
        config: Optional[WebIntelligenceConfig] = None,
        policy: Optional[WebPolicy] = None,
    ) -> None:
        self._config  = config or WebIntelligenceConfig()
        self._running = False

        self._rules   = WebRules(policy or WebPolicy())
        fetch_cfg     = FetchConfig(
            timeout_seconds    = self._config.fetch_timeout,
            max_retries        = self._config.max_retries,
            rotate_user_agents = self._config.rotate_user_agents,
        )
        self._fetcher   = Fetcher(config=fetch_cfg, rules=self._rules)
        self._news      = NewsAnalyzer()
        self._store     = MarketDataStore(max_bars_per_series=self._config.max_bars_stored)
        self._detector  = PatternDetector(min_bars=self._config.pattern_min_bars)
        self._aggregator = OHLCAggregator()

        # Profit-engine signal hooks (called when actionable intelligence is found)
        self._signal_hooks: List[Callable[[str, List[PatternSignal]], None]] = []
        self._news_hooks:   List[Callable[[SentimentResult], None]] = []

        # Optional core integration
        self._logger = None
        self._memory = None
        self._lock   = threading.Lock()

    # ------------------------------------------------------------------
    # Lifecycle
    # ------------------------------------------------------------------

    @classmethod
    def from_core(
        cls,
        core: Any,
        config: Optional[WebIntelligenceConfig] = None,
        policy: Optional[WebPolicy] = None,
    ) -> "WebIntelligence":
        """Create a WebIntelligence instance wired to a running NexusCore."""
        instance = cls(config, policy)
        instance._logger = core.logger
        instance._memory = core.memory

        # Optionally wire the security manager's blocked patterns into WebRules
        try:
            sec_policy = core.security._policy
            for pat in getattr(sec_policy, "blocked_patterns", []):
                instance._rules._policy.blocked_domains.add(pat)
        except Exception:
            pass

        return instance

    def start(self) -> None:
        self._running = True
        self._log("web_intelligence", "WebIntelligence subsystem started.")

    def stop(self) -> None:
        self._running = False
        self._log("web_intelligence", "WebIntelligence subsystem stopped.")

    # ------------------------------------------------------------------
    # HTTP fetching
    # ------------------------------------------------------------------

    def fetch(self, url: str, params: Optional[Dict[str, str]] = None) -> FetchResult:
        """Fetch a URL safely, enforcing all WebRules."""
        return self._fetcher.get(url, params=params)

    def fetch_json(self, url: str, params: Optional[Dict[str, str]] = None) -> Any:
        return self._fetcher.fetch_json(url, params=params)

    def fetch_text(self, url: str, params: Optional[Dict[str, str]] = None) -> str:
        return self._fetcher.fetch_text(url, params=params)

    # ------------------------------------------------------------------
    # News analysis
    # ------------------------------------------------------------------

    def analyze_news_item(self, item: NewsItem) -> SentimentResult:
        """Analyze a single NewsItem and fire any registered news hooks."""
        result = self._news.analyze(item)
        self._log("web_intelligence",
                  f"News analyzed: '{item.title[:60]}' → {result.sentiment.value} "
                  f"(score={result.score}, risk={result.risk_score})")
        if result.is_actionable(self._config.news_min_confidence, self._config.news_min_impact):
            for hook in self._news_hooks:
                try:
                    hook(result)
                except Exception:
                    pass
        if self._memory and result.risk_flags:
            self._memory.remember(
                f"news_risk_{datetime.now(timezone.utc).strftime('%Y%m%d%H%M%S')}",
                result.to_dict(), permanent=True,
            )
        return result

    def analyze_headlines(self, headlines: List[str], source: str = "unknown") -> Dict[str, Any]:
        """Score a batch of headline strings and return aggregated sentiment."""
        items   = [NewsItem(title=h, source=source) for h in headlines]
        results = self._news.analyze_batch(items)
        return self._news.aggregate_sentiment(results)

    def fetch_and_analyze(self, url: str, title_selector: Optional[str] = None) -> Optional[SentimentResult]:
        """
        Fetch a URL and analyze its text content as a news item.
        Returns None if the fetch fails or content is not text.
        """
        try:
            result = self._fetcher.get(url)
            if not result.ok:
                self._log("web_intelligence", f"Fetch failed {result.status_code}: {url}", level="warning")
                return None
            text = result.text()[:2000]   # cap to first 2 KB for analysis
            item = NewsItem(title=text[:200], content=text, url=url, source=url)
            return self.analyze_news_item(item)
        except WebRulesViolation as exc:
            self._log("web_intelligence", f"Fetch blocked: {exc}", level="warning")
            return None

    # ------------------------------------------------------------------
    # Market data
    # ------------------------------------------------------------------

    def ingest_bar(self, bar: OHLCBar) -> None:
        """Add an OHLC bar to the internal data store."""
        self._store.add(bar)

    def ingest_bars(self, bars: List[OHLCBar]) -> None:
        for bar in bars:
            self._store.add(bar)

    def get_bars(
        self,
        symbol: str,
        timeframe: TimeFrame = TimeFrame.D1,
        limit: int = 200,
    ) -> List[OHLCBar]:
        return self._store.get(symbol, timeframe, limit=limit)

    def get_latest(self, symbol: str, timeframe: TimeFrame = TimeFrame.D1) -> Optional[OHLCBar]:
        return self._store.latest(symbol, timeframe)

    # ------------------------------------------------------------------
    # Pattern detection
    # ------------------------------------------------------------------

    def detect_patterns(
        self,
        symbol: str,
        bars: Optional[List[OHLCBar]] = None,
        timeframe: TimeFrame = TimeFrame.D1,
    ) -> List[PatternSignal]:
        """
        Detect patterns in the provided bars (or fetched from the store).
        Fires registered signal hooks for actionable signals.
        """
        if bars is None:
            bars = self._store.get(symbol, timeframe, limit=500)
        signals = self._detector.scan(bars, symbol=symbol)
        actionable = [s for s in signals if s.is_actionable()]
        if actionable:
            for hook in self._signal_hooks:
                try:
                    hook(symbol, actionable)
                except Exception:
                    pass
            self._log(
                "web_intelligence",
                f"Patterns for '{symbol}': {len(actionable)} actionable "
                f"({', '.join(s.pattern_type.value for s in actionable[:3])})",
            )
        return signals

    # ------------------------------------------------------------------
    # Full intelligence scan
    # ------------------------------------------------------------------

    def scan(
        self,
        symbols: List[str],
        news_items: Optional[List[NewsItem]] = None,
        timeframe: TimeFrame = TimeFrame.D1,
    ) -> IntelligenceReport:
        """
        Run a full intelligence cycle:
        1. Analyze provided news items
        2. Detect patterns for each symbol
        Returns a consolidated IntelligenceReport.
        """
        report = IntelligenceReport(symbols=symbols)

        # News
        if news_items:
            results = self._news.analyze_batch(news_items)
            report.news_items = len(results)
            report.sentiment  = self._news.aggregate_sentiment(results)
            for r in results:
                if r.is_actionable():
                    for hook in self._news_hooks:
                        try:
                            hook(r)
                        except Exception:
                            pass

        # Patterns
        for symbol in symbols:
            try:
                signals = self.detect_patterns(symbol, timeframe=timeframe)
                report.patterns.extend(s.to_dict() for s in signals)
            except Exception as exc:
                report.errors.append(f"{symbol}: {exc}")

        self._log("web_intelligence", "Intelligence scan complete.", **report.summary())
        return report

    # ------------------------------------------------------------------
    # Hooks (profit_engine integration)
    # ------------------------------------------------------------------

    def on_pattern(self, fn: Callable[[str, List[PatternSignal]], None]) -> None:
        """Register a callback invoked when actionable patterns are detected."""
        self._signal_hooks.append(fn)

    def on_news(self, fn: Callable[[SentimentResult], None]) -> None:
        """Register a callback invoked when actionable news is analyzed."""
        self._news_hooks.append(fn)

    # ------------------------------------------------------------------
    # Status & introspection
    # ------------------------------------------------------------------

    def status(self) -> Dict[str, Any]:
        return {
            "running":     self._running,
            "data_store":  self._store.stats(),
            "rules":       self._rules.snapshot(),
            "news_hooks":  len(self._news_hooks),
            "pattern_hooks": len(self._signal_hooks),
        }

    def policy(self) -> Dict[str, Any]:
        return self._rules.snapshot()

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _log(self, module: str, message: str, level: str = "info", **kwargs: Any) -> None:
        if self._logger:
            getattr(self._logger, level, self._logger.info)(module, message, **kwargs)
