"""
OHLCV Data Buffer
==================
Thread-safe rolling candle store that ingests real-time bars from the
Alpaca CryptoDataStream and maintains two independent rolling DataFrames:

  1-Min  — aggregated from Alpaca 1-minute bar callbacks
  5-Min  — assembled incrementally as each 1-min bar closes a 5-min window

Design goals:
  • Thread-safe — bar_callback runs in a ThreadPoolExecutor thread while
    FastAPI request handlers read buffers from the asyncio event loop.
    A single threading.RLock guards all mutable state.
  • Fixed memory footprint — each (symbol, timeframe) buffer is capped at
    MAX_PERIODS rows (default 250). Older rows are dropped automatically.
    250 rows is the minimum needed to compute EMA-200 with a 50-bar warm-up.
  • Correct 5-min assembly — candles are built bar-by-bar using UTC-floor
    window alignment so they always represent clean 5-min intervals
    (00:00, 00:05, 00:10 …). A work-in-progress (WIP) candle accumulates
    until the first bar in the next window flushes it.
  • Minimal copies — get_candles() returns a shallow .copy() so callers
    cannot mutate internal state, but the copy is fast on small DataFrames.

Public API:
  ingest_bar(symbol, bar)                → None
  ingest_tick(symbol, price, volume, ts) → None   (for raw trade events)
  get_candles(symbol, timeframe)         → pd.DataFrame
  get_latest(symbol, timeframe)          → dict | None
  close(symbol, timeframe)              → pd.Series
  is_ready(symbol, timeframe, min_periods) → bool
  snapshot()                             → dict   (monitoring / health-check)
  symbols()                              → list[str]

Usage:
    from quant.data_buffer import market_buffer

    # In bar_callback:
    market_buffer.ingest_bar(bar.symbol, bar)

    # In TA engine:
    if market_buffer.is_ready("BTC/USD", "5Min"):
        df = market_buffer.get_candles("BTC/USD", "5Min")
        ema50 = ema(df["close"], 50)
"""

from __future__ import annotations

import logging
import threading
from datetime import timezone
from typing import Any

import pandas as pd

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

MAX_PERIODS: int = 250           # rows kept per (symbol, timeframe) buffer
_COLS: list[str] = ["open", "high", "low", "close", "volume"]

# Alpaca crypto bar attribute names (alpaca-py >= 0.20)
_BAR_ATTRS = ("open", "high", "low", "close", "volume", "timestamp")


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _floor_1min(ts: pd.Timestamp) -> pd.Timestamp:
    return ts.floor("1min")


def _floor_5min(ts: pd.Timestamp) -> pd.Timestamp:
    return ts.floor("5min")


def _to_utc_ts(raw) -> pd.Timestamp:
    """Normalize any timestamp type to a UTC-aware pd.Timestamp."""
    ts = pd.Timestamp(raw)
    if ts.tzinfo is None:
        ts = ts.tz_localize("UTC")
    else:
        ts = ts.tz_convert("UTC")
    return ts


def _empty_df() -> pd.DataFrame:
    """Return an empty OHLCV DataFrame with a UTC DatetimeIndex."""
    return pd.DataFrame(
        columns=_COLS,
        dtype=float,
        index=pd.DatetimeIndex([], tz="UTC", name="timestamp"),
    )


def _make_row(ts: pd.Timestamp, o: float, h: float, l: float, c: float, v: float) -> pd.DataFrame:
    """Build a single-row DataFrame suitable for pd.concat."""
    return pd.DataFrame(
        [[o, h, l, c, v]],
        columns=_COLS,
        index=pd.DatetimeIndex([ts], tz="UTC", name="timestamp"),
    )


# ---------------------------------------------------------------------------
# WIP candle — assembled bar-by-bar before the window closes
# ---------------------------------------------------------------------------

