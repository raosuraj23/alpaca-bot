import logging
import os
import time
from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field
from deps import ALPACA_API_KEY, ALPACA_API_SECRET, PAPER_TRADING, get_trading_client
from strategy.engine import master_engine
from agents.risk_agent import risk_agent
from agents.execution_agent import execution_agent
from core import state as core_state
from core.state import _push_log
from state import action_items as _ai_state

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/api")

_commentary_cache: dict = {"generated_at": 0.0, "text": None}
_COMMENTARY_TTL = 1800
_ACTION_ITEMS_TTL = 600

class OrderRequest(BaseModel):
    symbol: str = Field(default="BTC/USD", description="Trading symbol")
    side: str = Field(default="BUY", description="BUY or SELL")
    qty: float = Field(default=0.01, gt=0, description="Order quantity")


@router.post("/seed")
def place_order(payload: OrderRequest):
    """Places a market order via the full risk+execution pipeline."""
    if not PAPER_TRADING:
        raise HTTPException(status_code=403, detail="Live trading orders must go through the execution agent pipeline.")

    client = get_trading_client()
    price = master_engine.get_last_price(payload.symbol) or 0.0
    synthetic_signal = {
        "action": payload.side.upper(),
        "symbol": payload.symbol,
        "price": price,
        "confidence": 1.0,
        "bot": "tradepanel",
        "meta": {"source": "manual_ui"},
    }

    equity = 0.0
    try:
        equity = float(client.get_account().equity)
    except Exception:
        pass

    from risk.kill_switch import global_kill_switch
    global_kill_switch.evaluate_portfolio(equity)

    approved = risk_agent.process(synthetic_signal, equity)
    if not approved:
        raise HTTPException(status_code=403, detail="Risk gate rejected order (kill switch active or position limits exceeded).")

    approved["qty"] = payload.qty
    exec_result = execution_agent.execute(approved, signal_price=price)
    if not exec_result:
        raise HTTPException(status_code=502, detail="Execution failed — check trading_client and API keys.")

    _push_log(
        f"[TRADEPANEL] FILLED #{exec_result.order_id[:8]} — {payload.side.upper()} {payload.symbol} qty={exec_result.qty:.6f} fill=${exec_result.fill_price:.2f} slip=${exec_result.slippage:.4f}"
    )
    logger.info("[ORDER] FILLED %s %s qty=%.6f fill=%.2f", payload.side, payload.symbol, exec_result.qty, exec_result.fill_price)
    return {"status": "submitted", "order_id": exec_result.order_id}


@router.post("/backtest")
def run_backtest_endpoint(payload: dict):
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
            "net_profit": result.net_profit,
            "max_drawdown": result.max_drawdown,
            "profit_factor": result.profit_factor,
            "total_trades": result.total_trades,
            "win_rate": result.win_rate,
            "sharpe_ratio": result.sharpe_ratio,
            "equity_curve": result.equity_curve,
            "error": result.error,
        }
    except Exception as e:
        logger.error("[BACKTEST] %s", e)
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/market/history")
def get_market_history(symbol: str = "BTC/USD"):
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
            end=datetime.utcnow(),
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


