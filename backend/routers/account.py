from fastapi import APIRouter, HTTPException
from deps import get_trading_client
import logging

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/api")

@router.get("/account")
def get_account():
    client = get_trading_client()
    try:
        acc = client.get_account()
        equity      = float(acc.equity or 0)
        last_equity = float(getattr(acc, 'last_equity', None) or equity)
        today_pl    = equity - last_equity
        unrealized_pl = 0.0
        for attr in ('unrealized_pl', 'unrealized_plpc'):
            raw = getattr(acc, attr, None)
            if attr == 'unrealized_pl' and raw is not None:
                try: unrealized_pl = float(raw)
                except: pass
                break
        return {
            "equity": str(acc.equity),
            "buying_power": str(acc.buying_power),
            "cash": str(acc.cash),
            "portfolio_value": str(acc.portfolio_value),
            "status": acc.status.value if hasattr(acc.status, 'value') else str(acc.status).replace('AccountStatus.', ''),
            "last_equity": str(last_equity),
            "today_pl": round(today_pl, 2),
            "unrealized_pl": round(unrealized_pl, 2),
        }
    except Exception as e:
        logger.error("[ACCOUNT] %s", e)
        raise HTTPException(status_code=502, detail=str(e))

@router.get("/positions")
def get_positions():
    client = get_trading_client()

    def _str(v):
        return str(v) if v is not None else None

    try:
        pos = client.get_all_positions()
        return [{
            "symbol": p.symbol,
            "side": p.side.value if hasattr(p.side, 'value') else str(p.side).split('.')[-1],
            "size": _str(p.qty),
            "avg_entry_price": _str(p.avg_entry_price),
            "current_price": _str(p.current_price),
            "unrealized_pnl": _str(p.unrealized_pl),
        } for p in pos]
    except Exception as e:
        logger.error("[POSITIONS] %s", e)
        raise HTTPException(status_code=502, detail=str(e))

@router.get("/orders")
def get_orders():
    client = get_trading_client()
    try:
        from alpaca.trading.requests import GetOrdersRequest
        from alpaca.trading.enums import QueryOrderStatus
        req = GetOrdersRequest(status=QueryOrderStatus.ALL, limit=50)
        orders = client.get_orders(filter=req)
        return [{
            "id": str(o.id)[:8],
            "symbol": o.symbol,
            "side": o.side.value if hasattr(o.side, 'value') else str(o.side).replace('OrderSide.', ''),
            "qty": str(o.filled_qty or o.qty),
            "status": o.status.value if hasattr(o.status, 'value') else str(o.status).replace('OrderStatus.', ''),
            "fill_price": str(o.filled_avg_price) if o.filled_avg_price else None,
            "submitted_at": o.submitted_at.isoformat() if o.submitted_at else None,
        } for o in orders]
    except Exception as e:
        logger.error("[ORDERS] %s", e)
        raise HTTPException(status_code=502, detail=str(e))
