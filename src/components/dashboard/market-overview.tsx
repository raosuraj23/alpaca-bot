"use client"

import * as React from 'react';
import { Card, CardHeader, CardTitle, CardContent } from "@/components/ui/card";
import { useTradingStore } from '@/hooks/useTradingStream';
import { ValueTicker } from '@/components/ui/value-ticker';
import { createChart, AreaSeries } from 'lightweight-charts';
import type { IChartApi, Time } from 'lightweight-charts';
import { cssVar } from '@/lib/utils';

export function MarketOverview() {
  const ticker        = useTradingStore(s => s.ticker);
  const marketHistory = useTradingStore(s => s.marketHistory);
  const chartContainer = React.useRef<HTMLDivElement>(null);
  const chartRef       = React.useRef<IChartApi | null>(null);

  // Convert Nivo-format marketHistory [{id, data:[{x:isostring, y:price}]}]
  // into lightweight-charts [{time: unix_seconds, value}]
  const chartPoints = React.useMemo(() => {
    if (!marketHistory?.length || !marketHistory[0]?.data?.length) return [];
    return marketHistory[0].data.map((p: { x: string; y: number }) => ({
      time:  Math.floor(new Date(p.x).getTime() / 1000) as Time,
      value: p.y,
    }));
  }, [marketHistory]);

  React.useEffect(() => {
    const el = chartContainer.current;
    if (!el || chartPoints.length === 0) return;

    chartRef.current?.remove();

    // Resolve CSS variables at effect time — lightweight-charts uses canvas, not CSS
    const text         = cssVar('--muted-foreground');
    const border       = cssVar('--border');
    const purple       = cssVar('--kraken-purple');
    const purpleFill   = cssVar('--kraken-purple-fill');

    const chart = createChart(el, {
      layout: {
        background: { color: 'transparent' },
        textColor:  text,
        fontSize:   10,
        fontFamily: 'JetBrains Mono, monospace',
      },
      grid:            { vertLines: { visible: false }, horzLines: { visible: false } },
      timeScale:       { borderColor: border, timeVisible: true },
      rightPriceScale: { visible: false },
      leftPriceScale:  { visible: false },
      crosshair:       { vertLine: { visible: true }, horzLine: { visible: false } },
      autoSize: true,
    });

    const area = chart.addSeries(AreaSeries, {
      lineColor:        purple,
      topColor:         purpleFill,
      bottomColor:      'transparent',
      lineWidth:        2,
      priceLineVisible: false,
      lastValueVisible: false,
    });

    area.setData(chartPoints);
    chart.timeScale().fitContent();
    chartRef.current = chart;

    return () => {
      chart.remove();
      chartRef.current = null;
    };
  }, [chartPoints]);

  if (!ticker) return <div>Loading...</div>;

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
        {chartPoints.length > 0 ? (
          <div className="absolute inset-0">
            <div ref={chartContainer} className="w-full h-full" />
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
