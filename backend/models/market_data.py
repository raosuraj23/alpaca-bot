"""
Market Data & Execution ORM Models
====================================
SQLAlchemy models for the quantitative data layer.

Tables defined here:
  MarketCandle   — aggregated OHLCV bars from the Alpaca WebSocket feed
  QuantSignal    — deterministic TA signals (EMA cross, RSI gate, volume surge)
  OrderRecord    — full Alpaca order lifecycle (submitted → filled / rejected)
  SlippageRecord — per-fill slippage analysis linked to OrderRecord

All timestamps are timezone-aware UTC.
Composite indexes on (symbol, timestamp) support fast time-series queries
for the frontend Analysis tab and the backtesting engine.

Note: This module imports Base from db.database so all models are registered
in the same metadata pool and created by init_db() at startup.
"""

from __future__ import annotations

from datetime import datetime, timezone

from sqlalchemy import (
    Column, Integer, String, Float, DateTime, Index,
    ForeignKey, BigInteger,
)

from db.database import Base


def _utcnow() -> datetime:
    """Timezone-aware UTC timestamp factory (replaces deprecated datetime.utcnow)."""
    return datetime.now(timezone.utc)


# ---------------------------------------------------------------------------
# MarketCandle — aggregated OHLCV bars
# ---------------------------------------------------------------------------

class MarketCandle(Base):
    """
    Stores finalized OHLCV candles assembled from the Alpaca CryptoDataStream.
    The stream ingestion layer aggregates raw ticks into 1-Min and 5-Min bars
    before writing here — keeping row counts low and queries fast.

    Query pattern: WHERE symbol = ? AND timeframe = ? AND timestamp > ?
    Served by: idx_candle_symbol_tf_ts composite index.
    """
    __tablename__ = "market_candles"

    id         = Column(Integer, primary_key=True, index=True)
    symbol     = Column(String(20), nullable=False)   # e.g. 'BTC/USD'
    timeframe  = Column(String(5),  nullable=False)   # e.g. '1Min', '5Min'

    open_price  = Column(Float, nullable=False)
    high_price  = Column(Float, nullable=False)
    low_price   = Column(Float, nullable=False)
    close_price = Column(Float, nullable=False)
    volume      = Column(Float, nullable=False)

    # Bar open time — timezone-aware UTC
    timestamp = Column(
        DateTime(timezone=True),
        default=_utcnow,
        nullable=False,
    )

    __table_args__ = (
        # Composite index for charting queries: symbol + timeframe + time range
        Index("idx_candle_symbol_tf_ts", "symbol", "timeframe", "timestamp"),
    )

    def __repr__(self) -> str:
        return (
            f"<MarketCandle {self.symbol} {self.timeframe} "
            f"O={self.open_price} H={self.high_price} "
            f"L={self.low_price} C={self.close_price} V={self.volume} "
            f"@ {self.timestamp}>"
        )


# ---------------------------------------------------------------------------
# QuantSignal — deterministic TA signal log
# ---------------------------------------------------------------------------

class QuantSignal(Base):
    """
    Every time the TA engine evaluates a Golden Cross, RSI threshold breach,
    or volume surge, one row is written here regardless of whether the LLM
    Supervisor approves the trade. This separates deterministic logic from
    LLM reasoning and allows independent audit of the signal generator.

    Fields:
      signal_type      — raw BUY / SELL / HOLD from the TA engine
      llm_approved     — PENDING → APPROVED / REJECTED after LLM review
      ema_50_value     — EMA-50 at signal time
      ema_200_value    — EMA-200 at signal time (Golden / Death Cross reference)
      rsi_14_value     — RSI-14 at signal time
      volume_surge_ratio — current_volume / rolling_20bar_mean
    """
    __tablename__ = "quant_signals"

    id          = Column(Integer, primary_key=True, index=True)
    symbol      = Column(String(20), nullable=False)
    signal_type = Column(String(10), nullable=False)   # 'BUY' | 'SELL' | 'HOLD'

    # Indicator snapshots that triggered the signal
    ema_50_value        = Column(Float, nullable=True)
    ema_200_value       = Column(Float, nullable=True)
    rsi_14_value        = Column(Float, nullable=True)
    volume_surge_ratio  = Column(Float, nullable=True)  # e.g. 1.5 = 50% above mean

    # LLM Supervisor review outcome
    llm_approved = Column(String(10), default="PENDING", nullable=False)
    # PENDING | APPROVED | REJECTED

    timestamp = Column(
        DateTime(timezone=True),
        default=_utcnow,
        nullable=False,
    )

    __table_args__ = (
        Index("idx_signal_symbol_ts", "symbol", "timestamp"),
    )

    def __repr__(self) -> str:
        return (
            f"<QuantSignal {self.signal_type} {self.symbol} "
            f"EMA50={self.ema_50_value} EMA200={self.ema_200_value} "
            f"RSI={self.rsi_14_value} VSR={self.volume_surge_ratio} "
            f"llm={self.llm_approved} @ {self.timestamp}>"
        )


