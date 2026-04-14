"use client"

import * as React from 'react';
import { Card, CardHeader, CardTitle, CardContent } from "@/components/ui/card";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { useTradingStore } from '@/hooks/useTradingStream';

export function QuantStrategies() {
   const bots = useTradingStore(s => s.bots);
  return (
    <Card className="flex flex-col h-full bg-[var(--panel)]/50">
      <CardHeader className="py-4 px-6 border-b border-[var(--border)] flex flex-row items-center justify-between">
        <div>
          <CardTitle className="text-lg text-[var(--kraken-light)]">Strategy Fleet</CardTitle>
          <div className="text-xs text-[var(--muted-foreground)] mt-1 tracking-wide">Manage algorithmic agent deployment and allocation.</div>
        </div>
        <Button variant="default">+ Deploy New Agent</Button>
      </CardHeader>
      <CardContent className="p-0">
        <table className="w-full text-sm text-left">
          <thead className="bg-[var(--panel-muted)] border-b border-[var(--border)] text-[var(--muted-foreground)] uppercase text-xs tracking-wider">
            <tr>
              <th className="p-4 font-medium">Agent</th>
              <th className="p-4 font-medium">Algorithm</th>
              <th className="p-4 font-medium text-right">Allocation</th>
              <th className="p-4 font-medium text-right">24h Yield</th>
              <th className="p-4 font-medium text-center">Status</th>
              <th className="p-4 font-medium text-right">Actions</th>
            </tr>
          </thead>
          <tbody className="divide-y divide-[var(--border)]/50">
            {bots.map(bot => (
              <tr key={bot.id} className="hover:bg-[var(--panel-muted)]/30 transition-colors">
                <td className="p-4 font-medium text-[var(--foreground)]">
                  <div className="flex items-center gap-3">
                    <div className={`w-2 h-2 rounded-full ${bot.status === 'ACTIVE' ? 'bg-[var(--neon-green)] shadow-[0_0_8px_rgba(0,200,5,0.5)]' : 'bg-[var(--muted-foreground)]'}`} />
                    {bot.name}
                  </div>
                </td>
                <td className="p-4 text-[var(--muted-foreground)]">{bot.algo}</td>
                <td className="p-4 text-right font-mono tabular-nums">{bot.allocationPct}%</td>
                <td className={`p-4 text-right font-mono tabular-nums ${bot.yield24h >= 0 ? 'text-[var(--neon-green)]' : 'text-[var(--neon-red)]'}`}>
                  {bot.yield24h >= 0 ? '+' : ''}{bot.yield24h.toFixed(2)}%
                </td>
                <td className="p-4 text-center">
                  <Badge variant={bot.status === 'ACTIVE' ? 'success' : bot.status === 'HALTED' ? 'destructive' : 'outline'}>
                    {bot.status}
                  </Badge>
                </td>
                <td className="p-4 text-right">
                  <Button variant="outline" size="sm" className="mr-2">Config</Button>
                  <Button variant={bot.status === 'ACTIVE' ? 'destructive' : 'success'} size="sm">
                    {bot.status === 'ACTIVE' ? 'Halt' : 'Boot'}
                  </Button>
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </CardContent>
    </Card>
  );
}
