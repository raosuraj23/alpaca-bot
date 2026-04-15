"""
Options Trading Strategy Algorithms
======================================
Two options strategy agents for US equity options.
All strategies enforce market-hours gating (9:30 AM - 4:00 PM ET, Mon-Fri)
and respect the MIN_DAYS_TO_EXPIRY = 5 rule from MASTER_INSTRUCTIONS.

Signal schema for options:
  {
    "bot": str,
    "symbol": str,           # underlying equity symbol (e.g. "AAPL")
    "action": str,           # "BUY_CALL" | "SELL_CALL" | "BUY_PUT" | "SELL_PUT"
    "confidence": float,
    "price": float,          # current underlying price
    "meta": {
      "strategy": str,       # "covered_call" | "protective_put"
      "strike": float,
      "expiry_days": int,
      "underlying_price": float,
      "otm_pct": float,
    }
  }

Actual Alpaca options order submission is handled by the execution agent;
these classes only emit intent signals.
"""

import logging
from collections import deque
from datetime import datetime, time
import zoneinfo

from strategy.algorithms import BaseStrategy, FLAT, LONG

logger = logging.getLogger(__name__)

ET = zoneinfo.ZoneInfo("America/New_York")
MARKET_OPEN  = time(9, 30)
MARKET_CLOSE = time(16, 0)
MIN_DAYS_TO_EXPIRY = 5   # MASTER_INSTRUCTIONS hard rule


def _is_market_hours() -> bool:
    now = datetime.now(ET)
    if now.weekday() >= 5:
        return False
    return MARKET_OPEN <= now.time() <= MARKET_CLOSE


def _target_expiry_days(min_dte: int = 21, preferred_dte: int = 30) -> int:
    return max(min_dte, MIN_DAYS_TO_EXPIRY + 1, preferred_dte)


# ---------------------------------------------------------------------------
# Strategy 7: Covered Call Writer
# ---------------------------------------------------------------------------

class CoveredCallStrategy(BaseStrategy):
    """
    Sells a covered call against an assumed underlying equity position.

    Signal logic (market hours only):
      - Computes dual-EMA spread and 14-period RSI on the underlying.
      - When regime is NEUTRAL-to-mild-BULLISH (EMA spread -0.5% to +0.3%)
        AND RSI is in fair range (45-68):
          Emit SELL_CALL at strike 4% OTM with ~30 DTE
      - Cooldown of 50 ticks between signals.

    One open call position tracked per symbol.
    Allocation: 5% portfolio margin reserve.
    """

    asset_class = "OPTIONS"
    EMA_ALPHA_SHORT = 0.15
    EMA_ALPHA_LONG  = 0.04
    RSI_PERIOD      = 14
    CALL_OTM_PCT    = 0.04
    MIN_RSI         = 45.0
    MAX_RSI         = 68.0
    COOLDOWN_TICKS  = 50

    def __init__(self, bot_id="covered-call", name="Covered Call Writer", allocation=5):
        super().__init__(bot_id, name, allocation, "Covered Call")
        self._ema_short:   dict[str, float] = {}
        self._ema_long:    dict[str, float] = {}
        self._prices:      dict[str, deque] = {}
        self._avg_gain:    dict[str, float] = {}
        self._avg_loss:    dict[str, float] = {}
        self._rsi:         dict[str, float] = {}
        self._rsi_init:    dict[str, bool]  = {}
        self._cooldown:    dict[str, int]   = {}
        self._call_open:   dict[str, bool]  = {}

    def _update_ema(self, symbol: str, price: float):
        if symbol not in self._ema_short:
            self._ema_short[symbol] = price
            self._ema_long[symbol]  = price
            return
        a_s, a_l = self.EMA_ALPHA_SHORT, self.EMA_ALPHA_LONG
        self._ema_short[symbol] = price * a_s + self._ema_short[symbol] * (1 - a_s)
        self._ema_long[symbol]  = price * a_l + self._ema_long[symbol]  * (1 - a_l)

    def _update_rsi(self, symbol: str, price: float):
        if symbol not in self._prices:
            self._prices[symbol]   = deque(maxlen=self.RSI_PERIOD + 1)
            self._rsi_init[symbol] = False
        self._prices[symbol].append(price)
        if len(self._prices[symbol]) < self.RSI_PERIOD + 1:
            return
        if not self._rsi_init[symbol]:
            changes = [self._prices[symbol][i+1] - self._prices[symbol][i]
                       for i in range(self.RSI_PERIOD)]
            self._avg_gain[symbol] = sum(c for c in changes if c > 0) / self.RSI_PERIOD
            self._avg_loss[symbol] = sum(abs(c) for c in changes if c < 0) / self.RSI_PERIOD
            self._rsi_init[symbol] = True
        else:
            pl = list(self._prices[symbol])
            change = pl[-1] - pl[-2]
            a = 1.0 / self.RSI_PERIOD
            self._avg_gain[symbol] = self._avg_gain[symbol] * (1 - a) + max(0.0, change) * a
            self._avg_loss[symbol] = self._avg_loss[symbol] * (1 - a) + max(0.0, -change) * a
        loss = self._avg_loss[symbol]
        self._rsi[symbol] = 100.0 if loss == 0 else 100 - 100 / (1 + self._avg_gain[symbol] / loss)

    def analyze(self, symbol: str, price: float) -> dict | None:
        if not _is_market_hours():
            return None
        self._update_ema(symbol, price)
        self._update_rsi(symbol, price)
        if symbol not in self._rsi:
            return None
        self._cooldown[symbol] = max(0, self._cooldown.get(symbol, 0) - 1)
        if self._cooldown[symbol] > 0 or self._call_open.get(symbol, False):
            return None
        rsi    = self._rsi[symbol]
        short  = self._ema_short[symbol]
        long_  = self._ema_long[symbol]
        spread = (short - long_) / long_ if long_ else 0
        if not (-0.005 < spread < 0.003) or not (self.MIN_RSI <= rsi <= self.MAX_RSI):
            return None
        strike     = round(price * (1 + self.CALL_OTM_PCT), 2)
        confidence = min(0.88, 0.60 + (self.MAX_RSI - rsi) / 40)
        self._call_open[symbol]  = True
        self._cooldown[symbol]   = self.COOLDOWN_TICKS
        self.signal_count       += 1
        logger.info("[COVERED-CALL] %s -> SELL_CALL strike=%.2f OTM=%.1f%% RSI=%.1f",
                    symbol, strike, self.CALL_OTM_PCT * 100, rsi)
        return {
            "bot": self.id, "symbol": symbol, "action": "SELL_CALL",
            "confidence": round(confidence, 3), "price": price,
            "meta": {
                "strategy": "covered_call",
                "strike": strike,
                "expiry_days": _target_expiry_days(),
                "underlying_price": round(price, 4),
                "otm_pct": round(self.CALL_OTM_PCT * 100, 2),
                "rsi": round(rsi, 2),
                "ema_spread_pct": round(spread * 100, 4),
            }
        }

    def record_call_closed(self, symbol: str):
        """Call when short call is closed or expired."""
        self._call_open[symbol] = False

    def get_state(self, symbol: str) -> dict | None:
        rsi   = self._rsi.get(symbol)
        short = self._ema_short.get(symbol)
        long_ = self._ema_long.get(symbol)
        spread = (short - long_) / long_ if (short and long_) else None
        return {
            "strategy": self.id, "name": self.name, "asset_class": self.asset_class,
            "rsi": round(rsi, 2) if rsi is not None else None,
            "ema_spread_pct": round(spread * 100, 4) if spread is not None else None,
            "call_otm_pct": self.CALL_OTM_PCT * 100,
            "call_open": self._call_open.get(symbol, False),
            "cooldown_remaining": self._cooldown.get(symbol, 0),
            "market_hours": _is_market_hours(),
        }


