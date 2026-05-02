"""
NEXUS Profit Engine — Facade
Top-level orchestrator that wires strategy engine, risk manager, portfolio,
execution simulator, trading rules, and backtester into a single entry point.
Integrates with NexusCore when available.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Callable, Dict, List, Optional

from ._types import Bar, Fill, Order, OrderType, Side, Trade
from .backtester import Backtester, BacktestConfig, BacktestResult, DataFeed
from .execution_simulator import ExecutionConfig, ExecutionSimulator, FixedBpsSlippage
from .portfolio_manager import PortfolioManager, RebalanceAction
from .risk_manager import RiskLimits, RiskManager, RiskViolation
from .rules import TradingRules, TradingRulesViolation
from .strategy_engine import MarketSnapshot, Signal, Strategy, StrategyEngine


# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------

@dataclass
class ProfitEngineConfig:
    initial_capital:    float = 10_000.0
    commission_rate:    float = 0.001
    slippage_bps:       float = 2.0
    position_size_pct:  float = 5.0          # % of portfolio per signal
    risk_limits:        RiskLimits = field(default_factory=RiskLimits)
    execution_config:   Optional[ExecutionConfig] = None


# ---------------------------------------------------------------------------
# ProfitEngine facade
# ---------------------------------------------------------------------------

class ProfitEngine:
    """
    Single entry-point for the NEXUS profit engine.

    Handles the full live (or paper-trading) cycle:
      snapshot → strategy signals → risk checks → rule checks → execution → portfolio update

    Usage (standalone):
        engine = ProfitEngine(ProfitEngineConfig(initial_capital=5000))
        engine.start()
        engine.register_strategy(my_strategy)
        fills = engine.process_snapshot(snapshot)
        print(engine.status())

    Usage (with NexusCore):
        from core import get_core
        core = get_core()
        core.start()
        engine = ProfitEngine.from_core(core)
        engine.start()
    """

    def __init__(self, config: Optional[ProfitEngineConfig] = None) -> None:
        self._config    = config or ProfitEngineConfig()
        self._running   = False

        exec_cfg = self._config.execution_config or ExecutionConfig(
            commission_rate=self._config.commission_rate,
            slippage_model=FixedBpsSlippage(bps=self._config.slippage_bps),
            latency_ms=0,
        )

        self.strategy_engine  = StrategyEngine()
        self.risk_manager     = RiskManager(limits=self._config.risk_limits)
        self.portfolio        = PortfolioManager(initial_capital=self._config.initial_capital)
        self.execution        = ExecutionSimulator(config=exec_cfg)
        self.rules            = TradingRules()
        self._backtester      = Backtester(BacktestConfig(
            initial_capital   = self._config.initial_capital,
            commission_rate   = self._config.commission_rate,
            slippage_bps      = self._config.slippage_bps,
            risk_limits       = self._config.risk_limits,
        ))

        # Optional core integration
        self._logger = None
        self._memory = None

    # ------------------------------------------------------------------
    # Lifecycle
    # ------------------------------------------------------------------

    @classmethod
    def from_core(cls, core: Any, config: Optional[ProfitEngineConfig] = None) -> "ProfitEngine":
        """Create a ProfitEngine wired to a running NexusCore."""
        instance = cls(config)
        instance._logger = core.logger
        instance._memory = core.memory
        return instance

    def start(self) -> None:
        self._running = True
        self._log("profit_engine", "ProfitEngine started.",
                  capital=self._config.initial_capital, dry_run=False)

    def stop(self) -> None:
        self._running = False
        self._log("profit_engine", "ProfitEngine stopped.")

    # ------------------------------------------------------------------
    # Strategy management
    # ------------------------------------------------------------------

    def register_strategy(self, strategy: Strategy) -> None:
        self.strategy_engine.register(strategy)
        self._log("profit_engine", f"Strategy '{strategy.name}' registered.")

    def unregister_strategy(self, name: str) -> None:
        self.strategy_engine.unregister(name)

    # ------------------------------------------------------------------
    # Main cycle
    # ------------------------------------------------------------------

    def process_snapshot(
        self,
        snapshot: MarketSnapshot,
        order_type: OrderType = OrderType.MARKET,
    ) -> List[Fill]:
        """
        Full processing cycle for a market snapshot:
        1. Generate signals from all strategies
        2. Apply rule and risk checks
        3. Submit orders to execution simulator
        4. Update portfolio with fills
        Returns a list of Fills from this cycle.
        """
        signals = self.strategy_engine.run(snapshot)
        fills:   List[Fill] = []

        for sig in signals:
            bar = snapshot.bars.get(sig.symbol)
            if bar is None:
                continue

            # Rule check
            try:
                self.rules.check_before_trade(sig.symbol)
            except TradingRulesViolation as exc:
                self._log("profit_engine", f"Rule blocked trade: {exc}", level="warning")
                continue

            qty = self._size_position(sig, bar)
            if qty <= 0:
                continue

            order = Order(symbol=sig.symbol, side=sig.side,
                          order_type=order_type, quantity=qty,
                          metadata={"signal_id": sig.signal_id})

            # Risk check
            try:
                self.risk_manager.check_order(
                    order,
                    portfolio_value=self.portfolio.total_value,
                    current_price=bar.close,
                    open_positions=self.portfolio.open_position_count(),
                )
            except RiskViolation as exc:
                self._log("profit_engine", f"Risk blocked trade: {exc}", level="warning")
                continue

            # Execute
            fill = self.execution.submit(order, bar)
            if fill:
                self._handle_fill(fill)
                self.rules.on_trade_executed(sig.symbol)
                fills.append(fill)

        # Process any pending orders from this bar
        for bar in snapshot.bars.values():
            for fill in self.execution.process_pending(bar):
                self._handle_fill(fill)
                fills.append(fill)

        return fills

    def close_position(self, symbol: str, bar: Bar) -> Optional[Trade]:
        """Manually close an open position at the current bar price."""
        pos = self.portfolio._positions.get(symbol)
        if pos is None:
            return None
        order = Order(symbol=symbol, side=pos.side.opposite(),
                      order_type=OrderType.MARKET, quantity=pos.quantity)
        fill = self.execution.submit(order, bar)
        if fill:
            return self._handle_fill(fill)
        return None

    # ------------------------------------------------------------------
    # Backtesting
    # ------------------------------------------------------------------

    def backtest(
        self,
        strategy: Strategy,
        data_feed: DataFeed,
        config: Optional[BacktestConfig] = None,
    ) -> BacktestResult:
        """Run an offline backtest. Does not affect the live portfolio."""
        bt = Backtester(config or BacktestConfig(
            initial_capital  = self._config.initial_capital,
            commission_rate  = self._config.commission_rate,
            slippage_bps     = self._config.slippage_bps,
            risk_limits      = self._config.risk_limits,
        ))
        result = bt.run(strategy, data_feed)
        if self._memory:
            self._memory.remember(
                f"backtest_{strategy.name}",
                result.summary(),
                permanent=True,
            )
        return result

    # ------------------------------------------------------------------
    # Status
    # ------------------------------------------------------------------

    def status(self) -> Dict[str, Any]:
        return {
            "running":         self._running,
            "portfolio":       self.portfolio.stats(),
            "strategies":      self.strategy_engine.stats(),
            "execution":       self.execution.stats(),
            "risk_daily":      self.risk_manager.daily_stats(),
            "rules":           self.rules.status(),
        }

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _size_position(self, sig: Signal, bar: Bar) -> float:
        """Size a position as a % of current portfolio value."""
        if bar.close <= 0:
            return 0.0
        budget = self.portfolio.total_value * self._config.position_size_pct / 100
        return round(budget / bar.close, 8)

    def _handle_fill(self, fill: Fill) -> Optional[Trade]:
        existing = self.portfolio._positions.get(fill.symbol)
        trade: Optional[Trade] = None
        try:
            if existing and existing.side != fill.side:
                trade = self.portfolio.close_position(fill.symbol, fill)
                self.risk_manager.record_fill(trade.pnl, symbol=fill.symbol)
                if trade.pnl < 0:
                    self.rules.on_loss()
                else:
                    self.rules.on_win()
            else:
                self.portfolio.open_position(fill)
        except (ValueError, KeyError):
            pass
        return trade

    def _log(self, module: str, message: str, level: str = "info", **kwargs: Any) -> None:
        if self._logger:
            getattr(self._logger, level, self._logger.info)(module, message, **kwargs)
