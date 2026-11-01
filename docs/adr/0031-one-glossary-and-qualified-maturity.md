# 0031. One glossary for the project name and the maturity, stage and review axes

- **Status:** Accepted
- **Date:** 2026-10-27

## Context

The papers, core, the process library, the viewer and the website used overlapping names for
different things. "ChemE-as-Code", "Engineering-as-Code", "Plant-as-Code" and "Design-Ops" were
mixed. "Maturity" meant the calculation maturity `cheme maturity` evaluates
([0013](0013-calculation-maturity-separate-from-completeness-and-review.md)) and the design
maturity a process-library manifest claims (`process.yaml` `maturity`), next to the project
stage of `plant.yaml` ([0012](0012-stages-gates-and-sign-offs-on-the-default-branch.md)) and the
review status. `cheme maturity` printed "level: balanced (supports library maturity screening)"
and its findings "maturity screening claimed". A reader could not tell which axis was meant.

## Decision

- `docs/concepts/glossary.md` is the one vocabulary of ChemE-as-Code. The other
  ChemE-as-Code repositories (process library, viewer, website, papers) follow it. A change to it
  is a change to a contract between repositories and needs an ADR.
- The project is **ChemE-as-Code**. Engineering-as-Code, Plant-as-Code and Design-Ops are
  concepts from the literature; core's docs speak of "stages, gates and sign-offs".
- There are four axes: **calculation maturity** (sourced, balanced, predictive, engineering;
  `checks/maturity.json`), **design maturity** (concept to operating-reference; `process.yaml`
  `maturity`, capped by evidence), **project stage** (`plant.yaml` `stage`,
  `checks/status.json`) and **review status** (people only). User-facing text (docs, CLI
  output and help, finding messages, skills) always says "calculation maturity" or "design
  maturity", never a bare "maturity".
- Only wording changes. Field names, rule ids, schema ids, the `cheme maturity` command and the
  `kind: maturity` gate keep their names, so no plant repository migrates. The mapping from
  calculation maturity to design maturity stays as `chemeascode.project.maturity.LEVELS` has it
  and is documented once, in the glossary.
- `cheme maturity` text output ends with
  `calculation maturity: <level> (design maturity claimed: <claim>)`, then the design maturity
  the evidence supports.

## Consequences

- Positive: one place to look up a term; papers, library and website say the same thing.
- Positive: no migration, since the JSON report, the schemas and the rule ids are unchanged.
- Negative: finding messages and the text output changed wording; scripts that parsed the old
  text (`level: ...`, `maturity ... below ...`) need to read `--json` instead, as they should.
- Follow-ups: ChemE-as-Code/process-library#87 and ChemE-as-Code/website#71 adopt the
  glossary; the viewer shows stage and calculation maturity apart.

## Evidence

- `docs/concepts/glossary.md`, `docs/framework/maturity.md`,
  `src/chemeascode/project/maturity.py` (`report_lines`, the `cheme.maturity-claim-exceeds`
  message, the gate detail), `tests/test_maturity.py`, `tests/test_maturity_gate.py`.
