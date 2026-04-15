"use client"

import * as React from 'react';
import { Card, CardHeader, CardTitle, CardContent } from "@/components/ui/card";
import { BarChart3, PieChart, ShieldAlert, TrendingUp, TrendingDown, Activity } from 'lucide-react';
import { ResponsiveLine } from '@nivo/line';
import { useTradingStore } from '@/hooks/useTradingStream';

// ---------------------------------------------------------------------------
// PnL Calendar Heatmap — drill-down: Day / Week / Month / Year
// ---------------------------------------------------------------------------

type CalendarView = 'day' | 'week' | 'month' | 'year';

const DAY_NAMES  = ['Sun', 'Mon', 'Tue', 'Wed', 'Thu', 'Fri', 'Sat'];
const MONTH_NAMES = ['Jan','Feb','Mar','Apr','May','Jun','Jul','Aug','Sep','Oct','Nov','Dec'];

function cellColor(pnl: number | null, max: number): string {
  if (pnl === null) return 'hsla(255,15%,15%,0.8)';
  if (pnl === 0)    return 'hsla(250,10%,20%,0.8)';
  const intensity = Math.min(Math.abs(pnl) / (max || 1), 1);
  if (pnl > 0) return `hsla(150,${60 + intensity * 20}%,${20 + intensity * 18}%,1)`;
  return `hsla(350,${55 + intensity * 25}%,${22 + intensity * 18}%,1)`;
}

