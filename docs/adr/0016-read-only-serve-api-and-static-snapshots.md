# 0016. A read-only `cheme serve` API and static snapshots for the viewer

- **Status:** Accepted
- **Date:** 2026-10-17 (`serve`); static snapshots on 2026-10-23

## Context

The browser viewer (a separate ChemE-as-Code repository) shows sheets, diffs, streams, layout and
assessments. A server that writes could become a second editing path next to the files
([0002](0002-plant-data-as-plain-files-in-git.md), [0007](0007-agents-edit-files-directly-no-mcp-server.md))
and is a security risk on a developer's machine. Some uses (reviews, the Process Atlas) need no
server at all.

## Decision

- `cheme serve` (`interfaces/api/serve.py`, extra `serve`) is a read-only JSON API on
  localhost: it never writes to the plant repository. Endpoints reuse the command modules, take
  paths through `clean_path`/`Snapshot` and revisions through `Repo.resolve`, and run git with
  argument lists only. A session token header guards it. fastapi and uvicorn are imported nowhere
  else.
- `cheme export-static DIR` writes what the viewer requests for one revision as plain files
  (`cheme/viewer-snapshot/v1` manifest), so the viewer can run from static hosting.
- The serve API is a contract with the viewer; its reference page is generated from the OpenAPI
  document on every docs build.

## Consequences

- Positive: the viewer cannot corrupt a plant; one implementation per query shared by CLI and API.
- Positive: snapshots can be attached to a review or embedded without running Python.
- Negative: no editing in the browser; changes go through files and git.
- Negative: API changes must stay compatible with the viewer repository (a cross-repo contract,
  see the ADR rule in [0001](0001-record-architecture-decisions.md)).

## Evidence

- `cheme serve` and its hardening; static snapshots, then `--exclude`.
- `AGENTS.md`, `src/chemeascode/interfaces/api/serve.py`,
  [static-snapshot.md](../framework/static-snapshot.md).
