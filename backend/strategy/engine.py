"""
Strategy Engine
================
Singleton that owns all active trading strategy instances.
Coordinates signal generation from price ticks and provides
bot lifecycle management (halt, resume, allocation updates).
"""

import logging
from strategy.algorithms import MomentumStrategy, StatArbStrategy, HighFrequencyStrategy
from strategy.equity_algorithms import EquityMomentumStrategy, EquityRSIStrategy, EquityPairsStrategy, EQUITY_SYMBOLS
from strategy.options_algorithms import CoveredCallStrategy, ProtectivePutStrategy

CRYPTO_SYMBOLS_BASE = {"BTC/USD", "ETH/USD", "SOL/USD"}  # always included; scanner expands this
EQUITY_SYMBOL_SET   = set(EQUITY_SYMBOLS)

logger = logging.getLogger(__name__)


class StrategyEngine:
    def __init__(self):
        # Start with the base crypto set; scanner discovery updates this at runtime
        self.active_crypto_symbols: set[str] = set(CRYPTO_SYMBOLS_BASE)
        self.bots: dict = {
            # ── Crypto ────────────────────────────────────────────────────
            "momentum-alpha":   MomentumStrategy(),
            "statarb-gamma":    StatArbStrategy(),
            "hft-sniper":       HighFrequencyStrategy(),
            # ── Equity ────────────────────────────────────────────────────
            "equity-momentum":  EquityMomentumStrategy(),
            "equity-rsi":       EquityRSIStrategy(),
            "equity-pairs":     EquityPairsStrategy(),
            # ── Options ───────────────────────────────────────────────────
            "covered-call":     CoveredCallStrategy(),
            "protective-put":   ProtectivePutStrategy(),
        }
        self._last_prices: dict[str, float] = {}  # last known tick price per symbol

    def restore_from_db(self, states: list[dict]) -> None:
        """Called by startup_event() to restore persisted halt/resume states.
        Prevents bots from booting ACTIVE after a server restart when they were halted."""
        for row in states:
            bot = self.bots.get(row["bot_id"])
            if bot:
                bot.status     = row["status"]
                bot.allocation = row["allocation"]
                logger.info("[ENGINE] Restored %s → status=%s alloc=%.1f%%",
                            row["bot_id"], row["status"], row["allocation"])

    def update_strategy_params(self, bot_id: str, params: dict) -> bool:
        """Mutate strategy configuration at runtime (called by AutonomousPortfolioDirector)."""
        bot = self.bots.get(bot_id)
        if not bot:
            logger.warning("[ENGINE] update_strategy_params: unknown bot_id=%s", bot_id)
            return False
        bot.update_params(params)
        return True

    def spawn_variant(self, source_bot_id: str, new_bot_id: str, params: dict) -> bool:
        """Clone a bot with overridden params and add it as a new active bot.
        Returns False if source bot not found or new_bot_id already exists."""
        if new_bot_id in self.bots:
            logger.warning("[ENGINE] spawn_variant: %s already exists", new_bot_id)
            return False
        source = self.bots.get(source_bot_id)
        if not source:
            logger.warning("[ENGINE] spawn_variant: source %s not found", source_bot_id)
            return False
        import copy
        variant = copy.deepcopy(source)
        variant.id     = new_bot_id
        variant.name   = f"{source.name} [variant]"
        variant.status = "ACTIVE"
        variant.update_params(params)
        self.bots[new_bot_id] = variant
        logger.info("[ENGINE] Spawned variant %s from %s with params %s",
                    new_bot_id, source_bot_id, params)
        return True

    def set_active_crypto_symbols(self, symbols: set[str]) -> None:
        """Called by the scanner agent when it discovers new high-priority symbols.
        Always merges with the base set so BTC/ETH/SOL are never dropped."""
        merged = CRYPTO_SYMBOLS_BASE | {s for s in symbols if s.endswith("/USD")}
        if merged != self.active_crypto_symbols:
            logger.info("[ENGINE] Crypto symbol set updated: %s", sorted(merged))
            self.active_crypto_symbols = merged

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
                "assetClass":     getattr(bot, "asset_class", "CRYPTO"),
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
                "asset_class":  getattr(bot, "asset_class", "CRYPTO"),
                "fill_rate":    round(bot.fill_count / bot.signal_count, 3) if bot.signal_count > 0 else 0.0,
            }
            for bot_id, bot in self.bots.items()
        }

    def get_all_states(self) -> dict[str, list[dict]]:
        """Returns internal indicator state for all strategies across tracked symbols.
        Used by the ReflectionEngine for zero-cost market observations."""
        symbols: set[str] = set()
        for bot in self.bots.values():
            for attr in ('ema_short', '_prices', '_rsi_prices', '_returns', '_ema_short'):
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

    def notify_fill(self, bot_id: str, symbol: str, action: str, fill_price: float | None = None):
        """
        Called by execution pipeline after a confirmed fill.
        Updates position state on the strategy (FLAT/LONG tracking).
        For HFT, also records entry price for stop-loss tracking.
        """
        bot = self.bots.get(bot_id)
        if not bot:
            return
        bot.notify_fill(symbol, action)
        if bot_id == "hft-sniper" and action == "BUY" and fill_price is not None:
            if hasattr(bot, "set_entry_price"):
                bot.set_entry_price(symbol, fill_price)

    # ------------------------------------------------------------------
    # Signal Generation (called per market tick)
    # ------------------------------------------------------------------

    def get_last_price(self, symbol: str) -> float | None:
        """Returns the most recently seen tick price for a symbol, or None."""
        return self._last_prices.get(symbol)

    def process_tick(self, symbol: str, price: float) -> list[dict]:
        """
        Feeds a price tick to ACTIVE strategies whose asset class matches the symbol.

        Routing:
          Crypto symbols  → CRYPTO bots only
          Equity symbols  → EQUITY + OPTIONS bots only
        """
        self._last_prices[symbol] = price
        signals = []

        is_crypto = symbol in self.active_crypto_symbols
        is_equity = symbol in EQUITY_SYMBOL_SET

        for bot in self.bots.values():
            if bot.status != "ACTIVE":
                continue

            asset_class = getattr(bot, "asset_class", "CRYPTO")

            if is_crypto and asset_class != "CRYPTO":
                continue
            if is_equity and asset_class not in ("EQUITY", "OPTIONS"):
                continue
            if not is_crypto and not is_equity:
                continue  # unknown symbol — skip

            signal = bot.analyze(symbol, price)
            if signal:
                logger.info(
                    "[ENGINE] %s → %s %s @ $%.4f (conf=%.2f)",
                    bot.name, signal["action"], symbol, price, signal["confidence"]
                )
                signals.append(signal)
        return signals


# Global singleton — shared across FastAPI request handlers and the stream manager.
master_engine = StrategyEngine()
