"use client"

import { API_BASE } from '@/lib/api';
import * as React from 'react';
import { Card, CardHeader, CardTitle, CardContent } from "@/components/ui/card";
import { BrainCircuit, SearchCode, Zap, Eye, Calculator, GraduationCap, Filter, Bot, Sparkles } from 'lucide-react';
import { Badge } from "@/components/ui/badge";
import { useTradingStore } from '@/hooks/useTradingStream';

// ---------------------------------------------------------------------------
// Type helpers
// ---------------------------------------------------------------------------

interface ReflectionEntry {
  strategy?: string;
  action?: string;
  symbol?: string;
  confidence?: number;
  qty?: number;
  kelly_fraction?: number;
  meta?: Record<string, unknown>;
  timestamp?: string;
  type?: string;
  text?: string;
  state?: Record<string, unknown>;
  // Learning & Amends fields
  model?: string;
  reason?: string;
  impact?: string;
  date?: string;
  // Trade learning fields
  fill_price?: number;
  slippage?: number;
}

// Reflection type → visual style mapping
const TYPE_STYLES: Record<string, { icon: typeof Zap; label: string; color: string; border: string; bg: string }> = {
  observe:   { icon: Eye,            label: 'OBSERVE',   color: 'text-purple-400',                    border: 'border-purple-500/30',                bg: 'bg-purple-500/5' },
  calculate: { icon: Calculator,     label: 'POSITION',  color: 'text-blue-400',                      border: 'border-blue-500/30',                  bg: 'bg-blue-500/5' },
  decision:  { icon: Zap,            label: 'DECISION',  color: 'text-[var(--neon-green)]',           border: 'border-[var(--neon-green)]/40',       bg: 'bg-[var(--neon-green)]/5' },
  learning:  { icon: GraduationCap,  label: 'LEARNED',   color: 'text-amber-400',                     border: 'border-amber-500/30',                 bg: 'bg-amber-500/5' },
  director:  { icon: Bot,            label: 'DIRECTOR',  color: 'text-[var(--kraken-light)]',         border: 'border-[var(--kraken-purple)]/50',    bg: 'bg-[var(--kraken-purple)]/8' },
  scanner:   { icon: Sparkles,       label: 'SCANNER',   color: 'text-cyan-400',                      border: 'border-cyan-500/30',                  bg: 'bg-cyan-500/5' },
};

function getTypeStyle(type: string | undefined) {
  return TYPE_STYLES[type ?? ''] ?? TYPE_STYLES['observe'];
}

function formatTimestamp(ts: string | undefined): string {
  if (!ts) return 'Live';
  try {
    return new Date(ts).toLocaleTimeString('en-US', { hour12: false });
  } catch {
    return ts;
  }
}

// Convert a reflection payload into a display line
function reflectionToDisplay(r: ReflectionEntry): { time: string; text: string; type: string; strategy: string; symbol: string } {
  const time = formatTimestamp(r.timestamp);
  const strategy = r.strategy ?? 'system';
  const symbol = r.symbol ?? '';

  // Scanner events — Haiku-ranked symbol picks
  if (r.type === 'scanner') {
    const results = (r as any).results as any[] | undefined;
    if (results && results.length > 0) {
      const top = results[0];
      const picks = results.slice(0, 3).map((x: any) => `${x.symbol}(${x.signal})`).join(' · ');
      const text = `Top picks: ${picks} — ${top.symbol}: ${top.verdict ?? top.summary ?? ''}`;
      return { time, type: 'scanner', text, strategy: 'scanner', symbol: top.symbol ?? '' };
    }
    return { time, type: 'scanner', text: r.text ?? 'Scanner update', strategy: 'scanner', symbol: '' };
  }

  // Director autonomous action events
  if (r.type === 'director') {
    const entry = r as ReflectionEntry & { action?: string; target_bot?: string; success?: boolean };
    const status = entry.success === false ? '✗' : '✓';
    const text = `[${status}] ${entry.action ?? 'ACTION'} → ${(entry as any).target_bot ?? 'portfolio'}: ${r.reason ?? ''}`;
    return { time, type: 'director', text, strategy: 'director', symbol: (entry as any).target_bot ?? '' };
  }

  // If the reflection has a pre-formatted text field, use it
  if (r.text) {
    return { time, type: r.type ?? 'observe', text: r.text, strategy, symbol };
  }

  // Legacy format: action + symbol signals
  if (r.action && r.symbol) {
    const meta = r.meta ?? {};
    const metaStr = Object.entries(meta)
      .map(([k, v]) => `${k}=${typeof v === 'number' ? (v as number).toFixed(4) : v}`)
      .join(' · ');

    return {
      time,
      type: r.type ?? 'decision',
      strategy,
      symbol,
      text: `${r.strategy?.toUpperCase()} → ${r.action} ${r.symbol} @ conf=${r.confidence?.toFixed(2)} qty=${r.qty?.toFixed(6)} kelly=${r.kelly_fraction?.toFixed(4)}${metaStr ? ` | ${metaStr}` : ''}`,
    };
  }

  return { time, type: 'observe', text: JSON.stringify(r), strategy, symbol };
}

