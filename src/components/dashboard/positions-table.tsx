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
import { useTradingStore, RiskStatus } from '@/hooks/useTradingStream';
import { ValueTicker } from '@/components/ui/value-ticker';
import { parseUtc } from '@/lib/utils';

type Tab = 'positions' | 'orders' | 'risk';

interface PositionRow {
  id: string;
  symbol: string;
  side: string;
  size: number;
  entryPrice: number;
  unrealizedPnl: number;
}

interface OrderRow {
  id: string;
  symbol: string;
  side: string;
  size: number;
  status: string;
  timestamp: string | number;
}

function SortIndicator({ sorted }: { sorted: false | 'asc' | 'desc' }) {
  if (sorted === 'asc')  return <span className="text-[var(--kraken-light)]">▲</span>;
  if (sorted === 'desc') return <span className="text-[var(--kraken-light)]">▼</span>;
  return <span className="opacity-20">⇅</span>;
}

// ---------------------------------------------------------------------------
// Exposure heat map — horizontal bar split by notional per position
// ---------------------------------------------------------------------------

function ExposureBar({ positions }: { positions: PositionRow[] }) {
  if (positions.length === 0) return null;

  const notionals = positions.map(p => ({
    symbol: p.symbol,
    notional: Math.abs(p.size * p.entryPrice),
    side: p.side,
  }));
  const total = notionals.reduce((s, n) => s + n.notional, 0);
  if (total === 0) return null;

  const COLORS = [
    'var(--kraken-purple)',
    'var(--neon-green)',
    'var(--neon-blue)',
    'var(--warning)',
    'var(--agent-observe)',
    'var(--agent-calculate)',
  ];

  return (
    <div className="px-3 pt-2 pb-1.5 border-b border-[var(--border)] shrink-0">
      <div className="text-xs text-[var(--muted-foreground)] uppercase tracking-wider mb-1 opacity-60">Exposure</div>
      <div className="flex h-2 rounded-sm overflow-hidden gap-px">
        {notionals.map((n, i) => (
          <div
            key={n.symbol}
            title={`${n.symbol}: $${n.notional.toFixed(0)}`}
            style={{
              flexBasis: `${(n.notional / total) * 100}%`,
              background: COLORS[i % COLORS.length],
              opacity: n.side === 'LONG' ? 1 : 0.6,
            }}
          />
        ))}
      </div>
      <div className="flex gap-3 mt-1 flex-wrap">
        {notionals.map((n, i) => (
          <span key={n.symbol} className="text-xs font-mono tabular-nums text-[var(--muted-foreground)] opacity-60 flex items-center gap-1">
            <span className="inline-block w-1.5 h-1.5 rounded-sm" style={{ background: COLORS[i % COLORS.length] }} />
            {n.symbol}
          </span>
        ))}
      </div>
    </div>
  );
}

// ---------------------------------------------------------------------------
// Risk Status Panel
// ---------------------------------------------------------------------------

