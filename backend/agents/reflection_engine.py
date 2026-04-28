"""
Reflection Engine — Brain Tab Content Generator
=================================================
Generates 3 types of reflections pushed to the SSE stream:

1. Market Observations (60s cadence) — pure template, zero LLM
2. Position Analysis (120s cadence) — pure template, zero LLM
3. Trade Learnings (on fill) — Haiku, max_tokens=100

All observations and position analyses are derived directly from
strategy engine internal state (EMA spreads, Bollinger positions,
momentum readings). No LLM calls, no cost.
"""

import asyncio
import json
import logging
import pathlib
from datetime import datetime, timezone
from enum import Enum
from typing import Callable, Optional
from config import GEMINI_3_1_FLASH_LITE_MODEL, GEMINI_COST_IN, GEMINI_COST_OUT

logger = logging.getLogger(__name__)


class FailureClass(str, Enum):
    BAD_PREDICTION    = "BAD_PREDICTION"    # model was directionally wrong despite high confidence
    TIMING            = "TIMING"            # correct direction, but entry/exit timing degraded P&L
    EXECUTION_QUALITY = "EXECUTION"         # slippage or fill quality was the primary drag
    MARKET_SHOCK      = "MARKET_SHOCK"      # exogenous catalyst (news, macro) invalidated signal


def classify_failure(
    signal_confidence: float,
    realized_pnl: float,
    slippage: float,
    signal_price: float,
    news_shock: bool = False,
) -> FailureClass:
    """
    Deterministic failure classification for losing trades.
    Priority: MARKET_SHOCK > EXECUTION_QUALITY > BAD_PREDICTION > TIMING
    """
    if news_shock:
        return FailureClass.MARKET_SHOCK
    slippage_pct = abs(slippage / signal_price) if signal_price > 0 else 0.0
    if slippage_pct > 0.02:
        return FailureClass.EXECUTION_QUALITY
    if realized_pnl < 0 and signal_confidence > 0.70:
        return FailureClass.BAD_PREDICTION
    return FailureClass.TIMING

# Cadence constants (seconds)
OBSERVE_INTERVAL = 60
POSITION_INTERVAL = 120
WARMUP_DELAY = 15  # Let streams connect first


