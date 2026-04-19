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

        # momentum_z: normalise EMA spread to a rough z-score (0.5% spread ≈ 1σ typical)
        momentum_z = round(max(-4.0, min(4.0, spread / 0.005)), 4)

        signal = None
        if spread > 0.002 and self._last_cross.get(symbol) != "BUY" and self._is_flat(symbol):
            self._last_cross[symbol] = "BUY"
            confidence = min(0.99, 0.70 + abs(spread) * 10)
            signal = {
                "bot": self.id, "symbol": symbol, "action": "BUY",
                "confidence": round(confidence, 3), "price": price,
                "meta": {
                    "ema_short": round(short, 2), "ema_long": round(long_, 2),
                    "spread_pct": round(spread * 100, 4), "momentum_z": momentum_z,
                }
            }
        elif spread < -0.002 and self._last_cross.get(symbol) != "SELL" and self._is_long(symbol):
            self._last_cross[symbol] = "SELL"
            confidence = min(0.99, 0.70 + abs(spread) * 10)
            signal = {
                "bot": self.id, "symbol": symbol, "action": "SELL",
                "confidence": round(confidence, 3), "price": price,
                "meta": {
                    "ema_short": round(short, 2), "ema_long": round(long_, 2),
                    "spread_pct": round(spread * 100, 4), "momentum_z": momentum_z,
                }
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
        # Patchable by PortfolioDirector — use these names in UPDATE_STRATEGY_PARAMS
        self.lookback_period  = getattr(self, 'lookback_period', 20)   # Bollinger Band window (bars)
        self.sigma_multiplier = getattr(self, 'sigma_multiplier', 2.0) # Band width in standard deviations
        self.WINDOW = self.lookback_period  # internal alias kept for legacy references
        self._prices: dict[str, deque] = {}
        self._welford: dict[str, dict] = {} # Tracks count, mean, M2 for O(1) variance
        self._last_signal: dict[str, str] = {}

    def update_params(self, params: dict) -> None:
        """Extends BaseStrategy.update_params to sync lookback_period → WINDOW and reset state."""
        super().update_params(params)
        if 'lookback_period' in params:
            self.WINDOW = int(self.lookback_period)
            # Clear per-symbol state so deques are recreated with the new maxlen on next tick
            self._prices.clear()
            self._welford.clear()
            self._last_signal.clear()
            logger.info("[%s] Bollinger window reset to %d bars (state cleared)", self.name, self.WINDOW)

    def _bollinger(self, symbol: str) -> tuple[float, float, float]:
        """Returns (sma, upper_band, lower_band) from O(1) Welford state."""
        w = self._welford[symbol]
        mean = w["mean"]
        variance = w["M2"] / w["count"] if w["count"] > 0 else 0
        sigma = math.sqrt(max(0.0, variance))
        k = self.sigma_multiplier
        return mean, mean + k * sigma, mean - k * sigma

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
        band_width = upper - lower if upper != lower else 1.0
        bb_pos = round(max(0.0, min(1.0, (price - lower) / band_width)), 4)
        variance = w["M2"] / w["count"] if w["count"] > 0 else 0.0
        sigma = math.sqrt(max(0.0, variance))
        mom_z = round(max(-4.0, min(4.0, (price - sma) / sigma)) if sigma > 0 else 0.0, 4)

        if price < lower and self._last_signal.get(symbol) != "BUY" and self._is_flat(symbol):
            deviation_sigma = (lower - price) / max((upper - lower) / 4, 0.001)
            confidence = min(0.95, 0.65 + deviation_sigma * 0.15)
            self._last_signal[symbol] = "BUY"
            signal = {
                "bot": self.id, "symbol": symbol, "action": "BUY",
                "confidence": round(confidence, 3), "price": price,
                "meta": {
                    "sma": round(sma, 2), "upper": round(upper, 2),
                    "lower": round(lower, 2), "deviation_σ": round(deviation_sigma, 3),
                    "bb_position": bb_pos, "momentum_z": mom_z,
                }
            }
        elif price > upper and self._last_signal.get(symbol) != "SELL" and self._is_long(symbol):
            deviation_sigma = (price - upper) / max((upper - lower) / 4, 0.001)
            confidence = min(0.95, 0.65 + deviation_sigma * 0.15)
            self._last_signal[symbol] = "SELL"
            signal = {
                "bot": self.id, "symbol": symbol, "action": "SELL",
                "confidence": round(confidence, 3), "price": price,
                "meta": {
                    "sma": round(sma, 2), "upper": round(upper, 2),
                    "lower": round(lower, 2), "deviation_σ": round(deviation_sigma, 3),
                    "bb_position": bb_pos, "momentum_z": mom_z,
                }
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


# ---------------------------------------------------------------------------
# Strategy 7: Crypto Pairs (generic spread mean-reversion, no market-hours gate)
# ---------------------------------------------------------------------------

class CryptoPairsStrategy(BaseStrategy):
    """
    Pairs mean-reversion for any two crypto symbols (e.g. BTC/ETH, SOL/AVAX).

    Identical math to EquityPairsStrategy but with asset_class = "CRYPTO" and
    no market-hours gate. leg_a and leg_b are fully patchable so the director
    can instantiate any cross-asset spread at runtime.

    Params (all patchable):
      leg_a        str    First leg symbol (default "BTC/USD")
      leg_b        str    Second leg symbol (default "ETH/USD")
      window       int    Rolling spread window (default 30)
      z_threshold  float  Z-score entry threshold (default 2.0)
    """

    def __init__(self, bot_id="crypto-pairs", name="Crypto Pairs", allocation=15, **kwargs):
        super().__init__(bot_id, name, allocation, "Pairs Mean Reversion", **kwargs)
        self.leg_a       = getattr(self, 'leg_a',       "BTC/USD")
        self.leg_b       = getattr(self, 'leg_b',       "ETH/USD")
        self.WINDOW      = getattr(self, 'window',      30)
        self.Z_THRESHOLD = getattr(self, 'z_threshold', 2.0)
        self._reset_pair_state()

    def _reset_pair_state(self) -> None:
        self._price_a: float | None = None
        self._price_b: float | None = None
        self._spreads  = deque(maxlen=self.WINDOW)
        self._welford  = {"count": 0, "mean": 0.0, "M2": 0.0}
        self._last_signal: str = "NONE"

    def update_params(self, params: dict) -> None:
        """Reset spread history when legs change."""
        legs_changed = "leg_a" in params or "leg_b" in params
        super().update_params(params)
        if legs_changed:
            self._reset_pair_state()
            logger.info("[%s] Pair legs changed → state reset (leg_a=%s, leg_b=%s)",
                        self.name, self.leg_a, self.leg_b)

    async def aanalyze(self, symbol: str, price: float) -> dict | None:
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

        if len(self._spreads) == self.WINDOW:
            old = self._spreads[0]
            w["count"] -= 1
            d = old - w["mean"]
            w["mean"] -= d / max(1, w["count"])
            w["M2"]   -= d * (old - w["mean"])

        self._spreads.append(spread)
        w["count"] += 1
        d = spread - w["mean"]
        w["mean"] += d / w["count"]
        w["M2"]   += d * (spread - w["mean"])

        if w["count"] < self.WINDOW or symbol != self.leg_a:
            return None

        std     = math.sqrt(w["M2"] / w["count"]) if w["M2"] > 0 else 1e-9
        z_score = (spread - w["mean"]) / std

        signal = None
        if z_score < -self.Z_THRESHOLD and self._last_signal != "BUY" and self._is_flat(self.leg_a):
            self._last_signal = "BUY"
            self.signal_count += 1
            signal = {
                "bot": self.id, "symbol": self.leg_a, "action": "BUY",
                "confidence": round(min(0.93, 0.65 + abs(z_score) * 0.08), 3), "price": price,
                "meta": {"z_score": round(z_score, 3), "spread": round(spread, 6)},
            }
        elif z_score > self.Z_THRESHOLD and self._last_signal != "SELL" and self._is_long(self.leg_a):
            self._last_signal = "SELL"
            self.signal_count += 1
            signal = {
                "bot": self.id, "symbol": self.leg_a, "action": "SELL",
                "confidence": round(min(0.93, 0.65 + abs(z_score) * 0.08), 3), "price": price,
                "meta": {"z_score": round(z_score, 3), "spread": round(spread, 6)},
            }

        if signal:
            logger.info("[CRYPTO-PAIRS] %s/%s z=%.2f → %s (conf=%.2f)",
                        self.leg_a, self.leg_b, z_score, signal["action"], signal["confidence"])
        return signal

    def get_state(self, symbol: str) -> dict | None:
        if symbol not in (self.leg_a, self.leg_b):
            return None
        w = self._welford
        z_score = None
        if w["count"] >= self.WINDOW and w["M2"] > 0:
            z_score = round((self._spreads[-1] - w["mean"]) / math.sqrt(w["M2"] / w["count"]), 3)
        return {
            "strategy": self.id, "name": self.name,
            "leg_a": self.leg_a, "leg_b": self.leg_b,
            "price_a": self._price_a, "price_b": self._price_b,
            "z_score": z_score,
            "ticks_collected": w["count"],
            "position_state": self._position_state.get(self.leg_a, FLAT),
        }


# ---------------------------------------------------------------------------
# Strategy 8: News Momentum (short-burst directional bet, research-edge gated)
# ---------------------------------------------------------------------------

class NewsMomentumStrategy(BaseStrategy):
    """
    Short-burst directional bet activated when the ResearchAgent reports a
    high edge (model_probability − market_implied_probability) for this symbol.

    Logic:
      - BUY  when momentum_ticks-tick momentum is positive AND research edge > threshold
      - Forced close (SELL) after hold_limit_ticks regardless of P&L
      - Edge check delegates to an injected callable so this class stays stateless
        with respect to the research brief.

    Params (all patchable via update_params):
      edge_threshold   float   Minimum edge to allow entry (default 0.06)
      momentum_ticks   int     Rolling tick window for directional confirmation (default 5)
      hold_limit_ticks int     Max ticks to hold before forced exit (default 30)
    """

    def __init__(self, bot_id="news-momentum", name="News Momentum", allocation=15, **kwargs):
        super().__init__(bot_id, name, allocation, "News Momentum", **kwargs)
        self.edge_threshold   = getattr(self, 'edge_threshold',   0.06)
        self.momentum_ticks   = getattr(self, 'momentum_ticks',   5)
        self.hold_limit_ticks = getattr(self, 'hold_limit_ticks', 30)

        self._prices:     dict[str, deque] = {}
        self._hold_count: dict[str, int]   = {}   # ticks since entry (forced exit guard)
        # Callable injected by engine: (symbol) -> float | None (returns edge or None)
        self._get_edge:   dict[str, float] = {}   # edge cache, populated externally

    def set_edge(self, symbol: str, edge: float) -> None:
        """Called by engine/director after each research cycle to update edge cache."""
        self._get_edge[symbol] = edge

    async def aanalyze(self, symbol: str, price: float) -> dict | None:
        if symbol not in self._prices:
            self._prices[symbol]     = deque(maxlen=self.momentum_ticks + 1)
            self._hold_count[symbol] = 0

        self._prices[symbol].append(price)

        # Forced exit: position held too long
        if self._is_long(symbol):
            self._hold_count[symbol] += 1
            if self._hold_count[symbol] >= self.hold_limit_ticks:
                self._hold_count[symbol] = 0
                self.signal_count += 1
                logger.info("[NEWS-MOM] Forced close %s after %d ticks", symbol, self.hold_limit_ticks)
                return {
                    "bot": self.id, "symbol": symbol, "action": "SELL",
                    "confidence": 0.80, "price": price,
                    "meta": {"trigger": "hold_limit", "hold_ticks": self.hold_limit_ticks},
                }

        if len(self._prices[symbol]) < self.momentum_ticks + 1:
            return None

        edge = self._get_edge.get(symbol, 0.0)
        if abs(edge) < self.edge_threshold:
            return None

        prev = self._prices[symbol][0]
        momentum = (price - prev) / prev if prev else 0.0

        signal = None
        if edge > self.edge_threshold and momentum > 0 and self._is_flat(symbol):
            confidence = min(0.95, 0.65 + edge * 3)
            self._hold_count[symbol] = 0
            self.signal_count += 1
            signal = {
                "bot": self.id, "symbol": symbol, "action": "BUY",
                "confidence": round(confidence, 3), "price": price,
                "meta": {"edge": round(edge, 4), "momentum_pct": round(momentum * 100, 4)},
            }
        elif edge < -self.edge_threshold and momentum < 0 and self._is_long(symbol):
            confidence = min(0.95, 0.65 + abs(edge) * 3)
            self._hold_count[symbol] = 0
            self.signal_count += 1
            signal = {
                "bot": self.id, "symbol": symbol, "action": "SELL",
                "confidence": round(confidence, 3), "price": price,
                "meta": {"edge": round(edge, 4), "momentum_pct": round(momentum * 100, 4)},
            }

        if signal:
            logger.info("[NEWS-MOM] %s → %s (edge=%.3f, conf=%.2f)",
                        symbol, signal["action"], edge, signal["confidence"])
        return signal

    def get_state(self, symbol: str) -> dict | None:
        return {
            "strategy": self.id,
            "name": self.name,
            "edge": round(self._get_edge.get(symbol, 0.0), 4),
            "hold_ticks": self._hold_count.get(symbol, 0),
            "position_state": self._position_state.get(symbol, FLAT),
        }


# ---------------------------------------------------------------------------
# Strategy 8: Crypto Range Scalp (tight Bollinger scalp for consolidating crypto)
# ---------------------------------------------------------------------------

class CryptoRangeScalpStrategy(BaseStrategy):
    """
    Bollinger Band scalp intended for crypto in sideways/consolidating regimes.
    Differs from StatArb Gamma by using tighter bands (1.5σ) and a regime gate:
    entry is only allowed when the last min_range_ticks ticks show no EMA crossover
    (i.e., asset is range-bound, not trending).

    Params (all patchable):
      bb_period        int    Bollinger window (default 20)
      bb_sigma         float  Band width in σ (default 1.5)
      min_range_ticks  int    Ticks without EMA crossover required (default 10)
      cooldown_ticks   int    Ticks to wait after a signal (default 8)
    """

    def __init__(self, bot_id="crypto-range-scalp", name="Crypto Range Scalp", allocation=20, **kwargs):
        super().__init__(bot_id, name, allocation, "Range Scalp", **kwargs)
        self.bb_period       = getattr(self, 'bb_period',       20)
        self.bb_sigma        = getattr(self, 'bb_sigma',        1.5)
        self.min_range_ticks = getattr(self, 'min_range_ticks', 10)
        self.cooldown_ticks  = getattr(self, 'cooldown_ticks',  8)

        self._prices:       dict[str, deque] = {}
        self._welford:      dict[str, dict]  = {}
        self._ema_fast:     dict[str, float] = {}  # α=0.10
        self._ema_slow:     dict[str, float] = {}  # α=0.03
        self._range_ticks:  dict[str, int]   = {}  # consecutive non-crossover ticks
        self._cooldown:     dict[str, int]   = {}
        self._last_signal:  dict[str, str]   = {}

    async def aanalyze(self, symbol: str, price: float) -> dict | None:
        if symbol not in self._prices:
            self._prices[symbol]      = deque(maxlen=self.bb_period)
            self._welford[symbol]     = {"count": 0, "mean": 0.0, "M2": 0.0}
            self._ema_fast[symbol]    = price
            self._ema_slow[symbol]    = price
            self._range_ticks[symbol] = 0
            self._cooldown[symbol]    = 0
            self._last_signal[symbol] = "NONE"
            return None

        self._cooldown[symbol] = max(0, self._cooldown[symbol] - 1)

        # Update EMAs for regime detection
        self._ema_fast[symbol] = price * 0.10 + self._ema_fast[symbol] * 0.90
        self._ema_slow[symbol] = price * 0.03 + self._ema_slow[symbol] * 0.97
        trending = abs(self._ema_fast[symbol] - self._ema_slow[symbol]) / self._ema_slow[symbol] > 0.002
        self._range_ticks[symbol] = 0 if trending else self._range_ticks[symbol] + 1

        # Welford rolling variance
        w = self._welford[symbol]
        if len(self._prices[symbol]) == self.bb_period:
            old = self._prices[symbol][0]
            w["count"] -= 1
            d = old - w["mean"]
            w["mean"] -= d / max(1, w["count"])
            w["M2"]   -= d * (old - w["mean"])
            w["M2"]    = max(0.0, w["M2"])

        self._prices[symbol].append(price)
        w["count"] += 1
        d = price - w["mean"]
        w["mean"] += d / w["count"]
        w["M2"]   += d * (price - w["mean"])

        if w["count"] < self.bb_period:
            return None
        if self._range_ticks[symbol] < self.min_range_ticks:
            return None
        if self._cooldown[symbol] > 0:
            return None

        sigma = math.sqrt(max(0.0, w["M2"] / w["count"]))
        upper = w["mean"] + self.bb_sigma * sigma
        lower = w["mean"] - self.bb_sigma * sigma

        signal = None
        if price < lower and self._last_signal[symbol] != "BUY" and self._is_flat(symbol):
            dev = (lower - price) / max(sigma, 1e-9)
            self._last_signal[symbol] = "BUY"
            self._cooldown[symbol] = self.cooldown_ticks
            self.signal_count += 1
            signal = {
                "bot": self.id, "symbol": symbol, "action": "BUY",
                "confidence": round(min(0.92, 0.62 + dev * 0.10), 3), "price": price,
                "meta": {"upper": round(upper, 4), "lower": round(lower, 4),
                         "range_ticks": self._range_ticks[symbol]},
            }
        elif price > upper and self._last_signal[symbol] != "SELL" and self._is_long(symbol):
            dev = (price - upper) / max(sigma, 1e-9)
            self._last_signal[symbol] = "SELL"
            self._cooldown[symbol] = self.cooldown_ticks
            self.signal_count += 1
            signal = {
                "bot": self.id, "symbol": symbol, "action": "SELL",
                "confidence": round(min(0.92, 0.62 + dev * 0.10), 3), "price": price,
                "meta": {"upper": round(upper, 4), "lower": round(lower, 4),
                         "range_ticks": self._range_ticks[symbol]},
            }

        if signal:
            logger.info("[RANGE-SCALP] %s → %s (conf=%.2f, range_ticks=%d)",
                        symbol, signal["action"], signal["confidence"], self._range_ticks[symbol])
        return signal

    def get_state(self, symbol: str) -> dict | None:
        if symbol not in self._welford:
            return None
        w = self._welford[symbol]
        sigma = math.sqrt(max(0.0, w["M2"] / w["count"])) if w["count"] > 0 else 0
        return {
            "strategy": self.id,
            "name": self.name,
            "mean": round(w["mean"], 4),
            "sigma": round(sigma, 4),
            "range_ticks": self._range_ticks.get(symbol, 0),
            "cooldown_remaining": self._cooldown.get(symbol, 0),
            "position_state": self._position_state.get(symbol, FLAT),
        }
