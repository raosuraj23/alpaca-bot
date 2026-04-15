# Alpaca Quant Bot — Implementation Plan

> Last updated: 2026-04-15 | Branch: `second`

---

## Completed This Session

| Area | Status | What Was Done |
|------|--------|--------------|
| 0a — Naked SELL guard | ✅ Done | `execution_agent.py`: checks open positions before any SELL; eliminates `insufficient balance` errors |
| 0b — Signal visibility | ✅ Done | SIGNAL broadcast over WebSocket; exec failure log push; purple `[SIGNAL]` lines in Bot Control |
| 1 — Dead code cleanup | ✅ Done | Removed `CryptoMomentumStrategy` block from `main.py`; deleted `quant/signals.py` + test file |
| 2a — PnL Calendar | ✅ Done | `PnLCalendar` SVG component (12w×7d heatmap, 5-step color scale); wired into `PerformanceMetrics` render |
| 2b — LLM Cost chart | ✅ Done | `LLMUsage` DB model; token logging in `reflection_engine.py` + `scanner_agent.py`; `/api/analytics/llm-cost`; dual-line SVG in `performance-metrics.tsx` |
| 2c — Attribution PnL | ✅ Done | `_entry_prices` dict tracks BUY fill prices; SELL computes `realized_pnl = (fill - entry) × qty`; passes to `update_yield` |
| 2 — Analysis tab (partial) | ✅ Done | Period switcher (1D/1W/1M/YTD) on equity chart; `/api/analytics/returns` real histogram; return distribution renders live fill data |
| 3 — Reflection quality | ✅ Done | `max_tokens` 100→250; prompt adds USD/coin unit context; eliminates "0.285 grams BTC" hallucination |
| 4 — Symbol scanner | ✅ Done | `scanner_agent.py` (EMA+RSI+BB+volume + Haiku verdicts); `WatchlistItem` DB model; `/api/watchlist` + `/api/watchlist/scan`; TA Scanner in sidebar |
| YTD period bug | ✅ Fixed | Alpaca rejects "YTD" — mapped to "6M" in `/api/performance` period_map |

---

## Area 2 — Analysis Tab (Remaining)

### 2a. PnL Calendar Heatmap *(next priority)*

GitHub-style contribution heatmap: 12 weeks × 7 days, each cell = daily P&L.

**Data:** `/api/performance?period=YTD` → `history: [[ts_ms, equity]]`
**Calculation:** `daily_pnl[i] = equity[i] - equity[i-1]`
**Colour scale:**
```
deep red (< -$50) → red (< $0) → grey (~$0) → green (> $0) → deep green (> +$50)
```
**File:** Add `PnLCalendar` sub-component inside `performance-metrics.tsx`. Pure SVG grid — no new dependency.

---

### 2b. LLM Cost vs PnL Chart

Dual-line chart: cumulative LLM spend (red) vs cumulative realized PnL (green) over time.

**New DB model:**
```python
class LLMUsage(Base):
    __tablename__ = "llm_usage"
    id         = Column(Integer, primary_key=True)
    model      = Column(String(50))   # claude-haiku-4-5, claude-sonnet-4-6
    tokens_in  = Column(Integer)
    tokens_out = Column(Integer)
    cost_usd   = Column(Float)        # computed at insert time
    purpose    = Column(String(50))   # "reflection" | "scanner" | "orchestrator"
    timestamp  = Column(DateTime(timezone=True), default=_utcnow)
```

**Pricing (April 2026):**
- Haiku: $0.80/M input, $4.00/M output
- Sonnet: $3.00/M input, $15.00/M output

**New endpoint:** `GET /api/analytics/llm-cost`

**Files to change:**
- `backend/db/models.py` — add `LLMUsage`
- `backend/agents/reflection_engine.py` — log tokens after each Haiku call
- `backend/agents/scanner_agent.py` — log tokens after each Haiku call
- `backend/main.py` — add `/api/analytics/llm-cost` endpoint
- `src/components/dashboard/performance-metrics.tsx` — dual-line SVG chart

---