// ---------------------------------------------------------------------------
// Filter types
// ---------------------------------------------------------------------------
type FilterType = 'ALL' | 'observe' | 'calculate' | 'decision' | 'learning' | 'director' | 'scanner';
const FILTER_OPTIONS: { value: FilterType; label: string; color: string }[] = [
  { value: 'ALL',       label: 'All',        color: 'text-[var(--foreground)]' },
  { value: 'observe',   label: 'Observe',    color: 'text-purple-400' },
  { value: 'calculate', label: 'Position',   color: 'text-blue-400' },
  { value: 'decision',  label: 'Decision',   color: 'text-[var(--neon-green)]' },
  { value: 'learning',  label: 'Learning',   color: 'text-amber-400' },
  { value: 'director',  label: 'Director',   color: 'text-[var(--kraken-light)]' },
  { value: 'scanner',   label: 'Scanner',    color: 'text-cyan-400' },
];

// ---------------------------------------------------------------------------
// Component
// ---------------------------------------------------------------------------

export function BotReflections() {
  const learningHistory = useTradingStore(s => s.learningHistory) as ReflectionEntry[];
  const strategyStates = useTradingStore(s => s.strategyStates);
  const [mounted, setMounted] = React.useState(false);
  const [filter, setFilter] = React.useState<FilterType>('ALL');
  const [strategyFilter, setStrategyFilter] = React.useState<string>('ALL');
  const scrollRef = React.useRef<HTMLDivElement>(null);

  React.useEffect(() => { setMounted(true); }, []);

  const entries = React.useMemo(() => {
    return learningHistory
      .map(reflectionToDisplay)
      .filter(e => filter === 'ALL' || e.type === filter)
      .filter(e => strategyFilter === 'ALL' || e.strategy === strategyFilter);
  }, [learningHistory, filter, strategyFilter]);

  // Auto-scroll to top (newest first)
  React.useEffect(() => {
    if (scrollRef.current) {
      scrollRef.current.scrollTop = 0;
    }
  }, [entries.length]);

  // Collect unique strategies from history
  const strategies = React.useMemo(() => {
    const set = new Set<string>();
    learningHistory.forEach(r => { if (r.strategy) set.add(r.strategy); });
    return Array.from(set);
  }, [learningHistory]);

  if (!mounted) return (
    <div className="flex h-full gap-4">
      <Card className="flex-1 flex flex-col bg-[var(--panel)]">
        <CardContent className="flex-1 flex items-center justify-center">
          <div className="text-xs text-[var(--muted-foreground)] opacity-50">Loading Brain...</div>
        </CardContent>
      </Card>
    </div>
  );

  return (
    <div className="flex h-full gap-4">

      {/* ------------------------------------------------------------------ */}
      {/* Left: Historical Amends (DB-backed via /api/reflections)            */}
      {/* ------------------------------------------------------------------ */}
      <HistoricalAmends />

      {/* ------------------------------------------------------------------ */}
      {/* Right: Live Thought Matrix (SSE stream via /api/reflections/stream) */}
      {/* ------------------------------------------------------------------ */}
      <div className="flex-[2] flex flex-col gap-4">
        {/* Strategy Mental Model Panel */}
        <StrategyMentalModel states={strategyStates} />

        {/* Live Thought Stream */}
        <Card className="flex-1 flex flex-col bg-[var(--panel)]">
          <CardHeader className="py-3 border-b border-[var(--border)] flex flex-row items-center justify-between">
            <div className="flex items-center space-x-3">
              <SearchCode className="w-5 h-5 text-[var(--kraken-light)]" />
              <div className="flex flex-col">
                <CardTitle className="text-sm tracking-wide">Live Thought Matrix</CardTitle>
                <span className="text-xs text-[var(--muted-foreground)] uppercase">
                  Agent Internal Monologue
                </span>
              </div>
            </div>

            {/* Filter bar */}
            <div className="flex items-center gap-2">
              <Filter className="w-3.5 h-3.5 text-[var(--muted-foreground)]" />
              <div className="flex gap-1">
                {FILTER_OPTIONS.map(opt => (
                  <button
                    key={opt.value}
                    onClick={() => setFilter(opt.value)}
                    className={`px-2 py-0.5 text-xs rounded font-mono transition-all duration-200 ${
                      filter === opt.value
                        ? `${opt.color} bg-white/10 shadow-sm`
                        : 'text-[var(--muted-foreground)] hover:text-[var(--foreground)] hover:bg-white/5'
                    }`}
                  >
                    {opt.label}
                  </button>
                ))}
              </div>
              {strategies.length > 1 && (
                <select
                  value={strategyFilter}
                  onChange={e => setStrategyFilter(e.target.value)}
                  className="ml-2 px-2 py-0.5 text-xs rounded bg-[var(--panel-muted)] text-[var(--foreground)] border border-[var(--border)] font-mono"
                >
                  <option value="ALL">All Bots</option>
                  {strategies.map(s => (
                    <option key={s} value={s}>{s}</option>
                  ))}
                </select>
              )}
            </div>
          </CardHeader>
          <CardContent
            ref={scrollRef}
            className="flex-1 overflow-y-auto p-0 bg-[var(--background)]"
          >
            <div className="p-4 flex flex-col space-y-2 font-mono text-xs">
              {entries.length === 0 ? (
                <>
                  <div className="flex items-start space-x-3 p-2 rounded border border-[var(--border)] bg-[var(--panel-muted)]/30">
                    <span className="text-[var(--muted-foreground)] shrink-0">[SYSTEM]</span>
                    <span className="text-[var(--foreground)] leading-relaxed">
                      Initializing strategy engine... awaiting live market data.
                    </span>
                  </div>
                  <div className="flex items-start space-x-3 p-2 rounded border border-[var(--border)] bg-[var(--panel-muted)]/30">
                    <span className="text-[var(--muted-foreground)] shrink-0">[STREAM]</span>
                    <span className="text-[var(--foreground)] leading-relaxed">
                      Connecting to Alpaca CryptoDataStream — BTC/USD · ETH/USD · SOL/USD
                    </span>
                  </div>
                </>
              ) : (
                entries.map((t, i) => {
                  const style = getTypeStyle(t.type);
                  const Icon = style.icon;
                  return (
                    <div
                      key={i}
                      className={`flex items-start space-x-3 p-2 rounded border ${style.border} ${style.bg} transition-all duration-300 ${
                        i === 0 ? 'animate-in fade-in slide-in-from-top-1 duration-500' : ''
                      }`}
                    >
                      <span className="text-[var(--muted-foreground)] shrink-0 w-[60px]">[{t.time}]</span>
                      <Badge
                        variant="outline"
                        className={`shrink-0 px-1.5 py-0 text-[10px] font-mono ${style.color} border-current/30`}
                      >
                        <Icon className="w-2.5 h-2.5 mr-1 inline" />
                        {style.label}
                      </Badge>
                      <span className={`leading-relaxed break-all ${style.color}`}>{t.text}</span>
                    </div>
                  );
                })
              )}
              <div className="flex items-center space-x-2 p-2 opacity-50">
                <div className="w-1.5 h-1.5 rounded-sm bg-[var(--kraken-purple)] animate-pulse" />
                <span className="italic text-[var(--muted-foreground)]">
                  Listening to strategy engine signals...
                </span>
              </div>
            </div>
          </CardContent>
        </Card>
      </div>
    </div>
  );
}

