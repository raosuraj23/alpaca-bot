"use client"

import * as React from 'react';
import { Card, CardHeader, CardTitle, CardContent } from "@/components/ui/card";
import { BarChart3, PieChart, ShieldAlert, TrendingUp, TrendingDown, Activity } from 'lucide-react';
import {
  createChart, CandlestickSeries, LineSeries, HistogramSeries,
  CrosshairMode, createSeriesMarkers,
} from 'lightweight-charts';
import type { IChartApi, ISeriesApi, ISeriesMarkersPluginApi, SeriesMarker, Time } from 'lightweight-charts';
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
        <div className="mt-2 rounded-sm border border-[var(--border)]">
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
// RSI helper
// ---------------------------------------------------------------------------

function computeRsi(values: number[], period = 14): (number | null)[] {
  const result: (number | null)[] = new Array(values.length).fill(null);
  if (values.length <= period) return result;
  const changes = values.slice(1).map((v, i) => v - values[i]);
  let avgGain = changes.slice(0, period).filter(c => c > 0).reduce((s, c) => s + c, 0) / period;
  let avgLoss = changes.slice(0, period).filter(c => c < 0).reduce((s, c) => s + Math.abs(c), 0) / period;
  for (let i = period; i < values.length; i++) {
    const change = changes[i - 1];
    avgGain = (avgGain * (period - 1) + (change > 0 ? change : 0)) / period;
    avgLoss = (avgLoss * (period - 1) + (change < 0 ? Math.abs(change) : 0)) / period;
    const rs = avgLoss === 0 ? 100 : avgGain / avgLoss;
    result[i] = 100 - 100 / (1 + rs);
  }
  return result;
}

// ---------------------------------------------------------------------------
// TradingChart — lightweight-charts split-pane: candlestick + EMA (top),
// volume histogram + RSI (bottom). Signal annotations via createSeriesMarkers.
// ---------------------------------------------------------------------------

type OHLCVCandle = { time: number; open: number; high: number; low: number; close: number; volume: number };

