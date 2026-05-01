# Alpaca Quant Terminal - Execution Plan

## Phase 1: Core Engine Stabilization & Data Precision
- [x] Alembic migration: convert all price, quantity, slippage, PnL columns Float → Numeric(20, 9).
- [x] ExecutionAgent pre-flight layer: round qty/price to Alpaca tick & lot rules; enforce fractional = Day/Market, notional >= 1.00.
- [x] Convert all strategy `.analyze()` → `async def aanalyze()`; LLM calls → `await model.ainvoke()`.
- [x] O(1) math: Welford variance in StatArb/EquityPairs/ProtectivePut; O(1) RSI in EquityRSI/CoveredCall.

## Phase 2: Database Architecture & True PnL Tracking
- [x] Implement `ClosedTrade` ledger with FIFO reconciliation of opening/closing executions.
- [x] Portfolio time-series cron: snapshot account equity + drawdown into `PortfolioSnapshot` every 60 seconds.
- [x] State restoration: `master_engine` queries `BotState` on startup; restores halted/active bots with `BotAmend` overrides.

## Phase 3: Agentic Framework Overhaul (5-Step Pipeline)
- [x] Step 1 · Scan & Discovery: ScannerAgent uses Alpaca REST Historical API for universe scan; `on_universe_update` fires portfolio_director.
- [x] Step 2 · Research: multi-source news/sentiment → `ResearchBrief` with narrative vs. price comparison.
- [x] Step 3 · Predict: XGBoost + dialectical debate ensemble (DebateResult → AnalystSynthesis → TraderDecision); Edge gate >= 6% enforced.
- [x] Step 4 · Risk: Fractional Kelly sizing, VaR gate (1% daily 95% CI), drawdown kill-switch, PDT limit veto.
- [x] Step 5 · Compound (RAG Trade Memory): ChromaDB vector store — embed every closed round-trip trade; semantic search retrieves past failures before new entries.

## Phase 4: UI/UX Tab Streamlining
- [x] lightweight-charts installed (v5.1.0); used for equity curve + drawdown histogram.
- [x] Brain Tab SSE: `/api/reflections/stream` + `/api/logs/stream` streaming pipeline events to frontend.
- [x] Per-position close button + "Flatten All" panic button (liquidate all + halt all bots, no DB wipe).
- [ ] Hybrid charting (Analysis tab): restrict lightweight-charts to candlestick/execution marker pane; Nivo/Recharts SVG for PnL Calendar & LLM Cost graphs.
- [ ] Strict tabular-nums: enforce `font-mono tabular-nums` globally across Tear Sheet and Ledger tabs.

## Phase 5: Zero-Cost 24/7 Production Deployment
- [x] `docker-compose.yml` bundling FastAPI, Next.js, and PostgreSQL; backend and frontend Dockerfiles.
- [ ] Deploy to AWS EC2 `t3.micro` (12-month free tier) or GCP `e2-micro` (Always Free).
- [ ] PM2/Watchdog: auto-reconnect WebSocket on transient network failure; all secrets via AWS Secrets Manager or `.env`.
