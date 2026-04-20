import logging
import os
from datetime import datetime, timezone
from pathlib import Path
from pydantic import BaseModel
from langchain_anthropic import ChatAnthropic
from langchain_google_genai import ChatGoogleGenerativeAI
from langchain_core.messages import SystemMessage
from config import CLAUDE_HAIKU_MODEL, CLAUDE_SONNET_MODEL, CLAUDE_OPUS_MODEL, GEMINI_FLASH_MODEL

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Gemini daily request budget — preserves free-tier RPD limit
# ---------------------------------------------------------------------------

class GeminiDailyBudget:
    """
    Two-layer Gemini quota guard:

    Layer 1 — Soft pre-emptive counter (env GEMINI_DAILY_LIMIT, default 18).
      Prevents requests before hitting the actual API wall. Resets at UTC midnight.

    Layer 2 — Hard exception flag (mark_daily_exhausted).
      Set the moment a ResourceExhausted / GenerateRequestsPerDay error is caught
      anywhere in the codebase. Locks out Gemini for the rest of the calendar day
      regardless of the counter, so retry loops never spin on a dead quota.

    On a paid tier: set GEMINI_DAILY_LIMIT=100000 to disable the soft cap while
    keeping the hard exception flag as a safety net.
    """

    PRIORITY_TIERS = {"research"}  # reserved when budget is low

    def __init__(self):
        self._limit: int = int(os.getenv("GEMINI_DAILY_LIMIT", "18"))
        self._count: int = 0
        self._hard_exhausted: bool = False   # set by mark_daily_exhausted()
        self._day_anchor: int = self._today()

    def _today(self) -> int:
        return datetime.now(timezone.utc).timetuple().tm_yday

    def _maybe_reset(self) -> None:
        today = self._today()
        if today != self._day_anchor:
            logger.info(
                "[FACTORY] New UTC day — Gemini budget reset (used %d calls, hard_exhausted=%s)",
                self._count, self._hard_exhausted,
            )
            self._count = 0
            self._hard_exhausted = False
            self._day_anchor = today

    def mark_daily_exhausted(self) -> None:
        """
        Called by ResilientGeminiModel when the API returns a GenerateRequestsPerDay
        quota error. Permanently blocks all Gemini calls until UTC midnight.
        """
        if not self._hard_exhausted:
            logger.critical(
                "[FACTORY] Gemini daily RPD confirmed exhausted by API — "
                "routing ALL tiers to Claude until midnight UTC"
            )
        self._hard_exhausted = True
        self._count = self._limit  # keep counter consistent with UI display

    def mark_rpm_hit(self, tier: str) -> None:
        """Called when a per-minute rate limit fires (temporary — Gemini still available)."""
        logger.warning(
            "[FACTORY] Gemini RPM limit hit for '%s' tier — falling back to Claude for this call", tier
        )

    def request(self, tier: str) -> bool:
        """Returns True if a Gemini call is permitted for this tier."""
        self._maybe_reset()
        if self._hard_exhausted:
            return False
        if self._count >= self._limit:
            if self._count == self._limit:
                logger.warning(
                    "[FACTORY] Gemini soft budget exhausted (%d/%d) — routing to Claude",
                    self._count, self._limit,
                )
            return False
        # Reserve last 3 calls for high-priority tiers
        reserved_floor = max(0, self._limit - 3)
        if self._count >= reserved_floor and tier not in self.PRIORITY_TIERS:
            logger.info(
                "[FACTORY] Gemini budget low (%d/%d) — routing '%s' to Claude",
                self._count, self._limit, tier,
            )
            return False
        self._count += 1
        logger.debug("[FACTORY] Gemini granted '%s' (%d/%d)", tier, self._count, self._limit)
        return True

    @property
    def remaining(self) -> int:
        self._maybe_reset()
        if self._hard_exhausted:
            return 0
        return max(0, self._limit - self._count)

    @property
    def limit(self) -> int:
        return self._limit

    @property
    def hard_exhausted(self) -> bool:
        return self._hard_exhausted


# ---------------------------------------------------------------------------
# Resilient model wrapper — exception-based routing on ResourceExhausted
# ---------------------------------------------------------------------------

def _is_daily_quota_error(exc: Exception) -> bool:
    """True when the Google API signals the DAILY RPD limit (not a per-minute RPM spike)."""
    s = str(exc)
    return "GenerateRequestsPerDay" in s or "generate_content_free_tier_requests" in s


def _is_quota_error(exc: Exception) -> bool:
    """True for any Gemini 429 / ResourceExhausted error."""
    name = type(exc).__name__
    s = str(exc)
    return (
        "ResourceExhausted" in name
        or "429" in s
        or "quota" in s.lower()
        or "rate_limit" in s.lower()
    )


