# Performance Metrics Reference — Compound Skill

## The 5 Tracked Metrics

### 1. Win Rate

```
Win Rate = wins / total_trades
```

**Target:** ≥ 60% for a sustainable edge

A win rate below 50% means the strategy loses more often than it wins.
Below 60%, you need a very high reward/risk ratio to be profitable long-term.
The compound skill tracks this over rolling windows (daily, 7-day, 30-day).

Source: `ClosedTrade.win` field, queried nightly.

---

### 2. Sharpe Ratio

```
SR = (E[R] - Rf) / σ(R)
```

**Target:** > 2.0 (risk-adjusted return)

- `E[R]` = mean daily return
- `Rf`   = risk-free rate (approximated as 0 for intraday)
- `σ(R)` = standard deviation of daily returns
- Annualise: multiply by √252

| Sharpe | Interpretation |
|--------|---------------|
| < 0    | Losing money  |
| 0–1    | Acceptable    |
| 1–2    | Good          |
| > 2    | Excellent     |

Source: `PortfolioSnapshot.total_equity` time series, computed nightly.

---

### 3. Max Drawdown (MDD)

```
MDD = (Peak - Trough) / Peak × 100%
```

**Block new trades if MDD > 8%** (cumulative, all-time peak-to-trough)

Two thresholds enforced:
- Daily MDD ≥ 2%   → immediate automatic HALT (resets next day)
- Cumulative MDD ≥ 8% → soft halt (manual resume required)

Source: `kill_switch.evaluate_cumulative_drawdown()` on each trade.

---

### 4. Profit Factor

```
PF = gross_profit / gross_loss
```

**Target:** > 1.5 (healthy bot)

| Profit Factor | Interpretation |
|--------------|----------------|
| < 1.0        | Losing money   |
| 1.0–1.5      | Marginal       |
| 1.5–2.0      | Healthy        |
| > 2.0        | Strong edge    |

Source: `ClosedTrade.net_pnl`, aggregated nightly.

---

### 5. Brier Score

```
BS = (1/n) · Σ (p_i - o_i)²
```

**Target:** < 0.25 (lower = better calibrated)

- `p_i` = model confidence / probability at signal time
- `o_i` = actual outcome (1 = profitable, 0 = loss)

| Brier Score | Interpretation |
|-------------|----------------|
| 0.00        | Perfect calibration |
| < 0.20      | Well calibrated     |
| 0.20–0.25   | Acceptable          |
| 0.25        | Random (coin flip)  |
| > 0.25      | Overconfident       |

Feeds Kelly scalar: high BS → reduced α → smaller positions.
Source: `CalibrationRecord.brier_contribution`, mean aggregated nightly.

---

## Nightly Consolidation

Runs at 23:55 UTC. Writes to `backend/knowledge/metrics_log.jsonl`:

```json
{
  "date": "2026-04-18",
  "win_rate": 0.64,
  "sharpe": 2.1,
  "max_drawdown_pct": 1.2,
  "profit_factor": 1.87,
  "brier_score": 0.18,
  "total_trades": 12,
  "total_pnl": 145.20,
  "targets_met": {
    "win_rate": true,
    "sharpe": true,
    "max_drawdown": true,
    "profit_factor": true,
    "brier_score": true
  }
}
```

Future scan and research cycles load the last 5 nightly snapshots to detect
trend reversals (e.g., deteriorating win rate may prompt strategy parameter review).

## Feedback Loop

```
SELL fill
    ↓
learn_from_execution() [ALL fills — full log]
    ↓
_invoke_post_mortem() [losses only — Haiku 200t]
    ↓
failure_log.jsonl append
    ↓
23:55 UTC: nightly_consolidation()
    ↓
metrics_log.jsonl append
    ↓
next scan/research: load KB context
```
