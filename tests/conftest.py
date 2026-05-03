"""
NEXUS Test Suite — Shared Fixtures
Base classes, helpers, and utilities shared across all test modules.
Uses only stdlib unittest — no external dependencies.
"""

import os
import shutil
import sys
import tempfile
import unittest

# Ensure project root is on the path regardless of how tests are invoked
_PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _PROJECT_ROOT not in sys.path:
    sys.path.insert(0, _PROJECT_ROOT)


# ---------------------------------------------------------------------------
# Base test case
# ---------------------------------------------------------------------------

class NexusTestCase(unittest.TestCase):
    """
    Base class for all NEXUS tests.
    Provides an isolated temporary directory per test and
    common assertion helpers.
    """

    def setUp(self) -> None:
        self.tmp = tempfile.mkdtemp(prefix="nexus_tmp_")

    def tearDown(self) -> None:
        shutil.rmtree(self.tmp, ignore_errors=True)

    # ------------------------------------------------------------------
    # Path helpers
    # ------------------------------------------------------------------

    def tmp_path(self, *parts: str) -> str:
        """Return an absolute path inside the temp directory."""
        return os.path.join(self.tmp, *parts)

    def tmp_file(self, name: str, content: str = "") -> str:
        """Create a file in the temp directory and return its path."""
        path = self.tmp_path(name)
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, "w", encoding="utf-8") as fh:
            fh.write(content)
        return path

    def tmp_subdir(self, *parts: str) -> str:
        """Create and return a subdirectory inside the temp directory."""
        path = self.tmp_path(*parts)
        os.makedirs(path, exist_ok=True)
        return path

    # ------------------------------------------------------------------
    # Assertion helpers
    # ------------------------------------------------------------------

    def assertBetween(self, value: float, lo: float, hi: float, msg: str = "") -> None:
        self.assertGreaterEqual(value, lo, msg or f"{value} not >= {lo}")
        self.assertLessEqual(value, hi, msg or f"{value} not <= {hi}")

    def assertNonEmpty(self, collection, msg: str = "") -> None:
        self.assertTrue(len(collection) > 0, msg or "Expected non-empty collection")

    def assertDictHasKeys(self, d: dict, *keys: str) -> None:
        for key in keys:
            self.assertIn(key, d, f"Missing key: {key!r}")


# ---------------------------------------------------------------------------
# Sample Python source snippets for evolution/optimizer tests
# ---------------------------------------------------------------------------

CLEAN_PYTHON = '''\
def add(a: int, b: int) -> int:
    """Add two integers."""
    return a + b


def greet(name: str) -> str:
    """Return a greeting."""
    return f"Hello, {name}"
'''

SMELLY_PYTHON = '''\
import os, sys, *

def process(a, b, c, d, e, f, g):
    x = []
    for i in range(len(x)):
        pass
    if x == None:
        pass
    try:
        pass
    except:
        pass
    print("debug output")
    return x
'''

INVALID_PYTHON = '''\
def broken(:
    pass
'''


# ---------------------------------------------------------------------------
# Sample market data for profit_engine / web_intelligence tests
# ---------------------------------------------------------------------------

def make_ohlc_bars(n: int = 10, base: float = 100.0) -> list:
    """Return a list of OHLCBar-compatible dicts."""
    bars = []
    price = base
    for i in range(n):
        price += (i % 3 - 1) * 0.5
        bars.append({
            "symbol":    "BTC",
            "open":      round(price, 4),
            "high":      round(price + 1.0, 4),
            "low":       round(price - 1.0, 4),
            "close":     round(price + 0.2, 4),
            "volume":    1000 + i * 10,
            "timestamp": f"2026-01-{i+1:02d}T00:00:00+00:00",
        })
    return bars


def make_equity_curve(n: int = 20, start: float = 10000.0) -> list:
    """Return a deterministic equity curve (zigzag)."""
    curve = [start]
    for i in range(1, n):
        delta = 50.0 if i % 2 == 0 else -30.0
        curve.append(round(curve[-1] + delta, 2))
    return curve
