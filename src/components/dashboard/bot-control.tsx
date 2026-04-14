"use client"

import * as React from 'react';
import { Card, CardHeader, CardTitle, CardContent } from "@/components/ui/card";
import { Badge } from "@/components/ui/badge";
import { useTradingStore } from '@/hooks/useTradingStream';

export function BotControl() {
  const logs = useTradingStore(s => s.botLogs);
  const bots = useTradingStore(s => s.bots);

  const primaryBot = bots.length > 0 ? bots[0] : null;

  return (
    <Card className="flex flex-col h-full">
      <CardHeader className="py-2.5 px-3 flex flex-row items-center justify-between border-b border-[var(--border)]">
        <CardTitle className="text-xs uppercase tracking-wider font-semibold text-[var(--muted-foreground)]">Bot Control</CardTitle>
        <Badge variant={primaryBot?.status === 'ACTIVE' ? "success" : "outline"}>{primaryBot?.status || 'AWAITING'}</Badge>
      </CardHeader>
      
      <CardContent className="p-0 flex flex-col flex-1">
        {/* Strategy Parameters */}
        <div className="p-3 border-b border-[var(--border)] grid grid-cols-2 gap-4 bg-[var(--panel-muted)]/50">
          <div>
            <div className="text-xs text-[var(--muted-foreground)] uppercase tracking-wider mb-1">Strategy</div>
            <div className="text-sm font-medium">{primaryBot?.name || 'Loading Agents...'}</div>
          </div>
          <div>
            <div className="text-xs text-[var(--muted-foreground)] uppercase tracking-wider mb-1">Status</div>
            <div className={`text-sm font-medium ${primaryBot?.status === 'ACTIVE' ? 'text-[var(--neon-green)]' : 'text-[var(--muted-foreground)]'}`}>
               {primaryBot?.status === 'ACTIVE' ? 'Tracking' : 'Idle'}
            </div>
          </div>
        </div>

        {/* Console Logs */}
        <div className="flex-1 p-3 bg-[#050505] overflow-y-auto font-mono text-xs sm:text-xs leading-relaxed space-y-1">
          {logs.length === 0 && (
            <div className="text-[var(--muted-foreground)] opacity-40 text-xs">[SYSTEM] Awaiting first bar data from Alpaca stream...</div>
          )}
          {logs.map((log, i) => {
            const color = log.includes('[SYSTEM]') || log.includes('[STREAM]') ? 'text-blue-400'
              : log.includes('[EXECUTION]') || log.includes('FILLED') ? 'text-[var(--neon-green)]'
              : log.includes('[RISK AGENT] ✓') ? 'text-emerald-400'
              : log.includes('[RISK AGENT] ✗') || log.includes('Blocked') ? 'text-[var(--neon-red)]'
              : log.includes('[HEARTBEAT]') ? 'text-[var(--muted-foreground)] opacity-30'
              : 'text-[var(--muted-foreground)]';
            const now = new Date();
            const ts = `${String(now.getHours()).padStart(2,'0')}:${String(now.getMinutes()).padStart(2,'0')}:${String(now.getSeconds()).padStart(2,'0')}`;
            return (
              <div key={i} className={color}>
                <span className="opacity-40 select-none mr-2">{ts}</span>
                {log}
              </div>
            );
          })}
          <div className="animate-pulse text-[var(--muted-foreground)] opacity-30 mt-1">█</div>
        </div>
      </CardContent>
    </Card>
  );
}
