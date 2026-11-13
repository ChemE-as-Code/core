# 0075. The rest of a batch's energy balance: a recipe heat on its stream, the heat-up apart, a charged solid's heat of solution, agitation, a still's sensible rise and losses, a dryer's metal

- **Status:** Proposed
- **Date:** 2026-11-13

## Context

ADR 0063 (core 1.10.0) put a dose's heat of solution, the charge's heat-up and a recipe
vessel's metal into the batch models' duties; ADR 0068 timed a still's heat-up; ADR 0071 added
the heat of absorption. core#191 and its two comments still listed, from the process library's
batch entries:

- methyltriphenylphosphonium-bromide-1 L-8: the heat of solution of a charged (not dosed)
  solid, the PPh3, kept by hand in its charge's temperature;
- acetyl-chloride-1 L-11: the heat of mixing and of the phase separation;
- the heat of a recipe `heat` or `cool` operation is reported (ADR 0063), not written on an
  energy stream: methyltriphenylphosphonium-bromide-1's and potassium-tert-butoxide-1's Q1 are
  hand streams copied from `cheme process recipe`;
- metal and heat-up for conversion steps;
- the still's sensible rise while it boils, and its heat losses;
- potassium-tert-butoxide-1 L-5: the dryer heats its vessel's metal from the wet cake's
  temperature, not from the temperature its vessel was cooled to before the discharge; the
  entry scaled the dryer's `vessel_heat_capacity` by hand (2000 to 4075 kJ/K);
- potassium-tert-butoxide-1 L-6: a cool-down in a dryer's vessel has no model and no jacket
  time (`cheme.recipe-duration` refused a `cool` with `temperatures` there);
- potassium-tert-butoxide-1 L-11: with `batch.heat_up` the steam of the warm-up and the
  cooling water of the reaction are netted on one stream, so the warm-up stays a pass-through
  step with a hand duty;
- potassium-tert-butoxide-1 and tert-butyldimethylsilyl-chloride-1 L-12: an agitator's power,
  which ends as heat in the content, is in no model's energy balance.

Options considered: (1) an enthalpy balance of each vessel over the whole recipe, every
operation's content and temperature tracked from one to the next: it would need what the
concept stage does not know (the content of a charge or transfer operation, each one's heat
losses) and would change every batch plant's duties; (2) small, separately opted-in terms in
the models that already know the time and the temperatures, and a stream for the recipe's
existing heat report (chosen). Every term is opt-in, so a plant that uses none of them solves,
propagates, fingerprints and reports as in 1.12.0.

## Decision

