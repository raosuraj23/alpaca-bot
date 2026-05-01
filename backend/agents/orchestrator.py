"""
Orchestrator Engine — Stateful Conversation + Command Routing
==============================================================
The system brain. Receives natural language from the UI OrchestratorChat AND
high-probability quant signals from the deterministic TA engine.

Two entry points:
  process_chat(user_text)       — human-driven interaction (oversight, queries,
                                   manual commands). Zero automatic trade execution.
  process_signal(signal_event)  — called by the signal pipeline ONLY AFTER the
                                   free deterministic math (Golden Cross + RSI gate
                                   + Volume surge) has confirmed a setup. This is
                                   where API tokens are spent: the LLM fetches
                                   recent sentiment context and decides whether to
                                   approve or reject the quant signal.

Command routing (from process_chat):
  HALT_BOT         → master_engine.halt_bot(target_bot)
  RESUME_BOT       → master_engine.resume_bot(target_bot)
  ADJUST_ALLOCATION → master_engine.adjust_allocation(target_bot, pct)
  TRIGGER_BACKTEST → (Phase 4 — logged only)
  QUERY_RISK       → returns risk_agent.get_risk_status() inline
  PLACE_ORDER      → risk_agent.process() → execution_agent.execute() → Alpaca

Signal approval pipeline (from process_signal):
  SignalEvent (BUY) → LLM Supervisor node (sentiment + context analysis)
                    → APPROVED → ExecutionAgent → Alpaca
                    → REJECTED → QuantSignal.llm_approved = 'REJECTED', logged
"""

import asyncio
import json
import logging
import re
from datetime import datetime, timezone, timedelta
from langchain_core.messages import HumanMessage, AIMessage, SystemMessage
from config import (
    GEMINI_3_FLASH_MODEL, GEMINI_3_1_FLASH_LITE_MODEL, GEMINI_2_5_FLASH_LITE_MODEL,
    GEMINI_COST_IN, GEMINI_COST_OUT
)

from agents.factory import swarm_factory

logger = logging.getLogger(__name__)


async def _log_llm_cost(response, model_name: str, purpose: str,
                        price_in: float, price_out: float) -> None:
    try:
        usage = getattr(response, "usage_metadata", None) or {}
        t_in  = usage.get("input_tokens", 0)
        t_out = usage.get("output_tokens", 0)
        if not (t_in or t_out):
            return
        cost = (t_in * price_in + t_out * price_out) / 1_000_000
        from db.database import _get_session_factory
        from db.models import LLMUsage
        async with _get_session_factory()() as _s:
            _s.add(LLMUsage(model=model_name, tokens_in=t_in,
                            tokens_out=t_out, cost_usd=cost, purpose=purpose))
            await _s.commit()
    except Exception as exc:
        logger.debug("[ORCHESTRATOR] cost log skipped: %s", exc)


# History window: keep last N messages (each turn = 1 Human + 1 AI = 2 messages)
HISTORY_WINDOW = 6   # = 3 full turns

# Minimum bars in the buffer before the signal pipeline is active
# (matches quant.signals.MIN_BARS)
_SIGNAL_MIN_BARS = 201

# User message keywords that trigger a live Alpaca positions+account fetch
_LIVE_FETCH_KEYWORDS: frozenset[str] = frozenset({
    "position", "positions", "holding", "holdings", "balance",
    "equity", "account", "sell", "buy", "liquidate", "close", "order",
})


