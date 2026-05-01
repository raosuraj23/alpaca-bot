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

from config import settings
from risk.kill_switch import global_kill_switch
from risk.exposure import exposure_manager, SizingResult

_OPTIONS_ACTIONS = frozenset({"BUY_CALL", "SELL_CALL", "BUY_PUT", "SELL_PUT"})

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

        # --- 2. Signal-level gate (confidence + asset-class halt checks) ---
        if not global_kill_switch.evaluate_signal(signal):
            ks = global_kill_switch.get_status()
            symbol = signal.get("symbol", "")
            is_crypto = "/" in symbol
            if ks.get("triggered") or (not is_crypto and ks.get("triggered_equity")) or (is_crypto and ks.get("triggered_crypto")):
                reason = ks.get("reason") or "Kill switch active"
            else:
                reason = f"Signal confidence {signal.get('confidence', 0):.2f} below minimum threshold"
            logger.warning("[RISK AGENT] Signal gate blocked — %s", reason)
            return RiskCheckResult(
                passed=False, reason=reason,
                kelly_fraction=0.0, recommended_notional=0.0, recommended_qty=0.0,
                var_check_passed=False, var_limit=0.0,
            )                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                               

        # --- 3. Cumulative MDD gate (8% peak-to-trough across all time) ---
        if not global_kill_switch.evaluate_cumulative_drawdown(eq):
            status = global_kill_switch.get_status()
            reason = status.get("reason") or "Cumulative MDD gate active"
            logger.warning("[RISK AGENT] Cumulative MDD gate blocked signal from %s — %s",
                           signal.get("bot"), reason)
            return RiskCheckResult(
                passed=False, reason=reason,
                kelly_fraction=0.0, recommended_notional=0.0, recommended_qty=0.0,
                var_check_passed=False, var_limit=0.0,
            )

        # --- 4. Options DTE gate (must precede sizing) ---
        action = signal.get("action", "")
        if action in _OPTIONS_ACTIONS:
            meta = signal.get("meta") or {}
            dte = int(meta.get("expiry_days", 999))
            if dte < settings.min_days_to_expiry:
                reason = f"Options DTE {dte} < minimum {settings.min_days_to_expiry}"
                logger.warning("[RISK AGENT] %s %s blocked — %s", action, signal.get("symbol"), reason)
                return RiskCheckResult(
                    passed=False, reason=reason,
                    kelly_fraction=0.0, recommended_notional=0.0, recommended_qty=0.0,
                    var_check_passed=False, var_limit=0.0,
                )

        # --- 4b. Paper trading: options not supported by Alpaca paper environment ---
        if settings.paper_trading and action in _OPTIONS_ACTIONS:
            reason = (
                f"Options signals are disabled in paper trading mode "
                f"(action={action}, symbol={signal.get('symbol')}). "
                "Switch to live trading or assign an equity strategy to this symbol."
            )
            logger.info("[RISK AGENT] Paper trading: blocked %s %s", action, signal.get("symbol"))
            return RiskCheckResult(
                passed=False, reason=reason,
                kelly_fraction=0.0, recommended_notional=0.0, recommended_qty=0.0,
                var_check_passed=False, var_limit=0.0,
            )

        # --- 5. Position sizing (Kelly sizing for BUY; ExposureManager returns signal qty for SELL) ---
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
        # Annotate EV for formula tracking in DB
        p = float(signal.get("confidence", 0))
        b = exposure_manager.reward_risk_ratio
        if 0.0 < p < 1.0 and b > 0:
            signal["expected_value"] = round(p * b - (1.0 - p), 4)
        return signal

    def get_risk_status(self) -> dict:
        """Returns combined kill switch + exposure params for /api/risk/status."""
        from agents.factory import _gemini_budget
        from risk.calibration import calibration_tracker
        ks = global_kill_switch.get_status()
        return {
            **ks,
            "max_position_pct":    exposure_manager.max_position_pct * 100,
            "max_position_usd":    exposure_manager.max_position_usd,
            "max_kelly_fraction":  exposure_manager.max_kelly_fraction,
            "gemini_budget":       {
                "remaining":      _gemini_budget.remaining,
                "limit":          _gemini_budget.limit,
                "hard_exhausted": _gemini_budget.hard_exhausted,
            },
            "calibration":         calibration_tracker.summary(),
        }


risk_agent = RiskAgent()
