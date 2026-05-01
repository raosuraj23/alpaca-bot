"use client"

import * as React from 'react';
import { API_BASE } from '@/lib/api';
import { useTradingStore } from '@/store';
import {
  ShieldAlert, TrendingUp, TrendingDown, BarChart3,
  BrainCircuit, Zap, Activity,
} from 'lucide-react';

import { GlobalKPIs } from './GlobalKPIs';
import { EquityCurveTerminal } from './EquityCurveTerminal';
import { ReturnDistribution } from './ReturnDistribution';
import { LLMBreakdown, type LLMBreakdownData } from './LLMBreakdown';
import { LLMTelemetry } from './LLMTelemetry';
import { ConfidenceHistogram, type ConfidenceBucket } from './ConfidenceHistogram';
import { SignalConfidenceChart, type AgentStat } from './SignalConfidenceChart';

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

interface FormulaMetrics {
  avg_ev?: number | null;
  avg_kelly?: number | null;
  avg_market_edge?: number | null;
  avg_brier?: number | null;
}

interface SignalsData {
  has_data?: boolean;
  avg_market_edge?: number | null;
  avg_mispricing_z?: number | null;
  avg_bayes_update?: number | null;
  arb_score?: number | null;
  by_agent?: AgentStat[];
  confidence_distribution?: ConfidenceBucket[];
}

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
  const unrealizedPnl = useTradingStore(s => s.unrealizedPnl);
  const positions     = useTradingStore(s => s.positions);
  const lastSignal    = useTradingStore(s => s.lastSignal);

  const [period, setPeriod]   = React.useState<Period>('1D');
  const [loading, setLoading] = React.useState(false);
  const [perfData, setPerfData] = React.useState(performance);
  const [llmCostData, setLlmCostData] = React.useState<LLMCostData>({
    has_data: false, cumulative_cost: [], cumulative_pnl: [],
  });
  const [llmBreakdown, setLlmBreakdown] = React.useState<LLMBreakdownData>({
    has_data: false, total_calls: 0, total_tokens_in: 0, total_tokens_out: 0,
    total_cost_usd: 0, by_model: [], by_purpose: [], recent: [],
  });
  const [signalsData, setSignalsData] = React.useState<SignalsData>({ has_data: false });

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
    if (performance.has_data && period === '1D') setPerfData(performance);
  }, [performance, period]);

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

  React.useEffect(() => {
    let cancelled = false;
    const load = () =>
      fetch(`${API_BASE}/api/analytics/signals?period=${period}`)
        .then(r => r.ok ? r.json() : null)
        .then(d => { if (d && !cancelled) setSignalsData(d); })
        .catch(() => {});
    load();
    const id = setInterval(load, 30_000);
    return () => { cancelled = true; clearInterval(id); };
  }, [period]);

  const history    = (perfData.history ?? []) as [number, number][];
  const killActive = riskStatus?.triggered ?? false;
  const netPnl     = perfData.net_pnl ?? 0;
  const tradeCount = (perfData.realized_trades ?? []).length;
  const maxDd      = perfData.drawdown ?? 0;

  const winRate = React.useMemo(() => {
    const trades = perfData.realized_trades;
    if (!trades?.length) return null;
    return (trades.filter(t => t.pnl > 0).length / trades.length) * 100;
  }, [perfData.realized_trades]);

  const profitFactor = React.useMemo(() => {
    const trades = perfData.realized_trades;
    if (!trades?.length) return null;
    const gw = trades.filter(t => t.pnl > 0).reduce((s, t) => s + t.pnl, 0);
    const gl = trades.filter(t => t.pnl < 0).reduce((s, t) => s + Math.abs(t.pnl), 0);
    if (gl === 0) return gw > 0 ? Infinity : null;
    return gw / gl;
  }, [perfData.realized_trades]);

  const formulaMetrics = (perfData as typeof perfData & { formula_metrics?: FormulaMetrics }).formula_metrics;

  return (
    <div className="flex flex-col h-full min-h-0 gap-3 overflow-y-auto pr-1 pb-4">

      {killActive && (
        <div className="flex items-center gap-3 px-4 py-2.5 rounded-sm border border-[var(--neon-red)]/60 bg-[var(--neon-red)]/10 text-[var(--neon-red)] text-xs font-bold uppercase tracking-widest animate-pulse shrink-0">
          <ShieldAlert className="w-4 h-4 shrink-0" />
          Kill Switch Active — {riskStatus?.reason ?? 'Trading Halted'}
        </div>
      )}

      {/* ── Bento Grid ── */}
      <div className="grid grid-cols-12 gap-3">

        {/* Row 1 — KPI Strip + inline period filter */}
        <div className="col-span-12 flex flex-col gap-2">
          {/* Period filter sits above GlobalKPIs, no extra row */}
          <div className="flex items-center gap-2">
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
          <GlobalKPIs
            perfData={perfData}
            riskStatus={riskStatus}
            llmCostData={llmCostData}
            unrealizedPnl={unrealizedPnl}
            positions={positions}
            history={history}
            winRate={winRate}
            sharpe={perfData.sharpe ?? null}
            maxDrawdown={maxDd}
            profitFactor={profitFactor}
            brierScore={(perfData as { brier_score?: number | null }).brier_score ?? null}
            formulaMetrics={formulaMetrics}
            signalsData={signalsData}
          />
        </div>

        {/* Row 2 — Equity Curve (6) | Confidence Distribution (6, replaces Drawdown) */}
        <BentoCell
          className="col-span-12 lg:col-span-6 h-[260px]"
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
          className="col-span-12 lg:col-span-6 h-[260px]"
          header={
            <CellTitle
              icon={<BarChart3 />}
              title="Confidence Distribution"
              meta={signalsData.has_data ? `calibration` : undefined}
            />
          }
          bodyClass="p-3"
        >
          <ConfidenceHistogram data={signalsData.confidence_distribution ?? []} height={256} />
        </BentoCell>

        {/* Rows 3+4 — 3-col layout at lg+: Return Distribution | LLM Telemetry | LLM Intelligence | Signal Confidence (wraps) */}
        <BentoCell
          className="col-span-12 lg:col-span-6 h-[260px]"
          header={
            <CellTitle
              icon={<BarChart3 />}
              title="Return Distribution"
              meta={tradeCount > 0 ? `${tradeCount} trades` : (loading ? 'loading…' : undefined)}
            />
          }
          bodyClass="p-3"
        >
          <ReturnDistribution trades={perfData.realized_trades} height={208} />
        </BentoCell>

        <BentoCell
          className="col-span-12 lg:col-span-6 h-[260px]"
          header={
            <CellTitle
              icon={<Zap />}
              title="LLM Telemetry"
              meta={llmCostData.cumulative_ratio != null
                ? `$${llmCostData.cumulative_ratio.toFixed(4)}/trade`
                : undefined}
            />
          }
          bodyClass="p-3"
        >
          <LLMTelemetry llmRecords={[]} llmCostData={llmCostData} mode="cumulative" height={208} />
        </BentoCell>

        <BentoCell
          className="col-span-12 lg:col-span-6 h-[260px]"
          header={
            <CellTitle
              icon={<BrainCircuit />}
              title="LLM Intelligence"
              meta={llmBreakdown.has_data ? `${llmBreakdown.total_calls} calls` : undefined}
            />
          }
          bodyClass="p-3"
        >
          <LLMBreakdown data={llmBreakdown} height={208} />
        </BentoCell>

        <BentoCell
          className="col-span-12 lg:col-span-6 h-[260px]"
          header={
            <CellTitle
              icon={<Activity />}
              title="Signal Confidence vs Win Rate"
              meta={signalsData.by_agent?.length ? `${signalsData.by_agent.length} agents` : undefined}
            />
          }
          bodyClass="p-3"
        >
          <SignalConfidenceChart data={signalsData.by_agent ?? []} height={208} />
        </BentoCell>

      </div>
    </div>
  );
}
