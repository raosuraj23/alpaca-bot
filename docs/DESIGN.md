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

### Usage Rules
- **Never use raw hex/RGB** — always reference CSS variable tokens.
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

### 4.8 Scrollbars

All scrollable containers must use exactly:
```css
::-webkit-scrollbar { width: 2px; height: 2px; }
::-webkit-scrollbar-track { background: transparent; }
::-webkit-scrollbar-thumb { background: var(--panel-muted); }
::-webkit-scrollbar-thumb:hover { background: var(--kraken-purple); }
```

Global default in `globals.css`. Do not override to wider widths in components.

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

## 6. Depth & Elevation

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
- Use CSS variable tokens for every color — no raw hex in component files.
- Use `gap-1` or `gap-2` inside panels; `p-3` for card content padding.
- Use framer-motion for tab transitions and micro-interactions (opacity + Y offset).
- Show `SYNCING...` or a loading skeleton when data is not yet available.
- Use the `useEffect(() => setMounted(true), [])` pattern for any value that differs between server and client render (clocks, random seeds, live prices).
- Scroll containers get `overflow-y-auto` + 2px scrollbar only.

### DON'T
- **Never** use `rounded`, `rounded-md`, `rounded-lg`, or `rounded-full` for UI containers.
- **Never** use arbitrary border-radius values like `rounded-[6px]`.
- **Never** use arbitrary font sizes like `text-[13px]` — use the type hierarchy scale.
- **Never** use raw hex colors in JSX className strings.
- **Never** use `suppressHydrationWarning` as a patch for dynamic content — fix the hydration root cause.
- **Never** render prices or live numbers during SSR without a mount guard.
- **Never** use green/red for generic UI states unrelated to market direction.
- **Never** use `gap-4` or larger inside panel components.
- **Never** add `rounded-full` to badges or status indicators.
- **Never** display raw API error objects — surface user-friendly status text.

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
<Badge variant="success">ACTIVE</Badge>   // running strategy
<Badge variant="destructive">HALTED</Badge> // stopped
<Badge variant="warning">DEGRADED</Badge>  // partial failure
<Badge variant="outline">IDLE</Badge>      // not running
```
