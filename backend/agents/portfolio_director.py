"""
Autonomous Portfolio Director
==============================
Background asyncio task that runs every 15 minutes and acts as the AI brain
for portfolio-level decision making. Uses Haiku (fast/cheap tier) to:

  1. Read all bot states, stats, latest scanner results, and recent trade history
  2. Generate a structured Pydantic command list via with_structured_output()
  3. Execute each command through a registry-based CommandDispatcher
  4. Log every action to the BotAmend SQLite table for audit trail
  5. Push SSE events so the UI Brain tab reflects changes in real time

Supported command actions:
  HALT_BOT                   — halt a bot + persist BotState
  RESUME_BOT                 — resume a halted bot + persist BotState
  ADJUST_ALLOCATION          — change allocation % on a bot (hard-clamped 5–40%)
  UPDATE_STRATEGY_PARAMS     — mutate strategy parameters at runtime (key-intersected)
  SPAWN_BOT_VARIANT          — deep-copy a bot with new params, add to engine
  ASSIGN_EXISTING_STRATEGY   — bind an existing bot to a specific symbol (removes quarantine)
  CREATE_NEW_STRATEGY_INSTANCE — instantiate a new bot from any template for a specific symbol
  UNASSIGN_STRATEGY          — remove a bot-symbol binding
  NO_ACTION                  — Haiku recommends status quo (logged, not executed)

Architecture:
  - Pydantic structured outputs replace brittle regex JSON parsing
  - Native async ainvoke() replaces blocking run_in_executor
  - CommandDispatcher registry replaces if-elif monolith
  - Zero-trust guardrails inside each handler enforce hard limits
  - Trade history context enables win-rate-driven decisions
"""

import asyncio
import json
import logging
from datetime import datetime, timezone
from enum import Enum
from typing import Callable, Optional

from pydantic import BaseModel, Field
from config import CLAUDE_HAIKU_MODEL

logger = logging.getLogger(__name__)

INTERVAL = 900   # 15 minutes between reviews
WARMUP   = 60    # seconds to wait for streams to stabilize on startup
MAX_CMDS = 3     # cap commands per cycle to prevent runaway mutations

