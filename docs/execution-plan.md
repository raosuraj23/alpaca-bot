# Multi-Agent Backend Execution Blueprint

Tracks the engineering phases required to transition the Zustand mock-simulation state into a
live, orchestrated Multi-Agent Trading System on Python FastAPI + Alpaca Markets API.

---

Here is the comprehensive, phase-wise `execution-plan.md` for our algorithmic trading terminal. As your Product Owner, I have structured this roadmap to aggressively eliminate our technical debt, resolve the critical performance bottlenecks (specifically the synchronous blocking and $O(N)$ operations), and transition this platform from a "retail script" into an **institutional-grade, multi-agent automated trading ecosystem**.

All engineers are expected to adhere strictly to this execution order.

---

# 📈 Alpaca-Bot Execution Plan

**Product Vision:** A lightning-fast, multi-agent algorithmic trading terminal. The backend must be fully asynchronous, strictly typed, and mathematically optimized ($O(1)$ operations in the hot path). The frontend must be a zero-lag telemetry dashboard reflecting real-time state.

## 🚀 Phase 1: Core Engine Stabilization & Performance Optimization
*Focus: Eliminating event-loop blocking, $O(N)$ bottlenecks, and data loss.*

- [x] **Audit Existing Strategies**
- [ ] **Async Hot-Path Migration:** Convert all strategy `analyze()` methods to `async def aanalyze()`. Ensure `master_engine.process_tick()` uses `asyncio.gather()` to fan out ticks to active bots concurrently without blocking the Python event loop.
- [ ] **O(1) Math Refactoring:** Replace all generator-based variance/standard deviation calculations (e.g., `StatArbStrategy`, `EquityPairsStrategy`, `ProtectivePutStrategy`) with Welford's Online Algorithm. No $O(N)$ deque iterations on every market tick.
- [ ] **RSI Memory Optimization:** Refactor `EquityRSIStrategy` and `CoveredCallStrategy` to calculate Wilder's Smoothing RSI in $O(1)$ time by tracking `prev_price`, `avg_gain`, and `avg_loss` rather than storing and iterating over arrays of historical prices.
- [ ] **Strategy Factory Pattern:** Remove `copy.deepcopy()` in `StrategyEngine.spawn_variant()`. Implement a clean factory instantiation pattern passing configuration via `**kwargs`.
- [ ] **Data Type Safety (The PnL Bug):** Refactor the SQLAlchemy Database Models to replace all `Float` types with `Numeric(precision, scale)` / Python `Decimal` to stop floating-point corruption in fill prices, slippage, and PnL.

## 🗄️ Phase 2: Database Architecture & True PnL Tracking
*Focus: Tracking the full Trade Lifecycle instead of isolated executions.*

- [ ] **Schema Migration (Alembic):** Generate and apply an Alembic migration to upgrade column types and apply proper `index=True` on `alpaca_order_id` for webhook lookups.
- [ ] **Implement `ClosedTrade` Ledger:** Build a PnL service that reconciles opening and closing executions (FIFO/LIFO). The DB must track full round-trips (`entry_time`, `exit_time`, `realized_pnl`, `duration`) so the Reflection Agent has context on *why* a trade won or lost.
- [ ] **Portfolio Time-Series Logging:** Create an asynchronous cron job (via `APScheduler` or `asyncio`) to snapshot the account equity and active drawdown into the `PortfolioSnapshot` table every 60 seconds.
- [ ] **State Restoration:** Ensure `master_engine` successfully queries the `BotState` table on startup to resume halted/active bots and dynamically re-instantiate them with overrides from the `BotAmend` table.

## 🧠 Phase 3: Agentic Orchestration & Dynamic Discovery
*Focus: Making the AI agents performant, state-aware, and autonomous.*

