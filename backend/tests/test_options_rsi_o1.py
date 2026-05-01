"""
Verify that CoveredCallStrategy and ProtectivePutStrategy produce numerically
identical RSI values to the reference O(1) EquityRSIStrategy implementation,
and contain zero list(deque) conversions.
"""
import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import math
import pytest

# Patch missing env vars so config.py doesn't blow up on import
os.environ.setdefault("ALPACA_API_KEY_ID", "test")
os.environ.setdefault("ALPACA_API_SECRET_KEY", "test")

from strategy.options_algorithms import CoveredCallStrategy, ProtectivePutStrategy
from strategy.equity_algorithms import EquityRSIStrategy


PRICES = [
    100.0, 101.2, 100.8, 102.5, 103.1, 102.0, 101.5, 103.8, 104.2, 103.5,
    104.9, 105.3, 104.7, 106.0, 105.5, 107.1, 106.8, 108.0, 107.5, 109.2,
]

SYM = "AAPL"


def _feed_rsi_ref(prices):
    """Drive EquityRSIStrategy and collect RSI after every tick."""
    ref = EquityRSIStrategy()
    values = []
    for p in prices:
        ref._update_rsi_o1(SYM, p)
        values.append(ref._rsi.get(SYM))
    return values


def _feed_covered(prices):
    strat = CoveredCallStrategy()
    values = []
    for p in prices:
        strat._update_rsi(SYM, p)
        values.append(strat._rsi.get(SYM))
    return values


def _feed_protective(prices):
    strat = ProtectivePutStrategy()
    values = []
    for p in prices:
        strat._update_rsi(SYM, p)
        values.append(strat._rsi.get(SYM))
    return values


def test_covered_call_rsi_matches_reference():
    ref = _feed_rsi_ref(PRICES)
    got = _feed_covered(PRICES)
    for i, (r, g) in enumerate(zip(ref, got)):
        if r is None:
            assert g is None, f"tick {i}: expected None, got {g}"
        else:
            assert g is not None, f"tick {i}: expected {r:.4f}, got None"
            assert math.isclose(r, g, rel_tol=1e-9), (
                f"tick {i}: CoveredCall RSI {g:.6f} != ref {r:.6f}"
            )


def test_protective_put_rsi_matches_reference():
    ref = _feed_rsi_ref(PRICES)
    got = _feed_protective(PRICES)
    for i, (r, g) in enumerate(zip(ref, got)):
        if r is None:
            assert g is None, f"tick {i}: expected None, got {g}"
        else:
            assert g is not None, f"tick {i}: expected {r:.4f}, got None"
            assert math.isclose(r, g, rel_tol=1e-9), (
                f"tick {i}: ProtectivePut RSI {g:.6f} != ref {r:.6f}"
            )


def test_no_list_deque_conversion_in_options_algorithms():
    """Confirm the source file contains no list(self._ deque conversions."""
    import inspect
    import strategy.options_algorithms as mod
    src = inspect.getsource(mod)
    assert "list(self._prices" not in src
    assert "list(self._rsi_prices" not in src


def test_rsi_bounded():
    """RSI must stay in [0, 100] for all inputs."""
    for strat_cls in (CoveredCallStrategy, ProtectivePutStrategy):
        strat = strat_cls()
        for p in PRICES:
            strat._update_rsi(SYM, p)
            rsi = strat._rsi.get(SYM)
            if rsi is not None:
                assert 0.0 <= rsi <= 100.0, f"{strat_cls.__name__} RSI={rsi} out of bounds"
