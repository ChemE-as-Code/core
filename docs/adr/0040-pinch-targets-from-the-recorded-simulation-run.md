# 0040. Pinch targets from the recorded simulation run, every duty in one class and reconciled

- **Status:** Proposed
- **Date:** 2026-11-04

## Context

Core had pinch targeting (`domains/process/heat_integration/pinch.py`, problem table, `basis:
targets`) and turned simulated duties into pinch streams inside the simulation's energy audit
(`simulation/energy.py`), but no whole-plant command, no boundary-checked collection of the
plant's thermal streams and no record of a result (#134). The process library needs one
reference workflow for hda-1, cumene-1 and styrene-1 (process-library#313). Two failure modes
dominate such analyses: heat counted twice (a feed/effluent exchanger as utility and recovery,
a waste-heat boiler's steam as a second source) or not at all, and a theoretical difference
of utilities read as a saving. The simulators (DWSIM's worker, the IDAES worker) report per
stream only inlet and outlet values, no enthalpy-temperature profile. OpenPinch (MIT, 0.7.6)
was considered as an engine; it is left for an optional extra (#134, PR 3).

## Decision

- `cheme process pinch --dt-min X` takes the targets from the case's **recorded** run
  (`process/simulation-run.json`) and never runs the simulator. The record must be current
  (the inputs translate to its model fingerprint) and converged; otherwise it is an error. The
  run is rebuilt from the record's unit results and stream temperatures
  (`heat_integration.streams.out_from_record`).
- `heat_integration/streams.py` owns the duty-to-stream logic; `simulation/energy.py` calls it
  (`process_duties`) and keeps its own checks unchanged. Each thermal duty of the run is put in
  exactly one class: `utility`, `recovery` (counted once), `constrained` (reactors by default,
  with the reason; a sensitivity option includes them) or `excluded` (with the reason). The
  utility side of an exchanger against a utility terminal's stream is no stream.
- Quality per stream: `profile`, `segmented`, `linearised`, `insufficient`. With today's
  simulator output only `linearised` (one constant-CP or isothermal segment; never split at
  dew or bubble points) and `insufficient` (excluded, duty listed) occur, and the output says
  the targets rest on linearised streams.
- **Reconciliation:** the run's thermal duties are listed from the units' results alone and the
  streams must give each back within 0.1 kW + 1 % (the energy closure's tolerance). Heat left
  over is a warning, and `--write` refuses (exit 3).
- Three quantities, labelled so in every output: current utility demand (of the targeted
  streams), theoretical minimum utility demand at dTmin, theoretical energy-saving potential.
  The last is never called savings or recoverable heat. Utility-use pinch violations are
  reported apart from cross-pinch transfer, which is evaluated only for existing exchangers
  whose sides are all known.
- dTmin is required, one global value, with its source or `ASSUMED`; hot-side, cold-side and
  shifted pinch are always given.
- `process/pinch-run.json` (schema `cheme/pinch-run/v1`, one generated entry per case) keeps
  the settings, the core version, the simulation run's model and content fingerprints, the input
  fingerprints and the results. The engine is `native`; no dependency is added.

## Consequences

- Positive: one reproducible whole-plant target per case, comparable across plants; double
  counting and unaccounted heat are caught by the reconciliation, not by review; the energy
  audit and the pinch share one extraction.
- Positive: no simulator is needed to target a solved plant; CI tests hda-1 end to end from a
  fixture copy of its recorded run.
- Negative: every stream is linearised between its end temperatures, not on the safe side;
  streams that change phase or vary strongly in heat capacity give approximate pinch
  temperatures. Mixing points are taken as the flowsheet has them. A compressor train's
  intercooling, a multi-stream exchanger's net imbalance and a specified split's stated
  imbalance are excluded.
- Negative: a run recorded before the inputs changed must be simulated again before pinch
  works; a change to the translation that alters fingerprints makes recorded runs stale.
- Follow-ups (#134): the schema kind `heat_integration` (dTmin with source, boundary, per-unit
  class overrides, extra streams), `--check` and staleness of the pinch record, `--dt-min-sweep`,
  composite curve drawings, the skills' rework (PR 2); OpenPinch as an optional engine with
  several utility levels (PR 3). HEN synthesis is out of scope.

## Evidence

- #134 (PR 1).
- `src/chemeascode/domains/process/heat_integration/{streams,report}.py`,
  `src/chemeascode/domains/process/simulation/energy.py`,
  `src/chemeascode/interfaces/cli/process.py` (`pinch`).
- `tests/test_pinch.py`, `tests/test_process_pinch.py`, `tests/data/process-hda-1/`.
