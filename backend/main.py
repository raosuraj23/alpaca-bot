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
_stock_stream_task: Optional[asyncio.Task] = None
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
async def chat_with_orchestrator(payload: ChatPayload):
    """Routes user message to the LangChain orchestrator agent."""
    try:
        reply = await master_orchestrator.process_chat(payload.message)
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
async def halt_bot(bot_id: str, payload: BotLifecyclePayload = BotLifecyclePayload()):
    """Halt a specific trading bot by ID and persist state to SQLite."""
    success = master_engine.halt_bot(bot_id, reason=payload.reason)
    if not success:
        raise HTTPException(status_code=404, detail=f"Bot '{bot_id}' not found")
    # Persist halt state so it survives server restarts
    try:
        from db.database import _get_session_factory
        from db.models import BotState
        bot = master_engine.bots.get(bot_id)
        async with _get_session_factory()() as session:
            from sqlalchemy import select
            row = (await session.execute(select(BotState).where(BotState.bot_id == bot_id))).scalar_one_or_none()
            if row is None:
                row = BotState(bot_id=bot_id)
                session.add(row)
            row.status = "HALTED"
            row.allocation = bot.allocation if bot else 0.0
            await session.commit()
    except Exception as exc:
        logger.warning("[HALT] BotState persist failed: %s", exc)
    _push_log(f"[ORCHESTRATOR] ⛔ Bot '{bot_id}' halted — {payload.reason}")
    return {"status": "halted", "bot_id": bot_id, "reason": payload.reason}

