# 0014. DWSIM as an out-of-process simulation worker, and property methods claimed only where benchmarked

- **Status:** Accepted
- **Date:** 2026-10-22 (DWSIM worker); supported-method contract 2026-10-24; first benchmarked
  claim 2026-10-25

## Context

Predictive process simulation needs a rigorous simulator. DWSIM is open source but runs on .NET,
with its own runtime and native dependencies, which must not become a dependency of
`import chemeascode`. Thermodynamic property methods also have limited validity ranges, and a
selection tree can recommend a method that no route can run.

## Decision

- DWSIM runs out of process: `integrations/dwsim_worker.py` runs inside the Docker image of
  `docker/dwsim/` (or next to a local install), and `integrations/dwsim.py` talks to it in JSON.
  `domains/process/simulation/` translates the flowsheet into a model and writes results back as
  `calculated` values with an adapter result record. Tests needing DWSIM run only with
  `CHEME_DWSIM_TESTS=1` in the `dwsim` workflow.
- Every heavy dependency (simulators, CAD, ML) goes into an extra and an `integrations/` adapter,
  never into the base dependencies.
- The supported-method contract (`thermodynamics/methods.yml`): for each recommendable method,
  which route runs it; a method a route does not run is never replaced silently (explicit,
  reported substitutes). No application range is claimed unless a test benchmarks it. Today only
  DWSIM 9.0.5 Peng-Robinson for N2/O2/Ar is benchmarked (against CoolProp reference equations
  of state), and `cheme maturity` uses that claim.

## Consequences

- Positive: the base package stays light and installable; the simulator is swappable behind a
  JSON boundary; claims about property accuracy are backed by tests.
- Negative: simulation needs Docker or a local DWSIM; CI coverage of the simulator is a separate
  workflow.
- Negative: outside the benchmarked envelope, `predictive.property-regime` stays unsupported,
  so most chemistries cannot reach `predictive` yet.
- Limitation: no electrolytes, pseudocomponents or solids on the DWSIM route; DWSIM's own
  interaction parameters only.

## Evidence

- pre-release PR 68 (pre-release commit 58ca01e), CI workflow pre-release PR 71
  (pre-release commit dc779b0), reactors and columns in later PRs (pre-release PRs 78, 87).
- Supported-method contract pre-release PR 149 (pre-release commit c180ce5); benchmark
  pre-release PR 298 (pre-release commit be1d7f4); pre-release issue 137.
- `src/chemeascode/integrations/dwsim.py`, `dwsim_worker.py`, `docker/dwsim/Dockerfile`,
  `.github/workflows/dwsim.yml`, `src/chemeascode/domains/process/thermodynamics/methods.yml`,
  [architecture.md](../framework/architecture.md) ("Optional dependencies"),
  [maturity.md](../framework/maturity.md).