_SYSTEM_PROMPT = """You are an autonomous quantitative portfolio director.
Analyze the portfolio context and determine what actions, if any, should be taken.

Primary objective: maximize portfolio win rate and risk-adjusted return.
Use bot_win_rates and trade_history to identify underperforming and outperforming bots.

═══════════════════════════════════════════════════════════════
PRIORITY TASK — PENDING SYMBOL ASSIGNMENT (handle FIRST):
═══════════════════════════════════════════════════════════════
If pending_symbols is non-empty, you MUST emit one assignment command per symbol
BEFORE any other commands. Each pending symbol has been quarantined (no trading)
until you assign it a strategy.

Use ta_snapshots and research_edges to select the best algorithm:

  Strong trend (EMA spread > 0.3%) + positive edge  → equity-breakout OR momentum-alpha
  Consolidation / low vol (EMA spread < 0.1%)        → statarb-gamma, equity-rsi, OR crypto-range-scalp
  High news edge (abs(edge) > 0.07)                  → news-momentum
  Equity near VWAP mean-reversion profile            → vwap-reversion
  Two correlated equity symbols (e.g. NVDA/AMD)      → equity-pairs with leg_a/leg_b params
  Two correlated crypto symbols (e.g. BTC/ETH)       → crypto-pairs with leg_a/leg_b params
  An existing seed bot already handles similar symbols → ASSIGN_EXISTING_STRATEGY with that bot_id

For each pending symbol, emit one of:
  a) ASSIGN_EXISTING_STRATEGY — use an existing bot, set target_bot and params.symbol
  b) CREATE_NEW_STRATEGY_INSTANCE — instantiate a new bot from available_algorithms:
       set params.algorithm_type, params.new_bot_id ("<algo>-<ticker>-v1"),
       params.symbol, params.strategy_params (tuned for this symbol), and params.reason

═══════════════════════════════════════════════════════════════
PORTFOLIO OPTIMIZATION RULES (run after pending assignments):
═══════════════════════════════════════════════════════════════
- Only HALT bots with clear negative evidence (fill_rate < 0.1 AND yield24h < -0.5)
- Bots with win_rate < 0.35 AND total >= 10 trades are strong candidates for HALT or ADJUST_ALLOCATION down
- Bots with win_rate > 0.60 AND total >= 5 trades may warrant ADJUST_ALLOCATION increase
- ADJUST_ALLOCATION requires new_allocation_pct (a float 5.0–40.0). NEVER emit ADJUST_ALLOCATION without it.
- Allocation adjustments must be between 5% and 40%
- UPDATE_STRATEGY_PARAMS and SPAWN_BOT_VARIANT MUST use ONLY the parameter names in the registry below.
- SPAWN_BOT_VARIANT tries a parameter variant without halting the original
- Recommend NO_ACTION or an empty commands list if no intervention is warranted
- Always provide a reason and expected impact for each action
- Maximum 3 commands per cycle (pending assignments count toward this cap)

═══════════════════════════════════════════════════════════════
STRATEGY PARAMETER REGISTRY — exact attribute names:
═══════════════════════════════════════════════════════════════
  momentum-alpha:        alpha_short (0.05–0.40), alpha_long (0.01–0.15)
  statarb-gamma:         lookback_period (10–50), sigma_multiplier (1.5–3.0)
  hft-sniper:            MOMENTUM_THRESHOLD (0.0001–0.001), MOMENTUM_WINDOW (2–10), COOLDOWN_TICKS (3–20)
  equity-momentum:       alpha_short (0.05–0.40), alpha_long (0.01–0.15)
  equity-rsi:            rsi_period (7–21), rsi_oversold (20–40), rsi_overbought (60–80)
  equity-pairs:          leg_a str (e.g. "NVDA"), leg_b str (e.g. "AMD"), z_threshold (1.0–3.0), window (10–60)
  crypto-pairs:          leg_a str (e.g. "BTC/USD"), leg_b str (e.g. "ETH/USD"), z_threshold (1.0–3.0), window (10–60)
  equity-breakout:       atr_period (7–28), breakout_multiplier (1.0–3.0), volume_threshold (1.2–3.0), cooldown_ticks (5–40)
  vwap-reversion:        sigma_threshold (1.0–2.5), warmup_ticks (15–60)
  news-momentum:         edge_threshold (0.04–0.12), momentum_ticks (3–10), hold_limit_ticks (10–60)
  crypto-range-scalp:    bb_period (10–40), bb_sigma (1.0–2.5), min_range_ticks (5–20), cooldown_ticks (3–15)
  covered-call:          (no patchable params)
  protective-put:        (no patchable params)
"""

# ---------------------------------------------------------------------------
# Pydantic command schema
# ---------------------------------------------------------------------------

class CommandAction(str, Enum):
    HALT_BOT                    = "HALT_BOT"
    RESUME_BOT                  = "RESUME_BOT"
    ADJUST_ALLOCATION           = "ADJUST_ALLOCATION"
    UPDATE_STRATEGY_PARAMS      = "UPDATE_STRATEGY_PARAMS"
    SPAWN_BOT_VARIANT           = "SPAWN_BOT_VARIANT"
    ASSIGN_EXISTING_STRATEGY    = "ASSIGN_EXISTING_STRATEGY"
    CREATE_NEW_STRATEGY_INSTANCE = "CREATE_NEW_STRATEGY_INSTANCE"
    UNASSIGN_STRATEGY           = "UNASSIGN_STRATEGY"
    NO_ACTION                   = "NO_ACTION"


class CommandParams(BaseModel):
    new_allocation_pct: Optional[float] = Field(None, description="Target allocation 5–40%")
    reason: str  = Field("Director recommendation", description="One-sentence rationale")
    impact: str  = Field("Not specified", description="Expected statistical effect")
    strategy_params: Optional[dict]  = Field(None, description="Key-value pairs to mutate on strategy")
    source_bot:      Optional[str]   = Field(None, description="Bot ID to clone from")
    new_bot_id:      Optional[str]   = Field(None, description="Unique ID for the variant bot")
    # Symbol assignment fields
    symbol:          Optional[str]   = Field(None, description="Symbol to assign/unassign strategy to")
    algorithm_type:  Optional[str]   = Field(None, description="Algorithm template type for CREATE_NEW_STRATEGY_INSTANCE")


