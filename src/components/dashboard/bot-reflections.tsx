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
import { BrainCircuit, SearchCode, Zap, Eye, Calculator, GraduationCap, Filter, Bot, Sparkles, Activity } from 'lucide-react';
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
  // Learning & Amends fields
  model?: string;
  reason?: string;
  impact?: string;
  date?: string;
  // Trade learning fields
  fill_price?: number;
  slippage?: number;
  // Director fields
  target_bot?: string;
  success?: boolean;
}

// Reflection type → visual style mapping
const TYPE_STYLES: Record<string, { icon: typeof Zap; label: string; color: string; border: string; bg: string }> = {
  observe:   { icon: Eye,            label: 'OBSERVE',    color: 'text-[var(--agent-observe)]',        border: 'border-[var(--agent-observe)]/30',    bg: 'bg-[var(--agent-observe)]/5' },
  calculate: { icon: Calculator,     label: 'POSITION',   color: 'text-[var(--agent-calculate)]',      border: 'border-[var(--agent-calculate)]/30',  bg: 'bg-[var(--agent-calculate)]/5' },
  decision:  { icon: Zap,            label: 'DECISION',   color: 'text-[var(--neon-green)]',           border: 'border-[var(--neon-green)]/40',       bg: 'bg-[var(--neon-green)]/5' },
  learning:  { icon: GraduationCap,  label: 'LEARNED',    color: 'text-[var(--agent-learning)]',       border: 'border-[var(--agent-learning)]/30',   bg: 'bg-[var(--agent-learning)]/5' },
  director:  { icon: Bot,            label: 'DIRECTOR',   color: 'text-[var(--agent-execute)]',        border: 'border-[var(--agent-execute)]/30',    bg: 'bg-[var(--agent-execute)]/5' },
  scanner:   { icon: Sparkles,       label: 'SCANNER',    color: 'text-[var(--agent-scanner)]',        border: 'border-[var(--agent-scanner)]/30',    bg: 'bg-[var(--agent-scanner)]/5' },
  research:  { icon: SearchCode,     label: 'RESEARCH',   color: 'text-[var(--agent-research)]',       border: 'border-[var(--agent-research)]/30',   bg: 'bg-[var(--agent-research)]/5' },
};

function getTypeStyle(type: string | undefined) {
  return TYPE_STYLES[type ?? ''] ?? TYPE_STYLES['observe'];
}

function formatTimestamp(ts: string | number | undefined): string {
  if (!ts) return 'Live';
  try {
    return (parseUtc(ts) ?? new Date()).toLocaleString(undefined, { month: 'short', day: 'numeric', hour: '2-digit', minute: '2-digit', second: '2-digit', hour12: false });
  } catch {
    return String(ts);
  }
}

