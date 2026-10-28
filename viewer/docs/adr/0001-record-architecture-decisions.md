# 0001. Record architecture decisions

- **Status:** Accepted
- **Date:** 2026-10-25

## Context

The viewer grew quickly (milestone 2 scope on 2026-10-17, more than 60 pull requests in a week)
and its architectural choices are spread over the README's "Design notes", commit messages and
pull request descriptions. A contributor, human or agent, cannot easily tell which constraints
are deliberate (read-only, SVG only, no other data path than `src/api.ts`) and which are
accidents that may be changed.

## Decision

Architecture decisions are recorded as Architecture Decision Records (ADRs) in `docs/adr/`,
one Markdown file per decision, numbered `NNNN-kebab-title.md`, in a lightweight Nygard/MADR
format (Status, Date, Context, Decision, Consequences, Evidence; see [the template](template.md)).

The decisions taken before this record (0002 onwards) are written retroactively from the README,
the code and the git history, each with the date the history shows and the commits or pull
requests that evidence it. A pull request that changes the architecture adds a new ADR, or marks
an existing one as superseded; ADRs are not rewritten after acceptance.

## Consequences

- The deliberate constraints are written down in one place, with their reasons and costs.
- Retroactive records reconstruct reasons from the evidence available; where the history does
  not say why, the ADR says so instead of inventing a reason.
- One more file to write for architecture-changing pull requests.

## Evidence

- Michael Nygard, "Documenting Architecture Decisions" (2011); MADR.
- The same practice is adopted across the ChemE-as-Code repositories.
