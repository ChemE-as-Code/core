# 0068. Batch still: separate phases, a cut's own pressure and boil-up, the heat-up's time

- **Status:** Proposed
- **Date:** 2026-11-12

## Context

The process library's batch entries on core 1.9.0 to 1.11.0 (core#182, its comments; core#198,
core#214) found five gaps in the batch still of ADR 0055:

- **An end at a temperature failed** with "the still boils dry before its end" for some
  temperatures between two that solved (di-tert-butyl-dicarbonate-1 L-7: ST102 at 280 and
  320 K solved, 300 and 313.15 K did not). The bubble point is monotonic along a Rayleigh path
  (at a fixed temperature the bubble pressure falls as the volatile components leave), so the
  path was not at fault. The integrator bisected the step to where the stop changed sign, then
  re-evaluated the stop at that state with an absolute tolerance of 1e-15 K. The bubble point
  converges to 1e-11 relative from the previous point's guess, so the second evaluation could
  fall about 1e-9 K short. The integrator then shrank its step to nothing and reported a dry
  still. Whether it failed depended on the step sequence, so on the hours of flows a batch.
- **A component at zero amount asked for a vapour pressure** (potassium-tert-butoxide-1 L-3).
  The model already dropped a component the charge and the feed do not hold. `cheme validate`
  took the components of an inlet without a composition yet (before propagate) from its
  template, and called a template component without vapour pressure an error. That error
  stopped the plant before propagate could write the composition that has it at 0.
- **Suspended solids and dissolved non-volatiles counted in Raoult's mole fractions**
  (iodomethane-1 L-2, di-tert-butyl-dicarbonate-1 L-3). A suspended salt, a solid reagent or an
  immiscible acid phase lowered the volatile components' mole fractions as a dissolved solute
  would. Raoult's law then left 13 % of the iodomethane in the residue, so the entry assumed a
  constant relative volatility and lost the still's temperatures. In Boc2O's strip the hexane
  left boiled at 313 K instead of about 291 K, so the model left three times too much.
- **One pressure and one boil-up per still** (di-tert-butyl-dicarbonate-1 L-5, L-6). A vacuum
  ramp from 15 to 1 kPa(a), and a forerun limited by the vacuum pump (97.7 mol/h), were hand
  steps.
- **The heat-up had energy but no time** (methyltriphenylphosphonium-bromide-1 L-9). ADR 0063
  put the charge's heat-up and the vessel's metal in the still's duty. The recipe's distil time
  stayed the boil-up's, and the heat-up's 0.81 h was a hand operation.

Options considered for the phases: (1) an activity per phase or an electrolyte model, which
the concept stage has no data for; (2) solids always out of the liquid, which would change
every plant with a solid component in a still; (3) a list of the components in a phase of
their own, opt-in. For the pressure ramp: (1) a pressure profile in time within a cut, which
needs the flash and the sensible heat between; (2) a pressure per cut, a ramp in steps. For the
heat-up's time: (1) the jacket's UA and the medium's temperature (the recipe's heat
operation), which a still's boil-up does not give; (2) the boil-up's own heat input.

## Decision

- **The stop is reached where it was found.** Once the bisection finds the step's end in a
  step (the stop's sign changes over it), the integrator accepts that step and stops. It does
  not test the stop again at the same state. Every end (residue, distilled, time, temperature,
  purity) stops this way. A still that solved before gives the same cut to within that
  re-evaluation's tolerance.
- **An end past the dry point is refused, a crawl is bounded.** (Integration of 1.12.0: a
  column still with a time end past its dry point crept on near empty without end, its error
  control holding the step far above the boils-dry floor.) After each step the integrator
  bounds how far the end's value can still rise before the still boils dry: the volatile kmol
  left (distilled by mole), their mass (by mass), or their kmol times the most s per kmol of
  any vapour of them at the highest reflux (a time). An end beyond it is refused at once; no
  step changes. A run of 500 steps that each boil off less than 1e-6 of the charge is checked
  for pace (kmol boiled up, or the end's value, from the run's first evaluated step): one
  that does not reach the end within 10^6 steps stalls, and no phase takes more. The horizon
  is that large because the steps to an end next to the dry point do not converge as it
  nears (the batch-rectification example: 1988 steps to 2.49 h, 33116 to 2.492 h, 255217 to
  2.493 h, all solved by core 1.11.0); a smaller one refused ends 1.11.0 solves.
- **Only a component the still holds needs volatility data.** `cheme validate` checks the
  components an inlet's composition carries at a non-zero amount (as before). A component the
  template of an inlet without a composition lists is now an info finding
  (`cheme.process-still`, "needed only if the charge holds them"), not an error. The solve
  itself asks a vapour pressure only of a component the charge or the feed holds.
- **`still.separate_phase: [ids]`** lists components in a phase of their own: a suspended solid,
  an immiscible non-volatile liquid, a salt. They stay in the still and are left out of the
  liquid's mole fractions: Raoult's law (the bubble point), the vapour, the residue end's key
  fraction, the profile's key fraction and the column's still liquid. A component in it is
  non-volatile. `nonvolatile:` keeps its meaning: a dissolved solute, counted in the liquid.
  Solid components are not moved out by default, so a plant that does not use the field solves
  as before.
- **`cuts[].pressure` and `cuts[].boilup`.** A cut is collected at its own pressure (volatility
  raoult) and boil-up, else the still's. Where every cut has its own boil-up and there is no
  feed, the still's `boilup` is not used: it is not checked (its unit's data), and it does not
  make an end at a time depend on the hours of flows. Only the boil-ups up to the last end at
  a time decide that dependence. A vacuum ramp is a sequence of cuts, for example each
  ending at the same temperature. At a change of pressure the still's temperature steps to the
  new bubble point. The flash, or the heating, between is not in the time or the duty; a note
  names the step. Without a feed, the first cut's pressure is the still's from the start.
