"use client"

import * as React from 'react';
import { useTradingStore } from '@/store';
import { ShieldAlert } from 'lucide-react';

export function MiniKPIStrip() {
  const accountEquity = useTradingStore(s => s.accountEquity);
  const todayPnl      = useTradingStore(s => s.todayPnl);
  const riskStatus    = useTradingStore(s => s.riskStatus);

  const drawdownPct = riskStatus?.drawdown_pct ?? 0;
  const killActive  = riskStatus?.triggered ?? false;

  return (
    <div className="hidden lg:flex items-center gap-4 text-xs font-mono tabular-nums border-l border-[var(--border)] pl-4 ml-2">
      <KPISlot label="Equity">
        {accountEquity !== null
          ? `$${accountEquity.toLocaleString(undefined, { minimumFractionDigits: 0, maximumFractionDigits: 0 })}`
          : <span className="opacity-40">—</span>
        }
      </KPISlot>

      <KPISlot label="Day P&L">
        {todayPnl !== null ? (
          <span className={todayPnl >= 0 ? 'text-[var(--neon-green)]' : 'text-[var(--neon-red)]'}>
            {todayPnl >= 0 ? '+' : ''}${todayPnl.toLocaleString(undefined, { minimumFractionDigits: 2, maximumFractionDigits: 2 })}
          </span>
        ) : <span className="opacity-40">—</span>}
      </KPISlot>

      <KPISlot label="Drawdown" title="Daily drawdown: (start-of-day equity − current equity) / start-of-day equity. Kill switch fires at the 2% limit.">
        {riskStatus != null ? (
          <span className={drawdownPct >= 1.5 ? 'text-[var(--neon-red)]' : drawdownPct >= 0.5 ? 'text-[var(--agent-learning)]' : 'text-[var(--foreground)]'}>
            {drawdownPct.toFixed(2)}%
          </span>
        ) : <span className="opacity-40">—</span>}
      </KPISlot>

      {killActive && (
        <div className="flex items-center gap-1 px-2 py-0.5 bg-[var(--neon-red)]/10 border border-[var(--neon-red)]/40 rounded-sm text-[var(--neon-red)] animate-pulse">
          <ShieldAlert className="w-3 h-3 shrink-0" />
          <span className="uppercase tracking-widest text-xs font-bold">Kill Switch</span>
        </div>
      )}
    </div>
  );
}

function KPISlot({ label, children, title }: { label: string; children: React.ReactNode; title?: string }) {
  return (
    <div className="flex flex-col items-end leading-none gap-0.5" title={title}>
      <span className="text-[var(--muted-foreground)] uppercase tracking-widest text-xs">{label}</span>
      <span className="text-[var(--foreground)] font-bold">{children}</span>
    </div>
  );
}
