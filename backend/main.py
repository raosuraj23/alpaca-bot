import os
import json
import asyncio
import logging
import warnings
from datetime import datetime, timezone
from dotenv import load_dotenv


# langchain-google-genai imports deprecated google.generativeai internally;
# suppress until the package ships a google.genai-based release.
warnings.filterwarnings("ignore", category=FutureWarning, module="langchain_google_genai")
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from typing import Optional

load_dotenv()

logging.basicConfig(level=os.getenv("LOG_LEVEL", "INFO"))
logger = logging.getLogger(__name__)

from config import settings

app = FastAPI(title="Alpaca Multi-Agent API", version="2.0")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

from deps import ALPACA_API_KEY, ALPACA_API_SECRET, PAPER_TRADING, trading_client

from agents.orchestrator import master_orchestrator

# ==========================================
# ROUTERS
# ==========================================

from routers.account import router as account_router
from routers.bots import router as bots_router
from routers.analytics import router as analytics_router
from routers.agents import router as agents_router
from routers.trading import router as trading_router
import importlib.util
from pathlib import Path

_stream_path = Path(__file__).parent / "websockets" / "stream.py"
_spec = importlib.util.spec_from_file_location("backend_websockets_stream", str(_stream_path))
_stream_mod = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(_stream_mod)
stream_router = getattr(_stream_mod, "router")
stream_manager = getattr(_stream_mod, "stream_manager")
equity_stream_manager = getattr(_stream_mod, "equity_stream_manager")

app.include_router(account_router)
app.include_router(bots_router)
app.include_router(analytics_router)
app.include_router(agents_router)
app.include_router(trading_router)
app.include_router(stream_router)

# ==========================================
# AGENT FLEET IMPORTS
# ==========================================

from strategy.engine import master_engine
from agents.risk_agent import risk_agent
from agents.execution_agent import execution_agent
from quant.data_buffer import market_buffer

from strategy.equity_algorithms import EQUITY_SYMBOLS as _EQUITY_SEED
from core.state import (
    EQUITY_STREAM_SYMBOLS as _EQUITY_STREAM_SYMBOLS,
    CRYPTO_STREAM_SYMBOLS as _CRYPTO_STREAM_SYMBOLS,
    _crypto_stream_state,
    _equity_stream_state,
    _push_log,
    _push_reflection,
    _get_log_queue,
    _get_reflection_queue,
    connected_clients,
    _get_clients_lock,
)
import core.state as _core_state

# Seed the canonical equity stream symbol list if it's empty
if not _EQUITY_STREAM_SYMBOLS:
    _EQUITY_STREAM_SYMBOLS.extend(list(_EQUITY_SEED))

EQUITY_STREAM_SYMBOLS = _EQUITY_STREAM_SYMBOLS
CRYPTO_STREAM_SYMBOLS = _CRYPTO_STREAM_SYMBOLS


def _get_positions_for_reflection() -> list:
    if not trading_client:
        return []
    try:
        pos = trading_client.get_all_positions()
        return [
            {
                "symbol": p.symbol,
                "side": p.side.value if hasattr(p.side, "value") else str(p.side).split(".")[-1],
                "size": str(p.qty),
                "avg_entry_price": str(p.avg_entry_price),
                "current_price": str(p.current_price),
                "unrealized_pnl": str(p.unrealized_pl),
            }
            for p in pos
        ]
    except Exception:
        return []


async def _portfolio_snapshot_loop():
    from db.database import _get_session_factory
    from db.models import PortfolioSnapshot
    await asyncio.sleep(30)
    while True:
        try:
            total_equity = cash_balance = unrealized_pnl = realized_pnl_day = 0.0
            if trading_client:
                try:
                    acc = await asyncio.to_thread(trading_client.get_account)
                    total_equity = float(getattr(acc, "equity", None) or 0.0)
                    cash_balance = float(getattr(acc, "cash", None) or 0.0)
                    for attr in ("unrealized_pl", "unrealized_plpc"):
                        raw = getattr(acc, attr, None)
                        if attr == "unrealized_pl" and raw is not None:
                            try:
                                unrealized_pnl = float(raw)
                            except Exception:
                                pass
                            break
                    realized_pnl_day = float(getattr(acc, "realized_pl", 0.0) or 0.0)
                except Exception:
                    pass
            async with _get_session_factory()() as _s:
                _s.add(PortfolioSnapshot(
                    total_equity=total_equity,
                    cash_balance=cash_balance,
                    unrealized_pnl=unrealized_pnl,
                    realized_pnl_day=realized_pnl_day,
                ))
                await _s.commit()
        except Exception as snap_err:
            logger.debug("[SNAPSHOT] %s", snap_err)

        # Prune snapshots older than 48h to prevent unbounded table growth
        try:
            from db.models import PortfolioSnapshot
            from sqlalchemy import delete as _del
            from datetime import timedelta
            cutoff = datetime.now(timezone.utc) - timedelta(hours=48)
            async with _get_session_factory()() as _ps:
                await _ps.execute(_del(PortfolioSnapshot).where(PortfolioSnapshot.timestamp < cutoff))
                await _ps.commit()
        except Exception as _prune_err:
            logger.debug("[SNAPSHOT] Prune failed: %s", _prune_err)

        await asyncio.sleep(60)


