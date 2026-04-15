import os
import json
import asyncio
import logging
import time
from collections import deque
from dotenv import load_dotenv
from fastapi import FastAPI, WebSocket, WebSocketDisconnect, HTTPException
from fastapi.responses import StreamingResponse
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field
from typing import Optional

load_dotenv()

logging.basicConfig(level=os.getenv("LOG_LEVEL", "INFO"))
logger = logging.getLogger(__name__)

app = FastAPI(title="Alpaca Multi-Agent API", version="2.0")

# Allow Next.js local fetches — restrict to your domain in production
app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:3000"],
    allow_methods=["GET", "POST"],
    allow_headers=["Content-Type"],
)

ALPACA_API_KEY = os.getenv("ALPACA_API_KEY_ID") or os.getenv("ALPACA_API_KEY")
ALPACA_API_SECRET = os.getenv("ALPACA_API_SECRET_KEY") or os.getenv("ALPACA_API_SECRET")
PAPER_TRADING = os.getenv("PAPER_TRADING", "true").lower() == "true"

# trading_client is initialized once at module load (blocking REST client, safe to hold)
trading_client = None
# crypto_stream is NOT initialized here — created lazily inside stream_manager
# so that uvicorn hot-reload doesn't leave stale connections open against the
# Alpaca paper account's 1-connection limit, which causes the 429 spam loop.
_stream_task: Optional[asyncio.Task] = None
_ai_reflection_task: Optional[asyncio.Task] = None
_reflection_engine = None  # ReflectionEngine instance, initialized at startup

if ALPACA_API_KEY and ALPACA_API_SECRET:
    try:
        from alpaca.trading.client import TradingClient
        trading_client = TradingClient(ALPACA_API_KEY, ALPACA_API_SECRET, paper=PAPER_TRADING)
        logger.info("[ALPACA] TradingClient initialized (paper=%s)", PAPER_TRADING)
    except Exception as e:
        logger.warning("[ALPACA] TradingClient initialization failed: %s", e)
else:
    logger.warning("[ALPACA] API keys not configured — trading endpoints will return errors.")

from agents.orchestrator import master_orchestrator

connected_clients: list[WebSocket] = []
_clients_lock: asyncio.Lock | None = None  # initialized lazily inside the event loop


def _get_clients_lock() -> asyncio.Lock:
    global _clients_lock
    if _clients_lock is None:
        _clients_lock = asyncio.Lock()
    return _clients_lock

# ==========================================
# REST EXECUTOR API
# ==========================================

def _require_trading_client():
    if trading_client is None:
        raise HTTPException(status_code=503, detail="Alpaca API keys not configured.")

@app.get("/api/account")
def get_account():
    """Retrieve top-level account metrics for the UI header."""
    _require_trading_client()
    try:
        acc = trading_client.get_account()

        equity      = float(acc.equity or 0)
        last_equity = float(getattr(acc, 'last_equity', None) or equity)
        today_pl    = equity - last_equity

        # unrealized_pl may not exist on all account types — safe fallback
        unrealized_pl = 0.0
        for attr in ('unrealized_pl', 'unrealized_plpc'):
            raw = getattr(acc, attr, None)
            if attr == 'unrealized_pl' and raw is not None:
                try:
                    unrealized_pl = float(raw)
                except (ValueError, TypeError):
                    pass
                break

        return {
            "equity":         str(acc.equity),
            "buying_power":   str(acc.buying_power),
            "cash":           str(acc.cash),
            "portfolio_value": str(acc.portfolio_value),
            "status":         acc.status.value if hasattr(acc.status, 'value') else str(acc.status).replace('AccountStatus.', ''),
            "last_equity":    str(last_equity),
            "today_pl":       round(today_pl, 2),       # realized + unrealized change since last session open
            "unrealized_pl":  round(unrealized_pl, 2),  # open position unrealized P&L
        }
    except HTTPException:
        raise
    except Exception as e:
        logger.error("[ACCOUNT] %s", e)
        raise HTTPException(status_code=502, detail=str(e))

@app.get("/api/positions")
def get_positions():
    """Returns active portfolio holdings."""
    _require_trading_client()
    try:
        pos = trading_client.get_all_positions()
        return [
            {
                "symbol": p.symbol,
                # Strip Enum prefix e.g. PositionSide.LONG -> LONG
                "side": p.side.value if hasattr(p.side, 'value') else str(p.side).split('.')[-1],
                "size": str(p.qty),
                "avg_entry_price": str(p.avg_entry_price),
                "current_price": str(p.current_price),
                "unrealized_pnl": str(p.unrealized_pl),
            } for p in pos
        ]
    except HTTPException:
        raise
    except Exception as e:
        logger.error("[POSITIONS] %s", e)
        raise HTTPException(status_code=502, detail=str(e))