class ReflectionEngine:
    def __init__(
        self,
        push_fn: Callable[[dict], None],
        get_states_fn: Callable[[], dict],
        get_positions_fn: Optional[Callable[[], list]] = None,
    ):
        """
        Args:
            push_fn:          _push_reflection(data) from main.py
            get_states_fn:    master_engine.get_all_states
            get_positions_fn: callable returning Alpaca positions list (or None)
        """
        self._push = push_fn
        self._get_states = get_states_fn
        self._get_positions = get_positions_fn
        self._running = False

    async def run(self):
        """Main background loop — runs both observation cadences concurrently."""
        self._running = True
        await asyncio.sleep(WARMUP_DELAY)
        logger.info("[REFLECTION] Engine started (observe=%ds, position=%ds)",
                     OBSERVE_INTERVAL, POSITION_INTERVAL)

        await asyncio.gather(
            self._observe_loop(),
            self._position_loop(),
        )

    async def _observe_loop(self):
        """Emits market observation reflections from strategy state."""
        while self._running:
            try:
                self._emit_market_observations()
            except Exception as e:
                logger.warning("[REFLECTION] Observe error: %s", e)
            await asyncio.sleep(OBSERVE_INTERVAL)

    async def _position_loop(self):
        """Emits position analysis reflections when positions exist."""
        while self._running:
            try:
                self._emit_position_analysis()
            except Exception as e:
                logger.warning("[REFLECTION] Position analysis error: %s", e)
            await asyncio.sleep(POSITION_INTERVAL)

    # ------------------------------------------------------------------
    # Market Observations (zero LLM — pure template)
    # ------------------------------------------------------------------

    def _emit_market_observations(self):
        """Reads strategy internal state and emits human-readable observations."""
        states = self._get_states()
        if not states:
            return

        now = datetime.now(timezone.utc).isoformat()

        for symbol, bot_states in states.items():
            for state in bot_states:
                strategy_id = state.get("strategy", "unknown")
                bot_status = state.get("bot_status", "UNKNOWN")

                # Skip HALTED bots in observations
                if bot_status == "HALTED":
                    text = f"{state.get('name', strategy_id)} is HALTED — awaiting manual activation"
                    self._push({
                        "type": "observe",
                        "strategy": strategy_id,
                        "symbol": symbol,
                        "text": text,
                        "state": state,
                        "timestamp": now,
                    })
                    continue

                text = self._format_observation(state, symbol)
                if text:
                    self._push({
                        "type": "observe",
                        "strategy": strategy_id,
                        "symbol": symbol,
                        "text": text,
                        "state": state,
                        "timestamp": now,
                    })

    def _format_observation(self, state: dict, symbol: str) -> str:
        """Converts raw strategy state into a human-readable observation string."""
        strategy_id = state.get("strategy", "")
        name = state.get("name", strategy_id)

        if strategy_id == "momentum-alpha":
            spread = state.get("spread_pct", 0)
            bias = state.get("bias", "NEUTRAL")
            ema_s = state.get("ema_short", 0)
            ema_l = state.get("ema_long", 0)
            near = state.get("near_crossover", False)
            cross_hint = " ⚡ Near crossover threshold" if near else ""
            return (
                f"{name} on {symbol}: EMA spread {spread:+.4f}% "
                f"(short=${ema_s:,.2f} / long=${ema_l:,.2f}) — "
                f"Bias: {bias}{cross_hint}"
            )

        elif strategy_id == "statarb-gamma":
            if state.get("status") == "warming_up":
                ticks = state.get("ticks_collected", 0)
                return f"{name} on {symbol}: Warming up ({ticks}/20 ticks collected)"
            zone = state.get("zone", "NEUTRAL")
            pos = state.get("position_in_band_pct", 50)
            sma = state.get("sma", 0)
            upper = state.get("upper_band", 0)
            lower = state.get("lower_band", 0)
            return (
                f"{name} on {symbol}: Price at {pos:.0f}th pctile of Bollinger band "
                f"(SMA=${sma:,.2f}, band=[${lower:,.2f}–${upper:,.2f}]) — Zone: {zone}"
            )

        elif strategy_id == "hft-sniper":
            momentum = state.get("momentum_pct", 0)
            cooldown = state.get("cooldown_remaining", 0)
            status = state.get("status", "HALTED")
            if status == "HALTED":
                return f"{name}: HALTED — awaiting manual activation"
            cd_str = f" (cooldown: {cooldown} ticks)" if cooldown > 0 else ""
            return f"{name} on {symbol}: Tick momentum {momentum:+.5f}%{cd_str}"

        return None

    # ------------------------------------------------------------------
    # Position Analysis (zero LLM — pure template)
    # ------------------------------------------------------------------

    def _emit_position_analysis(self):
        """Reads open positions and cross-references with strategy state."""
        if not self._get_positions:
            return

        try:
            positions = self._get_positions()
        except Exception as e:
            logger.debug("[REFLECTION] Could not fetch positions: %s", e)
            return

        if not positions:
            return

        now = datetime.now(timezone.utc).isoformat()
        states = self._get_states()

        for pos in positions:
            symbol = pos.get("symbol", "?")
            side = pos.get("side", "?")
            pnl = float(pos.get("unrealized_pnl", 0) or 0)
            entry = float(pos.get("avg_entry_price", 0) or 0)
            current = float(pos.get("current_price", 0) or 0)
            pnl_pct = (pnl / (entry * float(pos.get("size", 1) or 1))) * 100 if entry else 0

            # Cross-reference with strategy bias
            strategy_bias = "UNKNOWN"
            strategy_name = "System"
            if symbol in states:
                for s in states[symbol]:
                    if s.get("bias"):
                        strategy_bias = s["bias"]
                        strategy_name = s.get("name", s.get("strategy", "?"))
                        break
                    elif s.get("zone"):
                        strategy_bias = s["zone"]
                        strategy_name = s.get("name", s.get("strategy", "?"))
                        break

            # Generate position assessment
            if pnl > 0:
                assessment = f"Profitable ({pnl_pct:+.2f}%) — holding"
                if strategy_bias == "BEARISH" and side == "LONG":
                    assessment += " ⚠️ Strategy bias turned bearish, consider tightening stop"
                elif strategy_bias == "BULLISH" and side == "LONG":
                    assessment += " ✓ Aligned with bullish strategy signal"
            elif pnl < 0:
                assessment = f"Underwater ({pnl_pct:+.2f}%)"
                if abs(pnl_pct) > 1.5:
                    assessment += " ⚠️ Approaching drawdown zone"
                elif strategy_bias == "BULLISH" and side == "LONG":
                    assessment += " — Strategy still bullish, holding"
                else:
                    assessment += " — Monitoring for exit signal"
            else:
                assessment = "Flat — awaiting price movement"

            text = (
                f"Position: {side} {symbol} (entry ${entry:,.2f} → ${current:,.2f}) "
                f"P&L: ${pnl:+,.2f} ({pnl_pct:+.2f}%) — {assessment} "
                f"[{strategy_name} bias: {strategy_bias}]"
            )

            self._push({
                "type": "calculate",
                "strategy": strategy_name.lower().replace(" ", "-"),
                "symbol": symbol,
                "text": text,
                "timestamp": now,
            })

    # ------------------------------------------------------------------
    # Trade Learning (Haiku, max_tokens=100 — called on fill)
    # ------------------------------------------------------------------

    async def learn_from_execution(self, execution_data: dict):
        """
        Called after each trade fill. Generates a one-sentence AI insight
        using Haiku (max_tokens=100), then persists to BotAmend table.

        Gracefully falls back to template if no LLM key is configured.
        """
        strategy = execution_data.get("strategy", "unknown")
        symbol = execution_data.get("symbol", "?")
        action = execution_data.get("action", "?")
        fill_price = execution_data.get("fill_price", 0)
        slippage = execution_data.get("slippage", 0)
        confidence = execution_data.get("confidence", 0)
        qty = execution_data.get("qty", 0)
        realized_pnl      = execution_data.get("realized_pnl")       # only for SELL fills
        entry_price       = execution_data.get("entry_price")        # only for SELL fills
        market_conditions = execution_data.get("market_conditions")  # JSON string from execution agent

        now = datetime.utcnow()

        # Compute hold duration for SELL fills (async DB lookup)
        hold_duration_min = execution_data.get("hold_duration_min")
        if hold_duration_min is None and action == "SELL":
            hold_duration_min = await self._compute_hold_duration(strategy, symbol)

        pnl_pct = 0.0
        if realized_pnl is not None and entry_price and entry_price > 0 and qty > 0:
            pnl_pct = (realized_pnl / (entry_price * qty)) * 100

        # Try LLM insight (Haiku, max_tokens=100)
        insight = None
        try:
            from agents.factory import swarm_factory
            model = swarm_factory.build_model(model_level="fast")
            if model:
                from langchain_core.messages import SystemMessage, HumanMessage
                sys_msg = SystemMessage(content=(
                    "You are a quant trading analyst reviewing paper trades (equities and crypto). "
                    "All prices and slippage are in USD. qty is a fractional amount. "
                    "For BUY trades: assess entry timing quality — was confidence well-calibrated "
                    "to market momentum? Was it a good entry point? "
                    "For SELL trades: assess round-trip profitability — did the exit capture gains "
                    "well? Was the exit premature or well-timed given the return? "
                    "Produce ONE concise sentence (max 35 words). "
                    "Reference specific USD figures and percentages from the data. No markdown, no preamble."
                ))

                if action == "SELL" and realized_pnl is not None and entry_price is not None:
                    trade_context = (
                        f"Strategy: {strategy} | Action: {action} | Symbol: {symbol}\n"
                        f"Qty: {qty:.6f} | Fill: ${fill_price:.2f} | Slippage: ${slippage:.4f} | Conf: {confidence:.0%}\n"
                        f"Entry: ${entry_price:.2f} | Realized PnL: ${realized_pnl:+.4f} | Return: {pnl_pct:+.2f}%"
                    )
                else:
                    trade_context = (
                        f"Strategy: {strategy} | Action: {action} | Symbol: {symbol}\n"
                        f"Qty: {qty:.6f} | Fill: ${fill_price:.2f} | Slippage: ${slippage:.4f} | Conf: {confidence:.0%}"
                    )

                user_msg = HumanMessage(content=trade_context)
                response = await model.ainvoke(
                    [sys_msg, user_msg],
                    max_tokens=250,
                )
                insight = response.content.strip()

                # Log token usage for cost tracking
                try:
                    usage = getattr(response, "usage_metadata", None) or {}
                    t_in  = usage.get("input_tokens", 0)
                    t_out = usage.get("output_tokens", 0)
                    cost  = (t_in * GEMINI_COST_IN + t_out * GEMINI_COST_OUT) / 1_000_000
                    from db.database import _get_session_factory
                    from db.models import LLMUsage
                    async with _get_session_factory()() as _s:
                        _s.add(LLMUsage(
                            model=GEMINI_3_1_FLASH_LITE_MODEL,
                            tokens_in=t_in,
                            tokens_out=t_out,
                            cost_usd=cost,
                            purpose="reflection",
                        ))
                        await _s.commit()
                except Exception as _le:
                    logger.debug("[REFLECTION] LLM usage log failed: %s", _le)

        except Exception as e:
            logger.debug("[REFLECTION] LLM insight failed, using template: %s", e)

        # Fallback template if no LLM
        if not insight:
            slip_quality = "excellent" if abs(slippage) < 0.5 else "acceptable" if abs(slippage) < 2 else "poor"
            if action == "SELL" and realized_pnl is not None:
                outcome = "profitable" if realized_pnl > 0 else "unprofitable"
                insight = (
                    f"{strategy} {action} {symbol} at ${fill_price:.2f}: "
                    f"{outcome} round-trip (PnL=${realized_pnl:+.4f}, {pnl_pct:+.2f}%) "
                    f"with {slip_quality} slippage."
                )
            else:
                insight = (
                    f"{strategy} {action} {symbol} filled at ${fill_price:.2f} "
                    f"with {slip_quality} slippage (${slippage:.4f}). "
                    f"Signal confidence was {confidence:.0%}."
                )

        impact = f"Slip=${slippage:.4f} | Conf={confidence:.0%}"

        # Classify failure and compute Brier Score contribution (for losing trades only)
        failure_cls: Optional[str] = None
        brier_contrib: Optional[float] = None
        outcome = 1 if (realized_pnl is not None and realized_pnl > 0) else 0

        if realized_pnl is not None:
            if realized_pnl <= 0:
                failure_cls = classify_failure(
                    signal_confidence=confidence,
                    realized_pnl=realized_pnl,
                    slippage=slippage,
                    signal_price=float(execution_data.get("signal_price", fill_price or 1.0)),
                ).value
            # Brier contribution: (forecast - outcome)^2 for every closed trade
            brier_contrib = round((confidence - outcome) ** 2, 6)

            # Feed into in-memory calibration tracker
            try:
                from risk.calibration import calibration_tracker
                calibration_tracker.log(strategy, confidence, outcome)
            except Exception as _ce:
                logger.debug("[REFLECTION] Calibration log failed: %s", _ce)

        # Persist to BotAmend + ReflectionLog
        try:
            from db.database import _get_session_factory
            from db.models import BotAmend, ReflectionLog, CalibrationRecord
            async with _get_session_factory()() as session:
                session.add(BotAmend(
                    model=strategy,
                    action=f"TRADE:{action}",
                    reason=insight,
                    impact=impact,
                    timestamp=now,
                ))
                session.add(ReflectionLog(
                    strategy=strategy,
                    symbol=symbol,
                    action=action,
                    insight=insight,
                    tokens_used=execution_data.get("_tokens_used"),
                    failure_class=failure_cls,
                    brier_contribution=brier_contrib,
                    entry_price=entry_price,
                    exit_price=fill_price if action == "SELL" else None,
                    hold_duration_min=hold_duration_min,
                    market_conditions=market_conditions,
                    timestamp=now,
                ))
                if realized_pnl is not None:
                    session.add(CalibrationRecord(
                        strategy=strategy,
                        forecast=round(confidence, 4),
                        outcome=outcome,
                        brier_contribution=brier_contrib,
                    ))
                await session.commit()
        except Exception as e:
            logger.warning("[REFLECTION] Failed to persist BotAmend/ReflectionLog: %s", e)

        # Compound learning: invoke post_mortem agent for ALL closed trades and persist to knowledge base
        if realized_pnl is not None:
            effective_cls = failure_cls if failure_cls else "WIN"
            pm_result = await self._invoke_post_mortem(execution_data, effective_cls)
            if pm_result:
                if pm_result.get("knowledge_entry"):
                    self._append_knowledge(pm_result, execution_data, effective_cls)
                
                # Immediate Parameter Adjustment
                adjustment = pm_result.get("adjustment")
                if adjustment and isinstance(adjustment, dict):
                    try:
                        from strategy.engine import master_engine
                        logger.info("[REFLECTION] Immediate parameter update for %s: %s", strategy, adjustment)
                        master_engine.update_strategy_params(strategy, adjustment)
                        asyncio.create_task(self._persist_bot_parameters(strategy, adjustment, "post_mortem"))
                    except Exception as e:
                        logger.warning("[REFLECTION] Failed to apply immediate parameter update: %s", e)

        # Push to SSE stream
        self._push({
            "type": "learning",
            "strategy": strategy,
            "symbol": symbol,
            "text": insight,
            "action": action,
            "fill_price": fill_price,
            "slippage": slippage,
            "confidence": confidence,
            "timestamp": now.isoformat(),
        })

        logger.info("[REFLECTION] Trade learning: %s", insight[:80])

    # ------------------------------------------------------------------
    # Compound Learning (Post-Mortem → Knowledge Base)
    # ------------------------------------------------------------------

    async def _invoke_post_mortem(self, execution_data: dict, outcome_cls: str) -> Optional[dict]:
        """
        Calls the post_mortem agent persona with trade data (win or loss).
        Returns parsed JSON dict (failure_class, root_cause, adjustment, knowledge_entry)
        or None on any failure. Budget: 250 tokens via fast tier (Haiku).
        """
        try:
            from agents.factory import swarm_factory
            from langchain_core.messages import HumanMessage

            model = swarm_factory.build_model(model_level="fast", max_tokens=250)
            if not model:
                return None

            system_msg = swarm_factory.get_system_prompt("post_mortem")
            if not system_msg:
                logger.debug("[REFLECTION] post_mortem persona not found in factory")
                return None
            
            # Extract historical failures for this bot+symbol
            strategy = execution_data.get("strategy", "unknown")
            symbol   = execution_data.get("symbol", "?")
            
            kb_path = pathlib.Path(__file__).resolve().parent.parent / "knowledge" / "failure_log.jsonl"
            recent_failures = []
            if kb_path.exists():
                with open(kb_path, "r", encoding="utf-8") as f:
                    for line in f:
                        try:
                            item = json.loads(line)
                            if item.get("strategy") == strategy and item.get("symbol") == symbol:
                                recent_failures.append({
                                    "outcome_class": item.get("outcome_class", item.get("failure_class")),
                                    "knowledge_entry": item.get("knowledge_entry")
                                })
                        except json.JSONDecodeError:
                            pass
                recent_failures = recent_failures[-3:] # keep last 3

            # Force actionable JSON parameters
            system_msg.content += (
                "\n\nCRITICAL INSTRUCTION: You must generate an actionable parameter tweak in the 'adjustment' field. "
                "Instead of just text, return a specific JSON dictionary representing the parameter change "
                "e.g. {\"MOMENTUM_THRESHOLD\": 0.0005}. Look at 'historical_failures' to avoid repeating the same mistakes or to double down on winning patterns."
            )

            trade_payload = json.dumps({
                "strategy":          strategy,
                "symbol":            symbol,
                "signal_confidence": execution_data.get("confidence", 0),
                "realized_pnl":      execution_data.get("realized_pnl", 0),
                "slippage_pct":      abs(execution_data.get("slippage", 0) /
                                         max(execution_data.get("signal_price",
                                             execution_data.get("fill_price", 1)) or 1, 0.01)),
                "entry_price":       execution_data.get("entry_price", 0),
                "exit_price":        execution_data.get("fill_price", 0),
                "hold_duration_min": execution_data.get("hold_duration_min", 0),
                "trade_outcome_class": outcome_cls,
                "historical_failures": recent_failures,
            })

            response = await model.ainvoke(
                [system_msg, HumanMessage(content=trade_payload)],
                max_tokens=200,
            )

            try:
                usage = getattr(response, "usage_metadata", None) or {}
                t_in  = usage.get("input_tokens", 0)
                t_out = usage.get("output_tokens", 0)
                cost  = (t_in * GEMINI_COST_IN + t_out * GEMINI_COST_OUT) / 1_000_000
                from db.database import _get_session_factory
                from db.models import LLMUsage
                async with _get_session_factory()() as _s:
                    _s.add(LLMUsage(
                        model=GEMINI_3_1_FLASH_LITE_MODEL,
                        tokens_in=t_in, tokens_out=t_out,
                        cost_usd=cost, purpose="post_mortem",
                    ))
                    await _s.commit()
            except Exception as _le:
                logger.debug("[REFLECTION] Post-mortem cost log failed: %s", _le)

            raw = response.content.strip()
            # Strip markdown fences if the model wraps in ```json ... ```
            if raw.startswith("```"):
                raw = raw.split("```")[1]
                if raw.startswith("json"):
                    raw = raw[4:]
            return json.loads(raw.strip())

        except Exception as exc:
            logger.debug("[REFLECTION] Post-mortem invocation failed: %s", exc)
            return None

    def _append_knowledge(self, entry: dict, execution_data: dict, outcome_cls: str) -> None:
        """Appends one structured entry to backend/knowledge/failure_log.jsonl."""
        kb_path = pathlib.Path(__file__).resolve().parent.parent / "knowledge" / "failure_log.jsonl"
        kb_path.parent.mkdir(parents=True, exist_ok=True)
        record = {
            "timestamp":       datetime.utcnow().isoformat() + "Z",
            "strategy":        execution_data.get("strategy", "unknown"),
            "symbol":          execution_data.get("symbol", "?"),
            "outcome_class":   outcome_cls,
            "failure_class":   outcome_cls, # retained for backward compatibility
            "knowledge_entry": entry.get("knowledge_entry", ""),
            "adjustment":      entry.get("adjustment", ""),
        }
        try:
            with open(kb_path, "a", encoding="utf-8") as f:
                f.write(json.dumps(record) + "\n")
            logger.info("[REFLECTION] Knowledge appended: %s", record["knowledge_entry"][:80])
        except Exception as exc:
            logger.warning("[REFLECTION] Failed to append knowledge: %s", exc)

    async def _persist_bot_parameters(self, bot_id: str, params: dict, updated_by: str) -> None:
        """Upsert the active strategy parameters into BotParameterControl."""
        try:
            from db.database import _get_session_factory
            from db.models import BotParameterControl
            from sqlalchemy import select
            import json as _json
            async with _get_session_factory()() as session:
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
                logger.info("[REFLECTION] BotParameterControl updated for %s", bot_id)
        except Exception as exc:
            logger.warning("[REFLECTION] BotParameterControl persist failed: %s", exc)

    async def _compute_hold_duration(self, bot_id: str, symbol: str) -> int | None:
        """Returns minutes between the last BUY fill and now for this bot+symbol pair."""
        try:
            from db.database import _get_session_factory
            from db.models import SignalRecord, ExecutionRecord as _ER
            from sqlalchemy import select, and_
            async with _get_session_factory()() as session:
                stmt = (
                    select(_ER.timestamp)
                    .join(SignalRecord, _ER.signal_id == SignalRecord.id)
                    .where(and_(
                        SignalRecord.strategy == bot_id,
                        SignalRecord.symbol   == symbol,
                        SignalRecord.action   == "BUY",
                        _ER.status            == "FILLED",
                    ))
                    .order_by(_ER.timestamp.desc())
                    .limit(1)
                )
                row = (await session.execute(stmt)).scalar_one_or_none()
                if row:
                    ts = row.replace(tzinfo=None) if row.tzinfo else row
                    delta = datetime.utcnow() - ts
                    return max(1, int(delta.total_seconds() / 60))
        except Exception as exc:
            logger.debug("[REFLECTION] hold_duration_min lookup failed: %s", exc)
        return None

    def stop(self):
        self._running = False