@app.post("/api/bots/{bot_id}/resume")
async def resume_bot(bot_id: str):
    """Resume a halted trading bot and persist ACTIVE state to SQLite."""
    success = master_engine.resume_bot(bot_id)
    if not success:
        raise HTTPException(status_code=404, detail=f"Bot '{bot_id}' not found")
    # Persist resume state
    try:
        from db.database import _get_session_factory
        from db.models import BotState
        bot = master_engine.bots.get(bot_id)
        async with _get_session_factory()() as session:
            from sqlalchemy import select
            row = (await session.execute(select(BotState).where(BotState.bot_id == bot_id))).scalar_one_or_none()
            if row is None:
                row = BotState(bot_id=bot_id)
                session.add(row)
            row.status = "ACTIVE"
            row.allocation = bot.allocation if bot else 0.0
            await session.commit()
    except Exception as exc:
        logger.warning("[RESUME] BotState persist failed: %s", exc)
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
async def get_performance(period: str = "1M"):
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

        # Annualised Sharpe & Sortino from period-over-period equity returns
        import math as _math
        sharpe = 0.0
        sortino = 0.0
        valid_eq = [e for e in equities if e is not None]
        if len(valid_eq) >= 2:
            rets = [
                (valid_eq[i] - valid_eq[i - 1]) / valid_eq[i - 1]
                for i in range(1, len(valid_eq))
                if valid_eq[i - 1] != 0
            ]
            if rets:
                mean_r = sum(rets) / len(rets)
                variance = sum((r - mean_r) ** 2 for r in rets) / max(len(rets) - 1, 1)
                std_r = _math.sqrt(variance)
                ann = _math.sqrt(252)
                if std_r > 0:
                    sharpe = round((mean_r / std_r) * ann, 3)
                neg = [r for r in rets if r < 0]
                if len(neg) > 1:
                    neg_mean = sum(neg) / len(neg)
                    down_var = sum((r - neg_mean) ** 2 for r in neg) / (len(neg) - 1)
                    down_std = _math.sqrt(down_var)
                    if down_std > 0:
                        sortino = round((mean_r / down_std) * ann, 3)

        # Compute realized trades for win-rate calculation in the UI
        realized_trades: list = []
        try:
            from db.database import _get_session_factory as _gsf
            from db.models import ExecutionRecord as _ER, SignalRecord as _SR
            from sqlalchemy import select as _sel
            from collections import defaultdict as _dd

            async def _fetch_trades():
                async with _gsf()() as _s:
                    _stmt = (
                        _sel(_ER.fill_price, _ER.qty, _SR.strategy, _SR.symbol, _SR.action, _ER.timestamp)
                        .join(_SR, _ER.signal_id == _SR.id)
                        .where(_ER.status == "FILLED")
                        .order_by(_SR.strategy, _SR.symbol, _ER.timestamp)
                    )
                    return (await _s.execute(_stmt)).all()

            _rows = await _fetch_trades()
            _groups = _dd(list)
            for _r in _rows:
                _groups[(_r.strategy, _r.symbol)].append(_r)

            for (_strat, _sym), _grp in _groups.items():
                _longs: list = []
                for _r in _grp:
                    _q = _r.qty or 1.0
                    if _r.action == "BUY":
                        _longs.append(_r)
                    elif _r.action == "SELL" and _longs:
                        _e = _longs.pop(0)
                        realized_trades.append({
                            "strategy": _strat,
                            "symbol":   _sym,
                            "pnl":      round((_r.fill_price - _e.fill_price) * (_e.qty or 1.0), 4),
                            "timestamp": _r.timestamp.isoformat() if _r.timestamp else None,
                        })
        except Exception as _rt_exc:
            logger.debug("[PERFORMANCE] realized_trades fetch failed: %s", _rt_exc)

        return {
            "history": curve, "net_pnl": net_pnl,
            "drawdown": round(max_dd, 4), "has_data": len(curve) > 0,
            "sharpe": sharpe, "sortino": sortino,
            "realized_trades": realized_trades,
        }
    except Exception as e:
        logger.error("[PERFORMANCE] %s", e)
        return {"history": [], "net_pnl": 0.0, "drawdown": 0.0, "has_data": False,
                "sharpe": 0.0, "sortino": 0.0, "realized_trades": []}


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
async def get_llm_cost(period: str = "1M"):
    """
    Returns LLM Cost vs PnL analytics, filtered by period (1D|1W|1M|YTD).

    Response:
      - cumulative_cost:  [[ts_ms, running_total_usd], ...]
      - cumulative_pnl:   [[ts_ms, portfolio_profit_loss_usd], ...]
      - daily_rows:       [{date, pnl_usd, cost_usd, ratio}] — daily breakdown
      - total_cost_usd, total_pnl_usd, cumulative_ratio — top-level KPIs
    All timestamps in the response are UTC epoch ms; frontend converts to locale.
    """
    from datetime import datetime, timedelta, timezone

    period_days = {"1D": 1, "1W": 7, "1M": 30, "YTD": 180}
    days_back   = period_days.get(period.upper(), 30)
    cutoff      = datetime.now(timezone.utc) - timedelta(days=days_back)

    alpaca_period_map = {
        "1D": ("1D", "1Min"), "1W": ("1W", "1H"), "1M": ("1M", "1D"), "YTD": ("6M", "1D"),
    }
    alpaca_period, alpaca_tf = alpaca_period_map.get(period.upper(), ("1M", "1D"))

    try:
        from db.database import _get_session_factory
        from db.models import LLMUsage
        from sqlalchemy import select

        async with _get_session_factory()() as session:
            cost_rows = (await session.execute(
                select(LLMUsage.timestamp, LLMUsage.cost_usd)
                .where(LLMUsage.timestamp >= cutoff)
                .order_by(LLMUsage.timestamp)
            )).fetchall()

        # Aggregate LLM costs by UTC date for daily table
        daily_cost: dict[str, float] = {}
        for ts, cost in cost_rows:
            if ts:
                day = ts.strftime("%Y-%m-%d")
                daily_cost[day] = daily_cost.get(day, 0.0) + (cost or 0.0)

        # Cumulative cost series (epoch ms, running total)
        cum_cost = 0.0
        cost_series: list[list] = []
        for ts, cost in cost_rows:
            if ts:
                cum_cost += cost or 0
                cost_series.append([int(ts.timestamp() * 1000), round(cum_cost, 6)])

        # Fetch portfolio daily PnL from Alpaca
        pnl_series: list[list] = []
        daily_pnl:  dict[str, float] = {}
        cum_pnl = 0.0
        try:
            if trading_client:
                hist        = trading_client.get("/account/portfolio/history",
                                                 {"period": alpaca_period, "timeframe": alpaca_tf})
                timestamps  = hist.get("timestamp") or []
                profit_loss = hist.get("profit_loss") or []
                for i, ts_epoch in enumerate(timestamps):
                    if i < len(profit_loss) and profit_loss[i] is not None:
                        cum_pnl = profit_loss[i]
                        pnl_series.append([ts_epoch * 1000, round(cum_pnl, 2)])
                        # Only map to calendar date for daily-bar timeframes
                        if alpaca_tf == "1D":
                            day = datetime.utcfromtimestamp(ts_epoch).strftime("%Y-%m-%d")
                            daily_pnl[day] = round(profit_loss[i], 2)
        except Exception as pnl_err:
            logger.debug("[ANALYTICS] portfolio history: %s", pnl_err)

        # Daily breakdown table — union of all dates that have cost or PnL
        all_days   = sorted(set(list(daily_cost.keys()) + list(daily_pnl.keys())))
        daily_rows = []
        for day in all_days:
            pnl_d  = daily_pnl.get(day, 0.0)
            cost_d = daily_cost.get(day, 0.0)
            ratio  = round(pnl_d / cost_d, 2) if cost_d > 0 else None
            daily_rows.append({"date": day, "pnl_usd": round(pnl_d, 2),
                                "cost_usd": round(cost_d, 6), "ratio": ratio})

        total_cost       = sum(r["cost_usd"] for r in daily_rows)
        cumulative_ratio = round(cum_pnl / total_cost, 2) if total_cost > 0 else None

        return {
            "has_data":         bool(cost_series or pnl_series),
            "cumulative_cost":  cost_series,
            "cumulative_pnl":   pnl_series,
            "daily_rows":       daily_rows[-30:],   # cap at 30 days for chart rendering
            "total_cost_usd":   round(total_cost, 6),
            "total_pnl_usd":    round(cum_pnl, 2),
            "cumulative_ratio": cumulative_ratio,   # total PnL ÷ total LLM spend
        }

    except Exception as e:
        logger.error("[ANALYTICS] llm-cost failed: %s", e)
        return {"has_data": False, "cumulative_cost": [], "cumulative_pnl": [],
                "daily_rows": [], "cumulative_ratio": None}


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