- [ ] **Scanner Agent Universe Fix:** Refactor `ScannerAgent._discover_symbols()` (Tier 1) to use Alpaca's REST Historical API instead of the real-time WebSocket buffer, fixing the data starvation bug.
- [ ] **Orchestrator Wiring:** Implement the `on_universe_update` callback. When the Scanner LLM updates the active universe, the Orchestrator must dynamically `ws.subscribe()` to the new tickers and spin up new strategy instances.
- [ ] **Async LLM Calls:** Refactor all LangChain calls (`ScannerAgent`, `ReflectionEngine`) from `model.invoke()` to `await model.ainvoke()` to stop Anthropic/Gemini network requests from stalling the trading terminal.
- [ ] **Batched Trade Reflection:** Update the `ReflectionEngine` to run a batch analysis on `ClosedTrade` records at the end of the day, suggesting parameter tweaks, rather than triggering LLM calls on every partial fill.
- [ ] **RAG Trade Memory (Optional/Late Phase 3):** Integrate PGVector or Chroma. Embed LLM insights. Query the vector DB prior to entries to prevent repeating historical mistakes in similar market regimes.

## 📈 Phase 4: Advanced Asset Classes & Risk Management
*Focus: Options integration, Implied Volatility, and the Kill Switch.*

- [ ] **Alpaca Options API Integration:** Upgrade the `ExecutionAgent` to consume signals from `CoveredCallStrategy` and `ProtectivePutStrategy`. Route orders to the `/v2/options/chain` endpoint.
- [ ] **Greeks & IV Filter:** Integrate real-time Implied Volatility (IV) and Delta/Theta checks before submitting option orders to prevent buying overpriced premium.
- [ ] **Multi-Leg Support:** Add execution handling for complex multi-leg combinations (straddles, strangles, spreads) ensuring atomic fills via the Alpaca Multi-leg protocol.
- [ ] **Global Risk Agent (Kill Switch):** Implement an independent watcher that monitors real-time `drawdown_pct`. If breached, immediately call `master_engine.halt_bot()` across all instances and liquidate open equity positions.

## 🖥️ Phase 5: Next.js UI/UX & Real-Time Telemetry
*Focus: Ensuring the frontend reflects institutional-grade speed.*

- [ ] **Lightweight Charts Optimization:** Refactor `TradingChart.tsx` to initialize `createChart` only *once* on mount. Use `candleRef.current.update()` to stream new WebSocket ticks into the chart, eliminating the $O(N)$ re-render freezing.
- [ ] **WebSocket Data Bindings:** Replace `setInterval(loadPerf, 60_000)` polling with Zustand WebSockets bindings. `ohlcvData`, `performance`, and `lastSignal` must update the UI in real-time.
- [ ] **Remove UI Heavy Computation:** Strip out `computeRsi()` and calendar PnL aggregation from the React thread. Consume pre-aggregated data strictly from the FastAPI backend.
- [ ] **Agent Logs Panel:** Build a streaming text panel beneath the "Bot Performance Matrix" to display real-time LangChain thought processes and Haiku verdicts as they arrive via Server-Sent Events (SSE). 
- [ ] **Environment Configuration:** Remove all hardcoded `http://localhost:8000` URLs. Implement strict `process.env.NEXT_PUBLIC_API_URL` handling.

## Phase Status (2026-04-15)

| Phase | Goal | Status | Completion |
|-------|------|--------|-----------|
| 1 | Market Data & Sockets | In progress | 75% |
| 1.5 | UI Data Pivot & Insights | Complete | 100% |
| 2 | Multi-Agent Network Core | In progress | 80% |
| 3 | Advanced Analytics (TradingView) | In progress | 60% |
| 4 | Production Hardening | Not started | 5% |

### Active Blockers

- `ALPACA_API_KEY_ID` / `ALPACA_API_SECRET_KEY` not set in `.env` → backend runs but all trading endpoints return 503
- `ANTHROPIC_API_KEY` not set → orchestrator chat returns offline warning
- VectorBT not in `backend/requirements.txt` → Phase 4 not startable
- Phase 3 SSE thought-stream generator not yet implemented (endpoint exists, no real emitter)

### What Already Exists (previously mis-tracked as TODO)

The following files are **fully implemented** and do NOT need to be created:

