"""
Equity Trading Strategy Algorithms
=====================================
Three algorithmic strategies for US equity assets (stocks/ETFs).
All strategies enforce market-hours gating: signals are only emitted
during regular US equity session (9:30 AM - 4:00 PM ET, Mon-Fri).

Position-state tracking: FLAT/LONG per symbol prevents naked SELLs.

Supported symbols (seed; universe grows dynamically via expand_universe()):
  EQUITY_SYMBOLS — initial bootstrap list, extended at runtime by scanner discovery
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

EQUITY_SYMBOLS = [
    "SPY", "QQQ", "AAPL", "MSFT", "NVDA",
    "TSLA", "AMZN", "GOOGL", "META", "AMD",
    "NFLX", "INTC", "JPM", "BAC", "GS",
]


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
        self._reset_pair_state()

    def _reset_pair_state(self) -> None:
        self._price_a: float | None = None
        self._price_b: float | None = None
        self._spreads = deque(maxlen=self.WINDOW)
        self._welford = {"count": 0, "mean": 0.0, "M2": 0.0}
        self._last_signal: str = "NONE"

    def update_params(self, params: dict) -> None:
        """Reset spread history when legs change so stale data doesn't corrupt the new pair."""
        legs_changed = "leg_a" in params or "leg_b" in params
        super().update_params(params)
        if "window" in params:
            self.WINDOW = int(self.WINDOW)
        if "z_threshold" in params:
            self.Z_THRESHOLD = float(self.Z_THRESHOLD)
        if legs_changed:
            self._reset_pair_state()
            logger.info("[%s] Pair legs changed → state reset (leg_a=%s, leg_b=%s)",
                        self.name, self.leg_a, self.leg_b)

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


# ---------------------------------------------------------------------------
# Strategy 7: Equity Breakout (ATR-based breakout with volume confirmation)
# ---------------------------------------------------------------------------

