# Requirements and design basis

**Scope.** What a plant has to achieve and under which conditions: product specifications and
targets, capacity, feed specifications and their variability, site conditions, constraints,
assumptions, operating cases, acceptance criteria, and design decisions with their reasons.

**Artifact types.** The design basis (`process/design-basis.yaml` in a plant repository today),
operating cases, a decision log.

**Code today.** The design-basis schema, `schemas.py` (`DesignBasis`, free-form below the top
level; `chemeascode.schemas` re-exports it). The process cases are
defined in `process/flowsheet.yaml` and owned by `process`.

**What will live here.** Schemas and loaders for these artifacts, and rules that check them for
consistency (units, cases referenced but not defined, targets without acceptance criteria).

**Out of scope.** Calculations that use the requirements: balances and simulation belong to
`process`, costing to `assessment`. No project-management or ticketing features.

This domain imports no other domain. See [the architecture](../../../../docs/framework/architecture.md).
