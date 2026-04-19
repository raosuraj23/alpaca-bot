---
name: compound
description: Compound learning — post-mortem analysis of losing trades writes lessons to knowledge base, feeds back into scan and research. Use when "compound", "post-mortem", "learn", "failure", "knowledge base", "lessons".
metadata:
  version: 2.0.0
  pattern: iterative
  tags: [post-mortem, knowledge-base, learning, compound, reflection, calibration, brier, nightly]
---

# Compound Skill

## CRITICAL: Before each scan/research cycle, load failure_log.jsonl (last 20 entries) to prevent repeating known mistakes.

## Triggers

- **Every SELL fill** — full trade record logged to `ReflectionLog` (entry/exit price, hold duration, market conditions)
- **Every SELL fill with `realized_pnl < 0`** — post-mortem agent invoked, KB entry appended to `failure_log.jsonl`
- **23:55 UTC nightly** — consolidation job aggregates day's metrics to `metrics_log.jsonl`

Code paths:
- `backend/agents/reflection_engine.py → learn_from_execution()` (all fills)
- `backend/agents/reflection_engine.py → _invoke_post_mortem()` (losses only)
- `backend/agents/nightly_consolidation.py → run_daily_snapshot()` (EOD)

---

## Full Trade Log Schema (ALL fills)

```json
{
  "strategy":          "momentum-alpha",
  "symbol":            "BTC/USD",
  "action":            "SELL",
  "signal_confidence": 0.75,
  "realized_pnl":      -50.0,
  "slippage_pct":      0.002,
  "entry_price":       55000,
  "exit_price":        50000,
  "hold_duration_min": 45,
  "market_conditions": {"rsi": 72, "ema_spread": 0.03, "volume_ratio": 1.2},
  "news_items":        ["headline 1", "headline 2"],
  "failure_class":     "BAD_PREDICTION"
}
```

---

## Post-Mortem Agent (losses only)

Called by `_invoke_post_mortem()` — Haiku fast-tier, 200 tokens, ~$0.000160/call.

### Classification Rules

| Class | Condition |
|-------|-----------|
| BAD_PREDICTION | Model directionally wrong despite confidence > 0.70 |
| TIMING | Correct direction but entry/exit timing degraded P&L |
| EXECUTION | Slippage > 2% of signal price was the primary drag |
| MARKET_SHOCK | Exogenous event (news, macro) invalidated signal |

### Output Schema

```json
{
  "failure_class":   "BAD_PREDICTION | TIMING | EXECUTION | MARKET_SHOCK",
  "root_cause":      "one sentence describing WHY the trade failed",
  "adjustment":      "one specific parameter or threshold to change",
  "knowledge_entry": "one-line fact under 100 chars for the knowledge base"
}
```

---

## Knowledge Base

**File:** `backend/knowledge/failure_log.jsonl`
Format: append-only JSONL — one entry per losing trade.

```json
{"timestamp": "...", "strategy": "momentum-alpha", "symbol": "BTC/USD",
 "failure_class": "BAD_PREDICTION", "entry_price": 55000, "exit_price": 50000,
 "predicted_prob": 0.80, "actual_outcome": 0, "hold_duration_min": 45,
 "brier_contribution": 0.04,
 "knowledge_entry": "BTC/USD: confidence >0.80 fails after FOMC announcements",
 "adjustment": "raise momentum confidence threshold from 0.70 to 0.80 for BTC/USD"}
```

**Reading:** `_load_knowledge_context(n=20)` in `backend/agents/scanner_agent.py` —
injects last N entries as bullet list into Gemini discovery + research prompts.

---

## Nightly Consolidation

Runs at 23:55 UTC via `NightlyConsolidation.run_daily_snapshot()`.

**File:** `backend/knowledge/metrics_log.jsonl`

```json
{"date": "2026-04-18", "win_rate": 0.64, "sharpe": 2.1, "max_drawdown_pct": 1.2,
 "profit_factor": 1.87, "brier_score": 0.18, "total_trades": 12, "total_pnl": 145.20,
 "targets_met": {"win_rate": true, "sharpe": true, "max_drawdown": true,
                 "profit_factor": true, "brier_score": true}}
```

---

## Performance Metrics Tracked

| Metric | Formula | Target | Source |
|--------|---------|--------|--------|
| Win Rate | wins / total_trades | ≥ 60% | `ClosedTrade.win` |
| Sharpe Ratio | (E[R] - Rf) / σ(R) | ≥ 2.0 | `PortfolioSnapshot` |
| Max Drawdown | (Peak - Trough) / Peak | < 8% (halt) | `KillSwitch._cumulative_mdd_pct` |
| Profit Factor | gross_profit / gross_loss | ≥ 1.5 | `ClosedTrade.net_pnl` |
| Brier Score | (1/n) · Σ(p_i - o_i)² | < 0.25 | `CalibrationRecord` |

---

## Feedback Loop

```
SELL fill
    ↓
learn_from_execution() [ALL fills — full log with hold_duration + market_conditions]
    ↓
_invoke_post_mortem()  [losses only — Haiku 200t]
    ↓
failure_log.jsonl      [knowledge base append]
    ↓
23:55 UTC nightly_consolidation()
    ↓
metrics_log.jsonl      [daily performance snapshot]
    ↓
next scan/research:    _load_knowledge_context() → Gemini prompt injection
```

---

## References

- `scripts/post_mortem.py` — full trade record schema + failure classification
- `scripts/nightly_consolidation.py` — metrics aggregation + targets_met
- `references/metrics.md` — all 5 metrics formulas + targets
- `backend/agents/reflection_engine.py` — full implementation
- `backend/agents/nightly_consolidation.py` — backend EOD agent
- `backend/risk/calibration.py` — Brier score + Kelly scalar
- `backend/knowledge/failure_log.jsonl` — failure knowledge base
- `backend/knowledge/metrics_log.jsonl` — nightly performance snapshots
