"""
Trading Strategy Algorithms
============================
Three distinct algorithmic strategies for CRYPTO assets, each implementing a different
trading paradigm. All strategies are stateful (maintain rolling windows in memory) and
are designed to be called on every price tick.

Position-state tracking: each strategy tracks a per-symbol position state (FLAT/LONG)
to prevent naked SELL signals when no position is held.

Signal schema emitted by analyze():
  {
    "bot": str,           # strategy bot_id
    "symbol": str,        # e.g. "BTC/USD"
    "action": str,        # "BUY" or "SELL"
    "confidence": float,  # 0.0–1.0
    "price": float,       # signal trigger price (for slippage reference)
    "meta": dict          # strategy-specific diagnostic values
  }
"""

import math
import logging
from collections import deque

logger = logging.getLogger(__name__)

# Position states
FLAT = "FLAT"
LONG = "LONG"


class BaseStrategy:
    asset_class: str = "CRYPTO"  # Override in equity/options subclasses

    def __init__(self, bot_id: str, name: str, allocation: int, algo_type: str, **kwargs):
        self.id = bot_id
        self.name = name
        self.allocation = allocation
        self.algo = algo_type
        self.status = "ACTIVE" if allocation > 0 else "HALTED"
        self.yield24h = 0.0
        self.signal_count = 0
        self.fill_count = 0
        # Per-symbol position state: FLAT means no position held
        self._position_state: dict[str, str] = {}
        
        # Allow dynamic parameter overriding from the Portfolio Director
        for k, v in kwargs.items():
            setattr(self, k, v)

    async def aanalyze(self, symbol: str, price: float) -> dict | None:
        """Asynchronous analysis pipeline to prevent event loop blocking."""
        return None

    def get_state(self, symbol: str) -> dict | None:
        """Returns current indicator state for reflection engine. Override per strategy."""
        return None

    def record_fill(self, pnl_delta: float):
        """Called by ExecutionAgent on confirmed fill to update 24h yield."""
        self.yield24h = round(self.yield24h + pnl_delta, 4)
        self.fill_count += 1

    def notify_fill(self, symbol: str, action: str):
        """Called by the execution pipeline after a confirmed fill to update position state."""
        if action == "BUY":
            self._position_state[symbol] = LONG
        elif action == "SELL":
            self._position_state[symbol] = FLAT

    def _is_long(self, symbol: str) -> bool:
        return self._position_state.get(symbol, FLAT) == LONG

    def _is_flat(self, symbol: str) -> bool:
        return self._position_state.get(symbol, FLAT) == FLAT

    def update_params(self, params: dict) -> None:
        """Safely mutate strategy configuration at runtime (called by AutonomousPortfolioDirector).
        Only updates attributes that already exist on the instance."""
        for key, val in params.items():
            if hasattr(self, key):
                setattr(self, key, val)
                logger.info("[%s] param updated: %s = %s", self.name, key, val)
            else:
                logger.warning("[%s] update_params: unknown param %s (skipped)", self.name, key)


# ---------------------------------------------------------------------------
# Strategy 1: Momentum Alpha (EMA Crossover)
# ---------------------------------------------------------------------------

