# Stages and gates

A plant advances through the stages listed in `plant.yaml` (the template: concept, basic,
detail). Each stage has gates in `checks/checks.yaml`; `cheme check` evaluates them and
`cheme check --write` signs a stage off in `checks/status.json`.

The project stage is one of four axes, kept apart: it is neither the calculation maturity
`cheme maturity` evaluates, nor the design maturity a process-library manifest claims, nor a
review status; see the [glossary](glossary.md).

The template's `STAGES.md` defines what each stage requires:

<!-- include: src/chemeascode/templates/project/STAGES.md :: # Stages -->

<!-- readme: ### check -->

<!-- readme: ### status -->
