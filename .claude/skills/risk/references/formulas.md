# Risk Formulas Reference — Risk Skill

## EDGE DETECTION

### Expected Value

```
EV = p · b - (1 - p)
```

`p` = model probability, `b` = decimal_odds − 1

### Market Edge

```
edge = p_model - p_mkt
```

Trade only when `edge > 0.04`

### Bayes Update

```
P(H|E) = P(E|H) · P(H) / P(E)
```

Update prior with each news signal.

### Brier Score

```
BS = (1/n) · Σ (p_i - o_i)²
```

Lower = better calibrated model. Target: BS < 0.25

---

## POSITION SIZING

### Kelly Criterion

```
f* = (p · b - q) / b
```

`q = 1 - p`. Full Kelly = maximum fraction of bankroll to stake.

Equivalent form: `f* = W - (1-W)/R` where W = win rate, R = reward/risk ratio.

### Fractional Kelly

```
f = α · f*,    α ∈ [0.25, 0.50]
```

Use half-Kelly (α = 0.5) for well-calibrated models (BS < 0.10).
Use quarter-Kelly (α = 0.25) when model is poorly calibrated (BS ≥ 0.25).

Brier-derived α:
```
α = 0.50 - (BS / 0.25) × 0.25
α = clamp(α, 0.25, 0.50)
```

### Value at Risk 95%

```
VaR = µ - 1.645 · σ
```

`µ` = expected return, `σ` = daily return std-dev.
Max daily loss at 95% confidence. Gate: VaR must not exceed 1% of NAV.

### Max Drawdown

```
MDD = (Peak - Trough) / Peak
```

- Daily MDD ≥ 2% → immediate HALT (auto-reset next day)
- Cumulative MDD ≥ 8% → SOFT HALT (manual resume required)

---

## ARBITRAGE & PERFORMANCE

### ARB Condition

```
Σ (1 / odds_i) < 1  →  risk-free profit exists
```

Sum of reciprocal odds below 1 means the book is overround.

### Mispricing Score

```
δ = (p_model - p_mkt) / σ
```

Z-score of model vs market divergence. δ > 1.5 = statistically significant edge.

### Sharpe Ratio

```
SR = (E[R] - Rf) / σ(R)
```

Risk-adjusted return. Target SR > 2.0. Annualised (multiply by √252).

### Profit Factor

```
PF = gross_profit / gross_loss
```

Healthy bot maintains PF > 1.5.

---

## HARD CAPS (non-negotiable)

| Parameter | Value |
|-----------|-------|
| Max daily drawdown | 2% of SOD equity → HALT |
| Max cumulative MDD | 8% peak-to-trough → SOFT HALT |
| Max position pct | 10% of account equity |
| Max position USD | $50,000 notional |
| Max concurrent positions | 15 |
| Max VaR | 1% of NAV daily |
| Min signal confidence | 0.30 |
| Min edge | 0.04 |
