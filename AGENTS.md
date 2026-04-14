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
| Risk Analyst | `src/components/dashboard/performance-metrics.tsx` | `backend/agents/risk_agent.py` *(Phase 2)* |
| Execution Agent | `src/components/dashboard/execution-log.tsx` | `backend/agents/execution_agent.py` *(Phase 2)* |

## Agent Boundaries

When building backend tasks, maintain strict separation between:

1. **Orchestrator** (`backend/agents/orchestrator.py`)
   - System brain. Receives natural language from `OrchestratorChat`.
   - Parses user intent into `OrchestratorCommand` actions.
   - Routes commands to Risk or Execution agents via LangGraph message passing.
   - Uses Claude Opus (smart tier) for complex strategy reasoning.
   - Uses Claude Haiku / Gemini (standard tier) for routing and formatting.

2. **Risk Agent** (`backend/agents/risk_agent.py`) *(Phase 2 — not yet created)*
   - Wraps `risk/kill_switch.py`. Every call to `execution/router.py` must pass through `kill_switch.check()` first.
   - Continuously evaluates: Max Daily Drawdown (2%), Position Size limits (10%/\$50k), VaR gate (1% 1-day 95%).
   - Automatically halts anomalous strategies and logs the event.
   - Powers the `PerformanceMetrics` tab with live risk metrics.

3. **Execution Agent** (`backend/agents/execution_agent.py`) *(Phase 2 — not yet created)*
   - Handles Alpaca API latency tracking and slippage calculation.
   - Constructs Level 2 limit orders.
   - Records fill price deviation from signal price as `slippage` in `TradeLog`.
   - Powers the `ExecutionLog` ledger with real fill data.

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

- SQLite models live in `backend/models.py` (to be created in Phase 2).
- Historical agent amends are stored in the `BotAmend` table.
- The `[Ledger]` tab queries `/api/ledger` for trade history.
- The `[Brain]` tab streams from `/api/reflections/stream` (Server-Sent Events).

## Backend File Locations

```
backend/
├── main.py                    # FastAPI app, REST + WebSocket endpoints
├── requirements.txt           # Python dependencies
├── agents/
│   ├── orchestrator.py        # OrchestratorEngine — Phase 1 COMPLETE
│   ├── factory.py             # SwarmFactory agent loader — Phase 1 COMPLETE
│   ├── risk_agent.py          # RiskAgent — Phase 2 TODO
│   └── execution_agent.py     # ExecutionAgent — Phase 2 TODO
├── risk/
│   ├── kill_switch.py         # Kill-switch enforcement — Phase 2 TODO
│   └── exposure.py            # VaR / Kelly / position sizing — Phase 2 TODO
├── execution/
│   └── router.py              # Order router to Alpaca — Phase 2 TODO
└── models.py                  # SQLAlchemy ORM models — Phase 2 TODO
```
