# Data sources and static snapshots

The viewer reads its data from one of two sources, with the same views and types in both:

- **A server**, `cheme serve` from the cheme-as-code package (the default). Every request goes
  through `src/api.ts`; an absent `rev` means the working tree.
- **A static snapshot**, the files `cheme export-static` writes for one revision, opened with
  `?data=<snapshot directory>` (`src/dataSource.ts`). No server is needed.

<!-- readme: ## Serve -->

<!-- readme: ## Static snapshot (no server) | without: ### Embedding -->

### The snapshot contract

`src/dataSource.ts` checks the manifest's `schema` (`cheme/viewer-snapshot/v1`) and answers each
request from the file the manifest names for its key: the endpoint without `/api/` (its path
decoded, as core records it raw: `datasheets/E 101`, not `datasheets/E%20101`), then `?` and the
query as `key=value` pairs sorted by key and joined with `&`, leaving out empty values and
`rev`. The manifest's `entries` map each key to `{file, status, type}`, and the file is read
from `data/<file>`. The key must match core's `snapshot_key`; core documents the contract in
`docs/framework/static-snapshot.md`.

To show a snapshot in a frame of another page, see [Embedding](embedding.md).