@app.get("/api/orders")
def get_orders():
    """Returns historical booked orders for the Ledger tab."""
    _require_trading_client()
    try:
        from alpaca.trading.requests import GetOrdersRequest
        from alpaca.trading.enums import QueryOrderStatus
        req = GetOrdersRequest(status=QueryOrderStatus.ALL, limit=50)
        orders = trading_client.get_orders(filter=req)
        return [
            {
                "id": str(o.id)[:8],
                "symbol": o.symbol,
                "side": o.side.value if hasattr(o.side, 'value') else str(o.side).replace('OrderSide.', ''),
                "qty": str(o.filled_qty or o.qty),
                "status": o.status.value if hasattr(o.status, 'value') else str(o.status).replace('OrderStatus.', ''),
                "fill_price": str(o.filled_avg_price) if o.filled_avg_price else None,
                "submitted_at": o.submitted_at.isoformat() if o.submitted_at else None,
            } for o in orders
        ]
    except HTTPException:
        raise
    except Exception as e:
        logger.error("[ORDERS] %s", e)
        raise HTTPException(status_code=502, detail=str(e))

class OrderRequest(BaseModel):
    symbol: str = Field(default="BTC/USD", description="Trading symbol")
    side: str = Field(default="BUY", description="BUY or SELL")
    qty: float = Field(default=0.01, gt=0, description="Order quantity")

@app.post("/api/seed")
def place_order(payload: OrderRequest):
    """Places a market order via the full risk+execution pipeline. Used by the TradePanel."""
    _require_trading_client()
    if not PAPER_TRADING:
        raise HTTPException(status_code=403, detail="Live trading orders must go through the execution agent pipeline.")
    try:
        # Get last tick price for slippage tracking; fallback to 0.0 if stream not yet running
        price = master_engine.get_last_price(payload.symbol) or 0.0

        synthetic_signal = {
            "action":     payload.side.upper(),
            "symbol":     payload.symbol,
            "price":      price,
            "confidence": 1.0,   # Manual UI orders bypass confidence gate
            "bot":        "tradepanel",
            "meta":       {"source": "manual_ui"},
        }

        # Evaluate kill switch before anything else
        equity = 0.0
        try:
            equity = float(trading_client.get_account().equity)
        except Exception:
            pass

        from risk.kill_switch import global_kill_switch
        global_kill_switch.evaluate_portfolio(equity)

        approved = risk_agent.process(synthetic_signal, equity)
        if not approved:
            raise HTTPException(status_code=403, detail="Risk gate rejected order (kill switch active or position limits exceeded).")

        # Honor the user's explicit qty rather than Kelly-sized qty
        approved["qty"] = payload.qty

        exec_result = execution_agent.execute(approved, signal_price=price)
        if not exec_result:
            raise HTTPException(status_code=502, detail="Execution failed — check trading_client and API keys.")

        _push_log(
            f"[TRADEPANEL] FILLED #{exec_result.order_id[:8]} — "
            f"{payload.side.upper()} {payload.symbol} qty={exec_result.qty:.6f} "
            f"fill=${exec_result.fill_price:.2f} slip=${exec_result.slippage:.4f}"
        )
        logger.info("[ORDER] FILLED %s %s qty=%.6f fill=%.2f", payload.side, payload.symbol, exec_result.qty, exec_result.fill_price)
        return {"status": "submitted", "order_id": exec_result.order_id}
    except HTTPException:
        raise
    except Exception as e:
        logger.error("[ORDER] %s", e)
        raise HTTPException(status_code=422, detail=str(e))

# ==========================================
# LLM SWARM API
# ==========================================

class ChatPayload(BaseModel):
    message: str = Field(..., min_length=1, max_length=2000)

@app.post("/api/agents/chat")
def chat_with_orchestrator(payload: ChatPayload):
    """Routes user message to the LangChain orchestrator agent."""
    try:
        reply = master_orchestrator.process_chat(payload.message)
        return {"sender": "ai", "text": reply}
    except Exception as e:
        logger.error("[ORCHESTRATOR] %s", e)
        raise HTTPException(status_code=500, detail="Orchestrator error")

# ==========================================
# AGENT FLEET & PERFORMANCE API
# ==========================================

from strategy.engine import master_engine
from agents.risk_agent import risk_agent
from agents.execution_agent import execution_agent
from quant.data_buffer import market_buffer

# In-memory queues — created lazily inside the running event loop
_log_queue: Optional[asyncio.Queue] = None
_reflection_queue: Optional[asyncio.Queue] = None

def _get_log_queue() -> asyncio.Queue:
    global _log_queue
    if _log_queue is None:
        _log_queue = asyncio.Queue(maxsize=500)
    return _log_queue

def _get_reflection_queue() -> asyncio.Queue:
    global _reflection_queue
    if _reflection_queue is None:
        _reflection_queue = asyncio.Queue(maxsize=500)
    return _reflection_queue

def _push_log(msg: str):
    try:
        _get_log_queue().put_nowait(json.dumps({"log": msg}))
    except asyncio.QueueFull:
        pass

def _push_reflection(data: dict):
    try:
        _get_reflection_queue().put_nowait(json.dumps(data))
    except asyncio.QueueFull:
        pass

