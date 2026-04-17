"use client"

import * as React from 'react';
import { useTradingEngine, useTradingStore } from '@/hooks/useTradingStream';
import { Activity, LayoutDashboard, BarChart3, LineChart, Cpu, History, BrainCircuit, BookOpen } from 'lucide-react';
import { motion, AnimatePresence } from 'framer-motion';

// Views
import { TradingDesk } from '@/components/dashboard/trading-desk';
import { PerformanceMetrics } from '@/components/dashboard/performance-metrics';
import { QuantStrategies } from '@/components/dashboard/strategy-grid';
import { BacktestRunner } from '@/components/dashboard/backtest-runner';
import { BotReflections } from '@/components/dashboard/bot-reflections';
import { OrchestratorChat } from '@/components/dashboard/orchestrator-chat';
import { TradeLedger } from '@/components/dashboard/trade-ledger';

function SystemClock() {
  const [mounted, setMounted] = React.useState(false);
  const [time, setTime] = React.useState<Date | null>(null);

  React.useEffect(() => {
    setMounted(true);
    setTime(new Date());
    const timer = setInterval(() => setTime(new Date()), 1000);
    return () => clearInterval(timer);
  }, []);

  if (!mounted || !time) {
    // Render a fixed-width placeholder so layout doesn't shift on mount
    return (
      <div className="flex flex-col items-end px-4 border-l border-[var(--border)] ml-2">
        <span className="text-xs text-[var(--kraken-light)] font-mono font-bold leading-none opacity-0">00:00:00</span>
        <span className="text-xs text-[var(--muted-foreground)] uppercase tracking-widest mt-0.5 opacity-0">Jan 1, 2024</span>
      </div>
    );
  }

  return (
    <div className="flex flex-col items-end px-4 border-l border-[var(--border)] ml-2">
      <span className="text-xs text-[var(--kraken-light)] font-mono font-bold leading-none">
        {time.toLocaleTimeString('en-US', { hour12: false })}
      </span>
      <span className="text-xs text-[var(--muted-foreground)] uppercase tracking-widest mt-0.5">
        {time.toLocaleDateString('en-US', { month: 'short', day: 'numeric', year: 'numeric' })}
      </span>
    </div>
  );
}
type TabView = 'DESK' | 'PERFORMANCE' | 'STRATEGIES' | 'BACKTEST' | 'LEDGER' | 'REFLECTIONS';

