---
name: scan
description: TA screener — score symbols, detect anomalies, select active watchlist. Use when "scan", "watchlist", "discovery", "anomaly", "universe".
metadata:
  version: 1.0.0
  pattern: context-aware
  tags: [scanner, ta, anomaly, watchlist, discovery, universe]
---

# Scan Skill

## Triggers

- **TIER 1 (Discovery):** every 30 minutes — score full universe, Gemini selects top `MAX_ACTIVE_SYMBOLS` (8)
- **TIER 2 (TA Screen):** every 5 minutes — score active + position symbols, Haiku writes verdicts
- **Breaking anomaly:** immediate SSE push on PRICE_SPIKE or VOLUME_SURGE

Code path: `backend/agents/scanner_agent.py → _gemini_discovery()`, `_haiku_rank()`

---

## TA Composite Score (`_score_symbol`)

| Condition | Score |
|-----------|-------|
| price > EMA20 | +1.0 |
| price < EMA20 | −1.0 |
| 45 < RSI(14) < 65 | +1.0 |
| RSI > 70 or < 30 | −0.5 |
| volume > 1.5× 7-day avg | +0.5 |
| price in lower 25% of Bollinger band | +0.5 |
| price in upper 75% of Bollinger band | −0.3 |

**Signal thresholds:** BUY if score > 1.0 | SELL if score < −1.0 | NEUTRAL otherwise

---

## Anomaly Detection

- **PRICE_SPIKE:** single-bar close move > 10%
- **VOLUME_SURGE:** current volume > 2× 7-day rolling average

Both anomalies emit to SSE and are logged. They flag symbols for elevated research attention but do not directly trigger orders.

---

## Universe Rules

- Seeds: 12 crypto + 10 equity symbols (bootstrap only — never hardcode new lists)
- Grows dynamically via `expand_universe()` when ResearchAgent recommends new focus symbols
- Position symbols always included in TIER 2 scan regardless of universe membership

---

## Knowledge Context Injection

Before every TIER 1 discovery call, load last 20 entries from `backend/knowledge/failure_log.jsonl` via `_load_knowledge_context(20)` and append to the `HumanMessage` content. Prevents the scanner from re-elevating symbols with known failure patterns.

```
Past failure knowledge (apply to avoid repeat mistakes):
[BAD_PREDICTION] BTC/USD: confidence >0.80 signals fail after FOMC announcements
[TIMING] ETH/USD: EMA crossover during low-volume weekends produces false positives
```

---

## Output Contract

Each result persisted to `WatchlistItem` table and pushed to SSE stream:
```json
{"symbol": "BTC/USD", "score": 1.5, "signal": "BUY", "verdict": "Strong EMA trend with volume confirmation", "price": 65000, "rsi": 58, "timestamp": "..."}
```

---

## References

- `backend/agents/scanner_agent.py` — full implementation
- `backend/knowledge/failure_log.jsonl` — failure knowledge base (read-only for this skill)
- `docs/DESIGN.md` — SSE event shapes
