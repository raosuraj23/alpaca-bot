"use client"

import { API_BASE } from '@/lib/api';
import * as React from 'react';
import { Card, CardContent } from "@/components/ui/card";
import { Badge } from "@/components/ui/badge";
import { useTradingStore } from '@/store';
import { ValueTicker } from '@/components/ui/value-ticker';
import { isCryptoSymbol } from '@/lib/utils';
import type { WatchlistTA } from '@/lib/types';
import { Sparkles } from 'lucide-react';

const ASSET_TEXT: Record<string, string> = {
  EQUITY:  'text-[var(--neon-green)]',
  OPTIONS: 'text-[var(--agent-learning)]',
  CRYPTO:  'text-[var(--kraken-light)]',
};

function RsiBar({ rsi }: { rsi: number | null }) {
  if (rsi == null) return null;
  const pct = Math.max(0, Math.min(100, rsi));
  const fill = rsi > 70 ? 'var(--neon-red)' : rsi < 30 ? 'var(--neon-green)' : 'var(--muted-foreground)';
  return (
    <div className="flex items-center gap-1 mt-0.5">
      <div className="w-10 h-1 rounded-sm overflow-hidden" style={{ background: 'var(--border)' }}>
        <div style={{ width: `${pct}%`, height: '100%', background: fill }} />
      </div>
      <span className="text-xs font-mono tabular-nums text-[var(--muted-foreground)] opacity-60">{rsi.toFixed(0)}</span>
    </div>
  );
}