@app.get("/api/ohlcv")
async def get_ohlcv(symbol: str = "BTC/USD", period: str = "1H"):
    """
    Returns OHLCV bars in lightweight-charts format for the TradingChart component.
    Supports both crypto (BTC/USD) and equity (SPY, AAPL, ...) symbols.
    period: "1H" = hourly bars for last 7 days, "1D" = daily bars for last 90 days.
    Response: { candles: [{time, open, high, low, close, volume}], symbol }
    time is Unix seconds (UTC) as required by lightweight-charts.
    """
    if not ALPACA_API_KEY:
        return {"candles": [], "symbol": symbol, "error": "API keys not configured"}
    try:
        from alpaca.data.timeframe import TimeFrame
        from datetime import datetime, timedelta

        is_crypto = "/" in symbol
        tf     = TimeFrame.Hour if period.upper() == "1H" else TimeFrame.Day
        window = timedelta(days=7) if period.upper() == "1H" else timedelta(days=90)
        start  = datetime.utcnow() - window
        end    = datetime.utcnow()

        if is_crypto:
            from alpaca.data.historical import CryptoHistoricalDataClient
            from alpaca.data.requests import CryptoBarsRequest
            client = CryptoHistoricalDataClient(ALPACA_API_KEY, ALPACA_API_SECRET)
            req    = CryptoBarsRequest(symbol_or_symbols=symbol, timeframe=tf, start=start, end=end)
            bars   = client.get_crypto_bars(req)
        else:
            from alpaca.data.historical import StockHistoricalDataClient
            from alpaca.data.requests import StockBarsRequest
            client = StockHistoricalDataClient(ALPACA_API_KEY, ALPACA_API_SECRET)
            req    = StockBarsRequest(symbol_or_symbols=symbol, timeframe=tf, start=start, end=end)
            bars   = client.get_stock_bars(req)

        if bars.df.empty:
            return {"candles": [], "symbol": symbol}

        candles = []
        for idx, row in bars.df.iterrows():
            ts = idx[1] if isinstance(idx, tuple) else idx
            candles.append({
                "time":   int(ts.timestamp()),
                "open":   float(row["open"]),
                "high":   float(row["high"]),
                "low":    float(row["low"]),
                "close":  float(row["close"]),
                "volume": float(row["volume"]),
            })
        logger.info("[OHLCV] %s %s — %d bars", symbol, period, len(candles))
        return {"candles": candles, "symbol": symbol}
    except Exception as e:
        logger.error("[OHLCV] %s", e)
        return {"candles": [], "symbol": symbol, "error": str(e)}

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


class _ManagedStockStream:
    """
    Thin wrapper around StockDataStream that overrides _run_forever() so that
    'connection limit exceeded' ValueErrors PROPAGATE to the caller instead of
    being swallowed by the SDK's internal retry loop.

    Mirrors _ManagedCryptoStream exactly — see that class for full rationale.
    """

    def __new__(cls, key: str, secret: str):
        from alpaca.data.live import StockDataStream

        stream = StockDataStream(key, secret)

        async def _managed_run_forever():
            import asyncio as _asyncio
            import websockets

            stream._loop = _asyncio.get_running_loop()

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
                        raise
                    await stream.close()
                    stream._running = False
                    logger.warning("[EQUITY STREAM] ValueError in stream: %s", e)
                except websockets.exceptions.WebSocketException as wse:
                    await stream.close()
                    stream._running = False
                    logger.warning("[EQUITY STREAM] WebSocket error, reconnecting: %s", wse)
                except Exception:
                    raise
                finally:
                    await _asyncio.sleep(0)

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
                                    _entry_times[key]  = exec_result.timestamp
                                    _persist_entry_prices(_entry_prices)
                                    master_engine.update_yield(signal['bot'], 0.0)
                                    master_engine.notify_fill(signal['bot'], symbol, 'BUY', exec_result.fill_price)
                                else:
                                    entry      = _entry_prices.pop(key, exec_result.fill_price)
                                    entry_time = _entry_times.pop(key, None)
                                    _persist_entry_prices(_entry_prices)
                                    realized_pnl = (exec_result.fill_price - entry) * exec_result.qty
                                    master_engine.update_yield(signal['bot'], realized_pnl)
                                    master_engine.notify_fill(signal['bot'], symbol, 'SELL')
                                    asyncio.create_task(_write_closed_trade(
                                        bot_id=signal['bot'], symbol=symbol, direction="LONG",
                                        entry_exec_id=None, exit_exec_id=None,
                                        entry_price=entry, exit_price=exec_result.fill_price,
                                        qty=exec_result.qty,
                                        entry_time=entry_time, exit_time=exec_result.timestamp,
                                    ))
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

            # Use the engine's dynamic symbol set — updated by scanner discoveries
            _crypto_syms = list(master_engine.active_crypto_symbols)
            stream.subscribe_bars(bar_callback, *_crypto_syms)
            stream.subscribe_quotes(quote_callback, *_crypto_syms)
            logger.info("[STREAM] Subscribed to crypto symbols: %s", _crypto_syms)

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


EQUITY_STREAM_SYMBOLS = ["SPY", "QQQ", "AAPL", "MSFT", "NVDA", "TSLA", "AMZN", "GOOGL"]

