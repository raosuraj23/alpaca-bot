"use client"

import * as React from 'react';
import { createChart, AreaSeries, HistogramSeries, createSeriesMarkers } from 'lightweight-charts';
import type { IChartApi, Time } from 'lightweight-charts';
import { Activity } from 'lucide-react';
import { cssVar } from '@/lib/utils';

interface EquityCurveTerminalProps {
  history: [number, number][];
  lastSignal: { action: string; timestamp: string } | null;
}

export function EquityCurveTerminal({ history, lastSignal }: EquityCurveTerminalProps) {
  const topRef    = React.useRef<HTMLDivElement>(null);
  const bottomRef = React.useRef<HTMLDivElement>(null);
  const chart1Ref = React.useRef<IChartApi | null>(null);
  const chart2Ref = React.useRef<IChartApi | null>(null);

  const { equityPoints, ddPoints, isPositive } = React.useMemo(() => {
    if (!history || history.length < 2) {
      return { equityPoints: [], ddPoints: [], isPositive: true };
    }
    const equityPoints = history.map(([ts, v]) => ({
      time: Math.floor(ts / 1000) as Time,
      value: v,
    }));
    let peak = history[0][1];
    const ddPoints = history.map(([ts, v]) => {
      if (v > peak) peak = v;
      const dd = peak > 0 ? ((peak - v) / peak) * -100 : 0;
      return { time: Math.floor(ts / 1000) as Time, value: dd };
    });
    const isPositive = history[history.length - 1][1] >= history[0][1];
    return { equityPoints, ddPoints, isPositive };
  }, [history]);

  // Equity curve chart
  React.useEffect(() => {
    const el = topRef.current;
    if (!el || equityPoints.length < 2) return;

    // Resolve CSS variables at effect time — lightweight-charts uses canvas, not CSS
    const text      = cssVar('--muted-foreground');
    const border    = cssVar('--border');
    const green     = cssVar('--neon-green');
    const red       = cssVar('--neon-red');
    const greenFill = cssVar('--neon-green-fill');
    const redFill   = cssVar('--neon-red-fill');

    const chart = createChart(el, {
      layout: { background: { color: 'transparent' as const }, textColor: text, fontSize: 10, fontFamily: 'JetBrains Mono, monospace' },
      grid: { vertLines: { color: border }, horzLines: { color: border } },
      crosshair: { mode: 1 as const },
      rightPriceScale: { borderColor: border, scaleMargins: { top: 0.1, bottom: 0.05 } },
      timeScale: { borderColor: border, timeVisible: true, secondsVisible: false },
      handleScale: false as const,
      handleScroll: false as const,
      autoSize: true,
    });
    chart1Ref.current = chart;

    const lineColor = isPositive ? green : red;
    const topColor  = isPositive ? greenFill : redFill;

    const area = chart.addSeries(AreaSeries, {
      lineColor,
      topColor,
      bottomColor: 'transparent',
      lineWidth: 2,
      priceFormat: { type: 'price', precision: 2, minMove: 0.01 },
    });
    area.setData(equityPoints);

    if (lastSignal) {
      const sigTs = Math.floor(new Date(lastSignal.timestamp).getTime() / 1000) as Time;
      const isBuy = lastSignal.action === 'BUY';
      createSeriesMarkers(area, [{
        time: sigTs,
        position: isBuy ? 'belowBar' : 'aboveBar',
        color: isBuy ? green : red,
        shape: isBuy ? 'arrowUp' : 'arrowDown',
        text: lastSignal.action,
      }]);
    }

    chart.timeScale().fitContent();

    return () => { chart.remove(); chart1Ref.current = null; };
  }, [equityPoints, isPositive, lastSignal]);

  // Drawdown chart
  React.useEffect(() => {
    const el = bottomRef.current;
    if (!el || ddPoints.length < 2) return;

    const text   = cssVar('--muted-foreground');
    const border = cssVar('--border');
    const red    = cssVar('--neon-red');

    const chart = createChart(el, {
      layout: { background: { color: 'transparent' as const }, textColor: text, fontSize: 10, fontFamily: 'JetBrains Mono, monospace' },
      grid: { vertLines: { color: border }, horzLines: { color: border } },
      crosshair: { mode: 1 as const },
      rightPriceScale: { borderColor: border, scaleMargins: { top: 0.05, bottom: 0 } },
      timeScale: { borderColor: border, timeVisible: true, secondsVisible: false },
      handleScale: false as const,
      handleScroll: false as const,
      autoSize: true,
    });
    chart2Ref.current = chart;

    const dd = chart.addSeries(HistogramSeries, {
      color: red,
      priceFormat: { type: 'percent', precision: 3, minMove: 0.001 },
    });
    dd.setData(ddPoints.map(p => ({ ...p, color: red })));
    chart.timeScale().fitContent();

    return () => { chart.remove(); chart2Ref.current = null; };
  }, [ddPoints]);

  // Sync time scales
  React.useEffect(() => {
    const c1 = chart1Ref.current;
    const c2 = chart2Ref.current;
    if (!c1 || !c2) return;

    const handler1 = (range: any) => { if (range) c2.timeScale().setVisibleLogicalRange(range); };
    const handler2 = (range: any) => { if (range) c1.timeScale().setVisibleLogicalRange(range); };

    c1.timeScale().subscribeVisibleLogicalRangeChange(handler1);
    c2.timeScale().subscribeVisibleLogicalRangeChange(handler2);

    return () => {
      c1.timeScale().unsubscribeVisibleLogicalRangeChange(handler1);
      c2.timeScale().unsubscribeVisibleLogicalRangeChange(handler2);
    };
  });

  if (equityPoints.length < 2) {
    return (
      <div className="flex flex-col items-center justify-center h-full gap-2">
        <Activity className="w-8 h-8 text-[var(--muted-foreground)] opacity-15" />
        <span className="text-xs font-mono text-[var(--muted-foreground)] opacity-50 uppercase tracking-widest">
          Awaiting Execution Data
        </span>
      </div>
    );
  }

  return (
    <div className="flex flex-col h-full gap-0">
      <div className="flex-[0.65] min-h-0" ref={topRef} />
      <div className="h-px bg-[var(--border)] opacity-30 shrink-0" />
      <div className="flex-[0.35] min-h-0" ref={bottomRef} />
    </div>
  );
}
