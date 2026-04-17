"""
Autonomous Portfolio Director
==============================
Background asyncio task that runs every 15 minutes and acts as the AI brain
for portfolio-level decision making. Uses Haiku (fast/cheap tier) to:

  1. Read all bot states, stats, and latest scanner results
  2. Generate a structured JSON list of action commands
  3. Execute each command immediately (fully autonomous — no user confirmation)
  4. Log every action to the BotAmend SQLite table for audit trail
  5. Push SSE events so the UI Brain tab reflects changes in real time

Supported command actions:
  HALT_BOT               — halt a bot + persist BotState
  RESUME_BOT             — resume a halted bot + persist BotState
  ADJUST_ALLOCATION      — change allocation % on a bot
  UPDATE_STRATEGY_PARAMS — mutate strategy parameters at runtime
  SPAWN_BOT_VARIANT      — deep-copy a bot with new params, add to engine
  NO_ACTION              — Haiku recommends status quo (logged, not executed)

Pattern mirrors ReflectionEngine — pure asyncio, no threading.
"""

import asyncio
import json
import logging
import re
from datetime import datetime, timezone
from typing import Callable

logger = logging.getLogger(__name__)

INTERVAL  = 900   # 15 minutes between reviews
WARMUP    = 60    # seconds to wait for streams to stabilize on startup
MAX_CMDS  = 3     # cap commands per cycle to prevent runaway mutations

