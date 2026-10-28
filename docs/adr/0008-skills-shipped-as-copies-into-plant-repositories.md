# 0008. Skills ship with the package and are installed as copies into plant repositories

- **Status:** Accepted
- **Date:** 2026-10-17 (template skills); manifest and `cheme skills update` on 2026-10-21

## Context

Agent skills (workflow and judgment instructions) must evolve with the commands they call.
Claude Code reads skills only from the repository it works in, so they cannot be referenced from
the installed package. Plant teams may also adapt a skill locally.

## Decision

- Skills are source code of cheme-as-code, living with the capability they drive:
  `domains/<d>/skills/<name>/` or `project/skills/<name>/`, with one seven-section structure.
- `cheme init` installs them as copies into `.claude/skills/<name>/` of the plant repository.
- A manifest of known skill versions (`scripts/build_skill_manifest.py`) lets
  `cheme skills status` tell outdated copies from locally modified ones;
  `cheme skills update` refreshes outdated copies and never replaces a modified skill without
  `--force`.
- Skills hold workflow and judgment; shared engineering algorithms belong in domain functions
  ([0010](0010-deterministic-domains-no-llm-calls.md)).

## Consequences

- Positive: skills are versioned, reviewed and tested with the code they call; plants can pin
  and adapt them.
- Negative: copies drift: after upgrading `cheme`, each plant must run `cheme skills update`.
- Negative: every skill change requires regenerating the manifest and the init golden file
  (`tests/data/init-manifest.txt`); `tests/test_skills.py` fails otherwise.

## Evidence

- pre-release commit 62c29e1 (template with skills `dexpi-xml`, `pid-edit`, `pid-draft`,
  `lists-sync`, `review`).
- pre-release commit 03211e3, pre-release commit 40ecc6c, pre-release commit 0466390
  in pre-release PR 58.
- `src/chemeascode/templates/install.py`, `README.md` ("How the pieces fit together"),
  [contributing.md](../framework/contributing.md) ("Adding or changing a skill").
