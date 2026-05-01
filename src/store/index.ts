import { create } from 'zustand';
import { useEffect, useRef } from 'react';
import { toast } from 'sonner';
import { API_BASE, WS_BASE } from '@/lib/api';

import type {
  AssetClass,
  TickerData,
  TradeLog,
  PositionData,
  WatchlistTA,
  SocketTickPayload,
  AlpacaAccountResponse,
  AlpacaPositionResponse,
  AlpacaOrderResponse,
} from '@/lib/types';

import { INITIAL_WATCHLIST } from '@/lib/static-data';

// Re-export types so existing component imports don't break
export type { TickerData, TradeLog, PositionData };

// ---------------------------------------------------------------------------
// Types
// ---------------------------------------------------------------------------

export interface RiskStatus {
  triggered:           boolean;
  reason:              string | null;
  drawdown_pct:        number;
  max_drawdown_pct:    number;
  start_of_day_equity: number | null;
  min_confidence_gate: number;
  max_position_pct:    number;
  max_position_usd:    number;
  max_kelly_fraction:  number;
}

// ---------------------------------------------------------------------------
// Store Interface
// ---------------------------------------------------------------------------

interface TradingStore {
  assetClass: AssetClass;
  activeSymbol: string;
  accountEquity: number | null;
  /** Today's total P&L (equity − last_equity, realized + unrealized since session open) */
  todayPnl: number | null;
  /** Total unrealized P&L across all open positions from Alpaca account */
  unrealizedPnl: number | null;
  ticker: TickerData | null;
  watchlist: TickerData[];
  recentTrades: TradeLog[];
  positions: PositionData[];
  botLogs: string[];
  marketHistory: any[];
  learningHistory: any[];
  aiInsights: string | null;
  riskStatus: RiskStatus | null;
  ledgerTrades: any[];
  scannerResults: WatchlistTA[];
  strategyStates: Record<string, any[]>;
  bots: any[];
  performance: { history: [number, number][]; net_pnl: number; drawdown: number; has_data: boolean; sharpe: number; sortino: number; realized_trades?: { pnl: number }[] };
  lastSignal: { bot_id: string; action: string; symbol: string; confidence: number; timestamp: string } | null;
  ohlcvData: { candles: { time: number; open: number; high: number; low: number; close: number; volume: number }[]; symbol: string } | null;
  wsStatus: 'connected' | 'reconnecting' | 'offline';

  setAssetClass: (ac: AssetClass) => void;
  setActiveSymbol: (s: string) => void;
  fetchMarketHistory: (s: string) => Promise<void>;
  fetchOHLCV: (symbol: string, period?: string) => Promise<void>;
  fetchRiskStatus: () => Promise<void>;
  fetchPositions: () => Promise<void>;
  fetchLedger: () => Promise<void>;
  injectSocketData: (ticks: Array<{ symbol: string, price: number, volume?: number }>) => void;
  fetchAPIIntegrations: () => Promise<void>;
  fetchStrategyStates: () => Promise<void>;
  fetchReflectionsHistory: () => Promise<void>;
}

// ---------------------------------------------------------------------------
// Store Implementation
// ---------------------------------------------------------------------------