function PnLCalendar({ history }: { history: [number, number][] }) {
  const [view, setView] = React.useState<CalendarView>('month');

  // Build daily PnL map: localDateKey → pnl
  const dailyPnl = React.useMemo(() => {
    const map = new Map<string, number>();
    if (!history || history.length < 2) return map;
    for (let i = 1; i < history.length; i++) {
      const pnl  = (history[i][1] ?? 0) - (history[i - 1][1] ?? 0);
      const date = new Date(history[i][0]);
      const key  = `${date.getFullYear()}-${String(date.getMonth() + 1).padStart(2,'0')}-${String(date.getDate()).padStart(2,'0')}`;
      map.set(key, (map.get(key) ?? 0) + pnl);
    }
    return map;
  }, [history]);

  // Build hourly PnL map for day view
  const hourlyPnl = React.useMemo(() => {
    const map = new Map<string, number>(); // key: YYYY-MM-DD-HH
    if (!history || history.length < 2) return map;
    for (let i = 1; i < history.length; i++) {
      const pnl  = (history[i][1] ?? 0) - (history[i - 1][1] ?? 0);
      const date = new Date(history[i][0]);
      const key  = `${date.getFullYear()}-${String(date.getMonth()+1).padStart(2,'0')}-${String(date.getDate()).padStart(2,'0')}-${String(date.getHours()).padStart(2,'0')}`;
      map.set(key, (map.get(key) ?? 0) + pnl);
    }
    return map;
  }, [history]);

  const today = React.useMemo(() => new Date(), []);

  // ── DAY VIEW: 24 hourly bars for today ────────────────────────────────────
  const dayCells = React.useMemo(() => {
    const datePrefix = `${today.getFullYear()}-${String(today.getMonth()+1).padStart(2,'0')}-${String(today.getDate()).padStart(2,'0')}`;
    return Array.from({ length: 24 }, (_, h) => {
      const key = `${datePrefix}-${String(h).padStart(2,'0')}`;
      return { hour: h, pnl: hourlyPnl.get(key) ?? null };
    });
  }, [hourlyPnl, today]);

  // ── WEEK VIEW: last 7 days ────────────────────────────────────────────────
  const weekCells = React.useMemo(() => {
    return Array.from({ length: 7 }, (_, i) => {
      const d = new Date(today);
      d.setDate(today.getDate() - 6 + i);
      const key = `${d.getFullYear()}-${String(d.getMonth()+1).padStart(2,'0')}-${String(d.getDate()).padStart(2,'0')}`;
      return { date: d, key, pnl: dailyPnl.get(key) ?? null };
    });
  }, [dailyPnl, today]);

  // ── MONTH VIEW: calendar grid for current month ───────────────────────────
  const monthCells = React.useMemo(() => {
    const year  = today.getFullYear();
    const month = today.getMonth();
    const firstDay    = new Date(year, month, 1).getDay(); // 0=Sun
    const daysInMonth = new Date(year, month + 1, 0).getDate();
    const cells: { date: Date | null; key: string; pnl: number | null }[] = [];
    // leading blanks
    for (let i = 0; i < firstDay; i++) cells.push({ date: null, key: `blank-${i}`, pnl: null });
    for (let d = 1; d <= daysInMonth; d++) {
      const date = new Date(year, month, d);
      const key  = `${year}-${String(month+1).padStart(2,'0')}-${String(d).padStart(2,'0')}`;
      cells.push({ date, key, pnl: dailyPnl.get(key) ?? null });
    }
    return cells;
  }, [dailyPnl, today]);

  // ── YEAR VIEW: 12-month aggregates ────────────────────────────────────────
  const yearCells = React.useMemo(() => {
    const year = today.getFullYear();
    return Array.from({ length: 12 }, (_, m) => {
      let total = 0;
      const days = new Date(year, m + 1, 0).getDate();
      for (let d = 1; d <= days; d++) {
        const key = `${year}-${String(m+1).padStart(2,'0')}-${String(d).padStart(2,'0')}`;
        total += dailyPnl.get(key) ?? 0;
      }
      return { month: m, pnl: total !== 0 ? total : null };
    });
  }, [dailyPnl, today]);

  const maxAbs = React.useMemo(() => {
    let m = 0.001;
    dailyPnl.forEach(v => { if (Math.abs(v) > m) m = Math.abs(v); });
    return m;
  }, [dailyPnl]);

  const VIEW_LABELS: Record<CalendarView, string> = { day: 'Day', week: 'Week', month: 'Month', year: 'Year' };

  return (
    <div className="flex flex-col gap-3">
      {/* Drill-down selector */}
      <div className="flex items-center gap-1">
        {(['day','week','month','year'] as CalendarView[]).map(v => (
          <button
            key={v}
            onClick={() => setView(v)}
            className={`px-2.5 py-0.5 text-xs font-mono rounded-sm border transition-colors ${
              view === v
                ? 'border-[var(--kraken-purple)] text-[var(--kraken-light)] bg-[var(--kraken-purple)]/20'
                : 'border-[var(--border)] text-[var(--muted-foreground)] hover:border-[var(--kraken-purple)]/40'
            }`}
          >
            {VIEW_LABELS[v]}
          </button>
        ))}
        <span className="ml-auto text-xs font-mono text-[var(--muted-foreground)] opacity-40 tabular-nums">
          {view === 'day'   && today.toLocaleDateString()}
          {view === 'week'  && 'Last 7 days'}
          {view === 'month' && `${MONTH_NAMES[today.getMonth()]} ${today.getFullYear()}`}
          {view === 'year'  && String(today.getFullYear())}
        </span>
      </div>

      {/* ── DAY: 24 hour bars ── */}
      {view === 'day' && (
        <div className="flex gap-1 items-end h-16">
          {dayCells.map(({ hour, pnl }) => {
            const maxH = Math.max(...dayCells.map(c => Math.abs(c.pnl ?? 0)), 0.001);
            const h    = pnl !== null ? Math.max((Math.abs(pnl) / maxH) * 100, 4) : 4;
            return (
              <div key={hour} className="flex-1 flex flex-col items-center group">
                <div
                  className="w-full rounded-t-sm transition-all duration-200 group-hover:brightness-125"
                  style={{ height: `${h}%`, background: cellColor(pnl, maxH) }}
                >
                  <title>{String(hour).padStart(2,'0')}:00{pnl != null ? ` — ${pnl >= 0 ? '+' : ''}$${pnl.toFixed(2)}` : ''}</title>
                </div>
                {hour % 6 === 0 && (
                  <span className="text-xs font-mono text-[var(--muted-foreground)] opacity-40 mt-1">
                    {String(hour).padStart(2,'0')}
                  </span>
                )}
              </div>
            );
          })}
        </div>
      )}

      {/* ── WEEK: 7 day bars with labels ── */}
      {view === 'week' && (
        <div className="flex gap-2 items-end h-20">
          {weekCells.map(({ date, pnl }) => {
            const maxH = Math.max(...weekCells.map(c => Math.abs(c.pnl ?? 0)), 0.001);
            const h    = pnl !== null ? Math.max((Math.abs(pnl) / maxH) * 100, 4) : 6;
            const isToday = date.toDateString() === today.toDateString();
            return (
              <div key={date.toISOString()} className="flex-1 flex flex-col items-center group cursor-default">
                {pnl !== null && (
                  <span className={`text-xs font-mono tabular-nums mb-1 opacity-0 group-hover:opacity-100 transition-opacity ${pnl >= 0 ? 'text-[var(--neon-green)]' : 'text-[var(--neon-red)]'}`}>
                    {pnl >= 0 ? '+' : ''}${pnl.toFixed(2)}
                  </span>
                )}
                <div className="w-full flex-1 flex items-end">
                  <div
                    className={`w-full rounded-t-sm transition-all duration-300 group-hover:brightness-125 ${isToday ? 'ring-1 ring-[var(--kraken-purple)]/40' : ''}`}
                    style={{ height: `${h}%`, background: cellColor(pnl, maxH) }}
                  />
                </div>
                <div className="mt-1.5 text-center">
                  <div className={`text-xs font-mono ${isToday ? 'text-[var(--kraken-light)] font-bold' : 'text-[var(--muted-foreground)] opacity-60'}`}>
                    {DAY_NAMES[date.getDay()]}
                  </div>
                  <div className="text-xs font-mono tabular-nums text-[var(--muted-foreground)] opacity-40">
                    {date.getDate()}
                  </div>
                </div>
              </div>
            );
          })}
        </div>
      )}

      {/* ── MONTH: calendar grid ── */}
      {view === 'month' && (
        <div>
          {/* Day-of-week headers */}
          <div className="grid grid-cols-7 mb-1">
            {DAY_NAMES.map(d => (
              <div key={d} className="text-xs font-mono text-center text-[var(--muted-foreground)] opacity-40 py-0.5">{d}</div>
            ))}
          </div>
          <div className="grid grid-cols-7 gap-0.5">
            {monthCells.map(({ date, key, pnl }) => {
              if (!date) return <div key={key} />;
              const isToday = date.toDateString() === today.toDateString();
              return (
                <div
                  key={key}
                  title={`${date.toLocaleDateString()}${pnl != null ? ` — ${pnl >= 0 ? '+' : ''}$${pnl.toFixed(2)}` : ''}`}
                  className={`aspect-square rounded-sm flex items-center justify-center cursor-default group transition-all hover:scale-110 ${isToday ? 'ring-1 ring-[var(--kraken-purple)]' : ''}`}
                  style={{ background: cellColor(pnl, maxAbs) }}
                >
                  <span className={`text-xs font-mono tabular-nums leading-none ${isToday ? 'text-[var(--kraken-light)] font-bold' : 'text-[var(--foreground)] opacity-60'}`}>
                    {date.getDate()}
                  </span>
                </div>
              );
            })}
          </div>
        </div>
      )}

      {/* ── YEAR: 12 month bars ── */}
      {view === 'year' && (
        <div className="flex gap-2 items-end h-20">
          {yearCells.map(({ month, pnl }) => {
            const maxH = Math.max(...yearCells.map(c => Math.abs(c.pnl ?? 0)), 0.001);
            const h    = pnl !== null ? Math.max((Math.abs(pnl) / maxH) * 100, 4) : 4;
            const isCurrent = month === today.getMonth();
            return (
              <div key={month} className="flex-1 flex flex-col items-center group cursor-default">
                {pnl !== null && (
                  <span className={`text-xs font-mono tabular-nums mb-1 opacity-0 group-hover:opacity-100 transition-opacity ${(pnl ?? 0) >= 0 ? 'text-[var(--neon-green)]' : 'text-[var(--neon-red)]'}`}>
                    {(pnl ?? 0) >= 0 ? '+' : ''}${(pnl ?? 0).toFixed(2)}
                  </span>
                )}
                <div className="w-full flex-1 flex items-end">
                  <div
                    className={`w-full rounded-t-sm transition-all duration-300 group-hover:brightness-125 ${isCurrent ? 'ring-1 ring-[var(--kraken-purple)]/40' : ''}`}
                    style={{ height: `${h}%`, background: cellColor(pnl, maxH) }}
                  />
                </div>
                <div className={`mt-1.5 text-xs font-mono ${isCurrent ? 'text-[var(--kraken-light)] font-bold' : 'text-[var(--muted-foreground)] opacity-50'}`}>
                  {MONTH_NAMES[month]}
                </div>
              </div>
            );
          })}
        </div>
      )}

      {/* Legend */}
      <div className="flex items-center justify-between text-xs font-mono text-[var(--muted-foreground)] opacity-40">
        <span>loss</span>
        <div className="flex items-center gap-0.5">
          {['hsl(350,80%,38%)', 'hsl(350,60%,28%)', 'hsla(255,15%,15%,0.8)', 'hsl(150,65%,25%)', 'hsl(150,80%,33%)'].map((c, i) => (
            <span key={i} style={{ background: c, display: 'inline-block', width: 14, height: 8, borderRadius: 1 }} />
          ))}
        </div>
        <span>profit</span>
      </div>
    </div>
  );
}

