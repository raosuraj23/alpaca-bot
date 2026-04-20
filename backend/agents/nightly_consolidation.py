"""
Nightly Consolidation Agent
============================
Runs at 23:55 UTC each day. Aggregates the day's trading performance
into a single metrics snapshot and appends it to:
  backend/knowledge/metrics_log.jsonl

Metrics computed:
  - win_rate        wins / total_trades (target ≥ 60%)
  - sharpe          annualised Sharpe from PortfolioSnapshot equity curve
  - max_drawdown_pct  peak-to-trough % across today's equity history
  - profit_factor   gross_profit / gross_loss (target ≥ 1.5)
  - brier_score     mean (forecast - outcome)² across today's trades
  - total_trades    count of closed trades today
  - total_pnl       sum of realized PnL today

Guardrails:
  1. Domain expertise embedded in risk logic — compliance before action
  2. Code is deterministic: scripts validate risk, not language instructions
  3. Progressive disclosure: SKILL.md keeps core rules, details in references/
  4. Parallel sub-agents per market — up to 10+ simultaneous signals
  5. Iterative improvement: compound skill logs every loss + pattern fix
"""

import asyncio
import json
import logging
import math
import pathlib
from datetime import datetime, timezone, timedelta
from typing import Callable, Optional

logger = logging.getLogger(__name__)

_KB_PATH = pathlib.Path(__file__).resolve().parent.parent / "knowledge" / "metrics_log.jsonl"


