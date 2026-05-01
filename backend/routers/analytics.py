import logging
import re
from datetime import timezone as _utc
from fastapi import APIRouter
from deps import get_trading_client, trading_client
from core.state import _entry_prices, _entry_times

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/api")

_PERIOD_DAYS = {"1D": 1, "1W": 7, "1M": 30, "YTD": 180, "ALL": 36500}

# Matches Alpaca crypto order symbols: e.g. BTCUSD, LTCUSD, DOGEUSDT, MATICUSD
_CRYPTO_SYMBOL_RE = re.compile(r'^[A-Z]{2,6}(USD[TC]?|BTC|ETH)$')


def _avg(vals):
    filtered = [v for v in vals if v is not None]
    return round(sum(filtered) / len(filtered), 4) if filtered else None


def _fmt_ts(ts) -> str | None:
    if ts is None:
        return None
    if ts.tzinfo is None:
        ts = ts.replace(tzinfo=_utc.utc)
    return ts.isoformat().replace("+00:00", "Z")


def _is_crypto_symbol(symbol: str | None) -> bool:
    if not symbol:
        return False
    return "/" in symbol or bool(_CRYPTO_SYMBOL_RE.match(symbol))


_OPTIONS_ACTIONS = frozenset({"BUY_CALL", "SELL_CALL", "BUY_PUT", "SELL_PUT"})


def _infer_asset_class(symbol: str | None, stored: str | None = None, action: str | None = None) -> str:
    if action and action.upper() in _OPTIONS_ACTIONS:
        return "OPTIONS"
    if stored == "OPTIONS":
        return "OPTIONS"
    # Re-detect from symbol to correct legacy records stored as EQUITY for crypto pairs
    if _is_crypto_symbol(symbol):
        return "CRYPTO"
    if stored:
        return stored
    return "EQUITY"

@router.get("/ledger")
async def get_ledger(limit: int = 50):
    """Returns historical execution records joined with their originating signals."""
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
                    SignalRecord.asset_class,
                )
                .join(SignalRecord, ExecutionRecord.signal_id == SignalRecord.id, isouter=True)
                .order_by(desc(ExecutionRecord.timestamp))
                .limit(limit)
            )
            rows = (await session.execute(stmt)).all()

        return [
            {
                "id": r.id,
                "order_id": r.alpaca_order_id[:8] if r.alpaca_order_id else None,
                "symbol": r.symbol,
                "side": r.action,
                "bot": r.strategy,
                "fill_price": r.fill_price,
                "slippage": r.slippage,
                "slippage_bps": round(r.slippage / r.fill_price * 10000, 2) if r.fill_price else None,
                "confidence": r.confidence,
                "asset_class": _infer_asset_class(r.symbol, r.asset_class, action=r.action),
                "timestamp": _fmt_ts(r.timestamp),
            }
            for r in rows
        ]
    except Exception as e:
        logger.error("[LEDGER] %s", e)
        return []


