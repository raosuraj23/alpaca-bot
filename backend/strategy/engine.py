"""
Strategy Engine
================
Singleton that owns all active trading strategy instances.
Coordinates signal generation from price ticks and provides
bot lifecycle management (halt, resume, allocation updates).
"""

import logging
from strategy.algorithms import MomentumStrategy, StatArbStrategy, HighFrequencyStrategy

logger = logging.getLogger(__name__)


class StrategyEngine:
    def __init__(self):
        self.bots: dict = {
            "momentum-alpha": MomentumStrategy(),
            "statarb-gamma":  StatArbStrategy(),
            "hft-sniper":     HighFrequencyStrategy(),
        }
        self._last_prices: dict[str, float] = {}  # last known tick price per symbol

    # ------------------------------------------------------------------
    # State Queries
    # ------------------------------------------------------------------

    def get_bot_states(self) -> list[dict]:
        """Returns JSON-serializable list of active bots for the UI."""
        return [
            {
                "id":             bot.id,
                "name":           bot.name,
                "status":         bot.status,
                "allocationPct":  bot.allocation,
                "yield24h":       bot.yield24h,
                "algo":           bot.algo,
                "signalCount":    bot.signal_count,
                "fillCount":      bot.fill_count,
            }
            for bot in self.bots.values()
        ]

    def get_stats(self) -> dict:
        """Per-bot analytics summary for the Performance tab."""
        return {
            bot_id: {
                "signal_count": bot.signal_count,
                "fill_count":   bot.fill_count,
                "yield24h":     bot.yield24h,
                "status":       bot.status,
                "fill_rate":    round(bot.fill_count / bot.signal_count, 3) if bot.signal_count > 0 else 0.0,
            }
            for bot_id, bot in self.bots.items()
        }

    def get_all_states(self) -> dict[str, list[dict]]:
        """Returns internal indicator state for all strategies across tracked symbols.
        Used by the ReflectionEngine for zero-cost market observations."""
        symbols = set()
        for bot in self.bots.values():
            # Collect known symbols from each strategy's internal price buffers
            for attr in ('ema_short', '_prices'):
                if hasattr(bot, attr):
                    symbols.update(getattr(bot, attr).keys())
        result = {}
        for sym in symbols:
            states = []
            for bot in self.bots.values():
                state = bot.get_state(sym)
                if state:
                    state["bot_status"] = bot.status
                    states.append(state)
            if states:
                result[sym] = states
        return result

    # ------------------------------------------------------------------
    # Lifecycle Controls
    # ------------------------------------------------------------------

    def halt_bot(self, bot_id: str, reason: str = "Manual halt") -> bool:
        """Sets bot status to HALTED. Returns True if bot was found and changed."""
        bot = self.bots.get(bot_id)
        if not bot:
            logger.warning("[ENGINE] halt_bot: unknown bot_id=%s", bot_id)
            return False
        bot.status = "HALTED"
        logger.info("[ENGINE] Bot %s HALTED — reason: %s", bot_id, reason)
        return True

    def resume_bot(self, bot_id: str) -> bool:
        """Sets bot status to ACTIVE. Returns True if bot was found and changed."""
        bot = self.bots.get(bot_id)
        if not bot:
            logger.warning("[ENGINE] resume_bot: unknown bot_id=%s", bot_id)
            return False
        bot.status = "ACTIVE"
        logger.info("[ENGINE] Bot %s RESUMED", bot_id)
        return True

    def adjust_allocation(self, bot_id: str, new_pct: float) -> bool:
        """Updates allocation percentage for a bot."""
        bot = self.bots.get(bot_id)
        if not bot:
            return False
        bot.allocation = max(0.0, min(100.0, new_pct))
        logger.info("[ENGINE] Bot %s allocation → %.1f%%", bot_id, bot.allocation)
        return True

    def update_yield(self, bot_id: str, pnl_delta: float):
        """Called by ExecutionAgent on confirmed fill to update 24h P&L."""
        bot = self.bots.get(bot_id)
        if bot:
            bot.record_fill(pnl_delta)

    # ------------------------------------------------------------------
    # Signal Generation (called per market tick)
    # ------------------------------------------------------------------

    def get_last_price(self, symbol: str) -> float | None:
        """Returns the most recently seen tick price for a symbol, or None."""
        return self._last_prices.get(symbol)

    def process_tick(self, symbol: str, price: float) -> list[dict]:
        """
        Feeds a price tick to all ACTIVE strategies.
        Returns a list of emitted signal dicts (may be empty).
        """
        self._last_prices[symbol] = price  # cache for manual order slippage calc
        signals = []
        for bot in self.bots.values():
            if bot.status != "ACTIVE":
                continue
            signal = bot.analyze(symbol, price)
            if signal:
                logger.info(
                    "[ENGINE] %s → %s %s @ $%.2f (conf=%.2f)",
                    bot.name, signal["action"], symbol, price, signal["confidence"]
                )
                signals.append(signal)
        return signals


# Global singleton — shared across FastAPI request handlers and the stream manager.
master_engine = StrategyEngine()
