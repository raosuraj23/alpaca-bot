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
import pathlib
from datetime import datetime, timezone, timedelta
from enum import Enum
from typing import Callable, Optional

from pydantic import BaseModel, Field, field_validator
from config import GEMINI_3_1_FLASH_LITE_MODEL
from state import action_items as _ai_state

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
- CRITICAL: target_bot MUST be set to an exact bot id from the 'bots' context for HALT_BOT,
  RESUME_BOT, ADJUST_ALLOCATION, and UPDATE_STRATEGY_PARAMS. If you cannot name a specific bot
  from the list, emit NO_ACTION instead — never emit a command with a missing target_bot.
- Only HALT bots with clear negative evidence (fill_rate < 0.1 AND yield24h < -0.5)
- A $0.00 24h yield alone is NOT sufficient to halt — no trades may simply mean no signal fired.
  Check fill_rate and trade_history before halting.
- Bots with win_rate < 0.35 AND total >= 10 trades are strong candidates for HALT or ADJUST_ALLOCATION down
- Bots with win_rate > 0.60 AND total >= 5 trades may warrant ADJUST_ALLOCATION increase
- ADJUST_ALLOCATION requires new_allocation_pct (a float 5.0–40.0). NEVER emit ADJUST_ALLOCATION without it.
- Allocation adjustments must be between 5% and 40%
- UPDATE_STRATEGY_PARAMS and SPAWN_BOT_VARIANT MUST use ONLY the parameter names in the registry below.
- SPAWN_BOT_VARIANT tries a parameter variant without halting the original
- Recommend NO_ACTION or an empty commands list if no intervention is warranted
- Always provide a reason and expected impact for each action
- Maximum 3 commands per cycle (pending assignments count toward this cap)
- kb_lessons contains recent post-mortem findings with concrete adjustment suggestions.
  Translate them into UPDATE_STRATEGY_PARAMS commands using ONLY these valid parameter keys:
    confidence_threshold, momentum_threshold, rsi_threshold, stop_loss_pct,
    max_position_pct, min_profit_to_exit_pct, warmup_ticks, MOMENTUM_THRESHOLD,
    STOP_LOSS_PCT, MIN_PROFIT_TO_EXIT_PCT, alpha_short, alpha_long, rsi_period,
    rsi_oversold, rsi_overbought, z_threshold, sigma_multiplier, edge_threshold.
  Example: kb_lesson "Raise confidence threshold from 0.92 to 0.95 for BTC/USD HFT entries" →
    UPDATE_STRATEGY_PARAMS target_bot="hft-sniper" params={"MOMENTUM_THRESHOLD": 0.95}
  Example: kb_lesson "Reduce momentum threshold for SOL/USD from 0.92 to 0.85" →
    UPDATE_STRATEGY_PARAMS target_bot="momentum-alpha" params={"alpha_short": 0.15}
  Example: kb_lesson "Raise signal confidence threshold from 0.92 to 0.95" →
    UPDATE_STRATEGY_PARAMS target_bot="momentum-alpha" params={"confidence_threshold": 0.95}
  Emit one UPDATE_STRATEGY_PARAMS per kb_lesson that names a numeric threshold change.
  If metrics_trend shows win_rate is declining, prioritise HALT_BOT or ADJUST_ALLOCATION down for worst bots.

═══════════════════════════════════════════════════════════════
POSITION COUNT MANAGEMENT (LIQUIDATE_POSITION):
═══════════════════════════════════════════════════════════════
The context includes position_count (current open positions) and position_limit (max allowed).
When position_count >= position_limit AND a new high-priority signal is pending:
  - Emit LIQUIDATE_POSITION for the weakest position to free a slot.
  - Use params.symbol to specify the position to close and params.reason for the rationale.
  - "Weakest" = most negative unrealized PnL, or a position that no bot is actively managing.
  - NEVER liquidate a position without a specific symbol in params.symbol.
  - Only liquidate if there is a clear reason (freeing cap for a better opportunity).

