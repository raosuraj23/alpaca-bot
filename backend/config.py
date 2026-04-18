"""
Central configuration — all credentials and risk parameters loaded from environment.
Fails loudly at import if any required variable is missing (pydantic ValidationError).
"""

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    # Alpaca
    alpaca_api_key_id: str
    alpaca_api_secret_key: str
    alpaca_base_url: str = "https://paper-api.alpaca.markets"
    paper_trading: bool = True

    # LLM providers
    anthropic_api_key: str
    gemini_api_key: str = ""

    # Database
    database_url: str = "sqlite:///./trading_bot.db"

    # Observability
    log_level: str = "INFO"
    playwright_headless: bool = False

    # Risk thresholds (all overridable via env without code changes)
    max_daily_drawdown_pct: float = 2.0     # 2% SOD equity → halt all signals
    max_concurrent_positions: int = 15      # hard cap on open positions
    max_kelly_fraction: float = 0.25        # fractional Kelly floor; scales up to 0.5 via calibration
    slippage_abort_pct: float = 0.02        # abort if pre-execution mid-quote drift > 2%
    min_signal_confidence: float = 0.30     # reject signals below this confidence
    min_edge: float = 0.04                  # model_prob - market_implied_prob must exceed 4%

    # Risk parameters for exposure manager
    var_daily_pct: float = 0.01             # 1% daily VaR limit (95th percentile)
    var_confidence: float = 0.95            # VaR confidence level
    reward_risk_ratio: float = 2.0          # assumed R:R ratio for Kelly sizing

    # Infrastructure
    frontend_url: str = "http://localhost:3000"
    alpaca_news_endpoint: str = "https://data.alpaca.markets/v1beta1/news"


settings = Settings()

# ---------------------------------------------------------------------------
# LLM model identifiers — single source of truth for all agent files
# ---------------------------------------------------------------------------
CLAUDE_HAIKU_MODEL  = "claude-haiku-4-5-20251001"
CLAUDE_SONNET_MODEL = "claude-sonnet-4-6"
CLAUDE_OPUS_MODEL   = "claude-opus-4-6"
GEMINI_FLASH_MODEL  = "gemini-2.5-flash"

# ---------------------------------------------------------------------------
# LLM pricing — $/M tokens (used for cost logging in all agent files)
# ---------------------------------------------------------------------------
HAIKU_COST_IN         = 0.80    # $/M input tokens
HAIKU_COST_OUT        = 4.00    # $/M output tokens
GEMINI_FLASH_COST_IN  = 0.075   # $/M input tokens
GEMINI_FLASH_COST_OUT = 0.30    # $/M output tokens