@router.post("/backfill-fill-prices")
async def backfill_fill_prices():
    """
    Two-phase repair:

    Phase 1 — Fix fill_price = 0 ExecutionRecords by fetching filled_avg_price
    from Alpaca using the stored alpaca_order_id. Recalculates ClosedTrade exit
    metrics for any linked exit leg.

    Phase 2 — Reconcile stale _entry_prices entries. For every (bot, symbol) the
    bot believes is still open, check against Alpaca's actual positions. If the
    position is gone, find the closing SELL order in Alpaca's history, write or
    patch the ClosedTrade record, and purge the stale entry from memory + disk.
    """
    import asyncio
    from decimal import Decimal
    from datetime import datetime, timezone
    from sqlalchemy import select
    from db.database import _get_session_factory
    from db.models import ExecutionRecord, ClosedTrade

    client = get_trading_client()
    if not client:
        return {"error": "trading client unavailable", "updated": 0, "skipped": 0, "reconciled": 0}

    factory  = _get_session_factory()
    updated  = 0
    skipped  = 0

    # ------------------------------------------------------------------
    # Phase 1: fix fill_price = 0 on FILLED ExecutionRecords
    # ------------------------------------------------------------------
    async with factory() as session:
        stmt = select(ExecutionRecord).where(
            ExecutionRecord.fill_price == Decimal("0"),
            ExecutionRecord.alpaca_order_id.isnot(None),
            ExecutionRecord.status == "FILLED",
        )
        zero_records = (await session.execute(stmt)).scalars().all()

    for rec in zero_records:
        try:
            order = await asyncio.to_thread(client.get_order_by_id, rec.alpaca_order_id)
            raw = order.filled_avg_price
        except Exception as e:
            logger.warning("[BACKFILL P1] Alpaca fetch failed for %s: %s", rec.alpaca_order_id[:8], e)
            skipped += 1
            continue

        if not raw:
            skipped += 1
            continue

        actual = Decimal(str(raw))
        async with factory() as session:
            row = await session.get(ExecutionRecord, rec.id)
            if row is None:
                skipped += 1
                continue
            row.fill_price = actual
            row.slippage   = Decimal("0")

            ct_stmt = select(ClosedTrade).where(ClosedTrade.exit_execution_id == rec.id)
            ct = (await session.execute(ct_stmt)).scalar_one_or_none()
            if ct is not None:
                entry = Decimal(str(ct.avg_entry_price or 0))
                qty   = Decimal(str(ct.qty or 0))
                pnl   = (actual - entry) * qty
                ct.avg_exit_price = actual
                ct.realized_pnl   = pnl
                ct.net_pnl        = pnl
                ct.win            = pnl > 0

            await session.commit()
            updated += 1
            logger.info("[BACKFILL P1] Fixed id=%d %s → %s", rec.id, rec.alpaca_order_id[:8], actual)

    # ------------------------------------------------------------------
    # Phase 2: reconcile stale _entry_prices against live Alpaca positions
    # ------------------------------------------------------------------
    from core.state import _entry_prices, _entry_times, persist_entry_prices
    from alpaca.trading.requests import GetOrdersRequest
    from alpaca.trading.enums import QueryOrderStatus

    # Build set of symbols currently open in Alpaca (normalised, no slash)
    live_norm: set[str] = set()
    try:
        for p in await asyncio.to_thread(client.get_all_positions):
            live_norm.add(str(p.symbol).upper().replace("/", ""))
    except Exception as e:
        logger.warning("[BACKFILL P2] Could not fetch live positions: %s", e)
        return {"updated": updated, "skipped": skipped, "reconciled": 0}

    # Fetch closed SELL orders from Alpaca (up to 500) for exit price lookup
    sell_orders: dict[str, list] = {}   # norm_symbol → [order, ...]
    try:
        orders = await asyncio.to_thread(
            client.get_orders,
            filter=GetOrdersRequest(status=QueryOrderStatus.CLOSED, limit=500),
        )
        for o in orders:
            if o.filled_avg_price is None:
                continue
            if str(o.side).split(".")[-1].upper() != "SELL":
                continue
            norm = str(o.symbol).upper().replace("/", "")
            sell_orders.setdefault(norm, []).append(o)
    except Exception as e:
        logger.warning("[BACKFILL P2] Could not fetch closed orders: %s", e)

    reconciled = 0
    stale_keys: list[tuple] = []

    for (bot, sym), entry_price in list(_entry_prices.items()):
        norm = sym.upper().replace("/", "")
        if norm in live_norm:
            continue    # still open — leave it alone

        stale_keys.append((bot, sym))

        # Parse entry time for chronological matching
        entry_time: datetime | None = None
        entry_time_str = _entry_times.get((bot, sym))
        if entry_time_str:
            try:
                entry_time = datetime.fromisoformat(entry_time_str)
                if entry_time.tzinfo is None:
                    entry_time = entry_time.replace(tzinfo=timezone.utc)
            except Exception:
                pass

        # Find best matching SELL order: filled after entry_time, earliest first
        candidates = sell_orders.get(norm, [])
        if entry_time:
            candidates = [o for o in candidates if o.filled_at and o.filled_at >= entry_time]
        candidates = sorted(candidates, key=lambda o: o.filled_at or datetime.min.replace(tzinfo=timezone.utc))
        sell = candidates[0] if candidates else None

        exit_price = float(sell.filled_avg_price) if sell else float(entry_price)
        exit_time  = sell.filled_at if sell else None
        qty_val    = float(sell.filled_qty or 0) if sell else 0.0
        pnl        = (exit_price - float(entry_price)) * qty_val

        async with factory() as session:
            # Find existing ClosedTrade for this bot+symbol with no exit recorded
            ct_stmt = select(ClosedTrade).where(
                ClosedTrade.bot_id == bot,
                ClosedTrade.symbol == sym,
            ).order_by(ClosedTrade.id.desc()).limit(1)
            ct = (await session.execute(ct_stmt)).scalar_one_or_none()

            if ct and (ct.avg_exit_price is None or float(ct.avg_exit_price or 0) == 0):
                ct.avg_exit_price = Decimal(str(exit_price))
                ct.exit_time      = exit_time
                ct.realized_pnl   = Decimal(str(round(pnl, 8)))
                ct.net_pnl        = Decimal(str(round(pnl, 8)))
                ct.win            = pnl > 0
                if qty_val > 0:
                    ct.qty = Decimal(str(qty_val))
            elif not ct:
                ct_entry = None
                if entry_time_str:
                    try:
                        ct_entry = datetime.fromisoformat(entry_time_str)
                        if ct_entry.tzinfo is None:
                            ct_entry = ct_entry.replace(tzinfo=timezone.utc)
                    except Exception:
                        pass
                session.add(ClosedTrade(
                    bot_id          = bot,
                    symbol          = sym,
                    qty             = Decimal(str(qty_val)),
                    avg_entry_price = Decimal(str(entry_price)),
                    avg_exit_price  = Decimal(str(exit_price)),
                    entry_time      = ct_entry,
                    exit_time       = exit_time,
                    realized_pnl    = Decimal(str(round(pnl, 8))),
                    net_pnl         = Decimal(str(round(pnl, 8))),
                    win             = pnl > 0,
                    asset_class     = "CRYPTO" if _is_crypto_symbol(sym) else "EQUITY",
                ))
            else:
                # ClosedTrade already has a valid exit — just purge the stale key
                pass

            await session.commit()
            reconciled += 1
            logger.info("[BACKFILL P2] Reconciled %s/%s exit=%.4f pnl=%.4f", bot, sym, exit_price, pnl)

    # Purge stale keys from memory and persist to disk
    for key in stale_keys:
        _entry_prices.pop(key, None)
        _entry_times.pop(key, None)
    if stale_keys:
        persist_entry_prices(_entry_prices, _entry_times)
        logger.info("[BACKFILL P2] Purged %d stale entries from _entry_prices", len(stale_keys))

    return {"updated": updated, "skipped": skipped, "reconciled": reconciled}


