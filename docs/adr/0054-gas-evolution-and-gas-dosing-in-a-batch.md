# 0054. Gas evolution and gas dosing in a batch: a vent outlet the gas leaves by as it forms

- **Status:** Proposed
- **Date:** 2026-11-05

## Context

Many batch routes still missing from the process library give off a gas as they react:
HCl from phosgenation (benzyl chloroformate), chlorosulfonation (p-toluenesulfonyl chloride)
and benzoyl chloride, CO2, HBr from a bromination. Several also dose a gas: phosgene, Cl2,
methyl nitrite. The route scouting run against core#165 found this gap in all four candidates
it checked. Gas evolution is outside #165's scope (batch work-up, the NBS lessons L-2, L-3 and
L-5), which this ADR does not address; #165 stays open for it.

The semi-batch of ADR 0050 is liquid only: a gas phase is refused, and nothing leaves the
vessel while it runs. The only workaround was to keep the gas as a dissolved liquid component
and strip it in a specified split after the reactor. That workaround has four costs:

- it overstates the content's volume, and so its concentrations;
- it needs a liquid molar volume and heat capacity the gas does not have in the liquid;
- the off-gas has no rate profile, so the scrubber cannot be sized;
- the screening cannot tell a gas that leaves from one that stays.

Options considered:

1. **A two-phase vessel model.** Vapour-liquid equilibrium or mass transfer between the
   liquid and a headspace (as PharmaPy's semi-batch reactor and evaporator do, Casas-Orozco et
   al., Comput. Chem. Eng. 153 (2021) 107408). This needs Henry constants or kLa, and a
   pressure balance, that a concept-stage entry does not have.
2. **PharmaPy as a backend.** It was reviewed and not adopted. Its dynamic units integrate
   through Assimulo (SUNDIALS), which cannot be installed with uv on Python 3.12+. It pins
   `numpy<2`. Its results would rest on a variable-step solver build outside core's
   reproducible Dormand-Prince stepper (ADRs 0010, 0011).
3. **A vent on the batch.** Named components leave the liquid as they form, by a second
   outlet stream, with an optional share that stays dissolved. A dose may pass part of a gas
   straight through. This is the same integrator with a sink beside the doses' sources.

## Decision

cheme-as-code takes option 3, natively and in pure Python. It copies no PharmaPy code and
cites the PharmaPy papers as literature only.

- **Schema** (`domains/process/schema.py`):
  - `Batch.vent: Vent | None`, where `Vent` is `{stream, components, fraction}`. `stream` is
    an outlet stream of the step. `components` are the gases that leave as they form.
    `fraction` maps a component to the share of what forms that leaves (default 1, at most 1).
  - `Dosing.absorbed: float | None` (0 < share <= 1) is the share of a dosed stream the liquid
    takes up. The rest passes through to the vent.
  - Both fields are left out of the dump when unset (`exclude_if`, as `Batch.dosing`). An
    unvented batch, semi-batch or dose therefore fingerprints exactly as in 1.7.0.
- **Model** (`stirred_tank.solve_batch`, liquid only): for each vent component `g`, with
  `G_g = sum_j max(nu_gj M_j r_j, 0)` its gross formation, reaction by reaction,
  `dn_g/dt = sum_j nu_gj M_j r_j - f_g G_g + doses` and `dv_g/dt = f_g G_g`. The vent takes a
  share of what each reaction forms, not of the net: a reaction that consumes `g` (a side
  reaction of the evolved gas, or a reversible one running back) draws on the liquid's `g`
  (charged, dosed, or the dissolved share `1 - f_g`), never on gas that has already left. The running totals `v_g` are
  extra states of the same Dormand-Prince run, added only when there is a vent, so an
  unvented batch integrates exactly as before.
  - A component vented whole and never charged or dosed has a liquid mole fraction of
    exactly 0, with no trace. It therefore needs no `liquid_molar_volume`,
    `liquid_heat_capacity` or activity data.
  - The step's extents are fitted to the liquid's change plus what left.
  - The liquid outlet is what the run leaves in the liquid. The vent is the rest of what was
    charged, dosed and formed, plus the gas that passed through. The two outlets therefore
    close the balance on the extents.
