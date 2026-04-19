"""
nightly_consolidation.py — EOD Performance Aggregation Script

Guardrails:
  1. Domain expertise embedded in risk logic — compliance before action
  2. Code is deterministic: scripts validate risk, not language instructions
  3. Progressive disclosure: SKILL.md keeps core rules, details in references/
  4. Parallel sub-agents per market — up to 10+ simultaneous signals
  5. Iterative improvement: compound skill logs every loss + pattern fix

Runs nightly at 23:55 UTC (via NightlyConsolidation agent).
Aggregates today's closed trades into a performance snapshot and
appends it to backend/knowledge/metrics_log.jsonl.

Metrics (all five tracked):
  Win Rate        wins / total_trades            target ≥ 60%
  Sharpe Ratio    annualised from equity curve   target ≥ 2.0
  Max Drawdown    peak-to-trough %               block if > 8%
  Profit Factor   gross_profit / gross_loss      target ≥ 1.5
  Brier Score     mean (p_i - o_i)²              target < 0.25

Backend implementation: backend/agents/nightly_consolidation.py
This script is the standalone reference / skill invocation version.

Usage:
    python nightly_consolidation.py --trades path/to/trades.jsonl
"""

from __future__ import annotations
import argparse
import json
import math
import sys
from datetime import date


def compute_metrics(trades: list[dict], cal_records: list[dict],
                    equity_series: list[float]) -> dict:
    """
    Compute all 5 performance metrics from raw trade + calibration data.

    Args:
        trades:         list of {pnl, win} dicts (ClosedTrade rows)
        cal_records:    list of {brier_contribution} dicts (CalibrationRecord rows)
        equity_series:  time-ordered list of portfolio equity values

    Returns:
        Full metrics snapshot dict.
    """
    total = len(trades)
    wins  = sum(1 for t in trades if t.get("win"))
    win_rate = wins / total if total > 0 else 0.0

    gross_p = sum(t["pnl"] for t in trades if t.get("pnl", 0) > 0)
    gross_l = sum(abs(t["pnl"]) for t in trades if t.get("pnl", 0) < 0)
    profit_factor = (gross_p / gross_l) if gross_l > 0 else (float("inf") if gross_p > 0 else 0.0)
    total_pnl = gross_p - gross_l

    brier_score = None
    if cal_records:
        brier_score = round(
            sum(r.get("brier_contribution", 0) for r in cal_records) / len(cal_records), 4
        )

    sharpe = 0.0
    max_dd = 0.0
    if len(equity_series) >= 2:
        rets = [
            (equity_series[i] - equity_series[i-1]) / equity_series[i-1]
            for i in range(1, len(equity_series))
            if equity_series[i-1] != 0
        ]
        if rets:
            mean_r = sum(rets) / len(rets)
            var    = sum((r - mean_r)**2 for r in rets) / max(len(rets) - 1, 1)
            std    = math.sqrt(var)
            if std > 0:
                sharpe = round(mean_r / std * math.sqrt(252), 3)

        peak = equity_series[0]
        for eq in equity_series:
            if eq > peak:
                peak = eq
            if peak > 0:
                dd = (peak - eq) / peak * 100
                max_dd = max(max_dd, dd)

    return {
        "date":             str(date.today()),
        "win_rate":         round(win_rate, 4),
        "sharpe":           sharpe,
        "max_drawdown_pct": round(max_dd, 4),
        "profit_factor":    round(min(profit_factor, 999.0), 4),
        "brier_score":      brier_score,
        "total_trades":     total,
        "total_pnl":        round(total_pnl, 4),
        "wins":             wins,
        "losses":           total - wins,
        # Target status
        "targets_met": {
            "win_rate":      win_rate >= 0.60,
            "sharpe":        sharpe >= 2.0,
            "max_drawdown":  max_dd < 8.0,
            "profit_factor": profit_factor >= 1.5,
            "brier_score":   brier_score is not None and brier_score < 0.25,
        },
    }


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Compute nightly performance metrics")
    parser.add_argument("--trades", help="Path to JSONL file with trade records")
    args = parser.parse_args()

    trades: list[dict] = []
    if args.trades:
        with open(args.trades) as f:
            for line in f:
                line = line.strip()
                if line:
                    trades.append(json.loads(line))

    snapshot = compute_metrics(trades=trades, cal_records=[], equity_series=[])
    print(json.dumps(snapshot, indent=2))