| File | Purpose |
|------|---------|
| `backend/agents/risk_agent.py` | RiskAgent with KillSwitch gate + Kelly fraction sizing |
| `backend/agents/execution_agent.py` | ExecutionAgent — Alpaca order submit + slippage recording |
| `backend/agents/graph.py` | LangGraph StateGraph: risk_agent → execution_agent pipeline |
| `backend/agents/orchestrator.py` | OrchestratorEngine with rolling 6-message conversation memory |
| `backend/db/models.py` | SQLAlchemy models: ExecutionRecord, SignalRecord, BotAmend |
| `backend/db/database.py` | Async SQLite session factory |
| `backend/strategy/engine.py` | StrategyEngine — 3-bot fleet (momentum-alpha, statarb-gamma, hft-sniper) |
| `backend/strategy/algorithms.py` | Strategy algorithm implementations |
| `backend/risk/kill_switch.py` | Global circuit breaker: 2% daily drawdown limit |
| `backend/risk/exposure.py` | VaR + Kelly position sizing |
| `backend/execution/router.py` | Order routing to Alpaca |

---

## Phase 1 — Foundational Market Data & Sockets

**Skill:** `realtime-websocket`

### Done

- FastAPI WebSocket `ws://localhost:8000/stream` broadcasting TICK/QUOTE payloads
- Zustand `useMockTradingStream.ts` bridge with `injectSocketData()` + `fetchAPIIntegrations()`
- REST endpoints: `/api/account`, `/api/positions`, `/api/orders`, `/api/seed`, `/api/bots`, `/api/risk/status`, `/api/ledger`, `/api/performance`, `/api/market/history`
- Lazy Alpaca client init — server starts safely without API keys
- Structured logging via Python `logging` module
- Signal pipeline: StrategyEngine → RiskAgent → ExecutionAgent → SSE events (fully wired)

### Remaining

1. **Configure API keys** — Copy `.env.example` to `.env`, fill in Alpaca paper trading keys
   - Verify `trading_client.get_account()` returns real equity value
   - Confirm WebSocket stream receives live BTC/USD ticks

2. **Fix asyncio thread safety** — `connected_clients` plain list not safe under concurrent connections
   - Add `_clients_lock = asyncio.Lock()` and wrap all list mutations + broadcast loops
   - File: `backend/main.py`

3. **Extend to equities** — Add `StockDataStream` subscription for AAPL, TSLA
   - Requires `ALPACA_BASE_URL=https://data.alpaca.markets` for market data feed
   - Skill: `realtime-websocket`

4. **Daily bar feed** — Subscribe to daily bars for accurate `change24h`
   - Currently approximated in `injectSocketData()` (MOCK comment)
   - Replace with Alpaca `CryptoBarsRequest` for historical day bar

5. **WebSocket reconnection** — Add exponential backoff in `useMockTradingStream.ts`
   - Currently closes silently on disconnect
   - Use `setTimeout` with 2s → 4s → 8s → 16s → 32s retry, max 5 attempts

---

## Phase 2 — Multi-Agent Network Core

**Skills:** `trading-strategy-agents`, `risk-management`, `claude-api`

### Done

- `OrchestratorEngine` with rolling 6-message in-memory conversation history
- `SwarmFactory` with model tiering: Claude Opus (smart) / Sonnet (standard) / Haiku (fast) / Gemini fallbacks
- `RiskAgent` — kill switch + Kelly fraction position sizing
- `ExecutionAgent` — Alpaca order submission + async slippage recording to SQLite
- `LangGraph` signal pipeline graph: risk_node → execution_node with conditional routing
- `/api/agents/chat` endpoint connected to `OrchestratorChat.tsx`
- SQLite models: ExecutionRecord, SignalRecord, BotAmend
- All 9 agent persona files enriched in `.claude/agents/`

### Remaining

#### 2a. Configure API Keys (prerequisite)

Fill `.env` with `ANTHROPIC_API_KEY`. Test the orchestrator chat:

```bash
curl -X POST http://localhost:8000/api/agents/chat \
  -H "Content-Type: application/json" \
  -d '{"message": "What strategies are currently running?"}'
```

Expected: JSON response from claude-sonnet-4-6 (not the offline warning).

#### 2b. Add Prompt Caching to Orchestrator

File: `backend/agents/orchestrator.py`

The system prompt (~2k tokens) is sent uncached on every invocation. Wrap with Anthropic's ephemeral cache:

