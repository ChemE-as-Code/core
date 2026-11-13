# 0073. Dosing against the jacket, coupled vessels and one-pot vessels over several batch steps

- **Status:** Proposed
- **Date:** 2026-11-13

## Context

core#184 collects what the process library's semi-batch entries still did by hand. Part A is the
dosing and the vessels around it; part B (initiation and induction, solid reactants, temperature
programmes: the rate side in `stirred_tank.py`) is a separate change.

- **Dosing time against the jacket** (methylmagnesium-bromide-1 L-10, sodium-azide-1 D-010). The
  recipe checks the model's peak duty against `U A (T - T_coolant)` of the jacket (ADR 0052), but
  the dosing time that makes the two meet was found by trying dosing times by hand.
- **Coupled vessels** (sodium-azide-1 L-11). R-101's methyl nitrite vent is R-102's dose. The
  recipe lines up the two dosings with `start.after`, but nothing checks that the two dosing
  times are equal or how closely the generator's gas follows the absorber's dose profile.
- **A gas passing through a dose without ideal-gas data** (sodium-azide-1 L-9). Its warming to
  the vessel's temperature is left out of the duty, and only the model's note said so.
- **Several batch steps in one vessel** (carbon-tetrabromide-1 L-2,
  tert-butyldimethylsilyl-chloride-1 L-2). A unit procedure over two semi-batch steps in one pot
  was `cheme.recipe-reference` (ADR 0057), so the entries split the pot into two vessels.
- **A later step in the vessel sizes it** (p-toluenesulfonyl-chloride-1 L-1). R102, a conversion
  step after R101 in the same vessel, adds a second portion of acid. The vessel was sized from
  R101's batch alone and would have been 99 % full, so the entry gave the volume by hand.
- **A transfer timed by the next vessel's dose** (p-toluenesulfonyl-chloride-1 L-3). The transfer
  into Q-101 lasts as long as Q-101's dosing, which was written as a duration with that note.