export const useTradingStore = create<TradingStore>((set, get) => ({
  assetClass:    'CRYPTO',
  activeSymbol:  'BTC/USD',
  accountEquity: null,
  todayPnl:      null,
  unrealizedPnl: null,
  ticker:        INITIAL_WATCHLIST[0],
  watchlist:     INITIAL_WATCHLIST,
  recentTrades:  [],
  positions:     [],
  botLogs:       [],
  bots:          [],
  performance:   { history: [], net_pnl: 0, drawdown: 0, has_data: false, sharpe: 0, sortino: 0 },
  lastSignal:    null,
  ohlcvData:     null,
  wsStatus:      'offline',
  marketHistory: [],
  learningHistory: [],
  aiInsights:    null,
  riskStatus:    null,
  ledgerTrades:  [],
  scannerResults: [],
  strategyStates: {},

  setAssetClass:  (ac) => set({ assetClass: ac }),
  setActiveSymbol: (s) => {
    set({
      activeSymbol: s,
      ticker: get().watchlist.find(w => w.symbol === s) ?? null,
    });
    get().fetchMarketHistory(s);
  },

  fetchMarketHistory: async (s: string) => {
    try {
      const encoded = encodeURIComponent(s);
      const res = await fetch(`${API_BASE}/api/market/history?symbol=${encoded}`, {
        signal: AbortSignal.timeout(5000)
      });
      if (res.ok) {
        set({ marketHistory: await res.json() });
      }
    } catch (err) {
      console.error('[ORCHESTRATOR] Error fetching market history', err);
      // Don't retry immediately, let the periodic refresh handle it
    }
  },

  fetchOHLCV: async (symbol: string, period = '1H') => {
    try {
      const encoded = encodeURIComponent(symbol);
      const res = await fetch(
        `${API_BASE}/api/ohlcv?symbol=${encoded}&period=${period}`,
        { signal: AbortSignal.timeout(10_000) },
      );
      if (res.ok) {
        const data = await res.json();
        if (data.candles?.length > 0) {
          set({ ohlcvData: { candles: data.candles, symbol: data.symbol } });
        }
      }
    } catch (err) {
      console.warn('[OHLCV] fetch failed — chart will use synthetic candles', err);
    }
  },

  fetchRiskStatus: async () => {
    try {
      const res = await fetch(`${API_BASE}/api/risk/status`, {
        signal: AbortSignal.timeout(5000),
      });
      if (res.ok) {
        const next = await res.json();
        const prev = get().riskStatus;
        if (next.triggered && !prev?.triggered) {
          toast.error(`Kill Switch Active — ${next.reason ?? 'Trading Halted'}`, { duration: Infinity });
        }
        set({ riskStatus: next });
      }
    } catch {
      // Silent fail — risk status is non-critical for UI
    }
  },

  fetchStrategyStates: async () => {
    try {
      const res = await fetch(`${API_BASE}/api/strategy/states`, {
        signal: AbortSignal.timeout(5000),
      });
      if (res.ok) {
        set({ strategyStates: await res.json() });
      }
    } catch {
      // Silent fail
    }
  },

  // Lightweight refresh — positions, orders, and account only.
  // Called on a 30s polling interval from useTradingEngine.
  fetchPositions: async () => {
    const safeFetch = async <T>(url: string): Promise<T | null> => {
      try {
        const res = await fetch(url, { signal: AbortSignal.timeout(10000) });
        if (!res.ok) return null;
        return await res.json() as T;
      } catch { return null; }
    };

    const [account, posData, ordData] = await Promise.all([
      safeFetch<AlpacaAccountResponse>(`${API_BASE}/api/account`),
      safeFetch<AlpacaPositionResponse[]>(`${API_BASE}/api/positions`),
      safeFetch<AlpacaOrderResponse[]>(`${API_BASE}/api/orders`),
    ]);

    if (account) {
      set({
        accountEquity: parseFloat(account.equity) || null,
        todayPnl:      account.today_pl      ?? null,
        unrealizedPnl: account.unrealized_pl ?? null,
      });
    }

    if (Array.isArray(posData)) {
      const safeParse = (v: string | null | undefined, fallback = 0) =>
        v != null ? (parseFloat(v) || fallback) : fallback;
      const mapped: PositionData[] = posData.map(p => ({
        id:            p.symbol,
        symbol:        p.symbol,
        side:          p.side.toUpperCase() as 'LONG' | 'SHORT',
        size:          safeParse(p.size),
        entryPrice:    safeParse(p.avg_entry_price ?? p.current_price),
        markPrice:     p.current_price != null ? parseFloat(p.current_price) : NaN,
        unrealizedPnl: safeParse(p.unrealized_pnl),
        realizedPnl:   0,
      }));
      set({ positions: mapped });
    }

    if (Array.isArray(ordData)) {
      const mapped: TradeLog[] = ordData.map(o => ({
        id:        o.id,
        timestamp: new Date(o.submitted_at).getTime(),
        side:      o.side.replace('OrderSide.', '').toUpperCase() as 'BUY' | 'SELL',
        price:     parseFloat(o.fill_price ?? '0'),
        size:      parseFloat(o.qty),
        symbol:    o.symbol,
        status:    (o.status === 'filled' ? 'filled' : o.status === 'canceled' ? 'cancelled' : 'pending') as import('@/lib/types').OrderStatus,
      }));
      set({ recentTrades: mapped });
    }
  },

  // Refreshes the execution ledger from DB. Called on 60s interval.
  fetchLedger: async () => {
    try {
      const res = await fetch(`${API_BASE}/api/ledger`, { signal: AbortSignal.timeout(10000) });
      if (res.ok) {
        const ledger = await res.json();
        if (Array.isArray(ledger)) set({ ledgerTrades: ledger });
      }
    } catch { /* silent fail */ }
  },

  // Real-time integration pipe for the Python FastAPI / Alpaca WebSocket bridge.
  // Receives an array of batched ticks from the backend stream and updates the Zustand store once.
  // In production, Alpaca provides precise daily bars; the change24h here is a
  // rough visual approximation until the daily bar feed is wired up (Phase 1).
  injectSocketData: (ticks) => {
    let currentList = get().watchlist;
    let newTicker = get().ticker;
    let isActiveChanged = false;

    // Use a map for O(1) deduplication of multiple ticks for the same symbol in a single batch
    const latestTicks = new Map<string, { symbol: string, price: number, volume?: number }>();
    for (const tick of ticks) {
      latestTicks.set(tick.symbol, tick);
    }

    let watchlistUpdated = false;
    for (const { symbol, price, volume } of latestTicks.values()) {
      const existing = currentList.find(w => w.symbol === symbol);
      if (existing) {
        watchlistUpdated = true;
        const diff       = price - existing.price;
        const changePct  = existing.change24h + (diff / price) * 100;
        const updated    = { ...existing, price, volume: volume ?? existing.volume, change24h: changePct };
        currentList      = currentList.map(item => item.symbol === symbol ? updated : item);

        const isActive = get().activeSymbol === symbol;
        if (isActive) {
          newTicker = { ...existing, price, volume: volume ?? existing.volume };
          isActiveChanged = true;
        }
      }
    }

    if (watchlistUpdated || isActiveChanged) {
      set({
        watchlist: currentList,
        ...(isActiveChanged && { ticker: newTicker }),
      });
    }
  },

  // Polls the FastAPI REST endpoints for account/position/order snapshots.
  // Called once on mount (with a short delay to avoid Next.js hydration races).
  fetchAPIIntegrations: async () => {
    const safeFetchJSON = async <T>(url: string): Promise<T | null> => {
      try {
        const res = await fetch(url, { signal: AbortSignal.timeout(30000) });
        if (!res.ok) return null;
        return await res.json() as T;
      } catch {
        return null;
      }
    };

    // Parallel fetch — fast endpoints only
    const [account, posData, ordData, bots, performance] = await Promise.all([
      safeFetchJSON<AlpacaAccountResponse>(`${API_BASE}/api/account`),
      safeFetchJSON<AlpacaPositionResponse[]>(`${API_BASE}/api/positions`),
      safeFetchJSON<AlpacaOrderResponse[]>(`${API_BASE}/api/orders`),
      safeFetchJSON<any[]>(`${API_BASE}/api/bots`),
      safeFetchJSON<any>(`${API_BASE}/api/performance`)
    ]);

    if (account) {
      set({
        accountEquity: parseFloat(account.equity) || null,
        todayPnl:      account.today_pl      ?? null,
        unrealizedPnl: account.unrealized_pl ?? null,
      });
    }

    if (Array.isArray(posData)) {
      const safeParse = (v: string | null | undefined, fallback = 0) =>
        v != null ? (parseFloat(v) || fallback) : fallback;
      const mapped: PositionData[] = posData.map(p => ({
        id:            p.symbol,
        symbol:        p.symbol,
        side:          p.side.toUpperCase() as 'LONG' | 'SHORT',
        size:          safeParse(p.size),
        entryPrice:    safeParse(p.avg_entry_price ?? p.current_price),
        markPrice:     p.current_price != null ? parseFloat(p.current_price) : NaN,
        unrealizedPnl: safeParse(p.unrealized_pnl),
        realizedPnl:   0,
      }));
      set({ positions: mapped });
    }

    if (Array.isArray(ordData)) {
      const mapped: TradeLog[] = ordData.map(o => ({
        id:        o.id,
        timestamp: new Date(o.submitted_at).getTime(),
        side:      o.side.replace('OrderSide.', '').toUpperCase() as 'BUY' | 'SELL',
        price:     parseFloat(o.fill_price ?? '0'),
        size:      parseFloat(o.qty),
        symbol:    o.symbol,
      }));
      set({ recentTrades: mapped });
    }

    if (Array.isArray(bots) && bots.length > 0) set({ bots });
    if (performance) set({ performance });

    // Risk status + ledger (non-blocking, run in parallel after core data)
    get().fetchRiskStatus();

    try {
      const ledger = await safeFetchJSON<any[]>(`${API_BASE}/api/ledger`);
      if (Array.isArray(ledger) && ledger.length > 0) set({ ledgerTrades: ledger });
    } catch { /* silent fail */ }

    // Strategy states — populates Strategy Mental Model in Brain tab
    get().fetchStrategyStates();

    // Seed Brain tab learning history from persisted reflection logs
    get().fetchReflectionsHistory();

    // Market history is fetched separately — it's the heaviest call
    get().fetchMarketHistory(get().activeSymbol);
  },

  fetchReflectionsHistory: async () => {
    try {
      const res = await fetch(`${API_BASE}/api/reflections/history`, {
        signal: AbortSignal.timeout(8000),
      });
      if (!res.ok) return;
      const rows: Array<{ strategy?: string; symbol?: string; action?: string; insight?: string; timestamp?: string }> =
        await res.json();
      if (!Array.isArray(rows) || rows.length === 0) return;
      const mapped = rows.map(r => ({
        type:      'learning' as const,
        text:      r.insight ?? '',
        strategy:  r.strategy,
        symbol:    r.symbol,
        action:    r.action,
        timestamp: r.timestamp,
      }));
      // Only seed if SSE hasn't already populated learningHistory
      const current = useTradingStore.getState().learningHistory;
      if (current.length === 0) {
        set({ learningHistory: mapped });
      }
    } catch { /* silent fail */ }
  },
}));

