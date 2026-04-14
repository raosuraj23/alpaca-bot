"use client"

import * as React from 'react';
import { Card, CardHeader, CardTitle, CardContent } from "@/components/ui/card";
import { useTradingStore } from '@/hooks/useTradingStream';
import { ValueTicker } from '@/components/ui/value-ticker';

export function SidebarWatchlist() {
  const { watchlist, activeSymbol, setActiveSymbol, assetClass } = useTradingStore();

  // Filter watchlist roughly by asset class static grouping
  const visibleTickers = watchlist.filter(w => {
    if (assetClass === 'CRYPTO') return w.symbol.includes('USD');
    if (assetClass === 'EQUITY') return !w.symbol.includes('USD');
    return true; // Options shows all for now
  });

  return (
    <Card className="h-full flex flex-col min-w-[240px]">
      <CardHeader className="py-2.5 px-3">
        <CardTitle className="text-xs uppercase tracking-wider font-semibold text-[var(--muted-foreground)]">Watchlist</CardTitle>
      </CardHeader>
      <CardContent className="flex-1 overflow-y-auto p-0 flex flex-col">
        {visibleTickers.map((ticker) => (
          <div 
            key={ticker.symbol} 
            onClick={() => setActiveSymbol(ticker.symbol)}
            className={`p-3 border-b border-[var(--border)] cursor-pointer transition-colors flex justify-between items-center ${activeSymbol === ticker.symbol ? 'bg-[var(--kraken-purple)]/10 border-l-2 border-l-[var(--kraken-purple)]' : 'hover:bg-[var(--panel-muted)] border-l-2 border-l-transparent'}`}
          >
            <div className="flex flex-col">
              <span className="font-bold text-sm text-[var(--kraken-light)]">{ticker.symbol}</span>
              <span className="text-xs text-[var(--muted-foreground)] tabular-nums mt-0.5">Vol: {(ticker.volume / 1000).toFixed(1)}k</span>
            </div>
            <div className="flex flex-col items-end">
              <span className="font-mono text-sm font-semibold">
                <ValueTicker value={ticker.price} />
              </span>
              <span className={`text-xs font-mono tabular-nums ${ticker.change24h >= 0 ? 'text-[var(--neon-green)]' : 'text-[var(--neon-red)]'}`}>
                {ticker.change24h >= 0 ? '+' : ''}{ticker.change24h.toFixed(2)}%
              </span>
            </div>
          </div>
        ))}
      </CardContent>
    </Card>
  );
}