# ---------------------------------------------------------------------------
# Strategy 8: Protective Put Agent
# ---------------------------------------------------------------------------

class ProtectivePutStrategy(BaseStrategy):
    """
    Buys a protective put hedge when downside risk is elevated.

    Signal logic (market hours only):
      - Tracks annualised volatility via rolling 20-period std dev of returns.
      - BUY_PUT  when ann_vol > 25% AND RSI < 40  (vol spike + oversold)
      - SELL_PUT when ann_vol < 15% OR  RSI > 55  (risk resolved - close hedge)

    One put position tracked per symbol at a time.
    Allocation: 3% portfolio (cost of insurance).
    """

    asset_class = "OPTIONS"
    VOL_WINDOW       = 20
    VOL_THRESHOLD    = 0.25
    VOL_RESET        = 0.15
    PUT_OTM_PCT      = 0.03
    RSI_PERIOD       = 14
    RSI_BUY_PUT      = 40
    RSI_CLOSE_PUT    = 55
    COOLDOWN_TICKS   = 30
    ANNUALISE_FACTOR = 252 ** 0.5

    def __init__(self, bot_id="protective-put", name="Protective Put", allocation=3):
        super().__init__(bot_id, name, allocation, "Protective Put")
        self._returns:    dict[str, deque] = {}
        self._last_price: dict[str, float] = {}
        self._rsi_prices: dict[str, deque] = {}
        self._avg_gain:   dict[str, float] = {}
        self._avg_loss:   dict[str, float] = {}
        self._rsi:        dict[str, float] = {}
        self._rsi_init:   dict[str, bool]  = {}
        self._cooldown:   dict[str, int]   = {}
        self._put_open:   dict[str, bool]  = {}

    def _update_vol(self, symbol: str, price: float) -> float | None:
        if symbol not in self._returns:
            self._returns[symbol]    = deque(maxlen=self.VOL_WINDOW)
            self._last_price[symbol] = price
            return None
        prev = self._last_price[symbol]
        if prev > 0:
            self._returns[symbol].append((price - prev) / prev)
        self._last_price[symbol] = price
        if len(self._returns[symbol]) < self.VOL_WINDOW:
            return None
        rets = list(self._returns[symbol])
        mean = sum(rets) / len(rets)
        var  = sum((r - mean) ** 2 for r in rets) / len(rets)
        return (var ** 0.5) * self.ANNUALISE_FACTOR

    def _update_rsi(self, symbol: str, price: float):
        if symbol not in self._rsi_prices:
            self._rsi_prices[symbol] = deque(maxlen=self.RSI_PERIOD + 1)
            self._rsi_init[symbol]   = False
        self._rsi_prices[symbol].append(price)
        if len(self._rsi_prices[symbol]) < self.RSI_PERIOD + 1:
            return
        if not self._rsi_init[symbol]:
            changes = [self._rsi_prices[symbol][i+1] - self._rsi_prices[symbol][i]
                       for i in range(self.RSI_PERIOD)]
            self._avg_gain[symbol] = sum(c for c in changes if c > 0) / self.RSI_PERIOD
            self._avg_loss[symbol] = sum(abs(c) for c in changes if c < 0) / self.RSI_PERIOD
            self._rsi_init[symbol] = True
        else:
            pl     = list(self._rsi_prices[symbol])
            change = pl[-1] - pl[-2]
            a      = 1.0 / self.RSI_PERIOD
            self._avg_gain[symbol] = self._avg_gain[symbol] * (1 - a) + max(0.0, change) * a
            self._avg_loss[symbol] = self._avg_loss[symbol] * (1 - a) + max(0.0, -change) * a
        loss = self._avg_loss[symbol]
        self._rsi[symbol] = 100.0 if loss == 0 else 100 - 100 / (1 + self._avg_gain[symbol] / loss)

    def analyze(self, symbol: str, price: float) -> dict | None:
        if not _is_market_hours():
            return None
        ann_vol = self._update_vol(symbol, price)
        self._update_rsi(symbol, price)
        if ann_vol is None or symbol not in self._rsi:
            return None
        self._cooldown[symbol] = max(0, self._cooldown.get(symbol, 0) - 1)
        if self._cooldown[symbol] > 0:
            return None
        rsi      = self._rsi[symbol]
        put_open = self._put_open.get(symbol, False)

        # Close hedge: risk resolved
        if put_open and (ann_vol < self.VOL_RESET or rsi > self.RSI_CLOSE_PUT):
            self._put_open[symbol]  = False
            self._cooldown[symbol]  = self.COOLDOWN_TICKS
            self.signal_count      += 1
            logger.info("[PROTECTIVE-PUT] %s -> SELL_PUT (close) vol=%.1f%% RSI=%.1f",
                        symbol, ann_vol * 100, rsi)
            return {
                "bot": self.id, "symbol": symbol, "action": "SELL_PUT",
                "confidence": 0.90, "price": price,
                "meta": {"strategy": "protective_put", "trigger": "close_hedge",
                         "ann_vol_pct": round(ann_vol * 100, 2), "rsi": round(rsi, 2),
                         "underlying_price": round(price, 4)}
            }

        # Open hedge: vol spike + oversold
        if not put_open and ann_vol > self.VOL_THRESHOLD and rsi < self.RSI_BUY_PUT:
            strike     = round(price * (1 - self.PUT_OTM_PCT), 2)
            confidence = min(0.90, 0.60 + (ann_vol - self.VOL_THRESHOLD) * 2)
            self._put_open[symbol]  = True
            self._cooldown[symbol]  = self.COOLDOWN_TICKS
            self.signal_count      += 1
            logger.info("[PROTECTIVE-PUT] %s -> BUY_PUT strike=%.2f vol=%.1f%% RSI=%.1f",
                        symbol, strike, ann_vol * 100, rsi)
            return {
                "bot": self.id, "symbol": symbol, "action": "BUY_PUT",
                "confidence": round(confidence, 3), "price": price,
                "meta": {
                    "strategy": "protective_put",
                    "strike": strike,
                    "expiry_days": _target_expiry_days(min_dte=21, preferred_dte=30),
                    "underlying_price": round(price, 4),
                    "otm_pct": round(self.PUT_OTM_PCT * 100, 2),
                    "ann_vol_pct": round(ann_vol * 100, 2),
                    "rsi": round(rsi, 2),
                }
            }
        return None

    def get_state(self, symbol: str) -> dict | None:
        rsi     = self._rsi.get(symbol)
        ann_vol = None
        if symbol in self._returns and len(self._returns[symbol]) >= self.VOL_WINDOW:
            rets = list(self._returns[symbol])
            mean = sum(rets) / len(rets)
            var  = sum((r - mean) ** 2 for r in rets) / len(rets)
            ann_vol = round((var ** 0.5) * self.ANNUALISE_FACTOR * 100, 2)
        return {
            "strategy": self.id, "name": self.name, "asset_class": self.asset_class,
            "ann_vol_pct": ann_vol,
            "vol_threshold_pct": self.VOL_THRESHOLD * 100,
            "rsi": round(rsi, 2) if rsi is not None else None,
            "put_open": self._put_open.get(symbol, False),
            "cooldown_remaining": self._cooldown.get(symbol, 0),
            "market_hours": _is_market_hours(),
        }
