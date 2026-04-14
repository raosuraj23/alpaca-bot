"""
Orchestrator Engine — Stateful Conversation + Command Routing
==============================================================
The system brain. Receives natural language from the UI OrchestratorChat,
maintains a rolling message history for conversational context, and parses
embedded OrchestratorCommand JSON to dispatch lifecycle actions to the
StrategyEngine and KillSwitch.

Command routing:
  HALT_BOT         → master_engine.halt_bot(target_bot)
  RESUME_BOT       → master_engine.resume_bot(target_bot)
  ADJUST_ALLOCATION → master_engine.adjust_allocation(target_bot, pct)
  TRIGGER_BACKTEST → (Phase 4 — logged only)
  QUERY_RISK       → returns risk_agent.get_risk_status() inline
"""

import json
import logging
import re
from langchain_core.messages import HumanMessage, AIMessage, SystemMessage

from agents.factory import swarm_factory

logger = logging.getLogger(__name__)

# History window: keep last N messages (each turn = 1 Human + 1 AI = 2 messages)
HISTORY_WINDOW = 6   # = 3 full turns


class OrchestratorEngine:
    def __init__(self):
        # Standard tier — Gemini 1.5-pro / Claude Sonnet for chat routing
        self.model = swarm_factory.build_model(model_level="standard")
        raw_prompt = swarm_factory.get_system_prompt("orchestrator-agent")
        # Cache the system prompt at Anthropic's ephemeral tier — avoids paying
        # full input token cost (~2k tokens) on every invocation.
        self.system_prompt = SystemMessage(
            content=raw_prompt.content,
            additional_kwargs={"cache_control": {"type": "ephemeral"}},
        )
        self._history: list = []   # rolling in-memory conversation buffer

    # ------------------------------------------------------------------
    # Public Interface
    # ------------------------------------------------------------------

    def process_chat(self, user_text: str) -> str:
        if not self.model:
            return (
                "⚠️ System Offline: No API keys mapped in .env. "
                "The LLM Swarm is currently sleeping. Please inject your keys to activate."
            )

        self._history.append(HumanMessage(content=user_text))
        messages = [self.system_prompt] + self._history[-HISTORY_WINDOW:]

        try:
            response = self.model.invoke(messages)
            reply = response.content
            self._history.append(AIMessage(content=reply))

            # Parse and execute any embedded commands in the reply
            commands = self._extract_commands(reply)
            for cmd in commands:
                self._dispatch_command(cmd)

            return reply

        except Exception as e:
            logger.error("[ORCHESTRATOR] LLM invocation failed: %s", e)
            return f"[SWARM ERROR] {str(e)}"

    def clear_history(self):
        """Resets the conversation context window."""
        self._history = []
        logger.info("[ORCHESTRATOR] Conversation history cleared.")

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

    def _dispatch_command(self, cmd: dict):
        """
        Routes a parsed OrchestratorCommand to the appropriate subsystem.
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
            if target_bot:
                reason = params.get("reason", "Orchestrator halt command")
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

        else:
            logger.warning("[ORCHESTRATOR] Unknown action: %s", action)


# Singleton orchestrator for FastAPI bindings
master_orchestrator = OrchestratorEngine()
