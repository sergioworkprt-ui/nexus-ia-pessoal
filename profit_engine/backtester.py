"""
NEXUS Profit Engine — Backtester
Offline strategy backtesting with pluggable data feeds, slippage, commissions,
and full performance metrics. No live broker dependency.
"""

from __future__ import annotations

import math
import statistics
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Callable, Dict, Iterator, List, Optional, Protocol

from ._types import Bar, Fill, Order, OrderType, Side, Trade
from .execution_simulator import ExecutionConfig, ExecutionSimulator, FixedBpsSlippage
from .portfolio_manager import PortfolioManager
from .risk_manager import RiskLimits, RiskManager, RiskViolation
from .rules import TradingRules, TradingRulesViolation
from .strategy_engine import MarketSnapshot, Signal, Strategy


# ---------------------------------------------------------------------------
# Data feed protocol (pluggable)
# ---------------------------------------------------------------------------

class DataFeed(Protocol):
    """
    Any object implementing this protocol can serve as a backtest data source.
    Implement in your own module and pass to Backtester.run().
    """

    def symbols(self) -> List[str]:
        """Return the list of symbols available in this feed."""
        ...

    def bars(self, symbol: str) -> Iterator[Bar]:
        """Yield bars for a symbol in chronological order."""
        ...


# ---------------------------------------------------------------------------
# Built-in data feeds
# ---------------------------------------------------------------------------

class InMemoryDataFeed:
    """
    Simple in-memory data feed backed by a list of Bar objects.
    Useful for unit tests and small experiments.
    """

    def __init__(self, bars: Dict[str, List[Bar]]) -> None:
        self._bars = bars

    def symbols(self) -> List[str]:
        return list(self._bars.keys())

    def bars(self, symbol: str) -> Iterator[Bar]:
        yield from self._bars.get(symbol, [])


class SyntheticDataFeed:
    """
    Generates synthetic OHLCV bars using a geometric Brownian motion model.
    Useful for stress-testing strategies without real data.
    """

    def __init__(
        self,
        symbols: List[str],
        n_bars: int = 252,
        start_price: float = 100.0,
        drift: float = 0.0002,
        volatility: float = 0.015,
        seed: Optional[int] = 42,
    ) -> None:
        import random
        self._syms = symbols
        self._n    = n_bars
        self._s0   = start_price
        self._mu   = drift
        self._sig  = volatility
        self._rng  = random.Random(seed)

    def symbols(self) -> List[str]:
        return self._syms

    def bars(self, symbol: str) -> Iterator[Bar]:
        import random
        price = self._s0
        for i in range(self._n):
            ret   = self._rng.gauss(self._mu, self._sig)
            close = price * math.exp(ret)
            high  = close * (1 + abs(self._rng.gauss(0, self._sig / 2)))
            low   = close * (1 - abs(self._rng.gauss(0, self._sig / 2)))
            vol   = abs(self._rng.gauss(1_000_000, 200_000))
            yield Bar(
                symbol    = symbol,
                timestamp = f"bar_{i:05d}",
                open      = price,
                high      = max(price, close, high),
                low       = min(price, close, low),
                close     = close,
                volume    = vol,
            )
            price = close


# ---------------------------------------------------------------------------
# Backtest configuration & result
# ---------------------------------------------------------------------------

@dataclass
class BacktestConfig:
    initial_capital:    float = 10_000.0
    commission_rate:    float = 0.001
    slippage_bps:       float = 2.0
    risk_free_rate:     float = 0.02          # annualised, for Sharpe ratio
    bars_per_year:      int   = 252
    order_type:         OrderType = OrderType.MARKET
    position_size_pct:  float = 10.0          # % of portfolio per signal
    max_open_positions: int   = 10
    risk_limits:        Optional[RiskLimits] = None
    enable_rules:       bool  = True          # circuit breaker / cooldown etc.


