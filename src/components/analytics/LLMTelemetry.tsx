"use client"

import * as React from 'react';
import {
  ScatterChart, Scatter, XAxis, YAxis, Tooltip, ResponsiveContainer,
  ComposedChart, Area, Line, CartesianGrid,
} from 'recharts';
import type { LLMExecutionRecord } from '@/lib/types';

const CHART_STYLE = { background: 'transparent', fontSize: 11, fontFamily: 'JetBrains Mono, monospace' };

const ASSET_DOT_COLORS: Record<string, string> = {
  CRYPTO: 'var(--kraken-purple)',
  EQUITY: 'var(--neon-green)',
  OPTIONS: 'var(--warning)',
};

interface LLMCostData {
  has_data: boolean;
  cumulative_cost: [number, number][];
  cumulative_pnl: [number, number][];
  total_cost_usd?: number;
  cumulative_ratio?: number | null;
}

interface LLMTelemetryProps {
  llmRecords: LLMExecutionRecord[];
  llmCostData: LLMCostData;
  /** 'scatter' = only latency vs PnL; 'cumulative' = only cumulative cost chart; 'both' = stacked (default) */
  mode?: 'scatter' | 'cumulative' | 'both';
  /** Explicit chart height in px. Must match the parent bento cell body area. */
  height?: number;
}

function EmptyState({ text }: { text: string }) {
  return (
    <div className="flex items-center justify-center h-full text-xs font-mono text-[var(--muted-foreground)] opacity-30 uppercase tracking-widest">
      {text}
    </div>
  );
}

function ScatterPane({ llmRecords, height = 256 }: { llmRecords: LLMExecutionRecord[]; height?: number }) {
  // Use costUsd (in millicents) vs tradePnl — latencyMs is not available in daily aggregate data
  const scatterData = React.useMemo(() =>
    llmRecords
      .filter(r => r.tradePnl != null && r.costUsd > 0)
      .map(r => ({
        costMc: r.costUsd * 1000,
        pnl: r.tradePnl!,
        assetClass: r.assetClass,
        strategy: r.strategy,
        date: new Date(r.timestamp).toLocaleDateString(undefined, { month: 'short', day: 'numeric' }),
      })),
    [llmRecords],
  );

  const scatterByClass = React.useMemo(() => {
    const map: Record<string, { costMc: number; pnl: number; date: string; strategy: string }[]> = {};
    for (const d of scatterData) {
      if (!map[d.assetClass]) map[d.assetClass] = [];
      map[d.assetClass].push({ costMc: d.costMc, pnl: d.pnl, date: d.date, strategy: d.strategy });
    }
    return map;
  }, [scatterData]);

  const legendH = 20;
  const chartH = height - legendH - 4;

  if (!scatterData.length) {
    return <EmptyState text="No daily cost/PnL data yet" />;
  }

  return (
    <div className="flex flex-col gap-1" style={{ height }}>
      <div style={{ height: chartH }}>
        <ResponsiveContainer width="100%" height={chartH} minWidth={0} minHeight={0}>
          <ScatterChart margin={{ top: 4, right: 8, bottom: 4, left: 40 }} style={CHART_STYLE}>
            <CartesianGrid strokeDasharray="4 4" stroke="var(--border)" strokeOpacity={0.3} />
            <XAxis
              type="number" dataKey="costMc" name="LLM Cost"
              tickFormatter={(v) => `${Number(v).toFixed(2)}m¢`}
              tick={{ fill: 'var(--muted-foreground)', fontSize: 10 }}
              stroke="var(--border)" tickLine={false} axisLine={false}
            />
            <YAxis
              type="number" dataKey="pnl" name="PnL"
              tickFormatter={(v) => `$${Number(v).toFixed(0)}`}
              tick={{ fill: 'var(--muted-foreground)', fontSize: 10 }}
              stroke="var(--border)" tickLine={false} axisLine={false} width={40}
            />
            <Tooltip
              cursor={{ strokeDasharray: '3 3', stroke: 'var(--border)' }}
              content={({ active, payload }) => {
                if (!active || !payload?.length) return null;
                const { costMc, pnl, date, strategy } = payload[0].payload;
                return (
                  <div className="bg-[var(--panel)] border border-[var(--border)] px-3 py-2 shadow-lg rounded-sm">
                    <div className="text-xs font-mono tabular-nums text-[var(--muted-foreground)]">{date}</div>
                    {strategy && strategy !== 'aggregate' && (
                      <div className="text-xs font-mono text-[var(--muted-foreground)] opacity-70">{strategy}</div>
                    )}
                    <div className="text-xs font-mono tabular-nums text-[var(--muted-foreground)]">Cost: {Number(costMc).toFixed(3)}m¢</div>
                    <div className={`text-xs font-mono font-bold tabular-nums ${pnl >= 0 ? 'text-[var(--neon-green)]' : 'text-[var(--neon-red)]'}`}>
                      PnL: {pnl >= 0 ? '+' : ''}${pnl.toFixed(2)}
                    </div>
                  </div>
                );
              }}
            />
            {Object.entries(scatterByClass).map(([cls, pts]) => (
              <Scatter
                key={cls}
                name={cls}
                data={pts}
                fill={ASSET_DOT_COLORS[cls] ?? 'var(--muted-foreground)'}
                fillOpacity={0.7}
                r={4}
              />
            ))}
          </ScatterChart>
        </ResponsiveContainer>
      </div>
      <div className="flex gap-3 px-1" style={{ height: legendH }}>
        {Object.keys(scatterByClass).map(cls => (
          <div key={cls} className="flex items-center gap-1">
            <span className="w-2 h-2 rounded-sm" style={{ background: ASSET_DOT_COLORS[cls] }} />
            <span className="text-xs font-mono text-[var(--muted-foreground)]">{cls}</span>
          </div>
        ))}
      </div>
    </div>
  );
}