class MomentumStrategy(BaseStrategy):
    """
    Dual-EMA crossover strategy.

    - EMA-short (α=0.20, approx 9-period): fast signal line
    - EMA-long  (α=0.05, approx 39-period): slow trend anchor

    Signal logic:
      BUY  when short_ema crosses above long_ema by > 0.2% AND position is FLAT
      SELL when short_ema crosses below long_ema by > 0.2% AND position is LONG

    Confidence is scaled by the magnitude of the crossover spread.
    """

    def __init__(self, bot_id="momentum-alpha", name="Momentum α", allocation=40, **kwargs):
        super().__init__(bot_id, name, allocation, "EMA Crossover", **kwargs)
        self.ema_short: dict[str, float] = {}
        self.ema_long:  dict[str, float] = {}
        self._ticks: dict[str, int] = {}
        self._last_cross: dict[str, str] = {}
        
        self.alpha_short = getattr(self, 'alpha_short', 0.20)
        self.alpha_long = getattr(self, 'alpha_long', 0.05)
        self.warmup_ticks = getattr(self, 'warmup_ticks', 40)

    async def aanalyze(self, symbol: str, price: float) -> dict | None:
        if symbol not in self.ema_short:
            self.ema_short[symbol] = price
            self.ema_long[symbol]  = price
            self._ticks[symbol] = 1
            self._last_cross[symbol] = "NONE"
            return None

        self._ticks[symbol] += 1
        self.ema_short[symbol] = (price * self.alpha_short) + (self.ema_short[symbol] * (1 - self.alpha_short))
        self.ema_long[symbol]  = (price * self.alpha_long) + (self.ema_long[symbol]  * (1 - self.alpha_long))

        # CRITICAL FIX: Require warmup period for EMA convergence
        if self._ticks[symbol] < self.warmup_ticks:
            return None

        short = self.ema_short[symbol]
        long_ = self.ema_long[symbol]
        spread = (short - long_) / long_

        signal = None
        if spread > 0.002 and self._last_cross.get(symbol) != "BUY" and self._is_flat(symbol):
            self._last_cross[symbol] = "BUY"
            confidence = min(0.99, 0.70 + abs(spread) * 10)
            signal = {
                "bot": self.id, "symbol": symbol, "action": "BUY",
                "confidence": round(confidence, 3), "price": price,
                "meta": {"ema_short": round(short, 2), "ema_long": round(long_, 2), "spread_pct": round(spread * 100, 4)}
            }
        elif spread < -0.002 and self._last_cross.get(symbol) != "SELL" and self._is_long(symbol):
            self._last_cross[symbol] = "SELL"
            confidence = min(0.99, 0.70 + abs(spread) * 10)
            signal = {
                "bot": self.id, "symbol": symbol, "action": "SELL",
                "confidence": round(confidence, 3), "price": price,
                "meta": {"ema_short": round(short, 2), "ema_long": round(long_, 2), "spread_pct": round(spread * 100, 4)}
            }

        if signal:
            self.signal_count += 1
            logger.debug("[MOMENTUM] %s → %s (conf=%.2f, spread=%.4f%%)",
                         symbol, signal["action"], signal["confidence"], spread * 100)
        return signal

    def get_state(self, symbol: str) -> dict | None:
        if symbol not in self.ema_short:
            return None
        short = self.ema_short[symbol]
        long_ = self.ema_long[symbol]
        spread = (short - long_) / long_ if long_ else 0
        bias = "BULLISH" if spread > 0 else "BEARISH" if spread < -0.001 else "NEUTRAL"
        return {
            "strategy": self.id,
            "name": self.name,
            "ema_short": round(short, 2),
            "ema_long": round(long_, 2),
            "spread_pct": round(spread * 100, 4),
            "bias": bias,
            "last_cross": self._last_cross.get(symbol, "NONE"),
            "position_state": self._position_state.get(symbol, FLAT),
            "near_crossover": abs(spread) < 0.003,
        }


# ---------------------------------------------------------------------------
# Strategy 2: StatArb Gamma (Bollinger Band Mean Reversion)
# ---------------------------------------------------------------------------

