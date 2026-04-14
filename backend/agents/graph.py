"""
LangGraph Multi-Agent StateGraph
==================================
Defines a directed graph connecting the three Phase 2 agents:
  orchestrator → risk_agent → execution_agent

This graph is used for structured multi-hop command flows where the
orchestrator's decision must pass through risk before execution.
For simple chat, the orchestrator handles routing inline.

Phase 2 status: HALT/RESUME/ADJUST commands are dispatched directly
in orchestrator.py (synchronous). The graph is wired but only called
for explicit pipeline-driven flows (e.g. when the orchestrator outputs
a BUY/SELL command requiring full risk + execution pipeline).
"""

from __future__ import annotations

import logging
from typing import TypedDict, Annotated, Any
import operator

logger = logging.getLogger(__name__)

# Lazy import guard — langgraph may not be installed yet.
try:
    from langgraph.graph import StateGraph, END

    # ---------------------------------------------------------------
    # Shared Agent State
    # ---------------------------------------------------------------

    class AgentState(TypedDict):
        # Input from previous node
        signal: dict                          # trading signal dict
        account_equity: float                 # current portfolio equity
        # Outputs accumulated through the pipeline
        risk_result: Any                      # RiskCheckResult (or None)
        execution_result: Any                 # ExecutionResult (or None)
        # Control flow
        messages: Annotated[list, operator.add]  # append-only log

    # ---------------------------------------------------------------
    # Node Functions
    # ---------------------------------------------------------------

    def risk_node(state: AgentState) -> AgentState:
        """Evaluates the signal through the RiskAgent."""
        from agents.risk_agent import risk_agent

        signal  = state["signal"]
        equity  = state["account_equity"]

        result = risk_agent.check(signal, equity)
        msg = (
            f"[RISK] {'✓ Approved' if result.passed else '✗ Rejected'} "
            f"{signal.get('action')} {signal.get('symbol')} "
            f"qty={result.recommended_qty:.6f} reason={result.reason}"
        )
        logger.info(msg)

        return {
            **state,
            "risk_result": result,
            "messages": [msg],
        }

    def execution_node(state: AgentState) -> AgentState:
        """Submits the order if risk approved."""
        from agents.execution_agent import execution_agent

        risk_result = state.get("risk_result")
        if not risk_result or not risk_result.passed:
            msg = "[EXECUTION] Skipped — risk check failed."
            return {**state, "execution_result": None, "messages": [msg]}

        signal = state["signal"]
        signal["qty"] = risk_result.recommended_qty

        result = execution_agent.execute(signal, signal_price=signal.get("price"))
        msg = (
            f"[EXECUTION] {'Filled' if result else 'Failed'} "
            f"{signal.get('action')} {signal.get('symbol')}"
        )
        if result:
            msg += f" fill=${result.fill_price:.2f} slip=${result.slippage:.4f}"

        logger.info(msg)
        return {**state, "execution_result": result, "messages": [msg]}

    def route_after_risk(state: AgentState) -> str:
        """Conditional edge: proceed to execution only if risk approved."""
        risk = state.get("risk_result")
        if risk and risk.passed:
            return "execution_agent"
        return END

    # ---------------------------------------------------------------
    # Graph Assembly
    # ---------------------------------------------------------------

    def build_trading_graph() -> Any:
        """Assembles and compiles the Phase 2 signal pipeline graph."""
        g = StateGraph(AgentState)
        g.add_node("risk_agent",      risk_node)
        g.add_node("execution_agent", execution_node)

        g.set_entry_point("risk_agent")
        g.add_conditional_edges("risk_agent", route_after_risk, {
            "execution_agent": "execution_agent",
            END: END,
        })
        g.add_edge("execution_agent", END)

        compiled = g.compile()
        logger.info("[GRAPH] Trading pipeline graph compiled (risk → execution).")
        return compiled

    trading_graph = build_trading_graph()

except ImportError:
    logger.warning(
        "[GRAPH] langgraph not installed — graph routing disabled. "
        "Install with: pip install langgraph>=0.2.0"
    )
    trading_graph = None


def run_signal_pipeline(signal: dict, account_equity: float) -> dict | None:
    """
    Entry point for running a signal through the full risk → execution graph.
    Falls back to None (noop) if langgraph is not installed.

    Returns the final AgentState dict, or None if pipeline not available.
    """
    if trading_graph is None:
        logger.warning("[GRAPH] trading_graph unavailable — signal pipeline skipped.")
        return None

    initial_state: AgentState = {
        "signal":           signal,
        "account_equity":   account_equity,
        "risk_result":      None,
        "execution_result": None,
        "messages":         [],
    }

    try:
        return trading_graph.invoke(initial_state)
    except Exception as e:
        logger.error("[GRAPH] Pipeline execution failed: %s", e)
        return None
