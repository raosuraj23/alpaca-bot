import logging
from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field
from agents.orchestrator import master_orchestrator
from agents.risk_agent import risk_agent

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/api")

class ChatPayload(BaseModel):
    message: str = Field(..., min_length=1, max_length=2000)


@router.post("/agents/chat")
async def chat_with_orchestrator(payload: ChatPayload):
    """Routes user message to the LangChain orchestrator agent."""
    try:
        reply = await master_orchestrator.process_chat(payload.message)
        return {"sender": "ai", "text": reply}
    except Exception as e:
        logger.error("[ORCHESTRATOR] %s", e)
        raise HTTPException(status_code=500, detail="Orchestrator error")


@router.get("/risk/status")
def get_risk_status():
    """Returns kill switch state, drawdown %, and exposure limits."""
    return risk_agent.get_risk_status()