export function SidebarWatchlist() {
  const { watchlist, activeSymbol, setActiveSymbol, assetClass } = useTradingStore();
  const setAssetClass = useTradingStore(s => (s as any).setAssetClass as (ac: 'EQUITY' | 'OPTIONS' | 'CRYPTO') => void);
  const scanResults = useTradingStore(s => s.scannerResults) as WatchlistTA[];
  const [scanning, setScanning] = React.useState(false);
  const [scanError, setScanError] = React.useState(false);
  const [expanded, setExpanded] = React.useState<string | null>(null);

  const triggerScan = async () => {
    setScanning(true);
    setScanError(false);
    try {
      const res = await fetch(`${API_BASE}/api/watchlist/scan`, { method: 'POST' });
      const data = await res.json();
      if (Array.isArray(data?.results)) {
        const results = data.results as WatchlistTA[];
        useTradingStore.setState({ scannerResults: results });
        const currentWl = useTradingStore.getState().watchlist;
        const existing = new Set(currentWl.map(t => t.symbol));
        const newEntries = results
          .filter(r => !existing.has(r.symbol))
          .map(r => ({ symbol: r.symbol, price: r.price ?? 0, change24h: 0, volume: 0, asset_class: r.asset_class }));
        if (newEntries.length > 0) {
          useTradingStore.setState({ watchlist: [...currentWl, ...newEntries] });
        }
      }
    } catch {
      setScanError(true);
    } finally {
      setScanning(false);
    }
  };

  const visibleTickers = React.useMemo(() =>
    watchlist.filter(w => {
      if (assetClass === 'CRYPTO')  return isCryptoSymbol(w.symbol);
      if (assetClass === 'OPTIONS') return w.asset_class === 'OPTIONS';
      // EQUITY: non-crypto symbols that are not explicitly tagged OPTIONS
      return !isCryptoSymbol(w.symbol) && w.asset_class !== 'OPTIONS';
    }),
    [watchlist, assetClass],
  );

  const scanSymbols = React.useMemo(() => new Set(scanResults.map(r => r.symbol)), [scanResults]);
  const visibleScanResults = React.useMemo(() =>
    scanResults.filter(r => {
      if (assetClass === 'CRYPTO')  return isCryptoSymbol(r.symbol);
      if (assetClass === 'OPTIONS') return r.asset_class === 'OPTIONS';
      return !isCryptoSymbol(r.symbol) && r.asset_class !== 'OPTIONS';
    }),
    [scanResults, assetClass],
  );

  return (
    <Card className="h-full flex flex-col min-w-[240px]">
      {/* Row 1: Watchlist label + SCAN button */}
      <div className="px-3 py-2 border-b border-[var(--border)] flex items-center justify-between">
        <span className="text-xs uppercase tracking-wider font-semibold text-[var(--muted-foreground)]">Watchlist</span>
        <button
          onClick={triggerScan}
          disabled={scanning}
          className="flex items-center gap-1 text-xs font-mono px-2 py-0.5 rounded-sm border border-[var(--kraken-purple)]/50 text-[var(--kraken-light)] hover:bg-[var(--kraken-purple)]/20 disabled:opacity-40 transition-colors"
        >
          <Sparkles className="w-3 h-3" />
          {scanning ? 'SCANNING…' : 'SCAN'}
        </button>
      </div>
      {/* Row 2: Asset class toggle — full-width, small buttons */}
      <div className="px-2 py-1.5 border-b border-[var(--border)] flex">
        <div className="flex flex-1 bg-[var(--background)] border border-[var(--border)] rounded-sm p-0.5 gap-0.5">
          {(['EQUITY', 'OPTIONS', 'CRYPTO'] as const).map(ac => (
            <button
              key={ac}
              onClick={() => setAssetClass(ac)}
              className={`flex-1 py-0.5 text-xs font-bold rounded-sm tracking-wider transition-colors ${assetClass === ac ? `bg-[var(--panel-muted)] ${ASSET_TEXT[ac]} shadow-sm` : 'text-[var(--muted-foreground)] hover:text-white'}`}
            >
              {ac}
            </button>
          ))}
        </div>
      </div>

      <CardContent className="flex-1 overflow-y-auto p-0 flex flex-col">

        {/* ── AI Analyst Picks (scanner results) at the top ── */}
        {visibleScanResults.length > 0 && (
          <div className="shrink-0">
            <div className="px-3 py-1.5 flex items-center gap-1.5 bg-[var(--kraken-purple)]/8 border-b border-[var(--border)]">
              <Sparkles className="w-3 h-3 text-[var(--kraken-light)]" />
              <span className="text-xs font-mono uppercase tracking-wider text-[var(--kraken-light)]">AI Analyst Picks</span>
              <span className="ml-auto text-xs font-mono text-[var(--muted-foreground)] opacity-40">{visibleScanResults.length}</span>
            </div>
            {visibleScanResults.map(r => {
              const isActive = activeSymbol === r.symbol;
              const isOpen   = expanded === r.symbol;
              return (
                <div key={r.symbol} className={`border-b border-[var(--border)]/60 ${isActive ? 'bg-[var(--kraken-purple)]/10 border-l-2 border-l-[var(--kraken-purple)]' : 'border-l-2 border-l-transparent'}`}>
                  <div
                    className="flex items-center justify-between px-3 py-2 cursor-pointer hover:bg-[var(--panel-muted)] transition-colors"
                    onClick={() => {
                      setActiveSymbol(r.symbol);
                      setExpanded(isOpen ? null : r.symbol);
                    }}
                  >
                    <div className="flex flex-col min-w-0">
                      <div className="flex items-center gap-2">
                        <span className="font-bold text-sm text-[var(--foreground)]">{r.symbol}</span>
                        {r.signal !== 'NEUTRAL' && (
                          <Badge
                            variant={r.signal === 'BUY' ? 'success' : 'destructive'}
                            className="text-xs py-0 px-1 shrink-0"
                          >
                            {r.signal}
                          </Badge>
                        )}
                      </div>
                      <RsiBar rsi={r.rsi ?? null} />
                    </div>
                    <div className="flex flex-col items-end shrink-0 ml-2">
                      <span className={`text-xs font-mono tabular-nums font-bold ${r.score >= 0 ? 'text-[var(--neon-green)]' : 'text-[var(--neon-red)]'}`}>
                        {r.score >= 0 ? '+' : ''}{r.score.toFixed(2)}
                      </span>
                    </div>
                  </div>
                  {isOpen && (
                    <div className="px-3 pb-2 text-xs text-[var(--muted-foreground)] leading-snug bg-[var(--background)]/40 border-t border-[var(--border)]/30 space-y-1">
                      <p className="pt-1">{r.verdict}</p>
                      <div className="flex gap-3 font-mono tabular-nums opacity-70">
                        {r.ema_spread != null && (
                          <span title="EMA spread: (ema20 - price) / price">
                            <span className="opacity-50">EMA </span>
                            <span className={r.ema_spread > 0 ? 'text-[var(--neon-green)]' : 'text-[var(--neon-red)]'}>
                              {(r.ema_spread * 100).toFixed(2)}%
                            </span>
                          </span>
                        )}
                        {r.vol_surge != null && (
                          <span title="Volume surge vs 20-bar avg">
                            <span className="opacity-50">Vol </span>
                            <span className={r.vol_surge >= 1.5 ? 'text-[var(--neon-green)]' : ''}>{r.vol_surge.toFixed(1)}x</span>
                          </span>
                        )}
                        {r.band_pct != null && (
                          <span title="Bollinger Band position (0=lower, 1=upper)">
                            <span className="opacity-50">BB </span>
                            <span className={r.band_pct < 0.25 ? 'text-[var(--neon-green)]' : r.band_pct > 0.75 ? 'text-[var(--neon-red)]' : ''}>
                              {(r.band_pct * 100).toFixed(0)}%
                            </span>
                          </span>
                        )}
                      </div>
                    </div>
                  )}
                </div>
              );
            })}
          </div>
        )}

        {scanError && (
          <div className="px-3 py-2 text-xs text-[var(--neon-red)] font-mono shrink-0">
            Scanner offline — check backend
          </div>
        )}

        {/* ── Static Watchlist ── */}
        {visibleTickers.length > 0 && (
          <div className="shrink-0">
            {scanResults.length > 0 && (
              <div className="px-3 py-1.5 border-b border-[var(--border)] bg-[var(--panel-muted)]/30">
                <span className="text-xs font-mono uppercase tracking-wider text-[var(--muted-foreground)] opacity-60">Watchlist</span>
              </div>
            )}
            {visibleTickers.map(ticker => (
              <div
                key={ticker.symbol}
                onClick={() => setActiveSymbol(ticker.symbol)}
                className={`p-3 border-b border-[var(--border)]/60 cursor-pointer transition-colors flex justify-between items-center ${
                  activeSymbol === ticker.symbol
                    ? 'bg-[var(--kraken-purple)]/10 border-l-2 border-l-[var(--kraken-purple)]'
                    : 'hover:bg-[var(--panel-muted)] border-l-2 border-l-transparent'
                }`}
              >
                <div className="flex flex-col">
                  <div className="flex items-center gap-1.5">
                    <span className="font-bold text-sm text-[var(--kraken-light)]">{ticker.symbol}</span>
                    {scanSymbols.has(ticker.symbol) && (
                      <Sparkles className="w-2.5 h-2.5 text-[var(--kraken-light)] opacity-70" />
                    )}
                  </div>
                  <span className="text-xs font-mono tabular-nums text-[var(--muted-foreground)] mt-0.5">Vol: {(ticker.volume / 1000).toFixed(1)}k</span>
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
          </div>
        )}

        {scanResults.length === 0 && !scanning && !scanError && (
          <div className="flex-1 flex items-end pb-4 px-3">
            <span className="text-xs text-[var(--muted-foreground)] opacity-40 font-mono">
              Press SCAN for AI analysis
            </span>
          </div>
        )}

      </CardContent>
    </Card>
  );
}
