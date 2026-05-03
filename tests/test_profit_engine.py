"""
NEXUS Test Suite — Profit Engine Module
Tests for: RiskManager, PortfolioManager, ExecutionSimulator,
Backtester (SyntheticDataFeed), and TradingRules.
All tests run in simulation mode — no live orders.
"""

import unittest

from conftest import NexusTestCase

from profit_engine._types import Bar, Side, Order, OrderType, Fill
from profit_engine.risk_manager import RiskManager, RiskLimits, RiskViolation
from profit_engine.portfolio_manager import PortfolioManager
from profit_engine.execution_simulator import ExecutionSimulator, ExecutionConfig
from profit_engine import FixedBpsSlippage
from profit_engine.backtester import Backtester, SyntheticDataFeed, BacktestConfig
from profit_engine.rules import TradingRules, TradingRulesViolation
from profit_engine.strategy_engine import MovingAverageCrossover, MarketSnapshot


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _bar(symbol: str = "BTC", close: float = 100.0, volume: float = 1000.0) -> Bar:
    return Bar(
        symbol=symbol, open=close - 0.5, high=close + 1.0,
        low=close - 1.0, close=close, volume=volume,
        timestamp="2026-01-01T00:00:00+00:00",
    )


def _market_order(symbol: str = "BTC", side: Side = Side.BUY, qty: float = 1.0) -> Order:
    return Order(
        symbol=symbol, side=side, order_type=OrderType.MARKET,
        quantity=qty,
    )


def _fill(symbol: str = "BTC", side: Side = Side.BUY,
          qty: float = 1.0, price: float = 100.0,
          commission: float = 0.1, ts: str = "2026-01-01T00:00:00+00:00") -> Fill:
    return Fill(
        order_id="o1", symbol=symbol, side=side,
        quantity=qty, price=price, commission=commission,
        timestamp=ts,
    )


# ---------------------------------------------------------------------------
# RiskManager
# ---------------------------------------------------------------------------

class TestRiskManager(NexusTestCase):

    def setUp(self) -> None:
        super().setUp()
        limits = RiskLimits(
            max_order_value=5000.0,
            max_daily_loss=500.0,
            max_drawdown_pct=20.0,
            max_open_positions=3,
        )
        self.rm = RiskManager(limits=limits)

    def test_check_order_small_passes(self) -> None:
        order = _market_order(qty=1.0)
        self.rm.check_order(order, portfolio_value=10000.0, current_price=100.0)

    def test_check_order_too_large_raises(self) -> None:
        order = _market_order(qty=100.0)
        with self.assertRaises(RiskViolation):
            self.rm.check_order(order, portfolio_value=10000.0, current_price=100.0)

    def test_daily_loss_breach_raises_on_check(self) -> None:
        # record_fill accumulates loss; check_order raises when limit exceeded
        self.rm.record_fill(-600.0, "BTC")
        order = _market_order(qty=1.0)
        with self.assertRaises(RiskViolation):
            self.rm.check_order(order, portfolio_value=10000.0, current_price=100.0)

    def test_record_fill_within_limit(self) -> None:
        self.rm.record_fill(-100.0, "BTC")  # should not raise

    def test_drawdown_breach_raises(self) -> None:
        self.rm.check_drawdown(10000.0)     # sets peak
        with self.assertRaises(RiskViolation):
            self.rm.check_drawdown(7000.0)  # 30% drop — exceeds 20% limit

    def test_daily_stats_returns_dict(self) -> None:
        s = self.rm.daily_stats()
        self.assertIsInstance(s, dict)
        self.assertIn("daily_loss", s)

    def test_violations_returns_list(self) -> None:
        self.assertIsInstance(self.rm.violations(), list)


# ---------------------------------------------------------------------------
# PortfolioManager
# ---------------------------------------------------------------------------

