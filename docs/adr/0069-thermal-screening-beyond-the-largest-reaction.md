# 0069. Thermal screening beyond the largest reaction: the network, every dose, the release over the batch, the content's boiling

- **Status:** Proposed
- **Date:** 2026-11-12

## Context

ADR 0058 gave `cheme process reactor-hazards` the MTT of what boils, the reactions that count,
the MTSR over time and the gas release at the MTSR. The batch library entries built on 1.8.0 to
1.11.0 found what it still left to scratch scripts (core#178 and its comments; the "core
limits" of the entries' DESIGN.md):

1. **One dosed reactant.** The accumulation is the first dosed reactant's. In
   di-tert-butyl-dicarbonate-1 (L-1) that is the CO2, a deliberate excess at 10.1 %, not the
   phosgene's 2.7 %; the excess counts as accumulated although nothing is left to react with
   it (core#178 item 6; benzyl-chloroformate-1 L-1, 0.173 at the end).
2. **The release at one moment.** The gas release is taken at the highest MTSR only, where
   di-tert-butyl-dicarbonate-1's reaction forms no gas (3e-25 m3/h); its scratch script found
   24.5 m3/h over the cooling profile. p-toluenesulfonyl-chloride-1 and benzyl-bromide-1 ran
   the same script.
3. **The largest single reaction.** dT_ad and the MTSR take each reaction alone. A consecutive
   reaction on a product is missed: copper-i-chloride-1 (L-2) gets 36.9 K from the
   chlorination alone, 45.8 K by hand with the comproportionation on the copper(II) formed.
4. **The MTT from what is charged and dosed.** A product that boils lowest is no candidate
   (acetyl-chloride-1 L-5: acetyl chloride 324 K under PCl3's 349 K; benzoyl-chloride-1 L-5,
   iodomethane-1 L-5), and a dose that reacts away still sets it (benzyl-bromide-1 L-5:
   bromine's 332 K; the entry computed the content's bubble point, 393.7 K, by hand).
5. **A gas held in the liquid** (core#178 item 5). Dissolved phosgene (di-tert-butyl-
   dicarbonate-1 L-2) and chlorine (copper-i-chloride-1 L-3) boil off or are stripped on a
   cooling failure: neither inventory nor stripped rate was screened.
6. **A content boiling at the MTSR** (potassium-tert-butoxide-1 L-10). ADR 0062 flags it
   (`boils`) and reports only the non-condensables.

Options for 3 were a sequence of reactions run to completion in their declared order (the
result depends on the order), a kinetic run of the adiabatic cooling failure (the rate laws
leave the fitted range, and a fast reaction's stiffness), or the most heat any forward extents
release, a small linear programme. For 4 the options were a vapour-liquid equilibrium of the
content (activity models, Henry constants a concept-stage entry lacks) or Raoult's law over the
components' vapour pressures, which the entries already declare for the vent's vapour.

## Decision

cheme-as-code extends the screening in `domains/safety/reaction_hazards.py` and a new pure
Python module `domains/safety/reaction_network.py`, from the semi-batch model's steps (each
`CoolingPoint` now also keeps each reaction's heat of reaction and the content's heat capacity,
and the result the amount of each dosed reactant charged and dosed). Stoessel's classes, the
accumulation `X_ac` (the first dosed reactant's), the semi-batch model and the outlets are
unchanged.

1. **The network potential.** `max sum_j (-dHr_j) xi_j` over forward extents `xi_j >= 0` of
   the counted reactions with every component kept non-negative, `n_i + sum_j a_ij xi_j >= 0`
   (`a_ij = nu_ij` for a reactant, `nu_ij (1 - f_i)` for a product, `f_i` a vent component's
   vented share), by the simplex method with Bland's rule. One reaction alone gives its run to
   completion; a consecutive reaction on a product adds its heat; of parallel reactions
   competing for a reactant the more exothermic takes it. `hazard.potential: network` makes it
   set dT_ad, the MTSR at every step (the profile, the worst moment) and the gas release's
   content after the cooling failure; `largest`, the default, keeps ADR 0058's. A batch or
   semi-batch with a consecutive pair among its counted reactions reports it without the
   choice (`network`: `adiabatic_rise_K`, `mtsr_K`, a semi-batch's `time_s`, `consecutive`,
   `in_mtsr`; a text line; a note where it is above the largest single reaction's MTSR). A
   continuous reactor reports it only with the choice. A counted reaction without a known
   heat is left out of the programme; where the known ones then release no heat together,
   the network is not known (as dT_ad without it): dT_ad, the MTSR and the class stay unset,
   not dT_ad 0 and the MTSR `T_p`.
2. **Every dosed reactant.** A semi-batch reports, per dosed reactant, its largest
   accumulation and when (`max`, `time_s`), and of it the share the screened reactions can
   still consume from the content then (`reactive_max`, `reactive_time_s`): the same programme
   with the reactant's consumption as the objective, at most what is there. A deliberate
   excess with nothing left to react with is not reactive. JSON `accumulations`, given with
   more than one dosed reactant or where the reactive share is below the plain one.
3. **The largest gas release over the batch.** A vented semi-batch's `gas_release` gains
   `largest_over_batch`: at every step the vent gas its content forms at that step's MTSR
   (every reaction at its rate law), with the liquid's vapour where `vent.vapour` is declared
   (`G Y / (1 - Y)` at that MTSR), the largest in m3/h, its time, temperature, rate by
   component (the gas and each vapour) and its ratio to `hazard.vent_capacity`. The vapour
   takes its latent heat from the reactions' heat at that step, `Q = sum_j (-dHr_j) M_j r_j`,
   so it is at most `Q / sum_i y_i dHvap_i` (`heat_limited`): ADR 0062's saturated vapour
   diverges as `Y` nears 1, which this bounds, and a content boiling at that step's MTSR
   counts that boil-up (without the heats of reaction or vaporization, its non-condensables
   only). `cheme.reactor-hazard-vent` compares the larger of it and
   the release at the MTSR with the capacity, and names it in its message where it is larger.
4. **Products as MTT candidates; the bubble point.** The default MTT counts a product a
   counted reaction forms in the liquid: its share once that reaction alone (or the network,
   when counted) ran to completion of the charge and doses, a vented product with the share
   the liquid keeps. A product under `DISSOLVED` (5 %) of that liquid, or boiling below `T_p`
   (it leaves as it forms, or the vessel is pressurised), is no candidate, nor, above
   atmospheric pressure, one without `heat_of_vaporization` (a note names it where its normal
   boiling point is below the MTT). `hazard.mtt_from: bubble-point` takes the MTT instead
   from the content's bubble point at the vessel's pressure, `sum_i gamma_i x_i P_i^sat(T) =
   P` (Raoult's law, `gamma_i` of `vent.vapour.activity` where given, else 1; `P_i^sat` the
   Antoine `vapour_pressure`, else Clausius-Clapeyron from `normal_boiling_point` and
   `heat_of_vaporization`; a component with neither boiling point nor vapour pressure, or
   `phase: solid`, does not boil; one with a boiling point only leaves the MTT missing, named),
   the lower of the worst moment's content (a batch: its charge) and that content once the
   cooling failure ran its course (the reaction setting the MTSR, or the network). Left out:
   dissolved gases (ADR 0058), vent components and dosed gases boiling below `T_p`, and a
   product a counted reaction forms (not charged or dosed) boiling below `T_p`, as the default
   MTT leaves it out: gases held in solution that do not follow Raoult's law, counted in the
   liquid but not boiling. JSON `bubble_point`.
5. **Gases held in the liquid.** A batch or semi-batch reports `dissolved_release`: each dosed
   gas, dissolved gas and vent component boiling below the MTSR then (as the default MTT
   leaves them out) at its largest amount in the liquid over the batch (kmol and kg per
   batch, when), its boiling point at the vessel's pressure against the MTSR then, and, with
   `vent.vapour`, the most of it the gas release strips off the liquid over the batch
   (`stripped_kmol_s`, `stripped_kg_h`). A new rule, `cheme.reactor-hazard-dissolved` (info),
   names them: core does not know which gas is toxic.
6. **The boil-up.** A content that boils at the MTSR (ADR 0062's `boils`) gets
   `gas_release.boil_up`: its bubble point `T_b` over the vent's volatile components, the
   reactions' heat at their rate laws there from the worst moment's content, `Q = sum_j
   (-dHr_j) M_j r_j(T_b)` (per batch), and the vapour it boils off, `Q / sum_i y_i dHvap_i`
   with `y_i` the vapour's composition at `T_b`, in kmol/s and m3/h at `T_b` and the vessel's
   pressure (a tempered reaction), with its ratio to the vent capacity. The finding and the note
   name it.

New schema fields (`ReactionHazard.potential`, `.mtt_from`) have `exclude_if`, and the new
JSON keys appear only when they hold something, so a reactor's dump, its fingerprint and the
outlets stay as they were. A reactor with one reaction or no consecutive pair, one dosed
reactant without excess, no vent and no gas held in its liquid reports as in 1.11.0.

## Consequences

- Positive: the library's scratch scripts over the cooling profile can go. On the entries as
  they are (core 1.11.0 data): di-tert-butyl-dicarbonate-1's largest release is 24.54 m3/h at
  2.05 h (its D-011: 24.5 m3/h at 7367 s), its phosgene's accumulation 0.0266 (2.67 %), the
  CO2's reactive share 0.044 of its 0.101, the phosgene stripped at most 0.096 kg/h (its D-011
  on core's basis); benzyl-bromide-1's largest release 66.3 m3/h at 0.78 h (its D-014 found 72.8 m3/h at 0.38 h with the saturated vapour alone, which needs 9 % more heat than the bromination's -32.3 kJ/mol gives at that moment); potassium-tert-butoxide-1 at k/10 571 m3/h, its boil-up, where the saturated vapour alone gives 6669 m3/h at Y = 0.996;
  acetyl-chloride-1's 31.2 m3/h at 69 s; p-toluenesulfonyl-chloride-1's R101 145.5 m3/h,
  0.97 of its vent, against 0.40 at the MTSR. copper-i-chloride-1's network gives dT_ad
  46.0 K (45.8 by hand) and the MTSR 354.4 / 372.1 K at k and k/100 (354.4 / 372.1 by hand).
  Without `hazard.mtt` the default MTT is acetyl chloride's 324.1 K (set by hand),
  benzoyl chloride's 471.0 K (set by hand) and iodomethane's 315.7 K; with `mtt_from:
  bubble-point` benzyl-bromide-1 gets 393.5 K (393.7 K by hand) and iodomethane-1 330.8 K
  (its ideal liquid's 329.5 K).
- Positive: a single linear programme gives both the network's heat and what of a reactant
  can still react; it is exact at a vertex and independent of the declaration order.
- Negative: behaviour that changes for plants that do not use the new fields, fixes stated in the
  CHANGELOG: a product boiling lowest now sets the default MTT; the `-vent` finding of a vented
  semi-batch compares the largest release over the batch, so its level can rise (none of the
  library's entries changes level; the ratio quoted rises for p-toluenesulfonyl-chloride-1 R101 0.40
  -> 0.97 and Q101 0.08 -> 0.09, sodium-azide-1 R101 0.59 -> 0.89, potassium-tert-butoxide-1 R101
  0.67 -> 0.90 (the vapour of the early dosing), benzyl-bromide-1 0.66 -> 0.74, acetyl-chloride-1
  0.008 -> 0.62, di-tert-butyl-dicarbonate-1 0 -> 0.49 and benzoyl-chloride-1 0.825 -> 0.826). New
  JSON keys and text lines appear for semi-batches with several dosed reactants or an excess,
  batches and semi-batches with a consecutive reaction, vented semi-batches and reactors holding a
  dissolved or dosed gas, with a new info finding for the last. The MTT, MTSR and class of every
  core example and library entry are those of 1.11.0.
- Negative: the network runs every counted reaction forward to its most exothermic end, an
  upper bound: a side reaction counted with it adds its heat in full (keep it out with
  `hazard.reactions`); equilibrium and the rates are not used. The reactive share uses the
  screened reactions, not their rates.
- Known limitations: the bubble point is Raoult's law with constant activity coefficients,
  and a gas held in solution is left out rather than given its solubility; the boil-up
  takes the worst moment's content at `T_b` with no level swell, head space or two-phase
  relief (still no blocked-vent pressure); the largest release is per step at that step's
  MTSR, not along the cooling failure's path, and only it is heat-limited (the release at the
  MTSR keeps ADR 0062's saturated vapour); a reflux reactor's condenser against the
  boil-off at the MTT (iodomethane-1 L-9) and a closed vessel's pressure are not screened;
  core does not know which component is toxic, so the dissolved release is info.

## Evidence

- core#178; this PR.
- `src/chemeascode/domains/safety/reaction_network.py` (`simplex`, `network_heat`, `reactive`,
  `bubble_point`), `src/chemeascode/domains/safety/reaction_hazards.py` (`_batch_network`,
  `_semibatch_network`, `_accumulations`, `_over_batch`, `_boil_up`, `_dissolved_release`,
  `_products`, `_bubble_mtt`), `src/chemeascode/domains/process/stirred_tank.py`
  (`CoolingPoint.heats`, `.capacity`, `TankResult.dosed_reactants`, `extent_rates`,
  `vent_gas_rates`), `src/chemeascode/domains/process/schema.py` (`ReactionHazard.potential`,
  `.mtt_from`).
- `tests/test_screening_network.py` against closed forms (a linear programme's vertex, the
  network heat of consecutive, competing, shared and vented reactions and of copper(I)
  chloride, the reactive share of an excess, a Clausius-Clapeyron bubble point, a semi-batch's
  consecutive pair at every step, two dosed first-order reactants, a second-order excess, the
  gas rate `k(T) n_A` at each step's MTSR, the inventory of a dissolved and a dosed gas, the
  boil-up `1e5 k n_A / dHvap` at `T_b = b / (a - ln(P / x_S))`, a product setting the MTT,
  Raoult's bubble point of two contents).
