# memory-preferences.md — Context Retention Instructions
# What Claude must track and restore across sessions.

## Purpose

This file tells Claude what state to reconstruct at the start of every session.
Before writing any code or analysis, Claude must ask: "What do I already know?"
and consult this file to avoid re-discovering API schemas, re-debugging known
issues, or re-running settled architectural decisions.

---

## 1. API Schema Discoveries

Record findings here as they are confirmed through live testing or official docs.
Do not rely on training knowledge alone — Alpaca's API changes.

### Alpaca REST API (confirmed fields)

GET /v2/account            → AccountModel (equity, buying_power, pattern_day_trader)
GET /v2/positions          → List[PositionModel] (symbol, qty, avg_entry_price, unrealized_pl)
POST /v2/orders            → OrderResult (id, status, filled_qty, filled_avg_price)
GET /v2/stocks/{symbol}/bars → BarModel (t, o, h, l, c, v, vw, n)

### Alpaca WebSocket (confirmed stream topics)
trades.{symbol}            → real-time trade ticks
quotes.{symbol}            → bid/ask quotes
bars.{symbol}              → per-minute OHLCV

### Anthropic API (confirmed behavior)
Input token savings: aggregated indicator summary saves ~95% tokens vs raw bars.
claude-haiku:   <1s latency, sufficient for sentiment binary classification.
claude-sonnet:  ~3-5s latency, required for strategy code generation.
Structured output: use response_format + Pydantic model validation.

---

## 2. Ongoing Bugs & Known Issues

Track active bugs here. Close them with a date and resolution.

| ID   | Module          | Description                              | Status   | Resolution |
|------|-----------------|------------------------------------------|----------|------------|
| B001 | execution/retry | Alpaca 429 not caught as rate-limit exc  | OPEN     | —          |
| B002 | ingestion/feed  | WebSocket drops on market close (4pm ET) | OPEN     | —          |

Add new entries as discovered. Never silently work around a bug without logging it.

---

## 3. Strategy Backtest Results Log

Every backtest run must be recorded here before a strategy is considered for
promotion to paper trading.

| Strategy         | Symbol  | Period          | Sharpe | Max DD | Calmar | Win% | Status        |
|------------------|---------|-----------------|--------|--------|--------|------|---------------|
| MomentumEquity   | SPY     | 2020-01–2022-12 | 1.42   | -14.2% | 0.98   | 54%  | Paper (active)|
| MeanReversionEQ  | QQQ     | 2021-01–2023-06 | 0.87   | -19.8% | 0.44   | 49%  | Rejected      |

Note: "Rejected" strategies must have a documented reason (e.g., "max DD exceeds
15% threshold in rules/security-and-risk.md").

---

## 4. Architectural Decisions Log (ADL)

Record major design decisions that must not be re-litigated without cause.

| Date       | Decision                                              | Rationale                                          |
|------------|-------------------------------------------------------|----------------------------------------------------|
| [DATE]     | Python over TypeScript                                | Quant ecosystem, alpaca-py, vectorbt               |
| [DATE]     | Pydantic v2 over dataclasses                          | Validators, JSON schema, LLM output parsing        |
| [DATE]     | Streamlit for dashboard (not FastAPI frontend)        | Speed to value; not a customer-facing product      |
| [DATE]     | SQLite locally, PostgreSQL in cloud (SQLAlchemy 2.0)  | Zero-migration-cost env var swap                   |

---

## 5. Session Restore Protocol

At the start of every session, Claude should:
1. Read this file.
2. Ask if any bugs in section 2 have been resolved since last session.
3. Confirm which strategy is currently active in paper trading (section 3).
4. Check if any new API schema behaviors have been observed (section 1).
5. Proceed with the user's current task using this context.

Claude must not re-propose rejected strategies or re-debate closed ADL entries
unless the user explicitly asks to revisit them.

---

## 6. Phase Completion Status Log

Record every phase (or sub-phase) here upon successful completion. Include the date,
what was shipped, and any follow-on items discovered during implementation.

| Date       | Phase  | Items Completed                                        | Follow-on / Notes                          |
|------------|--------|--------------------------------------------------------|--------------------------------------------|
| 2026-04-17 | Phase 1 · O(1) Math | Welford's sliding-window variance in StatArbStrategy, EquityPairsStrategy, ProtectivePutStrategy; O(1) RSI in EquityRSIStrategy + CoveredCallStrategy | All strategy state now O(1) per tick |
| 2026-04-17 | Phase 1 · Factory Pattern | Removed copy.deepcopy in spawn_variant; factory via type(source)(**kwargs) | None |
| 2026-04-17 | Phase 1+2 · DB Schema | Float→Numeric(18,8) on all price/qty/pnl cols; added ClosedTrade and PortfolioSnapshot models; composite index on (bot_id, symbol) | Alembic migration not yet generated — SQLite auto-creates on startup |
| 2026-04-17 | Phase 2 · Async LLM | orchestrator.process_chat + process_signal → async/ainvoke; reflection_engine.learn_from_execution → async/ainvoke | None |
| 2026-04-17 | Phase 2 · Snapshot + FIFO | _portfolio_snapshot_loop (60s cron); _write_closed_trade FIFO reconciliation on SELL fills; BotAmend param restore on startup | _entry_prices/_entry_times dicts in main.py memory; not persisted across restart |
| 2026-04-17 | Phase 3 · OHLCV | /api/ohlcv extended to support equity symbols via StockHistoricalDataClient + StockBarsRequest | None |
| 2026-04-17 | Phase 3 · Nivo removal | Confirmed no Nivo imports; lightweight-charts used instead | None |
| 2026-04-17 | Phase 4 · Backtest + URL cleanup | backend/backtest/runner.py (VectorBT); POST /api/backtest with SSE progress; BacktestRunner.tsx wired to real endpoint; all hardcoded localhost URLs → API_BASE/WS_BASE env constants | 50/50 Playwright tests passing |
| 2026-04-18 | Phase 3+ · Per-Symbol Strategy Assignment | New `SymbolStrategyAssignment` DB table; 4 new algorithm classes (EquityBreakout, VWAPReversion, NewsMomentum, CryptoRangeScalp); StrategyEngine quarantine + per-symbol routing + factory; PortfolioDirector new commands (ASSIGN_EXISTING_STRATEGY, CREATE_NEW_STRATEGY_INSTANCE, UNASSIGN_STRATEGY) + research-edge context; scanner quarantine trigger; startup restore; GET /api/symbol-strategies + GET /api/algorithms | Scanner-discovered symbols are quarantined until Director assigns strategy. Seed symbols use backward-compat asset-class routing. Director now has 12 algorithm templates to choose from. |

**How to update this table:**

After finishing a phase task, append a row with:

- `Date` — ISO date (YYYY-MM-DD)
- `Phase` — e.g. "Phase 1 · O(1) Math", "Phase 3 · SSE Reflections"
- `Items Completed` — one-line summary of what was shipped
- `Follow-on / Notes` — any new bugs found, decisions made, or deferred items

Claude must update this table after every successfully completed implementation
before reporting the task as done to the user.
