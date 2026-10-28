# Glossary

One vocabulary for core, the process library, the viewer, the website and the papers. Every
other ChemE-as-Code repository follows this page; where it and another text disagree, this page
is right and the other text is a bug.

## Project name and concepts

| term | meaning | where to use it |
|---|---|---|
| **ChemE-as-Code** | our open project: the `cheme` toolkit, viewer, process library and Process Atlas | everywhere in our own docs, sites and papers; the name to push |
| Engineering-as-Code | the general idea of engineering design as versioned text plus automated checks (lineage: Infrastructure-as-Code; Song 2026) | literature and background only |
| Plant-as-Code | the process-plant formulation in the Nature Chemical Engineering Comment (Schweidtmann & Demeyer 2026) | literature: "ChemE-as-Code implements Plant-as-Code and extends it beyond the plant (chemistry, experiments, life cycle assessment)" |
| Design-Ops | the change workflow (DevOps for engineering; Demeyer, Bacidore 2025) | literature; in our docs, "stages, gates and sign-offs" |

`cheme-as-code` (lower case) is the Python package, `chemeascode` its import name and `cheme`
its command; they are names of the toolkit, not of the project. The website never mentions the
concept lineage; the papers state it as in the table.

## Calculation maturity, design maturity, project stage, review status

Four separate axes. None of them implies another: a signed-off stage is not a review, a
claimed design maturity is not evidence, and passing gates sets no review status.

| axis | values | set by | source of truth |
|---|---|---|---|
| **calculation maturity** (evidence) | sourced → balanced → predictive → engineering | evaluated by `cheme maturity` | `checks/maturity.json` |
| **design maturity** (claimed in the library) | concept / screening / basic-engineering / detail-engineering / operating-reference | `process.yaml` `maturity`, capped by evidence (`cheme.maturity-claim-exceeds`) | process-library manifest |
| **project stage** (workflow) | concept / basic / detail (gates, sign-offs) | `plant.yaml` `stage`, `cheme check --write` | `checks/status.json` |
| **review status** | unreviewed / internally-reviewed / peer-reviewed / industry-validated | people only | `process.yaml` `validation.status`, review records |

**Always qualify the word.** User-facing text says "calculation maturity" (the four levels core
evaluates) or "design maturity" (the library manifest's label), never a bare "maturity". The
field names stay as they are (`process.yaml` `maturity`, the report's `level` and
`library_maturity`, the `kind: maturity` gate, the `cheme maturity` command): only labels and
docs carry the qualifier, so nothing migrates.

- [Calculation maturity](../framework/maturity.md): what each level requires and how
  `cheme maturity` evaluates it.
- [Stages and gates](stages-and-gates.md): the project stage, its gates and sign-offs.
- [ADR 0013](../adr/0013-calculation-maturity-separate-from-completeness-and-review.md): why
  calculation maturity is kept apart from artifact completeness and review.

### From calculation maturity to design maturity

The highest design maturity a reached calculation maturity supports. `cheme maturity` applies
it (`chemeascode.project.maturity.LEVELS`) and warns with `cheme.maturity-claim-exceeds` when
`process.yaml` claims more:

| calculation maturity reached | highest design maturity it supports |
|---|---|
| none | none |
| sourced | concept |
| balanced | screening |
| predictive | screening |
| engineering | basic-engineering |

No check in core supports `detail-engineering` or `operating-reference`. The text output of
`cheme maturity` names both, for example
`calculation maturity: balanced (design maturity claimed: screening)`.

### The website's lifecycle

The website's homepage groups the platform by lifecycle: Conceptual design / Engineering
development / Plant detail / Control and automation. That is a map of what the toolkit covers,
not a property of a plant: it is none of the four axes above, and no file records it.
