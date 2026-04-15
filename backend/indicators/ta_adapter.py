"""
TA Adapter — Unified Technical Analysis Interface
===================================================
Wraps TA-Lib (C backend, preferred) with a transparent fallback to pandas-ta
(pure Python). Both produce identical pd.Series outputs with the original
index preserved so callers never need to know which library is active.

All functions accept a pd.Series of close prices (or high/low/volume where
noted) and return a pd.Series with the same index. Inputs and outputs are
strictly typed. NaN-padded leading values follow each library's convention.

Usage:
    from indicators.ta_adapter import ema, rsi, macd, bollinger_bands, atr

Switching libraries:
    TA-Lib is selected automatically if importable. Set the environment
    variable TA_BACKEND=pandas_ta to force the fallback regardless.
"""

from __future__ import annotations

import os
import logging
import numpy as np
import pandas as pd
from typing import NamedTuple

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Backend detection — checked once at module import
# ---------------------------------------------------------------------------

_FORCED_BACKEND = os.getenv("TA_BACKEND", "").lower()

_TALIB_AVAILABLE = False
if _FORCED_BACKEND != "pandas_ta":
    try:
        import talib as _talib          # noqa: F401
        _TALIB_AVAILABLE = True
        logger.info("[TA_ADAPTER] Backend: TA-Lib %s (C extension)", _talib.__version__)
    except ImportError:
        logger.info("[TA_ADAPTER] TA-Lib not available — falling back to pandas-ta")

if not _TALIB_AVAILABLE:
    try:
        import pandas_ta as _pta        # noqa: F401
        logger.info("[TA_ADAPTER] Backend: pandas-ta %s (pure Python)", _pta.version)
    except ImportError as exc:
        raise ImportError(
            "No TA backend found. Install either TA-Lib or pandas-ta:\n"
            "  pip install TA-Lib          # preferred (requires C library)\n"
            "  pip install pandas-ta       # pure Python fallback"
        ) from exc

BACKEND: str = "talib" if _TALIB_AVAILABLE else "pandas_ta"


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _to_float64(s: pd.Series) -> np.ndarray:
    """Convert a Series to a C-contiguous float64 array (required by TA-Lib)."""
    return s.to_numpy(dtype=np.float64, na_value=np.nan, copy=False)


def _wrap(arr: np.ndarray, index: pd.Index) -> pd.Series:
    """Re-attach the original index to a numpy result array."""
    return pd.Series(arr, index=index, dtype="float64")


# ---------------------------------------------------------------------------
# EMA — Exponential Moving Average
# ---------------------------------------------------------------------------

def ema(close: pd.Series, period: int) -> pd.Series:
    """
    Exponential Moving Average.

    Args:
        close:  Series of close prices.
        period: Look-back window (e.g. 50, 200).

    Returns:
        pd.Series aligned to close.index, NaN for the first (period-1) bars.
    """
    if _TALIB_AVAILABLE:
        import talib
        return _wrap(talib.EMA(_to_float64(close), timeperiod=period), close.index)
    else:
        import pandas_ta as pta
        result = pta.ema(close, length=period)
        return result if result is not None else pd.Series(np.nan, index=close.index)


# ---------------------------------------------------------------------------
# SMA — Simple Moving Average
# ---------------------------------------------------------------------------

def sma(close: pd.Series, period: int) -> pd.Series:
    """Simple Moving Average."""
    if _TALIB_AVAILABLE:
        import talib
        return _wrap(talib.SMA(_to_float64(close), timeperiod=period), close.index)
    else:
        import pandas_ta as pta
        result = pta.sma(close, length=period)
        return result if result is not None else pd.Series(np.nan, index=close.index)


# ---------------------------------------------------------------------------
# RSI — Relative Strength Index
# ---------------------------------------------------------------------------

def rsi(close: pd.Series, period: int = 14) -> pd.Series:
    """
    Relative Strength Index (0–100).

    Args:
        close:  Series of close prices.
        period: RSI period (default 14).

    Returns:
        pd.Series in range [0, 100], NaN for the first period bars.
    """
    if _TALIB_AVAILABLE:
        import talib
        return _wrap(talib.RSI(_to_float64(close), timeperiod=period), close.index)
    else:
        import pandas_ta as pta
        result = pta.rsi(close, length=period)
        return result if result is not None else pd.Series(np.nan, index=close.index)