class StatArbStrategy(BaseStrategy):
    """
    Bollinger Band mean-reversion strategy on a single asset.

    Maintains a rolling 20-period price buffer. Computes:
      - SMA-20 (rolling mean)
      - σ-20   (rolling std dev)
      - Upper band = SMA + 2σ
      - Lower band = SMA - 2σ

    Signal logic:
      BUY  when price < lower band AND position is FLAT
      SELL when price > upper band AND position is LONG

    Confidence is proportional to how far price has deviated beyond the band:
      conf = 0.65 + min(0.30, deviation_σ * 0.15)

    Variance is tracked via Welford's sliding-window algorithm (O(1) per tick).
    """

    def __init__(self, bot_id="statarb-gamma", name="StatArb γ", allocation=35, **kwargs):
        super().__init__(bot_id, name, allocation, "Bollinger Band", **kwargs)
        self.WINDOW = getattr(self, 'window', 20)
        self._prices: dict[str, deque] = {}
        self._welford: dict[str, dict] = {} # Tracks count, mean, M2 for O(1) variance
        self._last_signal: dict[str, str] = {}

    def _bollinger(self, symbol: str) -> tuple[float, float, float]:
        """Returns (sma, upper_band, lower_band) from O(1) Welford state."""
        w = self._welford[symbol]
        mean = w["mean"]
        variance = w["M2"] / w["count"] if w["count"] > 0 else 0
        sigma = math.sqrt(max(0.0, variance))
        return mean, mean + 2 * sigma, mean - 2 * sigma

    async def aanalyze(self, symbol: str, price: float) -> dict | None:
        if symbol not in self._prices:
            self._prices[symbol] = deque(maxlen=self.WINDOW)
            self._welford[symbol] = {"count": 0, "mean": 0.0, "M2": 0.0}
            self._last_signal[symbol] = "NONE"

        prices = self._prices[symbol]
        w = self._welford[symbol]

        # Welford's Algorithm: Remove old price effect if window is full
        if len(prices) == self.WINDOW:
            old_price = prices[0]
            w["count"] -= 1
            delta = old_price - w["mean"]
            w["mean"] -= delta / max(1, w["count"])
            w["M2"] -= delta * (old_price - w["mean"])
            w["M2"] = max(0.0, w["M2"])

        # Add new price
        prices.append(price)
        w["count"] += 1
        delta = price - w["mean"]
        w["mean"] += delta / w["count"]
        w["M2"] += delta * (price - w["mean"])

        if w["count"] < self.WINDOW:
            return None

        sma, upper, lower = self._bollinger(symbol)

        signal = None
        if price < lower and self._last_signal.get(symbol) != "BUY" and self._is_flat(symbol):
            deviation_sigma = (lower - price) / max((upper - lower) / 4, 0.001)
            confidence = min(0.95, 0.65 + deviation_sigma * 0.15)
            self._last_signal[symbol] = "BUY"
            signal = {
                "bot": self.id, "symbol": symbol, "action": "BUY",
                "confidence": round(confidence, 3), "price": price,
                "meta": {"sma": round(sma, 2), "upper": round(upper, 2),
                         "lower": round(lower, 2), "deviation_σ": round(deviation_sigma, 3)}
            }
        elif price > upper and self._last_signal.get(symbol) != "SELL" and self._is_long(symbol):
            deviation_sigma = (price - upper) / max((upper - lower) / 4, 0.001)
            confidence = min(0.95, 0.65 + deviation_sigma * 0.15)
            self._last_signal[symbol] = "SELL"
            signal = {
                "bot": self.id, "symbol": symbol, "action": "SELL",
                "confidence": round(confidence, 3), "price": price,
                "meta": {"sma": round(sma, 2), "upper": round(upper, 2),
                         "lower": round(lower, 2), "deviation_σ": round(deviation_sigma, 3)}
            }

        if signal:
            self.signal_count += 1
            logger.debug("[STATARB] %s → %s (conf=%.2f, sma=%.2f, band=[%.2f, %.2f])",
                         symbol, signal["action"], signal["confidence"], sma, lower, upper)
        return signal

    def get_state(self, symbol: str) -> dict | None:
        if symbol not in self._prices or len(self._prices[symbol]) < self.WINDOW:
            return {"strategy": self.id, "name": self.name, "status": "warming_up",
                    "ticks_collected": len(self._prices.get(symbol, []))}
        sma, upper, lower = self._bollinger(symbol)
        price = self._prices[symbol][-1]
        band_width = upper - lower if upper != lower else 1
        position_pct = round((price - lower) / band_width * 100, 1)
        zone = "OVERSOLD" if position_pct < 10 else "OVERBOUGHT" if position_pct > 90 else "NEUTRAL"
        return {
            "strategy": self.id,
            "name": self.name,
            "sma": round(sma, 2),
            "upper_band": round(upper, 2),
            "lower_band": round(lower, 2),
            "position_in_band_pct": position_pct,
            "zone": zone,
            "position_state": self._position_state.get(symbol, FLAT),
            "last_signal": self._last_signal.get(symbol, "NONE"),
        }


# ---------------------------------------------------------------------------
# Strategy 3: HFT Sniper (Micro-Scalp Momentum)
# ---------------------------------------------------------------------------

