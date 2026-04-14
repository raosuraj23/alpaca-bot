"use client"

import * as React from 'react';
import { Card, CardHeader, CardTitle, CardContent } from "@/components/ui/card";
import { Button } from "@/components/ui/button";
import { Badge } from "@/components/ui/badge";
import { PlayCircle, DatabaseZap } from 'lucide-react';
import { ResponsiveLine } from '@nivo/line';

// ---------------------------------------------------------------------------
// Types
// ---------------------------------------------------------------------------

interface BacktestResult {
  net_profit:    number;
  max_drawdown:  number;
  profit_factor: number;
  total_trades:  number;
  win_rate:      number;
  sharpe_ratio:  number;
  equity_curve:  [number, number][];
  error?:        string | null;
}

// ---------------------------------------------------------------------------
// Constants
// ---------------------------------------------------------------------------

const STRATEGIES = [
  { value: 'momentum-alpha', label: 'Momentum Divergence α' },
  { value: 'statarb-gamma',  label: 'Statistical Arbitrage (Pairs)' },
  { value: 'hft-sniper',     label: 'Order Book Imbalance β' },
] as const;

// ---------------------------------------------------------------------------
// Component
// ---------------------------------------------------------------------------

export function BacktestRunner() {
  const [running,   setRunning]   = React.useState(false);
  const [result,    setResult]    = React.useState<BacktestResult | null>(null);
  const [error,     setError]     = React.useState<string | null>(null);

  const strategyRef  = React.useRef<HTMLSelectElement>(null);
  const startDateRef = React.useRef<HTMLInputElement>(null);
  const endDateRef   = React.useRef<HTMLInputElement>(null);

  const handleRun = async () => {
    setRunning(true);
    setResult(null);
    setError(null);

    const symbol    = 'BTC-USD';
    const strategy  = strategyRef.current?.value  ?? 'momentum-alpha';
    const startDate = startDateRef.current?.value ?? '2023-01-01';
    const endDate   = endDateRef.current?.value   ?? '2023-12-31';

    try {
      const res = await fetch('http://localhost:8000/api/backtest', {
        method:  'POST',
        headers: { 'Content-Type': 'application/json' },
        body:    JSON.stringify({ symbol, strategy, start_date: startDate, end_date: endDate }),
        signal:  AbortSignal.timeout(120_000),
      });

      if (!res.ok) {
        const detail = await res.text();
        throw new Error(`Server error ${res.status}: ${detail}`);
      }

      const data: BacktestResult = await res.json();
      if (data.error) {
        setError(data.error);
      } else {
        setResult(data);
      }
    } catch (err: unknown) {
      setError(err instanceof Error ? err.message : 'Unknown error');
    } finally {
      setRunning(false);
    }
  };

  // Build Nivo line data from equity curve
  const nivoData = React.useMemo(() => {
    if (!result?.equity_curve?.length) return null;
    return [
      {
        id: 'equity',
        data: result.equity_curve.map(([ts, eq]) => ({
          x: new Date(ts).toISOString().slice(0, 10),
          y: eq,
        })),
      },
    ];
  }, [result]);

  const isComplete = !!result && !error;

  return (
    <div className="h-full flex flex-col md:flex-row gap-4">

      {/* Parameter Settings */}
      <Card className="w-full md:w-[350px] flex flex-col bg-[var(--panel)]">
        <CardHeader className="border-b border-[var(--border)] py-4">
          <CardTitle className="text-sm">Strategy Engine</CardTitle>
          <div className="text-xs text-[var(--muted-foreground)]">Configure historical simulation boundaries</div>
        </CardHeader>
        <CardContent className="flex-1 p-4 space-y-6">
          <div className="space-y-2 text-sm">
            <label className="text-xs uppercase tracking-widest text-[var(--muted-foreground)] font-bold">
              Target Algorithm
            </label>
            <select
              ref={strategyRef}
              className="w-full bg-[var(--panel-muted)] border border-[var(--border)] rounded-sm px-3 py-2 outline-none focus:border-[var(--kraken-purple)] text-xs font-mono"
            >
              {STRATEGIES.map(s => (
                <option key={s.value} value={s.value}>{s.label}</option>
              ))}
            </select>
          </div>

          <div className="grid grid-cols-2 gap-3 text-sm">
            <div className="space-y-2">
              <label className="text-xs uppercase tracking-widest text-[var(--muted-foreground)] font-bold">
                Start Date
              </label>
              <input
                ref={startDateRef}
                type="date"
                defaultValue="2023-01-01"
                className="w-full bg-[var(--panel-muted)] border border-[var(--border)] rounded-sm px-2 py-1.5 outline-none font-mono text-xs"
              />
            </div>
            <div className="space-y-2">
              <label className="text-xs uppercase tracking-widest text-[var(--muted-foreground)] font-bold">
                End Date
              </label>
              <input
                ref={endDateRef}
                type="date"
                defaultValue="2023-12-31"
                className="w-full bg-[var(--panel-muted)] border border-[var(--border)] rounded-sm px-2 py-1.5 outline-none font-mono text-xs"
              />
            </div>
          </div>

          <div className="space-y-4 pt-4 border-t border-[var(--border)]">
            <div className="flex justify-between items-center text-xs">
              <span className="text-[var(--muted-foreground)]">Initial Capital</span>
              <span className="font-mono tabular-nums">$100,000</span>
            </div>
            <div className="flex justify-between items-center text-xs">
              <span className="text-[var(--muted-foreground)]">Slippage Model</span>
              <span className="font-mono tabular-nums">0.05%</span>
            </div>
            <div className="flex justify-between items-center text-xs">
              <span className="text-[var(--muted-foreground)]">Data Split</span>
              <span className="font-mono tabular-nums">70% IS / 30% OOS</span>
            </div>
          </div>

          <div className="pt-4 mt-auto">
            <Button
              onClick={handleRun}
              disabled={running}
              className="w-full py-6 font-bold tracking-wider uppercase"
              size="lg"
            >
              {running
                ? 'SIMULATING...'
                : <><PlayCircle className="w-5 h-5 mr-2" />RUN BACKTEST</>
              }
            </Button>
          </div>
        </CardContent>
      </Card>

      {/* Results View */}
      <Card className="flex-1 flex flex-col bg-[var(--background)]">
        <CardHeader className="border-b border-[var(--kraken-purple)]/30 bg-[var(--panel)]/50 py-3 flex flex-row items-center justify-between">
          <div className="flex items-center space-x-2">
            <DatabaseZap className="w-4 h-4 text-[var(--kraken-purple)]" />
            <CardTitle className="text-sm">Simulation Output</CardTitle>
          </div>
          {isComplete && <Badge variant="success">COMPLETE</Badge>}
          {error     && <Badge variant="destructive">ERROR</Badge>}
        </CardHeader>

        <CardContent className="flex-1 relative flex flex-col p-0 overflow-hidden">

          {/* Idle state */}
          {!running && !result && !error && (
            <div className="flex-1 flex items-center justify-center text-[var(--muted-foreground)] opacity-50 flex-col">
              <span className="mb-2">No active simulation data</span>
              <span className="text-xs font-mono">Select parameters and execute to map trajectory</span>
            </div>
          )}

          {/* Loading state */}
          {running && (
            <div className="flex-1 flex items-center justify-center flex-col gap-3">
              <div className="w-48 h-1 bg-[var(--panel-muted)] rounded-sm overflow-hidden">
                <div className="h-full bg-[var(--kraken-purple)] animate-pulse w-full" />
              </div>
              <span className="text-xs font-mono text-[var(--muted-foreground)]">
                Fetching data and running OOS simulation...
              </span>
            </div>
          )}

          {/* Error state */}
          {error && (
            <div className="flex-1 flex items-center justify-center p-6">
              <div className="text-xs font-mono text-[var(--neon-red)] bg-[var(--panel)] border border-[var(--neon-red)]/30 rounded-sm p-4 max-w-md">
                <div className="font-bold mb-1 uppercase tracking-wider">Simulation Error</div>
                {error}
              </div>
            </div>
          )}

          {/* Results */}
          {isComplete && result && (
            <div className="flex-1 flex flex-col p-4 gap-4">
              {/* Equity curve chart */}
              <div className="flex-1 min-h-[200px]">
                {nivoData ? (
                  <ResponsiveLine
                    data={nivoData}
                    margin={{ top: 10, right: 20, bottom: 40, left: 60 }}
                    xScale={{ type: 'point' }}
                    yScale={{ type: 'linear', min: 'auto', max: 'auto', stacked: false }}
                    curve="monotoneX"
                    axisBottom={{
                      tickSize: 0,
                      tickPadding: 8,
                      tickRotation: -35,
                      tickValues: 6,
                    }}
                    axisLeft={{
                      tickSize: 0,
                      tickPadding: 8,
                      format: (v: number) => `$${(v / 1000).toFixed(0)}k`,
                    }}
                    enablePoints={false}
                    enableGridX={false}
                    enableGridY={true}
                    gridYValues={5}
                    colors={[result.net_profit >= 0 ? 'var(--neon-green)' : 'var(--neon-red)']}
                    lineWidth={2}
                    theme={{
                      background: 'transparent',
                      axis: {
                        ticks: { text: { fill: 'var(--muted-foreground)', fontSize: 10 } },
                      },
                      grid: { line: { stroke: 'var(--border)', strokeWidth: 1 } },
                    }}
                    enableArea
                    areaOpacity={0.08}
                  />
                ) : null}
              </div>

              {/* KPI stat blocks */}
              <div className="grid grid-cols-2 md:grid-cols-4 gap-2">
                <StatBlock
                  label="Net Profit"
                  value={`${result.net_profit >= 0 ? '+' : ''}$${result.net_profit.toLocaleString('en-US', { minimumFractionDigits: 2 })}`}
                  positive={result.net_profit >= 0}
                />
                <StatBlock
                  label="Max Drawdown"
                  value={`-${result.max_drawdown.toFixed(2)}%`}
                  positive={false}
                />
                <StatBlock
                  label="Profit Factor"
                  value={result.profit_factor.toFixed(2)}
                  neutral
                />
                <StatBlock
                  label="Total Trades"
                  value={result.total_trades.toString()}
                  neutral
                />
                <StatBlock
                  label="Win Rate"
                  value={`${result.win_rate.toFixed(1)}%`}
                  positive={result.win_rate >= 50}
                />
                <StatBlock
                  label="Sharpe Ratio"
                  value={result.sharpe_ratio.toFixed(2)}
                  positive={result.sharpe_ratio >= 1}
                />
              </div>
            </div>
          )}
        </CardContent>
      </Card>
    </div>
  );
}

// ---------------------------------------------------------------------------
// Sub-component: stat block
// ---------------------------------------------------------------------------

function StatBlock({
  label,
  value,
  positive,
  neutral,
}: {
  label: string;
  value: string;
  positive?: boolean;
  neutral?: boolean;
}) {
  const color = neutral
    ? 'text-[var(--foreground)]'
    : positive
    ? 'text-[var(--neon-green)]'
    : 'text-[var(--neon-red)]';

  return (
    <div className="bg-[var(--panel)] p-3 rounded-sm border border-[var(--border)]">
      <div className="text-xs uppercase text-[var(--muted-foreground)] mb-1 tracking-wider">{label}</div>
      <div className={`text-lg font-mono tabular-nums font-bold ${color}`}>{value}</div>
    </div>
  );
}
