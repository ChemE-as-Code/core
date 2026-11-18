# 0065. Project-defined dynamic models through QSDsan

- **Status:** Proposed
- **Date:** 2026-11-09, revised 2026-11-16

## Context

A project can supply a Python wastewater model and its data. The numerical stack has its own dependency lock and interpreter. Core owns the engineering documents, the stream table and the case record.

## Decision

`process/simulation.yaml` declares a model identifier, a Python module, a primary input, an explicit list of module/data files and a timeout. Set `CHEME_QSDSAN_PYTHON` outside the repository to the absolute path to the numerical interpreter. Both `--check` and `--fill` execute **trusted project code with the user's permissions**. Temporary staging protects against accidental writes. A worker can access the host with the same privileges as the CLI. Review the declared code before execution.

Core copies the declared inputs into a fresh directory. It invokes the interpreter with `-E -s -B -X utf8 -m <worker> <request.json> <response.json>`, using a limited environment. The UTF-8 JSON request supplies `case`, `input`, `files`, `timeout_s` and a dedicated `evidence` output directory. The worker returns one `cheme/adapter-result/v1` object in the response file. Each returned stream has an existing ID, an empty `filled` list and quantities with numeric `value` and explicit `unit`. A worker may place additional evidence files inside the assigned directory.

Core validates the result, case, units and updated flowsheet, then publishes the calculated stream quantities, case record and a new evidence directory under `process/simulation-runs/`. Earlier evidence remains addressable. A failed worker or invalid response cannot publish results. Simultaneous fills are checked against the source snapshot. `--check` discards the staged computation. Project and diagram generation is a separate operation. Browse and validation operations only read.

## Consequences

Core and its viewer can be used without installing QSDsan. The numerical model and its accuracy remain the responsibility of the process project. See `examples/process-qsdsan` for the runnable protocol and the A2/O process-library project for the biological model.
