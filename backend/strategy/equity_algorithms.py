"""
Equity Trading Strategy Algorithms
=====================================
Three algorithmic strategies for US equity assets (stocks/ETFs).
All strategies enforce market-hours gating: signals are only emitted
during regular US equity session (9:30 AM - 4:00 PM ET, Mon-Fri).

Position-state tracking: FLAT/LONG per symbol prevents naked SELLs.

Supported symbols (configurable):
  EQUITY_SYMBOLS = ["SPY", "QQQ", "AAPL", "MSFT", "NVDA", "TSLA", "AMZN", "GOOGL"]
"""

import math
import logging
from collections import deque
from datetime import datetime, time
import zoneinfo

from strategy.algorithms import BaseStrategy, FLAT, LONG

logger = logging.getLogger(__name__)

ET = zoneinfo.ZoneInfo("America/New_York")
MARKET_OPEN  = time(9, 30)
MARKET_CLOSE = time(16, 0)

EQUITY_SYMBOLS = ["SPY", "QQQ", "AAPL", "MSFT", "NVDA", "TSLA", "AMZN", "GOOGL"]


def _is_market_hours() -> bool:
    """Returns True if current time is within regular US equity market hours (ET, Mon-Fri)."""
    now = datetime.now(ET)
    if now.weekday() >= 5:  # Saturday=5, Sunday=6
        return False
    return MARKET_OPEN <= now.time() <= MARKET_CLOSE


# ---------------------------------------------------------------------------
# Strategy 4: EMA Momentum Equity 
# ---------------------------------------------------------------------------

class EquityMomentumStrategy(BaseStrategy):
    asset_class = "EQUITY"

    def __init__(self, bot_id="equity-momentum", name="Equity Momentum", allocation=20, **kwargs):
        super().__init__(bot_id, name, allocation, "EMA Crossover (Equity)", **kwargs)
        self.ema_short: dict[str, float] = {}
        self.ema_long:  dict[str, float] = {}
        self._ticks: dict[str, int] = {}
        self._last_cross: dict[str, str] = {}
        
        self.alpha_short = getattr(self, 'alpha_short', 0.12)
        self.alpha_long = getattr(self, 'alpha_long', 0.03)
        self.warmup_ticks = getattr(self, 'warmup_ticks', 66) # Must wait for long EMA to stabilize

    async def aanalyze(self, symbol: str, price: float) -> dict | None:
        if not _is_market_hours():
            return None

        if symbol not in self.ema_short:
            self.ema_short[symbol] = price
            self.ema_long[symbol]  = price
            self._ticks[symbol] = 1
            self._last_cross[symbol] = "NONE"
            return None

        self._ticks[symbol] += 1
        self.ema_short[symbol] = (price * self.alpha_short) + (self.ema_short[symbol] * (1 - self.alpha_short))
        self.ema_long[symbol]  = (price * self.alpha_long) + (self.ema_long[symbol]  * (1 - self.alpha_long))

        if self._ticks[symbol] < self.warmup_ticks:
            return None

        short = self.ema_short[symbol]
        long_ = self.ema_long[symbol]
        spread = (short - long_) / long_

        signal = None
        if spread > 0.0015 and self._last_cross.get(symbol) != "BUY" and self._is_flat(symbol):
            self._last_cross[symbol] = "BUY"
            signal = {"bot": self.id, "symbol": symbol, "action": "BUY", "confidence": min(0.95, 0.68 + abs(spread) * 15), "price": price, "meta": {"spread_pct": spread}}
        elif spread < -0.0015 and self._last_cross.get(symbol) != "SELL" and self._is_long(symbol):
            self._last_cross[symbol] = "SELL"
            signal = {"bot": self.id, "symbol": symbol, "action": "SELL", "confidence": min(0.95, 0.68 + abs(spread) * 15), "price": price, "meta": {"spread_pct": spread}}

        if signal:
            self.signal_count += 1
            logger.info("[EQUITY-MOMENTUM] %s -> %s (conf=%.2f, spread=%.4f%%)",
                        symbol, signal["action"], signal["confidence"], spread * 100)
        return signal

    def get_state(self, symbol: str) -> dict | None:
        if symbol not in self.ema_short:
            return None
        short = self.ema_short[symbol]
        long_ = self.ema_long[symbol]
        spread = (short - long_) / long_ if long_ else 0
        return {
            "strategy": self.id,
            "name": self.name,
            "asset_class": self.asset_class,
            "ema_short": round(short, 4),
            "ema_long": round(long_, 4),
            "spread_pct": round(spread * 100, 4),
            "bias": "BULLISH" if spread > 0 else "BEARISH" if spread < 0 else "NEUTRAL",
            "position_state": self._position_state.get(symbol, FLAT),
            "market_hours": _is_market_hours(),
        }


