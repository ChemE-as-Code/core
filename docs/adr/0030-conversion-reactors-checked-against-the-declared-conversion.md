# 0030. Conversion reactors checked against the declared conversion

- **Status:** Accepted
- **Date:** 2026-10-27

## Context

`cheme process simulate` hands a step with `reactions:` to DWSIM 9.0.5 as a conversion reactor
(ADR 0014). DWSIM applies each reaction's conversion to its key component in the reaction's
phase of the reactor inlet only: `phase: liquid` converts the key in the inlet's liquid,
`vapor` in its vapour, `mixed` in the whole inlet. An inlet the property package splits
therefore reaches less than the declared conversion, without a message. On liquid-phase MTBE
synthesis (isobutene + methanol, stoichiometric liquid feeds, 2000 kPa(a), declared complete
conversion; `tests/test_process_simulate_energy_liquid.py`) Peng-Robinson splits off 0.5 %
"vapour" at 277.5 K (conversion 0.9943), PR78 0.15 % at 298.15 K (0.9985) and SRK 17.6 %
(0.8146); the "vapour" is most likely a second liquid labelled vapour. The worker returned no
extents for a conversion reactor and nothing compared the outcome with the declaration
(pre-release issue 371). DWSIM's behaviour is not ours to change; the run has to make it visible.

Options considered: a warning (the issue's suggestion), an error, or refusing liquid-phase
reactions on two-phase inlets before the solve (the phase split is only known after it).

## Decision

After a converged run, `simulation/conversion.py` compares every native conversion reactor
(coupled kinetic beds and equilibrium or Gibbs reactors are not compared) with its declaration:

- From DWSIM's inlet and outlet streams (molar flow, overall mole fractions) it computes, per key
  component, the achieved conversion `(n_in - n_out) / n_in` and the declared one, the
  consumption the declared conversions give on the whole inlet, every reaction converting its
  key's inlet flow in parallel (the worker gives all reactions one rank, which DWSIM applies so,
  checked live against `cheme process propagate`). Several reactions on one key add up.
- Where the reactions' stoichiometry is independent it also reports the extents (least squares,
  `chemistry.reactions.fit_extents`) and each reaction's achieved conversion, as the unit's
  `extents_kmol_h` and `conversions` in the summary and the run record.
- A key conversion off the declared one by more than 0.001 (absolute, fraction of the key's
  inlet flow) is `cheme.process-sim-conversion-mismatch`, level **error**, in
  `process/simulation.yaml` at the reactor's specs, with the inlet's vapour fraction in the
  message and a hint to bring the inlet to one phase or declare `phase: mixed` (or, for a
  `mixed` reaction or a one-phase inlet, to check that no co-reactant runs out first).

The tolerance: DWSIM applies a conversion directly, without iteration, and on a one-phase inlet
the recorded MTBE run reproduces the declared conversion within 1e-8; 0.001 is far above that
noise, below the smallest phase-split shortfall observed (PR78, 0.0015) and finer than a
declared conversion is usually known. It is an error, not a warning, because the stream values
written then follow a different reactor than the one declared: the run fails closed
(`predictive.converged` requires a run without errors), the values are still written and
recorded so the shortfall can be inspected.

## Consequences

- Positive: a conversion reactor short of (or beyond) its declaration can no longer pass
  unnoticed; conversion reactors report extents and conversions like the other reactors.
- Positive: infeasible declarations (a co-reactant exhausted before the key) are caught by the
  same comparison.
- Negative: a plant that relied on a split inlet now fails `predictive.converged` until the
  inlet is brought to one phase or the reaction is declared `mixed`.
- Known limitations: a reactor whose run message names it (liquid formed in a one-outlet
  reactor) or whose streams are missing is not compared; dependent reactions get no per-reaction
  extents (only the key's conversion); the comparison assumes the parallel (one-rank) reaction
  set the worker writes.

## Evidence

- pre-release issue 371.
- `src/chemeascode/domains/process/simulation/conversion.py`, wired in
  `src/chemeascode/domains/process/simulation/run.py`.
- `tests/test_process_simulate_conversion.py` (replayed DWSIM results: one liquid, SRK's split,
  the tolerance, parallel and independent reactions, through `simulate` and the record);
  `tests/test_process_simulate_energy_liquid.py` (DWSIM-gated: the finding for PR78 and SRK, not
  for Peng-Robinson).
