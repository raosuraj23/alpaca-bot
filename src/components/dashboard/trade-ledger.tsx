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
import { Badge } from "@/components/ui/badge";
import { Filter, Download, RefreshCw, TrendingUp, TrendingDown } from 'lucide-react';
import { useTradingStore } from '@/hooks/useTradingStream';
import { parseUtc } from '@/lib/utils';

// ---------------------------------------------------------------------------
// Types
// ---------------------------------------------------------------------------

interface ClosedTrade {
  strategy:    string;
  symbol:      string;
  entry_price: number;
  exit_price:  number | null;
  pnl:         number | null;
  qty:         number | null;
  entry_time:  string | null;
  exit_time:   string | null;
  confidence:  number;
  open?:       boolean;
}

interface RealizedPnlData {
  trades:         ClosedTrade[];
  open_positions: any[];
  total_closed:   number;
}

interface AccountData {
  equity:            number;
  buying_power:      number;
  cash:              number;
  long_market_value: number;
}

// ---------------------------------------------------------------------------
// KPI Summary Row
// ---------------------------------------------------------------------------

function KpiSummary({ data, ledgerCount }: { data: RealizedPnlData | null; ledgerCount: number }) {
  const closed   = data?.trades ?? [];
  const totalPnl = closed.reduce((s, t) => s + (t.pnl ?? 0), 0);
  const winners  = closed.filter(t => (t.pnl ?? 0) > 0).length;
  const winRate  = closed.length > 0 ? (winners / closed.length) * 100 : null;
  const avgPnl   = closed.length > 0 ? totalPnl / closed.length : null;
  const isPos    = totalPnl >= 0;

  const kpis = [
    { label: 'Realized PnL',    value: closed.length > 0 ? `${isPos ? '+' : ''}$${totalPnl.toFixed(2)}` : '—', color: closed.length > 0 ? (isPos ? 'text-[var(--neon-green)]' : 'text-[var(--neon-red)]') : 'text-[var(--muted-foreground)]' },
    { label: 'Win Rate',        value: winRate != null ? `${winRate.toFixed(0)}%` : '—', color: winRate != null ? (winRate >= 50 ? 'text-[var(--neon-green)]' : 'text-[var(--neon-red)]') : 'text-[var(--muted-foreground)]' },
    { label: 'Avg PnL / Trade', value: avgPnl != null ? `${avgPnl >= 0 ? '+' : ''}$${avgPnl.toFixed(4)}` : '—', color: avgPnl != null ? (avgPnl >= 0 ? 'text-[var(--neon-green)]' : 'text-[var(--neon-red)]') : 'text-[var(--muted-foreground)]' },
    { label: 'Closed Trades',   value: String(data?.total_closed ?? 0), color: 'text-[var(--foreground)]' },
    { label: 'Exec Records',    value: String(ledgerCount), color: 'text-[var(--foreground)]' },
  ];

  return (
    <div className="grid grid-cols-5 divide-x divide-[var(--border)] border-b border-[var(--border)] shrink-0 bg-[var(--panel-muted)]/40">
      {kpis.map(kpi => (
        <div key={kpi.label} className="flex flex-col px-4 py-2.5">
          <span className="text-xs text-[var(--muted-foreground)] uppercase tracking-wider mb-0.5 leading-none">{kpi.label}</span>
          <span className={`text-sm font-mono tabular-nums font-bold leading-snug ${kpi.color}`}>{kpi.value}</span>
        </div>
      ))}
    </div>
  );
}

// ---------------------------------------------------------------------------
// TicketIdCell — truncated display with title tooltip + click-to-copy
// ---------------------------------------------------------------------------