@app.get("/api/bots")
def get_bots():
    """Returns the fleet of active algorithmic trading bots."""
    return master_engine.get_bot_states()


# ==========================================
# RISK STATUS
# ==========================================

@app.get("/api/risk/status")
def get_risk_status():
    """Returns kill switch state, drawdown %, and exposure limits."""
    return risk_agent.get_risk_status()


# ==========================================
# BOT LIFECYCLE CONTROLS
# ==========================================

class BotLifecyclePayload(BaseModel):
    reason: str = "Manual override"

@app.post("/api/bots/{bot_id}/halt")
def halt_bot(bot_id: str, payload: BotLifecyclePayload = BotLifecyclePayload()):
    """Halt a specific trading bot by ID."""
    from risk.kill_switch import global_kill_switch
    success = master_engine.halt_bot(bot_id, reason=payload.reason)
    if not success:
        raise HTTPException(status_code=404, detail=f"Bot '{bot_id}' not found")
    _push_log(f"[ORCHESTRATOR] ⛔ Bot '{bot_id}' halted — {payload.reason}")
    return {"status": "halted", "bot_id": bot_id, "reason": payload.reason}

@app.post("/api/bots/{bot_id}/resume")
def resume_bot(bot_id: str):
    """Resume a halted trading bot by ID."""
    success = master_engine.resume_bot(bot_id)
    if not success:
        raise HTTPException(status_code=404, detail=f"Bot '{bot_id}' not found")
    _push_log(f"[ORCHESTRATOR] ▶️ Bot '{bot_id}' resumed.")
    return {"status": "resumed", "bot_id": bot_id}


# ==========================================
# LEDGER (historical fills from SQLite)
# ==========================================

@app.get("/api/ledger")
async def get_ledger(limit: int = 50):
    """
    Returns historical execution records joined with their originating signals.
    Powers the ExecutionLog tab with real fill + slippage data.
    """
    try:
        from sqlalchemy import select, desc
        from db.database import _get_session_factory
        from db.models import ExecutionRecord, SignalRecord

        async with _get_session_factory()() as session:
            stmt = (
                select(
                    ExecutionRecord.id,
                    ExecutionRecord.alpaca_order_id,
                    ExecutionRecord.fill_price,
                    ExecutionRecord.slippage,
                    ExecutionRecord.timestamp,
                    SignalRecord.strategy,
                    SignalRecord.symbol,
                    SignalRecord.action,
                    SignalRecord.confidence,
                )
                .join(SignalRecord, ExecutionRecord.signal_id == SignalRecord.id, isouter=True)
                .order_by(desc(ExecutionRecord.timestamp))
                .limit(limit)
            )
            rows = (await session.execute(stmt)).all()

        return [
            {
                "id":              r.id,
                "order_id":        r.alpaca_order_id[:8] if r.alpaca_order_id else None,
                "symbol":          r.symbol,
                "side":            r.action,
                "bot":             r.strategy,
                "fill_price":      r.fill_price,
                "slippage":        r.slippage,
                "slippage_bps":    round(r.slippage / r.fill_price * 10000, 2) if r.fill_price else None,
                "confidence":      r.confidence,
                "timestamp":       r.timestamp.isoformat() if r.timestamp else None,
            }
            for r in rows
        ]
    except Exception as e:
        logger.error("[LEDGER] %s", e)
        return []


# ==========================================
# HISTORICAL REFLECTIONS (bot_amends)
# ==========================================

@app.get("/api/reflections")
async def get_reflections(limit: int = 50):
    """
    Returns the historical BotAmend records from SQLite.
    Powers the 'Historical Learning & Amends' column in the Brain tab.
    """
    try:
        from sqlalchemy import select, desc
        from db.database import _get_session_factory
        from db.models import BotAmend

        async with _get_session_factory()() as session:
            stmt = select(BotAmend).order_by(desc(BotAmend.timestamp)).limit(limit)
            rows = (await session.execute(stmt)).scalars().all()

        return [
            {
                "model":     r.model,
                "action":    r.action,
                "reason":    r.reason,
                "impact":    r.impact,
                "date":      r.timestamp.strftime("%Y-%m-%d %H:%M") if r.timestamp else None,
            }
            for r in rows
        ]
    except Exception as e:
        logger.error("[REFLECTIONS] %s", e)
        return []


@app.get("/api/reflections/history")
async def get_reflections_history(limit: int = 50):
    """
    Returns last N ReflectionLog rows (post-trade AI insights).
    More structured than /api/reflections — includes symbol, action, token count.
    Powers the Brain tab history section.
    """
    try:
        from sqlalchemy import select, desc
        from db.database import _get_session_factory
        from db.models import ReflectionLog

        async with _get_session_factory()() as session:
            rows = (await session.execute(
                select(ReflectionLog).order_by(desc(ReflectionLog.timestamp)).limit(limit)
            )).scalars().all()

        return [
            {
                "id":          r.id,
                "strategy":    r.strategy,
                "symbol":      r.symbol,
                "action":      r.action,
                "insight":     r.insight,
                "tokens_used": r.tokens_used,
                "timestamp":   r.timestamp.strftime("%Y-%m-%d %H:%M") if r.timestamp else None,
            }
            for r in rows
        ]
    except Exception as e:
        logger.error("[REFLECTIONS/HISTORY] %s", e)
        return []


