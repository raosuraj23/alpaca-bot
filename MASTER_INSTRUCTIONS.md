# Master Project Instructions: Quant-Driven Trading Bot

## 1. Core Philosophy: Think Like a Quant
Every line of code and architectural decision must be rooted in quantitative rigor. Do not rely on intuition; rely on statistical significance.
* **Hypothesis-Driven:** Every trading strategy must start with a testable mathematical hypothesis.
* **Risk First:** Prioritize risk management over pure alpha. Implement strict constraints for Maximum Drawdown, Value at Risk (VaR), and position sizing (e.g., Kelly Criterion).
* **Rigorous Backtesting:** Model slippage, exchange fees, and latency. Ensure strictly separated in-sample and out-of-sample datasets to prevent overfitting.
* **Fail-Safes:** Implement automated kill-switches if the bot exceeds daily loss limits or detects anomalous API behavior.

## 2. Security Architecture
Security is paramount. Trading bots handle live capital; treat the infrastructure as a zero-trust environment.
* **No Hardcoding:** Never hardcode API keys, secret tokens, or wallet seeds. 
* **Environment Variables:** Use strictly scoped `.env` files or a secure vault (like AWS Secrets Manager or HashiCorp Vault) for all credentials.
* **IP Whitelisting:** Restrict API key execution to the specific IP addresses of your hosting environment.
* **Least Privilege:** Generate API keys with the absolute minimum permissions required (e.g., enable "Trade" and "Read", but strictly disable "Withdrawal").

## 3. Claude Code Best Practices & Plugin Integration
Leverage Claude's ecosystem efficiently, ensuring the code remains modular, tested, and strictly typed.
* **Awesome Claude Plugins:** You must actively query, integrate, and utilize relevant skills and libraries from `https://github.com/quemsah/awesome-claude-plugins`. Check this repository for market data fetchers, technical analysis tools, and backtesting integrations before writing custom boilerplates.
* **Modular Design:** Separate the codebase into distinct micro-services or modules: Data Ingestion, Alpha Generation (Strategy), Risk Management, and Execution.
* **Type Safety:** Use strict typing (e.g., TypeScript or Python with Pydantic/Type Hints) to ensure the LLM generates predictable, robust data structures.

## 4. Playwright Integration & Account Parameterization
When interacting with web interfaces (for scraping alternative data, managing exchange dashboards, or executing trades where APIs are limited), Playwright is the standard.
* **Parameterization:** All Playwright scripts must be fully parameterized. Use variables for `account_id`, `environment` (paper vs. live), and `proxy_url` to allow seamless switching between different trading accounts without rewriting logic.
* **Automated Code Review & Testing:** Use Playwright to build robust End-to-End (E2E) tests that simulate trading scenarios. Create automated code-review pipelines that test bot behavior against mock exchange interfaces.
* **Session Management:** Handle authentication state securely. Save and load session states (cookies/local storage) programmatically to avoid repeated logins and potential rate-limiting, tying each state file to its specific parameterized `account_id`.

## 5. Token Mindfulness & Cost Efficiency
LLM API calls can become expensive. Optimize how Claude is used in the trading loop.
* **Data Summarization:** Do not feed raw, tick-by-tick order book data into the LLM. Pre-process and aggregate data (e.g., standard OHLCV candles, computed technical indicators, or statistical summaries) via standard code before sending it to Claude for analysis.
* **Tiered Model Usage:** Use smaller, faster models for basic tasks (data routing, formatting, simple sentiment classification) and reserve heavier models (like Claude 3.5 Sonnet or Opus) exclusively for complex strategy formulation, code generation, or deep market analysis.
* **Context Management:** Prune conversation history aggressively. Only retain the minimum necessary context for the current analytical task to save on input tokens. Use strict JSON schemas for outputs to minimize output token bloat.
