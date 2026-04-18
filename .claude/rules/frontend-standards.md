# rules/frontend-standards.md — Frontend Coding Standards
# These rules are MANDATORY for all frontend (Next.js / React / Tailwind) work.

---

## 1. Border Radius

Never use arbitrary border radiuses. Adhere strictly to sharp corners or `rounded-sm`. Never use `rounded`, `rounded-md`, `rounded-lg`, `rounded-full`, or `rounded-[N]`.

---

## 2. Tabular Numerics

Every numerical value representing a ticker price, amount, size, percentage, or timestamp must use `font-mono tabular-nums`. No exceptions.

---

## 3. Font Sizes

Use the standard Tailwind scale only: `text-xs` (12px), `text-sm` (14px), `text-base` (16px), `text-lg` (18px). Never use `text-[10px]`, `text-[13px]`, `text-[9px]`, `text-[8px]`, or similar.

---

## 4. Hydration Pattern

For any value that differs between SSR and client render (clocks, live prices, `Date.now()`, random seeds), use:

```tsx
const [mounted, setMounted] = React.useState(false);
React.useEffect(() => setMounted(true), []);
if (!mounted) return null; // or a fixed-width placeholder
```

Never use `suppressHydrationWarning` as a workaround.

---

## 5. Data Fetching via Zustand

The frontend uses a decoupled Zustand state engine (`src/hooks/useTradingStream.ts`) that bridges WebSocket and REST data. Maintain cross-origin policies in `next.config.ts`.

---

## 8. Color Tokens Only

Never use raw hex color values in component className strings. Always reference CSS variable tokens (`var(--background)`, `var(--neon-green)`, etc.) as defined in `src/app/globals.css` and documented in `docs/DESIGN.md`.

---

## 9. Scrollbars Are 2px

The global scrollbar override in `globals.css` sets width/height to 2px. Do not override this to a larger value in components.

---

## 12. Timezone Display (mandatory)

All timestamps are stored and transmitted from the backend in UTC. The frontend **must** convert every UTC timestamp to the user's local timezone before display — use `new Date(utcMs).toLocaleString(undefined, ...)`, `.toLocaleTimeString(undefined, { hour12: false })`, or `.toLocaleDateString(undefined, ...)`. Always pass `undefined` as the locale argument (never hardcode `'en-US'` or any other BCP 47 locale). Raw UTC strings (e.g. `2024-01-15T10:00:00Z`) must never be shown to the user. This applies to: trade timestamps, order submission times, reflection logs, ledger entries, PnL calendar dates, and any ISO timestamp field from the API.

---

## 15. AI Chat Rendering

AI chat responses must use `react-markdown` for rendering. Never render LLM-generated text as plain `{m.text}` in JSX. Always wrap in `<ReactMarkdown components={MD_COMPONENTS}>` with explicit per-element class renderers. Strip raw ` ```json ... ``` ` command blocks before display using a `stripCommandBlocks()` helper.

---

## 16. TanStack React Table (mandatory for all data tables)

Every component that renders tabular data must use `@tanstack/react-table` (`useReactTable`, `getCoreRowModel`, `getSortedRowModel`, `flexRender`, `ColumnDef`). No raw HTML `<table>` elements in data-display components. Follow the pattern established in `src/components/analytics/BotPerformanceMatrix.tsx`: define typed `ColumnDef<T>[]` with `React.useMemo`, use `useReactTable` with sorting state, render via `table.getHeaderGroups()` and `table.getRowModel().rows`. Every sortable column shows ▲/▼/⇅ indicators via `header.column.getToggleSortingHandler()`.
