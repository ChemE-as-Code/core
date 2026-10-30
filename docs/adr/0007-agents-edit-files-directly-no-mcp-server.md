# 0007. Agents edit files directly; the CLI, not an MCP server, is the tool interface

- **Status:** Accepted
- **Date:** 2026-10-17 (confirmed for the authoring API in 0.4, 2026-10-18)

## Context

Agents could manipulate a plant through an edit-operation API or an MCP server (pyDEXPI has an
editor layer, patches and a private MCP server), or they could edit the files themselves and
call a validator. The research question behind the project is how far direct file editing with
strong validation goes. An operation API would also create a second source of state next to the
files.

## Decision

- Agents (and people) change a plant by editing its files and run `cheme` commands to validate,
  format, render, diff and generate. There is deliberately no MCP server and no edit-operation API.
- cheme-as-code does not use or expose pyDEXPI's editor commands (`pydexpi.editor`), its patches
  or its MCP server, and does not import DigiCo code (`pi_schemas`, `pydexpi_pro`, `digico_*`)
  or dexpi-js.
- Helpers stay stateless text tools: `copy`, `fragment`, `move`, `rename`, `set` and the
  generator-script library `domains.piping.authoring` write XML into the file, format it, and the
  result is validated like any hand edit.
- `interfaces/mcp/` holds only a README stating the boundary of a possible future adapter:
  optional extra, curated read-mostly tools calling the same functions as the CLI, never
  pyDEXPI's MCP server or editor.

## Consequences

- Positive: one state (the files), one diff, one review path; any coding agent that can edit
  text and run a shell works.
- Positive: the experiment stays clean: results measure file editing plus validation.
- Negative: agents must learn the XML (skills and snippets carry that cost); structured edits
  that an API could guarantee are checked after the fact by `validate`.
- Negative: hosts that only speak MCP cannot use the tools without an adapter.

## Evidence

- pre-release commit 62c29e1: the pyDEXPI editor/MCP ban is in `AGENTS.md` from 0.1.0.
- Authoring API "decided in 0.4, pre-release issue 13": pre-release commit 2ff49ad in pre-release PR 34.
- MCP boundary README: pre-release PR 58.
- `AGENTS.md`, `REFERENCE.md` (end of "Skills": "deliberately no MCP server"),
  `src/chemeascode/interfaces/mcp/README.md`, [architecture.md](../framework/architecture.md)
  ("MCP boundary").
