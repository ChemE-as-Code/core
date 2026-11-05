# 0059. Batch models write and check the duty of their energy streams

- **Status:** Proposed
- **Date:** 2026-11-05

## Context

The batch models know the heat they exchange. The semi-batch integrates the heat its reactions
release (ADR 0050), the batch still the latent heat of its boil-up (ADR 0055), the crystallizer
its lumped duty (ADR 0025), and a conversion step's declared heats of reaction give its heat
at a temperature. But `cheme process propagate` wrote only material streams. Only the dryer
compared its heating stream with its model (`dryer.energy.port`, `cheme.process-dryer-duty`,
ADR 0057). The batch entries of the process library (core#180) typed every duty by hand from
`cheme process reactors`, `stills` and `crystallizers`: benzyl-chloroformate-1 Q2, Q4 and Q5
(lesson L-8), sodium-azide-1 Q1 to Q6 (L-7), methylmagnesium-bromide-1 Q1 (L-9),
n-bromosuccinimide-1 Q2 (by a balance script). The values went stale silently when a model
input changed, and `process reactors` printed the duty of a liquid batch as `?` (it has no
ideal-gas data).

Options considered:

1. **A report only**, as the dryer: the stream stays typed by hand, the report compares. The
   hand step and its staleness stay.
2. **Each model's own port** (`batch.energy_port`, `still.energy_port`, `crystallizer.energy.
   port`, ...): four places for one idea, and a conversion step has no model block to hold it.
3. **One node-level `energy_port`, and propagate writes the duty** (chosen): the duty is a
   derived value like an outlet's flow, `calculated` with a fingerprint, never over a given or
   assumed one; a given one is compared.

## Decision

- **Which models.** `cheme process propagate` derives the duty of four models, as heat into
  the block or step per hour of the flowsheet's flows (the year average, ADR 0051):
  - an isothermal `reactor: batch` or `semibatch`: `-sum_j dHr_j xi_j + sum_d C_d (T - T_d)`,
    the heat its reactions release over the batch (as `heat_released` integrates it) and each
    dose warmed from its own temperature to the batch's (a dosed gas passing to the vent too,
    where its ideal-gas data are known). The charge's heat-up is a heat operation of the
    recipe, not part of the model (it holds the batch at its temperature from the start). An
    adiabatic batch has no duty.
  - a `still:`: its energy per batch over the batch's hours of flows, `sum_i dHvap_i D_i`
    (D_i the kmol/h distilled). The boil-up rate changes its time, not this duty.
  - a `crystallizer:` with `energy:`: its lumped duty.
  - a conversion step (`reactions:` with conversions, `reactor: conversion`, or a
    `selectivity:`): `sum_j xi_j dHr_j` with the declared `heat_of_reaction` at the outlet's
    temperature (taken as declared, as the batch models take it), every inlet brought from
    its temperature to it and every other outlet from it to its own, at the
    `liquid_heat_capacity` (the ideal-gas enthalpy for a stream whose phase is vapour, or a
    component without a liquid one). A gas-phase step whose components all have `ideal_gas`
    data takes `H(out) - H(in)` on the elements basis instead. Without the heats: no duty.
- **Which stream.** A block or step may give `energy_port: PORT`; without it the duty goes on
  its one heat stream: an energy stream whose other end is a block or step, or a utility
  terminal of kind steam, hot_oil, fired_heat, cooling_water, air_cooling or refrigerant.
  Electricity, fuel, other and a terminal without `utility:` are not heat, so an agitator's
  power never takes a reaction's heat. Several heat streams and no `energy_port`: nothing is
  written (`cheme.process-duty`, info).
- **Sign.** The convention of `domains/process/energy.py` and the dryer is kept: a duty is
  positive in its stream's direction. A stream into the node carries the heat in, a stream out
  of it the heat removed. A model whose heat flows against the stream's direction is a warning
  (`cheme.process-duty`), never written as a negative duty.
- **Provenance.** The duty is `calculated`, source `cheme process propagate: <model> duty
  <node> from <streams>`, with a fingerprint of what it depends on (the model's inputs as its
  outlets' fingerprints hold them, the heats of vaporization or reaction, the heat capacities,
  the streams' temperatures and the direction). It goes stale like any propagated value
  (`cheme.process-calculated-stale`). A flow-style stream (`{id: Q1, ...}` on one line, the
  library's usual form) is written in place.
- **Comparison.** A given or assumed duty is never overwritten. One that differs from the
  model's beyond the flowsheet's relative tolerance (as `cheme.process-dryer-duty`) is
  `cheme.process-duty`, a warning that names both values, from `process propagate --fill` and
  `--check`. A value calculated by `process simulate` is neither overwritten nor compared.
- **Rules.** `validate` reports `cheme.process-energy-port`: a port that is no energy port of
  the node (error), or one on a node no model gives a duty (warning).
- **Reports.** `process reactors` gives a batch's and a conversion step's `model_duty` (heat,
  terms, basis, missing, its stream and that stream's duty) and prints it where the ideal-gas
  duty is `?`; `process stills` adds the year-average duty.
- **Unchanged behaviour.** `energy_port` is left out of a node's dump when not given. A plant
  whose batch, still, crystallizer and conversion steps have no heat stream solves, reports and
  fingerprints as in 1.8.0 (every example does: `process propagate --check` prints the same).
  A plant whose step has one heat stream gets its duty written when the stream has none, and a
  warning, not an error, when a typed duty differs.

## Consequences

- Positive: a batch plant's duties follow from its models and go stale when a model input
  changes. The library's hand-typed duties are checked: on scratch copies the semi-batches of
  n-bromosuccinimide-1 (5.348 kW), methylmagnesium-bromide-1 (134.10 kW) and sodium-azide-1 R101
  (17.2171 kW), the stills T101 (1.178 kW) and ST101 (186.235 kW) and the crystallizer CR101
  (13.0999 kW) agree with them; benzyl-chloroformate-1 Q2 (its hand-added heat of absorption)
  and sodium-azide-1 Q2 (no dose warming) are named as differing.
- Negative: one duty per node. A reactor heated up by steam and cooled by brine, a still with
  its condensers, gets the model's net duty on the stream it names; the charge's heat-up, the
  condensers' duties (a cut's latent heat) and agitation stay typed by hand. A batch's duty is a
  year average, not the peak a jacket must take (the recipe's jacket check, ADR 0052).
- Limitations: no heat of absorption or solution of a dissolving gas (ADR 0054); a conversion
  step's heats of reaction are taken at the outlet's temperature as declared (no Kirchhoff
  correction to their own temperature), with constant liquid heat capacities; no heats of
  mixing. The dryer keeps its own comparison (`cheme.process-dryer-duty`) and is not written.
  `process simulate` does not couple batches, so the energy balance of a batch step
  (`process energy`) still needs enthalpies.
- Follow-ups: per-cut condenser duties of a still, a heat-up duty from the recipe's `heat`
  operation, the dryer's duty written like the others.

## Evidence

- core#180; this ADR's PR.
- `src/chemeascode/domains/process/duties.py` (the models' duties, the target stream, the
  rules), `propagate.py` (`_duty`, `_flow_edit`), `stirred_tank.py` (`TankResult.heat_terms`),
  `reactors.py` (`model_duty`), `batch_still.py` (`year_average_duty_kW`), `schema.py`
  (`Energetic.energy_port`), `model.py` (the rules).
- `tests/test_duties.py`: the batch's and semi-batch's heat against dHr x the extent and n cp
  dT, the still's against `sum dHvap_i D_i`, Felder's crystallizer against its lumped balance,
  a conversion step against Hess's path; the comparison, the direction, the energy port and
  plants without heat streams.
- process-library `benzyl-chloroformate-1`, `sodium-azide-1`, `methylmagnesium-bromide-1`,
  `n-bromosuccinimide-1` DESIGN.md core limits (scratch copies, not committed).
