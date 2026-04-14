"use client"

import * as React from 'react';
import { Card, CardHeader, CardTitle, CardContent } from "@/components/ui/card";
import { Badge } from "@/components/ui/badge";
import { useTradingStore } from '@/hooks/useTradingStream';

interface LedgerEntry {
  id: number;
  order_id: string | null;
  symbol: string;
  side: string;
  bot: string;
  fill_price: number;
  slippage: number;
  slippage_bps: number | null;
  confidence: number;
  timestamp: string | null;
}

export function ExecutionLog() {
  const recentTrades  = useTradingStore(s => s.recentTrades);
  const ledgerTrades  = useTradingStore(s => (s as any).ledgerTrades ?? []);

  // Merge: prefer ledgerTrades (DB-backed) when available, fall back to session trades
  const rows: LedgerEntry[] = React.useMemo(() => {
    if (ledgerTrades.length > 0) return ledgerTrades;

    // Map session trades (from /api/orders) into the ledger shape
    return recentTrades.map((t: any) => ({
      id:           t.id,
      order_id:     t.id,
      symbol:       t.symbol ?? '—',
      side:         t.side,
      bot:          '—',
      fill_price:   t.price,
      slippage:     0,
      slippage_bps: null,
      confidence:   null,
      timestamp:    t.timestamp ? new Date(t.timestamp).toISOString() : null,
    }));
  }, [recentTrades, ledgerTrades]);

  return (
    <Card className="h-full flex flex-col">
      <CardHeader className="py-2.5 px-3 border-b border-[var(--border)] flex flex-row items-center justify-between">
        <CardTitle className="text-xs uppercase tracking-wider font-semibold text-[var(--kraken-light)]">
          Booked Fills (Execution Ledger)
        </CardTitle>
        <Badge variant="outline" className="text-xs font-mono">
          {rows.length} fills
        </Badge>
      </CardHeader>
      <CardContent className="flex-1 overflow-y-auto p-0 pb-2">
        <table className="w-full text-left text-xs tabular-nums font-mono">
          <thead className="sticky top-0 bg-[var(--panel-muted)] border-b border-[var(--border)] text-[var(--muted-foreground)] shadow-sm">
            <tr>
              <th className="font-semibold p-2 pl-3">Time</th>
              <th className="font-semibold p-2">Symbol</th>
              <th className="font-semibold p-2">Bot</th>
              <th className="font-semibold p-2">Side</th>
              <th className="font-semibold p-2 text-right">Fill $</th>
              <th className="font-semibold p-2 pr-3 text-right">Slip bps</th>
            </tr>
          </thead>
          <tbody className="divide-y divide-[var(--border)]/20">
            {rows.map((row: LedgerEntry, i: number) => {
              const timeStr = row.timestamp
                ? new Date(row.timestamp).toLocaleTimeString('en-US', { hour12: false })
                : '—';
              const side = (row.side ?? '').replace('OrderSide.', '').toUpperCase();
              const slipColor = row.slippage_bps != null
                ? row.slippage_bps < 5 ? 'text-[var(--neon-green)]'
                  : row.slippage_bps < 20 ? 'text-[var(--foreground)]'
                  : 'text-[var(--neon-red)]'
                : 'text-[var(--muted-foreground)]';

              return (
                <tr key={`${row.id}-${i}`} className="hover:bg-[var(--panel-muted)] transition-colors">
                  <td className="p-1.5 pl-3 text-[var(--muted-foreground)]">{timeStr}</td>
                  <td className="p-1.5 text-[var(--foreground)] font-bold">{row.symbol}</td>
                  <td className="p-1.5 text-[var(--muted-foreground)] max-w-[80px] truncate">
                    {row.bot !== '—' ? (
                      <span className="px-1 py-0.5 rounded bg-[var(--panel-muted)] text-[var(--kraken-light)]">
                        {row.bot}
                      </span>
                    ) : '—'}
                  </td>
                  <td className={`p-1.5 font-bold ${side === 'BUY' ? 'text-[var(--neon-green)]' : 'text-[var(--neon-red)]'}`}>
                    {side}
                  </td>
                  <td className="p-1.5 text-right text-[var(--foreground)]">
                    {row.fill_price != null ? `$${row.fill_price.toFixed(2)}` : '—'}
                  </td>
                  <td className={`p-1.5 pr-3 text-right font-bold ${slipColor}`}>
                    {row.slippage_bps != null ? `${row.slippage_bps}` : '—'}
                  </td>
                </tr>
              );
            })}
          </tbody>
        </table>
        {rows.length === 0 && (
          <div className="flex items-center justify-center h-full text-xs text-[var(--muted-foreground)] italic mt-4">
            No executions booked in current session.
          </div>
        )}
      </CardContent>
    </Card>
  );
}
