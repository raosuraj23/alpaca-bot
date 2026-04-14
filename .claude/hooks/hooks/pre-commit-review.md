# hooks/pre-commit-review.md — Pre-Commit Code Review Checklist
# Claude must run through this checklist before finalizing any execution,
# routing, or risk module code. This simulates a mandatory peer review gate.
# A "FAIL" on any item BLOCKS the code from being committed.

---

## How to Use This Checklist

Before presenting finalized code for any of the following modules:
  - `execution/router.py`
  - `execution/paper_gate.py`
  - `risk/kill_switch.py`
  - `risk/position_sizer.py`
  - `ingestion/playwright_scraper.py`
  - Any new file in `alpha/`

Claude must explicitly state the checklist result for each item. Format:
  ✅ PASS — [brief note]
  ❌ FAIL — [what is wrong and what must be fixed before proceeding]

---

## Section A: Security Checks

### A1 — No Hardcoded Secrets
Scan all modified files for any string literal that resembles:
  - An API key (long alphanumeric string, ~40+ chars)
  - "sk-", "AKIA", "Bearer", or similar prefixes
  - Wallet addresses or seed phrases
  - Passwords or tokens in connection strings

PASS condition: Zero occurrences found.

### A2 — Config Source Verification
Any value sourced from `config.py` / `settings` must use the
`pydantic-settings` `Settings` object, not `os.getenv()` directly.

PASS condition: All env var accesses go through `from src.config import settings`.

### A3 — Log Sanitization
Check that no logging call (DEBUG, INFO, WARNING, ERROR) outputs:
  - API keys or secrets
  - Account numbers or equity values in a format that reveals position size
  - Raw Pydantic model dumps that may contain sensitive fields

PASS condition: All log calls use sanitized, field-specific messages.

---

## Section B: Risk Module Integration

### B1 — Kill Switch Wrapping
Every function that submits an order to Alpaca must call
`kill_switch.check()` BEFORE calling `alpaca_client.submit_order()`.

PASS condition: The call graph from any order creation to `router.py`
shows `kill_switch.check()` as a mandatory intermediate step.
No bypass paths exist (including exception handlers that re-try without re-checking).

### B2 — Position Size Compliance
Every new position must pass through `position_sizer.calculate()`.
The output must be validated against:
  - `MAX_POSITION_PCT` (10% of portfolio)
  - `MAX_POSITION_NOTIONAL` ($50,000)
  - Kelly fraction > 0 (negative Kelly = no trade)

PASS condition: No OrderRequest is constructed without a call to the position
sizer, and the size field is set to the sizer's output, not a user-supplied value.

### B3 — VaR Gate Presence
Before opening a new position, `risk/exposure.py` must be queried
to confirm the post-trade portfolio VaR stays within `MAX_PORTFOLIO_VAR_PCT`.

PASS condition: A VaR check call exists before any new position is opened.

### B4 — Paper/Live Gate
The paper/live gate in `paper_gate.py` must be called before any
order is submitted. Live trading requires:
  1. `settings.paper_trading == False`
  2. CLI flag `--live` is present in `sys.argv`
  3. A console confirmation prompt displaying the account ID

PASS condition: All three conditions are enforced in code, not just one.
Verify the confirmation prompt cannot be bypassed by piping input.

---

## Section C: Playwright Parameterization

### C1 — No Hardcoded URLs or Account Identifiers
Playwright scripts must accept `account_id`, `target_url`, and `proxy_url`
as parameters. No URL, username, or account ID may be a string literal
in the function body.

PASS condition: Function signature includes `account_id: str, target_url: str`
and all references to these values use the parameter, not a literal.

### C2 — Headless Mode Compatibility
All Playwright browser launches must use:
```python
browser = await playwright.chromium.launch(
    headless=settings.playwright_headless,
    ...
)
```
PASS condition: `headless=True` is NEVER hardcoded; it must read from `settings`.

### C3 — Session State Scoped to account_id
Session storage files must follow the naming pattern:
  `sessions/{account_id}.json`
and must be gitignored.

PASS condition: No session file is saved with a static name or in a non-gitignored
path.

### C4 — Rate Limiting and Robots Compliance
Playwright scripts must:
  1. Include a configurable delay between requests (default ≥ 1 second).
  2. Not scrape sources explicitly prohibited by their `robots.txt`.

PASS condition: A `request_delay_seconds: float = 1.0` parameter exists.

---

## Section D: Type Safety

### D1 — No Untyped Function Signatures
Every function and method must have fully annotated parameters and return type.
`-> None` is a valid return annotation; missing annotation is not.

PASS condition: Running `mypy src/` (or `pyright src/`) reports zero missing
annotation errors on modified files.

### D2 — No Raw Dict Usage for External Data
Any data received from Alpaca, an LLM, or a Playwright page must be
immediately parsed into a Pydantic model. No `dict` type annotations
for module-boundary values.

PASS condition: All function parameters and return values that represent external
data are typed as Pydantic models, not `dict`.

### D3 — Pydantic LLM Output Validation
Every LLM API call must parse its response through a Pydantic model before the result is used. Bare string responses must not flow into strategy logic.

PASS condition: `Model.model_validate_json(response.content[0].text)` or
equivalent is called before any LLM output is acted upon.

---

## Section E: Test Coverage

### E1 — Unit Test Exists
Every new function in `execution/`, `risk/`, and `alpha/` must have at least one unit test in `tests/unit/`.

PASS condition: A corresponding test file exists and `pytest tests/unit/` passes.

### E2 — Kill Switch Unit Test
`risk/kill_switch.py` must have tests covering:
  - Normal operation (no halt)
  - Halt triggered at exactly the threshold
  - Halt triggered above the threshold
  - Halt resets correctly at start of new trading day

PASS condition: All four cases exist as separate test functions.

### E3 — Paper Gate Cannot Be Bypassed
The test for `paper_gate.py` must demonstrate that calling the order submission path without `--live` flag and `paper_trading=False` raises an exception or returns early without submitting an order.

PASS condition: This test exists and passes.

---

## Final Sign-Off

Claude must output this block with all items resolved before presenting finalized code to the user:
PRE-COMMIT REVIEW RESULT
Security:      A1 ✅  A2 ✅  A3 ✅
Risk Modules:  B1 ✅  B2 ✅  B3 ✅  B4 ✅
Playwright:    C1 ✅  C2 ✅  C3 ✅  C4 ✅
Type Safety:   D1 ✅  D2 ✅  D3 ✅
Tests:         E1 ✅  E2 ✅  E3 ✅
VERDICT: ✅ APPROVED — Safe to present to user.
❌ BLOCKED  — [List failing items and required fixes]

If any item is ❌, Claude must fix the code before presenting it.
The checklist result must be shown to the user when presenting execution or risk code, so they have full visibility into what was verified.