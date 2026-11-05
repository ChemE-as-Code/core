# 0058. Semi-batch thermal screening: the MTT of what boils, the reactions that count, the MTSR over time, the gas release

- **Status:** Proposed
- **Date:** 2026-11-05

## Context

`cheme process reactor-hazards` screens a semi-batch by Stoessel's treatment (ADR 0050): the
dosed reactant's largest accumulation, and the cooling-failure temperature at the worst moment
as the MTSR. A vented batch leaves its gas out of the MTSR (ADR 0054). The batch library
entries built on 1.8.0 found four gaps (core#178; the "core limits" sections of the DESIGN.md
of benzyl-chloroformate-1, sodium-azide-1 and methylmagnesium-bromide-1):

1. **The default MTT** is the lowest normal boiling point of the liquid's components. With a
   dissolved gas that value means nothing: HCl at 188 K (benzyl chloroformate), methyl
   nitrite at 261 K (sodium azide) and methyl bromide at 277 K (Grignard). Each entry had to
   set `hazard.mtt` by hand. Above 110 kPa(a) the default gives no MTT at all, and under
   vacuum it takes the normal boiling point, which is higher than the boiling point at the
   vessel's pressure.
2. **Which reactions set dT_ad and the MTSR.** The screening takes the largest single reaction
   run to completion. A slow side reaction can then set both: dibenzyl carbonate gives 355.7 K
   in benzyl chloroformate, against about 300 K for the main reaction alone. There was no way
   to name the reactions that count, nor to see each reaction's value.
3. **The MTSR over time.** Only the worst moment was reported. An initiation charge or the end
   of a dosing segment had to be screened in scratch copies.
4. **The gas release.** With the vent blocked, the gas a cooling failure generates
   pressurises the vessel. A note named the vent's peak rate during normal operation, but gave
   no rate at the MTSR and no comparison with what the vent can pass.

The options for the MTT were a vapour-liquid equilibrium of the content (activity models,
Henry constants, all of them inputs a concept-stage entry lacks) or a rule on the declared
data. For the gas release they were a blocked-vent pressure model (head space, relief) or a
rate compared with a stated vent capacity.

## Decision

cheme-as-code extends the screening in `domains/safety/reaction_hazards.py`, in pure Python,
from the semi-batch model's own steps (`stirred_tank.solve_batch` records a `CoolingPoint` per
accepted step: its time, temperature, accumulation, each reaction's rise and the content).

1. **Default MTT.** The default MTT is the lowest boiling point of what boils in the liquid,
   at the reactor's pressure (its inlets' lowest). It leaves out three kinds of component:
   - a batch's vent components, even when charged;
   - the components of a dosed gas (a dose that declares `absorbed`);
   - dissolved gases, whose boiling point is below the process temperature `T_p`.

   A note names each one left out, and the JSON gives them as `mtt_left_out`. They boil off
   on a cooling failure; they do not boil the batch. When nothing else boils, the MTT needs
   `hazard.mtt` (`-missing`). From 90 to 110 kPa(a) the normal boiling point stands, as
   before. Outside that band the MTT comes from Clausius-Clapeyron,
   `1/T = 1/T_b - R ln(P/101.325)/dH_vap`, with the component's `heat_of_vaporization`.
   Without it:
   - under vacuum the normal boiling point stays, and a note says the MTT is lower;
   - above atmospheric pressure, a component that could set the MTT leaves the MTT missing,
     and a note names the `heat_of_vaporization` it needs. A component whose normal boiling
     point is above the lowest known one cannot set the MTT.
2. **Reactions that count.** `hazard.reactions: [ids]` names the reactions whose heat sets
   dT_ad and the MTSR. The default is unchanged: every reaction, the largest run to
   completion. With more than one reaction, or with that choice, the output gives the
   reactions counted and the reason (`counted_reactions`, `counted_basis`). It also gives each
   reaction alone (`per_reaction`): its dT_ad over the whole batch and its MTSR, for a
   semi-batch at its own worst moment and with that moment's time. The counted MTSR is the
   largest over time of `T + max over the counted j of rise_j`. With every reaction counted,
   this is the model's own cooling-failure temperature, to the last digit. A name the step
   does not hold is a warning, `cheme.reactor-hazard-reactions`, and every reaction then
   counts.
