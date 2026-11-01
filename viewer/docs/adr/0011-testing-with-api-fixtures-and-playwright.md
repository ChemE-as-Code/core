# 0011. Tests on real API fixtures: vitest units and Playwright with a mocked API

- **Status:** Accepted
- **Date:** 2026-10-17 (fixtures from core 2026-10-21)

## Context

The viewer is only as correct as its reading of core's API. Running a `cheme serve` in CI would
need core, pyDEXPI and a plant repository. Hand-written fixtures drift from what the
server really sends.

## Decision

- Unit tests (vitest + jsdom) cover the pure modules: API client URL building, sanitizer,
  highlight CSS, YAML tables, Markdown, `useAsync`, scene and model logic.
- Browser tests (Playwright, Chromium) run against the built `dist/` served by `vite preview`;
  every `/api` request is answered in the browser from `e2e/fixtures.ts` by route
  interception, so no server is needed. A test that would reach a real server is a bug.
- Fixtures are real responses: `scripts/regen-fixtures.py` runs core's FastAPI app with
  `TestClient` on copies of real plants (the ASU from process-library) and writes them.
  `tests/apiContract.test.ts` fails when a real response has a field the types do not know.
- CI runs unit tests, type check and build on Node 22.22.2 and 24, and the e2e job on Node 24.

## Consequences

- CI needs no secrets and no core checkout.
- Fixtures must be regenerated when core's API changes; that is manual and needs a core
  environment (`uv run --project ../core --extra serve`).
- GPU-dependent checks (frame rate) are reported, not enforced, on CI.

## Evidence

- "Playwright (1.63.0, Chromium) against dist/ ... with /api
  answered from fixtures by route interception"; CI.
- "Regenerate the API fixtures from plantcode and type every
  field it sends".
- "route.fetch reached a real server: none on CI".
- `.github/workflows/ci.yml`, `playwright.config.ts`.