async def equity_stream_manager():
    """
    Manages the Alpaca StockDataStream for US equity symbols.
    Feeds bars into master_engine just like the crypto stream, but only
    routes to EQUITY and OPTIONS strategy bots via asset-class routing in process_tick().
    Runs in parallel with stream_manager(); equity market hours are enforced inside
    each strategy's analyze() — no need to gate here.
    """
    from strategy.equity_algorithms import _is_market_hours
    backoff = 10
    max_backoff = 120
    attempts = 0
    max_attempts = 15

    while attempts < max_attempts:
        try:
            stock_stream = _ManagedStockStream(ALPACA_API_KEY, ALPACA_API_SECRET)

            async def equity_bar_callback(bar):
                price  = float(bar.close)
                symbol = bar.symbol
                market_buffer.ingest_bar(symbol, bar)
                await broadcast({"type": "TICK", "data": {
                    "symbol": symbol, "price": price,
                    "volume": bar.volume, "timestamp": bar.timestamp.isoformat()
                }})
                signal_price = price
                for signal in master_engine.process_tick(symbol, price):
                    meta_str = ", ".join(f"{k}={v}" for k, v in signal.get("meta", {}).items())
                    _push_log(
                        f"[{signal['bot'].upper()}] {signal['action']} signal on {symbol} "
                        f"@ ${price:,.2f} (conf: {signal['confidence']}) {meta_str}"
                    )
                    equity_bal = 0.0
                    try:
                        if trading_client:
                            equity_bal = float(trading_client.get_account().equity)
                    except Exception:
                        pass
                    from risk.kill_switch import global_kill_switch
                    global_kill_switch.evaluate_portfolio(equity_bal)
                    approved = risk_agent.process(signal, equity_bal)
                    if approved:
                        _push_log(
                            f"[RISK AGENT] \u2713 Approved {approved['action']} {symbol} "
                            f"qty={approved['qty']:.6f} notional=${approved.get('notional', 0):.2f}"
                        )
                        if trading_client:
                            exec_result = execution_agent.execute(approved, signal_price=signal_price)
                            if exec_result:
                                key = (signal['bot'], symbol)
                                if approved['action'] == 'BUY':
                                    _entry_prices[key] = exec_result.fill_price
                                    _entry_times[key]  = exec_result.timestamp
                                    _persist_entry_prices(_entry_prices)
                                    master_engine.update_yield(signal['bot'], 0.0)
                                    master_engine.notify_fill(signal['bot'], symbol, 'BUY', exec_result.fill_price)
                                else:
                                    entry      = _entry_prices.pop(key, exec_result.fill_price)
                                    entry_time = _entry_times.pop(key, None)
                                    _persist_entry_prices(_entry_prices)
                                    realized_pnl = (exec_result.fill_price - entry) * exec_result.qty
                                    master_engine.update_yield(signal['bot'], realized_pnl)
                                    master_engine.notify_fill(signal['bot'], symbol, 'SELL')
                                    asyncio.create_task(_write_closed_trade(
                                        bot_id=signal['bot'], symbol=symbol, direction="LONG",
                                        entry_exec_id=None, exit_exec_id=None,
                                        entry_price=entry, exit_price=exec_result.fill_price,
                                        qty=exec_result.qty,
                                        entry_time=entry_time, exit_time=exec_result.timestamp,
                                    ))
                                _push_log(
                                    f"[EXECUTION] FILLED #{exec_result.order_id[:8]} \u2014 "
                                    f"{approved['action']} {symbol} qty={exec_result.qty:.6f} "
                                    f"fill=${exec_result.fill_price:.2f}"
                                )
                    else:
                        _push_log(f"[RISK AGENT] \u2717 Blocked {signal['action']} {symbol} \u2014 risk gate rejected.")

            stock_stream.subscribe_bars(equity_bar_callback, *EQUITY_STREAM_SYMBOLS)
            logger.info("[EQUITY STREAM] Starting Alpaca StockDataStream for %s", EQUITY_STREAM_SYMBOLS)
            _push_log("[EQUITY STREAM] Connecting to Alpaca equity data stream...")

            import concurrent.futures
            loop = asyncio.get_running_loop()
            with concurrent.futures.ThreadPoolExecutor(max_workers=1) as executor:
                future = loop.run_in_executor(executor, stock_stream.run)
                try:
                    await future
                except concurrent.futures.CancelledError:
                    stock_stream.stop()
                    return

            logger.info("[EQUITY STREAM] Stream ended, reconnecting...")
            backoff = 10
            attempts = 0

        except asyncio.CancelledError:
            logger.info("[EQUITY STREAM] Task cancelled cleanly.")
            return

        except Exception as e:
            err_str = str(e).lower()
            attempts += 1

            if "connection limit" in err_str:
                wait = 65
                logger.warning(
                    "[EQUITY STREAM] Connection limit hit (attempt %d/%d). "
                    "Waiting %ds for Alpaca to release stale connection...",
                    attempts, max_attempts, wait,
                )
                _push_log(f"[EQUITY STREAM] \u23f3 Alpaca connection limit \u2014 waiting {wait}s for stale session to expire...")
                await asyncio.sleep(wait)
            else:
                logger.warning("[EQUITY STREAM] Error (attempt %d/%d): %s", attempts, max_attempts, e)
                _push_log(f"[EQUITY STREAM] Error \u2014 retrying in {backoff}s ({attempts}/{max_attempts})...")
                await asyncio.sleep(backoff)
                backoff = min(backoff * 2, max_backoff)

    logger.error("[EQUITY STREAM] Max reconnect attempts reached. Equity stream suspended.")
    _push_log("[EQUITY STREAM] \u274c Equity stream suspended after max retries.")


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


