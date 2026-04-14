import os
from pathlib import Path
from pydantic import BaseModel
from langchain_anthropic import ChatAnthropic
from langchain_google_genai import ChatGoogleGenerativeAI
from langchain_core.messages import SystemMessage

class AgentDef(BaseModel):
    name: str
    description: str
    system_prompt: str

class SwarmFactory:
    def __init__(self):
        # We look relative to the project root
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
                system_prompt = content # By default use raw content
                
                # If there's yaml frontmatter or specific tags, we extract them. The user's markdown
                # format for orchestrator indicates "name:", "description:", "system_prompt:" blocks
                if "system_prompt: |" in content:
                    parts = content.split("system_prompt: |")
                    system_prompt = parts[1].strip()

                self.personas[name] = AgentDef(
                    name=name,
                    description=f"Agent parsed from {name}.md",
                    system_prompt=system_prompt
                )
        print(f"[LLM SWARM] Factory Initialized with {len(self.personas)} personas.")

    def build_model(self, model_level="standard"):
        """Returns the appropriate LLM client based on cost/capability tier.

        Priority: Claude (primary) → Gemini (fallback) for all tiers.
        Claude is preferred because prompt caching is applied to the system
        prompt, which only works with Anthropic's API.

        Tiers:
        - smart:    claude-opus-4-6    / gemini-2.5-pro (fallback)
        - standard: claude-sonnet-4-6  / gemini-2.0-flash (fallback)
        - fast:     claude-haiku-4-5   / gemini-2.0-flash (fallback)
        """
        claude_key = os.getenv("ANTHROPIC_API_KEY")
        gemini_key = os.getenv("GEMINI_API_KEY")
        _valid_claude = bool(claude_key and claude_key not in ("", "your_anthropic_key_here"))
        _valid_gemini = bool(gemini_key and gemini_key not in ("", "your_gemini_key_here"))

        # --- Claude primary routes ---
        if model_level == "smart" and _valid_claude:
            return ChatAnthropic(
                model="claude-opus-4-6",
                temperature=0,
                anthropic_api_key=claude_key,
            )

        if model_level == "standard" and _valid_claude:
            return ChatAnthropic(
                model="claude-sonnet-4-6",
                temperature=0.1,
                anthropic_api_key=claude_key,
            )

        if model_level == "fast" and _valid_claude:
            return ChatAnthropic(
                model="claude-haiku-4-5-20251001",
                temperature=0.1,
                anthropic_api_key=claude_key,
            )

        # --- Gemini fallback routes (current stable model names) ---
        if model_level == "smart" and _valid_gemini:
            return ChatGoogleGenerativeAI(
                model="gemini-2.5-pro",
                temperature=0,
                google_api_key=gemini_key,
            )

        if model_level in ("standard", "fast") and _valid_gemini:
            return ChatGoogleGenerativeAI(
                model="gemini-2.0-flash",
                temperature=0.1,
                google_api_key=gemini_key,
            )

        return None

    def get_system_prompt(self, agent_name: str) -> SystemMessage:
        """Returns the fully constructed SystemMessage for a given agent persona."""
        persona = self.personas.get(agent_name)
        if not persona:
            return SystemMessage(content=f"You are the {agent_name} agent. Assist the user.")
            
        return SystemMessage(content=persona.system_prompt)

swarm_factory = SwarmFactory()
