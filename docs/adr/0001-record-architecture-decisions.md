# 0001. Record architecture decisions

- **Status:** Accepted
- **Date:** 2026-10-25

## Context

cheme-as-code grew from `plantcode` 0.1.0 (2026-10-17) to 0.8.0 in about a week, with several
agent sessions and humans contributing in parallel. The reasons for its main choices (plain
files, DEXPI XML, no MCP server, the layer rules, no compatibility aliases, ...) were spread over
the README, `docs/framework/*.md`, the CHANGELOG, `AGENTS.md`, test comments and pull request
descriptions. A new contributor, or an agent, had no single place to learn which choices are
deliberate and must not be "fixed" in passing, and which are open.

## Decision

We record architecturally significant decisions about this software as Architecture Decision
Records (ADRs) in `docs/adr/`, in the lightweight format of Michael Nygard
(Title, Status, Context, Decision, Consequences), with an added Evidence section that links the
commit or pull request and the files that implement or enforce the decision.

- One decision per file, `NNNN-kebab-title.md`, numbered in order, never renumbered.
- An accepted ADR is not rewritten. A changed decision gets a new ADR that supersedes the old
  one; the old one's status becomes "Superseded by NNNN".
- A pull request that changes the architecture, a public file format or schema, the agent
  interface (CLI, findings, skills) or a contract with another ChemE-as-Code repository adds or
  supersedes an ADR in the same pull request (rule in `AGENTS.md` and
  [contributing.md](../framework/contributing.md)).
- ADRs 0002 onwards were written retroactively on 2026-10-25 from the repository's history. Their
  date is the date the decision was taken according to git, not the date the record was written.

ADRs are about the software. A plant's engineering decisions live in that plant repository's
`DESIGN.md` (`D-NNN` entries), not here.

## Consequences

- Positive: the reasons behind the rules are in one indexed place, next to the code, versioned
  with it and reviewed in the same pull requests.
- Positive: retroactive records make implicit decisions explicit, including their known
  limitations.
- Negative: one more document to keep current; a stale ADR misleads. The supersede rule and the
  pull request rule are the mitigation.
- Limitation: the retroactive records summarise sources that remain authoritative for details
  (architecture.md, contract.md, maturity.md, the README). Where they disagree, the code and
  those documents win and the ADR should be superseded.

## Evidence

- This pull request: `docs/adr/`, `AGENTS.md`, `docs/framework/contributing.md`, `mkdocs.yml`.
- Michael Nygard, "Documenting Architecture Decisions" (2011).