// Convert a reflection payload into a display line
function reflectionToDisplay(r: ReflectionEntry): { time: string; text: string; type: string; strategy: string; symbol: string } {
  const time     = formatTimestamp(r.timestamp);
  const strategy = r.strategy ?? 'system';
  const symbol   = r.symbol ?? '';

  if (r.type === 'scanner') {
    const results = (r as any).results as any[] | undefined;
    if (results && results.length > 0) {
      const top   = results[0];
      const picks = results.slice(0, 3).map((x: any) => `${x.symbol}(${x.signal})`).join(' · ');
      return {
        time, type: 'scanner', strategy: 'scanner', symbol: top.symbol ?? '',
        text: `Top picks: ${picks} — ${top.symbol}: ${top.verdict ?? top.summary ?? ''}`,
      };
    }
    return { time, type: 'scanner', text: r.text ?? 'Scanner update', strategy: 'scanner', symbol: '' };
  }

  if (r.type === 'director') {
    const status = r.success === false ? '✗' : '✓';
    const text   = `[${status}] ${r.action ?? 'ACTION'} → ${r.target_bot ?? 'portfolio'}: ${r.reason ?? ''}`;
    return { time, type: 'director', text, strategy: 'director', symbol: r.target_bot ?? '' };
  }

  if (r.type === 'research') {
    const raw       = r as any;
    const theme     = raw.macro_theme ?? '';
    const focus     = Array.isArray(raw.focus) ? (raw.focus as string[]).join(' · ') : '';
    const text      = [theme, focus ? `Focus: ${focus}` : ''].filter(Boolean).join(' | ');
    return { time, type: 'research', text: text || 'Research brief received', strategy: 'researcher', symbol: '' };
  }

  if (r.text) {
    return { time, type: r.type ?? 'observe', text: r.text, strategy, symbol };
  }

  if (r.action && r.symbol) {
    const meta    = r.meta ?? {};
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
type FilterType = 'ALL' | 'observe' | 'calculate' | 'decision' | 'learning' | 'director' | 'scanner' | 'research';
const FILTER_OPTIONS: { value: FilterType; label: string; color: string }[] = [
  { value: 'ALL',       label: 'All',      color: 'text-[var(--foreground)]' },
  { value: 'observe',   label: 'Observe',  color: 'text-[var(--agent-observe)]' },
  { value: 'calculate', label: 'Position', color: 'text-[var(--agent-calculate)]' },
  { value: 'decision',  label: 'Decision', color: 'text-[var(--neon-green)]' },
  { value: 'learning',  label: 'Learning', color: 'text-[var(--agent-learning)]' },
  { value: 'director',  label: 'Director', color: 'text-[var(--agent-execute)]' },
  { value: 'scanner',   label: 'Scanner',  color: 'text-[var(--agent-scanner)]' },
  { value: 'research',  label: 'Research', color: 'text-[var(--agent-research)]' },
];

// ---------------------------------------------------------------------------
// Director Status Strip
// ---------------------------------------------------------------------------

function DirectorStatus({ entries }: { entries: ReturnType<typeof reflectionToDisplay>[] }) {
  const directorEntries = entries.filter(e => e.type === 'director').slice(0, 2);

  if (directorEntries.length === 0) return null;

  return (
    <Card className="bg-[var(--panel)] border-[var(--agent-execute)]/30">
      <CardHeader className="py-2.5 px-4 border-b border-[var(--agent-execute)]/20 flex flex-row items-center space-x-2 bg-gradient-to-r from-[var(--agent-execute)]/8 to-transparent">
        <Activity className="w-3.5 h-3.5 text-[var(--agent-execute)] shrink-0" />
        <CardTitle className="text-xs tracking-wide uppercase text-[var(--agent-execute)]">
          Director — Last Actions
        </CardTitle>
      </CardHeader>
      <CardContent className="py-2 px-4 space-y-1.5">
        {directorEntries.map((e, i) => (
          <div key={i} className="flex items-start gap-2 font-mono text-xs">
            <span className="text-[var(--muted-foreground)] shrink-0 w-[60px]">[{e.time}]</span>
            <span className="text-[var(--agent-execute)] leading-relaxed">{e.text}</span>
          </div>
        ))}
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
      biasColor = 'text-[var(--muted-foreground)]';
    } else {
      const mom = state.momentum_pct ?? 0;
      summary   = `Momentum: ${mom > 0 ? '+' : ''}${mom.toFixed(5)}%`;
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
      <CardHeader className="py-3 border-b border-[var(--kraken-purple)]/20 flex flex-row items-center justify-between bg-gradient-to-r from-[var(--kraken-purple)]/5 to-transparent">
        <div className="flex items-center space-x-3">
          <BrainCircuit className="w-4 h-4 text-[var(--kraken-purple)]" />
          <CardTitle className="text-xs tracking-wide uppercase">Strategy Mental Model</CardTitle>
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
                  className={`border-b border-[var(--border)]/50 last:border-b-0 hover:bg-[var(--panel-muted)]/20 transition-colors ${
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
// Component
// ---------------------------------------------------------------------------

export function BotReflections() {
  const learningHistory = useTradingStore(s => s.learningHistory) as ReflectionEntry[];
  const strategyStates  = useTradingStore(s => s.strategyStates);
  const [mounted, setMounted]               = React.useState(false);
  const [filter, setFilter]                 = React.useState<FilterType>('ALL');
  const [strategyFilter, setStrategyFilter] = React.useState<string>('ALL');
  const scrollRef = React.useRef<HTMLDivElement>(null);

  React.useEffect(() => { setMounted(true); }, []);

  // All entries before type/strategy filter — used for counts
  const allEntries = React.useMemo(() =>
    learningHistory.map(reflectionToDisplay),
    [learningHistory]
  );

  const countByType = React.useMemo(() => {
    const m: Record<string, number> = {};
    allEntries.forEach(e => { m[e.type] = (m[e.type] ?? 0) + 1; });
    return m;
  }, [allEntries]);

  const entries = React.useMemo(() =>
    allEntries
      .filter(e => filter === 'ALL' || e.type === filter)
      .filter(e => strategyFilter === 'ALL' || e.strategy === strategyFilter),
    [allEntries, filter, strategyFilter]
  );

  React.useEffect(() => {
    if (scrollRef.current) {
      scrollRef.current.scrollTop = 0;
    }
  }, [entries.length]);

  const strategies = React.useMemo(() => {
    const set = new Set<string>();
    learningHistory.forEach(r => { if (r.strategy) set.add(r.strategy); });
    return Array.from(set);
  }, [learningHistory]);

  const isLive = entries.length > 0;

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

      {/* Left: Historical Amends */}
      <HistoricalAmends />

      {/* Right: Strategy Mental Model + Director Status + Live Thought Matrix */}
      <div className="flex-[2] flex flex-col gap-3 min-h-0">

        <StrategyMentalModel states={strategyStates} />

        <DirectorStatus entries={entries} />

        {/* Live Thought Stream */}
        <Card className="flex-1 min-h-0 flex flex-col bg-[var(--panel)]">
          <CardHeader className="py-3 border-b border-[var(--border)] flex flex-row items-center justify-between">
            <div className="flex items-center space-x-3">
              <SearchCode className="w-5 h-5 text-[var(--kraken-light)]" />
              <div className="flex flex-col">
                <div className="flex items-center gap-2">
                  <CardTitle className="text-sm tracking-wide">Live Thought Matrix</CardTitle>
                  <div className={`w-1.5 h-1.5 rounded-sm ${isLive ? 'bg-[var(--neon-green)] animate-pulse' : 'bg-[var(--muted-foreground)]'}`} />
                  {entries.length > 0 && (
                    <span className="text-xs font-mono tabular-nums text-[var(--muted-foreground)] opacity-60">
                      {entries.length}
                    </span>
                  )}
                </div>
                <span className="text-xs text-[var(--muted-foreground)] uppercase">
                  Agent Internal Monologue
                </span>
              </div>
            </div>

            {/* Filter bar with counts */}
            <div className="flex items-center gap-2">
              <Filter className="w-3.5 h-3.5 text-[var(--muted-foreground)]" />
              <div className="flex gap-1">
                {FILTER_OPTIONS.map(opt => {
                  const count = opt.value === 'ALL'
                    ? allEntries.length
                    : (countByType[opt.value] ?? 0);
                  return (
                    <button
                      key={opt.value}
                      onClick={() => setFilter(opt.value)}
                      className={`flex items-center gap-1 px-2 py-0.5 text-xs rounded-sm font-mono transition-all duration-200 ${
                        filter === opt.value
                          ? `${opt.color} bg-white/10 shadow-sm`
                          : 'text-[var(--muted-foreground)] hover:text-[var(--foreground)] hover:bg-white/5'
                      }`}
                    >
                      {opt.label}
                      {count > 0 && (
                        <span className="tabular-nums text-[var(--muted-foreground)] opacity-60">
                          {count}
                        </span>
                      )}
                    </button>
                  );
                })}
              </div>
              {strategies.length > 1 && (
                <select
                  value={strategyFilter}
                  onChange={e => setStrategyFilter(e.target.value)}
                  className="ml-2 px-2 py-0.5 text-xs rounded-sm bg-[var(--panel-muted)] text-[var(--foreground)] border border-[var(--border)] font-mono"
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
                  <div className="flex items-start space-x-3 p-2 rounded-sm border border-[var(--border)] bg-[var(--panel-muted)]/30">
                    <span className="text-[var(--muted-foreground)] shrink-0">[SYSTEM]</span>
                    <span className="text-[var(--foreground)] leading-relaxed">
                      Initializing strategy engine... awaiting live market data.
                    </span>
                  </div>
                  <div className="flex items-start space-x-3 p-2 rounded-sm border border-[var(--border)] bg-[var(--panel-muted)]/30">
                    <span className="text-[var(--muted-foreground)] shrink-0">[STREAM]</span>
                    <span className="text-[var(--foreground)] leading-relaxed">
                      Connecting to Alpaca CryptoDataStream — awaiting live universe...
                    </span>
                  </div>
                </>
              ) : (
                entries.map((t, i) => {
                  const style = getTypeStyle(t.type);
                  const Icon  = style.icon;
                  return (
                    <div
                      key={i}
                      className={`flex items-start space-x-3 p-2 rounded-sm border ${style.border} ${style.bg} transition-all duration-300 ${
                        i === 0 ? 'animate-in fade-in slide-in-from-top-1 duration-500' : ''
                      }`}
                    >
                      <span className="text-[var(--muted-foreground)] shrink-0 w-[60px]">[{t.time}]</span>
                      <Badge
                        variant="outline"
                        className={`shrink-0 px-1.5 py-0 text-xs font-mono ${style.color} border-current/30`}
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
      <CardHeader className="py-4 border-b border-[var(--kraken-purple)]/30 flex flex-row items-center space-x-3 bg-gradient-to-r from-[var(--kraken-purple)]/10 to-transparent">
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