@router.get("/reflections")
async def get_reflections(limit: int = 50):
    """Returns the historical BotAmend records from SQLite."""
    try:
        from sqlalchemy import select, desc
        from db.database import _get_session_factory
        from db.models import BotAmend

        async with _get_session_factory()() as session:
            stmt = select(BotAmend).order_by(desc(BotAmend.timestamp)).limit(limit)
            rows = (await session.execute(stmt)).scalars().all()

        return [
            {
                "model": r.model,
                "action": r.action,
                "reason": r.reason,
                "impact": r.impact,
                "date": r.timestamp.strftime("%Y-%m-%d %H:%M") if r.timestamp else None,
            }
            for r in rows
        ]
    except Exception as e:
        logger.error("[REFLECTIONS] %s", e)
        return []


@router.get("/reflections/history")
async def get_reflections_history(limit: int = 50):
    """Returns last N ReflectionLog rows (post-trade AI insights)."""
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
                "id": r.id,
                "strategy": r.strategy,
                "symbol": r.symbol,
                "action": r.action,
                "insight": r.insight,
                "tokens_used": r.tokens_used,
                "timestamp": r.timestamp.strftime("%Y-%m-%d %H:%M") if r.timestamp else None,
            }
            for r in rows
        ]
    except Exception as e:
        logger.error("[REFLECTIONS/HISTORY] %s", e)
        return []


@router.get("/performance")
async def get_performance(period: str = "1M"):
    """Fetches real portfolio history from Alpaca."""
    client = get_trading_client()
    period_map = {
        "1D": ("1D", "1Min"),
        "1W": ("1W", "1H"),
        "1M": ("1M", "1D"),
        "YTD": ("6M", "1D"),
    }
    alpaca_period, timeframe = period_map.get(period.upper(), ("1M", "1D"))
    try:
        hist = client.get(
            "/account/portfolio/history",
            {"period": alpaca_period, "timeframe": timeframe},
        )

        timestamps = hist.get("timestamp") or []
        equities = hist.get("equity") or []
        profit_loss = hist.get("profit_loss") or []

        if not timestamps:
            return {"history": [], "net_pnl": 0.0, "drawdown": 0.0, "has_data": False}

        # Use profit_loss (cumulative PnL from period start) for the equity curve so the
        # chart shows meaningful gain/loss rather than a flat absolute-equity line.
        valid_pnl = [p for p in profit_loss if p is not None]
        net_pnl = valid_pnl[-1] if valid_pnl else 0.0

        # Build curve from profit_loss; fall back to equity if profit_loss is empty
        if any(p is not None for p in profit_loss):
            curve = [
                [timestamps[i] * 1000, profit_loss[i]]
                for i in range(len(timestamps))
                if i < len(profit_loss) and profit_loss[i] is not None
            ]
        else:
            curve = [[timestamps[i] * 1000, equities[i]] for i in range(len(timestamps)) if equities[i] is not None]

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

        realized_trades = []
        formula_metrics = {}
        total_trades = 0
        brier_score = None
        try:
            from db.database import _get_session_factory as _gsf
            from db.models import ClosedTrade as _CT, CalibrationRecord as _CR
            from sqlalchemy import select as _sel, func as _func

            async with _gsf()() as _s:
                _ct_rows = (await _s.execute(_sel(_CT).order_by(_CT.exit_time))).scalars().all()
                total_trades = (await _s.execute(_sel(_func.count()).select_from(_CT))).scalar() or 0
                _cal_rows = (await _s.execute(_sel(_CR))).scalars().all()

            for _r in _ct_rows:
                realized_trades.append({
                    "strategy": _r.bot_id,
                    "symbol": _r.symbol,
                    "pnl": round(float(_r.realized_pnl or 0), 4),
                    "timestamp": _r.exit_time.isoformat() if _r.exit_time else None,
                })

            if _ct_rows:
                formula_metrics = {
                    "avg_ev": _avg([float(r.entry_ev) for r in _ct_rows if r.entry_ev is not None]),
                    "avg_kelly": _avg([float(r.entry_kelly) for r in _ct_rows if r.entry_kelly is not None]),
                    "avg_market_edge": _avg([float(r.entry_edge) for r in _ct_rows if r.entry_edge is not None]),
                    "avg_brier": _avg([float(r.brier_contribution) for r in _ct_rows if r.brier_contribution is not None]),
                }

            if _cal_rows:
                brier_score = round(
                    sum(float(r.brier_contribution or 0) for r in _cal_rows) / len(_cal_rows), 4
                )
        except Exception as _rt_exc:
            logger.debug("[PERFORMANCE] DB fetch failed: %s", _rt_exc)

        return {
            "history": curve,
            "net_pnl": net_pnl,
            "drawdown": round(max_dd, 4),
            "has_data": len(curve) > 0,
            "sharpe": sharpe,
            "sortino": sortino,
            "realized_trades": realized_trades,
            "brier_score": brier_score,
            "total_trades": total_trades,
            "formula_metrics": formula_metrics or None,
        }
    except Exception as e:
        logger.error("[PERFORMANCE] %s", e)
        return {"history": [], "net_pnl": 0.0, "drawdown": 0.0, "has_data": False,
                "sharpe": 0.0, "sortino": 0.0, "realized_trades": []}


