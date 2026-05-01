"use client"

import { API_BASE } from '@/lib/api';
import * as React from 'react';
import {
  useReactTable,
  getCoreRowModel,
  getSortedRowModel,
  flexRender,
  type ColumnDef,
  type SortingState,
} from '@tanstack/react-table';
import { Card, CardHeader, CardTitle, CardContent } from "@/components/ui/card";
import { BrainCircuit, SearchCode, Zap, GraduationCap, Bot, Sparkles } from 'lucide-react';
import { Badge } from "@/components/ui/badge";
import { useTradingStore } from '@/store';
import { parseUtc } from '@/lib/utils';

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
  model?: string;
  reason?: string;
  impact?: string;
  date?: string;
  fill_price?: number;
  slippage?: number;
  target_bot?: string;
  success?: boolean;
}

function formatTimestamp(ts: string | number | undefined): string {
  if (!ts) return 'Live';
  try {
    return (parseUtc(ts) ?? new Date()).toLocaleString(undefined, { month: 'short', day: 'numeric', hour: '2-digit', minute: '2-digit', second: '2-digit', hour12: false });
  } catch {
    return String(ts);
  }
}

// ---------------------------------------------------------------------------
// Zone 1 — Agent Cards
// ---------------------------------------------------------------------------

function ScannerCard({ entries }: { entries: ReflectionEntry[] }) {
  const latest = entries.slice(0, 5);
  return (
    <Card className="flex flex-col bg-[var(--panel)] border-[var(--border)] overflow-hidden">
      <CardHeader className="py-3 px-4 border-b border-[var(--border)] flex flex-row items-center space-x-2 bg-[var(--panel)] shrink-0">
        <Sparkles className="w-4 h-4 text-[var(--agent-scanner)]" />
        <CardTitle className="text-xs tracking-wide uppercase text-[var(--agent-scanner)]">Scanner</CardTitle>
        {entries.length > 0 && (
          <span className="ml-auto font-mono tabular-nums text-xs text-[var(--muted-foreground)] opacity-50">
            {formatTimestamp(entries[0].timestamp)}
          </span>
        )}
      </CardHeader>
      <CardContent className="flex-1 overflow-y-auto p-3 space-y-2">
        {latest.length === 0 ? (
          <p className="text-xs text-[var(--muted-foreground)] opacity-50 italic">
            Scanner idle — next scan in ~5min
          </p>
        ) : latest.map((entry, i) => {
          const results = (entry as any).results as any[] | undefined;
          if (results && results.length > 0) {
            return (
              <div key={i} className="space-y-1.5">
                {results.slice(0, 4).map((r: any, j: number) => (
                  <div key={j} className="flex items-center gap-2">
                    <span className="font-mono tabular-nums text-xs text-[var(--foreground)] w-[76px] shrink-0">{r.symbol}</span>
                    <Badge variant="outline" className={`shrink-0 text-xs font-mono px-1.5 py-0 ${r.signal === 'BUY' ? 'text-[var(--neon-green)] border-[var(--neon-green)]/30' : r.signal === 'SELL' ? 'text-[var(--neon-red)] border-[var(--neon-red)]/30' : 'text-[var(--muted-foreground)]'}`}>
                      {r.signal ?? 'HOLD'}
                    </Badge>
                    <span className="text-xs text-[var(--muted-foreground)] truncate">{r.verdict ?? r.summary ?? ''}</span>
                  </div>
                ))}
              </div>
            );
          }
          return (
            <p key={i} className="text-xs text-[var(--muted-foreground)]">{entry.text ?? 'Scanner update'}</p>
          );
        })}
      </CardContent>
    </Card>
  );
}

