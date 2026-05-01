import logging
from fastapi import APIRouter, HTTPException
from pydantic import BaseModel
from sqlalchemy import select
from strategy.engine import master_engine
from db.database import _get_session_factory
from db.models import BotState
from core.state import _push_log

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/api")

class BotLifecyclePayload(BaseModel):
    reason: str = "Manual override"


@router.get("/bots")
def get_bots():
    """Returns the fleet of active algorithmic trading bots."""
    return master_engine.get_bot_states()


@router.get("/symbol-strategies")
def get_symbol_strategies():
    """Returns current per-symbol strategy assignments and pending quarantine list."""
    return {
        "symbol_strategy_map": master_engine.get_symbol_strategy_map(),
        "pending_assignment": master_engine.get_pending_assignment(),
    }


@router.get("/algorithms")
def get_available_algorithms():
    """Returns all algorithm types available for director-driven strategy instantiation."""
    return {"algorithms": master_engine.get_available_algorithms()}


@router.post("/bots/{bot_id}/halt")
async def halt_bot(bot_id: str, payload: BotLifecyclePayload = BotLifecyclePayload()):
    """Halt a specific trading bot by ID and persist state to SQLite."""
    success = master_engine.halt_bot(bot_id, reason=payload.reason)
    if not success:
        raise HTTPException(status_code=404, detail=f"Bot '{bot_id}' not found")

    try:
        async with _get_session_factory()() as session:
            row = (await session.execute(select(BotState).where(BotState.bot_id == bot_id))).scalar_one_or_none()
            if row is None:
                row = BotState(bot_id=bot_id)
                session.add(row)
            row.status = "HALTED"
            row.allocation = master_engine.bots.get(bot_id).allocation if master_engine.bots.get(bot_id) else 0.0
            await session.commit()
    except Exception as exc:
        logger.warning("[HALT] BotState persist failed: %s", exc)

    _push_log(f"[ORCHESTRATOR] ⛔ Bot '{bot_id}' halted — {payload.reason}")
    return {"status": "halted", "bot_id": bot_id, "reason": payload.reason}


@router.post("/bots/{bot_id}/resume")
async def resume_bot(bot_id: str):
    """Resume a halted trading bot and persist ACTIVE state to SQLite."""
    success = master_engine.resume_bot(bot_id)
    if not success:
        raise HTTPException(status_code=404, detail=f"Bot '{bot_id}' not found")

    try:
        async with _get_session_factory()() as session:
            row = (await session.execute(select(BotState).where(BotState.bot_id == bot_id))).scalar_one_or_none()
            if row is None:
                row = BotState(bot_id=bot_id)
                session.add(row)
            row.status = "ACTIVE"
            row.allocation = master_engine.bots.get(bot_id).allocation if master_engine.bots.get(bot_id) else 0.0
            await session.commit()
    except Exception as exc:
        logger.warning("[RESUME] BotState persist failed: %s", exc)

    _push_log(f"[ORCHESTRATOR] ▶️ Bot '{bot_id}' resumed.")
    return {"status": "resumed", "bot_id": bot_id}


@router.get("/strategy/states")
def get_strategy_states():
    """Returns current internal indicator state for all active strategies."""
    return master_engine.get_all_states()
