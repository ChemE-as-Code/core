# 0065. A bounded QSDsan A2/O worker behind process simulate

- **Status:** Proposed
- **Date:** 2026-11-09

## Context

The companion `processes/wwtp-a2o` example has a pinned numerical environment,
an EXPOsan-derived ASM2d calculation, native BFD/PFD generation and immutable run evidence.
The shared `cheme process simulate` command already supports DWSIM and IDAES.
Wastewater COD/N/P component bases are not molecular mass or mole fractions.

## Decision

Extend `cheme/simulation/v1` additively with `simulator: qsdsan` and a required `qsdsan`
configuration. Existing files still default to DWSIM. The initial supported `model` is only
`wwtp-a2o`; this is not a generic translator for arbitrary wastewater flowsheets.

```yaml
schema: cheme/simulation/v1
kind: simulation
simulator: qsdsan
qsdsan:
  model: wwtp-a2o
  environment: .venv
  input: inputs/baseline.json
  timeout_s: 300
```

Paths are project-relative and confined to the project. The command calls the fixed local
module `wwtp_a2o.interfaces.cli.cheme` using that environment's Python. No shell command from
YAML is executed. Core does not import/install QSDsan or EXPOsan. The worker calls the same
`project.run.execute` used by the VS Code entry point, including the unchanged solver settings.
The worker timeout includes imports, diagrams and saving results; it does not change the
example's 180-second integration limit. Molecular simulator settings and `--save` are rejected.

`--fill` retains a new `runs/<id>/` and saves its adapter entry in
`process/simulation-run.json`, preserving other cases and earlier run directories. Wastewater
stream values retain explicit mg COD/L, mg N/L, mg P/L and m3/day units; `filled` is empty.
No molecular stream property is filled. `converged` in the existing adapter contract denotes
completion of the requested integration and basic checks, not steady state or plant validation.
The report retains those distinct claims and the native API adds an explanatory finding.

`--check` copies the recipe to a disposable workspace, calculates there, and writes nothing to
the source project. A stale saved input fingerprint is a warning. Temporary outputs are discarded.
The API only reads through `Snapshot`; it never executes the worker. Its staleness comparison
includes the local source files, input JSON, generated engineering YAML and simulation config.

The numerical JSON is authoritative. The worker checks that existing diagram YAML still agrees
with its last generated input snapshot before regenerating it; independent diagram edits are
refused rather than silently replaced. Source changes and failures remain reviewable in retained
run folders. This adapter does not grant native engineering maturity or design approval.

## Consequences

- The CLI can run DWSIM, IDAES and this A2/O case without merging dependency stacks.
- The A2/O worker and core configuration form a bounded cross-repository contract.
- The old standalone `run_example.py` remains usable. MCP is not involved.
- The shared Stream table reads final wastewater values from the adapter record (ADR 0066).
  Time-series data are available in the run evidence.
- General wastewater schema/maturity support, arbitrary-model dispatch, deployment, concurrency
  control for multiple writes to one project and calibration are outside this local change.

## Evidence

- `tests/test_process_qsdsan.py`: dispatch, units, failure isolation, source tracking and check isolation.
- Existing DWSIM and architecture tests are run separately from live wastewater regression.
- Use the companion example's pinned baseline for the 200-day comparison against EXPOsan.