class NightlyConsolidation:
    def __init__(self, push_fn: Optional[Callable[[dict], None]] = None):
        self._push = push_fn
        self._running = False

    async def run(self):
        """Background loop: sleeps until 23:55 UTC, then runs a daily snapshot."""
        self._running = True
        logger.info("[CONSOLIDATION] Nightly consolidation agent started")
        while self._running:
            now_utc = datetime.now(timezone.utc)
            target = now_utc.replace(hour=23, minute=55, second=0, microsecond=0)
            if now_utc >= target:
                target += timedelta(days=1)
            sleep_secs = (target - now_utc).total_seconds()
            logger.info("[CONSOLIDATION] Next snapshot in %.0f minutes", sleep_secs / 60)
            await asyncio.sleep(sleep_secs)
            if self._running:
                await self.run_daily_snapshot()

    async def run_daily_snapshot(self):
        """Aggregate today's metrics and write to metrics_log.jsonl."""
        today_utc = datetime.now(timezone.utc).date()
        day_start = datetime(today_utc.year, today_utc.month, today_utc.day, tzinfo=timezone.utc)
        day_end   = day_start + timedelta(days=1)

        try:
            from db.database import _get_session_factory
            from db.models import ClosedTrade, CalibrationRecord, PortfolioSnapshot
            from sqlalchemy import select, and_, func

            async with _get_session_factory()() as session:
                # --- ClosedTrade: win_rate, profit_factor, total_trades, total_pnl ---
                trade_rows = (await session.execute(
                    select(ClosedTrade).where(and_(
                        ClosedTrade.exit_time >= day_start,
                        ClosedTrade.exit_time <  day_end,
                    ))
                )).scalars().all()

                total_trades = len(trade_rows)
                wins   = sum(1 for t in trade_rows if t.win)
                losses = total_trades - wins
                win_rate = wins / total_trades if total_trades > 0 else 0.0

                gross_profit = sum(float(t.net_pnl or 0) for t in trade_rows if (t.net_pnl or 0) > 0)
                gross_loss   = sum(abs(float(t.net_pnl or 0)) for t in trade_rows if (t.net_pnl or 0) < 0)
                profit_factor = (gross_profit / gross_loss) if gross_loss > 0 else (float("inf") if gross_profit > 0 else 0.0)
                total_pnl = gross_profit - gross_loss

                # --- CalibrationRecord: Brier score for today ---
                cal_rows = (await session.execute(
                    select(CalibrationRecord).where(and_(
                        CalibrationRecord.timestamp >= day_start,
                        CalibrationRecord.timestamp <  day_end,
                    ))
                )).scalars().all()

                brier_score = None
                if cal_rows:
                    brier_score = round(
                        sum(float(r.brier_contribution or 0) for r in cal_rows) / len(cal_rows), 4
                    )

                # --- PortfolioSnapshot: Sharpe + max drawdown ---
                snap_rows = (await session.execute(
                    select(PortfolioSnapshot).where(and_(
                        PortfolioSnapshot.timestamp >= day_start,
                        PortfolioSnapshot.timestamp <  day_end,
                    )).order_by(PortfolioSnapshot.timestamp)
                )).scalars().all()

                sharpe = 0.0
                max_dd = 0.0
                if len(snap_rows) >= 2:
                    equities = [float(s.total_equity or 0) for s in snap_rows if s.total_equity]
                    if len(equities) >= 2:
                        rets = [
                            (equities[i] - equities[i - 1]) / equities[i - 1]
                            for i in range(1, len(equities))
                            if equities[i - 1] != 0
                        ]
                        if rets:
                            mean_r = sum(rets) / len(rets)
                            variance = sum((r - mean_r) ** 2 for r in rets) / max(len(rets) - 1, 1)
                            std_r = math.sqrt(variance)
                            if std_r > 0:
                                sharpe = round((mean_r / std_r) * math.sqrt(252), 3)

                        peak = equities[0]
                        for eq in equities:
                            if eq > peak:
                                peak = eq
                            if peak > 0:
                                dd = (peak - eq) / peak * 100
                                max_dd = max(max_dd, dd)

        except Exception as exc:
            logger.error("[CONSOLIDATION] DB query failed: %s", exc)
            return

        snapshot = {
            "date":              str(today_utc),
            "win_rate":          round(win_rate, 4),
            "sharpe":            sharpe,
            "max_drawdown_pct":  round(max_dd, 4),
            "profit_factor":     round(min(profit_factor, 999.0), 4),
            "brier_score":       brier_score,
            "total_trades":      total_trades,
            "total_pnl":         round(total_pnl, 4),
            "wins":              wins,
            "losses":            losses,
        }

        self._write_snapshot(snapshot)
        self._push_sse(snapshot)

        logger.info(
            "[CONSOLIDATION] Daily snapshot — date=%s trades=%d win_rate=%.1f%% "
            "sharpe=%.2f profit_factor=%.2f brier=%s",
            today_utc, total_trades, win_rate * 100, sharpe,
            snapshot["profit_factor"], brier_score,
        )

        # --- XGBoost nightly retraining ---
        try:
            from predict.xgboost_classifier import xgb_classifier
            loop = asyncio.get_event_loop()
            trained = await loop.run_in_executor(None, xgb_classifier.train)
            if trained:
                logger.info("[CONSOLIDATION] XGBoost model retrained on updated trade history")
        except Exception as exc:
            logger.warning("[CONSOLIDATION] XGBoost retraining skipped: %s", exc)

    def _write_snapshot(self, snapshot: dict):
        try:
            _KB_PATH.parent.mkdir(parents=True, exist_ok=True)
            with open(_KB_PATH, "a", encoding="utf-8") as f:
                f.write(json.dumps(snapshot) + "\n")
        except Exception as exc:
            logger.warning("[CONSOLIDATION] Failed to write metrics_log.jsonl: %s", exc)

    def _push_sse(self, snapshot: dict):
        if not self._push:
            return
        try:
            self._push({
                "type":    "consolidation",
                "text":    (
                    f"Daily recap {snapshot['date']}: "
                    f"{snapshot['total_trades']} trades, "
                    f"win rate {snapshot['win_rate']*100:.1f}%, "
                    f"PnL ${snapshot['total_pnl']:+.2f}, "
                    f"Sharpe {snapshot['sharpe']:.2f}, "
                    f"Profit Factor {snapshot['profit_factor']:.2f}"
                ),
                "snapshot": snapshot,
                "timestamp": datetime.utcnow().isoformat(),
            })
        except Exception as exc:
            logger.debug("[CONSOLIDATION] SSE push failed: %s", exc)

    def stop(self):
        self._running = False