function TradingChart({ history, lastSignal, ohlcv }: {
  history:    [number, number][];
  lastSignal: { action: string; symbol: string; timestamp: string } | null;
  ohlcv?:     OHLCVCandle[];
}) {
  const containerRef  = React.useRef<HTMLDivElement>(null);
  const chartRef      = React.useRef<IChartApi | null>(null);
  const candleRef     = React.useRef<ISeriesApi<'Candlestick'> | null>(null);
  const markersRef    = React.useRef<ISeriesMarkersPluginApi<Time> | null>(null);

  // Rebuild chart when history or real OHLCV changes
  React.useEffect(() => {
    const el = containerRef.current;
    if (!el || !history || history.length < 2) return;

    const H = el.clientHeight || 260;

    const chart = createChart(el, {
      layout: {
        background: { color: 'transparent' },
        textColor:  'hsl(250,10%,65%)',
        fontSize:   10,
        fontFamily: 'JetBrains Mono, monospace',
      },
      grid: {
        vertLines: { color: 'hsla(255,40%,40%,0.06)' },
        horzLines: { color: 'hsla(255,40%,40%,0.06)' },
      },
      crosshair:       { mode: CrosshairMode.Normal },
      timeScale:       { borderColor: 'hsla(255,40%,40%,0.15)', timeVisible: true, secondsVisible: false },
      rightPriceScale: { borderColor: 'hsla(255,40%,40%,0.15)' },
      height:          H,
      autoSize:        true,
    });

    // Add second pane for volume/RSI
    chart.addPane();
    const panes = chart.panes();
    panes[0].setHeight(Math.floor(H * 0.68));
    panes[1].setHeight(Math.floor(H * 0.32));

    // Use real OHLCV bars when available; fall back to synthesizing from equity snapshots
    const candles = ohlcv && ohlcv.length > 0
      ? ohlcv.map(c => ({ time: c.time as Time, open: c.open, high: c.high, low: c.low, close: c.close }))
      : history.map(([ts, val], i) => ({
          time:  Math.floor(ts / 1000) as Time,
          open:  i === 0 ? val : history[i - 1][1],
          high:  Math.max(val, i === 0 ? val : history[i - 1][1]) * 1.001,
          low:   Math.min(val, i === 0 ? val : history[i - 1][1]) * 0.999,
          close: val,
        }));

    const volumes = ohlcv && ohlcv.length > 0
      ? ohlcv.map((c, i) => ({
          time:  c.time as Time,
          value: c.volume,
          color: i > 0 && c.close >= ohlcv[i - 1].close
            ? 'hsla(150,80%,45%,0.35)'
            : 'hsla(350,80%,60%,0.35)',
        }))
      : history.map(([ts, val], i) => ({
          time:  Math.floor(ts / 1000) as Time,
          value: i === 0 ? 0 : Math.abs(val - history[i - 1][1]),
          color: i > 0 && val >= history[i - 1][1]
            ? 'hsla(150,80%,45%,0.35)'
            : 'hsla(350,80%,60%,0.35)',
        }));

    // Candlestick series — pane 0
    const cSeries = chart.addSeries(CandlestickSeries, {
      upColor:        'hsl(150,80%,45%)',
      downColor:      'hsl(350,80%,60%)',
      borderUpColor:  'hsl(150,80%,45%)',
      borderDownColor:'hsl(350,80%,60%)',
      wickUpColor:    'hsl(150,80%,45%)',
      wickDownColor:  'hsl(350,80%,60%)',
    }, 0);
    cSeries.setData(candles);

    // EMA overlay — pane 0
    const EMA_PERIOD = 14;
    const emaData: { time: Time; value: number }[] = [];
    let ema = history[0]?.[1] ?? 0;
    const k = 2 / (EMA_PERIOD + 1);
    history.forEach(([ts, val]) => {
      ema = val * k + ema * (1 - k);
      emaData.push({ time: Math.floor(ts / 1000) as Time, value: ema });
    });
    const emaSeries = chart.addSeries(LineSeries, {
      color:            'hsl(264,80%,75%)',
      lineWidth:        1,
      priceLineVisible: false,
      lastValueVisible: false,
    }, 0);
    emaSeries.setData(emaData);

    // Volume histogram — pane 1
    const volSeries = chart.addSeries(HistogramSeries, {
      color:            'hsla(264,80%,65%,0.35)',
      priceLineVisible: false,
      lastValueVisible: false,
    }, 1);
    volSeries.setData(volumes);

    // RSI line — pane 1
    const rsiValues = computeRsi(history.map(([, v]) => v));
    const rsiData = history
      .map(([ts], i) => ({ time: Math.floor(ts / 1000) as Time, value: rsiValues[i] }))
      .filter((d): d is { time: Time; value: number } => d.value !== null);
    const rsiSeries = chart.addSeries(LineSeries, {
      color:            'hsl(40,90%,55%)',
      lineWidth:        1,
      priceLineVisible: false,
      lastValueVisible: false,
    }, 1);
    rsiSeries.setData(rsiData);

    chartRef.current  = chart;
    candleRef.current = cSeries;
    markersRef.current = createSeriesMarkers(cSeries, []);

    return () => {
      chart.remove();
      chartRef.current   = null;
      candleRef.current  = null;
      markersRef.current = null;
    };
  }, [history, ohlcv]);

  // Signal annotation — fires when lastSignal changes
  React.useEffect(() => {
    if (!lastSignal || !markersRef.current) return;
    const prev = markersRef.current.markers() ?? [];
    const marker: SeriesMarker<Time> = {
      time:     Math.floor(new Date(lastSignal.timestamp).getTime() / 1000) as Time,
      position: lastSignal.action === 'BUY' ? 'belowBar' : 'aboveBar',
      color:    lastSignal.action === 'BUY' ? 'hsl(150,80%,45%)' : 'hsl(350,80%,60%)',
      shape:    lastSignal.action === 'BUY' ? 'arrowUp' : 'arrowDown',
      text:     `${lastSignal.action} ${lastSignal.symbol}`,
    };
    markersRef.current.setMarkers([...prev, marker]);
  }, [lastSignal]);

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

  return (
    <div className="relative w-full h-full">
      <div ref={containerRef} className="w-full h-full" />
      {!ohlcv?.length && (
        <div className="absolute top-2 right-2 z-10 text-xs font-mono text-[var(--muted-foreground)] opacity-40 uppercase tracking-wider pointer-events-none">
          SYNTHETIC
        </div>
      )}
    </div>
  );
}

// ---------------------------------------------------------------------------
// Tear Sheet Sidebar — Sharpe, Sortino, Drawdown, Win Rate, Active Bots
// ---------------------------------------------------------------------------

function TearSheet({ perfData, bots, winRate }: {
  perfData: any;
  bots:     any[];
  winRate:  number | null;
}) {
  const activeBots = bots.filter((b: any) => b.status === 'ACTIVE').length;
  const drawdown   = perfData.drawdown ?? 0;
  const netPnl     = perfData.net_pnl  ?? 0;
  // Sharpe & Sortino sourced from backend /api/performance (annualised, sqrt(252))
  const sharpe  = perfData.sharpe  ?? 0;
  const sortino = perfData.sortino ?? 0;

  const rows = [
    {
      label: 'Net PnL',
      value: perfData.has_data ? `${netPnl >= 0 ? '+' : ''}$${netPnl.toFixed(2)}` : '—',
      color: netPnl >= 0 ? 'text-[var(--neon-green)]' : 'text-[var(--neon-red)]',
    },
    {
      label: 'Max Drawdown',
      value: `${drawdown.toFixed(3)}%`,
      color: drawdown >= 1.5 ? 'text-[var(--neon-red)]' : 'text-[var(--foreground)]',
    },
    {
      label: 'Sharpe',
      value: perfData.has_data ? sharpe.toFixed(2) : '—',
      color: 'text-[var(--foreground)]',
    },
    {
      label: 'Sortino',
      value: perfData.has_data ? sortino.toFixed(2) : '—',
      color: sortino >= 1 ? 'text-[var(--neon-green)]' : 'text-[var(--foreground)]',
    },
    {
      label: 'Win Rate',
      value: winRate != null ? `${winRate.toFixed(0)}%` : '—',
      color: winRate != null
        ? (winRate >= 50 ? 'text-[var(--neon-green)]' : 'text-[var(--neon-red)]')
        : 'text-[var(--muted-foreground)]',
    },
    {
      label: 'Active Bots',
      value: String(activeBots),
      color: activeBots > 0 ? 'text-[var(--neon-green)]' : 'text-[var(--muted-foreground)]',
    },
  ];

  return (
    <div className="w-40 shrink-0 flex flex-col gap-0 border-l border-[var(--border)] divide-y divide-[var(--border)]/40">
      {rows.map(row => (
        <div key={row.label} className="flex flex-col px-3 py-2.5">
          <span className="text-xs uppercase tracking-wider text-[var(--muted-foreground)] mb-0.5 leading-none">
            {row.label}
          </span>
          <span className={`text-sm font-mono tabular-nums font-bold leading-snug ${row.color}`}>
            {row.value}
          </span>
        </div>
      ))}
    </div>
  );
}