async def _write_closed_trade(
    bot_id: str,
    symbol: str,
    direction: str,
    entry_exec_id,
    entry_price: float,
    exit_price: float,
    qty: float,
    entry_time,
    exit_time,
):
    from db.database import _get_session_factory
    from db.models import ClosedTrade
    from datetime import datetime as _dt

    def _parse_ts(ts):
        if isinstance(ts, _dt):
            return ts.replace(tzinfo=None)
        if isinstance(ts, str):
            try:
                return _dt.fromisoformat(ts.replace("Z", "").split("+")[0])
            except ValueError:
                return None
        return None

    realized_pnl = (exit_price - entry_price) * qty if direction == "LONG" else (entry_price - exit_price) * qty
    win = realized_pnl > 0

    import re as _re2
    _CRYPTO_RE2 = _re2.compile(r'^[A-Z]{2,6}(USD[TC]?|BTC|ETH)$')
    asset_class      = "CRYPTO" if ("/" in symbol or bool(_CRYPTO_RE2.match(symbol))) else "EQUITY"
    entry_confidence: float | None = None

    entry_ev = entry_kelly = entry_edge = brier_contrib = None
    if entry_exec_id is not None:
        try:
            from db.models import ExecutionRecord as _ER, SignalRecord as _SR
            from sqlalchemy import select as _sel_s
            async with _get_session_factory()() as _ls:
                exec_row = (await _ls.execute(_sel_s(_ER).where(_ER.id == entry_exec_id))).scalar_one_or_none()
                if exec_row and exec_row.signal_id:
                    sig_row = (await _ls.execute(_sel_s(_SR).where(_SR.id == exec_row.signal_id))).scalar_one_or_none()
                    if sig_row:
                        entry_ev = float(sig_row.expected_value) if sig_row.expected_value is not None else None
                        entry_kelly = float(sig_row.kelly_fraction) if sig_row.kelly_fraction is not None else None
                        entry_edge = float(sig_row.market_edge) if sig_row.market_edge is not None else None
                        conf = float(sig_row.confidence or 0)
                        brier_contrib = round((conf - (1 if win else 0)) ** 2, 6)
                        entry_confidence = conf
                        asset_class = sig_row.asset_class or asset_class
        except Exception as _fme:
            logger.debug("[CLOSED TRADE] formula metrics lookup failed: %s", _fme)

    try:
        async with _get_session_factory()() as _s:
            _s.add(ClosedTrade(
                bot_id=bot_id, symbol=symbol, qty=qty,
                avg_entry_price=entry_price, avg_exit_price=exit_price,
                realized_pnl=realized_pnl, net_pnl=realized_pnl, win=win,
                entry_time=_parse_ts(entry_time), exit_time=_parse_ts(exit_time),
                entry_ev=entry_ev, entry_kelly=entry_kelly, entry_edge=entry_edge,
                brier_contribution=brier_contrib,
                asset_class=asset_class,
                confidence=entry_confidence,
            ))
            await _s.commit()
    except Exception as e:
        logger.warning("[CLOSED TRADE] Failed to persist: %s", e)
        return

    global _xgb_trade_counter
    _xgb_trade_counter += 1
    if _xgb_trade_counter % 25 == 0:
        asyncio.create_task(_retrain_xgboost_if_ready())


# ==========================================
# LIFECYCLE
# ==========================================

_stream_task: Optional[asyncio.Task] = None
_stock_stream_task: Optional[asyncio.Task] = None
_ai_reflection_task: Optional[asyncio.Task] = None
_scanner_task: Optional[asyncio.Task] = None
_research_task: Optional[asyncio.Task] = None

