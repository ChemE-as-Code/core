# 0005. Engineering YAML with versioned schemas, additive changes and `cheme migrate`

- **Status:** Accepted
- **Date:** 2026-10-19 (process schema v1); extended to every file kind on 2026-10-23

## Context

Lists (equipment, lines, instruments), the flowsheet, materials, datasheets, layout, LCA and
TEA inputs are not DEXPI. They need a format that agents and engineers edit easily and that a
tool can validate with line numbers. Plant repositories outlive cheme-as-code versions, so a
format change must not silently break them.

## Decision

- Non-P&ID engineering data is YAML, validated by pydantic models (`foundation.schema_base.Strict`)
  that live with their owning domain and are catalogued in `chemeascode.schemas`;
  `cheme schema NAME` prints the JSON Schema.
- Every file kind carries `schema: cheme/<kind>/vN`. A file without it reads as v1; an unknown id
  is an error naming the supported one.
- Schema changes add optional fields only, so existing repositories stay valid without edits. A
  breaking change gets a new version and a registered transform in `foundation/migrate.py`, run
  by `cheme migrate [--check | --write]`, which edits text so that comments and layout stay byte
  for byte.

## Consequences

- Positive: readable files with `file:line` findings; the schema is discoverable from the CLI.
- Positive: old repositories keep working, and the one-time upgrade is a reviewable diff.
- Negative: optional-only growth accumulates fields; every breaking change costs a transform and
  a test.
- Example of the mechanism in use: `cheme/lci_dataset/v2` with the v1 transform
  (pre-release commit 647d655, pre-release issue 179).

## Evidence

- Process schema v1: pre-release commit 17ab51f in pre-release PR 45 (0.5.0).
- Schemas moved to their owners: pre-release commit b4d191e in pre-release PR 58.
- `schema:` everywhere and `cheme migrate`: pre-release PR 125 (pre-release commit f790f2c,
  pre-release issue 113).
- `src/chemeascode/foundation/schema_base.py`, `foundation/migrate.py`,
  [contributing.md](../framework/contributing.md) ("Where things go", item 2),
  [contract.md](../framework/contract.md).