function ResearchCard({ entries }: { entries: ReflectionEntry[] }) {
  const latest = entries.slice(0, 3);
  return (
    <Card className="flex flex-col bg-[var(--panel)] border-[var(--border)] overflow-hidden">
      <CardHeader className="py-3 px-4 border-b border-[var(--border)] flex flex-row items-center space-x-2 bg-[var(--panel)] shrink-0">
        <SearchCode className="w-4 h-4 text-[var(--agent-research)]" />
        <CardTitle className="text-xs tracking-wide uppercase text-[var(--agent-research)]">Research</CardTitle>
        {entries.length > 0 && (
          <span className="ml-auto font-mono tabular-nums text-xs text-[var(--muted-foreground)] opacity-50">
            {formatTimestamp(entries[0].timestamp)}
          </span>
        )}
      </CardHeader>
      <CardContent className="flex-1 overflow-y-auto p-3 space-y-3">
        {latest.length === 0 ? (
          <p className="text-xs text-[var(--muted-foreground)] opacity-50 italic">
            Awaiting research brief...
          </p>
        ) : latest.map((entry, i) => {
          const raw = entry as any;
          const theme = raw.macro_theme ?? entry.text ?? '';
          const focus: string[] = Array.isArray(raw.focus) ? raw.focus : [];
          return (
            <div key={i} className="space-y-1.5">
              {theme && (
                <p className="text-xs text-[var(--foreground)] leading-relaxed line-clamp-3">{theme}</p>
              )}
              {focus.length > 0 && (
                <div className="flex flex-wrap gap-1">
                  {focus.slice(0, 5).map((sym: string) => (
                    <span key={sym} className="font-mono tabular-nums text-xs text-[var(--kraken-light)] bg-[var(--panel-muted)] px-1.5 py-0.5 rounded-sm">
                      {sym}
                    </span>
                  ))}
                </div>
              )}
            </div>
          );
        })}
      </CardContent>
    </Card>
  );
}

function DirectorCard({ entries }: { entries: ReflectionEntry[] }) {
  const latest = entries.slice(0, 5);
  return (
    <Card className="flex flex-col bg-[var(--panel)] border-[var(--border)] overflow-hidden">
      <CardHeader className="py-3 px-4 border-b border-[var(--border)] flex flex-row items-center space-x-2 bg-[var(--panel)] shrink-0">
        <Bot className="w-4 h-4 text-[var(--agent-execute)]" />
        <CardTitle className="text-xs tracking-wide uppercase text-[var(--agent-execute)]">Director</CardTitle>
        {entries.length > 0 && (
          <span className="ml-auto font-mono tabular-nums text-xs text-[var(--muted-foreground)] opacity-50">
            {formatTimestamp(entries[0].timestamp)}
          </span>
        )}
      </CardHeader>
      <CardContent className="flex-1 overflow-y-auto p-3 space-y-2">
        {latest.length === 0 ? (
          <p className="text-xs text-[var(--muted-foreground)] opacity-50 italic">
            Director quiet — next cycle in ~15min
          </p>
        ) : latest.map((entry, i) => (
          <div key={i} className="flex items-start gap-2">
            <span className={`shrink-0 text-xs font-bold leading-4 ${entry.success === false ? 'text-[var(--neon-red)]' : 'text-[var(--neon-green)]'}`}>
              {entry.success === false ? '✗' : '✓'}
            </span>
            <div className="min-w-0 flex-1">
              <div className="flex items-center gap-1.5 mb-0.5 flex-wrap">
                <Badge variant="outline" className="text-xs font-mono px-1.5 py-0 text-[var(--agent-execute)] border-[var(--agent-execute)]/30">
                  {entry.action ?? 'ACTION'}
                </Badge>
                {entry.target_bot && (
                  <span className="text-xs font-mono text-[var(--muted-foreground)]">→ {entry.target_bot}</span>
                )}
              </div>
              {entry.reason && (
                <p className="text-xs text-[var(--muted-foreground)] leading-relaxed truncate">{entry.reason}</p>
              )}
            </div>
          </div>
        ))}
      </CardContent>
    </Card>
  );
}

// ---------------------------------------------------------------------------
// Signals & Learnings log (replaces Live Thought Matrix)
// ---------------------------------------------------------------------------

