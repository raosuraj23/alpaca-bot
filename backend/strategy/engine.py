"""
Strategy Engine
================
Singleton that owns all active trading strategy instances.
Coordinates signal generation from price ticks and provides
bot lifecycle management (halt, resume, allocation updates).

Per-symbol strategy assignment
--------------------------------
New symbols discovered by the scanner are placed into _pending_assignment
(quarantined — no signals) until the Portfolio Director assigns them a strategy.

Seed symbols (BTC, ETH, SPY, AAPL, etc.) continue to use asset-class routing
for backward compatibility; the Director can override them with explicit assignments
at any time.
"""

import json
import logging
import asyncio
from typing import Callable, Optional

from strategy.algorithms import (
    MomentumStrategy, StatArbStrategy, HighFrequencyStrategy,
    NewsMomentumStrategy, CryptoRangeScalpStrategy, CryptoPairsStrategy,
)
from strategy.equity_algorithms import (
    EquityMomentumStrategy, EquityRSIStrategy, EquityPairsStrategy,
    EquityBreakoutStrategy, VWAPReversionStrategy, EQUITY_SYMBOLS,
)
from strategy.options_algorithms import CoveredCallStrategy, ProtectivePutStrategy

CRYPTO_SYMBOLS_BASE = {"BTC/USD", "ETH/USD", "SOL/USD"}  # always included; scanner expands this

logger = logging.getLogger(__name__)


