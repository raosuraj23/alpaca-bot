"use client"

import * as React from 'react';
import { Card, CardHeader, CardTitle, CardContent } from "@/components/ui/card";
import { Badge } from "@/components/ui/badge";
import { useTradingStore } from '@/hooks/useTradingStream';
import { ValueTicker } from '@/components/ui/value-ticker';

type Tab = 'positions' | 'orders' | 'history';

export function PositionsTable() {
  const positions    = useTradingStore(s => s.positions);
  const recentTrades = useTradingStore(s => s.recentTrades);
  const ledgerTrades = useTradingStore(s => s.ledgerTrades);
  const performance  = useTradingStore(s => s.performance);

  // Build a realized-PnL lookup from ledger: keyed by Alpaca order_id (first 8 chars)
  // Ledger rows have fill_price + slippage from the execution agent — we can derive
  // an approximate per-trade PnL once the backend supplies a paired entry_price.
  // For now we store slippage_bps (observable) and leave pnl as null until paired.
  const ledgerByOrderId = React.useMemo(() => {
    const map = new Map<string, { slippage_bps: number | null; confidence: number | null }>();
    for (const r of ledgerTrades) {
      if (r.order_id) map.set(r.order_id, { slippage_bps: r.slippage_bps ?? null, confidence: r.confidence ?? null });
    }
    return map;
  }, [ledgerTrades]);

  const [activeTab, setActiveTab] = React.useState<Tab>('positions');

  // Open orders: no fill price yet (price === 0) or explicitly pending
  const openOrders = recentTrades.filter(t => t.price === 0 || t.status === 'pending');
  // History: filled orders with a real fill price
  const history    = recentTrades.filter(t => t.price > 0 && t.status !== 'pending');

  const tabClass = (tab: Tab) =>
    activeTab === tab
      ? 'text-xs uppercase tracking-wider font-bold text-[var(--kraken-light)] border-b-2 border-[var(--kraken-purple)] pb-1 cursor-pointer'
      : 'text-xs uppercase tracking-wider font-semibold text-[var(--muted-foreground)] cursor-pointer hover:text-[var(--foreground)] pb-1';

  return (
    <Card className="h-full flex flex-col min-h-[250px]">
      <CardHeader className="py-2.5 px-3 border-b border-[var(--border)] flex flex-row items-center justify-between">
        <div className="flex space-x-4">
          <CardTitle className={tabClass('positions')} onClick={() => setActiveTab('positions')}>
            Positions ({positions.length})
          </CardTitle>
          <CardTitle className={tabClass('orders')} onClick={() => setActiveTab('orders')}>
            Open Orders ({openOrders.length})
          </CardTitle>
          <CardTitle className={tabClass('history')} onClick={() => setActiveTab('history')}>
            History ({history.length})
          </CardTitle>
        </div>
        <div className="text-xs font-mono font-bold text-[var(--foreground)]">
          DAY PNL:{' '}
          <span className={performance.net_pnl >= 0 ? 'text-[var(--neon-green)]' : 'text-[var(--neon-red)]'}>
            {performance.net_pnl >= 0 ? '+' : ''}${performance.net_pnl.toFixed(2)}
          </span>
        </div>
      </CardHeader>

      <CardContent className="flex-1 overflow-y-auto p-0">

        {/* ── POSITIONS TAB ── */}
        {activeTab === 'positions' && (
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
              {positions.length === 0 ? (
                <tr><td colSpan={6} className="p-4 text-center text-[var(--muted-foreground)]">No open positions</td></tr>
              ) : positions.map((pos) => (
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
                  <td className="p-2 pr-4 text-right font-mono font-bold">
                    <ValueTicker value={pos.unrealizedPnl} prefix="$" />
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        )}

        {/* ── OPEN ORDERS TAB ── */}
        {activeTab === 'orders' && (
          <table className="w-full text-left text-xs tabular-nums">
            <thead className="sticky top-0 bg-[var(--panel-muted)] border-b border-[var(--border)] text-[var(--muted-foreground)] shadow-sm">
              <tr>
                <th className="font-medium p-2 pl-4">Symbol</th>
                <th className="font-medium p-2 text-center">Side</th>
                <th className="font-medium p-2 text-right">Qty</th>
                <th className="font-medium p-2 text-right">Status</th>
                <th className="font-medium p-2 pr-4 text-right">Submitted</th>
              </tr>
            </thead>
            <tbody className="divide-y divide-[var(--border)]/30">
              {openOrders.length === 0 ? (
                <tr><td colSpan={5} className="p-4 text-center text-[var(--muted-foreground)]">No open orders</td></tr>
              ) : openOrders.map((o) => (
                <tr key={o.id} className="hover:bg-[var(--panel-muted)] transition-colors">
                  <td className="p-2 pl-4 font-bold text-[var(--foreground)]">{o.symbol}</td>
                  <td className="p-2 text-center">
                    <Badge variant={o.side === 'BUY' ? 'success' : 'destructive'} className="text-xs px-1.5">{o.side}</Badge>
                  </td>
                  <td className="p-2 text-right font-mono">{o.size.toFixed(4)}</td>
                  <td className="p-2 text-right">
                    <Badge variant="warning" className="text-xs px-1.5 uppercase">PENDING</Badge>
                  </td>
                  <td className="p-2 pr-4 text-right text-[var(--muted-foreground)]">
                    {new Date(o.timestamp).toLocaleTimeString()}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        )}

        {/* ── HISTORY TAB ── */}
        {activeTab === 'history' && (
          <table className="w-full text-left text-xs tabular-nums">
            <thead className="sticky top-0 bg-[var(--panel-muted)] border-b border-[var(--border)] text-[var(--muted-foreground)] shadow-sm">
              <tr>
                <th className="font-medium p-2 pl-4">Symbol</th>
                <th className="font-medium p-2 text-center">Side</th>
                <th className="font-medium p-2 text-right">Qty</th>
                <th className="font-medium p-2 text-right">Fill Price</th>
                <th className="font-medium p-2 text-right">Realized P&amp;L</th>
                <th className="font-medium p-2 text-right">Slip (bps)</th>
                <th className="font-medium p-2 pr-4 text-right">Time</th>
              </tr>
            </thead>
            <tbody className="divide-y divide-[var(--border)]/30">
              {history.length === 0 ? (
                <tr><td colSpan={7} className="p-4 text-center text-[var(--muted-foreground)]">No trade history</td></tr>
              ) : history.map((o) => {
                const ledger = ledgerByOrderId.get(o.id.slice(0, 8));
                // Realized PnL: available once backend supplies it; show slippage_bps as proxy
                const slipBps = ledger?.slippage_bps;
                return (
                  <tr key={o.id} className="hover:bg-[var(--panel-muted)] transition-colors">
                    <td className="p-2 pl-4 font-bold text-[var(--foreground)]">{o.symbol}</td>
                    <td className="p-2 text-center">
                      <Badge variant={o.side === 'BUY' ? 'success' : 'destructive'} className="text-xs px-1.5">{o.side}</Badge>
                    </td>
                    <td className="p-2 text-right font-mono">{o.size.toFixed(4)}</td>
                    <td className="p-2 text-right font-mono font-bold text-[var(--foreground)]">${o.price.toFixed(2)}</td>
                    <td className="p-2 text-right font-mono text-[var(--muted-foreground)]">
                      {/* Realized PnL requires paired position cost basis — not yet in order feed */}
                      —
                    </td>
                    <td className={`p-2 text-right font-mono ${
                      slipBps == null ? 'text-[var(--muted-foreground)]'
                        : slipBps < 0 ? 'text-[var(--neon-green)]'
                        : slipBps > 5 ? 'text-[var(--neon-red)]'
                        : 'text-[var(--foreground)]'
                    }`}>
                      {slipBps != null ? `${slipBps > 0 ? '+' : ''}${slipBps.toFixed(1)}` : '—'}
                    </td>
                    <td className="p-2 pr-4 text-right text-[var(--muted-foreground)]">
                      {new Date(o.timestamp).toLocaleString()}
                    </td>
                  </tr>
                );
              })}
            </tbody>
          </table>
        )}

      </CardContent>
    </Card>
  );
}