class _WIPCandle:
    """Mutable work-in-progress candle for a single open time window."""

    __slots__ = ("window_start", "open", "high", "low", "close", "volume")

    def __init__(
        self,
        window_start: pd.Timestamp,
        o: float, h: float, l: float, c: float, v: float,
    ):
        self.window_start = window_start
        self.open   = o
        self.high   = h
        self.low    = l
        self.close  = c
        self.volume = v

    def merge(self, h: float, l: float, c: float, v: float) -> None:
        """Incorporate a new bar into the current window."""
        if h > self.high:
            self.high = h
        if l < self.low:
            self.low = l
        self.close   = c
        self.volume += v

    def to_row(self) -> pd.DataFrame:
        return _make_row(
            self.window_start,
            self.open, self.high, self.low, self.close, self.volume,
        )


# ---------------------------------------------------------------------------
# OHLCVBuffer — main class
# ---------------------------------------------------------------------------

class OHLCVBuffer:
    """
    Rolling OHLCV candle store for multiple symbols and two timeframes.

    Internal state (all guarded by self._lock):
      _1min[symbol]    : pd.DataFrame — completed 1-min candles
      _5min[symbol]    : pd.DataFrame — completed 5-min candles
      _1min_wip[symbol]: _WIPCandle   — partial 1-min candle in progress
                                        (used for tick-level ingest only)
      _5min_wip[symbol]: _WIPCandle   — partial 5-min candle in progress
    """

    def __init__(self, max_periods: int = MAX_PERIODS):
        self._max = max_periods
        self._1min:     dict[str, pd.DataFrame] = {}
        self._5min:     dict[str, pd.DataFrame] = {}
        self._1min_wip: dict[str, _WIPCandle]   = {}
        self._5min_wip: dict[str, _WIPCandle]   = {}
        self._lock = threading.RLock()

    # ------------------------------------------------------------------
    # Ingestion — called from stream thread
    # ------------------------------------------------------------------

    def ingest_bar(self, symbol: str, bar: Any) -> None:
        """
        Ingest a 1-minute bar from the Alpaca CryptoDataStream.

        Accepts any object with attributes: open, high, low, close, volume,
        timestamp. Falls back gracefully if high/low/open are missing
        (some older SDK versions only expose close).

        Thread-safe. Called from bar_callback in the stream thread.
        """
        try:
            c   = float(bar.close)
            o   = float(getattr(bar, "open",   c))
            h   = float(getattr(bar, "high",   c))
            l   = float(getattr(bar, "low",    c))
            v   = float(getattr(bar, "volume", 0.0))
            ts  = _to_utc_ts(bar.timestamp)
        except (AttributeError, TypeError, ValueError) as exc:
            logger.warning("[BUFFER] ingest_bar failed for %s: %s", symbol, exc)
            return

        with self._lock:
            self._append_1min(symbol, ts, o, h, l, c, v)
            self._update_5min_from_bar(symbol, ts, o, h, l, c, v)

    def ingest_ohlcv_df(self, symbol: str, df: "pd.DataFrame") -> None:
        """Bulk-load a pre-fetched OHLCV DataFrame into the 1-min and 5-min buffers.

        df must have a UTC-aware DatetimeIndex and columns: open, high, low, close, volume.
        Used to pre-seed the buffer with historical REST data before live streams start,
        so TA indicators (EMA20, RSI14, etc.) are computable from the first scan.
        """
        if df is None or df.empty:
            return
        with self._lock:
            for ts, row in df.iterrows():
                try:
                    ts_utc = pd.Timestamp(ts)
                    if ts_utc.tzinfo is None:
                        ts_utc = ts_utc.tz_localize("UTC")
                    else:
                        ts_utc = ts_utc.tz_convert("UTC")
                    o = float(row.get("open",   row.get("close", 0)))
                    h = float(row.get("high",   row.get("close", 0)))
                    l = float(row.get("low",    row.get("close", 0)))
                    c = float(row.get("close",  0))
                    v = float(row.get("volume", 0))
                    self._append_1min(symbol, ts_utc, o, h, l, c, v)
                    self._update_5min_from_bar(symbol, ts_utc, o, h, l, c, v)
                except Exception:
                    continue

    def ingest_tick(
        self,
        symbol: str,
        price: float,
        volume: float,
        timestamp: Any,
    ) -> None:
        """
        Ingest a raw trade tick and aggregate into 1-min and 5-min candles.

        Ticks within the same minute are merged into the WIP candle.
        When the minute rolls over the completed candle is committed and
        the 5-min WIP is updated accordingly.

        Use this when subscribing to trade events instead of (or alongside)
        bar events. Thread-safe.
        """
        try:
            ts = _to_utc_ts(timestamp)
            o = h = l = c = float(price)
            v = float(volume)
        except (TypeError, ValueError) as exc:
            logger.warning("[BUFFER] ingest_tick failed for %s: %s", symbol, exc)
            return

        window_1min = _floor_1min(ts)

        with self._lock:
            wip = self._1min_wip.get(symbol)

            if wip is None:
                # First tick — open a new WIP
                self._1min_wip[symbol] = _WIPCandle(window_1min, o, h, l, c, v)

            elif wip.window_start == window_1min:
                # Same minute — merge into WIP
                wip.merge(h, l, c, v)

            else:
                # Minute rolled over — flush completed WIP as a 1-min candle
                completed = wip.to_row()
                completed_ts = wip.window_start
                co, ch, cl, cc, cv = (
                    wip.open, wip.high, wip.low, wip.close, wip.volume
                )
                self._commit_1min(symbol, completed)
                self._update_5min_from_bar(symbol, completed_ts, co, ch, cl, cc, cv)
                # Open new WIP for the fresh minute
                self._1min_wip[symbol] = _WIPCandle(window_1min, o, h, l, c, v)

    # ------------------------------------------------------------------
    # Internal commit helpers (called inside _lock)
    # ------------------------------------------------------------------

    def _append_1min(
        self,
        symbol: str,
        ts: pd.Timestamp,
        o: float, h: float, l: float, c: float, v: float,
    ) -> None:
        if symbol not in self._1min:
            self._1min[symbol] = _empty_df()
        row = _make_row(ts, o, h, l, c, v)
        self._1min[symbol] = pd.concat([self._1min[symbol], row]).tail(self._max)

    def _commit_1min(self, symbol: str, row: pd.DataFrame) -> None:
        if symbol not in self._1min:
            self._1min[symbol] = _empty_df()
        self._1min[symbol] = pd.concat([self._1min[symbol], row]).tail(self._max)

    def _update_5min_from_bar(
        self,
        symbol: str,
        ts: pd.Timestamp,
        o: float, h: float, l: float, c: float, v: float,
    ) -> None:
        """Merge a 1-min bar into the 5-min WIP, flushing when the window closes."""
        window_5min = _floor_5min(ts)

        if symbol not in self._5min:
            self._5min[symbol] = _empty_df()

        wip = self._5min_wip.get(symbol)

        if wip is None:
            # No candle open yet — start one
            self._5min_wip[symbol] = _WIPCandle(window_5min, o, h, l, c, v)
            logger.debug("[BUFFER] %s 5-min WIP opened @ %s", symbol, window_5min)

        elif wip.window_start == window_5min:
            # Same 5-min window — merge
            wip.merge(h, l, c, v)

        else:
            # New window — flush the completed candle
            completed = wip.to_row()
            self._5min[symbol] = pd.concat([self._5min[symbol], completed]).tail(self._max)
            logger.debug(
                "[BUFFER] %s 5-min candle closed O=%.2f H=%.2f L=%.2f C=%.2f V=%.2f @ %s",
                symbol, wip.open, wip.high, wip.low, wip.close, wip.volume, wip.window_start,
            )
            # Start fresh WIP for the new window
            self._5min_wip[symbol] = _WIPCandle(window_5min, o, h, l, c, v)

    # ------------------------------------------------------------------
    # Read API — called from FastAPI / TA engine (may be async context)
    # ------------------------------------------------------------------

    def get_candles(self, symbol: str, timeframe: str) -> pd.DataFrame:
        """
        Return a copy of the rolling OHLCV DataFrame for (symbol, timeframe).

        Returns an empty DataFrame if the symbol or timeframe has no data yet.
        The copy prevents callers from mutating internal state.

        Args:
            symbol:    e.g. 'BTC/USD'
            timeframe: '1Min' or '5Min'
        """
        with self._lock:
            store = self._resolve_store(timeframe)
            df = store.get(symbol, _empty_df())
            return df.copy()

    def get_latest(self, symbol: str, timeframe: str) -> dict | None:
        """
        Return the last completed candle as a plain dict, or None if the
        buffer has no data yet for (symbol, timeframe).
        """
        df = self.get_candles(symbol, timeframe)
        if df.empty:
            return None
        row = df.iloc[-1]
        return {
            "symbol":    symbol,
            "timeframe": timeframe,
            "timestamp": df.index[-1].isoformat(),
            "open":      float(row["open"]),
            "high":      float(row["high"]),
            "low":       float(row["low"]),
            "close":     float(row["close"]),
            "volume":    float(row["volume"]),
        }

    def close(self, symbol: str, timeframe: str) -> pd.Series:
        """
        Return just the close-price Series — the primary input for most
        TA indicator functions (EMA, RSI, MACD, Bollinger Bands).
        """
        return self.get_candles(symbol, timeframe)["close"]

    def high(self, symbol: str, timeframe: str) -> pd.Series:
        return self.get_candles(symbol, timeframe)["high"]

    def low(self, symbol: str, timeframe: str) -> pd.Series:
        return self.get_candles(symbol, timeframe)["low"]

    def volume(self, symbol: str, timeframe: str) -> pd.Series:
        return self.get_candles(symbol, timeframe)["volume"]

    def is_ready(
        self,
        symbol: str,
        timeframe: str,
        min_periods: int = 200,
    ) -> bool:
        """
        Return True when the buffer holds at least min_periods completed
        candles for (symbol, timeframe).

        The TA engine gates all indicator calculations behind is_ready()
        to avoid computing EMA-200 on fewer than 200 bars.
        """
        with self._lock:
            store = self._resolve_store(timeframe)
            df = store.get(symbol)
            return df is not None and len(df) >= min_periods

    def period_count(self, symbol: str, timeframe: str) -> int:
        """Return the number of completed candles currently in the buffer."""
        with self._lock:
            store = self._resolve_store(timeframe)
            df = store.get(symbol)
            return len(df) if df is not None else 0

    def symbols(self) -> list[str]:
        """Return all symbols that have received at least one bar."""
        with self._lock:
            return sorted(set(self._1min.keys()) | set(self._5min.keys()))

    def snapshot(self) -> dict[str, dict]:
        """
        Return a dict of buffer health metrics per symbol.
        Useful for a /api/buffer/status endpoint or logging.

        Example:
          {
            "BTC/USD": {
              "1Min": {"bars": 127, "ready": false, "latest": "2025-04-14T10:23:00+00:00"},
              "5Min": {"bars": 25,  "ready": false, "wip_window": "2025-04-14T10:20:00+00:00"},
            }
          }
        """
        with self._lock:
            result: dict[str, dict] = {}
            all_syms = set(self._1min.keys()) | set(self._5min.keys())
            for sym in sorted(all_syms):
                df1 = self._1min.get(sym, _empty_df())
                df5 = self._5min.get(sym, _empty_df())
                wip5 = self._5min_wip.get(sym)
                result[sym] = {
                    "1Min": {
                        "bars":   len(df1),
                        "ready":  len(df1) >= 200,
                        "latest": df1.index[-1].isoformat() if not df1.empty else None,
                    },
                    "5Min": {
                        "bars":      len(df5),
                        "ready":     len(df5) >= 200,
                        "wip_window": wip5.window_start.isoformat() if wip5 else None,
                        "latest":    df5.index[-1].isoformat() if not df5.empty else None,
                    },
                }
            return result

    # ------------------------------------------------------------------
    # Internal
    # ------------------------------------------------------------------

    def _resolve_store(self, timeframe: str) -> dict[str, pd.DataFrame]:
        """Map a timeframe string to the correct internal store dict."""
        if timeframe == "1Min":
            return self._1min
        if timeframe == "5Min":
            return self._5min
        raise ValueError(
            f"Unknown timeframe '{timeframe}'. Supported values: '1Min', '5Min'."
        )


# ---------------------------------------------------------------------------
# Module-level singleton — import and use directly
# ---------------------------------------------------------------------------

market_buffer: OHLCVBuffer = OHLCVBuffer(max_periods=MAX_PERIODS)
