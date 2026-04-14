"use client"

import * as React from 'react';
import { Card, CardHeader, CardTitle, CardContent } from "@/components/ui/card";
import { useTradingStore } from '@/hooks/useTradingStream';
import { ValueTicker } from '@/components/ui/value-ticker';
import { ResponsiveLine } from '@nivo/line';

export function MarketOverview() {
  const ticker = useTradingStore(s => s.ticker);
  const marketHistory = useTradingStore(s => s.marketHistory);
  
  if (!ticker) return <div>Loading...</div>;

  const chartData = marketHistory && marketHistory.length > 0 ? [{
    id: marketHistory[0].id,
    data: marketHistory[0].data.map((p: any) => ({
      x: new Date(p.x),
      y: p.y
    }))
  }] : [];

  return (
    <Card className="h-full flex flex-col">
      <CardHeader className="flex flex-row items-center justify-between pb-2">
        <CardTitle>{ticker.symbol} Overview</CardTitle>
        <div className="text-right">
          <div className="text-2xl font-bold">
            <ValueTicker value={ticker.price} prefix="$" />
          </div>
          <div className={`text-xs ${ticker.change24h >= 0 ? 'text-[var(--neon-green)]' : 'text-[var(--neon-red)]'}`}>
            {ticker.change24h >= 0 ? '+' : ''}{ticker.change24h}% (24h)
          </div>
        </div>
      </CardHeader>
      <CardContent className="flex-1 flex items-center justify-center border-t border-[var(--border)] relative bg-[var(--panel-muted)]">
        {chartData.length > 0 ? (
          <div className="absolute inset-0">
             <ResponsiveLine
                data={chartData}
                margin={{ top: 20, right: 20, bottom: 30, left: 20 }}
                xScale={{ type: 'time' }}
                yScale={{ type: 'linear', min: 'auto', max: 'auto', stacked: false, reverse: false }}
                axisTop={null}
                axisRight={null}
                axisBottom={{
                    format: '%H:%M',
                    tickSize: 5,
                    tickPadding: 5,
                    tickRotation: 0,
                }}
                axisLeft={null}
                enableGridX={false}
                enableGridY={false}
                colors={['var(--kraken-purple)']}
                lineWidth={2}
                enablePoints={false}
                useMesh={true}
                theme={{
                   tooltip: { container: { background: 'var(--panel)', color: 'var(--foreground)', fontSize: 12, borderRadius: 4, boxShadow: '0 4px 6px -1px rgba(0, 0, 0, 0.1)' } },
                   crosshair: { line: { stroke: 'var(--muted-foreground)', strokeWidth: 1, strokeOpacity: 0.5, strokeDasharray: '4 4' } }
                }}
              />
          </div>
        ) : (
          <div className="absolute inset-0 flex flex-col items-center justify-center gap-2 opacity-40">
             <svg className="w-8 h-8 text-[var(--muted-foreground)]" fill="none" viewBox="0 0 24 24" stroke="currentColor">
               <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={1} d="M7 12l3-3 3 3 4-4M8 21l4-4 4 4M3 4h18M4 4h16v12a1 1 0 01-1 1H5a1 1 0 01-1-1V4z" />
             </svg>
             <span className="text-xs text-[var(--muted-foreground)] uppercase tracking-wider">Awaiting bar data...</span>
          </div>
        )}
      </CardContent>
    </Card>
  );
}