class _ResilientStructuredChain:
    """
    Wraps a structured-output chain (from model.with_structured_output()) so that
    ResourceExhausted errors from Gemini fall over to the Claude equivalent.
    """

    def __init__(self, gemini_chain, claude_chain, tier: str):
        self._gemini = gemini_chain
        self._claude = claude_chain
        self._tier = tier

    async def ainvoke(self, messages, **kwargs):
        try:
            return await self._gemini.ainvoke(messages, **kwargs)
        except Exception as exc:
            if _is_quota_error(exc):
                if _is_daily_quota_error(exc):
                    _gemini_budget.mark_daily_exhausted()
                else:
                    _gemini_budget.mark_rpm_hit(self._tier)
                if self._claude:
                    logger.info("[FACTORY] Structured chain fallback to Claude for '%s'", self._tier)
                    return await self._claude.ainvoke(messages, **kwargs)
            raise

    def invoke(self, messages, **kwargs):
        try:
            return self._gemini.invoke(messages, **kwargs)
        except Exception as exc:
            if _is_quota_error(exc):
                if _is_daily_quota_error(exc):
                    _gemini_budget.mark_daily_exhausted()
                else:
                    _gemini_budget.mark_rpm_hit(self._tier)
                if self._claude:
                    logger.info("[FACTORY] Structured chain fallback to Claude for '%s'", self._tier)
                    return self._claude.invoke(messages, **kwargs)
            raise


class ResilientGeminiModel:
    """
    Drop-in wrapper around ChatGoogleGenerativeAI that automatically falls over to
    a Claude Haiku backup when Gemini raises ResourceExhausted.

    - GenerateRequestsPerDay error → calls _gemini_budget.mark_daily_exhausted(),
      which locks out all Gemini calls until UTC midnight (no more retry loops).
    - Per-minute RPM error → single-call fallback only; Gemini remains available
      for subsequent calls.

    Implements the LangChain Runnable interface surface used by all agents:
      invoke(), ainvoke(), with_structured_output()
    """

    def __init__(self, gemini_model, claude_fallback, tier: str):
        self._gemini = gemini_model
        self._claude = claude_fallback
        self._tier = tier

    def _handle_quota(self, exc: Exception) -> None:
        if _is_daily_quota_error(exc):
            _gemini_budget.mark_daily_exhausted()
        else:
            _gemini_budget.mark_rpm_hit(self._tier)

    def invoke(self, messages, **kwargs):
        try:
            return self._gemini.invoke(messages, **kwargs)
        except Exception as exc:
            if _is_quota_error(exc):
                self._handle_quota(exc)
                if self._claude:
                    logger.info("[FACTORY] invoke() fallback to Claude for '%s'", self._tier)
                    return self._claude.invoke(messages, **kwargs)
            raise

    async def ainvoke(self, messages, **kwargs):
        try:
            return await self._gemini.ainvoke(messages, **kwargs)
        except Exception as exc:
            if _is_quota_error(exc):
                self._handle_quota(exc)
                if self._claude:
                    logger.info("[FACTORY] ainvoke() fallback to Claude for '%s'", self._tier)
                    return await self._claude.ainvoke(messages, **kwargs)
            raise

    def with_structured_output(self, schema):
        try:
            gemini_chain = self._gemini.with_structured_output(schema)
        except (NotImplementedError, TypeError):
            gemini_chain = None
        claude_chain = None
        if self._claude:
            try:
                claude_chain = self._claude.with_structured_output(schema)
            except (NotImplementedError, TypeError):
                pass
        if gemini_chain is None:
            return claude_chain  # Gemini doesn't support structured output for this config
        return _ResilientStructuredChain(gemini_chain, claude_chain, self._tier)


_gemini_budget = GeminiDailyBudget()


class AgentDef(BaseModel):
    name: str
    description: str
    system_prompt: str

