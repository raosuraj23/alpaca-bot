"use client"

import * as React from 'react';
import { Card, CardHeader, CardTitle, CardContent } from "@/components/ui/card";
import { Badge } from "@/components/ui/badge";
import { TrendingUp, Activity, BarChart3, PieChart, ShieldAlert } from 'lucide-react';
import { useTradingStore } from '@/hooks/useTradingStream';

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

  const points: [number, number][] = history.map(([, v], i) => [
    (i / (history.length - 1)) * W,
    H - ((v - minY) / rangeY) * H * 0.85 - H * 0.05,
  ]);

  const linePath = points.map(([x, y], i) => `${i === 0 ? 'M' : 'L'}${x},${y}`).join(' ');
  const areaPath = `${linePath} L${W},${H} L0,${H} Z`;

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
      <path d={areaPath} fill="url(#eqGrad)" />
      <path d={linePath} fill="none" stroke="var(--kraken-purple)" strokeWidth="2.5"
            strokeLinejoin="round" strokeLinecap="round" />
    </svg>
  );
}

// ---------------------------------------------------------------------------
// Performance Metrics Component
// ---------------------------------------------------------------------------

export function PerformanceMetrics() {
  const performance  = useTradingStore(s => s.performance);
  const riskStatus   = useTradingStore(s => s.riskStatus);
  const bots         = useTradingStore(s => (s as any).bots ?? []);

  const drawdown    = riskStatus?.drawdown_pct ?? 0;
  const killActive  = riskStatus?.triggered ?? false;

  // Approximate Sharpe from history if available
  const sharpeApprox = React.useMemo(() => {
    if (!performance.history || performance.history.length < 5) return null;
    const returns = performance.history.slice(1).map(([, v], i) => {
      const prev = performance.history[i][1];
      return prev !== 0 ? (v - prev) / prev : 0;
    });
    const mean = returns.reduce((a, b) => a + b, 0) / returns.length;
    const std = Math.sqrt(returns.reduce((s, r) => s + (r - mean) ** 2, 0) / returns.length);
    return std > 0 ? (mean / std * Math.sqrt(252)).toFixed(2) : null;
  }, [performance.history]);

  const kpis = [
    {
      label: 'Total Net PnL',
      value: performance.has_data
        ? (performance.net_pnl >= 0 ? '+' : '') + `$${performance.net_pnl.toFixed(2)}`
        : '$0.00',
      sub: 'YTD Live',
      c: performance.net_pnl >= 0 ? 'text-[var(--neon-green)]' : 'text-[var(--neon-red)]',
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
      label: 'Max Position %',
      value: `${((riskStatus?.max_position_pct ?? 10))}%`,
      sub: `Cap: $${((riskStatus?.max_position_usd ?? 50000) / 1000).toFixed(0)}k`,
      c: 'text-[var(--kraken-light)]',
    },
    {
      label: 'Kelly Fraction',
      value: `${((riskStatus?.max_kelly_fraction ?? 0.25) * 100).toFixed(0)}%`,
      sub: 'Risk Budget',
      c: 'text-[var(--foreground)]',
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
            <div className="flex items-center space-x-2">
              <Badge variant="outline" className="text-xs">1D</Badge>
              <Badge variant="purple" className="text-xs">1W</Badge>
              <Badge variant="outline" className="text-xs">1M</Badge>
              <Badge variant="outline" className="text-xs">YTD</Badge>
            </div>
          </CardHeader>
          <CardContent className="flex-1 p-0 relative bg-[var(--background)] overflow-hidden">
            <EquityCurve history={performance.history as [number, number][]} />
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

      {/* Return Distribution */}
      <Card className="shrink-0 h-[220px] flex flex-col">
        <CardHeader className="border-b border-[var(--border)] py-2.5 px-4">
          <CardTitle className="text-xs uppercase tracking-widest text-[var(--muted-foreground)] flex items-center">
            <BarChart3 className="w-4 h-4 mr-2" /> Return Distribution (Kurtosis)
          </CardTitle>
        </CardHeader>
        <CardContent className="flex-1 p-4 flex items-end justify-between space-x-1 lg:space-x-2">
          {[5, 10, 15, 25, 45, 80, 100, 75, 40, 20, 15, 8, 5, 2, 1].map((height, i) => (
            <div key={i} className="flex-1 flex flex-col items-center group cursor-crosshair">
              <div className="text-xs font-mono opacity-0 group-hover:opacity-100 mb-1 transition-opacity text-[var(--kraken-light)]">
                {height}
              </div>
              <div
                className={`w-full rounded-t-sm transition-all duration-300 group-hover:brightness-150 ${
                  i < 6 ? 'bg-[var(--neon-red)]/50' : i === 6 ? 'bg-[var(--muted-foreground)]' : 'bg-[var(--neon-green)]/60'
                }`}
                style={{ height: `${height}%` }}
              />
              <div className="text-xs font-mono mt-1 text-[var(--muted-foreground)] opacity-50 group-hover:opacity-100 hidden sm:block">
                {i - 6}%
              </div>
            </div>
          ))}
        </CardContent>
      </Card>
    </div>
  );
}
