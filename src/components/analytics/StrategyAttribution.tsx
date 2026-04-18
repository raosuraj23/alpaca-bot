"use client"

import * as React from 'react';
import { PieChart, Pie, Cell, Tooltip, ResponsiveContainer } from 'recharts';

interface StrategyBot {
  id: string;
  name: string;
  algo: string;
  assetClass?: string;
  yield24h: number;
  signalCount?: number;
  status: string;
}

interface StrategyAttributionProps {
  bots: StrategyBot[];
}

const ASSET_COLORS: Record<string, string> = {
  CRYPTO: 'hsl(264, 80%, 65%)',
  EQUITY: 'hsl(150, 80%, 45%)',
  OPTIONS: 'hsl(40, 80%, 60%)',
};

const ALGO_COLORS = [
  'hsl(264, 80%, 65%)', 'hsl(150, 80%, 45%)', 'hsl(40, 80%, 60%)',
  'hsl(190, 70%, 60%)', 'hsl(0, 70%, 60%)', 'hsl(220, 70%, 65%)',
  'hsl(300, 60%, 60%)', 'hsl(60, 70%, 55%)',
];

export function StrategyAttribution({ bots }: StrategyAttributionProps) {
  const { innerData, outerData } = React.useMemo(() => {
    if (!bots.length) return { innerData: [], outerData: [] };

    const weight = (bot: StrategyBot) => Math.abs(bot.yield24h) || (bot.signalCount ?? 0) || 1;

    // Inner ring: by asset class
    const classMap: Record<string, number> = {};
    for (const bot of bots) {
      const ac = bot.assetClass ?? 'EQUITY';
      classMap[ac] = (classMap[ac] ?? 0) + weight(bot);
    }
    const innerData = Object.entries(classMap).map(([name, value]) => ({ name, value }));

    // Outer ring: by strategy/algo
    const algoMap: Record<string, number> = {};
    for (const bot of bots) {
      const key = bot.algo || bot.name;
      algoMap[key] = (algoMap[key] ?? 0) + weight(bot);
    }
    const outerData = Object.entries(algoMap).map(([name, value]) => ({ name, value }));

    return { innerData, outerData };
  }, [bots]);

  if (!bots.length || (!innerData.length && !outerData.length)) {
    return (
      <div className="flex items-center justify-center h-full text-xs font-mono text-[var(--muted-foreground)] opacity-40 uppercase tracking-widest">
        No strategy data
      </div>
    );
  }

  const legendItems = [...innerData.map(d => ({ name: d.name, color: ASSET_COLORS[d.name] ?? ALGO_COLORS[0], type: 'class' as const }))];

  return (
    <div className="flex flex-col h-full gap-2">
      <div style={{ height: 180 }}>
        <ResponsiveContainer width="100%" height="100%" minWidth={0} minHeight={0}>
          <PieChart>
            {/* Inner ring: asset class */}
            <Pie
              data={innerData}
              cx="50%"
              cy="50%"
              innerRadius="30%"
              outerRadius="48%"
              dataKey="value"
              strokeWidth={1}
              stroke="var(--background)"
            >
              {innerData.map((entry) => (
                <Cell key={entry.name} fill={ASSET_COLORS[entry.name] ?? ALGO_COLORS[0]} fillOpacity={0.9} />
              ))}
            </Pie>
            {/* Outer ring: strategy algo */}
            <Pie
              data={outerData}
              cx="50%"
              cy="50%"
              innerRadius="52%"
              outerRadius="72%"
              dataKey="value"
              strokeWidth={1}
              stroke="var(--background)"
            >
              {outerData.map((entry, i) => (
                <Cell key={entry.name} fill={ALGO_COLORS[i % ALGO_COLORS.length]} fillOpacity={0.75} />
              ))}
            </Pie>
            <Tooltip
              content={({ active, payload }) => {
                if (!active || !payload?.length) return null;
                const { name, value } = payload[0].payload;
                const total = (payload[0].payload.type === 'class' ? innerData : outerData).reduce((s: number, d: any) => s + d.value, 0);
                const pct = total > 0 ? ((value / total) * 100).toFixed(1) : '0';
                return (
                  <div className="bg-[var(--panel)] border border-[var(--border)] px-3 py-2 shadow-lg rounded-sm">
                    <div className="text-xs font-mono text-[var(--foreground)] font-bold">{name}</div>
                    <div className="text-xs font-mono tabular-nums text-[var(--muted-foreground)]">{pct}% weight</div>
                  </div>
                );
              }}
            />
          </PieChart>
        </ResponsiveContainer>
      </div>

      {/* Legend */}
      <div className="flex flex-wrap gap-x-3 gap-y-1 px-1 shrink-0">
        {legendItems.map(item => (
          <div key={item.name} className="flex items-center gap-1.5">
            <span className="w-2 h-2 rounded-sm shrink-0" style={{ background: item.color }} />
            <span className="text-xs font-mono text-[var(--muted-foreground)]">{item.name}</span>
          </div>
        ))}
      </div>
    </div>
  );
}