@app.get("/api/performance")
def get_performance(period: str = "1M"):
    """Fetches real portfolio history from Alpaca. period: 1D | 1W | 1M | YTD"""
    _require_trading_client()
    # Map UI period labels to Alpaca API params.
    # Alpaca accepts: 1D, 1W, 1M, 3M, 6M, 1A — "YTD" is NOT a valid value.
    period_map = {
        "1D": ("1D", "1Min"),
        "1W": ("1W", "1H"),
        "1M": ("1M", "1D"),
        "YTD": ("6M", "1D"),  # closest supported approximation for year-to-date
    }
    alpaca_period, timeframe = period_map.get(period.upper(), ("1M", "1D"))
    try:
        hist = trading_client.get(
            "/account/portfolio/history",
            {"period": alpaca_period, "timeframe": timeframe},
        )

        timestamps = hist.get("timestamp") or []
        equities = hist.get("equity") or []
        profit_loss = hist.get("profit_loss") or []

        if not timestamps:
            return {"history": [], "net_pnl": 0.0, "drawdown": 0.0, "has_data": False}

        curve = [[timestamps[i] * 1000, equities[i]]
                 for i in range(len(timestamps)) if equities[i] is not None]
        valid_pnl = [p for p in profit_loss if p is not None]
        net_pnl = valid_pnl[-1] if valid_pnl else 0.0

        # Compute max drawdown from equity curve
        max_dd = 0.0
        if equities:
            peak = equities[0] or 0
            for eq in equities:
                if eq is None:
                    continue
                if eq > peak:
                    peak = eq
                if peak > 0:
                    dd = (peak - eq) / peak * 100
                    max_dd = max(max_dd, dd)

        return {"history": curve, "net_pnl": net_pnl, "drawdown": round(max_dd, 4), "has_data": len(curve) > 0}
    except Exception as e:
        logger.error("[PERFORMANCE] %s", e)
        return {"history": [], "net_pnl": 0.0, "drawdown": 0.0, "has_data": False}


@app.get("/api/analytics/returns")
async def get_return_distribution():
    """
    Slippage distribution from ExecutionRecord — bps from signal price to fill price.
    Returns 11 buckets spanning -50 to +50 bps in 10 bps steps.
    Slippage bps = (fill_price - signal_price) / signal_price * 10000 ≈ stored slippage / fill_price * 10000.
    """
    try:
        from db.database import _get_session_factory
        from db.models import ExecutionRecord
        from sqlalchemy import select

        async with _get_session_factory()() as session:
            result = await session.execute(
                select(ExecutionRecord.fill_price, ExecutionRecord.slippage, ExecutionRecord.timestamp)
                .where(ExecutionRecord.status == "FILLED")
                .where(ExecutionRecord.fill_price > 0)
                .order_by(ExecutionRecord.timestamp)
            )
            rows = result.fetchall()

        if len(rows) < 1:
            return {"buckets": [], "has_data": False}

        # slippage_bps = slippage_usd / fill_price * 10000
        slippages_bps = [
            r[1] / r[0] * 10000
            for r in rows
            if r[0] > 0 and r[1] is not None
        ]

        if not slippages_bps:
            return {"buckets": [], "has_data": False}

        # 11 buckets: -50 to +50 bps in 10 bps steps
        edges = [-50 + i * 10 for i in range(12)]
        n_buckets = len(edges) - 1
        counts = [0] * n_buckets
        for bps in slippages_bps:
            placed = False
            for j in range(n_buckets):
                if edges[j] <= bps < edges[j + 1]:
                    counts[j] += 1
                    placed = True
                    break
            if not placed:
                counts[-1] += 1  # overflow into last bucket

        total = max(sum(counts), 1)
        buckets = [
            {"label": f"{edges[i]:+d}bps", "count": counts[i], "pct": round(counts[i] / total * 100, 1)}
            for i in range(n_buckets)
        ]
        return {"buckets": buckets, "has_data": True, "sample_size": len(slippages_bps)}

    except Exception as e:
        logger.error("[ANALYTICS] returns distribution failed: %s", e)
        return {"buckets": [], "has_data": False}


