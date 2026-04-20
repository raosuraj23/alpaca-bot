# TA Formulas Reference — Scan Skill

## EMA (Exponential Moving Average)

```
EMA(t) = price(t) × k + EMA(t-1) × (1 - k)
k = 2 / (n + 1)    where n = period (e.g. 20)
```

Bootstrap: EMA(0) = SMA over first n bars.

## RSI (Relative Strength Index, 14-period)

```
RS  = avg_gain / avg_loss  (Wilder smoothing, 14-bar)
RSI = 100 - (100 / (1 + RS))
```

Wilder smoothing: first avg = simple mean; subsequent = (prev_avg × 13 + new_value) / 14

Zones:
- RSI > 70 → overbought (sell pressure)
- RSI < 30 → oversold (buy pressure)
- 45 < RSI < 65 → neutral-bullish momentum (+1.0 score bonus)

## Bollinger Bands (20-period, 2σ)

```
SMA   = mean(close, 20)
σ     = stdev(close, 20)
upper = SMA + 2σ
lower = SMA - 2σ
```

Band position: `pct = (price - lower) / (upper - lower)`
- pct < 0.25 → price near lower band → mean-reversion opportunity (+0.5)
- pct > 0.75 → price near upper band → overbought (-0.3)

## Volume Ratio

```
volume_ratio = current_volume / rolling_7day_avg_volume
```

- ratio > 1.5 → volume surge → strong signal confirmation (+0.5)
- ratio > 2.0 → VOLUME_SURGE anomaly → immediate SSE alert

## Composite TA Score Table

| Condition | Score |
|-----------|-------|
| price > EMA20 | +1.0 |
| price < EMA20 | −1.0 |
| 45 < RSI < 65 | +1.0 |
| RSI > 70 or < 30 | −0.5 |
| volume > 1.5× avg | +0.5 |
| price in lower 25% BB | +0.5 |
| price in upper 75% BB | −0.3 |

## Signal Thresholds

```
score ≥  1.0 → BUY
score ≤ -1.0 → SELL
otherwise   → NEUTRAL
```

## Anomaly Thresholds

```
PRICE_SPIKE:  |close / prev_close - 1| > 0.10   (10% single-bar move)
VOLUME_SURGE: volume > 2× rolling_7day_avg
```
