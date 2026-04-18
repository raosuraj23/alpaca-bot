"use client"

import * as React from 'react';
import {
  AreaChart, Area,
  XAxis, YAxis, Tooltip, ResponsiveContainer, ReferenceLine,
} from 'recharts';
import { API_BASE } from '@/lib/api';
import { useTradingStore } from '@/hooks/useTradingStream';
import {
  ShieldAlert, TrendingUp, TrendingDown, BarChart3,
  Cpu, BrainCircuit,
} from 'lucide-react';


import { GlobalKPIs } from './GlobalKPIs';
import { EquityCurveTerminal } from './EquityCurveTerminal';
import { ReturnDistribution } from './ReturnDistribution';
import { BotPerformanceMatrix } from './BotPerformanceMatrix';
import { LLMBreakdown, type LLMBreakdownData } from './LLMBreakdown';

// ---------------------------------------------------------------------------
// Types
// ---------------------------------------------------------------------------

interface LLMCostData {
  has_data: boolean;
  cumulative_cost: [number, number][];
  cumulative_pnl: [number, number][];
  total_cost_usd?: number;
  cumulative_ratio?: number | null;
}

const EMPTY_PERF = {
  history: [] as [number, number][],
  net_pnl: 0,
  drawdown: 0,
  has_data: false,
  sharpe: 0,
  sortino: 0,
  realized_trades: undefined as { pnl: number }[] | undefined,
};

const PERIODS = ['1D', '1W', '1M', 'YTD', 'ALL'] as const;
type Period = typeof PERIODS[number];

const CHART_STYLE = { background: 'transparent', fontSize: 10, fontFamily: 'JetBrains Mono, monospace' };

// ---------------------------------------------------------------------------
// Bento cell wrapper
// ---------------------------------------------------------------------------

function BentoCell({
  header,
  children,
  className = '',
  bodyClass = '',
}: {
  header: React.ReactNode;
  children: React.ReactNode;
  className?: string;
  bodyClass?: string;
}) {
  return (
    <div className={`bg-[var(--panel)] border border-[var(--border)] rounded-sm overflow-hidden flex flex-col ${className}`}>
      <div className="border-b border-[var(--border)] px-4 py-2 flex items-center gap-2 shrink-0">
        {header}
      </div>
      <div className={`flex-1 min-h-0 overflow-hidden ${bodyClass}`}>
        {children}
      </div>
    </div>
  );
}

function CellTitle({ icon, title, meta }: { icon: React.ReactNode; title: string; meta?: React.ReactNode }) {
  return (
    <>
      <span className="inline-flex items-center shrink-0 text-[var(--muted-foreground)] [&>svg]:w-3.5 [&>svg]:h-3.5">{icon}</span>
      <span className="text-xs font-semibold uppercase tracking-wider text-[var(--muted-foreground)] flex-1">{title}</span>
      {meta && <span className="text-xs font-mono tabular-nums text-[var(--muted-foreground)] opacity-50 shrink-0">{meta}</span>}
    </>
  );
}

// ---------------------------------------------------------------------------
// Drawdown Chart
// ---------------------------------------------------------------------------

