"use client"

import * as React from 'react';
import { useTradingStore } from '@/hooks/useTradingStream';
import { Search } from 'lucide-react';

export function CommandPalette() {
  const [open, setOpen]   = React.useState(false);
  const [query, setQuery] = React.useState('');
  const [cursor, setCursor] = React.useState(0);
  const inputRef = React.useRef<HTMLInputElement>(null);

  const watchlist     = useTradingStore(s => s.watchlist);
  const setActiveSymbol = useTradingStore(s => s.setActiveSymbol);
  const activeSymbol  = useTradingStore(s => s.activeSymbol);

  const results = React.useMemo(() => {
    const q = query.trim().toUpperCase();
    if (!q) return watchlist.slice(0, 8);
    return watchlist
      .filter(t => t.symbol.includes(q))
      .slice(0, 8);
  }, [query, watchlist]);

  // Reset cursor when results change
  React.useEffect(() => { setCursor(0); }, [results]);

  // Focus input when opened
  React.useEffect(() => {
    if (open) {
      setQuery('');
      setTimeout(() => inputRef.current?.focus(), 50);
    }
  }, [open]);

  // Global Cmd+K / Ctrl+K toggle
  React.useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      if ((e.metaKey || e.ctrlKey) && e.key === 'k') {
        e.preventDefault();
        setOpen(o => !o);
      }
      if (e.key === 'Escape') setOpen(false);
    };
    window.addEventListener('keydown', onKey);
    return () => window.removeEventListener('keydown', onKey);
  }, []);

  const selectSymbol = (symbol: string) => {
    setActiveSymbol(symbol);
    setOpen(false);
  };

  const onKeyDown = (e: React.KeyboardEvent) => {
    if (e.key === 'ArrowDown') {
      e.preventDefault();
      setCursor(c => Math.min(c + 1, results.length - 1));
    } else if (e.key === 'ArrowUp') {
      e.preventDefault();
      setCursor(c => Math.max(c - 1, 0));
    } else if (e.key === 'Enter') {
      if (results[cursor]) selectSymbol(results[cursor].symbol);
    }
  };

  if (!open) return null;

  return (
    <div
      className="fixed inset-0 z-50 flex items-start justify-center pt-[20vh]"
      style={{ background: 'rgba(0,0,0,0.6)', backdropFilter: 'blur(2px)' }}
      onClick={() => setOpen(false)}
    >
      <div
        className="w-full max-w-sm rounded-sm border border-[var(--border)] shadow-2xl shadow-black/80 overflow-hidden"
        style={{ background: 'var(--panel)' }}
        onClick={e => e.stopPropagation()}
      >
        {/* Search input */}
        <div className="flex items-center gap-2 px-3 py-2.5 border-b border-[var(--border)]">
          <Search className="w-3.5 h-3.5 text-[var(--muted-foreground)] shrink-0" />
          <input
            ref={inputRef}
            value={query}
            onChange={e => setQuery(e.target.value)}
            onKeyDown={onKeyDown}
            placeholder="Search symbol…"
            className="flex-1 bg-transparent text-xs font-mono text-[var(--foreground)] placeholder:text-[var(--muted-foreground)] placeholder:opacity-40 outline-none"
          />
          <kbd className="text-xs font-mono text-[var(--muted-foreground)] opacity-40 shrink-0">ESC</kbd>
        </div>

        {/* Results */}
        <div className="max-h-64 overflow-y-auto">
          {results.length === 0 ? (
            <div className="px-3 py-4 text-xs text-[var(--muted-foreground)] opacity-40 text-center">
              No symbols found
            </div>
          ) : (
            results.map((ticker, i) => (
              <button
                key={ticker.symbol}
                onClick={() => selectSymbol(ticker.symbol)}
                className={`w-full flex items-center justify-between px-3 py-2 text-xs font-mono transition-colors border-b border-[var(--border)]/40 last:border-b-0 ${
                  i === cursor
                    ? 'bg-[var(--kraken-purple)]/15 text-[var(--kraken-light)]'
                    : 'text-[var(--foreground)] hover:bg-[var(--panel-muted)]'
                }`}
              >
                <span className="flex items-center gap-2">
                  {ticker.symbol === activeSymbol && (
                    <span className="w-1 h-1 rounded-sm bg-[var(--kraken-purple)]" />
                  )}
                  <span className="font-bold">{ticker.symbol}</span>
                </span>
                <span className={`tabular-nums ${(ticker.change24h ?? 0) >= 0 ? 'text-[var(--neon-green)]' : 'text-[var(--neon-red)]'}`}>
                  {(ticker.change24h ?? 0) >= 0 ? '+' : ''}{(ticker.change24h ?? 0).toFixed(2)}%
                </span>
              </button>
            ))
          )}
        </div>

        <div className="px-3 py-1.5 border-t border-[var(--border)] flex items-center gap-3">
          <span className="text-xs text-[var(--muted-foreground)] opacity-40 font-mono">↑↓ navigate · ↵ select · ⌘K toggle</span>
        </div>
      </div>
    </div>
  );
}
