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

    def __init__(self, bot_id: str, name: str, allocation: int, algo_type: str):
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

    def analyze(self, symbol: str, price: float) -> dict | None:
        """Must be overridden by child classes to emit signal dicts."""
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

    def __init__(self, bot_id="momentum-alpha", name="Momentum α", allocation=40):
        super().__init__(bot_id, name, allocation, "EMA Crossover")
        self.ema_short: dict[str, float] = {}
        self.ema_long:  dict[str, float] = {}
        self._last_cross: dict[str, str] = {}  # prevents duplicate signals

    def analyze(self, symbol: str, price: float) -> dict | None:
        if symbol not in self.ema_short:
            self.ema_short[symbol] = price
            self.ema_long[symbol]  = price
            self._last_cross[symbol] = "NONE"
            return None

        self.ema_short[symbol] = (price * 0.20) + (self.ema_short[symbol] * 0.80)
        self.ema_long[symbol]  = (price * 0.05) + (self.ema_long[symbol]  * 0.95)

        short = self.ema_short[symbol]
        long_ = self.ema_long[symbol]
        spread = (short - long_) / long_  # positive = bullish

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
    """

    WINDOW = 20

    def __init__(self, bot_id="statarb-gamma", name="StatArb γ", allocation=35):
        super().__init__(bot_id, name, allocation, "Bollinger Band")
        self._prices: dict[str, deque] = {}
        self._last_signal: dict[str, str] = {}

    def _bollinger(self, prices: deque) -> tuple[float, float, float]:
        """Returns (sma, upper_band, lower_band)."""
        n = len(prices)
        sma = sum(prices) / n
        variance = sum((p - sma) ** 2 for p in prices) / n
        sigma = math.sqrt(variance)
        return sma, sma + 2 * sigma, sma - 2 * sigma

    def analyze(self, symbol: str, price: float) -> dict | None:
        if symbol not in self._prices:
            self._prices[symbol] = deque(maxlen=self.WINDOW)
            self._last_signal[symbol] = "NONE"

        self._prices[symbol].append(price)

        # Need full window before emitting signals
        if len(self._prices[symbol]) < self.WINDOW:
            return None

        sma, upper, lower = self._bollinger(self._prices[symbol])

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
        sma, upper, lower = self._bollinger(self._prices[symbol])
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

    def __init__(self, bot_id="hft-sniper", name="HFT Sniper", allocation=25):
        super().__init__(bot_id, name, allocation, "Micro-Scalp Momentum")
        self._prices: dict[str, deque] = {}
        self._cooldown: dict[str, int] = {}   # ticks since last signal
        self._entry_price: dict[str, float] = {}  # entry price for stop-loss tracking

    def analyze(self, symbol: str, price: float) -> dict | None:
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

        prices_list = list(self._prices[symbol])
        prev = prices_list[0]
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
        prices_list = list(self._prices[symbol])
        prev = prices_list[0]
        current = prices_list[-1]
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
