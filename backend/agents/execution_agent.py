"""
Execution Agent — Order Submission + Slippage Recorder
========================================================
Terminal node in the signal pipeline. Receives risk-approved signals,
submits orders to Alpaca, calculates slippage, and persists records
to the SQLite database (SignalRecord + ExecutionRecord).
"""

import logging
import os
from datetime import datetime

logger = logging.getLogger(__name__)

# Pre-execution guard thresholds (overridable via config.settings if available)
_SLIPPAGE_ABORT_PCT   = float(os.getenv("SLIPPAGE_ABORT_PCT", "0.02"))   # abort if mid-quote drift > 2%
_MAX_CONCURRENT_POS   = int(os.getenv("MAX_CONCURRENT_POSITIONS", "15"))  # hard cap on open positions

# Lazy imports for DB to avoid circular imports at module load time


class ExecutionResult:
    __slots__ = ("order_id", "symbol", "action", "qty", "fill_price",
                 "signal_price", "slippage", "slippage_pct", "bot_id", "timestamp",
                 "hold_duration_min", "market_conditions")

    def __init__(self, **kwargs):
        for k, v in kwargs.items():
            setattr(self, k, v)

    def to_dict(self) -> dict:
        return {s: getattr(self, s, None) for s in self.__slots__}


def _get_trading_client():
    """
    Resolves the Alpaca TradingClient from whichever module namespace owns it.
    Under `uvicorn main:app`, `__main__` is uvicorn — NOT the app module.
    We search sys.modules by the known import names used at startup.
    """
    import sys
    for name in ("main", "backend.main", "__main__"):
        m = sys.modules.get(name)
        tc = getattr(m, "trading_client", None) if m else None
        if tc is not None:
            return tc
    return None


