"""
Kill Switch — Global Risk Circuit Breaker
==========================================
Enforces the following hard risk rules across all trading activity:

  1. Max Daily Drawdown: if portfolio drops ≥ 2% from start-of-day equity,
     equity signal transmission is blocked (crypto continues — 24/7 market).
  2. Min Signal Confidence: signals below 0.30 confidence are rejected.
  3. Manual Override: operator can halt/resume via orchestrator commands.
  4. Cumulative MDD Gate: if peak-to-trough drawdown exceeds 8% across all
     time, trading is soft-halted until operator manually resumes.

Start-of-day equity resets at midnight UTC automatically.

Guardrails:
  1. Domain expertise embedded in risk logic — compliance before action
  2. Code is deterministic: scripts validate risk, not language instructions
  3. Progressive disclosure: SKILL.md keeps core rules, details in references/
  4. Parallel sub-agents per market — up to 10+ simultaneous signals
  5. Iterative improvement: compound skill logs every loss + pattern fix
"""

import logging
from collections import defaultdict, deque
from datetime import datetime, timezone, timedelta
from config import settings as _cfg

logger = logging.getLogger(__name__)

MAX_DAILY_DRAWDOWN_PCT      = 2.0   # Hard threshold: block all signals at 2% daily loss
MAX_CUMULATIVE_DRAWDOWN_PCT = 8.0   # Soft halt: peak-to-trough drawdown > 8% across all time
MIN_SIGNAL_CONFIDENCE       = 0.30  # Any signal below this is rejected

# SEC Pattern Day Trader rule: ≥4 day trades in a rolling 5-trading-day window
# triggers a hard block if account equity < $25,000.
PDT_EQUITY_THRESHOLD    = 25_000.0  # PDT rules apply below this equity level
PDT_MAX_DAY_TRADES      = 3         # max day trades per 5-trading-day rolling window


