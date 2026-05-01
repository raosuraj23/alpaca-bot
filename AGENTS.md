<!-- BEGIN:nextjs-agent-rules -->
# Next.js App Router Rules

This project uses the Next.js App Router (v14+). Use `"use client"` on every component that bridges UI with Zustand stores or uses browser APIs.

**Hydration Rule:** Never use `suppressHydrationWarning` to hide dynamic content. Instead, use the mount guard pattern:

```tsx
const [mounted, setMounted] = React.useState(false);
React.useEffect(() => setMounted(true), []);
if (!mounted) return <Skeleton />;  // or null
```

This applies to: clocks, live prices, random seeds, `Date.now()` calls, and any value that differs between SSR and the first client render.
<!-- END:nextjs-agent-rules -->

---

# LLM Orchestrator System Rules

The overarching goal is to deploy an LLM-Agent Orchestrator backend bridging Alpaca with our UI.

## UI Entry Points

| Agent | UI Component | Backend File |
|-------|-------------|-------------|
| Orchestrator | `src/components/dashboard/orchestrator-chat.tsx` | `backend/agents/orchestrator.py` |
| Risk Analyst | `src/components/dashboard/performance-metrics.tsx` | `backend/agents/risk_agent.py` |
| Execution Agent | `src/components/dashboard/execution-log.tsx` | `backend/agents/execution_agent.py` |
| Scanner Agent | `src/components/dashboard/sidebar-watchlist.tsx` | `backend/agents/scanner_agent.py` |
| Reflection Engine | `src/components/dashboard/bot-reflections.tsx` | `backend/agents/reflection_engine.py` |
| Portfolio Director | `src/components/dashboard/bot-control.tsx` | `backend/agents/portfolio_director.py` |
| Research Agent | `src/components/dashboard/ai-insights.tsx` | `backend/agents/research_agent.py` |

## Agent Boundaries

When building backend tasks, maintain strict separation between:

1. **Orchestrator** (`backend/agents/orchestrator.py`)
   - System brain. Receives natural language from `OrchestratorChat`.
   - Parses user intent into `OrchestratorCommand` actions.
   - Routes commands to Risk or Execution agents.
   - Uses Claude Opus (smart tier) for complex strategy reasoning.
   - Uses Claude Haiku / Gemini (standard tier) for routing and formatting.

2. **Risk Agent** (`backend/agents/risk_agent.py`)
   - Wraps `risk/kill_switch.py`. Every order must pass through `kill_switch.check()` first.
   - Continuously evaluates: Max Daily Drawdown (2%), Position Size limits (10%/$50k), VaR gate (1% 1-day 95%).
   - Automatically halts anomalous strategies and logs the event.
   - Powers the `PerformanceMetrics` tab with live risk metrics.

3. **Execution Agent** (`backend/agents/execution_agent.py`)
   - Handles Alpaca API latency tracking and slippage calculation.
   - Constructs market orders via the Alpaca trading client.
   - Records fill price deviation from signal price as `slippage` in `ExecutionRecord`.
   - Powers the `ExecutionLog` ledger with real fill data.

4. **Scanner Agent** (`backend/agents/scanner_agent.py`)
   - Three-tier symbol discovery: TA screener → Haiku filter → dynamic universe.
   - Outputs scored watchlist to `/api/watchlist`; pushes new symbols into live streams.
   - Runs on a configurable cadence (default 5 min).

5. **Research Agent** (`backend/agents/research_agent.py`)
   - Gemini 2.5 Flash deep-research loop (30-min cadence).
   - Fetches news + macroeconomic context, produces `ResearchBrief`.
   - Fed into ScannerAgent Tier 1 for better symbol selection and edge detection.

6. **Reflection Engine** (`backend/agents/reflection_engine.py`)
   - Post-trade AI insight generation triggered after every fill.
   - Persists insights to `ReflectionLog` table; streams to Brain tab via SSE.
   - Generates `BotAmend` strategy parameter updates.

