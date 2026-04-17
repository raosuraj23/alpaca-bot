"""
Risk Agent — Signal Gatekeeper
================================
Every signal emitted by the StrategyEngine passes through here before
reaching the ExecutionAgent. The RiskAgent enforces:

  1. Kill switch check (drawdown + manual halt)
  2. Kelly-sized position sizing via ExposureManager
  3. Returns a RiskCheckResult with pass/fail + sizing details
"""

import logging
from dataclasses import dataclass

from risk.kill_switch import global_kill_switch
from risk.exposure import exposure_manager, SizingResult

logger = logging.getLogger(__name__)


@dataclass
class RiskCheckResult:
    passed:              bool
    reason:              str
    kelly_fraction:      float
    recommended_notional: float
    recommended_qty:     float
    var_check_passed:    bool
    var_limit:           float


class RiskAgent:
    """
    The Risk Agent observes strategy-generated signals and acts as the
    pre-execution gatekeeper. Must be called synchronously in the signal
    pipeline before any order is submitted.
    """

    def check(
        self,
        signal: dict,
        account_equity: float,
        current_equity: float | None = None,
        start_of_day_equity: float | None = None,
    ) -> RiskCheckResult:
        """
        Full risk evaluation for a signal.

        Args:
            signal:              Signal dict from StrategyEngine
            account_equity:      Total portfolio equity (for sizing)
            current_equity:      Current equity for drawdown check (defaults to account_equity)
            start_of_day_equity: Optional — provided on first call to set SOD baseline

        Returns:
            RiskCheckResult with passed=True if signal may execute.
        """
        eq = current_equity if current_equity is not None else account_equity
        sod = start_of_day_equity

        # --- 1. Portfolio-level drawdown gate ---
        if not global_kill_switch.evaluate_portfolio(eq, sod):
            status = global_kill_switch.get_status()
            reason = status.get("reason") or "Kill switch active"
            logger.warning("[RISK AGENT] Portfolio gate blocked signal from %s — %s",
                           signal.get("bot"), reason)
            return RiskCheckResult(
                passed=False, reason=reason,
                kelly_fraction=0.0, recommended_notional=0.0, recommended_qty=0.0,
                var_check_passed=False, var_limit=0.0,
            )

        # --- 2. Signal-level confidence + manual halt gate ---
        if not global_kill_switch.evaluate_signal(signal):
            reason = f"Signal confidence {signal.get('confidence', 0):.2f} below minimum threshold"
            logger.warning("[RISK AGENT] Signal gate blocked — %s", reason)
            return RiskCheckResult(
                passed=False, reason=reason,
                kelly_fraction=0.0, recommended_notional=0.0, recommended_qty=0.0,
                var_check_passed=False, var_limit=0.0,
            )                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                               

        # --- 3. Position sizing ---
        sizing: SizingResult = exposure_manager.size(signal, account_equity)

        if sizing.recommended_qty <= 0:
            reason = f"Sizing produced zero quantity — {sizing.rejection_reason or 'edge too thin'}"
            logger.warning("[RISK AGENT] Zero-qty rejection on %s — %s", signal.get("symbol"), reason)
            return RiskCheckResult(
                passed=False, reason=reason,
                kelly_fraction=sizing.kelly_fraction,
                recommended_notional=sizing.recommended_notional,
                recommended_qty=0.0,
                var_check_passed=sizing.var_check_passed,
                var_limit=sizing.var_limit,
            )

        logger.info(
            "[RISK AGENT] ✓ Approved %s %s qty=%.6f notional=$%.2f kelly=%.4f",
            signal.get("action"), signal.get("symbol"),
            sizing.recommended_qty, sizing.recommended_notional, sizing.kelly_fraction
        )

        return RiskCheckResult(
            passed=True,
            reason="All risk checks passed",
            kelly_fraction=sizing.kelly_fraction,
            recommended_notional=sizing.recommended_notional,
            recommended_qty=sizing.recommended_qty,
            var_check_passed=sizing.var_check_passed,
            var_limit=sizing.var_limit,
        )

    # Convenience wrapper for the stream_manager's existing call pattern
    def process(self, signal: dict, account_equity: float) -> dict | None:
        """
        Legacy convenience wrapper. Mutates the signal dict with 'qty'
        and returns it if approved, or None if rejected.
        Used by the WebSocket bar_callback pipeline.
        """
        result = self.check(signal, account_equity)
        if not result.passed:
            return None
        signal["qty"] = result.recommended_qty
        signal["notional"] = result.recommended_notional
        signal["kelly_fraction"] = result.kelly_fraction
        return signal

    def get_risk_status(self) -> dict:
        """Returns combined kill switch + exposure params for /api/risk/status."""
        ks = global_kill_switch.get_status()
        return {
            **ks,
            "max_position_pct":   exposure_manager.max_position_pct * 100,
            "max_position_usd":   exposure_manager.max_position_usd,
            "max_kelly_fraction": exposure_manager.max_kelly_fraction,
        }


risk_agent = RiskAgent()
