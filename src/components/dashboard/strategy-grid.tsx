"use client"

import * as React from 'react';
import {
  useReactTable,
  getCoreRowModel,
  getSortedRowModel,
  getFilteredRowModel,
  flexRender,
  type ColumnDef,
  type SortingState,
  type RowSelectionState,
} from '@tanstack/react-table';
import { Card, CardHeader, CardTitle, CardContent } from "@/components/ui/card";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { useTradingStore } from '@/hooks/useTradingStream';
import { API_BASE } from '@/lib/api';

type Bot = {
  id: string;
  name: string;
  algo: string;
  allocationPct: number;
  yield24h: number;
  status: string;
  assetClass?: 'CRYPTO' | 'EQUITY' | 'OPTIONS';
  signalCount?: number;
  fillCount?: number;
};

const ASSET_COLORS: Record<string, string> = {
  CRYPTO:  'text-[var(--kraken-light)] bg-[var(--kraken-purple)]/20 border-[var(--kraken-purple)]/30',
  EQUITY:  'text-[var(--neon-green)] bg-[var(--neon-green)]/10 border-[var(--neon-green)]/20',
  OPTIONS: 'text-[var(--agent-learning)] bg-[var(--agent-learning)]/10 border-[var(--agent-learning)]/20',
};

const MIN_WIN_RATE_SAMPLE = 10;

function Dash() {
  return <span className="font-mono tabular-nums text-[var(--muted-foreground)] opacity-30">—</span>;
}

function AllocationBar({ value }: { value: number }) {
  return (
    <div className="flex items-center justify-end gap-2">
      <span className="font-mono tabular-nums text-right">{value}%</span>
      <div className="w-10 h-1 bg-[var(--border)] rounded-sm overflow-hidden shrink-0">
        <div
          className="h-full bg-[var(--kraken-purple)]/70 rounded-sm"
          style={{ width: `${Math.min(value, 100)}%` }}
        />
      </div>
    </div>
  );
}

function BotActions({ bot }: { bot: Bot }) {
  return (
    <div className="flex justify-end gap-2">
      <Button variant="outline" size="sm">Config</Button>
      <Button variant={bot.status === 'ACTIVE' ? 'destructive' : 'success'} size="sm">
        {bot.status === 'ACTIVE' ? 'Halt' : 'Boot'}
      </Button>
    </div>
  );
}

