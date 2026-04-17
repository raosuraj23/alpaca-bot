"""
Equity Trading Strategy Algorithms
=====================================
Three algorithmic strategies for US equity assets (stocks/ETFs).
All strategies enforce market-hours gating: signals are only emitted
during regular US equity session (9:30 AM – 4:00 PM ET, Mon–Fri).

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
    """Returns True if current time is within regular US equity market hours (ET, Mon–Fri)."""
    now = datetime.now(ET)
    if now.weekday() >= 5:  # Saturday=5, Sunday=6
        return False
    return MARKET_OPEN <= now.time() <= MARKET_CLOSE


# ---------------------------------------------------------------------------
# Strategy 4: EMA Momentum Equity (same crossover logic as crypto momentum)
# ---------------------------------------------------------------------------

class EquityMomentumStrategy(BaseStrategy):
    """
    Dual-EMA crossover strategy adapted for US equities.

    Slower EMAs than the crypto variant to suit lower-frequency equity data:
      - EMA-short (α=0.12, approx 16-period)
      - EMA-long  (α=0.03, approx 66-period)

    Signal logic (market hours only):
      BUY  when short crosses above long by > 0.15% AND position FLAT
      SELL when short crosses below long by > 0.15% AND position LONG

    Starts ACTIVE with 20% allocation.
    """

    asset_class = "EQUITY"

    def __init__(self, bot_id="equity-momentum", name="Equity Momentum", allocation=20):
        super().__init__(bot_id, name, allocation, "EMA Crossover (Equity)")
        self.ema_short: dict[str, float] = {}
        self.ema_long:  dict[str, float] = {}
        self._last_cross: dict[str, str] = {}

    def analyze(self, symbol: str, price: float) -> dict | None:
        if not _is_market_hours():
            return None

        if symbol not in self.ema_short:
            self.ema_short[symbol] = price
            self.ema_long[symbol]  = price
            self._last_cross[symbol] = "NONE"
            return None

        self.ema_short[symbol] = (price * 0.12) + (self.ema_short[symbol] * 0.88)
        self.ema_long[symbol]  = (price * 0.03) + (self.ema_long[symbol]  * 0.97)

        short = self.ema_short[symbol]
        long_ = self.ema_long[symbol]
        spread = (short - long_) / long_

        signal = None
        if spread > 0.0015 and self._last_cross.get(symbol) != "BUY" and self._is_flat(symbol):
            self._last_cross[symbol] = "BUY"
            confidence = min(0.95, 0.68 + abs(spread) * 15)
            signal = {
                "bot": self.id, "symbol": symbol, "action": "BUY",
                "confidence": round(confidence, 3), "price": price,
                "meta": {"ema_short": round(short, 4), "ema_long": round(long_, 4),
                         "spread_pct": round(spread * 100, 4), "market_hours": True}
            }
        elif spread < -0.0015 and self._last_cross.get(symbol) != "SELL" and self._is_long(symbol):
            self._last_cross[symbol] = "SELL"
            confidence = min(0.95, 0.68 + abs(spread) * 15)
            signal = {
                "bot": self.id, "symbol": symbol, "action": "SELL",
                "confidence": round(confidence, 3), "price": price,
                "meta": {"ema_short": round(short, 4), "ema_long": round(long_, 4),
                         "spread_pct": round(spread * 100, 4), "market_hours": True}
            }

        if signal:
            self.signal_count += 1
            logger.info("[EQUITY-MOMENTUM] %s → %s (conf=%.2f, spread=%.4f%%)",
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
# Strategy 5: RSI Mean Reversion (Equity)
# ---------------------------------------------------------------------------

class EquityRSIStrategy(BaseStrategy):
    """
    RSI-based mean reversion for individual equities.

    Maintains a 14-period RSI per symbol using Wilder's smoothing.

    Signal logic (market hours only):
      BUY  when RSI < 30 (oversold) AND position FLAT
      SELL when RSI > 70 (overbought) AND position LONG

    Confidence scales linearly with RSI extremity:
      BUY  conf = 0.60 + (30 - RSI) / 30 * 0.35
      SELL conf = 0.60 + (RSI - 70) / 30 * 0.35

    Allocation: 15% default.
    """

    asset_class = "EQUITY"
    RSI_PERIOD = 14
    RSI_OVERSOLD  = 30
    RSI_OVERBOUGHT = 70

    def __init__(self, bot_id="equity-rsi", name="Equity RSI", allocation=15):
        super().__init__(bot_id, name, allocation, "RSI Mean Reversion")
        self._prices: dict[str, deque] = {}
        self._avg_gain: dict[str, float] = {}
        self._avg_loss: dict[str, float] = {}
        self._rsi: dict[str, float] = {}
        self._last_signal: dict[str, str] = {}
        self._initialized: dict[str, bool] = {}

    def _update_rsi(self, symbol: str, price: float):
        """Wilder's smoothed RSI update."""
        if symbol not in self._prices:
            self._prices[symbol] = deque(maxlen=self.RSI_PERIOD + 1)
            self._initialized[symbol] = False

        self._prices[symbol].append(price)

        if len(self._prices[symbol]) < self.RSI_PERIOD + 1:
            return

        if not self._initialized[symbol]:
            changes = [self._prices[symbol][i+1] - self._prices[symbol][i]
                       for i in range(self.RSI_PERIOD)]
            gains = [c for c in changes if c > 0]
            losses = [abs(c) for c in changes if c < 0]
            self._avg_gain[symbol] = sum(gains) / self.RSI_PERIOD
            self._avg_loss[symbol] = sum(losses) / self.RSI_PERIOD
            self._initialized[symbol] = True
        else:
            prices = list(self._prices[symbol])
            change = prices[-1] - prices[-2]
            gain = max(0.0, change)
            loss = max(0.0, -change)
            alpha = 1.0 / self.RSI_PERIOD
            self._avg_gain[symbol] = (self._avg_gain[symbol] * (1 - alpha)) + (gain * alpha)
            self._avg_loss[symbol] = (self._avg_loss[symbol] * (1 - alpha)) + (loss * alpha)

        if self._avg_loss[symbol] == 0:
            self._rsi[symbol] = 100.0
        else:
            rs = self._avg_gain[symbol] / self._avg_loss[symbol]
            self._rsi[symbol] = 100 - (100 / (1 + rs))

    def analyze(self, symbol: str, price: float) -> dict | None:
        if not _is_market_hours():
            return None

        self._update_rsi(symbol, price)

        if symbol not in self._rsi:
            return None

        rsi = self._rsi[symbol]
        signal = None

        if rsi < self.RSI_OVERSOLD and self._last_signal.get(symbol) != "BUY" and self._is_flat(symbol):
            confidence = min(0.95, 0.60 + (self.RSI_OVERSOLD - rsi) / 30 * 0.35)
            self._last_signal[symbol] = "BUY"
            signal = {
                "bot": self.id, "symbol": symbol, "action": "BUY",
                "confidence": round(confidence, 3), "price": price,
                "meta": {"rsi": round(rsi, 2), "zone": "OVERSOLD"}
            }
        elif rsi > self.RSI_OVERBOUGHT and self._last_signal.get(symbol) != "SELL" and self._is_long(symbol):
            confidence = min(0.95, 0.60 + (rsi - self.RSI_OVERBOUGHT) / 30 * 0.35)
            self._last_signal[symbol] = "SELL"
            signal = {
                "bot": self.id, "symbol": symbol, "action": "SELL",
                "confidence": round(confidence, 3), "price": price,
                "meta": {"rsi": round(rsi, 2), "zone": "OVERBOUGHT"}
            }

        if signal:
            self.signal_count += 1
            logger.info("[EQUITY-RSI] %s → %s (conf=%.2f, RSI=%.1f)",
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
# Strategy 6: Equity Pairs Mean Reversion (SPY / QQQ spread)
# ---------------------------------------------------------------------------

class EquityPairsStrategy(BaseStrategy):
    """
    Statistical pairs trading between two correlated ETFs (default: SPY / QQQ).

    Maintains a rolling 30-period z-score of the price spread ratio (SPY / QQQ).

    Signal logic:
      When z-score < -2.0 (SPY cheap vs QQQ):
        BUY  SPY  (expect spread to revert upward)
      When z-score > +2.0 (SPY expensive vs QQQ):
        SELL SPY  (expect spread to revert downward — exit LONG)

    Only SPY signals are emitted here (QQQ is the reference leg).
    Allocation: 10% default.

    Spread variance tracked via Welford's sliding-window algorithm (O(1) per tick).
    """

    asset_class = "EQUITY"
    WINDOW = 30
    Z_THRESHOLD = 2.0

    def __init__(self, bot_id="equity-pairs", name="Pairs SPY/QQQ", allocation=10,
                 leg_a="SPY", leg_b="QQQ"):
        super().__init__(bot_id, name, allocation, "Pairs Mean Reversion")
        self.leg_a = leg_a
        self.leg_b = leg_b
        self._price_a: float | None = None
        self._price_b: float | None = None
        self._spread_history: deque = deque(maxlen=self.WINDOW)
        self._last_signal: str = "NONE"
        # Welford sliding-window state for spread variance
        self._w_mean: float = 0.0
        self._w_M2:   float = 0.0
        self._w_n:    int   = 0

    def _update_welford(self, spread: float) -> None:
        """Welford's sliding-window variance update (O(1)).
        Must be called BEFORE appending spread to self._spread_history."""
        n_cur = len(self._spread_history)
        if n_cur == 0:
            self._w_mean = spread
            self._w_M2   = 0.0
            self._w_n    = 1
        elif n_cur < self.WINDOW:
            self._w_n += 1
            delta = spread - self._w_mean
            self._w_mean += delta / self._w_n
            self._w_M2   += delta * (spread - self._w_mean)
        else:
            old_x    = self._spread_history[0]
            old_mean = self._w_mean
            self._w_mean += (spread - old_x) / self.WINDOW
            self._w_M2   += (spread - old_x) * (
                (spread - self._w_mean) + (old_x - old_mean)
            )
            self._w_M2 = max(0.0, self._w_M2)

    def analyze(self, symbol: str, price: float) -> dict | None:
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
        self._update_welford(spread)
        self._spread_history.append(spread)

        if len(self._spread_history) < self.WINDOW:
            return None

        # Only emit signal on leg_a tick to avoid double-firing
        if symbol != self.leg_a:
            return None

        mean    = self._w_mean
        std     = math.sqrt(self._w_M2 / self.WINDOW) if self._w_M2 > 0 else 1e-9
        z_score = (spread - mean) / std

        signal = None
        if z_score < -self.Z_THRESHOLD and self._last_signal != "BUY" and self._is_flat(self.leg_a):
            confidence = min(0.93, 0.65 + abs(z_score) * 0.08)
            self._last_signal = "BUY"
            signal = {
                "bot": self.id, "symbol": self.leg_a, "action": "BUY",
                "confidence": round(confidence, 3), "price": price,
                "meta": {"z_score": round(z_score, 3), "spread_ratio": round(spread, 4),
                         "mean": round(mean, 4), "std": round(std, 4)}
            }
        elif z_score > self.Z_THRESHOLD and self._last_signal != "SELL" and self._is_long(self.leg_a):
            confidence = min(0.93, 0.65 + abs(z_score) * 0.08)
            self._last_signal = "SELL"
            signal = {
                "bot": self.id, "symbol": self.leg_a, "action": "SELL",
                "confidence": round(confidence, 3), "price": price,
                "meta": {"z_score": round(z_score, 3), "spread_ratio": round(spread, 4),
                         "mean": round(mean, 4), "std": round(std, 4)}
            }

        if signal:
            self.signal_count += 1
            logger.info("[EQUITY-PAIRS] %s/%s z=%.2f → %s %s (conf=%.2f)",
                        self.leg_a, self.leg_b, z_score,
                        signal["action"], self.leg_a, signal["confidence"])
        return signal

    def get_state(self, symbol: str) -> dict | None:
        if symbol not in (self.leg_a, self.leg_b):
            return None
        z_score = None
        if len(self._spread_history) >= self.WINDOW and self._w_M2 > 0:
            std     = math.sqrt(self._w_M2 / self.WINDOW)
            spread  = self._spread_history[-1]
            z_score = round((spread - self._w_mean) / std, 3)
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
            "ticks_collected": len(self._spread_history),
            "market_hours": _is_market_hours(),
        }
