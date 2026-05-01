from datetime import datetime, timezone
from decimal import Decimal
from sqlalchemy import Column, Integer, String, Numeric, DateTime, Boolean, ForeignKey, JSON, Text
from db.database import Base

def _utcnow() -> datetime:
    return datetime.now(timezone.utc)

# ---------------------------------------------------------
# SIGNAL & EXECUTION LAYER
# ---------------------------------------------------------

class SignalRecord(Base):
    """Tracks generated sub-signals natively from the Strategy Engine."""
    __tablename__ = "signals"

    id = Column(Integer, primary_key=True, index=True)
    strategy = Column(String(50), index=True)
    symbol = Column(String(20), index=True)
    action = Column(String(10)) # BUY/SELL/HALT
    confidence = Column(Numeric(5, 4)) # e.g., 0.9521
    timestamp = Column(DateTime(timezone=True), default=_utcnow)
    processed = Column(Boolean, default=False)
    # Formula metrics — captured at signal generation time
    expected_value      = Column(Numeric(8, 4), nullable=True)   # EV = p*b - (1-p)
    kelly_fraction      = Column(Numeric(5, 4), nullable=True)   # half-Kelly sizing fraction
    market_edge         = Column(Numeric(5, 4), nullable=True)   # p_model - p_mkt
    market_implied_prob = Column(Numeric(5, 4), nullable=True)   # p_mkt from scanner/research
    mispricing_z_score  = Column(Numeric(8, 4), nullable=True)   # (p_model - p_mkt) / rolling_sigma
    xgboost_prob        = Column(Numeric(5, 4), nullable=True)   # XGBoost P(win) at signal time
    signal_features     = Column(JSON, nullable=True)            # TA feature vector used by XGBoost
    asset_class         = Column(String(10), nullable=True, index=True)  # CRYPTO | EQUITY | OPTIONS

class ExecutionRecord(Base):
    """Tracks physical Alpaca executions correlating to algorithmic signals."""
    __tablename__ = "executions"

    id = Column(Integer, primary_key=True, index=True)
    signal_id = Column(Integer, ForeignKey("signals.id"))
    alpaca_order_id = Column(String(50), unique=True, index=True) # CRITICAL: Indexed for Webhooks
    side = Column(String(10)) # BUY / SELL
    fill_price = Column(Numeric(20, 9), default=Decimal('0.0'))   # Precision for Crypto/Equities
    qty = Column(Numeric(20, 9), default=Decimal('0.0'))
    commission = Column(Numeric(10, 4), default=Decimal('0.0'))   # Must track fees for Net PnL
    slippage = Column(Numeric(20, 9), default=Decimal('0.0'))
    status = Column(String(20), default="FILLED")
    failure_reason = Column(String(500), nullable=True)
    timestamp = Column(DateTime(timezone=True), default=_utcnow, index=True)
    asset_class = Column(String(10), nullable=True)  # CRYPTO | EQUITY | OPTIONS
    bid_price = Column(Numeric(20, 9), nullable=True)   # best bid at submission time
    ask_price = Column(Numeric(20, 9), nullable=True)   # best ask at submission time
    # Options-specific metadata (null for equity/crypto)
    contract_symbol = Column(String(50), nullable=True)  # resolved OCC symbol e.g. AAPL230217C00160000
    option_type     = Column(String(4),  nullable=True)  # "call" | "put"
    strike_price    = Column(Numeric(20, 9), nullable=True)
    expiry_date     = Column(String(20), nullable=True)  # ISO date from resolved contract

# ---------------------------------------------------------
# PNL & PORTFOLIO LAYER (NEW - FIXES THE BUG)
# ---------------------------------------------------------

