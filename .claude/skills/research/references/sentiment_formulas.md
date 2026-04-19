# Sentiment & Edge Formulas Reference — Research Skill

## Expected Value (EV)

```
EV = p · b - (1 - p)
```

- `p` = model probability of the event occurring
- `b` = decimal_odds − 1 (net profit per unit staked)
- EV > 0 → positive expectation; EV < 0 → negative expectation

Example: p=0.72, odds=1.538 → b=0.538 → EV = 0.72×0.538 − 0.28 = 0.107

## Market Edge

```
edge = p_model - p_mkt
```

- `p_model` = LLM/XGBoost probability estimate
- `p_mkt`   = market-implied probability (1 / decimal_odds)
- **Minimum viable edge: 0.04** — trades below this are blocked

## Bayes Update

```
P(H|E) = P(E|H) · P(H) / P(E)
```

Update the model's prior `P(H)` with each new news signal `E`.

- `P(E|H)` = likelihood of observing this news given hypothesis H is true
- `P(E)`   = marginal probability of observing the news signal
- Use iteratively: each signal narrows uncertainty around the true probability

## Brier Score (Calibration Accuracy)

```
BS = (1/n) · Σ (p_i - o_i)²
```

- `p_i` = model probability forecast for trade i
- `o_i` = actual outcome (1 = profitable, 0 = loss)
- Range: 0.0 (perfect) to 1.0 (perfectly wrong)
- Target: BS < 0.25; random model = 0.25

## Mispricing Score (Z-score)

```
δ = (p_model - p_mkt) / σ
```

- `σ` = volatility of the price signal
- Z-score interpretation: δ > 1.5 → statistically significant mispricing

## Edge Minimum Gate

```python
MIN_EDGE = 0.04   # 4 percentage points

if edge <= MIN_EDGE:
    reject("Edge too thin — do not trade")
```

## Research Cycle

1. Fetch news (Alpaca + 3 RSS feeds, max 40 items)
2. Build TA snapshot for candidate symbols
3. Gemini (1500t) produces ResearchBrief with `model_prob` per symbol
4. Compute edge = model_prob − market_implied_prob for each
5. Forward symbols with edge > 0.04 to scanner for TIER 1 elevation
6. Breaking news fast-path: Haiku (250t) if confidence > 0.75