class DirectorCommand(BaseModel):
    action:     CommandAction
    target_bot: Optional[str]   = Field(None, description="Bot ID this command targets")
    params:     CommandParams    = Field(default_factory=CommandParams)


class ActionList(BaseModel):
    commands: list[DirectorCommand] = Field(default_factory=list)


# ---------------------------------------------------------------------------
# Command Dispatcher — registry-based, replaces if-elif monolith
# ---------------------------------------------------------------------------

class CommandDispatcher:
    """
    Maps CommandAction enums to isolated async handler methods.
    Each handler owns its own zero-trust guardrails.
    """

    def __init__(self, db_factory: Optional[Callable] = None) -> None:
        self._db_factory = db_factory
        self._registry: dict[CommandAction, Callable] = {
            CommandAction.HALT_BOT:                     self._handle_halt_bot,
            CommandAction.RESUME_BOT:                   self._handle_resume_bot,
            CommandAction.ADJUST_ALLOCATION:            self._handle_adjust_allocation,
            CommandAction.UPDATE_STRATEGY_PARAMS:       self._handle_update_strategy_params,
            CommandAction.SPAWN_BOT_VARIANT:            self._handle_spawn_bot_variant,
            CommandAction.ASSIGN_EXISTING_STRATEGY:     self._handle_assign_existing_strategy,
            CommandAction.CREATE_NEW_STRATEGY_INSTANCE: self._handle_create_new_strategy_instance,
            CommandAction.UNASSIGN_STRATEGY:            self._handle_unassign_strategy,
        }

    async def dispatch(
        self,
        cmd: DirectorCommand,
        engine,
        persist_fn: Callable,
    ) -> bool:
        """Route cmd to its registered handler. Returns success bool."""
        handler = self._registry.get(cmd.action)
        if handler is None:
            logger.warning("[DIRECTOR] No handler registered for action: %s", cmd.action)
            return False
        try:
            return await handler(cmd, engine, persist_fn)
        except Exception as exc:
            logger.error(
                "[DIRECTOR] Handler %s failed for bot=%s: %s",
                cmd.action, cmd.target_bot, exc,
            )
            return False

    # ------------------------------------------------------------------
    # Isolated async handlers
    # ------------------------------------------------------------------

    async def _handle_halt_bot(
        self, cmd: DirectorCommand, engine, persist_fn: Callable
    ) -> bool:
        if not cmd.target_bot:
            logger.warning("[DIRECTOR] HALT_BOT missing target_bot")
            return False
        success = engine.halt_bot(cmd.target_bot, reason=cmd.params.reason)
        if success:
            asyncio.create_task(persist_fn(cmd.target_bot, "HALTED", engine))
        return success

    async def _handle_resume_bot(
        self, cmd: DirectorCommand, engine, persist_fn: Callable
    ) -> bool:
        if not cmd.target_bot:
            logger.warning("[DIRECTOR] RESUME_BOT missing target_bot")
            return False
        success = engine.resume_bot(cmd.target_bot)
        if success:
            asyncio.create_task(persist_fn(cmd.target_bot, "ACTIVE", engine))
        return success

    async def _handle_adjust_allocation(
        self, cmd: DirectorCommand, engine, persist_fn: Callable
    ) -> bool:
        if not cmd.target_bot:
            logger.warning("[DIRECTOR] ADJUST_ALLOCATION missing target_bot")
            return False
        raw_pct = cmd.params.new_allocation_pct
        if raw_pct is None:
            logger.warning("[DIRECTOR] ADJUST_ALLOCATION missing new_allocation_pct for bot=%s", cmd.target_bot)
            return False
        # Zero-trust guardrail: hard clamp to [5.0, 40.0]
        clamped_pct = max(5.0, min(40.0, float(raw_pct)))
        if clamped_pct != float(raw_pct):
            logger.warning(
                "[DIRECTOR] ADJUST_ALLOCATION clamped %.2f%% → %.2f%% for bot=%s",
                raw_pct, clamped_pct, cmd.target_bot,
            )
        return engine.adjust_allocation(cmd.target_bot, clamped_pct)

    async def _handle_update_strategy_params(
        self, cmd: DirectorCommand, engine, persist_fn: Callable
    ) -> bool:
        if not cmd.target_bot:
            logger.warning("[DIRECTOR] UPDATE_STRATEGY_PARAMS missing target_bot")
            return False
        raw_params: dict = cmd.params.strategy_params or {}
        if not raw_params:
            return False

        # Zero-trust guardrail: intersect with actual strategy attributes
        bot = engine.bots.get(cmd.target_bot)
        if bot and hasattr(bot, "strategy"):
            valid_keys = set(vars(bot.strategy).keys())
            sanitised  = {k: v for k, v in raw_params.items() if k in valid_keys}
            discarded  = set(raw_params.keys()) - valid_keys
            if discarded:
                logger.warning(
                    "[DIRECTOR] UPDATE_STRATEGY_PARAMS discarded unknown keys %s for bot=%s",
                    discarded, cmd.target_bot,
                )
            raw_params = sanitised

        if not raw_params:
            logger.warning(
                "[DIRECTOR] UPDATE_STRATEGY_PARAMS all keys invalid for bot=%s", cmd.target_bot
            )
            return False
        return engine.update_strategy_params(cmd.target_bot, raw_params)

    async def _handle_spawn_bot_variant(
        self, cmd: DirectorCommand, engine, persist_fn: Callable
    ) -> bool:
        source_bot = cmd.params.source_bot or cmd.target_bot
        new_bot_id = cmd.params.new_bot_id
        if not source_bot or not new_bot_id:
            logger.warning(
                "[DIRECTOR] SPAWN_BOT_VARIANT requires source_bot and new_bot_id — "
                "source=%s new_id=%s", source_bot, new_bot_id,
            )
            return False
        strategy_params = cmd.params.strategy_params or {}
        return engine.spawn_variant(source_bot, new_bot_id, strategy_params)

    async def _handle_assign_existing_strategy(
        self, cmd: DirectorCommand, engine, persist_fn: Callable
    ) -> bool:
        symbol  = cmd.params.symbol
        bot_id  = cmd.target_bot or cmd.params.source_bot
        if not symbol or not bot_id:
            logger.warning("[DIRECTOR] ASSIGN_EXISTING_STRATEGY requires symbol and target_bot")
            return False
        success = engine.assign_strategy_to_symbol(symbol, bot_id)
        if success:
            asyncio.create_task(
                persist_fn(bot_id, engine.bots[bot_id].status if bot_id in engine.bots else "ACTIVE", engine)
            )
            asyncio.create_task(self._persist_symbol_assignment(symbol, bot_id, bot_id, engine, cmd))
        return success

    async def _handle_create_new_strategy_instance(
        self, cmd: DirectorCommand, engine, persist_fn: Callable
    ) -> bool:
        symbol     = cmd.params.symbol
        algo_type  = cmd.params.algorithm_type
        new_bot_id = cmd.params.new_bot_id
        if not symbol or not algo_type or not new_bot_id:
            logger.warning(
                "[DIRECTOR] CREATE_NEW_STRATEGY_INSTANCE requires symbol, algorithm_type, new_bot_id "
                "— got symbol=%s algo=%s bot_id=%s", symbol, algo_type, new_bot_id,
            )
            return False
        # Validate algorithm type exists
        if algo_type not in engine._strategy_templates:
            logger.warning("[DIRECTOR] CREATE_NEW_STRATEGY_INSTANCE: unknown algo_type=%s", algo_type)
            return False
        strategy_params = cmd.params.strategy_params or {}
        success = engine.create_strategy_for_symbol(symbol, algo_type, strategy_params, new_bot_id)
        if success:
            asyncio.create_task(persist_fn(new_bot_id, "ACTIVE", engine))
            asyncio.create_task(
                self._persist_symbol_assignment(symbol, new_bot_id, algo_type, engine, cmd)
            )
        return success

    async def _handle_unassign_strategy(
        self, cmd: DirectorCommand, engine, persist_fn: Callable
    ) -> bool:
        symbol = cmd.params.symbol
        bot_id = cmd.target_bot
        if not symbol or not bot_id:
            logger.warning("[DIRECTOR] UNASSIGN_STRATEGY requires symbol and target_bot")
            return False
        success = engine.unassign_strategy_from_symbol(symbol, bot_id)
        if success:
            asyncio.create_task(self._deactivate_symbol_assignment(symbol, bot_id))
        return success

    async def _persist_symbol_assignment(
        self, symbol: str, bot_id: str, algo_type: str, engine, cmd: "DirectorCommand"
    ) -> None:
        """Persist a new symbol-strategy assignment to the DB."""
        try:
            from db.models import SymbolStrategyAssignment
            from sqlalchemy import select
            bot     = engine.bots.get(bot_id)
            params  = cmd.params.strategy_params
            async with self._db_factory()() as session:
                # Deactivate any prior active assignment for this symbol+bot_id
                existing = (await session.execute(
                    select(SymbolStrategyAssignment)
                    .where(SymbolStrategyAssignment.symbol == symbol)
                    .where(SymbolStrategyAssignment.bot_id == bot_id)
                    .where(SymbolStrategyAssignment.active == True)
                )).scalars().all()
                for row in existing:
                    row.active = False

                row = SymbolStrategyAssignment(
                    symbol         = symbol,
                    bot_id         = bot_id,
                    algorithm_type = algo_type,
                    assigned_by    = "director",
                    rationale      = cmd.params.reason[:500] if cmd.params.reason else None,
                    params_json    = json.dumps(params) if params else None,
                    active         = True,
                )
                session.add(row)
                await session.commit()
                logger.info("[DIRECTOR] SymbolStrategyAssignment persisted: %s → %s", symbol, bot_id)
        except Exception as exc:
            logger.warning("[DIRECTOR] SymbolStrategyAssignment persist failed: %s", exc)

    async def _deactivate_symbol_assignment(self, symbol: str, bot_id: str) -> None:
        """Mark a symbol-strategy assignment inactive in the DB."""
        try:
            from db.models import SymbolStrategyAssignment
            from sqlalchemy import select
            async with self._db_factory()() as session:
                rows = (await session.execute(
                    select(SymbolStrategyAssignment)
                    .where(SymbolStrategyAssignment.symbol == symbol)
                    .where(SymbolStrategyAssignment.bot_id == bot_id)
                    .where(SymbolStrategyAssignment.active == True)
                )).scalars().all()
                for row in rows:
                    row.active = False
                await session.commit()
        except Exception as exc:
            logger.warning("[DIRECTOR] Deactivate assignment failed: %s", exc)


