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


def _is_crypto(symbol: str) -> bool:
    """
    Crypto detection that handles both 'LINK/USD' and 'LINKUSD' formats.
    Checks '/' first, then looks up CRYPTO_STREAM_SYMBOLS (dynamically maintained
    by the scanner), then falls back to a length+suffix heuristic.
    """
    if "/" in symbol:
        return True
    try:
        from core.state import CRYPTO_STREAM_SYMBOLS
        norm = symbol.upper()
        for cs in CRYPTO_STREAM_SYMBOLS:
            if cs.upper().replace("/", "") == norm:
                return True
    except Exception:
        pass
    # Heuristic: Alpaca crypto USD pairs are 5-9 char all-alpha strings ending in USD/USDT/USDC
    return len(symbol) >= 5 and symbol.upper().endswith(("USD", "USDT", "USDC")) and symbol.isalpha()


# Pre-execution guard thresholds sourced from validated config (pydantic-settings)
from config import settings as _cfg
_SLIPPAGE_ABORT_PCT = _cfg.slippage_abort_pct
_MAX_CONCURRENT_POS = _cfg.max_concurrent_positions

# Data client for pre-submission quote fetching (separate from TradingClient)
_data_client = None
try:
    from alpaca.data.historical import StockHistoricalDataClient
    _data_client = StockHistoricalDataClient(
        api_key=_cfg.alpaca_api_key_id,
        secret_key=_cfg.alpaca_api_secret_key,
    )