class HighFrequencyStrategy(BaseStrategy):
    """
    High-frequency micro-scalp strategy based on tick-by-tick momentum.

    Tracks last N prices per symbol. Signal logic:
      - Compute the rolling 3-tick momentum: (current - prev3) / prev3
      - If momentum > +THRESHOLD AND position is FLAT → BUY
      - If momentum < -THRESHOLD AND position is LONG → SELL
      - Stop-loss: if price moves 0.5% against entry → forced SELL
      - Fires at most once per COOLDOWN ticks per symbol (rate-limit)

    Starts ACTIVE with 25% allocation. Position-aware to prevent naked SELLs.
    """

    MOMENTUM_WINDOW = 3            # look-back ticks
    MOMENTUM_THRESHOLD = 0.0003   # 0.03% move in 3 ticks triggers signal
    COOLDOWN_TICKS = 5             # minimum ticks between signals per symbol
    STOP_LOSS_PCT = 0.005          # 0.5% adverse move forces SELL exit

    def __init__(self, bot_id="hft-sniper", name="HFT Sniper", allocation=25, **kwargs):
        super().__init__(bot_id, name, allocation, "Micro-Scalp Momentum", **kwargs)
        self._prices: dict[str, deque] = {}
        self._cooldown: dict[str, int] = {}   # ticks since last signal
        self._entry_price: dict[str, float] = {}  # entry price for stop-loss tracking

    async def aanalyze(self, symbol: str, price: float) -> dict | None:
        if symbol not in self._prices:
            self._prices[symbol] = deque(maxlen=self.MOMENTUM_WINDOW + 1)
            self._cooldown[symbol] = 0

        self._prices[symbol].append(price)
        self._cooldown[symbol] = max(0, self._cooldown[symbol] - 1)

        if len(self._prices[symbol]) < self.MOMENTUM_WINDOW + 1:
            return None

        # -- Stop-loss check (fires even during cooldown) --
        if self._is_long(symbol) and symbol in self._entry_price:
            entry = self._entry_price[symbol]
            adverse_move = (entry - price) / entry  # positive = price fell
            if adverse_move >= self.STOP_LOSS_PCT:
                self._cooldown[symbol] = self.COOLDOWN_TICKS
                self.signal_count += 1
                logger.warning("[HFT] STOP-LOSS triggered on %s: entry=%.4f current=%.4f move=%.3f%%",
                               symbol, entry, price, adverse_move * 100)
                return {
                    "bot": self.id, "symbol": symbol, "action": "SELL",
                    "confidence": 0.99, "price": price,
                    "meta": {"trigger": "stop_loss", "entry_price": round(entry, 4),
                             "adverse_move_pct": round(adverse_move * 100, 4)}
                }

        if self._cooldown[symbol] > 0:
            return None

        # Fix: O(1) deque access instead of O(N) list conversion
        prev = self._prices[symbol][0]
        momentum = (price - prev) / prev if prev != 0 else 0.0

        signal = None
        if momentum > self.MOMENTUM_THRESHOLD and self._is_flat(symbol):
            confidence = min(0.92, 0.60 + abs(momentum) * 500)
            signal = {
                "bot": self.id, "symbol": symbol, "action": "BUY",
                "confidence": round(confidence, 3), "price": price,
                "meta": {"momentum_pct": round(momentum * 100, 5),
                         "window_ticks": self.MOMENTUM_WINDOW}
            }
            self._cooldown[symbol] = self.COOLDOWN_TICKS

        elif momentum < -self.MOMENTUM_THRESHOLD and self._is_long(symbol):
            confidence = min(0.92, 0.60 + abs(momentum) * 500)
            signal = {
                "bot": self.id, "symbol": symbol, "action": "SELL",
                "confidence": round(confidence, 3), "price": price,
                "meta": {"momentum_pct": round(momentum * 100, 5),
                         "window_ticks": self.MOMENTUM_WINDOW}
            }
            self._cooldown[symbol] = self.COOLDOWN_TICKS

        if signal:
            self.signal_count += 1
            logger.debug("[HFT] %s → %s (conf=%.2f, momentum=%.5f%%)",
                         symbol, signal["action"], signal["confidence"], momentum * 100)
        return signal

    def notify_fill(self, symbol: str, action: str):
        """Override to also track entry price for stop-loss."""
        super().notify_fill(symbol, action)
        # Entry price is set externally by the execution pipeline via set_entry_price()
        if action == "SELL" and symbol in self._entry_price:
            del self._entry_price[symbol]

    def set_entry_price(self, symbol: str, price: float):
        """Called by execution pipeline after a confirmed BUY fill."""
        self._entry_price[symbol] = price

    def get_state(self, symbol: str) -> dict | None:
        if symbol not in self._prices or len(self._prices[symbol]) < self.MOMENTUM_WINDOW + 1:
            return {"strategy": self.id, "name": self.name, "status": self.status,
                    "warming_up": True}
        prev = self._prices[symbol][0]
        current = self._prices[symbol][-1]
        momentum = (current - prev) / prev if prev else 0
        entry = self._entry_price.get(symbol)
        return {
            "strategy": self.id,
            "name": self.name,
            "status": self.status,
            "momentum_pct": round(momentum * 100, 5),
            "cooldown_remaining": self._cooldown.get(symbol, 0),
            "position_state": self._position_state.get(symbol, FLAT),
            "entry_price": round(entry, 4) if entry else None,
        }
