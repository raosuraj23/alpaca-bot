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
from config import settings

logger = logging.getLogger(__name__)

# Risk parameters — sourced from config so they're overridable via env vars
MAX_POSITION_PCT    = 0.10                       # 10% of equity hard cap (structural constant)
MAX_POSITION_USD    = 50_000                     # $50k absolute cap (structural constant)
MAX_KELLY_FRACTION  = settings.max_kelly_fraction
REWARD_RISK_RATIO   = settings.reward_risk_ratio
VAR_DAILY_PCT       = settings.var_daily_pct
VAR_CONFIDENCE      = settings.var_confidence


def kelly_fraction(
    win_rate: float,
    win_loss_ratio: float,
    kelly_scale: float = 0.25,
) -> float:
    """
    Fractional Kelly sizing adapted for continuous price-action assets.

    Full Kelly: f* = W - (1 - W) / R
    where W = win_rate, R = win/loss ratio (reward:risk).
    Use fractional Kelly (0.25–0.50) for live trading to reduce variance.

    Args:
        win_rate:       Historical win rate 0 < W < 1
        win_loss_ratio: Average win / average loss (R ratio), must be > 0
        kelly_scale:    Fraction of full Kelly to use (0.25 = quarter-Kelly, 0.50 = half-Kelly)

    Returns:
        Fractional Kelly position size as a fraction of bankroll, floored at 0.
    """
    if win_loss_ratio <= 0 or not 0.0 < win_rate < 1.0:
        raise ValueError(f"Invalid Kelly inputs: win_rate={win_rate}, win_loss_ratio={win_loss_ratio}")
    full_kelly = win_rate - (1.0 - win_rate) / win_loss_ratio
    return max(0.0, full_kelly * kelly_scale)  # floored at zero — never size negatively


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
        bot_id     = signal.get("bot", "")
        confidence = float(signal.get("confidence", 0.5))
        price      = float(signal.get("price", 1.0))

        if account_equity <= 0 or price <= 0:
            return SizingResult(
                kelly_fraction=0.0, recommended_notional=0.0, recommended_qty=0.0,
                var_check_passed=False, var_limit=0.0,
                rejection_reason="Invalid equity or price"
            )

        # SELL signals reduce exposure — skip Kelly sizing, use the signal's actual qty
        if signal.get("action", "").upper() == "SELL":
            sell_qty = float(signal.get("qty", 0.0))
            logger.info("[EXPOSURE] SELL %s qty=%.9f (exit order — Kelly sizing skipped)", symbol, sell_qty)
            return SizingResult(
                kelly_fraction=0.0,
                recommended_notional=round(sell_qty * price, 2),
                recommended_qty=sell_qty,
                var_check_passed=True,
                var_limit=0.0,
                rejection_reason=None,
            )

        # --- Dynamic Kelly Fraction via calibration scalar ---
        # calibration_scalar returns [0.25, 0.50] based on rolling Brier Score.
        # Well-calibrated strategies earn higher position sizes; poor ones are capped at quarter-Kelly.
        try:
            from risk.calibration import calibration_tracker
            cal_scalar = calibration_tracker.calibration_scalar(bot_id)
        except Exception:
            cal_scalar = self.max_kelly_fraction  # fallback if calibration not loaded

        p = confidence
        q = 1.0 - p
        b = self.reward_risk_ratio
        raw_kelly = (p * b - q) / b           # raw Kelly fraction (0..1 for winning edge)
        kelly = max(0.0, raw_kelly)            # Kelly is 0 if edge is negative
        capped_kelly = kelly * cal_scalar      # dynamic fractional Kelly

        # --- Notional Calculation ---
        notional = account_equity * capped_kelly

        # Apply hard caps — use bot's allocation_pct if present, else fall back to config max_position_pct
        alloc_pct = signal.get("allocation_pct", self.max_position_pct) if isinstance(signal, dict) else self.max_position_pct
        max_notional = min(account_equity * alloc_pct, self.max_position_usd)
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
            "[EXPOSURE] %s kelly=%.4f capped=%.4f(scalar=%.2f) notional=$%.2f qty=%.6f var_limit=$%.2f",
            symbol, kelly, capped_kelly, cal_scalar, notional, qty, var_limit
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