# Counter for XGBoost auto-retrain trigger (every 25 closed trades)
_xgb_trade_counter: int = 0


async def _retrain_xgboost_if_ready() -> None:
    try:
        from predict.xgboost_classifier import xgb_classifier
        trained = await asyncio.to_thread(xgb_classifier.train)
        if trained:
            logger.info("[XGBOOST] Auto-retrain complete")
        else:
            logger.debug("[XGBOOST] Auto-retrain skipped (insufficient data)")
    except Exception as _xe:
        logger.debug("[XGBOOST] Auto-retrain error: %s", _xe)


@app.on_event("startup")
async def startup_event():
    global _stream_task, _stock_stream_task, _ai_reflection_task, _scanner_task, _research_task

    from db.database import init_db
    await init_db()

    # Restore persisted bot halt/resume states
    try:
        from db.database import _get_session_factory
        from db.models import BotState, BotParameterControl
        from sqlalchemy import select as _select
        import json as _json
        async with _get_session_factory()() as _session:
            _bot_states = (await _session.execute(_select(BotState))).scalars().all()
            master_engine.restore_from_db([
                {"bot_id": s.bot_id, "status": s.status, "allocation": float(s.allocation)}
                for s in _bot_states
            ])
            
            _param_controls = (await _session.execute(_select(BotParameterControl))).scalars().all()
            for _pc in _param_controls:
                if _pc.params_json:
                    try:
                        _params = _json.loads(_pc.params_json)
                        master_engine.update_strategy_params(_pc.bot_id, _params)
                    except Exception as _pe:
                        logger.debug("[STARTUP] BotParameterControl restore failed for %s: %s", _pc.bot_id, _pe)
            from db.models import SymbolStrategyAssignment as _SSA
            from sqlalchemy import select as _ssa_select
            _assignments = (await _session.execute(
                _ssa_select(_SSA).where(_SSA.active == True)
            )).scalars().all()
            if _assignments:
                master_engine.restore_symbol_assignments(_assignments)
                logger.info("[STARTUP] Restored %d symbol-strategy assignments", len(_assignments))
    except Exception as _exc:
        logger.warning("[STARTUP] BotState restore failed: %s", _exc)

    # Restore per-strategy LONG position state from persisted entry prices so
    # strategies can generate SELL signals for positions opened in prior sessions.
    from core.state import _entry_prices as _ep
    _restored = 0
    for (_bot_id, _sym), _ep_price in _ep.items():
        master_engine.notify_fill(_bot_id, _sym, "BUY", _ep_price)
        _restored += 1
    if _restored:
        logger.info("[STARTUP] Restored LONG position state for %d open entries", _restored)

    _get_log_queue()
    _get_reflection_queue()
    logger.info("Multi-Agent REST/WS Gateway booted (paper=%s).", PAPER_TRADING)
    _push_log("[SYSTEM] Trading Engine Online — initializing stream...")

    if ALPACA_API_KEY and ALPACA_API_SECRET:
        _stream_task = asyncio.create_task(
            stream_manager(write_closed_trade_fn=_write_closed_trade)
        )
        _stock_stream_task = asyncio.create_task(equity_stream_manager(write_closed_trade_fn=_write_closed_trade))

    # Reflection engine
    from agents.reflection_engine import ReflectionEngine
    _reflection_engine = ReflectionEngine(
        push_fn=_push_reflection,
        get_states_fn=master_engine.get_all_states,
        get_positions_fn=_get_positions_for_reflection,
    )
    _core_state.reflection_engine = _reflection_engine
    _ai_reflection_task = asyncio.create_task(_reflection_engine.run())

    # Portfolio snapshot loop
    asyncio.create_task(_portfolio_snapshot_loop())
    logger.info("[SNAPSHOT] Portfolio snapshot loop started (60s cadence)")

    from quant.data_buffer import market_buffer as _mb

    def _scanner_push_symbols(symbols: list) -> None:
        """Subscribe the engine and live WebSocket streams to a list of symbols.

        Called by both the TIER 1 'discover' event and the TIER 2 on_universe_update
        callback so every scan cycle can expand coverage without a restart.
        """
        if not symbols:
            return
        crypto_syms = {s for s in symbols if s.endswith("/USD")}
        equity_syms = {s for s in symbols if "/" not in s}

        if crypto_syms:
            known_crypto = set(master_engine.active_crypto_symbols)
            for _sym in crypto_syms - known_crypto:
                master_engine.add_to_pending(_sym)
            master_engine.set_active_crypto_symbols(crypto_syms)
            _cs = _crypto_stream_state.get("stream")
            _cb = _crypto_stream_state.get("bar_callback")
            _qb = _crypto_stream_state.get("quote_callback")
            if _cs and _cb:
                new_crypto = crypto_syms - set(CRYPTO_STREAM_SYMBOLS)
                if new_crypto:
                    try:
                        _cs.subscribe_bars(_cb, *new_crypto)
                        if _qb:
                            _cs.subscribe_quotes(_qb, *new_crypto)
                        CRYPTO_STREAM_SYMBOLS.extend(new_crypto)
                        logger.info("[SCANNER→CRYPTO STREAM] Subscribed new symbols: %s", new_crypto)
                    except Exception as _e:
                        logger.warning("[SCANNER→CRYPTO STREAM] Subscribe failed: %s", _e)
            logger.info("[SCANNER→ENGINE] Crypto symbols updated: %s", crypto_syms)

        if equity_syms:
            known_equity = set(master_engine.active_equity_symbols)
            for _sym in equity_syms - known_equity:
                master_engine.add_to_pending(_sym)
            master_engine.set_active_equity_symbols(equity_syms)
            _es = _equity_stream_state.get("stream")
            _ecb = _equity_stream_state.get("callback")
            if _es and _ecb:
                new_eq = equity_syms - set(EQUITY_STREAM_SYMBOLS)
                if new_eq:
                    try:
                        _es.subscribe_bars(_ecb, *new_eq)
                        EQUITY_STREAM_SYMBOLS.extend(new_eq)
                        logger.info("[SCANNER→EQUITY STREAM] Subscribed new symbols: %s", new_eq)
                    except Exception as _e:
                        logger.warning("[SCANNER→EQUITY STREAM] Subscribe failed: %s", _e)
            logger.info("[SCANNER→ENGINE] Equity symbols updated: %s", equity_syms)

    def _scanner_push(data: dict) -> None:
        _push_reflection(data)
        if data.get("type") != "discover":
            return
        _scanner_push_symbols(data.get("symbols", []))

    # Research Agent
    from agents.research_agent import ResearchAgent
    _research_agent = ResearchAgent(
        push_fn=_push_reflection,
        get_buffer_fn=lambda: _mb,
        signal_callback=master_orchestrator.process_signal,
    )
    _core_state.research_agent = _research_agent
    _research_task = asyncio.create_task(_research_agent.run())
    logger.info("[RESEARCH] Research Agent started (Gemini 2.5 Flash, 30-min cadence)")

    # Scanner Agent
    from agents.scanner_agent import ScannerAgent
    _scanner_agent = ScannerAgent(
        push_fn=_scanner_push,
        get_buffer_fn=lambda: _mb,
        get_research_fn=lambda: _research_agent,
        set_equity_symbols_fn=lambda syms: master_engine.set_active_equity_symbols(set(syms)),
        on_universe_update=_scanner_push_symbols,
    )
    _core_state.scanner_agent = _scanner_agent   # exposes to /api/watchlist and /api/watchlist/scan
    _scanner_task = asyncio.create_task(_scanner_agent.run())

    # 5-min news polling loop
    async def _news_poll_loop():
        await asyncio.sleep(60)
        _seen_ids: set = set()
        while True:
            try:
                if _research_agent:
                    news = await _research_agent._fetch_news_items()
                    new_items = [n for n in news if n.get("id") not in _seen_ids]
                    if new_items:
                        _seen_ids.update(n["id"] for n in new_items if n.get("id"))
                        if len(_seen_ids) > 500:
                            _seen_ids = set(list(_seen_ids)[-200:])
                        asyncio.create_task(_research_agent.analyze_breaking_news(new_items))
            except Exception:
                pass
            await asyncio.sleep(300)

    asyncio.create_task(_news_poll_loop())

    # Autonomous Portfolio Director
    from agents.portfolio_director import AutonomousPortfolioDirector
    from db.database import _get_session_factory as _gsf_director
    _director = AutonomousPortfolioDirector(
        push_fn=_push_reflection,
        get_engine_fn=lambda: master_engine,
        get_scanner_fn=lambda: _scanner_agent.get_last_results() if _scanner_agent else [],
        db_factory=_gsf_director,
    )
    _director.set_research_fn(lambda: _research_agent)
    asyncio.create_task(_director.run())
    logger.info("[DIRECTOR] Autonomous Portfolio Director scheduled (15 min interval)")



    # Nightly Consolidation
    from agents.nightly_consolidation import NightlyConsolidation
    _nightly = NightlyConsolidation(push_fn=_push_reflection)
    asyncio.create_task(_nightly.run())
    logger.info("[CONSOLIDATION] Nightly consolidation agent scheduled (23:55 UTC)")

    # XGBoost startup training
    async def _xgb_startup_train():
        try:
            from predict.xgboost_classifier import xgb_classifier
            trained = await asyncio.get_event_loop().run_in_executor(None, xgb_classifier.train)
            if trained:
                logger.info("[PREDICT] XGBoost model trained on startup from existing trade history")
            else:
                logger.info("[PREDICT] XGBoost in cold-start mode (insufficient data — signals pass through)")
        except Exception as _xgb_err:
            logger.info("[PREDICT] XGBoost startup training skipped: %s", _xgb_err)

    asyncio.create_task(_xgb_startup_train())

    # Stop-loss monitor — fires SELL when any position loses > 1.5% from entry
    _STOP_LOSS_PCT = 0.015

    async def _stop_loss_monitor_task():
        await asyncio.sleep(30)
        while True:
            await asyncio.sleep(60)
            try:
                from core.state import _entry_prices
                if not _entry_prices or not trading_client:
                    continue
                positions = await asyncio.to_thread(trading_client.get_all_positions)
                pos_by_symbol = {p.symbol.replace("/", ""): p for p in positions}
                checked: set[str] = set()
                for (bot_id, symbol), entry in list(_entry_prices.items()):
                    if not entry or entry <= 0:
                        continue
                    norm = symbol.replace("/", "")
                    if norm in checked:
                        continue
                    pos = pos_by_symbol.get(norm)
                    if pos is None:
                        continue
                    current = float(pos.current_price)
                    loss_pct = (entry - current) / entry
                    if loss_pct >= _STOP_LOSS_PCT:
                        checked.add(norm)
                        logger.warning(
                            "[STOP-LOSS] %s entry=%.4f current=%.4f loss=%.2f%% — submitting market SELL",
                            symbol, entry, current, loss_pct * 100,
                        )
                        try:
                            from alpaca.trading.requests import MarketOrderRequest
                            from alpaca.trading.enums import OrderSide, TimeInForce
                            req = MarketOrderRequest(
                                symbol=pos.symbol,
                                qty=float(pos.qty),
                                side=OrderSide.SELL,
                                time_in_force=TimeInForce.DAY,
                            )
                            await asyncio.to_thread(trading_client.submit_order, req)
                            logger.info("[STOP-LOSS] Market SELL submitted for %s qty=%s", symbol, pos.qty)
                        except Exception as _sell_err:
                            logger.warning("[STOP-LOSS] SELL submit failed for %s: %s", symbol, _sell_err)
            except Exception as _mon_err:
                logger.debug("[STOP-LOSS] Monitor error: %s", _mon_err)

    asyncio.create_task(_stop_loss_monitor_task())
    logger.info("[STOP-LOSS] Stop-loss monitor started (1.5%% threshold, 60s cadence)")

    # Market lifecycle — auto-halt equity bots at close, resume at open
    async def _market_lifecycle_task():
        from strategy.equity_algorithms import _is_market_hours
        last_state: bool | None = None
        while True:
            await asyncio.sleep(60)
            now_open = _is_market_hours()
            if now_open == last_state:
                continue
            last_state = now_open
            if now_open:
                logger.info("[LIFECYCLE] Market open — resuming equity bots")
                master_engine.resume_all_equity_bots()
            else:
                logger.info("[LIFECYCLE] Market closed — halting equity bots")
                master_engine.halt_all_equity_bots()

    asyncio.create_task(_market_lifecycle_task())
    logger.info("[LIFECYCLE] Market lifecycle task started")


@app.get("/")
def read_root():
    return {"status": "Automated Multi-Agent Pipeline Online"}


@app.on_event("shutdown")
async def shutdown_event():
    global _stream_task, _stock_stream_task, _ai_reflection_task, _scanner_task, _research_task
    for task in (_stream_task, _stock_stream_task, _ai_reflection_task, _scanner_task, _research_task):
        if task and not task.done():
            task.cancel()
            try:
                await task
            except asyncio.CancelledError:
                pass
    logger.info("[STREAM] Clean shutdown complete.")
