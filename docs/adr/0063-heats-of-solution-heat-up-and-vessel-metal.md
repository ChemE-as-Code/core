# 0063. Heats of solution and mixing, the heat-up of the charge and of the vessel's metal

- **Status:** Proposed
- **Date:** 2026-11-06

## Context

Since ADR 0059 the batch models write the duty of their energy streams. The batch entries of
the process library on core 1.9.0 (core#191) still typed four heats by hand, each on its own
assumed stream next to the model's duty:

- the dilution heat of the acids dosed into the quench of p-toluenesulfonyl-chloride-1 (Q10,
  16.03 kW, lesson L-2);
- the heat of absorption of the phosgene left dissolved in benzyl-chloroformate-1 (Q2A,
  1.18 kW, L-10);
- the charge of methyltriphenylphosphonium-bromide-1's still heated to its bubble point, and
  the still's steel (Q9, 19.96 kW), and the reactor's steel cooled with the slurry (Q10,
  1.63 kW, L-7); the recipe's heating and cooling times left the steel out;
- the PPh3's dissolution heat in MTPPB (L-8) and the mixing heat of acetyl-chloride-1 (L-11),
  of charged rather than dosed material.

ADR 0054 left a dissolving dose without a heat of absorption: its reactions' heats were to be
written with the dose as a gas, so that the absorption is released as the dose reacts. That
leaves out the absorption of what dissolves and does not react (BCF's Q2A), and it has no
counterpart for a dosed liquid's heat of dilution. ADR 0054 named `dosing.heat_of_solution` as a
follow-up; ADR 0059 named a heat-up duty from the recipe.

Options considered:

1. **An enthalpy model of the liquid** (excess enthalpies, an electrolyte model). Concept-stage
   entries have one integral heat per component at most, often an order of magnitude.
2. **One field per hand stream**, on each model: four places for the same idea, and the
   steel of a vessel over several steps would be given once per step.
3. **Three small, separately opted-in terms** (chosen): a dose's integral heat of solution,
   the charge's heat-up where the model knows both temperatures, and the vessel's metal given
   once, on the recipe's vessel.

## Decision

- **Heat of solution** (`schema.py`): `Dosing.heat_of_solution: {values: {component:
  kJ/kmol}, provenance, source}`, kJ/kmol (= J/mol) of the component dosed, negative when
  mixing releases heat (as a heat of reaction). It is the integral heat of solution, dilution
  or mixing at the batch's dilution and temperature, for a liquid or a gas. For a gas with
  `absorbed` it applies to the share that dissolves, so the heats of the reactions consuming a
  dissolved dose are then written on the dissolved basis (the gas-basis heat plus the heat of
  absorption); giving both a gas-basis heat of reaction and a heat of absorption counts the
  absorption twice, which core cannot detect.
  - The semi-batch (`stirred_tank.solve_batch`) releases it at the dose's rate,
    `q_d(t) sum_i n_d,i (-dH_sol,i)`, since a dose mixes in at once: in the adiabatic balance,
    in the isothermal peak cooling duty (so in the recipe's jacket check, ADR 0052) and, over the
    batch, as the heat term `solution` (`sum n dH_sol`) of the ADR 0059 duty.
  - **Screening**: it counts in `dT_ad` (the batch's potential with all of it dosed at once, a
    dosing error), with its own value in `heat_of_solution` and a note, and not in the MTSR.
    The reasoning: the MTSR of a semi-batch is the content's temperature when the cooling fails
    and the dosing is stopped (its interlock, the model's assumption, ADR 0050). What has mixed in
    has released its heat of solution already, and the cooling removed it at `T_p`; what has not
    been dosed never enters. Nothing of the mixing heat is accumulated, unlike an unreacted
    reagent, so the cooling-failure profile (ADR 0058) is as without it. A cooling failure with
    the dosing going on adds each portion's heat of solution as it adds its reaction: that case
    is excluded by the interlock, as for the reaction. An adiabatic semi-batch's temperature
    holds the heat of solution, so its MTSR does too, through the model.
- **Charge heat-up** (opt-in, so a plant keeps its 1.9.0 duties):
  - `batch.heat_up: true` on an isothermal batch or semi-batch: the term `charge heat-up`,
    `C_charge (T - T_in)` (the charge's `liquid_heat_capacity`; a closed gas batch's ideal-gas
    cv at the mean temperature), from the charge's inlet temperature to the batch's.
  - `still.heat_up: true` (volatility raoult): the term `charge heat-up`, the charge from its
    inlet temperature to its bubble point at the start, in the still's duty and in `process
    stills`; a charge at or above its bubble point takes none (its flash is not modelled).
  - The recipe reports the heat of every `heat` or `cool` operation with `temperatures`
    (`RecipeResult.heats`, `process recipe`): the content's and the metal's kJ per batch, the
    mean kW over the operation and the year average. This is a report, the basis of a heater
    step's hand duty: a model in the same vessel that changes the temperature (a crystallizer's
    cool-down) holds the same heat in its own duty.
- **Vessel metal** (`recipe.py`): `vessel.metal_heat_capacity: kJ/K` on a unit procedure's
  vessel, the vessel's mass times its cp.
  - The jacket's heat and cool times use `C + C_m`, the metal at the content's temperature.
  - Each model in the vessel (its `unit` or `units`) that changes the content's temperature
    gets the term `vessel metal`, `C_m (T_1 - T_0)` over the batch's hours of flows: a batch or
    semi-batch from its charge's temperature to its own, a still from its charge's to its end
    temperature, a crystallizer from its feed's to its own. A model at its charge's temperature
    gets none.
  - A unit procedure holding a still (and no batch step) may now give a `vessel`: it is sized
    from what its steps take in (or its given `volume`), with no jacket check (the still's pot,
    MTPPB L-1); 1.9.0 refused it as `cheme.recipe-reference`.
- **Provenance and fingerprints.** The terms are in the `calculated` duty's fingerprint: the
  heats of solution (in the batch's inputs), `heat_up`, the charge's heat capacities, the metal's
  kJ/K, the batch's hours and the temperatures. `heat_up` is left out of the outlets'
  fingerprints (it changes no outlet). Every new field is left out of the dump when not given
  (`exclude_if`), so a plant without them solves, reports and fingerprints as in 1.9.0; the only
  report a plant gets without them is the recipe's heat of its jacket-timed operations.
- **Rules** (`cheme.process-reactor`): a heat of solution of an undeclared component (error) or
  of one the dose does not carry (warning). `heat_up` on an adiabatic batch, or on a still at
  constant volatility, is a schema error.

## Consequences

- Positive: on scratch copies of the library the hand streams go. p-toluenesulfonyl-chloride-1's
  Q101 with the acids' heats (-75 and -20 kJ/mol) writes Q5 54.946 kW (38.92 + 16.03), and the
  jacket check meets the 190.5 kW peak (210 kW removable). benzyl-chloroformate-1 with
  phosgene's -24.8 kJ/mol and its heats on the dissolved basis writes Q2 19.884 kW (18.704 + Q2A
  1.18). In methyltriphenylphosphonium-bromide-1, the still's `heat_up` and C-101's 2500 kJ/K
  write Q7 60.633 kW (40.669 + Q9 19.964), and R-101's 3000 kJ/K writes Q3 5.186 kW (3.552 + Q10
  1.634). R-101's heating and cooling now take 0.25 h longer each.
- Positive: closed forms hold (`tests/test_heats_and_heat_up.py`): the peak cooling duty
  `q ((-dH)(1 - exp(-k t_d)) - dH_sol) / V` of a fast first-order dosing, the adiabatic balance
  with the mixing heat, the heat-up `n cp (T_b - T_in)` to Raoult's bubble point, and the jacket
  time `(C + C_m) / (UA) ln(...)`.
- Negative: one integral heat per component, constant over the batch: no dependence on the
  dilution reached (a heat of dilution varies along the dosing), on temperature, or on a second
  liquid phase. The heat of solution of a charged solid (MTPPB's PPh3, L-8), a vented gas's
  retained share (ADR 0054's `fraction`; write its dissolution into the heat of reaction) and
  acetyl-chloride-1's heat of mixing on phase separation are not covered.
- Limitations: the metal follows the content and starts each operation at its temperature (a
  vessel left warmer by the previous batch is not modelled); the equipment list's mass is not
  read, the recipe's vessel holds the kJ/K; a conversion step gets no metal or heat-up term; the
  still's content's sensible rise while it boils and its heat losses are still left out; the
  recipe's heat of an operation is reported, not written to a stream.

## Evidence

- core#191; this ADR's PR.
- `src/chemeascode/domains/process/schema.py` (`HeatOfSolution`, `Dosing.heat_of_solution`,
  `Batch.heat_up`, `Still.heat_up`), `stirred_tank.py` (`Dose.solution`, `_heat_up`),
  `batch_still.py` (`_heat_up`, `_heat_entry`), `recipe.py` (`Vessel.metal_heat_capacity`,
  `HeatResult`, `metal_of`), `duties.py` (`with_metal`), `crystallization.py`
  (`_metal_entry`), `domains/safety/reaction_hazards.py` (`_solution_rise`), `model.py`
  (`_solution_rules`).
- `tests/test_heats_and_heat_up.py`.
- process-library `p-toluenesulfonyl-chloride-1` (L-2, Q10), `benzyl-chloroformate-1` (L-10,
  Q2A), `methyltriphenylphosphonium-bromide-1` (L-1, L-7, L-8, Q9, Q10): scratch copies, not
  committed.
- Stoessel, F. (2008) Thermal Safety of Chemical Processes, Wiley-VCH, chapter 7: the MTSR of a
  semi-batch with the feed stopped on a cooling failure.