@router.get("/ohlcv")
async def get_ohlcv(symbol: str = "BTC/USD", period: str = "1H"):
    if not ALPACA_API_KEY:
        return {"candles": [], "symbol": symbol, "error": "API keys not configured"}

    try:
        from alpaca.data.timeframe import TimeFrame
        from datetime import datetime, timedelta

        is_crypto = "/" in symbol
        tf = TimeFrame.Hour if period.upper() == "1H" else TimeFrame.Day
        window = timedelta(days=7) if period.upper() == "1H" else timedelta(days=90)
        start = datetime.utcnow() - window
        end = datetime.utcnow()

        if is_crypto:
            from alpaca.data.historical import CryptoHistoricalDataClient
            from alpaca.data.requests import CryptoBarsRequest
            client = CryptoHistoricalDataClient(ALPACA_API_KEY, ALPACA_API_SECRET)
            req = CryptoBarsRequest(symbol_or_symbols=symbol, timeframe=tf, start=start, end=end)
            bars = client.get_crypto_bars(req)
        else:
            from alpaca.data.historical import StockHistoricalDataClient
            from alpaca.data.requests import StockBarsRequest
            client = StockHistoricalDataClient(ALPACA_API_KEY, ALPACA_API_SECRET)
            req = StockBarsRequest(symbol_or_symbols=symbol, timeframe=tf, start=start, end=end)
            bars = client.get_stock_bars(req)

        if bars.df.empty:
            return {"candles": [], "symbol": symbol}

        candles = []
        for idx, row in bars.df.iterrows():
            ts = idx[1] if isinstance(idx, tuple) else idx
            candles.append({
                "time": int(ts.timestamp()),
                "open": float(row["open"]),
                "high": float(row["high"]),
                "low": float(row["low"]),
                "close": float(row["close"]),
                "volume": float(row["volume"]),
            })
        logger.info("[OHLCV] %s %s — %d bars", symbol, period, len(candles))
        return {"candles": candles, "symbol": symbol}
    except Exception as e:
        logger.error("[OHLCV] %s", e)
        return {"candles": [], "symbol": symbol, "error": str(e)}


@router.get("/watchlist")
def get_watchlist():
    if core_state.scanner_agent is None:
        return []
    return core_state.scanner_agent.get_last_results()


@router.get("/market/pulse")
def get_market_pulse():
    results = []

    INDEX_SYMBOLS = ["SPY", "QQQ", "DIA", "IWM", "VIX"]
    INDEX_NAMES = {"SPY": "S&P 500", "QQQ": "NASDAQ 100", "DIA": "Dow Jones", "IWM": "Russell 2000", "VIX": "VIX"}
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


@router.post("/watchlist/scan")
async def trigger_scan():
    if core_state.scanner_agent is None:
        raise HTTPException(status_code=503, detail="Scanner agent not initialized")
    results = await core_state.scanner_agent.run_once()
    return {"status": "ok", "results": results}


@router.get("/market/news")
def get_market_news(symbols: str = "BTC,ETH,SPY,QQQ,AAPL"):
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
                "id": a.get("id"),
                "headline": a.get("headline"),
                "summary": a.get("summary", ""),
                "source": a.get("source"),
                "url": a.get("url"),
                "symbols": a.get("symbols", []),
                "published": a.get("created_at"),
            }
            for a in articles
        ]
    except Exception as e:
        logger.warning("[NEWS] %s", e)
        return []


@router.get("/market/commentary")
async def get_market_commentary(force: bool = False):
    now = time.time()
    if not force and _commentary_cache["text"] and (now - _commentary_cache["generated_at"]) < _COMMENTARY_TTL:
        return {"text": _commentary_cache["text"], "generated_at": _commentary_cache["generated_at"], "cached": True}

    ANTHROPIC_API_KEY = os.getenv("ANTHROPIC_API_KEY")
    if not ANTHROPIC_API_KEY:
        return {"text": None, "error": "ANTHROPIC_API_KEY not set"}

    try:
        bot_states = master_engine.get_bot_states()
        bot_summary = ", ".join(
            f"{b['name']} ({b['status']}, yield24h=${b['yield24h']:.2f})"
            for b in bot_states
        )
        pos_list = []
        client = None
        try:
            client = get_trading_client()
        except Exception:
            pass
        if client:
            try:
                raw_pos = client.get_all_positions()
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
        from config import CLAUDE_HAIKU_MODEL
        client = Anthropic(api_key=ANTHROPIC_API_KEY)
        msg = client.messages.create(
            model=CLAUDE_HAIKU_MODEL,
            max_tokens=512,
            messages=[{"role": "user", "content": prompt}],
        )
        text = msg.content[0].text if msg.content else None
        _commentary_cache["generated_at"] = now
        _commentary_cache["text"] = text
        return {"text": text, "generated_at": now, "cached": False}
    except Exception as e:
        logger.error("[COMMENTARY] %s", e)
        return {"text": None, "error": str(e)}


