"use client"

import * as React from 'react';
import { MarketOverview } from '@/components/dashboard/market-overview';
import { ExecutionLog } from '@/components/dashboard/execution-log';
import { BotControl } from '@/components/dashboard/bot-control';
import { AiInsights } from '@/components/dashboard/ai-insights';
import { SidebarWatchlist } from '@/components/dashboard/sidebar-watchlist';
import { PositionsTable } from '@/components/dashboard/positions-table';

export function TradingDesk() {
  return (
    <div className="flex h-full gap-2 min-h-0">

      {/* Sidebar Navigation */}
      <aside className="w-[260px] hidden xl:flex flex-col flex-shrink-0">
        <SidebarWatchlist />
      </aside>

      {/* Main Execution Core */}
      <div className="flex-1 flex flex-col gap-2 min-w-0 min-h-0">

        {/* Top row — 3 columns */}
        <div className="flex-1 flex flex-col lg:flex-row gap-2 min-h-0">

          {/* Market & Tape */}
          <section className="flex-1 flex flex-col gap-2 min-w-0 min-h-0">
            <div className="flex-[0.7] min-h-0">
              <MarketOverview />
            </div>
            <div className="flex-[0.6] min-h-0">
              <ExecutionLog />
            </div>
          </section>

          {/* Quant Controls */}
          <section className="flex-[1] min-w-[300px] min-h-0">
            <BotControl />
          </section>

          {/* Streaming Intelligence */}
          <section className="w-[380px] flex-shrink-0 min-h-0">
            <AiInsights />
          </section>

        </div>

        {/* Bottom strip — Positions / Orders / Risk */}
        <div className="h-[340px] shrink-0">
          <PositionsTable />
        </div>

      </div>
    </div>
  );
}
