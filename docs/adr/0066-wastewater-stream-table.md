# 0066. Wastewater results in the native stream table

- **Status:** Proposed
- **Date:** 2026-11-09

## Context

ADR 0065 records QSDsan stream outputs with explicit measurement bases, but the native
Stream table only displays molecular properties. Interpreting m3/day as kg/h or COD/N/P
fractions as molecular composition would be incorrect.

## Decision

Extend `GET /api/streams` additively for `simulator: qsdsan`. A pure process-domain
projection joins the selected case's saved `process/simulation-run.json` by stream id.
It adds `wastewater` metadata and per-row `wastewater` quantities without changing the
existing `properties`, `composition`, `units` or `balances`. The same Snapshot and
simulation-view helper provide revision, case selection and input fingerprint comparison.
Serving never executes a simulator or writes to a process repository.

Columns are liquid flow (m3/day), COD (mg COD/L), TN and NH4-N (mg N/L), TP and PO4-P
(mg P/L), and TSS (mg TSS/L). Values retain their recorded numbers and unit strings.
Only finite JSON numbers with the expected measurement basis are displayed. Missing,
wrong-unit or invalid cells are absent, never replaced with zero. Mismatched cases or
simulators, failed runs and duplicate stream ids do not populate the table. Findings
identify the record, rule and recovery hint. Stale runs remain inspectable with warnings
on both the record and its cells; absent input currency is not presented as verified.

The viewer displays these quantities directly in its existing Stream table, preserving
stream connections, BFD links, case/revision selection and filters. The existing molecular
balance panel is separately labelled and initially collapsed for wastewater. It is not
reinterpreted as a dynamic COD/N/P balance. Chemical-process tables retain their original
columns and calculations. No new simulation or plant file schema is required.

## Consequences

- Users can inspect the saved A2/O run inside the native viewer without rerunning it.
- Values are final simulated-time outputs, not evidence of steady state, plant validation,
  regulatory compliance or whole-system elemental conservation.
- This extends the display limitation of ADR 0065; numerical workers remain unchanged.
- The first supported dataset is the bounded QSDsan A2/O adapter. Other wastewater models
  require their own reviewed result contract, not automatic conversion or guessed units.
- `tests/test_process_wastewater.py` checks projection, missing/invalid values, case and
  simulator matching, stale inputs and read-only API behavior. `viewer/e2e/wastewater.spec.ts`
  checks native display. Existing process/simulation tests cover chemical-process compatibility.