class ClosedTrade(Base):
    """Tracks a full round-trip trade for highly accurate Realized PnL reporting."""
    __tablename__ = "closed_trades"

    id = Column(Integer, primary_key=True, index=True)
    bot_id = Column(String(50), ForeignKey("bot_states.bot_id"), index=True)
    symbol = Column(String(20), index=True)
    entry_time = Column(DateTime(timezone=True))
    exit_time = Column(DateTime(timezone=True), index=True)
    entry_execution_id = Column(Integer, ForeignKey("executions.id"), nullable=True)
    exit_execution_id = Column(Integer, ForeignKey("executions.id"), nullable=True)
    qty = Column(Numeric(20, 9))
    avg_entry_price = Column(Numeric(20, 9))
    avg_exit_price = Column(Numeric(20, 9))
    realized_pnl = Column(Numeric(18, 4))        # Gross PnL
    net_pnl = Column(Numeric(18, 4))             # Realized PnL minus commissions
    win = Column(Boolean)                        # Fast querying for win-rate
    # Formula metrics — snapshotted from entry signal for post-trade analysis
    entry_ev           = Column(Numeric(8, 4), nullable=True)   # EV at entry
    entry_kelly        = Column(Numeric(5, 4), nullable=True)   # Kelly fraction at entry
    entry_edge         = Column(Numeric(5, 4), nullable=True)   # market_edge at entry
    brier_contribution = Column(Numeric(8, 6), nullable=True)   # (confidence - outcome)^2
    asset_class        = Column(String(10), nullable=True)      # CRYPTO | EQUITY | OPTIONS
    confidence         = Column(Numeric(5, 4), nullable=True)   # signal confidence at entry
    # Options-specific metadata (null for equity/crypto)
    option_type  = Column(String(4),  nullable=True)  # "call" | "put"
    strike_price = Column(Numeric(20, 9), nullable=True)
    expiry_date  = Column(String(20), nullable=True)

class PortfolioSnapshot(Base):
    """Time-series equity curve for fast UI rendering (bypasses Alpaca API limits)."""
    __tablename__ = "portfolio_snapshots"

    id = Column(Integer, primary_key=True, index=True)
    timestamp = Column(DateTime(timezone=True), default=_utcnow, index=True)
    total_equity = Column(Numeric(18, 4))
    cash_balance = Column(Numeric(18, 4))
    margin_used = Column(Numeric(18, 4), nullable=True)
    unrealized_pnl = Column(Numeric(18, 4))
    realized_pnl_day = Column(Numeric(18, 4))
    drawdown_threshold = Column(Numeric(18, 4), nullable=True)

class MarketConditionSnapshot(Base):
    """Stores the state of the market order book and indicators at exact execution time."""
    __tablename__ = "market_condition_snapshots"

    id = Column(Integer, primary_key=True, index=True)
    execution_id = Column(Integer, ForeignKey("executions.id"), nullable=True)
    symbol = Column(String(20), index=True)
    timestamp = Column(DateTime(timezone=True), default=_utcnow, index=True)
    bid_price = Column(Numeric(20, 9))
    ask_price = Column(Numeric(20, 9))
    spread = Column(Numeric(10, 6), nullable=True)
    volume_profile = Column(JSON, nullable=True)

# ---------------------------------------------------------
# AGENT & SYSTEM LAYER
# ---------------------------------------------------------

class BotState(Base):
    """Persists bot halt/resume state across server restarts."""
    __tablename__ = "bot_states"

    id = Column(Integer, primary_key=True)
    bot_id = Column(String(50), unique=True, index=True)
    status = Column(String(20), default="ACTIVE")     
    allocation = Column(Numeric(18, 4), default=Decimal('0.0')) # Swapped to Numeric
    updated_at = Column(DateTime(timezone=True), default=_utcnow, onupdate=_utcnow)

class BotParameterControl(Base):
    """Single source of truth for the active strategy parameters of a bot."""
    __tablename__ = "bot_parameter_control"
    
    bot_id = Column(String(80), primary_key=True, index=True)
    params_json = Column(Text, nullable=False)
    updated_by = Column(String(50), default="system")
    updated_at = Column(DateTime(timezone=True), default=_utcnow, onupdate=_utcnow)

class LLMUsage(Base):
    """Tracks per-call LLM token consumption and USD cost for cost-vs-PnL analysis."""
    __tablename__ = "llm_usage"

    id = Column(Integer, primary_key=True, index=True)
    model = Column(String(50))                          
    tokens_in = Column(Integer, default=0)
    tokens_out = Column(Integer, default=0)
    cost_usd = Column(Numeric(10, 6), default=Decimal('0.0')) # 6 decimal places for micro-cents
    purpose = Column(String(50))                          
    timestamp = Column(DateTime(timezone=True), default=_utcnow)

