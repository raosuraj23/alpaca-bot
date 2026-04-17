"use client"

import * as React from 'react';
import { Card, CardHeader, CardTitle, CardContent } from "@/components/ui/card";
import { Badge } from "@/components/ui/badge";
import { useTradingStore } from '@/hooks/useTradingStream';
import { ValueTicker } from '@/components/ui/value-ticker';

interface ScanResult {
  symbol: string;
  score: number;
  signal: 'BUY' | 'SELL' | 'NEUTRAL';
  verdict: string;
  price: number;
  rsi: number | null;
  timestamp: string;
}

export function SidebarWatchlist() {
  const { watchlist, activeSymbol, setActiveSymbol, assetClass } = useTradingStore();
  // scannerResults is kept live by the SSE stream in useTradingStream.ts —
  // "scanner" events from the backend update it automatically every 5 min.
  const scanResults = useTradingStore(s => s.scannerResults) as ScanResult[];
  const [scanning, setScanning] = React.useState(false);
  const [scanError, setScanError] = React.useState(false);

  const triggerScan = async () => {
    setScanning(true);
    setScanError(false);
    try {
      const res = await fetch('http://localhost:8000/api/watchlist/scan', { method: 'POST' });
      const data = await res.json();
      // Write directly into the shared Zustand store so all consumers update
      if (Array.isArray(data?.results)) {
        useTradingStore.setState({ scannerResults: data.results });
      }
    } catch {
      setScanError(true);
    } finally {
      setScanning(false);
    }
  };

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

        {/* ── Scanner Panel ── */}
        <div className="mt-auto border-t border-[var(--border)] shrink-0">
          <div className="px-3 py-2 flex items-center justify-between">
            <span className="text-xs uppercase tracking-wider font-semibold text-[var(--muted-foreground)]">
              TA Scanner
            </span>
            <button
              onClick={triggerScan}
              disabled={scanning}
              className="text-xs font-mono px-2 py-0.5 rounded-sm border border-[var(--kraken-purple)]/50 text-[var(--kraken-light)] hover:bg-[var(--kraken-purple)]/20 disabled:opacity-40 transition-colors"
            >
              {scanning ? 'SCANNING…' : 'SCAN'}
            </button>
          </div>

          {scanError && (
            <div className="px-3 pb-2 text-xs text-[var(--neon-red)] font-mono">
              Scanner offline
            </div>
          )}

          {scanResults.length > 0 && (
            <div className="flex flex-col">
              {scanResults.map(r => (
                <div
                  key={r.symbol}
                  className="px-3 py-2 border-t border-[var(--border)]/50 hover:bg-[var(--panel-muted)] transition-colors"
                >
                  <div className="flex items-center justify-between mb-0.5">
                    <span className="text-xs font-bold text-[var(--foreground)]">{r.symbol}</span>
                    <Badge
                      variant={r.signal === 'BUY' ? 'success' : r.signal === 'SELL' ? 'destructive' : 'outline'}
                      className="text-xs py-0 px-1"
                    >
                      {r.signal}
                    </Badge>
                  </div>
                  <div className="flex justify-between items-center">
                    <span className="text-xs font-mono tabular-nums text-[var(--muted-foreground)]">
                      score {r.score >= 0 ? '+' : ''}{r.score.toFixed(2)}
                    </span>
                    {r.rsi != null && (
                      <span className="text-xs font-mono tabular-nums text-[var(--muted-foreground)]">
                        RSI {r.rsi.toFixed(0)}
                      </span>
                    )}
                  </div>
                  <p className="text-xs text-[var(--muted-foreground)] opacity-70 mt-0.5 leading-tight line-clamp-2">
                    {r.verdict}
                  </p>
                </div>
              ))}
            </div>
          )}

          {scanResults.length === 0 && !scanning && !scanError && (
            <div className="px-3 pb-3 text-xs text-[var(--muted-foreground)] opacity-40 font-mono">
              Press SCAN to analyse symbols
            </div>
          )}
        </div>
      </CardContent>
    </Card>
  );
}
