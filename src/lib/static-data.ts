/**
 * Offline data constants for UI development and testing.
 * STATIC — replace each section with real API/WebSocket data when the
 * corresponding backend phase is complete (see execution-plan.md).
 */

import type { TickerData, StrategyBot, TradeLog, PositionData } from './types';

// ---------------------------------------------------------------------------
// Phase 1 STATIC — replace with live Alpaca WebSocket feed
// ---------------------------------------------------------------------------

export const INITIAL_WATCHLIST: TickerData[] = [
  { symbol: 'BTC/USD', price: 64205.50, change24h: 1.2,  volume: 15400.2 },
  { symbol: 'ETH/USD', price: 3450.10,  change24h: -0.4, volume: 8400.1  },
  { symbol: 'SOL/USD', price: 145.20,   change24h: 5.6,  volume: 1200.5  },
  { symbol: 'AAPL',    price: 173.50,   change24h: 0.8,  volume: 45000.0 },
  { symbol: 'TSLA',    price: 180.20,   change24h: -2.1, volume: 85000.0 },
];

// ---------------------------------------------------------------------------
// Phase 2 STATIC — replace with live strategy fleet from orchestrator API
// ---------------------------------------------------------------------------

export const STATIC_BOTS: StrategyBot[] = [
  {
    id:            'momentum-alpha',
    name:          'Momentum α',
    status:        'ACTIVE',
    allocationPct: 40,
    yield24h:      2.34,
    algo:          'Momentum',
    tradesToday:   14,
  },
  {
    id:            'statarb-gamma',
    name:          'StatArb γ',
    status:        'ACTIVE',
    allocationPct: 35,
    yield24h:      1.12,
    algo:          'Statistical Arbitrage',
    tradesToday:   6,
  },
  {
    id:            'hft-sniper',
    name:          'HFT Sniper',
    status:        'HALTED',
    allocationPct: 25,
    yield24h:      -0.45,
    algo:          'High-Frequency',
    tradesToday:   0,
  },
];

// ---------------------------------------------------------------------------
// Phase 1 STATIC — replace with real order history from /api/orders
// ---------------------------------------------------------------------------

export const STATIC_RECENT_TRADES: TradeLog[] = [
  {
    id:              'TRD-001',
    timestamp:       Date.now() - 1000 * 60 * 5,
    side:            'BUY',
    symbol:          'BTC/USD',
    price:           64100.00,
    size:            0.25,
    agentOrigin:     'Momentum α',
    signalConfidence: 0.87,
    slippage:        2.50,
  },
  {
    id:              'TRD-002',
    timestamp:       Date.now() - 1000 * 60 * 12,
    side:            'SELL',
    symbol:          'ETH/USD',
    price:           3445.50,
    size:            1.10,
    agentOrigin:     'StatArb γ',
    signalConfidence: 0.72,
    slippage:        0.80,
  },
];

// ---------------------------------------------------------------------------
// Phase 1 STATIC — replace with real positions from /api/positions
// ---------------------------------------------------------------------------

export const STATIC_POSITIONS: PositionData[] = [
  {
    id:           'BTC/USD',
    symbol:       'BTC/USD',
    side:         'LONG',
    size:         0.25,
    entryPrice:   64100.00,
    markPrice:    64205.50,
    unrealizedPnl: 26.38,
    realizedPnl:  0,
  },
  {
    id:           'AAPL',
    symbol:       'AAPL',
    side:         'LONG',
    size:         50,
    entryPrice:   171.20,
    markPrice:    173.50,
    unrealizedPnl: 115.00,
    realizedPnl:  0,
  },
];

// ---------------------------------------------------------------------------
// Phase 3 STATIC — replace with /api/reflections/stream SSE events
// ---------------------------------------------------------------------------

export const STATIC_BOT_LOGS: string[] = [
  '[SYSTEM] Multi-Agent API Synchronized',
  '[STRATEGY:EXEC] Waiting for streams...',
];

/** Shape mirrors the BotReflections component fields.
 *  Phase 3: replace with SQLite BotAmend table query via /api/reflections. */
export const STATIC_LEARNING_HISTORY: {
  id:     number;
  date:   string;
  model:  string;
  action: string;
  reason: string;
  impact: string;
}[] = [
  {
    id:     1,
    date:   '2026-04-12 14:22:01',
    model:  'Momentum α',
    action: 'PARAMETER_ADJUST',
    reason: 'Excessive false positives on 5m EMA cross detected. Increased threshold bound by 1.5%.',
    impact: '+2.4% Win Rate',
  },
  {
    id:     2,
    date:   '2026-04-11 09:15:40',
    model:  'StatArb γ',
    action: 'STRATEGY_HALT',
    reason: 'Cointegration breakdown across Tech sector pairing. Suspended trading to prevent mean-reversion traps.',
    impact: 'Risk Averted',
  },
  {
    id:     3,
    date:   '2026-04-10 16:04:12',
    model:  'HFT Sniper',
    action: 'LATENCY_COMPENSATION',
    reason: 'API routing ping degraded. Expanded limit order tolerance logic dynamically.',
    impact: 'Fill Ratio Normalized',
  },
];
