# 0072. Shared project-worker execution, provenance and result publication

- **Status:** Proposed
- **Date:** 2026-11-19
- **Refines:** [0065](0065-qsdsan-a2o-process-worker.md), [0066](0066-wastewater-stream-table.md)

## Context

[core#290](https://github.com/ChemE-as-Code/core/issues/290) asks for reusable execution before
Aspen Plus, HYSYS and Dymola adapters are added. Core #254 is merged at `0e858853e159ded7fc408a98bc294a671cd75c60`;
this extraction starts there. It does not change any biological or molecular numerical algorithm.
Python modules are one deployment option, not the definition of a simulator.

## Decision

- `ProjectAdapter` owns supported modes, bounded options, native identifiers, solver diagnostics,
  legacy interpretation and publication shape. `ProjectWorkerBackend` binds it to the existing
  registry. Only working adapters are registered; commercial names are refused today.
- `WorkerTransport.execute(root, WorkerRequest)` owns staging, invocation, timeout and cleanup.
  The first implementation is `LocalPythonTransport`. Deployment configuration selects the
  interpreter outside plant YAML. Future session/remote transports implement the same protocol;
  no COM automation, credentials, scheduler or network protocol is implemented here.
- Process orchestration owns case/input checks, provenance, results validation and publication.
  `worker_model`, `worker_evidence`, `worker_publication` and `worker_run` contain no simulator
  names or wastewater ownership prefixes. QSDsan-specific legacy translation stays in `qsdsan`.
- `cheme/worker-request/v1` declares run/case/mode, model and input paths, configuration,
  mappings, timeout and assigned evidence destination. Declared files are copied and hashed
  as bytes. No shell command or machine executable path is accepted in engineering configuration.
- `cheme/adapter-result/v2` extends the existing `AdapterResult` with execution, numerical
  convergence, integration progress and an independent steady-state assessment. `completed`
  means a dynamic interval completed, never numerical convergence or plant validation. A
  steady-state solve reports `converged`; a physical steady-state claim requires its own method
  and evidence. Exit zero alone cannot publish a result.
- V1 retains its four statuses and existing meaning. DWSIM, IDAES, props and propagate continue
  emitting v1. Existing records are read without rewriting. Historical `integration_completed`
  is displayed as a legacy completion flag and cannot satisfy the numerical convergence gate.
  Maturity and heat-integration consumers share that gate, including for legacy records.
  The published A2/O v1 worker is translated only when its `result.json` and trajectory support
  completion; arbitrary legacy `converged` alone is insufficient. New worker authors use v2.
- New cells carry a structured producer (`tool`, `adapter`, `model`). Only that producer's
  calculated cells are replaced or excluded from its fingerprint. The QSDsan adapter recognizes
  its exact historical source string. Given/assumed and foreign producer values are protected.
  Measured quantities stay under `calculated`; molecular publication targets state fields with
  explicit units/composition. Existing DWSIM/IDAES filling is untouched.
- The CSV trajectory manifest records hash, columns/units, interval and final instantaneous
  snapshot. Times increase except an explicitly labelled `before`, `after` pair at an event.
  Stable stream/unit/instrument references are validated. Opaque native files stay as evidence.
- A successful fill appends evidence under `process/simulation-runs/<id>/`, replaces the
  flowsheet and case record under an exclusive writer lock and checks for concurrent edits.
  Each rename is atomic, not the pair. On an ordinary I/O failure core restores the old sheet
  and removes the uncommitted evidence. A process/power interruption between renames is not a
  transaction guarantee: inspect the archived entry and rerun. Failed attempts have separate
  diagnostic directories and never replace the accepted case. Check mode writes no plant files.
  If rollback itself fails, retain and name the previous sheet in a recovery directory for
  manual repair; this exceptional storage failure cannot guarantee the live pair is consistent.

## Consequences

The same path supports a test-only simulator with another solver name, dynamic CSV evidence,
molecular publication and a non-Python session stand-in. No commercial software is needed in CI.
Actual vendor sessions must still implement licence acquisition/release, cancellation/timeout
cleanup and native diagnostics. Exact APIs and versions need verification at implementation.

New worker results change their schema/status and use `cheme.process-worker` findings. These
public output changes are **breaking** under ADR 0032: release them in a major release and update
result consumers to v2. This work prepares an unreleased change; it creates no release or tag.
The enclosing case collection stays `cheme/simulation-run/v1` and may contain both result versions.
Model fingerprints use contract 2 and raw asset hashes; an old result can be marked stale until
rerun, but is never rewritten or reinterpreted as independent steady-state evidence.

## Evidence

- `tests/test_process_workers.py`: a second adapter, real subprocess, events, partial results,
  native files, protected values, concurrent changes and a session transport stand-in.
- `tests/test_qsdsan_worker_contract.py`, `test_process_qsdsan.py`, `test_process_wastewater.py`:
  interpreter precedence, subprocess failures/descendant cleanup, rollback and read-only users.
- [Adapter author guide](../framework/project-workers.md).

The real 200-day A2/O baseline was rerun on Windows with Python 3.12.13 and the existing
QSDsan 1.5.3 / EXPOsan 1.5.3 numerical environment, using the library example at `1bcb8de4`.
Previous run `d52a819f1cfd47fc8544353031abb5dd` and new run
`0b890652d2e448959ed995f74443d98e` have identical 170-by-804 state arrays and recorded times.
All 84 final stream values agree at `rtol=1e-6`, `atol=1e-8`; the real browser table and PFD
inspector retain their measured units. The same 200-day baseline was rerun on Ubuntu, where all
84 final stream values also matched the preserved Windows baseline at the same tolerances.
The Ubuntu trajectory matched the previous Ubuntu baseline exactly (170 states at 827 recorded
times), and the Stream table displayed all 84 values with their original units. Original run
folders were preserved. This verifies software reproducibility. Plant calibration, independent
steady-state evidence and commercial adapter execution remain outside this verification.
