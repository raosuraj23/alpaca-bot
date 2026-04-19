"use client"

import * as React from 'react';
import {
  ComposedChart, Bar, Line, XAxis, YAxis, Tooltip, ResponsiveContainer,
  ReferenceLine, Cell,
} from 'recharts';

export interface AgentStat {
  agent: string;
  avg_confidence: number;
  win_rate: number;
  trade_count: number;
  total_pnl?: number;
}

interface SignalConfidenceChartProps {
  data: AgentStat[];
  height?: number;
}

const CHART_STYLE = { background: 'transparent', fontSize: 10, fontFamily: 'JetBrains Mono, monospace' };

function shortLabel(agent: string): string {
  // Shorten long bot IDs like "equity-breakout-nvda-v1" → "NVDA" or "equity-breakout"
  const parts = agent.split('-');
  if (parts.length >= 3) {
    // Try to extract symbol (usually 2nd-to-last before version)
    const maybeSymbol = parts[parts.length - 2];
    if (maybeSymbol && maybeSymbol !== 'v1' && maybeSymbol.length <= 6) {
      return maybeSymbol.toUpperCase();
    }
    return parts.slice(0, 2).join('-');
  }
  return agent.length > 12 ? agent.slice(0, 12) : agent;
}

export function SignalConfidenceChart({ data, height = 256 }: SignalConfidenceChartProps) {
  const chartData = React.useMemo(() =>
    data
      .filter(d => d.trade_count >= 1)
      .slice(0, 12)
      .map(d => ({
        label: shortLabel(d.agent),
        full: d.agent,
        confidence: Math.round(d.avg_confidence * 100),
        winRate: Math.round(d.win_rate * 100),
        count: d.trade_count,
        pnl: d.total_pnl ?? null,
        calibrated: Math.abs(d.avg_confidence - d.win_rate) < 0.10,
      })),
  [data]);

  const hasData = chartData.length > 0;

  if (!hasData) {
    return (
      <div className="flex flex-col items-center justify-center gap-2" style={{ height }}>
        <span className="text-xs font-mono text-[var(--muted-foreground)] opacity-40 uppercase tracking-widest">
          No signal data yet
        </span>
      </div>
    );
  }

  return (
    <div style={{ height }}>
      <ResponsiveContainer width="100%" height={height} minWidth={0} minHeight={0}>
        <ComposedChart data={chartData} margin={{ top: 4, right: 12, bottom: 20, left: 4 }} style={CHART_STYLE}>
          <XAxis
            dataKey="label"
            tick={{ fill: 'var(--muted-foreground)', fontSize: 9 }}
            stroke="var(--border)"
            tickLine={false}
            axisLine={false}
            angle={-30}
            textAnchor="end"
            interval={0}
          />
          <YAxis
            domain={[0, 100]}
            tickFormatter={v => `${v}%`}
            tick={{ fill: 'var(--muted-foreground)', fontSize: 10 }}
            stroke="var(--border)"
            tickLine={false}
            axisLine={false}
            width={32}
          />
          {/* 60% win-rate target line */}
          <ReferenceLine y={60} stroke="var(--neon-green)" strokeDasharray="4 3" strokeOpacity={0.4} />
          {/* Perfect calibration diagonal approximated as a 45° reference */}
          <ReferenceLine
            segment={[{ x: chartData[0]?.label, y: chartData[0]?.confidence ?? 50 }, { x: chartData[chartData.length - 1]?.label, y: chartData[chartData.length - 1]?.confidence ?? 50 }]}
            stroke="var(--muted-foreground)"
            strokeDasharray="2 4"
            strokeOpacity={0.25}
          />
          <Tooltip
            content={({ active, payload }) => {
              if (!active || !payload?.length) return null;
              const d = payload[0]?.payload;
              return (
                <div className="bg-[var(--panel)] border border-[var(--border)] px-3 py-2 shadow-lg rounded-sm text-xs font-mono">
                  <div className="text-[var(--foreground)] font-bold mb-1 truncate max-w-[160px]">{d.full}</div>
                  <div className="text-[var(--kraken-light)]">Avg confidence: {d.confidence}%</div>
                  <div className={d.winRate >= 60 ? 'text-[var(--neon-green)]' : 'text-[var(--neon-red)]'}>
                    Win rate: {d.winRate}%
                  </div>
                  <div className="text-[var(--muted-foreground)] opacity-60">{d.count} trades</div>
                  {d.pnl !== null && (
                    <div className={`font-mono tabular-nums mt-0.5 ${d.pnl >= 0 ? 'text-[var(--neon-green)]' : 'text-[var(--neon-red)]'}`}>
                      {d.pnl >= 0 ? '+' : ''}${d.pnl.toFixed(2)} PnL
                    </div>
                  )}
                  {d.calibrated && (
                    <div className="text-[var(--neon-green)] mt-1">Well calibrated ✓</div>
                  )}
                </div>
              );
            }}
          />
          <Bar dataKey="confidence" fill="var(--kraken-purple)" fillOpacity={0.5} isAnimationActive={false} radius={[2, 2, 0, 0]}>
            {chartData.map((d, i) => (
              <Cell key={i} fill={d.calibrated ? 'var(--kraken-light)' : 'var(--kraken-purple)'} fillOpacity={0.55} />
            ))}
          </Bar>
          <Line
            type="monotone"
            dataKey="winRate"
            stroke="var(--neon-green)"
            strokeWidth={1.5}
            dot={{ r: 3, fill: 'var(--neon-green)', strokeWidth: 0 }}
            isAnimationActive={false}
          />
        </ComposedChart>
      </ResponsiveContainer>
      <div className="flex items-center gap-3 px-2 mt-1">
        <span className="flex items-center gap-1 text-xs font-mono text-[var(--muted-foreground)] opacity-60">
          <span className="inline-block w-2 h-2 rounded-sm bg-[var(--kraken-purple)] opacity-70" />
          Avg confidence
        </span>
        <span className="flex items-center gap-1 text-xs font-mono text-[var(--muted-foreground)] opacity-60">
          <span className="inline-block w-2 h-2 rounded-full bg-[var(--neon-green)]" />
          Win rate
        </span>
        <span className="text-xs font-mono text-[var(--muted-foreground)] opacity-40 ml-auto">
          60% target —
        </span>
      </div>
    </div>
  );
}
