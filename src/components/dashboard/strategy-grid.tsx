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
};

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
        <div className="flex items-center gap-3 font-medium text-[var(--foreground)]">
          <div className={`w-2 h-2 rounded-sm ${row.original.status === 'ACTIVE' ? 'bg-[var(--neon-green)] shadow-[0_0_8px_rgba(0,200,5,0.5)]' : 'bg-[var(--muted-foreground)]'}`} />
          {row.original.name}
        </div>
      ),
    },
    {
      accessorKey: 'algo',
      header: 'Algorithm',
      cell: ({ getValue }) => (
        <span className="text-[var(--muted-foreground)]">{getValue() as string}</span>
      ),
    },
    {
      accessorKey: 'allocationPct',
      header: 'Allocation',
      cell: ({ getValue }) => (
        <span className="text-right block font-mono tabular-nums">{getValue() as number}%</span>
      ),
    },
    {
      accessorKey: 'yield24h',
      header: '24h Yield',
      cell: ({ getValue }) => {
        const v = getValue() as number;
        return (
          <span className={`text-right block font-mono tabular-nums ${v >= 0 ? 'text-[var(--neon-green)]' : 'text-[var(--neon-red)]'}`}>
            {v >= 0 ? '+' : ''}{v.toFixed(2)}%
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
      <CardHeader className="py-4 px-6 border-b border-[var(--border)] flex flex-row items-center justify-between">
        <div>
          <CardTitle className="text-lg text-[var(--kraken-light)]">Strategy Fleet</CardTitle>
          <div className="text-xs text-[var(--muted-foreground)] mt-1 tracking-wide">
            Manage algorithmic agent deployment and allocation.
          </div>
        </div>
        <Button variant="default">+ Deploy New Agent</Button>
      </CardHeader>
      <CardContent className="p-0">
        <table className="w-full text-sm text-left font-mono">
          <thead className="bg-[var(--panel-muted)] border-b border-[var(--border)] text-[var(--muted-foreground)] uppercase text-xs tracking-wider">
            {table.getHeaderGroups().map(hg => (
              <tr key={hg.id}>
                {hg.headers.map(header => {
                  const sorted = header.column.getIsSorted();
                  return (
                    <th
                      key={header.id}
                      className={`p-4 font-medium select-none ${header.column.getCanSort() ? 'cursor-pointer hover:text-[var(--foreground)] transition-colors' : ''}`}
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
                  <td key={cell.id} className="p-4">
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
