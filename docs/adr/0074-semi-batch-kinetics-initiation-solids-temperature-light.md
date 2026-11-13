# 0074. Semi-batch kinetics: an initiation, a solid phase with a surface rate, a temperature programme or reflux, a photochemical rate

- **Status:** Proposed
- **Date:** 2026-11-13

## Context

The semi-batch of ADR 0050 is one isothermal or adiabatic liquid whose rate laws hold from the
first second. core#184 (part B, and its comments from the process library's waves 2 to 4)
lists what the library's entries did by hand instead:

- **No induction period** (methylmagnesium-bromide-1 L-1, tert-butyldimethylsilyl-chloride-1
  L-1). A Grignard formation starts only once the magnesium is activated; while it has not
  initiated, a dose accumulates. The entries stood in a rate constant slowed for the whole batch
  (k/100) and ran a second, hand-made case for an uninitiated initiation charge. The dosing could
  not be made conditional on the initiation.
- **A solid reactant as a pseudo-liquid** (methylmagnesium-bromide-1 L-4, copper-i-chloride-1
  L-1, iodomethane-1 with red phosphorus and iodine). The metal needs a `liquid_molar_volume`,
  counts in the liquid's mole fractions and volume, and enters the rate law as an order in its
  pseudo-concentration (2/3 as a surface proxy); there is no particle size or surface.
- **A solid forming during dosing carried dissolved** (methyltriphenylphosphonium-bromide-1 L-2,
  carbon-tetrabromide-1 L-6): the salt's volume and heat capacity are a solution's.
- **One temperature per semi-batch** (acetyl-chloride-1 L-8, p-toluenesulfonyl-chloride-1 L-3):
  the sources dose at one temperature and hold at another; the model ran both at one.
- **No reactor at reflux** (benzyl-bromide-1 L-2, iodomethane-1 L-8): the temperature of a
  boiling content follows its bubble point as the reaction changes it.
- **No photochemical rate law** (benzyl-bromide-1 L-1): the rate of a light-driven step is an
  assumed thermal `k`, and a lamp failure a smaller `k`.

Options considered: a general time-dependent rate multiplier and temperature as script
callbacks (not declarative, not checkable, a script per entry); a separate integrator per term
(duplicates ADR 0050's balances); declared terms on the existing `batch:` block that the one
integrator takes, split into segments where a term changes. The last keeps one model, one
fingerprint and the library's numbers.

## Decision

cheme-as-code adds five opt-in terms to `batch:` and two to a rate law, solved by
`stirred_tank._solve_batch` with `domains/process/batch_kinetics.py`. A batch without them
solves exactly as before: same break points, same arithmetic.

- **Initiation.** `batch.initiation: {time, factor, reactions, provenance, source}` runs the
  named reactions (default every one) at `factor` (default 0) of their rate laws until `time` s
  after the charge. `dosing[].after_initiation: true` counts a dose's `start` from the
  initiation (`Batch.segments`, `dosing_end`): a feed interlocked on a positive initiation. A
  semi-batch with an initiation is run a second time as the **uninitiated scenario**: the
  initiation never comes, the waiting doses never start, until the initiation was due or the
  last other dose ends; its largest accumulation and its worst cooling-failure temperature (the
  content then reacting to completion, every reaction of the model) are reported
  (`TankResult.initiation`, `process reactors`), screened (`reactor-hazards` JSON `initiation`)
  and checked: `cheme.reactor-hazard-initiation` warns when that MTSR is above the MTT or the
  TD24 (info otherwise). The initiation is a declared switch, not a prediction.
- **Solid phase.** `batch.solids: {id: {density, diameter | specific_area, provenance}}` carries
  a component as a solid: out of the liquid's mole fractions, concentrations and activities,
  its volume `n M / density` in the content's, its `liquid_heat_capacity` in the content's heat
  capacity; a rate per m3 is per m3 of the liquid. A rate law naming its concentration is
  refused; a `reverse: equilibrium` takes its activity as 1, and a solid not there neither
  reacts nor dissolves. A precipitate forming as it reacts is carried this way.
- **Surface rate.** `rate.basis: surface` with `rate.solid` is per m2 of that solid's surface:
  equal particles charged at the start (`diameter`: `6 / (density d)` m2/kg, or
  `specific_area`), shrinking at a constant number, `A = A_0 (n / n_0)^(2/3)`. A dosed surface
  solid, a CSTR and a fixed bed refuse it.
- **Temperature.** `batch.program: {points: [[s, K]]}` (isothermal; first point at 0 s) moves
  the temperature linearly between its points, held after the last; `batch.heat: reflux` holds
  the liquid at its bubble point at the vessel's pressure (Raoult's law, the bubble point moved
  from `safety/reaction_network.py` to `process/batch_kinetics.py`), total reflux with no vapour
  hold-up. The duty takes `doses` warmed to the temperature each met and a `content` term, the
  content's sensible heat as its temperature moves. A given outlet temperature other than the
  programme's end, or any at reflux, is refused; reflux refuses a vent's vapour and head space
  (the gas over a boiling liquid is its vapour) and `heat_up`.
