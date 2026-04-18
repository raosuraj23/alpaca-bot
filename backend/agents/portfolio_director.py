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
  HALT_BOT               — halt a bot + persist BotState
  RESUME_BOT             — resume a halted bot + persist BotState
  ADJUST_ALLOCATION      — change allocation % on a bot (hard-clamped 5–40%)
  UPDATE_STRATEGY_PARAMS — mutate strategy parameters at runtime (key-intersected)
  SPAWN_BOT_VARIANT      — deep-copy a bot with new params, add to engine
  NO_ACTION              — Haiku recommends status quo (logged, not executed)

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

Rules:
- Only HALT bots with clear negative evidence (fill_rate < 0.1 AND yield24h < -0.5)
- Bots with win_rate < 0.35 AND total >= 10 trades are strong candidates for HALT or ADJUST_ALLOCATION down
- Bots with win_rate > 0.60 AND total >= 5 trades may warrant ADJUST_ALLOCATION increase
- ADJUST_ALLOCATION requires new_allocation_pct (a float 5.0–40.0). NEVER emit ADJUST_ALLOCATION without it.
- Allocation adjustments must be between 5% and 40%
- UPDATE_STRATEGY_PARAMS and SPAWN_BOT_VARIANT MUST use ONLY the parameter names listed in the
  STRATEGY PARAMETER REGISTRY below. Any other name will be silently rejected by the engine.
- SPAWN_BOT_VARIANT tries a parameter variant without halting the original
- Recommend NO_ACTION or an empty commands list if no intervention is warranted
- Always provide a reason and expected impact for each action
- Maximum 3 commands per cycle

STRATEGY PARAMETER REGISTRY — exact attribute names the engine accepts:

  momentum-alpha (crypto EMA crossover):
    alpha_short  float  0.05–0.40   EMA short-window smoothing factor (higher = faster response)
    alpha_long   float  0.01–0.15   EMA long-window smoothing factor  (lower = smoother trend)

  statarb-gamma (Bollinger Band mean reversion):
    lookback_period  int    10–50   Bollinger Band window in bars (higher = smoother bands)
    sigma_multiplier float  1.5–3.0 Band width in standard deviations (higher = fewer but stronger signals)

  hft-sniper (tick momentum):
    MOMENTUM_THRESHOLD  float  0.0001–0.001  Minimum tick momentum % to trigger a signal
    MOMENTUM_WINDOW     int    2–10          Ticks used to compute momentum slope
    COOLDOWN_TICKS      int    3–20          Ticks to wait after a signal before re-arming

  equity-momentum (equity EMA crossover):
    alpha_short  float  0.05–0.40
    alpha_long   float  0.01–0.15

  equity-rsi (RSI mean reversion):
    rsi_period    int    7–21    RSI lookback window
    rsi_oversold  float  20–40   RSI level that triggers BUY (default 30)
    rsi_overbought float 60–80   RSI level that triggers SELL (default 70)

  equity-pairs (SPY/QQQ pairs):
    z_threshold  float  1.0–3.0  Z-score threshold to enter a trade (default 2.0)
    window       int    10–60    Spread rolling window in bars (default 30)

For variant bots (bot_id ending in -v1, -v2, etc.), use the same parameters as the source bot.
"""

# ---------------------------------------------------------------------------
# Pydantic command schema
# ---------------------------------------------------------------------------

class CommandAction(str, Enum):
    HALT_BOT               = "HALT_BOT"
    RESUME_BOT             = "RESUME_BOT"
    ADJUST_ALLOCATION      = "ADJUST_ALLOCATION"
    UPDATE_STRATEGY_PARAMS = "UPDATE_STRATEGY_PARAMS"
    SPAWN_BOT_VARIANT      = "SPAWN_BOT_VARIANT"
    NO_ACTION              = "NO_ACTION"


class CommandParams(BaseModel):
    new_allocation_pct: Optional[float] = Field(None, description="Target allocation 5–40%")
    reason: str  = Field("Director recommendation", description="One-sentence rationale")
    impact: str  = Field("Not specified", description="Expected statistical effect")
    strategy_params: Optional[dict]  = Field(None, description="Key-value pairs to mutate on strategy")
    source_bot:      Optional[str]   = Field(None, description="Bot ID to clone from")
    new_bot_id:      Optional[str]   = Field(None, description="Unique ID for the variant bot")


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

    def __init__(self) -> None:
        self._registry: dict[CommandAction, Callable] = {
            CommandAction.HALT_BOT:               self._handle_halt_bot,
            CommandAction.RESUME_BOT:             self._handle_resume_bot,
            CommandAction.ADJUST_ALLOCATION:      self._handle_adjust_allocation,
            CommandAction.UPDATE_STRATEGY_PARAMS: self._handle_update_strategy_params,
            CommandAction.SPAWN_BOT_VARIANT:      self._handle_spawn_bot_variant,
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
        # Zero-trust guardrail: both IDs required
        if not source_bot or not new_bot_id:
            logger.warning(
                "[DIRECTOR] SPAWN_BOT_VARIANT requires source_bot and new_bot_id — "
                "source=%s new_id=%s", source_bot, new_bot_id,
            )
            return False
        strategy_params = cmd.params.strategy_params or {}
        return engine.spawn_variant(source_bot, new_bot_id, strategy_params)


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
        self._db_factory     = db_factory
        self._model          = None   # lazy raw ChatModel (kept for reference)
        self._structured_llm = None   # lazy with_structured_output runnable
        self._dispatcher     = CommandDispatcher()
        self._running        = False

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

        context = {
            "bots":          engine.get_bot_states(),
            "stats":         engine.get_stats(),
            "scanner":       scanner[:10],
            "trade_history": raw_trades[:20],   # recent 20 trades for LLM context
            "bot_win_rates": bot_win_rates,     # pre-aggregated for token efficiency
            "ts":            datetime.now(timezone.utc).isoformat(),
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
