from datetime import datetime, timezone
from sqlalchemy import Column, Integer, String, Numeric, DateTime, Boolean, ForeignKey, Index
from db.database import Base


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


class SignalRecord(Base):
    """Tracks generated sub-signals from the Strategy Engine."""
    __tablename__ = "signals"

    id         = Column(Integer, primary_key=True, index=True)
    strategy   = Column(String(50), index=True)
    symbol     = Column(String(20), index=True)
    action     = Column(String(10))  # BUY/SELL/HALT
    confidence = Column(Numeric(6, 4), default=0.0)
    timestamp  = Column(DateTime(timezone=True), default=_utcnow, index=True)
    processed  = Column(Boolean, default=False)


class ExecutionRecord(Base):
    """Tracks physical Alpaca executions correlating to algorithmic signals."""
    __tablename__ = "executions"

    id               = Column(Integer, primary_key=True, index=True)
    signal_id        = Column(Integer, ForeignKey("signals.id"))
    alpaca_order_id  = Column(String(50), nullable=True, index=True)
    fill_price       = Column(Numeric(18, 8), default=0.0)
    qty              = Column(Numeric(18, 8), default=1.0)
    slippage         = Column(Numeric(18, 8), default=0.0)
    status           = Column(String(20), default="FILLED")
    failure_reason   = Column(String(500), nullable=True)
    timestamp        = Column(DateTime(timezone=True), default=_utcnow)


class ClosedTrade(Base):
    """Full round-trip trade record (FIFO BUY→SELL reconciliation)."""
    __tablename__ = "closed_trades"

    id                  = Column(Integer, primary_key=True, index=True)
    bot_id              = Column(String(50), index=True)
    symbol              = Column(String(20), index=True)
    direction           = Column(String(10), default="LONG")   # LONG | SHORT
    entry_execution_id  = Column(Integer, ForeignKey("executions.id"), nullable=True)
    exit_execution_id   = Column(Integer, ForeignKey("executions.id"), nullable=True)
    entry_price         = Column(Numeric(18, 8), default=0.0)
    exit_price          = Column(Numeric(18, 8), default=0.0)
    qty                 = Column(Numeric(18, 8), default=0.0)
    realized_pnl        = Column(Numeric(18, 8), default=0.0)
    entry_time          = Column(DateTime(timezone=True), nullable=True)
    exit_time           = Column(DateTime(timezone=True), nullable=True, index=True)


# Composite index for efficient bot+symbol closed-trade lookups
Index("ix_closed_trades_bot_symbol", ClosedTrade.bot_id, ClosedTrade.symbol)


class PortfolioSnapshot(Base):
    """60-second equity snapshots for Sharpe/Sortino and drawdown tracking."""
    __tablename__ = "portfolio_snapshots"

    id           = Column(Integer, primary_key=True, index=True)
    equity       = Column(Numeric(18, 2), default=0.0)
    drawdown_pct = Column(Numeric(10, 6), default=0.0)
    timestamp    = Column(DateTime(timezone=True), default=_utcnow, index=True)


class BotAmend(Base):
    """Tracks deep historical parameter adjustments from Agent insights."""
    __tablename__ = "bot_amends"

    id          = Column(Integer, primary_key=True, index=True)
    model       = Column(String(50))
    action      = Column(String(50))
    target_bot  = Column(String(50), nullable=True)
    reason      = Column(String(500))
    impact      = Column(String(100))
    params_json = Column(String(500), nullable=True)
    timestamp   = Column(DateTime(timezone=True), default=_utcnow)


class BotState(Base):
    """Persists bot halt/resume state across server restarts."""
    __tablename__ = "bot_states"

    id         = Column(Integer, primary_key=True)
    bot_id     = Column(String(50), unique=True, index=True)
    status     = Column(String(20), default="ACTIVE")  # ACTIVE | HALTED
    allocation = Column(Numeric(8, 4), default=0.0)
    updated_at = Column(DateTime(timezone=True), default=_utcnow, onupdate=_utcnow)


class ReflectionLog(Base):
    """Stores post-trade AI insights with optional FK to the triggering execution."""
    __tablename__ = "reflection_logs"

    id           = Column(Integer, primary_key=True, index=True)
    execution_id = Column(Integer, ForeignKey("executions.id"), nullable=True)
    strategy     = Column(String(50), index=True)
    symbol       = Column(String(20))
    action       = Column(String(10))
    insight      = Column(String(500))
    tokens_used  = Column(Integer, nullable=True)
    timestamp    = Column(DateTime(timezone=True), default=_utcnow)


class LLMUsage(Base):
    """Tracks per-call LLM token consumption and USD cost."""
    __tablename__ = "llm_usage"

    id         = Column(Integer, primary_key=True, index=True)
    model      = Column(String(50))
    tokens_in  = Column(Integer, default=0)
    tokens_out = Column(Integer, default=0)
    cost_usd   = Column(Numeric(10, 6), default=0.0)
    purpose    = Column(String(50))  # "reflection" | "scanner" | "orchestrator"
    timestamp  = Column(DateTime(timezone=True), default=_utcnow)


class WatchlistItem(Base):
    """Scanner Agent output — persisted symbol scores and Haiku verdicts."""
    __tablename__ = "watchlist_items"

    id           = Column(Integer, primary_key=True, index=True)
    symbol       = Column(String(20), unique=True, index=True)
    score        = Column(Numeric(8, 4), default=0.0)
    signal       = Column(String(10), default="NEUTRAL")  # BUY / SELL / NEUTRAL
    verdict      = Column(String(200), nullable=True)
    last_scanned = Column(DateTime(timezone=True), default=_utcnow)
    active       = Column(Boolean, default=True)