# ---------------------------------------------------------------------------
# Autonomous Portfolio Director
# ---------------------------------------------------------------------------

class AutonomousPortfolioDirector:
    """
    Periodically reviews portfolio state and autonomously executes LLM-recommended
    parameter changes, halts, resumes, allocation adjustments, and bot spawning.
    """

    def __init__(
        self,
        push_fn: Callable[[dict], None],
        get_engine_fn: Callable,
        get_scanner_fn: Callable,
        db_factory: Callable,
    ) -> None:
        """
        Args:
            push_fn:        SSE push callable (_push_reflection from main.py)
            get_engine_fn:  callable returning master_engine (StrategyEngine singleton)
            get_scanner_fn: callable returning current list of scanner scan results
            db_factory:     _get_session_factory from db.database
        """
        self._push           = push_fn
        self._get_engine     = get_engine_fn
        self._get_scanner    = get_scanner_fn
        self._get_research   = None   # injected post-construction via set_research_fn()
        self._db_factory     = db_factory
        self._model          = None   # lazy raw ChatModel (kept for reference)
        self._structured_llm = None   # lazy with_structured_output runnable
        self._dispatcher     = CommandDispatcher(db_factory=db_factory)
        self._running        = False

    def set_research_fn(self, fn: Callable) -> None:
        """Inject the research agent getter so director can read the latest brief."""
        self._get_research = fn

    def _ensure_structured_llm(self):
        """Lazy-build the structured-output runnable on first use."""
        if self._structured_llm is not None:
            return self._structured_llm

        from agents.factory import swarm_factory
        model = swarm_factory.build_model(model_level="director")
        self._model = model
        if model is None:
            return None

        try:
            self._structured_llm = model.with_structured_output(ActionList)
        except (NotImplementedError, TypeError) as exc:
            logger.warning(
                "[DIRECTOR] with_structured_output not supported by %s: %s",
                type(model).__name__, exc,
            )
            self._structured_llm = None

        return self._structured_llm

    async def run(self) -> None:
        """Main background loop — warmup then cycle every INTERVAL seconds."""
        self._running = True
        await asyncio.sleep(WARMUP)
        logger.info("[DIRECTOR] Autonomous Portfolio Director started (interval=%ds)", INTERVAL)
        while self._running:
            try:
                await self._review_and_act()
            except Exception as exc:
                logger.error("[DIRECTOR] Review cycle failed: %s", exc)
            await asyncio.sleep(INTERVAL)

    async def _review_and_act(self) -> None:
        """Single review cycle: gather context → LLM → execute → log → SSE."""
        engine  = self._get_engine()
        scanner = self._get_scanner() or []

        raw_trades = await self._get_trade_history()

        # Compute per-bot win rate for the LLM (token-efficient summary)
        # Only include bot IDs that currently exist in the engine — stale variant IDs
        # from DB history would cause the LLM to hallucinate commands on non-existent bots.
        live_bot_ids = set(engine.bots.keys())
        bot_win_rates: dict[str, dict] = {}
        for t in raw_trades:
            bid = t["bot_id"] or "unknown"
            if bid not in live_bot_ids:
                continue  # skip trades from bots no longer in the engine
            if bid not in bot_win_rates:
                bot_win_rates[bid] = {"wins": 0, "total": 0, "net_pnl": 0.0}
            bot_win_rates[bid]["total"]   += 1
            bot_win_rates[bid]["wins"]    += 1 if t["win"] else 0
            bot_win_rates[bid]["net_pnl"] += t["net_pnl"]
        for v in bot_win_rates.values():
            v["win_rate"] = round(v["wins"] / v["total"], 3) if v["total"] else 0.0

        # Gather per-symbol TA snapshots for pending symbols
        pending = engine.get_pending_assignment()
        ta_snapshots: dict = {}
        for sym in pending:
            ta_snapshots[sym] = engine.get_ta_snapshot(sym)

        # Gather research edges for pending symbols
        research_edges: dict = {}
        if self._get_research:
            try:
                research_agent = self._get_research()
                if research_agent and hasattr(research_agent, "_last_brief") and research_agent._last_brief:
                    brief = research_agent._last_brief
                    for s in getattr(brief, "sentiment_by_symbol", []):
                        research_edges[s.symbol] = {
                            "sentiment":  s.sentiment,
                            "edge":       round(getattr(s, "edge", 0.0), 4),
                            "confidence": round(getattr(s, "confidence", 0.5), 3),
                        }
            except Exception as _re:
                logger.debug("[DIRECTOR] Research brief unavailable: %s", _re)

        context = {
            "bots":               engine.get_bot_states(),
            "stats":              engine.get_stats(),
            "scanner":            scanner[:10],
            "trade_history":      raw_trades[:20],
            "bot_win_rates":      bot_win_rates,
            "pending_symbols":    pending,
            "symbol_assignments": engine.get_symbol_strategy_map(),
            "available_algorithms": engine.get_available_algorithms(),
            "ta_snapshots":       ta_snapshots,
            "research_edges":     research_edges,
            "ts":                 datetime.now(timezone.utc).isoformat(),
        }

        commands: list[DirectorCommand] = await self._generate_commands(context)
        if not commands:
            logger.info("[DIRECTOR] No actions recommended this cycle")
            return

        # MAX_CMDS enforced here before entering dispatcher loop
        for cmd in commands[:MAX_CMDS]:
            if cmd.action == CommandAction.NO_ACTION:
                continue
            success = await self._dispatcher.dispatch(cmd, engine, self._persist_bot_state)
            await self._log_amend(cmd, success)
            self._push_sse(cmd, success)

    async def _get_trade_history(self) -> list[dict]:
        """Fetch recent closed trades from SQLite for win-rate analysis."""
        try:
            from db.models import ClosedTrade
            from sqlalchemy import select, desc
            async with self._db_factory()() as session:
                rows = (await session.execute(
                    select(ClosedTrade).order_by(desc(ClosedTrade.exit_time)).limit(50)
                )).scalars().all()
                return [
                    {
                        "bot_id":    r.bot_id,
                        "symbol":    r.symbol,
                        "net_pnl":   float(r.net_pnl or 0),
                        "win":       r.win,
                        "exit_time": r.exit_time.isoformat() if r.exit_time else None,
                    }
                    for r in rows
                ]
        except Exception as exc:
            logger.warning("[DIRECTOR] Trade history fetch failed: %s", exc)
            return []

    async def _generate_commands(self, context: dict) -> list[DirectorCommand]:
        """Invoke the structured-output LLM and return a validated command list."""
        try:
            structured_llm = self._ensure_structured_llm()
            if structured_llm is None:
                logger.info("[DIRECTOR] No LLM configured — skipping review cycle")
                return []

            from langchain_core.messages import HumanMessage, SystemMessage
            system = SystemMessage(content=_SYSTEM_PROMPT)
            user   = HumanMessage(content=json.dumps(context, default=str))

            result: ActionList = await structured_llm.ainvoke([system, user])
            logger.info("[DIRECTOR] Generated %d command(s)", len(result.commands))
            return result.commands

        except Exception as exc:
            logger.error("[DIRECTOR] LLM generation failed: %s", exc)
            return []

    async def _persist_bot_state(self, bot_id: str, status: str, engine) -> None:
        """Persist halt/resume state to SQLite BotState table."""
        try:
            from db.models import BotState
            from sqlalchemy import select
            bot = engine.bots.get(bot_id)
            async with self._db_factory()() as session:
                row = (await session.execute(
                    select(BotState).where(BotState.bot_id == bot_id)
                )).scalar_one_or_none()
                if row is None:
                    row = BotState(bot_id=bot_id)
                    session.add(row)
                row.status     = status
                row.allocation = bot.allocation if bot else 0.0
                await session.commit()
        except Exception as exc:
            logger.warning("[DIRECTOR] BotState persist failed for %s: %s", bot_id, exc)

    async def _log_amend(self, cmd: DirectorCommand, success: bool) -> None:
        """Write a BotAmend row to the SQLite audit trail."""
        try:
            from db.models import BotAmend
            amend = BotAmend(
                model       = CLAUDE_HAIKU_MODEL,
                action      = cmd.action.value,
                target_bot  = cmd.target_bot,
                reason      = cmd.params.reason[:500],
                impact      = cmd.params.impact[:100],
                params_json = json.dumps(cmd.params.strategy_params) if cmd.params.strategy_params else None,
            )
            async with self._db_factory()() as session:
                session.add(amend)
                await session.commit()
            logger.info(
                "[DIRECTOR] BotAmend logged: %s → %s (success=%s)",
                cmd.action.value, cmd.target_bot, success,
            )
        except Exception as exc:
            logger.warning("[DIRECTOR] BotAmend log failed: %s", exc)

    def _push_sse(self, cmd: DirectorCommand, success: bool) -> None:
        """Push director event to the SSE reflection stream for Brain tab display."""
        try:
            self._push({
                "type":       "director",
                "action":     cmd.action.value,
                "target_bot": cmd.target_bot,
                "reason":     cmd.params.reason,
                "impact":     cmd.params.impact,
                "success":    success,
                "timestamp":  int(datetime.now(timezone.utc).timestamp() * 1000),
            })
        except Exception as exc:
            logger.warning("[DIRECTOR] SSE push failed: %s", exc)
