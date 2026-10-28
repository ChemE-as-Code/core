# 0002. Plant data as plain files in git, the single source of truth

- **Status:** Accepted
- **Date:** 2026-10-17

## Context

Process plant design data usually lives in proprietary CAD databases and spreadsheets, which
neither engineers' review practice nor coding agents can diff, branch or merge. Coding agents are
good at editing text files under git. The project's premise is to treat a plant like code.

## Decision

A plant is a git repository of plain text files: DEXPI XML P&IDs, engineering lists and process
data in YAML, decisions and reviews in Markdown, gates and sign-offs in `checks/`. These files are
the only state. cheme-as-code is a tool that reads, checks, formats, renders and generates those
files; it keeps no database, no server-side state and no hidden cache that is authoritative.
History, review and approval use git (commits, branches, pull requests). The plant repository
holds data, not tools: every check runs the installed `cheme`.

## Consequences

- Positive: every change is a reviewable diff with an author and a commit; branches allow
  alternatives; CI can run the same checks as a developer.
- Positive: agents need no special API, only file editing and the CLI (see
  [0007](0007-agents-edit-files-directly-no-mcp-server.md)).
- Negative: concurrent edits of the same file conflict like code; large binary or generated
  artifacts (renders, simulation results) need policies (generated files carry fingerprints,
  [0011](0011-per-value-provenance-and-fingerprints.md)).
- Negative: text formats must be kept diff-friendly by tooling
  ([0003](0003-dexpi-xml-via-pydexpi-as-the-pid-format.md)).
- Limitation: collaborative real-time editing, authentication and transactions are left to
  downstream applications that work on snapshots (architecture.md, "Use from downstream
  applications").

## Evidence

- pre-release commit 62c29e1 "plantcode 0.1.0: validate, fmt, render, diff, check for git
  plant repositories" (2026-10-17).
- `README.md` (opening paragraph, "How the pieces fit together"),
  `src/chemeascode/foundation/workspace.py` (`Workspace`: the file kinds of a plant repository),
  `src/chemeascode/templates/project/`.
