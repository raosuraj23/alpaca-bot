import asyncio
import concurrent.futures
import json
import logging
from fastapi import APIRouter, WebSocket, WebSocketDisconnect
from fastapi.responses import StreamingResponse
from deps import ALPACA_API_KEY, ALPACA_API_SECRET, trading_client
from core import state
from core.state import (
    _get_clients_lock,
    connected_clients,
    _get_log_queue,
    _get_reflection_queue,
    _push_log,
    _push_reflection,
    _crypto_stream_state,
    _equity_stream_state,
    EQUITY_STREAM_SYMBOLS,
    _entry_prices,
    _entry_times,
)
from strategy.engine import master_engine
from quant.data_buffer import market_buffer
from agents.risk_agent import risk_agent
from agents.execution_agent import execution_agent

logger = logging.getLogger(__name__)
router = APIRouter()

class _ManagedCryptoStream:
    def __new__(cls, key: str, secret: str):
        from alpaca.data.live import CryptoDataStream

        stream = CryptoDataStream(key, secret)

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
                    logger.warning("[STREAM] ValueError in stream: %s", e)
                except websockets.exceptions.WebSocketException as wse:
                    await stream.close()
                    stream._running = False
                    logger.warning("[STREAM] WebSocket error, reconnecting: %s", wse)
                except Exception:
                    raise
                finally:
                    await _asyncio.sleep(0)

        import types
        stream._run_forever = _managed_run_forever
        return stream


class _ManagedStockStream:
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


