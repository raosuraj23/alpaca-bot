"""
validate_edge.py — Edge Detection & EV Validator

Guardrails:
  1. Domain expertise embedded in risk logic — compliance before action
  2. Code is deterministic: scripts validate risk, not language instructions
  3. Progressive disclosure: SKILL.md keeps core rules, details in references/
  4. Parallel sub-agents per market — up to 10+ simultaneous signals
  5. Iterative improvement: compound skill logs every loss + pattern fix

Usage:
    result = validate_edge(p_model=0.72, p_mkt=0.65, decimal_odds=1.538, sigma=0.04)
    # {"edge": 0.07, "ev": 0.108, "mispricing_z": 1.75, "passed": True, "reason": "..."}

Standalone test:
    python validate_edge.py
"""

from __future__ import annotations
import json
import math

MIN_EDGE = 0.04   # Minimum model-vs-market edge required to trade


def validate_edge(
    p_model: float,
    p_mkt: float,
    decimal_odds: float = 2.0,
    sigma: float | None = None,
) -> dict:
    """
    Compute edge, expected value, and mispricing Z-score.

    Args:
        p_model:       Model probability estimate (0–1)
        p_mkt:         Market-implied probability (0–1)
        decimal_odds:  Decimal odds from the market (b = decimal_odds - 1)
        sigma:         Price volatility std-dev for Z-score (optional)

    Returns:
        {
          "edge": float,          # p_model - p_mkt
          "ev": float,            # p*b - (1-p)
          "mispricing_z": float,  # (p_model - p_mkt) / sigma, or None
          "passed": bool,         # edge > MIN_EDGE
          "reason": str,
        }
    """
    if not (0.0 < p_model < 1.0):
        raise ValueError(f"p_model must be in (0, 1): {p_model}")
    if not (0.0 < p_mkt < 1.0):
        raise ValueError(f"p_mkt must be in (0, 1): {p_mkt}")
    if decimal_odds <= 1.0:
        raise ValueError(f"decimal_odds must be > 1: {decimal_odds}")

    b    = decimal_odds - 1.0   # net odds (profit per unit bet)
    edge = p_model - p_mkt
    ev   = p_model * b - (1.0 - p_model)

    mispricing_z = None
    if sigma and sigma > 0:
        mispricing_z = round(edge / sigma, 4)

    passed = edge > MIN_EDGE
    reason = (
        f"edge {edge:.4f} > {MIN_EDGE} ✓" if passed
        else f"edge {edge:.4f} ≤ {MIN_EDGE} — below minimum threshold"
    )

    return {
        "edge":          round(edge, 4),
        "ev":            round(ev, 4),
        "mispricing_z":  mispricing_z,
        "passed":        passed,
        "reason":        reason,
    }


def bayes_update(prior: float, likelihood_given_h: float, likelihood: float) -> float:
    """
    P(H|E) = P(E|H) * P(H) / P(E)

    Args:
        prior:               P(H)
        likelihood_given_h:  P(E|H)
        likelihood:          P(E)  = P(E|H)*P(H) + P(E|not H)*P(not H)
    """
    if likelihood <= 0:
        raise ValueError("P(E) must be positive")
    posterior = (likelihood_given_h * prior) / likelihood
    return round(min(max(posterior, 0.0), 1.0), 6)


if __name__ == "__main__":
    cases = [
        dict(p_model=0.72, p_mkt=0.65, decimal_odds=1.538, sigma=0.04),
        dict(p_model=0.60, p_mkt=0.57, decimal_odds=1.75),   # edge below threshold
        dict(p_model=0.80, p_mkt=0.70, decimal_odds=1.43, sigma=0.05),
    ]
    for c in cases:
        print(json.dumps(validate_edge(**c), indent=2))

    print("\nBayes update example:")
    print(bayes_update(prior=0.65, likelihood_given_h=0.85, likelihood=0.70))