function RiskStatusPanel({ riskStatus, fetchRiskStatus }: {
  riskStatus: RiskStatus | null;
  fetchRiskStatus: () => Promise<void>;
}) {
  React.useEffect(() => {
    fetchRiskStatus();
    const id = setInterval(fetchRiskStatus, 15_000);
    return () => clearInterval(id);
  }, [fetchRiskStatus]);

  if (!riskStatus) {
    return (
      <div className="flex items-center justify-center h-full text-xs text-[var(--muted-foreground)] opacity-40">
        Loading risk status...
      </div>
    );
  }

  const ddPct = riskStatus.drawdown_pct ?? 0;
  const maxDdPct = riskStatus.max_drawdown_pct ?? 0.02;
  const ddUtilization = maxDdPct > 0 ? Math.min(1, ddPct / maxDdPct) : 0;

  return (
    <div className="p-3 space-y-3">
      {riskStatus.triggered && (
        <div className="px-3 py-2 bg-[var(--neon-red)]/10 border border-[var(--neon-red)]/40 rounded-sm">
          <span className="text-xs font-bold text-[var(--neon-red)] uppercase tracking-wider">
            Kill Switch Active: {riskStatus.reason ?? 'Unknown reason'}
          </span>
        </div>
      )}

      {/* Drawdown utilization bar */}
      <div>
        <div className="flex items-center justify-between mb-1">
          <span className="text-xs text-[var(--muted-foreground)] uppercase tracking-wider">Daily Drawdown</span>
          <span className={`text-xs font-mono tabular-nums font-bold ${ddPct > 0.015 ? 'text-[var(--neon-red)]' : ddPct > 0.01 ? 'text-[var(--warning)]' : 'text-[var(--foreground)]'}`}>
            {(ddPct * 100).toFixed(2)}% / {(maxDdPct * 100).toFixed(0)}%
          </span>
        </div>
        <div className="h-1.5 rounded-sm overflow-hidden" style={{ background: 'var(--border)' }}>
          <div
            className="h-full rounded-sm transition-all"
            style={{
              width: `${ddUtilization * 100}%`,
              background: ddUtilization > 0.75 ? 'var(--neon-red)' : ddUtilization > 0.5 ? 'var(--warning)' : 'var(--neon-green)',
            }}
          />
        </div>
      </div>

      {/* Risk parameters grid */}
      <div className="grid grid-cols-2 gap-x-4 gap-y-2">
        <div>
          <span className="text-xs text-[var(--muted-foreground)] uppercase tracking-wider block mb-0.5">Max Position</span>
          <span className="text-xs font-mono tabular-nums text-[var(--foreground)]">
            {(riskStatus.max_position_pct * 100).toFixed(0)}% / ${riskStatus.max_position_usd.toLocaleString()}
          </span>
        </div>
        <div>
          <span className="text-xs text-[var(--muted-foreground)] uppercase tracking-wider block mb-0.5">Kelly Cap</span>
          <span className="text-xs font-mono tabular-nums text-[var(--foreground)]">
            {(riskStatus.max_kelly_fraction * 100).toFixed(0)}%
          </span>
        </div>
        <div>
          <span className="text-xs text-[var(--muted-foreground)] uppercase tracking-wider block mb-0.5">Min Confidence</span>
          <span className="text-xs font-mono tabular-nums text-[var(--foreground)]">
            {(riskStatus.min_confidence_gate * 100).toFixed(0)}%
          </span>
        </div>
        <div>
          <span className="text-xs text-[var(--muted-foreground)] uppercase tracking-wider block mb-0.5">SOD Equity</span>
          <span className="text-xs font-mono tabular-nums text-[var(--foreground)]">
            {riskStatus.start_of_day_equity != null
              ? `$${riskStatus.start_of_day_equity.toLocaleString(undefined, { minimumFractionDigits: 2, maximumFractionDigits: 2 })}`
              : '—'}
          </span>
        </div>
      </div>
    </div>
  );
}

// ---------------------------------------------------------------------------
// PositionsTable
// ---------------------------------------------------------------------------

