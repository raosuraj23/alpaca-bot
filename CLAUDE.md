@AGENTS.md
@DESIGN.md
@MASTER_INSTRUCTIONS.md

## Project Definition

Alpaca Quant Bot is a multi-agent quantitative trading system with an institutional-grade Next.js front-end and a Python/FastAPI multi-agent backend.

---

## Core Rules

1. **Never use arbitrary border radiuses.** Adhere strictly to sharp corners or `rounded-sm`. Never use `rounded`, `rounded-md`, `rounded-lg`, `rounded-full`, or `rounded-[N]`.

2. **Tabular Numerics are mandatory.** Every numerical value representing a ticker price, amount, size, percentage, or timestamp must use `font-mono tabular-nums`. No exceptions.

3. **No arbitrary font sizes.** Use the standard Tailwind scale only: `text-xs` (12px), `text-sm` (14px), `text-base` (16px), `text-lg` (18px). Never use `text-[10px]`, `text-[13px]`, `text-[9px]`, `text-[8px]`, or similar.

4. **Hydration pattern.** For any value that differs between SSR and client render (clocks, live prices, `Date.now()`, random seeds), use:
   ```tsx
   const [mounted, setMounted] = React.useState(false);
   React.useEffect(() => setMounted(true), []);
   if (!mounted) return null; // or a fixed-width placeholder
   ```
   Never use `suppressHydrationWarning` as a workaround.

5. **Data Fetching via Zustand.** The frontend uses a decoupled Zustand state engine (`src/hooks/useMockTradingStream.ts`) that bridges WebSocket and REST data. Maintain cross-origin policies in `next.config.ts`.

6. **Canonical type definitions.** All TypeScript interfaces for market data, trades, positions, agents, and API responses live in `src/lib/types.ts`. Import from there — do not redefine types locally.

7. **Mock data isolation.** All mock data constants (`INITIAL_WATCHLIST`, `MOCK_BOTS`, `MOCK_POSITIONS`, etc.) live in `src/lib/mock-data.ts`. Each export is annotated with a `// MOCK — replace when Phase N complete` comment. Never bury mock data in store or component files.

8. **Color tokens only.** Never use raw hex color values in component className strings. Always reference CSS variable tokens (`var(--background)`, `var(--neon-green)`, etc.) as defined in `src/app/globals.css` and documented in `DESIGN.md`.

9. **Scrollbars are 2px.** The global scrollbar override in `globals.css` sets width/height to 2px. Do not override this to a larger value in components.

10. **Agent Orchestrator Pipeline.** Follow `execution-plan.md` for the multi-stage rollout of the Python FastAPI orchestrator. Do not skip phases or implement backend logic without following the agent boundaries defined in `AGENTS.md`.

11. **Security non-negotiables.** Never hardcode API keys. All credentials come from `.env` via pydantic-settings. Never enable Alpaca Transfer/Withdrawal permissions. See `MASTER_INSTRUCTIONS.md` and `.claude/rules/security-and-risk.md` for full rules.

---

## File Map (key locations)

| File / Directory | Purpose |
|-----------------|---------|
| `src/lib/types.ts` | Canonical TypeScript type definitions (TickerData, TradeLog, PositionData, etc.) |
| `src/lib/mock-data.ts` | Mock data constants — isolated, annotated, phase-tagged |
| `src/lib/utils.ts` | `cn()` Tailwind merge utility |
| `src/hooks/useMockTradingStream.ts` | Zustand store + WebSocket bridge |
| `src/app/globals.css` | Design token CSS variables + scrollbar styles |
| `src/components/ui/` | Primitive design system components (Card, Button, Badge, ValueTicker) |
| `src/components/dashboard/` | 14 dashboard view components |
| `backend/agents/orchestrator.py` | LLM Orchestrator engine |
| `backend/agents/factory.py` | Agent factory / model tier selector |
| `execution-plan.md` | 4-phase backend rollout with current completion status |
| `DESIGN.md` | Full UI/UX design system specification (awesome-design-md format) |
| `AGENTS.md` | Agent architecture, boundaries, and backend file map |

---

## Available Skills

These Claude Code skills are pre-loaded and directly applicable to this project. Invoke them when the task matches:

| Skill | Invoke When |
|-------|------------|
| `trading-strategy-agents` | Building or extending the multi-agent orchestrator, risk agent, or execution agent |
| `trading-ui-patterns` | Dashboard components, order panels, position tables, watchlist UI |
| `risk-management` | Kill-switch logic, VaR computation, Kelly Criterion position sizing |
| `realtime-websocket` | Zustand WebSocket bridge, Alpaca stream manager, SSE endpoints |
| `charting-nivo` | Replacing SVG mock charts with real Nivo data-bound charts |
| `performance-optimization` | Memoization of expensive renders, virtualization for trade tables |
| `testing-playwright` | E2E tests for trading scenarios in `tests/dashboard.spec.ts` |
| `ai-insights` | AI analysis cards, orchestrator chat UI, thought stream matrix |
| `claude-api` | Optimizing Anthropic SDK usage, prompt caching in orchestrator |
| `frontend-design` | New component design following the Kraken aesthetic |
| `feature-dev` | Guided multi-step feature development with codebase analysis |