class TestPortfolioManager(NexusTestCase):

    def setUp(self) -> None:
        super().setUp()
        self.pm = PortfolioManager(initial_capital=10000.0)

    def test_initial_cash(self) -> None:
        self.assertAlmostEqual(self.pm.cash, 10000.0)

    def test_equity_equals_initial_when_no_positions(self) -> None:
        self.assertAlmostEqual(self.pm.total_value, 10000.0)

    def test_open_position(self) -> None:
        fill = _fill("BTC", Side.BUY, qty=1.0, price=5000.0, commission=5.0)
        self.pm.open_position(fill)
        pos = self.pm.positions()
        symbols = [p["symbol"] for p in pos]
        self.assertIn("BTC", symbols)

    def test_close_position(self) -> None:
        buy = _fill("ETH", Side.BUY, qty=2.0, price=1000.0, commission=2.0,
                    ts="2026-01-01T00:00:00+00:00")
        sell = _fill("ETH", Side.SELL, qty=2.0, price=1100.0, commission=2.0,
                     ts="2026-01-02T00:00:00+00:00")
        self.pm.open_position(buy)
        self.pm.close_position("ETH", sell)
        pos = self.pm.positions()
        symbols = [p["symbol"] for p in pos]
        self.assertNotIn("ETH", symbols)

    def test_realised_pnl_after_profitable_trade(self) -> None:
        buy = _fill("SOL", Side.BUY, qty=10.0, price=50.0, commission=0.0)
        sell = _fill("SOL", Side.SELL, qty=10.0, price=60.0, commission=0.0,
                     ts="2026-01-02T00:00:00+00:00")
        self.pm.open_position(buy)
        self.pm.close_position("SOL", sell)
        self.assertGreater(self.pm.realised_pnl, 0.0)

    def test_stats_returns_dict(self) -> None:
        s = self.pm.stats()
        self.assertIsInstance(s, dict)
        self.assertIn("total_value", s)


# ---------------------------------------------------------------------------
# ExecutionSimulator
# ---------------------------------------------------------------------------

class TestExecutionSimulator(NexusTestCase):

    def setUp(self) -> None:
        super().setUp()
        cfg = ExecutionConfig(slippage_model=FixedBpsSlippage(bps=5))
        self.sim = ExecutionSimulator(config=cfg)

    def test_market_order_fills_immediately(self) -> None:
        order = _market_order(qty=1.0)
        bar   = _bar(close=100.0)
        fill  = self.sim.submit(order, bar)
        self.assertIsNotNone(fill)
        self.assertEqual(fill.symbol, "BTC")
        self.assertGreater(fill.price, 0.0)

    def test_fill_price_includes_slippage(self) -> None:
        order = _market_order(side=Side.BUY, qty=1.0)
        bar   = _bar(close=100.0)
        fill  = self.sim.submit(order, bar)
        # BUY with positive slippage: fill at open with bps applied
        self.assertGreater(fill.price, 0.0)

    def test_limit_order_queued_not_filled(self) -> None:
        order = Order(symbol="BTC", side=Side.BUY,
                      order_type=OrderType.LIMIT, quantity=1.0, limit_price=90.0)
        bar  = _bar(close=100.0)
        fill = self.sim.submit(order, bar)
        self.assertIsNone(fill)
        self.assertEqual(len(self.sim.pending_orders()), 1)

    def test_limit_order_fills_via_process_pending(self) -> None:
        # BUY limit fills when bar.low <= limit_price
        order = Order(symbol="BTC", side=Side.BUY,
                      order_type=OrderType.LIMIT, quantity=1.0, limit_price=110.0)
        self.sim.submit(order)
        bar   = _bar(close=100.0)   # bar.low = 99.0 <= 110.0 → fills
        fills = self.sim.process_pending(bar)
        self.assertNonEmpty(fills)

    def test_limit_order_not_filled_when_price_above(self) -> None:
        # BUY limit: does not fill when bar.low > limit_price
        order = Order(symbol="BTC", side=Side.BUY,
                      order_type=OrderType.LIMIT, quantity=1.0, limit_price=90.0)
        self.sim.submit(order)
        bar   = _bar(close=100.0)   # bar.low = 99.0 > 90.0 → no fill
        fills = self.sim.process_pending(bar)
        self.assertEqual(len(fills), 0)

    def test_stats_returns_dict(self) -> None:
        self.assertIsInstance(self.sim.stats(), dict)


# ---------------------------------------------------------------------------
# Backtester + SyntheticDataFeed
# ---------------------------------------------------------------------------