class BotAmend(Base):
    __tablename__ = "bot_amends"
    id = Column(Integer, primary_key=True, index=True)
    model = Column(String(50))
    action = Column(String(50))
    target_bot = Column(String(50), nullable=True)
    reason = Column(String(500))
    impact = Column(String(100))
    params_json = Column(String(500), nullable=True)
    status = Column(String(20), default="logged")  # logged | acted | dismissed
    timestamp = Column(DateTime(timezone=True), default=_utcnow)

class ReflectionLog(Base):
    __tablename__ = "reflection_logs"
    id = Column(Integer, primary_key=True, index=True)
    execution_id = Column(Integer, ForeignKey("executions.id"), nullable=True)
    strategy = Column(String(50), index=True)
    symbol = Column(String(20))
    action = Column(String(10))
    insight = Column(Text)
    tokens_used = Column(Integer, nullable=True)
    # Compound / learning fields
    failure_class      = Column(String(30), nullable=True)      # BAD_PREDICTION | TIMING | EXECUTION | MARKET_SHOCK
    brier_contribution = Column(Numeric(8, 6), nullable=True)   # (forecast - outcome)^2 for this trade
    # Rich trade context (populated for all SELL fills)
    entry_price        = Column(Numeric(20, 9), nullable=True)  # avg entry price for the round-trip
    exit_price         = Column(Numeric(20, 9), nullable=True)  # fill price on exit
    hold_duration_min  = Column(Integer, nullable=True)         # minutes between entry and exit
    market_conditions  = Column(String(500), nullable=True)     # JSON: {rsi, ema_spread, volume_ratio}
    timestamp          = Column(DateTime(timezone=True), default=_utcnow)


class CalibrationRecord(Base):
    """Persists per-strategy calibration snapshots for the Compound learning loop."""
    __tablename__ = "calibration_records"
    id = Column(Integer, primary_key=True, index=True)
    strategy = Column(String(50), index=True)
    forecast = Column(Numeric(5, 4))       # signal confidence at entry
    outcome = Column(Integer)              # 1 = profitable, 0 = loss
    brier_contribution = Column(Numeric(8, 6))  # (forecast - outcome)^2
    timestamp = Column(DateTime(timezone=True), default=_utcnow, index=True)

class WatchlistItem(Base):
    __tablename__ = "watchlist_items"
    id = Column(Integer, primary_key=True, index=True)
    symbol = Column(String(20), unique=True, index=True)
    score = Column(Numeric(5, 4), default=Decimal('0.0'))
    signal = Column(String(10), default="NEUTRAL")
    verdict = Column(String(200), nullable=True)
    last_scanned = Column(DateTime(timezone=True), default=_utcnow)
    active = Column(Boolean, default=True)
    asset_class  = Column(String(10), nullable=True)     # CRYPTO | EQUITY
    rsi          = Column(Numeric(6, 2), nullable=True)  # RSI-14
    ema_spread   = Column(Numeric(8, 6), nullable=True)  # (ema20 - price) / price
    volume_ratio = Column(Numeric(8, 4), nullable=True)  # current_vol / 20-bar avg
    bb_position  = Column(Numeric(5, 4), nullable=True)  # (price - lower) / (upper - lower)


class SymbolStrategyAssignment(Base):
    """Tracks per-symbol strategy assignments created by the Portfolio Director."""
    __tablename__ = "symbol_strategy_assignments"

    id = Column(Integer, primary_key=True, index=True)
    symbol = Column(String(20), index=True)
    bot_id = Column(String(80))                      # e.g. "equity-breakout-nvda-v1"
    algorithm_type = Column(String(50))              # e.g. "equity-breakout"
    assigned_by = Column(String(20), default="director")  # "director" | "manual"
    rationale = Column(String(500), nullable=True)
    params_json = Column(String(1000), nullable=True)     # JSON-encoded custom params
    active = Column(Boolean, default=True, index=True)
    assigned_at = Column(DateTime(timezone=True), default=_utcnow, index=True)
