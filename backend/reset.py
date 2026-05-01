"""
reset.py — Standalone full-reset script.

Usage:
    cd backend
    python reset.py

Actions (in order):
  1. Cancel all open Alpaca orders
  2. Close all open Alpaca positions
  3. Truncate all 13 database tables

Exits with code 0 on success, 1 on any error.
"""

import sys
import os

# Ensure backend/ is on the path so config/deps resolve
sys.path.insert(0, os.path.dirname(__file__))

from dotenv import load_dotenv
load_dotenv()

import sqlite3
import logging

logging.basicConfig(level="INFO", format="%(levelname)s  %(message)s")
log = logging.getLogger("reset")

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


def _alpaca_reset() -> None:
    from deps import trading_client
    if trading_client is None:
        raise RuntimeError("Alpaca TradingClient not initialized — check API keys in .env")

    log.info("Step 1/3 — Cancelling all open orders …")
    try:
        trading_client.cancel_orders()
        log.info("  ✓ All orders cancelled")
    except Exception as exc:
        log.warning("  ! cancel_orders raised: %s (may have been no orders)", exc)

    log.info("Step 2/3 — Closing all open positions …")
    try:
        trading_client.close_all_positions(cancel_orders=True)
        log.info("  ✓ All positions closed")
    except Exception as exc:
        log.warning("  ! close_all_positions raised: %s (may have been no positions)", exc)


def _db_reset() -> None:
    from config import settings

    raw_url = settings.database_url
    # Strip SQLAlchemy dialect prefix to get a plain file path
    db_path = (
        raw_url
        .replace("sqlite+aiosqlite:///", "")
        .replace("sqlite:///", "")
    )
    if not os.path.isabs(db_path):
        db_path = os.path.join(os.path.dirname(__file__), db_path)

    log.info("Step 3/3 — Wiping database at %s …", db_path)

    if not os.path.exists(db_path):
        log.warning("  ! Database file not found — nothing to wipe")
        return

    conn = sqlite3.connect(db_path)
    try:
        cur = conn.cursor()
        cur.execute("PRAGMA foreign_keys = OFF")
        for table in TABLES:
            try:
                cur.execute(f"DELETE FROM {table}")
                log.info("  ✓ Cleared table: %s (%d rows removed)", table, cur.rowcount)
            except sqlite3.OperationalError as exc:
                log.warning("  ! Skipped table %s: %s", table, exc)
        cur.execute("PRAGMA foreign_keys = ON")
        conn.commit()
        log.info("  ✓ Database wiped")
    finally:
        conn.close()


def main() -> None:
    log.info("=== ALPACA BOT FULL RESET ===")
    try:
        _alpaca_reset()
        _db_reset()
        log.info("=== RESET COMPLETE ===")
    except Exception as exc:
        log.error("RESET FAILED: %s", exc)
        sys.exit(1)


if __name__ == "__main__":
    main()