```python
self.system_prompt = SystemMessage(
    content=self.system_prompt.content,
    additional_kwargs={"cache_control": {"type": "ephemeral"}}
)
```

Skill: `claude-api`

#### 2c. Implement TRIGGER_BACKTEST Handler

File: `backend/agents/orchestrator.py` — `_dispatch_command()`

Currently logs "Phase 4 handler not yet implemented". Once Phase 4 is complete, wire to `POST /api/backtest`.

---

## Phase 3 — Bot Brain Reflection Generation

**Skills:** `ai-insights`, `realtime-websocket`

### Done

- SSE endpoint `/api/reflections/stream` exists in `main.py`
- SSE endpoint `/api/logs/stream` exists in `main.py`
- `BotAmend` SQLAlchemy model exists in `db/models.py`
- Frontend `bot-reflections.tsx` connects via `EventSource`
- `_push_reflection()` helper exists in `main.py`

### Remaining

#### 3a. Implement SSE Thought Stream Generator

File: `backend/main.py`

The `/api/reflections/stream` endpoint currently uses a basic queue drain loop. Implement a real AI insights generator:

```python
async def _ai_reflection_generator():
    """Generates periodic AI reflections from recent signal + execution data."""
    while True:
        # 1. Query last N ExecutionRecords from DB
        # 2. Build summary prompt for the orchestrator
        # 3. Invoke fast-tier LLM for reflection
        # 4. Persist to BotAmend table
        # 5. Push to SSE queue
        await asyncio.sleep(30)  # reflection cadence
```

#### 3b. Replace Frontend Mock Data

File: `src/components/dashboard/bot-reflections.tsx`

Replace hardcoded `thoughtStream` array with live `EventSource` on `/api/reflections/stream`.

---

## Phase 4 — Backtesting Engine Pipeline

**Skills:** `trading-strategy-agents`, `charting-nivo`

### Remaining

#### 4a. Add VectorBT to requirements

```
# backend/requirements.txt additions:
vectorbt>=0.26.0
```

#### 4b. Backtest Runner

File: `backend/backtest/runner.py` (create)

```python
import vectorbt as vbt

def run_backtest(params: BacktestParams) -> BacktestResult:
    data = vbt.YFData.download(params.symbol, start=params.start_date, end=params.end_date)
    # Apply strategy signal generation
    # Model slippage: 0.05%, fees: 0% (Alpaca paper)
    # Strictly separate in-sample (70%) / out-of-sample (30%)
    portfolio = vbt.Portfolio.from_signals(close, entries, exits, ...)
    return BacktestResult(
        net_profit=float(portfolio.total_profit()),
        max_drawdown=float(portfolio.max_drawdown()),
        sharpe_ratio=float(portfolio.sharpe_ratio()),
        equity_curve=portfolio.value().to_list()
    )
```

#### 4c. Backend Endpoint

```
POST /api/backtest   { symbol, strategy, start_date, end_date }
```

#### 4d. Wire BacktestRunner.tsx to Real Data

- Replace SVG mock chart with Nivo `ResponsiveLine` bound to `BacktestResult.equity_curve`
- Connect Run button to `POST /api/backtest`
- Stream progress via SSE, update progress bar in real time
- Skill: `charting-nivo`

---

---

## Phase 1.5 — UI Data Pivot & Insights (COMPLETE — 2026-04-15)

All items shipped:

| Item | File | Status |
|------|------|--------|
| AI Insights → News feed + Haiku commentary (30-min cache) | `ai-insights.tsx` | Done |
| Ledger realized PnL via FIFO queue matching per bot+symbol | `trade-ledger.tsx` | Done |
| Drill-down PnL calendar (Day / Week / Month / Year views) | `performance-metrics.tsx` | Done |
| Bot Performance Matrix (replaces slippage histogram) | `performance-metrics.tsx` | Done |
| Account balance KPIs: Equity, Buying Power, Cash, Long Mkt Val | `trade-ledger.tsx` | Done |
| `AsyncSessionLocal` import bug fix (500 on realized-pnl endpoint) | `backend/main.py` | Done |
| Orchestrator fixes: QUERY_POSITIONS, HALT_BOT all, PLACE_ORDER qty% | `orchestrator.py` | Done |
| All timestamps converted to user local timezone in frontend | All components | Done |
| `lastSignal` Zustand store field wired to WebSocket SIGNAL events | `useTradingStream.ts` | Done |

