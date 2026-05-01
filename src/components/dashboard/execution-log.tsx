"use client"

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
import { EmptyState } from "@/components/ui/empty-state";
import { useTradingStore } from '@/store';
import { parseUtc } from '@/lib/utils';

interface LedgerEntry {
  id: number;
  order_id: string | null;
  symbol: string;
  side: string;
  bot: string;
  fill_price: number;
  qty: number | null;
  slippage: number;
  slippage_bps: number | null;
  confidence: number;
  timestamp: string | null;
}

export function ExecutionLog() {
  const recentTrades = useTradingStore(s => s.recentTrades);
  const ledgerTrades = useTradingStore(s => (s as any).ledgerTrades ?? []);
  const [sorting, setSorting] = React.useState<SortingState>([{ id: 'timestamp', desc: true }]);

  const rows: LedgerEntry[] = React.useMemo(() => {
    if (ledgerTrades.length > 0) return ledgerTrades.map((t: any) => ({ ...t, qty: t.qty ?? t.size ?? null }));
    return recentTrades.map((t: any) => ({
      id:           t.id,
      order_id:     t.id,
      symbol:       t.symbol ?? '—',
      side:         t.side,
      bot:          '—',
      fill_price:   t.price,
      qty:          t.size ?? null,
      slippage:     0,
      slippage_bps: null,
      confidence:   null,
      timestamp:    t.timestamp ? (parseUtc(t.timestamp)?.toISOString() ?? null) : null,
    }));
  }, [recentTrades, ledgerTrades]);

  // Only show slippage column when at least one row has non-zero slippage
  const hasNonZeroSlippage = React.useMemo(
    () => rows.some(r => r.slippage_bps != null && r.slippage_bps !== 0),
    [rows],
  );

  const columns = React.useMemo<ColumnDef<LedgerEntry>[]>(() => {
    const cols: ColumnDef<LedgerEntry>[] = [
      {
        accessorKey: 'timestamp',
        header: 'Time',
        cell: ({ getValue }) => {
          const ts = getValue() as string | null;
          return (
            <span className="text-[var(--muted-foreground)]">
              {ts ? new Date(ts).toLocaleString(undefined, { month: 'short', day: 'numeric', hour: '2-digit', minute: '2-digit', second: '2-digit', hour12: false }) : '—'}
            </span>
          );
        },
      },
      {
        accessorKey: 'symbol',
        header: 'Symbol',
        cell: ({ getValue }) => (
          <span className="text-[var(--foreground)] font-bold">{getValue() as string}</span>
        ),
      },
      {
        accessorKey: 'bot',
        header: 'Bot',
        cell: ({ getValue }) => {
          const bot = getValue() as string;
          return bot !== '—' ? (
            <span title={bot} className="px-1 py-0.5 rounded-sm bg-[var(--panel-muted)] text-[var(--kraken-light)] truncate max-w-[80px] block">
              {bot}
            </span>
          ) : <span className="text-[var(--muted-foreground)]">—</span>;
        },
      },
      {
        accessorKey: 'side',
        header: 'Side',
        cell: ({ getValue }) => {
          const side = (getValue() as string ?? '').replace('OrderSide.', '').toUpperCase();
          return (
            <span className={`font-bold ${side === 'BUY' ? 'text-[var(--neon-green)]' : 'text-[var(--neon-red)]'}`}>
              {side}
            </span>
          );
        },
      },
      {
        accessorKey: 'fill_price',
        header: 'Fill $',
        cell: ({ getValue }) => {
          const v = getValue() as number;
          return (
            <span className="text-right block text-[var(--foreground)]">
              {v != null ? `$${v.toFixed(2)}` : '—'}
            </span>
          );
        },
      },
    ];

    // Slippage column — only when data has non-zero values
    if (hasNonZeroSlippage) {
      cols.push({
        accessorKey: 'slippage_bps',
        header: 'Slip bps',
        cell: ({ getValue }) => {
          const v = getValue() as number | null;
          const color = v != null
            ? v < 5 ? 'text-[var(--neon-green)]' : v < 20 ? 'text-[var(--foreground)]' : 'text-[var(--neon-red)]'
            : 'text-[var(--muted-foreground)]';
          return <span className={`text-right block font-bold ${color}`}>{v != null ? `${v}` : '—'}</span>;
        },
      });
    }

    return cols;
  }, [hasNonZeroSlippage]);

  const table = useReactTable({
    data: rows,
    columns,
    state: { sorting },
    onSortingChange: setSorting,
    getCoreRowModel: getCoreRowModel(),
    getSortedRowModel: getSortedRowModel(),
  });

  return (
    <Card className="h-full flex flex-col">
      <CardHeader className="py-2.5 px-3 border-b border-[var(--border)] flex flex-row items-center justify-between">
        <CardTitle className="text-xs uppercase tracking-wider font-semibold text-[var(--kraken-light)]">
          Booked Fills (Execution Ledger)
        </CardTitle>
        <Badge variant="outline" className="text-xs font-mono">
          {rows.length} fills
        </Badge>
      </CardHeader>
      <CardContent className="flex-1 overflow-y-auto p-0 pb-2">
        <table className="w-full text-left text-xs tabular-nums font-mono">
          <thead className="sticky top-0 bg-[var(--panel-muted)] border-b border-[var(--border)] text-[var(--muted-foreground)] shadow-sm">
            {table.getHeaderGroups().map(hg => (
              <tr key={hg.id}>
                {hg.headers.map((header, i) => {
                  const sorted = header.column.getIsSorted();
                  return (
                    <th
                      key={header.id}
                      className={`font-semibold p-2 ${i === 0 ? 'pl-3' : ''} ${i === hg.headers.length - 1 ? 'pr-3 text-right' : ''} select-none ${header.column.getCanSort() ? 'cursor-pointer hover:text-[var(--foreground)] transition-colors' : ''}`}
                      onClick={header.column.getToggleSortingHandler()}
                    >
                      <span className="inline-flex items-center gap-1">
                        {flexRender(header.column.columnDef.header, header.getContext())}
                        {sorted === 'asc' && <span className="text-[var(--kraken-light)]">▲</span>}
                        {sorted === 'desc' && <span className="text-[var(--kraken-light)]">▼</span>}
                        {!sorted && header.column.getCanSort() && <span className="opacity-20">⇅</span>}
                      </span>
                    </th>
                  );
                })}
              </tr>
            ))}
          </thead>
          <tbody className="divide-y divide-[var(--border)]/20">
            {table.getRowModel().rows.map(row => (
              <tr key={row.id} className="hover:bg-[var(--panel-muted)] transition-colors">
                {row.getVisibleCells().map((cell, i) => (
                  <td key={cell.id} className={`p-1.5 ${i === 0 ? 'pl-3' : ''} ${i === row.getVisibleCells().length - 1 ? 'pr-3' : ''}`}>
                    {flexRender(cell.column.columnDef.cell, cell.getContext())}
                  </td>
                ))}
              </tr>
            ))}
          </tbody>
        </table>
        {rows.length === 0 && (
          <EmptyState message="No executions booked in current session" />
        )}
      </CardContent>
    </Card>
  );
}