function CumulativePane({ llmCostData, height = 256 }: { llmCostData: LLMCostData; height?: number }) {
  const chartData = React.useMemo(() => {
    if (!llmCostData.cumulative_pnl?.length && !llmCostData.cumulative_cost?.length) return [];
    const pnlMap = new Map(llmCostData.cumulative_pnl.map(([ts, v]) => [ts, v]));
    const costMap = new Map(llmCostData.cumulative_cost.map(([ts, v]) => [ts, v]));
    const allTs = [...new Set([...pnlMap.keys(), ...costMap.keys()])].sort();
    return allTs.map(ts => ({
      ts,
      pnl: pnlMap.get(ts) ?? 0,
      cost: (costMap.get(ts) ?? 0) * 1000,
    }));
  }, [llmCostData]);

  if (!chartData.length) {
    return <EmptyState text="No LLM cost data yet" />;
  }

  return (
    <div style={{ height }}>
      <ResponsiveContainer width="100%" height={height} minWidth={0} minHeight={0}>
        <ComposedChart data={chartData} margin={{ top: 8, right: 48, bottom: 4, left: 48 }} style={CHART_STYLE}>
          <CartesianGrid strokeDasharray="4 4" stroke="var(--border)" strokeOpacity={0.3} vertical={false} />
          <XAxis
            dataKey="ts" type="number" domain={['dataMin', 'dataMax']} scale="time"
            tickFormatter={(v) => new Date(v).toLocaleDateString()}
            tick={{ fill: 'var(--muted-foreground)', fontSize: 10 }}
            stroke="var(--border)" tickLine={false} axisLine={false}
          />
          <YAxis
            yAxisId="pnl"
            tickFormatter={(v) => `$${Number(v).toFixed(0)}`}
            tick={{ fill: 'var(--muted-foreground)', fontSize: 10 }}
            stroke="var(--border)" tickLine={false} axisLine={false} width={44}
          />
          <YAxis
            yAxisId="cost" orientation="right"
            tickFormatter={(v) => `${Number(v).toFixed(1)}m¢`}
            tick={{ fill: 'var(--muted-foreground)', fontSize: 10 }}
            stroke="var(--border)" tickLine={false} axisLine={false} width={44}
          />
          <Tooltip
            content={({ active, payload, label }) => {
              if (!active || !payload?.length) return null;
              return (
                <div className="bg-[var(--panel)] border border-[var(--border)] px-3 py-2 shadow-lg rounded-sm">
                  <div className="text-xs text-[var(--muted-foreground)] mb-1">{new Date(Number(label ?? 0)).toLocaleDateString()}</div>
                  {payload.map((p, i) => (
                    <div key={i} className="text-xs font-mono tabular-nums" style={{ color: String(p.stroke ?? p.fill) }}>
                      {p.name === 'pnl' ? `PnL: $${Number(p.value).toFixed(2)}` : `Cost: ${Number(p.value).toFixed(3)}m¢`}
                    </div>
                  ))}
                </div>
              );
            }}
          />
          <Area
            yAxisId="cost" type="monotone" dataKey="cost" name="cost"
            stroke="var(--neon-red)" fill="var(--neon-red)" fillOpacity={0.1}
            strokeWidth={1.5} dot={false}
          />
          <Line
            yAxisId="pnl" type="monotone" dataKey="pnl" name="pnl"
            stroke="var(--neon-green)" strokeWidth={2} dot={false}
            activeDot={{ r: 3 }}
          />
        </ComposedChart>
      </ResponsiveContainer>
    </div>
  );
}

export function LLMTelemetry({ llmRecords, llmCostData, mode = 'both', height = 256 }: LLMTelemetryProps) {
  if (mode === 'scatter') {
    return <ScatterPane llmRecords={llmRecords} height={height} />;
  }
  if (mode === 'cumulative') {
    return <CumulativePane llmCostData={llmCostData} height={height} />;
  }

  const halfH = Math.floor((height - 40) / 2);
  // 'both' — stacked
  return (
    <div className="flex flex-col gap-4" style={{ height }}>
      <div>
        <div className="text-xs font-mono text-[var(--muted-foreground)] uppercase tracking-widest mb-1 px-1">
          Daily LLM Cost vs PnL
        </div>
        <ScatterPane llmRecords={llmRecords} height={halfH} />
      </div>
      <div>
        <div className="text-xs font-mono text-[var(--muted-foreground)] uppercase tracking-widest mb-1 px-1">
          Cumulative PnL vs LLM Cost
        </div>
        <CumulativePane llmCostData={llmCostData} height={halfH} />
      </div>
    </div>
  );
}