async def stream_manager(write_closed_trade_fn=None):
    if not (ALPACA_API_KEY and ALPACA_API_SECRET):
        logger.warning("[STREAM] No API keys — live stream disabled.")
        return

    conn_limit_wait = 65
    backoff = 5
    max_backoff = 120
    attempts = 0
    max_attempts = 15
    _active_stream = [None]

    while attempts < max_attempts:
        try:
            stream = _ManagedCryptoStream(ALPACA_API_KEY, ALPACA_API_SECRET)
            _active_stream[0] = stream

            async def bar_callback(bar):
                price = float(bar.close)
                symbol = bar.symbol

                market_buffer.ingest_bar(symbol, bar)
                await broadcast({"type": "TICK", "data": {
                    "symbol": symbol,
                    "price": price,
                    "volume": bar.volume,
                    "timestamp": bar.timestamp.isoformat(),
                }})

                signal_price = price
                signals = await master_engine.process_tick(symbol, price)
                if not signals:
                    return

                equity = 0.0
                try:
                    if trading_client:
                        equity = float(trading_client.get_account().equity)
                except Exception:
                    pass

                from risk.kill_switch import global_kill_switch
                global_kill_switch.evaluate_portfolio(equity)

                for signal in signals:
                    meta_str = ", ".join(f"{k}={v}" for k, v in signal.get("meta", {}).items())
                    _push_log(
                        f"[{signal['bot'].upper()}] {signal['action']} signal on {symbol} @ ${price:,.2f} (conf: {signal['confidence']}) {meta_str}"
                    )

                    from predict.feature_extractor import extract_features, compute_market_implied_prob
                    from predict.xgboost_classifier import xgb_classifier
                    _xgb_features = extract_features(signal)
                    _mkt_prob = compute_market_implied_prob(_xgb_features)
                    _gate = xgb_classifier.gate(_xgb_features, _mkt_prob)
                    signal["xgboost_prob"] = _gate["xgboost_prob"]
                    signal["market_implied_prob"] = _gate["market_implied_prob"]
                    signal["edge"] = _gate["edge"]
                    signal["signal_features"] = _xgb_features.tolist()
                    if not _gate["approved"]:
                        _push_log(
                            f"[XGBOOST] Rejected {signal['bot'].upper()} {signal['action']} {symbol} — {_gate['reason']}"
                        )
                        continue

                    approved = risk_agent.process(signal, equity)
                    if approved:
                        _push_log(
                            f"[RISK AGENT] ✓ Approved {approved['action']} {symbol} qty={approved['qty']:.6f} notional=${approved.get('notional', 0):.2f}"
                        )
                        _push_reflection({
                            "strategy": signal['bot'],
                            "action": approved['action'],
                            "symbol": symbol,
                            "confidence": signal['confidence'],
                            "qty": approved['qty'],
                            "kelly_fraction": approved.get('kelly_fraction', 0),
                            "meta": signal.get('meta', {}),
                            "timestamp": bar.timestamp.isoformat(),
                            "type": "decision",
                        })
                        if trading_client:
                            await broadcast({"type": "SIGNAL", "data": {
                                "bot_id": signal['bot'],
                                "action": approved['action'],
                                "symbol": symbol,
                                "confidence": signal['confidence'],
                                "qty": approved['qty'],
                                "timestamp": bar.timestamp.isoformat(),
                            }})
                            exec_result = execution_agent.execute(approved, signal_price=signal_price)
                            if exec_result:
                                key = (signal['bot'], symbol)
                                if approved['action'] == 'BUY':
                                    state._entry_prices[key] = exec_result.fill_price
                                    state._entry_times[key] = exec_result.timestamp
                                    state.persist_entry_prices(state._entry_prices, state._entry_times)
                                    master_engine.update_yield(signal['bot'], 0.0)
                                    master_engine.notify_fill(signal['bot'], symbol, 'BUY', exec_result.fill_price)
                                else:
                                    entry = state._entry_prices.pop(key, exec_result.fill_price)
                                    entry_time = state._entry_times.pop(key, None)
                                    state.persist_entry_prices(state._entry_prices, state._entry_times)
                                    realized_pnl = (exec_result.fill_price - entry) * exec_result.qty
                                    master_engine.update_yield(signal['bot'], realized_pnl)
                                    master_engine.notify_fill(signal['bot'], symbol, 'SELL')
                                    if write_closed_trade_fn:
                                        asyncio.create_task(write_closed_trade_fn(
                                            bot_id=signal['bot'], symbol=symbol, direction="LONG",
                                            entry_exec_id=None,
                                            entry_price=entry, exit_price=exec_result.fill_price,
                                            qty=exec_result.qty,
                                            entry_time=entry_time, exit_time=exec_result.timestamp,
                                        ))
                                _push_log(
                                    f"[EXECUTION] FILLED #{exec_result.order_id[:8]} — {approved['action']} {symbol} qty={exec_result.qty:.6f} fill=${exec_result.fill_price:.2f} slip=${exec_result.slippage:.4f} ({exec_result.slippage_pct:.3f}%)"
                                )
                                if state.reflection_engine:
                                    _refl_payload = {
                                        "strategy": signal['bot'],
                                        "symbol": symbol,
                                        "action": approved['action'],
                                        "fill_price": exec_result.fill_price,
                                        "slippage": exec_result.slippage,
                                        "confidence": signal['confidence'],
                                        "qty": exec_result.qty,
                                    }
                                    if approved['action'] == 'SELL':
                                        _refl_payload["realized_pnl"] = realized_pnl
                                        _refl_payload["entry_price"] = entry
                                    asyncio.create_task(state.reflection_engine.learn_from_execution(_refl_payload))
                            else:
                                _push_log(
                                    f"[EXECUTION] ✗ FAILED {approved['action']} {symbol} — order rejected (naked SELL or Alpaca error)"
                                )
                    else:
                        _push_log(f"[RISK AGENT] ✗ Blocked {signal['action']} {symbol} — risk gate rejected.")

            async def quote_callback(quote):
                await broadcast({"type": "QUOTE", "data": {
                    "symbol": quote.symbol,
                    "price": float(quote.ask_price),
                    "timestamp": quote.timestamp.isoformat(),
                }})

            _crypto_syms = list(master_engine.active_crypto_symbols)
            stream.subscribe_bars(bar_callback, *_crypto_syms)
            stream.subscribe_quotes(quote_callback, *_crypto_syms)
            logger.info("[STREAM] Subscribed to crypto symbols: %s", _crypto_syms)

            _crypto_stream_state["stream"] = stream
            _crypto_stream_state["bar_callback"] = bar_callback
            _crypto_stream_state["quote_callback"] = quote_callback

            logger.info("[STREAM] Starting Alpaca CryptoDataStream...")
            _push_log("[STREAM] Connecting to Alpaca live data stream...")

            loop = asyncio.get_running_loop()
            with concurrent.futures.ThreadPoolExecutor(max_workers=1) as executor:
                future = loop.run_in_executor(executor, stream.run)
                try:
                    await future
                except concurrent.futures.CancelledError:
                    stream.stop()
                    return

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
                logger.warning("[STREAM] Connection limit hit (attempt %d/%d). Waiting %ds for Alpaca to release stale connection...", attempts, max_attempts, conn_limit_wait)
                _push_log(f"[STREAM] ⏳ Alpaca connection limit — waiting {conn_limit_wait}s for stale session to expire...")
                await asyncio.sleep(conn_limit_wait)
                conn_limit_wait = min(int(conn_limit_wait * 1.5), 180)
            else:
                logger.warning("[STREAM] Error (attempt %d/%d): %s", attempts, max_attempts, e)
                _push_log(f"[STREAM] Connection error — retrying in {backoff}s ({attempts}/{max_attempts})...")
                await asyncio.sleep(backoff)
                backoff = min(backoff * 2, max_backoff)

    logger.error("[STREAM] Max reconnect attempts reached. Live stream suspended.")
    _push_log("[STREAM] ❌ Stream suspended after max retries. Restart backend to reconnect.")


