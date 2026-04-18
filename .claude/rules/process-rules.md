# rules/process-rules.md — Development Process Rules
# These rules govern data architecture, testing, and task completion workflow.

---

## 6. Canonical Type Definitions

All TypeScript interfaces for market data, trades, positions, agents, and API responses live in `src/lib/types.ts`. Import from there — do not redefine types locally.

---

## 7. Mock Data Isolation

All mock data constants (`INITIAL_WATCHLIST`, `MOCK_BOTS`, `MOCK_POSITIONS`, etc.) live in `src/lib/mock-data.ts`. Each export is annotated with a `// MOCK — replace when Phase N complete` comment. Never bury mock data in store or component files.

---

## 13. Playwright Tests Are Mandatory

Run `npx playwright test` after every code change before reporting the task complete. If tests fail, fix the failures before finishing — do not skip or suppress them. If no test exists for the changed feature, write one first, then run the full suite.

---

## 14. Phase Completion Logging Is Mandatory

After every successfully completed phase or sub-phase task, update the Phase Completion Status Log in `.claude/memory-preferences.md` (Section 6) with the date, phase name, items shipped, and any follow-on notes. Do this before reporting the task as done to the user.
