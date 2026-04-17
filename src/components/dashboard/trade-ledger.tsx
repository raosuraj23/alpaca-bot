"use client"

import { API_BASE } from '@/lib/api';
import * as React from 'react';
import { Card, CardHeader, CardTitle, CardContent } from "@/components/ui/card";
import { Badge } from "@/components/ui/badge";
import { Filter, Download, ArrowUpDown, ChevronDown, RefreshCw, TrendingUp, TrendingDown } from 'lucide-react';
import { useTradingStore } from '@/hooks/useTradingStream';

// ---------------------------------------------------------------------------
// Types
// ---------------------------------------------------------------------------

interface ClosedTrade {
  strategy:     string;
  symbol:       string;
  entry_price:  number;
  exit_price:   number;
  pnl_per_unit: number;
  entry_time:   string | null;
  exit_time:    string | null;
  confidence:   number;
}

interface RealizedPnlData {
  trades:         ClosedTrade[];
  open_positions: any[];
  total_closed:   number;
}

interface AccountData {
  equity:            number;
  buying_power:      number;
  cash:              number;
  long_market_value: number;
}

// ---------------------------------------------------------------------------
// KPI Summary Row
// ---------------------------------------------------------------------------

function KpiSummary({ data, ledgerCount }: { data: RealizedPnlData | null; ledgerCount: number }) {
  const closed   = data?.trades ?? [];
  const totalPnl = closed.reduce((s, t) => s + (t.pnl_per_unit ?? 0), 0);
  const winners  = closed.filter(t => (t.pnl_per_unit ?? 0) > 0).length;
  const winRate  = closed.length > 0 ? (winners / closed.length) * 100 : null;
  const avgPnl   = closed.length > 0 ? totalPnl / closed.length : null;
  const isPos    = totalPnl >= 0;

  const kpis = [
    {
      label: 'Realized PnL',
      value: closed.length > 0 ? `${isPos ? '+' : ''}$${totalPnl.toFixed(2)}` : '—',
      color: closed.length > 0
        ? (isPos ? 'text-[var(--neon-green)]' : 'text-[var(--neon-red)]')
        : 'text-[var(--muted-foreground)]',
    },
    {
      label: 'Win Rate',
      value: winRate != null ? `${winRate.toFixed(0)}%` : '—',
      color: winRate != null
        ? (winRate >= 50 ? 'text-[var(--neon-green)]' : 'text-[var(--neon-red)]')
        : 'text-[var(--muted-foreground)]',
    },
    {
      label: 'Avg PnL / Trade',
      value: avgPnl != null ? `${avgPnl >= 0 ? '+' : ''}$${avgPnl.toFixed(4)}` : '—',
      color: avgPnl != null
        ? (avgPnl >= 0 ? 'text-[var(--neon-green)]' : 'text-[var(--neon-red)]')
        : 'text-[var(--muted-foreground)]',
    },
    {
      label: 'Closed Trades',
      value: String(data?.total_closed ?? 0),
      color: 'text-[var(--foreground)]',
    },
    {
      label: 'Exec Records',
      value: String(ledgerCount),
      color: 'text-[var(--foreground)]',
    },
  ];

  return (
    <div className="grid grid-cols-5 divide-x divide-[var(--border)] border-b border-[var(--border)] shrink-0 bg-[var(--panel-muted)]/40">
      {kpis.map(kpi => (
        <div key={kpi.label} className="flex flex-col px-4 py-2.5">
          <span className="text-xs text-[var(--muted-foreground)] uppercase tracking-wider mb-0.5 leading-none">{kpi.label}</span>
          <span className={`text-sm font-mono tabular-nums font-bold leading-snug ${kpi.color}`}>{kpi.value}</span>
        </div>
      ))}
    </div>
  );
}

// ---------------------------------------------------------------------------
// TradeLedger Component
// ---------------------------------------------------------------------------

