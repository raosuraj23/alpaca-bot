import { create } from 'zustand';
import { useEffect, useRef } from 'react';

import type {
  AssetClass,
  TickerData,
  TradeLog,
  PositionData,
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
  strategyStates: Record<string, any[]>;

  setAssetClass: (ac: AssetClass) => void;
  setActiveSymbol: (s: string) => void;
  fetchMarketHistory: (s: string) => Promise<void>;
  fetchRiskStatus: () => Promise<void>;
  injectSocketData: (symbol: string, price: number, volume?: number) => void;
  fetchAPIIntegrations: () => Promise<void>;
  fetchStrategyStates: () => Promise<void>;
}

// ---------------------------------------------------------------------------
// Store Implementation
// ---------------------------------------------------------------------------

export const useTradingStore = create<TradingStore>((set, get) => ({
  assetClass:    'CRYPTO',
  activeSymbol:  'BTC/USD',
  accountEquity: null,
  ticker:        INITIAL_WATCHLIST[0],
  watchlist:     INITIAL_WATCHLIST,
  recentTrades:  [],
  positions:     [],
  botLogs:       [],
  bots:          [],
  performance:   { history: [], net_pnl: 0, drawdown: 0, has_data: false },
  marketHistory: [],
  learningHistory: [],
  aiInsights:    null,
  riskStatus:    null,
  ledgerTrades:  [],
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
      const res = await fetch(`http://localhost:8000/api/market/history?symbol=${encoded}`);
      if (res.ok) {
        set({ marketHistory: await res.json() });
      }
    } catch (err) {
      console.error('[ORCHESTRATOR] Error fetching market history', err);
    }
  },

  fetchRiskStatus: async () => {
    try {
      const res = await fetch('http://localhost:8000/api/risk/status', {
        signal: AbortSignal.timeout(5000),
      });
      if (res.ok) {
        set({ riskStatus: await res.json() });
      }
    } catch {
      // Silent fail — risk status is non-critical for UI
    }
  },

  fetchStrategyStates: async () => {
    try {
      const res = await fetch('http://localhost:8000/api/strategy/states', {
        signal: AbortSignal.timeout(5000),
      });
      if (res.ok) {
        set({ strategyStates: await res.json() });
      }
    } catch {
      // Silent fail
    }
  },

  // Real-time integration pipe for the Python FastAPI / Alpaca WebSocket bridge.
  // Receives symbol + price from the backend stream and updates the Zustand store.
  // In production, Alpaca provides precise daily bars; the change24h here is a
  // rough visual approximation until the daily bar feed is wired up (Phase 1).
  injectSocketData: (symbol, price, volume) => {
    const currentList = get().watchlist;
    const existing = currentList.find(w => w.symbol === symbol);

    let newWatchlist = currentList;
    if (existing) {
      const diff       = price - existing.price;
      const changePct  = existing.change24h + (diff / price) * 100;
      const updated    = { ...existing, price, volume: volume ?? existing.volume, change24h: changePct };
      newWatchlist     = currentList.map(item => item.symbol === symbol ? updated : item);
    }

    const isActive = get().activeSymbol === symbol;
    const newTicker = isActive && existing
      ? { ...existing, price, volume: volume ?? existing.volume }
      : get().ticker;

    // (Removed offline execution trace injection)
    const newTrades = get().recentTrades;

    set({
      watchlist: newWatchlist,
      recentTrades: newTrades,
      ...(isActive && { ticker: newTicker }),
    });
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
      safeFetchJSON<AlpacaAccountResponse>('http://localhost:8000/api/account'),
      safeFetchJSON<AlpacaPositionResponse[]>('http://localhost:8000/api/positions'),
      safeFetchJSON<AlpacaOrderResponse[]>('http://localhost:8000/api/orders'),
      safeFetchJSON<any[]>('http://localhost:8000/api/bots'),
      safeFetchJSON<any>('http://localhost:8000/api/performance')
    ]);

    if (account) set({ accountEquity: parseFloat(account.equity) || null });

    if (Array.isArray(posData)) {
      const mapped: PositionData[] = posData.map(p => ({
        id:           p.symbol,
        symbol:       p.symbol,
        side:         p.side.toUpperCase() as 'LONG' | 'SHORT',
        size:         parseFloat(p.size),
        entryPrice:   parseFloat(p.avg_entry_price ?? p.current_price),
        markPrice:    parseFloat(p.current_price),
        unrealizedPnl: parseFloat(p.unrealized_pnl),
        realizedPnl:  0,
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
      const ledger = await safeFetchJSON<any[]>('http://localhost:8000/api/ledger');
      if (Array.isArray(ledger) && ledger.length > 0) set({ ledgerTrades: ledger });
    } catch { /* silent fail */ }

    // Market history is fetched separately — it's the heaviest call
    get().fetchMarketHistory(get().activeSymbol);
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
const WS_URL = 'ws://localhost:8000/stream';
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
        attemptsRef.current = 0;  // reset backoff on successful connection
      };

      ws.onmessage = (event) => {
        try {
          const payload = JSON.parse(event.data) as SocketTickPayload;
          if (payload.type === 'QUOTE' || payload.type === 'TICK') {
            const { symbol, price, volume } = payload.data;
            useTradingStore.getState().injectSocketData(symbol, price, volume);
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
          return;
        }
        const delay = WS_BASE_DELAY_MS * Math.pow(2, attemptsRef.current - 1);
        console.warn(`[ORCHESTRATOR] WebSocket closed — reconnecting in ${delay}ms (attempt ${attemptsRef.current}/${WS_MAX_ATTEMPTS})`);
        retryTimer.current = setTimeout(connect, delay);
      };
    };

    connect();

    // SSE Endpoint connections
    const reflectionsSSE = new EventSource('http://localhost:8000/api/reflections/stream');
    reflectionsSSE.onmessage = (event) => {
      try {
        const data = JSON.parse(event.data);
        if (data.heartbeat) return; // ignore heartbeats
        if (data.insight) {
          useTradingStore.setState({ aiInsights: data.insight });
        }
        // All reflection types go to learningHistory (observe, calculate, decision, learning)
        if (data.type) {
          useTradingStore.setState(s => ({
            learningHistory: [data, ...s.learningHistory].slice(0, 100)
          }));
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

    const logsSSE = new EventSource('http://localhost:8000/api/logs/stream');
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

    return () => {
      destroyed = true;
      clearTimeout(timer);
      clearTimeout(retry);
      if (retryTimer.current) clearTimeout(retryTimer.current);
      wsRef.current?.close();
      reflectionsSSE.close();
      logsSSE.close();
    };
  }, []);
}