@router.get("/analytics/returns")
async def get_return_distribution():
    """Slippage distribution from ExecutionRecord."""
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

        slippages_bps = [
            r[1] / r[0] * 10000
            for r in rows
            if r[0] > 0 and r[1] is not None
        ]

        if not slippages_bps:
            return {"buckets": [], "has_data": False}

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
                counts[-1] += 1

        total = max(sum(counts), 1)
        buckets = [
            {"label": f"{edges[i]:+d}bps", "count": counts[i], "pct": round(counts[i] / total * 100, 1)}
            for i in range(n_buckets)
        ]
        return {"buckets": buckets, "has_data": True, "sample_size": len(slippages_bps)}
    except Exception as e:
        logger.error("[ANALYTICS] returns distribution failed: %s", e)
        return {"buckets": [], "has_data": False}


@router.get("/analytics/signals")
async def get_signals_analytics(period: str = "1D"):
    from datetime import datetime as _dt, timezone as _tz, timedelta
    from db.database import _get_session_factory
    from db.models import SignalRecord, CalibrationRecord
    from sqlalchemy import select as _sel

    days = _PERIOD_DAYS.get(period.upper(), 1)
    cutoff = _dt.now(_tz.utc) - timedelta(days=days)

    try:
        from db.models import ClosedTrade
        from sqlalchemy import func as _func
        async with _get_session_factory()() as session:
            sig_rows = (await session.execute(
                _sel(SignalRecord).where(SignalRecord.timestamp >= cutoff)
            )).scalars().all()
            cal_rows = (await session.execute(
                _sel(CalibrationRecord).where(CalibrationRecord.timestamp >= cutoff)
            )).scalars().all()
            pnl_rows = (await session.execute(
                _sel(
                    ClosedTrade.bot_id,
                    ClosedTrade.win,
                    _func.sum(ClosedTrade.net_pnl).label("total_pnl"),
                    _func.avg(ClosedTrade.net_pnl).label("avg_pnl"),
                ).where(ClosedTrade.exit_time >= cutoff).group_by(ClosedTrade.bot_id, ClosedTrade.win)
            )).all()

        edges, mispricings, bayes_updates, arb_flags = [], [], [], []
        for r in sig_rows:
            if r.market_edge is not None:
                edges.append(float(r.market_edge))
            if r.mispricing_z_score is not None:
                mispricings.append(float(r.mispricing_z_score))
            xp = float(r.xgboost_prob) if r.xgboost_prob is not None else None
            mp = float(r.market_implied_prob) if r.market_implied_prob is not None else None
            if xp is not None and mp is not None and mp > 0:
                bayes_updates.append(xp / mp)
                arb_flags.append(1 if xp > mp else 0)

        arb_score = round(sum(arb_flags) / len(arb_flags), 4) if arb_flags else None

        pnl_by_bot: dict = {}
        avg_win_pnl: dict = {}
        avg_loss_pnl: dict = {}
        for r in pnl_rows:
            if not r.bot_id:
                continue
            if r.win:
                pnl_by_bot[r.bot_id] = pnl_by_bot.get(r.bot_id, 0.0) + float(r.total_pnl or 0)
                avg_win_pnl[r.bot_id] = float(r.avg_pnl or 0)
            else:
                pnl_by_bot[r.bot_id] = pnl_by_bot.get(r.bot_id, 0.0) + float(r.total_pnl or 0)
                avg_loss_pnl[r.bot_id] = float(r.avg_pnl or 0)

        asset_class_by_strat: dict = {
            r.strategy: r.asset_class
            for r in sig_rows
            if r.strategy and r.asset_class
        }

        agent_map: dict = {}
        for r in cal_rows:
            strat = r.strategy or "unknown"
            if strat not in agent_map:
                agent_map[strat] = {"wins": 0, "total": 0, "conf_sum": 0.0}
            agent_map[strat]["total"] += 1
            agent_map[strat]["wins"] += int(r.outcome or 0)
            agent_map[strat]["conf_sum"] += float(r.forecast or 0)

        by_agent = sorted(
            [
                {
                    "agent": k,
                    "avg_confidence": round(v["conf_sum"] / v["total"], 4),
                    "win_rate": round(v["wins"] / v["total"], 4),
                    "trade_count": v["total"],
                    "total_pnl": round(pnl_by_bot.get(k, 0.0), 2),
                    "asset_class": asset_class_by_strat.get(k, "EQUITY" if "/" not in k else "CRYPTO"),
                }
                for k, v in agent_map.items() if v["total"] >= 1
            ],
            key=lambda x: x["trade_count"],
            reverse=True,
        )

        dist = [
            {"bucket_min": round(i / 10, 1), "bucket_max": round((i + 1) / 10, 1), "wins": 0, "losses": 0, "pnl": 0.0}
            for i in range(10)
        ]
        for r in cal_rows:
            if r.forecast is None:
                continue
            idx = min(int(float(r.forecast) * 10), 9)
            strat = r.strategy or "unknown"
            if r.outcome == 1:
                dist[idx]["wins"] += 1
                dist[idx]["pnl"] += avg_win_pnl.get(strat, 0.0)
            else:
                dist[idx]["losses"] += 1
                dist[idx]["pnl"] += avg_loss_pnl.get(strat, 0.0)
        for d in dist:
            d["pnl"] = round(d["pnl"], 2)

        return {
            "has_data": len(sig_rows) > 0 or len(cal_rows) > 0,
            "avg_market_edge": _avg(edges),
            "avg_mispricing_z": _avg(mispricings),
            "avg_bayes_update": _avg(bayes_updates),
            "arb_score": arb_score,
            "by_agent": by_agent,
            "confidence_distribution": dist,
        }
    except Exception as exc:
        logger.error("[SIGNALS ANALYTICS] %s", exc)
        return {"has_data": False, "avg_market_edge": None, "avg_mispricing_z": None,
                "avg_bayes_update": None, "arb_score": None, "by_agent": [], "confidence_distribution": []}