function SignalsLog({ entries }: { entries: ReflectionEntry[] }) {
  const scrollRef = React.useRef<HTMLDivElement>(null);
  const prevLen   = React.useRef(0);

  React.useEffect(() => {
    if (entries.length > prevLen.current && scrollRef.current) {
      scrollRef.current.scrollTop = 0;
    }
    prevLen.current = entries.length;
  }, [entries.length]);

  const isLive = entries.length > 0;

  return (
    <Card className="flex-1 min-h-0 flex flex-col bg-[var(--panel)]">
      <CardHeader className="py-3 border-b border-[var(--border)] flex flex-row items-center space-x-3 bg-[var(--panel)] shrink-0">
        <Zap className="w-4 h-4 text-[var(--neon-green)]" />
        <div className="flex items-center gap-2">
          <CardTitle className="text-sm tracking-wide">Signals & Learnings</CardTitle>
          <div className={`w-1.5 h-1.5 rounded-sm ${isLive ? 'bg-[var(--neon-green)] animate-pulse' : 'bg-[var(--muted-foreground)]'}`} />
          {entries.length > 0 && (
            <span className="text-xs font-mono tabular-nums text-[var(--muted-foreground)] opacity-60">
              {entries.length}
            </span>
          )}
        </div>
      </CardHeader>
      <CardContent ref={scrollRef} className="flex-1 overflow-y-auto p-0 bg-[var(--background)]">
        <div className="p-4 flex flex-col space-y-2 font-mono text-xs">
          {entries.length === 0 ? (
            <div className="flex items-start space-x-3 p-2 rounded-sm border border-[var(--border)] bg-[var(--panel-muted)]/30">
              <span className="text-[var(--muted-foreground)] leading-relaxed">
                No signals fired yet — strategy engine warming up.
              </span>
            </div>
          ) : entries.map((entry, i) => {
            const isDecision = entry.type === 'decision';
            const color  = isDecision ? 'text-[var(--neon-green)]'       : 'text-[var(--agent-learning)]';
            const border = isDecision ? 'border-[var(--neon-green)]/30'  : 'border-[var(--agent-learning)]/30';
            const bg     = isDecision ? 'bg-[var(--neon-green)]/5'       : 'bg-[var(--agent-learning)]/5';
            const Icon   = isDecision ? Zap : GraduationCap;
            const label  = isDecision ? 'SIGNAL' : 'LEARNED';

            let text = entry.text ?? '';
            if (!text && entry.action && entry.symbol) {
              const meta = entry.meta ?? {};
              const metaStr = Object.entries(meta)
                .map(([k, v]) => `${k}=${typeof v === 'number' ? (v as number).toFixed(4) : v}`)
                .join(' · ');
              text = `${entry.strategy?.toUpperCase()} → ${entry.action} ${entry.symbol} @ conf=${entry.confidence?.toFixed(2)} qty=${entry.qty?.toFixed(6)} kelly=${entry.kelly_fraction?.toFixed(4)}${metaStr ? ` | ${metaStr}` : ''}`;
            }

            return (
              <div
                key={i}
                className={`flex items-start space-x-3 p-2 rounded-sm border ${border} ${bg} ${i === 0 ? 'animate-in fade-in slide-in-from-top-1 duration-500' : ''}`}
              >
                <span className="text-[var(--muted-foreground)] shrink-0 w-[60px]">[{formatTimestamp(entry.timestamp)}]</span>
                <Badge variant="outline" className={`shrink-0 px-1.5 py-0 text-xs font-mono ${color} border-current/30`}>
                  <Icon className="w-2.5 h-2.5 mr-1 inline" />
                  {label}
                </Badge>
                <span className={`leading-relaxed break-all ${color}`}>{text}</span>
              </div>
            );
          })}
          <div className="flex items-center space-x-2 p-2 opacity-50">
            <div className="w-1.5 h-1.5 rounded-sm bg-[var(--kraken-purple)] animate-pulse" />
            <span className="italic text-[var(--muted-foreground)]">Listening to strategy engine signals...</span>
          </div>
        </div>
      </CardContent>
    </Card>
  );
}

// ---------------------------------------------------------------------------
// Strategy Mental Model Row type
// ---------------------------------------------------------------------------

type MentalModelRow = {
  symbol: string;
  strategyId: string;
  name: string;
  botStatus: string;
  summary: string;
  biasColor: string;
};

