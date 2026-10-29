# 0032. Semantic versioning from 1.0.0

- **Status:** Accepted
- **Date:** 2026-10-29

## Context

cheme-as-code went from `plantcode` 0.1.0 to 0.8.0, the first public release of this repository,
in under two weeks. While pre-1.0, a breaking change needed no version signal: modules moved
without a compatibility layer ([0018](0018-rename-plantcode-to-cheme-as-code-without-aliases.md),
`docs/framework/migration-table.md`), and the process library pins core by commit. Plant
repositories, the process library, the website and external users now depend on the commands,
the file formats and the viewer API, so a reader needs to tell from the version whether an
update can break them. Options: stay on 0.x with breaking minors, or 1.0.0 with semantic versioning.

## Decision

From 1.0.0 cheme-as-code follows [Semantic Versioning 2.0.0](https://semver.org/). The public
interface is:

- the `cheme` commands, their options, exit codes and finding rule ids;
- the file formats and schemas of a plant repository (`cheme schema`, the project template) and
  the run records (`process-run/v1`);
- the `cheme serve` API that the viewer uses;
- the documented Python API (`chemeascode.domains.piping.authoring` and the functions the docs
  name as an API).

A change that breaks any of these needs a new **major** version; a backward-compatible addition
a **minor**; a fix a **patch**. Breaking changes are listed under "Breaking" in CHANGELOG.md with
the migration (for a schema, `cheme migrate`). Other modules are internal: moving one still needs
no compatibility layer, but a move of a documented API path is breaking. A release is the
version in `pyproject.toml`, its CHANGELOG section and an annotated tag `vX.Y.Z` on `main`.

## Consequences

- Dependents can pin `~=1.0` instead of a commit.
- Breaking work is batched into major releases, or provided as an addition first and removed in
  the next major.
- Deciding what is public takes judgment at review time; this list is the reference.

## Evidence

`pyproject.toml` (1.0.0), CHANGELOG.md, `docs/framework/contributing.md` ("Releases and
versions", "Moving a module"), tag `v1.0.0`.