@router.get("/analytics/llm-cost")
async def get_llm_cost(period: str = "1M"):
    from datetime import datetime, timedelta, timezone

    days_back = _PERIOD_DAYS.get(period.upper(), 30)
    cutoff = datetime.now(timezone.utc) - timedelta(days=days_back)

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

            from sqlalchemy import func as sqlfunc
            purpose_rows = (await session.execute(
                select(
                    sqlfunc.strftime("%Y-%m-%d", LLMUsage.timestamp).label("day"),
                    LLMUsage.purpose,
                    sqlfunc.sum(LLMUsage.cost_usd).label("cost"),
                )
                .where(LLMUsage.timestamp >= cutoff)
                .group_by("day", LLMUsage.purpose)
            )).fetchall()

        daily_cost = {}
        for ts, cost in cost_rows:
            if ts:
                day = ts.strftime("%Y-%m-%d")
                daily_cost[day] = daily_cost.get(day, 0.0) + float(cost or 0.0)

        cum_cost = 0.0
        cost_series = []
        for ts, cost in cost_rows:
            if ts:
                cum_cost += float(cost or 0)
                cost_series.append([int(ts.timestamp() * 1000), round(cum_cost, 6)])

        pnl_series = []
        daily_pnl = {}
        cum_pnl = 0.0
        try:
            if trading_client:
                hist = trading_client.get("/account/portfolio/history",
                                         {"period": alpaca_period, "timeframe": alpaca_tf})
                timestamps = hist.get("timestamp") or []
                profit_loss = hist.get("profit_loss") or []
                for i, ts_epoch in enumerate(timestamps):
                    if i < len(profit_loss) and profit_loss[i] is not None:
                        cum_pnl = profit_loss[i]
                        pnl_series.append([ts_epoch * 1000, round(cum_pnl, 2)])
                        # Bucket into calendar day regardless of timeframe (last value wins = end-of-day cumulative)
                        day = datetime.utcfromtimestamp(ts_epoch).strftime("%Y-%m-%d")
                        daily_pnl[day] = round(profit_loss[i], 2)
        except Exception as pnl_err:
            logger.debug("[ANALYTICS] portfolio history: %s", pnl_err)

        daily_purpose = {}
        for day, purpose, cost in purpose_rows:
            if day:
                daily_purpose.setdefault(day, {})[purpose] = round(float(cost or 0), 6)

        all_days = sorted(set(list(daily_cost.keys()) + list(daily_pnl.keys())))
        daily_rows = []
        for day in all_days:
            pnl_d = daily_pnl.get(day, 0.0)
            cost_d = daily_cost.get(day, 0.0)
            ratio = round(pnl_d / cost_d, 2) if cost_d > 0 else None
            daily_rows.append({"date": day, "pnl_usd": round(pnl_d, 2),
                                "cost_usd": round(cost_d, 6), "ratio": ratio,
                                "cost_by_purpose": daily_purpose.get(day, {})})

        total_cost = sum(r["cost_usd"] for r in daily_rows)
        cumulative_ratio = round(cum_pnl / total_cost, 2) if total_cost > 0 else None

        return {
            "has_data": bool(cost_series or pnl_series),
            "cumulative_cost": cost_series,
            "cumulative_pnl": pnl_series,
            "daily_rows": daily_rows[-30:],
            "total_cost_usd": round(total_cost, 6),
            "total_pnl_usd": round(cum_pnl, 2),
            "cumulative_ratio": cumulative_ratio,
        }

    except Exception as e:
        logger.error("[ANALYTICS] llm-cost failed: %s", e)
        return {"has_data": False, "cumulative_cost": [], "cumulative_pnl": [],
                "daily_rows": [], "cumulative_ratio": None}


