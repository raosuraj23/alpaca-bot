---
name: predict
description: Signal approval — XGBoost probability gate + dual LLM ensemble vote (Gemini + Haiku AND logic) with calibration tracking. Use when "signal", "approve", "predict", "ensemble", "confidence", "vote", "xgboost", "probability".
metadata:
  version: 2.0.0
  pattern: context-aware
  tags: [signal, approval, ensemble, gemini, haiku, orchestrator, calibration, brier, xgboost, probability]
---

# Predict Skill

## Triggers

Called by:
1. `main.py` bar callbacks (TA signal pipeline) — for every strategy signal from `StrategyEngine.process_tick()`
2. `orchestrator.process_signal()` — for research/breaking-news signals from `ResearchAgent`

---

## 3-Layer Approval Pipeline

```
TA signal from StrategyEngine
        ↓
[Layer 1] XGBoost Probability Gate       ← NEW
  • extract_features(signal) → 10-dim feature vector
  • xgb_classifier.gate(features, market_implied_prob)
  • Reject if P(win) < 0.55 OR edge < 0.04
        ↓
[Layer 2] LLM Ensemble Voting (unchanged)
  Gemini Flash (50t) ──┐
                       ├── AND gate → APPROVE/REJECT
  Haiku (100t)      ──┘
        ↓
[Layer 3] RiskAgent: Kelly sizing + VaR
        ↓
ExecutionAgent: Alpaca order
```

---

## Layer 1 — XGBoost Probability Gate

Code path: `backend/predict/`

### Feature Vector (10 dimensions)

| Index | Name | Source |
|-------|------|--------|
| 0 | `ema_spread_ratio` | `(ema_fast - ema_slow) / ema_slow` |
| 1 | `rsi_14_norm` | `rsi_14 / 100.0` |
| 2 | `volume_surge_ratio` | raw from signal meta |
| 3 | `golden_cross_flag` | bool → 1.0/0.0 |
| 4 | `rsi_gate_flag` | RSI in 40–60 zone → 1.0/0.0 |
| 5 | `volume_surge_flag` | vol > 1.5× SMA → 1.0/0.0 |
| 6 | `bb_position` | Bollinger band position (0=lower, 1=upper) |
| 7 | `atr_norm` | ATR / price |
| 8 | `momentum_z` | `(price - sma20) / std20` |
| 9 | `confidence_raw` | TA signal confidence (0–1) |

Missing optional fields default to 0.5 (neutral).

### Market-Implied Probability

```
p_mkt = sigmoid(momentum_z) = 1 / (1 + exp(-z))
```

z=0 → 50% (no directional edge); z=+2 → ~88%

### Gate Thresholds (from `config.py` / env)

```python
XGBOOST_MIN_CONFIDENCE = 0.55   # env: XGBOOST_MIN_CONFIDENCE
MIN_EDGE               = 0.04   # env: MIN_EDGE (shared with ResearchAgent)
```

A signal is approved if: `P(win) ≥ 0.55 AND (P(win) - p_mkt) ≥ 0.04`

### Cold-Start Behaviour

- No model file or `< 50` closed trades: gate passes all signals (`approved=True`), logged as "cold start"
- Once trained: persists to `backend/models/xgboost_signal.pkl`
- Retrains nightly via `NightlyConsolidation.run_daily_snapshot()` at 23:55 UTC
- Also trained at startup if sufficient history exists

### Training Data

JOIN: `SignalRecord.signal_features` + `ClosedTrade.win` matched on `(strategy=bot_id, symbol, timestamp ±5 min)`
Model: `XGBClassifier(n_estimators=100, max_depth=4, learning_rate=0.1)`

---

## Layer 2 — Ensemble Voting (Dual LLM)

Two models run **in parallel** via `asyncio.gather()`:

| Voter | Model | Budget | Tier |
|-------|-------|--------|------|
| Primary | `gemini-2.5-flash` | 50t | `signal` |
| Secondary | `claude-haiku-4-5-20251001` | 100t | `chat` |

**Approval logic:** AND — both must output `APPROVED` or the signal is `REJECTED`.

**Disagreement handling:** If voters differ, log `[VOTER DISAGREEMENT]` at WARNING level, include both rationales in the rejection message, and REJECT.

### Response Format (each voter)

```json
{"llm_decision": "APPROVED" | "REJECTED", "rationale": "one sentence"}
```

### Combined Output

```json
{
  "llm_decision": "APPROVED" | "REJECTED",
  "rationale": "Gemini: <rationale> | Haiku: <rationale>",
  "signal_event": {...}
}
```

---

## Cost Logging

Each LLM voter logs its own `LLMUsage` row with `purpose="orchestrator_signal_vote"`.

Cost per signal (LLM only — XGBoost is CPU-only, no API cost):
- Gemini Flash 50t: ~$0.000004
- Haiku 100t: ~$0.000080
- Total: ~$0.000084 (negligible)

XGBoost gate saves LLM cost by blocking low-probability signals before voters are called.

---

## Calibration Tracking

After every closed trade:
- `CalibrationTracker.log(strategy, confidence, outcome)` records (forecast, binary outcome)
- `brier_score()` = mean((forecast − outcome)²) over a rolling 100-trade window
- `calibration_scalar()` maps Brier Score [0.00–0.25] → Kelly multiplier [0.50–0.25]
  - Perfectly calibrated (BS=0.00) → half-Kelly (0.50)
  - Random guessing (BS=0.25) → quarter-Kelly (0.25)

Code path: `backend/risk/calibration.py → CalibrationTracker`

---

## Minimum Confidence Gate

Even before the XGBoost gate, a signal must pass `settings.min_signal_confidence` (0.30). Enforced by `kill_switch.evaluate_signal()` in `risk_agent.check()`.

---

## DB Fields Written Per Signal (SignalRecord)

| Column | Source |
|--------|--------|
| `xgboost_prob` | XGBoost P(win) |
| `market_implied_prob` | sigmoid(momentum_z) |
| `market_edge` | xgb_prob - market_implied_prob |
| `signal_features` | JSON feature vector (10 dims) |

---

## References

- `backend/predict/feature_extractor.py` — feature extraction + market_implied_prob
- `backend/predict/xgboost_classifier.py` — XGBoost training + gate
- `backend/agents/orchestrator.py` — dual voter implementation + XGBoost pre-gate
- `backend/risk/calibration.py` — Brier score + Kelly scalar
- `backend/agents/factory.py` — `build_model(model_level)` tier definitions
- `.claude/skills/predict/scripts/validate_signal.py` — standalone validator
- `.claude/skills/predict/references/probability_formulas.md` — mathematical reference
