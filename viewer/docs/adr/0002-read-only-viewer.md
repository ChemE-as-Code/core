# 0002. The viewer is read-only

- **Status:** Accepted
- **Date:** 2026-10-17

## Context

In ChemE-as-Code the plant is a git repository of text files (DEXPI P&IDs, YAML lists,
Markdown). People and agents change it by editing those files, and the engineering record is the
git history with its reviews and sign-offs. A viewer that also edits would need its own
write path, conflict handling, authentication and audit trail, and would compete with the files
as the place where the design is changed.

## Decision

The viewer only shows a plant repository: files, drawings, lists, history, diffs, checks and
reports. Editing stays with people and agents working on the files. The only action that runs
anything on the server is "Run now" on the checks page, which evaluates the checks on the
working tree without writing `checks/status.json`, and it needs the server's per-launch token
(`POST /api/checks/run` with the token from `/api/session`). Issues are created through
GitHub's own issue forms (the "New ..." links on the issues page), not by the viewer.

## Consequences

- No write API, no locking, no merge UI; the viewer cannot corrupt a plant.
- It fits the static snapshot (ADR 0004) and the Atlas embedding (ADR 0008) with no change.
- Users who want to fix what they see must switch to an editor or an agent; the viewer links
  to the file and line (validation findings open the file at the line) to make that short.

## Evidence

- "Milestone 2 scope": "Read-only. Editing stays with people and agents working on
  the files."
- "Read-only viewer over a plant repository".
- Token POST for check runs; README, routes `/checks` and `/issues`.