- **Vents** (iodomethane-1, copper-i-chloride-1, wave 4). The N2 of a dosed air needs a vent
  that no reaction forms a gas for (ADR 0071's `inerts` covers it). Vents from more than one
  step could not be reported in one vessel.

Options considered for the dosing time:

1. A recipe option that sets the dose operation's duration to the shortest dosing. The
   flowsheet's model would then keep its declared dosing while the cycle used another one, so
   the outlet, the accumulation and the screening would no longer match the cycle.
2. A design specification (ADR 0070) that writes `batch.dosing.time`. A spec adjusts feeds and
   splits; a jacket's limit is an inequality on a peak, and a recipe is needed for the batch
   size and the vessel.
3. **A value the recipe reports** (chosen), on request, beside the jacket check that already
   holds `U A` and the peak duty. The engineer writes it into the flowsheet's dosing.

## Decision

- **The shortest dosing** (`domains/process/dosing.py`, `recipe.py`).
  - `vessel.jacket.shortest_dosing: true` is opt-in, and left out of the dump when false.
  - For each semi-batch step of the vessel, the dosing schedule is stretched in time by a factor
    `s` from the first dose's start: every dose's `time` and `profile` durations and its `start`'s
    lag behind the first dose. The wait before the first dose, the shares and the post-reaction
    stay as they are, so a wait in which nothing reacts does not lengthen the result.
  - The model is solved again at each trial factor. The peak duty of one batch is
    `peak_cooling_duty x end volume x the batch's hours of flows`, as in the jacket check.
  - The smallest `s` whose peak duty the jacket removes at the step's charge is found by halving
    or doubling from `s = 1` to bracket it, then bisecting in `ln s` to 1e-4. The search stays
    between 1e-3 and 1e3.
  - `process recipe` reports `dosing`: the declared and the shortest dosing time (from the
    first dose's start to the last dose's end, in h), the peak and the removable kW, the number
    of runs, or the reason there is none. The reasons are: no coolant temperature; a coolant
    not colder than the process (no run); an adiabatic batch; a model that does not solve; a
    jacket that removes the
    peak at 1e-3 of the dosing time (not jacket-limited); or one that removes it at no factor
    up to 1e3 (the charge's own reaction or the post-reaction sets the peak). The model keeps
    its declared dosing.
  - A step coupled to another by a vent (below), the generator or its absorber, doses with it:
    each one's `dosing` entry names the other (`coupled`) and, where both report one, the
    pair's shortest dosing, the larger of the two (`pair`). The generator's own jacket may
    allow a shorter dosing than its absorber's takes the gas at.
- **Coupled vessels** (`dosing.couplings`, `dosing.rules`).
  - A coupling is a semi-batch dose whose stream is another batch or semi-batch step's vent,
    directly or through at most 10 steps with one material inlet each.
  - `cheme.process-coupled-dosing` (warning) compares the dose's segments with the generator's
    schedule: its one dose's segments, its doses' window, or a batch's 0 to `time`. A generator
    that ends at a target has no schedule to compare.
  - Where the generator solves, an info finding gives the largest difference between two
    shares: `F_g(t)`, the share of the generator's vent gas that has left by time `t`, and
    `F_d(t)`, the share the dose has fed by then. Both clocks start at the charge. `F_g` comes
    from the new `TankResult.vent_profile`, the vent's running total at every accepted step. It
    is additive and not in any report.
  - `cheme.recipe-coupling` (warning): the absorber's first dose (or react) operation `from:` it
    does not start, in one batch's timeline, when the generator's does.
- **A gas passing through without ideal-gas data** (`cheme.process-reactor`, warning). A
  vented semi-batch's dose with `absorbed` below 1, or a vent's inerts in a dose, passes gas
  through the vessel. Where those components have no `ideal_gas` data, the warning names them.
  The model's note stays, since it explains the result.
- **A vessel over several batch steps** (`recipe.py`).
  - A unit procedure whose `units` (or block) hold several batch or semi-batch steps is no
    longer `cheme.recipe-reference`. Each step's model gives its content.
  - The vessel is sized from the largest content of any of the steps.
  - The jacket is checked against each step's peak duty, at that step's own charge.
    `VesselResult.steps` lists each step's volumes, peak, jacket area and removable duty. The
    vessel's own fields are those of the step with the least margin, and
    `cheme.recipe-jacket` names the step.
  - A `heat` or `cool` with `temperatures` takes the content of the batch step that its next
    `from:` operation names. That is the step's charge when none of its operations came
    earlier, and its end otherwise. After the last such operation it takes the end of that
    step. Where no operation names one of the steps in `from:`, the kinds decide: before every
    `dose` and `react`, the first step's charge; after them, the last step's end; between them
    the step is not known, a `cheme.recipe-duration` error that asks for the `from:`.
  - Each vented step reports its vent (`_vents`).
  - `datasheets fill` (`batch_vessel`) gives each step its own peak duty.
  - A vessel of one batch step is sized, checked and timed as before. `steps` is left out of
    its JSON.
- **Other steps in a batch step's vessel.** A step of the unit procedure that is no batch step
  may take in more for one batch than the batch steps' content. Its inflow is its material
  inlets per batch, from the liquid molar volumes. When it exceeds the batch content by more
  than 1 %, that is `cheme.recipe-vessel` (warning). `vessel.size_from: steps` (opt-in) sizes
  the vessel from that inflow too. A given `vessel.volume` is sized from nothing: the inflow
  is then checked against its `fill_fraction` instead, a warning only where it exceeds both the
  batch content and the volume times the fill fraction.
- **A transfer from the next vessel's dose.** A `transfer` may take `from:` a semi-batch step.
  Its duration is the time, from start to end, of that step's dose whose stream comes from the
  unit procedure's steps, directly or through steps with one material inlet each. A step without
  such a dose is `cheme.recipe-reference`.

## Consequences

- Positive:
  - The dosing time a jacket allows is solved instead of tried by hand. In a test it meets the
    closed form `-dH F (1 - exp(-k t_d)) / t_d = U A dT` of a first-order semi-batch to 3e-3.
  - Coupled vessels are checked on both their schedule and their gas profile. The test's
    largest share difference matches the closed form to 1e-3.
  - A one-pot sequence of batch steps can be one vessel, sized and checked for every step.
  - A second portion that overfills a vessel is no longer silent.
- Negative:
  - The shortest dosing stretches the declared schedule's shape. It does not optimise a profile
    (a fast start and a slow end), and it takes the jacket at the charge, as the check does.
  - Each trial solves the model once, about 15 to 25 runs.
  - The coupling's share difference is reported, not judged: without a basis for a threshold
    it stays info, whatever its size.
- Library effect: see the CHANGELOG entry. New findings only (sodium-azide-1's L-9 warning and its
  coupling info; p-toluenesulfonyl-chloride-1's second portion as a vessel warning); no number of
  any entry changes.
- Open:
  - The shortest dosing as a recipe option that changes the cycle: the flowsheet's model would
    keep the declared dosing, so it is reported for the engineer to write into `batch.dosing`.
  - A transfer of a liquid product into a dose is timed by `from:`, but the product's own
    profile is not compared: a batch's liquid leaves at its end, so there is no profile to
    compare.
  - Vents of work-up steps that are not batch models (iodomethane-1's lumped work-up vents) have
    no rate model and therefore no peak per batch. Their amount per batch is the flowsheet's
    stream times the batch's hours.
  - Holds and transfers still run no model (carbon-tetrabromide-1 L-9).
  - The rate side of core#184 (part B) is not covered here.
  - Three items of #184's wave-6 comment, posted after this change was scoped, are not covered
    here or in part B:
    - methanesulfonyl-chloride-1 L-6: a vessel is sized from the larger of the charge and the
      end of the batch (`max(charge_volume, end_volume)`, as before this ADR, and the same for
      each step here). A gas-forming semi-batch holds the most at the end of its dosing. The
      model integrates the content at every step, so the largest content over the batch is
      within reach. Sizing from it would change the working volume of library entries, so it
      needs an opt-in or a finding of its own.
    - methanesulfonyl-chloride-1 L-3: the jacket's heating of an endothermic dose is not
      checked. The jacket check compares the peak cooling duty only. The heating needs the
      model's peak heating duty and the heating medium's `U A (T_h - T)`.
    - tert-butyldimethylsilyl-chloride-1 L-15: a unit procedure's `start` names only an
      operation's start, with no offset and no alignment to an operation's end. A dose that
      must run in another vessel's transfer is still aligned by a hold set by hand. The
      `transfer` `from:` here goes the other way: it times the transfer by the dose.

## Evidence

- core#184 and its comments; process-library entries sodium-azide-1 (L-9, L-11, D-010),
  methylmagnesium-bromide-1 L-10, carbon-tetrabromide-1 L-2,
  tert-butyldimethylsilyl-chloride-1 L-2, p-toluenesulfonyl-chloride-1 L-1 and L-3,
  copper-i-chloride-1 L-3, iodomethane-1; this ADR's PR.
- `src/chemeascode/domains/process/dosing.py` (`dosing_time`, `stretched`, `peak_at`,
  `shortest_factor`, `couplings`, `deviation`, `rules`), `recipe.py` (`Jacket.shortest_dosing`,
  `Vessel.size_from`, `DosingLimit`, `_tanks`, `_content_of`, `_steps_vessel`,
  `_jacketed_step`, `_other_steps`, `_transfer_time`, `_dosing_limit`, `_coupled_limits`,
  `_coupling_findings`, `_vents`), `stirred_tank.py` (`TankResult.vent_profile`), `model.py`
  (`rules`).
- `tests/test_dosing_vessels.py`; `tests/test_recipe.py`, `tests/test_semibatch_vent.py`.
