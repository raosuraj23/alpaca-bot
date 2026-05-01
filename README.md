# Alpaca Quant Terminal — Multi-Agent Orchestrator

A state-of-the-art quantitative trading dashboard engineered for algorithmic supervision. Built with an institutional-grade multi-tab Next.js interface following Kraken dark-mode aesthetics.

## Tech Stack

| Layer | Technology |
|-------|-----------|
| Frontend framework | Next.js (App Router) 16.2.3 |
| UI library | React 19.2.4 |
| Styling | Tailwind CSS 4.x |
| State management | Zustand 5.0.12 |
| Animation | Framer Motion |
| Charts | Nivo (bar, line) + lightweight-charts |
| Backend API | FastAPI + Uvicorn |
| LLM orchestration | LangChain + Anthropic SDK |
| LLM providers | Claude (Anthropic) + Gemini (Google) |
| Trading API | Alpaca-py |
| Quant / Data | Pandas, NumPy, XGBoost |
| E2E testing | Playwright |

## Project Architecture

Split into an **Automated Supervisor UI** (Next.js) and a **Multi-Agent Python Backend** (FastAPI).

```
alpaca-bot/
├── src/
│   ├── app/              # Next.js App Router (layout, page, globals.css)
│   ├── components/
│   │   ├── dashboard/    # Dashboard view components
│   │   ├── analytics/    # Analytics panel components
│   │   └── ui/           # Design system primitives (Card, Button, Badge)
│   ├── store/
│   │   └── index.ts      # Zustand store + WebSocket/SSE bridge
│   └── lib/
│       ├── types.ts       # Canonical TypeScript type definitions
│       ├── mock-data.ts   # Mock data constants
│       ├── static-data.ts # Static seed data
│       ├── api.ts         # API_BASE / WS_BASE constants
│       └── utils.ts       # Utilities (cn, parseUtc)
├── backend/
│   ├── main.py            # FastAPI entry point + startup lifecycle
│   ├── deps.py            # Dependency injection (Alpaca TradingClient)
│   ├── config.py          # Pydantic-settings config
│   ├── routers/           # Modular API endpoints (account, bots, analytics, trading, agents)
│   ├── websockets/        # Alpaca stream managers + SSE + WebSocket
│   ├── agents/            # 8 LLM agents (orchestrator, risk, execution, scanner, research, reflection, director, nightly)
│   ├── core/              # Shared in-memory state (queues, streams, entry prices)
│   ├── state/             # Action-items cache
│   ├── risk/              # Kill-switch, VaR, Kelly, calibration
│   ├── strategy/          # MasterStrategyEngine + algo implementations
│   ├── predict/           # XGBoost probability gate + feature extractor
│   ├── quant/             # OHLCV data buffer
│   ├── backtest/          # VectorBT backtest runner
│   ├── db/                # SQLAlchemy async models + SQLite schema migration
│   ├── knowledge/         # Compound learning post-mortem knowledge base
│   └── requirements.txt
├── docs/
│   ├── DESIGN.md          # Full UI/UX design system specification
│   └── execution-plan.md  # 5-phase backend rollout with phase status
├── tests/
│   └── dashboard.spec.ts  # Playwright E2E tests
├── scripts/
│   └── uvicorn_capture.py # Dev server capture utility
├── execution-plan.md      # High-level 5-phase roadmap (summary)
├── AGENTS.md              # Agent architecture + backend file map
└── CLAUDE.md              # AI assistant project instructions
```

## Feature Status

| Feature | Status |
|---------|--------|
| Kraken dark-mode UI (14+ panels) | Complete |
| Tab navigation (Desk, Analysis, Bots, Tests, Ledger, Brain) | Complete |
| Real-time live data via Zustand + SSE | Complete |
| WebSocket bridge to FastAPI | Complete |
| REST integration (account, positions, orders) | Complete |
| Orchestrator chat (LangChain) | Complete |
| Risk agent (drawdown / VaR / kill-switch) | Complete |
| Execution agent (slippage tracking) | Complete |
| XGBoost signal probability gate | Complete |
| Scanner agent (TA screener + universe discovery) | Complete |
| Research agent (Gemini 2.5 Flash deep research) | Complete |
| Reflection engine (post-trade AI insights) | Complete |
| Portfolio Director (autonomous 15-min review loop) | Complete |
| Backtesting engine (VectorBT) | Complete |
| Analytics dashboard (LLM cost, calibration, returns) | Complete |
| Options trading integration | Phase 5 — planned |

## Getting Started

### 1. Frontend

```bash
npm install
npm run dev
```

Opens at `http://localhost:3000`. The UI runs on mock data if the backend is unavailable.

### 2. Backend (Multi-Agent Engine)

```bash
# Create and activate virtual environment
python -m venv venv

# Windows
.\venv\Scripts\activate

# macOS / Linux
source venv/bin/activate

# Install dependencies
pip install -r backend/requirements.txt

# Start the FastAPI server (run from project root)
uvicorn backend.main:app --reload --port 8000
```

API docs available at `http://localhost:8000/docs`.

### 3. Environment Variables

Copy `.env.example` to `.env` and fill in your credentials:

```bash
cp .env.example .env
```

Required variables:

```
ALPACA_API_KEY_ID=your_paper_trading_key
ALPACA_API_SECRET_KEY=your_paper_trading_secret
ALPACA_BASE_URL=https://paper-api.alpaca.markets
PAPER_TRADING=true
ANTHROPIC_API_KEY=your_claude_api_key
GEMINI_API_KEY=your_gemini_key
DATABASE_URL=sqlite:///./alpaca_quant.db
```

> **Security:** Never commit `.env` with real credentials. All keys must use paper trading permissions only (Trade + Read; never Transfer or Withdrawal).

### 4. E2E Tests

```bash
npx playwright test
```

## Design System

All UI is governed by `docs/DESIGN.md`. Key rules:

- Colors: CSS variable tokens only (never raw hex in component files)
- Numbers: `font-mono tabular-nums` on every price, size, PnL, percentage
- Corners: `rounded-sm` maximum — no `rounded`, `rounded-md`, or `rounded-full`
- Scrollbars: 2px width globally
- Font sizes: standard Tailwind scale (`text-xs`, `text-sm`, `text-base`) — no arbitrary sizes

## Roadmap

See `execution-plan.md` for the 5-phase backend roadmap. Current completion: **~90%** (Phases 1–4 complete, Phase 5 Options pending).
