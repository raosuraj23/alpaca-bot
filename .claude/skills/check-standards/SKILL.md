---
name: check-standards
description: Verify a frontend component meets all mandatory coding standards before marking a task complete. Use after any frontend edit.
user-invocable: false
---

Before reporting any frontend change complete, run through this checklist against the modified files:

1. **Tabular numerics** — Every price, amount, size, percentage, or timestamp value uses `font-mono tabular-nums`. No exceptions.

2. **Border radius** — No `rounded`, `rounded-md`, `rounded-lg`, `rounded-full`, or `rounded-[N]` classes. Only sharp corners or `rounded-sm` are allowed.

3. **Timezone conversion** — UTC timestamps are never shown raw. Every timestamp uses `toLocaleTimeString(undefined, ...)`, `toLocaleString(undefined, ...)`, or `toLocaleDateString(undefined, ...)` with `undefined` as the locale (never `'en-US'` or any hardcoded BCP 47 tag).

4. **Data tables** — Any tabular data display uses `@tanstack/react-table` (`useReactTable`, `ColumnDef`, `flexRender`). No raw `<table>` elements in data-display components. Sortable columns show ▲/▼/⇅ indicators.

5. **AI/LLM text rendering** — LLM-generated text is wrapped in `<ReactMarkdown components={MD_COMPONENTS}>`, never rendered as plain `{m.text}`. Raw ` ```json ``` ` command blocks are stripped via `stripCommandBlocks()` before display.

6. **Color tokens** — No raw hex color values in `className` strings. Only CSS variable tokens (`var(--background)`, `var(--neon-green)`, etc.) from `src/app/globals.css`.

7. **Hydration guard** — Any value that differs between SSR and client render (clocks, live prices, `Date.now()`) uses the mount guard pattern:
   ```tsx
   const [mounted, setMounted] = React.useState(false);
   React.useEffect(() => setMounted(true), []);
   if (!mounted) return null;
   ```
   Never use `suppressHydrationWarning`.

8. **Font sizes** — Only standard Tailwind scale: `text-xs`, `text-sm`, `text-base`, `text-lg`. No arbitrary sizes like `text-[10px]`.

Report each violation with the file path and line number. If all checks pass, state "Standards verified — no violations found."
