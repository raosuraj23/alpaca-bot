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
import { Activity } from 'lucide-react';

interface BotRow {
  id: string;
  name: string;
  status: string;
  assetClass?: string;
  algo: string;
  signalCount?: number;
  fillCount?: number;
  yield24h: number;
}

interface BotPerformanceMatrixProps {
  bots: BotRow[];
}

const ASSET_COLORS: Record<string, string> = {
  CRYPTO: 'text-[var(--kraken-light)] bg-[var(--kraken-purple)]/20 border-[var(--kraken-purple)]/30',
  EQUITY: 'text-[var(--neon-green)] bg-[var(--neon-green)]/10 border-[var(--neon-green)]/20',
  OPTIONS: 'text-[var(--agent-learning)] bg-[var(--agent-learning)]/10 border-[var(--agent-learning)]/20',
};

function Dash() {
  return <span className="font-mono tabular-nums text-[var(--muted-foreground)] opacity-30">—</span>;
}

export function BotPerformanceMatrix({ bots }: BotPerformanceMatrixProps) {
  const [sorting, setSorting] = React.useState<SortingState>([]);

  const data = React.useMemo<BotRow[]>(() => bots, [bots]);

  const columns = React.useMemo<ColumnDef<BotRow>[]>(() => [
    {
      accessorKey: 'name',
      header: 'Bot',
      cell: ({ getValue }) => (
        <span className="font-mono font-semibold text-[var(--foreground)] truncate max-w-[120px] block">
          {getValue() as string}
        </span>
      ),
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
      accessorKey: 'status',
      header: 'Status',
      cell: ({ getValue }) => {
        const active = (getValue() as string) === 'ACTIVE';
        return (
          <span className={`inline-flex items-center gap-1 text-xs font-mono ${active ? 'text-[var(--neon-green)]' : 'text-[var(--muted-foreground)]'}`}>
            <span className={`w-1.5 h-1.5 rounded-sm ${active ? 'bg-[var(--neon-green)]' : 'bg-[var(--muted-foreground)] opacity-40'}`} />
            {active ? 'ACTIVE' : 'HALTED'}
          </span>
        );
      },
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
      cell: ({ getValue }) => {
        const v = getValue() as number | null;
        if (v == null) return <Dash />;
        return <span className={`font-mono tabular-nums ${v >= 50 ? 'text-[var(--neon-green)]' : 'text-[var(--neon-red)]'}`}>{v.toFixed(1)}%</span>;
      },
    },
    {
      id: 'fillCount',
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
  ], []);

  const table = useReactTable({
    data,
    columns,
    state: { sorting },
    onSortingChange: setSorting,
    getCoreRowModel: getCoreRowModel(),
    getSortedRowModel: getSortedRowModel(),
  });

  if (bots.length === 0) {
    return (
      <div className="flex flex-col items-center justify-center py-10 gap-2">
        <Activity className="w-5 h-5 text-[var(--muted-foreground)] opacity-20" />
        <span className="text-xs font-mono text-[var(--muted-foreground)] opacity-40 uppercase tracking-widest">
          Awaiting Execution Data
        </span>
      </div>
    );
  }

  const scrollClass = bots.length > 10 ? 'overflow-y-auto max-h-[280px]' : 'overflow-hidden';

  return (
    <div className={scrollClass}>
      <table className="w-full text-xs font-mono">
        <thead className="sticky top-0 bg-[var(--panel-muted)] text-[var(--muted-foreground)] border-b border-[var(--border)]">
          {table.getHeaderGroups().map(hg => (
            <tr key={hg.id}>
              {hg.headers.map(header => {
                const sorted = header.column.getIsSorted();
                return (
                  <th
                    key={header.id}
                    className={`text-left font-medium p-2 tracking-wider uppercase select-none ${header.column.getCanSort() ? 'cursor-pointer hover:text-[var(--foreground)] transition-colors' : ''}`}
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
        <tbody className="divide-y divide-[var(--border)]/30">
          {table.getRowModel().rows.map(row => (
            <tr key={row.id} className="hover:bg-[var(--panel-muted)] transition-colors">
              {row.getVisibleCells().map(cell => (
                <td key={cell.id} className="p-2 tabular-nums">
                  {flexRender(cell.column.columnDef.cell, cell.getContext())}
                </td>
              ))}
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}