@app.get("/api/analytics/llm-cost")
async def get_llm_cost():
    """
    Returns dual time-series for the LLM Cost vs PnL chart:
      - cumulative_cost: [[timestamp_ms, cumulative_usd], ...]
      - cumulative_pnl:  [[timestamp_ms, cumulative_pnl_usd], ...]
    Both series share the same time axis (daily resolution).
    """
    try:
        from db.database import _get_session_factory
        from db.models import LLMUsage, ExecutionRecord
        from sqlalchemy import select

        async with _get_session_factory()() as session:
            cost_rows = (await session.execute(
                select(LLMUsage.timestamp, LLMUsage.cost_usd)
                .order_by(LLMUsage.timestamp)
            )).fetchall()

            exec_rows = (await session.execute(
                select(ExecutionRecord.timestamp, ExecutionRecord.fill_price)
                .where(ExecutionRecord.status == "FILLED")
                .where(ExecutionRecord.fill_price > 0)
                .order_by(ExecutionRecord.timestamp)
            )).fetchall()

        if not cost_rows and not exec_rows:
            return {"has_data": False, "cumulative_cost": [], "cumulative_pnl": []}

        # Build cumulative LLM cost series
        cum_cost = 0.0
        cost_series: list[list] = []
        for ts, cost in cost_rows:
            cum_cost += cost or 0
            cost_series.append([int(ts.timestamp() * 1000) if ts else 0, round(cum_cost, 6)])

        # Build cumulative PnL series from Alpaca portfolio history (1W, daily bars)
        pnl_series: list[list] = []
        cum_pnl = 0.0
        try:
            hist = trading_client.get(
                "/account/portfolio/history",
                {"period": "1W", "timeframe": "1D"},
            )
            timestamps = hist.get("timestamp") or []
            profit_loss = hist.get("profit_loss") or []
            for i, ts in enumerate(timestamps):
                if i < len(profit_loss) and profit_loss[i] is not None:
                    cum_pnl = profit_loss[i]
                    pnl_series.append([ts * 1000, round(cum_pnl, 2)])
        except Exception as pnl_err:
            logger.debug("[ANALYTICS] portfolio history for llm-cost chart: %s", pnl_err)

        return {
            "has_data": bool(cost_series or pnl_series),
            "cumulative_cost": cost_series,
            "cumulative_pnl":  pnl_series,
            "total_cost_usd":  round(cum_cost, 6),
            "total_pnl_usd":   round(cum_pnl, 2),
        }

    except Exception as e:
        logger.error("[ANALYTICS] llm-cost failed: %s", e)
        return {"has_data": False, "cumulative_cost": [], "cumulative_pnl": []}


async def reflection_generator():
    """Live SSE stream — emits strategy engine reflections & signal events."""
    yield f"data: {json.dumps({'heartbeat': True})}\n\n"
    q = _get_reflection_queue()
    while True:
        try:
            payload = await asyncio.wait_for(q.get(), timeout=20)
            yield f"data: {payload}\n\n"
        except asyncio.TimeoutError:
            yield f"data: {json.dumps({'heartbeat': True})}\n\n"

