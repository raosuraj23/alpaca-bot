# rules/security-and-risk.md — Security & Quantitative Risk Guardrails
# These rules are MANDATORY. No code may be merged that violates them.

---

## Part 1: Security Rules

### 1.1 Secrets & Credentials

RULE: No API key, secret, token, wallet seed, or password may appear in any
Python source file, Jupyter notebook, test file, log file, or commit.

- All credentials are loaded exclusively via pydantic-settings from environment
  variables. The canonical config object is `backend/config.py`.
- Locally: variables are stored in `.env` (gitignored). `.env.example` with
  placeholder values IS committed.
- In cloud: variables are loaded from AWS Secrets Manager or GCP Secret Manager.
  The deployment script `scripts/cloud_deploy.sh` must never inline credentials.

Required environment variables (all must be present at startup or the app exits):
ALPACA_API_KEY_ID=
ALPACA_API_SECRET_KEY=
ALPACA_BASE_URL=https://paper-api.alpaca.markets   ← default is paper
PAPER_TRADING=true                                  ← explicit flag
ANTHROPIC_API_KEY=
DATABASE_URL=sqlite:///./trading_bot.db             ← local default
PLAYWRIGHT_HEADLESS=false                           ← true in cloud
LOG_LEVEL=INFO

Config validation at startup:
```python
from pydantic_settings import BaseSettings, SettingsConfigDict

class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8")

    alpaca_api_key_id: str
    alpaca_api_secret_key: str
    alpaca_base_url: str = "https://paper-api.alpaca.markets"
    paper_trading: bool = True
    anthropic_api_key: str
    database_url: str = "sqlite:///./trading_bot.db"
    playwright_headless: bool = False
    log_level: str = "INFO"

settings = Settings()  # Fails loudly at import if any required var is missing
```

### 1.2 Alpaca API Key Permissions

Keys must be generated with ONLY these permissions:
- ✅ Trade (place, modify, cancel orders)
- ✅ Read (account, positions, market data)
- ❌ Transfer — NEVER enable
- ❌ Withdrawal — NEVER enable

Claude must never generate code that calls Alpaca's bank/transfer endpoints.

### 1.3 Least-Privilege API Usage

- Playwright sessions must be scoped to specific, parameterized targets.
  Never grant a session access to cookie storage it does not need.
- Session state files are named `sessions/{account_id}.json` and are gitignored.
- LLM API calls must use scoped system prompts. Never inject user-controlled
  strings directly into a system prompt without sanitization.

### 1.4 Logging Hygiene

- NEVER log API keys, secrets, or PII.
- Use structured logging (Python's `structlog` or `logging` with JSON formatter).
- Log all trade intents, risk check results, and kill switch events.
- Mask order amounts in DEBUG-level logs if they could identify position size.

---

## Part 2: Quantitative Kill-Switches

These are non-negotiable, hard-coded thresholds. They exist in `risk/kill_switch.py`
and MUST wrap every call to `execution/router.py`.

### 2.1 Max Daily Drawdown (absolute halt)

```python
MAX_DAILY_DRAWDOWN_PCT: float = 0.02   # 2% of starting day equity = HALT
```

Behavior: If `(start_of_day_equity - current_equity) / start_of_day_equity >= 0.02`,
the kill switch fires. All open orders are cancelled. No new orders are placed for
the remainder of the trading day. An alert is logged.

This value may be changed via env var `MAX_DAILY_DRAWDOWN_PCT` but the code must
read it from config, not be hardcoded to a different value.

### 2.2 Max Single Position Size

```python
MAX_POSITION_PCT: float = 0.10         # No single position > 10% of portfolio
MAX_POSITION_NOTIONAL: float = 50_000  # Hard cap in USD regardless of portfolio size
```

### 2.3 Kelly Criterion Position Sizing (required for all equity strategies)

```python
def kelly_fraction(win_rate: float, win_loss_ratio: float) -> float:
    """
    Full Kelly: f* = W - (1-W)/R
    where W = win rate, R = win/loss ratio.
    Use HALF-KELLY (f*/2) for live trading to reduce variance.
    """
    if win_loss_ratio <= 0 or not 0 < win_rate < 1:
        raise ValueError("Invalid Kelly inputs")
    full_kelly = win_rate - (1 - win_rate) / win_loss_ratio
    return max(0.0, full_kelly / 2)  # Half-Kelly, floored at zero
```

### 2.4 Value at Risk (VaR) Gate

```python
MAX_PORTFOLIO_VAR_PCT: float = 0.01    # 1-day 95% VaR must not exceed 1% of NAV
```

VaR is computed via historical simulation (250-day rolling window) in
`risk/exposure.py` before any new position is opened.

### 2.5 Maximum Open Positions

```python
MAX_CONCURRENT_POSITIONS: int = 10     # Total equity + options legs combined
```

### 2.6 Anomalous API Behavior Detector

If any of the following occur, trading is suspended and an alert is raised:
- Alpaca API returns HTTP 5xx more than 3 times in 60 seconds.
- Order fill price deviates from mid-quote by more than 3 standard deviations.
- Account equity changes by more than 5% in under 60 seconds (flash crash guard).

### 2.7 Options-Specific Constraints

```python
MAX_NET_DELTA: float = 0.30            # Net portfolio delta as fraction of NAV
MAX_GAMMA_EXPOSURE: float = 0.05       # Gamma exposure as fraction of NAV
MIN_DAYS_TO_EXPIRY: int = 5            # Never hold options within 5 days of expiry
```

---

## Part 3: Code Review Mandates

Before any execution or risk module is merged:
1. Every risk parameter must be sourced from `config.py`, never hardcoded.
2. Every order entry point must pass through `kill_switch.check()` first.
3. The paper/live gate must be present and tested.
4. No strategy may be promoted to paper without a logged backtest entry in
   `memory-preferences.md` section 3.