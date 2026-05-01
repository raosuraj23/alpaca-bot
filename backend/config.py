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
    anthropic_api_key: str = ""
    gemini_api_key: str = ""

    # Database
    database_url: str = "sqlite:///./alpaca_quant.db"

    # Observability
    log_level: str = "INFO"
    playwright_headless: bool = False

    # Risk thresholds (all overridable via env without code changes)
    max_daily_drawdown_pct: float = 2.0     # 2% SOD equity → halt all signals
    max_concurrent_positions: int = 10      # hard cap on open positions (security-and-risk.md §2.5)
    max_kelly_fraction: float = 0.25        # fractional Kelly floor; scales up to 0.5 via calibration
    slippage_abort_pct: float = 0.005       # abort if pre-execution mid-quote drift > 0.5%
    min_signal_confidence: float = 0.55     # reject signals below this confidence (aligned with xgboost gate)
    min_edge: float = 0.06                  # model_prob - market_implied_prob must exceed 6% (covers ~50bps costs)
    xgboost_min_confidence: float = 0.55    # XGBoost P(win) gate — reject signals below this

    # Risk parameters for exposure manager
    var_daily_pct: float = 0.01             # 1% daily VaR limit (95th percentile)
    var_confidence: float = 0.95            # VaR confidence level
    reward_risk_ratio: float = 2.0          # assumed R:R ratio for Kelly sizing

    # Options-specific risk constraints (security-and-risk.md §2.7)
    max_net_delta: float = 0.30             # net portfolio delta as fraction of NAV
    max_gamma_exposure: float = 0.05        # gamma exposure as fraction of NAV
    min_days_to_expiry: int = 5             # never hold options within 5 DTE

    # Kill-switch intraday recovery (non-manual triggers only)
    recovery_window_secs: int = 5400        # 90-min window to recover after drawdown halt
    recovery_threshold_pct: float = 0.5    # resume when equity within 0.5% of SOD equity

    # Infrastructure
    frontend_url: str = "http://localhost:3000"
    alpaca_news_endpoint: str = "https://data.alpaca.markets/v1beta1/news"


settings = Settings()

# ---------------------------------------------------------------------------
# LLM model identifiers — single source of truth for all agent files
#
# Tier strategy (all confirmed free-tier per ai.google.dev/gemini-api/docs/pricing):
#   GEMINI_FREE_MODEL     — gemini-3.1-flash-lite-preview (500 RPD free, higher than 2.5-flash)
#   GEMINI_FALLBACK_MODEL — same
#
# Note: preview models are free but may become paid or renamed on GA.
# Monitor https://ai.google.dev/gemini-api/docs/deprecations for changes.
# ---------------------------------------------------------------------------
GEMINI_FREE_MODEL     = "gemini-3.1-flash-lite-preview"
GEMINI_FALLBACK_MODEL = GEMINI_FREE_MODEL

# Legacy aliases — all resolve to free-tier primary.
GEMINI_3_FLASH_MODEL        = GEMINI_FALLBACK_MODEL
GEMINI_3_1_FLASH_LITE_MODEL = GEMINI_FALLBACK_MODEL
GEMINI_2_5_FLASH_LITE_MODEL = GEMINI_FREE_MODEL
GEMINI_FLASH_MODEL          = GEMINI_FALLBACK_MODEL

# Anthropic models (unused in free-tier mode — kept for reference)
CLAUDE_HAIKU_MODEL  = "claude-haiku-4-5-20251001"
CLAUDE_SONNET_MODEL = "claude-sonnet-4-6"
CLAUDE_OPUS_MODEL   = "claude-opus-4-6"

# ---------------------------------------------------------------------------
# LLM pricing — $/M tokens (used for cost logging in all agent files)
# ---------------------------------------------------------------------------
GEMINI_COST_IN  = 0.0     # gemini-3.1-flash-lite-preview — free during preview
GEMINI_COST_OUT = 0.0     # gemini-3.1-flash-lite-preview — free during preview
GEMINI_FLASH_COST_IN  = 0.0   # gemini-3.1-flash-lite-preview — free during preview
GEMINI_FLASH_COST_OUT = 0.0   # gemini-3.1-flash-lite-preview — free during preview