@app.get("/api/reflections/stream")
async def stream_reflections():
    """Server-Sent Events endpoint for agent reflections and learning."""
    return StreamingResponse(reflection_generator(), media_type="text/event-stream",
                             headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"})

async def log_generator():
    """Live SSE stream — emits the real-time agent decision log."""
    yield f"data: {json.dumps({'log': '[SYSTEM] Trading Engine Online — monitoring live market feeds...'})}\n\n"
    q = _get_log_queue()
    while True:
        try:
            payload = await asyncio.wait_for(q.get(), timeout=20)
            yield f"data: {payload}\n\n"
        except asyncio.TimeoutError:
            yield f"data: {json.dumps({'log': '[HEARTBEAT] Awaiting next bar...'})}\n\n"

@app.get("/api/logs/stream")
async def stream_logs():
    """Server-Sent Events endpoint for raw agent control logs."""
    return StreamingResponse(log_generator(), media_type="text/event-stream",
                             headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"})

@app.post("/api/backtest")
def run_backtest_endpoint(payload: dict):
    """
    Runs an out-of-sample backtest for the given strategy and symbol.
    Accepts: { symbol, strategy, start_date, end_date }
    Returns: BacktestResult JSON
    """
    from backtest.runner import BacktestParams, run_backtest
    params = BacktestParams(
        symbol=payload.get("symbol", "BTC-USD"),
        strategy=payload.get("strategy", "momentum-alpha"),
        start_date=payload.get("start_date", "2023-01-01"),
        end_date=payload.get("end_date", "2023-12-31"),
    )
    try:
        result = run_backtest(params)
        return {
            "net_profit":    result.net_profit,
            "max_drawdown":  result.max_drawdown,
            "profit_factor": result.profit_factor,
            "total_trades":  result.total_trades,
            "win_rate":      result.win_rate,
            "sharpe_ratio":  result.sharpe_ratio,
            "equity_curve":  result.equity_curve,
            "error":         result.error,
        }
    except Exception as e:
        logger.error("[BACKTEST] %s", e)
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/api/market/history")
def get_market_history(symbol: str = "BTC/USD"):
    """Fetches real historical crypto bars for plotting Nivo chart."""
    if not ALPACA_API_KEY:
        return []
        
    try:
        from alpaca.data.historical import CryptoHistoricalDataClient
        from alpaca.data.requests import CryptoBarsRequest
        from alpaca.data.timeframe import TimeFrame
        from datetime import datetime, timedelta
        
        client = CryptoHistoricalDataClient(ALPACA_API_KEY, ALPACA_API_SECRET)
        req = CryptoBarsRequest(
            symbol_or_symbols=symbol,
            timeframe=TimeFrame.Hour,
            start=datetime.utcnow() - timedelta(days=2),
            end=datetime.utcnow()
        )
        bars = client.get_crypto_bars(req)
        
        if bars.df.empty:
            return []
            
        data = []
        for index, row in bars.df.iterrows():
            data.append({"x": index[1].isoformat(), "y": row.close})
            
        return [{"id": symbol, "data": data}]
    except Exception as e:
        logger.error("[HISTORY] %s", e)
        return []

# ==========================================
# WEBSOCKET STREAMING
# ==========================================

# ==========================================
# MANAGED STREAM (connection-limit aware)
# ==========================================

class _ManagedCryptoStream:
    """
    Thin wrapper around CryptoDataStream that overrides _run_forever() so that
    'connection limit exceeded' ValueErrors PROPAGATE to the caller instead of
    being swallowed by the SDK's internal retry loop.

    Root cause of the 429-spam: SDK's _run_forever() catches every exception and
    retries immediately, so our outer 65s cooldown in stream_manager never fires.
    By overriding _run_forever() we break that cycle — on connection limit the
    error bubbles up through asyncio.run() → executor future → our outer handler.
    """

    def __new__(cls, key: str, secret: str):
        """Return a patched CryptoDataStream instance."""
        from alpaca.data.live import CryptoDataStream

        stream = CryptoDataStream(key, secret)

        # Capture original method and patch the instance
        async def _managed_run_forever():
            import asyncio as _asyncio
            import websockets

            # Must set _loop so that stop() can call is_running() without crashing
            stream._loop = _asyncio.get_running_loop()

            # Mirror SDK: don't start until at least one subscription is registered
            while not any(
                v for k, v in stream._handlers.items()
                if k not in ("cancelErrors", "corrections")
            ):
                if not stream._stop_stream_queue.empty():
                    stream._stop_stream_queue.get(timeout=1)
                    return
                await _asyncio.sleep(0)

            stream._should_run = True
            stream._running = False

            while True:
                try:
                    if not stream._should_run:
                        return
                    if not stream._running:
                        await stream._start_ws()
                        await stream._send_subscribe_msg()
                        stream._running = True
                    await stream._consume()
                except _asyncio.CancelledError:
                    raise
                except ValueError as e:
                    if "connection limit" in str(e).lower():
                        # DO NOT RETRY — propagate so stream_manager applies 65s cooldown
                        raise
                    await stream.close()
                    stream._running = False
                    logger.warning("[STREAM] ValueError in stream: %s", e)
                except websockets.exceptions.WebSocketException as wse:
                    await stream.close()
                    stream._running = False
                    logger.warning("[STREAM] WebSocket error, reconnecting: %s", wse)
                except Exception:
                    raise
                finally:
                    await _asyncio.sleep(0)

        # Bind the override to the stream instance
        import types
        stream._run_forever = _managed_run_forever

        return stream


async def stream_manager():
    """Manages the Alpaca CryptoDataStream with proper lifecycle handling.

    Key design decisions:
    - Creates a NEW CryptoDataStream per attempt (never reuses stale objects)
    - Runs stream.run() in a thread via asyncio.to_thread() so the blocking
      SDK call doesn't stall the FastAPI event loop
    - Detects 'connection limit exceeded' (Alpaca paper: 1 concurrent stream)
      and waits 65s before retrying — giving Alpaca time to release the stale
      TCP connection from the previous uvicorn process
    - All other errors use standard exponential backoff
    """
    if not (ALPACA_API_KEY and ALPACA_API_SECRET):
        logger.warning("[STREAM] No API keys — live stream disabled.")
        return

    CONNECTION_LIMIT_COOLDOWN = 65   # Alpaca releases stale connections in ~60s
    backoff = 5
    max_backoff = 120
    attempts = 0
    max_attempts = 15

    # Shared mutable reference so inner callbacks can close the stream
    _active_stream: list = [None]

    while attempts < max_attempts:
        try:
            stream = _ManagedCryptoStream(ALPACA_API_KEY, ALPACA_API_SECRET)
            _active_stream[0] = stream

            # --- Define callbacks (must be recreated per stream instance) ---
            async def bar_callback(bar):
                price = float(bar.close)
                symbol = bar.symbol

                # --- Step 1: Feed OHLCV buffer (free, no LLM cost) ---
                market_buffer.ingest_bar(symbol, bar)

                await broadcast({"type": "TICK", "data": {
                    "symbol": symbol, "price": price,
                    "volume": bar.volume, "timestamp": bar.timestamp.isoformat()
                }})
                # Capture signal_price at emission time for slippage calculation
                signal_price = price

                for signal in master_engine.process_tick(symbol, price):
                    meta_str = ", ".join(f"{k}={v}" for k, v in signal.get('meta', {}).items())
                    _push_log(
                        f"[{signal['bot'].upper()}] {signal['action']} signal on {symbol} "
                        f"@ ${price:,.2f} (conf: {signal['confidence']}) {meta_str}"
                    )

                    equity = 0.0
                    try:
                        if trading_client:
                            equity = float(trading_client.get_account().equity)
                    except Exception:
                        pass

                    # Update kill switch with current equity (drawdown tracking)
                    from risk.kill_switch import global_kill_switch
                    global_kill_switch.evaluate_portfolio(equity)

                    approved = risk_agent.process(signal, equity)
                    if approved:
                        _push_log(
                            f"[RISK AGENT] ✓ Approved {approved['action']} {symbol} "
                            f"qty={approved['qty']:.6f} notional=${approved.get('notional', 0):.2f}"
                        )
                        # Push rich reflection event for the Brain tab
                        _push_reflection({
                            "strategy":      signal['bot'],
                            "action":        approved['action'],
                            "symbol":        symbol,
                            "confidence":    signal['confidence'],
                            "qty":           approved['qty'],
                            "kelly_fraction": approved.get('kelly_fraction', 0),
                            "meta":          signal.get('meta', {}),
                            "timestamp":     bar.timestamp.isoformat(),
                            "type":          "decision",
                        })
                        if trading_client:
                            # Broadcast SIGNAL event so Bot Control panel shows it in real time
                            await broadcast({
                                "type": "SIGNAL",
                                "data": {
                                    "bot_id":     signal['bot'],
                                    "action":     approved['action'],
                                    "symbol":     symbol,
                                    "confidence": signal['confidence'],
                                    "qty":        approved['qty'],
                                    "timestamp":  bar.timestamp.isoformat(),
                                }
                            })
                            # Pass signal_price for accurate slippage computation
                            exec_result = execution_agent.execute(approved, signal_price=signal_price)
                            if exec_result:
                                key = (signal['bot'], symbol)
                                if approved['action'] == 'BUY':
                                    _entry_prices[key] = exec_result.fill_price
                                    master_engine.update_yield(signal['bot'], 0.0)
                                else:
                                    entry = _entry_prices.pop(key, exec_result.fill_price)
                                    realized_pnl = (exec_result.fill_price - entry) * exec_result.qty
                                    master_engine.update_yield(signal['bot'], realized_pnl)
                                _push_log(
                                    f"[EXECUTION] FILLED #{exec_result.order_id[:8]} — "
                                    f"{approved['action']} {symbol} qty={exec_result.qty:.6f} "
                                    f"fill=${exec_result.fill_price:.2f} "
                                    f"slip=${exec_result.slippage:.4f} ({exec_result.slippage_pct:.3f}%)"
                                )
                                # Trigger post-trade learning reflection
                                if _reflection_engine:
                                    asyncio.create_task(_reflection_engine.learn_from_execution({
                                        "strategy": signal['bot'],
                                        "symbol": symbol,
                                        "action": approved['action'],
                                        "fill_price": exec_result.fill_price,
                                        "slippage": exec_result.slippage,
                                        "confidence": signal['confidence'],
                                        "qty": exec_result.qty,
                                    }))
                            else:
                                _push_log(
                                    f"[EXECUTION] ✗ FAILED {approved['action']} {symbol} "
                                    f"— order rejected (naked SELL or Alpaca error)"
                                )
                    else:
                        _push_log(f"[RISK AGENT] ✗ Blocked {signal['action']} {symbol} — risk gate rejected.")

            async def quote_callback(quote):
                await broadcast({"type": "QUOTE", "data": {
                    "symbol": quote.symbol, "price": float(quote.ask_price),
                    "timestamp": quote.timestamp.isoformat()
                }})

            stream.subscribe_bars(bar_callback, "BTC/USD", "ETH/USD", "SOL/USD")
            stream.subscribe_quotes(quote_callback, "BTC/USD", "ETH/USD", "SOL/USD")

            logger.info("[STREAM] Starting Alpaca CryptoDataStream...")
            _push_log("[STREAM] Connecting to Alpaca live data stream...")

            # Run blocking stream.run() in a thread — keeps event loop free.
            # stream.run() calls _run_forever() internally; we let it block
            # in a thread and use CancelledError to stop it cleanly.
            import concurrent.futures
            loop = asyncio.get_running_loop()
            with concurrent.futures.ThreadPoolExecutor(max_workers=1) as executor:
                future = loop.run_in_executor(executor, stream.run)
                try:
                    await future
                except concurrent.futures.CancelledError:
                    stream.stop()
                    return

            # If run() returns normally (stream closed), reset and retry
            logger.info("[STREAM] Stream ended, reconnecting...")
            backoff = 5
            attempts = 0

        except asyncio.CancelledError:
            logger.info("[STREAM] Stream task cancelled cleanly.")
            if _active_stream[0]:
                try:
                    _active_stream[0].stop()
                except Exception:
                    pass
            return

        except Exception as e:
            err_str = str(e).lower()
            attempts += 1

            if "connection limit" in err_str:
                # Alpaca paper: only 1 stream per account. Wait for stale connection release.
                wait = CONNECTION_LIMIT_COOLDOWN
                logger.warning("[STREAM] Connection limit hit (attempt %d/%d). "
                               "Waiting %ds for Alpaca to release stale connection...",
                               attempts, max_attempts, wait)
                _push_log(f"[STREAM] \u23f3 Alpaca connection limit \u2014 waiting {wait}s for stale session to expire...")
                await asyncio.sleep(wait)
            else:
                logger.warning("[STREAM] Error (attempt %d/%d): %s", attempts, max_attempts, e)
                _push_log(f"[STREAM] Connection error \u2014 retrying in {backoff}s ({attempts}/{max_attempts})...")
                await asyncio.sleep(backoff)
                backoff = min(backoff * 2, max_backoff)

    logger.error("[STREAM] Max reconnect attempts reached. Live stream suspended.")
    _push_log("[STREAM] \u274c Stream suspended after max retries. Restart backend to reconnect.")


async def broadcast(message: dict):
    if not connected_clients:
        return
    payload = json.dumps(message)
    dead_clients = []

    async with _get_clients_lock():
        clients_snapshot = list(connected_clients)

    for client in clients_snapshot:
        try:
            await client.send_text(payload)
        except Exception:
            dead_clients.append(client)

    if dead_clients:
        async with _get_clients_lock():
            for client in dead_clients:
                if client in connected_clients:
                    connected_clients.remove(client)

def _get_positions_for_reflection() -> list:
    """Fetches current positions from Alpaca for the reflection engine."""
    if not trading_client:
        return []
    try:
        pos = trading_client.get_all_positions()
        return [
            {
                "symbol": p.symbol,
                "side": p.side.value if hasattr(p.side, 'value') else str(p.side).split('.')[-1],
                "size": str(p.qty),
                "avg_entry_price": str(p.avg_entry_price),
                "current_price": str(p.current_price),
                "unrealized_pnl": str(p.unrealized_pl),
            } for p in pos
        ]
    except Exception:
        return []


@app.get("/api/strategy/states")
def get_strategy_states():
    """Returns current internal indicator state for all active strategies.
    Powers the Strategy Mental Model panel in the Brain tab."""
    return master_engine.get_all_states()


_scanner_agent = None
_scanner_task: Optional[asyncio.Task] = None
_entry_prices: dict[tuple, float] = {}  # (bot_id, symbol) → BUY fill price for PnL tracking


@app.get("/api/watchlist")
def get_watchlist():
    """Returns the latest scanner results (TA scores + Haiku verdicts)."""
    if _scanner_agent is None:
        return []
    return _scanner_agent.get_last_results()


@app.post("/api/watchlist/scan")
async def trigger_scan():
    """Triggers an immediate on-demand symbol scan."""
    if _scanner_agent is None:
        raise HTTPException(status_code=503, detail="Scanner agent not initialized")
    results = await _scanner_agent.run_once()
    return {"status": "ok", "results": results}


@app.on_event("startup")
async def startup_event():
    global _stream_task, _ai_reflection_task, _reflection_engine, _scanner_agent, _scanner_task
    from db.database import init_db
    await init_db()
    _get_log_queue()
    _get_reflection_queue()
    logger.info("Multi-Agent REST/WS Gateway booted (paper=%s).", PAPER_TRADING)
    _push_log("[SYSTEM] Trading Engine Online — initializing stream...")
    if ALPACA_API_KEY and ALPACA_API_SECRET:
        _stream_task = asyncio.create_task(stream_manager())

    # Start the reflection engine
    from agents.reflection_engine import ReflectionEngine
    _reflection_engine = ReflectionEngine(
        push_fn=_push_reflection,
        get_states_fn=master_engine.get_all_states,
        get_positions_fn=_get_positions_for_reflection,
    )
    _ai_reflection_task = asyncio.create_task(_reflection_engine.run())

    # Start the scanner agent
    from agents.scanner_agent import ScannerAgent
    from quant.data_buffer import market_buffer as _mb
    _scanner_agent = ScannerAgent(
        push_fn=_push_reflection,
        get_buffer_fn=lambda: _mb,
    )
    _scanner_task = asyncio.create_task(_scanner_agent.run())


@app.on_event("shutdown")
async def shutdown_event():
    global _stream_task, _ai_reflection_task, _scanner_task
    for task in (_stream_task, _ai_reflection_task, _scanner_task):
        if task and not task.done():
            task.cancel()
            try:
                await task
            except asyncio.CancelledError:
                pass
    logger.info("[STREAM] Clean shutdown complete.")

@app.websocket("/stream")
async def websocket_endpoint(websocket: WebSocket):
    await websocket.accept()
    async with _get_clients_lock():
        connected_clients.append(websocket)
    try:
        while True:
            await websocket.receive_text()
    except WebSocketDisconnect:
        async with _get_clients_lock():
            if websocket in connected_clients:
                connected_clients.remove(websocket)

@app.get("/")
def read_root():
    return {"status": "Automated Multi-Agent Pipeline Online"}
