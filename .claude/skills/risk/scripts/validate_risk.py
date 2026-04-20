"""
validate_risk.py — Deterministic 4-Gate Risk Checker

Guardrails:
  1. Domain expertise embedded in risk logic — compliance before action
  2. Code is deterministic: scripts validate risk, not language instructions
  3. Progressive disclosure: SKILL.md keeps core rules, details in references/
  4. Parallel sub-agents per market — up to 10+ simultaneous signals
  5. Iterative improvement: compound skill logs every loss + pattern fix

Gates (evaluated in order):
  1. Daily drawdown:       (sod_equity - current_equity) / sod_equity >= 0.02 → HALT
  2. Confidence:           signal_confidence < 0.30 → REJECT
  3. VaR:                  recommended_notional × vol > var_limit × equity → CLAMP
  4. Cumulative MDD:       mdd_pct >= 0.08 → SOFT HALT (manual resume required)

Usage:
    result = validate_risk(
        sod_equity=100000, current_equity=98500, peak_equity=102000,
        signal_confidence=0.75, recommended_notional=8000,
        portfolio_vol=0.012, account_equity=98500,
    )

Standalone test:
    python validate_risk.py
"""

from __future__ import annotations
import json

# Thresholds (read from env in production — mirrored here for offline use)
MAX_DAILY_DRAWDOWN_PCT       = 0.02    # 2% daily halt
MAX_CUMULATIVE_DRAWDOWN_PCT  = 0.08    # 8% all-time halt
MIN_SIGNAL_CONFIDENCE        = 0.30
MAX_PORTFOLIO_VAR_PCT        = 0.01    # 1-day 95% VaR limit as % of NAV


def validate_risk(
    sod_equity: float,
    current_equity: float,
    peak_equity: float,
    signal_confidence: float,
    recommended_notional: float,
    portfolio_vol: float,
    account_equity: float,
) -> dict:
    """
    Full 4-gate risk validation.

    Returns:
        {"passed": bool, "gate": str | None, "reason": str, "action": str}
        action: "HALT" | "REJECT" | "CLAMP" | "SOFT_HALT" | "PASS"
    """
    # Gate 1: Daily drawdown
    if sod_equity > 0:
        daily_dd = (sod_equity - current_equity) / sod_equity
        if daily_dd >= MAX_DAILY_DRAWDOWN_PCT:
            return {
                "passed": False,
                "gate":   "gate_1_daily_drawdown",
                "reason": f"Daily drawdown {daily_dd:.2%} ≥ {MAX_DAILY_DRAWDOWN_PCT:.0%} limit",
                "action": "HALT",
            }

    # Gate 2: Confidence
    if signal_confidence < MIN_SIGNAL_CONFIDENCE:
        return {
            "passed": False,
            "gate":   "gate_2_confidence",
            "reason": f"Signal confidence {signal_confidence:.2f} < {MIN_SIGNAL_CONFIDENCE} minimum",
            "action": "REJECT",
        }

    # Gate 3: VaR check
    var_limit_usd  = account_equity * MAX_PORTFOLIO_VAR_PCT
    position_var   = recommended_notional * portfolio_vol
    var_clamped    = False
    if position_var > var_limit_usd and var_limit_usd > 0:
        var_clamped = True
        recommended_notional = var_limit_usd / portfolio_vol if portfolio_vol > 0 else var_limit_usd

    # Gate 4: Cumulative MDD
    if peak_equity > 0:
        cum_mdd = (peak_equity - current_equity) / peak_equity
        if cum_mdd >= MAX_CUMULATIVE_DRAWDOWN_PCT:
            return {
                "passed": False,
                "gate":   "gate_4_cumulative_mdd",
                "reason": f"Cumulative MDD {cum_mdd:.2%} ≥ {MAX_CUMULATIVE_DRAWDOWN_PCT:.0%} — manual resume required",
                "action": "SOFT_HALT",
            }

    return {
        "passed":               True,
        "gate":                 None,
        "reason":               "All 4 gates passed" + (" (VaR clamped)" if var_clamped else ""),
        "action":               "CLAMP" if var_clamped else "PASS",
        "recommended_notional": round(recommended_notional, 2),
        "var_clamped":          var_clamped,
    }


if __name__ == "__main__":
    cases = [
        # All pass
        dict(sod_equity=100000, current_equity=99000, peak_equity=100000,
             signal_confidence=0.75, recommended_notional=5000, portfolio_vol=0.01, account_equity=99000),
        # Gate 1: daily drawdown
        dict(sod_equity=100000, current_equity=97500, peak_equity=100000,
             signal_confidence=0.75, recommended_notional=5000, portfolio_vol=0.01, account_equity=97500),
        # Gate 2: low confidence
        dict(sod_equity=100000, current_equity=99000, peak_equity=100000,
             signal_confidence=0.20, recommended_notional=5000, portfolio_vol=0.01, account_equity=99000),
        # Gate 4: cumulative MDD
        dict(sod_equity=95000, current_equity=90000, peak_equity=103000,
             signal_confidence=0.75, recommended_notional=5000, portfolio_vol=0.01, account_equity=90000),
    ]
    for c in cases:
        print(json.dumps(validate_risk(**c), indent=2))