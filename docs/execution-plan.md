# Alpaca Quant Terminal - Execution Plan

## Phase 1: Core Dashboard & AI Orchestration
- [x] Complete Next.js Kraken dark mode UI design.
- [x] Implement Zustand state layer and WebSocket integrations.
- [x] Build LangChain master orchestrator engine.
- [x] Deploy dual-LLM architecture (Opus for strategy, Haiku for routing).

## Phase 2: Risk Management & Live Execution
- [x] Develop risk_agent.py and kill_switch.py to gate all trades.
- [x] Integrate execution_agent.py with live Alpaca latency/slippage tracking.
- [x] Transition state to SQLite via SQLAlchemy models in `backend/db`.
- [x] Implement modular backend API structure (`backend/routers/`).

## Phase 3: AI Reflection & Continuous Learning
- [x] Implement `BotAmend` generation and storage logic.
- [x] Build SSE endpoints for streaming reflection logs directly to the dashboard.
- [x] Create the Brain tab to render the live stream of AI thoughts and trade post-mortems.

## Phase 4: Backtesting Engine (VectorBT)
- [ ] Install and configure VectorBT for high-performance vectorized backtesting.
- [ ] Connect `BacktestRunner` to fetch historical Alpaca market data.
- [ ] Build `/api/backtest` endpoint.
- [ ] Update frontend Tests tab to render VectorBT equity curves and drawdown metrics.

## Phase 5: Options Trading Integration
- [ ] Update Alpaca clients to support option chains.
- [ ] Implement `OptionsPricingModel` (Black-Scholes / Binomial).
- [ ] Develop `volatility-arbitrage` AI agent.
- [ ] Update Dashboard positions table to support Greeks rendering (Delta, Gamma, Theta, Vega).