═══════════════════════════════════════════════════════════════
STRATEGY PARAMETER REGISTRY — exact attribute names:
═══════════════════════════════════════════════════════════════
  momentum-alpha:        alpha_short (0.05–0.40), alpha_long (0.01–0.15),
                         min_profit_to_exit_pct (0.001–0.010)
  statarb-gamma:         lookback_period (10–50), sigma_multiplier (1.5–3.0),
                         min_profit_to_exit_pct (0.001–0.010)
  hft-sniper:            MOMENTUM_THRESHOLD (0.0001–0.001), MOMENTUM_WINDOW (2–10),
                         COOLDOWN_TICKS (3–20), STOP_LOSS_PCT (0.003–0.020),
                         MIN_PROFIT_TO_EXIT_PCT (0.001–0.010)
  equity-momentum:       alpha_short (0.05–0.40), alpha_long (0.01–0.15),
                         min_profit_to_exit_pct (0.001–0.010)
  equity-rsi:            rsi_period (7–21), rsi_oversold (20–40), rsi_overbought (60–80),
                         min_profit_to_exit_pct (0.001–0.010)
  equity-pairs:          leg_a str (e.g. "NVDA"), leg_b str (e.g. "AMD"), z_threshold (1.0–3.0), window (10–60)
  crypto-pairs:          leg_a str (e.g. "BTC/USD"), leg_b str (e.g. "ETH/USD"), z_threshold (1.0–3.0), window (10–60)
  equity-breakout:       atr_period (7–28), breakout_multiplier (1.0–3.0), volume_threshold (1.2–3.0), cooldown_ticks (5–40)
  vwap-reversion:        sigma_threshold (1.0–2.5), warmup_ticks (15–60)
  news-momentum:         edge_threshold (0.04–0.12), momentum_ticks (3–10), hold_limit_ticks (10–60)
  crypto-range-scalp:    bb_period (10–40), bb_sigma (1.0–2.5), min_range_ticks (5–20), cooldown_ticks (3–15)
  covered-call:          (no patchable params)
  protective-put:        (no patchable params)

