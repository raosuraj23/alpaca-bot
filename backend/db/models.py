from datetime import datetime, timezone
from sqlalchemy import Column, Integer, String, Float, DateTime, Boolean, ForeignKey
from db.database import Base


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


class SignalRecord(Base):
    """Tracks generated sub-signals natively from the Strategy Engine."""
    __tablename__ = "signals"

    id = Column(Integer, primary_key=True, index=True)
    strategy = Column(String(50), index=True)
    symbol = Column(String(20), index=True)
    action = Column(String(10)) # BUY/SELL/HALT
    confidence = Column(Float)
    timestamp = Column(DateTime(timezone=True), default=_utcnow)
    processed = Column(Boolean, default=False)

class ExecutionRecord(Base):
    """Tracks physical Alpaca executions correlating to algorithmic signals."""
    __tablename__ = "executions"

    id = Column(Integer, primary_key=True, index=True)
    signal_id = Column(Integer, ForeignKey("signals.id"))
    alpaca_order_id = Column(String(50), nullable=True)
    fill_price = Column(Float, default=0.0)
    qty = Column(Float, default=1.0)         # filled quantity from Alpaca order
    slippage = Column(Float, default=0.0)
    status = Column(String(20), default="FILLED")
    failure_reason = Column(String(500), nullable=True)
    timestamp = Column(DateTime(timezone=True), default=_utcnow)

class BotAmend(Base):
    """Tracks deep historical parameter adjustments from Agent insights."""
    __tablename__ = "bot_amends"

    id          = Column(Integer, primary_key=True, index=True)
    model       = Column(String(50))
    action      = Column(String(50))
    target_bot  = Column(String(50), nullable=True)       # which bot was affected
    reason      = Column(String(500))
    impact      = Column(String(100))                     # Expected statistical effect
    params_json = Column(String(500), nullable=True)      # JSON of changed params
    timestamp   = Column(DateTime(timezone=True), default=_utcnow)


class BotState(Base):
    """Persists bot halt/resume state across server restarts."""
    __tablename__ = "bot_states"

    id         = Column(Integer, primary_key=True)
    bot_id     = Column(String(50), unique=True, index=True)
    status     = Column(String(20), default="ACTIVE")     # ACTIVE | HALTED
    allocation = Column(Float, default=0.0)
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
    """Tracks per-call LLM token consumption and USD cost for cost-vs-PnL analysis."""
    __tablename__ = "llm_usage"

    id         = Column(Integer, primary_key=True, index=True)
    model      = Column(String(50))                          # e.g. claude-haiku-4-5, claude-sonnet-4-6
    tokens_in  = Column(Integer, default=0)
    tokens_out = Column(Integer, default=0)
    cost_usd   = Column(Float, default=0.0)                  # computed at insert time
    purpose    = Column(String(50))                          # "reflection" | "scanner" | "orchestrator"
    timestamp  = Column(DateTime(timezone=True), default=_utcnow)


class WatchlistItem(Base):
    """Scanner Agent output — persisted symbol scores and Haiku verdicts."""
    __tablename__ = "watchlist_items"

    id           = Column(Integer, primary_key=True, index=True)
    symbol       = Column(String(20), unique=True, index=True)
    score        = Column(Float, default=0.0)           # Composite TA score
    signal       = Column(String(10), default="NEUTRAL") # BUY / SELL / NEUTRAL
    verdict      = Column(String(200), nullable=True)   # Haiku one-liner
    last_scanned = Column(DateTime(timezone=True), default=_utcnow)
    active       = Column(Boolean, default=True)
