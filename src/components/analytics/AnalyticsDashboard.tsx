"use client"

import * as React from 'react';
import { API_BASE } from '@/lib/api';
import { useTradingStore } from '@/hooks/useTradingStream';
import {
  ShieldAlert, TrendingUp, TrendingDown, BarChart3,
  Cpu, Zap, Activity,
} from 'lucide-react';

import { GlobalKPIs } from './GlobalKPIs';
import { EquityCurveTerminal } from './EquityCurveTerminal';
import { ReturnDistribution } from './ReturnDistribution';
import { LLMTelemetry } from './LLMTelemetry';
import { BotPerformanceMatrix } from './BotPerformanceMatrix';
import type { LLMExecutionRecord } from '@/lib/types';

// ---------------------------------------------------------------------------
// Types
// ---------------------------------------------------------------------------

interface LLMDailyRow {
  date: string;
  pnl_usd: number;
  cost_usd: number;
  ratio: number | null;
}

interface LLMCostData {
  has_data: boolean;
  cumulative_cost: [number, number][];
  cumulative_pnl: [number, number][];
  daily?: LLMDailyRow[];
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
      {/* [&>svg] constrains the lucide icon SVG to 14×14 to prevent overflow into title text */}
      <span className="inline-flex items-center shrink-0 text-[var(--muted-foreground)] [&>svg]:w-3.5 [&>svg]:h-3.5">{icon}</span>
      <span className="text-xs font-semibold uppercase tracking-wider text-[var(--muted-foreground)] flex-1">{title}</span>
      {meta && <span className="text-xs font-mono tabular-nums text-[var(--muted-foreground)] opacity-50 shrink-0">{meta}</span>}
    </>
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

  // Fetch performance data — clear realized_trades during load so histogram shows empty state
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

  const history = (perfData.history ?? []) as [number, number][];
  const killActive = riskStatus?.triggered ?? false;
  const netPnl = perfData.net_pnl ?? 0;

  const llmRecords = React.useMemo<LLMExecutionRecord[]>(() => {
    if (!llmCostData.daily?.length) return [];
    return llmCostData.daily.map((row, i) => ({
      id: `daily-${i}`,
      timestamp: new Date(row.date).getTime(),
      strategy: 'aggregate',
      latencyMs: 0,
      totalTokens: 0,
      costUsd: row.cost_usd,
      tradePnl: row.pnl_usd,
      assetClass: 'CRYPTO' as const,
    }));
  }, [llmCostData.daily]);

  const tradeCount = (perfData.realized_trades ?? []).length;

  return (
    <div className="flex flex-col h-full min-h-0 gap-3 overflow-y-auto pr-1 pb-4">

      {/* Kill Switch Banner */}
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

        {/* Row 2 — Equity Curve (7) | LLM Scatter: Latency vs PnL (5) — equal height */}
        <BentoCell
          className="col-span-12 lg:col-span-7 h-[320px]"
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
          className="col-span-12 lg:col-span-5 h-[320px]"
          header={<CellTitle icon={<Zap />} title="LLM Latency vs Trade PnL" />}
          bodyClass="p-3"
        >
          <LLMTelemetry llmRecords={llmRecords} llmCostData={llmCostData} mode="scatter" />
        </BentoCell>

        {/* Row 3 — Return Distribution (5) | Cumulative PnL vs LLM Cost (7) — equal height */}
        <BentoCell
          className="col-span-12 lg:col-span-5 h-[320px]"
          header={
            <CellTitle
              icon={<BarChart3 />}
              title="Return Distribution"
              meta={tradeCount > 0 ? `${tradeCount} trades` : (loading ? 'loading…' : undefined)}
            />
          }
          bodyClass="p-3"
        >
          <ReturnDistribution trades={perfData.realized_trades} />
        </BentoCell>

        <BentoCell
          className="col-span-12 lg:col-span-7 h-[320px]"
          header={
            <CellTitle
              icon={<Activity />}
              title="Cumulative PnL vs LLM Cost"
              meta={llmCostData.has_data ? `$${(llmCostData.total_cost_usd ?? 0).toFixed(4)} spent` : undefined}
            />
          }
          bodyClass="p-3"
        >
          <LLMTelemetry llmRecords={llmRecords} llmCostData={llmCostData} mode="cumulative" />
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
