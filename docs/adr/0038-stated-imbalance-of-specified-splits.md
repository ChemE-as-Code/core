# 0038. A specified split's energy imbalance is stated, and the plant closure takes it

- **Status:** Proposed
- **Date:** 2026-10-30

## Context

The simulation's energy audit (`domains/process/simulation/energy.py`, `cheme process energy`,
`predictive.energy-closure`) closes every unit and the plant on the solved stream enthalpies.
A `component_separator` (DWSIM's ComponentSeparator) splits its feed by given recoveries
(`basis: specified`), so nothing in it conserves energy: its outlets' enthalpy differs from
its inlet's by whatever the split implies. DWSIM reports that difference as `EnergyImb`, but
the sign of `EnergyImb` was never shown, so the audit refused the unit
(`sim-energy-unsupported`, "the sign of the component separator's energy imbalance is not
established") and with it the whole plant. In the ammonia-1 platform run (core#60,
process-library#86, D-024) every reactor closed but the plant audit stayed `unsupported`
because of C301 (aMDEA CO2 removal) and X401 (dryer). The specified split is the documented
fallback for units core cannot simulate (electrolyte absorption, adsorption, drying,
membranes), so no plant that relies on it could show its energy closure.

Options considered:

1. Establish the sign of `EnergyImb` in a live DWSIM test and use it as a duty. That needs
   DWSIM, and it would still count a bookkeeping number as a heat duty.
2. Leave the plant unsupported (the status quo).
3. Take the imbalance from the solved streams themselves (enthalpy out minus in, the same
   enthalpy flows every other closure uses), state it with a fixed sign convention, and close
   the plant with it as a stated residual. `EnergyImb` is then not needed. Each run records how
   it relates to the streams' value.

## Decision

cheme-as-code takes option 3.

- A specified split (`STATED_UNITS`: `component_separator`) gets `status: stated` in
  `energy.closure.units`, with `imbalance_kW` = sum of outlet enthalpy flows minus sum of inlet
  enthalpy flows (kW, simulator enthalpies), `sign_convention` (positive: the heat the unit
  would have to take in for its balance to close), `heat_in_kW` equal to it, the enthalpy flows
  and the unit tolerance. It is not judged: no `residual_kW`, never `sim-energy-unbalanced`.
- The simulator's `EnergyImb` (the worker's `duty_kW`) is recorded as `simulator_imbalance_kW`
  with `simulator_convention`: `out-minus-in` or `in-minus-out` (it equals the stated value
  or its negative within the tolerance), `negligible`, `differs` or `not-reported`. The
  closure never relies on it.
- The plant closure adds `stated_kW` (the sum) and `stated` (unit -> kW). Its residual is
  boundary enthalpy out minus in (plus the formation term) minus the units' heat and work
  minus `stated_kW`; `heat_in_kW` stays the units' heat without the stated imbalances. The
  tolerance counts `|stated_kW|` with the duties.
- A specified split whose imbalance exceeds its tolerance gives `cheme.process-sim-energy-stated`
  (info), which names the value and its sign. A specified split without stream enthalpies
  makes the plant `not-evaluable`, with the reason.
- The stated imbalance is not a utility (`utilities` does not count it). The real unit's
  duties (regenerator reboiler, dryer heating) are not modelled by the split and are
  accounted for separately.
- `predictive.energy-closure` passes on a plant that closes with stated imbalances, and its
  detail names them. Runs recorded before this change keep their `unsupported` plant until
  they are simulated again; `cheme process energy` says so.
- `cheme process simulate` still writes no duty to a separator's energy stream (`run.py`
  `_into_unit`).

## Consequences

- Positive: plants that keep a specified split for a unit core cannot simulate get a plant
  energy verdict. The verdict tests the rest of the flowsheet (every other unit, recycle
  convergence) and shows the split's imbalance as a number with a sign. It does not depend on
  an unverified simulator sign, and every run records evidence for DWSIM's convention.
- Negative: a large stated imbalance can hide a real modelling gap (the energy a real absorber
  or dryer needs). It is shown as an info finding and in the plant line, not as a failure.
  Reviewers have to read it.
- Open: once `simulator_convention` has been observed in live runs, the energy stream of a
  separator could carry its duty (`run.py`). The record does not keep per-stream enthalpies,
  so an older run cannot be re-audited without simulating again.

## Evidence

- Issue core#60.
- `src/chemeascode/domains/process/simulation/energy.py` (`_stated`, `_closure`),
  `src/chemeascode/domains/process/energy.py` (`energy_text`),
  `src/chemeascode/project/maturity.py` (`_energy_audit`).
- `tests/test_energy_closure.py` (specified-split tests).