export function PositionsTable() {
  const positions      = useTradingStore(s => s.positions);
  const recentTrades   = useTradingStore(s => s.recentTrades);
  const riskStatus     = useTradingStore(s => s.riskStatus);
  const fetchRiskStatus = useTradingStore(s => s.fetchRiskStatus);

  const [todayPl, setTodayPl] = React.useState<number | null>(null);

  React.useEffect(() => {
    const load = () =>
      fetch(`${API_BASE}/api/account`, { signal: AbortSignal.timeout(8000) })
        .then(r => r.ok ? r.json() : null)
        .then(d => { if (d) setTodayPl(Number(d.today_pl ?? 0)); })
        .catch(() => {});
    load();
    const id = setInterval(load, 30_000);
    return () => clearInterval(id);
  }, []);

  const [activeTab, setActiveTab] = React.useState<Tab>('positions');
  const [posSorting, setPosSorting]     = React.useState<SortingState>([]);
  const [orderSorting, setOrderSorting] = React.useState<SortingState>([]);

  const openOrders = recentTrades.filter((t: any) => t.price === 0 || t.status === 'pending');

  // ── Positions columns ──────────────────────────────────────────────────────
  const posColumns = React.useMemo<ColumnDef<PositionRow>[]>(() => [
    {
      accessorKey: 'symbol',
      header: 'Symbol',
      cell: ({ getValue }) => (
        <span className="font-bold text-[var(--foreground)]">{getValue() as string}</span>
      ),
    },
    {
      accessorKey: 'side',
      header: 'Side',
      cell: ({ getValue }) => {
        const s = getValue() as string;
        return <Badge variant={s === 'LONG' ? 'success' : 'destructive'} className="text-xs px-1.5">{s}</Badge>;
      },
    },
    {
      accessorKey: 'size',
      header: 'Size',
      cell: ({ getValue }) => (
        <span className="text-right block font-mono tabular-nums text-[var(--foreground)]">
          {(getValue() as number).toFixed(4)}
        </span>
      ),
    },
    {
      accessorKey: 'entryPrice',
      header: 'Entry Price',
      cell: ({ getValue }) => (
        <span className="text-right block font-mono tabular-nums text-[var(--muted-foreground)]">
          ${(getValue() as number).toFixed(2)}
        </span>
      ),
    },
    {
      accessorKey: 'unrealizedPnl',
      header: 'Unrealized PnL',
      cell: ({ getValue }) => (
        <div className="text-right">
          <ValueTicker value={getValue() as number} prefix="$" />
        </div>
      ),
    },
  ], []);

  // ── Open Orders columns ────────────────────────────────────────────────────
  const orderColumns = React.useMemo<ColumnDef<OrderRow>[]>(() => [
    {
      accessorKey: 'symbol',
      header: 'Symbol',
      cell: ({ getValue }) => (
        <span className="font-bold text-[var(--foreground)]">{getValue() as string}</span>
      ),
    },
    {
      accessorKey: 'side',
      header: 'Side',
      cell: ({ getValue }) => {
        const s = getValue() as string;
        return (
          <div className="flex justify-center">
            <Badge variant={s === 'BUY' ? 'success' : 'destructive'} className="text-xs px-1.5">{s}</Badge>
          </div>
        );
      },
    },
    {
      accessorKey: 'size',
      header: 'Qty',
      cell: ({ getValue }) => (
        <span className="text-right block font-mono tabular-nums">{(getValue() as number).toFixed(4)}</span>
      ),
    },
    {
      accessorKey: 'status',
      header: 'Status',
      cell: () => (
        <div className="text-right">
          <Badge variant="warning" className="text-xs px-1.5 uppercase">PENDING</Badge>
        </div>
      ),
    },
    {
      accessorKey: 'timestamp',
      header: 'Submitted',
      cell: ({ getValue }) => {
        const ts = getValue() as string | number;
        return (
          <span className="text-right block text-[var(--muted-foreground)] font-mono tabular-nums">
            {ts ? (parseUtc(ts)?.toLocaleTimeString(undefined, { hour12: false }) ?? '—') : '—'}
          </span>
        );
      },
    },
  ], []);

  // ── Table instances ────────────────────────────────────────────────────────
  const posTable = useReactTable({
    data: positions as PositionRow[],
    columns: posColumns,
    state: { sorting: posSorting },
    onSortingChange: setPosSorting,
    getCoreRowModel: getCoreRowModel(),
    getSortedRowModel: getSortedRowModel(),
  });

  const orderTable = useReactTable({
    data: openOrders as OrderRow[],
    columns: orderColumns,
    state: { sorting: orderSorting },
    onSortingChange: setOrderSorting,
    getCoreRowModel: getCoreRowModel(),
    getSortedRowModel: getSortedRowModel(),
  });

  const tabClass = (tab: Tab) =>
    activeTab === tab
      ? 'text-xs uppercase tracking-wider font-bold text-[var(--kraken-light)] border-b-2 border-[var(--kraken-purple)] pb-1 cursor-pointer'
      : 'text-xs uppercase tracking-wider font-semibold text-[var(--muted-foreground)] cursor-pointer hover:text-[var(--foreground)] pb-1';

  const renderTable = (table: ReturnType<typeof useReactTable<any>>, emptyMsg: string, colSpan: number) => (
    <table className="w-full text-left text-xs tabular-nums font-mono">
      <thead className="sticky top-0 bg-[var(--panel-muted)] border-b border-[var(--border)] text-[var(--muted-foreground)] shadow-sm">
        {table.getHeaderGroups().map(hg => (
          <tr key={hg.id}>
            {hg.headers.map((header, i) => {
              const sorted = header.column.getIsSorted();
              return (
                <th
                  key={header.id}
                  className={`font-medium p-2 ${i === 0 ? 'pl-4' : ''} ${i === hg.headers.length - 1 ? 'pr-4' : ''} select-none ${header.column.getCanSort() ? 'cursor-pointer hover:text-[var(--foreground)] transition-colors' : ''}`}
                  onClick={header.column.getToggleSortingHandler()}
                >
                  <span className="inline-flex items-center gap-1">
                    {flexRender(header.column.columnDef.header, header.getContext())}
                    {header.column.getCanSort() && <SortIndicator sorted={sorted} />}
                  </span>
                </th>
              );
            })}
          </tr>
        ))}
      </thead>
      <tbody className="divide-y divide-[var(--border)]/30">
        {table.getRowModel().rows.length === 0 ? (
          <tr>
            <td colSpan={colSpan} className="p-4 text-center text-[var(--muted-foreground)]">
              {emptyMsg}
            </td>
          </tr>
        ) : table.getRowModel().rows.map(row => (
          <tr key={row.id} className="hover:bg-[var(--panel-muted)] transition-colors">
            {row.getVisibleCells().map((cell, i) => (
              <td key={cell.id} className={`p-2 ${i === 0 ? 'pl-4' : ''} ${i === row.getVisibleCells().length - 1 ? 'pr-4' : ''}`}>
                {flexRender(cell.column.columnDef.cell, cell.getContext())}
              </td>
            ))}
          </tr>
        ))}
      </tbody>
    </table>
  );

  return (
    <Card className="h-full flex flex-col min-h-[250px]">
      <CardHeader className="py-2.5 px-3 border-b border-[var(--border)] flex flex-row items-center justify-between">
        <div className="flex space-x-4">
          <CardTitle className={tabClass('positions')} onClick={() => setActiveTab('positions')}>
            Positions ({positions.length})
          </CardTitle>
          <CardTitle className={tabClass('orders')} onClick={() => setActiveTab('orders')}>
            Open Orders ({openOrders.length})
          </CardTitle>
          <CardTitle className={tabClass('risk')} onClick={() => setActiveTab('risk')}>
            Risk
          </CardTitle>
        </div>
        <div className="text-xs font-mono font-bold text-[var(--foreground)]">
          DAY PNL:{' '}
          {todayPl != null ? (
            <span className={todayPl >= 0 ? 'text-[var(--neon-green)]' : 'text-[var(--neon-red)]'}>
              {todayPl >= 0 ? '+' : ''}${todayPl.toFixed(2)}
            </span>
          ) : (
            <span className="text-[var(--muted-foreground)] opacity-40">—</span>
          )}
        </div>
      </CardHeader>

      {/* Exposure heat map — only when positions are open */}
      {activeTab === 'positions' && positions.length > 0 && (
        <ExposureBar positions={positions as PositionRow[]} />
      )}

      <CardContent className="flex-1 overflow-y-auto p-0">
        {activeTab === 'positions' && renderTable(posTable, 'No open positions', 5)}
        {activeTab === 'orders'    && renderTable(orderTable, 'No open orders',  5)}
        {activeTab === 'risk'      && (
          <RiskStatusPanel riskStatus={riskStatus} fetchRiskStatus={fetchRiskStatus} />
        )}
      </CardContent>
    </Card>
  );
}
