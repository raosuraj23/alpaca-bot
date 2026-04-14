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
      <aside className="w-[260px] hidden xl:block flex-shrink-0">
        <SidebarWatchlist />
      </aside>

      {/* Main Execution Core */}
      <div className="flex-1 flex flex-col gap-2 min-w-0">
        
        {/* Top Split */}
        <div className="flex-1 flex flex-col lg:flex-row gap-2 min-h-[400px]">
          {/* Market & Tape */}
          <section className="flex-1 flex flex-col gap-2 min-w-0">
            <div className="flex-[0.8] min-h-[250px]">
              <MarketOverview />
            </div>
            <div className="flex-[1.2] min-h-[250px]">
              <ExecutionLog />
            </div>
          </section>

          {/* Quant Controls */}
          <section className="flex-[1.5] min-w-[300px]">
            <BotControl />
          </section>

          {/* Streaming Intelligence */}
          <section className="w-[320px] flex flex-col gap-2 flex-shrink-0">
            <div className="flex-1 min-h-[400px]">
              <AiInsights />
            </div>
          </section>
        </div>

        {/* Bottom Split (Positions) */}
        <div className="h-[280px] flex-shrink-0">
          <PositionsTable />
        </div>

      </div>
    </div>
  );
}
