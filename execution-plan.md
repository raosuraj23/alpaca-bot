# Multi-Agent Backend Execution Blueprint

Tracks the engineering phases required to transition the Zustand mock-simulation state into a
live, orchestrated Multi-Agent Trading System on Python FastAPI + Alpaca Markets API.

---

## Phase Status (2026-04-14)

| Phase | Goal | Status | Completion |
|-------|------|--------|-----------|
| 1 | Market Data & Sockets | In progress | 70% |
| 2 | Multi-Agent Network Core | In progress | 75% |
| 3 | Bot Brain Reflection | In progress | 15% |
| 4 | Backtesting Engine | Not started | 5% |

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

## Immediate Action Items (Do These First)

1. `cp .env.example .env` and fill in Alpaca paper trading keys + ANTHROPIC_API_KEY
2. `cd backend && uvicorn main:app --reload` — verify `/api/account` returns real data
3. Test orchestrator: `curl -X POST http://localhost:8000/api/agents/chat -H "Content-Type: application/json" -d '{"message": "What strategies are currently running?"}'`
4. Run `npx playwright test` — all E2E tests must pass