// ---------------------------------------------------------------------------
// Performance Metrics Component
// ---------------------------------------------------------------------------

const PERIODS = ['1D', '1W', '1M', 'YTD'] as const;
type Period = typeof PERIODS[number];

export function PerformanceMetrics() {
  const performance    = useTradingStore(s => s.performance);
  const riskStatus     = useTradingStore(s => s.riskStatus);
  const bots           = useTradingStore(s => s.bots);
  const todayPnl       = useTradingStore(s => s.todayPnl);
  const unrealizedPnl  = useTradingStore(s => s.unrealizedPnl);
  const positions      = useTradingStore(s => s.positions);
  const ohlcvData      = useTradingStore(s => s.ohlcvData);
  const fetchOHLCV     = useTradingStore(s => s.fetchOHLCV);
  const lastSignal    = useTradingStore(s => s.lastSignal);

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

  // Fetch real OHLCV once on mount; refresh when period changes
  React.useEffect(() => {
    fetchOHLCV('BTC/USD', '1H');
  }, [fetchOHLCV]);

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

  // Win rate — closed realized trades where pnl > 0 (not equity day-count)
  const winRate = React.useMemo(() => {
    const trades = perfData.realized_trades as { pnl: number }[] | undefined;
    if (!trades || trades.length === 0) return null;
    const wins = trades.filter((t: { pnl: number }) => t.pnl > 0).length;
    return (wins / trades.length) * 100;
  }, [perfData.realized_trades]);

  const drawdown   = perfData.drawdown ?? riskStatus?.drawdown_pct ?? 0;
  const killActive = riskStatus?.triggered ?? false;

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
      value: perfData.has_data ? (perfData.sharpe ?? 0).toFixed(2) : '—',
      sub: 'Annualised √252',
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
    <div className="flex flex-col h-full gap-4 pr-2 pb-4">

      {/* Kill Switch Alert Banner */}
      {killActive && (
        <div className="flex items-center gap-3 px-4 py-2.5 rounded-sm border border-[var(--neon-red)]/60 bg-[var(--neon-red)]/10 text-[var(--neon-red)] text-xs font-bold uppercase tracking-widest animate-pulse shrink-0">
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

      {/* ── Row 1: TradingView Chart — split-pane candlestick + volume/RSI ── */}
      <Card className="shrink-0 flex flex-col h-[320px]">
        <CardHeader className="border-b border-[var(--border)] py-2.5 px-4 flex flex-row items-center justify-between shrink-0">
          <div className="flex items-center gap-3">
            {(perfData.net_pnl ?? 0) >= 0
              ? <TrendingUp className="w-4 h-4 text-[var(--neon-green)]" />
              : <TrendingDown className="w-4 h-4 text-[var(--neon-red)]" />
            }
            <div className="flex flex-col">
              <CardTitle className="text-xs tracking-wider uppercase font-semibold text-[var(--muted-foreground)]">
                Equity Curve
              </CardTitle>
              <span className={`text-lg font-mono tabular-nums font-bold leading-tight ${(perfData.net_pnl ?? 0) >= 0 ? 'text-[var(--neon-green)]' : 'text-[var(--neon-red)]'}`}>
                {(perfData.net_pnl ?? 0) >= 0 ? '+' : ''}${(perfData.net_pnl ?? 0).toFixed(2)}
              </span>
            </div>
          </div>
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
        <CardContent className="flex-1 p-0 bg-[var(--background)] flex overflow-hidden">
          <div className="flex-1 min-w-0 overflow-hidden">
            <TradingChart
              history={perfData.history as [number, number][]}
              lastSignal={lastSignal}
              ohlcv={ohlcvData?.candles}
            />
          </div>
          <TearSheet
            perfData={perfData}
            bots={bots}
            winRate={winRate}
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
          <CardContent className="flex-1 p-3 flex flex-col gap-2.5">
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
          <CardContent className="flex-1 p-0">
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
