"use client"

import * as React from 'react';
import { Card, CardHeader, CardTitle, CardContent } from "@/components/ui/card";
import { Badge } from "@/components/ui/badge";
import { BrainCircuit } from "lucide-react";
import { useTradingStore } from '@/hooks/useTradingStream';

const TYPE_LABELS: Record<string, string> = {
  observe:  'OBSERVE',
  learn:    'LEARN',
  scanner:  'SCAN',
  position: 'POSITION',
  decision: 'DECISION',
};

export function AiInsights() {
  const insight         = useTradingStore(s => s.aiInsights);
  const learningHistory = useTradingStore(s => s.learningHistory);
  const scannerResults  = useTradingStore(s => s.scannerResults);

  const recentEvents = learningHistory.slice(0, 5);
  const topScan      = scannerResults[0] ?? null;

  return (
    <Card className="flex flex-col h-full bg-gradient-to-b from-[var(--panel)] to-[#0A0D14]">
      <CardHeader className="py-2.5 px-3 border-b border-[var(--border)] flex flex-row justify-between items-center">
        <div className="flex flex-row items-center space-x-2">
          <BrainCircuit className="w-4 h-4 text-purple-400" />
          <CardTitle className="text-xs uppercase tracking-wider font-semibold text-purple-200/70">AI Insights</CardTitle>
        </div>
        <div className="flex items-center gap-2">
          {recentEvents.length > 0 && (
            <span className="w-1.5 h-1.5 rounded-full bg-[var(--neon-green)] animate-pulse" />
          )}
          <Badge className="bg-purple-500/20 text-purple-300 border-purple-500/30">Claude 3.5</Badge>
        </div>
      </CardHeader>

      <CardContent className="flex-1 p-3 overflow-y-auto space-y-3">

        {/* Latest insight text — set from observe/learn SSE events */}
        <div className="space-y-1.5">
          <div className="flex items-center space-x-2">
            <div className={`w-2 h-2 rounded-full ${insight ? 'bg-[var(--kraken-purple)]' : 'bg-[var(--panel-muted)]'} animate-pulse`} />
            <h4 className="text-xs font-semibold uppercase tracking-wider text-[var(--foreground)]">
              {insight ? 'Live Intelligence' : 'Awaiting Analysis'}
            </h4>
          </div>
          <p className="text-xs text-[var(--muted-foreground)] leading-relaxed min-h-[40px]">
            {insight ?? 'Listening to the data stream. Reflection engine warms up after 15s...'}
          </p>
        </div>

        {/* Top scanner pick */}
        {topScan && (
          <div className="border border-[var(--border)] rounded-sm p-2 bg-[var(--panel-muted)]">
            <div className="flex items-center justify-between mb-1">
              <span className="text-xs uppercase font-semibold text-[var(--muted-foreground)]">Top Scan Pick</span>
              <Badge
                variant={topScan.signal === 'BUY' ? 'success' : topScan.signal === 'SELL' ? 'destructive' : 'outline'}
                className="text-xs px-1.5"
              >
                {topScan.signal}
              </Badge>
            </div>
            <div className="text-xs font-bold text-[var(--foreground)] mb-0.5">{topScan.symbol}</div>
            <div className="text-xs text-[var(--muted-foreground)]">{topScan.verdict ?? '—'}</div>
          </div>
        )}

        {/* Live reflection feed */}
        {recentEvents.length > 0 && (
          <div className="space-y-1">
            <div className="text-xs uppercase font-semibold text-[var(--muted-foreground)] tracking-wider">Reflection Feed</div>
            {recentEvents.map((ev: any, i: number) => (
              <div key={i} className="border-l-2 border-[var(--kraken-purple)]/40 pl-2 py-0.5">
                <div className="flex items-center gap-1.5 mb-0.5">
                  <Badge variant="outline" className="text-xs px-1 py-0 font-mono">
                    {TYPE_LABELS[ev.type] ?? ev.type?.toUpperCase() ?? 'EVENT'}
                  </Badge>
                  {ev.strategy && (
                    <span className="text-xs text-[var(--kraken-light)] font-mono">{ev.strategy}</span>
                  )}
                  {ev.symbol && (
                    <span className="text-xs text-[var(--muted-foreground)] font-mono">{ev.symbol}</span>
                  )}
                </div>
                <p className="text-xs text-[var(--muted-foreground)] leading-snug line-clamp-2">
                  {ev.text ?? '—'}
                </p>
              </div>
            ))}
          </div>
        )}

      </CardContent>
    </Card>
  );
}
