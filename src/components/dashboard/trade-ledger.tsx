"use client"

import * as React from 'react';
import { Card, CardHeader, CardTitle, CardContent } from "@/components/ui/card";
import { Badge } from "@/components/ui/badge";
import { Filter, Download, ArrowUpDown, ChevronDown } from 'lucide-react';
import { useTradingStore } from '@/hooks/useTradingStream';

export function TradeLedger() {
  // ledgerTrades comes from /api/ledger (DB join of ExecutionRecord + SignalRecord)
  // Shape: {id, order_id, symbol, side, bot, fill_price, slippage, slippage_bps, confidence, timestamp}
  const ledgerTrades = useTradingStore(s => s.ledgerTrades);

  return (
    <Card className="h-full flex flex-col bg-[var(--panel)] overflow-hidden">

      {/* Ledger Toolbar */}
      <CardHeader className="py-3 px-4 border-b border-[var(--border)] flex flex-row items-center justify-between bg-gradient-to-b from-[var(--kraken-purple)]/5 to-transparent flex-shrink-0">
        <div className="flex items-center space-x-3">
          <CardTitle className="text-sm font-bold tracking-wide">Master Execution Ledger</CardTitle>
          <Badge variant="outline" className="px-2">{ledgerTrades.length} RECORDS</Badge>
        </div>

        {/* Filters */}
        <div className="flex items-center space-x-2">
          {['Asset Class', 'Automated Agent', 'Timeframe', 'Outcome'].map((filter) => (
            <button key={filter} className="hidden lg:flex items-center px-3 py-1.5 bg-[var(--background)] border border-[var(--border)] rounded text-xs text-[var(--muted-foreground)] hover:text-[var(--foreground)] transition-colors">
              {filter} <ChevronDown className="w-3 h-3 ml-1.5 opacity-60" />
            </button>
          ))}
          <button className="p-1.5 bg-[var(--kraken-purple)] text-white rounded hover:bg-[var(--kraken-light)] transition-colors ml-2 shadow-[0_0_10px_rgba(139,92,246,0.3)]">
            <Filter className="w-4 h-4" />
          </button>
          <button className="p-1.5 bg-[var(--panel-muted)] border border-[var(--border)] rounded hover:bg-[var(--background)] transition-colors text-[var(--muted-foreground)]">
            <Download className="w-4 h-4" />
          </button>
        </div>
      </CardHeader>

      {/* Ledger Table */}
      <CardContent className="flex-1 overflow-auto p-0">
        <table className="w-full text-xs text-left tabular-nums font-mono whitespace-nowrap">
          <thead className="sticky top-0 bg-[var(--panel-muted)] border-b border-[var(--border)] text-[var(--muted-foreground)] shadow-sm z-10">
            <tr>
              <th className="font-semibold p-3 pl-4 cursor-pointer hover:text-[var(--foreground)]">
                <span className="flex items-center">Ticket ID <ArrowUpDown className="w-3 h-3 ml-1" /></span>
              </th>
              <th className="font-semibold p-3 cursor-pointer hover:text-[var(--foreground)]">Timestamp</th>
              <th className="font-semibold p-3 cursor-pointer hover:text-[var(--foreground)]">Symbol</th>
              <th className="font-semibold p-3 text-center">Direction</th>
              <th className="font-semibold p-3 text-center hidden md:table-cell">Origin Agent</th>
              <th className="font-semibold p-3 text-right hidden xl:table-cell">Signal Conf.</th>
              <th className="font-semibold p-3 text-right hidden lg:table-cell">Slippage</th>
              <th className="font-semibold p-3 pr-4 text-right font-bold text-[var(--kraken-light)]">Fill Price</th>
            </tr>
          </thead>
          <tbody className="divide-y divide-[var(--border)]/30">
            {ledgerTrades.length === 0 ? (
              <tr>
                <td colSpan={8} className="p-6 text-center text-[var(--muted-foreground)]">
                  No execution records yet
                </td>
              </tr>
            ) : ledgerTrades.map((r: any) => (
              <tr key={r.id} className="hover:bg-[var(--panel-muted)] transition-colors group cursor-default">
                <td className="p-3 pl-4 text-[var(--muted-foreground)]">
                  {r.order_id ?? String(r.id)}
                </td>
                <td className="p-3 text-[var(--foreground)]">
                  {r.timestamp ? new Date(r.timestamp).toLocaleString() : '—'}
                </td>
                <td className="p-3 font-bold">{r.symbol ?? '—'}</td>
                <td className="p-3 text-center">
                  <Badge
                    variant={r.side === 'BUY' ? 'success' : 'destructive'}
                    className="text-xs px-1.5 uppercase font-sans tracking-widest"
                  >
                    {r.side ?? '—'}
                  </Badge>
                </td>
                <td className="p-3 text-center hidden md:table-cell">
                  <Badge variant="outline" className="font-sans font-normal opacity-80">
                    {r.bot ?? '—'}
                  </Badge>
                </td>
                <td className="p-3 text-right text-[var(--kraken-light)] hidden xl:table-cell">
                  {r.confidence != null ? `${(r.confidence * 100).toFixed(0)}%` : '—'}
                </td>
                <td className="p-3 text-right hidden lg:table-cell">
                  {r.slippage_bps != null
                    ? <span className="text-[var(--neon-red)]">{r.slippage_bps.toFixed(1)} bps</span>
                    : <span className="text-[var(--muted-foreground)]">—</span>}
                </td>
                <td className="p-3 pr-4 text-right font-bold text-sm text-[var(--foreground)]">
                  {r.fill_price != null ? `$${Number(r.fill_price).toFixed(2)}` : '—'}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </CardContent>
    </Card>
  );
}