export default function AppShell() {
  const [activeTab, setActiveTab] = React.useState<TabView>('DESK');
  const { assetClass, setAssetClass, activeSymbol, accountEquity } = useTradingStore();
  
  // Mount the simulation WebSocket engine globally
  useTradingEngine();

  const renderView = () => {
    switch(activeTab) {
      case 'DESK': return <TradingDesk />;
      case 'PERFORMANCE': return <PerformanceMetrics />;
      case 'STRATEGIES': return <QuantStrategies />;
      case 'BACKTEST': return <BacktestRunner />;
      case 'LEDGER': return <TradeLedger />;
      case 'REFLECTIONS': return <BotReflections />;
      default: return <TradingDesk />;
    }
  };

  return (
    <div className="flex flex-col h-screen overflow-hidden bg-[var(--background)] text-[var(--foreground)] selection:bg-[var(--kraken-purple)] selection:text-white font-sans">
      
      {/* Top Header */}
      <header className="h-14 border-b border-[var(--border)] bg-[var(--panel)] flex items-center px-4 justify-between shrink-0 shadow-md relative z-20">
        <div className="flex items-center space-x-3">
          <div className="w-6 h-6 bg-[var(--kraken-purple)] rounded-sm flex items-center justify-center shadow-[0_0_10px_rgba(139,92,246,0.6)]">
            <Activity className="w-4 h-4 text-white" strokeWidth={2.5} />
          </div>
          <span className="font-bold tracking-tight text-md text-[var(--kraken-light)] mr-2">ALPACA X</span>

          {/* Asset Class Selector Toggle */}
          <div className="flex bg-[var(--background)] border border-[var(--border)] rounded-sm p-1 mx-2">
            {(['EQUITY', 'OPTIONS', 'CRYPTO'] as const).map(ac => (
               <button
                 key={ac}
                 onClick={() => setAssetClass(ac)}
                 className={`px-3 py-1 text-xs font-bold rounded-sm tracking-wider transition-colors ${assetClass === ac ? 'bg-[var(--panel-muted)] text-[var(--kraken-light)] shadow-sm' : 'text-[var(--muted-foreground)] hover:text-white'}`}
               >
                 {ac}
               </button>
            ))}
          </div>
          
          <div className="h-4 w-px bg-[var(--border)] mx-1" />
          
          {/* Tab Navigation with Scroll Wrap to Prevent Squishing */}
          <nav className="flex space-x-1 lg:space-x-2 overflow-x-auto scrollbar-hide py-1">
             <TabButton active={activeTab === 'DESK'} onClick={() => setActiveTab('DESK')} icon={<LayoutDashboard />}>Desk</TabButton>
             <TabButton active={activeTab === 'PERFORMANCE'} onClick={() => setActiveTab('PERFORMANCE')} icon={<LineChart />}>Analysis</TabButton>
             <TabButton active={activeTab === 'STRATEGIES'} onClick={() => setActiveTab('STRATEGIES')} icon={<Cpu />}>Bots</TabButton>
             <TabButton active={activeTab === 'BACKTEST'} onClick={() => setActiveTab('BACKTEST')} icon={<History />}>Tests</TabButton>
             <TabButton active={activeTab === 'LEDGER'} onClick={() => setActiveTab('LEDGER')} icon={<BookOpen />}>Ledger</TabButton>
             <TabButton active={activeTab === 'REFLECTIONS'} onClick={() => setActiveTab('REFLECTIONS')} icon={<BrainCircuit />}>Brain</TabButton>
          </nav>
        </div>

        {/* Global Stats KPIs */}
        <div className="flex space-x-6 text-xs font-mono font-medium items-center">
          <div className="hidden lg:flex items-center space-x-1 border border-[var(--border)] bg-[var(--panel-muted)] px-3 py-1.5 rounded-sm">
            <span className="text-[var(--muted-foreground)] uppercase mr-1">Active:</span>
            <span className="text-[var(--foreground)]">{activeSymbol}</span>
          </div>

          <div className="flex items-center gap-1.5">
            <div className="w-1.5 h-1.5 rounded-sm bg-[var(--neon-green)] animate-live" />
            <span className="text-[var(--neon-green)] font-bold text-xs tracking-widest">LIVE</span>
          </div>

          <div className="flex flex-col items-end border-l border-[var(--border)] pl-4 ml-1">
            <span className="text-xs text-[var(--muted-foreground)] uppercase tracking-widest leading-none mb-0.5">Total Equity</span>
            <span className="text-sm font-mono tabular-nums font-bold text-[var(--foreground)] leading-none">
              {accountEquity !== null
                ? `$${accountEquity.toLocaleString(undefined, { minimumFractionDigits: 2, maximumFractionDigits: 2 })}`
                : <span className="text-[var(--muted-foreground)] opacity-50 text-xs">SYNCING...</span>
              }
            </span>
          </div>

          <SystemClock />
        </div>
      </header>

      {/* Main Viewport Container */}
      <main className="flex-1 overflow-hidden relative p-4">
        <AnimatePresence mode="wait">
          <motion.div
            key={activeTab}
            initial={{ opacity: 0, y: 5 }}
            animate={{ opacity: 1, y: 0 }}
            exit={{ opacity: 0, y: -5 }}
            transition={{ duration: 0.15, ease: "easeOut" }}
            className="h-full"
          >
            {renderView()}
          </motion.div>
        </AnimatePresence>
      </main>
      <OrchestratorChat />
    </div>
  );
}

function TabButton({ active, onClick, children, icon }: { active: boolean, onClick: () => void, children: React.ReactNode, icon: React.ReactNode }) {
  return (
    <button
      onClick={onClick}
      className={`relative px-3 py-1.5 text-xs font-semibold tracking-wider uppercase transition-colors flex items-center gap-1.5 rounded-sm
        ${active
          ? 'text-[var(--kraken-light)] bg-[var(--kraken-purple)]/10'
          : 'text-[var(--muted-foreground)] hover:text-[var(--foreground)] hover:bg-[var(--panel-muted)]'
        }
      `}
    >
      <span className="w-3 h-3 shrink-0 opacity-75">{icon}</span>
      <span>{children}</span>
      {active && (
        <motion.div
          layoutId="activeTabUnderline"
          className="absolute bottom-0 left-2 right-2 h-px bg-[var(--kraken-purple)] shadow-[0_0_6px_rgba(139,92,246,0.9)]"
        />
      )}
    </button>
  );
}
