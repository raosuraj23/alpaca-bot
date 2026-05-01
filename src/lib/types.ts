/**
 * Canonical TypeScript type definitions for the Alpaca Quant Terminal.
 * All dashboard components and the Zustand store import from here.
 */

// ---------------------------------------------------------------------------
// Market / Asset Types
// ---------------------------------------------------------------------------

export type AssetClass = 'CRYPTO' | 'EQUITY' | 'OPTIONS';

export type OrderSide = 'BUY' | 'SELL';

export type PositionSide = 'LONG' | 'SHORT';

export type OrderType = 'market' | 'limit' | 'stop';

export type OrderStatus = 'pending' | 'filled' | 'cancelled' | 'rejected';

export type BotStatus = 'ACTIVE' | 'HALTED' | 'IDLE' | 'DEGRADED';

// ---------------------------------------------------------------------------
// Core Data Interfaces
// ---------------------------------------------------------------------------

export interface TickerData {
  symbol: string;
  price: number;
  change24h: number;
  volume: number;
  /** Optional: bid price from Level 1 quote */
  bid?: number;
  /** Optional: ask price from Level 1 quote */
  ask?: number;
  /** Optional: timestamp of last update (ms since epoch) */
  lastUpdated?: number;
  /** Asset class — used to filter the watchlist sidebar tabs */
  asset_class?: AssetClass;
}

export interface TradeLog {
  id: string;
  /** Unix timestamp in milliseconds */
  timestamp: number;
  side: OrderSide;
  price: number;
  size: number;
  symbol?: string;
  /** Originating agent or strategy name */
  agentOrigin?: string;
  /** Signal confidence score 0–1 */
  signalConfidence?: number;
  /** Slippage from signal price to fill price */
  slippage?: number;
  status?: OrderStatus;
  /** CRYPTO | EQUITY | OPTIONS */
  assetClass?: AssetClass;
}

export interface PositionData {
  id: string;
  symbol: string;
  side: PositionSide;
  size: number;
  entryPrice: number;
  /** Current mark price */
  markPrice?: number;
  unrealizedPnl: number;
  realizedPnl: number;
  /** Position open timestamp (ms since epoch) */
  openedAt?: number;
  /** CRYPTO | EQUITY | OPTIONS */
  assetClass?: AssetClass;
}

// ---------------------------------------------------------------------------
// Strategy / Bot Types
// ---------------------------------------------------------------------------

export interface StrategyBot {
  id: string;
  name: string;
  status: BotStatus;
  /** Percentage of portfolio allocated to this strategy */
  allocationPct: number;
  /** 24-hour yield percentage */
  yield24h: number;
  /** Strategy algorithm type */
  algo: string;
  /** Asset class this bot trades */
  assetClass?: AssetClass;
  /** Total signals emitted */
  signalCount?: number;
  /** Total confirmed fills */
  fillCount?: number;
  /** Number of trades executed today */
  tradesToday?: number;
}

// ---------------------------------------------------------------------------
// Agent / Orchestrator Types
// ---------------------------------------------------------------------------

export interface AgentMessage {
  role: 'user' | 'assistant' | 'system';
  content: string;
  /** Timestamp (ms since epoch) */
  timestamp: number;
  /** Which agent produced this message */
  agentName?: string;
}

export interface OrchestratorCommand {
  action: 'HALT_BOT' | 'RESUME_BOT' | 'ADJUST_ALLOCATION' | 'TRIGGER_BACKTEST' | 'QUERY_RISK';
  targetBot?: string;
  params?: Record<string, unknown>;
}

// ---------------------------------------------------------------------------
// API Response Shapes (from FastAPI backend)
// ---------------------------------------------------------------------------

export interface AlpacaAccountResponse {
  equity: string;
  buying_power: string;
  cash: string;
  portfolio_value: string;
  status: string;
  /** Portfolio equity at start of last trading session */
  last_equity?: string;
  /** Today's total P&L: equity − last_equity (realized + unrealized change) */
  today_pl?: number;
  /** Total unrealized P&L across all open positions */
  unrealized_pl?: number;
}

export interface AlpacaPositionResponse {
  symbol: string;
  side: string;
  size: string;
  current_price: string;
  unrealized_pnl: string;
  avg_entry_price?: string;
}

export interface AlpacaOrderResponse {
  id: string;
  symbol: string;
  side: string;
  qty: string;
  fill_price: string | null;
  submitted_at: string;
  status: string;
}

// ---------------------------------------------------------------------------
// WebSocket Payload Types
// ---------------------------------------------------------------------------

export interface SocketTickPayload {
  type: 'TICK' | 'QUOTE';
  data: {
    symbol: string;
    price: number;
    volume?: number;
    bid?: number;
    ask?: number;
  };
}

// ---------------------------------------------------------------------------
// Backtest Types
// ---------------------------------------------------------------------------

export interface BacktestParams {
  strategy: string;
  startDate: string;
  endDate: string;
  initialCapital: number;
  symbol?: string;
}

export interface BacktestResult {
  netProfit: number;
  maxDrawdown: number;
  profitFactor: number;
  totalTrades: number;
  winRate: number;
  sharpeRatio: number;
  /** Equity curve data points [timestamp, equity] */
  equityCurve: [number, number][];
}

// ---------------------------------------------------------------------------
// Analytics Types
// ---------------------------------------------------------------------------

export interface RealizedTrade {
  id: string;
  symbol: string;
  assetClass: AssetClass;
  strategy: string;
  side: OrderSide;
  entryPrice: number;
  exitPrice: number;
  qty: number;
  pnl: number;
  entryTime: number;
  exitTime: number;
  slippage?: number;
  llmCostUsd?: number;
  confidence?: number;
  win?: boolean;
}

export interface WatchlistTA {
  symbol: string;
  score: number;
  signal: string;
  verdict?: string;
  price?: number;
  rsi?: number | null;
  ema_spread?: number | null;
  vol_surge?: number | null;
  band_pct?: number | null;
  asset_class?: AssetClass;
  timestamp?: string;
  last_scanned?: string;
}

export interface LLMExecutionRecord {
  id: string;
  timestamp: number;
  strategy: string;
  latencyMs: number;
  totalTokens: number;
  costUsd: number;
  tradePnl: number | null;
  assetClass: AssetClass;
}

export interface PortfolioSnapshot {
  timestamp: number;
  equity: number;
  benchmark?: number;
}

export type ActionItemType = 'LIQUIDATE' | 'REACTIVATE' | 'HALT' | 'MONITOR' | 'ADJUST';
export type ActionItemUrgency = 'HIGH' | 'MEDIUM' | 'LOW';

export interface ActionItem {
  type: ActionItemType;
  symbol?: string;
  strategy?: string;
  title: string;
  reason: string;
  urgency: ActionItemUrgency;
}

export interface ActionItemsResponse {
  items: ActionItem[];
  generated_at: number;
  cached: boolean;
  error?: string;
}