class EquityBreakoutStrategy(BaseStrategy):
    """
    ATR-based breakout strategy for equities.

    BUY when:
      - price > N-bar high + breakout_multiplier × ATR
      - volume_ratio (current / avg) > volume_threshold
      - position is FLAT
    SELL on trailing stop: if price falls below entry − atr_period-bar ATR.

    ATR uses Wilder's smoothing (O(1)). Volume tracked via EWM average.

    Params (all patchable):
      atr_period          int    ATR smoothing window (default 14)
      breakout_multiplier float  ATR multiple above N-bar high to confirm breakout (default 1.5)
      volume_threshold    float  Volume ratio threshold (default 1.8)
      cooldown_ticks      int    Ticks between signals (default 20)
    """
    asset_class = "EQUITY"

    def __init__(self, bot_id="equity-breakout", name="Equity Breakout", allocation=15, **kwargs):
        super().__init__(bot_id, name, allocation, "ATR Breakout", **kwargs)
        self.atr_period          = getattr(self, 'atr_period',          14)
        self.breakout_multiplier = getattr(self, 'breakout_multiplier', 1.5)
        self.volume_threshold    = getattr(self, 'volume_threshold',    1.8)
        self.cooldown_ticks      = getattr(self, 'cooldown_ticks',      20)

        self._prev_price:  dict[str, float] = {}
        self._atr:         dict[str, float] = {}   # Wilder smoothed ATR
        self._highs:       dict[str, deque] = {}   # rolling N-bar highs
        self._avg_vol:     dict[str, float] = {}   # EWM volume average
        self._ticks:       dict[str, int]   = {}
        self._cooldown:    dict[str, int]   = {}
        self._entry_price: dict[str, float] = {}

    def _update_atr(self, symbol: str, price: float, volume: float = 0.0) -> None:
        if symbol not in self._prev_price:
            self._prev_price[symbol] = price
            self._atr[symbol]        = 0.0
            self._highs[symbol]      = deque(maxlen=self.atr_period)
            self._avg_vol[symbol]    = volume if volume > 0 else 1.0
            self._ticks[symbol]      = 1
            return
        self._ticks[symbol] += 1
        tr = abs(price - self._prev_price[symbol])
        alpha = 1.0 / self.atr_period
        self._atr[symbol]     = self._atr[symbol] * (1 - alpha) + tr * alpha
        self._prev_price[symbol] = price
        self._highs[symbol].append(price)
        if volume > 0:
            self._avg_vol[symbol] = self._avg_vol[symbol] * 0.95 + volume * 0.05

    async def aanalyze(self, symbol: str, price: float, volume: float = 0.0) -> dict | None:
        if not _is_market_hours():
            return None

        self._update_atr(symbol, price, volume)
        self._cooldown[symbol] = max(0, self._cooldown.get(symbol, 0) - 1)

        if self._ticks.get(symbol, 0) < self.atr_period:
            return None

        atr     = self._atr[symbol]
        n_high  = max(self._highs[symbol]) if self._highs[symbol] else price
        vol_ok  = (volume / max(self._avg_vol.get(symbol, 1.0), 1e-6)) >= self.volume_threshold

        # Trailing stop exit
        if self._is_long(symbol) and symbol in self._entry_price:
            stop = self._entry_price[symbol] - atr
            if price <= stop:
                self._cooldown[symbol] = self.cooldown_ticks
                del self._entry_price[symbol]
                self.signal_count += 1
                return {
                    "bot": self.id, "symbol": symbol, "action": "SELL",
                    "confidence": 0.90, "price": price,
                    "meta": {"trigger": "trailing_stop", "atr": round(atr, 4)},
                }

        if self._cooldown[symbol] > 0:
            return None

        breakout_level = n_high + self.breakout_multiplier * atr
        signal = None
        if price > breakout_level and vol_ok and self._is_flat(symbol):
            conf = min(0.93, 0.70 + (price - breakout_level) / max(atr, 1e-6) * 0.05)
            self._cooldown[symbol]    = self.cooldown_ticks
            self._entry_price[symbol] = price
            self.signal_count += 1
            signal = {
                "bot": self.id, "symbol": symbol, "action": "BUY",
                "confidence": round(conf, 3), "price": price,
                "meta": {"breakout_level": round(breakout_level, 4), "atr": round(atr, 4),
                         "n_high": round(n_high, 4)},
            }

        if signal:
            logger.info("[EQUITY-BREAKOUT] %s → %s (conf=%.2f, atr=%.4f)",
                        symbol, signal["action"], signal["confidence"], atr)
        return signal

    def get_state(self, symbol: str) -> dict | None:
        return {
            "strategy": self.id,
            "name": self.name,
            "asset_class": self.asset_class,
            "atr": round(self._atr.get(symbol, 0.0), 4),
            "cooldown_remaining": self._cooldown.get(symbol, 0),
            "position_state": self._position_state.get(symbol, FLAT),
            "entry_price": round(self._entry_price[symbol], 4) if symbol in self._entry_price else None,
            "market_hours": _is_market_hours(),
        }


# ---------------------------------------------------------------------------
# Strategy 8: VWAP Reversion (equity intraday mean-reversion to VWAP)
# ---------------------------------------------------------------------------

