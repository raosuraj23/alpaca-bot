# Alpaca X — Design System

> Quant terminal aesthetic. Kraken-dark surfaces, void-purple primary, neon market semantics. Bloomberg-density information surface — every pixel earns its place.

---

## 1. Design Principles

1. **Density is dignity.** Quants want to see everything. Sparse dashboards are insulting; pack information without crowding.
2. **Color is meaning, not decoration.** Green/red are reserved for P&L direction. Purple is the system's voice (agents, brand, focus). Yellow/amber is alert. Cyan is data discovery.
3. **Every surface is actionable.** No purely informational panels — show a finding, give the user a way to act on it.
4. **Typography is the chart.** Tabular figures align numbers; the eye scans columns of mono digits faster than any visualization.
5. **Glow is grammar.** Subtle bloom marks live state, active focus, and risk severity. It's tunable per-user (`muted` / `standard` / `charged`).

---

## 2. Color Tokens

All colors live in `:root` in `styles.css`. Use the CSS variable, never the literal value, so density / accent tweaks can recompose the system.

### 2.1 Surfaces

| Token | Value | Usage |
|---|---|---|
| `--background` | `hsl(255 30% 6%)` | Page background — deepest layer |
| `--panel` | `hsl(255 20% 10%)` | Card / table / dialog background |
| `--panel-muted` | `hsl(255 15% 15%)` | Inset rows, progress tracks, muted chips |
| `--panel-elevated` | `hsl(255 18% 12%)` | Header, sticky chrome, modals |
| `--border` | `hsla(255 40% 40% / 0.15)` | Default 1px divider |
| `--border-strong` | `hsla(255 40% 50% / 0.28)` | Section divider, focus ring base |

### 2.2 Foreground

| Token | Value | Usage |
|---|---|---|
| `--foreground` | `hsl(210 20% 95%)` | Body text |
| `--muted-foreground` | `hsl(250 10% 65%)` | Secondary text, captions |
| `--dim-foreground` | `hsl(250 8% 45%)` | Tertiary, axis ticks, disabled |

### 2.3 Brand · Void Purple

| Token | Value | Usage |
|---|---|---|
| `--kraken-purple` | `hsl(264 80% 65%)` | Primary CTAs, brand mark, agent stream highlight |
| `--kraken-light` | `hsl(264 80% 75%)` | Active states, links, secondary brand |
| `--kraken-deep` | `hsl(264 80% 45%)` | Pressed states, deep accents |
| `--kraken-purple-soft` | `hsla(264 80% 65% / 0.12)` | Selected-row tint, focus surface |

### 2.4 Market Semantics

| Token | Value | Usage |
|---|---|---|
| `--neon-green` | `hsl(150 80% 45%)` | Positive P&L, BUY, gains, healthy gates |
| `--neon-red` | `hsl(350 80% 60%)` | Negative P&L, SELL, losses, breached gates |
| `--neon-green-soft` | `hsla(150 80% 45% / 0.12)` | Long-position row tint |
| `--neon-red-soft` | `hsla(350 80% 60% / 0.12)` | Short-position row tint, critical alert bg |

### 2.5 Agent Type Palette

Each pipeline stage / agent role has a fixed hue. Never re-color these.

| Token | Stage | Value |
|---|---|---|
| `--agent-scanner` | Scan | `hsl(190 70% 60%)` (cyan) |
| `--agent-research` | Research | `hsl(168 65% 55%)` (teal) |
| `--agent-calculate` | Predict | `hsl(220 70% 65%)` (blue) |
| `--agent-risk` | Risk | `hsl(350 70% 60%)` (red) |
| `--agent-execute` | Execute | `hsl(14 82% 62%)` (orange) |
| `--agent-director` | Orchestrator | `hsl(264 80% 75%)` (purple-light) |
| `--agent-learning` | Reflection / warning | `hsl(40 80% 60%)` (amber) |
| `--agent-observe` | Passive observation | `hsl(270 60% 65%)` |

---

## 3. Typography

### 3.1 Font Stacks

```css
--font-sans: 'Inter', -apple-system, BlinkMacSystemFont, 'Segoe UI', sans-serif;
--font-mono: 'JetBrains Mono', ui-monospace, 'SF Mono', Menlo, monospace;
```