# ---------------------------------------------------------------------------
# Strategy 5: RSI Mean Reversion (Equity) - O(1) Memory Fix
# ---------------------------------------------------------------------------

class EquityRSIStrategy(BaseStrategy):
    asset_class = "EQUITY"

    def __init__(self, bot_id="equity-rsi", name="Equity RSI", allocation=15, **kwargs):
        super().__init__(bot_id, name, allocation, "RSI Mean Reversion", **kwargs)
        self.RSI_PERIOD = getattr(self, 'rsi_period', 14)
        self.RSI_OVERSOLD = getattr(self, 'rsi_oversold', 30)
        self.RSI_OVERBOUGHT = getattr(self, 'rsi_overbought', 70)
        
        self._prev_price: dict[str, float] = {}
        self._avg_gain: dict[str, float] = {}
        self._avg_loss: dict[str, float] = {}
        self._rsi: dict[str, float] = {}
        self._ticks: dict[str, int] = {}
        self._last_signal: dict[str, str] = {}

    def _update_rsi_o1(self, symbol: str, price: float):
        """O(1) Wilder's smoothing without needing a deque."""
        if symbol not in self._prev_price:
            self._prev_price[symbol] = price
            self._avg_gain[symbol] = 0.0
            self._avg_loss[symbol] = 0.0
            self._ticks[symbol] = 1
            return

        self._ticks[symbol] += 1
        change = price - self._prev_price[symbol]
        self._prev_price[symbol] = price

        gain = max(0.0, change)
        loss = max(0.0, -change)

        # Simple SMA for the first RSI_PERIOD ticks
        if self._ticks[symbol] <= self.RSI_PERIOD:
            self._avg_gain[symbol] += gain
            self._avg_loss[symbol] += loss
            if self._ticks[symbol] == self.RSI_PERIOD:
                self._avg_gain[symbol] /= self.RSI_PERIOD
                self._avg_loss[symbol] /= self.RSI_PERIOD
            return

        # Wilder's Smoothing thereafter
        alpha = 1.0 / self.RSI_PERIOD
        self._avg_gain[symbol] = (self._avg_gain[symbol] * (1 - alpha)) + (gain * alpha)
        self._avg_loss[symbol] = (self._avg_loss[symbol] * (1 - alpha)) + (loss * alpha)

        if self._avg_loss[symbol] == 0:
            self._rsi[symbol] = 100.0
        else:
            rs = self._avg_gain[symbol] / self._avg_loss[symbol]
            self._rsi[symbol] = 100 - (100 / (1 + rs))

    async def aanalyze(self, symbol: str, price: float) -> dict | None:
        if not _is_market_hours():
            return None

        self._update_rsi_o1(symbol, price)

        if symbol not in self._rsi:
            return None

        rsi = self._rsi[symbol]
        signal = None

        if rsi < self.RSI_OVERSOLD and self._last_signal.get(symbol) != "BUY" and self._is_flat(symbol):
            self._last_signal[symbol] = "BUY"
            signal = {"bot": self.id, "symbol": symbol, "action": "BUY", "confidence": min(0.95, 0.60 + (self.RSI_OVERSOLD - rsi) / 30 * 0.35), "price": price}
        elif rsi > self.RSI_OVERBOUGHT and self._last_signal.get(symbol) != "SELL" and self._is_long(symbol):
            self._last_signal[symbol] = "SELL"
            signal = {"bot": self.id, "symbol": symbol, "action": "SELL", "confidence": min(0.95, 0.60 + (rsi - self.RSI_OVERBOUGHT) / 30 * 0.35), "price": price}

        if signal:
            self.signal_count += 1
            logger.info("[EQUITY-RSI] %s -> %s (conf=%.2f, RSI=%.1f)",
                        symbol, signal["action"], signal["confidence"], rsi)
        return signal

    def get_state(self, symbol: str) -> dict | None:
        rsi = self._rsi.get(symbol)
        return {
            "strategy": self.id,
            "name": self.name,
            "asset_class": self.asset_class,
            "rsi": round(rsi, 2) if rsi is not None else None,
            "zone": ("OVERSOLD" if rsi and rsi < self.RSI_OVERSOLD
                     else "OVERBOUGHT" if rsi and rsi > self.RSI_OVERBOUGHT
                     else "NEUTRAL"),
            "position_state": self._position_state.get(symbol, FLAT),
            "market_hours": _is_market_hours(),
        }


