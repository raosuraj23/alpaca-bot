"""
kelly_size.py — Kelly Criterion Position Calculator

Guardrails:
  1. Domain expertise embedded in risk logic — compliance before action
  2. Code is deterministic: scripts validate risk, not language instructions
  3. Progressive disclosure: SKILL.md keeps core rules, details in references/
  4. Parallel sub-agents per market — up to 10+ simultaneous signals
  5. Iterative improvement: compound skill logs every loss + pattern fix

Formulas:
  Full Kelly:       f* = W - (1-W)/R
  Fractional Kelly: f  = α × f*    where α ∈ [0.25, 0.50]
  α from Brier:     α  = 0.50 - (BS / 0.25) × 0.25  (clamped to [0.25, 0.50])

Hard caps applied after Kelly:
  - max 10% of account equity per position
  - max $50,000 notional regardless of portfolio size

Usage:
    result = kelly_size(
        win_rate=0.68, reward_risk_ratio=2.0,
        account_equity=100000, brier_score=0.18,
        price=65000,
    )

Standalone test:
    python kelly_size.py
"""

from __future__ import annotations
import json
import math

MAX_POSITION_PCT = 0.10      # 10% of account equity
MAX_POSITION_USD = 50_000.0  # hard notional cap
REWARD_RISK_RATIO_DEFAULT = 2.0


def kelly_alpha(brier_score: float | None) -> float:
    """
    Derive fractional Kelly multiplier α from the strategy's Brier score.

    BS = 0.00 (perfect) → α = 0.50 (half-Kelly)
    BS = 0.25 (random)  → α = 0.25 (quarter-Kelly floor)
    """
    if brier_score is None:
        return 0.25   # conservative default until calibration data exists
    alpha = 0.50 - (brier_score / 0.25) * 0.25
    return round(max(0.25, min(0.50, alpha)), 4)


def kelly_size(
    win_rate: float,
    account_equity: float,
    reward_risk_ratio: float = REWARD_RISK_RATIO_DEFAULT,
    brier_score: float | None = None,
    price: float | None = None,
) -> dict:
    """
    Compute Kelly position size with hard caps.

    Args:
        win_rate:          Historical win rate (0–1) or signal confidence
        account_equity:    Total portfolio value in USD
        reward_risk_ratio: Expected reward / risk ratio (default 2.0)
        brier_score:       Model Brier score for α scaling (None = conservative)
        price:             Asset price (used to compute share/unit quantity)

    Returns:
        {
          "kelly_full":           float,  # f* before fractional scaling
          "kelly_fraction":       float,  # f after α scaling
          "alpha":                float,  # Brier-derived multiplier
          "recommended_notional": float,  # USD, after hard caps
          "recommended_qty":      float | None,
          "cap_applied":          str | None,
        }
    """
    if not (0.0 < win_rate < 1.0):
        raise ValueError(f"win_rate must be in (0, 1): {win_rate}")
    if reward_risk_ratio <= 0:
        raise ValueError(f"reward_risk_ratio must be positive: {reward_risk_ratio}")
    if account_equity <= 0:
        raise ValueError(f"account_equity must be positive: {account_equity}")

    # Full Kelly: f* = W - (1-W)/R
    full_kelly = win_rate - (1.0 - win_rate) / reward_risk_ratio
    full_kelly = max(0.0, full_kelly)

    # Fractional Kelly via Brier-derived α
    alpha          = kelly_alpha(brier_score)
    frac_kelly     = full_kelly * alpha
    raw_notional   = frac_kelly * account_equity

    # Apply hard caps
    cap_applied = None
    pct_cap     = account_equity * MAX_POSITION_PCT
    notional    = raw_notional

    if notional > MAX_POSITION_USD:
        notional    = MAX_POSITION_USD
        cap_applied = f"USD cap ${MAX_POSITION_USD:,.0f}"
    if notional > pct_cap:
        notional    = pct_cap
        cap_applied = f"10% equity cap ${pct_cap:,.0f}"

    qty = None
    if price and price > 0:
        qty = round(notional / price, 6)

    return {
        "kelly_full":           round(full_kelly, 6),
        "kelly_fraction":       round(frac_kelly, 6),
        "alpha":                alpha,
        "recommended_notional": round(notional, 2),
        "recommended_qty":      qty,
        "cap_applied":          cap_applied,
    }


if __name__ == "__main__":
    cases = [
        dict(win_rate=0.68, account_equity=100000, reward_risk_ratio=2.0, brier_score=0.18, price=65000),
        dict(win_rate=0.55, account_equity=50000,  reward_risk_ratio=1.5, brier_score=0.22, price=180),
        dict(win_rate=0.60, account_equity=500000, reward_risk_ratio=2.0, brier_score=0.10, price=420),
    ]
    for c in cases:
        print(json.dumps(kelly_size(**c), indent=2))
