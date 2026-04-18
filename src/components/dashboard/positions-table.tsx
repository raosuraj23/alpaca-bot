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
import { useTradingStore } from '@/hooks/useTradingStream';
import { ValueTicker } from '@/components/ui/value-ticker';
import { parseUtc } from '@/lib/utils';

type Tab = 'positions' | 'orders' | 'history';

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

interface HistoryRow {
  id: string;
  symbol: string;
  side: string;
  size: number;
  price: number;
  slippage_bps: number | null;
  timestamp: string | number;
}

function SortIndicator({ sorted }: { sorted: false | 'asc' | 'desc' }) {
  if (sorted === 'asc')  return <span className="text-[var(--kraken-light)]">▲</span>;
  if (sorted === 'desc') return <span className="text-[var(--kraken-light)]">▼</span>;
  return <span className="opacity-20">⇅</span>;
}

export function PositionsTable() {
  const positions    = useTradingStore(s => s.positions);
  const recentTrades = useTradingStore(s => s.recentTrades);
  const ledgerTrades = useTradingStore(s => s.ledgerTrades);

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

  const ledgerByOrderId = React.useMemo(() => {
    const map = new Map<string, { slippage_bps: number | null; confidence: number | null }>();
    for (const r of ledgerTrades) {
      if (r.order_id) map.set(r.order_id, { slippage_bps: r.slippage_bps ?? null, confidence: r.confidence ?? null });
    }
    return map;
  }, [ledgerTrades]);

  const [activeTab, setActiveTab] = React.useState<Tab>('positions');
  const [posSorting, setPosSorting]     = React.useState<SortingState>([]);
  const [orderSorting, setOrderSorting] = React.useState<SortingState>([]);
  const [histSorting, setHistSorting]   = React.useState<SortingState>([{ id: 'timestamp', desc: true }]);

  const openOrders = recentTrades.filter((t: any) => t.price === 0 || t.status === 'pending');
  const history    = recentTrades.filter((t: any) => t.price > 0 && t.status !== 'pending');

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

  // ── History columns ────────────────────────────────────────────────────────
  const histColumns = React.useMemo<ColumnDef<HistoryRow>[]>(() => [
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
      accessorKey: 'price',
      header: 'Fill Price',
      cell: ({ getValue }) => (
        <span className="text-right block font-mono tabular-nums font-bold text-[var(--foreground)]">
          ${(getValue() as number).toFixed(2)}
        </span>
      ),
    },
    {
      accessorKey: 'slippage_bps',
      header: 'Slip (bps)',
      cell: ({ getValue }) => {
        const v = getValue() as number | null;
        const cls = v == null ? 'text-[var(--muted-foreground)]'
          : v < 0 ? 'text-[var(--neon-green)]'
          : v > 5 ? 'text-[var(--neon-red)]'
          : 'text-[var(--foreground)]';
        return (
          <span className={`text-right block font-mono tabular-nums ${cls}`}>
            {v != null ? `${v > 0 ? '+' : ''}${v.toFixed(1)}` : '—'}
          </span>
        );
      },
    },
    {
      accessorKey: 'timestamp',
      header: 'Time',
      cell: ({ getValue }) => {
        const ts = getValue() as string | number;
        return (
          <span className="text-right block text-[var(--muted-foreground)] font-mono tabular-nums">
            {ts ? (parseUtc(ts)?.toLocaleString(undefined, { hour12: false }) ?? '—') : '—'}
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

  const histData = React.useMemo<HistoryRow[]>(() =>
    history.map((o: any) => {
      const ledger = ledgerByOrderId.get(o.id?.slice(0, 8));
      return {
        id: o.id,
        symbol: o.symbol,
        side: o.side,
        size: o.size,
        price: o.price,
        slippage_bps: ledger?.slippage_bps ?? null,
        timestamp: o.timestamp,
      };
    }), [history, ledgerByOrderId]);

  const histTable = useReactTable({
    data: histData,
    columns: histColumns,
    state: { sorting: histSorting },
    onSortingChange: setHistSorting,
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
          <CardTitle className={tabClass('history')} onClick={() => setActiveTab('history')}>
            History ({history.length})
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

      <CardContent className="flex-1 overflow-y-auto p-0">
        {activeTab === 'positions' && renderTable(posTable,   'No open positions', 5)}
        {activeTab === 'orders'    && renderTable(orderTable, 'No open orders',    5)}
        {activeTab === 'history'   && renderTable(histTable,  'No trade history',  6)}
      </CardContent>
    </Card>
  );
}