- **A boil-up in `m3/h`**: the vapour's volume at the still's temperature and pressure as an
  ideal gas (`V = Vdot P / (R T)`, volatility raoult). This is a vacuum pump's capacity. With a
  column it is the boil-up's at the still.
- **`still.heat_up_time: true`.** The heat terms of the still's duty besides the boil-up (the
  charge's and a swap's feed's heat-up, a recipe vessel's metal; ADR 0063) take time at the
  still's own boil-up's heat input: `t = (Q_whole - Q_boil-up) / (Q_boil-up / t_boil)` over
  the cuts collected at it, which for a boil-up in kW is its value. A cut's own boil-up (a
  forerun the vacuum pump limits) limits the vapour, not the heating, so it does not slow the
  heat-up; where every cut has its own, the mean over the whole boil-up stands in. `cheme
  process stills` reports it (`heat_up_time_h`, `time_h`), and a recipe `distil` operation
  `from:` the still takes the boil-up and this time together.
  A term that gives heat back takes no time. The metal heats with the charge from its start
  to the still's first bubble point `T_0`, then over the boil-up only as far as the still ends
  above `T_0`: `C_m [(T_0 - T_start) + max(T_end - T_0, 0)]`. A vacuum ramp that ends colder
  than the charge still times the metal's heat-up to `T_0` and gives no time back for its
  cooling. Without the field the time is the boil-up's, as before.
- **What a still that does not use them keeps.** Each new field is optional and left out of the
  still's dump when unset: `separate_phase`, `heat_up_time`, a cut's `pressure` and `boilup`.
  So the outlets' fingerprint stays as it was. A cut's pressure enters the fingerprint. A cut's
  boil-up enters it only with an end at a time (as the still's boil-up does), and
  `heat_up_time` never does (it is the recipe's). The JSON report adds `pressure_kPa` and
  `boilup` only to a cut with its own, and `heat_up_time_h` only with `heat_up_time`.

## Consequences

- A still end past the dry point (the batch-rectification example's product cut at 10 h, or
  99.9 % distilled; core 1.11.0 hung) is refused at its first steps. A reachable end the
  integration crawls towards (2.495 h there, unsolved by 1.11.0 in 15 minutes) is refused
  after some 55000 steps, 2 to 3 minutes; one whose pace never falls runs up to 10^6 steps
  (some 40 minutes) before it is refused. The bound covers only ends at a share distilled or
  at a time: a temperature, purity or residue end past the dry point relies on the pace check.
- An end at a temperature can replace a residue key set by hand to reach a temperature
  (di-tert-butyl-dicarbonate-1 D-006). A still whose end was reached by the old second
  evaluation solves to the same values within the bubble point's tolerance.
- A plant built before propagate no longer has to declare a vented gas `nonvolatile` to pass
  `cheme validate` (potassium-tert-butoxide-1's H2).
- With `separate_phase`, iodomethane-1's ST101 on Raoult's law, ended at 357.15 K, leaves below
  0.01 % of the iodomethane in the residue, instead of 10.3 % with the red phosphorus and the
  phosphorous acid counted, and it reports temperatures. Whether that acid phase is really immiscible stays the
  plant's assumption. Boc2O's second strip, as a ramp of cuts at 10, 5, 2.5 and 1 kPa(a)
  each to 313.15 K with the salts apart, leaves 0.49 mol% hexane in the pot instead of the
  1.9 mol% set by hand, its pot starting at 291 K at 10 kPa(a) instead of 257 K at 1 kPa(a).
  Its distillation's forerun with a boil-up of 1900 m3/h at 0.13 kPa(a) takes 3.26 h, near the
  3.35 h the entry timed by hand.
- methyltriphenylphosphonium-bromide-1's ST101 with `heat_up_time` gives the heat-up 0.814 h at
  its 250 kW (the hand operation: 0.806 h, its metal heated to the bubble point only), and the
  recipe's distil takes it without the hand `heat` operation.
- On di-tert-butyl-dicarbonate-1 (process-library main, core 1.11.0), ST102 ended at 290 or
  295 K failed with "boils dry"; on a benzene-toluene still 59 of 180 ends between 380.5 and
  410 K failed. All solve now.
- A residue end on a still with `separate_phase` is the key's share of the liquid, not of the
  whole pot, so a plant adding the field reviews its residue ends.
- The pressure ramp is in steps: the flash cooling at each step and the sensible heat in
  between are not modelled, and neither is a ramp within a cut.
- The heat-up's rate is the boil-up's heat input, not the jacket's: a still whose jacket
  heats the charge faster or slower than it boils up gives the heat operation by hand, as a
  `duration` on the recipe's `heat`, and leaves `heat_up_time` off. A `heat` with
  `temperatures` and a jacket has no batch content on a still and is refused
  (cheme.recipe-reference).
- Not covered (core#182 stays open for these): activities of a non-ideal liquid, a boil-up that
  follows the jacket's falling driving force, a reaction in a still.
