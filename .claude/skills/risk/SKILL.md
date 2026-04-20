---
name: risk
description: Risk sizing and kill-switch — Kelly criterion, VaR gate, drawdown limits, position caps. Use when "risk", "kelly", "size", "drawdown", "kill switch", "var", "position limit".
metadata:
  version: 1.0.0
  pattern: context-aware
  tags: [risk, kelly, var, kill-switch, drawdown, calibration, position, sizing]
---

# Risk Skill

## Gate Pipeline (3 sequential checks)

Every signal must pass all three gates before reaching the execution agent:

```
1. kill_switch.evaluate_portfolio() — daily drawdown check
2. kill_switch.evaluate_signal()    — minimum confidence check
3. exposure_manager.size()          — Kelly sizing + VaR gate
```

Code path: `backend/agents/risk_agent.py → check()`, wraps `backend/risk/`

---

## Kill Switch Thresholds

| Parameter | Value | Source |
|-----------|-------|--------|
| Max daily drawdown | 2% of SOD equity | `settings.max_daily_drawdown_pct` |
| Min signal confidence | 0.30 | `settings.min_signal_confidence` |
| Auto-reset | UTC midnight (new trading day) | `kill_switch.py` |

**Manual override:** `kill_switch.manual_halt(reason)` / `manual_resume()` — persists until explicitly cleared.

Code path: `backend/risk/kill_switch.py`

---

## Kelly Criterion (Position Sizing)

```
Full Kelly:  f* = W - (1-W)/R
where W = win_rate (signal confidence), R = reward:risk ratio (settings.reward_risk_ratio = 2.0)

Applied:     kelly_fraction = f* × calibration_scalar
```

`calibration_scalar` from `CalibrationTracker.calibration_scalar(strategy)`:
- Brier Score = 0.00 (perfect) → scalar = 0.50 (half-Kelly)
- Brier Score = 0.25 (random) → scalar = 0.25 (quarter-Kelly floor)

**Hard caps applied after Kelly:**
- Max 10% of account equity per position (`settings.max_position_pct`)
- Max $50,000 notional regardless of equity (`settings.max_position_usd` = 50,000)

Code path: `backend/risk/exposure.py → ExposureManager.size()`, `backend/risk/calibration.py`

---

## VaR Gate (1-Day, 95% Confidence)

```
MAX_PORTFOLIO_VAR_PCT = settings.var_daily_pct  # default 0.01 (1% of NAV)
```

Computed via historical simulation on the position's symbol. If `recommended_notional` exceeds the VaR limit, it is **clamped** to the limit (not outright rejected) and `var_check_passed = False` is flagged in `RiskCheckResult`.

---

## Position Limits

| Parameter | Value | Source |
|-----------|-------|--------|
| Max concurrent positions | 15 | `settings.max_concurrent_positions` |
| Max slippage before abort | 2% | `settings.slippage_abort_pct` |
| Min days to expiry (options) | 5 | `security-and-risk.md §2.7` |
| Max net delta (options) | 30% of NAV | `security-and-risk.md §2.7` |

---

## Anomalous API Behavior Detector

Trading is suspended and an alert raised if:
- Alpaca API returns HTTP 5xx > 3 times in 60 seconds
- Fill price deviates > 3 standard deviations from mid-quote
- Account equity changes > 5% in under 60 seconds (flash crash guard)

---

## Output Contract (`RiskCheckResult`)

```python
@dataclass
class RiskCheckResult:
    passed: bool
    reason: str
    kelly_fraction: float
    recommended_notional: float
    recommended_qty: float
    var_check_passed: bool
    var_limit: float
```

---

## References

- `backend/risk/kill_switch.py` — drawdown circuit breaker
- `backend/risk/exposure.py` — Kelly sizing + VaR gate
- `backend/risk/calibration.py` — Brier score → Kelly scalar
- `backend/agents/risk_agent.py` — 3-gate pipeline
- `.claude/rules/security-and-risk.md` — full mandate (MANDATORY reading)