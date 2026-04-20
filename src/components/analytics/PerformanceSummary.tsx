"use client"

import * as React from 'react';

interface FormulaItem {
  label: string;
  formula: string;
  note: string;
  value?: string | null;
  met?: boolean | null;
}

interface FormulaSection {
  title: string;
  items: FormulaItem[];
}

function ValueBadge({ value, met }: { value: string | null | undefined; met?: boolean | null }) {
  if (value == null) {
    return <span className="font-mono tabular-nums text-xs text-[var(--muted-foreground)] opacity-30">—</span>;
  }
  const color =
    met === true  ? 'text-[var(--neon-green)]' :
    met === false ? 'text-[var(--neon-red)]' :
    'text-[var(--kraken-light)]';
  return (
    <span className={`font-mono tabular-nums text-xs font-bold ${color}`}>{value}</span>
  );
}

interface PerformanceSummaryProps {
  winRate: number | null;
  sharpe: number | null;
  maxDrawdown: number | null;
  profitFactor: number | null;
  brierScore: number | null;
  realizedTrades?: { pnl: number }[];
  formulaMetrics?: {
    avg_ev?: number | null;
    avg_kelly?: number | null;
    avg_market_edge?: number | null;
    avg_brier?: number | null;
  };
}

export function PerformanceSummary({
  winRate,
  sharpe,
  maxDrawdown,
  profitFactor,
  brierScore,
  realizedTrades,
  formulaMetrics,
}: PerformanceSummaryProps) {

  const kelly = React.useMemo(() => {
    if (winRate == null || profitFactor == null || profitFactor <= 0) return null;
    return Math.max(0, (winRate / 100) - (1 - winRate / 100) / profitFactor) / 2;
  }, [winRate, profitFactor]);

  const ev = React.useMemo(() => {
    if (winRate == null || profitFactor == null) return null;
    return (winRate / 100) * profitFactor - (1 - winRate / 100);
  }, [winRate, profitFactor]);

  const varPct = React.useMemo(() => {
    if (!realizedTrades || realizedTrades.length < 5) return null;
    const pnls = realizedTrades.map(t => t.pnl);
    const mean = pnls.reduce((s, v) => s + v, 0) / pnls.length;
    const std = Math.sqrt(pnls.reduce((s, v) => s + (v - mean) ** 2, 0) / pnls.length);
    return mean - 1.645 * std;
  }, [realizedTrades]);

  // Prefer DB aggregates, fall back to frontend estimates
  const evVal    = formulaMetrics?.avg_ev    ?? ev;
  const kellyVal = formulaMetrics?.avg_kelly ?? kelly;
  const edgeVal  = formulaMetrics?.avg_market_edge ?? null;
  const brierVal = formulaMetrics?.avg_brier ?? brierScore;

  const fmtPct = (v: number | null | undefined) =>
    v != null ? `${(v * 100).toFixed(1)}%` : null;

  const sections: FormulaSection[] = [
    {
      title: 'Edge Detection',
      items: [
        {
          label:   'Expected Value',
          formula: 'EV = p·b - (1-p)',
          note:    'p = model prob, b = decimal odds - 1',
          value:   evVal != null ? evVal.toFixed(3) : null,
          met:     evVal != null ? evVal > 0 : null,
        },
        {
          label:   'Market Edge',
          formula: 'edge = p_model - p_mkt',
          note:    'Trade only when edge > 0.04',
          value:   edgeVal != null ? edgeVal.toFixed(3) : null,
          met:     edgeVal != null ? edgeVal > 0.04 : null,
        },
        {
          label:   'Bayes Update',
          formula: 'P(H|E) = P(E|H)·P(H) / P(E)',
          note:    'Update prior with each news signal',
          value:   null,
          met:     null,
        },
        {
          label:   'Brier Score',
          formula: 'BS = (1/n)·Σ(p_i - o_i)²',
          note:    'Lower = better calibrated model',
          value:   brierVal != null ? brierVal.toFixed(4) : null,
          met:     brierVal != null ? brierVal < 0.25 : null,
        },
      ],
    },
    {
      title: 'Position Sizing',
      items: [
        {
          label:   'Kelly Criterion',
          formula: 'f* = (p·b - q) / b',
          note:    'q = 1-p. Max fraction of bankroll',
          value:   fmtPct(kellyVal != null ? kellyVal * 2 : null),
          met:     kellyVal != null ? kellyVal > 0 : null,
        },
        {
          label:   'Fractional Kelly (25%)',
          formula: 'f = 0.25 · f*',
          note:    'Conservative sizing — reduces variance',
          value:   kellyVal != null ? fmtPct(kellyVal * 0.5) : null,
          met:     kellyVal != null ? kellyVal > 0 : null,
        },
        {
          label:   'Value at Risk 95%',
          formula: 'VaR = µ - 1.645·σ',
          note:    'Max daily loss at 95% confidence',
          value:   varPct != null ? `$${varPct.toFixed(2)}` : null,
          met:     varPct != null ? varPct > -100 : null,
        },
        {
          label:   'Max Drawdown',
          formula: 'MDD = (Peak - Trough) / Peak',
          note:    'Block new trades if MDD > 8%',
          value:   maxDrawdown != null ? `-${maxDrawdown.toFixed(2)}%` : null,
          met:     maxDrawdown != null ? maxDrawdown < 8.0 : null,
        },
      ],
    },
    {
      title: 'Arbitrage & Performance',
      items: [
        {
          label:   'ARB Condition',
          formula: 'Σ (1/odds_i) < 1 → profit',
          note:    'Sum of reciprocal odds below 1',
          value:   null,
          met:     null,
        },
        {
          label:   'Mispricing Score',
          formula: 'δ = (p_model - p_mkt) / σ',
          note:    'Z-score of model vs market divergence',
          value:   null,
          met:     null,
        },
        {
          label:   'Sharpe Ratio',
          formula: 'SR = (E[R] - Rf) / σ(R)',
          note:    'Risk-adjusted return. Target SR > 2.0',
          value:   sharpe != null ? sharpe.toFixed(2) : null,
          met:     sharpe != null ? sharpe >= 2.0 : null,
        },
        {
          label:   'Profit Factor',
          formula: 'PF = gross_profit / gross_loss',
          note:    'Healthy bot maintains PF > 1.5',
          value:   profitFactor != null
            ? (!isFinite(profitFactor) ? '∞' : profitFactor.toFixed(2))
            : null,
          met:     profitFactor != null ? profitFactor >= 1.5 : null,
        },
      ],
    },
  ];

  return (
    <div className="bg-[var(--panel)] border border-[var(--border)] rounded-sm">
      <div className="px-4 py-2 border-b border-[var(--border)] flex items-center gap-2">
        <span className="text-xs font-semibold uppercase tracking-wider text-[var(--muted-foreground)]">
          Core Formulas
        </span>
        <span className="text-xs font-mono text-[var(--muted-foreground)] opacity-40 ml-auto">
          live tracked values
        </span>
      </div>

      <div className="px-4 py-3 grid grid-cols-1 sm:grid-cols-3 gap-4">
        {sections.map((section) => (
          <div key={section.title}>
            <p className="text-xs text-[var(--foreground)] uppercase tracking-wider mb-2 opacity-60">
              {section.title}
            </p>
            <div className="flex flex-col gap-3">
              {section.items.map((item) => (
                <div key={item.label} className="flex flex-col gap-0.5">
                  <div className="flex items-center justify-between gap-2">
                    <span className="text-xs text-[var(--muted-foreground)] opacity-60">{item.label}</span>
                    <ValueBadge value={item.value} met={item.met} />
                  </div>
                  <code className="text-xs font-mono text-[var(--foreground)]">{item.formula}</code>
                  <span className="text-xs text-[var(--muted-foreground)] opacity-40">{item.note}</span>
                </div>
              ))}
            </div>
          </div>
        ))}
      </div>
    </div>
  );
}
