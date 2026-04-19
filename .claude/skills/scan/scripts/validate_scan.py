"""
validate_scan.py — Deterministic TA Score Validator

Guardrails:
  1. Domain expertise embedded in risk logic — compliance before action
  2. Code is deterministic: scripts validate risk, not language instructions
  3. Progressive disclosure: SKILL.md keeps core rules, details in references/
  4. Parallel sub-agents per market — up to 10+ simultaneous signals
  5. Iterative improvement: compound skill logs every loss + pattern fix

Usage:
    result = validate_scan(price=65000, ema20=63000, rsi=52, volume=1500,
                           volume_avg=900, bb_lower=61000, bb_upper=67000)
    # {"score": 2.0, "signal": "BUY", "reasons": [...], "passed": True}

Standalone test:
    python validate_scan.py
"""

from __future__ import annotations
import json
import math


MIN_BUY_SCORE  =  1.0
MIN_SELL_SCORE = -1.0


def validate_scan(
    price: float,
    ema20: float,
    rsi: float,
    volume: float,
    volume_avg: float,
    bb_lower: float,
    bb_upper: float,
) -> dict:
    """
    Compute composite TA score and derive signal.

    Score table (mirrors scanner_agent._score_symbol):
      price > EMA20               → +1.0
      price < EMA20               → -1.0
      45 < RSI(14) < 65           → +1.0
      RSI > 70 or RSI < 30        → -0.5
      volume > 1.5× 7-day avg     → +0.5
      price in lower 25% BB band  → +0.5
      price in upper 75% BB band  → -0.3

    Returns:
        {"score": float, "signal": "BUY"|"SELL"|"NEUTRAL",
         "reasons": list[str], "passed": bool}
    """
    if math.isnan(price) or price <= 0:
        raise ValueError(f"Invalid price: {price}")
    if math.isnan(ema20) or ema20 <= 0:
        raise ValueError(f"Invalid EMA20: {ema20}")
    if not (0 <= rsi <= 100):
        raise ValueError(f"RSI out of range: {rsi}")
    if volume < 0 or volume_avg < 0:
        raise ValueError("Volume values must be non-negative")

    score = 0.0
    reasons: list[str] = []

    # EMA trend
    if price > ema20:
        score += 1.0
        reasons.append(f"price ${price:,.2f} > EMA20 ${ema20:,.2f} (+1.0)")
    else:
        score -= 1.0
        reasons.append(f"price ${price:,.2f} < EMA20 ${ema20:,.2f} (-1.0)")

    # RSI band
    if 45 < rsi < 65:
        score += 1.0
        reasons.append(f"RSI {rsi:.1f} in neutral-bullish band 45-65 (+1.0)")
    elif rsi > 70 or rsi < 30:
        score -= 0.5
        reasons.append(f"RSI {rsi:.1f} in extreme zone (>70 or <30) (-0.5)")

    # Volume surge
    if volume_avg > 0 and volume > 1.5 * volume_avg:
        score += 0.5
        reasons.append(f"volume {volume:,.0f} > 1.5× avg {volume_avg:,.0f} (+0.5)")

    # Bollinger Band position
    bb_range = bb_upper - bb_lower
    if bb_range > 0:
        pct_in_band = (price - bb_lower) / bb_range
        if pct_in_band < 0.25:
            score += 0.5
            reasons.append(f"price in lower 25% of BB band (pctile={pct_in_band:.2%}) (+0.5)")
        elif pct_in_band > 0.75:
            score -= 0.3
            reasons.append(f"price in upper 75% of BB band (pctile={pct_in_band:.2%}) (-0.3)")

    if score >= MIN_BUY_SCORE:
        signal = "BUY"
    elif score <= MIN_SELL_SCORE:
        signal = "SELL"
    else:
        signal = "NEUTRAL"

    return {
        "score":   round(score, 2),
        "signal":  signal,
        "reasons": reasons,
        "passed":  signal != "NEUTRAL",
    }


if __name__ == "__main__":
    test_cases = [
        dict(price=65000, ema20=63000, rsi=52, volume=1500, volume_avg=900, bb_lower=61000, bb_upper=67000),
        dict(price=40000, ema20=45000, rsi=28, volume=800,  volume_avg=900, bb_lower=38000, bb_upper=50000),
        dict(price=100,   ema20=100,   rsi=50, volume=100,  volume_avg=100, bb_lower=95,    bb_upper=105),
    ]
    for tc in test_cases:
        print(json.dumps(validate_scan(**tc), indent=2))