async def equity_stream_manager(write_closed_trade_fn=None):
    from strategy.equity_algorithms import _is_market_hours

    # Stagger startup so crypto stream connects first and doesn't compete for the same slot.
    await asyncio.sleep(15)

    conn_limit_wait = 65
    backoff = 10
    max_backoff = 120
    attempts = 0
    max_attempts = 15

    while attempts < max_attempts:
        try:
            stock_stream = _ManagedStockStream(ALPACA_API_KEY, ALPACA_API_SECRET)

            async def equity_bar_callback(bar):
                price = float(bar.close)
                symbol = bar.symbol
                market_buffer.ingest_bar(symbol, bar)
                await broadcast({"type": "TICK", "data": {
                    "symbol": symbol,
                    "price": price,
                    "volume": bar.volume,
                    "timestamp": bar.timestamp.isoformat(),
                }})
                signal_price = price
                signals = await master_engine.process_tick(symbol, price)
                if not signals:
                    return

                equity_bal = 0.0
                try:
                    if trading_client:
                        equity_bal = float(trading_client.get_account().equity)
                except Exception:
                    pass

                from risk.kill_switch import global_kill_switch
                global_kill_switch.evaluate_portfolio(equity_bal)

                for signal in signals:
                    meta_str = ", ".join(f"{k}={v}" for k, v in signal.get("meta", {}).items())
                    _push_log(
                        f"[{signal['bot'].upper()}] {signal['action']} signal on {symbol} @ ${price:,.2f} (conf: {signal['confidence']}) {meta_str}"
                    )

                    from predict.feature_extractor import extract_features, compute_market_implied_prob
                    from predict.xgboost_classifier import xgb_classifier
                    _xgb_feats = extract_features(signal)
                    _mkt_p = compute_market_implied_prob(_xgb_feats)
                    _g = xgb_classifier.gate(_xgb_feats, _mkt_p)
                    signal["xgboost_prob"] = _g["xgboost_prob"]
                    signal["market_implied_prob"] = _g["market_implied_prob"]
                    signal["edge"] = _g["edge"]
                    signal["signal_features"] = _xgb_feats.tolist()
                    if not _g["approved"]:
                        _push_log(
                            f"[XGBOOST] Rejected {signal['bot'].upper()} {signal['action']} {symbol} — {_g['reason']}"
                        )
                        continue

                    approved = risk_agent.process(signal, equity_bal)
                    if approved:
                        _push_log(
                            f"[RISK AGENT] ✓ Approved {approved['action']} {symbol} qty={approved['qty']:.6f} notional=${approved.get('notional', 0):.2f}"
                        )
                        if trading_client:
                            exec_result = execution_agent.execute(approved, signal_price=signal_price)
                            if exec_result:
                                key = (signal['bot'], symbol)
                                if approved['action'] == 'BUY':
                                    state._entry_prices[key] = exec_result.fill_price
                                    state._entry_times[key] = exec_result.timestamp
                                    state.persist_entry_prices(state._entry_prices, state._entry_times)
                                    master_engine.update_yield(signal['bot'], 0.0)
                                    master_engine.notify_fill(signal['bot'], symbol, 'BUY', exec_result.fill_price)
                                else:
                                    entry = state._entry_prices.pop(key, exec_result.fill_price)
                                    entry_time = state._entry_times.pop(key, None)
                                    state.persist_entry_prices(state._entry_prices, state._entry_times)
                                    realized_pnl = (exec_result.fill_price - entry) * exec_result.qty
                                    master_engine.update_yield(signal['bot'], realized_pnl)
                                    master_engine.notify_fill(signal['bot'], symbol, 'SELL')
                                    if write_closed_trade_fn:
                                        asyncio.create_task(write_closed_trade_fn(
                                            bot_id=signal['bot'], symbol=symbol, direction="LONG",
                                            entry_exec_id=None,
                                            entry_price=entry, exit_price=exec_result.fill_price,
                                            qty=exec_result.qty,
                                            entry_time=entry_time, exit_time=exec_result.timestamp,
                                        ))
                                _push_log(
                                    f"[EXECUTION] FILLED #{exec_result.order_id[:8]} — {approved['action']} {symbol} qty={exec_result.qty:.6f} fill=${exec_result.fill_price:.2f}"
                                )
                                if state.reflection_engine:
                                    _refl_eq = {
                                        "strategy": signal['bot'],
                                        "symbol": symbol,
                                        "action": approved['action'],
                                        "fill_price": exec_result.fill_price,
                                        "slippage": exec_result.slippage,
                                        "confidence": signal['confidence'],
                                        "qty": exec_result.qty,
                                    }
                                    if approved['action'] == 'SELL':
                                        _refl_eq["realized_pnl"] = realized_pnl
                                        _refl_eq["entry_price"] = entry
                                    asyncio.create_task(state.reflection_engine.learn_from_execution(_refl_eq))
                    else:
                        _push_log(f"[RISK AGENT] ✗ Blocked {signal['action']} {symbol} — risk gate rejected.")

            stock_stream.subscribe_bars(equity_bar_callback, *state.EQUITY_STREAM_SYMBOLS)
            _equity_stream_state["stream"] = stock_stream
            _equity_stream_state["callback"] = equity_bar_callback
            logger.info("[EQUITY STREAM] Starting Alpaca StockDataStream for %s", state.EQUITY_STREAM_SYMBOLS)
            _push_log("[EQUITY STREAM] Connecting to Alpaca equity data stream...")

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
                logger.warning("[EQUITY STREAM] Connection limit hit (attempt %d/%d). Waiting %ds for Alpaca to release stale connection...", attempts, max_attempts, conn_limit_wait)
                _push_log(f"[EQUITY STREAM] ⏳ Alpaca connection limit — waiting {conn_limit_wait}s for stale session to expire...")
                await asyncio.sleep(conn_limit_wait)
                conn_limit_wait = min(int(conn_limit_wait * 1.5), 180)
            else:
                logger.warning("[EQUITY STREAM] Error (attempt %d/%d): %s", attempts, max_attempts, e)
                _push_log(f"[EQUITY STREAM] Error — retrying in {backoff}s ({attempts}/{max_attempts})...")
                await asyncio.sleep(backoff)
                backoff = min(backoff * 2, max_backoff)

    logger.error("[EQUITY STREAM] Max reconnect attempts reached. Equity stream suspended.")
    _push_log("[EQUITY STREAM] ❌ Equity stream suspended after max retries.")


async def reflection_generator():
    yield f"data: {json.dumps({'heartbeat': True})}\n\n"
    q = _get_reflection_queue()
    while True:
        try:
            payload = await asyncio.wait_for(q.get(), timeout=20)
            yield f"data: {payload}\n\n"
        except asyncio.TimeoutError:
            yield f"data: {json.dumps({'heartbeat': True})}\n\n"


@router.get("/api/reflections/stream")
def stream_reflections():
    return StreamingResponse(reflection_generator(), media_type="text/event-stream",
                             headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"})


async def log_generator():
    yield f"data: {json.dumps({'log': '[SYSTEM] Trading Engine Online — monitoring live market feeds...'})}\n\n"
    q = _get_log_queue()
    while True:
        try:
            payload = await asyncio.wait_for(q.get(), timeout=20)
            yield f"data: {payload}\n\n"
        except asyncio.TimeoutError:
            yield f"data: {json.dumps({'log': '[HEARTBEAT] Awaiting next bar...'})}\n\n"


@router.get("/api/logs/stream")
def stream_logs():
    return StreamingResponse(log_generator(), media_type="text/event-stream",
                             headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"})


@router.websocket("/stream")
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
