# Alpaca Quant Terminal — Architecture Reference

> Source of truth for system architecture decisions. Kept in sync with DESIGN.md, AGENTS.md, and execution-plan.md.

---

## 1. System Overview

```
┌─────────────────────────────────────────────────────┐
│  Next.js Frontend (localhost:3000)                   │
│  React 19 · Tailwind CSS 4 · Zustand · Framer Motion│
│                                                      │
│  ┌─────────┐  ┌──────────┐  ┌──────────────────┐   │
│  │ Zustand  │◄─┤WebSocket │◄─┤ FastAPI Backend   │   │
│  │  Store   │  │ Bridge   │  │  localhost:8000   │   │
│  └────┬─────┘  └──────────┘  └────────┬─────────┘   │
│       │                               │              │
│  14 Dashboard Panels           Alpaca Markets API    │
│  (DESK/ANALYSIS/BOTS/           (Paper Trading)      │
│   TESTS/LEDGER/BRAIN)                │               │
└───────────────────────────────────────────────────── ┘
                                   │
                          LangChain Orchestrator
                          Claude claude-sonnet-4-6
                          + LangGraph (Phase 2)
```

---

## 2. Frontend Component Tree

```
AppShell (src/app/page.tsx)
├── Header
│   ├── Brand (ALPACA X)
│   ├── AssetClassSelector (EQUITY | OPTIONS | CRYPTO)
│   ├── TabNavigation (6 tabs)
│   ├── LiveIndicator
│   ├── TotalEquity (from Zustand accountEquity)
│   └── SystemClock (mount-guarded, no SSR)
├── MainViewport (animated with Framer Motion)
│   ├── [DESK]        → TradingDesk
│   │   ├── SidebarWatchlist
│   │   ├── MarketOverview
│   │   ├── ExecutionLog
│   │   ├── BotControl
│   │   ├── AiInsights
│   │   ├── PositionsTable
│   │   └── TradePanel
│   ├── [ANALYSIS]    → PerformanceMetrics
│   ├── [BOTS]        → QuantStrategies
│   ├── [TESTS]       → BacktestRunner
│   ├── [LEDGER]      → TradeLedger
│   └── [BRAIN]       → BotReflections
└── OrchestratorChat (fixed FAB, bottom-right)
```

---

## 3. Design System Tokens (DESIGN.md — authoritative)

| Role | CSS Variable | Value |
|------|-------------|-------|
| Background | `--background` | `hsl(255, 30%, 6%)` |
| Panel | `--panel` | `hsl(255, 20%, 10%)` |
| Panel Hover | `--panel-muted` | `hsl(255, 15%, 15%)` |
| Border | `--border` | `hsla(255, 40%, 40%, 0.15)` |
| Text | `--foreground` | `hsl(210, 20%, 95%)` |
| Text Muted | `--muted-foreground` | `hsl(250, 10%, 65%)` |
| Purple Brand | `--kraken-purple` | `hsl(264, 80%, 65%)` |
| Purple Light | `--kraken-light` | `hsl(264, 80%, 75%)` |
| Green (LONG) | `--neon-green` | `hsl(150, 80%, 45%)` |
| Red (SHORT) | `--neon-red` | `hsl(350, 80%, 60%)` |

Typography: Inter (UI) + JetBrains Mono (all numbers, monospace). All numbers: `font-mono tabular-nums`.

---

## 4. Backend API Endpoints

| Method | Path | Phase | Description |
|--------|------|-------|-------------|
| GET | `/api/account` | 1 ✅ | Account equity + buying power |
| GET | `/api/positions` | 1 ✅ | Active holdings |
| GET | `/api/orders` | 1 ✅ | Order history (last 50) |
| POST | `/api/seed` | 1 ✅ | Place market order (accepts symbol/side/qty) |
| POST | `/api/agents/chat` | 1 ✅ | Orchestrator LLM chat |
| WS | `/stream` | 1 ✅ | Real-time market data broadcast |
| GET | `/api/reflections` | 3 📋 | Agent learning history (DB query) |
| SSE | `/api/reflections/stream` | 3 📋 | Live thought stream |
| POST | `/api/backtest` | 4 📋 | Launch VectorBT simulation |
| SSE | `/api/backtest/stream` | 4 📋 | Stream backtest progress % |
| POST | `/api/strategies/deploy` | 2 📋 | Deploy/configure strategy bot |