@dataclass
class BacktestResult:
    config:           BacktestConfig
    trades:           List[Trade]
    equity_curve:     List[float]             # portfolio value at each bar
    final_value:      float
    initial_capital:  float

    @property
    def total_return_pct(self) -> float:
        return (self.final_value / self.initial_capital - 1) * 100

    @property
    def win_rate_pct(self) -> float:
        if not self.trades:
            return 0.0
        return sum(1 for t in self.trades if t.is_winner) / len(self.trades) * 100

    @property
    def max_drawdown_pct(self) -> float:
        if not self.equity_curve:
            return 0.0
        peak = self.equity_curve[0]
        max_dd = 0.0
        for val in self.equity_curve:
            peak  = max(peak, val)
            dd    = (peak - val) / peak * 100 if peak > 0 else 0.0
            max_dd = max(max_dd, dd)
        return round(max_dd, 4)

    @property
    def sharpe_ratio(self) -> float:
        if len(self.equity_curve) < 2:
            return 0.0
        returns = [
            (self.equity_curve[i] / self.equity_curve[i - 1] - 1)
            for i in range(1, len(self.equity_curve))
        ]
        if not returns:
            return 0.0
        avg_r = statistics.mean(returns)
        std_r = statistics.pstdev(returns)
        if std_r == 0:
            return 0.0
        rf_per_bar = self.config.risk_free_rate / self.config.bars_per_year
        return round((avg_r - rf_per_bar) / std_r * math.sqrt(self.config.bars_per_year), 4)

    @property
    def profit_factor(self) -> float:
        gross_profit = sum(t.pnl for t in self.trades if t.pnl > 0)
        gross_loss   = abs(sum(t.pnl for t in self.trades if t.pnl < 0))
        return round(gross_profit / gross_loss, 4) if gross_loss > 0 else float("inf")

    @property
    def avg_trade_pnl(self) -> float:
        if not self.trades:
            return 0.0
        return round(sum(t.pnl for t in self.trades) / len(self.trades), 4)

    def summary(self) -> Dict[str, Any]:
        return {
            "initial_capital":    self.initial_capital,
            "final_value":        round(self.final_value, 4),
            "total_return_pct":   round(self.total_return_pct, 4),
            "win_rate_pct":       round(self.win_rate_pct, 4),
            "max_drawdown_pct":   self.max_drawdown_pct,
            "sharpe_ratio":       self.sharpe_ratio,
            "profit_factor":      self.profit_factor,
            "avg_trade_pnl":      self.avg_trade_pnl,
            "total_trades":       len(self.trades),
            "total_bars":         len(self.equity_curve),
        }


# ---------------------------------------------------------------------------
# Backtester
# ---------------------------------------------------------------------------