**Rule:** Every number is mono with `font-variant-numeric: tabular-nums`. Use the `.mono.tabular` utility classes.

### 3.2 Type Scale

| Class | Size | Line | Weight | Usage |
|---|---|---|---|---|
| `.tiny` | 10px | 1.4 | 400/600 | Captions, axis labels, badges |
| `.small` | 11px | 1.4 | 400/600 | Table cells, body labels |
| (default) | 13px | 1.45 | 400 | Card body, paragraph copy |
| `.card-title` | 11px | 1.2 | 700 | Card headers (uppercase, tracked) |
| `.kpi-value` | 16–22px | 1.1 | 700 | KPI strip values (mono, tabular) |
| `.kpi-label` | 9px | 1.2 | 500 | KPI labels (uppercase, tracked) |

Letter-spacing for uppercase eyebrow labels: `0.08em` to `0.12em`.

### 3.3 Utility Classes

```
.mono / .tabular / .uc / .bold / .semibold
.dim / .muted / .green / .red
```

---

## 4. Spacing & Layout

### 4.1 Spacing Scale

Density-aware. Multiply the base by `var(--density)` (0.75 / 1.0 / 1.15).

| Token | Standard |
|---|---|
| `--pad-xs` | 4px |
| `--pad-sm` | 8px |
| `--pad-md` | 12px |
| `--pad-lg` | 16px |

### 4.2 Grid Gaps

- **Page-level grid gap:** `10px`
- **Inside cards / panels:** `8–12px`
- **Inline element gap (chips, KPI cells):** `6–8px`

Cards never paint their own outer margin — they sit in a flex/grid that owns gap.

### 4.3 Card Radius

Almost flat: `border-radius: 2px`. Never softer. The terminal aesthetic depends on hard edges.

---

## 5. Components

### 5.1 Card

```jsx
<Card title="Equity Curve · 90D" icon="◉" right={<Badge>+8.2%</Badge>} flush>
  …content…
</Card>
```

- `flush` — remove the inner content padding (used when the body is a table or list of full-bleed rows).
- Header is 36px tall, `border-bottom: 1px solid var(--border)`.
- Title: uppercase `.card-title`, optional leading symbol icon (1ch, brand-purple).
- `right` slot is right-aligned in the header.

### 5.2 Badge

Variants: `success` (green), `destructive` (red), `warning` (amber), `outline` (purple-light), `purple` (filled brand).

Padding `2px 6px`, mono, uppercase, tracked.

### 5.3 KPI Cell

```
┌────────────────────────┐
│ LABEL · 9px uc tracked │
│ VALUE · 16–22px mono   │
│ subtitle · 10px dim    │
└────────────────────────┘
```

Used in horizontal strips at the top of every tab. Always `display: grid` with explicit columns.

### 5.4 Buttons

| Variant | Bg | Border | Text |
|---|---|---|---|
| `btn` | `--kraken-purple` | same | `#fff` |
| `btn-outline` | transparent | `--border-strong` | `--foreground` |
| `btn-destructive` | `--neon-red` | same | `#fff` |
| `btn-ghost` | transparent | none | `--muted-foreground` |

Sizes: `btn-sm` (24px h, 11px), default (32px h, 12px). Always `border-radius: 2px`.

### 5.5 Table

- Header: `background: var(--panel)`, sticky when scrollable, 9px uc tracked labels.
- Row border: `1px solid hsla(255 40% 40% / 0.08)`.
- Numeric cells: `text-align: right`, `mono.tabular`.
- Min row height: 28px (compact) / 32px (standard) / 36px (comfortable).

### 5.6 Sparkline

- Default: 1.4px stroke, optional area fill at `0.18` opacity.
- Color is semantic (green up, red down, purple neutral).
- No grid lines, no axes — these are micro-charts, not analytics.

### 5.7 Status Dot

`6×6px` square (not circle), border-radius 1px. `.animate-live` for breathing pulse.

---

## 6. Motion

| Transition | Duration | Easing |
|---|---|---|
| Hover state | `120ms` | `ease-out` |
| Tab / panel swap | `200ms` | `ease` |
| Sparkline / bar value change | `400ms` | `ease` |
| Glow pulse (`.animate-live`) | `1.6s` | infinite ease-in-out |
| Ticker price flash | `600ms` | once, then fade |

