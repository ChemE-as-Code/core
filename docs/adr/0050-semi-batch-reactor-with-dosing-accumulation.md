# 0050. A semi-batch reactor with dosed feeds, its accumulation taken by the thermal screening

- **Status:** Proposed
- **Date:** 2026-11-05

## Context

Most fine-chemical reagents still missing from the process library (process-library#133 to
#167, plan core#158) are made by dosing an exothermic reagent into a charge. cheme-as-code had
`reactor: batch` (`domains/process/stirred_tank.py`, `solve_batch`): everything charged at
the start, then integrated over a time or to a target conversion. A dosed step could only be
modelled as that batch, which gets two things wrong:

- the composition and heat release over time: the reagent's concentration stays low while it
  is dosed, so the rate and the heat release are limited by the dosing;
- the thermal screening (`domains/safety/reaction_hazards.py`): every batch screened with an
  accumulation `X_ac = 1` (all charged, cooling fails at the start). Every dosing-controlled
  step therefore came out as Stoessel class 4 or 5, and the screening could not tell a step the
  dosing controls from one that accumulates its reagent.

Options considered:

1. A separate integrator and schema block for a semi-batch. This duplicates the batch's rate
   laws, energy balance and step control.
2. Dosing as component amounts on the batch (no stream). The dosed feed then appears nowhere
   in the flowsheet, and the balance, the LCI and the TEA miss it.
3. `reactor: semibatch` on the existing `batch:` block, with `dosing:` naming the dosed inlet
   streams; `solve_batch` takes the doses as sources. One integrator, and the dosed feed is a
   stream like any other.

## Decision

cheme-as-code takes option 3.

- **Schema** (`domains/process/schema.py`): `Batch.dosing: list[Dosing]`, where `Dosing` is
  `{stream, time | profile, start}`. `stream` is an inlet stream of the step, and its flow is
  the amount dosed per hour of charge (the batch's basis). `time` (s) doses at a constant rate.
  `profile` gives `[duration s, share]` segments at constant rates, with shares adding up to 1.
  `start` (s) delays the dose. With dosing, `time` or `target` is the post-reaction after the
  last dose, and the batch may also end with the dosing (neither given). `dosing` is left out
  of the dump when empty, so a batch's outlet fingerprint does not change.
  `Reacting.reactor` gains `semibatch`, which reads the `batch:` block.
- **Model** (`stirred_tank.solve_batch(..., doses)`): the batch's balances with the doses as
  piecewise-constant sources, `dn_i/dt = sum_j nu_ij M_j r_j + sum_d F_d,i`, and adiabatically
  each dose's sensible heat, `C_d (T_d - T)`. The same Dormand-Prince stepper runs segment by
  segment between the doses' break points, then over the post-reaction. A semi-batch is liquid
  only; a gas is refused. A batch without doses is integrated exactly as before.
- **Report** (`TankResult`, `process reactors` `tank` entry): `dosing_time_s`,
  `charge_volume_m3`, the accumulation profile and its maximum,
  `X(t) = n_reagent(t) / (charged + dosed)` for the first dosed reactant, the cooling failure
  at its worst moment, and the peak cooling duty. The cooling failure is the time, the
  temperature, and `T + max_j(-dHr_j xi_j,max(n)) / C(n)`, the content reacting to completion
  adiabatically with the dosing stopped. The peak cooling duty (isothermal) is the reaction's
  heat plus the doses' warming, in kW per m3 of the final content: an intensive figure that
  the vessel and jacket check (core#158 package 3) scales by the working volume.
- **Screening** (`reaction_hazards.screen_node`): for a semi-batch, `X_ac` is the maximum
  accumulation, `MTSR` the cooling-failure temperature at the worst moment, and `T_p` the
  temperature then. `dT_ad` is that of the whole batch, charge and doses. Using the content's
  heat capacity at that moment is more conservative than `T_p + X_ac dT_ad` with the final
  heat capacity; the latter is used only when no cooling-failure temperature can be computed.
  A batch keeps `X_ac = 1`.
- **Rules** (`cheme.process-reactor`, errors): a `batch` with `dosing`, a `semibatch` without
  it, a dosed stream that is no inlet of the step, more or fewer than one charge stream besides
  the doses, a reaction that is not liquid-phase. The batch's own rules (rate laws, one phase,
  heat data of an adiabatic liquid) apply to a semi-batch too.
- **Elsewhere**: `process propagate --fill` writes the outlet (all inlets react to one
  outlet). `process reactor-uncertainty` samples it, with the key's conversion taken over all
  that was charged and dosed. `datasheets fill` leaves the volume and duty TBD, as for a batch,
  until the batch size is known (package 2). The model basis reports it as kinetic with its
  own assumptions (`ASSUMPTIONS["semibatch"]`).
- **DWSIM**: `process simulate` refuses a semi-batch with a translate failure. DWSIM's
  reactors take one inlet stream, and the outer loop (`simulation/coupling.py`) reads one.

## Consequences

- Positive: the reaction-hazard screening separates dosing-controlled steps (low `X_ac`, low
  class) from accumulating ones. The analytic first-order case
  `X_max = (1 - exp(-k t_d)) / (k t_d)` is reproduced to 1e-6, and a fast and a slow reaction
  with the same dose and heat land in class 1 and class 4.
- Positive: the dosed feed is a flowsheet stream, so balance, LCI and TEA see it without
  further work.
- Negative: the dosing rate is fixed by the declaration; there is no control of the dosing
  on the accumulation or temperature (a later `domains/control` sequence or phase logic,
  core#158 package 6).
- Limitations: liquid only; each dose mixes in at once (no feed-pipe or mixing time); one
  dosed reactant's accumulation is reported (the first dosed reactant); no DWSIM coupling;
  the cooling-failure temperature uses the largest single reaction run to completion, as the
  batch's `dT_ad` does, and no secondary decomposition (the TD24 comes from calorimetry only).
- Follow-ups: the batch size and recipe (package 2) turn the per-hour-of-charge basis into
  batches and size the vessel and jacket (package 3) from the peak cooling duty.

## Evidence

- core#158 (plan), this ADR's PR.
- `src/chemeascode/domains/process/stirred_tank.py` (`Dose`, `solve_batch`, `split_inlets`,
  `tank_inlet`), `schema.py` (`Dosing`, `Batch.dosing`), `model.py` (`_dosing_rules`),
  `reactors.py` (`semibatch_entry`), `domains/safety/reaction_hazards.py`
  (`_screen_semibatch`).
- `tests/test_semibatch.py`; `examples/process-semibatch`.
- Stoessel, F. (1993) What is your thermal risk? Chem. Eng. Prog. 89(10), 68-75; Stoessel, F.
  (2008) Thermal Safety of Chemical Processes, Wiley-VCH, chapters 3 and 7 (semi-batch
  accumulation and MTSR).
