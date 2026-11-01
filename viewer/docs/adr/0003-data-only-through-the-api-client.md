# 0003. Data only through the `cheme serve` API, behind one typed client

- **Status:** Accepted
- **Date:** 2026-10-17

## Context

The viewer needs the file tree, file contents, git history, rendered drawings and the results
of core's commands (validation, streams, LCA, layout, ...). Re-implementing any of that in
TypeScript would duplicate core's logic and drift from it. Core already owns these
computations and can expose them as a JSON API (`cheme serve`, FastAPI).

## Decision

The viewer gets all its data from the `cheme serve` HTTP API (or from a static snapshot of the
same answers, ADR 0004). `src/api.ts` is the only code that talks to the server; it is typed
against the API contract of `cheme serve`, and an absent `rev` means the working tree. The dev
server proxies `/api` to the API (`CHEME_API`); in production `cheme serve --ui dist` serves
the build and the API from one origin. The viewer computes presentation only (tables, scenes,
charts), not engineering results.

## Consequences

- One transport to swap (the static snapshot source plugs in behind `api`), one place to
  type and test.
- Every new view needs a core endpoint first; viewer features follow core releases
  (many commits are "Follow core's ... contract").
- Types can drift from the server: guarded by `tests/apiContract.test.ts`, which fails when a
  real response has a field the types do not know (ADR 0011).

## Evidence

- "coded against the plantcode serve JSON API
  contract", "Typed API client, Vite dev proxy".
- Every field the API sends is typed; contract test.
- REFERENCE.md (formerly the README), "Design notes": "`src/api.ts` is the only code that talks to the server."