═══════════════════════════════════════════════════════════════
HAIKU ANALYST RECOMMENDATIONS (from live position analysis):
═══════════════════════════════════════════════════════════════
The context key haiku_recommendations contains observations generated by the
Haiku market analyst from live position and bot data. Treat these as additional
signal — you may act on them, partially act, or override with your own assessment.
Cite the item title in your reason string if you act on one.
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
    LIQUIDATE_POSITION          = "LIQUIDATE_POSITION"
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

    @field_validator("strategy_params", mode="before")
    @classmethod
    def _coerce_strategy_params(cls, v):
        """Coerce LLM string outputs like 'KEY=val' or '{...}' into a proper dict."""
        if v is None or isinstance(v, dict):
            return v
        if isinstance(v, str):
            v = v.strip()
            # Try JSON first
            try:
                parsed = json.loads(v)
                if isinstance(parsed, dict):
                    return parsed
            except Exception:
                pass
            # Try key=value pairs (e.g. "MOMENTUM_THRESHOLD=0.85, COOLDOWN_TICKS=10")
            result = {}
            for part in v.split(","):
                part = part.strip()
                if "=" in part:
                    k, _, val = part.partition("=")
                    k = k.strip()
                    val = val.strip()
                    try:
                        result[k] = float(val) if "." in val else int(val)
                    except ValueError:
                        result[k] = val
            return result if result else None
        return v


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
            CommandAction.LIQUIDATE_POSITION:           self._handle_liquidate_position,
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
        success = engine.adjust_allocation(cmd.target_bot, clamped_pct)
        if success:
            asyncio.create_task(persist_fn(cmd.target_bot, "ACTIVE", engine))
        return success

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
        # Bot objects ARE the strategy instances — there is no separate .strategy attr
        bot = engine.bots.get(cmd.target_bot)
        if bot:
            sanitised  = {k: v for k, v in raw_params.items() if hasattr(bot, k) and not callable(getattr(bot, k))}
            discarded  = set(raw_params.keys()) - set(sanitised.keys())
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
        success = engine.update_strategy_params(cmd.target_bot, raw_params)
        if success:
            asyncio.create_task(self._persist_bot_parameters(cmd.target_bot, raw_params, "director"))
        return success

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

    async def _handle_liquidate_position(
        self, cmd: DirectorCommand, engine, persist_fn: Callable
    ) -> bool:
        symbol = cmd.params.symbol
        if not symbol:
            logger.warning("[DIRECTOR] LIQUIDATE_POSITION missing params.symbol")
            return False
        try:
            from agents.execution_agent import execution_agent, _get_trading_client

            trading_client = _get_trading_client()
            if not trading_client:
                logger.warning("[DIRECTOR] LIQUIDATE_POSITION: trading client unavailable")
                return False
            norm = symbol.replace("/", "")
            positions = trading_client.get_all_positions()
            held_qty = 0.0
            current_price = 0.0
            for p in positions:
                if p.symbol.upper() == norm.upper() or p.symbol.upper() == symbol.upper():
                    held_qty += float(p.qty)
                    if current_price == 0.0 and p.current_price:
                        current_price = float(p.current_price)
            if held_qty <= 0:
                logger.warning("[DIRECTOR] LIQUIDATE_POSITION: no position found for %s", symbol)
                return False

            signal = {
                "action": "SELL",
                "symbol": symbol,
                "qty": held_qty,
                "bot": cmd.target_bot or "director",
                "strategy": "director-liquidation",
                "confidence": 1.0,
                "price": current_price,
                "meta": {"reason": cmd.params.reason},
            }
            result = execution_agent.execute(
                signal,
                signal_price=current_price if current_price > 0 else None,
            )
            success = result is not None and getattr(result, "status", None) not in ("FAILED", None)
            if success and result:
                await self._write_director_closed_trade(
                    bot_id=signal["bot"],
                    symbol=symbol,
                    exit_price=result.fill_price,
                    qty=result.qty,
                )
            logger.info(
                "[DIRECTOR] LIQUIDATE_POSITION %s qty=%.4f success=%s",
                symbol, held_qty, success,
            )
            return success
        except Exception as exc:
            logger.error("[DIRECTOR] LIQUIDATE_POSITION failed for %s: %s", symbol, exc)
            return False

    async def _write_director_closed_trade(
        self, bot_id: str, symbol: str, exit_price: float, qty: float
    ) -> None:
        """Write a ClosedTrade record for a director-initiated SELL by looking up the prior BUY."""
        try:
            import re as _re
            _CRYPTO_RE = _re.compile(r'^[A-Z]{2,6}(USD[TC]?|BTC|ETH)$')
            asset_class = "CRYPTO" if ("/" in symbol or bool(_CRYPTO_RE.match(symbol))) else "EQUITY"
            from db.models import ExecutionRecord, SignalRecord, ClosedTrade
            from sqlalchemy import select, desc
            from datetime import datetime, timezone
            async with self._db_factory()() as session:
                buy_stmt = (
                    select(ExecutionRecord.fill_price, ExecutionRecord.timestamp)
                    .join(SignalRecord, ExecutionRecord.signal_id == SignalRecord.id)
                    .where(SignalRecord.strategy == bot_id)
                    .where(SignalRecord.symbol == symbol)
                    .where(SignalRecord.action == "BUY")
                    .where(ExecutionRecord.status == "FILLED")
                    .where(ExecutionRecord.fill_price > 0)
                    .order_by(desc(ExecutionRecord.timestamp))
                    .limit(1)
                )
                buy_row = (await session.execute(buy_stmt)).first()
                entry_price = float(buy_row.fill_price) if buy_row else exit_price
                entry_time = buy_row.timestamp if buy_row else None
                pnl = (exit_price - entry_price) * qty
                session.add(ClosedTrade(
                    bot_id=bot_id, symbol=symbol, qty=qty,
                    avg_entry_price=entry_price, avg_exit_price=exit_price,
                    realized_pnl=pnl, net_pnl=pnl, win=pnl > 0,
                    entry_time=entry_time,
                    exit_time=datetime.now(timezone.utc).replace(tzinfo=None),
                    asset_class=asset_class,
                    confidence=1.0,
                ))
                await session.commit()
                logger.info("[DIRECTOR] ClosedTrade written for %s %s pnl=%.4f", bot_id, symbol, pnl)
        except Exception as ct_err:
            logger.warning("[DIRECTOR] ClosedTrade write failed for %s: %s", symbol, ct_err)

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

    async def _persist_bot_parameters(self, bot_id: str, params: dict, updated_by: str) -> None:
        """Upsert the active strategy parameters into BotParameterControl."""
        try:
            from db.models import BotParameterControl
            from sqlalchemy import select
            import json as _json
            async with self._db_factory()() as session:
                row = (await session.execute(
                    select(BotParameterControl).where(BotParameterControl.bot_id == bot_id)
                )).scalar_one_or_none()
                if not row:
                    row = BotParameterControl(bot_id=bot_id, params_json="{}")
                    session.add(row)
                
                # Merge parameters with existing to retain un-updated keys
                existing = {}
                if row.params_json:
                    try:
                        existing = _json.loads(row.params_json)
                    except Exception:
                        pass
                existing.update(params)
                row.params_json = _json.dumps(existing)
                row.updated_by = updated_by
                await session.commit()
                logger.info("[DIRECTOR] BotParameterControl updated for %s", bot_id)
        except Exception as exc:
            logger.warning("[DIRECTOR] BotParameterControl persist failed: %s", exc)


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

    def _load_kb_context(self, n: int = 20) -> list[dict]:
        """Read the last n entries from failure_log.jsonl + metrics_log trend for Director context."""
        from collections import deque
        kb_path = pathlib.Path(__file__).resolve().parent.parent / "knowledge" / "failure_log.jsonl"
        entries = []
        if kb_path.exists():
            try:
                tail = deque(kb_path.open(encoding="utf-8"), maxlen=n)
                for line in tail:
                    try:
                        entries.append(json.loads(line))
                    except json.JSONDecodeError:
                        pass
            except OSError:
                pass

        # Append daily metrics trend so Director knows if performance is improving or declining
        metrics_path = kb_path.parent / "metrics_log.jsonl"
        if metrics_path.exists():
            try:
                tail = deque(metrics_path.open(encoding="utf-8"), maxlen=7)
                daily = [json.loads(l) for l in tail if l.strip()]
                if len(daily) >= 2:
                    trend = "improving" if daily[-1].get("win_rate", 0) > daily[0].get("win_rate", 0) else "declining"
                    entries.append({
                        "source": "metrics_trend",
                        "trend": trend,
                        "latest_win_rate": daily[-1].get("win_rate"),
                        "latest_sharpe": daily[-1].get("sharpe"),
                        "days_tracked": len(daily),
                    })
            except Exception:
                pass

        return entries

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
        from strategy.equity_algorithms import _is_market_hours
        self._running = True
        await asyncio.sleep(WARMUP)
        logger.info("[DIRECTOR] Autonomous Portfolio Director started (interval=%ds)", INTERVAL)
        while self._running:
            if not _is_market_hours():
                await asyncio.sleep(60)
                continue
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

        # Compute per-bot stats using the 48h lookback window
        cutoff = datetime.now(timezone.utc) - timedelta(hours=48)
        bot_win_rates = await self._compute_strategy_stats(cutoff)
        
        # Filter to only live bots
        live_bot_ids = set(engine.bots.keys())
        bot_win_rates = {k: v for k, v in bot_win_rates.items() if k in live_bot_ids}

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
                if research_agent:
                    brief = research_agent.get_latest_brief()  # TTL-aware (35 min)
                    if brief:
                        for s in getattr(brief, "sentiment_by_symbol", []):
                            research_edges[s.symbol] = {
                                "sentiment":  s.sentiment,
                                "edge":       round(getattr(s, "edge", 0.0), 4),
                                "confidence": round(getattr(s, "confidence", 0.5), 3),
                            }
            except Exception as _re:
                logger.debug("[DIRECTOR] Research brief unavailable: %s", _re)

        haiku_items = _ai_state.get_items()

        # Fetch live position count for LIQUIDATE_POSITION decisions
        position_count = 0
        position_limit = int(__import__("os").getenv("MAX_CONCURRENT_POSITIONS", "15"))
        try:
            from deps import trading_client as _tc
            if _tc:
                position_count = len(_tc.get_all_positions())
        except Exception:
            pass

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
            "kb_lessons":         self._load_kb_context(10),
            "haiku_recommendations": haiku_items,
            "position_count":     position_count,
            "position_limit":     position_limit,
            "ts":                 datetime.now(timezone.utc).isoformat(),
        }

        commands: list[DirectorCommand] = await self._generate_commands(context)
        if not commands:
            logger.info("[DIRECTOR] No actions recommended this cycle")
            return

        # Pre-dispatch validation: silently drop malformed commands rather than
        # wasting a BotAmend row on them.
        valid_commands = []
        for cmd in commands[:MAX_CMDS]:
            if cmd.action == CommandAction.NO_ACTION:
                continue
            rejection = self._validate_command(cmd, engine)
            if rejection:
                logger.warning("[DIRECTOR] Command dropped — %s", rejection)
            else:
                valid_commands.append(cmd)

        for cmd in valid_commands:
            success = await self._dispatcher.dispatch(cmd, engine, self._persist_bot_state)
            await self._log_amend(cmd, success)
            self._push_sse(cmd, success)

    async def _compute_strategy_stats(self, cutoff: datetime) -> dict[str, dict]:
        """Return per-strategy aggregates from CalibrationRecord + ReflectionLog."""
        from db.models import CalibrationRecord, ReflectionLog
        from sqlalchemy import select

        stats: dict[str, dict] = {}

        try:
            async with self._db_factory()() as session:
                cal_rows = (await session.execute(
                    select(CalibrationRecord).where(CalibrationRecord.timestamp >= cutoff)
                )).scalars().all()

                for r in cal_rows:
                    strat = r.strategy or "unknown"
                    if strat not in stats:
                        stats[strat] = {
                            "wins": 0, "total": 0, "conf_sum": 0.0,
                            "brier_sum": 0.0, "failure_classes": [],
                        }
                    stats[strat]["total"] += 1
                    stats[strat]["wins"] += int(r.outcome or 0)
                    stats[strat]["conf_sum"] += float(r.forecast or 0)
                    stats[strat]["brier_sum"] += float(r.brier_contribution or 0)

                ref_rows = (await session.execute(
                    select(ReflectionLog.strategy, ReflectionLog.failure_class)
                    .where(ReflectionLog.timestamp >= cutoff)
                    .where(ReflectionLog.failure_class.is_not(None))
                )).all()

            for r in ref_rows:
                strat = r.strategy or "unknown"
                if strat in stats and r.failure_class:
                    stats[strat]["failure_classes"].append(r.failure_class)

            # Compute derived metrics
            for strat, s in stats.items():
                n = s["total"] or 1
                s["win_rate"] = round(s["wins"] / n, 4)
                s["avg_confidence"] = round(s["conf_sum"] / n, 4)
                s["avg_brier"] = round(s["brier_sum"] / n, 6)
                fcs = s["failure_classes"]
                s["dominant_failure"] = max(set(fcs), key=fcs.count) if fcs else None
                del s["failure_classes"]
        except Exception as exc:
            logger.warning("[DIRECTOR] Stats computation failed: %s", exc)

        return stats

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

    def _validate_command(self, cmd: DirectorCommand, engine) -> str | None:
        """
        Sanity-check a command before dispatching.
        Returns an error string if the command should be dropped, else None.
        """
        requires_target = {
            CommandAction.HALT_BOT,
            CommandAction.RESUME_BOT,
            CommandAction.ADJUST_ALLOCATION,
            CommandAction.UPDATE_STRATEGY_PARAMS,
            CommandAction.SPAWN_BOT_VARIANT,
        }
        if cmd.action in requires_target:
            if not cmd.target_bot:
                return f"{cmd.action.value} missing target_bot (reason: {cmd.params.reason[:80]})"
            if cmd.target_bot not in engine.bots:
                return f"{cmd.action.value} target_bot='{cmd.target_bot}' not in active bots"
        if cmd.action == CommandAction.ADJUST_ALLOCATION and cmd.params.new_allocation_pct is None:
            return f"ADJUST_ALLOCATION missing new_allocation_pct for bot={cmd.target_bot}"
        if cmd.action in (CommandAction.ASSIGN_EXISTING_STRATEGY, CommandAction.UNASSIGN_STRATEGY,
                          CommandAction.LIQUIDATE_POSITION) and not cmd.params.symbol:
            return f"{cmd.action.value} missing params.symbol"
        return None

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
            if not result:
                logger.warning("[DIRECTOR] LLM returned empty structured output (likely rate limited)")
                return []
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
            from sqlalchemy import select
            amend = BotAmend(
                model       = GEMINI_3_1_FLASH_LITE_MODEL,
                action      = cmd.action.value,
                target_bot  = cmd.target_bot,
                reason      = cmd.params.reason[:500],
                impact      = cmd.params.impact[:100],
                params_json = json.dumps(cmd.params.strategy_params) if cmd.params.strategy_params else None,
            )
            async with self._db_factory()() as session:
                session.add(amend)
                
                # Update status of AI recommendations if acted upon
                ai_items = _ai_state.get_items()
                acted_titles = [item.get("title") for item in ai_items if item.get("title") and item["title"] in cmd.params.reason]
                
                if acted_titles:
                    pending = (await session.execute(
                        select(BotAmend)
                        .where(BotAmend.action.like("ACTION_ITEM:%"))
                        .where(BotAmend.status == "pending")
                    )).scalars().all()
                    
                    for p in pending:
                        for title in acted_titles:
                            if p.reason and p.reason.startswith(title + ":"):
                                p.status = "acted"
                                logger.info("[DIRECTOR] Marked AI recommendation as acted: %s", title)
                                
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
                "timestamp":  datetime.now(timezone.utc).isoformat(),
            })
        except Exception as exc:
            logger.warning("[DIRECTOR] SSE push failed: %s", exc)
