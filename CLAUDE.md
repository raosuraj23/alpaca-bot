## Project Definition

Alpaca Quant Bot is a multi-agent quantitative trading system with an institutional-grade Next.js front-end and a Python/FastAPI multi-agent backend.

---

## Core Rules
DO NOT MAKE ANY VCHANGES UNTIL YOU HAVE 95% CONFIDENCE IN WHAT YOU NEED TO BUILD. ASK ME FOLLOW-UP QUESTIONS UNTIL YOU REACH THAT CONFIDENCE

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

12. **Timezone rule (mandatory).** All timestamps are stored and transmitted from the backend in UTC. The frontend **must** convert every UTC timestamp to the user's local timezone before display — use `new Date(utcMs).toLocaleString()`, `.toLocaleTimeString()`, or `.toLocaleDateString()`. Raw UTC strings (e.g. `2024-01-15T10:00:00Z`) must never be shown to the user. This applies to: trade timestamps, order submission times, reflection logs, ledger entries, PnL calendar dates, and any ISO timestamp field from the API.


---
