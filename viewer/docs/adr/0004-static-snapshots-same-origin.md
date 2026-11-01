# 0004. Static snapshots as a second data source, same-origin only

- **Status:** Accepted
- **Date:** 2026-10-22 (same-origin rule 2026-10-25)

## Context

The Process Atlas is a static site with no backend, yet it should show each process with the
viewer's P&IDs, stream tables, layout and reports. Running `cheme serve` per process on a
public host is not an option. A query parameter that loads data from an arbitrary URL would,
however, let anyone show their own "plant" under the hosting site's name.

## Decision

`cheme export-static DIR` (core) writes the API answers of one revision as files with a
`manifest.json`. The viewer opens them with `?data=<snapshot directory>`: `src/dataSource.ts`
answers requests from the manifest (key: endpoint plus raw sorted query, no `rev`) and
`src/api.ts` switches its transport with `useSnapshot()`, so views and types are identical in
both modes. In snapshot mode the router uses hash history and `npm run build:static` builds
with relative asset paths, so one build works on any static host. A snapshot is one read-only
revision: History, Diff and "Run now" are hidden, unsupported requests answer 404/405 with a
reason, and a failed `?data=` never falls back to a server.

`?data=` must resolve to the page's own origin; other origins are allowed only when listed at
build time in `VITE_SNAPSHOT_ORIGINS`.

## Consequences

- The viewer runs with no server at all, which is what lets the Atlas embed it.
- The snapshot key contract is shared with core (`docs/framework/static-snapshot.md` there) and
  must change in both repositories together; `tests/dataSource.test.ts` checks key parity.
- Snapshots show one revision only; no diff or history in the Atlas.
- Hosting snapshots on a separate data host needs a rebuild with `VITE_SNAPSHOT_ORIGINS` and
  CORS on that host.

## Evidence

- "Static snapshot data source: the viewer without a server".
- "Open ?data= snapshots from the page's own origin only".
- REFERENCE.md (formerly the README), "Static snapshot (no server)".