class Backtester:
    """
    Drives a Strategy over a DataFeed bar-by-bar, routing signals through
    ExecutionSimulator and PortfolioManager, enforcing risk limits.

    The backtester is stateless between run() calls — each run creates
    fresh PortfolioManager, RiskManager, and ExecutionSimulator instances.
    """

    def __init__(
        self,
        config: Optional[BacktestConfig] = None,
        indicator_fn: Optional[Callable[[str, List[Bar]], Dict[str, float]]] = None,
    ) -> None:
        """
        indicator_fn: optional callable(symbol, history) → dict of indicator values.
        If provided, computed indicators are injected into each MarketSnapshot.
        """
        self._config       = config or BacktestConfig()
        self._indicator_fn = indicator_fn

    def run(self, strategy: Strategy, data_feed: DataFeed) -> BacktestResult:
        """
        Run a full backtest. Returns a BacktestResult with trades and metrics.
        """
        cfg = self._config

        portfolio   = PortfolioManager(initial_capital=cfg.initial_capital)
        risk_mgr    = RiskManager(limits=cfg.risk_limits or RiskLimits(
            max_open_positions=cfg.max_open_positions,
        ))
        exec_sim    = ExecutionSimulator(ExecutionConfig(
            commission_rate=cfg.commission_rate,
            slippage_model=FixedBpsSlippage(bps=cfg.slippage_bps),
            latency_ms=0,   # no real latency in backtest
        ))
        rules       = TradingRules() if cfg.enable_rules else None

        # Align bars from all symbols by iterating round-robin
        all_bars: Dict[str, List[Bar]] = {
            sym: list(data_feed.bars(sym)) for sym in data_feed.symbols()
        }
        history: Dict[str, List[Bar]] = {sym: [] for sym in all_bars}
        equity_curve: List[float]     = []

        # Determine iteration length from the longest symbol feed
        n_bars = max((len(v) for v in all_bars.values()), default=0)

        for i in range(n_bars):
            current_bars: Dict[str, Bar] = {}
            prices: Dict[str, float]     = {}

            for sym, bars_list in all_bars.items():
                if i < len(bars_list):
                    bar = bars_list[i]
                    current_bars[sym] = bar
                    history[sym].append(bar)
                    prices[sym] = bar.close

            # Process any pending limit/stop orders from previous bars
            for sym, bar in current_bars.items():
                pending_fills = exec_sim.process_pending(bar)
                for fill in pending_fills:
                    self._handle_fill(fill, portfolio, risk_mgr)

            # Build market snapshot with optional indicators
            indicators: Dict[str, Dict[str, float]] = {}
            if self._indicator_fn:
                for sym in current_bars:
                    indicators[sym] = self._indicator_fn(sym, history[sym])

            snapshot = MarketSnapshot(
                bars=current_bars,
                history=history,
                indicators=indicators,
            )

            # Generate signals and convert to orders
            signals = strategy.generate(snapshot)
            for sig in signals:
                if sig.symbol not in current_bars:
                    continue
                bar = current_bars[sig.symbol]

                # Rule checks (swallow violations — just skip the trade)
                if rules:
                    try:
                        rules.check_before_trade(sig.symbol)
                    except TradingRulesViolation:
                        continue

                qty = self._position_size(sig, portfolio, cfg)
                if qty <= 0:
                    continue

                order = Order(
                    symbol=sig.symbol,
                    side=sig.side,
                    order_type=cfg.order_type,
                    quantity=qty,
                )

                # Risk check
                try:
                    risk_mgr.check_order(
                        order,
                        portfolio_value=portfolio.total_value,
                        current_price=bar.close,
                        open_positions=portfolio.open_position_count(),
                    )
                except RiskViolation:
                    continue

                # Execute
                fill = exec_sim.submit(order, bar)
                if fill:
                    self._handle_fill(fill, portfolio, risk_mgr)
                    if rules:
                        rules.on_trade_executed(sig.symbol)

            # Update portfolio prices and record equity
            portfolio.update_prices(prices)
            equity_curve.append(portfolio.total_value)

        return BacktestResult(
            config=cfg,
            trades=list(portfolio._trades),
            equity_curve=equity_curve,
            final_value=portfolio.total_value,
            initial_capital=cfg.initial_capital,
        )

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    def _position_size(
        self, sig: Signal, portfolio: PortfolioManager, cfg: BacktestConfig
    ) -> float:
        """Calculate order quantity from position_size_pct of portfolio value."""
        price = portfolio._positions[sig.symbol].current_price if sig.symbol in portfolio._positions else None
        if price is None:
            # Use last known price — caller should not reach here without a bar
            return 0.0
        budget = portfolio.total_value * cfg.position_size_pct / 100
        qty    = budget / price
        return round(qty, 8) if qty > 0 else 0.0

    def _handle_fill(
        self, fill: Fill, portfolio: PortfolioManager, risk_mgr: RiskManager
    ) -> None:
        """Route a fill to open or close a position based on the existing state."""
        existing = portfolio._positions.get(fill.symbol)
        try:
            if existing and existing.side != fill.side:
                trade = portfolio.close_position(fill.symbol, fill)
                risk_mgr.record_fill(trade.pnl, symbol=fill.symbol)
            else:
                portfolio.open_position(fill)
        except (ValueError, KeyError):
            pass   # insufficient cash or other non-critical error — skip fill
