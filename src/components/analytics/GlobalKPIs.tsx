"use client"

import * as React from 'react';

interface FormulaMetrics {
  avg_ev?: number | null;
  avg_kelly?: number | null;
  avg_market_edge?: number | null;
  avg_brier?: number | null;
}

interface PerfData {
  has_data: boolean;
  net_pnl?: number;
  sharpe?: number;
  sortino?: number;
  drawdown?: number;
  realized_trades?: { pnl: number }[];
  history?: [number, number][];
  brier_score?: number | null;
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

interface SignalsData {
  has_data?: boolean;
  avg_market_edge?: number | null;
  avg_mispricing_z?: number | null;
  avg_bayes_update?: number | null;
  arb_score?: number | null;
}

interface GlobalKPIsProps {
  perfData: PerfData;
  riskStatus: RiskStatus | null;
  llmCostData: LLMCostData;
  unrealizedPnl: number | null;
  positions: { unrealizedPnl: number }[];
  history: [number, number][];
  winRate: number | null;
  sharpe: number | null;
  maxDrawdown: number;
  profitFactor: number | null;
  brierScore: number | null;
  formulaMetrics?: FormulaMetrics;
  signalsData?: SignalsData;
}

function FormulaRow({ label, formula, note, value, met }: {
  label: string;
  formula: string;
  note: string;
  value: string | null;
  met: boolean | null;
}) {
  const valueColor =
    met === true  ? 'text-[var(--neon-green)]' :
    met === false ? 'text-[var(--neon-red)]' :
    'text-[var(--kraken-light)]';

  return (
    <div className="flex flex-col gap-0.5">
      <div className="flex items-baseline justify-between gap-2">
        <span className="text-xs text-[var(--muted-foreground)] opacity-60 leading-tight">{label}</span>
        {value != null
          ? <span className={`font-mono tabular-nums text-xs font-bold shrink-0 ${valueColor}`}>{value}</span>
          : <span className="font-mono tabular-nums text-xs text-[var(--muted-foreground)] opacity-30 shrink-0">—</span>
        }
      </div>
      <code className="text-xs font-mono text-[var(--foreground)] opacity-70">{formula}</code>
      <span className="text-xs text-[var(--muted-foreground)] opacity-40">{note}</span>
    </div>
  );
}

export function GlobalKPIs({
  perfData, riskStatus, llmCostData, unrealizedPnl, positions,
  winRate, sharpe, maxDrawdown, profitFactor, brierScore, formulaMetrics, signalsData,
}: GlobalKPIsProps) {

  const kelly = React.useMemo(() => {
    if (winRate == null || profitFactor == null || profitFactor <= 0) return null;
    return Math.max(0, (winRate / 100) - (1 - winRate / 100) / profitFactor) / 2;
  }, [winRate, profitFactor]);

  const ev = React.useMemo(() => {
    if (winRate == null || profitFactor == null) return null;
    return (winRate / 100) * profitFactor - (1 - winRate / 100);
  }, [winRate, profitFactor]);

  const varPct = React.useMemo(() => {
    const trades = perfData.realized_trades;
    if (!trades || trades.length < 5) return null;
    const pnls = trades.map(t => t.pnl);
    const mean = pnls.reduce((s, v) => s + v, 0) / pnls.length;
    const std = Math.sqrt(pnls.reduce((s, v) => s + (v - mean) ** 2, 0) / pnls.length);
    return mean - 1.645 * std;
  }, [perfData.realized_trades]);

  const liveUnrealized = React.useMemo(() => {
    const posSum = positions.reduce((sum, p) => sum + (p.unrealizedPnl ?? 0), 0);
    if (positions.length > 0) return posSum;
    if (unrealizedPnl !== null && unrealizedPnl !== 0) return unrealizedPnl;
    return null;
  }, [unrealizedPnl, positions]);

  // LLM PnL / AI Cost — ratio of net PnL to total LLM spend
  const llmRoi = React.useMemo(() => {
    if (!llmCostData.has_data || !llmCostData.total_cost_usd || llmCostData.total_cost_usd === 0) return null;
    const pnlArr = llmCostData.cumulative_pnl;
    if (!pnlArr?.length) return null;
    const totalPnl = pnlArr[pnlArr.length - 1][1];
    return totalPnl / llmCostData.total_cost_usd;
  }, [llmCostData]);

  // Prefer live signals data, fall back to ClosedTrade aggregates, then frontend estimates
  const evVal    = formulaMetrics?.avg_ev          ?? ev;
  const kellyVal = formulaMetrics?.avg_kelly       ?? kelly;
  const edgeVal  = signalsData?.avg_market_edge    ?? formulaMetrics?.avg_market_edge ?? null;
  const brierVal = formulaMetrics?.avg_brier       ?? brierScore;
  const mispricingZ = signalsData?.avg_mispricing_z ?? null;
  const bayesUpd    = signalsData?.avg_bayes_update ?? null;
  const arbScore    = signalsData?.arb_score        ?? null;

  const fmtPct = (v: number | null | undefined) =>
    v != null ? `${(v * 100).toFixed(1)}%` : null;

  const netPnl = perfData.net_pnl ?? 0;
  const pfDisplay = profitFactor == null ? null : !isFinite(profitFactor) ? '∞' : profitFactor.toFixed(2);

  return (
    <div className="bg-[var(--panel)] border border-[var(--border)] rounded-sm">
      <div className="px-4 py-2 border-b border-[var(--border)] flex items-center gap-2">
        <span className="text-xs font-semibold uppercase tracking-wider text-[var(--muted-foreground)]">
          Core Formulas
        </span>
        <span className="text-xs font-mono text-[var(--muted-foreground)] opacity-40 ml-auto">live tracked values</span>
      </div>

      <div className="grid grid-cols-2 lg:grid-cols-4 divide-x divide-[var(--border)]">

        {/* Col 1 — Edge Detection */}
        <div className="px-4 py-3 flex flex-col gap-3">
          <p className="text-xs uppercase tracking-wider text-[var(--foreground)] opacity-60">Edge Detection</p>
          <FormulaRow
            label="Expected Value"
            formula="EV = p·b - (1-p)"
            note="p = model prob, b = decimal odds - 1"
            value={evVal != null ? evVal.toFixed(3) : null}
            met={evVal != null ? evVal > 0 : null}
          />
          <FormulaRow
            label="Market Edge"
            formula="edge = p_model - p_mkt"
            note="Trade only when edge > 0.04"
            value={edgeVal != null ? edgeVal.toFixed(3) : null}
            met={edgeVal != null ? edgeVal > 0.04 : null}
          />
          <FormulaRow
            label="Bayes Update"
            formula="P(H|E) / P(H) = xgb_prob / p_mkt"
            note="Ratio > 1 means model is more bullish than market"
            value={bayesUpd != null ? `${bayesUpd.toFixed(2)}x` : null}
            met={bayesUpd != null ? bayesUpd > 1.0 : null}
          />
          <FormulaRow
            label="Brier Score"
            formula="BS = (1/n)·Σ(p_i - o_i)²"
            note="Lower = better calibrated model"
            value={brierVal != null ? brierVal.toFixed(4) : null}
            met={brierVal != null ? brierVal < 0.25 : null}
          />
        </div>

        {/* Col 2 — Position Sizing */}
        <div className="px-4 py-3 flex flex-col gap-3">
          <p className="text-xs uppercase tracking-wider text-[var(--foreground)] opacity-60">Position Sizing</p>
          <FormulaRow
            label="Kelly Criterion"
            formula="f* = (p·b - q) / b"
            note="q = 1-p. Max fraction of bankroll"
            value={fmtPct(kellyVal != null ? kellyVal * 2 : null)}
            met={kellyVal != null ? kellyVal > 0 : null}
          />
          <FormulaRow
            label="Fractional Kelly (25%)"
            formula="f = 0.25 · f*"
            note="Conservative sizing — reduces variance"
            value={kellyVal != null ? fmtPct(kellyVal * 0.5) : null}
            met={kellyVal != null ? kellyVal > 0 : null}
          />
          <FormulaRow
            label="Value at Risk 95%"
            formula="VaR = µ - 1.645·σ"
            note="Max daily loss at 95% confidence"
            value={varPct != null ? `$${varPct.toFixed(2)}` : null}
            met={varPct != null ? varPct > -100 : null}
          />
          <FormulaRow
            label="Max Drawdown"
            formula="MDD = (Peak - Trough) / Peak"
            note="Block new trades if MDD > 8%"
            value={`-${maxDrawdown.toFixed(2)}%`}
            met={maxDrawdown < 8.0}
          />
        </div>

        {/* Col 3 — Arbitrage & Performance */}
        <div className="px-4 py-3 flex flex-col gap-3">
          <p className="text-xs uppercase tracking-wider text-[var(--foreground)] opacity-60">Arb & Performance</p>
          <FormulaRow
            label="ARB Condition"
            formula="model_edge_rate = Σ(xgb > p_mkt) / N"
            note="Fraction of signals where model beats market"
            value={arbScore != null ? `${(arbScore * 100).toFixed(1)}%` : null}
            met={arbScore != null ? arbScore > 0.5 : null}
          />
          <FormulaRow
            label="Mispricing Score"
            formula="δ = (p_model - p_mkt) / σ"
            note="Z-score of model vs market divergence"
            value={mispricingZ != null ? mispricingZ.toFixed(3) : null}
            met={mispricingZ != null ? Math.abs(mispricingZ) > 1.0 : null}
          />
          <FormulaRow
            label="Sharpe Ratio"
            formula="SR = (E[R] - Rf) / σ(R)"
            note="Risk-adjusted return. Target SR > 2.0"
            value={sharpe != null ? sharpe.toFixed(2) : null}
            met={sharpe != null ? sharpe >= 2.0 : null}
          />
          <FormulaRow
            label="Profit Factor"
            formula="PF = gross_profit / gross_loss"
            note="Healthy bot maintains PF > 1.5"
            value={pfDisplay}
            met={profitFactor != null ? profitFactor >= 1.5 : null}
          />
        </div>

        {/* Col 4 — LLM & PnL */}
        <div className="px-4 py-3 flex flex-col gap-3">
          <p className="text-xs uppercase tracking-wider text-[var(--foreground)] opacity-60">LLM & PnL</p>
          <FormulaRow
            label="PnL / AI Cost"
            formula="net_pnl / total_llm_cost_usd"
            note="PnL generated per $1 of AI spend"
            value={llmRoi != null ? `${llmRoi.toFixed(1)}x` : null}
            met={llmRoi == null ? null : llmRoi >= 0}
          />
          <FormulaRow
            label="Win Rate"
            formula="W = wins / total trades"
            note="Target ≥ 60%"
            value={winRate != null ? `${winRate.toFixed(1)}%` : null}
            met={winRate == null ? null : winRate >= 60}
          />
          <FormulaRow
            label="Realized PnL"
            formula="Σ closed trade PnL"
            note="Net of commissions"
            value={perfData.has_data ? `${netPnl >= 0 ? '+' : ''}$${netPnl.toFixed(2)}` : null}
            met={perfData.has_data ? netPnl >= 0 : null}
          />
          <FormulaRow
            label="Unrealized PnL"
            formula="Σ mark-to-market open positions"
            note="Excludes closed trades"
            value={liveUnrealized != null ? `${liveUnrealized >= 0 ? '+' : ''}$${liveUnrealized.toFixed(2)}` : null}
            met={liveUnrealized == null ? null : liveUnrealized >= 0}
          />
        </div>

      </div>
    </div>
  );
}