7. **Portfolio Director** (`backend/agents/portfolio_director.py`)
   - Autonomous 15-min review loop using Claude Haiku tool use.
   - Reads scanner results + bot states; executes allocation, halt/resume, and param changes.
   - Logs all decisions to `BotAmend` table; streams to Brain tab via SSE.

8. **Nightly Consolidation** (`backend/agents/nightly_consolidation.py`)
   - Runs at 23:55 UTC; writes daily metrics to `metrics_log.jsonl`.
   - Summarises win rates, PnL attribution, and LLM costs per strategy.

## Inter-Agent Message Schema

All agent-to-agent messages must conform to this JSON schema:

```json
{
  "agent": "orchestrator | risk_agent | execution_agent",
  "action": "HALT_BOT | RESUME_BOT | ADJUST_ALLOCATION | TRIGGER_BACKTEST | QUERY_RISK",
  "target_bot": "momentum-alpha | statarb-gamma | hft-sniper",
  "params": {
    "reason": "string",
    "new_allocation_pct": "number (optional)",
    "max_drawdown_override": "number (optional)"
  },
  "timestamp": 1713000000000
}
```

## Stateless Operations

AI memory state must be managed via SQLite (local) or a remote vector DB.

- SQLite models live in `backend/db/models.py`.
- Historical agent amends are stored in the `BotAmend` table.
- The `[Ledger]` tab queries `/api/ledger` for trade history.
- The `[Brain]` tab streams from `/api/reflections/stream` (Server-Sent Events).

## Backend File Locations

```text
backend/
├── main.py                    # Lightweight FastAPI entry point + startup lifecycle
├── deps.py                    # Dependency injection (Alpaca TradingClient)
├── config.py                  # Pydantic-settings config (all env vars)
├── requirements.txt
├── routers/                   # Modular FastAPI endpoints
│   ├── account.py             # /api/account, /api/positions, /api/orders
│   ├── agents.py              # /api/agents/chat, /api/risk/status
│   ├── analytics.py           # /api/ledger, /api/performance, /api/analytics/*
│   ├── bots.py                # /api/bots, /api/bots/{id}/halt|resume, /api/strategy/states
│   └── trading.py             # /api/seed, /api/ohlcv, /api/watchlist, /api/market/*
├── websockets/
│   └── stream.py              # Alpaca stream managers + SSE + WebSocket /stream
├── agents/
│   ├── orchestrator.py        # OrchestratorEngine (LangChain)
│   ├── factory.py             # SwarmFactory — LLM client factory
│   ├── risk_agent.py          # RiskAgent — kill-switch gate
│   ├── execution_agent.py     # ExecutionAgent — order execution + slippage
│   ├── scanner_agent.py       # ScannerAgent — TA screener + universe discovery
│   ├── research_agent.py      # ResearchAgent — Gemini deep-research loop
│   ├── reflection_engine.py   # ReflectionEngine — post-trade AI insights
│   ├── portfolio_director.py  # AutonomousPortfolioDirector — 15-min review loop
│   └── nightly_consolidation.py  # NightlyConsolidation — 23:55 UTC daily metrics
├── core/
│   └── state.py               # Shared in-memory state (queues, streams, entry prices)
├── state/
│   └── action_items.py        # Cached Haiku action-items state
├── risk/
│   ├── kill_switch.py         # Kill-switch enforcement
│   ├── exposure.py            # VaR / Kelly / position sizing
│   └── calibration.py        # Brier score calibration tracking
├── strategy/
│   ├── engine.py              # MasterStrategyEngine — tick routing + bot lifecycle
│   ├── algorithms.py          # Crypto strategy implementations
│   └── equity_algorithms.py   # Equity strategy implementations
├── predict/
│   ├── xgboost_classifier.py  # XGBoost probability gate (pre-LLM)
│   └── feature_extractor.py   # Signal feature engineering
├── quant/
│   └── data_buffer.py         # OHLCV market data buffer
├── backtest/
│   └── runner.py              # VectorBT backtest runner
├── db/
│   ├── models.py              # SQLAlchemy ORM models
│   └── database.py            # Async SQLite engine + schema migration
└── knowledge/                 # Compound learning knowledge base (post-mortems)
```
