"use client"

import * as React from 'react';

interface PerfData {
  has_data: boolean;
  net_pnl?: number;
  sharpe?: number;
  sortino?: number;
  drawdown?: number;
  realized_trades?: { pnl: number }[];
  history?: [number, number][];
}

interface RiskStatus {
  triggered: boolean;
  drawdown_pct: number;
  max_drawdown_pct: number;
}

interface LLMCostData {
  has_data: boolean;
  total_cost_usd?: number;
  cumulative_ratio?: number | null;
  cumulative_pnl?: [number, number][];
}

interface GlobalKPIsProps {
  perfData: PerfData;
  riskStatus: RiskStatus | null;
  llmCostData: LLMCostData;
  unrealizedPnl: number | null;
  positions: { unrealizedPnl: number }[];
  history: [number, number][];
}

function KpiCard({ label, value, sub, colorClass }: {
  label: string;
  value: string;
  sub?: string;
  colorClass: string;
}) {
  return (
    <div className="flex flex-col justify-between bg-[var(--panel)] border border-[var(--border)] rounded-sm p-3 gap-1 shadow-sm min-h-[72px]">
      <span className="text-xs text-[var(--muted-foreground)] uppercase tracking-wider leading-tight">{label}</span>
      <span className={`text-sm font-bold font-mono tabular-nums leading-none ${colorClass}`}>{value}</span>
      {sub && <span className="text-xs text-[var(--muted-foreground)] opacity-50 font-mono tabular-nums">{sub}</span>}
    </div>
  );
}

export function GlobalKPIs({ perfData, riskStatus, llmCostData, unrealizedPnl, positions, history }: GlobalKPIsProps) {
  const drawdown = perfData.drawdown ?? riskStatus?.drawdown_pct ?? 0;
  const maxDdPct = riskStatus?.max_drawdown_pct ?? 2;

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

  const drawdownDuration = React.useMemo(() => {
    if (!history || history.length < 2) return null;
    let peak = history[0][1];
    let peakTime = history[0][0];
    let maxDurationMs = 0;
    let inDrawdown = false;
    let ddStart = 0;
    for (const [ts, v] of history) {
      if (v >= peak) {
        if (inDrawdown) {
          maxDurationMs = Math.max(maxDurationMs, ts - ddStart);
          inDrawdown = false;
        }
        peak = v;
        peakTime = ts;
      } else if (!inDrawdown) {
        inDrawdown = true;
        ddStart = peakTime;
      }
    }
    if (inDrawdown) {
      maxDurationMs = Math.max(maxDurationMs, history[history.length - 1][0] - ddStart);
    }
    if (maxDurationMs === 0) return null;
    return Math.ceil(maxDurationMs / 86_400_000);
  }, [history]);

  const liveUnrealized = React.useMemo(() => {
    // Show — when backend reports 0 and there are no open positions (no real data yet)
    const posSum = positions.reduce((sum, p) => sum + (p.unrealizedPnl ?? 0), 0);
    if (positions.length > 0) return posSum;
    if (unrealizedPnl !== null && unrealizedPnl !== 0) return unrealizedPnl;
    return null;
  }, [unrealizedPnl, positions]);

  const llmTokenEff = React.useMemo(() => {
    if (!llmCostData.has_data || !llmCostData.total_cost_usd || llmCostData.total_cost_usd === 0) return null;
    const pnlArr = llmCostData.cumulative_pnl;
    if (!pnlArr?.length) return null;
    const totalPnl = pnlArr[pnlArr.length - 1][1];
    const costPer1M = llmCostData.total_cost_usd / 1_000_000;
    return costPer1M > 0 ? totalPnl / costPer1M : null;
  }, [llmCostData]);

  const netPnl = perfData.net_pnl ?? 0;
  const pfDisplay = profitFactor == null ? '—' : !isFinite(profitFactor) ? '∞' : profitFactor.toFixed(2);

  const kpis = [
    {
      label: 'Total Net PnL',
      value: perfData.has_data ? `${netPnl >= 0 ? '+' : ''}$${netPnl.toFixed(2)}` : '$0.00',
      colorClass: netPnl >= 0 ? 'text-[var(--neon-green)]' : 'text-[var(--neon-red)]',
    },
    {
      label: 'Unrealized PnL',
      value: liveUnrealized != null ? `${liveUnrealized >= 0 ? '+' : ''}$${liveUnrealized.toFixed(2)}` : '—',
      colorClass: liveUnrealized == null ? 'text-[var(--muted-foreground)]' : liveUnrealized >= 0 ? 'text-[var(--neon-green)]' : 'text-[var(--neon-red)]',
    },
    {
      label: 'Sharpe Ratio',
      value: perfData.has_data ? (perfData.sharpe ?? 0).toFixed(2) : '—',
      colorClass: (perfData.sharpe ?? 0) >= 1 ? 'text-[var(--neon-green)]' : 'text-[var(--foreground)]',
    },
    {
      label: 'Sortino Ratio',
      value: perfData.has_data ? (perfData.sortino ?? 0).toFixed(2) : '—',
      colorClass: (perfData.sortino ?? 0) >= 1 ? 'text-[var(--neon-green)]' : 'text-[var(--foreground)]',
    },
    {
      label: 'Max Drawdown',
      value: `${drawdown.toFixed(3)}%`,
      sub: drawdownDuration != null ? `${drawdownDuration}d duration` : undefined,
      colorClass: drawdown >= maxDdPct * 0.75 ? 'text-[var(--neon-red)]' : 'text-[var(--foreground)]',
    },
    {
      label: 'Win Rate',
      value: winRate != null ? `${winRate.toFixed(1)}%` : '—',
      colorClass: winRate == null ? 'text-[var(--muted-foreground)]' : winRate >= 50 ? 'text-[var(--neon-green)]' : 'text-[var(--neon-red)]',
    },
    {
      label: 'Profit Factor',
      value: pfDisplay,
      colorClass: profitFactor == null ? 'text-[var(--muted-foreground)]' : profitFactor >= 1.5 ? 'text-[var(--neon-green)]' : profitFactor < 1.0 ? 'text-[var(--neon-red)]' : 'text-[var(--foreground)]',
    },
    {
      label: 'LLM PnL / 1M Tokens',
      value: llmTokenEff != null ? `$${llmTokenEff.toFixed(2)}` : '—',
      colorClass: llmTokenEff == null ? 'text-[var(--muted-foreground)]' : llmTokenEff >= 0 ? 'text-[var(--neon-green)]' : 'text-[var(--neon-red)]',
    },
  ];

  return (
    <div className="grid grid-cols-2 sm:grid-cols-4 gap-2">
      {kpis.map((kpi, i) => (
        <KpiCard key={i} label={kpi.label} value={kpi.value} sub={kpi.sub} colorClass={kpi.colorClass} />
      ))}
    </div>
  );
}