_SYSTEM_PROMPT = """You are an autonomous quantitative portfolio director.
You monitor live trading bots, their performance stats, and market scanner results.
You output ONLY a valid JSON array of action commands — no prose, no markdown.

Each command object must follow this schema exactly:
{
  "action": "HALT_BOT | RESUME_BOT | ADJUST_ALLOCATION | UPDATE_STRATEGY_PARAMS | SPAWN_BOT_VARIANT | NO_ACTION",
  "target_bot": "<bot_id or null>",
  "params": {
    "new_allocation_pct": <number, optional>,
    "reason": "<one sentence>",
    "impact": "<expected statistical effect>",
    "strategy_params": {<key: value pairs to mutate on the strategy, optional>},
    "source_bot": "<bot_id to clone from, required for SPAWN_BOT_VARIANT>",
    "new_bot_id": "<unique id for variant, required for SPAWN_BOT_VARIANT>"
  }
}

Rules:
- Output [] if no action is needed
- Only HALT bots with clear negative evidence (fill_rate < 0.1 AND yield24h < -0.5)
- ADJUST_ALLOCATION changes must be between 5% and 40%
- UPDATE_STRATEGY_PARAMS must use existing attribute names from the bot strategy
- SPAWN_BOT_VARIANT is for trying a parameter variant without halting the original
- Maximum 3 commands per cycle
- Always include reason and impact in params
"""


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
    ):
        """
        Args:
            push_fn:        SSE push callable (_push_reflection from main.py)
            get_engine_fn:  callable returning master_engine (StrategyEngine singleton)
            get_scanner_fn: callable returning current list of scanner scan results
            db_factory:     _get_session_factory from db.database
        """
        self._push        = push_fn
        self._get_engine  = get_engine_fn
        self._get_scanner = get_scanner_fn
        self._db_factory  = db_factory
        self._model       = None   # lazy-loaded Haiku client
        self._running     = False

    def _ensure_model(self):
        """Lazy-load the Haiku LLM client on first use."""
        if self._model is None:
            from agents.factory import swarm_factory
            self._model = swarm_factory.build_model(model_level="fast")
        return self._model

    async def run(self):
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

    async def _review_and_act(self):
        """Single review cycle: gather context → LLM → execute → log → SSE."""
        engine  = self._get_engine()
        scanner = self._get_scanner() or []

        context = {
            "bots":    engine.get_bot_states(),
            "stats":   engine.get_stats(),
            "scanner": scanner[:10],   # top 10 scanner results for token efficiency
            "ts":      datetime.now(timezone.utc).isoformat(),
        }

        commands = await self._generate_commands(context)
        if not commands:
            logger.info("[DIRECTOR] No actions recommended this cycle")
            return

        for cmd in commands[:MAX_CMDS]:
            action = cmd.get("action", "")
            if action == "NO_ACTION":
                continue
            success = self._execute_command(cmd, engine)
            await self._log_amend(cmd, success)
            self._push_sse(cmd, success)

    async def _generate_commands(self, context: dict) -> list[dict]:
        """Call Haiku with portfolio context, parse the JSON command array response."""
        try:
            model = self._ensure_model()
            from langchain_core.messages import HumanMessage, SystemMessage
            system = SystemMessage(content=_SYSTEM_PROMPT)
            user   = HumanMessage(content=json.dumps(context, default=str))
            # Run sync LLM call in threadpool to avoid blocking the event loop
            response = await asyncio.get_event_loop().run_in_executor(
                None,
                lambda: model.invoke([system, user])
            )
            raw = response.content if hasattr(response, "content") else str(response)
            # Extract JSON array — strip any accidental markdown fences
            match = re.search(r'\[.*\]', raw, re.DOTALL)
            if not match:
                logger.warning("[DIRECTOR] No JSON array in LLM response: %s", raw[:200])
                return []
            commands = json.loads(match.group())
            if not isinstance(commands, list):
                return []
            logger.info("[DIRECTOR] Generated %d command(s)", len(commands))
            return commands
        except Exception as exc:
            logger.error("[DIRECTOR] LLM generation failed: %s", exc)
            return []

    def _execute_command(self, cmd: dict, engine) -> bool:
        """Execute a single command against the strategy engine. Returns success bool."""
        action     = cmd.get("action", "")
        target_bot = cmd.get("target_bot")
        params     = cmd.get("params", {})
        reason     = params.get("reason", "Director recommendation")

        try:
            if action == "HALT_BOT" and target_bot:
                success = engine.halt_bot(target_bot, reason=reason)
                if success:
                    asyncio.create_task(self._persist_bot_state(target_bot, "HALTED", engine))
                return success

            elif action == "RESUME_BOT" and target_bot:
                success = engine.resume_bot(target_bot)
                if success:
                    asyncio.create_task(self._persist_bot_state(target_bot, "ACTIVE", engine))
                return success

            elif action == "ADJUST_ALLOCATION" and target_bot:
                pct = float(params.get("new_allocation_pct", 0))
                return engine.adjust_allocation(target_bot, pct)

            elif action == "UPDATE_STRATEGY_PARAMS" and target_bot:
                strategy_params = params.get("strategy_params", {})
                if strategy_params:
                    return engine.update_strategy_params(target_bot, strategy_params)
                return False

            elif action == "SPAWN_BOT_VARIANT":
                source_id       = params.get("source_bot", target_bot)
                new_bot_id      = params.get("new_bot_id")
                strategy_params = params.get("strategy_params", {})
                if source_id and new_bot_id:
                    return engine.spawn_variant(source_id, new_bot_id, strategy_params)
                return False

            else:
                logger.warning("[DIRECTOR] Unknown or incomplete action: %s / %s", action, target_bot)
                return False

        except Exception as exc:
            logger.error("[DIRECTOR] Execute failed for %s/%s: %s", action, target_bot, exc)
            return False

    async def _persist_bot_state(self, bot_id: str, status: str, engine):
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

    async def _log_amend(self, cmd: dict, success: bool):
        """Write a BotAmend row to the SQLite audit trail."""
        try:
            from db.models import BotAmend
            params          = cmd.get("params", {})
            action          = cmd.get("action", "UNKNOWN")
            target_bot      = cmd.get("target_bot")
            strategy_params = params.get("strategy_params", {})

            amend = BotAmend(
                model       = "claude-haiku-4-5",
                action      = action,
                target_bot  = target_bot,
                reason      = params.get("reason", "")[:500],
                impact      = params.get("impact", "")[:100],
                params_json = json.dumps(strategy_params) if strategy_params else None,
            )
            async with self._db_factory()() as session:
                session.add(amend)
                await session.commit()
            logger.info("[DIRECTOR] BotAmend logged: %s → %s (success=%s)",
                        action, target_bot, success)
        except Exception as exc:
            logger.warning("[DIRECTOR] BotAmend log failed: %s", exc)

    def _push_sse(self, cmd: dict, success: bool):
        """Push director event to the SSE reflection stream for Brain tab display."""
        params = cmd.get("params", {})
        try:
            self._push({
                "type":       "director",
                "action":     cmd.get("action", ""),
                "target_bot": cmd.get("target_bot"),
                "reason":     params.get("reason", ""),
                "impact":     params.get("impact", ""),
                "success":    success,
                "timestamp":  int(datetime.now(timezone.utc).timestamp() * 1000),
            })
        except Exception as exc:
            logger.warning("[DIRECTOR] SSE push failed: %s", exc)