@router.get("/analytics/llm-breakdown")
async def get_llm_breakdown(period: str = "1M"):
    from datetime import datetime, timedelta, timezone

    days_back = _PERIOD_DAYS.get(period.upper(), 30)
    cutoff = datetime.now(timezone.utc) - timedelta(days=days_back)

    try:
        from db.database import _get_session_factory
        from db.models import LLMUsage
        from sqlalchemy import select, func as sqlfunc

        async with _get_session_factory()() as session:
            model_rows = (await session.execute(
                select(
                    LLMUsage.model,
                    sqlfunc.count(LLMUsage.id).label("calls"),
                    sqlfunc.sum(LLMUsage.tokens_in).label("tokens_in"),
                    sqlfunc.sum(LLMUsage.tokens_out).label("tokens_out"),
                    sqlfunc.sum(LLMUsage.cost_usd).label("cost_usd"),
                )
                .where(LLMUsage.timestamp >= cutoff)
                .group_by(LLMUsage.model)
                .order_by(sqlfunc.sum(LLMUsage.cost_usd).desc())
            )).fetchall()

            purpose_rows = (await session.execute(
                select(
                    LLMUsage.purpose,
                    sqlfunc.count(LLMUsage.id).label("calls"),
                    sqlfunc.sum(LLMUsage.cost_usd).label("cost_usd"),
                    sqlfunc.sum(LLMUsage.tokens_in).label("tokens_in"),
                    sqlfunc.sum(LLMUsage.tokens_out).label("tokens_out"),
                )
                .where(LLMUsage.timestamp >= cutoff)
                .group_by(LLMUsage.purpose)
                .order_by(sqlfunc.sum(LLMUsage.cost_usd).desc())
            )).fetchall()

            recent_rows = (await session.execute(
                select(
                    LLMUsage.model,
                    LLMUsage.purpose,
                    LLMUsage.tokens_in,
                    LLMUsage.tokens_out,
                    LLMUsage.cost_usd,
                    LLMUsage.timestamp,
                )
                .where(LLMUsage.timestamp >= cutoff)
                .order_by(LLMUsage.timestamp.desc())
                .limit(15)
            )).fetchall()

            totals = (await session.execute(
                select(
                    sqlfunc.count(LLMUsage.id),
                    sqlfunc.sum(LLMUsage.tokens_in),
                    sqlfunc.sum(LLMUsage.tokens_out),
                    sqlfunc.sum(LLMUsage.cost_usd),
                )
                .where(LLMUsage.timestamp >= cutoff)
            )).fetchone()

        total_calls, total_ti, total_to, total_cost = totals or (0, 0, 0, 0)

        return {
            "has_data": bool(total_calls and total_calls > 0),
            "total_calls": int(total_calls or 0),
            "total_tokens_in": int(total_ti or 0),
            "total_tokens_out": int(total_to or 0),
            "total_cost_usd": round(float(total_cost or 0), 6),
            "by_model": [
                {
                    "model": r.model or "unknown",
                    "calls": int(r.calls),
                    "tokens_in": int(r.tokens_in or 0),
                    "tokens_out": int(r.tokens_out or 0),
                    "cost_usd": round(float(r.cost_usd or 0), 6),
                }
                for r in model_rows
            ],
            "by_purpose": [
                {
                    "purpose": r.purpose or "unknown",
                    "calls": int(r.calls),
                    "cost_usd": round(float(r.cost_usd or 0), 6),
                    "tokens_in": int(r.tokens_in or 0),
                    "tokens_out": int(r.tokens_out or 0),
                }
                for r in purpose_rows
            ],
            "recent": [
                {
                    "model": r.model or "unknown",
                    "purpose": r.purpose or "unknown",
                    "tokens_in": int(r.tokens_in or 0),
                    "tokens_out": int(r.tokens_out or 0),
                    "cost_usd": round(float(r.cost_usd or 0), 6),
                    "ts": int((r.timestamp.replace(tzinfo=timezone.utc) if r.timestamp and r.timestamp.tzinfo is None else r.timestamp).timestamp() * 1000) if r.timestamp else 0,
                }
                for r in recent_rows
            ],
        }
    except Exception as e:
        logger.error("[ANALYTICS] llm-breakdown failed: %s", e)
        return {
            "has_data": False,
            "total_calls": 0, "total_tokens_in": 0, "total_tokens_out": 0, "total_cost_usd": 0,
            "by_model": [], "by_purpose": [], "recent": [],
        }


