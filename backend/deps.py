import os
import logging
from fastapi import HTTPException

logger = logging.getLogger(__name__)

ALPACA_API_KEY = os.getenv("ALPACA_API_KEY_ID") or os.getenv("ALPACA_API_KEY")
ALPACA_API_SECRET = os.getenv("ALPACA_API_SECRET_KEY") or os.getenv("ALPACA_API_SECRET")
PAPER_TRADING = os.getenv("PAPER_TRADING", "true").lower() == "true"

trading_client = None

if ALPACA_API_KEY and ALPACA_API_SECRET:
    try:
        from alpaca.trading.client import TradingClient
        trading_client = TradingClient(ALPACA_API_KEY, ALPACA_API_SECRET, paper=PAPER_TRADING)
        logger.info("[ALPACA] TradingClient initialized (paper=%s)", PAPER_TRADING)
    except Exception as e:
        logger.warning("[ALPACA] TradingClient initialization failed: %s", e)
else:
    logger.warning("[ALPACA] API keys not configured — trading endpoints will return errors.")

def get_trading_client():
    if trading_client is None:
        raise HTTPException(status_code=503, detail="Alpaca API keys not configured.")
    return trading_client