function TicketIdCell({ fullId, short }: { fullId: string; short: string }) {
  const [copied, setCopied] = React.useState(false);
  const handleClick = () => {
    navigator.clipboard.writeText(fullId).catch(() => {});
    setCopied(true);
    setTimeout(() => setCopied(false), 600);
  };
  return (
    <span
      title={fullId}
      onClick={handleClick}
      className={`cursor-pointer transition-colors ${copied ? 'text-[var(--neon-green)]' : 'text-[var(--muted-foreground)] hover:text-[var(--foreground)]'}`}
    >
      {short}
    </span>
  );
}

// ---------------------------------------------------------------------------
// TradeLedger Component
// ---------------------------------------------------------------------------

export function TradeLedger() {
  const ledgerTrades = useTradingStore(s => s.ledgerTrades);
  const fetchLedger  = useTradingStore(s => s.fetchLedger);
  const positions    = useTradingStore(s => s.positions);

  const [realizedData, setRealizedData] = React.useState<RealizedPnlData | null>(null);
  const [accountData, setAccountData]   = React.useState<AccountData | null>(null);
  const [lastRefresh, setLastRefresh]   = React.useState<Date | null>(null);
  const [refreshing, setRefreshing]     = React.useState(false);
  const [mounted, setMounted]           = React.useState(false);
  const [filterSide, setFilterSide]     = React.useState<'ALL' | 'BUY' | 'SELL'>('ALL');
  const [filterOutcome, setFilterOutcome] = React.useState<'ALL' | 'WIN' | 'LOSS'>('ALL');
  const [ledgerSorting, setLedgerSorting]   = React.useState<SortingState>([{ id: 'timestamp', desc: true }]);
  const [historySorting, setHistorySorting] = React.useState<SortingState>([{ id: 'entry_time', desc: true }]);

  React.useEffect(() => { setMounted(true); }, []);

  const loadRealizedPnl = React.useCallback(async () => {
    try {
      const res = await fetch(`${API_BASE}/api/analytics/realized-pnl`, { signal: AbortSignal.timeout(10000) });
      if (res.ok) { setRealizedData(await res.json()); setLastRefresh(new Date()); }
    } catch { /* silent */ }
  }, []);

  const loadAccountData = React.useCallback(async () => {
    try {
      const res = await fetch(`${API_BASE}/api/account`, { signal: AbortSignal.timeout(8000) });
      if (res.ok) setAccountData(await res.json());
    } catch { /* silent */ }
  }, []);

  const handleRefresh = async () => {
    setRefreshing(true);
    await Promise.all([fetchLedger(), loadRealizedPnl()]);
    setRefreshing(false);
  };

  React.useEffect(() => { loadRealizedPnl(); const t = setInterval(loadRealizedPnl, 30_000); return () => clearInterval(t); }, [loadRealizedPnl]);
  React.useEffect(() => { loadAccountData(); const t = setInterval(loadAccountData, 30_000); return () => clearInterval(t); }, [loadAccountData]);

  const realizedPnlByLedgerId = React.useMemo(() => {
    if (!realizedData || realizedData.trades.length === 0) return new Map<number, number>();
    const queues = new Map<string, number[]>();
    [...realizedData.trades].sort((a, b) => (a.exit_time ?? '').localeCompare(b.exit_time ?? ''))
      .forEach(t => { const k = `${t.strategy}|${t.symbol}`; if (!queues.has(k)) queues.set(k, []); queues.get(k)!.push(t.pnl ?? 0); });
    const remaining = new Map<string, number[]>();
    queues.forEach((v, k) => remaining.set(k, [...v]));
    const result = new Map<number, number>();
    for (const row of [...ledgerTrades].reverse()) {
      if (row.side !== 'SELL') continue;
      const q = remaining.get(`${row.bot}|${row.symbol}`);
      if (q && q.length > 0) result.set(row.id, q.shift()!);
    }
    return result;
  }, [realizedData, ledgerTrades]);

  const filteredLedger = React.useMemo(() => ledgerTrades.filter((r: any) => {
    if (filterSide !== 'ALL' && r.side !== filterSide) return false;
    if (filterOutcome !== 'ALL') {
      const pnl = r.side === 'SELL' ? (realizedPnlByLedgerId.get(r.id) ?? null) : null;
      if (filterOutcome === 'WIN'  && !(pnl != null && pnl >= 0)) return false;
      if (filterOutcome === 'LOSS' && !(pnl != null && pnl < 0))  return false;
    }
    return true;
  }), [ledgerTrades, filterSide, filterOutcome, realizedPnlByLedgerId]);

  const roundTripRows = React.useMemo(() => {
    const closed = (realizedData?.trades ?? []).map(t => ({ ...t, open: false }));
    const open   = (realizedData?.open_positions ?? []).map(op => {
      const live = positions.find((p: any) => p.symbol === op.symbol);
      return { ...op, open: true, qty: live ? Number(live.size ?? op.qty ?? null) : op.qty ?? null, exit_price: live ? Number(live.markPrice ?? live.entryPrice ?? 0) : null, unrealized_pnl: live ? Number(live.unrealizedPnl ?? 0) : null };
    });
    return [...closed, ...open];
  }, [realizedData, positions]);

  const hasNonZeroSlippage = React.useMemo(
    () => ledgerTrades.some((r: any) => r.slippage_bps != null && r.slippage_bps !== 0),
    [ledgerTrades],
  );

  // ------------------------------------------------------------------
  // Ledger table columns
  // ------------------------------------------------------------------
  const ledgerColumns = React.useMemo<ColumnDef<any>[]>(() => {
    const cols: ColumnDef<any>[] = [
      {
        accessorKey: 'order_id',
        header: 'Ticket ID',
        cell: ({ row }) => {
          const fullId = row.original.order_id ?? String(row.original.id);
          const short  = fullId.length > 8 ? fullId.slice(0, 8) + '…' : fullId;
          return <TicketIdCell fullId={fullId} short={short} />;
        },
      },
      {
        accessorKey: 'timestamp',
        header: 'Timestamp',
        cell: ({ getValue }) => <span className="text-[var(--foreground)]">{getValue() ? (parseUtc(getValue() as string)?.toLocaleString(undefined, { hour12: false }) ?? '—') : '—'}</span>,
      },
      {
        accessorKey: 'symbol',
        header: 'Symbol',
        cell: ({ getValue }) => <span className="font-bold text-[var(--foreground)]">{(getValue() as string) ?? '—'}</span>,
      },
      {
        accessorKey: 'side',
        header: 'Direction',
        cell: ({ getValue }) => (
          <div className="flex justify-center">
            <Badge variant={(getValue() as string) === 'BUY' ? 'success' : 'destructive'} className="text-xs px-1.5 uppercase font-sans tracking-widest">
              {(getValue() as string) ?? '—'}
            </Badge>
          </div>
        ),
      },
      {
        accessorKey: 'bot',
        header: 'Origin Agent',
        cell: ({ getValue }) => (
          <div className="hidden md:flex justify-center">
            <Badge variant="outline" className="font-sans font-normal opacity-80">{(getValue() as string) ?? '—'}</Badge>
          </div>
        ),
      },
      {
        accessorKey: 'confidence',
        header: 'Signal Conf.',
        cell: ({ getValue }) => {
          const v = getValue() as number | null;
          const pct = v != null ? v * 100 : null;
          const color = pct == null ? 'text-[var(--muted-foreground)]'
            : pct >= 85 ? 'text-[var(--neon-green)]'
            : pct >= 70 ? 'text-[var(--foreground)]'
            : 'text-[var(--warning)]';
          return <span className={`text-right block hidden xl:block ${color}`}>{pct != null ? `${pct.toFixed(0)}%` : '—'}</span>;
        },
      },
      {
        accessorKey: 'fill_price',
        header: 'Fill Price',
        cell: ({ getValue }) => {
          const v = getValue() as number | null;
          return <span className="text-right block font-bold text-[var(--foreground)]">{v != null ? `$${Number(v).toFixed(2)}` : '—'}</span>;
        },
      },
      {
        id: 'realized_pnl',
        header: 'Realized PnL',
        enableSorting: false,
        cell: ({ row }) => {
          const realPnl = row.original.side === 'SELL' ? (realizedPnlByLedgerId.get(row.original.id) ?? null) : null;
          return realPnl != null ? (
            <span className={`flex items-center justify-end gap-0.5 font-bold ${realPnl >= 0 ? 'text-[var(--neon-green)]' : 'text-[var(--neon-red)]'}`}>
              {realPnl >= 0 ? <TrendingUp className="w-3 h-3 shrink-0" /> : <TrendingDown className="w-3 h-3 shrink-0" />}
              {realPnl >= 0 ? '+' : ''}${realPnl.toFixed(4)}
            </span>
          ) : (
            <span className="text-right block text-[var(--muted-foreground)] opacity-40">—</span>
          );
        },
      },
    ];

    if (hasNonZeroSlippage) {
      cols.splice(6, 0, {
        accessorKey: 'slippage_bps',
        header: 'Slippage',
        cell: ({ getValue }) => {
          const v = getValue() as number | null;
          const color = v == null ? 'text-[var(--muted-foreground)]'
            : v < 5 ? 'text-[var(--neon-green)]'
            : v < 20 ? 'text-[var(--foreground)]'
            : 'text-[var(--neon-red)]';
          return <span className={`text-right block ${color}`}>{v != null ? `${v.toFixed(1)} bps` : '—'}</span>;
        },
      });
    }

    return cols;
  }, [realizedPnlByLedgerId, hasNonZeroSlippage]);

  // ------------------------------------------------------------------
  // Trade history table columns
  // ------------------------------------------------------------------
  const historyColumns = React.useMemo<ColumnDef<any>[]>(() => [
    {
      accessorKey: 'symbol',
      header: 'Symbol',
      cell: ({ row }) => (
        <div className="flex items-center gap-1.5 font-semibold text-[var(--foreground)]">
          <span className={`w-1.5 h-1.5 rounded-sm shrink-0 ${row.original.open ? 'bg-[var(--neon-green)] animate-pulse' : 'bg-[var(--muted-foreground)] opacity-40'}`} />
          {row.original.symbol}
        </div>
      ),
    },
    { accessorKey: 'strategy', header: 'Bot', cell: ({ getValue }) => <span className="text-[var(--muted-foreground)] truncate max-w-[90px] block">{getValue() as string}</span> },
    { accessorKey: 'entry_price', header: 'Open @ price', cell: ({ getValue }) => <span className="text-right block text-[var(--foreground)]">${Number(getValue()).toFixed(4)}</span> },
    {
      accessorKey: 'entry_time',
      header: 'Open time',
      cell: ({ getValue }) => <span className="text-right block text-[var(--muted-foreground)]">{getValue() ? (parseUtc(getValue() as string)?.toLocaleString(undefined, { hour12: false }) ?? '—') : '—'}</span>,
    },
    {
      accessorKey: 'exit_price',
      header: 'Close @ price',
      cell: ({ row }) => {
        const v = row.original.exit_price;
        return v != null
          ? <span className={`text-right block ${row.original.open ? 'text-[var(--kraken-light)]' : 'text-[var(--foreground)]'}`}>${Number(v).toFixed(4)}</span>
          : <span className="text-right block text-[var(--muted-foreground)] opacity-40">—</span>;
      },
    },
    {
      accessorKey: 'exit_time',
      header: 'Close time',
      cell: ({ row }) => row.original.open
        ? <span className="text-right block text-[var(--neon-green)] opacity-70">live</span>
        : <span className="text-right block text-[var(--muted-foreground)]">{row.original.exit_time ? (parseUtc(row.original.exit_time)?.toLocaleString(undefined, { hour12: false }) ?? '—') : '—'}</span>,
    },
    { accessorKey: 'qty', header: 'Qty', cell: ({ getValue }) => <span className="text-right block text-[var(--foreground)]">{(getValue() as number) != null ? Number(getValue()).toFixed(6) : '—'}</span> },
    {
      accessorKey: 'pnl',
      header: 'PnL',
      cell: ({ row }) => {
        const pnl = row.original.open ? (row.original.unrealized_pnl ?? null) : row.original.pnl;
        const pos = pnl != null && pnl >= 0;
        return pnl != null
          ? <span className={`text-right block font-bold ${pos ? 'text-[var(--neon-green)]' : 'text-[var(--neon-red)]'}`}>{pos ? '+' : ''}${pnl.toFixed(4)}{row.original.open && <span className="text-xs ml-1 opacity-50">unr.</span>}</span>
          : <span className="text-right block text-[var(--muted-foreground)] opacity-40">—</span>;
      },
    },
  ], []);

  const ledgerTable = useReactTable({
    data: filteredLedger,
    columns: ledgerColumns,
    state: { sorting: ledgerSorting },
    onSortingChange: setLedgerSorting,
    getCoreRowModel: getCoreRowModel(),
    getSortedRowModel: getSortedRowModel(),
  });

  const historyTable = useReactTable({
    data: roundTripRows,
    columns: historyColumns,
    state: { sorting: historySorting },
    onSortingChange: setHistorySorting,
    getCoreRowModel: getCoreRowModel(),
    getSortedRowModel: getSortedRowModel(),
  });

  if (!mounted) return null;

  const SortIcon = ({ col }: { col: any }) => {
    const s = col.getIsSorted();
    return s === 'asc' ? <span className="text-[var(--kraken-light)]">▲</span> : s === 'desc' ? <span className="text-[var(--kraken-light)]">▼</span> : col.getCanSort() ? <span className="opacity-20">⇅</span> : null;
  };

  return (
    <Card className="h-full flex flex-col bg-[var(--panel)] overflow-hidden">

      {/* Ledger Toolbar */}
      <CardHeader className="py-3 px-4 border-b border-[var(--border)] flex flex-row items-center justify-between bg-gradient-to-b from-[var(--kraken-purple)]/5 to-transparent flex-shrink-0">
        <div className="flex items-center space-x-3">
          <CardTitle className="text-sm font-bold tracking-wide">Master Execution Ledger</CardTitle>
          <Badge variant="outline" className="px-2">{ledgerTrades.length} RECORDS</Badge>
        </div>
        <div className="flex items-center space-x-2">
          {/* Desktop filter buttons */}
          {(['ALL', 'BUY', 'SELL'] as const).map(side => (
            <button key={side} onClick={() => setFilterSide(side)} className={`hidden md:flex items-center px-3 py-1.5 border rounded-sm text-xs font-mono transition-colors ${filterSide === side ? 'border-[var(--kraken-purple)] text-[var(--kraken-light)] bg-[var(--kraken-purple)]/20' : 'bg-[var(--background)] border-[var(--border)] text-[var(--muted-foreground)] hover:text-[var(--foreground)]'}`}>{side}</button>
          ))}
          {(['ALL', 'WIN', 'LOSS'] as const).map(outcome => (
            <button key={outcome} onClick={() => setFilterOutcome(outcome)} className={`hidden md:flex items-center px-3 py-1.5 border rounded-sm text-xs font-mono transition-colors ${filterOutcome === outcome ? 'border-[var(--kraken-purple)] text-[var(--kraken-light)] bg-[var(--kraken-purple)]/20' : 'bg-[var(--background)] border-[var(--border)] text-[var(--muted-foreground)] hover:text-[var(--foreground)]'}`}>{outcome}</button>
          ))}
          {/* Mobile filter selects */}
          <select value={filterSide} onChange={e => setFilterSide(e.target.value as any)} className="md:hidden bg-[var(--panel-muted)] border border-[var(--border)] rounded-sm text-xs font-mono text-[var(--foreground)] px-1.5 py-1 outline-none">
            {(['ALL', 'BUY', 'SELL'] as const).map(s => <option key={s} value={s}>{s}</option>)}
          </select>
          <select value={filterOutcome} onChange={e => setFilterOutcome(e.target.value as any)} className="md:hidden bg-[var(--panel-muted)] border border-[var(--border)] rounded-sm text-xs font-mono text-[var(--foreground)] px-1.5 py-1 outline-none">
            {(['ALL', 'WIN', 'LOSS'] as const).map(o => <option key={o} value={o}>{o}</option>)}
          </select>
          {lastRefresh && <span className="hidden lg:block text-xs font-mono tabular-nums text-[var(--muted-foreground)] opacity-40">{lastRefresh.toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' })}</span>}
          <button onClick={handleRefresh} disabled={refreshing} className="p-1.5 bg-[var(--panel-muted)] border border-[var(--border)] rounded-sm hover:bg-[var(--background)] transition-colors text-[var(--muted-foreground)] disabled:opacity-40">
            <RefreshCw className={`w-3.5 h-3.5 ${refreshing ? 'animate-spin' : ''}`} />
          </button>
          <button className="p-1.5 bg-[var(--kraken-purple)] text-white rounded-sm hover:bg-[var(--kraken-light)] transition-colors ml-1 shadow-[0_0_10px_rgba(139,92,246,0.3)]"><Filter className="w-4 h-4" /></button>
          <button className="p-1.5 bg-[var(--panel-muted)] border border-[var(--border)] rounded-sm hover:bg-[var(--background)] transition-colors text-[var(--muted-foreground)]"><Download className="w-4 h-4" /></button>
        </div>
      </CardHeader>

      {/* Account Balance Strip */}
      <div className="grid grid-cols-4 divide-x divide-[var(--border)] border-b border-[var(--border)] shrink-0 bg-[var(--panel-muted)]/20">
        {[{ label: 'Equity', value: accountData?.equity, color: 'text-[var(--foreground)]' }, { label: 'Buying Power', value: accountData?.buying_power, color: 'text-[var(--foreground)]' }, { label: 'Cash', value: accountData?.cash, color: 'text-[var(--foreground)]' }, { label: 'Long Mkt Val', value: accountData?.long_market_value, color: 'text-[var(--neon-green)]' }].map(({ label, value, color }) => (
          <div key={label} className="flex flex-col px-4 py-2">
            <span className="text-xs text-[var(--muted-foreground)] uppercase tracking-wider mb-0.5 leading-none">{label}</span>
            {value != null
              ? <span className={`text-sm font-mono tabular-nums font-bold leading-snug ${color}`}>${Number(value).toLocaleString(undefined, { minimumFractionDigits: 2, maximumFractionDigits: 2 })}</span>
              : accountData == null
                ? <span className="inline-block animate-pulse bg-[var(--border)] h-3 w-16 rounded-sm mt-0.5" />
                : <span className="text-sm font-mono tabular-nums font-bold leading-snug text-[var(--muted-foreground)]">$0.00</span>
            }
          </div>
        ))}
      </div>

      <KpiSummary data={realizedData} ledgerCount={ledgerTrades.length} />

      {/* Ledger Table */}
      <CardContent className="flex-1 overflow-auto p-0">
        <table className="w-full text-xs text-left tabular-nums font-mono whitespace-nowrap">
          <thead className="sticky top-0 bg-[var(--panel-muted)] border-b border-[var(--border)] text-[var(--muted-foreground)] shadow-sm z-10">
            {ledgerTable.getHeaderGroups().map(hg => (
              <tr key={hg.id}>
                {hg.headers.map((header, i) => (
                  <th key={header.id} className={`font-semibold p-3 ${i === 0 ? 'pl-4' : ''} ${i === hg.headers.length - 1 ? 'pr-4 text-right text-[var(--kraken-light)]' : ''} select-none ${header.column.getCanSort() ? 'cursor-pointer hover:text-[var(--foreground)] transition-colors' : ''}`} onClick={header.column.getToggleSortingHandler()}>
                    <span className="inline-flex items-center gap-1">{flexRender(header.column.columnDef.header, header.getContext())}<SortIcon col={header.column} /></span>
                  </th>
                ))}
              </tr>
            ))}
          </thead>
          <tbody className="divide-y divide-[var(--border)]/30">
            {ledgerTable.getRowModel().rows.length === 0 ? (
              <tr><td colSpan={ledgerColumns.length} className="p-6 text-center text-[var(--muted-foreground)]">{ledgerTrades.length === 0 ? 'No execution records yet' : 'No records match filters'}</td></tr>
            ) : ledgerTable.getRowModel().rows.map(row => (
              <tr key={row.id} className="hover:bg-[var(--panel-muted)] transition-colors cursor-default">
                {row.getVisibleCells().map((cell, i) => (
                  <td key={cell.id} className={`p-3 ${i === 0 ? 'pl-4' : ''} ${i === row.getVisibleCells().length - 1 ? 'pr-4' : ''}`}>
                    {flexRender(cell.column.columnDef.cell, cell.getContext())}
                  </td>
                ))}
              </tr>
            ))}
          </tbody>
        </table>
      </CardContent>

      {/* Trade History */}
      <div className="shrink-0 border-t border-[var(--border)]">
        <div className="flex items-center justify-between px-4 py-2.5 border-b border-[var(--border)] bg-[var(--panel-muted)]/30">
          <span className="text-xs uppercase tracking-widest font-mono text-[var(--muted-foreground)]">Trade History — Open &amp; Close Legs</span>
          <span className="text-xs font-mono text-[var(--muted-foreground)] opacity-40">30s · UTC→local</span>
        </div>
        <div className="overflow-auto max-h-[280px]">
          {roundTripRows.length === 0 ? (
            <div className="flex items-center justify-center py-8 text-xs font-mono text-[var(--muted-foreground)] opacity-40 uppercase tracking-widest">No trade history yet</div>
          ) : (
            <table className="w-full text-xs tabular-nums font-mono whitespace-nowrap min-w-[700px]">
              <thead className="sticky top-0 bg-[var(--panel-muted)] text-[var(--muted-foreground)] border-b border-[var(--border)]">
                {historyTable.getHeaderGroups().map(hg => (
                  <tr key={hg.id}>
                    {hg.headers.map((header, i) => (
                      <th key={header.id} className={`text-left font-medium p-2 ${i === 0 ? 'pl-4' : ''} ${i === hg.headers.length - 1 ? 'pr-4 text-right' : ''} select-none ${header.column.getCanSort() ? 'cursor-pointer hover:text-[var(--foreground)] transition-colors' : ''}`} onClick={header.column.getToggleSortingHandler()}>
                        <span className="inline-flex items-center gap-1">{flexRender(header.column.columnDef.header, header.getContext())}<SortIcon col={header.column} /></span>
                      </th>
                    ))}
                  </tr>
                ))}
              </thead>
              <tbody className="divide-y divide-[var(--border)]/30">
                {historyTable.getRowModel().rows.map(row => (
                  <tr key={row.id} className={`hover:bg-[var(--panel-muted)] transition-colors ${row.original.open ? 'opacity-75' : ''}`}>
                    {row.getVisibleCells().map((cell, i) => (
                      <td key={cell.id} className={`p-2 ${i === 0 ? 'pl-4' : ''} ${i === row.getVisibleCells().length - 1 ? 'pr-4' : ''}`}>
                        {flexRender(cell.column.columnDef.cell, cell.getContext())}
                      </td>
                    ))}
                  </tr>
                ))}
              </tbody>
            </table>
          )}
        </div>
      </div>
    </Card>
  );
}