@app.get("/api/analytics/realized-pnl")
async def get_realized_pnl():
    """
    Pairs BUY → SELL ExecutionRecords (via SignalRecord join) to compute realized P&L per trade.
    Returns a list of closed trades with entry price, exit price, qty, and net P&L.
    Falls back to in-memory _entry_prices for any currently open positions.
    """
    from db.database import _get_session_factory
    from db.models import ExecutionRecord, SignalRecord
    from sqlalchemy import select, and_

    try:
        async with _get_session_factory()() as session:
            # Load all filled execution records joined to their signal for action + strategy + symbol
            stmt = (
                select(
                    ExecutionRecord.id,
                    ExecutionRecord.fill_price,
                    ExecutionRecord.qty,
                    ExecutionRecord.timestamp,
                    SignalRecord.strategy,
                    SignalRecord.symbol,
                    SignalRecord.action,
                    SignalRecord.confidence,
                )
                .join(SignalRecord, ExecutionRecord.signal_id == SignalRecord.id)
                .where(ExecutionRecord.status == "FILLED")
                .order_by(SignalRecord.strategy, SignalRecord.symbol, ExecutionRecord.timestamp)
            )
            rows = (await session.execute(stmt)).all()

        # Group by (strategy, symbol) and pair BUY → SELL in chronological order (FIFO).
        # LONG trades: entry=BUY, exit=SELL → pnl = (exit - entry) * qty
        # SHORT trades: entry=SELL, exit=BUY → pnl = (entry - exit) * qty
        from collections import defaultdict
        groups: dict = defaultdict(list)
        for row in rows:
            groups[(row.strategy, row.symbol)].append(row)

        trades = []
        for (strategy, symbol), group_rows in groups.items():
            open_longs: list  = []  # stack of BUY rows awaiting a SELL
            open_shorts: list = []  # stack of SELL rows awaiting a BUY (SHORT entry)
            for row in group_rows:
                qty = row.qty or 1.0
                if row.action == "BUY":
                    if open_shorts:
                        # Close a SHORT: entry was SELL, exit is BUY
                        entry_row = open_shorts.pop(0)
                        entry_qty = entry_row.qty or 1.0
                        pnl = (entry_row.fill_price - row.fill_price) * entry_qty
                        trades.append({
                            "strategy":   strategy,
                            "symbol":     symbol,
                            "direction":  "SHORT",
                            "entry_price": round(entry_row.fill_price, 4),
                            "exit_price":  round(row.fill_price, 4),
                            "qty":         round(entry_qty, 6),
                            "pnl":         round(pnl, 4),
                            "entry_time":  entry_row.timestamp.isoformat() if entry_row.timestamp else None,
                            "exit_time":   row.timestamp.isoformat() if row.timestamp else None,
                            "confidence":  round(entry_row.confidence or 0, 3),
                        })
                    else:
                        open_longs.append(row)
                elif row.action == "SELL":
                    if open_longs:
                        # Close a LONG: entry was BUY, exit is SELL
                        entry_row = open_longs.pop(0)
                        entry_qty = entry_row.qty or 1.0
                        pnl = (row.fill_price - entry_row.fill_price) * entry_qty
                        trades.append({
                            "strategy":   strategy,
                            "symbol":     symbol,
                            "direction":  "LONG",
                            "entry_price": round(entry_row.fill_price, 4),
                            "exit_price":  round(row.fill_price, 4),
                            "qty":         round(entry_qty, 6),
                            "pnl":         round(pnl, 4),
                            "entry_time":  entry_row.timestamp.isoformat() if entry_row.timestamp else None,
                            "exit_time":   row.timestamp.isoformat() if row.timestamp else None,
                            "confidence":  round(entry_row.confidence or 0, 3),
                        })
                    else:
                        open_shorts.append(row)

        # Add currently open positions from in-memory dict
        open_positions = [
            {
                "strategy":   bot,
                "symbol":     sym,
                "direction":  "LONG",
                "entry_price": round(price, 4),
                "exit_price":  None,
                "qty":         None,
                "pnl":         None,
                "entry_time":  None,
                "exit_time":   None,
                "confidence":  None,
                "open":        True,
            }
            for (bot, sym), price in _entry_prices.items()
        ]

        return {"trades": trades, "open_positions": open_positions, "total_closed": len(trades)}

    except Exception as e:
        logger.error("[REALIZED PNL] %s", e)
        return {"trades": [], "open_positions": [], "total_closed": 0, "error": str(e)}


@app.get("/api/strategy/states")
def get_strategy_states():
    """Returns current internal indicator state for all active strategies.
    Powers the Strategy Mental Model panel in the Brain tab."""
    return master_engine.get_all_states()


_scanner_agent = None
_scanner_task: Optional[asyncio.Task] = None
_ENTRY_PRICES_FILE = os.path.join(os.path.dirname(__file__), "_entry_prices.json")

def _load_entry_prices() -> dict[tuple, float]:
    """Restores entry prices from disk so restarts don't lose open-position cost basis."""
    try:
        with open(_ENTRY_PRICES_FILE, "r") as f:
            raw: dict[str, float] = json.load(f)
        result = {}
        for k, v in raw.items():
            parts = k.split("|", 1)
            if len(parts) == 2:
                result[(parts[0], parts[1])] = float(v)
        logger.info("[ENTRY PRICES] Restored %d open positions from disk", len(result))
        return result
    except FileNotFoundError:
        return {}
    except Exception as e:
        logger.warning("[ENTRY PRICES] Failed to restore from disk: %s", e)
        return {}

def _persist_entry_prices(entry_prices: dict[tuple, float]):
    """Writes current entry-price map to disk after every fill."""
    try:
        raw = {f"{bot}|{sym}": price for (bot, sym), price in entry_prices.items()}
        with open(_ENTRY_PRICES_FILE, "w") as f:
            json.dump(raw, f)
    except Exception as e:
        logger.warning("[ENTRY PRICES] Failed to persist to disk: %s", e)

