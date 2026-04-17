"use client"

import { API_BASE } from '@/lib/api';
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
                  className="w-full rounded-sm transition-all duration-200 group-hover:brightness-125"
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
                    className={`w-full rounded-sm transition-all duration-300 group-hover:brightness-125 ${isToday ? 'ring-1 ring-[var(--kraken-purple)]/40' : ''}`}
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
                    className={`w-full rounded-sm transition-all duration-300 group-hover:brightness-125 ${isCurrent ? 'ring-1 ring-[var(--kraken-purple)]/40' : ''}`}
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

  const toX = (ts: number) => {
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
        `${i === 0 ? 'M' : 'L'}${toX(ts).toFixed(1)},${toY(v).toFixed(1)}`
      ).join(' ')
    : null;

  const pnlPath = data.cumulative_pnl.length > 1
    ? data.cumulative_pnl.map(([ts, v], i) =>
        `${i === 0 ? 'M' : 'L'}${toX(ts).toFixed(1)},${toY(v).toFixed(1)}`
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
                <th className="py-1 px-2 text-left font-medium tracking-wider">Date</th>
                <th className="py-1 px-2 text-right font-medium tracking-wider">Day PnL</th>
                <th className="py-1 px-2 text-right font-medium tracking-wider">LLM Cost</th>
                <th className="py-1 px-2 text-right font-medium tracking-wider">Ratio</th>
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
// Tear Sheet Sidebar — 8-row metrics panel alongside equity curve
// ---------------------------------------------------------------------------

function TearSheet({ perfData, winRate, todayPnl, unrealizedPnl, profitFactor, calmarRatio }: {
  perfData:      any;
  winRate:       number | null;
  todayPnl:      number | null;
  unrealizedPnl: number | null;
  profitFactor:  number | null;
  calmarRatio:   number | null;
}) {
  const drawdown = perfData.drawdown ?? 0;
  const sharpe   = perfData.sharpe  ?? 0;
  const sortino  = perfData.sortino ?? 0;

  const pfDisplay = profitFactor == null
    ? '—'
    : !isFinite(profitFactor)
      ? '∞'
      : profitFactor.toFixed(2);

  const rows = [
    {
      label: 'Max DD',
      value: `${drawdown.toFixed(3)}%`,
      color: drawdown >= 1.5 ? 'text-[var(--neon-red)]' : 'text-[var(--foreground)]',
    },
    {
      label: 'Sharpe',
      value: perfData.has_data ? sharpe.toFixed(2) : '—',
      color: sharpe >= 1 ? 'text-[var(--neon-green)]' : 'text-[var(--foreground)]',
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
      label: 'Profit F.',
      value: pfDisplay,
      color: profitFactor == null
        ? 'text-[var(--muted-foreground)]'
        : profitFactor >= 1.5
          ? 'text-[var(--neon-green)]'
          : profitFactor < 1.0
            ? 'text-[var(--neon-red)]'
            : 'text-[var(--foreground)]',
    },
    {
      label: 'Calmar',
      value: calmarRatio != null ? calmarRatio.toFixed(2) : '—',
      color: calmarRatio != null && calmarRatio >= 0.5
        ? 'text-[var(--neon-green)]'
        : 'text-[var(--foreground)]',
    },
    {
      label: "Today",
      value: todayPnl != null
        ? (todayPnl >= 0 ? '+' : '') + `$${todayPnl.toFixed(2)}`
        : '—',
      color: (todayPnl ?? 0) >= 0 ? 'text-[var(--neon-green)]' : 'text-[var(--neon-red)]',
    },
    {
      label: 'Unreal.',
      value: unrealizedPnl != null
        ? (unrealizedPnl >= 0 ? '+' : '') + `$${unrealizedPnl.toFixed(2)}`
        : '—',
      color: (unrealizedPnl ?? 0) >= 0 ? 'text-[var(--neon-green)]' : 'text-[var(--neon-red)]',
    },
  ];

  return (
    <div className="w-48 shrink-0 flex flex-col gap-0 border-l border-[var(--border)] divide-y divide-[var(--border)]/40">
      {rows.map(row => (
        <div key={row.label} className="flex flex-col px-3 py-2">
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
// DrawdownChart — running peak-to-trough underwater curve
// ---------------------------------------------------------------------------

function DrawdownChart({ history }: { history: [number, number][] }) {
  const gradId = React.useId().replace(/:/g, '_');

  const ddPoints = React.useMemo(() => {
    if (!history || history.length < 2) return [] as { dd: number }[];
    let peak = history[0][1];
    return history.map(([, val]) => {
      if (val > peak) peak = val;
      return { dd: peak > 0 ? ((peak - val) / peak) * 100 : 0 };
    });
  }, [history]);

  const maxDd = React.useMemo(
    () => Math.max(...ddPoints.map(p => p.dd), 0.001),
    [ddPoints],
  );

  const maxDdIdx = React.useMemo(
    () => ddPoints.reduce((mi, p, i) => (p.dd > (ddPoints[mi]?.dd ?? 0) ? i : mi), 0),
    [ddPoints],
  );

  if (ddPoints.length < 2) {
    return (
      <div className="w-full h-[110px] flex items-center justify-center text-xs font-mono text-[var(--muted-foreground)] opacity-30 uppercase tracking-widest">
        Insufficient history
      </div>
    );
  }

  const W = 1000; const H = 100;
  const PL = 38; const PR = 6; const PT = 10; const PB = 16;

  const toX = (i: number) => PL + (i / Math.max(ddPoints.length - 1, 1)) * (W - PL - PR);
  const toY = (dd: number) => PT + (dd / maxDd) * (H - PT - PB);

  const pts = ddPoints.map((p, i) => `${toX(i).toFixed(1)},${toY(p.dd).toFixed(1)}`);
  const linePath = `M${pts.join(' L')}`;
  const areaPath = `${linePath} L${toX(ddPoints.length - 1).toFixed(1)},${(H - PB).toFixed(1)} L${toX(0).toFixed(1)},${(H - PB).toFixed(1)} Z`;

  const mxX = toX(maxDdIdx);
  const mxY = toY(ddPoints[maxDdIdx]?.dd ?? 0);
  const labelRight = mxX > W * 0.75;

  return (
    <div className="w-full" style={{ height: 110 }}>
      <svg
        viewBox={`0 0 ${W} ${H}`}
        preserveAspectRatio="none"
        style={{ width: '100%', height: '100%' }}
      >
        <defs>
          <linearGradient id={gradId} x1="0" y1="0" x2="0" y2="1">
            <stop offset="0%" stopColor="var(--neon-red)" stopOpacity="0.4" />
            <stop offset="100%" stopColor="var(--neon-red)" stopOpacity="0.04" />
          </linearGradient>
        </defs>

        {/* Zero baseline */}
        <line x1={PL} y1={PT} x2={W - PR} y2={PT}
              stroke="var(--border)" strokeWidth="0.8" strokeDasharray="4,4" />

        {/* Area fill */}
        <path d={areaPath} fill={`url(#${gradId})`} />

        {/* Stroke line */}
        <path d={linePath} fill="none" stroke="var(--neon-red)" strokeWidth="1.5"
              strokeLinejoin="round" strokeLinecap="round" />

        {/* Max drawdown annotation */}
        {(ddPoints[maxDdIdx]?.dd ?? 0) > 0.01 && (
          <>
            <circle cx={mxX} cy={mxY} r={3}
              fill="var(--neon-red)" stroke="var(--background)" strokeWidth="1.5" />
            <text
              x={labelRight ? mxX - 5 : mxX + 5}
              y={mxY - 4}
              textAnchor={labelRight ? 'end' : 'start'}
              fill="var(--neon-red)" fontSize={8}
              fontFamily="JetBrains Mono, monospace"
            >
              {`-${(ddPoints[maxDdIdx]?.dd ?? 0).toFixed(2)}%`}
            </text>
          </>
        )}

        {/* Current drawdown dot */}
        {(() => {
          const last = ddPoints[ddPoints.length - 1];
          if (!last || last.dd < 0.001) return null;
          return (
            <circle cx={toX(ddPoints.length - 1)} cy={toY(last.dd)} r={2.5}
              fill="var(--neon-red)" opacity="0.7" />
          );
        })()}

        {/* Y-axis labels */}
        <text x={PL - 3} y={PT + 4} textAnchor="end"
              fill="var(--muted-foreground)" fontSize={7}
              fontFamily="JetBrains Mono, monospace" opacity="0.5">0%</text>
        <text x={PL - 3} y={H - PB} textAnchor="end"
              fill="var(--neon-red)" fontSize={7}
              fontFamily="JetBrains Mono, monospace" opacity="0.7">
          {`-${maxDd.toFixed(1)}%`}
        </text>
      </svg>
    </div>
  );
}

// ---------------------------------------------------------------------------
// RollingMetricsChart — 20-day rolling Sharpe over time
// ---------------------------------------------------------------------------

function RollingMetricsChart({ history }: { history: [number, number][] }) {
  const WINDOW   = 20;
  const SQRT_252 = Math.sqrt(252);

  const rollingPoints = React.useMemo(() => {
    if (!history || history.length < WINDOW + 2) return [] as { sharpe: number }[];
    const returns: number[] = [];
    for (let i = 1; i < history.length; i++) {
      const prev = history[i - 1][1];
      returns.push(prev !== 0 ? (history[i][1] - prev) / prev : 0);
    }
    const pts: { sharpe: number }[] = [];
    for (let i = WINDOW; i <= returns.length; i++) {
      const win  = returns.slice(i - WINDOW, i);
      const mean = win.reduce((s, r) => s + r, 0) / WINDOW;
      const vari = win.reduce((s, r) => s + (r - mean) ** 2, 0) / (WINDOW - 1);
      const std  = Math.sqrt(vari);
      pts.push({ sharpe: std < 1e-10 ? 0 : (mean / std) * SQRT_252 });
    }
    return pts;
  }, [history]);

  if (rollingPoints.length < 2) {
    return (
      <div className="flex flex-col items-center justify-center h-full gap-2">
        <Activity className="w-5 h-5 text-[var(--muted-foreground)] opacity-20" />
        <div className="text-xs font-mono text-[var(--muted-foreground)] opacity-40 uppercase tracking-widest text-center">
          Need {WINDOW + 2}+ equity snapshots
        </div>
      </div>
    );
  }

  const W = 1000; const H = 90;
  const PL = 34; const PR = 6; const PT = 8; const PB = 8;

  const rawMax = Math.max(...rollingPoints.map(p => Math.abs(p.sharpe)));
  const yMax   = Math.max(Math.min(rawMax, 10), 1);

  const toX = (i: number) => PL + (i / Math.max(rollingPoints.length - 1, 1)) * (W - PL - PR);
  const toY = (s: number) => {
    const clamped = Math.max(Math.min(s, yMax), -yMax);
    return PT + ((-clamped + yMax) / (2 * yMax)) * (H - PT - PB);
  };
  const zeroY = toY(0);

  // Contiguous negative segments for red shading
  const negSegs: { s: number; e: number }[] = [];
  let segStart: number | null = null;
  rollingPoints.forEach((p, i) => {
    if (p.sharpe < 0 && segStart === null) segStart = i;
    if (p.sharpe >= 0 && segStart !== null) {
      negSegs.push({ s: segStart, e: i - 1 });
      segStart = null;
    }
  });
  if (segStart !== null) negSegs.push({ s: segStart, e: rollingPoints.length - 1 });

  const pts = rollingPoints.map((p, i) => `${toX(i).toFixed(1)},${toY(p.sharpe).toFixed(1)}`);
  const linePath = `M${pts.join(' L')}`;

  const lastSharpe = rollingPoints[rollingPoints.length - 1]?.sharpe ?? 0;

  return (
    <div className="flex flex-col gap-1 h-full">
      <svg viewBox={`0 0 ${W} ${H}`} preserveAspectRatio="none" style={{ width: '100%', flex: 1 }}>
        {/* Zero line */}
        <line x1={PL} y1={zeroY} x2={W - PR} y2={zeroY}
              stroke="var(--border)" strokeWidth="1" strokeDasharray="4,4" />

        {/* Negative zone shading */}
        {negSegs.map((seg, i) => (
          <rect key={i}
            x={toX(seg.s)} y={zeroY}
            width={Math.max(toX(seg.e) - toX(seg.s), 1)}
            height={H - PB - zeroY}
            fill="var(--neon-red)" opacity="0.12"
          />
        ))}

        {/* Sharpe line */}
        <path d={linePath} fill="none" stroke="var(--kraken-purple)" strokeWidth="1.5"
              strokeLinejoin="round" strokeLinecap="round" />

        {/* Y-axis labels */}
        <text x={PL - 3} y={PT + 4} textAnchor="end"
              fill="var(--muted-foreground)" fontSize={7}
              fontFamily="JetBrains Mono, monospace" opacity="0.5">
          +{yMax.toFixed(0)}
        </text>
        <text x={PL - 3} y={H - PB} textAnchor="end"
              fill="var(--muted-foreground)" fontSize={7}
              fontFamily="JetBrains Mono, monospace" opacity="0.5">
          -{yMax.toFixed(0)}
        </text>
        <text x={PL - 3} y={zeroY + 3} textAnchor="end"
              fill="var(--muted-foreground)" fontSize={6}
              fontFamily="JetBrains Mono, monospace" opacity="0.4">0</text>
      </svg>
      <div className="flex items-center justify-between text-xs font-mono tabular-nums text-[var(--muted-foreground)] opacity-50 px-1">
        <span>20-day window · {rollingPoints.length} points</span>
        <span className={lastSharpe >= 0 ? 'text-[var(--neon-green)]' : 'text-[var(--neon-red)]'}>
          Current {lastSharpe >= 0 ? '+' : ''}{lastSharpe.toFixed(2)}
        </span>
      </div>
    </div>
  );
}

// ---------------------------------------------------------------------------
// TradeDistribution — histogram of realized trade P&L returns
// ---------------------------------------------------------------------------

function TradeDistribution({ trades }: { trades: { pnl: number }[] | undefined }) {
  const N_BINS = 12;

  const stats = React.useMemo(() => {
    if (!trades || trades.length < 3) return null;
    const pnls = trades.map(t => t.pnl);
    const minP = Math.min(...pnls);
    const maxP = Math.max(...pnls);
    const range = maxP - minP || 1;
    const bw = range / N_BINS;

    const counts = new Array(N_BINS).fill(0);
    pnls.forEach(p => {
      const idx = Math.min(Math.floor((p - minP) / bw), N_BINS - 1);
      counts[idx]++;
    });

    const mean = pnls.reduce((s, p) => s + p, 0) / pnls.length;
    const sorted = [...pnls].sort((a, b) => a - b);
    const median = sorted.length % 2 === 0
      ? (sorted[sorted.length / 2 - 1] + sorted[sorted.length / 2]) / 2
      : sorted[Math.floor(sorted.length / 2)];
    const variance = pnls.reduce((s, p) => s + (p - mean) ** 2, 0) / pnls.length;
    const std = Math.sqrt(variance);
    const skewness = std < 1e-10 ? 0 : (3 * (mean - median)) / std;

    const bins = counts.map((count, i) => ({
      mid: minP + (i + 0.5) * bw,
      count,
    }));

    return { bins, minP, range, bw, mean, skewness, total: pnls.length };
  }, [trades]);

  if (!stats) {
    return (
      <div className="flex flex-col items-center justify-center h-full gap-2">
        <BarChart3 className="w-5 h-5 text-[var(--muted-foreground)] opacity-20" />
        <div className="text-xs font-mono text-[var(--muted-foreground)] opacity-40 uppercase tracking-widest text-center">
          Need 3+ closed trades
        </div>
      </div>
    );
  }

  const { bins, minP, range, mean, skewness, total } = stats;

  const W = 1000; const H = 80;
  const PL = 6; const PR = 6; const PT = 8; const PB = 4;

  const maxCount = Math.max(...bins.map(b => b.count), 1);
  const slotW    = (W - PL - PR) / bins.length;
  const barGap   = 3;
  const meanX    = PL + ((mean - minP) / range) * (W - PL - PR);

  const skewLabel = skewness > 0.2
    ? 'right-skewed +'
    : skewness < -0.2
      ? 'left-skewed !'
      : 'symmetric';
  const skewColor = skewness > 0.2
    ? 'text-[var(--neon-green)]'
    : skewness < -0.2
      ? 'text-[var(--neon-red)]'
      : 'text-[var(--muted-foreground)]';

  return (
    <div className="flex flex-col gap-1 h-full">
      <svg viewBox={`0 0 ${W} ${H}`} preserveAspectRatio="none" style={{ width: '100%', flex: 1 }}>
        {bins.map((bin, i) => {
          const isPos = bin.mid >= 0;
          const bh = Math.max((bin.count / maxCount) * (H - PT - PB), bin.count > 0 ? 2 : 1);
          const x  = PL + i * slotW + barGap / 2;
          const y  = H - PB - bh;
          return (
            <rect key={i}
              x={x} y={y}
              width={Math.max(slotW - barGap, 1)} height={bh}
              fill={isPos ? 'var(--neon-green)' : 'var(--neon-red)'}
              opacity="0.75"
            />
          );
        })}

        {/* Mean line */}
        {meanX >= PL && meanX <= W - PR && (
          <line x1={meanX} y1={PT} x2={meanX} y2={H - PB}
                stroke="var(--foreground)" strokeWidth="1.5"
                strokeDasharray="3,3" opacity="0.45" />
        )}
      </svg>
      <div className="flex items-center justify-between text-xs font-mono tabular-nums text-[var(--muted-foreground)] opacity-60 px-1">
        <span>{total} trades · mean ${mean.toFixed(2)}</span>
        <span className={skewColor}>{skewLabel}</span>
      </div>
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
  const lastSignal     = useTradingStore(s => s.lastSignal);

  const [period, setPeriod] = React.useState<Period>('1M');
  const [perfData, setPerfData] = React.useState(performance);
  const [llmCostData, setLlmCostData] = React.useState<LLMCostData>({
    has_data: false, cumulative_cost: [], cumulative_pnl: [],
  });

  React.useEffect(() => {
    const loadPerf = () =>
      fetch(`${API_BASE}/api/performance?period=${period}`)
        .then(r => r.ok ? r.json() : null)
        .then(d => { if (d) setPerfData(d); })
        .catch(() => {});
    loadPerf();
    const interval = setInterval(loadPerf, 60_000);
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
      fetch(`${API_BASE}/api/analytics/llm-cost?period=${period}`)
        .then(r => r.ok ? r.json() : null)
        .then(d => { if (d) setLlmCostData(d); })
        .catch(() => {});
    load();
    const interval = setInterval(load, 60_000);
    return () => clearInterval(interval);
  }, [period]);

  // Win rate — closed realized trades where pnl > 0
  const winRate = React.useMemo(() => {
    const trades = perfData.realized_trades as { pnl: number }[] | undefined;
    if (!trades || trades.length === 0) return null;
    const wins = trades.filter((t: { pnl: number }) => t.pnl > 0).length;
    return (wins / trades.length) * 100;
  }, [perfData.realized_trades]);

  // Profit Factor — gross wins / gross losses
  const profitFactor = React.useMemo(() => {
    const trades = perfData.realized_trades as { pnl: number }[] | undefined;
    if (!trades || trades.length === 0) return null;
    const gw = trades.filter(t => t.pnl > 0).reduce((s, t) => s + t.pnl, 0);
    const gl = trades.filter(t => t.pnl < 0).reduce((s, t) => s + Math.abs(t.pnl), 0);
    if (gl === 0) return gw > 0 ? Infinity : null;
    return gw / gl;
  }, [perfData.realized_trades]);

  const drawdown   = perfData.drawdown ?? riskStatus?.drawdown_pct ?? 0;
  const killActive = riskStatus?.triggered ?? false;

  // Calmar Ratio — annualised return / max drawdown
  const calmarRatio = React.useMemo(() => {
    if (drawdown <= 0 || !perfData.has_data) return null;
    const hist = perfData.history as [number, number][];
    if (!hist || hist.length < 2) return null;
    const firstEq = hist[0][1];
    const lastEq  = hist[hist.length - 1][1];
    const days    = Math.max((hist[hist.length - 1][0] - hist[0][0]) / 86_400_000, 1);
    const annRet  = ((lastEq - firstEq) / (firstEq || 1)) * (252 / days);
    return annRet / (drawdown / 100);
  }, [perfData, drawdown]);

  // Compute unrealized P&L total from live positions as fallback
  const positionsUnrealizedPnl = React.useMemo(
    () => positions.reduce((sum, p) => sum + (p.unrealizedPnl ?? 0), 0),
    [positions],
  );
  const liveUnrealized = unrealizedPnl ?? positionsUnrealizedPnl;

  const pfDisplay = profitFactor == null
    ? '—'
    : !isFinite(profitFactor)
      ? '∞'
      : profitFactor.toFixed(2);

  // 8-item KPI grid: 4×2 layout
  const kpis = [
    // Row 1: return / risk metrics
    {
      label: 'Total Net PnL',
      value: perfData.has_data
        ? (perfData.net_pnl >= 0 ? '+' : '') + `$${perfData.net_pnl.toFixed(2)}`
        : '$0.00',
      sub: `${period} Realized`,
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
      label: 'Sharpe Ratio',
      value: perfData.has_data ? (perfData.sharpe ?? 0).toFixed(2) : '—',
      sub: 'Annualised √252',
      c: (perfData.sharpe ?? 0) >= 1
        ? 'text-[var(--neon-green)]'
        : 'text-[var(--foreground)]',
    },
    {
      label: 'Sortino Ratio',
      value: perfData.has_data ? (perfData.sortino ?? 0).toFixed(2) : '—',
      sub: 'Downside deviation',
      c: (perfData.sortino ?? 0) >= 1
        ? 'text-[var(--neon-green)]'
        : 'text-[var(--foreground)]',
    },
    // Row 2: efficiency / execution metrics
    {
      label: 'Calmar Ratio',
      value: calmarRatio != null ? calmarRatio.toFixed(2) : '—',
      sub: 'Ann. Return / DD',
      c: calmarRatio == null
        ? 'text-[var(--muted-foreground)]'
        : calmarRatio >= 0.5
          ? 'text-[var(--neon-green)]'
          : 'text-[var(--foreground)]',
    },
    {
      label: 'Win Rate',
      value: winRate != null ? `${winRate.toFixed(0)}%` : '—',
      sub: `${(perfData.realized_trades?.length ?? 0)} trades`,
      c: winRate != null
        ? (winRate >= 50 ? 'text-[var(--neon-green)]' : 'text-[var(--neon-red)]')
        : 'text-[var(--muted-foreground)]',
    },
    {
      label: 'Profit Factor',
      value: pfDisplay,
      sub: 'Gross P / Gross L',
      c: profitFactor == null
        ? 'text-[var(--muted-foreground)]'
        : profitFactor >= 1.5
          ? 'text-[var(--neon-green)]'
          : profitFactor < 1.0
            ? 'text-[var(--neon-red)]'
            : 'text-[var(--foreground)]',
    },
    {
      label: 'PnL / LLM Cost',
      value: llmCostData.cumulative_ratio != null
        ? `${llmCostData.cumulative_ratio.toFixed(1)}x`
        : '—',
      sub: `${period} efficiency`,
      c: (llmCostData.cumulative_ratio ?? 0) >= 1
        ? 'text-[var(--neon-green)]'
        : llmCostData.cumulative_ratio != null
          ? 'text-[var(--neon-red)]'
          : 'text-[var(--muted-foreground)]',
    },
  ];

  const history = perfData.history as [number, number][];

  return (
    <div className="flex flex-col h-full gap-4 pr-2 pb-4">

      {/* Kill Switch Alert Banner */}
      {killActive && (
        <div className="flex items-center gap-3 px-4 py-2.5 rounded-sm border border-[var(--neon-red)]/60 bg-[var(--neon-red)]/10 text-[var(--neon-red)] text-xs font-bold uppercase tracking-widest animate-pulse shrink-0">
          <ShieldAlert className="w-4 h-4 shrink-0" />
          Kill Switch Active — {riskStatus?.reason ?? 'Trading Halted'}
        </div>
      )}

      {/* KPI Grid — 4×2 layout */}
      <div className="grid grid-cols-2 md:grid-cols-4 gap-3 shrink-0">
        {kpis.map((kpi, i) => (
          <Card key={i} className="bg-[var(--panel)]/80">
            <CardContent className="p-3 flex flex-col justify-center text-center sm:text-left">
              <div className="text-xs text-[var(--muted-foreground)] uppercase tracking-wider mb-1 line-clamp-1">
                {kpi.label}
              </div>
              <div className={`text-lg font-bold font-mono tabular-nums ${kpi.c}`}>
                {kpi.value}
              </div>
              <div className="text-xs text-[var(--muted-foreground)] mt-1 line-clamp-1">
                {kpi.sub}
              </div>
            </CardContent>
          </Card>
        ))}
      </div>

      {/* ── Row 1: Equity Curve (h-400) + TearSheet (w-48) ── */}
      <Card className="shrink-0 flex flex-col h-[400px]">
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
              history={history}
              lastSignal={lastSignal}
              ohlcv={ohlcvData?.candles}
            />
          </div>
          <TearSheet
            perfData={perfData}
            winRate={winRate}
            todayPnl={todayPnl}
            unrealizedPnl={liveUnrealized}
            profitFactor={profitFactor}
            calmarRatio={calmarRatio}
          />
        </CardContent>
      </Card>

      {/* ── Row 2: Drawdown / Underwater Chart ── */}
      {history?.length >= 2 && (
        <Card className="shrink-0 flex flex-col">
          <CardHeader className="border-b border-[var(--border)] py-2 px-4 flex flex-row items-center shrink-0">
            <TrendingDown className="w-3.5 h-3.5 text-[var(--neon-red)] mr-2 shrink-0" />
            <CardTitle className="text-xs uppercase tracking-widest text-[var(--muted-foreground)]">
              Underwater / Drawdown
            </CardTitle>
            <span className="ml-auto text-xs font-mono text-[var(--muted-foreground)] opacity-40">
              Running peak-to-trough
            </span>
          </CardHeader>
          <CardContent className="p-0">
            <DrawdownChart history={history} />
          </CardContent>
        </Card>
      )}

      {/* ── Row 3: Rolling Sharpe | Trade P&L Distribution ── */}
      <div className="grid grid-cols-1 lg:grid-cols-2 gap-4 shrink-0">

        <Card className="flex flex-col h-[180px]">
          <CardHeader className="border-b border-[var(--border)] py-2.5 px-4 flex flex-row items-center shrink-0">
            <Activity className="w-4 h-4 text-[var(--kraken-light)] mr-2" />
            <CardTitle className="text-xs uppercase tracking-widest text-[var(--muted-foreground)]">
              Rolling Sharpe
            </CardTitle>
            <span className="ml-auto text-xs font-mono text-[var(--muted-foreground)] opacity-40">20-day</span>
          </CardHeader>
          <CardContent className="flex-1 p-2 flex flex-col">
            <RollingMetricsChart history={history} />
          </CardContent>
        </Card>

        <Card className="flex flex-col h-[180px]">
          <CardHeader className="border-b border-[var(--border)] py-2.5 px-4 flex flex-row items-center shrink-0">
            <BarChart3 className="w-4 h-4 text-[var(--kraken-light)] mr-2" />
            <CardTitle className="text-xs uppercase tracking-widest text-[var(--muted-foreground)]">
              Trade P&L Distribution
            </CardTitle>
          </CardHeader>
          <CardContent className="flex-1 p-2 flex flex-col">
            <TradeDistribution trades={perfData.realized_trades} />
          </CardContent>
        </Card>
      </div>

      {/* ── Row 4: Strategy Attribution + Bot Performance Matrix ── */}
      <div className="grid grid-cols-1 lg:grid-cols-2 gap-4 shrink-0">

        {/* Strategy Attribution — dual-bar: signal share + PnL attribution */}
        <Card className="flex flex-col h-[240px]">
          <CardHeader className="border-b border-[var(--border)] py-2.5 px-4 flex flex-row items-center shrink-0">
            <PieChart className="w-4 h-4 text-[var(--kraken-light)] mr-2" />
            <CardTitle className="text-xs uppercase tracking-widest text-[var(--muted-foreground)]">
              Strategy Attribution
            </CardTitle>
          </CardHeader>
          <CardContent className="flex-1 p-3 flex flex-col gap-2 overflow-y-auto">
            {bots.length === 0 ? (
              <div className="text-xs text-[var(--muted-foreground)] opacity-50 italic">
                Connecting to strategy engine...
              </div>
            ) : (() => {
              const totalSignals = bots.reduce((s: number, b: any) => s + (b.signalCount ?? 0), 0);
              const totalPnl     = bots.reduce((s: number, b: any) => s + Math.abs(b.yield24h ?? 0), 0);
              return (
                <>
                  {/* Column labels */}
                  <div className="flex items-center gap-2 pb-1 border-b border-[var(--border)]/30 shrink-0">
                    <div className="w-28 shrink-0" />
                    <div className="flex-1 flex justify-between text-xs font-mono text-[var(--muted-foreground)] opacity-40 uppercase tracking-wider">
                      <span>Signal</span>
                      <span>PnL</span>
                    </div>
                    <div className="w-20 text-right text-xs font-mono text-[var(--muted-foreground)] opacity-40 uppercase tracking-wider">
                      Eff.
                    </div>
                  </div>

                  {bots.map((bot: any) => {
                    const signalShare = totalSignals > 0
                      ? ((bot.signalCount ?? 0) / totalSignals) * 100
                      : 0;
                    const pnlShare = totalPnl > 0
                      ? (Math.abs(bot.yield24h ?? 0) / totalPnl) * 100
                      : 0;
                    const efficiency = (bot.signalCount ?? 0) > 0
                      ? (bot.yield24h ?? 0) / (bot.signalCount ?? 1)
                      : null;
                    const isPos = (bot.yield24h ?? 0) >= 0;

                    return (
                      <div key={bot.id} className="flex items-center gap-2">
                        {/* Name + status dot */}
                        <div className="flex items-center gap-1.5 w-28 shrink-0 min-w-0">
                          <span className={`w-1.5 h-1.5 rounded-sm shrink-0 ${
                            bot.status === 'ACTIVE'
                              ? 'bg-[var(--neon-green)] shadow-[0_0_4px_var(--neon-green)]'
                              : 'bg-[var(--muted-foreground)]'
                          }`} />
                          <span className="text-xs font-mono font-semibold text-[var(--foreground)] truncate">
                            {bot.name}
                          </span>
                        </div>

                        {/* Dual bars */}
                        <div className="flex-1 flex flex-col gap-0.5">
                          <div className="h-1 w-full bg-[var(--background)] overflow-hidden rounded-sm">
                            <div
                              className="h-full transition-all duration-700"
                              style={{
                                width: `${Math.max(signalShare, signalShare > 0 ? 2 : 0)}%`,
                                background: 'var(--kraken-purple)',
                                opacity: 0.7,
                              }}
                            />
                          </div>
                          <div className="h-1 w-full bg-[var(--background)] overflow-hidden rounded-sm">
                            <div
                              className="h-full transition-all duration-700"
                              style={{
                                width: `${Math.max(pnlShare, pnlShare > 0 ? 2 : 0)}%`,
                                background: isPos ? 'var(--neon-green)' : 'var(--neon-red)',
                              }}
                            />
                          </div>
                        </div>

                        {/* Efficiency */}
                        <div className="w-20 text-right shrink-0">
                          <span className={`text-xs font-mono tabular-nums ${
                            efficiency == null
                              ? 'text-[var(--muted-foreground)] opacity-40'
                              : efficiency >= 0
                                ? 'text-[var(--neon-green)]'
                                : 'text-[var(--neon-red)]'
                          }`}>
                            {efficiency != null
                              ? `${efficiency >= 0 ? '+' : ''}$${Math.abs(efficiency).toFixed(2)}/sig`
                              : '—'}
                          </span>
                        </div>
                      </div>
                    );
                  })}
                </>
              );
            })()}
          </CardContent>
        </Card>

        {/* Bot Performance Matrix */}
        <Card className="flex flex-col h-[240px]">
          <CardHeader className="border-b border-[var(--border)] py-2.5 px-4 flex flex-row items-center shrink-0">
            <Activity className="w-4 h-4 text-[var(--kraken-light)] mr-2" />
            <CardTitle className="text-xs uppercase tracking-widest text-[var(--muted-foreground)]">
              Bot Performance Matrix
            </CardTitle>
          </CardHeader>
          <CardContent className="flex-1 p-0 overflow-y-auto max-h-[188px]">
            {bots.length === 0 ? (
              <div className="flex items-center justify-center h-full text-xs text-[var(--muted-foreground)] opacity-40">
                Connecting...
              </div>
            ) : (
              <table className="w-full text-xs tabular-nums font-mono">
                <thead className="sticky top-0 bg-[var(--panel-muted)] text-[var(--muted-foreground)] border-b border-[var(--border)]">
                  <tr>
                    <th className="text-left font-medium p-2 pl-3 tracking-wider">Bot</th>
                    <th className="text-center font-medium p-2 tracking-wider">Status</th>
                    <th className="text-right font-medium p-2 tracking-wider">Signals</th>
                    <th className="text-right font-medium p-2 tracking-wider">Fill %</th>
                    <th className="text-right font-medium p-2 tracking-wider">Yield</th>
                    <th className="text-right font-medium p-2 pr-3 tracking-wider">Avg/Trade</th>
                  </tr>
                </thead>
                <tbody className="divide-y divide-[var(--border)]/30">
                  {bots.map((bot: any) => {
                    const fillRate = (bot.signalCount ?? 0) > 0
                      ? ((bot.fillCount ?? 0) / (bot.signalCount ?? 1) * 100).toFixed(0)
                      : '—';
                    const yield24h = bot.yield24h ?? 0;
                    const isPos    = yield24h >= 0;
                    const fills    = bot.fillCount ?? 0;
                    const avgTrade = fills > 0 ? yield24h / fills : null;
                    return (
                      <tr key={bot.id} className="hover:bg-[var(--panel-muted)] transition-colors">
                        <td className="p-2 pl-3 font-mono font-semibold text-[var(--foreground)] truncate max-w-[90px]">
                          {bot.name}
                        </td>
                        <td className="p-2 text-center">
                          <span className={`inline-flex items-center gap-1 text-xs font-mono ${
                            bot.status === 'ACTIVE' ? 'text-[var(--neon-green)]' : 'text-[var(--muted-foreground)]'
                          }`}>
                            <span className={`w-1 h-1 rounded-sm ${
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
                        <td className={`p-2 text-right font-bold ${
                          yield24h !== 0 ? (isPos ? 'text-[var(--neon-green)]' : 'text-[var(--neon-red)]') : 'text-[var(--muted-foreground)] opacity-40'
                        }`}>
                          {yield24h !== 0 ? `${isPos ? '+' : ''}$${yield24h.toFixed(2)}` : '—'}
                        </td>
                        <td className={`p-2 pr-3 text-right ${
                          avgTrade == null
                            ? 'text-[var(--muted-foreground)] opacity-40'
                            : avgTrade >= 0
                              ? 'text-[var(--neon-green)]'
                              : 'text-[var(--neon-red)]'
                        }`}>
                          {avgTrade != null
                            ? `${avgTrade >= 0 ? '+' : ''}$${avgTrade.toFixed(2)}`
                            : '—'}
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

      {/* ── Row 5: PnL Calendar + LLM Cost vs PnL ── */}
      <div className="grid grid-cols-1 lg:grid-cols-2 gap-4 shrink-0">

        {/* PnL Calendar Heatmap */}
        <Card className="flex flex-col">
          <CardHeader className="border-b border-[var(--border)] py-2.5 px-4 shrink-0">
            <CardTitle className="text-xs uppercase tracking-widest text-[var(--muted-foreground)]">
              PnL Calendar
            </CardTitle>
          </CardHeader>
          <CardContent className="p-4">
            <PnLCalendar history={history} />
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
