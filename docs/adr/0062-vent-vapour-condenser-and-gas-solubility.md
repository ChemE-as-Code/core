# 0062. A batch's vent carries the liquid's vapour, with a partial vent condenser and a Henry split

- **Status:** Proposed
- **Date:** 2026-11-06

## Context

ADR 0054 gave a vented batch or semi-batch a second outlet: the named gases leave the liquid as
they form, a stated `fraction` of each. Its follow-ups (core#179) named what the batch entries
of the process library then had to do by hand:

- **The vent carries no vapour of the liquid.** acetyl-chloride-1 L-3: acetyl chloride is at
  69 kPa at 313 K, two thirds of the pressure, and the vent condenser E-103's load, R-101's
  evaporative cooling and the acetyl chloride past E-103 came from a script; the last was typed
  into the flowsheet as a vent `fraction`. benzyl-bromide-1 L-3: the HBr carries 0.6 to 1.0 mol
  of toluene per mol at 363 K; the reflux condenser E-102's duty, the evaporative cooling and the
  toluene left in the vent were script values outside the balance, and the vapour's heat had to
  be carried on hand-made energy streams. benzoyl-chloride-1 L-2: benzoyl chloride at about 20
  kPa at 413 K; its vapour line was sized by hand for 100 / (1 - 0.23) m3/h. methylmagnesium-
  bromide-1: 2-MeTHF at about 30 kPa at 318 K.
- **No gas solubility.** acetyl-chloride-1 L-6: the source's lower phase holds 6 wt% HCl, the
  model none. p-toluenesulfonyl-chloride-1 L-5: the quench's 10 % HCl vent fraction is an input,
  not a result. benzoyl-chloride-1 L-3: the crude holds no dissolved HCl.
- **The screening's gas release** (ADR 0058) counts the vent's components only, not the
  vapour that goes with them up the vent line at the MTSR.

Options considered:

1. **A two-phase vessel**: a head space with its own pressure balance, mass transfer (kLa)
   between the liquid and the gas. The data are not at hand in a concept-stage entry, and the
   pressure balance would change every vented batch's solution.
2. **A post-processing estimate**: the vapour from the end composition, a mean of the start and
   the end (benzyl-bromide-1's script). Quick, but the liquid's balance and the duties would not
   see it, and the composition changes over the batch.
3. **The vapour in the vent's own integration** (chosen): the gas that leaves is saturated with
   the liquid's volatile components at each moment of the same Dormand-Prince run, an optional
   flash at a stated condenser temperature on it, and a Henry constant that sets the dissolved
   share of a vent gas. No new phase, no pressure balance: the vessel stays at its stream
   pressure, as in ADR 0054.

## Decision

- **Schema** (`domains/process/schema.py`), on `Batch.vent`, each left out of the dump when not
  given (`exclude_if`), so a vent without them fingerprints as in 1.9.0:
  - `vapour: {components, activity, source}` (`VentVapour`): the gas leaves saturated with the
    liquid's volatile `components` (default: every component of the batch with an Antoine
    `vapour_pressure`, never a vent component), `activity` a sourced constant activity
    coefficient per component (default 1, an ideal liquid).
  - `condenser: {temperature, returns, energy_port, provenance, source}` (`VentCondenser`, needs
    `vapour`): a partial condenser at `temperature` K; `returns: vessel` (default) or the outlet
    stream of the step the condensate leaves by; `energy_port` the step's energy port whose
    stream takes its duty.
  - `henry: {gas: {points: [[K, kPa]], provenance, source}}` (`HenryConstant`): `p_g = H x_g`,
    ln H linear in 1/T between the points (one point: constant; outside them the end segment,
    with a note). A gas takes `henry` or `fraction`, not both; `fraction` stays the fallback
    for a gas without data.
- **Model** (`domains/process/vent_vapour.py`, `stirred_tank.solve_batch`):
  - The non-condensables `G'` (the vent's components as they form and a dosed gas passing
    through) carry `s_i' = G' y_i / (1 - Y)` of each volatile component, `y_i = gamma_i x_i
    P_i^sat(T) / P`, `Y = sum_i y_i`, from the liquid's composition at each step; the running
    totals are extra states of the same run, added only with `vapour`. `Y >= 1` is a content at
    its boiling point and is refused (a vent is no still or reflux).
  - The condenser is one isothermal flash of `G'` (inerts) and `s'` at `K_i = P_i^sat(T_c) /
    P` over an ideal condensate: the Rachford-Rice function with an inert, monotone in the gas
    share, by bisection. With `returns: vessel` the liquid loses only what passes; otherwise it
    loses `s'` and the condensate is a third outlet.
  - Heat: the vapour's latent heat `dHvap_i s_i'` cools the content (adiabatic: in `dT/dt`;
    isothermal: the `vent vapour` term of the model duty, ADR 0059), a returned condensate is
    warmed back from `T_c` (`condensate return`). The condenser removes `sum_i [c_i dHvap_i +
    s_i cp_i (T - T_c)] + sum_g [H_g(T) - H_g(T_c)]` at constant heats of vaporization (the
    vapour condensed at T and cooled as liquid; what passes condensed, cooled and re-evaporated
    on the same path; the gases as ideal gases, their term left out with a note without
    `ideal_gas` data, as ADR 0054 does for a passing dose's warming). It is integrated with the
    run, and given by term for an isothermal batch.
  - Henry: the share of what forms that leaves is found by successive substitution over whole
    runs (at most 40), so that the liquid at the end holds `x_g = y_g P / H_g(T_end)`, `y_g`
    the gas's share of the gas over the liquid (the non-condensables in the ratio they form,
    times `1 - Y`). The dissolved share is the same over the run, so the dissolved gas counts
    in the liquid's volume and concentrations as it forms. What was charged or dosed of the gas
    stays; a liquid above or below its solubility at the bounds is said in a note.
  - The step's extents are fitted to the liquid's change plus what left by the vent, vapour
    included; the outlets close the balance on them.
- **Propagate**: the vent stream carries the gases and the vapour past the condenser, at the
  condenser's temperature where there is one; a condensate stream gets its composition, flow,
  the condenser's temperature and the vessel's pressure; all share the batch's fingerprint
  (the vent's dump, and, with `vapour`, the volatile components' Antoine constants and heats of
  vaporization). The condenser's duty is a second candidate of ADR 0059 on its own stream
  (`calculated`; compared, never overwritten, where given or assumed), and that stream is never
  the jacket's: `target()` leaves it out of the step's heat streams. `cheme validate` derives
  it as it does the batch's (ADR 0059).
- **Reports**: `process reactors` adds `vapour_kmol_h`, `vapour_share`, `temperature_K`,
  `condensate_kmol_h`, `condenser_duty` (as a model duty with its stream) and `henry` (each
  gas's constant, partial pressure, solubility, dissolved amount, share vented, state);
  `process recipe` gives the vent's m3/h at the condenser's temperature; `process
  model-basis` lists the vapour's and Henry split's assumptions.
- **Screening** (ADR 0058): with `vapour`, the gas release at the MTSR is vapour-laden: its
  volume is the non-condensables' over `1 - Y`, `Y` over the worst moment's content at the
  MTSR (`vapour_share`, `noncondensable_m3_h`; a condenser is not credited, its cooling may fail
  too). `formed_kmol` and `formed_m3` stay the gas formed, the non-condensables on one basis;
  the volume it leaves with, vapour included, is `formed_m3_with_vapour`. A content whose vapour pressure reaches the vessel's at the MTSR `boils`: a warning of
  its own (`cheme.reactor-hazard-vent`) to size the relief for the boil-up.
- **Rules** (`cheme.process-reactor`): errors for a vapour component undeclared or without a
  `vapour_pressure`; a vent or condensate stream whose template lacks the vapour's components;
  a condensate stream that is no outlet of the step (three outlets are then allowed); a
  condenser `energy_port` that is no energy port of the step, or the step's own; a Henry gas
  missing from the liquid's template; a condenser `temperature` at or above the vessel's (the
  charge's temperature in a case, which an isothermal batch holds), which would condense
  nothing and heat the gas. Warnings for `vapour` with no volatile component, and for such a
  condenser on an adiabatic batch (it only starts at the charge's temperature).
- **Unchanged behaviour**: a vent without `vapour`, `condenser` and `henry` integrates,
  propagates, fingerprints, reports and screens as in 1.9.0 (the vented and fractional
  semi-batch of `tests/test_semibatch_vent.py` write 1.9.0's fingerprints; the process
  library's entries give the same `validate`, `propagate --check`, `reactors`,
  `reactor-hazards` and `recipe` output on 1.9.0 and on this change). `GENERATOR_VERSION` is
  unchanged (the drawn output format did not change); the process generator's code did, so
  every BFD/PFD needs `cheme process build` once.

## Consequences

- Positive: the closed forms hold. Every component at one vapour pressure, the vapour is `G Y
  / (1 - Y)` to 1e-9; one condensable over an inert passes `G K_c / (1 - K_c)` whatever the
  vessel's composition (1e-6); an adiabatic batch with vapour follows `T = T_0 - (kappa / c)
  ln(1 - c xi / N_0)` to 1e-7; a Henry gas ends at `x = P / H` to 1e-8; the condenser's
  integrated duty equals its terms.
- Positive, on scratch copies of the process library (not committed):
  - acetyl-chloride-1 (`vapour: {components: [ACCL, ACOH, H2O]}`, condenser at 268.15 K back to
    R-101, its duty on a new stream to brine): the vent past E-103 is 99.4 mol% HCl; R-101's own
    gas loads E-103 with 0.0048 kW and its evaporative cooling is 0.0052 kW. This does **not**
    resolve its L-3: R-101 forms almost no HCl (0.008 kmol/h), and the gas that carries most of
    the vapour is the head space the PCl3 dose displaces and the nitrogen, which the model does
    not represent. It passes 2.06e-5 kmol/h of acetyl chloride past E-103, 0.0019 % of the
    1.098 kmol/h formed, against the entry's own per-source estimate of about 0.099 % and its
    typed upper bound of 0.213 % (`fraction` 0.00213); the script's 0.17 and 0.19 kW are of
    that carrier gas too. The entry keeps its hand fraction and script until a head space and
    sweep gas are modelled.
  - benzyl-bromide-1 (`vapour: {}`, condenser at 303.15 K back to R-101): 0.734 mol of vapour
    per mol of HBr over the batch (the script's linear mean 0.803), 0.049 mol of toluene per mol
    past E-102 (script 0.051), E-102's duty 6.97 kW (script Q4 8.16 kW on the 0.803), the vessel's
    evaporative cooling and condensate return 7.30 kW (script 8.24 kW with E-103's return);
    the model's duty then flows into R-101 (1.13 kW), which `propagate` reports against Q12's
    direction, as D-009 found by hand.
  - benzoyl-chloride-1 (`vapour: {}`): 0.13 kmol/h of organics in the off-gas (mostly benzoyl
    chloride), the gas release at the MTSR 108.6 m3/h with a vapour share of 0.242 (the hand
    value 0.23), 1.09 times the stated vent capacity of 100 m3/h: a warning where 1.9.0 gave
    info at 81.6 m3/h.
- Negative: still no head space, no inert sweep or purge gas, no pressure balance and no
  mass-transfer limit: the gas leaves saturated as it forms, and the vessel stays at its stream
  pressure (a reduced pressure is a stream pressure, nothing more). A content at its boiling
  point is refused, not refluxed.
- Limitations:
  - an ideal liquid unless constant activity coefficients are given (no UNIFAC in the vent,
    whose call per step would cost the run); an ideal condensate; constant heats of
    vaporization and liquid heat capacities; Antoine fits used outside their range without a
    note;
  - the vent's gases do not dissolve in the condensate, and a vent gas is never a condensable
    (HCl is supercritical at most of these temperatures);
  - the Henry split takes the solubility at the end of the run, with the same dissolved share
    over the run; it does not degas what was charged or dosed (methyltriphenylphosphonium-
    bromide-1 L-3's dosed excess of methyl bromide still needs its hand split) and adds no heat
    of absorption or desorption;
  - one condenser per vent, one stage; the screening credits none;
  - `process simulate` still refuses a vented batch.
- Follow-ups: a head-space and inert sweep (the gas a dose displaces, a nitrogen purge;
  acetyl-chloride-1 L-3); the degassing of a dosed or charged excess by its solubility (core#179
  item 2: sodium-azide-1 L-2's dissolved methyl nitrite, methyltriphenylphosphonium-bromide-1
  L-3); a heat of absorption of a dosed gas (core#179 item 4); a reflux at the boiling point.
  This ADR covers core#179 items 1 (solubility-based venting, at the vessel's stream pressure)
  and 3 (solvent vapour and a reflux or vent condenser); items 2, 4 and 5 stay open.

## Evidence

- core#179 and its comments (benzyl-chloroformate-1, sodium-azide-1, methylmagnesium-bromide-1,
  p-toluenesulfonyl-chloride-1, benzoyl-chloride-1, benzyl-bromide-1, acetyl-chloride-1,
  methyltriphenylphosphonium-bromide-1); this ADR's PR.
- `src/chemeascode/domains/process/vent_vapour.py` (`VentPhase`, `condense`, `condenser_heat`,
  `phase_of`), `schema.py` (`VentVapour`, `VentCondenser`, `HenryConstant`, `Vent`),
  `stirred_tank.py` (`solve_batch`, `_henry_step`, `_vapour_results`, `_vapour_heat`),
  `propagate.py` (`condensate_of`, `_condenser_candidate`, `_candidate`), `duties.py`
  (`condenser_target`, `condenser_duty`), `model.py` (`_vent_vapour_rules`), `reactors.py`
  (`vent_entry`, `_vent_lines`), `recipe.py` (`_vent`), `domains/safety/reaction_hazards.py`
  (`_vapour_laden`).
- `tests/test_vent_vapour.py`: the closed forms above, the flash, the condenser's duty and
  terms, Henry, the boiling refusal, the schema; propagate's vent, condensate and condenser
  duty, the rules, the reports, the screening and the recipe; the 1.9.0 fingerprints of a vent
  without the new fields.
- process-library `benzyl-bromide-1` L-3 and `benzoyl-chloride-1` L-2, the DESIGN.md core
  limits this covers, on scratch copies, not committed. `acetyl-chloride-1` L-3 was run the same
  way and stays open: its vent vapour is carried by the displaced head space and the nitrogen,
  which are not modelled (Consequences).