function buildMentalModelRow(symbol: string, state: any): MentalModelRow {
  const strategyId = state.strategy ?? 'unknown';
  const name       = state.name ?? strategyId;
  const botStatus  = state.bot_status ?? 'UNKNOWN';

  let summary   = '';
  let biasColor = 'text-[var(--muted-foreground)]';

  if (strategyId === 'momentum-alpha') {
    const spread = state.spread_pct ?? 0;
    const bias   = state.bias ?? 'NEUTRAL';
    const near   = state.near_crossover;
    summary = `EMA spread: ${spread > 0 ? '+' : ''}${spread.toFixed(4)}%`;
    if (near) summary += ' ⚡ Near crossover';
    summary += ` | Bias: ${bias}`;
    biasColor = bias === 'BULLISH'
      ? 'text-[var(--neon-green)]'
      : bias === 'BEARISH'
      ? 'text-[var(--neon-red)]'
      : 'text-[var(--muted-foreground)]';
  } else if (strategyId === 'statarb-gamma') {
    if (state.status === 'warming_up') {
      summary = `Warming up (${state.ticks_collected ?? 0}/20 ticks)`;
    } else {
      const pos  = state.position_in_band_pct ?? 50;
      const zone = state.zone ?? 'NEUTRAL';
      summary   = `BB position: ${pos.toFixed(0)}th pctile | Zone: ${zone}`;
      biasColor  = zone === 'OVERSOLD'
        ? 'text-[var(--neon-green)]'
        : zone === 'OVERBOUGHT'
        ? 'text-[var(--neon-red)]'
        : 'text-[var(--muted-foreground)]';
    }
  } else if (strategyId === 'hft-sniper') {
    if (botStatus === 'HALTED') {
      summary   = 'HALTED — awaiting activation';
    } else {
      const mom = state.momentum_pct ?? 0;
      summary   = `Momentum: ${mom > 0 ? '+' : ''}${mom.toFixed(5)}%`;
    }
  } else {
    // Generic fallback for all other strategy types
    const skip = new Set(['strategy', 'name', 'bot_status', 'status']);
    const keys = Object.keys(state).filter(k => !skip.has(k));
    if (state.status === 'warming_up') {
      summary = `Warming up (${state.ticks_collected ?? 0} ticks)`;
    } else if (keys.length > 0) {
      summary = keys.slice(0, 3)
        .map(k => `${k}=${String(state[k]).slice(0, 12)}`)
        .join(' · ');
    }
  }

  return { symbol, strategyId, name, botStatus, summary, biasColor };
}

// ---------------------------------------------------------------------------
// Strategy Mental Model Panel — TanStack React Table
// ---------------------------------------------------------------------------

