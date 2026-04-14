"use client"

import * as React from 'react';
import { Card, CardHeader, CardTitle, CardContent } from "@/components/ui/card";
import { Badge } from "@/components/ui/badge";
import { BrainCircuit } from "lucide-react";
import { useTradingStore } from '@/hooks/useTradingStream';

export function AiInsights() {
  const insight = useTradingStore(s => s.aiInsights);
  return (
    <Card className="flex flex-col h-full bg-gradient-to-b from-[var(--panel)] to-[#0A0D14]">
      <CardHeader className="py-2.5 px-3 border-b border-[var(--border)] flex flex-row justify-between items-center">
        <div className="flex flex-row items-center space-x-2">
          <BrainCircuit className="w-4 h-4 text-purple-400" />
          <CardTitle className="text-xs uppercase tracking-wider font-semibold text-purple-200/70">AI Insights</CardTitle>
        </div>
        <Badge className="bg-purple-500/20 text-purple-300 border-purple-500/30">Claude 3.5</Badge>
      </CardHeader>
      <CardContent className="flex-1 p-3 overflow-y-auto space-y-4">
        
        <div className="space-y-2">
          <div className="flex items-center space-x-2">
            <div className={`w-2 h-2 rounded-full ${insight ? 'bg-[var(--kraken-purple)]' : 'bg-[var(--neon-green)]'} animate-pulse`} />
            <h4 className="text-sm font-medium text-[var(--foreground)]">{insight ? "Live Intelligence Report" : "Awaiting Analysis"}</h4>
          </div>
          <p className="text-xs text-[var(--muted-foreground)] leading-relaxed min-h-[60px]">
            {insight || "Listening to the data stream. Orchestrator agents are actively observing the market structure and awaiting sufficient data volume..."}
          </p>
        </div>

        {insight && (
          <div className="border border-[var(--border)] rounded-sm p-2 bg-[var(--panel-muted)]">
            <div className="text-xs uppercase font-semibold text-[var(--muted-foreground)] mb-1">Recommendation</div>
            <div className="text-xs text-[var(--foreground)]">
              Agent response generated and logged by system.
            </div>
          </div>
        )}

      </CardContent>
    </Card>
  );
}
