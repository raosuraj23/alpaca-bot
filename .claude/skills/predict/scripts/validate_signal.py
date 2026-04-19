"""
validate_signal.py — Ensemble Vote Validator

Guardrails:
  1. Domain expertise embedded in risk logic — compliance before action
  2. Code is deterministic: scripts validate risk, not language instructions
  3. Progressive disclosure: SKILL.md keeps core rules, details in references/
  4. Parallel sub-agents per market — up to 10+ simultaneous signals
  5. Iterative improvement: compound skill logs every loss + pattern fix

Usage:
    result = validate_signal(
        gemini_vote="APPROVE", gemini_confidence=0.82,
        haiku_vote="APPROVE",  haiku_confidence=0.75,
    )
    # {"approved": True, "consensus_confidence": 0.785, "confidence_delta": 0.07, ...}

    gate = validate_xgboost_gate(xgb_prob=0.62, market_implied_prob=0.51)
    # {"approved": True, "edge": 0.11, ...}

Standalone test:
    python validate_signal.py
"""

from __future__ import annotations
import json
import logging

logger = logging.getLogger(__name__)

MIN_CONFIDENCE         = 0.30   # Minimum signal confidence to even consider
AGREEMENT_REQUIRED     = True   # AND logic: both models must APPROVE
XGBOOST_MIN_CONFIDENCE = 0.55   # XGBoost P(win) gate threshold
MIN_EDGE               = 0.04   # XGBoost P(win) - market_implied_prob threshold


# ---------------------------------------------------------------------------
# Layer 1 — XGBoost Gate
# ---------------------------------------------------------------------------

def validate_xgboost_gate(xgb_prob: float, market_implied_prob: float) -> dict:
    """
    XGBoost probability gate validator.

    Rejects if:
      - xgb_prob < XGBOOST_MIN_CONFIDENCE (0.55)
      - (xgb_prob - market_implied_prob) < MIN_EDGE (0.04)

    Returns:
        {
          "approved": bool,
          "xgboost_prob": float,
          "market_implied_prob": float,
          "edge": float,
          "reason": str,
        }
    """
    edge = round(xgb_prob - market_implied_prob, 4)

    if xgb_prob < XGBOOST_MIN_CONFIDENCE:
        return {
            "approved": False,
            "xgboost_prob": round(xgb_prob, 4),
            "market_implied_prob": round(market_implied_prob, 4),
            "edge": edge,
            "reason": f"XGBoost P(win)={xgb_prob:.3f} < threshold {XGBOOST_MIN_CONFIDENCE:.2f}",
        }

    if edge < MIN_EDGE:
        return {
            "approved": False,
            "xgboost_prob": round(xgb_prob, 4),
            "market_implied_prob": round(market_implied_prob, 4),
            "edge": edge,
            "reason": (
                f"edge={edge:.3f} (P(win)={xgb_prob:.3f} - p_mkt={market_implied_prob:.3f}) "
                f"< min_edge {MIN_EDGE:.2f}"
            ),
        }

    return {
        "approved": True,
        "xgboost_prob": round(xgb_prob, 4),
        "market_implied_prob": round(market_implied_prob, 4),
        "edge": edge,
        "reason": (
            f"approved — P(win)={xgb_prob:.3f} edge={edge:+.3f} "
            f"(threshold: conf≥{XGBOOST_MIN_CONFIDENCE:.2f}, edge≥{MIN_EDGE:.2f})"
        ),
    }


# ---------------------------------------------------------------------------
# Layer 2 — LLM Ensemble Gate
# ---------------------------------------------------------------------------

def validate_signal(
    gemini_vote: str,
    gemini_confidence: float,
    haiku_vote: str,
    haiku_confidence: float,
) -> dict:
    """
    Dual LLM ensemble vote validator (AND logic).

    Both Gemini Flash and Claude Haiku must vote APPROVE.
    Consensus confidence = mean of both confidence scores.

    Returns:
        {
          "approved": bool,
          "consensus_confidence": float,
          "confidence_delta": float,  # abs(gemini_conf - haiku_conf)
          "disagreement": bool,
          "reason": str,
        }
    """
    gemini_vote = (gemini_vote or "").upper().strip()
    haiku_vote  = (haiku_vote  or "").upper().strip()

    if gemini_confidence < MIN_CONFIDENCE:
        return _reject(
            gemini_confidence, haiku_confidence,
            f"Gemini confidence {gemini_confidence:.2f} < {MIN_CONFIDENCE} minimum",
        )

    if haiku_confidence < MIN_CONFIDENCE:
        return _reject(
            gemini_confidence, haiku_confidence,
            f"Haiku confidence {haiku_confidence:.2f} < {MIN_CONFIDENCE} minimum",
        )

    disagreement = (gemini_vote != haiku_vote)
    if disagreement:
        logger.warning(
            "[PREDICT] Ensemble disagreement: Gemini=%s (%.2f) vs Haiku=%s (%.2f)",
            gemini_vote, gemini_confidence, haiku_vote, haiku_confidence,
        )

    both_approve = (gemini_vote == "APPROVE" and haiku_vote == "APPROVE")
    consensus    = (gemini_confidence + haiku_confidence) / 2.0
    delta        = abs(gemini_confidence - haiku_confidence)

    if not both_approve:
        return {
            "approved":             False,
            "consensus_confidence": round(consensus, 4),
            "confidence_delta":     round(delta, 4),
            "disagreement":         disagreement,
            "reason":               f"AND-gate failed: Gemini={gemini_vote}, Haiku={haiku_vote}",
        }

    return {
        "approved":             True,
        "consensus_confidence": round(consensus, 4),
        "confidence_delta":     round(delta, 4),
        "disagreement":         disagreement,
        "reason":               f"Both APPROVE — consensus confidence {consensus:.2%}",
    }


def _reject(gc: float, hc: float, reason: str) -> dict:
    return {
        "approved":             False,
        "consensus_confidence": round((gc + hc) / 2.0, 4),
        "confidence_delta":     round(abs(gc - hc), 4),
        "disagreement":         False,
        "reason":               reason,
    }


if __name__ == "__main__":
    print("=== Layer 1: XGBoost Gate ===")
    xgb_cases = [
        dict(xgb_prob=0.62, market_implied_prob=0.51),   # approved — clear edge
        dict(xgb_prob=0.62, market_implied_prob=0.60),   # rejected — edge < 0.04
        dict(xgb_prob=0.48, market_implied_prob=0.40),   # rejected — P(win) < 0.55
        dict(xgb_prob=0.55, market_implied_prob=0.50),   # approved — just at threshold
    ]
    for c in xgb_cases:
        print(json.dumps(validate_xgboost_gate(**c), indent=2))

    print("\n=== Layer 2: LLM Ensemble ===")
    llm_cases = [
        dict(gemini_vote="APPROVE", gemini_confidence=0.82, haiku_vote="APPROVE",  haiku_confidence=0.75),
        dict(gemini_vote="APPROVE", gemini_confidence=0.78, haiku_vote="REJECT",   haiku_confidence=0.55),
        dict(gemini_vote="REJECT",  gemini_confidence=0.60, haiku_vote="APPROVE",  haiku_confidence=0.80),
        dict(gemini_vote="APPROVE", gemini_confidence=0.25, haiku_vote="APPROVE",  haiku_confidence=0.30),
    ]
    for c in llm_cases:
        print(json.dumps(validate_signal(**c), indent=2))