# ---------------------------------------------------------------------------
# OrderRecord — full Alpaca order lifecycle
# ---------------------------------------------------------------------------

class OrderRecord(Base):
    """
    Tracks every order from the moment it is submitted to Alpaca through
    fill / cancellation / rejection. One row per order_id.

    Linked to QuantSignal via quant_signal_id (nullable — manual orders
    placed via TradePanel or OrchestratorChat have no QuantSignal parent).

    Fields:
      source    — 'strategy' | 'tradepanel' | 'orchestrator'
      bot_id    — strategy name that generated the signal (e.g. 'momentum-alpha')
      status    — mirrors Alpaca order status lifecycle
      latency_ms — elapsed ms between submitted_at and filled_at
    """
    __tablename__ = "order_records"

    id              = Column(Integer, primary_key=True, index=True)
    alpaca_order_id = Column(String(50), unique=True, nullable=False, index=True)
    symbol          = Column(String(20), nullable=False)
    side            = Column(String(10), nullable=False)   # 'BUY' | 'SELL'
    order_type      = Column(String(10), nullable=False, default="MARKET")
    time_in_force   = Column(String(10), nullable=False, default="GTC")

    # Quantities
    requested_qty   = Column(Float, nullable=False)
    filled_qty      = Column(Float, nullable=True)

    # Prices
    requested_price = Column(Float, nullable=True)   # None for market orders
    fill_price      = Column(Float, nullable=True)   # avg fill price

    # Lifecycle
    status          = Column(String(20), nullable=False, default="SUBMITTED")
    # SUBMITTED | PARTIALLY_FILLED | FILLED | CANCELLED | REJECTED | EXPIRED

    # Timing
    submitted_at    = Column(DateTime(timezone=True), default=_utcnow, nullable=False)
    filled_at       = Column(DateTime(timezone=True), nullable=True)
    latency_ms      = Column(BigInteger, nullable=True)  # fill_at - submitted_at in ms

    # Provenance
    source          = Column(String(20), nullable=False, default="strategy")
    bot_id          = Column(String(50), nullable=True)
    quant_signal_id = Column(Integer, ForeignKey("quant_signals.id"), nullable=True)

    __table_args__ = (
        Index("idx_order_symbol_ts", "symbol", "submitted_at"),
        Index("idx_order_bot_ts",    "bot_id",  "submitted_at"),
    )

    def __repr__(self) -> str:
        return (
            f"<OrderRecord {self.side} {self.symbol} "
            f"qty={self.requested_qty} fill={self.fill_price} "
            f"status={self.status} src={self.source}>"
        )


# ---------------------------------------------------------------------------
# SlippageRecord — per-fill slippage analysis
# ---------------------------------------------------------------------------

class SlippageRecord(Base):
    """
    One row per filled order. Captures the delta between the price at which
    the strategy signal fired and the actual Alpaca fill price.

    slippage_abs   = abs(fill_price - signal_price)
    slippage_pct   = slippage_abs / signal_price * 100

    Used by:
      - ExecutionAgent to persist fill quality
      - PerformanceMetrics tab to show avg slippage per strategy
      - Backtesting engine to apply realistic execution costs
    """
    __tablename__ = "slippage_records"

    id              = Column(Integer, primary_key=True, index=True)
    order_id        = Column(
        Integer,
        ForeignKey("order_records.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )

    symbol          = Column(String(20), nullable=False)
    signal_price    = Column(Float, nullable=False)   # price at signal emission
    fill_price      = Column(Float, nullable=False)   # actual Alpaca fill price
    slippage_abs    = Column(Float, nullable=False)   # absolute dollar slippage
    slippage_pct    = Column(Float, nullable=False)   # percentage slippage
    latency_ms      = Column(BigInteger, nullable=True)  # signal → fill round-trip ms
    bot_id          = Column(String(50), nullable=True)

    timestamp = Column(
        DateTime(timezone=True),
        default=_utcnow,
        nullable=False,
    )

    __table_args__ = (
        Index("idx_slip_symbol_ts", "symbol",  "timestamp"),
        Index("idx_slip_bot_ts",    "bot_id",  "timestamp"),
    )

    def __repr__(self) -> str:
        return (
            f"<SlippageRecord {self.symbol} "
            f"signal={self.signal_price} fill={self.fill_price} "
            f"slip={self.slippage_abs:.4f} ({self.slippage_pct:.3f}%) "
            f"lat={self.latency_ms}ms>"
        )
