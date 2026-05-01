"use client"

import { API_BASE } from '@/lib/api';
import * as React from 'react';
import { Card, CardHeader, CardTitle, CardContent } from "@/components/ui/card";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { useTradingStore } from '@/store';
import { collapseRepeats } from '@/lib/utils';
import { ChevronDown, Square, Play, TrendingUp, TrendingDown, Zap } from 'lucide-react';

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
  const lastSignal         = useTradingStore(s => s.lastSignal);
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
  const isHalted = selectedBot?.status === 'HALTED';

  // Keyboard shortcuts: Shift+H = halt, Shift+R = resume
  React.useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      if (!e.shiftKey || e.target instanceof HTMLInputElement || e.target instanceof HTMLTextAreaElement) return;
      if (e.key === 'H') handleHalt();
      if (e.key === 'R') handleResume();
    };
    window.addEventListener('keydown', onKey);
    return () => window.removeEventListener('keydown', onKey);
  // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [selectedBot, actionPending]);

  const handleHalt = async () => {
    if (!selectedBot || actionPending) return;
    setActionPending('halt');
    try {
      await fetch(`${API_BASE}/api/bots/${selectedBot.id}/halt`, {
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
      await fetch(`${API_BASE}/api/bots/${selectedBot.id}/resume`, {
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
    if (log.includes('[SYSTEM]') || log.includes('[STREAM]'))                  return 'text-[var(--neon-blue)]';
    if (log.includes('[EXECUTION]') && log.includes('FILLED'))                 return 'text-[var(--neon-green)]';
    if (log.includes('[EXECUTION]') && log.includes('FAILED'))                 return 'text-[var(--neon-red)]';
    if (log.includes('[SIGNAL]'))                                               return 'text-[var(--kraken-light)]';
    if (log.includes('[RISK AGENT] ✓'))                                         return 'text-[var(--neon-green)]';
    if (log.includes('[RISK AGENT] ✗') || log.includes('Blocked'))             return 'text-[var(--neon-red)]';
    if (log.includes('[HEARTBEAT]'))                                            return 'text-[var(--muted-foreground)] opacity-40';
    return 'text-[var(--muted-foreground)]';
  };

  const collapsedLogs = React.useMemo(() => collapseRepeats(logs), [logs]);

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

        {/* ── HALT Banner ── */}
        {isHalted && (
          <div className="px-3 py-1.5 bg-[var(--neon-red)]/10 border-b border-[var(--neon-red)]/40 flex items-center gap-2 shrink-0">
            <Square className="w-3 h-3 text-[var(--neon-red)] shrink-0" />
            <span className="text-xs font-bold text-[var(--neon-red)] uppercase tracking-wider">
              Bot Halted — All order entry suspended
            </span>
          </div>
        )}

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
                    <span className={`w-1.5 h-1.5 rounded-sm ${
                      selectedBot.status === 'ACTIVE'
                        ? 'bg-[var(--neon-green)] shadow-[0_0_4px_var(--neon-green)]'
                        : selectedBot.status === 'HALTED'
                        ? 'bg-[var(--neon-red)]'
                        : 'bg-[var(--muted-foreground)]'
                    }`} />
                    <span className="font-semibold">{selectedBot.name}</span>
                    <span className="text-[var(--muted-foreground)] opacity-60">· {selectedBot.algo}</span>
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
                      <span className={`w-1.5 h-1.5 rounded-sm ${
                        bot.status === 'ACTIVE'
                          ? 'bg-[var(--neon-green)] shadow-[0_0_4px_var(--neon-green)]'
                          : bot.status === 'HALTED'
                          ? 'bg-[var(--neon-red)]'
                          : 'bg-[var(--muted-foreground)]'
                      }`} />
                      <span>{bot.name}</span>
                      <span className="text-[var(--muted-foreground)] opacity-50">· {bot.algo}</span>
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
            {/* Last Signal (replaces static Alloc %) */}
            <div className="flex flex-col col-span-1">
              <span className="text-xs text-[var(--muted-foreground)] uppercase tracking-wider mb-0.5">Last Signal</span>
              {lastSignal ? (
                <span className={`text-xs font-mono tabular-nums font-bold flex items-center gap-0.5 ${
                  lastSignal.action === 'BUY' ? 'text-[var(--neon-green)]' : 'text-[var(--neon-red)]'
                }`}>
                  <Zap className="w-3 h-3 shrink-0" />
                  {lastSignal.symbol}
                </span>
              ) : (
                <span className="text-xs font-mono tabular-nums text-[var(--muted-foreground)] opacity-40">—</span>
              )}
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

        {/* ── Halt / Resume Controls — only one is visible at a time ── */}
        <div className="px-3 py-2 border-b border-[var(--border)] flex gap-2 shrink-0">
          <Button
            variant="destructive"
            className={`flex-1 h-7 text-xs uppercase tracking-wider font-bold ${isHalted ? 'hidden' : ''}`}
            onClick={handleHalt}
            disabled={!selectedBot || !!actionPending}
          >
            <Square className="w-3 h-3 mr-1" />
            {actionPending === 'halt' ? 'Halting...' : 'Halt [⇧H]'}
          </Button>
          <Button
            variant="success"
            className={`flex-1 h-7 text-xs uppercase tracking-wider font-bold ${!isHalted ? 'hidden' : ''}`}
            onClick={handleResume}
            disabled={!selectedBot || !!actionPending}
          >
            <Play className="w-3 h-3 mr-1" />
            {actionPending === 'resume' ? 'Resuming...' : 'Resume [⇧R]'}
          </Button>
        </div>

        {/* ── Console Logs ── */}
        <div className="flex-1 p-3 bg-[var(--panel)] overflow-y-auto font-mono text-xs leading-relaxed space-y-0.5">
          {collapsedLogs.length === 0 && (
            <div className="text-[var(--muted-foreground)] opacity-40">[SYSTEM] Awaiting first bar data from Alpaca stream...</div>
          )}
          {collapsedLogs.map(({ message, count }, i) => {
            const now = new Date();
            const ts = `${String(now.getHours()).padStart(2,'0')}:${String(now.getMinutes()).padStart(2,'0')}:${String(now.getSeconds()).padStart(2,'0')}`;
            return (
              <div key={i} className={`flex items-baseline gap-1.5 ${logColour(message)}`}>
                <span className="opacity-40 select-none shrink-0">{ts}</span>
                <span className="flex-1">{message}</span>
                {count > 1 && (
                  <span className="shrink-0 px-1 py-0 rounded-sm bg-[var(--panel-muted)] text-[var(--muted-foreground)] opacity-60 text-xs tabular-nums">
                    ×{count}
                  </span>
                )}
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