// ---------------------------------------------------------------------------
// Strategy Mental Model Panel
// ---------------------------------------------------------------------------

function StrategyMentalModel({ states }: { states: Record<string, any[]> }) {
  const symbols = Object.keys(states);

  if (symbols.length === 0) {
    return (
      <Card className="bg-[var(--panel)] border-[var(--border)]">
        <CardHeader className="py-3 border-b border-[var(--border)] flex flex-row items-center space-x-3">
          <BrainCircuit className="w-4 h-4 text-[var(--kraken-purple)]" />
          <CardTitle className="text-xs tracking-wide uppercase">Strategy Mental Model</CardTitle>
        </CardHeader>
        <CardContent className="py-3">
          <p className="text-xs text-[var(--muted-foreground)] italic opacity-60">
            Awaiting market data — strategy states will appear once the stream connects...
          </p>
        </CardContent>
      </Card>
    );
  }

  return (
    <Card className="bg-[var(--panel)] border-[var(--border)]">
      <CardHeader className="py-3 border-b border-[var(--kraken-purple)]/20 flex flex-row items-center space-x-3 bg-gradient-to-r from-[var(--kraken-purple)]/5 to-transparent">
        <BrainCircuit className="w-4 h-4 text-[var(--kraken-purple)]" />
        <CardTitle className="text-xs tracking-wide uppercase">Strategy Mental Model</CardTitle>
      </CardHeader>
      <CardContent className="py-3 px-4">
        <div className="grid grid-cols-1 md:grid-cols-3 gap-3">
          {symbols.slice(0, 1).map(symbol =>
            (states[symbol] ?? []).map((state: any, idx: number) => {
              const strategyId = state.strategy ?? 'unknown';
              const name = state.name ?? strategyId;
              const botStatus = state.bot_status ?? 'UNKNOWN';

              let summary = '';
              let biasColor = 'text-[var(--muted-foreground)]';

              if (strategyId === 'momentum-alpha') {
                const spread = state.spread_pct ?? 0;
                const bias = state.bias ?? 'NEUTRAL';
                const near = state.near_crossover;
                summary = `EMA spread: ${spread > 0 ? '+' : ''}${spread.toFixed(4)}%`;
                if (near) summary += ' ⚡ Near crossover';
                summary += ` | Bias: ${bias}`;
                biasColor = bias === 'BULLISH' ? 'text-[var(--neon-green)]' : bias === 'BEARISH' ? 'text-red-400' : 'text-[var(--muted-foreground)]';
              } else if (strategyId === 'statarb-gamma') {
                if (state.status === 'warming_up') {
                  summary = `Warming up (${state.ticks_collected ?? 0}/20 ticks)`;
                } else {
                  const pos = state.position_in_band_pct ?? 50;
                  const zone = state.zone ?? 'NEUTRAL';
                  summary = `BB position: ${pos.toFixed(0)}th pctile | Zone: ${zone}`;
                  biasColor = zone === 'OVERSOLD' ? 'text-[var(--neon-green)]' : zone === 'OVERBOUGHT' ? 'text-red-400' : 'text-[var(--muted-foreground)]';
                }
              } else if (strategyId === 'hft-sniper') {
                if (botStatus === 'HALTED') {
                  summary = 'HALTED — awaiting activation';
                  biasColor = 'text-[var(--muted-foreground)]';
                } else {
                  const mom = state.momentum_pct ?? 0;
                  summary = `Momentum: ${mom > 0 ? '+' : ''}${mom.toFixed(5)}%`;
                }
              }

              const statusDot = botStatus === 'ACTIVE'
                ? 'bg-[var(--neon-green)] shadow-[0_0_6px_rgba(0,255,136,0.5)]'
                : 'bg-[var(--muted-foreground)]';

              return (
                <div
                  key={`${symbol}-${strategyId}-${idx}`}
                  className="flex items-start space-x-3 p-2.5 rounded border border-[var(--border)] bg-[var(--panel-muted)]/20"
                >
                  <div className={`w-2 h-2 mt-1 rounded-sm ${statusDot} shrink-0`} />
                  <div className="flex flex-col min-w-0">
                    <span className="text-xs font-bold text-[var(--foreground)] truncate">{name}</span>
                    <span className={`text-[10px] font-mono ${biasColor} leading-relaxed mt-0.5`}>
                      {summary}
                    </span>
                  </div>
                </div>
              );
            })
          )}
        </div>
      </CardContent>
    </Card>
  );
}

