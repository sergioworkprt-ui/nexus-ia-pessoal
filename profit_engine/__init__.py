"""
NEXUS Profit Engine package.

Provides strategy execution, risk management, portfolio tracking,
simulated order execution, backtesting, and global trading safety rules.

Quick start:
    from profit_engine import ProfitEngine, ProfitEngineConfig

    engine = ProfitEngine(ProfitEngineConfig(initial_capital=10_000))
    engine.start()

Backtest quick start:
    from profit_engine import ProfitEngine, SyntheticDataFeed, MovingAverageCrossover

    engine  = ProfitEngine()
    strat   = MovingAverageCrossover(symbols=["SYM"])
    feed    = SyntheticDataFeed(symbols=["SYM"], n_bars=252)
    result  = engine.backtest(strat, feed)
    print(result.summary())
"""

# Shared types
from ._types import Bar, Fill, Order, OrderStatus, OrderType, Position, Side, Trade

# Rules & violations
from .rules import (
    CircuitBreaker,
    CircuitBreakerConfig,
    Cooldown,
    KillSwitch,
    SessionGuard,
    TradingRules,
    TradingRulesViolation,
)

# Risk management
from .risk_manager import RiskLimits, RiskManager, RiskViolation

# Portfolio
from .portfolio_manager import PortfolioManager, RebalanceAction

# Execution simulation
from .execution_simulator import (
    ExecutionConfig,
    ExecutionSimulator,
    FixedBpsSlippage,
    SlippageModel,
    SpreadSlippage,
)

# Strategy engine
from .strategy_engine import (
    MarketSnapshot,
    MovingAverageCrossover,
    Signal,
    SignalAggregator,
    Strategy,
    StrategyEngine,
)

# Backtester
from .backtester import (
    Backtester,
    BacktestConfig,
    BacktestResult,
    DataFeed,
    InMemoryDataFeed,
    SyntheticDataFeed,
)

# Facade
from .profit_engine import ProfitEngine, ProfitEngineConfig

__all__ = [
    # Types
    "Bar", "Fill", "Order", "OrderStatus", "OrderType", "Position", "Side", "Trade",
    # Rules
    "CircuitBreaker", "CircuitBreakerConfig", "Cooldown", "KillSwitch",
    "SessionGuard", "TradingRules", "TradingRulesViolation",
    # Risk
    "RiskLimits", "RiskManager", "RiskViolation",
    # Portfolio
    "PortfolioManager", "RebalanceAction",
    # Execution
    "ExecutionConfig", "ExecutionSimulator",
    "FixedBpsSlippage", "SlippageModel", "SpreadSlippage",
    # Strategy
    "MarketSnapshot", "MovingAverageCrossover", "Signal",
    "SignalAggregator", "Strategy", "StrategyEngine",
    # Backtest
    "Backtester", "BacktestConfig", "BacktestResult",
    "DataFeed", "InMemoryDataFeed", "SyntheticDataFeed",
    # Facade
    "ProfitEngine", "ProfitEngineConfig",
]
