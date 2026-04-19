"use client"

import * as React from 'react';
import {
  BarChart, Bar, XAxis, YAxis, Tooltip, ResponsiveContainer, Cell, ReferenceLine,
} from 'recharts';

export interface ConfidenceBucket {
  bucket_min: number;
  bucket_max: number;
  wins: number;
  losses: number;
  pnl?: number;
}

interface ConfidenceHistogramProps {
  data: ConfidenceBucket[];
  height?: number;
}

const CHART_STYLE = { background: 'transparent', fontSize: 10, fontFamily: 'JetBrains Mono, monospace' };

export function ConfidenceHistogram({ data, height = 256 }: ConfidenceHistogramProps) {
  const chartData = React.useMemo(() =>
    data.map(b => ({
      label: `${Math.round(b.bucket_min * 100)}–${Math.round(b.bucket_max * 100)}%`,
      wins: b.wins,
      losses: b.losses,
      total: b.wins + b.losses,
      winRate: (b.wins + b.losses) > 0 ? b.wins / (b.wins + b.losses) : null,
      pnl: b.pnl ?? null,
    })),
  [data]);

  const hasData = chartData.some(d => d.total > 0);

  if (!hasData) {
    return (
      <div className="flex flex-col items-center justify-center gap-2" style={{ height }}>
        <span className="text-xs font-mono text-[var(--muted-foreground)] opacity-40 uppercase tracking-widest">
          No calibration data yet
        </span>
      </div>
    );
  }

  return (
    <div style={{ height }}>
      <ResponsiveContainer width="100%" height={height} minWidth={0} minHeight={0}>
        <BarChart data={chartData} margin={{ top: 4, right: 8, bottom: 16, left: 4 }} style={CHART_STYLE} stackOffset="none">
          <defs>
            <linearGradient id="winGrad" x1="0" y1="0" x2="0" y2="1">
              <stop offset="5%" stopColor="var(--neon-green)" stopOpacity={0.8} />
              <stop offset="95%" stopColor="var(--neon-green)" stopOpacity={0.4} />
            </linearGradient>
            <linearGradient id="lossGrad" x1="0" y1="0" x2="0" y2="1">
              <stop offset="5%" stopColor="var(--neon-red)" stopOpacity={0.8} />
              <stop offset="95%" stopColor="var(--neon-red)" stopOpacity={0.4} />
            </linearGradient>
          </defs>
          <XAxis
            dataKey="label"
            tick={{ fill: 'var(--muted-foreground)', fontSize: 9 }}
            stroke="var(--border)"
            tickLine={false}
            axisLine={false}
            interval={1}
          />
          <YAxis
            tick={{ fill: 'var(--muted-foreground)', fontSize: 10 }}
            stroke="var(--border)"
            tickLine={false}
            axisLine={false}
            width={24}
          />
          <ReferenceLine y={0} stroke="var(--border)" strokeOpacity={0.4} />
          <Tooltip
            content={({ active, payload, label }) => {
              if (!active || !payload?.length) return null;
              const d = payload[0]?.payload;
              return (
                <div className="bg-[var(--panel)] border border-[var(--border)] px-3 py-2 shadow-lg rounded-sm text-xs font-mono">
                  <div className="text-[var(--muted-foreground)] mb-1">Confidence {label}</div>
                  <div className="text-[var(--neon-green)]">Wins: {d.wins}</div>
                  <div className="text-[var(--neon-red)]">Losses: {d.losses}</div>
                  {d.winRate != null && (
                    <div className={`mt-1 font-bold ${d.winRate >= 0.6 ? 'text-[var(--neon-green)]' : 'text-[var(--neon-red)]'}`}>
                      Win rate: {(d.winRate * 100).toFixed(0)}%
                    </div>
                  )}
                  {d.pnl !== null && (
                    <div className={`font-mono tabular-nums mt-0.5 ${d.pnl >= 0 ? 'text-[var(--neon-green)]' : 'text-[var(--neon-red)]'}`}>
                      {d.pnl >= 0 ? '+' : ''}${d.pnl.toFixed(2)} PnL
                    </div>
                  )}
                </div>
              );
            }}
          />
          <Bar dataKey="wins" stackId="a" fill="url(#winGrad)" isAnimationActive={false} radius={[0, 0, 0, 0]} />
          <Bar dataKey="losses" stackId="a" fill="url(#lossGrad)" isAnimationActive={false} radius={[2, 2, 0, 0]} />
        </BarChart>
      </ResponsiveContainer>
      <div className="flex items-center gap-3 px-2 mt-1">
        <span className="flex items-center gap-1 text-xs font-mono text-[var(--muted-foreground)] opacity-60">
          <span className="inline-block w-2 h-2 rounded-sm bg-[var(--neon-green)] opacity-70" />
          Wins
        </span>
        <span className="flex items-center gap-1 text-xs font-mono text-[var(--muted-foreground)] opacity-60">
          <span className="inline-block w-2 h-2 rounded-sm bg-[var(--neon-red)] opacity-70" />
          Losses
        </span>
        <span className="text-xs font-mono text-[var(--muted-foreground)] opacity-40 ml-auto">
          by confidence bucket
        </span>
      </div>
    </div>
  );
}