---

## Phase 3 — Advanced Analytics (TradingView)

**Skills:** `charting-nivo` (remove), `frontend-design`

### Done

- `lightweight-charts` v5 installed
- `PnLCurve` (Nivo `ResponsiveLine`) replaced with `TradingChart` component
- Single-chart split-pane: candlestick + EMA (pane 0), volume histogram + RSI (pane 1)
- X-axis automatically synchronized (same chart instance)
- Signal annotations via `createSeriesMarkers` — BUY↑ / SELL↓ markers on candle
- Performance Tear Sheet sidebar: Net PnL, Max Drawdown, Sharpe, Win Rate, Active Bots
- `lastSignal` store field feeds real-time annotations from WebSocket SIGNAL events

### Remaining

#### 3a. Remove Nivo dependencies

Once confirmed no other component uses Nivo:

```bash
npm uninstall @nivo/line @nivo/bar @nivo/core
```

Check first: `grep -r "from '@nivo" src/`

#### 3b. Live OHLCV feed (replaces synthetic candles)

Current `TradingChart` synthesizes candles from equity snapshots (`[timestamp_ms, equity_value][]`). Replace with a proper OHLCV backend endpoint:

```
GET /api/ohlcv?symbol=BTC/USD&period=1D
→ { candles: [{time, open, high, low, close, volume}] }
```

Backend: use `CryptoBarsRequest` from Alpaca `historical_data_client`. Map each bar to lightweight-charts `CandlestickData` format (`time` in Unix seconds).

#### 3c. Sharpe / Sortino from backend

Add to `/api/performance` response:
```python
"sharpe":  computed_sharpe,   # annualised
"sortino": computed_sortino,  # annualised, downside deviation only
```

Tear Sheet sidebar reads these directly instead of computing client-side.

---

## Phase 4 — Production Hardening

**Skills:** `trading-strategy-agents`

### Remaining

#### 4a. Add VectorBT to requirements

```
# backend/requirements.txt additions:
vectorbt>=0.26.0
```

#### 4b. Backtest Runner

File: `backend/backtest/runner.py` (create)

```python
import vectorbt as vbt

def run_backtest(params: BacktestParams) -> BacktestResult:
    data = vbt.YFData.download(params.symbol, start=params.start_date, end=params.end_date)
    # Apply strategy signal generation
    # Model slippage: 0.05%, fees: 0% (Alpaca paper)
    # Strictly separate in-sample (70%) / out-of-sample (30%)
    portfolio = vbt.Portfolio.from_signals(close, entries, exits, ...)
    return BacktestResult(
        net_profit=float(portfolio.total_profit()),
        max_drawdown=float(portfolio.max_drawdown()),
        sharpe_ratio=float(portfolio.sharpe_ratio()),
        equity_curve=portfolio.value().to_list()
    )
```

#### 4d. Backend Endpoint

```
POST /api/backtest   { symbol, strategy, start_date, end_date }
```

#### 4e. Wire BacktestRunner.tsx to Real Data

- Replace SVG mock chart with `lightweight-charts` `LineSeries` bound to `BacktestResult.equity_curve`
- Connect Run button to `POST /api/backtest`
- Stream progress via SSE, update progress bar in real time

---

## Immediate Action Items (Do These First)

1. `cp .env.example .env` and fill in Alpaca paper trading keys + ANTHROPIC_API_KEY
2. `cd backend && uvicorn main:app --reload` — verify `/api/account` returns real data
3. Test realized PnL endpoint: `curl http://localhost:8000/api/analytics/realized-pnl` → should return 200
4. Test orchestrator: `curl -X POST http://localhost:8000/api/agents/chat -H "Content-Type: application/json" -d '{"message": "show positions"}'`
5. Open Analysis tab → confirm split-pane chart renders with candlestick + volume/RSI panes
6. Run `npx playwright test` — all E2E tests must pass
