# ChemE-as-Code

**Plant design as code.** A process plant kept as plain files in a git repository: DEXPI 2.0.1
P&IDs, engineering lists in YAML, decisions in Markdown. Engineers and coding agents such as
Claude Code edit the files; `cheme`, the command of the `cheme-as-code` package, checks them.

`cheme` gives people and agents what they need to work on engineering files the way they work on
code: a validator with `file:line` findings, a formatter that keeps diffs small, a renderer, a
visual diff and engineering-step gates. On top of that it generates the BFD and PFD from process
YAML, builds a 3D layout model, and derives a material take-off, an estimate and an LCA from the
committed files.

!!! note "Status"
    Research prototype of the Process Intelligence Research group, private until the first
    release. Since 0.7.0 the package is `cheme-as-code`, the import name `chemeascode` and the
    command `cheme` (formerly `plantcode`); plant repositories migrate once, see
    [Rename](framework/rename.md).

## Where to start

- **[Install](getting-started/install.md)** `cheme` and its optional extras.
- **[Your first plant](getting-started/first-plant.md)**: `cheme init`, git setup, validate,
  render.
- **[The project template](getting-started/project-template.md)**: what `cheme init` writes.
- **Concepts**: [repository layout](concepts/repository-layout.md),
  [plant.yaml](concepts/plant-yaml.md), [stages and gates](concepts/stages-and-gates.md),
  [provenance](concepts/provenance.md), the [glossary](concepts/glossary.md).
- **Guides** for P&IDs, the process BFD/PFD, the 3D layout, MTO and estimate, LCA, the viewer
  and agents.
- **Reference**: the [CLI](reference/cli.md), the [schemas](reference/schemas.md) and the
  [serve API](reference/serve-api.md), generated from the code on every build.
- **Framework**: how the package is organised and how to contribute
  ([architecture](framework/architecture.md), [contributing](framework/contributing.md)).

## At a glance

<!-- readme: ## Use | body | intro -->
