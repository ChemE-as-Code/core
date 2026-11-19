# Project-worker adapter author guide

The shared path implements [ADR 0072](../adr/0072-shared-project-worker-execution-and-results.md)
and [core#290](https://github.com/ChemE-as-Code/core/issues/290). QSDsan is its first production
adapter. Aspen Plus, HYSYS and Dymola are design targets, not implemented backends.

## Adding an adapter

1. Implement `ProjectAdapter` in `domains/process/simulation/`. Set `id`, `title`, `modes`,
   and `publication` (`measured` or `molecular`). Use `worker` for the portable configuration;
   QSDsan retains its established `qsdsan` key. Register a `ProjectWorkerBackend(adapter)` only
   after the implementation and its contract tests work.
2. Override `validate_configuration` for an explicit, bounded set of JSON options. The default
   accepts no options. Validate types, bounds and supported mode; reject unknown keys. Do not
   embed executable paths, licence servers, credentials, commands or Python expressions there.
3. Identify the native model with `model`, `input`, and `files`. They are slash-separated project
   paths and are copied/hashed as bytes. Include model code, initialization data and lock files.
   A missing asset refuses execution with its path. The input file is included automatically.
   Native assets larger than the viewer's text-file limit are fingerprinted without parsing or
   embedding them in API responses; their size does not make a current result appear stale.
4. Supply native-to-ChemE mappings under `mappings.streams`, `.units`, `.instruments`. Response
   IDs are native identifiers when a mapping is supplied, otherwise stable ChemE IDs. Unknown
   targets and many-to-one mappings are refused. A trajectory reference follows the same mapping.
5. Select a `WorkerTransport` outside plant data. The local Python default calls a declared
   module with request/response JSON paths; override `transport` for another environment.
   It returns `ExecutionResult(execution, result)`. A transport owns its session, resources,
   diagnostics and timeout. Closing a session and releasing its licence is its responsibility
   on success and failure. No real remote/session transport is supplied by this change.
6. Translate native output in `normalize`, returning `AdapterResult` v2. Report the actual
   version/method. It must not claim completion, convergence or steady state from exit code zero.
   Keep numerical diagnostics and native output inside the assigned evidence folder. Symlinks,
   junctions, traversal and special files are refused.

The standard-library-only `examples/process-qsdsan/demo_worker.py` illustrates the exchange.
`tests/test_process_workers.py` is the simulator-neutral dynamic and molecular example; its
adapter is registered only within tests. The shared path does not import QSDsan/EXPOsan SDKs.

## Deployment and staging

For QSDsan, `CHEME_QSDSAN_PYTHON` takes precedence over `CHEME_WORKER_PYTHON`, including when
the former is invalid. Missing/invalid settings name the required executable. An interpreter
must be an existing absolute file. The process uses `-E -s -B -X utf8`, a controlled environment,
an argument list and no shell. Secrets from arbitrary parent environment variables are not
forwarded. The selected environment and its installed packages still need their own lock.

Both CLI modes execute trusted project code with the user's permissions. Temporary copies are
for reproducibility and accidental-write protection; this is not a security sandbox. Core
archives the original staged files under `cheme-inputs/`, before execution can edit them.
The timeout kills the worker process tree (Windows) or process group (POSIX). Workers must not
detach independent background services and must close any external resources they own.

`WorkerRequest` includes `schema`, `run_id`, `case`, `mode`, `model`, `input`, `files`,
`configuration`, `mappings`, `timeout_s`, assigned `evidence` and input fingerprints. A transport
does not decide whether the numerical output is accepted. `ExecutionOutcome` reports
`completed`, `failed`, `timed-out` or `refused`, transport, exit code, elapsed seconds and message.
Cancellation is not an implemented public outcome.

## Result semantics and publication

V2 keeps `solver`, `case`, `units`, `streams`, `messages`, `findings` and optional fingerprints.
It adds `outcome`:

```yaml
schema: cheme/adapter-result/v2
case: design
status: completed
solver: {name: Example simulator, version: '1', method: integration}
outcome:
  mode: dynamic
  convergence: not-applicable
  integration: {start: 0, requested_end: 24, achieved_end: 24, time_unit: h, completed: true}
  steady_state: {state: not-evaluated}
streams:
  - id: outlet
    values: {tracer: {value: 4, unit: mg/L}}
    filled: []
```

Core sets `execution` from the transport, disregarding a worker-supplied claim. `convergence`
is `converged`, `not-converged`, `not-applicable` or `unknown`. Dynamic publication requires
`completed`, a complete interval and no explicit numerical failure. Steady-state mode requires
`converged`. A steady-state *assessment* is separate: `established` requires a method and
confined evidence files. A completed integration alone never establishes it. Failed/partial
results remain diagnostics; scalar values from them cannot become accepted output.
Maturity and heat-integration consumers use the same numerical-convergence check. A legacy
dynamic completion flag cannot qualify a run as a converged input for pinch targets.

Measured publication writes `state.<case>.calculated.<quantity>` with finite numeric value and
an explicit unit. Known measured bases (mg COD/L, mg N/L, mg P/L, etc.) are checked without
converting them to molecular concentration. Molecular publication supports temperature,
pressure, flow and duty in the flowsheet units, and normalized mass/mole-fraction composition
over declared components. It never infers a conversion between these two publication shapes.
The adapter performs any explicit native-to-flowsheet conversion before returning the result.
DWSIM/IDAES continue using their established fill, deviation and energy-balance path.

Producer identity is `{tool: cheme process simulate, adapter: <id>, model: <model>}`. Foreign,
given and assumed cells are protected even if their display source looks similar. Obsolete
outputs of the same producer/case are removed. Contract-2 model fingerprints cover portable
configuration, mappings, declared source/data bytes and authored process state; only the same
producer's derived fields are excluded. A successful fill does not make itself stale.

Accepted evidence remains under `process/simulation-runs/<id>/`; `cheme-simulation-entry.json`
is the archived case entry. Rejected fill attempts use `process/simulation-attempts/<id>/` and
`cheme-attempt.json` with `accepted: false`. These do not replace the last successful entry.
`--check` discards staging and all evidence. Publication detects changed model inputs and changed
case-record bytes under the writer lock. See the ADR for rollback and crash boundaries.
The raw worker response and normalized adapter result are archived separately. If storage fails
during both publication and rollback, core names a retained `<id>-recovery/previous-sheet` for
manual recovery; it does not claim the interrupted pair of files is consistent.

## Time-series manifest

`trajectories` is a list of `cheme/trajectory/v1` objects inside the v2 result. Each has `path`,
`format: csv`, raw `sha256` hex digest, `time_variable`, `time_unit` (`s`, `min`, `h`, `day`),
`start`, `end`, `variables` (unique `name`, nonempty `unit`, optional `reference`) and
`final_snapshot: {time: <end>, selection: last-row, interpretation: instantaneous}`.
References use `{kind: stream|unit|instrument, id: <native-or-stable-id>, quantity: <optional>}`.
A stream reference with a quantity must match the final scalar's value and unit exactly.

CSV is UTF-8, with or without a BOM. Headers must equal the declared columns, all numerical
data must be finite, and observed times must match the declared integration interval. An
optional `event_side_column` allows `sample`, `before`, `after`; a duplicate timestamp is
permitted only for an adjacent `before` then `after` pair. Other repeats/reversals are refused.
The final row is an instantaneous snapshot, never an average or a steady-state assertion.
No binary MAT/FMU/native-result reader is required: preserve those files as opaque evidence.
Large arrays are not embedded in YAML or the API. The viewer displays outcome metadata and
links to saved evidence; plotting and live operation remain outside this interface.

## Future simulator considerations

| Simulator | Adapter and transport work still needed |
|---|---|
| Aspen Plus | Native assets, explicit variable/unit mappings, installed licensed environment, steady-state solve diagnostics; a session transport must close/release resources. |
| Aspen HYSYS | Native assets, session lifecycle, capabilities declared separately for steady-state/dynamic modes and actual integration/solver diagnostics. |
| Dymola | Modelica/native assets, initialization and bounded solver options, dynamic time/event data and final snapshot mapping; optional native outputs retained. |

These are interface design requirements from issue #290, not claims that any commercial
adapter works. Verify exact vendor APIs and supported versions when implementing them.
Dymola's vendor documentation describes scripting and FMI interoperability
([Dassault Systèmes](https://www.3ds.com/products/catia/dymola/export-capabilities-interfacing-other-software));
the transport must therefore accommodate more than a local Python-module assumption.

## Required tests for an adapter

Exercise a real minimal worker, missing interpreter/asset/module, malformed JSON, nonzero exit,
timeout and cleanup; numerical failure and partial integration; correct IDs, units, final
snapshot and trajectory events; binary staging/fingerprints; protected/foreign cells; check-only
immutability, concurrent edits and publication rollback. Cover CLI, read-only API, stream/PFD
staleness and outcome presentation. Tests must not require a commercial licence. Separately
record which real simulator baseline was rerun and its numerical comparison tolerances.
