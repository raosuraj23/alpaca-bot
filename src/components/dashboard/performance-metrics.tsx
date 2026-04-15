"use client"

import * as React from 'react';
import { Card, CardHeader, CardTitle, CardContent } from "@/components/ui/card";
import { Activity, BarChart3, PieChart, ShieldAlert } from 'lucide-react';
import { useTradingStore } from '@/hooks/useTradingStream';

// ---------------------------------------------------------------------------
// PnL Calendar Heatmap (12-week GitHub-style grid)
// ---------------------------------------------------------------------------

function PnLCalendar({ history }: { history: [number, number][] }) {
  const WEEKS = 12;
  const DAYS  = 7;
  const CELL  = 12;
  const GAP   = 2;

  const dailyPnl = React.useMemo(() => {
    if (!history || history.length < 2) return new Map<string, number>();
    const map = new Map<string, number>();
    for (let i = 1; i < history.length; i++) {
      const pnl = (history[i][1] ?? 0) - (history[i - 1][1] ?? 0);
      const date = new Date(history[i][0]);
      const key = `${date.getFullYear()}-${date.getMonth()}-${date.getDate()}`;
      map.set(key, pnl);
    }
    return map;
  }, [history]);

  const cells = React.useMemo(() => {
    const result: { key: string; pnl: number | null; label: string }[] = [];
    const today = new Date();
    const startDate = new Date(today);
    startDate.setDate(today.getDate() - WEEKS * DAYS + 1);
    for (let d = 0; d < WEEKS * DAYS; d++) {
      const date = new Date(startDate);
      date.setDate(startDate.getDate() + d);
      const key = `${date.getFullYear()}-${date.getMonth()}-${date.getDate()}`;
      const label = date.toLocaleDateString('en-US', { month: 'short', day: 'numeric' });
      result.push({ key, pnl: dailyPnl.get(key) ?? null, label });
    }
    return result;
  }, [dailyPnl]);

  const cellColor = (pnl: number | null) => {
    if (pnl === null) return 'var(--panel-muted)';
    if (pnl >  50) return 'hsl(150,80%,35%)';
    if (pnl >   0) return 'hsl(150,60%,25%)';
    if (pnl === 0) return 'hsl(250,10%,25%)';
    if (pnl >  -50) return 'hsl(350,60%,30%)';
    return 'hsl(350,80%,40%)';
  };

  const W = WEEKS * (CELL + GAP);
  const H = DAYS  * (CELL + GAP);

  return (
    <div className="flex flex-col gap-1">
      <svg viewBox={`0 0 ${W} ${H}`} style={{ width: '100%', height: `${H + 4}px` }}>
        {cells.map(({ key, pnl, label }, i) => {
          const col = Math.floor(i / DAYS);
          const row = i % DAYS;
          const x = col * (CELL + GAP);
          const y = row * (CELL + GAP);
          return (
            <g key={key}>
              <rect
                x={x} y={y} width={CELL} height={CELL}
                fill={cellColor(pnl)}
                rx={1}
              >
                <title>{label}{pnl !== null ? ` — ${pnl >= 0 ? '+' : ''}$${pnl.toFixed(2)}` : ' — no data'}</title>
              </rect>
            </g>
          );
        })}
      </svg>
      <div className="flex justify-between text-xs font-mono tabular-nums text-[var(--muted-foreground)] opacity-50">
        <span>12 weeks ago</span>
        <div className="flex items-center gap-1">
          {['hsl(350,80%,40%)', 'hsl(350,60%,30%)', 'hsl(250,10%,25%)', 'hsl(150,60%,25%)', 'hsl(150,80%,35%)'].map((c, i) => (
            <span key={i} style={{ background: c, display: 'inline-block', width: 10, height: 10, borderRadius: 1 }} />
          ))}
          <span>loss → profit</span>
        </div>
        <span>today</span>
      </div>
    </div>
  );
}

// ---------------------------------------------------------------------------
// LLM Cost vs Cumulative PnL — dual-line SVG chart
// ---------------------------------------------------------------------------