### 2c. Strategy Attribution Real PnL

`master_engine.update_yield(bot_id, 0.0)` always passes `0.0` → attribution shows `$0.00`.

**Fix in `backend/main.py` (bar_callback):**
```python
_entry_prices: dict[tuple, float] = {}  # module-level: (bot_id, symbol) → fill price

# On BUY fill:
_entry_prices[(signal['bot'], symbol)] = exec_result.fill_price

# On SELL fill:
entry = _entry_prices.pop((signal['bot'], symbol), exec_result.fill_price)
realized_pnl = (exec_result.fill_price - entry) * exec_result.qty
master_engine.update_yield(signal['bot'], realized_pnl)
```

---

## Area 3 — Reflection Quality (Remaining)

### 3a. ReflectionLog Table with Execution FK

```python
class ReflectionLog(Base):
    __tablename__ = "reflection_logs"
    id           = Column(Integer, primary_key=True)
    execution_id = Column(Integer, ForeignKey("executions.id"), nullable=True)
    strategy     = Column(String(50))
    symbol       = Column(String(20))
    action       = Column(String(10))
    insight      = Column(String(500))
    tokens_used  = Column(Integer, nullable=True)
    timestamp    = Column(DateTime(timezone=True), default=_utcnow)
```

**Files:** `backend/db/models.py` + `backend/agents/reflection_engine.py`

### 3b. Learnings REST Endpoint

`GET /api/reflections` → last 50 `ReflectionLog` rows → Brain tab history section.

---

## Phase 2 Remaining

### Prompt Caching on Orchestrator

**File:** `backend/agents/orchestrator.py`

```python
self.system_prompt = SystemMessage(
    content=self.system_prompt.content,
    additional_kwargs={"cache_control": {"type": "ephemeral"}}
)
```
Saves ~2k input tokens on every chat invocation. Skill: `claude-api`

---

## Phase 4 — Backtesting Engine

### 4a. Add VectorBT to `backend/requirements.txt`
```
vectorbt>=0.26.0
```

### 4b. `backend/backtest/runner.py` (new file)
- OHLCV via `vbt.YFData.download()`
- Reuse `strategy/algorithms.py` signal logic
- Slippage: 0.05%, fees: 0%
- Strict 70/30 in-sample/out-of-sample split
- Returns: `{net_profit, max_drawdown, sharpe_ratio, equity_curve: [float]}`

### 4c. Endpoints
- `POST /api/backtest { symbol, strategy, start_date, end_date }`
- `GET /api/backtest/stream` — SSE progress 0–100%

### 4d. `BacktestRunner.tsx`
- Replace SVG mock with Nivo `ResponsiveLine` bound to `equity_curve`
- Live progress bar via SSE

Skills: `charting-nivo`, `trading-strategy-agents`

---

## Known Bugs

| Bug | File | Fix Status |
|-----|------|-----------|
| Strategy attribution always $0 | `main.py:716` | Pending — Area 2c above |
| `hft-sniper` stays HALTED across restarts | `risk/kill_switch.py` | Pending — add midnight daily reset |
| YTD period → Alpaca 400 error | `main.py` | ✅ Fixed — mapped to 6M |
| Reflection "0.285 grams BTC" | `reflection_engine.py` | ✅ Fixed — prompt rewritten |

---

## Priority Order for Next Session

1. **2a** — PnL calendar heatmap (visual impact, data already available via portfolio history)
2. **2c** — Attribution real PnL via entry price tracker (5-line fix)
3. **2b** — LLM cost chart (needs `LLMUsage` model first)
4. **3a** — `ReflectionLog` FK table + `GET /api/reflections` endpoint
5. Prompt caching on orchestrator (`claude-api` skill)
6. Phase 4 — VectorBT backtest engine

---

## Run Commands

```bash
# Backend
cd backend && uvicorn main:app --reload

# Frontend
npm run dev

# E2E tests
npx playwright test

# Verify performance endpoint
curl "http://localhost:8000/api/performance?period=1M"

# Trigger scanner
curl -X POST http://localhost:8000/api/watchlist/scan
```