@router.get("/analytics/realized-pnl")
async def get_realized_pnl():
    """Directly fetches ClosedTrade records and open positions."""
    try:
        from db.database import _get_session_factory
        from db.models import ClosedTrade
        from sqlalchemy import select

        async with _get_session_factory()() as session:
            stmt = select(ClosedTrade).order_by(ClosedTrade.exit_time)
            rows = (await session.execute(stmt)).scalars().all()

        trades = []
        for row in rows:
            trades.append({
                "strategy": row.bot_id,
                "symbol": row.symbol,
                "direction": "LONG",
                "entry_price": round(float(row.avg_entry_price or 0), 4),
                "exit_price": round(float(row.avg_exit_price or 0), 4),
                "qty": round(float(row.qty or 0), 6),
                "pnl": round(float(row.realized_pnl or 0), 4),
                "entry_time": row.entry_time.isoformat() if row.entry_time else None,
                "exit_time": row.exit_time.isoformat() if row.exit_time else None,
                "confidence": round(float(row.confidence), 4) if row.confidence is not None else None,
                "asset_class": _infer_asset_class(row.symbol, row.asset_class),
                "win": bool(row.win),
            })

        live_positions: dict[str, float] = {}
        if trading_client and _entry_prices:
            try:
                for p in trading_client.get_all_positions():
                    live_positions[str(p.symbol)] = round(float(p.qty or 0), 6)
            except Exception:
                pass

        alpaca_ok = bool(live_positions)  # True when get_all_positions() succeeded

        open_positions = []
        for (bot, sym), price in _entry_prices.items():
            entry_time = _entry_times.get((bot, sym))
            qty = live_positions.get(sym)

            if alpaca_ok and qty is None:
                logger.info("[OPEN_POSITIONS] Skipping stale entry (%s, %s) — not in Alpaca live positions", bot, sym)
                continue

            open_positions.append({
                "strategy": bot,
                "symbol": sym,
                "direction": "LONG",
                "entry_price": round(float(price or 0), 4),
                "exit_price": None,
                "qty": qty,
                "pnl": None,
                "entry_time": entry_time,
                "exit_time": None,
                "confidence": None,
                "asset_class": _infer_asset_class(sym),
                "open": True,
            })

        if not trades and trading_client:
            try:
                from alpaca.trading.requests import GetOrdersRequest
                from alpaca.trading.enums import QueryOrderStatus
                closed_orders = trading_client.get_orders(
                    filter=GetOrdersRequest(status=QueryOrderStatus.CLOSED, limit=100)
                )
                order_map = {}
                for o in closed_orders:
                    if o.filled_avg_price is None:
                        continue
                    sym = str(o.symbol)
                    order_map.setdefault(sym, []).append({
                        "side": str(o.side).split(".")[-1].upper(),
                        "fill_price": float(o.filled_avg_price),
                        "qty": float(o.filled_qty or 0),
                        "filled_at": o.filled_at.isoformat() if o.filled_at else None,
                    })
                for sym, orders in order_map.items():
                    buys = [o for o in orders if o["side"] == "BUY"]
                    sells = [o for o in orders if o["side"] == "SELL"]
                    for sell in sells:
                        buy = buys.pop(0) if buys else None
                        pnl = (sell["fill_price"] - (buy["fill_price"] if buy else sell["fill_price"])) * sell["qty"]
                        trades.append({
                            "strategy": "alpaca-history",
                            "symbol": sym,
                            "direction": "LONG",
                            "entry_price": round(buy["fill_price"] if buy else sell["fill_price"], 4),
                            "exit_price": round(sell["fill_price"], 4),
                            "qty": round(sell["qty"], 6),
                            "pnl": round(pnl, 4),
                            "entry_time": buy["filled_at"] if buy else None,
                            "exit_time": sell["filled_at"],
                            "confidence": 0.0,
                        })
            except Exception as _fb_err:
                logger.debug("[REALIZED PNL] Alpaca fallback failed: %s", _fb_err)

        return {"trades": trades, "open_positions": open_positions, "total_closed": len(trades)}

    except Exception as e:
        logger.error("[REALIZED PNL] %s", e)
        return {"trades": [], "open_positions": [], "total_closed": 0, "error": str(e)}


