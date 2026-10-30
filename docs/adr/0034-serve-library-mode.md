# 0034. `cheme serve` serves a folder of plants, each under its own prefix

- **Status:** Accepted
- **Date:** 2026-10-30

## Context

The viewer is used locally on several plants: a process library (`processes/*/plant.yaml` in one
repository) or a folder of plant repositories. `cheme serve` served exactly one plant: at the
library root it failed (no `plant.yaml` above), and looking at another process meant restarting
the server (core#66). Every endpoint closes over one `Repo` in `create_app` (about 2,000 lines),
with per-plant caches and a per-launch session token for running the checks.

Options considered:

1. A `?plant=` parameter on every endpoint: every handler, cache key and the viewer's every call
   change; the caches of all plants mix.
2. One server per plant on its own port, behind a proxy the user starts: no change to core, but
   no index and no switching from the viewer.
3. One ASGI app that dispatches `/p/<id>/...` to the plant's own, unchanged `create_app`.

## Decision

cheme-as-code takes option 3. `cheme serve` on a folder with no `plant.yaml` above it but plants
below it (at most 3 levels, skipping hidden folders and `node_modules`, `build`, `dist`, `site`,
`venv`), or with `--library`, serves:

- `GET /api/plants`: the plants from their working trees (id, path, name, stage, sheets, the
  recorded maturity of `checks/maturity.json`, and the optional `title`, `summary` and `families`
  of a `process.yaml`). Nothing is evaluated live; the viewer does not depend on the
  `process.yaml` fields (it is a tool for local work, not the Process Atlas).
- `/p/<id>/...`: the plant's `create_app`, created on first use and kept, with the path below the
  prefix. The prefix is not put into `root_path` (Starlette builds `request.url` from it, and the
  plant app's cross-site guard tests `request.url.path`).
- The viewer at `/` and at every `/p/<id>/` page.

A plant id is the folder name (the relative path when two plants share one) and is only looked up
among the discovered plants. Inside a plant, `cheme serve` behaves as before.

The viewer reads its plant from the URL (`/p/<id>/`: the API base and the router base), shows an
index of the plants at `/` of a library, and switches plants with a page load, which resets every
per-plant state at once.

## Consequences

- Positive: no endpoint changes; per-plant caches and session tokens stay per plant; single-plant
  servers and their URLs are unchanged; the viewer works against both (a 404 for `/api/plants`
  means one plant).
- Negative: each opened plant keeps its app and caches in memory for the life of the server (a
  plant's caches are bounded LRUs); a plant added to the folder needs a restart.
- Static snapshots stay one per plant. A snapshot opened from the Process Atlas gets a link back
  (`?back=`); no plant switcher in snapshots.

## Evidence

- `src/chemeascode/interfaces/api/library.py`, `cheme serve` in `src/chemeascode/interfaces/cli/`.
- `tests/test_serve_library.py`.
- The viewer: `viewer/src/lib/plants.ts`, `viewer/src/PlantsApp.vue`, `viewer/e2e/library.spec.ts`.
