"""
Execution Agent — Order Submission + Slippage Recorder
========================================================
Terminal node in the signal pipeline. Receives risk-approved signals,
submits orders to Alpaca, calculates slippage, and persists records
to the SQLite database (SignalRecord + ExecutionRecord).
"""

import logging
from datetime import datetime

logger = logging.getLogger(__name__)

# Lazy imports for DB to avoid circular imports at module load time


class ExecutionResult:
    __slots__ = ("order_id", "symbol", "action", "qty", "fill_price",
                 "signal_price", "slippage", "slippage_pct", "bot_id", "timestamp")

    def __init__(self, **kwargs):
        for k, v in kwargs.items():
            setattr(self, k, v)

    def to_dict(self) -> dict:
        return {s: getattr(self, s, None) for s in self.__slots__}


class ExecutionAgent:
    """
    Handles physical Alpaca order submission.
    For every approved signal:
      1. Pulls trading_client from __main__ (same pattern as AlpacaRouter)
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
            return None

        import __main__
        trading_client = getattr(__main__, "trading_client", None)

        if not trading_client:
            logger.warning("[EXECUTION AGENT] trading_client unavailable — skipping live submission.")
            return None

        try:
            from alpaca.trading.requests import MarketOrderRequest
            from alpaca.trading.enums import OrderSide, TimeInForce

            side  = OrderSide.BUY if action == "BUY" else OrderSide.SELL
            order = MarketOrderRequest(
                symbol=symbol,
                qty=qty,
                side=side,
                time_in_force=TimeInForce.GTC,
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
                slippage=slippage,
            )

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
            )

        except Exception as e:
            logger.error("[EXECUTION AGENT] Submission failed for %s %s: %s", action, symbol, e)
            return None

    def _persist_async(
        self,
        bot_id: str,
        symbol: str,
        action: str,
        confidence: float,
        order_id: str,
        fill_price: float,
        slippage: float,
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
                    bot_id=bot_id, symbol=symbol, action=action,
                    confidence=confidence, order_id=order_id,
                    fill_price=fill_price, slippage=slippage,
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
        order_id: str,
        fill_price: float,
        slippage: float,
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
                )
                session.add(sig)
                await session.flush()  # populate sig.id

                exe = ExecutionRecord(
                    signal_id=sig.id,
                    alpaca_order_id=order_id,
                    fill_price=fill_price,
                    slippage=slippage,
                )
                session.add(exe)
                await session.commit()
                logger.debug("[EXECUTION AGENT] DB write OK — signal_id=%d alpaca=%s", sig.id, order_id)

        except Exception as e:
            logger.error("[EXECUTION AGENT] DB persist failed: %s", e)


execution_agent = ExecutionAgent()
