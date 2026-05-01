import logging
import os
from datetime import datetime, timezone
from pathlib import Path
from pydantic import BaseModel
from langchain_google_genai import ChatGoogleGenerativeAI
from langchain_core.messages import SystemMessage
from config import GEMINI_3_FLASH_MODEL, GEMINI_3_1_FLASH_LITE_MODEL, GEMINI_2_5_FLASH_LITE_MODEL

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
        self._limit: int = int(os.getenv("GEMINI_DAILY_LIMIT", "450"))
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
        """Returns the Gemini model best suited for the task.

        All tiers use gemini-3.1-flash-lite-preview (500 RPD free, higher limit than 2.5-flash).
        When the daily free-tier budget runs out, build_model() returns None
        and callers gracefully degrade (template fallback / skip).
        """
        gemini_key = os.getenv("GEMINI_API_KEY")
        _valid_gemini_key = bool(gemini_key and gemini_key not in ("", "your_gemini_key_here"))

        def _gemini_permitted() -> bool:
            """True only if the key is configured AND the daily budget permits this tier."""
            return _valid_gemini_key and _gemini_budget.request(model_level)

        if not _gemini_permitted():
            return None

        # Paid fallback — reserved for deep reasoning tasks only
        if model_level in ("smart", "research"):
            from config import GEMINI_FALLBACK_MODEL
            model_name = GEMINI_FALLBACK_MODEL
            temp   = 0.0
            budget = max_tokens or (4096 if model_level == "smart" else 1500)
        else:
            # Free tier — all other tiers
            from config import GEMINI_FREE_MODEL
            model_name = GEMINI_FREE_MODEL
            temp   = 0.1
            if model_level == "signal":
                temp   = 0.0
                budget = max_tokens or 150
            elif model_level == "discovery":
                temp   = 0.0
                budget = max_tokens or 800
            elif model_level == "chat":
                budget = max_tokens or 300
            elif model_level == "director":
                budget = max_tokens or 400
            elif model_level == "fast":
                budget = max_tokens or 150
            else:
                budget = max_tokens or 2048

        return ChatGoogleGenerativeAI(
            model=model_name,
            temperature=temp,
            max_output_tokens=budget,
            google_api_key=gemini_key,
            max_retries=3,
        )

    def get_system_prompt(self, agent_name: str) -> SystemMessage:
        """Returns the fully constructed SystemMessage for a given agent persona."""
        persona = self.personas.get(agent_name)
        if not persona:
            return SystemMessage(content=f"You are the {agent_name} agent. Assist the user.")
        return SystemMessage(content=persona.system_prompt)

swarm_factory = SwarmFactory()
