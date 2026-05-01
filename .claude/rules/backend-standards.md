# rules/backend-standards.md — Backend Coding Standards
# These rules are MANDATORY for all backend (Python / FastAPI / agents) work.

---

## 10. Agent Orchestrator Pipeline

Follow `docs/execution-plan.md` for the multi-stage rollout of the Python FastAPI orchestrator. Do not skip phases or implement backend logic without following the agent boundaries defined in `AGENTS.md`.

---

## 11. Security Non-Negotiables

Never hardcode API keys. All credentials come from `.env` via pydantic-settings. Never enable Alpaca Transfer/Withdrawal permissions. See `.claude/rules/security-and-risk.md` for full rules.

---

## 17. Gemini Model Version

The canonical Gemini model is `gemini-3.1-flash-lite-preview` everywhere (500 RPD free tier — higher than `gemini-2.5-flash`'s 20 RPD). Never use `gemini-2.0-flash` or `gemini-2.5-flash` in any agent, factory, or cost-log string. Update all references whenever touching `agents/factory.py` or any file that logs a model name.

---

## 18. No Hardcoded Symbol Lists in Agents

Trading universes (`CRYPTO_UNIVERSE`, `EQUITY_UNIVERSE`, `EQUITY_STREAM_SYMBOLS`, etc.) must use the dynamic `expand_universe()` / `get_universe()` pattern from `backend/agents/scanner_agent.py`. Seeds are allowed as bootstrap-only starting points. Never add new hardcoded symbol lists outside of those seed constants.