function StrategyMentalModel({ states }: { states: Record<string, any[]> }) {
  const symbols = Object.keys(states);

  const rows = React.useMemo<MentalModelRow[]>(() =>
    Object.entries(states).flatMap(([symbol, stateArr]) =>
      (stateArr ?? []).map(state => buildMentalModelRow(symbol, state))
    ),
    [states]
  );

  const [sorting, setSorting] = React.useState<SortingState>([
    { id: 'botStatus', desc: false },
  ]);

  const columns = React.useMemo<ColumnDef<MentalModelRow>[]>(() => [
    {
      id: 'botStatus',
      accessorKey: 'botStatus',
      header: '',
      size: 32,
      cell: ({ row }) => {
        const active = row.original.botStatus === 'ACTIVE';
        return (
          <div className={`w-2 h-2 rounded-sm shrink-0 mx-auto ${
            active
              ? 'bg-[var(--neon-green)] shadow-[0_0_6px_rgba(0,255,136,0.5)]'
              : 'bg-[var(--muted-foreground)] opacity-40'
          }`} />
        );
      },
      sortingFn: (a, b) => {
        const order = (s: string) => s === 'ACTIVE' ? 0 : 1;
        return order(a.original.botStatus) - order(b.original.botStatus);
      },
    },
    {
      id: 'symbol',
      accessorKey: 'symbol',
      header: 'Symbol',
      size: 88,
      cell: ({ getValue }) => (
        <span className="font-mono tabular-nums text-xs text-[var(--muted-foreground)]">
          {getValue() as string}
        </span>
      ),
    },
    {
      id: 'name',
      accessorKey: 'name',
      header: 'Strategy',
      cell: ({ getValue }) => (
        <span className="text-xs font-bold text-[var(--foreground)]">
          {getValue() as string}
        </span>
      ),
    },
    {
      id: 'details',
      accessorKey: 'summary',
      header: 'State',
      enableSorting: false,
      cell: ({ row }) => (
        <span className={`font-mono text-xs leading-relaxed ${row.original.biasColor}`}>
          {row.original.summary || '—'}
        </span>
      ),
    },
  ], []);

  const table = useReactTable({
    data: rows,
    columns,
    state: { sorting },
    onSortingChange: setSorting,
    getCoreRowModel: getCoreRowModel(),
    getSortedRowModel: getSortedRowModel(),
  });

  if (symbols.length === 0) {
    return (
      <Card className="bg-[var(--panel)] border-[var(--border)]">
        <CardHeader className="py-3 border-b border-[var(--border)] flex flex-row items-center space-x-3">
          <BrainCircuit className="w-4 h-4 text-[var(--kraken-purple)]" />
          <CardTitle className="text-xs tracking-wide uppercase" title="Live state snapshot for each active strategy — EMA spread, Bollinger Band position, momentum, bias direction, and bot activation status.">Strategy Mental Model</CardTitle>
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
    <Card className="bg-[var(--panel)] border-[var(--border)] shrink-0">
      <CardHeader className="py-3 border-b border-[var(--border)] flex flex-row items-center justify-between bg-[var(--panel)]">
        <div className="flex items-center space-x-3">
          <BrainCircuit className="w-4 h-4 text-[var(--kraken-purple)]" />
          <CardTitle className="text-xs tracking-wide uppercase" title="Live state snapshot for each active strategy — EMA spread, Bollinger Band position, momentum, bias direction, and bot activation status.">Strategy Mental Model</CardTitle>
        </div>
        <span className="font-mono tabular-nums text-xs text-[var(--muted-foreground)] opacity-50">
          {rows.length} states
        </span>
      </CardHeader>
      <CardContent className="p-0">
        <div className="overflow-x-auto overflow-y-auto max-h-[220px]">
          <table className="w-full border-collapse">
            <thead className="sticky top-0 z-10">
              {table.getHeaderGroups().map(hg => (
                <tr key={hg.id} className="border-b border-[var(--border)] bg-[var(--panel)]">
                  {hg.headers.map(header => (
                    <th
                      key={header.id}
                      style={{ width: header.column.getSize() !== 150 ? header.column.getSize() : undefined }}
                      className="py-1.5 px-3 text-left text-xs uppercase tracking-wide text-[var(--muted-foreground)] font-normal select-none"
                    >
                      {header.column.getCanSort() ? (
                        <button
                          onClick={header.column.getToggleSortingHandler()}
                          className="flex items-center gap-1 hover:text-[var(--foreground)] transition-colors"
                        >
                          {flexRender(header.column.columnDef.header, header.getContext())}
                          <span className="opacity-50">
                            {header.column.getIsSorted() === 'asc' ? '▲' : header.column.getIsSorted() === 'desc' ? '▼' : '⇅'}
                          </span>
                        </button>
                      ) : (
                        flexRender(header.column.columnDef.header, header.getContext())
                      )}
                    </th>
                  ))}
                </tr>
              ))}
            </thead>
            <tbody>
              {table.getRowModel().rows.map((row, i) => (
                <tr
                  key={row.id}
                  className={`border-b border-[var(--border)]/30 last:border-b-0 hover:bg-[var(--panel-muted)]/20 transition-colors ${
                    i % 2 === 0 ? '' : 'bg-[var(--panel-muted)]/10'
                  }`}
                >
                  {row.getVisibleCells().map(cell => (
                    <td key={cell.id} className="py-1.5 px-3">
                      {flexRender(cell.column.columnDef.cell, cell.getContext())}
                    </td>
                  ))}
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </CardContent>
    </Card>
  );
}

// ---------------------------------------------------------------------------
// Historical Amends column
// ---------------------------------------------------------------------------

function HistoricalAmends() {
  const [mounted, setMounted] = React.useState(false);
  const [amends, setAmends]   = React.useState<ReflectionEntry[]>([]);

  React.useEffect(() => {
    setMounted(true);
    const load = () =>
      fetch(`${API_BASE}/api/reflections`)
        .then(r => r.ok ? r.json() : [])
        .then(setAmends)
        .catch(() => {});
    load();
    const id = setInterval(load, 30_000);
    return () => clearInterval(id);
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
      <CardHeader className="py-4 border-b border-[var(--border)] flex flex-row items-center space-x-3 bg-[var(--panel)] shrink-0">
        <BrainCircuit className="w-5 h-5 text-[var(--kraken-purple)]" />
        <div className="flex flex-col flex-1 min-w-0">
          <CardTitle className="text-sm tracking-wide">Historical Learning & Amends</CardTitle>
          {amends.length > 0 && (
            <span className="text-xs font-mono tabular-nums text-[var(--muted-foreground)] opacity-50">
              {amends.length} records · 30s refresh
            </span>
          )}
        </div>
      </CardHeader>
      <CardContent className="flex-1 overflow-y-auto p-4 space-y-4">
        {amends.length === 0 ? (
          <div className="text-xs text-[var(--muted-foreground)] opacity-50 italic">
            No learning records yet — amends are generated after strategy performance analysis.
          </div>
        ) : amends.map((item, i) => {
          const impactColor = item.impact?.startsWith('-')
            ? 'text-[var(--neon-red)]'
            : 'text-[var(--neon-green)]';
          return (
            <div key={i} className="relative pl-6 pb-2 border-l border-[var(--border)] last:border-l-transparent">
              <div className="absolute left-[-5px] top-1 w-2.5 h-2.5 rounded-sm bg-[var(--kraken-purple)] shadow-[0_0_6px_rgba(139,92,246,0.4)]" />
              <div className="flex justify-between items-start mb-1">
                <div className="flex items-center space-x-2">
                  <Badge variant="purple" className="px-1.5 py-0 text-xs">
                    {item.action ?? 'LEARNED'}
                  </Badge>
                  <span className="text-xs text-[var(--foreground)] font-bold">
                    {item.model ?? 'Orchestrator'}
                  </span>
                </div>
                <span className="text-xs text-[var(--muted-foreground)] font-mono tabular-nums">
                  {item.date ? (parseUtc(item.date)?.toLocaleString(undefined, { month: 'short', day: 'numeric', hour: '2-digit', minute: '2-digit', second: '2-digit', hour12: false }) ?? 'Live') : 'Live'}
                </span>
              </div>
              <p className="text-xs text-[var(--muted-foreground)] mb-2 mt-2 leading-relaxed">
                {item.reason}
              </p>
              <div className={`text-xs font-mono tracking-wider font-bold ${impactColor}`}>
                IMPACT: {item.impact ?? 'Analyzing...'}
              </div>
            </div>
          );
        })}
      </CardContent>
    </Card>
  );
}

// ---------------------------------------------------------------------------
// Brain Tab Root
// ---------------------------------------------------------------------------

export function BotReflections() {
  const learningHistory = useTradingStore(s => s.learningHistory) as ReflectionEntry[];
  const strategyStates  = useTradingStore(s => s.strategyStates);
  const [mounted, setMounted] = React.useState(false);

  React.useEffect(() => { setMounted(true); }, []);

  const scannerEntries  = React.useMemo(() => learningHistory.filter(e => e.type === 'scanner'),                           [learningHistory]);
  const researchEntries = React.useMemo(() => learningHistory.filter(e => e.type === 'research'),                          [learningHistory]);
  const directorEntries = React.useMemo(() => learningHistory.filter(e => e.type === 'director'),                          [learningHistory]);
  const signalEntries   = React.useMemo(() => learningHistory.filter(e => e.type === 'decision' || e.type === 'learning'), [learningHistory]);

  if (!mounted) return (
    <div className="flex h-full items-center justify-center">
      <div className="text-xs text-[var(--muted-foreground)] opacity-50">Loading Brain...</div>
    </div>
  );

  return (
    <div className="flex flex-col h-full gap-4 overflow-hidden">

      {/* Zone 1 — Agent Activity Grid */}
      <div className="grid grid-cols-3 gap-4 shrink-0 h-[200px]">
        <ScannerCard  entries={scannerEntries}  />
        <ResearchCard entries={researchEntries} />
        <DirectorCard entries={directorEntries} />
      </div>

      {/* Zone 2 — Intelligence & State */}
      <div className="flex flex-1 gap-4 min-h-0">

        {/* Left: Historical Amends */}
        <HistoricalAmends />

        {/* Right: Strategy Mental Model + Signals */}
        <div className="flex-[2] flex flex-col gap-3 min-h-0">
          <StrategyMentalModel states={strategyStates} />
          <SignalsLog entries={signalEntries} />
        </div>
      </div>
    </div>
  );
}
