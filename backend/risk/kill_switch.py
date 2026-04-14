"""
Kill Switch — Global Risk Circuit Breaker
==========================================
Enforces the following hard risk rules across all trading activity:

  1. Max Daily Drawdown: if portfolio drops ≥ 2% from start-of-day equity,
     ALL signal transmission is blocked immediately.
  2. Min Signal Confidence: signals below 0.30 confidence are rejected.
  3. Manual Override: operator can halt/resume via orchestrator commands.

Start-of-day equity resets at midnight UTC automatically.
"""

import logging
from datetime import datetime, timezone

logger = logging.getLogger(__name__)

MAX_DAILY_DRAWDOWN_PCT = 2.0     # Hard threshold: block all signals at 2% loss
MIN_SIGNAL_CONFIDENCE  = 0.30    # Any signal below this is rejected


class KillSwitch:
    def __init__(self, max_daily_drawdown_pct: float = MAX_DAILY_DRAWDOWN_PCT):
        self.max_daily_drawdown_pct = max_daily_drawdown_pct
        self.triggered         = False
        self.triggered_reason  = None
        self.start_of_day_equity: float | None = None
        self._day_anchor: int | None = None   # UTC day number of last SOD reset
        self._drawdown_pct: float = 0.0

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _today_utc(self) -> int:
        return datetime.now(timezone.utc).timetuple().tm_yday

    def _maybe_reset_day(self, current_equity: float):
        """Resets start-of-day equity at midnight UTC."""
        today = self._today_utc()
        if self._day_anchor != today:
            logger.info("[KILL SWITCH] New trading day detected — resetting SOD equity to $%.2f", current_equity)
            self.start_of_day_equity = current_equity
            self._day_anchor = today
            self._drawdown_pct = 0.0
            # Do NOT reset `triggered` here — a manual halt persists day-over-day
            # until explicitly resumed by operator.

    # ------------------------------------------------------------------
    # Portfolio-Level Gate
    # ------------------------------------------------------------------

    def evaluate_portfolio(self, current_equity: float, start_of_day_equity: float | None = None) -> bool:
        """
        Checks whether global portfolio drawdown has exceeded the daily limit.
        Call this on every tick or at portfolio poll intervals.

        Returns True if trading is allowed, False if kill switch is active.
        """
        if start_of_day_equity is not None:
            # Allow caller to provide SOD equity for the first call
            if self.start_of_day_equity is None:
                self.start_of_day_equity = start_of_day_equity
                self._day_anchor = self._today_utc()
        else:
            self._maybe_reset_day(current_equity)

        if self.triggered:
            return False

        sod = self.start_of_day_equity
        if sod is None or sod <= 0:
            return True  # No baseline yet — allow trading

        drawdown = ((sod - current_equity) / sod) * 100
        self._drawdown_pct = drawdown

        if drawdown >= self.max_daily_drawdown_pct:
            reason = f"Daily drawdown {drawdown:.3f}% ≥ {self.max_daily_drawdown_pct}% limit"
            logger.critical("[KILL SWITCH] TRIGGERED — %s", reason)
            self.triggered = True
            self.triggered_reason = reason
            return False

        return True

    # ------------------------------------------------------------------
    # Signal-Level Gate
    # ------------------------------------------------------------------

    def evaluate_signal(self, signal: dict) -> bool:
        """
        Per-signal gate. Called before every order submission.
        Returns True if the signal may proceed to the execution agent.
        """
        if self.triggered:
            logger.warning("[KILL SWITCH] Blocking signal — circuit breaker active: %s", self.triggered_reason)
            return False

        confidence = signal.get("confidence", 0.0)
        if confidence < MIN_SIGNAL_CONFIDENCE:
            logger.warning("[KILL SWITCH] Blocking low-confidence signal (%.2f < %.2f) from %s",
                           confidence, MIN_SIGNAL_CONFIDENCE, signal.get("bot", "unknown"))
            return False

        return True

    # ------------------------------------------------------------------
    # Manual Override Controls
    # ------------------------------------------------------------------

    def manual_halt(self, reason: str = "Operator initiated halt"):
        """Triggered by orchestrator HALT command or dashboard UI."""
        logger.warning("[KILL SWITCH] MANUAL HALT activated — %s", reason)
        self.triggered = True
        self.triggered_reason = f"MANUAL: {reason}"

    def manual_resume(self):
        """Clears a manual halt. Does NOT override automatic drawdown triggers."""
        if self.triggered and self.triggered_reason and self.triggered_reason.startswith("MANUAL"):
            logger.info("[KILL SWITCH] Manual halt cleared — trading resumed")
            self.triggered = False
            self.triggered_reason = None
        else:
            logger.warning("[KILL SWITCH] resume() called but halt was automatic (drawdown) — not cleared")

    # ------------------------------------------------------------------
    # Status Reporting (feeds /api/risk/status)
    # ------------------------------------------------------------------

    def get_status(self) -> dict:
        return {
            "triggered":           self.triggered,
            "reason":              self.triggered_reason,
            "drawdown_pct":        round(self._drawdown_pct, 4),
            "max_drawdown_pct":    self.max_daily_drawdown_pct,
            "start_of_day_equity": self.start_of_day_equity,
            "min_confidence_gate": MIN_SIGNAL_CONFIDENCE,
        }


global_kill_switch = KillSwitch()