✅ = complete, 📋 = planned

---

## 5. WebSocket Payload Schema

```json
// Market tick (from Alpaca CryptoDataStream bars)
{ "type": "TICK", "data": { "symbol": "BTC/USD", "price": 64230.50, "volume": 1.25, "timestamp": "2026-04-13T21:00:00Z" } }

// Quote (from Alpaca CryptoDataStream quotes)
{ "type": "QUOTE", "data": { "symbol": "BTC/USD", "price": 64231.00, "timestamp": "2026-04-13T21:00:01Z" } }

// Phase 3: Bot signal (from execution agent)
{ "type": "SIGNAL", "data": { "bot_id": "momentum-alpha", "action": "LONG", "confidence": 0.89, "symbol": "BTC/USD" } }
```

---

## 6. Multi-Agent Architecture (Phase 2 target)

```
User Message
     │
     ▼
OrchestratorEngine (claude-sonnet-4-6)
     │  parse intent → OrchestratorCommand
     ├──► RiskAgent ──► check() ──► PASS/FAIL
     │         │                      │
     │         │ PASS                 │ FAIL
     │         ▼                      ▼
     ├──► ExecutionAgent         Halt + Alert
     │    submit_order()
     │    record slippage
     │
     └──► AiInsightsAgent (claude-haiku for sentiment, sonnet for analysis)
          generate_insight()
```

Agent files: `.claude/agents/*.md` — loaded by `backend/agents/factory.py` at startup.

---

## 7. State Management (Frontend)

Zustand store (`useTradingStore`) is the single source of truth:

```
TradingStore
├── assetClass: 'CRYPTO' | 'EQUITY' | 'OPTIONS'
├── activeSymbol: string
├── accountEquity: number | null        ← from /api/account
├── ticker: TickerData | null           ← from WebSocket
├── watchlist: TickerData[]             ← updated via injectSocketData()
├── recentTrades: TradeLog[]            ← from /api/orders or WebSocket fills
├── positions: PositionData[]           ← from /api/positions
└── botLogs: string[]                   ← MOCK (Phase 2: from /stream SIGNAL events)
```

Type definitions: `src/lib/types.ts` (canonical — never redefine locally).
Mock data: `src/lib/mock-data.ts` (phase-annotated constants).

---

## 8. Performance Optimization Plan

1. **Memoization** — `React.memo` on chart components + `useMemo` for Nivo data arrays
2. **Virtualization** — `@tanstack/react-virtual` for TradeLedger rows (cap DOM at 50 visible rows)
3. **Zustand transient updates** — `api.subscribe` for high-frequency ticker updates, bypassing React render cycle for intermediate ticks
4. **Web Workers** — Offload VaR computation, standard deviation, and large array operations
5. **Lazy imports** — Dynamic `import()` for Nivo chart components to reduce initial bundle
6. **Nivo optimization** — `animate={false}` on real-time charts, limit to 200 visible data points

---

## 9. Security Architecture

See `.claude/rules/security-and-risk.md` for full rules. Key points:

- All credentials via pydantic-settings from `.env` (never hardcoded)
- Alpaca keys: Trade + Read ONLY (Transfer/Withdrawal disabled)
- CORS: restricted to `http://localhost:3000` in development
- Paper trading gate in `/api/seed`: live orders blocked unless `PAPER_TRADING=false` explicitly set
- WebSocket auth: JWT token validation planned for Phase 3
- Session files: `sessions/{account_id}.json` (gitignored)