function DrawdownChart({ history, height = 256 }: { history: [number, number][]; height?: number }) {
  const data = React.useMemo(() => {
    if (history.length < 2) return null;
    let peak = history[0][1];
    return history.map(([ts, v]) => {
      if (v > peak) peak = v;
      const dd = peak > 0 ? -((peak - v) / peak) * 100 : 0;
      return { ts, dd };
    });
  }, [history]);

  if (!data) {
    return (
      <div className="flex flex-col items-center justify-center gap-2" style={{ height }}>
        <TrendingDown className="w-5 h-5 text-[var(--muted-foreground)] opacity-20" />
        <span className="text-xs font-mono text-[var(--muted-foreground)] opacity-40 uppercase tracking-widest">
          No history yet
        </span>
      </div>
    );
  }

  const minDd = Math.min(...data.map(d => d.dd));

  return (
    <div style={{ height }}>
      <ResponsiveContainer width="100%" height={height} minWidth={0} minHeight={0}>
        <AreaChart data={data} margin={{ top: 4, right: 8, bottom: 4, left: 4 }} style={CHART_STYLE}>
          <defs>
            <linearGradient id="ddGrad" x1="0" y1="0" x2="0" y2="1">
              <stop offset="5%" stopColor="var(--neon-red)" stopOpacity={0.35} />
              <stop offset="95%" stopColor="var(--neon-red)" stopOpacity={0.05} />
            </linearGradient>
          </defs>
          <XAxis dataKey="ts" hide />
          <YAxis
            domain={[minDd * 1.1, 0]}
            tickFormatter={v => `${Number(v).toFixed(1)}%`}
            tick={{ fill: 'var(--muted-foreground)', fontSize: 10 }}
            stroke="var(--border)" tickLine={false} axisLine={false} width={36}
          />
          <ReferenceLine y={0} stroke="var(--border)" strokeDasharray="3 3" strokeOpacity={0.6} />
          <Tooltip
            content={({ active, payload }) => {
              if (!active || !payload?.length) return null;
              const { ts, dd } = payload[0].payload;
              return (
                <div className="bg-[var(--panel)] border border-[var(--border)] px-3 py-2 shadow-lg rounded-sm">
                  <div className="text-xs text-[var(--muted-foreground)]">
                    {new Date(ts).toLocaleDateString(undefined, { month: 'short', day: 'numeric' })}
                  </div>
                  <div className="text-sm font-mono font-bold tabular-nums text-[var(--neon-red)]">
                    {Number(dd).toFixed(3)}%
                  </div>
                </div>
              );
            }}
          />
          <Area
            type="monotone"
            dataKey="dd"
            stroke="var(--neon-red)"
            strokeWidth={1.5}
            fill="url(#ddGrad)"
            isAnimationActive={false}
          />
        </AreaChart>
      </ResponsiveContainer>
    </div>
  );
}

// ---------------------------------------------------------------------------
// Main export
// ---------------------------------------------------------------------------

