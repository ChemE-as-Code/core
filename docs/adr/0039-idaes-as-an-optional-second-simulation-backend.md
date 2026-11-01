# 0039. IDAES as an optional second simulation backend, chosen in simulation.yaml

- **Status:** Proposed
- **Date:** 2026-10-31

## Context

`cheme process simulate` had one simulator, DWSIM, run out of process (ADR 0014) with its own
tear iteration (ADR 0033). DWSIM needs Docker or a local .NET install, which many machines (and
agents) do not have. Core issue #12 asks for an optional IDAES/Pyomo backend that uses the shared
inputs and results and never becomes a base dependency. IDAES (idaes-pse) is open source, solves
the whole flowsheet as one equation system (IPOPT) and ships a modular property framework with
example component data for benzene, toluene, hydrogen and methane, the components of the
toluene hydrodealkylation (HDA) flowsheet that IDAES's own tutorial uses.

Where the backend is chosen was the open question:

- a `--simulator` option on `cheme process simulate`: quick to switch, but the simulator is not
  recorded with the inputs, so `--check` (and `cheme validate`, which translates without a
  simulator) cannot know which simulator produced a stored value, and two runs of the same files
  could fill different numbers;
- `simulator:` in `process/simulation.yaml`: the field already existed (`Literal["dwsim"]`) and
  the simulation file is already an input of every simulated value's fingerprint and of the run
  record.

## Decision

- `process/simulation.yaml` chooses the backend: `simulator: dwsim` (the default; files without
  the field are unchanged) or `simulator: idaes`. There is no command-line override: the
  simulator is an input of the result, like the property package. A model translated for IDAES
  carries `simulator: idaes`, so its fingerprint differs from DWSIM's; a DWSIM model's
  fingerprint is unchanged.
- The IDAES worker runs out of process, like DWSIM's: `integrations/idaes.py` starts
  `integrations/idaes_worker.py` in the Python that `CHEME_IDAES_PYTHON` names (or the command in
  `CHEME_IDAES_COMMAND`) and exchanges JSON on stdin/stdout. The worker imports only the standard
  library, idaes-pse and Pyomo; cheme-as-code never imports `idaes` or `pyomo`
  (`tests/test_boundaries.py` lists both as lazy-only libraries). No extra is added to
  `pyproject.toml`: IDAES and its solver binaries live in their own environment.
- Both backends take the same simulator model (`simulation/translate.py`) and return results in
  the same shape (`streams`, `units`, `energies`, `converged`, `iterations`, `messages`), so the
  `--fill`/`--check` path, the conversion and energy checks, the run record
  (`process/simulation-run.json`) and the provenance are shared: provenance `calculated`, origin
  `simulated`, source `cheme process simulate: IDAES <idaes-pse version>, <property package>`,
  the model fingerprint. The run record's `simulator` also names the numerical solver (IPOPT and
  its version) and keeps an initialization that did not finish under `notes`.
- The first scope is bounded to what the HDA loop needs, and everything else is refused at
  translation (`cheme.process-sim-backend-unsupported`, error) before any solver runs:
  - units: heater, cooler, valve, pump, mixer, splitter, flash, conversion (stoichiometric)
    reactor with one outlet and one-phase conversion reactions; compressor and expander with the
    Peng-Robinson package only; recycles by tear streams (a sequential-decomposition
    initialization of two passes, then one simultaneous IPOPT solve);
  - property packages: `IDAES ideal VLE` (Raoult's law, ideal gas) and `IDAES Peng-Robinson`
    (every kij 0), both built with IDAES's generic framework from the component data IDAES
    ships in its example packages (`BT_ideal`, `BT_PR`, `HC_PR`); the worker reads that data at
    run time and core copies none of it;
  - compounds: benzene, toluene, hydrogen and methane (hydrogen and methane in the vapour only);
  - feeds by temperature and pressure (no saturation feeds), no interaction parameters.
- No IDAES package is benchmarked by cheme-as-code: translation reports
  `cheme.process-sim-method-unbenchmarked` (info), `methods.yml` claims nothing for the IDAES
  route, and its values are not predictive.
- Tests that need IDAES run only with `CHEME_IDAES_TESTS=1` (and `CHEME_IDAES_PYTHON`); the rest
  replay a recorded worker response.

## Consequences

- Positive: a flowsheet within the scope can be simulated without Docker or .NET; the two
  backends share one result path, so a later cross-backend comparison is a matter of switching
  one field.
- Positive: the base package stays free of IDAES, Pyomo and solver binaries.
- Negative: a run of the HDA loop takes minutes (each unit's property initialization runs in
  every pass); `--save` writes nothing with IDAES (there is no flowsheet file to open elsewhere).
- Negative: agreement with DWSIM is not validation; nothing here benchmarks the IDAES packages,
  and IDAES's example component data carry the application range IDAES gives them, not one
  cheme-as-code claims.
- Limitations and follow-ups: no columns, heat exchangers (two-sided), component separators,
  equilibrium, Gibbs or kinetic (fixed-bed) reactors, compressors with intercoolers,
  saturation feeds or interaction parameters; no other compounds; no CI workflow runs the live
  tests yet. The reactor/PFR pilot and optimization of core issue #12 remain open.

## Evidence

- `src/chemeascode/integrations/idaes.py`, `src/chemeascode/integrations/idaes_worker.py`,
  `src/chemeascode/domains/process/simulation/backends.py`, the `simulator` field in
  `src/chemeascode/domains/process/simulation/schema.py`.
- `tests/test_process_simulate_idaes.py` (translation, refusals, recorded-response fill and
  check; live run with `CHEME_IDAES_TESTS=1`), `tests/test_boundaries.py`.
- `examples/process-hda-idaes`, [docs/framework/idaes.md](../framework/idaes.md).
- Core issue #12; ADR 0014 (out-of-process worker, claims only where benchmarked), ADR 0029
  (run records), ADR 0033 (DWSIM tear iteration).