class KillSwitch:
    def __init__(
        self,
        max_daily_drawdown_pct: float = MAX_DAILY_DRAWDOWN_PCT,
        max_cumulative_drawdown_pct: float = MAX_CUMULATIVE_DRAWDOWN_PCT,
    ):
        self.max_daily_drawdown_pct      = max_daily_drawdown_pct
        self.max_cumulative_drawdown_pct = max_cumulative_drawdown_pct
        self.triggered         = False          # global flag — set by manual halt or cumulative MDD
        self.triggered_equity  = False          # set by equity daily drawdown only
        self.triggered_crypto  = False          # reserved for future per-class crypto drawdown gate
        self.triggered_reason  = None
        self.start_of_day_equity: float | None = None
        self._day_anchor: int | None = None   # UTC day number of last SOD reset
        self._drawdown_pct: float = 0.0
        self._peak_equity: float = 0.0        # Running all-time high for cumulative MDD
        self._cumulative_mdd_pct: float = 0.0
        self._trigger_time: datetime | None = None  # When drawdown halt fired
        # PDT tracking — keyed by (normalized_symbol, date_str)
        # Stores timestamps of open→close round-trips within the rolling 5-day window
        self._day_trade_log: deque = deque()   # deque of (symbol, datetime) tuples

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _today_utc(self) -> int:
        return datetime.now(timezone.utc).timetuple().tm_yday

    def _maybe_reset_day(self, current_equity: float):
        """Resets start-of-day equity at midnight UTC.
        Auto-clears drawdown-triggered halts on a new day (fresh session = fresh limit).
        Manual halts (reason prefixed 'MANUAL:') persist until operator explicitly resumes.
        """
        today = self._today_utc()
        if self._day_anchor != today:
            logger.info("[KILL SWITCH] New trading day — resetting SOD equity to $%.2f", current_equity)
            self.start_of_day_equity = current_equity
            self._day_anchor = today
            self._drawdown_pct = 0.0
            # Auto-clear drawdown triggers on new day; keep manual halts locked.
            if self.triggered and not (self.triggered_reason or "").startswith("MANUAL"):
                logger.info("[KILL SWITCH] Drawdown halt auto-cleared for new trading day")
                self.triggered = False
                self.triggered_reason = None
            # Always clear equity daily drawdown on day rollover regardless of reason
            if self.triggered_equity:
                logger.info("[KILL SWITCH] Equity drawdown halt auto-cleared for new trading day")
                self.triggered_equity = False

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

        # Intraday recovery check for equity drawdown halt
        if self.triggered_equity and self._trigger_time is not None:
            elapsed = (datetime.now(timezone.utc) - self._trigger_time).total_seconds()
            sod_r = self.start_of_day_equity
            if (elapsed <= _cfg.recovery_window_secs and sod_r and sod_r > 0
                    and abs(current_equity - sod_r) / sod_r * 100 <= _cfg.recovery_threshold_pct):
                logger.info("[KILL SWITCH] Intraday recovery detected — resuming equity trading")
                self.triggered_equity = False
                self._trigger_time = None

        if self.triggered:
            # Global flag: manual halt or cumulative MDD — blocks everything
            return False

        sod = self.start_of_day_equity
        if sod is None or sod <= 0:
            return True  # No baseline yet — allow trading

        drawdown = ((sod - current_equity) / sod) * 100
        self._drawdown_pct = drawdown

        if drawdown >= self.max_daily_drawdown_pct:
            reason = f"Daily drawdown {drawdown:.3f}% ≥ {self.max_daily_drawdown_pct}% limit"
            logger.critical("[KILL SWITCH] EQUITY HALT TRIGGERED — %s", reason)
            self.triggered_equity = True
            self.triggered_reason = reason
            self._trigger_time = datetime.now(timezone.utc)
            return False

        return True

    # ------------------------------------------------------------------
    # Cumulative MDD Gate (8% peak-to-trough across all time)
    # ------------------------------------------------------------------

    def evaluate_cumulative_drawdown(self, current_equity: float) -> bool:
        """
        Tracks the all-time equity peak and fires a soft halt if the
        cumulative drawdown exceeds max_cumulative_drawdown_pct (default 8%).

        Returns True if trading is allowed, False if cumulative MDD is breached.
        Manual resume required to clear this halt.
        """
        if current_equity <= 0:
            return not self.triggered

        if current_equity > self._peak_equity:
            self._peak_equity = current_equity

        if self._peak_equity > 0:
            mdd = (self._peak_equity - current_equity) / self._peak_equity * 100
            self._cumulative_mdd_pct = mdd
            if mdd >= self.max_cumulative_drawdown_pct and not self.triggered:
                reason = (
                    f"Cumulative MDD {mdd:.2f}% ≥ {self.max_cumulative_drawdown_pct}% limit — "
                    "MANUAL: resume required"
                )
                logger.critical("[KILL SWITCH] CUMULATIVE MDD TRIGGERED — %s", reason)
                self.triggered = True
                self.triggered_reason = reason
                return False

        return not self.triggered

    # ------------------------------------------------------------------
    # Signal-Level Gate
    # ------------------------------------------------------------------

    def evaluate_signal(self, signal: dict, account_equity: float = 0.0) -> bool:
        """
        Per-signal gate. Called before every order submission.
        Returns True if the signal may proceed to the execution agent.
        Asset-class aware: equity drawdown only blocks equity signals; crypto runs 24/7.

        Args:
            signal:         Signal dict.
            account_equity: Current account equity — used for PDT threshold check.
                            Defaults to 0 (worst-case: PDT rules apply) when unavailable.
        """
        if self.triggered:
            logger.warning("[KILL SWITCH] Blocking signal — global circuit breaker active: %s", self.triggered_reason)
            return False

        symbol = signal.get("symbol", "")
        is_crypto = "/" in symbol
        if not is_crypto and self.triggered_equity:
            logger.warning("[KILL SWITCH] Blocking equity signal — equity drawdown halt active: %s", self.triggered_reason)
            return False
        if is_crypto and self.triggered_crypto:
            logger.warning("[KILL SWITCH] Blocking crypto signal — crypto halt active: %s", self.triggered_reason)
            return False

        confidence = signal.get("confidence", 0.0)
        if confidence < MIN_SIGNAL_CONFIDENCE:
            logger.warning("[KILL SWITCH] Blocking low-confidence signal (%.2f < %.2f) from %s",
                           confidence, MIN_SIGNAL_CONFIDENCE, signal.get("bot", "unknown"))
            return False

        if not self.evaluate_pdt(signal, account_equity):
            return False

        return True

    # ------------------------------------------------------------------
    # PDT (Pattern Day Trader) Enforcement
    # ------------------------------------------------------------------

    def record_day_trade(self, symbol: str):
        """
        Register a completed day trade (same-day open+close) for PDT tracking.
        Call this from the execution agent whenever a SELL fills against a same-day
        BUY on an equity symbol.

        Only equity symbols are subject to PDT rules — crypto is 24/7.
        """
        if "/" in symbol:
            return  # crypto — PDT does not apply
        now = datetime.now(timezone.utc)
        self._day_trade_log.append((symbol.upper(), now))
        logger.info("[PDT] Recorded day trade: %s — rolling count now %d",
                    symbol, self._count_day_trades())

    def _count_day_trades(self) -> int:
        """Count day trades in the rolling 5-trading-day window (≈ 7 calendar days)."""
        cutoff = datetime.now(timezone.utc) - timedelta(days=7)
        while self._day_trade_log and self._day_trade_log[0][1] < cutoff:
            self._day_trade_log.popleft()
        return len(self._day_trade_log)

    def evaluate_pdt(self, signal: dict, account_equity: float) -> bool:
        """
        Returns True if the trade may proceed, False if it would violate PDT rules.

        PDT rules apply only when:
          - account_equity < $25,000 (institutional accounts are exempt)
          - asset is an equity (not crypto)
          - action is BUY (new position) AND rolling day-trade count ≥ 3
            (the 4th day trade that day would trigger the PDT flag)

        Args:
            signal: The signal dict with 'symbol' and 'action'.
            account_equity: Current account equity in USD.
        """
        symbol = signal.get("symbol", "")
        action = signal.get("action", "").upper()

        if "/" in symbol:
            return True  # crypto — no PDT restriction

        if action != "BUY":
            return True  # SELL closes a position — always allow

        if account_equity >= PDT_EQUITY_THRESHOLD:
            return True  # PDT rules don't apply to well-capitalised accounts

        count = self._count_day_trades()
        if count >= PDT_MAX_DAY_TRADES:
            logger.warning(
                "[PDT] BLOCKING %s BUY — %d day trades in rolling 5-day window "
                "(limit=%d, equity=$%.0f < $%.0f threshold)",
                symbol, count, PDT_MAX_DAY_TRADES, account_equity, PDT_EQUITY_THRESHOLD,
            )
            return False

        return True

    def get_pdt_status(self) -> dict:
        """Returns PDT state for the /api/risk/status endpoint."""
        return {
            "day_trade_count":    self._count_day_trades(),
            "day_trade_limit":    PDT_MAX_DAY_TRADES,
            "pdt_equity_threshold": PDT_EQUITY_THRESHOLD,
        }

    # ------------------------------------------------------------------
    # Manual Override Controls
    # ------------------------------------------------------------------

    def manual_halt(self, reason: str = "Operator initiated halt"):
        """Triggered by orchestrator HALT command or dashboard UI."""
        logger.warning("[KILL SWITCH] MANUAL HALT activated — %s", reason)
        self.triggered = True
        self.triggered_reason = f"MANUAL: {reason}"

    def manual_resume(self):
        """Clears a manual halt and any active equity drawdown halt."""
        cleared = False
        if self.triggered and self.triggered_reason and self.triggered_reason.startswith("MANUAL"):
            logger.info("[KILL SWITCH] Manual halt cleared — trading resumed")
            self.triggered = False
            self.triggered_reason = None
            cleared = True
        if self.triggered_equity:
            logger.info("[KILL SWITCH] Equity drawdown halt cleared by operator resume")
            self.triggered_equity = False
            cleared = True
        if not cleared:
            logger.warning("[KILL SWITCH] resume() called but no clearable halt was active")

    # ------------------------------------------------------------------
    # Status Reporting (feeds /api/risk/status)
    # ------------------------------------------------------------------

    def get_status(self) -> dict:
        return {
            "triggered":                  self.triggered,
            "triggered_equity":           self.triggered_equity,
            "triggered_crypto":           self.triggered_crypto,
            "reason":                     self.triggered_reason,
            "drawdown_pct":               round(self._drawdown_pct, 4),
            "max_drawdown_pct":           self.max_daily_drawdown_pct,
            "cumulative_mdd_pct":         round(self._cumulative_mdd_pct, 4),
            "max_cumulative_drawdown_pct": self.max_cumulative_drawdown_pct,
            "peak_equity":                self._peak_equity,
            "start_of_day_equity":        self.start_of_day_equity,
            "min_confidence_gate":        MIN_SIGNAL_CONFIDENCE,
            **self.get_pdt_status(),
        }


global_kill_switch = KillSwitch()