export function TradeLedger() {
  const ledgerTrades = useTradingStore(s => s.ledgerTrades);
  const fetchLedger  = useTradingStore(s => s.fetchLedger);

  const [realizedData, setRealizedData]   = React.useState<RealizedPnlData | null>(null);
  const [accountData, setAccountData]     = React.useState<AccountData | null>(null);
  const [lastRefresh, setLastRefresh]     = React.useState<Date | null>(null);
  const [refreshing, setRefreshing]       = React.useState(false);
  const [mounted, setMounted]             = React.useState(false);

  React.useEffect(() => { setMounted(true); }, []);

  const loadRealizedPnl = React.useCallback(async () => {
    try {
      const res = await fetch(`${API_BASE}/api/analytics/realized-pnl`, {
        signal: AbortSignal.timeout(10000),
      });
      if (res.ok) {
        const data = await res.json();
        setRealizedData(data);
        setLastRefresh(new Date());
      }
    } catch { /* silent */ }
  }, []);

  const loadAccountData = React.useCallback(async () => {
    try {
      const res = await fetch(`${API_BASE}/api/account`, {
        signal: AbortSignal.timeout(8000),
      });
      if (res.ok) {
        const data = await res.json();
        setAccountData(data);
      }
    } catch { /* silent */ }
  }, []);

  const handleRefresh = async () => {
    setRefreshing(true);
    await Promise.all([fetchLedger(), loadRealizedPnl()]);
    setRefreshing(false);
  };

  // Initial load + 60s auto-refresh
  React.useEffect(() => {
    loadRealizedPnl();
    const interval = setInterval(loadRealizedPnl, 60_000);
    return () => clearInterval(interval);
  }, [loadRealizedPnl]);

  // Account balance — initial load + 60s auto-refresh
  React.useEffect(() => {
    loadAccountData();
    const interval = setInterval(loadAccountData, 60_000);
    return () => clearInterval(interval);
  }, [loadAccountData]);

  // Build a queue of realized trades per bot+symbol, matched FIFO to SELL rows in the ledger.
  // ledgerTrades is ordered newest-first; realized trades are ordered chronologically.
  // We reverse ledger to chronological order, pop realized PnL onto each SELL, then re-sort.
  const realizedPnlByLedgerId = React.useMemo(() => {
    if (!realizedData || realizedData.trades.length === 0) return new Map<number, number>();

    // Build per bot+symbol queues of realized pnl values (chronological order)
    const queues = new Map<string, number[]>();
    [...realizedData.trades]
      .sort((a, b) => (a.exit_time ?? '').localeCompare(b.exit_time ?? ''))
      .forEach(t => {
        const key = `${t.strategy}|${t.symbol}`;
        if (!queues.has(key)) queues.set(key, []);
        queues.get(key)!.push(t.pnl_per_unit);
      });

    // Clone queues so we can pop from them
    const remaining = new Map<string, number[]>();
    queues.forEach((v, k) => remaining.set(k, [...v]));

    // Walk ledger rows oldest-first, assign realized PnL to each SELL row
    const result = new Map<number, number>();
    const chronologicalLedger = [...ledgerTrades].reverse();
    for (const row of chronologicalLedger) {
      if (row.side !== 'SELL') continue;
      const key = `${row.bot}|${row.symbol}`;
      const queue = remaining.get(key);
      if (queue && queue.length > 0) {
        result.set(row.id, queue.shift()!);
      }
    }
    return result;
  }, [realizedData, ledgerTrades]);

  if (!mounted) return null;

  return (
    <Card className="h-full flex flex-col bg-[var(--panel)] overflow-hidden">

      {/* Ledger Toolbar */}
      <CardHeader className="py-3 px-4 border-b border-[var(--border)] flex flex-row items-center justify-between bg-gradient-to-b from-[var(--kraken-purple)]/5 to-transparent flex-shrink-0">
        <div className="flex items-center space-x-3">
          <CardTitle className="text-sm font-bold tracking-wide">Master Execution Ledger</CardTitle>
          <Badge variant="outline" className="px-2">{ledgerTrades.length} RECORDS</Badge>
        </div>

        <div className="flex items-center space-x-2">
          {['Asset Class', 'Automated Agent', 'Timeframe', 'Outcome'].map((filter) => (
            <button key={filter} className="hidden lg:flex items-center px-3 py-1.5 bg-[var(--background)] border border-[var(--border)] rounded-sm text-xs text-[var(--muted-foreground)] hover:text-[var(--foreground)] transition-colors">
              {filter} <ChevronDown className="w-3 h-3 ml-1.5 opacity-60" />
            </button>
          ))}
          {lastRefresh && (
            <span className="hidden lg:block text-xs font-mono tabular-nums text-[var(--muted-foreground)] opacity-40">
              {lastRefresh.toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' })}
            </span>
          )}
          <button
            onClick={handleRefresh}
            disabled={refreshing}
            className="p-1.5 bg-[var(--panel-muted)] border border-[var(--border)] rounded-sm hover:bg-[var(--background)] transition-colors text-[var(--muted-foreground)] disabled:opacity-40"
          >
            <RefreshCw className={`w-3.5 h-3.5 ${refreshing ? 'animate-spin' : ''}`} />
          </button>
          <button className="p-1.5 bg-[var(--kraken-purple)] text-white rounded-sm hover:bg-[var(--kraken-light)] transition-colors ml-1 shadow-[0_0_10px_rgba(139,92,246,0.3)]">
            <Filter className="w-4 h-4" />
          </button>
          <button className="p-1.5 bg-[var(--panel-muted)] border border-[var(--border)] rounded-sm hover:bg-[var(--background)] transition-colors text-[var(--muted-foreground)]">
            <Download className="w-4 h-4" />
          </button>
        </div>
      </CardHeader>

      {/* Account Balance Strip */}
      <div className="grid grid-cols-4 divide-x divide-[var(--border)] border-b border-[var(--border)] shrink-0 bg-[var(--panel-muted)]/20">
        {[
          { label: 'Equity',        value: accountData?.equity,            color: 'text-[var(--foreground)]' },
          { label: 'Buying Power',  value: accountData?.buying_power,      color: 'text-[var(--foreground)]' },
          { label: 'Cash',          value: accountData?.cash,              color: 'text-[var(--foreground)]' },
          { label: 'Long Mkt Val',  value: accountData?.long_market_value, color: 'text-[var(--neon-green)]' },
        ].map(({ label, value, color }) => (
          <div key={label} className="flex flex-col px-4 py-2">
            <span className="text-xs text-[var(--muted-foreground)] uppercase tracking-wider mb-0.5 leading-none">{label}</span>
            <span className={`text-sm font-mono tabular-nums font-bold leading-snug ${color}`}>
              {value != null ? `$${Number(value).toLocaleString('en-US', { minimumFractionDigits: 2, maximumFractionDigits: 2 })}` : '—'}
            </span>
          </div>
        ))}
      </div>

      {/* KPI Summary */}
      <KpiSummary data={realizedData} ledgerCount={ledgerTrades.length} />

      {/* Ledger Table */}
      <CardContent className="flex-1 overflow-auto p-0">
        <table className="w-full text-xs text-left tabular-nums font-mono whitespace-nowrap">
          <thead className="sticky top-0 bg-[var(--panel-muted)] border-b border-[var(--border)] text-[var(--muted-foreground)] shadow-sm z-10">
            <tr>
              <th className="font-semibold p-3 pl-4 cursor-pointer hover:text-[var(--foreground)]">
                <span className="flex items-center">Ticket ID <ArrowUpDown className="w-3 h-3 ml-1" /></span>
              </th>
              <th className="font-semibold p-3 cursor-pointer hover:text-[var(--foreground)]">Timestamp</th>
              <th className="font-semibold p-3 cursor-pointer hover:text-[var(--foreground)]">Symbol</th>
              <th className="font-semibold p-3 text-center">Direction</th>
              <th className="font-semibold p-3 text-center hidden md:table-cell">Origin Agent</th>
              <th className="font-semibold p-3 text-right hidden xl:table-cell">Signal Conf.</th>
              <th className="font-semibold p-3 text-right hidden lg:table-cell">Slippage</th>
              <th className="font-semibold p-3 text-right">Fill Price</th>
              <th className="font-semibold p-3 pr-4 text-right font-bold text-[var(--kraken-light)]">Realized PnL</th>
            </tr>
          </thead>
          <tbody className="divide-y divide-[var(--border)]/30">
            {ledgerTrades.length === 0 ? (
              <tr>
                <td colSpan={9} className="p-6 text-center text-[var(--muted-foreground)]">
                  No execution records yet
                </td>
              </tr>
            ) : ledgerTrades.map((r: any) => {
              // Enrich SELL rows with matched realized pnl (FIFO-matched by bot+symbol)
              const realPnl = r.side === 'SELL' ? (realizedPnlByLedgerId.get(r.id) ?? null) : null;

              return (
                <tr key={r.id} className="hover:bg-[var(--panel-muted)] transition-colors cursor-default">
                  <td className="p-3 pl-4 text-[var(--muted-foreground)]">
                    {r.order_id ? r.order_id.slice(0, 8) + '…' : String(r.id)}
                  </td>
                  <td className="p-3 text-[var(--foreground)]">
                    {r.timestamp ? new Date(r.timestamp).toLocaleString() : '—'}
                  </td>
                  <td className="p-3 font-bold text-[var(--foreground)]">{r.symbol ?? '—'}</td>
                  <td className="p-3 text-center">
                    <Badge
                      variant={r.side === 'BUY' ? 'success' : 'destructive'}
                      className="text-xs px-1.5 uppercase font-sans tracking-widest"
                    >
                      {r.side ?? '—'}
                    </Badge>
                  </td>
                  <td className="p-3 text-center hidden md:table-cell">
                    <Badge variant="outline" className="font-sans font-normal opacity-80">
                      {r.bot ?? '—'}
                    </Badge>
                  </td>
                  <td className="p-3 text-right text-[var(--kraken-light)] hidden xl:table-cell">
                    {r.confidence != null ? `${(r.confidence * 100).toFixed(0)}%` : '—'}
                  </td>
                  <td className="p-3 text-right hidden lg:table-cell">
                    {r.slippage_bps != null
                      ? <span className="text-[var(--neon-red)]">{r.slippage_bps.toFixed(1)} bps</span>
                      : <span className="text-[var(--muted-foreground)]">—</span>}
                  </td>
                  <td className="p-3 text-right font-bold text-[var(--foreground)]">
                    {r.fill_price != null ? `$${Number(r.fill_price).toFixed(2)}` : '—'}
                  </td>
                  <td className="p-3 pr-4 text-right font-bold">
                    {realPnl != null ? (
                      <span className={`flex items-center justify-end gap-0.5 ${realPnl >= 0 ? 'text-[var(--neon-green)]' : 'text-[var(--neon-red)]'}`}>
                        {realPnl >= 0
                          ? <TrendingUp className="w-3 h-3 shrink-0" />
                          : <TrendingDown className="w-3 h-3 shrink-0" />
                        }
                        {realPnl >= 0 ? '+' : ''}${realPnl.toFixed(4)}
                      </span>
                    ) : (
                      <span className="text-[var(--muted-foreground)] opacity-40">
                        {r.side === 'BUY' ? 'open' : '—'}
                      </span>
                    )}
                  </td>
                </tr>
              );
            })}
          </tbody>
        </table>
      </CardContent>
    </Card>
  );
}
