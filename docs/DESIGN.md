# DESIGN.md — Alpaca Quant Terminal

> Follows the [awesome-design-md](https://github.com/VoltAgent/awesome-design-md) specification format.
> Purpose: LLM-readable design system for consistent UI generation across agents and codegen tools.

---

## 1. Visual Theme & Atmosphere

**Identity:** Institutional crypto-quant terminal. Void-purple void canvas with electric neon accents. Zero decoration. Every pixel earns its place.

**Mood:** Kraken-dark. Cool. Data-dense. Trustworthy under pressure. The aesthetic of a Bloomberg terminal crossed with a dark-mode exchange interface.

**Key principles:**
- Information density over whitespace — pack the grid, never breathe
- Color carries semantic weight — green is LONG/profit, red is SHORT/loss, purple is system/brand
- Numbers are sacred — monospace, tabular-numeral alignment, never truncated
- Motion is purposeful — transitions signal state change, not decoration
- Sharp edges signal precision — no decorative rounding, corners exist to contain

---

## 2. Color Palette & Roles

All colors are defined as CSS custom properties in `src/app/globals.css`.

### Core Surfaces

| Token | CSS Variable | Value | Role |
|-------|-------------|-------|------|
| Background Root | `--background` | `hsl(255, 30%, 6%)` | Page/app background. Near-black deep indigo. |
| Panel Primary | `--panel` | `hsl(255, 20%, 10%)` | Cards, headers, sidebars. Slightly lifted from root. |
| Panel Hover/Secondary | `--panel-muted` | `hsl(255, 15%, 15%)` | Hover states, active toggles, nested containers. |
| Border | `--border` | `hsla(255, 40%, 40%, 0.15)` | All dividers, table rules, card outlines. Translucent purple. |

### Text

| Token | CSS Variable | Value | Role |
|-------|-------------|-------|------|
| Text Primary | `--foreground` | `hsl(210, 20%, 95%)` | Body text, labels, active values. Off-white. |
| Text Muted | `--muted-foreground` | `hsl(250, 10%, 65%)` | Labels, secondary annotations, captions. |

### Accent / Brand

| Token | CSS Variable | Value | Role |
|-------|-------------|-------|------|
| Kraken Purple | `--kraken-purple` | `hsl(264, 80%, 65%)` | Primary CTA buttons, active tab underline, focus rings, brand icon glow. |
| Kraken Light | `--kraken-light` | `hsl(264, 80%, 75%)` | Highlighted text, header labels, hover state for purple elements. |

### Market Semantics

| Token | CSS Variable | Value | Role |
|-------|-------------|-------|------|
| Neon Green | `--neon-green` | `hsl(150, 80%, 45%)` | LONG direction, positive PnL, BUY orders, upward delta, profit values. |
| Neon Red | `--neon-red` | `hsl(350, 80%, 60%)` | SHORT direction, negative PnL, SELL orders, downward delta, loss values. |

### Agent / Reflection Type Colors

Used exclusively in the Brain tab (BotReflections) to color-code agent thought types.
Defined as CSS variables — never use raw Tailwind palette names (`text-purple-400` is forbidden).

| Token | CSS Variable | Value | Role |
|-------|-------------|-------|------|
| Agent Observe | `--agent-observe` | `hsl(270, 60%, 65%)` | OBSERVE — market scan events |
| Agent Calculate | `--agent-calculate` | `hsl(220, 70%, 65%)` | POSITION — Kelly/sizing events |
| Agent Scanner | `--agent-scanner` | `hsl(190, 70%, 60%)` | SCANNER — Haiku symbol ranking |
| Agent Learning | `--agent-learning` | `hsl(40, 80%, 60%)` | LEARNED — strategy amendment |

DECISION (neon-green) and DIRECTOR (kraken-light) reuse existing tokens.

### Usage Rules
- **Never use raw hex/RGB** — always reference CSS variable tokens.
- **Never use raw Tailwind palette colors** (`text-purple-400`, `text-blue-400`, `text-amber-400`, `text-cyan-400`) — define a CSS variable and reference it. Audit finding: `bot-reflections.tsx` originally violated this.
- **Neon green = LONG/profit only.** Do not use for generic "success" states unrelated to market direction.
- **Neon red = SHORT/loss only.** Do not use for generic "error" or "danger" states unrelated to market.
- **Purple = system/brand.** Used for UI chrome, active states, and AI/orchestrator elements.

---

## 3. Typography Rules

### Font Families

| Role | Font | Import |
|------|------|--------|
| UI Sans-serif | `Inter` | Google Fonts via `next/font/google` |
| All Numbers & Monospace | `JetBrains Mono` | Google Fonts via `next/font/google` |

### Non-Negotiable Rules
- **ALL numerical values** (prices, sizes, PnL, percentages, timestamps) **must use `font-mono` + `tabular-nums`** class. No exceptions.
- Inter uses tight tracking (`tracking-tight` or `tracking-wide` for uppercase labels).
- JetBrains Mono is used for any terminal-style log output or console text.

### Type Hierarchy

| Level | Tailwind Classes | Use |
|-------|-----------------|-----|
| Page Title | `text-sm font-bold tracking-tight text-[var(--kraken-light)]` | App name / section headers |
| Section Header | `text-xs font-semibold uppercase tracking-wider text-[var(--muted-foreground)]` | Card titles, panel labels |
| Body / Table | `text-xs text-[var(--foreground)]` | Default UI text, table cells |
| Caption / Annotation | `text-xs text-[var(--muted-foreground)]` | Sub-labels, tooltips, trailing metadata |
| Live Price (large) | `text-xl font-mono font-bold tabular-nums text-[var(--foreground)]` | Ticker display, current price |
| Metric Value | `text-sm font-mono tabular-nums font-semibold` | KPI cards, stat boxes |
| Console / Log | `text-xs font-mono text-[var(--muted-foreground)]` | Bot logs, execution traces |

### Forbidden Patterns
- **No** `text-[13px]`, `text-[10px]`, `text-[8px]`, or other arbitrary sizes — use the scale above.
- **No** non-mono font for any number, even inline in a sentence.

---

## 4. Component Stylings

### 4.1 Card

The base surface container for all dashboard panels.

```
bg-[var(--panel)]
border border-[var(--border)]
rounded-sm
shadow-lg shadow-black/40
```

- Header: `py-2.5 px-3`, title in `text-xs uppercase tracking-wider font-semibold text-[var(--muted-foreground)]`
- Content: `p-3`
- Never use `rounded-md` or larger on cards.

### 4.2 Buttons

Five semantic variants (defined in `src/components/ui/button.tsx`):

| Variant | When to Use | Visual |
|---------|-------------|--------|
| `default` | Primary CTAs, strategy actions | Kraken purple fill, glow shadow |
| `outline` | Secondary actions, cancel | Purple border, transparent fill |
| `ghost` | Tertiary, icon-only buttons | No border, hover bg only |
| `success` | BUY orders, LONG entries | Neon green fill + glow |
| `destructive` | SELL orders, SHORT entries, HALT | Neon red fill + glow |

Rules:
- Always `rounded-sm` — never `rounded` or `rounded-md`
- `uppercase tracking-wider font-bold` for trade execution buttons
- Icon-only buttons: use `ghost` variant with `p-1.5`

### 4.3 Badges

Five semantic variants (defined in `src/components/ui/badge.tsx`):

| Variant | Color | Use |
|---------|-------|-----|
| `default` | Purple | General system status |
| `success` | Neon green | Active, running, LONG, profitable |
| `destructive` | Neon red | Halted, SELL, SHORT, loss |
| `warning` | Amber | Degraded, pending, approaching limit |
| `outline` | Muted | Inactive, neutral, disabled |

| `purple` | Kraken purple | AI/orchestrator actions, learning events |

All badges: `text-xs font-mono uppercase tracking-wider`

### 4.4 Inputs

```
bg-[var(--panel-muted)]
border border-[var(--border)]
rounded-sm
p-2 text-sm
focus:outline-none focus:border-[var(--muted-foreground)]
font-mono tabular-nums   ← for numeric inputs
```

- Never use default browser focus ring — override with `focus:outline-none focus:border-[var(--kraken-purple)]`

### 4.5 Tabs (Navigation)

```
Active tab: text-white + bottom underline bar (h-0.5, bg-[var(--kraken-purple)], glow shadow)
Inactive tab: text-[var(--muted-foreground)] hover:text-[var(--kraken-light)] hover:bg-[var(--panel-muted)]
Tab bar: border-b border-[var(--border)]
```

- Active indicator uses `framer-motion` `layoutId="activeTabUnderline"` for animated slide
- Tab text: `text-xs font-semibold tracking-wide`

### 4.6 Tables

```
Table header: text-xs uppercase tracking-wider text-[var(--muted-foreground)] border-b border-[var(--border)]
Table rows: text-xs font-mono text-[var(--foreground)] border-b border-[var(--border)]/50 hover:bg-[var(--panel-muted)]
Numeric cells: tabular-nums font-mono
```

- Sticky header: `sticky top-0 bg-[var(--panel)] z-10`
- Scrollable body: hidden or 2px scrollbar only

### 4.7 ValueTicker

Defined in `src/components/ui/value-ticker.tsx`. Animated price display with directional flash.

- On price increase: flash `text-[var(--neon-green)]` for 300ms
- On price decrease: flash `text-[var(--neon-red)]` for 300ms
- Steady state: `text-[var(--foreground)]`
- Always: `font-mono tabular-nums`

### 4.7b TanStack Table (BotPerformanceMatrix and sortable data tables)

When a data table requires column sorting, use `@tanstack/react-table` with `getSortedRowModel`.

```tsx
import { useReactTable, getCoreRowModel, getSortedRowModel, flexRender } from '@tanstack/react-table';

// Sort indicator in header cell:
<th onClick={header.column.getToggleSortingHandler()} className="cursor-pointer select-none">
  {flexRender(header.column.columnDef.header, header.getContext())}
  {{ asc: ' ▲', desc: ' ▼' }[header.column.getIsSorted() as string] ?? ''}
</th>
```

Rules:

- Do NOT add `ArrowUpDown` icons to column headers that are not wired to actual sorting — it creates false affordance.
- Table wrapper: `overflow-hidden` when row count ≤ 10; add `overflow-y-auto` only when row count > 10.
- Sticky header: `sticky top-0 bg-[var(--panel-muted)] z-10`

### 4.8 Scrollbars

All scrollable containers must use exactly:
```css
::-webkit-scrollbar { width: 2px; height: 2px; }
::-webkit-scrollbar-track { background: transparent; }
::-webkit-scrollbar-thumb { background: var(--panel-muted); }
::-webkit-scrollbar-thumb:hover { background: var(--kraken-purple); }
```

Global default in `globals.css`. Do not override to wider widths in components.

### 4.9 EmptyState Component

All empty/awaiting-data states must use the shared `src/components/ui/empty-state.tsx` component. Do not create bespoke inline empty divs per-component.

```tsx
<EmptyState
  icon={<Activity className="w-6 h-6" />}
  title="Awaiting Execution Data"
  subtitle="Empty states appear here until the strategy engine connects"
/>
```

Visual rules:

- Icon: `opacity-20`, `text-[var(--muted-foreground)]`
- Title: `text-xs font-mono uppercase tracking-widest text-[var(--muted-foreground)] opacity-50`
- Subtitle: `text-xs text-[var(--muted-foreground)] opacity-30` (optional)
- Container: `flex flex-col items-center justify-center gap-2 h-full`

### 4.10 KpiCard Component

The standard KPI metric cell used in GlobalKPIs, TradeLedger, and AnalyticsDashboard. Defined in `src/components/ui/kpi-card.tsx`.

```tsx
<KpiCard label="Sharpe Ratio" value="1.84" colorClass="text-[var(--neon-green)]" />
```

Layout: `flex flex-col bg-[var(--panel)] border border-[var(--border)] rounded-sm p-2.5 gap-1`

- Label: `text-xs text-[var(--muted-foreground)] uppercase tracking-wider`
- Value: `text-sm font-bold font-mono tabular-nums` + semantic color class

---

## 5. Layout Principles

### Grid System
- Outer padding: `p-4` on the main viewport
- Internal component gaps: `gap-1` (4px) or `gap-2` (8px) — never `gap-3` or larger inside panels
- Sidebar width: fixed `w-48` to `w-56`
- Panels fill remaining flex/grid space with `flex-1` or `col-span-N`

### Spacing Scale (inner panels)
- Section padding: `p-3`
- Row gaps: `space-y-2` or `space-y-1`
- Label-value pairs: `flex justify-between` with `text-xs`

### Density Rules
- Minimize dead space — a header `py-2.5`, not `py-4`
- Card content `p-3`, not `p-6`
- Table rows `py-2`, not `py-3`

### Navigation
- Single-page tab architecture — all views render inside one route
- Tab bar lives in the header — never in the main content area
- Max 6 tabs; each labeled with icon + short label
- Asset class selector (EQUITY / OPTIONS / CRYPTO) in header, left of tabs

### Responsive Behavior
| Breakpoint | Behavior |
|-----------|---------|
| `< md` (< 768px) | Sidebar collapses, single column layout, tabs scroll horizontally |
| `md` (768px) | 2-column grid for desk view |
| `lg` (1024px+) | Full multi-panel grid, global KPIs visible in header |

- Mobile: hide `hidden lg:flex` elements in header (active symbol display)
- Touch targets: minimum `h-8` for interactive elements
- Horizontal scroll on tab nav: `overflow-x-auto scrollbar-hide`

---

## 6. Charting Guidelines

### 6.1 Library Roles

| Library                   | Use Case                                                                                                        |
|---------------------------|-----------------------------------------------------------------------------------------------------------------|
| `lightweight-charts` (v5) | Real-time OHLCV price charts, equity curves, drawdown panes — time axis, crosshair, live streaming tick updates |
| `recharts`                | Statistical analytics — histograms, scatter plots, donut/pie attribution, cumulative line charts                |

Never mix both libraries on the same data series. Recharts for analytics; lightweight-charts for price action.

### 6.2 Recharts — Critical Container Rule (width(-1) fix)

`ResponsiveContainer` measures its parent's `offsetHeight`. If the parent's height is resolved via `flex-1` alone (without a committed pixel height in the flex chain), it reports `-1` and the chart renders blank.

**Required pattern:**

```tsx
{/* Explicit pixel height on the direct parent div */}
<div style={{ height: 260 }}>
  <ResponsiveContainer width="100%" height="100%" minWidth={0} minHeight={0}>
    <AreaChart ...>
```

Never rely solely on `flex-1` for chart container height. Always set `style={{ height: 'Xpx' }}` on the immediate wrapper `div`.

### 6.3 lightweight-charts (v5) — React Integration Pattern

Follow the pattern established in `src/components/dashboard/market-overview.tsx`:

```tsx
const containerRef = React.useRef<HTMLDivElement>(null);
const chartRef = React.useRef<IChartApi | null>(null);

React.useEffect(() => {
  const el = containerRef.current;
  if (!el || data.length === 0) return;
  chartRef.current?.remove();

  const chart = createChart(el, {
    layout: { background: { color: 'transparent' }, textColor: 'hsl(250,10%,65%)', fontSize: 10, fontFamily: 'JetBrains Mono, monospace' },
    grid:   { vertLines: { visible: false }, horzLines: { visible: false } },
    autoSize: true,
  });

  const series = chart.addSeries(AreaSeries, { lineColor: 'var(--neon-green)', ... });
  series.setData(data);
  chart.timeScale().fitContent();
  chartRef.current = chart;

  return () => { chart.remove(); chartRef.current = null; };
}, [data]);

return <div ref={containerRef} style={{ height: 280 }} />;
```

Key rules:

- Always call `chart.remove()` in the cleanup function.
- Use `autoSize: true` — do not set explicit `width`/`height` in chart options.
- The container `div` must have an explicit `style={{ height: 'Xpx' }}`.
- Time values must be Unix seconds (`Math.floor(ms / 1000) as Time`), not milliseconds.

### 6.4 Dual-Pane Chart (EquityCurveTerminal)

For the Analytics equity curve with a synced drawdown pane, create two separate `lightweight-charts` instances and sync crosshairs manually:

```tsx
chart1.subscribeCrosshairMove(param => {
  if (param.time) chart2.setCrosshairPosition(param.point?.x ?? 0, param.point?.y ?? 0, series2);
  else chart2.clearCrosshairPosition();
});
```

Pane proportions: top equity pane `65%` height, bottom drawdown pane `35%`. Both in a `flex-col` wrapper with explicit total height.

### 6.5 Chart Color Tokens

Always use HSL values (not CSS var references) inside `lightweight-charts` options, since the chart renders to a canvas and cannot read CSS variables:

| Semantic      | Value to use                              |
|---------------|-------------------------------------------|
| Equity up     | `hsl(150, 80%, 45%)` (neon-green)         |
| Equity down   | `hsl(350, 80%, 60%)` (neon-red)           |
| Benchmark     | `hsl(264, 80%, 65%)` (kraken-purple)      |
| Drawdown fill | `hsla(350, 80%, 60%, 0.25)`               |
| Grid / axis   | `hsla(255, 40%, 40%, 0.15)` (border)      |
| Label text    | `hsl(250, 10%, 65%)` (muted-foreground)   |

For recharts, CSS variables work fine in `stroke` and `fill` props since they resolve in the SVG context.

### 6.6 No Inner Scroll on Charts or Short Tables

Charts must never have a scroll container. Tables with 10 or fewer rows must not scroll — use `overflow-hidden` on the table wrapper. Only add `overflow-y-auto` when row count exceeds 10.

---

## 7. Depth & Elevation

### Surface Hierarchy

| Level | Token | Usage |
|-------|-------|-------|
| 0 — Page | `--background` `hsl(255,30%,6%)` | App shell background |
| 1 — Panel | `--panel` `hsl(255,20%,10%)` | Cards, header bar, sidebars |
| 2 — Inset | `--panel-muted` `hsl(255,15%,15%)` | Nested inputs, active toggles, hover rows |
| 3 — Floating | `--panel` + `shadow-xl shadow-black/60` | Modals, popovers, chat overlay |

### Shadow Scale

| Context | Shadow |
|---------|--------|
| Card default | `shadow-lg shadow-black/40` |
| Floating overlay (chat, modal) | `shadow-xl shadow-black/60` |
| Brand/accent glow | `shadow-[0_0_10px_rgba(139,92,246,0.6)]` (purple) |
| Green glow (BUY button) | `shadow-[0_0_8px_rgba(74,222,128,0.4)]` |
| Red glow (SELL button) | `shadow-[0_0_8px_rgba(248,113,113,0.4)]` |

### Borders
- Default: `border border-[var(--border)]` — translucent purple at 15% opacity
- Accent border: `border border-[var(--kraken-purple)]/30` — used for KPI highlight boxes
- No `divide-*` utilities — use explicit `border-b border-[var(--border)]` on rows

---

## 7. Do's and Don'ts

### DO

- Use `rounded-sm` (2px) as the maximum corner radius everywhere.
- Apply `tabular-nums font-mono` to every price, size, percentage, and timestamp.
- Use CSS variable tokens for every color — no raw hex or raw Tailwind palette names in component files.
- Use `gap-1` or `gap-2` inside panels; `p-3` for card content padding.
- Use framer-motion for tab transitions and micro-interactions (opacity + Y offset).
- Show `SYNCING...` or a loading skeleton when data is not yet available.
- Use the `useEffect(() => setMounted(true), [])` pattern for any value that differs between server and client render (clocks, random seeds, live prices).
- Scroll containers get `overflow-y-auto` + 2px scrollbar only.
- Wrap every recharts `ResponsiveContainer` parent in a `div` with explicit `style={{ height: 'Xpx' }}`.
- Wrap every `lightweight-charts` container `div` with explicit `style={{ height: 'Xpx' }}` and `autoSize: true`.
- Use `@tanstack/react-table` for any table that requires column sorting.
- Use the shared `EmptyState` component for all awaiting-data fallbacks.
- Use the shared `KpiCard` component for all label/value metric cells.
- Centralize all polling intervals (`setInterval`) inside `useTradingEngine()` — never in individual view components.

### DON'T

- **Never** use `rounded`, `rounded-md`, `rounded-lg`, or `rounded-full` for UI containers.
- **Never** use arbitrary border-radius values like `rounded-[6px]`.
- **Never** use arbitrary font sizes like `text-[13px]` or `text-[10px]` — use the type hierarchy scale.
- **Never** use raw hex colors or raw Tailwind palette names (`text-purple-400`, `text-blue-400`, `text-amber-400`) in JSX className strings — define a CSS variable.
- **Never** use `suppressHydrationWarning` as a patch for dynamic content — fix the hydration root cause.
- **Never** render prices or live numbers during SSR without a mount guard.
- **Never** use green/red for generic UI states unrelated to market direction.
- **Never** use `gap-4` or larger inside panel components.
- **Never** add `rounded-full` to badges or status indicators.
- **Never** display raw API error objects — surface user-friendly status text.
- **Never** place a `ResponsiveContainer` inside a flex container that has no committed pixel height in the flex chain.
- **Never** add sort icons (`ArrowUpDown`) to table column headers that are not wired to actual sort handlers.
- **Never** add a `max-h` scroll zone inside an already-scrollable card — it creates double-scroll UX.
- **Never** create per-component `setInterval` timers for API polling — register them in `useTradingEngine()`.

---

## 8. Responsive Behavior

### Breakpoint Strategy

```
Mobile (default):  < 768px   — single column, collapsed sidebar, horizontal scroll tabs
Tablet  (md):      768px+    — 2-col grid appears, sidebar visible at reduced width
Desktop (lg):      1024px+   — full multi-panel grid, header KPIs visible
Wide    (xl):      1280px+   — wider sidebar, more columns in desk grid
```

### Header Behavior
- Logo + brand: always visible
- Asset class selector: visible at `sm`+
- Tab navigation: scrolls horizontally on mobile (`overflow-x-auto`)
- Active symbol badge: `hidden lg:flex`
- LIVE indicator + TOTAL EQUITY: always visible
- System clock: always visible

### Main Grid Collapse
- TradingDesk on mobile: vertical stack, each panel full-width
- Sidebar watchlist: full-width row on mobile, left sidebar on `lg`+
- Performance Metrics: stacked KPI cards on mobile, 3-col grid on `lg`+

### Touch Targets
- All interactive elements: minimum `h-8` (32px) height
- Tab buttons: `py-1.5 px-4` minimum
- Table rows: `py-2` minimum

---

## 9. Agent Prompt Guide

Quick reference for LLMs generating new components or modifying existing ones.

### Color Quick Reference
```
Background:      bg-[var(--background)]
Panel/Card:      bg-[var(--panel)]
Hover/Active:    bg-[var(--panel-muted)]
Border:          border-[var(--border)]
Text:            text-[var(--foreground)]
Text muted:      text-[var(--muted-foreground)]
Purple accent:   text-[var(--kraken-purple)]  /  bg-[var(--kraken-purple)]
Purple light:    text-[var(--kraken-light)]
Green (LONG):    text-[var(--neon-green)]
Red (SHORT):     text-[var(--neon-red)]
```

### New Panel / Card Template
```tsx
<Card className="flex flex-col">
  <CardHeader className="py-2.5 px-3">
    <CardTitle className="text-xs uppercase tracking-wider font-semibold text-[var(--muted-foreground)]">
      PANEL TITLE
    </CardTitle>
  </CardHeader>
  <CardContent className="p-3 space-y-2">
    {/* content */}
  </CardContent>
</Card>
```

### KPI Metric Row Template
```tsx
<div className="flex justify-between text-xs">
  <span className="text-[var(--muted-foreground)]">Label</span>
  <span className="font-mono tabular-nums text-[var(--foreground)]">Value</span>
</div>
```

### Market Direction Value Template
```tsx
<span className={`font-mono tabular-nums text-xs ${value >= 0 ? 'text-[var(--neon-green)]' : 'text-[var(--neon-red)]'}`}>
  {value >= 0 ? '+' : ''}{value.toFixed(2)}%
</span>
```

### Table Row Template
```tsx
<tr className="border-b border-[var(--border)]/50 hover:bg-[var(--panel-muted)] transition-colors">
  <td className="py-2 px-3 text-xs text-[var(--muted-foreground)]">{label}</td>
  <td className="py-2 px-3 text-xs font-mono tabular-nums text-[var(--foreground)]">{value}</td>
</tr>
```

### Hydration-Safe Dynamic Value Template
```tsx
// For any value that differs between SSR and client (clocks, live prices, random seeds)
const [mounted, setMounted] = React.useState(false);
React.useEffect(() => setMounted(true), []);
if (!mounted) return null; // or a static skeleton
```

### Status Badge Usage
```tsx
import { Badge } from "@/components/ui/badge";
<Badge variant="success">ACTIVE</Badge>      // running strategy
<Badge variant="destructive">HALTED</Badge>  // stopped
<Badge variant="warning">DEGRADED</Badge>    // partial failure
<Badge variant="outline">IDLE</Badge>        // not running
<Badge variant="purple">LEARNED</Badge>      // AI/orchestrator action
```

### Recharts Chart Container Template

```tsx
{/* Always use explicit pixel height on the wrapper — never flex-1 alone */}
<div style={{ height: 260 }}>
  <ResponsiveContainer width="100%" height="100%" minWidth={0} minHeight={0}>
    <AreaChart data={data} margin={{ top: 8, right: 8, bottom: 4, left: 48 }}
               style={{ background: 'transparent', fontSize: 11, fontFamily: 'JetBrains Mono, monospace' }}>
      <CartesianGrid strokeDasharray="4 4" stroke="var(--border)" strokeOpacity={0.4} vertical={false} />
      <XAxis tick={{ fill: 'var(--muted-foreground)', fontSize: 10 }} stroke="var(--border)" tickLine={false} axisLine={false} />
      <YAxis tick={{ fill: 'var(--muted-foreground)', fontSize: 10 }} stroke="var(--border)" tickLine={false} axisLine={false} />
      <Tooltip contentStyle={{ background: 'var(--panel)', border: '1px solid var(--border)', borderRadius: 2 }} />
    </AreaChart>
  </ResponsiveContainer>
</div>
```

### Agent Reflection Type Filter Button Template

```tsx
{/* Use CSS variable tokens — never raw Tailwind palette classes */}
<button
  onClick={() => setFilter(type)}
  className={`px-2 py-0.5 text-xs rounded-sm font-mono transition-all ${
    active ? 'text-[var(--agent-observe)] bg-white/10' : 'text-[var(--muted-foreground)] hover:text-[var(--foreground)]'
  }`}
>
  {label}
</button>
```

### TanStack Sortable Table Template

```tsx
import { useReactTable, getCoreRowModel, getSortedRowModel, flexRender,
         createColumnHelper, SortingState } from '@tanstack/react-table';

const [sorting, setSorting] = React.useState<SortingState>([]);
const table = useReactTable({
  data, columns,
  state: { sorting },
  onSortingChange: setSorting,
  getCoreRowModel: getCoreRowModel(),
  getSortedRowModel: getSortedRowModel(),
});

// Header cell with sort indicator:
<th onClick={h.column.getToggleSortingHandler()} className="cursor-pointer select-none text-left p-2 text-xs uppercase tracking-wider text-[var(--muted-foreground)]">
  {flexRender(h.column.columnDef.header, h.getContext())}
  {({ asc: ' ▲', desc: ' ▼' } as Record<string, string>)[h.column.getIsSorted() as string] ?? ''}
</th>
```