# ---------------------------------------------------------------------------
# Strategy 6: Equity Pairs Mean Reversion (Welford's O(1) Fix)
# ---------------------------------------------------------------------------

class EquityPairsStrategy(BaseStrategy):
    asset_class = "EQUITY"

    def __init__(self, bot_id="equity-pairs", name="Pairs SPY/QQQ", allocation=10, **kwargs):
        super().__init__(bot_id, name, allocation, "Pairs Mean Reversion", **kwargs)
        self.leg_a = getattr(self, 'leg_a', "SPY")
        self.leg_b = getattr(self, 'leg_b', "QQQ")
        self.WINDOW = getattr(self, 'window', 30)
        self.Z_THRESHOLD = getattr(self, 'z_threshold', 2.0)
        
        self._price_a: float | None = None
        self._price_b: float | None = None
        
        self._spreads = deque(maxlen=self.WINDOW)
        self._welford = {"count": 0, "mean": 0.0, "M2": 0.0}
        self._last_signal: str = "NONE"

    async def aanalyze(self, symbol: str, price: float) -> dict | None:
        if not _is_market_hours():
            return None

        if symbol == self.leg_a:
            self._price_a = price
        elif symbol == self.leg_b:
            self._price_b = price
        else:
            return None

        if self._price_a is None or self._price_b is None or self._price_b == 0:
            return None

        spread = self._price_a / self._price_b
        w = self._welford

        # Welford's Algorithm for O(1) Variance
        if len(self._spreads) == self.WINDOW:
            old_spread = self._spreads[0]
            w["count"] -= 1
            delta = old_spread - w["mean"]
            w["mean"] -= delta / w["count"]
            w["M2"] -= delta * (old_spread - w["mean"])

        self._spreads.append(spread)
        w["count"] += 1
        delta = spread - w["mean"]
        w["mean"] += delta / w["count"]
        w["M2"] += delta * (spread - w["mean"])

        if w["count"] < self.WINDOW:
            return None

        # Only emit on leg_a tick to avoid double-firing
        if symbol != self.leg_a:
            return None

        mean = w["mean"]
        variance = w["M2"] / w["count"]
        std = math.sqrt(variance) if variance > 0 else 1e-9
        z_score = (spread - mean) / std

        signal = None
        if z_score < -self.Z_THRESHOLD and self._last_signal != "BUY" and self._is_flat(self.leg_a):
            self._last_signal = "BUY"
            signal = {"bot": self.id, "symbol": self.leg_a, "action": "BUY", "confidence": min(0.93, 0.65 + abs(z_score) * 0.08), "price": price}
        elif z_score > self.Z_THRESHOLD and self._last_signal != "SELL" and self._is_long(self.leg_a):
            self._last_signal = "SELL"
            signal = {"bot": self.id, "symbol": self.leg_a, "action": "SELL", "confidence": min(0.93, 0.65 + abs(z_score) * 0.08), "price": price}

        if signal:
            self.signal_count += 1
            logger.info("[EQUITY-PAIRS] %s/%s z=%.2f -> %s %s (conf=%.2f)",
                        self.leg_a, self.leg_b, z_score,
                        signal["action"], self.leg_a, signal["confidence"])
        return signal

    def get_state(self, symbol: str) -> dict | None:
        if symbol not in (self.leg_a, self.leg_b):
            return None
        z_score = None
        w = self._welford
        if w["count"] >= self.WINDOW and w["M2"] > 0:
            std = math.sqrt(w["M2"] / w["count"])
            spread = self._spreads[-1]
            z_score = round((spread - w["mean"]) / std, 3)
        return {
            "strategy": self.id,
            "name": self.name,
            "asset_class": self.asset_class,
            "leg_a": self.leg_a,
            "leg_b": self.leg_b,
            "price_a": self._price_a,
            "price_b": self._price_b,
            "z_score": z_score,
            "position_state": self._position_state.get(self.leg_a, FLAT),
            "ticks_collected": w["count"],
            "market_hours": _is_market_hours(),
        }
