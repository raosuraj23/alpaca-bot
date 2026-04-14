from datetime import datetime
from sqlalchemy import Column, Integer, String, Float, DateTime, Boolean, ForeignKey
from db.database import Base

class SignalRecord(Base):
    """Tracks generated sub-signals natively from the Strategy Engine."""
    __tablename__ = "signals"
    
    id = Column(Integer, primary_key=True, index=True)
    strategy = Column(String(50), index=True)
    symbol = Column(String(20), index=True)
    action = Column(String(10)) # BUY/SELL/HALT
    confidence = Column(Float)
    timestamp = Column(DateTime, default=datetime.utcnow)
    processed = Column(Boolean, default=False)
    
class ExecutionRecord(Base):
    """Tracks physical Alpaca executions correlating to algorithmic signals."""
    __tablename__ = "executions"
    
    id = Column(Integer, primary_key=True, index=True)
    signal_id = Column(Integer, ForeignKey("signals.id"))
    alpaca_order_id = Column(String(50))
    fill_price = Column(Float)
    slippage = Column(Float, default=0.0)
    timestamp = Column(DateTime, default=datetime.utcnow)
    
class BotAmend(Base):
    """Tracks deep historical parameter adjustments from Agent insights."""
    __tablename__ = "bot_amends"
    
    id = Column(Integer, primary_key=True, index=True)
    model = Column(String(50))
    action = Column(String(50))
    reason = Column(String(500))
    impact = Column(String(100)) # Expected statistical effect
    timestamp = Column(DateTime, default=datetime.utcnow)
