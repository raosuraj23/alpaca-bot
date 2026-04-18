"""
Calibration Tracker — Rolling Brier Score per strategy.

Brier Score = mean((forecast - outcome)^2) over a rolling window.
Range [0, 1]; lower is better calibrated.

Adaptation for continuous momentum/arbitrage signals:
  outcome = 1 if realized_pnl > 0 (profitable trade), 0 if loss
  forecast = signal.confidence at trade entry

The calibration_scalar() method maps current Brier Score to a Kelly multiplier
in [0.25, 0.50]: well-calibrated strategies earn higher Kelly allocation,
poorly calibrated strategies are capped at quarter-Kelly.
"""

import logging
from collections import deque

logger = logging.getLogger(__name__)

_KELLY_FLOOR   = 0.25   # minimum Kelly fraction regardless of calibration
_KELLY_CEILING = 0.50   # maximum Kelly fraction for perfectly calibrated strategies
_WINDOW        = 100    # rolling trades per strategy


class CalibrationTracker:
    """Tracks rolling Brier Score per strategy and maps it to a dynamic Kelly scalar."""

    def __init__(self, window: int = _WINDOW):
        self._window = window
        self._records: dict[str, deque] = {}  # strategy → deque[(forecast, outcome)]

    def log(self, strategy: str, forecast: float, outcome: int) -> None:
        """
        Record a completed trade for calibration.

        Args:
            strategy: bot_id string (e.g. "momentum-alpha")
            forecast: signal confidence at entry (0.0–1.0)
            outcome: 1 if trade was profitable (realized_pnl > 0), else 0
        """
        if strategy not in self._records:
            self._records[strategy] = deque(maxlen=self._window)
        self._records[strategy].append((float(forecast), int(outcome)))
        logger.debug(
            "[CALIBRATION] %s logged — forecast=%.3f outcome=%d samples=%d",
            strategy, forecast, outcome, len(self._records[strategy]),
        )

    def brier_score(self, strategy: str) -> float | None:
        """
        Mean squared error between forecast probabilities and binary outcomes.
        Returns None if fewer than 10 samples (insufficient data).
        """
        records = self._records.get(strategy)
        if not records or len(records) < 10:
            return None
        return sum((f - o) ** 2 for f, o in records) / len(records)

    def calibration_scalar(self, strategy: str) -> float:
        """
        Maps the Brier Score to a Kelly multiplier in [0.25, 0.50]:
          BS = 0.00  → scalar = 0.50  (perfect calibration → full half-Kelly)
          BS = 0.25  → scalar = 0.25  (random guessing → quarter-Kelly floor)

        Falls back to _KELLY_FLOOR when insufficient data.
        """
        bs = self.brier_score(strategy)
        if bs is None:
            return _KELLY_FLOOR  # conservative default during warmup
        # Linear interpolation: scalar = 0.50 - bs * 1.0, clamped to [0.25, 0.50]
        scalar = _KELLY_CEILING - bs * 1.0
        return max(_KELLY_FLOOR, min(_KELLY_CEILING, scalar))

    def win_rate(self, strategy: str) -> float | None:
        """Rolling win rate over the calibration window. Returns None if < 5 samples."""
        records = self._records.get(strategy)
        if not records or len(records) < 5:
            return None
        return sum(o for _, o in records) / len(records)

    def sample_count(self, strategy: str) -> int:
        records = self._records.get(strategy)
        return len(records) if records else 0

    def summary(self) -> dict[str, dict]:
        """Returns per-strategy calibration stats for the /api/risk/status endpoint."""
        out = {}
        for strat in self._records:
            out[strat] = {
                "samples":     self.sample_count(strat),
                "brier_score": self.brier_score(strat),
                "win_rate":    self.win_rate(strat),
                "kelly_scalar": self.calibration_scalar(strat),
            }
        return out


calibration_tracker = CalibrationTracker()
