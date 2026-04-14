import logging
import os

logger = logging.getLogger(__name__)

PAPER_TRADING = os.getenv("PAPER_TRADING", "true").lower() == "true"

class AlpacaRouter:
    """Bridging strategy engine decisions to actual API HTTP executions."""
    def submit(self, signal: dict):
        # We must import `trading_client` lazily to avoid circular imports 
        # from main.py's initialization
        try:
            import __main__
            trading_client = getattr(__main__, 'trading_client', None)
            
            if not trading_client:
                # If imported outside of main (like pytest), mock success
                logger.warning("[ROUTER] trading_client object missing, assuming offline test mode.")
                return None
                
            from alpaca.trading.requests import MarketOrderRequest
            from alpaca.trading.enums import OrderSide, TimeInForce
            
            side = OrderSide.BUY if signal['action'] == 'BUY' else OrderSide.SELL
            order = MarketOrderRequest(
                symbol=signal['symbol'],
                qty=signal['qty'],
                side=side,
                time_in_force=TimeInForce.GTC,
            )
            
            if PAPER_TRADING:
                result = trading_client.submit_order(order_data=order)
                logger.info(f"[ROUTER] FILLED! Alpaca ID: {result.id}")
                return result
            else:
                logger.warning("[ROUTER] Blocked execution. Live trading protection engaged.")
                return None
        except ImportError:
             logger.error("[ROUTER] Could not resolve Alpaca SDK.")
        except Exception as e:
            logger.error(f"[ROUTER] Submission failed: {e}")
            return None

live_order_router = AlpacaRouter()