_entry_prices: dict[tuple, float] = _load_entry_prices()  # (bot_id, symbol) → BUY fill price
# Tracks BUY fill timestamp for ClosedTrade reconciliation — (bot_id, symbol) → ISO timestamp str
_entry_times: dict[tuple, str] = {}


@app.get("/api/watchlist")
def get_watchlist():
    """Returns the latest scanner results (TA scores + Haiku verdicts)."""
    if _scanner_agent is None:
        return []
    return _scanner_agent.get_last_results()


@app.get("/api/market/pulse")
def get_market_pulse():
    """
    Returns a price snapshot for major market symbols across indices, FX proxies, and crypto.
    Used by the MarketPulse sentiment panel on the Desk tab.
    Returns: list of {symbol, name, price, change_pct, category}
    """
    results = []

    # ── Equity / Index ETFs ─────────────────────────────────────────────────
    INDEX_SYMBOLS = ["SPY", "QQQ", "DIA", "IWM", "VIX"]
    INDEX_NAMES = {"SPY": "S&P 500", "QQQ": "NASDAQ 100", "DIA": "Dow Jones",
                   "IWM": "Russell 2000", "VIX": "VIX"}
    if ALPACA_API_KEY:
        try:
            from alpaca.data.historical import StockHistoricalDataClient
            from alpaca.data.requests import StockSnapshotRequest
            stock_client = StockHistoricalDataClient(ALPACA_API_KEY, ALPACA_API_SECRET)
            snap_req = StockSnapshotRequest(symbol_or_symbols=INDEX_SYMBOLS)
            snaps = stock_client.get_stock_snapshot(snap_req)
            for sym in INDEX_SYMBOLS:
                snap = snaps.get(sym)
                if snap and snap.latest_trade:
                    price = float(snap.latest_trade.price)
                    # daily change from daily_bar open if available
                    change_pct = 0.0
                    if snap.daily_bar:
                        open_px = float(snap.daily_bar.open)
                        change_pct = ((price - open_px) / open_px * 100) if open_px else 0.0
                    results.append({
                        "symbol": sym,
                        "name": INDEX_NAMES.get(sym, sym),
                        "price": round(price, 2),
                        "change_pct": round(change_pct, 3),
                        "category": "indices",
                    })
        except Exception as e:
            logger.warning("[MARKET PULSE] Equity snapshots failed: %s", e)

    # ── Crypto ─────────────────────────────────────────────────────────────
    CRYPTO_SYMBOLS = ["BTC/USD", "ETH/USD", "SOL/USD"]
    CRYPTO_NAMES = {"BTC/USD": "Bitcoin", "ETH/USD": "Ethereum", "SOL/USD": "Solana"}
    if ALPACA_API_KEY:
        try:
            from alpaca.data.historical import CryptoHistoricalDataClient
            from alpaca.data.requests import CryptoSnapshotRequest
            crypto_client = CryptoHistoricalDataClient(ALPACA_API_KEY, ALPACA_API_SECRET)
            snap_req = CryptoSnapshotRequest(symbol_or_symbols=CRYPTO_SYMBOLS)
            snaps = crypto_client.get_crypto_snapshot(snap_req)
            for sym in CRYPTO_SYMBOLS:
                snap = snaps.get(sym)
                if snap and snap.latest_trade:
                    price = float(snap.latest_trade.price)
                    change_pct = 0.0
                    if snap.daily_bar:
                        open_px = float(snap.daily_bar.open)
                        change_pct = ((price - open_px) / open_px * 100) if open_px else 0.0
                    results.append({
                        "symbol": sym,
                        "name": CRYPTO_NAMES.get(sym, sym),
                        "price": round(price, 4 if price < 10 else 2),
                        "change_pct": round(change_pct, 3),
                        "category": "crypto",
                    })
        except Exception as e:
            logger.warning("[MARKET PULSE] Crypto snapshots failed: %s", e)

    # ── FX via ratio ETFs (Alpaca doesn't stream spot FX) ──────────────────
    FX_SYMBOLS = ["UUP", "FXE", "FXB"]
    FX_NAMES = {"UUP": "USD Index", "FXE": "EUR/USD", "FXB": "GBP/USD"}
    if ALPACA_API_KEY and FX_SYMBOLS:
        try:
            from alpaca.data.historical import StockHistoricalDataClient
            from alpaca.data.requests import StockSnapshotRequest
            stock_client = StockHistoricalDataClient(ALPACA_API_KEY, ALPACA_API_SECRET)
            snap_req = StockSnapshotRequest(symbol_or_symbols=FX_SYMBOLS)
            snaps = stock_client.get_stock_snapshot(snap_req)
            for sym in FX_SYMBOLS:
                snap = snaps.get(sym)
                if snap and snap.latest_trade:
                    price = float(snap.latest_trade.price)
                    change_pct = 0.0
                    if snap.daily_bar:
                        open_px = float(snap.daily_bar.open)
                        change_pct = ((price - open_px) / open_px * 100) if open_px else 0.0
                    results.append({
                        "symbol": sym,
                        "name": FX_NAMES.get(sym, sym),
                        "price": round(price, 2),
                        "change_pct": round(change_pct, 3),
                        "category": "fx",
                    })
        except Exception as e:
            logger.warning("[MARKET PULSE] FX snapshots failed: %s", e)

    return results


