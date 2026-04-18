"use client"

import * as React from 'react';
import {
  BarChart, Bar, XAxis, YAxis, Tooltip, ResponsiveContainer, ReferenceLine,
} from 'recharts';
import { BarChart3 } from 'lucide-react';

const CHART_STYLE = { background: 'transparent', fontSize: 11, fontFamily: 'JetBrains Mono, monospace' };
const N_BINS = 16;

interface ReturnDistributionProps {
  trades: { pnl: number }[] | undefined;
  /** Explicit chart height in px. Must match the parent bento cell body area. */
  height?: number;
}

export function ReturnDistribution({ trades, height = 256 }: ReturnDistributionProps) {
  const bins = React.useMemo(() => {
    if (!trades || trades.length === 0) return null;
    const pnls = trades.map(t => t.pnl);
    const minP = Math.min(...pnls);
    const maxP = Math.max(...pnls);
    const bw = (maxP - minP || 1) / N_BINS;
    const counts = new Array(N_BINS).fill(0);
    pnls.forEach(p => { counts[Math.min(Math.floor((p - minP) / bw), N_BINS - 1)]++; });
    return counts.map((count, i) => ({
      mid: minP + (i + 0.5) * bw,
      count,
    }));
  }, [trades]);

  if (!bins) {
    return (
      <div className="flex flex-col items-center justify-center gap-2" style={{ height }}>
        <BarChart3 className="w-5 h-5 text-[var(--muted-foreground)] opacity-20" />
        <span className="text-xs font-mono text-[var(--muted-foreground)] opacity-40 uppercase tracking-widest text-center">
          Need closed trades
        </span>
      </div>
    );
  }

  return (
    // Explicit pixel height prevents Recharts width(-1)/height(-1) warning
    <div style={{ height }}>
      <ResponsiveContainer width="100%" height="100%" minWidth={0} minHeight={0}>
        <BarChart data={bins} margin={{ top: 4, right: 8, bottom: 4, left: 8 }} style={CHART_STYLE}>
          <XAxis
            dataKey="mid"
            tickFormatter={(v) => `$${Number(v).toFixed(0)}`}
            tick={{ fill: 'var(--muted-foreground)', fontSize: 10 }}
            stroke="var(--border)" tickLine={false} axisLine={false}
            interval="preserveStartEnd"
          />
          <YAxis
            tick={{ fill: 'var(--muted-foreground)', fontSize: 10 }}
            stroke="var(--border)" tickLine={false} axisLine={false} width={20}
          />
          <ReferenceLine x={0} stroke="var(--border)" strokeDasharray="3 3" strokeOpacity={0.6} />
          <Tooltip
            content={({ active, payload }) => {
              if (!active || !payload?.length) return null;
              const { mid, count } = payload[0].payload;
              return (
                <div className="bg-[var(--panel)] border border-[var(--border)] px-3 py-2 shadow-lg rounded-sm">
                  <div className="text-xs text-[var(--muted-foreground)]">around ${Number(mid).toFixed(2)}</div>
                  <div className="text-sm font-mono font-bold tabular-nums text-[var(--foreground)]">{count} trades</div>
                </div>
              );
            }}
          />
          <Bar
            dataKey="count"
            isAnimationActive={false}
            shape={(props: any) => {
              const { x, y, width, height: h, mid } = props;
              const fill = Number(mid) >= 0 ? 'var(--neon-green)' : 'var(--neon-red)';
              return <rect x={x} y={y} width={width} height={Math.max(h, 0)} fill={fill} rx={1} ry={1} />;
            }}
          />
        </BarChart>
      </ResponsiveContainer>
    </div>
  );
}