class StrategyEngine:
    def __init__(self, ws_subscribe_callback: Optional[Callable[[list[str]], None]] = None):
        self.ws_subscribe_callback = ws_subscribe_callback
        # Start with the base crypto set; scanner discovery updates this at runtime
        self.active_crypto_symbols: set[str] = set(CRYPTO_SYMBOLS_BASE)
        # Equity symbols routing table; grows as scanner/research surface new tickers
        self.active_equity_symbols: set[str] = set(EQUITY_SYMBOLS)

        # Full algorithm template library — used by director to instantiate new bots
        self._strategy_templates: dict[str, type] = {
            # ── Crypto ────────────────────────────────────────────────────
            "momentum-alpha":      MomentumStrategy,
            "statarb-gamma":       StatArbStrategy,
            "hft-sniper":          HighFrequencyStrategy,
            "news-momentum":       NewsMomentumStrategy,
            "crypto-range-scalp":  CryptoRangeScalpStrategy,
            "crypto-pairs":        CryptoPairsStrategy,
            # ── Equity ────────────────────────────────────────────────────
            "equity-momentum":     EquityMomentumStrategy,
            "equity-rsi":          EquityRSIStrategy,
            "equity-pairs":        EquityPairsStrategy,
            "equity-breakout":     EquityBreakoutStrategy,
            "vwap-reversion":      VWAPReversionStrategy,
            # ── Options ───────────────────────────────────────────────────
            "covered-call":        CoveredCallStrategy,
            "protective-put":      ProtectivePutStrategy,
        }

        # Seed bots (one instance per base algorithm, always running on their asset class)
        _seed_algo_ids = [
            "momentum-alpha", "statarb-gamma", "hft-sniper",
            "equity-momentum", "equity-rsi", "equity-pairs",
            "covered-call", "protective-put",
        ]
        self.bots: dict = {
            name: self._strategy_templates[name]() for name in _seed_algo_ids
        }
        self._last_prices: dict[str, float] = {}

        # Per-symbol assignment: symbol → list of bot_ids explicitly assigned by director
        self._symbol_strategy_map: dict[str, list[str]] = {}

        # Symbols quarantined pending director strategy assignment (scanner-discovered only)
        self._pending_assignment: set[str] = set()

        # Track which symbols are "seed" so they are not quarantined
        self._seed_symbols: set[str] = set(CRYPTO_SYMBOLS_BASE) | set(EQUITY_SYMBOLS)

    # ------------------------------------------------------------------
    # Symbol quarantine & assignment
    # ------------------------------------------------------------------

    def add_to_pending(self, symbol: str) -> None:
        """Called by scanner when a brand-new (non-seed) symbol is discovered.
        The symbol will be quarantined until the director assigns a strategy."""
        if symbol in self._seed_symbols:
            return
        if symbol in self._pending_assignment:
            return
        if symbol in self._symbol_strategy_map:
            return  # already assigned — not a new symbol
        self._pending_assignment.add(symbol)
        logger.info("[ENGINE] Symbol %s quarantined — awaiting director strategy assignment", symbol)

    def assign_strategy_to_symbol(self, symbol: str, bot_id: str) -> bool:
        """Bind an existing bot to a symbol. Removes symbol from pending quarantine."""
        if bot_id not in self.bots:
            logger.warning("[ENGINE] assign_strategy_to_symbol: unknown bot_id=%s", bot_id)
            return False
        if symbol not in self._symbol_strategy_map:
            self._symbol_strategy_map[symbol] = []
        if bot_id not in self._symbol_strategy_map[symbol]:
            self._symbol_strategy_map[symbol].append(bot_id)
        self._pending_assignment.discard(symbol)
        logger.info("[ENGINE] Symbol %s → assigned to bot %s", symbol, bot_id)
        return True

    def unassign_strategy_from_symbol(self, symbol: str, bot_id: str) -> bool:
        """Remove a bot from a symbol's assignment list."""
        assignments = self._symbol_strategy_map.get(symbol)
        if not assignments or bot_id not in assignments:
            return False
        assignments.remove(bot_id)
        if not assignments:
            del self._symbol_strategy_map[symbol]
        logger.info("[ENGINE] Symbol %s unassigned from bot %s", symbol, bot_id)
        return True

    def create_strategy_for_symbol(
        self,
        symbol: str,
        algo_type: str,
        params: dict,
        bot_id: str,
    ) -> bool:
        """
        Instantiate a new bot from a template, configure it with custom params,
        register it in self.bots, and assign it to the symbol.
        """
        if bot_id in self.bots:
            logger.warning("[ENGINE] create_strategy_for_symbol: bot_id %s already exists", bot_id)
            return False
        cls = self._strategy_templates.get(algo_type)
        if cls is None:
            logger.warning("[ENGINE] create_strategy_for_symbol: unknown algo_type=%s", algo_type)
            return False

        bot = cls()
        bot.id     = bot_id
        bot.name   = f"{bot.name} [{symbol}]"
        bot.status = "ACTIVE"
        if params:
            bot.update_params(params)

        self.bots[bot_id] = bot
        self.assign_strategy_to_symbol(symbol, bot_id)
        logger.info("[ENGINE] Created %s (algo=%s) for symbol %s with params %s",
                    bot_id, algo_type, symbol, params)
        return True

    def restore_symbol_assignments(self, assignments: list) -> None:
        """Called at startup to restore persisted symbol-strategy assignments from DB."""
        import json as _json
        for row in assignments:
            symbol     = row.symbol
            bot_id     = row.bot_id
            algo_type  = row.algorithm_type
            params_raw = row.params_json

            if bot_id not in self.bots:
                # Re-instantiate the bot from its template
                params = {}
                if params_raw:
                    try:
                        params = _json.loads(params_raw)
                    except Exception:
                        pass
                cls = self._strategy_templates.get(algo_type)
                if cls:
                    bot = cls()
                    bot.id     = bot_id
                    bot.name   = f"{bot.name} [{symbol}]"
                    bot.status = "ACTIVE"
                    if params:
                        bot.update_params(params)
                    self.bots[bot_id] = bot
                    logger.info("[ENGINE] Restored custom bot %s (algo=%s) for %s", bot_id, algo_type, symbol)
                else:
                    logger.warning("[ENGINE] restore_symbol_assignments: unknown algo_type=%s for %s", algo_type, symbol)
                    continue

            # Wire the assignment
            if symbol not in self._symbol_strategy_map:
                self._symbol_strategy_map[symbol] = []
            if bot_id not in self._symbol_strategy_map[symbol]:
                self._symbol_strategy_map[symbol].append(bot_id)
            self._pending_assignment.discard(symbol)
            logger.info("[ENGINE] Restored assignment %s → %s", symbol, bot_id)

    def get_pending_assignment(self) -> list[str]:
        return sorted(self._pending_assignment)

    def get_symbol_strategy_map(self) -> dict[str, list[str]]:
        return dict(self._symbol_strategy_map)

    def get_available_algorithms(self) -> list[str]:
        return list(self._strategy_templates.keys())

    # ------------------------------------------------------------------
    # Restore & lifecycle
    # ------------------------------------------------------------------

    def restore_from_db(self, states: list[dict]) -> None:
        """Called by startup_event() to restore persisted halt/resume states."""
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
        """Properly instantiate a new bot using the factory pattern."""
        if new_bot_id in self.bots:
            logger.warning("[ENGINE] spawn_variant: %s already exists", new_bot_id)
            return False
        source = self.bots.get(source_bot_id)
        if not source:
            logger.warning("[ENGINE] spawn_variant: source %s not found", source_bot_id)
            return False

        bot_class = type(source)
        variant = bot_class()
        variant.id     = new_bot_id
        variant.name   = f"{source.name} [variant]"
        variant.allocation = getattr(source, "allocation", 0.0)
        variant.status = "ACTIVE"
        variant.update_params(params)

        self.bots[new_bot_id] = variant
        logger.info("[ENGINE] Spawned variant %s from %s with params %s",
                    new_bot_id, source_bot_id, params)
        return True

    def set_active_crypto_symbols(self, symbols: set[str]) -> None:
        """Merges new crypto symbols and commands the WebSocket to subscribe."""
        merged = CRYPTO_SYMBOLS_BASE | {s for s in symbols if s.endswith("/USD")}
        new_symbols = merged - self.active_crypto_symbols

        if new_symbols:
            logger.info("[ENGINE] New crypto symbols discovered: %s", list(new_symbols))
            self.active_crypto_symbols = merged

            if self.ws_subscribe_callback:
                self.ws_subscribe_callback(list(new_symbols))

    def set_active_equity_symbols(self, symbols: set[str]) -> None:
        """Merges newly discovered equity symbols into the tick-routing table."""
        new_symbols = {s for s in symbols if "/" not in s} - self.active_equity_symbols
        if new_symbols:
            logger.info("[ENGINE] New equity symbols discovered: %s", list(new_symbols))
            self.active_equity_symbols |= new_symbols

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
        """Returns internal indicator state for all strategies across tracked symbols."""
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

    def get_ta_snapshot(self, symbol: str) -> dict:
        """Returns a compact TA state snapshot for a symbol (used by director for context)."""
        snap: dict = {"symbol": symbol, "last_price": self._last_prices.get(symbol)}
        for bot in self.bots.values():
            state = bot.get_state(symbol)
            if state:
                snap[bot.id] = state
        return snap

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
        """Called by execution pipeline after a confirmed fill."""
        bot = self.bots.get(bot_id)
        if not bot:
            return
        bot.notify_fill(symbol, action)
        if action == "BUY" and fill_price is not None and hasattr(bot, "set_entry_price"):
            bot.set_entry_price(symbol, fill_price)

    # ------------------------------------------------------------------
    # Signal Generation (called per market tick)
    # ------------------------------------------------------------------

    def get_last_price(self, symbol: str) -> float | None:
        """Returns the most recently seen tick price for a symbol, or None."""
        return self._last_prices.get(symbol)

    async def process_tick(self, symbol: str, price: float) -> list[dict]:
        """Asynchronously dispatches price updates to active bots.

        Routing priority:
          1. If symbol is in _pending_assignment → quarantined, return [].
          2. If symbol has explicit assignments in _symbol_strategy_map → route only to those bots.
          3. Otherwise fall back to asset-class routing (seed symbols, backward compat).
        """
        self._last_prices[symbol] = price

        # 1. Quarantine check
        if symbol in self._pending_assignment:
            return []

        # 2. Explicit per-symbol assignment
        assigned_ids = self._symbol_strategy_map.get(symbol)
        if assigned_ids is not None:
            active_bots = [
                self.bots[bid]
                for bid in assigned_ids
                if bid in self.bots and self.bots[bid].status == "ACTIVE"
            ]
        else:
            # 3. Asset-class fallback for seed symbols
            is_crypto = symbol in self.active_crypto_symbols
            is_equity = symbol in self.active_equity_symbols
            active_bots = []
            for bot in self.bots.values():
                if bot.status != "ACTIVE":
                    continue
                asset_class = getattr(bot, "asset_class", "CRYPTO")
                if is_crypto and asset_class == "CRYPTO":
                    active_bots.append(bot)
                elif is_equity and asset_class in ("EQUITY", "OPTIONS"):
                    active_bots.append(bot)

        if not active_bots:
            return []

        tasks = [bot.aanalyze(symbol, price) for bot in active_bots]
        results = await asyncio.gather(*tasks, return_exceptions=True)

        valid_signals = []
        for bot, signal in zip(active_bots, results):
            if isinstance(signal, Exception):
                logger.error("[ENGINE] %s crashed on tick: %s", bot.name, signal)
                continue
            if signal:
                logger.info("[ENGINE] %s -> %s %s", bot.name, signal["action"], symbol)
                valid_signals.append(signal)

        return valid_signals


# Global singleton — shared across FastAPI request handlers and the stream manager.
master_engine = StrategyEngine()