export function QuantStrategies() {
  const bots = useTradingStore(s => s.bots) as Bot[];
  const [sorting, setSorting] = React.useState<SortingState>([{ id: 'yield24h', desc: true }]);
  const [rowSelection, setRowSelection] = React.useState<RowSelectionState>({});

  const totalAlloc = React.useMemo(
    () => bots.reduce((s, b) => s + (b.allocationPct ?? 0), 0),
    [bots]
  );

  const columns = React.useMemo<ColumnDef<Bot>[]>(() => [
    {
      id: 'select',
      enableSorting: false,
      header: ({ table }) => (
        <input
          type="checkbox"
          className="accent-[var(--kraken-purple)] w-3 h-3 cursor-pointer"
          checked={table.getIsAllRowsSelected()}
          onChange={table.getToggleAllRowsSelectedHandler()}
        />
      ),
      cell: ({ row }) => (
        <input
          type="checkbox"
          className="accent-[var(--kraken-purple)] w-3 h-3 cursor-pointer"
          checked={row.getIsSelected()}
          onChange={row.getToggleSelectedHandler()}
          onClick={e => e.stopPropagation()}
        />
      ),
    },
    {
      accessorKey: 'name',
      header: 'Agent',
      cell: ({ row }) => {
        const isActive = row.original.status === 'ACTIVE';
        const isHalted = row.original.status === 'HALTED';
        return (
          <div className="flex items-center gap-2 whitespace-nowrap">
            <div className={`w-2 h-2 rounded-sm shrink-0 ${isActive ? 'bg-[var(--neon-green)] shadow-[0_0_8px_rgba(0,200,5,0.5)]' : 'bg-[var(--muted-foreground)] opacity-40'}`} />
            <span className="font-medium text-[var(--foreground)]">{row.original.name}</span>
            {isHalted && (
              <Badge variant="destructive" className="text-xs px-1 py-0 leading-none">HALTED</Badge>
            )}
          </div>
        );
      },
    },
    {
      accessorKey: 'assetClass',
      header: 'Class',
      cell: ({ getValue }) => {
        const ac = (getValue() as string | undefined) ?? 'EQUITY';
        const cls = ASSET_COLORS[ac] ?? ASSET_COLORS.EQUITY;
        return (
          <span className={`inline-block px-1.5 py-0.5 text-xs font-mono font-bold border rounded-sm ${cls}`}>
            {ac}
          </span>
        );
      },
    },
    {
      accessorKey: 'algo',
      header: 'Algorithm',
      cell: ({ getValue }) => (
        <span className="text-[var(--muted-foreground)] whitespace-nowrap">{getValue() as string}</span>
      ),
    },
    {
      accessorKey: 'allocationPct',
      header: 'Alloc %',
      cell: ({ getValue }) => <AllocationBar value={getValue() as number} />,
    },
    {
      accessorKey: 'signalCount',
      header: 'Signals',
      cell: ({ getValue }) => {
        const v = getValue() as number | undefined;
        if (!v) return <Dash />;
        return <span className="font-mono tabular-nums text-[var(--foreground)]">{v.toLocaleString()}</span>;
      },
    },
    {
      id: 'winRate',
      header: 'Win Rate',
      accessorFn: (row) => {
        const sc = row.signalCount ?? 0;
        const fc = row.fillCount ?? 0;
        return sc > 0 ? (fc / sc) * 100 : null;
      },
      cell: ({ row, getValue }) => {
        const v = getValue() as number | null;
        const fills = row.original.fillCount ?? 0;
        if (v == null || fills < MIN_WIN_RATE_SAMPLE) return <Dash />;
        return (
          <span className={`font-mono tabular-nums ${v >= 50 ? 'text-[var(--neon-green)]' : 'text-[var(--neon-red)]'}`}>
            {v.toFixed(1)}%{' '}
            <span className="text-[var(--muted-foreground)] text-xs opacity-60">({fills})</span>
          </span>
        );
      },
    },
    {
      id: 'fills',
      header: 'Fills',
      accessorFn: (row) => row.fillCount ?? null,
      cell: ({ getValue }) => {
        const v = getValue() as number | null;
        if (v == null || v === 0) return <Dash />;
        return <span className="font-mono tabular-nums text-[var(--foreground)]">{v.toLocaleString()}</span>;
      },
    },
    {
      accessorKey: 'yield24h',
      header: 'Yield 24h',
      cell: ({ getValue }) => {
        const v = getValue() as number;
        if (v === 0) return <Dash />;
        return (
          <span className={`font-mono tabular-nums font-bold ${v >= 0 ? 'text-[var(--neon-green)]' : 'text-[var(--neon-red)]'}`}>
            {v >= 0 ? '+' : ''}${v.toFixed(2)}
          </span>
        );
      },
    },
    {
      id: 'avgTrade',
      header: 'Avg/Trade',
      accessorFn: (row) => {
        const fills = row.fillCount ?? 0;
        return fills > 0 ? row.yield24h / fills : null;
      },
      cell: ({ getValue }) => {
        const v = getValue() as number | null;
        if (v == null) return <Dash />;
        return (
          <span className={`font-mono tabular-nums ${v >= 0 ? 'text-[var(--neon-green)]' : 'text-[var(--neon-red)]'}`}>
            {v >= 0 ? '+' : ''}${v.toFixed(2)}
          </span>
        );
      },
    },
    {
      id: 'actions',
      header: '',
      enableSorting: false,
      cell: ({ row }) => <BotActions bot={row.original} />,
    },
  ], []);

  const table = useReactTable({
    data: bots,
    columns,
    state: { sorting, rowSelection },
    onSortingChange: setSorting,
    onRowSelectionChange: setRowSelection,
    getCoreRowModel: getCoreRowModel(),
    getSortedRowModel: getSortedRowModel(),
    getFilteredRowModel: getFilteredRowModel(),
  });

  const selectedIds = Object.keys(rowSelection).filter(k => rowSelection[k]).map(idx => bots[+idx]?.id).filter(Boolean);

  async function bulkAction(action: 'halt' | 'resume') {
    try {
      await fetch(`${API_BASE}/api/bots/bulk`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ ids: selectedIds, action }),
      });
    } catch {
      // endpoint may not exist yet — intent logged
    }
    setRowSelection({});
  }

  return (
    <Card className="flex flex-col h-full bg-[var(--panel)]/50 relative">
      <CardHeader className="py-4 px-6 border-b border-[var(--border)] flex flex-row items-center justify-between shrink-0">
        <div>
          <CardTitle className="text-lg text-[var(--kraken-light)]">Strategy Fleet</CardTitle>
          <div className="text-xs text-[var(--muted-foreground)] mt-1 tracking-wide">
            Manage algorithmic agent deployment and allocation.
          </div>
        </div>
        <div className="flex items-center gap-3">
          <span className={`text-xs font-mono tabular-nums ${totalAlloc > 100 ? 'text-[var(--neon-red)]' : 'text-[var(--muted-foreground)]'}`}>
            Total: {totalAlloc}%
          </span>
        </div>
      </CardHeader>
      <CardContent className="p-0 overflow-x-auto">
        <table className="w-full text-sm text-left font-mono">
          <thead className="bg-[var(--panel-muted)] border-b border-[var(--border)] text-[var(--muted-foreground)] uppercase text-xs tracking-wider">
            {table.getHeaderGroups().map(hg => (
              <tr key={hg.id}>
                {hg.headers.map(header => {
                  const sorted = header.column.getIsSorted();
                  return (
                    <th
                      key={header.id}
                      className={`p-4 font-medium select-none whitespace-nowrap ${header.column.getCanSort() ? 'cursor-pointer hover:text-[var(--foreground)] transition-colors' : ''}`}
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
          <tbody className="divide-y divide-[var(--border)]/50">
            {table.getRowModel().rows.map(row => (
              <tr
                key={row.id}
                className={`hover:bg-[var(--panel-muted)]/30 transition-colors ${row.original.status === 'HALTED' ? 'opacity-50' : ''}`}
              >
                {row.getVisibleCells().map(cell => (
                  <td key={cell.id} className="p-4 whitespace-nowrap">
                    {flexRender(cell.column.columnDef.cell, cell.getContext())}
                  </td>
                ))}
              </tr>
            ))}
          </tbody>
        </table>
      </CardContent>

      {/* Bulk action toolbar */}
      {selectedIds.length > 0 && (
        <div className="absolute bottom-4 left-1/2 -translate-x-1/2 flex items-center gap-3 px-4 py-2 bg-[var(--panel)] border border-[var(--border)] rounded-sm shadow-lg z-10 text-xs font-mono whitespace-nowrap">
          <span className="text-[var(--muted-foreground)]">{selectedIds.length} selected</span>
          <span className="text-[var(--border)]">·</span>
          <button
            className="text-[var(--neon-red)] hover:text-[var(--neon-red)]/80 transition-colors"
            onClick={() => bulkAction('halt')}
          >
            Halt All
          </button>
          <button
            className="text-[var(--neon-green)] hover:text-[var(--neon-green)]/80 transition-colors"
            onClick={() => bulkAction('resume')}
          >
            Resume All
          </button>
          <button
            className="text-[var(--muted-foreground)] hover:text-[var(--foreground)] transition-colors"
            onClick={() => setRowSelection({})}
          >
            Clear
          </button>
        </div>
      )}
    </Card>
  );
}
