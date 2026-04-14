# Alpaca Quant Terminal — Multi-Agent Orchestrator

A state-of-the-art quantitative trading dashboard engineered for high-frequency algorithmic supervision. Built with an institutional-grade multi-tab Next.js interface following Kraken dark-mode aesthetics.

## Tech Stack

| Layer | Technology | Version |
|-------|-----------|---------|
| Frontend framework | Next.js (App Router) | 16.2.3 |
| UI library | React | 19.2.4 |
| Styling | Tailwind CSS | 4.x |
| State management | Zustand | 5.0.12 |
| Animation | Framer Motion | 12.38.0 |
| Charts | Nivo (bar, line) | 0.99.0 |
| Backend API | FastAPI + Uvicorn | 0.104.1 / 0.24.0 |
| LLM orchestration | LangChain + LangGraph | 0.1.13 / 0.0.30 |
| LLM providers | Claude (Anthropic) + Gemini (Google) | via LangChain |
| Trading API | Alpaca-py | 0.32.0 |
| Quant / Data | Pandas, NumPy, CCXT | 2.1.3 / 1.26.2 / 4.1.38 |
| E2E testing | Playwright | 1.59.1 |

## Project Architecture

Split into an **Automated Supervisor UI** (Next.js) and a **Multi-Agent Python Backend** (FastAPI + LangChain).

```
alpaca-bot/
├── src/
│   ├── app/              # Next.js App Router (layout, page, globals.css)
│   ├── components/
│   │   ├── dashboard/    # 14 dashboard view components
│   │   └── ui/           # Design system primitives (Card, Button, Badge, ValueTicker)
│   ├── hooks/
│   │   └── useMockTradingStream.ts   # Zustand store + WebSocket bridge
│   └── lib/
│       ├── types.ts      # Canonical TypeScript type definitions
│       ├── mock-data.ts  # Mock data constants (replace with real API in each phase)
│       └── utils.ts      # cn() utility
├── backend/
│   ├── main.py           # FastAPI app — REST endpoints + WebSocket stream
│   ├── agents/
│   │   ├── orchestrator.py   # LLM Orchestrator engine (Phase 1 complete)
│   │   └── factory.py        # Agent factory / model tier selector
│   └── requirements.txt
├── tests/
│   └── dashboard.spec.ts # Playwright E2E tests
├── DESIGN.md             # Full UI/UX design system specification
├── AGENTS.md             # Agent architecture + backend file map
├── execution-plan.md     # 4-phase backend rollout with current status
└── MASTER_INSTRUCTIONS.md  # Core quant philosophy + security rules
```

## Feature Status

| Feature | Status |
|---------|--------|
| Kraken dark-mode UI (14 panels) | Complete |
| Tab navigation (Desk, Analysis, Bots, Tests, Ledger, Brain) | Complete |
| Real-time mock data via Zustand | Complete |
| WebSocket bridge to FastAPI | Complete |
| REST integration (account, positions, orders) | Complete |
| Orchestrator chat (LangChain) | Complete (needs API keys) |
| Risk agent (drawdown / VaR / kill-switch) | Phase 2 — in progress |
| Execution agent (slippage tracking) | Phase 2 — in progress |
| Bot reflection / thought stream | Phase 3 — planned |
| Backtesting engine (VectorBT) | Phase 4 — planned |
| Real Alpaca market data feed | Needs API key configuration |

## Getting Started

### 1. Frontend

```bash
npm install
npm run dev
```

Opens at `http://localhost:3000`. The UI runs fully on mock data if the backend is unavailable.

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

# Start the FastAPI server
cd backend
uvicorn main:app --reload --port 8000
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
GEMINI_API_KEY=your_gemini_key_optional
DATABASE_URL=sqlite:///./trading_bot.db
```

> **Security:** Never commit `.env` with real credentials. All keys must use paper trading permissions only (Trade + Read; never Transfer or Withdrawal).

### 4. E2E Tests

```bash
npx playwright test
```

## Design System

All UI is governed by `DESIGN.md`. Key rules:

- Colors: CSS variable tokens only (never raw hex in component files)
- Numbers: `font-mono tabular-nums` on every price, size, PnL, percentage
- Corners: `rounded-sm` maximum — no `rounded`, `rounded-md`, or `rounded-full`
- Scrollbars: 2px width globally
- Font sizes: standard Tailwind scale (`text-xs`, `text-sm`, `text-base`) — no arbitrary sizes

## Roadmap

See `execution-plan.md` for the detailed 4-phase backend rollout. Current overall completion: **~40%** (Phase 1 at 70%, Phases 2–4 pending API key configuration and agent implementation).