- **A recipe operation's heat on its stream.** `Operation.stream` on a `heat` or `cool` with
  `temperatures` (schema error without them) names an energy stream with one end at a block or
  step of the unit procedure (`recipe._nodes`) that no model's duty goes on (`duties.target`,
  the still's and vent condenser's, the heat-up port; `cheme.recipe-reference` otherwise).
  `recipe.stream_heats` gives its heat into the content, `(C + C_m)(T_1 - T_0)` per batch (C
  the batch's charge before its dose, else its end, as the jacket time takes it; a dryer's wet
  cake before the `dry`, else its product; `C_m` the vessel's `metal_heat_capacity`, or 0),
  over the batch's hours of flows, as the models' duties (not the recipe's cycle: the two agree
  within the `cheme.recipe-basis` tolerance). `cheme process propagate` writes it `calculated`
  in the stream's direction, its fingerprint the operation, the content's and metal's kJ/K,
  the hours and the unit's inlets and batch-size stream; a given or assumed duty is compared
  (`cheme.process-duty`, from validate too). `process recipe` lists the operation in `heats`
  with its `stream` even in a vessel without metal; a heat on no stream reports as in 1.12.0.
- **The heat-up on its own stream.** `batch.heat_up_port: PORT` (with `heat_up`; schema error
  otherwise) takes the terms `charge heat-up` and `vessel metal` of a batch's duty to the
  energy stream at that port (`duties.split_heat_up`, `heat_up_target`), the rest to the
  model's `energy_port` or one heat stream, which no longer considers that port. `process
  reactors` adds `model_duty.heat_up`. A port that is no energy port of the node, or is its
  `energy_port`, is `cheme.process-energy-port` (error).
- **A charged solid's heat of solution.** `batch.heat_of_solution` (an isothermal batch or
  semi-batch; schema error on an adiabatic one, whose charge temperature is the one after it
  dissolved) is the integral heat per kmol charged, `HeatOfSolution` as a dose's. It is
  released as the charge dissolves, before the batch reacts: in the duty's term `solution`
  (`sum n_0 dH_sol`), and a share the vent's vapour takes off the liquid takes it back as a
  dose's does (ADR 0063: the mean over all of it that entered the liquid); not in the peak
  cooling duty, the jacket check or the screening (nothing of it is released at a rate or
  accumulated). Rules as a dose's (`cheme.process-reactor`): an undeclared component (error),
  one the charge does not carry (warning).
- **Agitation.** `AgitatorPower {value: kW}` on `batch.agitator_power` (isothermal) and
  `still.agitator_power`: the shaft power that ends as heat in the content while the model runs
  (the batch's dosing and reaction time; the still's boil-up time), the term `agitation`,
  `-P t` over the batch's hours of flows. A batch takes those hours from
  `process/recipe.yaml` (its duty is not known without them, and says so). The recipe adds `P`
  to the batch's peak duty for the jacket check.
- **A still's sensible rise and heat losses** (volatility raoult, schema error otherwise).
  `still.sensible_heat: true`: the pot's content heated as its bubble point rises while it
  boils, `int C dT = [C (T - T_0)] - int (T - T_0) sum_i cp_i dN_i` over each integration step,
  the integral by composite Simpson's rule over `SUBSTEPS` (8) dense evaluations of the step;
  every pot component's `liquid_heat_capacity` (separate-phase and non-volatile ones too).
  `still.heat_loss: {ua: W/K, ambient_temperature: K}`: `UA int (T - T_amb) dt` over the
  boil-up. Both are computed beside the integration, never in its state, so the cuts, the
  residue and the time are those without them. The terms `sensible rise` and `heat losses`;
  with `heat_up_time` (ADR 0068) the positive ones take time as the heat-up does. Not in them:
  the column's holdup, the step between cuts at a new pressure, a portion mixing in, the
  losses during the heat-up or a hold.
- **A conversion step's metal.** `vessel_metal: true` on a conversion step (node level,
  `Energetic`) in a recipe vessel with `metal_heat_capacity` adds the term `vessel metal` from
  its inlets' temperature to its outlets' (each side's mean weighted by its heat capacity, as
  the Hess path takes it). Its content's heat-up is in its Hess path already (ADR 0059: each
  inlet from its temperature, each outlet to its own). On a node that is no conversion step,
  or in no such vessel, it is a `cheme.process-duty` warning.
- **A dryer's metal and a cool-down in its vessel.** A dryer's unit procedure's
  `vessel.metal_heat_capacity`, which 1.12.0 ignored for a dryer, is the dryer's metal
  (`recipe.dryer_metal`): `C_m (T - T_left) / h_batch`, `T_left` the end temperature of the
  last operation with `temperatures` before the `dry` in the procedure's cycle (a cool-down
  before the discharge), else the wet cake's. With the dryer's own `energy.vessel_heat_capacity`
  too it is an error (`cheme.recipe-vessel`, and the dryer's energy lists it as missing). A
  `heat` or `cool` with `temperatures` in a dryer's vessel, refused by 1.12.0, takes its time
  from the jacket, `(C + C_m) / (U A) ln(...)`, C the wet cake's (before the `dry`) or the
  product's (after it) at the components' `liquid_heat_capacity`, A the jacket's `area` or the
  vessel's heated area. A filter's vessel keeps the refusal.
- **Fingerprints.** Every new field is left out of its dump when not given (`exclude_if`).
  `batch.heat_up_port`, `heat_of_solution` and `agitator_power` are in `stirred_tank.duty_only`;
  a still's `sensible_heat`, `heat_loss` and `agitator_power` in `batch_still.STILL_DUTY_ONLY`;
  `vessel_metal` in `recycle.NOT_SWEPT`: none is in the outlets' or a tear's fingerprint. Each
  is in its duty's fingerprint (`ModelDuty.inputs`).

## Consequences

- Positive: closed forms hold (`tests/test_batch_energy.py`): the heat-up on its own stream,
  `n cp dT + C_m dT / h`, and the rest as the duty without `heat_up`; the agitator's `-P t /
  h`; a charged heat of solution's `n_0 dH_sol` with the outlet and the peak cooling duty
  unchanged; a recipe heat-up's `(C + C_m) dT / h` on its stream, stale when the operation
  changes; a conversion step's metal `C_m (T_out - T_in) / h`; a dryer's metal from a
  cool-down's end temperature, and the cool-down's jacket time and heat; a still's sensible
  rise and heat loss against quadratures of their integrals along Raoult's bubble point to
  1e-6.
- Positive: on a scratch copy of potassium-tert-butoxide-1 (process-library main), REACT's
  `heat` operation with `stream: Q1` and Q1's hand duty removed: `process propagate --fill`
  writes Q1 25.5655 kW `calculated` (the hand value, the recipe's year average: 25.57 kW, 606.2
  MJ a batch). The entry's other lessons have the means now: the dryer's 2000 kJ/K on DR-101's
  recipe vessel with a `cool` to 313.15 K (L-5, L-6; its jacket's U and area are the plant's
  to give), `batch.heat_up_port` (L-11), `agitator_power` (L-12).
- The process library gives the same results on this change as on its base (106 entries and
  tert-butyldimethylsilyl-chloride-1: `process propagate --check`, and `reactors`,
  `reactor-hazards`, `recipe`, `stills`, `crystallizers --json` on every batch entry): no
  library entry uses a new field, and no library dryer's vessel gives `metal_heat_capacity`.
- Negative: the terms are constants or simple integrals: one integral heat of solution per
  charged component, an agitator's power constant over the model's time (not over the recipe's
  other operations), a heat loss at one UA and ambient temperature over the boil-up only. A
  recipe heat's content is the batch's charge or end (or the dryer's cake or product), as the
  jacket time takes it, not the content at that operation in general.
- Left open:
  - acetyl-chloride-1 L-11, the heat of mixing and of the phase separation: a dose's or the
    charge's integral heat of solution can be given since 1.10.0 and now, but no value for PCl3
    in acetic acid is sourced, and the heat of a second liquid phase separating needs an excess
    enthalpy model of both liquids, for which the concept stage has no data; no model can
    decide it from what the entry knows (even the reaction heat's sign depends on the
    phosphorous acid's state, its D-005);
  - an agitator's or a drive's power in a dryer and a crystallizer: the dryer's balance divides
    by an `efficiency` that already lumps what it gains and loses, so whether an agitator's heat
    enters before or after it is the plant's to say, and the crystallizer's lumped balance has
    no time of its own to multiply a power by;
  - a vessel's heat losses besides a still's, and the losses during a heat-up or a hold.

## Evidence

- core#191 and its comments; process-library methyltriphenylphosphonium-bromide-1 L-8,
  acetyl-chloride-1 L-11, potassium-tert-butoxide-1 L-5, L-6, L-11, L-12,
  tert-butyldimethylsilyl-chloride-1 L-12; this ADR's PR.
- `src/chemeascode/domains/process/schema.py` (`AgitatorPower`, `HeatLoss`,
  `Batch.heat_up_port`, `Batch.heat_of_solution`, `Batch.agitator_power`,
  `Still.sensible_heat`, `Still.heat_loss`, `Still.agitator_power`, `Energetic.vessel_metal`),
  `recipe.py` (`Operation.stream`, `stream_heats`, `dryer_metal`, `_dryer_content`),
  `duties.py` (`split_heat_up`, `heat_up_target`, `_agitation`, `_still_extras`,
  `_conversion_metal`), `propagate.py` (`_recipe_duties`), `batch_still.py` (`gain`,
  `SUBSTEPS`, `STILL_DUTY_ONLY`), `stirred_tank.py` (the charged heat of solution), `dryer.py`
  (`energy_balance`'s metal), `model.py` (`_charge_solution_rules`).
- `tests/test_batch_energy.py`.