class OrchestratorEngine:
    def __init__(self):
        # chat tier — Claude Haiku with prompt caching for command parsing (300t)
        self.model = swarm_factory.build_model(model_level="chat")
        # signal tier — Gemini 2.5 Flash Lite primary voter (150t)
        self.signal_model = swarm_factory.build_model(model_level="signal")
        # second voter — Gemini 3.1 Flash Lite independent signal approval (150t)
        self.secondary_voter = swarm_factory.build_model(model_level="fast", max_tokens=150)
        raw_prompt = swarm_factory.get_system_prompt("orchestrator-agent")
        self.system_prompt = SystemMessage(content=raw_prompt.content)
        self._history: list = []   # rolling in-memory conversation buffer

    # ------------------------------------------------------------------
    # Public Interface
    # ------------------------------------------------------------------

    async def process_chat(self, user_text: str) -> str:
        if not self.model:
            return (
                "⚠️ System Offline: No API keys mapped in .env. "
                "The LLM Swarm is currently sleeping. Please inject your keys to activate."
            )

        self._history.append(HumanMessage(content=user_text))
        ctx = await self._build_context_message(user_text)
        messages = [self.system_prompt, ctx] + self._history[-HISTORY_WINDOW:]

        try:
            # --- Round 1: initial LLM response + command dispatch ---
            response = await self.model.ainvoke(messages)
            reply = response.content
            await _log_llm_cost(response, GEMINI_3_1_FLASH_LITE_MODEL,
                                "orchestrator_chat", GEMINI_COST_IN, GEMINI_COST_OUT)

            commands = self._extract_commands(reply)
            results = []
            for cmd in commands:
                result = self._dispatch_command(cmd)
                if result:
                    results.append(result)

            # --- Round 2: feed tool results back so LLM can act on them ---
            if results:
                result_text = "\n".join(f"→ {r}" for r in results)
                followup_messages = (
                    [self.system_prompt, ctx]
                    + self._history[-HISTORY_WINDOW:]
                    + [
                        AIMessage(content=reply),
                        HumanMessage(
                            content=(
                                f"[TOOL RESULTS]\n{result_text}\n\n"
                                "Based on the above results, complete your response to the user. "
                                "Follow the Trade Confirmation Protocol if applicable."
                            )
                        ),
                    ]
                )
                followup_response = await self.model.ainvoke(followup_messages)
                await _log_llm_cost(
                    followup_response, GEMINI_3_1_FLASH_LITE_MODEL,
                    "orchestrator_chat_followup", GEMINI_COST_IN, GEMINI_COST_OUT,
                )
                followup_reply = followup_response.content

                followup_commands = self._extract_commands(followup_reply)
                followup_results = []
                for cmd in followup_commands:
                    r = self._dispatch_command(cmd)
                    if r:
                        followup_results.append(r)

                final_reply = followup_reply
                if followup_results:
                    lines = "\n".join(f"→ {r}" for r in followup_results)
                    final_reply += f"\n\n**Execution Results:**\n{lines}"

                self._history.append(AIMessage(content=final_reply))
                return final_reply

            # No command results — return round-1 reply as-is
            self._history.append(AIMessage(content=reply))
            return reply

        except Exception as e:
            logger.error("[ORCHESTRATOR] LLM invocation failed: %s", e)
            return f"[SWARM ERROR] {str(e)}"

    def clear_history(self):
        """Resets the conversation context window."""
        self._history = []
        logger.info("[ORCHESTRATOR] Conversation history cleared.")

    async def _build_context_message(self, user_text: str) -> SystemMessage:
        """Build a grounded context block injected before LLM inference.

        Always includes cached bot/risk state. Fetches live Alpaca positions
        and account only when user_text contains a trigger keyword.
        """
        from strategy.engine import master_engine
        from agents.risk_agent import risk_agent
        from agents.execution_agent import _get_trading_client

        lines: list[str] = ["[LIVE CONTEXT — use this as ground truth, do not invent data]"]

        try:
            bot_states = master_engine.get_bot_states()
            bot_summary = " | ".join(
                f"{b['id']} {b['status']} {b['allocationPct']:.0f}%"
                for b in bot_states[:8]
            )
            lines.append(f"Bot states: {bot_summary}")
        except Exception:
            lines.append("Bot states: unavailable")

        try:
            risk = risk_agent.get_risk_status()
            lines.append(
                f"Risk: kill_switch={risk.get('kill_switch_active', 'unknown')}  "
                f"drawdown={risk.get('daily_drawdown_pct', 0):.2%}"
            )
        except Exception:
            lines.append("Risk: unavailable")

        lower = user_text.lower()
        if any(kw in lower for kw in _LIVE_FETCH_KEYWORDS):
            try:
                tc = _get_trading_client()
                if tc:
                    positions = tc.get_all_positions()
                    account = tc.get_account()
                    pos_parts = [
                        f"{p.symbol} qty={p.qty} price=${float(p.current_price or 0):.2f} "
                        f"unreal_pl={float(p.unrealized_pl or 0):+.2f}"
                        for p in positions
                    ] or ["none"]
                    lines.append(f"Positions (live): {' | '.join(pos_parts)}")
                    lines.append(
                        f"Account equity: ${float(account.equity):,.2f}  "
                        f"buying_power: ${float(account.buying_power):,.2f}"
                    )
                else:
                    lines.append("[Alpaca unavailable — do not fabricate position data]")
            except Exception as exc:
                logger.warning("[ORCHESTRATOR] Live fetch failed: %s", exc)
                lines.append("[Alpaca unavailable — do not fabricate position data]")

        return SystemMessage(content="\n".join(lines))

    # ------------------------------------------------------------------
    # Quant Signal Handoff — LLM Supervisor Node
    # ------------------------------------------------------------------

    async def process_signal(self, signal_event: dict) -> dict:
        """
        Called by the signal pipeline after the deterministic TA engine emits a
        BUY signal. This is the ONLY place where the LLM is woken up for trade
        decisions — it does NOT run on every tick, only after all three
        mathematical conditions (Golden Cross + RSI gate + Volume surge) pass.

        The LLM's job here is narrow and explicit:
          1. Acknowledge the quant setup (structured signal_event dict).
          2. Provide brief sentiment context (recent news tone, macro bias).
          3. Emit APPROVED or REJECTED with a one-sentence rationale.

        The response is parsed for a JSON block:
            {"llm_decision": "APPROVED" | "REJECTED", "rationale": "..."}

        Returns:
            {
                "llm_decision": "APPROVED" | "REJECTED" | "ERROR",
                "rationale":    str,
                "signal_event": dict,   # original signal passed through
            }
        """
        if not self.signal_model and not self.secondary_voter and not self.model:
            logger.warning("[ORCHESTRATOR] LLM offline — auto-approving quant signal for %s",
                           signal_event.get("asset"))
            return {
                "llm_decision": "APPROVED",
                "rationale":    "LLM offline — signal auto-approved by default.",
                "signal_event": signal_event,
            }

        # --- XGBoost probability gate (runs before LLM spend) ---
        try:
            from predict.feature_extractor import extract_features, compute_market_implied_prob
            from predict.xgboost_classifier import xgb_classifier
            _feats = extract_features(signal_event)
            _mkt_p = compute_market_implied_prob(_feats)
            _gate  = xgb_classifier.gate(_feats, _mkt_p)
            signal_event["xgboost_prob"]        = _gate["xgboost_prob"]
            signal_event["market_implied_prob"] = _gate["market_implied_prob"]
            signal_event["edge"]                = _gate["edge"]
            signal_event["market_edge"]         = _gate["edge"]   # alias for DB column
            signal_event["mispricing_z_score"]  = _gate.get("mispricing_z_score")
            signal_event["signal_features"]     = _feats.tolist()
            if not _gate["approved"]:
                logger.info("[ORCHESTRATOR] XGBoost gate rejected signal — %s", _gate["reason"])
                return {
                    "llm_decision": "REJECTED",
                    "rationale":    f"[XGBOOST GATE] {_gate['reason']}",
                    "signal_event": signal_event,
                }
        except Exception as _xgb_exc:
            logger.debug("[ORCHESTRATOR] XGBoost gate skipped: %s", _xgb_exc)
        # --- End XGBoost gate ---

        # Normalise TA fields — strategies store them either at top-level or in meta{}
        _meta = signal_event.get("meta") or {}
        if not signal_event.get("ema_50") and _meta.get("ema_short"):
            signal_event["ema_50"] = _meta["ema_short"]
        if not signal_event.get("ema_200") and _meta.get("ema_long"):
            signal_event["ema_200"] = _meta["ema_long"]

        asset      = signal_event.get("asset", "UNKNOWN")
        signal_ts  = signal_event.get("timestamp", "")
        ema50      = signal_event.get("ema_50") or 0
        ema200     = signal_event.get("ema_200") or 0
        rsi_val    = signal_event.get("rsi_14") or 0
        vsr        = signal_event.get("volume_surge_ratio") or 0
        cond       = signal_event.get("conditions", {})

        def _fmt(v: float) -> str:
            return f"{v:.2f}" if v else "N/A"

        # Fetch recent lessons for this asset and strategy from the knowledge base
        recent_lessons = ""
        try:
            import pathlib
            kb_path = pathlib.Path(__file__).resolve().parent.parent / "knowledge" / "failure_log.jsonl"
            if kb_path.exists():
                strategy = signal_event.get('bot', 'unknown')
                lessons = []
                _kb_cutoff = datetime.now(timezone.utc) - timedelta(days=14)
                with open(kb_path, "r", encoding="utf-8") as f:
                    for line in f:
                        try:
                            item = json.loads(line)
                            ts_str = item.get("timestamp", "")
                            if ts_str:
                                try:
                                    item_ts = datetime.fromisoformat(ts_str.replace("Z", "+00:00"))
                                    if item_ts < _kb_cutoff:
                                        continue
                                except ValueError:
                                    pass
                            if item.get("strategy") == strategy and item.get("symbol") == asset:
                                entry = item.get("knowledge_entry")
                                if entry:
                                    lessons.append(entry)
                        except json.JSONDecodeError:
                            pass
                if lessons:
                    lessons_text = "\n".join(f"- {l}" for l in lessons[-3:])
                    recent_lessons = f"\nRecent Lessons (Historical Failures for this setup):\n{lessons_text}\n"
                    recent_lessons += "CRITICAL: If the current context matches these failure patterns, you MUST REJECT this signal."
        except Exception as kb_err:
            logger.debug("[ORCHESTRATOR] KB read failed: %s", kb_err)

        supervisor_prompt = (
            f"IMPORTANT: Output ONLY the JSON code block below. "
            f"No markdown headers, no preamble, no analysis text — nothing before or after the block.\n\n"
            f"Asset: {asset}\n"
            f"Signal timestamp: {signal_ts}\n"
            f"Strategy: {signal_event.get('bot', 'unknown')}\n"
            f"Conditions: golden_cross={cond.get('golden_cross')}, "
            f"rsi_gate={cond.get('rsi_gate')}, volume_surge={cond.get('volume_surge')}\n"
            f"EMA-50={_fmt(ema50)}, EMA-200={_fmt(ema200)}, RSI={_fmt(rsi_val)}, vol_ratio={_fmt(vsr)}×\n"
            f"Note: N/A indicators are not tracked by this strategy — treat them as neutral.\n\n"
            f"Your role: sentiment/context validation only (the TA math is already confirmed).\n"
            f"Decision: APPROVED if macro context supports the move, REJECTED if it does not.\n"
            f"{recent_lessons}\n\n"
            f"Respond with ONLY this block — nothing before or after it:\n"
            f"```json\n"
            f"{{\"llm_decision\": \"APPROVED\", \"rationale\": \"one sentence\"}}\n"
            f"```"
        )

        def _parse_voter_reply(reply: str) -> tuple[str, str]:
            """Extract decision and rationale from a voter's response."""
            decision  = "ERROR"
            rationale = "Could not parse LLM response."

            # Strategy 1: JSON inside a ```json ... ``` or ```json ... <eof> fence
            for fence_pat in (r"```json\s*(\{.*?\})\s*(?:```|$)", r"```\s*(\{.*?\})\s*(?:```|$)"):
                for match in re.finditer(fence_pat, reply, re.DOTALL):
                    try:
                        parsed = json.loads(match.group(1))
                        if "llm_decision" in parsed:
                            decision  = parsed["llm_decision"].upper()
                            rationale = parsed.get("rationale", rationale)
                            break
                    except json.JSONDecodeError:
                        pass
                if decision in ("APPROVED", "REJECTED"):
                    break

            # Strategy 2: any bare JSON object with llm_decision (no fence required)
            if decision not in ("APPROVED", "REJECTED"):
                for match in re.finditer(r"\{[^{}]*\}", reply, re.DOTALL):
                    try:
                        parsed = json.loads(match.group(0))
                        if "llm_decision" in parsed:
                            decision  = parsed["llm_decision"].upper()
                            rationale = parsed.get("rationale", rationale)
                            break
                    except json.JSONDecodeError:
                        pass

            # Strategy 3: keyword scan when no JSON found at all
            if decision not in ("APPROVED", "REJECTED"):
                upper = reply.upper()
                if "APPROVED" in upper and "REJECTED" not in upper:
                    decision  = "APPROVED"
                    rationale = "[keyword fallback] " + reply[:200].strip()
                elif "REJECTED" in upper:
                    decision  = "REJECTED"
                    rationale = "[keyword fallback] " + reply[:200].strip()
                else:
                    decision  = "REJECTED"
                    rationale = f"Unrecognised response — defaulting REJECTED. Raw: {reply[:120]}"
            return decision, rationale

        async def _call_voter(model, model_name: str, price_in: float, price_out: float):
            """Invoke one voter and return (decision, rationale), or ('ERROR', reason)."""
            if not model:
                return "ERROR", f"{model_name} unavailable"
            try:
                response = await model.ainvoke(
                    [self.system_prompt, HumanMessage(content=supervisor_prompt)]
                )
                await _log_llm_cost(response, model_name,
                                    "Validation", price_in, price_out)
                return _parse_voter_reply(response.content)
            except Exception as exc:
                logger.error("[ORCHESTRATOR] Voter %s failed: %s", model_name, exc)
                return "ERROR", str(exc)

        try:
            gemini_decision, gemini_rationale = "ERROR", "Gemini unavailable"
            secondary_decision, secondary_rationale = "ERROR", "Secondary model unavailable"

            # Run both voters concurrently — total latency = max(gemini, secondary)
            gemini_result, secondary_result = await asyncio.gather(
                _call_voter(self.signal_model or self.model,
                            GEMINI_2_5_FLASH_LITE_MODEL, GEMINI_COST_IN, GEMINI_COST_OUT),
                _call_voter(self.secondary_voter or self.model,
                            GEMINI_3_1_FLASH_LITE_MODEL, GEMINI_COST_IN, GEMINI_COST_OUT),
            )
            gemini_decision, gemini_rationale = gemini_result
            secondary_decision, secondary_rationale = secondary_result

            # Primary-decisive: Gemini is authoritative; secondary vote is advisory only.
            if gemini_decision == "APPROVED":
                final_decision  = "APPROVED"
                final_rationale = f"Primary approved | Secondary: {secondary_decision} ({secondary_rationale[:80]})"
                if secondary_decision != "APPROVED":
                    logger.info("[ORCHESTRATOR] Secondary dissent on %s (advisory only): %s", asset, secondary_rationale[:80])
            else:
                final_decision  = "REJECTED"
                final_rationale = f"Primary rejected: {gemini_rationale} | Secondary: {secondary_decision}"

            logger.info("[ORCHESTRATOR] Signal %s %s → ensemble: %s | %s",
                        asset, signal_ts, final_decision, final_rationale[:120])

            return {
                "llm_decision": final_decision,
                "rationale":    final_rationale,
                "signal_event": signal_event,
            }

        except Exception as exc:
            logger.error("[ORCHESTRATOR] process_signal ensemble failed: %s", exc)
            return {
                "llm_decision": "ERROR",
                "rationale":    str(exc),
                "signal_event": signal_event,
            }

    # ------------------------------------------------------------------
    # Command Parsing
    # ------------------------------------------------------------------

    def _extract_commands(self, text: str) -> list[dict]:
        """
        Scans the LLM reply for embedded JSON command blocks.
        The orchestrator's system prompt instructs it to wrap commands in:
            ```json
            { "action": "HALT_BOT", ... }
            ```
        Returns a list of parsed command dicts (may be empty).
        """
        commands = []
        # Match ```json ... ``` blocks (greedy, handles multi-line)
        pattern = r"```json\s*(\{.*?\})\s*```"
        for match in re.finditer(pattern, text, re.DOTALL):
            try:
                cmd = json.loads(match.group(1))
                if "action" in cmd:
                    commands.append(cmd)
                    logger.info("[ORCHESTRATOR] Parsed command: %s", cmd)
            except json.JSONDecodeError as e:
                logger.warning("[ORCHESTRATOR] Command JSON parse error: %s", e)
        return commands

    # ------------------------------------------------------------------
    # Command Dispatch
    # ------------------------------------------------------------------

    def _dispatch_command(self, cmd: dict) -> dict | None:
        """
        Routes a parsed OrchestratorCommand to the appropriate subsystem.
        Returns a result dict for commands that produce meaningful output
        (e.g. PLACE_ORDER fill details, QUERY_RISK status). Returns None
        for fire-and-forget lifecycle commands.
        All routing happens synchronously — the strategy engine operations
        are in-memory and thread-safe.
        """
        # Lazy import to avoid circular dependency at module load
        from strategy.engine import master_engine
        from agents.risk_agent import risk_agent

        action     = cmd.get("action", "").upper()
        target_bot = cmd.get("target_bot")
        params     = cmd.get("params", {})

        logger.info("[ORCHESTRATOR] Dispatching command: action=%s target=%s params=%s",
                    action, target_bot, params)

        if action == "HALT_BOT":
            reason = params.get("reason", "Orchestrator halt command")
            if str(target_bot).lower() in ("all", "*"):
                results_map = {}
                for bot_id in list(master_engine.bots.keys()):
                    results_map[bot_id] = master_engine.halt_bot(bot_id, reason=reason)
                logger.info("[ORCHESTRATOR] HALT_BOT all → %s", results_map)
                return {"halted": list(results_map.keys()), "count": len(results_map)}
            elif target_bot:
                success = master_engine.halt_bot(target_bot, reason=reason)
                logger.info("[ORCHESTRATOR] HALT_BOT → %s success=%s", target_bot, success)
            else:
                logger.warning("[ORCHESTRATOR] HALT_BOT missing target_bot")

        elif action == "RESUME_BOT":
            if target_bot:
                success = master_engine.resume_bot(target_bot)
                logger.info("[ORCHESTRATOR] RESUME_BOT → %s success=%s", target_bot, success)

        elif action == "ADJUST_ALLOCATION":
            new_pct = params.get("new_allocation_pct")
            if target_bot and new_pct is not None:
                success = master_engine.adjust_allocation(target_bot, float(new_pct))
                logger.info("[ORCHESTRATOR] ADJUST_ALLOCATION → %s %.1f%% success=%s",
                            target_bot, new_pct, success)

        elif action == "TRIGGER_BACKTEST":
            logger.info("[ORCHESTRATOR] TRIGGER_BACKTEST received — Phase 4 handler (not yet implemented)")

        elif action == "QUERY_RISK":
            status = risk_agent.get_risk_status()
            logger.info("[ORCHESTRATOR] QUERY_RISK → %s", status)
            return status

        elif action == "QUERY_POSITIONS":
            try:
                from agents.execution_agent import _get_trading_client
                tc = _get_trading_client()
                if not tc:
                    return {"error": "Trading client unavailable"}
                positions = tc.get_all_positions()
                result = [
                    {
                        "symbol":       p.symbol,
                        "qty":          str(p.qty),
                        "unrealized_pl": str(p.unrealized_pl),
                        "current_price": str(p.current_price),
                        "side":         str(p.side),
                    }
                    for p in positions
                ]
                logger.info("[ORCHESTRATOR] QUERY_POSITIONS → %d positions", len(result))
                return {"positions": result, "count": len(result)}
            except Exception as exc:
                logger.error("[ORCHESTRATOR] QUERY_POSITIONS failed: %s", exc)
                return {"error": str(exc)}

        elif action == "PLACE_ORDER":
            return self._place_order(params)

        else:
            logger.warning("[ORCHESTRATOR] Unknown action: %s", action)

        return None

    def _parse_qty(self, qty_raw, portfolio_value: float) -> float:
        """Parse qty which may be a float, int, or percentage string like '100%'."""
        if isinstance(qty_raw, str) and qty_raw.strip().endswith('%'):
            fraction = float(qty_raw.strip().rstrip('%')) / 100.0
            return round(portfolio_value * fraction, 8)
        try:
            return float(qty_raw)
        except (TypeError, ValueError):
            return 0.0

    def _place_order(self, params: dict) -> dict:
        """
        Execute a manual order from the orchestrator chat.
        Routes through the full risk pipeline (kill switch + sizing), then
        submits via ExecutionAgent. The user-specified qty overrides Kelly sizing.
        """
        import sys
        from strategy.engine import master_engine
        from agents.risk_agent import risk_agent
        from agents.execution_agent import execution_agent, _get_trading_client

        symbol   = params.get("symbol", "BTC/USD")
        side     = params.get("side", "BUY").upper()
        qty_raw  = params.get("qty", 0.0)
        reason   = params.get("reason", "orchestrator manual order")

        # Fetch equity early so we can parse percentage quantities
        equity = 0.0
        try:
            tc = _get_trading_client()
            if tc:
                equity = float(tc.get_account().equity)
        except Exception:
            pass

        qty = self._parse_qty(qty_raw, equity)

        if qty <= 0:
            logger.warning("[ORCHESTRATOR] PLACE_ORDER rejected — qty must be > 0")
            return {"error": "qty must be > 0"}

        # Get last known tick price for slippage calculation
        price = master_engine.get_last_price(symbol) or 0.0

        # For SELL orders, fall back to Alpaca position's current_price when cache is cold
        if price <= 0.0 and side == "SELL" and tc:
            try:
                norm = symbol.replace("/", "")
                for p in tc.get_all_positions():
                    if p.symbol.replace("/", "") == norm:
                        price = float(p.current_price or 0.0)
                        break
            except Exception:
                pass

        synthetic_signal = {
            "action":     side,
            "symbol":     symbol,
            "price":      price,
            "qty":        qty,   # lets risk_agent SELL fast-path read the user-specified qty
            "confidence": 1.0,   # Manual orders always pass the confidence gate
            "bot":        "orchestrator",
            "meta":       {"reason": reason, "source": "manual"},
        }

        # Enforce kill switch + position sizing via RiskAgent
        approved = risk_agent.process(synthetic_signal, equity)
        if not approved:
            logger.warning("[ORCHESTRATOR] PLACE_ORDER blocked by risk gate — %s %s", side, symbol)
            return {"error": "Risk gate rejected the order (kill switch active or sizing limits exceeded)."}

        # Override Kelly-sized qty with the user's explicit quantity
        approved["qty"] = qty

        exec_result = execution_agent.execute(approved, signal_price=price)
        if not exec_result:
            reason = getattr(execution_agent, "last_error", None) or "unknown error — check server logs"
            logger.error("[ORCHESTRATOR] PLACE_ORDER execution failed — %s %s qty=%s: %s", side, symbol, qty, reason)
            return {"error": f"Execution failed: {reason}"}

        logger.info(
            "[ORCHESTRATOR] PLACE_ORDER filled — order_id=%s %s %s qty=%.6f fill=%.2f slip=%.4f",
            exec_result.order_id, side, symbol, exec_result.qty,
            exec_result.fill_price, exec_result.slippage,
        )
        return exec_result.to_dict()


# Singleton orchestrator for FastAPI bindings
master_orchestrator = OrchestratorEngine()