@app.post("/api/watchlist/scan")
async def trigger_scan():
    """Triggers an immediate on-demand symbol scan."""
    if _scanner_agent is None:
        raise HTTPException(status_code=503, detail="Scanner agent not initialized")
    results = await _scanner_agent.run_once()
    return {"status": "ok", "results": results}


# ==========================================
# MARKET NEWS + HAIKU COMMENTARY
# ==========================================

# In-memory commentary cache {generated_at: float, text: str}
_commentary_cache: dict = {"generated_at": 0.0, "text": None}
_COMMENTARY_TTL = 1800  # 30 minutes


@app.get("/api/market/news")
def get_market_news(symbols: str = "BTC,ETH,SPY,QQQ,AAPL"):
    """
    Returns latest news headlines from Alpaca's News API.
    symbols: comma-separated list of tickers (without /USD suffix).
    """
    if not ALPACA_API_KEY:
        return []
    try:
        import requests as _req
        sym_list = [s.strip() for s in symbols.split(",") if s.strip()]
        resp = _req.get(
            "https://data.alpaca.markets/v1beta1/news",
            params={"symbols": ",".join(sym_list), "limit": 20, "sort": "desc"},
            headers={
                "APCA-API-KEY-ID": ALPACA_API_KEY,
                "APCA-API-SECRET-KEY": ALPACA_API_SECRET,
            },
            timeout=8,
        )
        if not resp.ok:
            logger.warning("[NEWS] Alpaca news returned %s", resp.status_code)
            return []
        data = resp.json()
        articles = data.get("news", [])
        return [
            {
                "id":        a.get("id"),
                "headline":  a.get("headline"),
                "summary":   a.get("summary", ""),
                "source":    a.get("source"),
                "url":       a.get("url"),
                "symbols":   a.get("symbols", []),
                "published": a.get("created_at"),
            }
            for a in articles
        ]
    except Exception as e:
        logger.warning("[NEWS] %s", e)
        return []


@app.get("/api/market/commentary")
async def get_market_commentary(force: bool = False):
    """
    Returns a cached Claude Haiku market commentary (refreshed every 30 min).
    Pass ?force=true to regenerate immediately.
    Covers: macro sentiment, crypto, equities, open positions, watchlist.
    """
    global _commentary_cache

    now = time.time()
    if not force and _commentary_cache["text"] and (now - _commentary_cache["generated_at"]) < _COMMENTARY_TTL:
        return {"text": _commentary_cache["text"], "generated_at": _commentary_cache["generated_at"], "cached": True}

    ANTHROPIC_API_KEY = os.getenv("ANTHROPIC_API_KEY")
    if not ANTHROPIC_API_KEY:
        return {"text": None, "error": "ANTHROPIC_API_KEY not set"}

    # Gather context: bot states + positions
    try:
        bot_states = master_engine.get_bot_states()
        bot_summary = ", ".join(
            f"{b['name']} ({b['status']}, yield24h=${b['yield24h']:.2f})"
            for b in bot_states
        )
        pos_list = []
        if trading_client:
            try:
                raw_pos = trading_client.get_all_positions()
                pos_list = [f"{p.symbol} {p.side} qty={p.qty} unrealPnL=${p.unrealized_pl}" for p in raw_pos]
            except Exception:
                pass
        pos_summary = ", ".join(pos_list) if pos_list else "No open positions"

        prompt = (
            f"You are a quantitative trading analyst. Provide a concise, data-driven market commentary in 3-4 short paragraphs covering:\n"
            f"1. Overall macro sentiment (risk-on/risk-off, key market levels)\n"
            f"2. Crypto market (BTC, ETH, SOL trends)\n"
            f"3. Equities outlook (SPY, QQQ, sector rotation)\n"
            f"4. Portfolio focus: Active strategies: {bot_summary}. Positions: {pos_summary}\n\n"
            f"Be concise, use specific numbers where relevant, and give actionable insights. "
            f"Avoid generic disclaimers. Write for a quantitative trader."
        )

        from anthropic import Anthropic
        client = Anthropic(api_key=ANTHROPIC_API_KEY)
        msg = client.messages.create(
            model="claude-haiku-4-5-20251001",
            max_tokens=512,
            messages=[{"role": "user", "content": prompt}],
        )
        text = msg.content[0].text if msg.content else None
        _commentary_cache = {"generated_at": now, "text": text}
        return {"text": text, "generated_at": now, "cached": False}
    except Exception as e:
        logger.error("[COMMENTARY] %s", e)
        return {"text": None, "error": str(e)}


async def _portfolio_snapshot_loop():
    """Background loop: write a PortfolioSnapshot every 60 seconds."""
    from db.database import _get_session_factory
    from db.models import PortfolioSnapshot
    from risk.kill_switch import global_kill_switch
    await asyncio.sleep(30)  # let streams connect first
    while True:
        try:
            equity = 0.0
            if trading_client:
                try:
                    equity = float(trading_client.get_account().equity)
                except Exception:
                    pass
            drawdown_pct = 0.0
            try:
                ks = global_kill_switch
                if hasattr(ks, 'start_of_day_equity') and ks.start_of_day_equity > 0:
                    drawdown_pct = max(0.0, (ks.start_of_day_equity - equity) / ks.start_of_day_equity)
            except Exception:
                pass
            async with _get_session_factory()() as _s:
                _s.add(PortfolioSnapshot(equity=equity, drawdown_pct=drawdown_pct))
                await _s.commit()
        except Exception as snap_err:
            logger.debug("[SNAPSHOT] %s", snap_err)
        await asyncio.sleep(60)