export function AnalyticsDashboard() {
  const performance   = useTradingStore(s => s.performance);
  const riskStatus    = useTradingStore(s => s.riskStatus);
  const bots          = useTradingStore(s => s.bots);
  const unrealizedPnl = useTradingStore(s => s.unrealizedPnl);
  const positions     = useTradingStore(s => s.positions);
  const lastSignal    = useTradingStore(s => s.lastSignal);

  const [period, setPeriod]       = React.useState<Period>('1M');
  const [loading, setLoading]     = React.useState(false);
  const [perfData, setPerfData]   = React.useState(performance);
  const [llmCostData, setLlmCostData] = React.useState<LLMCostData>({
    has_data: false, cumulative_cost: [], cumulative_pnl: [],
  });
  const [llmBreakdown, setLlmBreakdown] = React.useState<LLMBreakdownData>({
    has_data: false, total_calls: 0, total_tokens_in: 0, total_tokens_out: 0,
    total_cost_usd: 0, by_model: [], by_purpose: [], recent: [],
  });

  React.useEffect(() => {
    let cancelled = false;
    setLoading(true);
    setPerfData(prev => ({ ...prev, realized_trades: undefined }));

    const load = () =>
      fetch(`${API_BASE}/api/performance?period=${period}`)
        .then(r => r.ok ? r.json() : null)
        .then(d => { if (d && !cancelled) { setPerfData(d); setLoading(false); } })
        .catch(() => { if (!cancelled) setLoading(false); });

    load();
    const id = setInterval(load, 30_000);
    return () => { cancelled = true; clearInterval(id); };
  }, [period]);

  React.useEffect(() => {
    if (performance.has_data) setPerfData(performance);
  }, [performance]);

  React.useEffect(() => {
    let cancelled = false;
    const load = () =>
      fetch(`${API_BASE}/api/analytics/llm-cost?period=${period}`)
        .then(r => r.ok ? r.json() : null)
        .then(d => { if (d && !cancelled) setLlmCostData(d); })
        .catch(() => {});
    load();
    const id = setInterval(load, 30_000);
    return () => { cancelled = true; clearInterval(id); };
  }, [period]);

  React.useEffect(() => {
    let cancelled = false;
    const load = () =>
      fetch(`${API_BASE}/api/analytics/llm-breakdown?period=${period}`)
        .then(r => r.ok ? r.json() : null)
        .then(d => { if (d && !cancelled) setLlmBreakdown(d); })
        .catch(() => {});
    load();
    const id = setInterval(load, 60_000);
    return () => { cancelled = true; clearInterval(id); };
  }, [period]);

  const history = (perfData.history ?? []) as [number, number][];
  const killActive = riskStatus?.triggered ?? false;
  const netPnl = perfData.net_pnl ?? 0;
  const tradeCount = (perfData.realized_trades ?? []).length;
  const maxDd = perfData.drawdown ?? 0;

  return (
    <div className="flex flex-col h-full min-h-0 gap-3 overflow-y-auto pr-1 pb-4">

      {killActive && (
        <div className="flex items-center gap-3 px-4 py-2.5 rounded-sm border border-[var(--neon-red)]/60 bg-[var(--neon-red)]/10 text-[var(--neon-red)] text-xs font-bold uppercase tracking-widest animate-pulse shrink-0">
          <ShieldAlert className="w-4 h-4 shrink-0" />
          Kill Switch Active — {riskStatus?.reason ?? 'Trading Halted'}
        </div>
      )}

      {/* Filter Bar */}
      <div className="flex items-center gap-2 shrink-0">
        <div className="flex bg-[var(--panel)] border border-[var(--border)] rounded-sm p-0.5">
          {PERIODS.map(p => (
            <button
              key={p}
              onClick={() => setPeriod(p)}
              className={`px-3 py-1 text-xs font-mono rounded-sm transition-colors ${
                period === p
                  ? 'bg-[var(--kraken-purple)]/20 text-[var(--kraken-light)] border border-[var(--kraken-purple)]/40'
                  : 'text-[var(--muted-foreground)] hover:text-[var(--foreground)]'
              }`}
            >
              {p}
            </button>
          ))}
        </div>
        {loading && (
          <span className="text-xs font-mono text-[var(--muted-foreground)] opacity-50 animate-pulse">loading...</span>
        )}
        <span className="text-xs font-mono text-[var(--muted-foreground)] opacity-40 ml-auto">30s refresh</span>
      </div>

      {/* ── Bento Grid ── */}
      <div className="grid grid-cols-12 gap-3">

        {/* Row 1 — KPI Strip */}
        <div className="col-span-12">
          <GlobalKPIs
            perfData={perfData}
            riskStatus={riskStatus}
            llmCostData={llmCostData}
            unrealizedPnl={unrealizedPnl}
            positions={positions}
            history={history}
          />
        </div>

        {/* Row 2 — Equity Curve (6) | Drawdown (6) */}
        <BentoCell
          className="col-span-12 lg:col-span-6 h-[320px]"
          header={
            <CellTitle
              icon={netPnl >= 0 ? <TrendingUp /> : <TrendingDown />}
              title="Equity Curve"
              meta={`${netPnl >= 0 ? '+' : ''}$${netPnl.toFixed(2)}`}
            />
          }
          bodyClass="p-0"
        >
          <EquityCurveTerminal history={history} lastSignal={lastSignal} />
        </BentoCell>

        <BentoCell
          className="col-span-12 lg:col-span-6 h-[320px]"
          header={
            <CellTitle
              icon={<TrendingDown />}
              title="Drawdown"
              meta={history.length >= 2 ? `${maxDd.toFixed(3)}%` : undefined}
            />
          }
          bodyClass="p-3"
        >
          <DrawdownChart history={history} height={256} />
        </BentoCell>

        {/* Row 3 — Return Distribution (6) | LLM Intelligence (6) */}
        <BentoCell
          className="col-span-12 lg:col-span-6 h-[320px]"
          header={
            <CellTitle
              icon={<BarChart3 />}
              title="Return Distribution"
              meta={tradeCount > 0 ? `${tradeCount} trades` : (loading ? 'loading…' : undefined)}
            />
          }
          bodyClass="p-3"
        >
          <ReturnDistribution trades={perfData.realized_trades} height={256} />
        </BentoCell>

        <BentoCell
          className="col-span-12 lg:col-span-6 h-[320px]"
          header={
            <CellTitle
              icon={<BrainCircuit />}
              title="LLM Intelligence"
              meta={llmBreakdown.has_data ? `${llmBreakdown.total_calls} calls` : undefined}
            />
          }
          bodyClass="p-3"
        >
          <LLMBreakdown data={llmBreakdown} height={256} />
        </BentoCell>

        {/* Row 4 — Bot Performance Matrix */}
        <BentoCell
          className="col-span-12"
          header={<CellTitle icon={<Cpu />} title="Bot Performance Matrix" meta={`${bots.length} bots`} />}
          bodyClass="p-0"
        >
          <BotPerformanceMatrix bots={bots} />
        </BentoCell>

      </div>
    </div>
  );
}
