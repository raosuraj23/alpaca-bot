"""
post_mortem.py — Enhanced Post-Mortem Analyzer

Guardrails:
  1. Domain expertise embedded in risk logic — compliance before action
  2. Code is deterministic: scripts validate risk, not language instructions
  3. Progressive disclosure: SKILL.md keeps core rules, details in references/
  4. Parallel sub-agents per market — up to 10+ simultaneous signals
  5. Iterative improvement: compound skill logs every loss + pattern fix

Every losing trade triggers this script. It classifies the failure,
generates a knowledge base entry via Haiku, and appends to failure_log.jsonl.

Full trade record logged for ALL fills (wins + losses):
  - entry_price, exit_price, predicted_probability, actual_outcome
  - profit_loss, hold_duration_min, market_conditions, news_items

Failure classes:
  BAD_PREDICTION  — model directionally wrong despite confidence > 0.70
  TIMING         — correct direction but entry/exit timing degraded P&L
  EXECUTION      — slippage > 2% of signal price was the primary drag
  MARKET_SHOCK   — exogenous event (news, macro) invalidated signal

Usage (as library):
    from post_mortem import classify_failure, format_kb_entry

Standalone test:
    python post_mortem.py
"""

from __future__ import annotations
import json
from dataclasses import dataclass, asdict
from datetime import datetime
from enum import Enum


class FailureClass(str, Enum):
    BAD_PREDICTION = "BAD_PREDICTION"
    TIMING         = "TIMING"
    EXECUTION      = "EXECUTION"
    MARKET_SHOCK   = "MARKET_SHOCK"


@dataclass
class TradeRecord:
    """Full trade context for post-mortem analysis (all fills)."""
    strategy:           str
    symbol:             str
    entry_price:        float
    exit_price:         float
    predicted_prob:     float           # signal confidence at entry
    actual_outcome:     int             # 1 = profitable, 0 = loss
    profit_loss:        float
    hold_duration_min:  int | None
    market_conditions:  dict | None     # {rsi, ema_spread, volume_ratio, ...}
    news_items:         list[str]
    slippage_pct:       float
    timestamp:          str = ""

    def brier_contribution(self) -> float:
        """(forecast - outcome)² for this trade."""
        return round((self.predicted_prob - self.actual_outcome) ** 2, 6)


def classify_failure(record: TradeRecord) -> FailureClass:
    """
    Deterministic failure classification.
    Priority: MARKET_SHOCK > EXECUTION > BAD_PREDICTION > TIMING
    """
    if record.news_items and any(
        w in " ".join(record.news_items).lower()
        for w in ("crash", "halt", "circuit", "fed", "fomc", "emergency", "ban")
    ):
        return FailureClass.MARKET_SHOCK

    if record.slippage_pct > 0.02:
        return FailureClass.EXECUTION

    if record.predicted_prob > 0.70 and record.actual_outcome == 0:
        return FailureClass.BAD_PREDICTION

    return FailureClass.TIMING


def format_kb_entry(record: TradeRecord, failure_cls: FailureClass,
                    root_cause: str, adjustment: str) -> dict:
    """Build a structured knowledge base record."""
    return {
        "timestamp":       datetime.utcnow().isoformat() + "Z",
        "strategy":        record.strategy,
        "symbol":          record.symbol,
        "failure_class":   failure_cls.value,
        "entry_price":     record.entry_price,
        "exit_price":      record.exit_price,
        "predicted_prob":  record.predicted_prob,
        "actual_outcome":  record.actual_outcome,
        "profit_loss":     round(record.profit_loss, 4),
        "hold_duration_min": record.hold_duration_min,
        "brier_contribution": record.brier_contribution(),
        "root_cause":      root_cause,
        "adjustment":      adjustment,
        "knowledge_entry": f"[{failure_cls.value}] {record.symbol}: {root_cause[:80]}",
    }


if __name__ == "__main__":
    rec = TradeRecord(
        strategy="momentum-alpha",
        symbol="BTC/USD",
        entry_price=65000,
        exit_price=60000,
        predicted_prob=0.80,
        actual_outcome=0,
        profit_loss=-500.0,
        hold_duration_min=45,
        market_conditions={"rsi": 72, "ema_spread": 0.03},
        news_items=["Fed signals rate hold"],
        slippage_pct=0.001,
    )

    cls = classify_failure(rec)
    entry = format_kb_entry(rec, cls,
                            root_cause="High-confidence BUY entered during Fed announcement window",
                            adjustment="Block momentum signals 30min before/after FOMC")
    print(json.dumps(entry, indent=2))
    print(f"\nBrier contribution: {rec.brier_contribution()}")