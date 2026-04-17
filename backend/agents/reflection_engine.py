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
import logging
from datetime import datetime
from typing import Callable, Optional

logger = logging.getLogger(__name__)

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

        now = datetime.utcnow().isoformat()

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

        now = datetime.utcnow().isoformat()
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

        now = datetime.utcnow()

        # Try LLM insight (Haiku, max_tokens=100)
        insight = None
        try:
            from agents.factory import swarm_factory
            model = swarm_factory.build_model(model_level="fast")
            if model:
                from langchain_core.messages import SystemMessage, HumanMessage
                sys_msg = SystemMessage(content=(
                    "You are a quant trading analyst reviewing crypto paper trades. "
                    "All prices and slippage are in USD. qty is a fractional coin amount "
                    "(e.g. 0.0003 BTC, 0.005 ETH — never grams or kg). "
                    "Produce ONE concise sentence (max 30 words) analysing slippage quality, "
                    "confidence calibration, or market conditions. "
                    "Reference specific USD figures from the data. No markdown, no preamble."
                ))
                user_msg = HumanMessage(content=(
                    f"Strategy: {strategy} | Action: {action} | Symbol: {symbol}\n"
                    f"Qty: {qty:.6f} coins | Fill price: ${fill_price:.2f} USD | "
                    f"Slippage: ${slippage:.4f} USD | Signal confidence: {confidence:.0%}"
                ))
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
                    # Haiku pricing: $0.80/M input, $4.00/M output
                    cost  = (t_in * 0.80 + t_out * 4.00) / 1_000_000
                    from db.database import _get_session_factory
                    from db.models import LLMUsage
                    async with _get_session_factory()() as _s:
                        _s.add(LLMUsage(
                            model="claude-haiku-4-5",
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
            insight = (
                f"{strategy} {action} {symbol} filled at ${fill_price:.2f} "
                f"with {slip_quality} slippage (${slippage:.4f}). "
                f"Signal confidence was {confidence:.0%}."
            )

        impact = f"Slip=${slippage:.4f} | Conf={confidence:.0%}"

        # Persist to BotAmend + ReflectionLog
        try:
            from db.database import _get_session_factory
            from db.models import BotAmend, ReflectionLog
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
                    timestamp=now,
                ))
                await session.commit()
        except Exception as e:
            logger.warning("[REFLECTION] Failed to persist BotAmend/ReflectionLog: %s", e)

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

    def stop(self):
        self._running = False
"""
Description: Dedicated reflection engine that generates market observations (60s, no LLM),
position analysis (120s, no LLM), and post-trade learnings (on fill, Haiku max_tokens=100).
"""