// ---------------------------------------------------------------------------
// LLM Cost vs Cumulative PnL — dual-line SVG chart
// ---------------------------------------------------------------------------

interface LLMDailyRow {
  date:     string;
  pnl_usd:  number;
  cost_usd: number;
  ratio:    number | null;
}

interface LLMCostData {
  has_data:          boolean;
  cumulative_cost:   [number, number][];
  cumulative_pnl:    [number, number][];
  daily_rows?:       LLMDailyRow[];
  total_cost_usd?:   number;
  total_pnl_usd?:    number;
  cumulative_ratio?: number | null;
}

function LLMCostChart({ data }: { data: LLMCostData }) {
  const W = 600; const H = 140;
  const PAD = 4;

  if (!data.has_data || (!data.cumulative_cost.length && !data.cumulative_pnl.length)) {
    return (
      <div className="flex flex-col items-center justify-center h-full text-center">
        <BarChart3 className="w-6 h-6 text-[var(--muted-foreground)] opacity-20 mb-2" />
        <div className="text-xs text-[var(--muted-foreground)] opacity-50 uppercase tracking-widest">
          Awaiting LLM Calls
        </div>
      </div>
    );
  }

  const allValues = [
    ...data.cumulative_cost.map(([, v]) => v),
    ...data.cumulative_pnl.map(([, v]) => Math.abs(v)),
  ];
  const maxV = Math.max(...allValues, 0.001);
  const minV = Math.min(...data.cumulative_pnl.map(([, v]) => v), 0);

  const toX = (ts: number, series: [number, number][]) => {
    const allTs = [
      ...data.cumulative_cost.map(([t]) => t),
      ...data.cumulative_pnl.map(([t]) => t),
    ];
    const minTs = Math.min(...allTs);
    const maxTs = Math.max(...allTs);
    return maxTs === minTs ? W / 2 : PAD + ((ts - minTs) / (maxTs - minTs)) * (W - PAD * 2);
  };
  const toY = (v: number) => {
    const range = maxV - minV || 1;
    return H - PAD - ((v - minV) / range) * (H - PAD * 2);
  };

  const costPath = data.cumulative_cost.length > 1
    ? data.cumulative_cost.map(([ts, v], i) =>
        `${i === 0 ? 'M' : 'L'}${toX(ts, data.cumulative_cost).toFixed(1)},${toY(v).toFixed(1)}`
      ).join(' ')
    : null;

  const pnlPath = data.cumulative_pnl.length > 1
    ? data.cumulative_pnl.map(([ts, v], i) =>
        `${i === 0 ? 'M' : 'L'}${toX(ts, data.cumulative_pnl).toFixed(1)},${toY(v).toFixed(1)}`
      ).join(' ')
    : null;

  // Zero line
  const zeroY = toY(0).toFixed(1);

  return (
    <div className="flex flex-col gap-2">
      <svg viewBox={`0 0 ${W} ${H}`} style={{ width: '100%', height: `${H}px` }}>
        {/* Zero line */}
        <line x1={0} y1={zeroY} x2={W} y2={zeroY}
              stroke="var(--border)" strokeWidth="1" strokeDasharray="4,4" />
        {/* PnL line (green/red depending on sign) */}
        {pnlPath && (
          <path d={pnlPath} fill="none"
                stroke="var(--neon-green)" strokeWidth="2"
                strokeLinejoin="round" strokeLinecap="round" />
        )}
        {/* Cost line (red — always negative to portfolio) */}
        {costPath && (
          <path d={costPath} fill="none"
                stroke="var(--neon-red)" strokeWidth="2"
                strokeLinejoin="round" strokeLinecap="round" strokeDasharray="6,3" />
        )}
      </svg>
      {/* Legend */}
      <div className="flex items-center gap-4 text-xs font-mono tabular-nums text-[var(--muted-foreground)]">
        <div className="flex items-center gap-1">
          <span className="inline-block w-6 h-0.5 bg-[var(--neon-green)]" />
          <span>PnL {data.total_pnl_usd !== undefined ? `$${data.total_pnl_usd.toFixed(2)}` : ''}</span>
        </div>
        <div className="flex items-center gap-1">
          <span className="inline-block w-5 border-t-2 border-dashed border-[var(--neon-red)]" />
          <span>LLM Cost ${(data.total_cost_usd ?? 0).toFixed(4)}</span>
        </div>
        {data.cumulative_ratio != null && (
          <div className="ml-auto flex items-center gap-1">
            <span className="text-[var(--muted-foreground)] opacity-60">Efficiency:</span>
            <span className={`font-bold ${data.cumulative_ratio >= 1 ? 'text-[var(--neon-green)]' : 'text-[var(--neon-red)]'}`}>
              {data.cumulative_ratio.toFixed(1)}x
            </span>
          </div>
        )}
      </div>

      {/* Daily breakdown table */}
      {data.daily_rows && data.daily_rows.length > 0 && (
        <div className="mt-2 overflow-y-auto max-h-[120px] rounded-sm border border-[var(--border)]">
          <table className="w-full text-xs tabular-nums font-mono">
            <thead className="sticky top-0 bg-[var(--panel-muted)]">
              <tr className="text-[var(--muted-foreground)] border-b border-[var(--border)]">
                <th className="py-1 px-2 text-left font-medium">Date</th>
                <th className="py-1 px-2 text-right font-medium">Day PnL</th>
                <th className="py-1 px-2 text-right font-medium">LLM Cost</th>
                <th className="py-1 px-2 text-right font-medium">Ratio</th>
              </tr>
            </thead>
            <tbody className="divide-y divide-[var(--border)]/30">
              {[...data.daily_rows].reverse().map(row => (
                <tr key={row.date} className="hover:bg-[var(--panel-muted)] transition-colors">
                  <td className="py-1 px-2 text-[var(--muted-foreground)]">
                    {new Date(row.date + 'T00:00:00').toLocaleDateString()}
                  </td>
                  <td className={`py-1 px-2 text-right ${row.pnl_usd >= 0 ? 'text-[var(--neon-green)]' : 'text-[var(--neon-red)]'}`}>
                    {row.pnl_usd >= 0 ? '+' : ''}${row.pnl_usd.toFixed(2)}
                  </td>
                  <td className="py-1 px-2 text-right text-[var(--muted-foreground)]">
                    ${row.cost_usd.toFixed(4)}
                  </td>
                  <td className={`py-1 px-2 text-right font-bold ${
                    row.ratio == null ? 'text-[var(--muted-foreground)]'
                      : row.ratio >= 1 ? 'text-[var(--neon-green)]'
                      : 'text-[var(--neon-red)]'
                  }`}>
                    {row.ratio != null ? `${row.ratio.toFixed(1)}x` : '—'}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </div>
  );
}

// ---------------------------------------------------------------------------
// Nivo P&L Curve — Robinhood/TradingView style
// ---------------------------------------------------------------------------

function PnLCurve({ history, netPnl }: { history: [number, number][]; netPnl: number }) {
  const isUp = netPnl >= 0;
  const lineColor = isUp ? 'hsl(150,80%,45%)' : 'hsl(350,80%,60%)';

  if (!history || history.length < 2) {
    return (
      <div className="flex flex-col items-center justify-center h-full gap-2">
        <BarChart3 className="w-8 h-8 text-[var(--muted-foreground)] opacity-15" />
        <div className="text-xs text-[var(--muted-foreground)] opacity-50 uppercase tracking-widest">
          Awaiting trade executions
        </div>
      </div>
    );
  }

  // Pass Date objects — Nivo format:'native' requires real Date, not strings.
  // JavaScript Date always displays in local timezone, so UTC→local is automatic.
  const nivoData = [{
    id: 'pnl',
    data: history.map(([ts, val]) => ({
      x: new Date(ts),   // Date object: local time for display
      y: val,
    })),
  }];

  const values = history.map(([, v]) => v);
  const minVal = Math.min(...values);
  const maxVal = Math.max(...values);
  const padding = (maxVal - minVal) * 0.1 || 1;

  const fmtY = (v: number) =>
    v >= 1000 ? `$${(v / 1000).toFixed(1)}k` : v <= -1000 ? `-$${(Math.abs(v) / 1000).toFixed(1)}k` : `$${v.toFixed(0)}`;

  const fmtTime = (d: Date) => {
    if (!(d instanceof Date) || isNaN(d.getTime())) return '';
    return d.toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' });
  };

  return (
    <ResponsiveLine
      data={nivoData}
      margin={{ top: 10, right: 16, bottom: 28, left: 56 }}
      xScale={{ type: 'time', format: 'native', precision: 'minute' }}
      yScale={{ type: 'linear', min: minVal - padding, max: maxVal + padding }}
      axisBottom={{
        tickValues: 5,
        tickSize: 0,
        tickPadding: 6,
        format: (v: Date) => fmtTime(v),
      }}
      axisLeft={{
        tickSize: 0,
        tickPadding: 8,
        tickValues: 4,
        format: (v: number) => fmtY(v),
      }}
      enableGridX={false}
      gridYValues={4}
      theme={{
        axis: {
          ticks: { text: { fill: 'hsla(250,10%,65%,0.6)', fontSize: 9, fontFamily: 'monospace' } },
        },
        grid: { line: { stroke: 'hsla(255,40%,40%,0.10)', strokeWidth: 1 } },
        crosshair: { line: { stroke: 'hsla(255,40%,70%,0.4)', strokeWidth: 1, strokeDasharray: '4 4' } },
        tooltip: {
          container: {
            background: 'hsl(255,20%,10%)',
            border: '1px solid hsla(255,40%,40%,0.3)',
            borderRadius: 2,
            padding: '4px 8px',
            fontSize: 11,
            fontFamily: 'monospace',
            color: 'hsl(210,20%,95%)',
          },
        },
      }}
      colors={[lineColor]}
      lineWidth={2}
      enablePoints={false}
      enableArea={true}
      areaOpacity={0.12}
      useMesh={true}
      crosshairType="x"
      tooltip={({ point }) => {
        const d = point.data.x as Date;
        const localTime = d instanceof Date && !isNaN(d.getTime())
          ? d.toLocaleString()
          : String(point.data.xFormatted);
        return (
          <div className="text-xs font-mono tabular-nums">
            <span className="opacity-60 mr-2">{localTime}</span>
            <span style={{ color: lineColor }} className="font-bold">
              ${Number(point.data.y).toFixed(2)}
            </span>
          </div>
        );
      }}
    />
  );
}

// ---------------------------------------------------------------------------
// Performance Metrics Component
// ---------------------------------------------------------------------------

const PERIODS = ['1D', '1W', '1M', 'YTD'] as const;
type Period = typeof PERIODS[number];

export function PerformanceMetrics() {
  const performance   = useTradingStore(s => s.performance);
  const riskStatus    = useTradingStore(s => s.riskStatus);
  const bots          = useTradingStore(s => s.bots);
  const todayPnl      = useTradingStore(s => s.todayPnl);
  const unrealizedPnl = useTradingStore(s => s.unrealizedPnl);
  const positions     = useTradingStore(s => s.positions);

  const [period, setPeriod] = React.useState<Period>('1M');
  const [perfData, setPerfData] = React.useState(performance);
  const [llmCostData, setLlmCostData] = React.useState<LLMCostData>({
    has_data: false, cumulative_cost: [], cumulative_pnl: [],
  });

  React.useEffect(() => {
    const loadPerf = () =>
      fetch(`http://localhost:8000/api/performance?period=${period}`)
        .then(r => r.ok ? r.json() : null)
        .then(d => { if (d) setPerfData(d); })
        .catch(() => {});
    loadPerf();
    const interval = setInterval(loadPerf, 60_000); // refresh every 60s
    return () => clearInterval(interval);
  }, [period]);

  React.useEffect(() => {
    if (performance.has_data) setPerfData(performance);
  }, [performance]);

  React.useEffect(() => {
    const load = () =>
      fetch(`http://localhost:8000/api/analytics/llm-cost?period=${period}`)
        .then(r => r.ok ? r.json() : null)
        .then(d => { if (d) setLlmCostData(d); })
        .catch(() => {});
    load();
    const interval = setInterval(load, 60_000);
    return () => clearInterval(interval);
  }, [period]);

  const drawdown    = perfData.drawdown ?? riskStatus?.drawdown_pct ?? 0;
  const killActive  = riskStatus?.triggered ?? false;

  // Annualization factor depends on the bar frequency for each period
  // 1D = 1-minute bars (390/day), 1W/1M/YTD = daily bars
  const sharpeAnnFactor = period === '1D' ? Math.sqrt(252 * 390) : Math.sqrt(252);

  const sharpeApprox = React.useMemo(() => {
    if (!perfData.history || perfData.history.length < 5) return null;
    const returns = perfData.history.slice(1).map(([, v]: [number, number], i: number) => {
      const prev = perfData.history[i][1];
      return prev !== 0 ? (v - prev) / prev : 0;
    });
    const mean = returns.reduce((a: number, b: number) => a + b, 0) / returns.length;
    const std = Math.sqrt(returns.reduce((s: number, r: number) => s + (r - mean) ** 2, 0) / returns.length);
    return std > 0 ? (mean / std * sharpeAnnFactor).toFixed(2) : null;
  }, [perfData.history, sharpeAnnFactor]);

  // Compute unrealized P&L total from live positions as fallback when account doesn't supply it
  const positionsUnrealizedPnl = React.useMemo(
    () => positions.reduce((sum, p) => sum + (p.unrealizedPnl ?? 0), 0),
    [positions],
  );
  const liveUnrealized = unrealizedPnl ?? positionsUnrealizedPnl;

  const kpis = [
    {
      label: 'Total Net PnL',
      value: perfData.has_data
        ? (perfData.net_pnl >= 0 ? '+' : '') + `$${perfData.net_pnl.toFixed(2)}`
        : '$0.00',
      sub: `${period} Live`,
      c: (perfData.net_pnl ?? 0) >= 0 ? 'text-[var(--neon-green)]' : 'text-[var(--neon-red)]',
    },
    {
      label: 'Max Drawdown',
      value: `${drawdown.toFixed(3)}%`,
      sub: `Limit: ${riskStatus?.max_drawdown_pct ?? 2}%`,
      c: drawdown >= (riskStatus?.max_drawdown_pct ?? 2) * 0.75
        ? 'text-[var(--neon-red)]'
        : 'text-[var(--foreground)]',
    },
    {
      label: 'Kill Switch',
      value: killActive ? 'TRIGGERED' : 'ARMED',
      sub: killActive ? (riskStatus?.reason ?? 'Active') : 'Monitoring',
      c: killActive ? 'text-[var(--neon-red)] animate-pulse' : 'text-[var(--neon-green)]',
    },
    {
      label: 'Sharpe Ratio',
      value: sharpeApprox ?? (performance.has_data ? 'N/A' : '—'),
      sub: 'Annualised',
      c: 'text-[var(--foreground)]',
    },
    {
      label: 'Unrealized P&L',
      value: liveUnrealized != null
        ? (liveUnrealized >= 0 ? '+' : '') + `$${liveUnrealized.toFixed(2)}`
        : '—',
      sub: `${positions.length} open position${positions.length !== 1 ? 's' : ''}`,
      c: liveUnrealized >= 0 ? 'text-[var(--neon-green)]' : 'text-[var(--neon-red)]',
    },
    {
      label: "Today's P&L",
      value: todayPnl != null
        ? (todayPnl >= 0 ? '+' : '') + `$${todayPnl.toFixed(2)}`
        : '—',
      sub: 'vs. Last Session',
      c: (todayPnl ?? 0) >= 0 ? 'text-[var(--neon-green)]' : 'text-[var(--neon-red)]',
    },
    {
      label: 'PnL / LLM Cost',
      value: llmCostData.cumulative_ratio != null
        ? `${llmCostData.cumulative_ratio.toFixed(1)}x`
        : '—',
      sub: `${period} efficiency ratio`,
      c: (llmCostData.cumulative_ratio ?? 0) >= 1
        ? 'text-[var(--neon-green)]'
        : llmCostData.cumulative_ratio != null
          ? 'text-[var(--neon-red)]'
          : 'text-[var(--muted-foreground)]',
    },
  ];

  return (
    <div className="flex flex-col h-full gap-4 overflow-y-auto pr-2 pb-4">

      {/* Kill Switch Alert Banner */}
      {killActive && (
        <div className="flex items-center gap-3 px-4 py-2.5 rounded-lg border border-[var(--neon-red)]/60 bg-[var(--neon-red)]/10 text-[var(--neon-red)] text-xs font-bold uppercase tracking-widest animate-pulse shrink-0">
          <ShieldAlert className="w-4 h-4 shrink-0" />
          Kill Switch Active — {riskStatus?.reason ?? 'Trading Halted'}
        </div>
      )}

      {/* KPI Grid */}
      <div className="grid grid-cols-2 md:grid-cols-4 lg:grid-cols-7 gap-3 shrink-0">
        {kpis.map((kpi, i) => (
          <Card key={i} className="bg-[var(--panel)]/80">
            <CardContent className="p-3 flex flex-col justify-center text-center sm:text-left">
              <div className="text-xs text-[var(--muted-foreground)] uppercase tracking-wider mb-1 line-clamp-1">
                {kpi.label}
              </div>
              <div className={`text-lg sm:text-xl font-bold font-mono ${kpi.c}`}>
                {kpi.value}
              </div>
              <div className="text-xs text-[var(--muted-foreground)] mt-1 line-clamp-1">
                {kpi.sub}
              </div>
            </CardContent>
          </Card>
        ))}
      </div>

      {/* ── Row 1: P&L Curve — Robinhood/TradingView style ── */}
      <Card className="shrink-0 flex flex-col h-[280px]">
        <CardHeader className="border-b border-[var(--border)] py-2.5 px-4 flex flex-row items-center justify-between shrink-0">
          <div className="flex items-center gap-3">
            {(perfData.net_pnl ?? 0) >= 0
              ? <TrendingUp className="w-4 h-4 text-[var(--neon-green)]" />
              : <TrendingDown className="w-4 h-4 text-[var(--neon-red)]" />
            }
            <div className="flex flex-col">
              <CardTitle className="text-xs tracking-wider uppercase font-semibold text-[var(--muted-foreground)]">
                Net P&amp;L
              </CardTitle>
              <span className={`text-lg font-mono tabular-nums font-bold leading-tight ${(perfData.net_pnl ?? 0) >= 0 ? 'text-[var(--neon-green)]' : 'text-[var(--neon-red)]'}`}>
                {(perfData.net_pnl ?? 0) >= 0 ? '+' : ''}${(perfData.net_pnl ?? 0).toFixed(2)}
              </span>
            </div>
          </div>
          {/* Period selector — drives P&L curve, returns, AND LLM cost */}
          <div className="flex items-center gap-1">
            {PERIODS.map(p => (
              <button
                key={p}
                onClick={() => setPeriod(p)}
                className={`px-2.5 py-1 text-xs font-mono rounded-sm border transition-colors ${
                  period === p
                    ? 'border-[var(--kraken-purple)] text-[var(--kraken-light)] bg-[var(--kraken-purple)]/20'
                    : 'border-[var(--border)] text-[var(--muted-foreground)] hover:border-[var(--kraken-purple)]/40 hover:text-[var(--foreground)]'
                }`}
              >
                {p}
              </button>
            ))}
          </div>
        </CardHeader>
        <CardContent className="flex-1 p-0 bg-[var(--background)]">
          <PnLCurve
            history={perfData.history as [number, number][]}
            netPnl={perfData.net_pnl ?? 0}
          />
        </CardContent>
      </Card>

      {/* ── Row 2: Strategy Attribution + Bot Performance Matrix ── */}
      <div className="grid grid-cols-1 lg:grid-cols-2 gap-4 shrink-0">

        {/* Strategy Attribution — bar width = signal activity; color = yield sign */}
        <Card className="flex flex-col h-[220px]">
          <CardHeader className="border-b border-[var(--border)] py-2.5 px-4 flex flex-row items-center shrink-0">
            <PieChart className="w-4 h-4 text-[var(--kraken-light)] mr-2" />
            <CardTitle className="text-xs uppercase tracking-widest text-[var(--muted-foreground)]">
              Strategy Attribution
            </CardTitle>
          </CardHeader>
          <CardContent className="flex-1 p-3 flex flex-col gap-2.5 overflow-y-auto">
            {bots.length === 0 ? (
              <div className="text-xs text-[var(--muted-foreground)] opacity-50 italic">
                Connecting to strategy engine...
              </div>
            ) : bots.map((bot: any) => {
              // Use signal count for bar width — meaningful even before first sell
              const maxSignals = Math.max(...bots.map((b: any) => b.signalCount ?? 0), 1);
              const barWidth   = ((bot.signalCount ?? 0) / maxSignals) * 100;
              const hasYield   = (bot.yield24h ?? 0) !== 0;
              const isPos      = (bot.yield24h ?? 0) >= 0;
              const fillRate   = (bot.signalCount ?? 0) > 0
                ? Math.round(((bot.fillCount ?? 0) / (bot.signalCount ?? 1)) * 100)
                : null;
              return (
                <div key={bot.id} className="space-y-0.5">
                  <div className="flex justify-between items-center text-xs">
                    <div className="flex items-center gap-1.5 min-w-0">
                      <span className={`w-1.5 h-1.5 rounded-full shrink-0 ${
                        bot.status === 'ACTIVE'
                          ? 'bg-[var(--neon-green)] shadow-[0_0_4px_var(--neon-green)]'
                          : 'bg-[var(--muted-foreground)]'
                      }`} />
                      <span className="font-semibold text-[var(--foreground)] truncate">{bot.name}</span>
                      {bot.assetClass && bot.assetClass !== 'CRYPTO' && (
                        <span className="text-xs text-[var(--muted-foreground)] opacity-40 shrink-0">{bot.assetClass}</span>
                      )}
                    </div>
                    <div className="flex items-center gap-2 font-mono tabular-nums shrink-0 ml-2">
                      <span className="text-[var(--muted-foreground)] opacity-50 text-xs">
                        {bot.signalCount ?? 0}s {fillRate != null ? `· ${fillRate}%` : ''}
                      </span>
                      <span className={`font-bold text-xs ${hasYield ? (isPos ? 'text-[var(--neon-green)]' : 'text-[var(--neon-red)]') : 'text-[var(--muted-foreground)] opacity-40'}`}>
                        {hasYield ? `${isPos ? '+' : ''}$${Math.abs(bot.yield24h ?? 0).toFixed(2)}` : 'no fills'}
                      </span>
                    </div>
                  </div>
                  <div className="h-1 w-full bg-[var(--background)] overflow-hidden rounded-sm">
                    <div
                      className="h-full transition-all duration-700"
                      style={{
                        width: `${Math.max(barWidth, barWidth > 0 ? 3 : 0)}%`,
                        background: bot.status !== 'ACTIVE'
                          ? 'hsla(250,10%,50%,0.3)'
                          : hasYield
                            ? (isPos ? 'var(--neon-green)' : 'var(--neon-red)')
                            : 'var(--kraken-purple)',
                      }}
                    />
                  </div>
                </div>
              );
            })}
          </CardContent>
        </Card>

        {/* Bot Performance Matrix — replaces Slippage Distribution */}
        <Card className="flex flex-col h-[220px]">
          <CardHeader className="border-b border-[var(--border)] py-2.5 px-4 flex flex-row items-center shrink-0">
            <Activity className="w-4 h-4 text-[var(--kraken-light)] mr-2" />
            <CardTitle className="text-xs uppercase tracking-widest text-[var(--muted-foreground)]">
              Bot Performance Matrix
            </CardTitle>
          </CardHeader>
          <CardContent className="flex-1 overflow-y-auto p-0">
            {bots.length === 0 ? (
              <div className="flex items-center justify-center h-full text-xs text-[var(--muted-foreground)] opacity-40">
                Connecting...
              </div>
            ) : (
              <table className="w-full text-xs tabular-nums font-mono">
                <thead className="sticky top-0 bg-[var(--panel-muted)] text-[var(--muted-foreground)] border-b border-[var(--border)]">
                  <tr>
                    <th className="text-left font-medium p-2 pl-3">Bot</th>
                    <th className="text-center font-medium p-2">Status</th>
                    <th className="text-right font-medium p-2">Signals</th>
                    <th className="text-right font-medium p-2">Fill %</th>
                    <th className="text-right font-medium p-2 pr-3">Yield</th>
                  </tr>
                </thead>
                <tbody className="divide-y divide-[var(--border)]/30">
                  {bots.map((bot: any) => {
                    const fillRate = (bot.signalCount ?? 0) > 0
                      ? ((bot.fillCount ?? 0) / (bot.signalCount ?? 1) * 100).toFixed(0)
                      : '—';
                    const yield24h = bot.yield24h ?? 0;
                    const isPos = yield24h >= 0;
                    return (
                      <tr key={bot.id} className="hover:bg-[var(--panel-muted)] transition-colors">
                        <td className="p-2 pl-3 font-sans font-semibold text-[var(--foreground)] truncate max-w-[100px]">
                          {bot.name}
                        </td>
                        <td className="p-2 text-center">
                          <span className={`inline-flex items-center gap-1 text-xs font-sans ${
                            bot.status === 'ACTIVE' ? 'text-[var(--neon-green)]' : 'text-[var(--muted-foreground)]'
                          }`}>
                            <span className={`w-1 h-1 rounded-full ${
                              bot.status === 'ACTIVE' ? 'bg-[var(--neon-green)]' : 'bg-[var(--muted-foreground)]'
                            }`} />
                            {bot.status === 'ACTIVE' ? 'ON' : 'OFF'}
                          </span>
                        </td>
                        <td className="p-2 text-right text-[var(--foreground)]">
                          {(bot.signalCount ?? 0).toLocaleString()}
                        </td>
                        <td className="p-2 text-right text-[var(--foreground)]">
                          {fillRate}{fillRate !== '—' ? '%' : ''}
                        </td>
                        <td className={`p-2 pr-3 text-right font-bold ${
                          yield24h !== 0 ? (isPos ? 'text-[var(--neon-green)]' : 'text-[var(--neon-red)]') : 'text-[var(--muted-foreground)] opacity-40'
                        }`}>
                          {yield24h !== 0 ? `${isPos ? '+' : ''}$${yield24h.toFixed(2)}` : '—'}
                        </td>
                      </tr>
                    );
                  })}
                </tbody>
              </table>
            )}
          </CardContent>
        </Card>
      </div>

      {/* ── Row 3: PnL Calendar + LLM Cost vs PnL ── */}
      <div className="grid grid-cols-1 lg:grid-cols-2 gap-4 shrink-0">

        {/* PnL Calendar Heatmap */}
        <Card className="flex flex-col">
          <CardHeader className="border-b border-[var(--border)] py-2.5 px-4 shrink-0">
            <CardTitle className="text-xs uppercase tracking-widest text-[var(--muted-foreground)]">
              PnL Calendar
            </CardTitle>
          </CardHeader>
          <CardContent className="p-4">
            <PnLCalendar history={perfData.history as [number, number][]} />
          </CardContent>
        </Card>

        {/* LLM Cost vs PnL — period-driven */}
        <Card className="flex flex-col">
          <CardHeader className="border-b border-[var(--border)] py-2.5 px-4 flex flex-row items-center justify-between shrink-0">
            <CardTitle className="text-xs uppercase tracking-widest text-[var(--muted-foreground)]">
              LLM Cost vs PnL
            </CardTitle>
            <div className="flex items-center gap-2 text-xs font-mono tabular-nums">
              {llmCostData.cumulative_ratio != null && (
                <span className={`font-bold ${llmCostData.cumulative_ratio >= 1 ? 'text-[var(--neon-green)]' : 'text-[var(--neon-red)]'}`}>
                  {llmCostData.cumulative_ratio.toFixed(1)}x efficiency
                </span>
              )}
              {llmCostData.has_data && (
                <span className="text-[var(--muted-foreground)] opacity-60">
                  ${(llmCostData.total_cost_usd ?? 0).toFixed(4)} spent
                </span>
              )}
            </div>
          </CardHeader>
          <CardContent className="p-3 flex flex-col gap-2">
            <LLMCostChart data={llmCostData} />
          </CardContent>
        </Card>
      </div>
    </div>
  );
}