- **Light.** `rate.form: photochemical` is `r = Phi(T) prod(c_i^a_i) q_a`: `k` the quantum yield
  (the amount reacting per amount of photons absorbed; above 1 for a chain), `q_a` the photons
  the liquid absorbs per m3 from `batch.light: {power, wavelength, absorber, absorptivity,
  path_length, on}`: `power` W of radiant power entering per m3 of the charge (intensive, as the
  batch's basis), `q_0 = P lambda / (h c N_A)` with the CODATA 2022 exact constants, absorbed by
  `1 - 10^(-epsilon c l)` (Beer-Lambert, decadic), the lamp on in its `on` windows. The power
  absorbed heats the content (the duty's `light` term, the adiabatic balance). A photochemical
  rate without its light raises.
- **Segments.** The integrator splits the dosing and the post-reaction at the initiation, the
  programme's points and the lamp's windows (`batch_kinetics.breaks`), so each term is constant
  within a segment (`Regime`: the reactions' factors, the lamp, the programme's slope).
- **Fingerprints and rules.** The new keys are left out of the dump when not given, so existing
  outlets keep their fingerprints; reflux adds its components' vapour-pressure data.
  `cheme.process-reactor` checks an initiation's reactions, a solid's and an absorber's
  declaration (a solid not `phase: solid`: warning), a surface rate's solid in `batch.solids`, a
  photochemical rate's light (a light without one: warning), and that these terms sit on
  liquid-phase reactions. The screening's gas release takes the particles and the light from
  the charge in the case screened (`extent_rates(..., case)`). A batch (not semi-batch) with a
  programme or at reflux keeps `T_p` the charge's, with a note.

## Consequences

- Positive: a Grignard's induction, its interlock and the uninitiated initiation charge are one
  model run and one finding, not a k/100 stand-in and a second hand case; a metal reacts on its
  shrinking surface; a precipitate leaves the liquid's concentrations; a step can dose cold and
  hold warm, or boil at reflux; a light-driven step has a photon budget and a dark state.
- Positive: each term is tested against its closed form (first order with an induction, the
  dose into an uninitiated charge, the shrinking sphere `1 - (1 - X)^(1/3) = t / tau`, an
  Arrhenius rate along a programme, the bubble point by Antoine, the zero-order photon-limited
  rate and Beer-Lambert).
- Negative: more inputs a library entry must source or mark ASSUMED (an induction time, a
  particle size, a quantum yield, a lamp's radiant power); none of them is estimated here.
- Limitations and follow-ups:
  - The initiation is a declared time, not a model of the activation (no autocatalysis, no
    dependence on water or the activator); the interlock is on that time, not on a measured heat
    flow.
  - A solid that precipitates only above its solubility needs a phase-change reaction with a
    rate law and a solubility as its `equilibrium_constant`; there is no nucleation or growth
    on a crystal surface (a seed's area), no crystal size and no population balance, so a dosed
    surface solid (iodomethane-1's iodine) is refused rather than approximated.
  - Reflux has no vapour hold-up, no condenser or jacket limit, no vent vapour; the reflux
    screening barrier (condenser capacity against the boil-off at the MTT, iodomethane-1 L-9)
    and the recipe's jacket check at reflux stay open (the recipe takes a peak duty of an
    isothermal step only).
  - The light is monochromatic, one absorber and one path length, the content well mixed (no
    light gradient in the rate); the screening has no lamp-failure scenario beyond an `on`
    window.
  - A liquid-liquid split of a reacting mass (acetyl-chloride-1 L-2) is not part of this.

## Evidence

- core#184 (part B and its comments), this ADR's pull request.
- `src/chemeascode/domains/process/batch_kinetics.py`, `stirred_tank.py` (`_solid_phase`,
  `_uninitiated`, `_Mixture.surface`, `_Mixture.absorbed`, `_moving_terms`), `schema.py`
  (`Initiation`, `TemperatureProgram`, `SolidPhase`, `Light`, `Dosing.after_initiation`,
  `Batch.segments`), `domains/chemistry/rates.py` (`basis: surface`, `form: photochemical`),
  `domains/safety/reaction_hazards.py` (`_initiation`, `cheme.reactor-hazard-initiation`),
  `model.py` (`_kinetics_rules`).
- `tests/test_semibatch_kinetics.py`.
- Constants: CODATA 2022 (NIST, physics.nist.gov/cgi-bin/cuu/Value?h, ?c, ?na), each exact.
  Quantum yield: IUPAC, Braslavsky, S. E. (2007) Glossary of terms used in photochemistry, 3rd
  edition, Pure Appl. Chem. 79, 293-465, doi:10.1351/pac200779030293, as cited by the open
  Wikipedia article "Quantum yield" (read 2026-11-13); Beer-Lambert law, decadic, and its
  assumptions: Wikipedia "Beer-Lambert law" (read 2026-11-13).