interface LLMCostData {
  has_data: boolean;
  cumulative_cost: [number, number][];
  cumulative_pnl:  [number, number][];
  total_cost_usd?: number;
  total_pnl_usd?:  number;
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
      <div className="flex items-center gap-4 text-xs font-mono tabular-nums text-[var(--muted-foreground)]">
        <div className="flex items-center gap-1">
          <span className="inline-block w-6 h-0.5 bg-[var(--neon-green)]" />
          <span>Cumulative PnL {data.total_pnl_usd !== undefined ? `$${data.total_pnl_usd.toFixed(2)}` : ''}</span>
        </div>
        <div className="flex items-center gap-1">
          <span className="inline-block w-5 border-t-2 border-dashed border-[var(--neon-red)]" />
          <span>LLM Cost ${(data.total_cost_usd ?? 0).toFixed(4)}</span>
        </div>
      </div>
    </div>
  );
}

// ---------------------------------------------------------------------------
// Dynamic SVG Equity Curve
// ---------------------------------------------------------------------------

function EquityCurve({ history }: { history: [number, number][] }) {
  const W = 600;
  const H = 200;

  if (!history || history.length < 2) {
    return (
      <div className="absolute inset-0 flex flex-col items-center justify-center">
        <Activity className="w-8 h-8 text-[var(--muted-foreground)] opacity-20 mb-3" />
        <div className="text-sm font-bold text-[var(--muted-foreground)] uppercase tracking-widest opacity-80">
          Awaiting Executions
        </div>
        <div className="text-xs text-[var(--muted-foreground)] opacity-50 mt-1 uppercase">
          Portfolio History is Empty
        </div>
      </div>
    );
  }

  const values = history.map(([, v]) => v).filter(v => v != null && !isNaN(v));
  const minY = Math.min(...values);
  const maxY = Math.max(...values);
  const rangeY = maxY - minY || 1;

  const LABEL_W = 56; // reserved px on right for Y-axis labels
  const chartW  = W - LABEL_W;

  const points: [number, number][] = history.map(([, v], i) => [
    (i / (history.length - 1)) * chartW,
    H - ((v - minY) / rangeY) * H * 0.85 - H * 0.05,
  ]);

  const linePath = points.map(([x, y], i) => `${i === 0 ? 'M' : 'L'}${x},${y}`).join(' ');
  const areaPath = `${linePath} L${chartW},${H} L0,${H} Z`;

  const fmt = (v: number) =>
    v >= 1000 ? `$${(v / 1000).toFixed(1)}k` : `$${v.toFixed(0)}`;

  // Y-axis: top (max), mid, bottom (min)
  const yLabels = [
    { v: maxY, y: H * 0.05 },
    { v: (minY + maxY) / 2, y: H * 0.5 },
    { v: minY, y: H * 0.9 },
  ];

  return (
    <svg
      viewBox={`0 0 ${W} ${H}`}
      preserveAspectRatio="none"
      className="absolute inset-0 w-full h-full"
    >
      <defs>
        <linearGradient id="eqGrad" x1="0" y1="0" x2="0" y2="1">
          <stop offset="0%" stopColor="var(--kraken-purple)" stopOpacity="0.45" />
          <stop offset="100%" stopColor="var(--kraken-purple)" stopOpacity="0.0" />
        </linearGradient>
      </defs>
      {/* Horizontal guide lines */}
      {yLabels.map(({ y }, i) => (
        <line key={i} x1={0} y1={y} x2={chartW} y2={y}
              stroke="hsla(255,40%,40%,0.12)" strokeWidth="1" />
      ))}
      <path d={areaPath} fill="url(#eqGrad)" />
      <path d={linePath} fill="none" stroke="var(--kraken-purple)" strokeWidth="2.5"
            strokeLinejoin="round" strokeLinecap="round" />
      {/* Y-axis labels — rendered at fixed pixel size so they don't scale */}
      {yLabels.map(({ v, y }, i) => (
        <text key={i}
          x={chartW + 4} y={y + 4}
          fontSize="10" fill="hsla(250,10%,65%,0.8)"
          fontFamily="monospace"
        >
          {fmt(v)}
        </text>
      ))}
    </svg>
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
  const [returnBuckets, setReturnBuckets] = React.useState<{ label: string; count: number; pct: number }[]>([]);
  const [returnsHasData, setReturnsHasData] = React.useState(false);
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
    const loadReturns = () =>
      fetch('http://localhost:8000/api/analytics/returns')
        .then(r => r.ok ? r.json() : null)
        .then(d => {
          if (d?.has_data) { setReturnBuckets(d.buckets); setReturnsHasData(true); }
        })
        .catch(() => {});
    loadReturns();
    const interval = setInterval(loadReturns, 60_000); // refresh every 60s
    return () => clearInterval(interval);
  }, []);

  React.useEffect(() => {
    fetch('http://localhost:8000/api/analytics/llm-cost')
      .then(r => r.ok ? r.json() : null)
      .then(d => { if (d) setLlmCostData(d); })
      .catch(() => {});
  }, []);

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
      <div className="grid grid-cols-2 md:grid-cols-3 lg:grid-cols-6 gap-3 shrink-0">
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

      <div className="grid grid-cols-1 lg:grid-cols-3 gap-4 shrink-0 h-[350px]">
        {/* Live Equity Curve */}
        <Card className="lg:col-span-2 flex flex-col">
          <CardHeader className="border-b border-[var(--border)] py-3 px-4 flex flex-row items-center justify-between bg-gradient-to-b from-[var(--panel-muted)] to-transparent">
            <div className="flex items-center space-x-2">
              <Activity className="w-4 h-4 text-[var(--kraken-purple)]" />
              <CardTitle className="text-xs tracking-wider uppercase font-bold text-[var(--kraken-light)]">
                Live Equity Trajectory
              </CardTitle>
            </div>
            <div className="flex items-center space-x-1">
              {PERIODS.map(p => (
                <button
                  key={p}
                  onClick={() => setPeriod(p)}
                  className={`px-2 py-0.5 text-xs font-mono rounded-sm border transition-colors ${
                    period === p
                      ? 'border-[var(--kraken-purple)] text-[var(--kraken-light)] bg-[var(--kraken-purple)]/20'
                      : 'border-[var(--border)] text-[var(--muted-foreground)] hover:border-[var(--kraken-purple)]/50'
                  }`}
                >
                  {p}
                </button>
              ))}
            </div>
          </CardHeader>
          <CardContent className="flex-1 p-0 relative bg-[var(--background)] overflow-hidden">
            <EquityCurve history={perfData.history as [number, number][]} />
          </CardContent>
        </Card>

        {/* Strategy Attribution — real per-bot yield */}
        <Card className="flex flex-col">
          <CardHeader className="border-b border-[var(--border)] py-3 px-4 flex flex-row items-center font-bold">
            <PieChart className="w-4 h-4 text-[var(--kraken-light)] mr-2" />
            <CardTitle className="text-xs uppercase tracking-widest text-[var(--muted-foreground)]">
              Strategy Attribution
            </CardTitle>
          </CardHeader>
          <CardContent className="flex-1 p-4 flex flex-col space-y-4 overflow-y-auto">
            {bots.length === 0 ? (
              <div className="text-xs text-[var(--muted-foreground)] opacity-50 italic">
                Connecting to strategy engine...
              </div>
            ) : bots.map((bot: any, i: number) => {
              const colors = [
                'bg-[var(--kraken-purple)]',
                'bg-[var(--neon-green)]',
                'bg-[var(--kraken-light)]',
              ];
              const maxYield = Math.max(...bots.map((b: any) => Math.abs(b.yield24h ?? 0)), 0.001);
              const ratio = Math.abs((bot.yield24h ?? 0) / maxYield) * 100;
              const isPositive = (bot.yield24h ?? 0) >= 0;
              return (
                <div key={bot.id} className="space-y-1.5">
                  <div className="flex justify-between text-xs font-bold">
                    <div className="flex items-center gap-1.5">
                      <span className={`w-1.5 h-1.5 rounded-full ${bot.status === 'ACTIVE' ? 'bg-[var(--neon-green)] shadow-[0_0_6px_var(--neon-green)]' : 'bg-[var(--muted-foreground)]'}`} />
                      <span className="text-[var(--foreground)]">{bot.name}</span>
                    </div>
                    <span className={`font-mono ${isPositive ? 'text-[var(--neon-green)]' : 'text-[var(--neon-red)]'}`}>
                      {isPositive ? '+' : ''}${(bot.yield24h ?? 0).toFixed(2)}
                    </span>
                  </div>
                  <div className="h-1.5 w-full bg-[var(--background)] rounded-full overflow-hidden">
                    <div
                      className={`h-full ${colors[i % colors.length]} transition-all duration-700 ${isPositive ? 'shadow-[0_0_8px_currentColor]' : 'opacity-50'}`}
                      style={{ width: `${Math.max(ratio, 4)}%` }}
                    />
                  </div>
                  <div className="text-xs text-[var(--muted-foreground)] font-mono">
                    {bot.signalCount ?? 0} signals · {bot.fillCount ?? 0} fills
                  </div>
                </div>
              );
            })}
          </CardContent>
        </Card>
      </div>

      {/* Slippage Distribution */}
      <Card className="shrink-0 h-[220px] flex flex-col">
        <CardHeader className="border-b border-[var(--border)] py-2.5 px-4 flex flex-row items-center justify-between">
          <CardTitle className="text-xs uppercase tracking-widest text-[var(--muted-foreground)] flex items-center">
            <BarChart3 className="w-4 h-4 mr-2" /> Slippage Distribution
          </CardTitle>
          {returnsHasData && (
            <span className="text-xs font-mono text-[var(--muted-foreground)] opacity-60">bps per fill</span>
          )}
        </CardHeader>
        <CardContent className="flex-1 p-4 flex items-end justify-between space-x-1 lg:space-x-2">
          {returnsHasData ? returnBuckets.map((bucket, i) => {
            const maxPct = Math.max(...returnBuckets.map(b => b.pct), 1);
            const height = Math.max((bucket.pct / maxPct) * 100, 2);
            const isNeg = bucket.label.startsWith('-');
            const isZero = bucket.label === '+0bps';
            return (
              <div key={i} className="flex-1 flex flex-col items-center group cursor-crosshair">
                <div className="text-xs font-mono opacity-0 group-hover:opacity-100 mb-1 transition-opacity text-[var(--kraken-light)]">
                  {bucket.count}
                </div>
                <div
                  className={`w-full rounded-t-sm transition-all duration-300 group-hover:brightness-150 ${
                    isNeg ? 'bg-[var(--neon-green)]/60' : isZero ? 'bg-[var(--muted-foreground)]' : 'bg-[var(--neon-red)]/50'
                  }`}
                  style={{ height: `${height}%` }}
                />
                <div className="text-xs font-mono mt-1 text-[var(--muted-foreground)] opacity-50 group-hover:opacity-100 hidden sm:block">
                  {bucket.label}
                </div>
              </div>
            );
          }) : (
            <div className="flex-1 flex flex-col items-center justify-center text-center">
              <BarChart3 className="w-8 h-8 text-[var(--muted-foreground)] opacity-20 mb-2" />
              <div className="text-xs text-[var(--muted-foreground)] opacity-50 uppercase tracking-widest">
                Awaiting Fills
              </div>
              <div className="text-xs text-[var(--muted-foreground)] opacity-30 mt-1">
                Populates after first execution
              </div>
            </div>
          )}
        </CardContent>
      </Card>

      {/* PnL Calendar Heatmap */}
      <Card className="shrink-0 flex flex-col">
        <CardHeader className="border-b border-[var(--border)] py-2.5 px-4">
          <CardTitle className="text-xs uppercase tracking-widest text-[var(--muted-foreground)]">
            Daily PnL Calendar (12w)
          </CardTitle>
        </CardHeader>
        <CardContent className="p-4">
          <PnLCalendar history={perfData.history as [number, number][]} />
        </CardContent>
      </Card>

      {/* LLM Cost vs PnL */}
      <Card className="shrink-0 flex flex-col">
        <CardHeader className="border-b border-[var(--border)] py-2.5 px-4 flex flex-row items-center justify-between">
          <CardTitle className="text-xs uppercase tracking-widest text-[var(--muted-foreground)]">
            LLM Cost vs Cumulative PnL
          </CardTitle>
          {llmCostData.has_data && (
            <span className="text-xs font-mono tabular-nums text-[var(--muted-foreground)] opacity-60">
              net: {((llmCostData.total_pnl_usd ?? 0) - (llmCostData.total_cost_usd ?? 0)) >= 0 ? '+' : ''}
              ${((llmCostData.total_pnl_usd ?? 0) - (llmCostData.total_cost_usd ?? 0)).toFixed(2)}
            </span>
          )}
        </CardHeader>
        <CardContent className="p-4 h-[180px]">
          <LLMCostChart data={llmCostData} />
        </CardContent>
      </Card>
    </div>
  );
}
