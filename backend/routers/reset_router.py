"""
POST /api/reset — Cancel all orders, close all positions, truncate all DB tables.
"""

import os
import logging
import sqlite3
from fastapi import APIRouter, HTTPException

from deps import trading_client
from config import settings

log = logging.getLogger(__name__)

router = APIRouter(tags=["reset"])

TABLES = [
    "signals",
    "executions",
    "closed_trades",
    "portfolio_snapshots",
    "market_condition_snapshots",
    "bot_states",
    "bot_parameter_control",
    "llm_usage",
    "bot_amends",
    "reflection_logs",
    "calibration_records",
    "watchlist_items",
    "symbol_strategy_assignments",
]


@router.post("/api/reset")
async def full_reset():
    if trading_client is None:
        raise HTTPException(status_code=503, detail="Alpaca API keys not configured.")

    steps: list[str] = []
    errors: list[str] = []

    # Step 1: Cancel all open orders
    try:
        trading_client.cancel_orders()
        steps.append("cancel_orders: ok")
        log.info("[RESET] All orders cancelled")
    except Exception as exc:
        msg = f"cancel_orders: {exc}"
        steps.append(msg)
        log.warning("[RESET] %s", msg)

    # Step 2: Close all open positions
    try:
        trading_client.close_all_positions(cancel_orders=True)
        steps.append("close_all_positions: ok")
        log.info("[RESET] All positions closed")
    except Exception as exc:
        msg = f"close_all_positions: {exc}"
        steps.append(msg)
        log.warning("[RESET] %s", msg)

    # Step 3: Truncate all DB tables
    raw_url = settings.database_url
    db_path = (
        raw_url
        .replace("sqlite+aiosqlite:///", "")
        .replace("sqlite:///", "")
    )
    if not os.path.isabs(db_path):
        db_path = os.path.join(os.path.dirname(__file__), "..", db_path)

    if not os.path.exists(db_path):
        steps.append("db_wipe: skipped (file not found)")
    else:
        try:
            conn = sqlite3.connect(db_path)
            cur = conn.cursor()
            cur.execute("PRAGMA foreign_keys = OFF")
            wiped: list[str] = []
            for table in TABLES:
                try:
                    cur.execute(f"DELETE FROM {table}")
                    wiped.append(table)
                except sqlite3.OperationalError as exc:
                    errors.append(f"{table}: {exc}")
            cur.execute("PRAGMA foreign_keys = ON")
            conn.commit()
            conn.close()
            steps.append(f"db_wipe: cleared {len(wiped)}/{len(TABLES)} tables")
            log.info("[RESET] DB wiped — tables: %s", wiped)
        except Exception as exc:
            errors.append(f"db_wipe: {exc}")
            log.error("[RESET] DB wipe failed: %s", exc)

    return {"ok": len(errors) == 0, "steps": steps, "errors": errors}