class VWAPReversionStrategy(BaseStrategy):
    """
    Intraday mean-reversion to VWAP for equity symbols.

    BUY  when price deviates below VWAP by > sigma_threshold standard deviations.
    SELL when price deviates above VWAP by > sigma_threshold, or position is LONG.

    VWAP and rolling variance are computed via O(1) cumulative accumulation.
    State is reset at each market open (9:30 AM ET).

    Params (all patchable):
      sigma_threshold  float  Deviation in σ to trigger entry (default 1.5)
      warmup_ticks     int    Minimum ticks before emitting signals (default 30)
    """
    asset_class = "EQUITY"

    def __init__(self, bot_id="vwap-reversion", name="VWAP Reversion", allocation=15, **kwargs):
        super().__init__(bot_id, name, allocation, "VWAP Reversion", **kwargs)
        self.sigma_threshold = getattr(self, 'sigma_threshold', 1.5)
        self.warmup_ticks    = getattr(self, 'warmup_ticks',    30)

        # Per-symbol VWAP state: cumulative price*volume and volume, plus Welford variance
        self._cum_pv:     dict[str, float] = {}   # sum(price * volume)
        self._cum_vol:    dict[str, float] = {}   # sum(volume)
        self._welford:    dict[str, dict]  = {}   # rolling price variance
        self._ticks:      dict[str, int]   = {}
        self._last_date:  dict[str, int]   = {}   # day-of-year to detect session reset
        self._last_signal: dict[str, str]  = {}

    def _reset_session(self, symbol: str, price: float) -> None:
        self._cum_pv[symbol]     = price
        self._cum_vol[symbol]    = 1.0
        self._welford[symbol]    = {"count": 0, "mean": 0.0, "M2": 0.0}
        self._ticks[symbol]      = 0
        self._last_signal[symbol] = "NONE"

    def _update(self, symbol: str, price: float, volume: float = 1.0) -> None:
        now = datetime.now(ET)
        day = now.timetuple().tm_yday
        if symbol not in self._last_date or self._last_date[symbol] != day:
            self._reset_session(symbol, price)
            self._last_date[symbol] = day
            return

        self._ticks[symbol] += 1
        v = volume if volume > 0 else 1.0
        self._cum_pv[symbol]  += price * v
        self._cum_vol[symbol] += v

        w = self._welford[symbol]
        w["count"] += 1
        d = price - w["mean"]
        w["mean"] += d / w["count"]
        w["M2"]   += d * (price - w["mean"])

    async def aanalyze(self, symbol: str, price: float, volume: float = 1.0) -> dict | None:
        if not _is_market_hours():
            return None

        self._update(symbol, price, volume)

        if self._ticks.get(symbol, 0) < self.warmup_ticks:
            return None

        w    = self._welford[symbol]
        vwap = self._cum_pv[symbol] / max(self._cum_vol[symbol], 1e-9)
        std  = math.sqrt(max(0.0, w["M2"] / w["count"])) if w["count"] > 0 else 0.0

        if std < 1e-9:
            return None

        z = (price - vwap) / std

        signal = None
        if z < -self.sigma_threshold and self._last_signal.get(symbol) != "BUY" and self._is_flat(symbol):
            self._last_signal[symbol] = "BUY"
            conf = min(0.93, 0.65 + abs(z) * 0.06)
            self.signal_count += 1
            signal = {
                "bot": self.id, "symbol": symbol, "action": "BUY",
                "confidence": round(conf, 3), "price": price,
                "meta": {"vwap": round(vwap, 4), "z_score": round(z, 3), "std": round(std, 4)},
            }
        elif z > self.sigma_threshold and self._last_signal.get(symbol) != "SELL" and self._is_long(symbol):
            self._last_signal[symbol] = "SELL"
            conf = min(0.93, 0.65 + abs(z) * 0.06)
            self.signal_count += 1
            signal = {
                "bot": self.id, "symbol": symbol, "action": "SELL",
                "confidence": round(conf, 3), "price": price,
                "meta": {"vwap": round(vwap, 4), "z_score": round(z, 3), "std": round(std, 4)},
            }

        if signal:
            logger.info("[VWAP-REV] %s → %s (z=%.2f, vwap=%.4f, conf=%.2f)",
                        symbol, signal["action"], z, vwap, signal["confidence"])
        return signal

    def get_state(self, symbol: str) -> dict | None:
        if symbol not in self._ticks:
            return None
        vwap = (self._cum_pv.get(symbol, 0) /
                max(self._cum_vol.get(symbol, 1e-9), 1e-9))
        w = self._welford.get(symbol, {})
        std = math.sqrt(max(0.0, w.get("M2", 0) / w["count"])) if w.get("count", 0) > 0 else 0.0
        return {
            "strategy": self.id,
            "name": self.name,
            "asset_class": self.asset_class,
            "vwap": round(vwap, 4),
            "std": round(std, 4),
            "ticks": self._ticks.get(symbol, 0),
            "position_state": self._position_state.get(symbol, FLAT),
            "market_hours": _is_market_hours(),
        }