except Exception as _dce:
    logger.warning("[EXECUTION AGENT] StockHistoricalDataClient init failed: %s — limit orders disabled", _dce)

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

    def __init__(self):
        self.last_error: str | None = None  # set whenever execute() returns None

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

        # Reject equity BUY orders outside market hours — crypto symbols contain "/"
        if action == "BUY" and "/" not in symbol:
            from strategy.equity_algorithms import _is_market_hours
            if not _is_market_hours():
                self.last_error = f"equity market closed for {symbol}"
                logger.warning("[EXECUTION AGENT] Rejected equity BUY outside market hours: %s", symbol)
                return None

        if qty <= 0:
            self.last_error = "zero quantity"
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
            self.last_error = "Alpaca trading_client unavailable — check ALPACA_API_KEY_ID and ALPACA_API_SECRET_KEY in .env"
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
                    self.last_error = f"position limit {_MAX_CONCURRENT_POS} reached ({len(all_positions)} open)"
                    logger.warning(
                        "[EXECUTION AGENT] Position count limit reached (%d/%d) — aborting BUY %s",
                        len(all_positions), _MAX_CONCURRENT_POS, symbol,
                    )
                    self._persist_async(
                        bot_id=bot_id, symbol=symbol, action=action,
                        confidence=approved_signal.get("confidence", 0.0),
                        order_id=None, fill_price=0.0, slippage=0.0,
                        status="FAILED",
                        failure_reason=self.last_error,
                    )
                    return None
            except Exception as _pe:
                logger.debug("[EXECUTION AGENT] Position count check failed: %s", _pe)

        # --- Pre-execution guard: buying power cap ---
        if action == "BUY" and s_price > 0:
            try:
                account = trading_client.get_account()
                buying_power = float(account.buying_power)
                max_affordable_qty = buying_power / s_price
                if max_affordable_qty <= 0:
                    self.last_error = f"insufficient buying power ${buying_power:.2f}"
                    logger.warning(
                        "[EXECUTION AGENT] Insufficient buying power ($%.2f) for %s @ $%.2f — aborting",
                        buying_power, symbol, s_price,
                    )
                    self._persist_async(
                        bot_id=bot_id, symbol=symbol, action=action,
                        confidence=approved_signal.get("confidence", 0.0),
                        order_id=None, fill_price=0.0, slippage=0.0,
                        status="FAILED",
                        failure_reason=self.last_error,
                    )
                    return None
                if qty > max_affordable_qty:
                    adjusted_qty = round(max_affordable_qty * 0.95, 6)  # 5% buffer for price movement
                    logger.warning(
                        "[EXECUTION AGENT] Capping qty %.6f → %.6f for %s (buying_power=$%.2f @ $%.2f)",
                        qty, adjusted_qty, symbol, buying_power, s_price,
                    )
                    qty = adjusted_qty
                    approved_signal = {**approved_signal, "qty": qty}
            except Exception as _bp:
                logger.debug("[EXECUTION AGENT] Buying power check failed: %s — proceeding", _bp)

        # --- Pre-execution guard: slippage check via latest quote ---
        _bid_at_submit = 0.0
        _ask_at_submit = 0.0
        if s_price > 0:
            try:
                if _data_client and not _is_crypto(symbol):
                    from alpaca.data.requests import StockLatestQuoteRequest
                    resp = _data_client.get_stock_latest_quote(
                        StockLatestQuoteRequest(symbol_or_symbols=symbol)
                    )
                    quote = resp.get(symbol)
                else:
                    quote = None
                _bid_at_submit = float(getattr(quote, "bid_price", 0) or 0)
                _ask_at_submit = float(getattr(quote, "ask_price", 0) or 0)
                if _bid_at_submit > 0 and _ask_at_submit > 0:
                    mid = (_bid_at_submit + _ask_at_submit) / 2
                    pre_slip_pct = abs(mid - s_price) / s_price
                    if pre_slip_pct > _SLIPPAGE_ABORT_PCT:
                        resized_qty = round(qty * (s_price / mid), 8) if mid > 0 else 0.0
                        if resized_qty <= 1e-8:
                            logger.warning(
                                "[EXECUTION AGENT] Pre-execution slippage abort: %.2f%% > %.0f%% limit "
                                "for %s (signal=$%.4f mid=$%.4f) — resized qty negligible",
                                pre_slip_pct * 100, _SLIPPAGE_ABORT_PCT * 100, symbol, s_price, mid,
                            )
                            self._persist_async(
                                bot_id=bot_id, symbol=symbol, action=action,
                                confidence=approved_signal.get("confidence", 0.0),
                                order_id=None, fill_price=0.0, slippage=pre_slip_pct * s_price,
                                status="FAILED",
                                failure_reason=f"pre-execution slippage {pre_slip_pct:.2%} > {_SLIPPAGE_ABORT_PCT:.0%} limit — resized qty negligible",
                            )
                            return None
                        logger.warning(
                            "[EXECUTION AGENT] Pre-execution slippage %.2f%% > %.0f%% — resizing qty "
                            "%.6f → %.6f for %s (signal=$%.4f mid=$%.4f)",
                            pre_slip_pct * 100, _SLIPPAGE_ABORT_PCT * 100, qty, resized_qty,
                            symbol, s_price, mid,
                        )
                        qty = resized_qty
                        s_price = mid
            except Exception as _qe:
                logger.debug("[EXECUTION AGENT] Quote slippage check failed: %s — proceeding", _qe)

        # Options routing: branch before equity SELL guard.
        _OPTIONS_ACTIONS = {"BUY_CALL", "SELL_CALL", "BUY_PUT", "SELL_PUT"}
        if action in _OPTIONS_ACTIONS:
            return self._execute_options_order(approved_signal, s_price, trading_client)

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
                    self.last_error = f"no open position found for {symbol} — cannot SELL"
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

        # --- Pre-execution guard: minimum notional ($1.00) ---
        _effective_price = s_price or float(approved_signal.get("price", 0.0)) or 1.0
        _notional = qty * _effective_price
        if _notional < 1.00:
            self.last_error = f"notional ${_notional:.4f} < $1.00 minimum"
            logger.warning(
                "[EXECUTION AGENT] Notional guard: %.9f × $%.4f = $%.4f < $1.00 — aborting %s %s",
                qty, _effective_price, _notional, action, symbol,
            )
            self._persist_async(
                bot_id=bot_id, symbol=symbol, action=action,
                confidence=approved_signal.get("confidence", 0.0),
                order_id=None, fill_price=0.0, slippage=0.0,
                status="FAILED",
                failure_reason=self.last_error,
            )
            return None

        try:
            from alpaca.trading.requests import LimitOrderRequest, MarketOrderRequest
            from alpaca.trading.enums import OrderSide, TimeInForce

            side  = OrderSide.BUY if action == "BUY" else OrderSide.SELL
            is_crypto    = _is_crypto(symbol)
            is_fractional = (qty % 1) != 0

            # Prefer limit orders to cap slippage; fall back to market if no valid quote.
            limit_price: float | None = None
            if _bid_at_submit > 0 and _ask_at_submit > 0:
                if action == "BUY":
                    limit_price = round(_ask_at_submit * 1.0005, 8)
                else:
                    limit_price = round(_bid_at_submit * 0.9995, 8)

            if limit_price and limit_price > 0:
                # IOC for crypto (no stale resting orders); DAY for fractional equity; GTC otherwise
                tif = TimeInForce.IOC if is_crypto else (TimeInForce.DAY if is_fractional else TimeInForce.GTC)
                order = LimitOrderRequest(
                    symbol=symbol, qty=qty, side=side, time_in_force=tif, limit_price=limit_price,
                )
                logger.info("[EXECUTION AGENT] LIMIT order %s %s qty=%.6f @ $%.4f (5bps buffer)",
                            action, symbol, qty, limit_price)
            else:
                # Alpaca requires DAY for fractional equity orders (error 42210000 with GTC)
                tif = TimeInForce.DAY if (not is_crypto and is_fractional) else TimeInForce.GTC
                order = MarketOrderRequest(symbol=symbol, qty=qty, side=side, time_in_force=tif)
                logger.warning("[EXECUTION AGENT] No quote available — falling back to MARKET order for %s", symbol)

            result = trading_client.submit_order(order_data=order)
            order_id = str(result.id)

            # IOC limit orders that don't fill return canceled/expired — treat as not executed.
            if limit_price and str(getattr(result, "status", "")).lower() in ("canceled", "expired"):
                logger.warning(
                    "[EXECUTION AGENT] IOC limit order %s %s unfilled (status=%s) — aborting",
                    action, symbol, result.status,
                )
                self._persist_async(
                    bot_id=bot_id, symbol=symbol, action=action,
                    confidence=approved_signal.get("confidence", 0.0),
                    order_id=order_id, fill_price=0.0, slippage=0.0,
                    status="FAILED",
                    failure_reason=f"IOC limit order unfilled: status={result.status}",
                )
                return None

            filled_avg   = result.filled_avg_price
            # Limit/market orders on paper may return pending_new before fill — one re-fetch gets the real price.
            if not filled_avg:
                try:
                    filled_order = trading_client.get_order_by_id(order_id)
                    filled_avg   = filled_order.filled_avg_price
                except Exception as _fe:
                    logger.debug("[EXECUTION AGENT] Order re-fetch failed for %s: %s", order_id, _fe)
            fill_price = float(filled_avg) if filled_avg else s_price
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
                bid_price=_bid_at_submit,
                ask_price=_ask_at_submit,
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
            self.last_error = failure_reason
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

    # ------------------------------------------------------------------
    # Options order helpers
    # ------------------------------------------------------------------

    def _resolve_option_contract(
        self,
        trading_client,
        underlying: str,
        strike: float,
        expiry_days: int,
        option_type: str,  # "call" | "put"
    ) -> str | None:
        """Find the nearest-match OCC option contract symbol via Alpaca's options chain."""
        from datetime import date, timedelta
        try:
            from alpaca.trading.requests import GetOptionContractsRequest

            today = date.today()
            target_date = today + timedelta(days=expiry_days)
            req = GetOptionContractsRequest(
                underlying_symbols=[underlying],
                type=option_type,
                expiration_date_gte=str(target_date - timedelta(days=7)),
                expiration_date_lte=str(target_date + timedelta(days=7)),
                strike_price_gte=str(round(strike * 0.97, 2)),
                strike_price_lte=str(round(strike * 1.03, 2)),
            )
            response = trading_client.get_option_contracts(req)
            contracts = response.option_contracts or []
            if not contracts:
                logger.warning(
                    "[EXECUTION AGENT] No option contracts found for %s %s strike=%.2f expiry≈%d DTE",
                    underlying, option_type.upper(), strike, expiry_days,
                )
                return None
            # Pick nearest by strike distance, break ties by closest DTE
            best = min(
                contracts,
                key=lambda c: (
                    abs(float(c.strike_price) - strike),
                    abs((date.fromisoformat(str(c.expiration_date)) - target_date).days),
                ),
            )
            logger.info(
                "[EXECUTION AGENT] Resolved option contract: %s (strike=%.2f exp=%s)",
                best.symbol, float(best.strike_price), best.expiration_date,
            )
            return str(best.symbol)
        except Exception as e:
            logger.error("[EXECUTION AGENT] Option contract resolution failed: %s", e)
            return None

    def _execute_options_order(
        self,
        approved_signal: dict,
        s_price: float,
        trading_client,
    ) -> "ExecutionResult | None":
        """Submit an options order (covered call, protective put, etc.)."""
        from alpaca.trading.requests import MarketOrderRequest, GetOptionContractsRequest  # noqa: F401
        from alpaca.trading.enums import OrderSide, OrderType, TimeInForce, PositionIntent

        underlying = approved_signal.get("symbol", "UNKNOWN")
        action      = approved_signal.get("action", "")
        bot_id      = approved_signal.get("bot", "unknown")
        meta        = approved_signal.get("meta") or {}
        strike      = float(meta.get("strike", s_price))
        expiry_days = int(meta.get("expiry_days", 30))
        option_type = "call" if "CALL" in action else "put"
        is_sell     = action.startswith("SELL_")

        # For covered writes, require an underlying equity position.
        held_qty = 0.0
        if is_sell:
            try:
                positions = trading_client.get_all_positions()
                held_qty = sum(
                    float(p.qty) for p in positions
                    if p.symbol.replace("/", "") == underlying
                )
            except Exception as pe:
                logger.warning("[EXECUTION AGENT] OPTIONS guard: position check failed (%s) — proceeding", pe)

            if held_qty < 100.0:
                logger.warning(
                    "[EXECUTION AGENT] OPTIONS guard: insufficient underlying for covered %s %s "
                    "(held=%.4f shares, need ≥100 per contract) — aborting",
                    action, underlying, held_qty,
                )
                self._persist_async(
                    bot_id=bot_id, symbol=underlying, action=action,
                    confidence=approved_signal.get("confidence", 0.0),
                    order_id=None, fill_price=0.0, slippage=0.0,
                    status="FAILED",
                    failure_reason=f"insufficient underlying for covered write (held={held_qty:.4f} < 100)",
                )
                return None

        # 1 contract covers 100 shares; guard above ensures held_qty ≥ 100 for sells.
        contracts = int(held_qty / 100) if is_sell else 1

        contract_symbol = self._resolve_option_contract(
            trading_client, underlying, strike, expiry_days, option_type
        )
        if not contract_symbol:
            self._persist_async(
                bot_id=bot_id, symbol=underlying, action=action,
                confidence=approved_signal.get("confidence", 0.0),
                order_id=None, fill_price=0.0, slippage=0.0,
                status="FAILED", failure_reason="no matching option contract found",
            )
            return None

        side             = OrderSide.SELL if is_sell else OrderSide.BUY
        position_intent  = PositionIntent.SELL_TO_OPEN if is_sell else PositionIntent.BUY_TO_OPEN

        try:
            order = MarketOrderRequest(
                symbol=contract_symbol,
                qty=contracts,
                side=side,
                time_in_force=TimeInForce.DAY,
                position_intent=position_intent,
            )
            result     = trading_client.submit_order(order_data=order)
            order_id   = str(result.id)
            fill_price = float(result.filled_avg_price) if result.filled_avg_price else s_price
            slippage   = abs(fill_price - s_price)
            slip_pct   = (slippage / s_price * 100) if s_price > 0 else 0.0

            logger.info(
                "[EXECUTION AGENT] OPTIONS FILLED %s %s contract=%s qty=%d fill=$%.4f signal=$%.2f slippage=$%.4f",
                action, underlying, contract_symbol, contracts, fill_price, s_price, slippage,
            )

            self._persist_async(
                bot_id=bot_id,
                symbol=underlying,
                action=action,
                confidence=approved_signal.get("confidence", 0.0),
                order_id=order_id,
                fill_price=fill_price,
                qty=float(contracts),
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
                contract_symbol=contract_symbol,
                option_type=option_type,
                strike_price=strike,
                expiry_days=expiry_days,
            )

            return ExecutionResult(
                order_id=order_id,
                symbol=underlying,
                action=action,
                qty=float(contracts),
                fill_price=fill_price,
                signal_price=s_price,
                slippage=slippage,
                slippage_pct=round(slip_pct, 6),
                bot_id=bot_id,
                timestamp=datetime.utcnow().isoformat(),
                market_conditions=None,
                hold_duration_min=None,
            )

        except Exception as e:
            failure_reason = str(e)
            logger.error("[EXECUTION AGENT] OPTIONS submission failed for %s %s: %s", action, underlying, failure_reason)
            self._persist_async(
                bot_id=bot_id, symbol=underlying, action=action,
                confidence=approved_signal.get("confidence", 0.0),
                order_id=None, fill_price=0.0, slippage=0.0,
                status="FAILED", failure_reason=failure_reason,
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
        bid_price: float = 0.0,
        ask_price: float = 0.0,
        contract_symbol: str | None = None,
        option_type: str | None = None,
        strike_price: float | None = None,
        expiry_days: int | None = None,
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
                    bid_price=bid_price,
                    ask_price=ask_price,
                    contract_symbol=contract_symbol,
                    option_type=option_type,
                    strike_price=strike_price,
                    expiry_days=expiry_days,
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
        bid_price: float = 0.0,
        ask_price: float = 0.0,
        contract_symbol: str | None = None,
        option_type: str | None = None,
        strike_price: float | None = None,
        expiry_days: int | None = None,
    ):
        """Writes SignalRecord, ExecutionRecord, and MarketConditionSnapshot to SQLite."""
        try:
            from db.database import _get_session_factory
            from db.models import SignalRecord, ExecutionRecord, MarketConditionSnapshot

            import re as _re
            _CRYPTO_RE = _re.compile(r'^[A-Z]{2,6}(USD[TC]?|BTC|ETH)$')
            _OPT_ACTIONS = {"BUY_CALL", "SELL_CALL", "BUY_PUT", "SELL_PUT"}
            if action.upper() in _OPT_ACTIONS:
                asset_class = "OPTIONS"
            elif "/" in symbol or bool(_CRYPTO_RE.match(symbol)):
                asset_class = "CRYPTO"
            else:
                asset_class = "EQUITY"

            # Derive ISO expiry date from expiry_days offset if provided
            expiry_date: str | None = None
            if expiry_days is not None:
                from datetime import date, timedelta
                expiry_date = (date.today() + timedelta(days=expiry_days)).isoformat()

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
                    asset_class=asset_class,
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
                    asset_class=asset_class,
                    bid_price=bid_price if bid_price > 0 else None,
                    ask_price=ask_price if ask_price > 0 else None,
                    contract_symbol=contract_symbol,
                    option_type=option_type,
                    strike_price=strike_price,
                    expiry_date=expiry_date,
                )
                session.add(exe)
                await session.flush()  # populate exe.id

                # Write market condition snapshot whenever we have valid quote data
                if bid_price > 0 and ask_price > 0:
                    mcs = MarketConditionSnapshot(
                        execution_id=exe.id,
                        symbol=symbol,
                        bid_price=bid_price,
                        ask_price=ask_price,
                        spread=round(ask_price - bid_price, 8),
                    )
                    session.add(mcs)

                await session.commit()
                logger.debug(
                    "[EXECUTION AGENT] DB write OK — signal_id=%d alpaca=%s status=%s asset=%s",
                    sig.id, order_id, status, asset_class
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
