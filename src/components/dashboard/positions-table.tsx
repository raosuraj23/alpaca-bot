"use client"

import * as React from 'react';
import { Card, CardHeader, CardTitle, CardContent } from "@/components/ui/card";
import { Badge } from "@/components/ui/badge";
import { useTradingStore } from '@/hooks/useTradingStream';
import { ValueTicker } from '@/components/ui/value-ticker';

export function PositionsTable() {
  const positions = useTradingStore(s => s.positions);
  const recentTrades = useTradingStore(s => s.recentTrades);
  const performance = useTradingStore(s => s.performance);
  
  const openOrdersCount = recentTrades.filter(t => t.status === 'pending').length;

  return (
    <Card className="h-full flex flex-col min-h-[250px]">
      <CardHeader className="py-2.5 px-3 border-b border-[var(--border)] flex flex-row items-center justify-between">
        <div className="flex space-x-4">
          <CardTitle className="text-xs uppercase tracking-wider font-bold text-[var(--kraken-light)] border-b-2 border-[var(--kraken-purple)] pb-1">Positions ({positions.length})</CardTitle>
          <CardTitle className="text-xs uppercase tracking-wider font-semibold text-[var(--muted-foreground)] cursor-pointer hover:text-[var(--foreground)]">Open Orders ({openOrdersCount})</CardTitle>
          <CardTitle className="text-xs uppercase tracking-wider font-semibold text-[var(--muted-foreground)] cursor-pointer hover:text-[var(--foreground)]">History</CardTitle>
        </div>
        <div className="text-xs font-mono font-bold text-[var(--foreground)]">
          DAY PNL: <span className={performance.net_pnl >= 0 ? "text-[var(--neon-green)]" : "text-[var(--neon-red)]"}>{performance.net_pnl >= 0 ? '+' : ''}${performance.net_pnl.toFixed(2)}</span>
        </div>
      </CardHeader>
      
      <CardContent className="flex-1 overflow-y-auto p-0">
        <table className="w-full text-left text-xs tabular-nums">
          <thead className="sticky top-0 bg-[var(--panel-muted)] border-b border-[var(--border)] text-[var(--muted-foreground)] shadow-sm">
            <tr>
              <th className="font-medium p-2 pl-4">Symbol</th>
              <th className="font-medium p-2">Side</th>
              <th className="font-medium p-2 text-right">Size</th>
              <th className="font-medium p-2 text-right">Entry Price</th>
              <th className="font-medium p-2 text-right">Realized PnL</th>
              <th className="font-medium p-2 pr-4 text-right">Unrealized PnL</th>
            </tr>
          </thead>
          <tbody className="divide-y divide-[var(--border)]/30">
            {positions.map((pos) => (
              <tr key={pos.id} className="hover:bg-[var(--panel-muted)] transition-colors">
                <td className="p-2 pl-4 font-bold text-[var(--foreground)]">{pos.symbol}</td>
                <td className="p-2">
                  <Badge variant={pos.side === 'LONG' ? 'success' : 'destructive'} className="text-xs px-1.5">{pos.side}</Badge>
                </td>
                <td className="p-2 text-right font-mono text-[var(--foreground)]">{pos.size.toFixed(4)}</td>
                <td className="p-2 text-right text-[var(--muted-foreground)]">${pos.entryPrice.toFixed(2)}</td>
                <td className={`p-2 text-right font-mono ${pos.realizedPnl >= 0 ? 'text-[var(--neon-green)]' : 'text-[var(--neon-red)]'}`}>
                  ${pos.realizedPnl.toFixed(2)}
                </td>
                <td className={`p-2 pr-4 text-right font-mono font-bold`}>
                  <ValueTicker value={pos.unrealizedPnl} prefix="$" />
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </CardContent>
    </Card>
  );
}
