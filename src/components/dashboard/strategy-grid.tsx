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
import { Button } from "@/components/ui/button";
import { useTradingStore } from '@/hooks/useTradingStream';

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

function Dash() {
  return <span className="font-mono tabular-nums text-[var(--muted-foreground)] opacity-30">—</span>;
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

  const columns = React.useMemo<ColumnDef<Bot>[]>(() => [
    {
      accessorKey: 'name',
      header: 'Agent',
      cell: ({ row }) => (
        <div className="flex items-center gap-2 font-medium text-[var(--foreground)] whitespace-nowrap">
          <div className={`w-2 h-2 rounded-sm shrink-0 ${row.original.status === 'ACTIVE' ? 'bg-[var(--neon-green)] shadow-[0_0_8px_rgba(0,200,5,0.5)]' : 'bg-[var(--muted-foreground)] opacity-40'}`} />
          {row.original.name}
        </div>
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
      accessorKey: 'algo',
      header: 'Algorithm',
      cell: ({ getValue }) => (
        <span className="text-[var(--muted-foreground)] whitespace-nowrap">{getValue() as string}</span>
      ),
    },
    {
      accessorKey: 'allocationPct',
      header: 'Alloc %',
      cell: ({ getValue }) => (
        <span className="block text-right font-mono tabular-nums">{getValue() as number}%</span>
      ),
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
        return (
          <span className={`font-mono tabular-nums ${v >= 50 ? 'text-[var(--neon-green)]' : 'text-[var(--neon-red)]'}`}>
            {v.toFixed(1)}%
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
      accessorKey: 'status',
      header: 'Status',
      cell: ({ getValue }) => {
        const s = getValue() as string;
        return (
          <div className="flex justify-center">
            <Badge variant={s === 'ACTIVE' ? 'success' : s === 'HALTED' ? 'destructive' : 'outline'}>
              {s}
            </Badge>
          </div>
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
    state: { sorting },
    onSortingChange: setSorting,
    getCoreRowModel: getCoreRowModel(),
    getSortedRowModel: getSortedRowModel(),
  });

  return (
    <Card className="flex flex-col h-full bg-[var(--panel)]/50">
      <CardHeader className="py-4 px-6 border-b border-[var(--border)] flex flex-row items-center justify-between shrink-0">
        <div>
          <CardTitle className="text-lg text-[var(--kraken-light)]">Strategy Fleet</CardTitle>
          <div className="text-xs text-[var(--muted-foreground)] mt-1 tracking-wide">
            Manage algorithmic agent deployment and allocation.
          </div>
        </div>
        <Button variant="default">+ Deploy New Agent</Button>
      </CardHeader>
      <CardContent className="p-0 overflow-x-auto">
        <table className="w-full text-sm text-left font-mono min-w-[900px]">
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
              <tr key={row.id} className="hover:bg-[var(--panel-muted)]/30 transition-colors">
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
    </Card>
  );
}