3. **MTSR profile.** A semi-batch reports `mtsr_profile`: time, `X_ac`, temperature and the
   counted MTSR at the model's steps nearest 21 even moments over the batch, plus the worst
   moment. These are values at steps, never interpolated. The text output gives a compact line
   of six of them and the worst.
4. **Gas release at the MTSR.** A vented batch or semi-batch reports `gas_release`: the rate
   at which the vent's components form, `f_g sum_j max(nu_gj M_j r_j, 0)`. Every reaction runs
   at its rate law, with the content of the worst moment (the accumulated reactant), at the
   MTSR and the vessel's pressure. That is an upper bound: the content reacts away as it heats.
   The rate is given in kmol/s and in m3/h at the MTSR and the vessel's pressure. It is per
   batch (`process/recipe.yaml`'s batch size), else per hour of the flowsheet's flows, and the
   output says which. The output also gives the gas one reaction, the largest, forms run to
   completion. The new rule `cheme.reactor-hazard-vent` reports it:
   - a warning without `hazard.vent_capacity` (m3/h at the vessel's pressure, from the vent
     sizing);
   - a warning above that capacity, or when there is no batch size to compare on;
   - info within it.

Stoessel's classes, the accumulation and the semi-batch model are unchanged. The new
`ReactionHazard` fields have `exclude_if`, so a reactor's dump and fingerprints stay as they
were. The JSON gives the new keys only when they hold something.

## Consequences

- Positive: the library entries' hand-set MTTs can go. In sodium-azide-1 the default is now
  methanol's 337.6 K, the value its authors set; in methylmagnesium-bromide-1 at 120 kPa(a) it
  is 356.5 K from 2-MeTHF's heat of vaporization.
- Positive: a side reaction no longer hides the main one. Benzyl chloroformate's PHOSG alone
  gives 300.2 K in the full model, against 355.7 K for the side reaction CARB, in one run.
- Positive: an initiation charge or the end of the dosing shows in the profile without scratch
  copies.
- Negative: two behaviours change for plants that do not use the new fields. They are fixes,
  stated in the CHANGELOG:
  - a vent component, a dosed gas and a dissolved gas no longer set the default MTT;
  - under vacuum a component with `heat_of_vaporization` boils lower.

  Every vented batch gets the new `-vent` warning until it states a vent capacity.
- Negative: the dissolved-gas rule follows the declared boiling points, not a phase
  equilibrium. A gas held in solution well above its boiling point (a solvate, a complex) is
  still left out, and a dissolved gas does not lower the liquor's boiling point.
- Known limitations: the products are not candidates for the MTT, only what is charged and
  dosed (as before). The blocked-vent pressure is not screened: there is no head space or
  relief model. Nor is a dissolved toxic gas boiling off on cooling failure (core#178 item 5).
  A deliberate excess of the dosed reagent still counts as accumulated (item 6). The profile
  is for a semi-batch only: a batch's worst moment is its start. Clausius-Clapeyron takes one
  heat of vaporization, and a component's Antoine `vapour_pressure` is not used for the MTT.

## Evidence

- core#178; this PR.
- `src/chemeascode/domains/safety/reaction_hazards.py` (`_default_mtt`, `boiling_point`,
  `_counted`, `_profile`, `_per_reaction`, `_gas`), `src/chemeascode/domains/process/
  stirred_tank.py` (`CoolingPoint`, `TankResult.cooling_profile`, `vent_gas_rate`),
  `src/chemeascode/domains/process/schema.py` (`ReactionHazard.reactions`, `.vent_capacity`).
- `tests/test_semibatch_screening.py` against closed forms (the first-order dosed semi-batch's
  profile, two parallel reactions, Clausius-Clapeyron, the gas rate `k(MTSR) n_A`);
  `tests/test_semibatch_vent.py` (the vent and dosed gas left out of the MTT).