# ---------------------------------------------------------------------------
# MACD — Moving Average Convergence/Divergence
# ---------------------------------------------------------------------------

class MACDResult(NamedTuple):
    macd: pd.Series
    signal: pd.Series
    histogram: pd.Series


def macd(
    close: pd.Series,
    fast: int = 12,
    slow: int = 26,
    signal_period: int = 9,
) -> MACDResult:
    """
    MACD line, signal line, and histogram.

    Returns:
        MACDResult(macd, signal, histogram) — each a pd.Series.
    """
    if _TALIB_AVAILABLE:
        import talib
        m, s, h = talib.MACD(
            _to_float64(close),
            fastperiod=fast,
            slowperiod=slow,
            signalperiod=signal_period,
        )
        return MACDResult(
            _wrap(m, close.index),
            _wrap(s, close.index),
            _wrap(h, close.index),
        )
    else:
        import pandas_ta as pta
        df = pta.macd(close, fast=fast, slow=slow, signal=signal_period)
        cols = df.columns.tolist() if df is not None else []
        nan = pd.Series(np.nan, index=close.index)
        if df is None or len(cols) < 3:
            return MACDResult(nan, nan, nan)
        return MACDResult(df[cols[0]], df[cols[1]], df[cols[2]])


# ---------------------------------------------------------------------------
# Bollinger Bands
# ---------------------------------------------------------------------------

class BollingerResult(NamedTuple):
    upper: pd.Series
    middle: pd.Series
    lower: pd.Series


def bollinger_bands(
    close: pd.Series,
    period: int = 20,
    std_dev: float = 2.0,
) -> BollingerResult:
    """
    Bollinger Bands (upper, middle/SMA, lower).

    Returns:
        BollingerResult(upper, middle, lower) — each a pd.Series.
    """
    if _TALIB_AVAILABLE:
        import talib
        u, m, lo = talib.BBANDS(
            _to_float64(close),
            timeperiod=period,
            nbdevup=std_dev,
            nbdevdn=std_dev,
        )
        return BollingerResult(_wrap(u, close.index), _wrap(m, close.index), _wrap(lo, close.index))
    else:
        import pandas_ta as pta
        df = pta.bbands(close, length=period, std=std_dev)
        cols = df.columns.tolist() if df is not None else []
        nan = pd.Series(np.nan, index=close.index)
        if df is None or len(cols) < 3:
            return BollingerResult(nan, nan, nan)
        # pandas-ta column order: BBL, BBM, BBU, BBB, BBP
        return BollingerResult(df[cols[2]], df[cols[1]], df[cols[0]])


# ---------------------------------------------------------------------------
# ATR — Average True Range
# ---------------------------------------------------------------------------

def atr(
    high: pd.Series,
    low: pd.Series,
    close: pd.Series,
    period: int = 14,
) -> pd.Series:
    """Average True Range — volatility measure using high/low/close."""
    if _TALIB_AVAILABLE:
        import talib
        return _wrap(
            talib.ATR(_to_float64(high), _to_float64(low), _to_float64(close), timeperiod=period),
            close.index,
        )
    else:
        import pandas_ta as pta
        result = pta.atr(high, low, close, length=period)
        return result if result is not None else pd.Series(np.nan, index=close.index)


# ---------------------------------------------------------------------------
# Volume ratio — non-library, pure pandas (always available)
# ---------------------------------------------------------------------------

def volume_surge_ratio(volume: pd.Series, window: int = 20) -> pd.Series:
    """
    Current volume divided by the rolling mean volume.
    A value of 1.5 means the current bar's volume is 50% above the mean.

    Args:
        volume: Series of bar volumes.
        window: Rolling look-back period (default 20 bars).

    Returns:
        pd.Series of floats, NaN for the first (window-1) bars.
    """
    rolling_mean = volume.rolling(window=window, min_periods=window).mean()
    return (volume / rolling_mean).rename("volume_surge_ratio")