class ExecutionAgent:
    """
    Handles physical Alpaca order submission.
    For every approved signal:
      1. Resolves trading_client via sys.modules (safe under uvicorn)
      2. Submits a MarketOrderRequest
      3. Records SignalRecord + ExecutionRecord to SQLite
      4. Returns ExecutionResult with slippage data
    """

    def execute(self, approved_signal: dict, signal_price: float | None = None) -> ExecutionResult | None:
        """
        Execute an approved signal.

        Args:
            approved_signal: Signal dict enriched by RiskAgent (includes 'qty')
            signal_price: Price at signal emission time (for slippage calculation).
                          Falls back to approved_signal['price'] if not provided.
        """
        symbol  = approved_signal.get("symbol", "UNKNOWN")
        action  = approved_signal.get("action", "BUY")
        qty     = float(approved_signal.get("qty", 0.0))
        bot_id  = approved_signal.get("bot", "unknown")
        s_price = signal_price or float(approved_signal.get("price", 0.0))

        if qty <= 0:
            logger.error("[EXECUTION AGENT] Zero qty — aborting submission for %s %s", action, symbol)
            self._persist_async(
                bot_id=bot_id,
                symbol=symbol,
                action=action,
                confidence=approved_signal.get("confidence", 0.0),
                order_id=None,
                fill_price=0.0,
                slippage=0.0,
                status="FAILED",
                failure_reason="zero quantity",
            )
            return None

        trading_client = _get_trading_client()

        if not trading_client:
            logger.warning("[EXECUTION AGENT] trading_client unavailable — skipping live submission.")
            self._persist_async(
                bot_id=bot_id,
                symbol=symbol,
                action=action,
                confidence=approved_signal.get("confidence", 0.0),
                order_id=None,
                fill_price=0.0,
                slippage=0.0,
                status="FAILED",
                failure_reason="trading client unavailable",
            )
            return None

        # --- Pre-execution guard: max concurrent positions ---
        if action == "BUY":
            try:
                all_positions = trading_client.get_all_positions()
                if len(all_positions) >= _MAX_CONCURRENT_POS:
                    logger.warning(
                        "[EXECUTION AGENT] Position count limit reached (%d/%d) — aborting BUY %s",
                        len(all_positions), _MAX_CONCURRENT_POS, symbol,
                    )
                    self._persist_async(
                        bot_id=bot_id, symbol=symbol, action=action,
                        confidence=approved_signal.get("confidence", 0.0),
                        order_id=None, fill_price=0.0, slippage=0.0,
                        status="FAILED",
                        failure_reason=f"position limit {_MAX_CONCURRENT_POS} reached",
                    )
                    return None
            except Exception as _pe:
                logger.debug("[EXECUTION AGENT] Position count check failed: %s", _pe)

        # --- Pre-execution guard: slippage check via latest quote ---
        if s_price > 0:
            try:
                quote = trading_client.get_latest_quote(symbol)
                bid = float(getattr(quote, "bid_price", 0) or 0)
                ask = float(getattr(quote, "ask_price", 0) or 0)
                if bid > 0 and ask > 0:
                    mid = (bid + ask) / 2
                    pre_slip_pct = abs(mid - s_price) / s_price
                    if pre_slip_pct > _SLIPPAGE_ABORT_PCT:
                        logger.warning(
                            "[EXECUTION AGENT] Pre-execution slippage abort: %.2f%% > %.0f%% limit "
                            "for %s (signal=$%.4f mid=$%.4f)",
                            pre_slip_pct * 100, _SLIPPAGE_ABORT_PCT * 100, symbol, s_price, mid,
                        )
                        self._persist_async(
                            bot_id=bot_id, symbol=symbol, action=action,
                            confidence=approved_signal.get("confidence", 0.0),
                            order_id=None, fill_price=0.0, slippage=pre_slip_pct * s_price,
                            status="FAILED",
                            failure_reason=f"pre-execution slippage {pre_slip_pct:.2%} > {_SLIPPAGE_ABORT_PCT:.0%} limit",
                        )
                        return None
            except Exception as _qe:
                logger.debug("[EXECUTION AGENT] Quote slippage check failed: %s — proceeding", _qe)

        # SELL guard: reject if we hold no position in this symbol.
        # Alpaca symbols may be "BTC/USD" (stream) or "BTCUSD" (position) — normalise both.
        if action == "SELL":
            try:
                positions = trading_client.get_all_positions()
                norm = symbol.replace("/", "")
                held_qty = sum(
                    float(p.qty) for p in positions
                    if p.symbol.replace("/", "") == norm
                )
                if held_qty <= 0:
                    logger.warning(
                        "[EXECUTION AGENT] SELL guard: no open position in %s — aborting naked SELL",
                        symbol,
                    )
                    self._persist_async(
                        bot_id=bot_id,
                        symbol=symbol,
                        action=action,
                        confidence=approved_signal.get("confidence", 0.0),
                        order_id=None,
                        fill_price=0.0,
                        slippage=0.0,
                        status="FAILED",
                        failure_reason="no open position for SELL",
                    )
                    return None
            except Exception as pos_err:
                logger.warning(
                    "[EXECUTION AGENT] Position check failed (%s) — proceeding cautiously", pos_err
                )

        try:
            from alpaca.trading.requests import MarketOrderRequest
            from alpaca.trading.enums import OrderSide, TimeInForce

            side  = OrderSide.BUY if action == "BUY" else OrderSide.SELL
            # Alpaca requires DAY for fractional equity orders (error 42210000 with GTC)
            is_crypto    = "/" in symbol
            is_fractional = (qty % 1) != 0
            tif = TimeInForce.DAY if (not is_crypto and is_fractional) else TimeInForce.GTC
            order = MarketOrderRequest(
                symbol=symbol,
                qty=qty,
                side=side,
                time_in_force=tif,
            )

            result = trading_client.submit_order(order_data=order)
            order_id   = str(result.id)
            fill_price = float(result.filled_avg_price) if result.filled_avg_price else s_price
            slippage   = abs(fill_price - s_price)
            slip_pct   = (slippage / s_price * 100) if s_price > 0 else 0.0

            logger.info(
                "[EXECUTION AGENT] FILLED %s %s qty=%.6f fill=$%.2f signal=$%.2f slippage=$%.4f (%.4f%%)",
                action, symbol, qty, fill_price, s_price, slippage, slip_pct
            )

            # Persist to DB asynchronously (fire-and-forget)
            self._persist_async(
                bot_id=bot_id,
                symbol=symbol,
                action=action,
                confidence=approved_signal.get("confidence", 0.0),
                order_id=order_id,
                fill_price=fill_price,
                qty=qty,
                slippage=slippage,
                status="FILLED",
                failure_reason=None,
                expected_value=approved_signal.get("expected_value"),
                kelly_fraction=approved_signal.get("kelly_fraction"),
                market_edge=approved_signal.get("market_edge"),
                market_implied_prob=approved_signal.get("market_implied_prob"),
                mispricing_z_score=approved_signal.get("mispricing_z_score"),
                xgboost_prob=approved_signal.get("xgboost_prob"),
                signal_features=approved_signal.get("signal_features"),
            )

            market_conditions = self._extract_market_conditions(approved_signal) if action == "SELL" else None

            return ExecutionResult(
                order_id=order_id,
                symbol=symbol,
                action=action,
                qty=qty,
                fill_price=fill_price,
                signal_price=s_price,
                slippage=slippage,
                slippage_pct=round(slip_pct, 6),
                bot_id=bot_id,
                timestamp=datetime.utcnow().isoformat(),
                market_conditions=market_conditions,
                hold_duration_min=None,  # computed async in reflection_engine
            )

        except Exception as e:
            failure_reason = str(e)
            logger.error("[EXECUTION AGENT] Submission failed for %s %s: %s", action, symbol, failure_reason)
            self._persist_async(
                bot_id=bot_id,
                symbol=symbol,
                action=action,
                confidence=approved_signal.get("confidence", 0.0),
                order_id=None,
                fill_price=0.0,
                slippage=0.0,
                status="FAILED",
                failure_reason=failure_reason,
            )
            return None

    def _persist_async(
        self,
        bot_id: str,
        symbol: str,
        action: str,
        confidence: float,
        order_id: str | None,
        fill_price: float,
        qty: float = 1.0,
        slippage: float = 0.0,
        status: str = "FILLED",
        failure_reason: str | None = None,
        expected_value: float | None = None,
        kelly_fraction: float | None = None,
        market_edge: float | None = None,
        market_implied_prob: float | None = None,
        mispricing_z_score: float | None = None,
        xgboost_prob: float | None = None,
        signal_features: list | None = None,
    ):
        """
        Spawns a background coroutine to write SignalRecord + ExecutionRecord.
        Uses asyncio.create_task() so it doesn't block the WebSocket callback.
        """
        import asyncio
        try:
            loop = asyncio.get_event_loop()
            if loop.is_running():
                asyncio.create_task(self._write_db(
                    bot_id=bot_id,
                    symbol=symbol,
                    action=action,
                    confidence=confidence,
                    order_id=order_id,
                    fill_price=fill_price,
                    qty=qty,
                    slippage=slippage,
                    status=status,
                    failure_reason=failure_reason,
                    expected_value=expected_value,
                    kelly_fraction=kelly_fraction,
                    market_edge=market_edge,
                    market_implied_prob=market_implied_prob,
                    mispricing_z_score=mispricing_z_score,
                    xgboost_prob=xgboost_prob,
                    signal_features=signal_features,
                ))
        except RuntimeError:
            # No running event loop (e.g. in tests) — skip persistence
            pass

    async def _write_db(
        self,
        bot_id: str,
        symbol: str,
        action: str,
        confidence: float,
        order_id: str | None,
        fill_price: float,
        qty: float = 1.0,
        slippage: float = 0.0,
        status: str = "FILLED",
        failure_reason: str | None = None,
        expected_value: float | None = None,
        kelly_fraction: float | None = None,
        market_edge: float | None = None,
        market_implied_prob: float | None = None,
        mispricing_z_score: float | None = None,
        xgboost_prob: float | None = None,
        signal_features: list | None = None,
    ):
        """Writes a SignalRecord and linked ExecutionRecord to SQLite."""
        try:
            from db.database import _get_session_factory
            from db.models import SignalRecord, ExecutionRecord

            async with _get_session_factory()() as session:
                sig = SignalRecord(
                    strategy=bot_id,
                    symbol=symbol,
                    action=action,
                    confidence=confidence,
                    processed=True,
                    expected_value=expected_value,
                    kelly_fraction=kelly_fraction,
                    market_edge=market_edge,
                    market_implied_prob=market_implied_prob,
                    mispricing_z_score=mispricing_z_score,
                    xgboost_prob=xgboost_prob,
                    signal_features=signal_features,
                )
                session.add(sig)
                await session.flush()  # populate sig.id

                exe = ExecutionRecord(
                    signal_id=sig.id,
                    alpaca_order_id=order_id,
                    fill_price=fill_price,
                    qty=qty,
                    slippage=slippage,
                    status=status,
                    failure_reason=failure_reason,
                )
                session.add(exe)
                await session.commit()
                logger.debug(
                    "[EXECUTION AGENT] DB write OK — signal_id=%d alpaca=%s status=%s",
                    sig.id, order_id, status
                )

        except Exception as e:
            logger.error("[EXECUTION AGENT] DB persist failed: %s", e)


    def _extract_market_conditions(self, signal: dict) -> str | None:
        """Packs strategy state fields from the signal into a compact JSON string."""
        import json
        meta = signal.get("meta") or {}
        conditions = {
            k: meta.get(k)
            for k in ("rsi", "ema_spread", "volume_ratio", "zone", "bias")
            if meta.get(k) is not None
        }
        return json.dumps(conditions) if conditions else None


execution_agent = ExecutionAgent()
