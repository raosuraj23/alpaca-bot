"""
Exposure Manager — Position Sizing
=====================================
Implements Kelly Criterion sizing with a VaR gate and hard notional cap.

Sizing formula:
  Kelly fraction:  f* = (p·b - q) / b
    where  p = signal confidence
           b = reward/risk ratio (default 2.0 for crypto)
           q = 1 - p

  Notional:        notional = account_equity * f* * max_kelly_fraction
  VaR gate:        reject if notional > VaR limit (equity * var_pct / confidence_level)
  Hard cap:        notional capped at max(10% equity, $50,000)
"""

import logging
from dataclasses import dataclass

logger = logging.getLogger(__name__)

# Risk parameters (adjustable per strategy)
MAX_POSITION_PCT    = 0.10   # 10% of equity hard cap
MAX_POSITION_USD    = 50_000 # $50k absolute cap
MAX_KELLY_FRACTION  = 0.25   # never bet more than 25% of Kelly suggestion
REWARD_RISK_RATIO   = 2.0    # assumed R:R (2:1 take-profit / stop-loss)
VAR_DAILY_PCT       = 0.01   # 1% daily VaR limit
VAR_CONFIDENCE      = 0.95   # 95th percentile


@dataclass
class SizingResult:
    kelly_fraction: float
    recommended_notional: float
    recommended_qty: float
    var_check_passed: bool
    var_limit: float
    rejection_reason: str | None


class ExposureManager:
    def __init__(
        self,
        max_position_pct: float = MAX_POSITION_PCT,
        max_position_usd: float = MAX_POSITION_USD,
        max_kelly_fraction: float = MAX_KELLY_FRACTION,
        reward_risk_ratio: float = REWARD_RISK_RATIO,
    ):
        self.max_position_pct   = max_position_pct
        self.max_position_usd   = max_position_usd
        self.max_kelly_fraction = max_kelly_fraction
        self.reward_risk_ratio  = reward_risk_ratio

    def calculate_order_size(self, signal: dict, account_equity: float) -> float:
        """
        Returns recommended quantity (in units of the asset) after applying
        Kelly sizing + VaR gate. Falls back to a minimum safe size if equity
        is unavailable or checks fail.
        """
        result = self.size(signal, account_equity)
        if result.rejection_reason:
            logger.warning("[EXPOSURE] Sizing rejected — %s", result.rejection_reason)
            return 0.0
        return result.recommended_qty

    def size(self, signal: dict, account_equity: float) -> SizingResult:
        """Full sizing computation. Returns a SizingResult with diagnostics."""
        symbol     = signal.get("symbol", "")
        confidence = float(signal.get("confidence", 0.5))
        price      = float(signal.get("price", 1.0))

        if account_equity <= 0 or price <= 0:
            return SizingResult(
                kelly_fraction=0.0, recommended_notional=0.0, recommended_qty=0.0,
                var_check_passed=False, var_limit=0.0,
                rejection_reason="Invalid equity or price"
            )

        # --- Kelly Fraction ---
        p = confidence
        q = 1.0 - p
        b = self.reward_risk_ratio
        raw_kelly = (p * b - q) / b           # raw Kelly fraction (0..1 for winning edge)
        kelly = max(0.0, raw_kelly)            # Kelly is 0 if edge is negative
        capped_kelly = kelly * self.max_kelly_fraction  # fractional Kelly (safer)

        # --- Notional Calculation ---
        notional = account_equity * capped_kelly

        # Apply hard caps
        max_notional = min(account_equity * self.max_position_pct, self.max_position_usd)
        notional = min(notional, max_notional)

        # --- VaR Gate ---
        # Daily 1% VaR at 95% confidence: max loss = equity * var_pct / confidence_level
        var_limit = account_equity * VAR_DAILY_PCT / VAR_CONFIDENCE
        var_passed = notional <= var_limit

        if not var_passed:
            notional = var_limit  # clamp to VaR limit rather than outright reject
            logger.info("[EXPOSURE] Notional clamped to VaR limit $%.2f", var_limit)

        qty = round(notional / price, 6) if price > 0 else 0.0

        logger.info(
            "[EXPOSURE] %s kelly=%.4f capped=%.4f notional=$%.2f qty=%.6f var_limit=$%.2f",
            symbol, kelly, capped_kelly, notional, qty, var_limit
        )

        return SizingResult(
            kelly_fraction=round(capped_kelly, 6),
            recommended_notional=round(notional, 2),
            recommended_qty=qty,
            var_check_passed=var_passed,
            var_limit=round(var_limit, 2),
            rejection_reason=None,
        )


exposure_manager = ExposureManager()