- **Heat**: a vented component's `heat_of_reaction` is taken as forming it as a gas at the
  vessel's temperature, where it leaves. This is what reaction calorimetry with free off-gas
  measures.
  - The gas carries its own enthalpy away. The liquid's energy balance keeps its form, with
    the heat capacity of the liquid alone, adiabatic or isothermal. No heat of desorption or
    solution is added.
  - A gas passing through is warmed from its dose temperature to the vessel's, with its
    ideal-gas cp. This term goes into the adiabatic balance and the isothermal peak cooling
    duty. Without ideal-gas data the term is left out and a note says so.
  - A dosed gas that dissolves adds no heat of absorption or condensation (HCl into water
    about -75 kJ/mol, phosgene's condensation about -24 kJ/mol, Cl2 about -20 kJ/mol): a dose
    enters with only its sensible heat (`liquid_heat_capacity`). Write the `heat_of_reaction`
    of the reactions that consume it with the dosed gas as a gas (as reaction calorimetry with
    gas dosing measures it), so that this heat is counted, released as the dose reacts. That
    gives a conservative MTSR (the unreacted dose's absorption heat is in the potential), but
    the isothermal cooling duty during dosing leaves out the absorption of the gas that has not
    yet reacted. Written on the dissolved basis, the absorption heat is missing from both.
- **Report** (`TankResult.vent`, `peak_vent_rate`, `peak_vent_time`, `peak_vent_flow`):
  - `process reactors` (`tank.vent`) gives the kmol/h of each component that left, and the
    peak rate in kmol/s per m3 of the content at the end (an intensive figure, like the peak
    cooling duty), with its time. The rate is the instantaneous formation plus the passing gas
    at each accepted step.
  - `process recipe` (`RecipeResult.vents`) scales this by the batch's hours of flows. It
    gives the peak in kmol/s, and in m3/h at the vessel's temperature and pressure, plus the
    kmol and kg one batch gives off: the off-gas line's and scrubber's basis.
- **Propagate**: a vented batch has two outlets, the liquid and the vent. Both are written as
  calculated: composition, flow (from the model, not from the inlets' total), and the liquid's
  temperature and pressure. They share one fingerprint (the model's inputs, with the vent).
- **Screening** (`reaction_hazards`):
  - A vented gas adds nothing to the content's heat capacity or to the MTSR.
  - A partly absorbed dose counts with its absorbed share in `dT_ad`.
  - Neither a vented gas nor a passing one sets the MTT, which is the lowest boiling point of
    what stays in the liquid.
  - A note gives the vent's peak gas rate. With the vent blocked that gas pressurises the
    vessel, which the thermal screening does not assess.
- **Rules** (`cheme.process-reactor`):
  - errors: the vent stream is no outlet of the step, or its only outlet (the liquid needs
    its own); more than two outlets; an undeclared vent component; a vented batch on gas-phase
    reactions (a semi-batch's own rule already refuses them); the vent stream's template lacks
    a vent component or a component of a dose with `absorbed` below 1 (it passes through); a
    dose with `absorbed` below 1 and no vent;
  - warning: a vent component that none of the step's reactions forms.
- **DWSIM**: `process simulate` refuses a vented batch with a translate failure (its reactors
  give one outlet), as it refuses a semi-batch.

## Consequences

- Positive: phosgenation, chlorosulfonation and bromination steps can be modelled with their
  off-gas as a stream. The liquid's volume and concentrations are right, the balance closes
  over both outlets, and the scrubber has a peak rate per batch.
- Positive: the closed form holds. For `A -> B(l) + G(g)`, first order, A dosed at a constant
  `q`, the vent rate equals the reaction rate, `q (1 - exp(-k t))`, and reaches its peak when
  the dosing ends. The model reproduces it to 1e-6, and the adiabatic balance to 1e-7.
- Positive: a dosed gas that dissolves needed no change and is now documented and tested. A
  dosed gas that is only partly taken up is one field.
- Negative: the vented gas leaves at once. There is no mass-transfer limit, no saturation or
  Henry's law, and no headspace or pressure balance, so the vessel stays at its stream
  pressure. A vent fraction stands in for a known solubility.
- Limitations:
  - The vent stream carries the batch's end temperature. For an adiabatic batch the gas
    actually left at the temperature of each moment.
  - No heat of desorption or of absorption (a dissolving dose's heat is counted only through
    a gas-basis `heat_of_reaction`, as it reacts), and no stripping of the solvent by the gas
    (the solvent's vapour in the off-gas).
  - No off-gas profile beyond its peak.
  - A gas-phase batch cannot vent.
  - The screening does not assess the gas generation's pressure.
- Follow-ups, each its own core issue: a headspace pressure balance and a gas-release term in
  the screening (Stoessel's gas-production criterion); the solvent vapour in the off-gas from
  the vessel's VLE; the reduced-pressure effect on a gas-evolving step; optionally a
  `dosing.heat_of_solution` source term for a dissolving dose.

## Evidence

- Feature F1 of the route review run against core#165 (the scout reports place gas evolution
  outside #165's scope and propose a dedicated core issue, "Gas evolution and gas dosing in a
  batch or semi-batch"); this ADR's PR. #165 stays open for its work-up scope.
- `src/chemeascode/domains/process/schema.py` (`Vent`, `Batch.vent`, `Dosing.absorbed`),
  `stirred_tank.py` (`solve_batch`, `Dose.passing`, `_solve_node`), `propagate.py`
  (`outlets_of`), `model.py` (`_vent_rules`), `reactors.py` (`vent_entry`), `recipe.py`
  (`VentResult`, `_vent`), `domains/safety/reaction_hazards.py` (`_vent_note`),
  `simulation/translate.py`.
- `tests/test_semibatch_vent.py`: the closed forms, balance closure, propagate's two outlets,
  rules, screening and recipe, and the 1.7.0 fingerprints of an unvented batch and
  semi-batch.
- PharmaPy, reviewed and not adopted (literature only): Casas-Orozco, D. et al. (2021),
  Comput. Chem. Eng. 153, 107408.
- Stoessel, F. (2008) Thermal Safety of Chemical Processes, Wiley-VCH, chapter 7 (semi-batch
  reactors) and the gas release as a separate criterion.
