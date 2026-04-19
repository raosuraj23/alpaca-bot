# Probability & Calibration Formulas Reference — Predict Skill

## Full 3-Layer Pipeline

```text
TA signal from StrategyEngine
        ↓
[1] XGBoost Gate: P(win) ≥ 0.55 AND edge ≥ 0.04
        ↓
[2] LLM Ensemble: Gemini APPROVE AND Haiku APPROVE
        ↓
[3] RiskAgent: Kelly sizing + VaR gate → Execution
```

---

## XGBoost Probability Gate

### Feature Vector (10-dim)

```python
features = [
  ema_spread_ratio,   # (ema_fast - ema_slow) / ema_slow
  rsi_14_norm,        # rsi_14 / 100.0
  volume_surge_ratio, # vol / 20-bar avg
  golden_cross_flag,  # bool → 1.0/0.0
  rsi_gate_flag,      # rsi in 40–60 zone → 1.0/0.0
  volume_surge_flag,  # vol > 1.5× threshold → 1.0/0.0
  bb_position,        # (price - lower) / (upper - lower), clamped 0–1
  atr_norm,           # ATR / price
  momentum_z,         # (price - sma20) / std20
  confidence_raw,     # TA signal confidence (0–1)
]
```

Missing optional fields default to 0.5 (neutral).

### Market-Implied Probability

```text
p_mkt = sigmoid(z) = 1 / (1 + exp(-z))
```

where `z = momentum_z = (price - sma20) / std20`

| z-score | p_mkt         |
| ------- | ------------- |
| -2.0    | 12%           |
| -1.0    | 27%           |
| 0.0     | 50% (neutral) |
| +1.0    | 73%           |
| +2.0    | 88%           |

### Confidence + Edge Gate

```text
approved = (xgb_prob ≥ 0.55) AND (edge ≥ 0.04)
where edge = xgb_prob - p_mkt
```

### Cold-Start Behaviour

```python
if not trained OR samples < 50:
    approved = True  # pass-through until model is ready
```

---

## Ensemble AND Logic

```text
approved = (vote_gemini == APPROVE) AND (vote_haiku == APPROVE)
```

Both models must agree. A single REJECT blocks the signal.
Disagreement is logged at WARNING for calibration review.

Rationale: reduces false positives at the cost of missing some true positives.
Target: false positive rate < 10% over rolling 30-day window.

---

## Brier Score (Calibration Accuracy)

```text
BS = (1/n) · Σ (p_i - o_i)²
```

- `p_i` = ensemble consensus confidence for trade i
- `o_i` = actual outcome (1 = profitable, 0 = loss)
- BS = 0.00 → perfect calibration
- BS = 0.25 → random (equivalent to coin flip)
- BS = 1.00 → perfectly wrong

Tracking: each closed trade logs a `CalibrationRecord` with `brier_contribution = (p - o)²`.
Running mean feeds into Kelly scalar reduction.

## Calibration Scalar (Brier → Kelly multiplier)

```text
α = 0.50 - (BS / 0.25) × 0.25
α = clamp(α, 0.25, 0.50)
```

| Brier Score    | α (Kelly multiplier) |
| -------------- | -------------------- |
| 0.00 (perfect) | 0.50 (half-Kelly)    |
| 0.125          | 0.375                |
| 0.25 (random)  | 0.25 (quarter-Kelly) |

## Mispricing Z-Score

```text
δ = (p_model - p_mkt) / σ
```

- δ > 1.5 → statistically significant edge
- δ < 1.0 → marginal signal (skip if edge is below 0.04)

## ARB Condition

```text
Σ (1 / odds_i) < 1  →  risk-free profit exists
```

When the sum of reciprocal odds across all outcomes is less than 1,
a pure arbitrage exists. Rare in efficient markets but appears during
illiquid hours or fast-moving news events.

## Confidence Minimum Gate

```python
MIN_CONFIDENCE = 0.30
```

Any signal with confidence < 0.30 is rejected before reaching risk sizing.
This is a hard floor — not adjustable via calibration scalar.

## Cost Per Signal

```text
XGBoost gate:  $0.00  (CPU-only inference, no API call)
Gemini 50t:    ~$0.000004
Haiku 100t:    ~$0.000080
Total (if XGBoost passes): ~$0.000084
```

XGBoost gate blocks low-probability signals before LLM voters are called,
saving ~$0.000084 per rejected signal.
