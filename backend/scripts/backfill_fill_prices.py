"""
Backfill fill_price = 0.0 records in ExecutionRecord by querying Alpaca for
the actual filled_avg_price using the stored alpaca_order_id.

Also recalculates avg_exit_price / realized_pnl / net_pnl / win on any
ClosedTrade row linked via exit_execution_id.

Run from the backend/ directory:
    python scripts/backfill_fill_prices.py [--dry-run]
"""

import asyncio
import logging
import sys
from decimal import Decimal

logging.basicConfig(level=logging.INFO, format="%(levelname)s  %(message)s")
log = logging.getLogger("backfill")

DRY_RUN = "--dry-run" in sys.argv


async def main() -> None:
    import os, pathlib

    # Ensure backend/ is on sys.path regardless of CWD
    sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent))

    from config import settings
    from alpaca.trading.client import TradingClient

    trading_client = TradingClient(
        api_key=settings.alpaca_api_key_id,
        secret_key=settings.alpaca_api_secret_key,
        paper=settings.paper_trading,
    )

    from db.database import _get_session_factory, init_db
    from db.models import ExecutionRecord, ClosedTrade
    from sqlalchemy import select

    await init_db()
    factory = _get_session_factory()

    async with factory() as session:
        # Fetch all FILLED executions with fill_price = 0 that have an order ID
        stmt = select(ExecutionRecord).where(
            ExecutionRecord.fill_price == Decimal("0"),
            ExecutionRecord.alpaca_order_id.isnot(None),
            ExecutionRecord.status == "FILLED",
        )
        records = (await session.execute(stmt)).scalars().all()

    if not records:
        log.info("No zero-fill FILLED records found — nothing to backfill.")
        return

    log.info("Found %d record(s) with fill_price = 0.0", len(records))
    if DRY_RUN:
        log.info("DRY-RUN mode — no writes will be made.")

    updated = 0
    skipped = 0

    for rec in records:
        order_id = rec.alpaca_order_id
        try:
            order = trading_client.get_order_by_id(order_id)
        except Exception as e:
            log.warning("  [%s] Alpaca fetch failed: %s — skipping", order_id[:8], e)
            skipped += 1
            continue

        raw = order.filled_avg_price
        if not raw:
            log.warning("  [%s] filled_avg_price still None on Alpaca — skipping", order_id[:8])
            skipped += 1
            continue

        actual_price = Decimal(str(raw))
        log.info(
            "  [%s] id=%d symbol=%s  0.0 → %s",
            order_id[:8], rec.id, getattr(rec, "symbol", "?"), actual_price,
        )

        if DRY_RUN:
            continue

        async with factory() as session:
            row = await session.get(ExecutionRecord, rec.id)
            if row is None:
                skipped += 1
                continue

            row.fill_price = actual_price
            row.slippage   = Decimal("0")   # original signal price unavailable

            # Update linked ClosedTrade (exit leg) if it exists
            ct_stmt = select(ClosedTrade).where(ClosedTrade.exit_execution_id == rec.id)
            ct = (await session.execute(ct_stmt)).scalar_one_or_none()
            if ct is not None:
                ct.avg_exit_price = actual_price
                entry = Decimal(str(ct.avg_entry_price or 0))
                qty   = Decimal(str(ct.qty or 0))
                pnl   = (actual_price - entry) * qty
                ct.realized_pnl = pnl
                ct.net_pnl      = pnl
                ct.win          = pnl > 0
                log.info(
                    "    └─ ClosedTrade id=%d  exit_price=%s  pnl=%s  win=%s",
                    ct.id, actual_price, round(pnl, 4), pnl > 0,
                )

            await session.commit()
            updated += 1

    log.info(
        "Done. updated=%d  skipped=%d%s",
        updated, skipped, " (dry-run)" if DRY_RUN else "",
    )


if __name__ == "__main__":
    asyncio.run(main())