@router.get("/analytics/watchlist-ta")
async def get_watchlist_ta():
    """Returns all WatchlistItem rows with TA metrics for analytics display."""
    try:
        from db.database import _get_session_factory
        from db.models import WatchlistItem
        from sqlalchemy import select

        async with _get_session_factory()() as session:
            rows = (await session.execute(
                select(WatchlistItem).where(WatchlistItem.active == True).order_by(WatchlistItem.score.desc())
            )).scalars().all()

        return [
            {
                "symbol": r.symbol,
                "score": float(r.score) if r.score is not None else 0.0,
                "signal": r.signal,
                "verdict": r.verdict,
                "asset_class": _infer_asset_class(r.symbol, r.asset_class),
                "rsi": float(r.rsi) if r.rsi is not None else None,
                "ema_spread": float(r.ema_spread) if r.ema_spread is not None else None,
                "vol_surge": float(r.volume_ratio) if r.volume_ratio is not None else None,
                "band_pct": float(r.bb_position) if r.bb_position is not None else None,
                "last_scanned": r.last_scanned.isoformat() if r.last_scanned else None,
            }
            for r in rows
        ]
    except Exception as e:
        logger.error("[WATCHLIST-TA] %s", e)
        return []


@router.get("/analytics/signals-by-asset-class")
async def get_signals_by_asset_class(period: str = "1D"):
    """Returns signal and trade stats broken down by CRYPTO vs EQUITY."""
    from datetime import datetime as _dt, timezone as _tz, timedelta
    from db.database import _get_session_factory
    from db.models import SignalRecord, ClosedTrade
    from sqlalchemy import select as _sel, func as _func

    days = _PERIOD_DAYS.get(period.upper(), 1)
    cutoff = _dt.now(_tz.utc) - timedelta(days=days)

    try:
        async with _get_session_factory()() as session:
            sig_rows = (await session.execute(
                _sel(
                    SignalRecord.asset_class,
                    _func.count(SignalRecord.id).label("signal_count"),
                    _func.avg(SignalRecord.confidence).label("avg_confidence"),
                    _func.avg(SignalRecord.market_edge).label("avg_edge"),
                    _func.avg(SignalRecord.xgboost_prob).label("avg_xgboost"),
                )
                .where(SignalRecord.timestamp >= cutoff)
                .group_by(SignalRecord.asset_class)
            )).all()

            trade_rows = (await session.execute(
                _sel(
                    ClosedTrade.asset_class,
                    _func.count(ClosedTrade.id).label("trade_count"),
                    _func.sum(ClosedTrade.net_pnl).label("total_pnl"),
                    _func.avg(ClosedTrade.net_pnl).label("avg_pnl"),
                )
                .where(ClosedTrade.exit_time >= cutoff)
                .group_by(ClosedTrade.asset_class)
            )).all()

        trade_map = {(r.asset_class or "UNKNOWN"): r for r in trade_rows}

        result = []
        for r in sig_rows:
            ac = r.asset_class or "UNKNOWN"
            tr = trade_map.get(ac)
            result.append({
                "asset_class": ac,
                "signal_count": int(r.signal_count or 0),
                "avg_confidence": round(float(r.avg_confidence or 0), 4),
                "avg_edge": round(float(r.avg_edge or 0), 4) if r.avg_edge is not None else None,
                "avg_xgboost_prob": round(float(r.avg_xgboost or 0), 4) if r.avg_xgboost is not None else None,
                "trade_count": int(tr.trade_count) if tr else 0,
                "total_pnl": round(float(tr.total_pnl or 0), 2) if tr else 0.0,
                "avg_pnl": round(float(tr.avg_pnl or 0), 2) if tr else 0.0,
            })

        return {"has_data": bool(result), "by_asset_class": result}
    except Exception as e:
        logger.error("[SIGNALS-BY-ASSET-CLASS] %s", e)
        return {"has_data": False, "by_asset_class": []}