// ---------------------------------------------------------------------------
// Historical Amends column — fetches /api/reflections on mount
// ---------------------------------------------------------------------------

function HistoricalAmends() {
  const [mounted, setMounted] = React.useState(false);
  const [amends, setAmends]   = React.useState<ReflectionEntry[]>([]);

  React.useEffect(() => {
    setMounted(true);
    fetch(`${API_BASE}/api/reflections`)
      .then(r => r.ok ? r.json() : [])
      .then(setAmends)
      .catch(() => {});
  }, []);

  if (!mounted) return (
    <Card className="flex-1 flex flex-col bg-[var(--panel)]">
      <CardContent className="flex-1 flex items-center justify-center">
        <div className="text-xs text-[var(--muted-foreground)] opacity-50">Loading...</div>
      </CardContent>
    </Card>
  );

  return (
    <Card className="flex-1 flex flex-col bg-[var(--panel)]">
      <CardHeader className="py-4 border-b border-[var(--kraken-purple)]/30 flex flex-row items-center space-x-3 bg-gradient-to-r from-[var(--kraken-purple)]/10 to-transparent">
        <BrainCircuit className="w-5 h-5 text-[var(--kraken-purple)]" />
        <CardTitle className="text-sm tracking-wide">Historical Learning & Amends</CardTitle>
      </CardHeader>
      <CardContent className="flex-1 overflow-y-auto p-4 space-y-4">
        {amends.length === 0 ? (
          <div className="text-xs text-[var(--muted-foreground)] opacity-50 italic">
            No learning records yet — amends are generated after strategy performance analysis.
          </div>
        ) : amends.map((item, i) => (
          <div key={i} className="relative pl-6 pb-2 border-l border-[var(--border)] last:border-l-transparent">
            <div className="absolute left-[-5px] top-1 w-2.5 h-2.5 rounded-sm bg-[var(--kraken-purple)] shadow-[0_0_8px_rgba(139,92,246,0.8)]" />
            <div className="flex justify-between items-start mb-1">
              <div className="flex items-center space-x-2">
                <Badge variant="purple" className="px-1.5 py-0 text-xs">
                  {item.action ?? 'LEARNED'}
                </Badge>
                <span className="text-xs text-[var(--foreground)] font-bold">
                  {item.model ?? 'Orchestrator'}
                </span>
              </div>
              <span className="text-xs text-[var(--muted-foreground)] font-mono">
                {item.date ?? 'Live'}
              </span>
            </div>
            <p className="text-xs text-[var(--muted-foreground)] mb-2 mt-2 leading-relaxed">
              {item.reason}
            </p>
            <div className="text-xs text-[var(--neon-green)] font-mono tracking-wider font-bold">
              IMPACT: {item.impact ?? 'Analyzing...'}
            </div>
          </div>
        ))}
      </CardContent>
    </Card>
  );
}
