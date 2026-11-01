# 0006. YAML lists as tables driven by their JSON Schema

- **Status:** Accepted
- **Date:** 2026-10-17

## Context

Equipment, line, instrument and check lists are YAML files validated by JSON Schemas in core.
New list kinds and new fields appear with core releases. Hand-written table components per list
would lag behind the schemas and duplicate their field definitions.

## Decision

`/yaml/<path>` shows a list as a table whose columns come from the JSON Schema the API sends
with the file (`src/lib/yamlTable.ts`: local `$ref` resolution, type summaries, item schemas
of array properties). Keys rows have but the schema does not list are still shown and marked.
Any other YAML is shown as a tree; the source view is highlighted by a small tokenizer that
yields text tokens only.

## Consequences

- A new list kind or field in core shows up in the viewer without viewer changes.
- Column order and labels are only as good as the schema; domain-specific presentation
  (datasheets, streams, cause & effect) still gets its own page.
- The viewer depends on the API sending the schema with the YAML.

## Evidence

- "YAML lists with schema-aware tables".
- `src/lib/yamlTable.ts`, `tests/yamlTable.test.ts`.