// ---------------------------------------------------------------------------
// WebSocket Bridge Hook
// ---------------------------------------------------------------------------

/**
 * Mounts the WebSocket connection to the FastAPI backend stream.
 * Attempts ws://localhost:8000/stream; logs a warning on failure and
 * falls back to the offline data already in the Zustand store.
 * Call this once at the app root (src/app/page.tsx).
 */
const WS_URL = `${WS_BASE}/stream`;
const WS_MAX_ATTEMPTS = 5;
const WS_BASE_DELAY_MS = 2000;

export function useTradingEngine() {
  const wsRef      = useRef<WebSocket | null>(null);
  const attemptsRef = useRef(0);
  const retryTimer  = useRef<ReturnType<typeof setTimeout> | null>(null);

  useEffect(() => {
    let destroyed = false;

    const connect = () => {
      if (destroyed) return;
      console.log('[ORCHESTRATOR] Connecting to Multi-Agent Engine:', WS_URL);
      const ws = new WebSocket(WS_URL);
      wsRef.current = ws;

      ws.onopen = () => {
        attemptsRef.current = 0;
        useTradingStore.setState({ wsStatus: 'connected' });
      };

      let batchedTicks: Array<{ symbol: string, price: number, volume?: number }> = [];
      let batchTimer: ReturnType<typeof setTimeout> | null = null;

      ws.onmessage = (event) => {
        try {
          const payload = JSON.parse(event.data) as SocketTickPayload;
          if (payload.type === 'QUOTE' || payload.type === 'TICK') {
            const { symbol, price, volume } = payload.data;
            batchedTicks.push({ symbol, price, volume });

            if (!batchTimer) {
              batchTimer = setTimeout(() => {
                if (batchedTicks.length > 0) {
                  useTradingStore.getState().injectSocketData(batchedTicks);
                  batchedTicks = [];
                }
                batchTimer = null;
              }, 100); // Batch updates every 100ms
            }
          } else if (payload.type === 'SIGNAL') {
            const d = payload.data as any;
            const log = `[SIGNAL] ${d.bot_id?.toUpperCase()} ${d.action} ${d.symbol} qty=${Number(d.qty).toFixed(6)} conf=${d.confidence}`;
            useTradingStore.setState(s => ({
              botLogs: [...s.botLogs, log].slice(-100),
              lastSignal: d,
            }));
            toast.info(`Signal: ${d.action} ${d.symbol} @ ${Math.round(d.confidence * 100)}%`, { duration: 4000 });
          }
        } catch (err) {
          console.error('[ORCHESTRATOR] WebSocket message parse error', err);
        }
      };

      ws.onerror = () => {
        console.warn('[ORCHESTRATOR] Backend unavailable — running on offline data.');
      };

      ws.onclose = () => {
        if (destroyed) return;
        attemptsRef.current += 1;
        if (attemptsRef.current > WS_MAX_ATTEMPTS) {
          console.warn('[ORCHESTRATOR] WebSocket max reconnect attempts reached.');
          useTradingStore.setState({ wsStatus: 'offline' });
          return;
        }
        useTradingStore.setState({ wsStatus: 'reconnecting' });
        const delay = WS_BASE_DELAY_MS * Math.pow(2, attemptsRef.current - 1);
        console.warn(`[ORCHESTRATOR] WebSocket closed — reconnecting in ${delay}ms (attempt ${attemptsRef.current}/${WS_MAX_ATTEMPTS})`);
        retryTimer.current = setTimeout(connect, delay);
      };
    };

    connect();

    // SSE Endpoint connections
    const reflectionsSSE = new EventSource(`${API_BASE}/api/reflections/stream`);
    reflectionsSSE.onmessage = (event) => {
      try {
        const data = JSON.parse(event.data);
        if (data.heartbeat) return; // ignore heartbeats

        // Set aiInsights: prefer explicit insight field, fall back to text from
        // observe/learn/scanner events (the backend never sends data.insight directly).
        if (data.insight) {
          useTradingStore.setState({ aiInsights: data.insight });
        } else if (data.text && (data.type === 'observe' || data.type === 'learn' || data.type === 'scanner')) {
          useTradingStore.setState({ aiInsights: data.text });
        }

        // Scanner results update the scannerResults store slice
        if (data.type === 'scanner' && Array.isArray(data.results)) {
          useTradingStore.setState({ scannerResults: data.results });
          toast.success(`Scanner: ${data.results.length} picks updated`, { duration: 3000 });
        }

        // All reflection types go to learningHistory (observe, calculate, decision, learning)
        if (data.type) {
          useTradingStore.setState(s => {
            const top = s.learningHistory[0];
            const key = `${data.timestamp}|${data.strategy}|${data.type}`;
            const topKey = top ? `${top.timestamp}|${top.strategy}|${top.type}` : null;
            if (key === topKey) return {};
            return { learningHistory: [data, ...s.learningHistory].slice(0, 100) };
          });
        }
        // Update strategy states from observe events
        if (data.type === 'observe' && data.state) {
          useTradingStore.setState(s => {
            const sym = data.symbol;
            const current = { ...s.strategyStates };
            if (!current[sym]) current[sym] = [];
            const idx = current[sym].findIndex((st: any) => st.strategy === data.strategy);
            if (idx >= 0) {
              current[sym][idx] = data.state;
            } else {
              current[sym].push(data.state);
            }
            return { strategyStates: current };
          });
        }
      } catch (e) {}
    };

    const logsSSE = new EventSource(`${API_BASE}/api/logs/stream`);
    logsSSE.onmessage = (event) => {
      try {
        const data = JSON.parse(event.data);
        if (data.log) {
          useTradingStore.setState(s => ({
            botLogs: [...s.botLogs, data.log].slice(-100) // Keep last 100
          }));
        }
      } catch (e) {}
    };

    // Hydration guard: short delay to avoid Next.js SSR dispatch race
    const timer = setTimeout(() => {
      useTradingStore.getState().fetchAPIIntegrations();
    }, 50);

    // Retry once after 4s in case alpha backend wasn't ready on first mount
    const retry = setTimeout(() => {
      const { bots } = useTradingStore.getState();
      if (!bots || bots.length === 0) {
        useTradingStore.getState().fetchAPIIntegrations();
      }
    }, 4000);

    // Continuous polling — keep positions, orders, and ledger fresh
    const pollPositions = setInterval(() => {
      useTradingStore.getState().fetchPositions();
    }, 30_000); // 30s — strategy states arrive via SSE observe events

    const pollLedger = setInterval(() => {
      useTradingStore.getState().fetchLedger();
    }, 60_000); // 60s — execution ledger from DB

    // Poll bots + performance every 60s so strategy attribution + status stays current
    const pollBots = setInterval(() => {
      Promise.all([
        fetch(`${API_BASE}/api/bots`).then(r => r.ok ? r.json() : null),
        fetch(`${API_BASE}/api/performance`).then(r => r.ok ? r.json() : null),
      ]).then(([bots, perf]) => {
        if (Array.isArray(bots) && bots.length > 0) useTradingStore.setState({ bots });
        if (perf) useTradingStore.setState({ performance: perf });
      }).catch(() => {});
    }, 60_000); // 60s

    const mergeWatchlistFromScan = (d: any[]) => {
      useTradingStore.setState({ scannerResults: d });
      const currentWl = useTradingStore.getState().watchlist;
      const existing = new Set(currentWl.map(t => t.symbol));
      // Update asset_class on entries whose class changed (equity promoted to OPTIONS)
      const updated = currentWl.map(t => {
        const scan = d.find((r: any) => r?.symbol === t.symbol);
        return scan?.asset_class && scan.asset_class !== t.asset_class
          ? { ...t, asset_class: scan.asset_class }
          : t;
      });
      const newEntries = d
        .filter((r: any) => r?.symbol && !existing.has(r.symbol))
        .map((r: any) => ({ symbol: r.symbol, price: r.price ?? 0, change24h: 0, volume: 0, asset_class: r.asset_class }));
      useTradingStore.setState({ watchlist: newEntries.length > 0 ? [...updated, ...newEntries] : updated });
    };

    // Poll watchlist scanner results every 5 min (matches backend scan cadence)
    const pollWatchlist = setInterval(() => {
      fetch(`${API_BASE}/api/watchlist`)
        .then(r => r.ok ? r.json() : null)
        .then(d => { if (Array.isArray(d) && d.length > 0) mergeWatchlistFromScan(d); })
        .catch(() => {});
    }, 300_000); // 5 min

    // Initial scanner load
    fetch(`${API_BASE}/api/watchlist`)
      .then(r => r.ok ? r.json() : null)
      .then(d => { if (Array.isArray(d) && d.length > 0) mergeWatchlistFromScan(d); })
      .catch(() => {});

    return () => {
      destroyed = true;
      clearTimeout(timer);
      clearTimeout(retry);
      clearInterval(pollPositions);
      clearInterval(pollLedger);
      clearInterval(pollBots);
      clearInterval(pollWatchlist);
      if (retryTimer.current) clearTimeout(retryTimer.current);
      wsRef.current?.close();
      reflectionsSSE.close();
      logsSSE.close();
    };
  }, []);
}