class SwarmFactory:
    def __init__(self):
        self.agents_dir = Path(__file__).resolve().parent.parent.parent / ".claude" / "agents"
        self.personas = {}
        self._load_all_agents()

    def _load_all_agents(self):
        """Scans the .claude/agents directories and extracts name, description, and system_prompt"""
        if not self.agents_dir.exists():
            print(f"[LLM SWARM] Warning: Agent directory not found at {self.agents_dir}")
            return

        for filepath in self.agents_dir.glob("*.md"):
            with open(filepath, "r", encoding="utf-8") as f:
                content = f.read()
                name = filepath.stem
                system_prompt = content
                if "system_prompt: |" in content:
                    parts = content.split("system_prompt: |")
                    system_prompt = parts[1].strip()
                self.personas[name] = AgentDef(
                    name=name,
                    description=f"Agent parsed from {name}.md",
                    system_prompt=system_prompt
                )
        print(f"[LLM SWARM] Factory Initialized with {len(self.personas)} personas.")

    def build_model(self, model_level: str = "standard", max_tokens: int | None = None):
        """Returns the LLM best suited for the task at the lowest cost.

        Principle: minimum capable model + strict token budget.
        Both providers are used simultaneously — each tier maps to the
        model that fits the task, not a primary/fallback chain.

        Tiers:
          research  — gemini-2.5-flash  / haiku fallback  (1500t, 30-min deep analysis)
          discovery — gemini-2.5-flash  / haiku fallback  (800t,  symbol ranked selection)
          fast      — gemini-2.5-flash  / haiku fallback  (150t,  verdicts, learnings)
          chat      — claude-haiku      / flash fallback  (300t,  command parsing + caching)
          signal    — gemini-2.5-flash  / haiku fallback  (150t,  binary APPROVED/REJECTED + rationale)
          director  — claude-haiku      / flash fallback  (400t,  Pydantic structured output)
          smart     — claude-opus-4-6   / gemini-2.5-flash (legacy, uncapped)
          standard  — claude-sonnet-4-6 / gemini-2.5-flash (legacy, uncapped)
        """
        claude_key = os.getenv("ANTHROPIC_API_KEY")
        gemini_key = os.getenv("GEMINI_API_KEY")
        _valid_claude = bool(claude_key and claude_key not in ("", "your_anthropic_key_here"))
        _valid_gemini_key = bool(gemini_key and gemini_key not in ("", "your_gemini_key_here"))

        def _gemini_permitted() -> bool:
            """True only if the key is configured AND the daily budget permits this tier."""
            return _valid_gemini_key and _gemini_budget.request(model_level)

        def _haiku(temp: float, budget: int) -> ChatAnthropic | None:
            if not _valid_claude:
                return None
            return ChatAnthropic(
                model=CLAUDE_HAIKU_MODEL,
                temperature=temp,
                max_tokens=budget,
                anthropic_api_key=claude_key,
            )

        def _resilient_flash(temp: float, budget: int) -> ResilientGeminiModel | None:
            """
            Returns a ResilientGeminiModel that calls Gemini and automatically falls
            over to Claude Haiku when ResourceExhausted is raised. Returns None if
            neither key is available.
            """
            if not _gemini_permitted():
                return None  # budget depleted — caller falls through to bare Haiku
            gemini = ChatGoogleGenerativeAI(
                model=GEMINI_FLASH_MODEL,
                temperature=temp,
                max_output_tokens=budget,
                google_api_key=gemini_key,
            )
            claude_fb = _haiku(temp, budget)
            return ResilientGeminiModel(gemini, claude_fb, model_level)

        # ── research ─────────────────────────────────────────────────────────
        if model_level == "research":
            budget = max_tokens or 1500
            return _resilient_flash(0, budget) or _haiku(0, budget)

        # ── discovery ────────────────────────────────────────────────────────
        if model_level == "discovery":
            budget = max_tokens or 800
            return _resilient_flash(0, budget) or _haiku(0, budget)

        # ── fast ─────────────────────────────────────────────────────────────
        if model_level == "fast":
            budget = max_tokens or 150
            return _resilient_flash(0.1, budget) or _haiku(0.1, budget)

        # ── chat ─────────────────────────────────────────────────────────────
        # Claude Haiku primary — no Gemini wrapper needed
        if model_level == "chat":
            budget = max_tokens or 300
            return _haiku(0.1, budget) or _resilient_flash(0.1, budget)

        # ── signal ───────────────────────────────────────────────────────────
        if model_level == "signal":
            budget = max_tokens or 150
            return _resilient_flash(0, budget) or _haiku(0, budget)

        # ── director ─────────────────────────────────────────────────────────
        # Claude Haiku primary — no Gemini wrapper needed
        if model_level == "director":
            budget = max_tokens or 400
            return _haiku(0.1, budget) or _resilient_flash(0.1, budget)

        # ── smart (legacy) ───────────────────────────────────────────────────
        if model_level == "smart":
            if _valid_claude:
                return ChatAnthropic(
                    model=CLAUDE_OPUS_MODEL,
                    temperature=0,
                    anthropic_api_key=claude_key,
                )
            return _resilient_flash(0, 4096) or None

        # ── standard (legacy) ────────────────────────────────────────────────
        if model_level == "standard":
            if _valid_claude:
                return ChatAnthropic(
                    model=CLAUDE_SONNET_MODEL,
                    temperature=0.1,
                    anthropic_api_key=claude_key,
                )
            return _resilient_flash(0.1, 2048) or None

        return None

    def get_system_prompt(self, agent_name: str) -> SystemMessage:
        """Returns the fully constructed SystemMessage for a given agent persona."""
        persona = self.personas.get(agent_name)
        if not persona:
            return SystemMessage(content=f"You are the {agent_name} agent. Assist the user.")
        return SystemMessage(content=persona.system_prompt)

swarm_factory = SwarmFactory()
