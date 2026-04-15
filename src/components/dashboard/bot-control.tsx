"use client"

import * as React from 'react';
import { Card, CardHeader, CardTitle, CardContent } from "@/components/ui/card";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { useTradingStore } from '@/hooks/useTradingStream';
import { ChevronDown, Square, Play, TrendingUp, TrendingDown } from 'lucide-react';

// ---------------------------------------------------------------------------
// Helpers
// ---------------------------------------------------------------------------

function statusVariant(status: string): 'success' | 'destructive' | 'warning' | 'outline' {
  if (status === 'ACTIVE') return 'success';
  if (status === 'HALTED') return 'destructive';
  if (status === 'DEGRADED') return 'warning';
  return 'outline';
}

// ---------------------------------------------------------------------------
// Bot Control Component
// ---------------------------------------------------------------------------

export function BotControl() {
  const logs               = useTradingStore(s => s.botLogs);
  const bots               = useTradingStore(s => s.bots);
  const fetchAPIIntegrations = useTradingStore(s => s.fetchAPIIntegrations);

  const [selectedBotId, setSelectedBotId] = React.useState<string | null>(null);
  const [dropdownOpen, setDropdownOpen]   = React.useState(false);
  const [actionPending, setActionPending] = React.useState<string | null>(null);
  const [mounted, setMounted]             = React.useState(false);
  const logEndRef = React.useRef<HTMLDivElement>(null);

  React.useEffect(() => setMounted(true), []);

  // Auto-select first bot when bots arrive
  React.useEffect(() => {
    if (bots.length > 0 && !selectedBotId) {
      setSelectedBotId(bots[0].id);
    }
  }, [bots, selectedBotId]);

  // Auto-scroll log to bottom on new entries
  React.useEffect(() => {
    logEndRef.current?.scrollIntoView({ behavior: 'smooth' });
  }, [logs.length]);

  const selectedBot = bots.find(b => b.id === selectedBotId) ?? null;

  const handleHalt = async () => {
    if (!selectedBot || actionPending) return;
    setActionPending('halt');
    try {
      await fetch(`http://localhost:8000/api/bots/${selectedBot.id}/halt`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ reason: 'Manual override via Bot Control' }),
      });
      await fetchAPIIntegrations();
    } catch (e) {
      console.error('[BOT CONTROL] Halt failed', e);
    } finally {
      setActionPending(null);
    }
  };

  const handleResume = async () => {
    if (!selectedBot || actionPending) return;
    setActionPending('resume');
    try {
      await fetch(`http://localhost:8000/api/bots/${selectedBot.id}/resume`, {
        method: 'POST',
      });
      await fetchAPIIntegrations();
    } catch (e) {
      console.error('[BOT CONTROL] Resume failed', e);
    } finally {
      setActionPending(null);
    }
  };

  const logColour = (log: string) => {
    if (log.includes('[SYSTEM]') || log.includes('[STREAM]'))                  return 'text-blue-400';
    if (log.includes('[EXECUTION]') && log.includes('FILLED'))                 return 'text-[var(--neon-green)]';
    if (log.includes('[EXECUTION]') && log.includes('FAILED'))                 return 'text-[var(--neon-red)]';
    if (log.includes('[SIGNAL]'))                                               return 'text-[var(--kraken-light)]';
    if (log.includes('[RISK AGENT] ✓'))                                         return 'text-emerald-400';
    if (log.includes('[RISK AGENT] ✗') || log.includes('Blocked'))             return 'text-[var(--neon-red)]';
    if (log.includes('[HEARTBEAT]'))                                            return 'text-[var(--muted-foreground)] opacity-30';
    return 'text-[var(--muted-foreground)]';
  };

  if (!mounted) return null;

  return (
    <Card className="flex flex-col h-full">
      <CardHeader className="py-2.5 px-3 flex flex-row items-center justify-between border-b border-[var(--border)]">
        <CardTitle className="text-xs uppercase tracking-wider font-semibold text-[var(--muted-foreground)]">Bot Control</CardTitle>
        <Badge variant={statusVariant(selectedBot?.status ?? '')}>
          {selectedBot?.status ?? 'AWAITING'}
        </Badge>
      </CardHeader>

      <CardContent className="p-0 flex flex-col flex-1 overflow-hidden">

        {/* ── Bot Selector ── */}
        <div className="px-3 py-2 border-b border-[var(--border)] bg-[var(--panel-muted)]/40">
          <div className="text-xs text-[var(--muted-foreground)] uppercase tracking-wider mb-1.5">Active Strategy</div>
          <div className="relative">
            <button
              onClick={() => setDropdownOpen(o => !o)}
              className="w-full flex items-center justify-between px-2.5 py-1.5 bg-[var(--panel-muted)] border border-[var(--border)] rounded-sm text-xs font-mono text-[var(--foreground)] hover:border-[var(--kraken-purple)]/50 transition-colors"
            >
              <span className="flex items-center gap-2">
                {selectedBot ? (
                  <>
                    <span className={`w-1.5 h-1.5 rounded-full ${
                      selectedBot.status === 'ACTIVE'
                        ? 'bg-[var(--neon-green)] shadow-[0_0_4px_var(--neon-green)]'
                        : 'bg-[var(--muted-foreground)]'
                    }`} />
                    <span className="font-semibold">{selectedBot.name}</span>
                    <span className="text-[var(--muted-foreground)] opacity-60">— {selectedBot.algo}</span>
                    {selectedBot.assetClass && selectedBot.assetClass !== 'CRYPTO' && (
                      <Badge variant="outline" className="text-xs px-1 py-0 leading-none opacity-60">
                        {selectedBot.assetClass}
                      </Badge>
                    )}
                  </>
                ) : (
                  <span className="text-[var(--muted-foreground)]">Loading agents...</span>
                )}
              </span>
              <ChevronDown className={`w-3 h-3 text-[var(--muted-foreground)] transition-transform ${dropdownOpen ? 'rotate-180' : ''}`} />
            </button>

            {dropdownOpen && bots.length > 0 && (
              <div className="absolute z-20 top-full left-0 right-0 mt-1 bg-[var(--panel)] border border-[var(--border)] rounded-sm shadow-xl shadow-black/60 overflow-hidden">
                {bots.map(bot => (
                  <button
                    key={bot.id}
                    onClick={() => { setSelectedBotId(bot.id); setDropdownOpen(false); }}
                    className={`w-full flex items-center justify-between px-2.5 py-2 text-xs font-mono hover:bg-[var(--panel-muted)] transition-colors border-b border-[var(--border)] last:border-b-0 ${
                      bot.id === selectedBotId
                        ? 'bg-[var(--panel-muted)] text-[var(--kraken-light)]'
                        : 'text-[var(--foreground)]'
                    }`}
                  >
                    <span className="flex items-center gap-2">
                      <span className={`w-1.5 h-1.5 rounded-full ${
                        bot.status === 'ACTIVE'
                          ? 'bg-[var(--neon-green)] shadow-[0_0_4px_var(--neon-green)]'
                          : 'bg-[var(--muted-foreground)]'
                      }`} />
                      <span>{bot.name}</span>
                      <span className="text-[var(--muted-foreground)] opacity-50">{bot.algo}</span>
                      {bot.assetClass && bot.assetClass !== 'CRYPTO' && (
                        <Badge variant="outline" className="text-xs px-1 py-0 leading-none opacity-60">
                          {bot.assetClass}
                        </Badge>
                      )}
                    </span>
                    <div className="flex items-center gap-2">
                      <span className={`font-mono tabular-nums ${(bot.yield24h ?? 0) >= 0 ? 'text-[var(--neon-green)]' : 'text-[var(--neon-red)]'}`}>
                        {(bot.yield24h ?? 0) >= 0 ? '+' : ''}${(bot.yield24h ?? 0).toFixed(2)}
                      </span>
                      <Badge variant={statusVariant(bot.status)} className="text-xs px-1">
                        {bot.status}
                      </Badge>
                    </div>
                  </button>
                ))}
              </div>
            )}
          </div>
        </div>

        {/* ── Selected Bot Stats ── */}
        {selectedBot && (
          <div className="px-3 py-2 border-b border-[var(--border)] grid grid-cols-4 gap-2 shrink-0">
            <div className="flex flex-col">
              <span className="text-xs text-[var(--muted-foreground)] uppercase tracking-wider mb-0.5">Alloc.</span>
              <span className="text-xs font-mono tabular-nums font-bold text-[var(--foreground)]">
                {(selectedBot.allocationPct ?? 0).toFixed(0)}%
              </span>
            </div>
            <div className="flex flex-col">
              <span className="text-xs text-[var(--muted-foreground)] uppercase tracking-wider mb-0.5">Gain 24h</span>
              <span className={`text-xs font-mono tabular-nums font-bold flex items-center gap-0.5 ${
                (selectedBot.yield24h ?? 0) >= 0 ? 'text-[var(--neon-green)]' : 'text-[var(--neon-red)]'
              }`}>
                {(selectedBot.yield24h ?? 0) >= 0
                  ? <TrendingUp className="w-3 h-3" />
                  : <TrendingDown className="w-3 h-3" />
                }
                {(selectedBot.yield24h ?? 0) >= 0 ? '+' : ''}${Math.abs(selectedBot.yield24h ?? 0).toFixed(2)}
              </span>
            </div>
            <div className="flex flex-col">
              <span className="text-xs text-[var(--muted-foreground)] uppercase tracking-wider mb-0.5">Signals</span>
              <span className="text-xs font-mono tabular-nums text-[var(--foreground)]">
                {(selectedBot.signalCount ?? 0).toLocaleString()}
              </span>
            </div>
            <div className="flex flex-col">
              <span className="text-xs text-[var(--muted-foreground)] uppercase tracking-wider mb-0.5">Fill Rate</span>
              <span className="text-xs font-mono tabular-nums text-[var(--foreground)]">
                {(selectedBot.signalCount ?? 0) > 0
                  ? `${(((selectedBot.fillCount ?? 0) / (selectedBot.signalCount ?? 1)) * 100).toFixed(0)}%`
                  : '—'}
              </span>
            </div>
          </div>
        )}

        {/* ── All Bots Strip — scrollable compact rows ── */}
        {bots.length > 1 && (
          <div className="border-b border-[var(--border)] shrink-0 overflow-y-auto max-h-[112px]">
            {bots.map(bot => (
              <button
                key={bot.id}
                onClick={() => setSelectedBotId(bot.id)}
                className={`w-full flex items-center justify-between px-3 py-1 text-xs font-mono transition-colors border-b border-[var(--border)]/40 last:border-b-0 ${
                  bot.id === selectedBotId
                    ? 'bg-[var(--kraken-purple)]/10 text-[var(--kraken-light)]'
                    : 'text-[var(--muted-foreground)] hover:bg-[var(--panel-muted)]'
                }`}
              >
                <div className="flex items-center gap-2 min-w-0">
                  <span className={`w-1 h-1 rounded-full shrink-0 ${bot.status === 'ACTIVE' ? 'bg-[var(--neon-green)]' : 'bg-[var(--muted-foreground)]'}`} />
                  <span className="truncate font-semibold">{bot.name}</span>
                  {bot.assetClass && bot.assetClass !== 'CRYPTO' && (
                    <span className="text-xs opacity-40 shrink-0">{bot.assetClass}</span>
                  )}
                </div>
                <span className={`tabular-nums font-mono shrink-0 ml-2 ${(bot.yield24h ?? 0) >= 0 ? 'text-[var(--neon-green)]' : 'text-[var(--neon-red)]'}`}>
                  {(bot.yield24h ?? 0) >= 0 ? '+' : ''}${Math.abs(bot.yield24h ?? 0).toFixed(2)}
                </span>
              </button>
            ))}
          </div>
        )}

        {/* ── Halt / Resume Controls ── */}
        <div className="px-3 py-2 border-b border-[var(--border)] flex gap-2 shrink-0">
          <Button
            variant="destructive"
            className="flex-1 h-7 text-xs uppercase tracking-wider font-bold"
            onClick={handleHalt}
            disabled={!selectedBot || selectedBot.status === 'HALTED' || !!actionPending}
          >
            <Square className="w-3 h-3 mr-1" />
            {actionPending === 'halt' ? 'Halting...' : 'Halt'}
          </Button>
          <Button
            variant="success"
            className="flex-1 h-7 text-xs uppercase tracking-wider font-bold"
            onClick={handleResume}
            disabled={!selectedBot || selectedBot.status === 'ACTIVE' || !!actionPending}
          >
            <Play className="w-3 h-3 mr-1" />
            {actionPending === 'resume' ? 'Resuming...' : 'Resume'}
          </Button>
        </div>

        {/* ── Console Logs ── */}
        <div className="flex-1 p-3 bg-[#050505] overflow-y-auto font-mono text-xs leading-relaxed space-y-0.5">
          {logs.length === 0 && (
            <div className="text-[var(--muted-foreground)] opacity-40">[SYSTEM] Awaiting first bar data from Alpaca stream...</div>
          )}
          {logs.map((log, i) => {
            const now = new Date();
            const ts = `${String(now.getHours()).padStart(2,'0')}:${String(now.getMinutes()).padStart(2,'0')}:${String(now.getSeconds()).padStart(2,'0')}`;
            return (
              <div key={i} className={logColour(log)}>
                <span className="opacity-40 select-none mr-2">{ts}</span>
                {log}
              </div>
            );
          })}
          <div ref={logEndRef} />
          <div className="animate-pulse text-[var(--muted-foreground)] opacity-30 mt-1">█</div>
        </div>
      </CardContent>
    </Card>
  );
}
