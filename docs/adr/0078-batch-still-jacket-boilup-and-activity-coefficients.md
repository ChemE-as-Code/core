# 0078. Batch still: a jacket's boil-up and UNIFAC activity coefficients; no reaction in a still

- **Status:** Proposed
- **Date:** 2026-11-19

## Context

core#182 still had three gaps open after ADR 0068 (released in 1.12.0):

- **The boil-up is one constant mean** (iodomethane-1 L-4, benzyl-bromide-1 L-6): the jacket's
  driving force falls as the pot heats, but a still boils up at one rate (kmol/h, kW, ...).
  ADR 0068 timed the heat-up at the boil-up's heat input and left the jacket's own rate to a
  hand `heat` operation.
- **An ideal liquid only** (benzoyl-chloride-1 L-9, benzyl-bromide-1 L-9, acetyl-chloride-1
  L-10): a non-ideal mixture, or an azeotrope, cannot be represented, so these stills' basis is
  reported as not sourced.
- **No reaction inside a still** (di-tert-butyl-dicarbonate-1 L-10): Boc2O's thermal
  decomposition while it is distilled.

Core already has two activity models: original UNIFAC from the components' CAS numbers
(`thermo`, extra `props`; the liquid-phase reactions' `activity` basis) and NRTL with the
caller's binary parameters (`integrations.thermo.nrtl_ln_gammas`, the LLE systems of `process
extract`). It has rate laws (`process/reactions.yaml`, `chemistry/rates.py`) in the batch and
semi-batch reactor, with a vent for the gas a reaction forms (ADR 0054, 0062, 0071).

Options considered for the jacket: (1) UA and the medium on the still's boil-up; (2) the
recipe vessel's jacket (`u`, `area`, `heating_temperature`), and the wetted area from the
vessel's diameter and the liquid's volume. For the liquid: (1) UNIFAC; (2) NRTL with binary
pairs on the still; (3) constant activity coefficients, as on a vent (ADR 0062). For the
reaction: (1) rate laws in the still's balance, `dN/ds = -y + R dt/ds`; (2) none, and say why.

## Decision

- **A jacket's boil-up, `boilup: {value: UA, unit: kW/K, medium_temperature: K}`** (on the
  still or on a cut). The heat input is `UA (T_m - T)` at the still's bubble point T, so the
  vapour rate is `V = UA (T_m - T) / lambda(y)`: each kmol boiled up takes `lambda(y) / (UA
  (T_m - T))` s. It needs volatility raoult and the heats of vaporization. UA and the medium
  are constant (option 1): the still stays solvable from the flowsheet alone. Option 2 would
  size the vessel from the still's content and take the still's rate from the vessel, a
  circle between propagate and the recipe, and needs the liquid's volume along the path. An
  end at or above the medium's temperature is refused when the flowsheet is read. A still
  that would reach its end only above it (a residue end past it) stalls with the reason (the
  heat input falls towards 0 near the medium), not as a still that boils dry. A stall is put
  down to the medium only where the driving force `T_m - T` has fallen below 1 % of the one
  the run started at; any other stall (a column crawling on a trace it enriches, ADR 0061)
  keeps the pace's reason.
- **The heat-up's time with a jacket** (`heat_up_time`, ADR 0068). It takes the jacket's mean
  input over the charge's heat-up: UA times the log-mean of `T_m - T_in` and `T_m - T_0`. The
  charge and the vessel's metal heated to the first bubble point `T_0` then take the jacket's
  own time, `C / UA ln((T_m - T_in) / (T_m - T_0))`, which is the recipe's `heat` time with
  `temperatures`. The other terms (a swap's feed, the metal above `T_0`) take the same mean
  rate. With a charge at or above `T_0`, or of unknown temperature, the input is
  `UA (T_m - T_0)`. Where every cut has its own boil-up (ADR 0068: the mean over the whole
  boil-up stands in) and they are one jacket, the same UA and medium on each, that jacket
  heats the charge and the log-mean holds as on the still. Cuts at different jackets, or a
  jacket on some only, keep ADR 0068's mean: there is no one jacket to take a log-mean of.
- **`volatility.activity: unifac`** (raoult only): modified Raoult's law, `y_i P = gamma_i x_i
  P_i(T)`, with original UNIFAC (DDBST groups, `thermo`) at the still's liquid and
  temperature. The liquid is without the `separate_phase` components and includes dissolved
  non-volatiles and solids. The bubble point is solved at the coefficients of the last
  temperature, again until it moves by less than 1e-11 of itself. Each component of the
  liquid needs its `cas` (`cheme.process-still`, error; the solve refuses it too), and a
  component without UNIFAC groups is refused, never taken as ideal. So is a liquid with a pair
  of main groups that UNIFAC's table (UFIP) has no parameters for, in either direction:
  thermo's `from_subgroups` would take that interaction as 0, part of an ideal liquid (water
  and iodomethane, main groups 7 and 32, have none). thermo's UNIFAC is set
  up once per solve and evaluated with `to_T_xs`
  (`integrations.thermo.unifac_gammas`, about 40 times faster than setting it up per call).
  The still holds one liquid. A liquid that UNIFAC splits into two (water and toluene, a
  heteroazeotrope) has no single bubble point on this model: a homogeneous liquid of water
  0.1 in toluene at 1 atm would start boiling at 324.1 K on UNIFAC, while any liquid of the
  two boils at or above 357.5 K, where `P_water + P_toluene = P` (water's Antoine constants
  as acetyl-chloride-1 gives them, NIST WebBook after Stull 1947; toluene's as
  `examples/process-solvent-swap`). It is refused, never
  solved: at each bubble point where a component's activity `gamma_i x_i` exceeds 1 (the
  tangent-plane distance of that component pure, `-ln(gamma_i x_i)`, below 0), and at each
  point of the profile by Michelsen's tangent-plane test, by successive substitution from a
  trial liquid of each component nearly pure. The test catches a split whose activities all
  stay below 1 (1-butanol 0.1 in water at 360 K). It is not a global minimisation: a gap the
  successive substitution does not reach from these trials passes. `separate_phase` is no way
  around it, as it keeps its component from boiling; a heterogeneous distillation needs a
  specified split or `process simulate`. A column takes the K-values `gamma_i P_i / P` at the still for the whole column. The latent
  heat stays the components' (no heat of mixing). NRTL (option 2) is not taken now. It needs
  sourced VLE pairs for every pair of the still's liquid; the library's stills hold three to
  six components, and core ships NRTL pairs only for LLE systems fitted to tie lines, which do
  not describe the vapour. It can follow as `activity: nrtl` with its pairs, once a plant has
  them. Constant coefficients (option 3) do not follow a still's composition, which changes
  from the charge to the residue.
- **No reaction in a still** (option 2). The still keeps refusing a step that is also a
  reactor (`cheme.process-still`). The model cannot decide a reaction cleanly for three
  reasons:
  - The still integrates over the kmol boiled up, `s`, and its time follows from the
    boil-up. A reaction runs in time: during the heat-up, where nothing boils up, and as the
    rate falls, `dt/ds` grows without bound. A time-based integrator for a reacting still would
    be a second path through every end, cut and swap, not an option on this one.
  - At a heat-input boil-up (kW, kW/K) the reaction's heat changes the vapour rate, `V = (Q +
    sum_j (-dH_j) r_j V_L) / lambda`. The duty's terms (ADR 0059, 0063) and the heat-up's time
    would need a reaction term, and an endothermic reaction could stop the boil-up.
  - Boc2O's decomposition, the case in core#182, gives isobutene and CO2. The still's
    condenser is total and has no gas outlet: a gas has no Antoine vapour pressure (refused),
    or it would condense into the distillate. Modelling it needs a vent on the still with a
    partial condenser and Henry's law (ADR 0062, 0071), a new outlet kind and the recipe's
    off-gas per batch (core#182 item 5).

  A form that only allows reactions whose products are all liquid would not cover the case it
  was asked for. A decomposition during a distillation stays a reactor step before the still,
  at the still's temperature for its time, with its vent, or a hand estimate in the plant's
  `DESIGN.md`.
- **What a still that does not use them keeps.** `activity` and `medium_temperature` are left
  out of the dump when unset, so a still's outlets' fingerprint stays as it was. With a time
  end, a jacket's `medium_temperature` enters the fingerprint with its UA, and so do the heats
  of vaporization. With activity coefficients, the CAS numbers enter it (the
  activity model itself is in the still's own dump). `process stills` names the model in its
  `detail` ("modified Raoult's law, UNIFAC activity coefficients", "(jacket, medium at T K)"),
  replaces the ideal liquid in the assumptions (with a column, where there is no ideal liquid
  to replace, adds the modified Raoult's law beside the column's K-values), and adds the
  jacket's, in place of the constant boil-up where every boil-up is a jacket (beside it where
  some are). The volatility's own
  provenance decides whether the activity coefficients count as sourced.

## Consequences

- Positive: a jacket's boil-up follows its falling driving force. Benzene over a dissolved
  non-volatile (60:40 kmol, 1 atm, UA 2 kW/K, medium 450 K, 2 h of flows) is half distilled in
  6.62 h as its pot heats from 370.6 to 414.4 K and the heat input falls from 158.7 to 71.1 kW.
  At a constant 158.7 kW it takes 5.38 h. The time agrees with the quadrature of `lambda / (UA
  (T_m - T))` along the path within 1e-7 (`tests/test_still_jacket_activity.py`).
- Positive: a non-ideal liquid boils on its own bubble point. Methanol 0.3 in toluene at 1 atm
  starts boiling at 338.9 K on UNIFAC, against 359.5 K for an ideal liquid. With 30 %
  distilled, its distillate holds 0.781 methanol (0.594 ideal) and its residue 0.094 (0.174).
  The residue agrees with Rayleigh's integral on an independent bubble point (thermo's
  `from_subgroups`, bisection) within 1e-6. At 0.97 methanol the charge lies past the
  minimum-boiling azeotrope: on UNIFAC the residue grows richer in methanol (0.974), where the
  ideal liquid strips it (0.960). The Antoine constants are those of
  `examples/process-solvent-swap` (NIST WebBook).
- Positive: the library's stills (process-library main, every entry) give the same `process
  stills --json`, `process recipe --json` and `propagate --check` as core 1.12.0 (with #254):
  neither field is used there, and an ideal still runs the same bubble point as before.
- Negative: UNIFAC is predictive. Its error for a given mixture is not known here, and a
  still on it is not more sourced than its volatility's provenance says. Each solve
  evaluates UNIFAC a few times per bubble point, and the tangent-plane test some tens to a
  few hundred times per point of the profile (methanol-toluene: 0.34 s against 0.02 s ideal
  without the test, about 1.6 times that with it).
- Negative: the jacket's UA and medium are constant. The wetted area does not fall as the pot
  empties, so a still that empties below its jacket boils up too fast towards the end. The
  sensible heat of the content as T rises is not taken from the jacket.
- Not covered (core#182): NRTL or measured activity coefficients in a still, the wetted area
  over the boil-up, a reaction in a still (above), a charge above its bubble point (#279).

## Evidence

- core#182 and its comments; this ADR's pull request.
- `src/chemeascode/domains/process/batch_still.py` (`_Phase.bubble`, `_activity`,
  `seconds_per_mole`, `_jacket_heat_input`, `ACTIVITY_ASSUMPTION`, `JACKET_ASSUMPTION`, the
  rules), `schema.py` (`Volatility.activity`, `Boilup.medium_temperature`),
  `integrations/thermo.py` (`unifac_gammas`), `model_basis.py` (`_still_assumptions`).
- `tests/test_still_jacket_activity.py`.
- Follows ADR 0055, 0061, 0063 and 0068.