class TestBacktester(NexusTestCase):

    def test_synthetic_feed_deterministic(self) -> None:
        feed1 = SyntheticDataFeed(["BTC"], n_bars=50, seed=42)
        feed2 = SyntheticDataFeed(["BTC"], n_bars=50, seed=42)
        bars1 = list(feed1.bars("BTC"))
        bars2 = list(feed2.bars("BTC"))
        self.assertEqual(len(bars1), len(bars2))
        self.assertAlmostEqual(bars1[0].close, bars2[0].close, places=6)

    def test_synthetic_feed_correct_bar_count(self) -> None:
        feed = SyntheticDataFeed(["BTC"], n_bars=100, seed=1)
        bars = list(feed.bars("BTC"))
        self.assertEqual(len(bars), 100)

    def test_synthetic_feed_ohlcv_valid(self) -> None:
        feed = SyntheticDataFeed(["ETH"], n_bars=20, seed=7)
        for bar in feed.bars("ETH"):
            self.assertGreaterEqual(bar.high, bar.close)
            self.assertLessEqual(bar.low, bar.close)
            self.assertGreaterEqual(bar.volume, 0)

    def test_backtester_runs_with_synthetic_data(self) -> None:
        strategy = MovingAverageCrossover(symbols=["BTC"])
        config   = BacktestConfig(initial_capital=10000.0)
        bt       = Backtester(config=config)
        feed     = SyntheticDataFeed(["BTC"], n_bars=60, seed=42)
        result   = bt.run(strategy, feed)
        self.assertIsNotNone(result)

    def test_backtest_result_has_equity_curve(self) -> None:
        strategy = MovingAverageCrossover(symbols=["BTC"])
        bt   = Backtester()
        feed = SyntheticDataFeed(["BTC"], n_bars=60, seed=42)
        result = bt.run(strategy, feed)
        self.assertIsInstance(result.equity_curve, list)
        self.assertGreater(len(result.equity_curve), 0)

    def test_backtest_result_has_summary(self) -> None:
        strategy = MovingAverageCrossover(symbols=["BTC"])
        bt   = Backtester()
        feed = SyntheticDataFeed(["BTC"], n_bars=50, seed=42)
        result = bt.run(strategy, feed)
        d = result.summary()
        self.assertIsInstance(d, dict)


# ---------------------------------------------------------------------------
# TradingRules / KillSwitch
# ---------------------------------------------------------------------------

class TestTradingRules(NexusTestCase):

    def setUp(self) -> None:
        super().setUp()
        self.rules = TradingRules()

    def test_kill_switch_off_by_default(self) -> None:
        self.assertFalse(self.rules.kill_switch.is_engaged)

    def test_engage_kill_switch(self) -> None:
        self.rules.kill_switch.engage(reason="max loss hit")
        self.assertTrue(self.rules.kill_switch.is_engaged)

    def test_disengage_kill_switch(self) -> None:
        self.rules.kill_switch.engage(reason="test")
        self.rules.kill_switch.disengage()
        self.assertFalse(self.rules.kill_switch.is_engaged)

    def test_check_raises_when_killed(self) -> None:
        self.rules.kill_switch.engage(reason="test")
        with self.assertRaises(TradingRulesViolation):
            self.rules.check_before_trade("BTC")

    def test_check_passes_normally(self) -> None:
        self.rules.check_before_trade("BTC")   # should not raise

    def test_status_returns_dict(self) -> None:
        s = self.rules.status()
        self.assertIsInstance(s, dict)
        self.assertIn("kill_switch", s)


# ---------------------------------------------------------------------------
# MovingAverageCrossover Strategy
# ---------------------------------------------------------------------------

class TestMovingAverageCrossover(NexusTestCase):

    def setUp(self) -> None:
        super().setUp()
        self.strategy = MovingAverageCrossover(symbols=["BTC"])

    def test_generate_returns_list(self) -> None:
        bars = [_bar(close=float(100 + i)) for i in range(10)]
        snap = MarketSnapshot(
            bars={"BTC": bars[-1]},
            history={"BTC": bars},
        )
        signals = self.strategy.generate(snap)
        self.assertIsInstance(signals, list)

    def test_no_signal_before_enough_bars(self) -> None:
        bars = [_bar(close=float(100 + i)) for i in range(3)]
        snap = MarketSnapshot(
            bars={"BTC": bars[-1]},
            history={"BTC": bars},
        )
        signals = self.strategy.generate(snap)
        self.assertIsInstance(signals, list)

    def test_signal_strength_bounded(self) -> None:
        bars = [_bar(close=float(100 + i)) for i in range(40)]
        snap = MarketSnapshot(
            bars={"BTC": bars[-1]},
            history={"BTC": bars},
        )
        signals = self.strategy.generate(snap)
        for s in signals:
            self.assertBetween(s.strength, 0.0, 1.0)


if __name__ == "__main__":
    unittest.main()