async def _write_closed_trade(
    bot_id: str,
    symbol: str,
    direction: str,
    entry_exec_id: int | None,
    exit_exec_id: int | None,
    entry_price: float,
    exit_price: float,
    qty: float,
    entry_time,
    exit_time,
):
    """Persist a FIFO-matched round-trip trade to the closed_trades table."""
    from db.database import _get_session_factory
    from db.models import ClosedTrade
    realized_pnl = (exit_price - entry_price) * qty if direction == "LONG" else (entry_price - exit_price) * qty
    try:
        async with _get_session_factory()() as _s:
            _s.add(ClosedTrade(
                bot_id=bot_id,
                symbol=symbol,
                direction=direction,
                entry_execution_id=entry_exec_id,
                exit_execution_id=exit_exec_id,
                entry_price=entry_price,
                exit_price=exit_price,
                qty=qty,
                realized_pnl=realized_pnl,
                entry_time=entry_time,
                exit_time=exit_time,
            ))
            await _s.commit()
    except Exception as e:
        logger.warning("[CLOSED TRADE] Failed to persist: %s", e)


@app.on_event("startup")
async def startup_event():
    global _stream_task, _stock_stream_task, _ai_reflection_task, _reflection_engine, _scanner_agent, _scanner_task
    from db.database import init_db
    await init_db()

    # Restore persisted bot halt/resume states so bots don't auto-restart as ACTIVE
    try:
        from db.database import _get_session_factory
        from db.models import BotState, BotAmend
        from sqlalchemy import select as _select
        import json as _json
        async with _get_session_factory()() as _session:
            _bot_states = (await _session.execute(_select(BotState))).scalars().all()
            master_engine.restore_from_db([
                {"bot_id": s.bot_id, "status": s.status, "allocation": float(s.allocation)}
                for s in _bot_states
            ])
            # Re-apply the latest UPDATE_STRATEGY_PARAMS amend for each bot
            _amends = (await _session.execute(
                _select(BotAmend)
                .where(BotAmend.action == "UPDATE_STRATEGY_PARAMS")
                .order_by(BotAmend.timestamp)
            )).scalars().all()
            for _amend in _amends:
                if _amend.target_bot and _amend.params_json:
                    try:
                        _params = _json.loads(_amend.params_json)
                        master_engine.update_strategy_params(_amend.target_bot, _params)
                    except Exception as _pe:
                        logger.debug("[STARTUP] BotAmend re-apply failed for %s: %s", _amend.target_bot, _pe)
    except Exception as _exc:
        logger.warning("[STARTUP] BotState restore failed: %s", _exc)

    _get_log_queue()
    _get_reflection_queue()
    logger.info("Multi-Agent REST/WS Gateway booted (paper=%s).", PAPER_TRADING)
    _push_log("[SYSTEM] Trading Engine Online — initializing stream...")
    if ALPACA_API_KEY and ALPACA_API_SECRET:
        _stream_task = asyncio.create_task(stream_manager())
        _stock_stream_task = asyncio.create_task(equity_stream_manager())

    # Start the reflection engine
    from agents.reflection_engine import ReflectionEngine
    _reflection_engine = ReflectionEngine(
        push_fn=_push_reflection,
        get_states_fn=master_engine.get_all_states,
        get_positions_fn=_get_positions_for_reflection,
    )
    _ai_reflection_task = asyncio.create_task(_reflection_engine.run())

    # Start portfolio snapshot loop (60s cadence)
    asyncio.create_task(_portfolio_snapshot_loop())
    logger.info("[SNAPSHOT] Portfolio snapshot loop started (60s cadence)")

    # Start the scanner agent — wrap push_fn to intercept "discover" events and
    # propagate newly discovered symbols into the strategy engine's routing table.
    from agents.scanner_agent import ScannerAgent
    from quant.data_buffer import market_buffer as _mb

    def _scanner_push(data: dict) -> None:
        _push_reflection(data)
        if data.get("type") == "discover":
            symbols: list[str] = data.get("symbols", [])
            if symbols:
                master_engine.set_active_crypto_symbols(set(symbols))
                logger.info("[SCANNER→ENGINE] Symbol set updated: %s", symbols)

    _scanner_agent = ScannerAgent(
        push_fn=_scanner_push,
        get_buffer_fn=lambda: _mb,
    )
    _scanner_task = asyncio.create_task(_scanner_agent.run())

    # Start the Autonomous Portfolio Director — reviews bots every 15 min and
    # executes Haiku-recommended changes (allocations, params, halt/resume, variants)
    from agents.portfolio_director import AutonomousPortfolioDirector
    from db.database import _get_session_factory as _gsf_director
    _director = AutonomousPortfolioDirector(
        push_fn        = _push_reflection,
        get_engine_fn  = lambda: master_engine,
        get_scanner_fn = lambda: _scanner_agent.get_last_results() if _scanner_agent else [],
        db_factory     = _gsf_director,
    )
    asyncio.create_task(_director.run())
    logger.info("[DIRECTOR] Autonomous Portfolio Director scheduled (15 min interval)")


@app.on_event("shutdown")
async def shutdown_event():
    global _stream_task, _stock_stream_task, _ai_reflection_task, _scanner_task
    for task in (_stream_task, _stock_stream_task, _ai_reflection_task, _scanner_task):
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