@router.get("/market/action-items")
async def get_action_items(force: bool = False):
    from state import action_items as _ai_state

    now = time.time()
    cached_items = _ai_state.get_items()
    if not force and cached_items and (now - _ai_state.get_generated_at()) < _ACTION_ITEMS_TTL:
        return {"items": cached_items, "generated_at": _ai_state.get_generated_at(), "cached": True}

    ANTHROPIC_API_KEY = os.getenv("ANTHROPIC_API_KEY")
    if not ANTHROPIC_API_KEY:
        return {"items": [], "error": "ANTHROPIC_API_KEY not set"}

    try:
        bot_states = master_engine.get_bot_states()
        bot_win_rates_ctx = [
            f"{b['name']} ({b.get('algo','?')}) status={b['status']} yield24h=${b.get('yield24h',0):.2f} alloc={b.get('allocationPct',0):.0f}%"
            for b in bot_states
        ]
        pos_lines = []
        client = None
        try:
            client = get_trading_client()
        except Exception:
            pass
        if client:
            try:
                raw_pos = client.get_all_positions()
                for p in raw_pos:
                    pos_lines.append(
                        f"{p.symbol} {p.side} qty={p.qty} unrealPnL=${p.unrealized_pl} cost=${p.cost_basis}"
                    )
            except Exception:
                pass

        pos_ctx = "\n".join(pos_lines) if pos_lines else "No open positions"
        bot_ctx = "\n".join(bot_win_rates_ctx) if bot_win_rates_ctx else "No active bots"

        system_prompt = (
            "You are a quantitative portfolio analyst assistant. "
            "Analyze the live portfolio state and produce 3 to 5 structured action items. "
            "Each item must cite specific data (PnL, qty, win rate, spread). "
            "Urgency: HIGH = immediate risk or opportunity, MEDIUM = this session, LOW = watch. "
            "Types: LIQUIDATE (exit a losing/illiquid position), REACTIVATE (resume a halted strategy), "
            "HALT (pause an underperforming strategy), MONITOR (watch a price level or metric), "
            "ADJUST (change allocation or params). "
            "Be concise, data-driven, actionable."
        )
        user_prompt = f"Active bots:\n{bot_ctx}\n\nOpen positions:\n{pos_ctx}\n\nGenerate portfolio action items now."

        import anthropic as _anthropic
        from config import CLAUDE_HAIKU_MODEL

        client = _anthropic.Anthropic(api_key=ANTHROPIC_API_KEY)
        response = client.messages.create(
            model=CLAUDE_HAIKU_MODEL,
            max_tokens=1024,
            system=system_prompt,
            messages=[{"role": "user", "content": user_prompt}],
            tools=[{
                "name": "submit_action_items",
                "description": "Submit structured portfolio action items",
                "input_schema": {
                    "type": "object",
                    "properties": {
                        "items": {
                            "type": "array",
                            "items": {
                                "type": "object",
                                "required": ["type", "title", "reason", "urgency"],
                                "properties": {
                                    "type": {"type": "string", "enum": ["LIQUIDATE", "REACTIVATE", "HALT", "MONITOR", "ADJUST"]},
                                    "symbol": {"type": "string"},
                                    "strategy": {"type": "string"},
                                    "title": {"type": "string"},
                                    "reason": {"type": "string"},
                                    "urgency": {"type": "string", "enum": ["HIGH", "MEDIUM", "LOW"]},
                                },
                            },
                        },
                    },
                    "required": ["items"],
                },
            }],
            tool_choice={"type": "tool", "name": "submit_action_items"},
        )

        raw_items = []
        for block in response.content:
            if block.type == "tool_use" and block.name == "submit_action_items":
                raw_items = block.input.get("items", [])
                break

        validated = []
        for item in raw_items:
            try:
                from pydantic import BaseModel

                class _ActionItem(BaseModel):
                    type: str
                    symbol: str | None = None
                    strategy: str | None = None
                    title: str
                    reason: str
                    urgency: str

                validated.append(_ActionItem(**item).dict())
            except Exception:
                pass

        _ai_state.set_items(validated, now)
        logger.info("[ACTION-ITEMS] Generated %d items", len(validated))
        return {"items": validated, "generated_at": now, "cached": False}
    except Exception as e:
        logger.error("[ACTION-ITEMS] %s", e)
        return {"items": [], "error": str(e)}