No bounces, no spring physics. This is a tool, not a toy.

---

## 7. Patterns

### 7.1 Action Queue

Every tab that exposes findings should follow this row pattern (see `analysis.jsx`):

```
[ Severity · 76px ][ Finding + Impact + Recommendation · 1fr ][ Evidence · 110px ][ Primary + Secondary CTAs · 200px ]
```

- Severity colors map: `critical → --neon-red`, `warning → --agent-learning`, `info → --kraken-light`.
- Critical rows get a `rgba(239,68,68,0.04)` row tint and a 2px left border in severity color.
- Primary CTA fills with severity color; secondary is `btn-outline`.

### 7.2 Decision Trace

The **Brain tab** uses a vertical 5-stage rail (numbered 1–5, each colored by `--agent-*` token), with each stage exposing:

1. **What it saw** (input)
2. **What it concluded** (output + confidence bar)
3. **Status glyph** (`✓` pass, `⊘` block, `—` skip)

Confidence is always a 4px-tall bar with a `box-shadow: inset 0 0 4px <color>` glow — this is the system's universal "model probability" visual.

### 7.3 Pipeline Ribbon

The 5-step Scan→Research→Predict→Risk→Execute ribbon at the top of the Desk uses agent-token colors with a baton-passing animation: the active stage glows at full strength; adjacent stages glow at 0.3; rest are flat. Connector arrows shift opacity.

### 7.4 Live State

Anything that updates in real time gets:
- A `.animate-live` pulse dot in the upper-right of its container, OR
- A directional flash on value change (green if up, red if down, 600ms decay).

Never both — pick one per surface.

---

## 8. Tweaks (User-Customizable)

The Tweaks panel exposes:

| Tweak | Options | Effect |
|---|---|---|
| `density` | compact / standard / comfortable | Sets `--density` 0.75 / 1.0 / 1.15 |
| `accent` | muted / standard / charged | Sets `--glow-strength` 0.4 / 1.0 / 1.6 |
| `layoutMode` | three_col / split | Desk middle-row layout |
| `showPipeline` | bool | Toggles the agent pipeline ribbon |
| `tickRate` | 200–2000ms | Live ticker simulator interval |

State persists via the `__edit_mode_set_keys` postMessage protocol; defaults wrapped in `EDITMODE-BEGIN/END` markers in `app.jsx`.

---

## 9. File Structure

```
Alpaca X.html       — entry, script tags, font preconnects
styles.css          — tokens, base styles, utility classes, responsive rules
data.js             — synthetic tickers, bots, executions, reflections
primitives.jsx      — Card, Badge, Button, KPI, StatusDot, Sparkline, ValueTicker, fmt*
pipeline.jsx        — AgentPipeline ribbon, KPIStrip header
desk-components.jsx — Watchlist, MarketOverview, ExecutionLog, PositionsTable, AiInsights, BotControl
brain.jsx           — Brain tab (Decision Stream + 5-stage Trace + Calibration + RAG memory + Live Cognition)
analysis.jsx       — Analysis tab (KPIs + Equity/DD + Risk Radar + LLM Cost + Action Queue + Bot matrix)
tabs.jsx            — LedgerTab, BotsTab, TestsTab
tweaks-panel.jsx    — Tweaks chrome + control primitives
app.jsx             — App root, Header, OrchChat, DeskTab, tab routing
```

Each tab file exports its component(s) via `Object.assign(window, { … })` so they're available across `<script type="text/babel">` scopes.

---

## 10. Accessibility & Copy

- Minimum body text size: 11px (only for tabular numbers and table headers; never running prose).
- Focus ring: 2px solid `--kraken-purple` with 2px offset, never removed.
- Status colors must always be paired with a glyph or label — don't rely on color alone for severity.
- Copy voice: declarative, technical, terse. Numbers first, prose second. Never use exclamation points. Use the Oxford comma. Lowercase eyebrow labels become uppercase via CSS.

---

*Last updated: integrated with Alpaca X v2 (Brain tab redesign + Analysis Action Queue).*
