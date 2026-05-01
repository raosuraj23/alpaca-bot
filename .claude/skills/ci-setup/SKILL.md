---
name: ci-setup
description: Generate a GitHub Actions CI pipeline for this Next.js + FastAPI + Playwright project. Creates .github/workflows/ci.yml.
disable-model-invocation: true
---

Generate `.github/workflows/ci.yml` for this project. The pipeline must:

**Trigger conditions:**
- Push to `main` branch
- All pull requests targeting `main`

**Jobs to include:**

### Job 1: `frontend`
- Runner: `ubuntu-latest`
- Steps:
  1. `actions/checkout@v4`
  2. `actions/setup-node@v4` with Node 20, cache `npm`
  3. `npm ci` in project root
  4. `npx tsc --noEmit` — TypeScript type check
  5. `npx eslint src/` — ESLint lint check
  6. Upload any lint output as artifact on failure

### Job 2: `playwright`
- Runner: `ubuntu-latest`
- Depends on `frontend` job passing
- Steps:
  1. `actions/checkout@v4`
  2. `actions/setup-node@v4` with Node 20, cache `npm`
  3. `npm ci`
  4. `npx playwright install --with-deps chromium`
  5. Start backend: `pip install -r requirements.txt && uvicorn backend.main:app &`
  6. `npx playwright test` with env vars: `ALPACA_API_KEY_ID`, `ALPACA_API_SECRET_KEY`, `ANTHROPIC_API_KEY` from GitHub secrets
  7. `actions/upload-artifact@v4` — upload `test-results/` and `playwright-report/` on failure

### Job 3: `backend`
- Runner: `ubuntu-latest`
- Steps:
  1. `actions/checkout@v4`
  2. `actions/setup-python@v5` — ask user for Python version (default 3.11)
  3. `pip install -r requirements.txt`
  4. `python -m py_compile backend/main.py backend/config.py` — import validation
  5. Validate `.env.example` has all required keys

**GitHub Secrets required** (tell the user to add these in repo Settings → Secrets):
- `ALPACA_API_KEY_ID`
- `ALPACA_API_SECRET_KEY`
- `ALPACA_BASE_URL` (default: `https://paper-api.alpaca.markets`)
- `ANTHROPIC_API_KEY`
- `DATABASE_URL` (default: `sqlite:///./trading_bot.db`)

Before generating the file, ask the user:
1. What Python version are they using? (check pyproject.toml or .python-version)
2. Do they want test artifacts (playwright-report/) uploaded to GitHub on failure?

Then write the complete YAML to `.github/workflows/ci.yml`.
