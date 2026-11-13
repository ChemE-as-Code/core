# 0071. Gas-liquid batch: inerts, a head space, degassing, the heat of absorption and the vent condenser's freezing

- **Status:** Proposed
- **Date:** 2026-11-12

## Context

ADR 0054 gave a vented batch or semi-batch a vent the gas a reaction forms leaves by; ADR 0062
saturated that gas with the liquid's vapour, added a partial vent condenser and a Henry split of
a formed gas. core#179, reopened after 1.10.0, still listed what the process library's batch
entries did by hand:

- **A head space and an inert sweep or purge gas as the vapour's carrier.** acetyl-chloride-1
  L-3: R-101 forms almost no HCl (0.008 kmol/h), so the gas that carries the acetyl chloride
  vapour to the vent condenser is the nitrogen of the head space, which the PCl3 dose and the
  rising vapour pressure expel. ADR 0062's model saturated only the HCl and gave a vent loss
  far below the entry's per-source estimate; the entry kept a hand `fraction` and a script.
- **Degassing of a dissolved, unreacted charge or dose** (item 2). methyltriphenylphosphonium-
  bromide-1 L-3: the excess methyl bromide is stripped from the slurry by a nitrogen sweep, a
  hand split with an ASSUMED 90 % share; `batch.vent` takes only what a reaction forms.
- **A vent for a gas that passes through without a reaction forming it.** copper-i-chloride-1
  L-3: the nitrogen of the dosed air; a dose's `absorbed` share (ADR 0054) works only for a
  gas the vent also lists as formed.
- **The heat of absorption of a formed gas that dissolves** (item 4): the Henry split of ADR
  0062 kept the gas dissolved without its heat.
- **No freezing check of the vent condenser.** potassium-tert-butoxide-1 L-9: tert-butanol
  freezes at 298.3 K, and a 298 K cooling-water inlet would freeze the condenser shut; the
  entry moved every cooling duty to a tempered loop by hand.

Options considered:

1. **A two-phase vessel with a pressure balance and mass transfer** (ADR 0062's option 1):
   still without the data at concept stage, and it would change every vented batch.
2. **A degassing or flash step after the batch** (methyltriphenylphosphonium-bromide-1's
   suggestion): simple, but the sweep runs while the batch reacts, and a separate step would
   not see the head space a dose displaces, nor the vapour it carries during the batch.
3. **The head space and the inert gas in the vent's own integration** (chosen): the vessel
   stays at its stream pressure; the head space is the vessel's volume less the liquid's, held
   saturated; inerts pass through; the gas leaving is whatever the head space expels plus what
   passes, carrying the vapour as in ADR 0062. One more set of states in the same
   Dormand-Prince run, added only when a vent declares them.

## Decision

- **Schema** (`domains/process/schema.py`), every new key left out of the dump when not given
  (`exclude_if`), so a vent or a component without them fingerprints as in 1.11.0:
  - `Vent.inerts: [component]`: gases that never dissolve. A dose's share of them passes
    straight through to the vent (a sweep, the nitrogen of a dosed air); the head space holds
    them; each carries the liquid's vapour like a formed gas. `Vent.components` may now be empty
    when `inerts` is given (a vent of a sweep alone); a component is a formed gas or an inert,
    not both; an inert is no `vapour` component; an inert in the charge is refused (pad the
    head space with it).
  - `Vent.head_space: {stream, provenance, source}` (`HeadSpace`, needs `inerts`): the
    vessel's head space, padded by `stream`, an inlet of the step that carries only inerts
    (kmol/h of it, on the batch's basis: the head space's inert at the start). A batch then
    takes one charge stream besides that pad (and its doses).
  - `Vent.heat_of_absorption: {values: {gas: kJ/kmol}, unit, provenance, source}`
    (`HeatOfAbsorption`): per kmol dissolved, negative when dissolving releases heat; for a
    formed gas (`components`) or a degassing gas (`vapour.henry`).
  - `VentVapour.henry: {gas: HenryConstant}`: a dissolved gas with no Antoine
    `vapour_pressure` in `materials.yaml` (a dilute solute such as HCl, or a gas above its
    critical point) that degasses at `y = H x / P` instead of Raoult's law; it is a vapour
    component, never a vent component or inert, never condensed.
  - `Component.melting_point` (K): the pure liquid's freezing point.
- **Model** (`stirred_tank.solve_batch`, `vent_vapour.py`):
  - Inerts: each dose's inerts are moved to the dose's passing gas (ADR 0054's path): they
    reach the vent at the dose's rate, never the liquid, its volume or its concentrations.
  - Head space: the vessel is the charge's volume plus the head space its pad fills at the
    start, saturated: `V_vessel = V_0 + n_pad R T / ((1 - Y_0) P)`. The head space then holds
    `H = (1 - Y) P (V_vessel - V) / (R T)` of non-condensables. The non-condensables that form
    and pass through enter it, and it expels `F = In - dH/dt` of its own composition, which
    carries `F Y / (1 - Y)` of the liquid's vapour. `dH/dt` depends on that vapour (the liquid
    loses it, and in an adiabatic batch it cools the content) linearly, `dH/dt = D_a + F D_b`,
    so `F = (In - D_a) / (1 + D_b)`, with `D_a` and `D_b` from the liquid's molar volumes and
    `dY` (the K-values' derivative in T by central difference). A head space that expands
    (`F < 0`) draws gas back from the vent line, without vapour, with a note when more is drawn
    back than was expelled. A liquid that fills the vessel is refused. What the head space
    holds at the end leaves by the vent too, without vapour (with the next charge or the purge),
    so the whole pad and every formed gas reach the vent and the balance closes. A Henry split
    (ADR 0062) then takes the gas's share over the liquid from the head space's composition at
    the end.
  - Degassing: any vapour component, by Raoult's law or, with `vapour.henry`, Henry's, is
    stripped by whatever gas leaves (a formed gas, an inert sweep, the head space's gas), so a
    charged or dosed excess degasses with no new mechanism. A Henry gas passes the vent
    condenser as a gas: the flash runs over the condensables only, with the Henry gas among
    the inerts, and the condenser cools it as a gas.
  - Heat of absorption: a formed gas's dissolved share (`1 - fraction`, or the Henry share)
    releases it as it forms (a running total in the state: the isothermal duty's term
    `absorption`, in `dT/dt` of an adiabatic batch, in a semi-batch's peak cooling duty). A
    degassing gas takes it back as it leaves: its heat of desorption, `-heat_of_absorption`,
    stands in for the latent heat in ADR 0062's `vent vapour` term and the evaporative cooling
    (left out with a note without it). The reactions' heats stay on the gas basis.
- **Propagate and reports**: the pad's kmol are an input of the batch's fingerprint
  (`head_space`, only with a head space); the vent stream carries the inerts. `process
  reactors` adds the head space (`vent.head_space`: the vessel's and the head space's m3 at the
  start and the end, per hour of charge, its gas at the start and the end and what it
  expelled), the reactor's model basis (`cheme maturity`) the assumptions
  (`vent_vapour.GAS_ASSUMPTIONS`), `process recipe` the inerts in the vent's peak and per batch. `reactor-hazards` leaves a vent's
  inerts and a head space's pad out of the content, the MTT and the gas release's volume (a
  note says they pass through); a vent of inerts only (`components` empty) has no formed-gas
  release at the MTSR: the dosing stops at a cooling failure, and nothing forms. A content
  boiling at the MTSR still boils up through it: with `vapour`, such a vent reports
  `gas_release.boils` and `boil_up` (ADR 0069) and the `cheme.reactor-hazard-vent` warning, and
  nothing else of a gas release. A `vapour.henry` gas is a gas held in solution in the
  screening too: the gas release carries it at `H x / P` (the vent's own K-values), and the
  default MTT and `hazard.mtt_from: bubble-point` leave it out whatever its share of the liquid
  or its boiling point, naming it in `mtt_left_out` and `dissolved_release` (with what the gas
  release strips of it), with or without a `normal_boiling_point`.
- **Rules** (`cheme.process-reactor`, errors): an inert or degassing gas undeclared; an inert
  in a reaction; a head space's pad that is no material inlet of the step, or that carries
  more than the inerts; a vent stream whose template lacks an inert. New rule
  `cheme.process-condenser-freezing` (warning): a vent condenser whose outlet temperature, or
  the supply temperature of the utility its `energy_port` stream runs to (the coldest its tube
  wall can get), lies below the `melting_point` of a component it condenses (not a Henry gas),
  with the hint to keep both above it (a tempered coolant) or to say in DESIGN.md why the
  mixture cannot freeze. The same rule checks a batch still's condenser (`batch_still.rules`):
  the supply temperature of the utility its `condenser_port` stream (by default a column's one
  heat stream out) runs to, against the `melting_point` of each component its distillate's
  cuts carry at 1 mol% or more (a trace freezes out far below its pure melting point).
- **Unchanged behaviour**: a vent without `inerts`, `head_space`, `heat_of_absorption` and
  `vapour.henry`, and a component without `melting_point`, solves, propagates, fingerprints,
  reports and screens as in 1.11.0. The twelve batch entries of the process library (acetyl-
  chloride-1, benzyl-bromide-1, benzoyl-chloride-1, iodomethane-1, methyltriphenylphosphonium-
  bromide-1, p-toluenesulfonyl-chloride-1, benzyl-chloroformate-1, sodium-azide-1,
  copper-i-chloride-1, di-tert-butyl-dicarbonate-1, potassium-tert-butoxide-1,
  carbon-tetrabromide-1) give `propagate --check` clean and the same `process reactors`,
  `reactor-hazards` and `recipe` output on 1.11.0 and on this change (the release as a whole
  changes `reactor-hazards` for vented semi-batches as ADR 0069 describes). `GENERATOR_VERSION` is
  unchanged; the process generator's code changed, so every BFD/PFD needs `cheme process build`
  once.

## Consequences

- Positive: the closed forms hold (`tests/test_vent_gas.py`). A dissolved volatile over a
  non-volatile solvent swept by an inert at `g` kmol/s follows `n_S ln(n / n_0) + (1 - K)(n -
  n_0) = -g K t` to 1e-7, by Raoult's law or Henry's alike; the head space a dose displaces at
  a constant vapour share expels `F = c v q / (1 + v P Y / (R T))`, `c = (1 - Y) P / (R T)`, to
  1e-8, and holds `(1 - Y) P (V_vessel - V) / (R T)` at the end; a formed gas's dissolved 60 %
  releases `0.6 xi h_abs` to 1e-7.
- Positive, on scratch copies of the process library (not committed):
  - acetyl-chloride-1 (R101's vent `{components: [HCL], inerts: [N2], vapour: {components:
    [ACCL, ACOH, H2O, PCL3]}, condenser: 268.15 K, head_space: {stream: SN2}}`, the pad 1.33 m3
    of nitrogen at 313 K a batch, 0.00855 kmol/h): the head space falls from 1.33 to 0.73 m3 a
    batch, it expels 0.0076 kmol/h of the pad's 0.0086 kmol/h and 0.0065 kmol/h of the HCl
    over the batch (the entry's hand estimate: about 0.035 of 0.049 kmol a batch, here 0.044),
    the vapour 0.491 of the gas at the end (the entry's figure). 0.00046 kmol/h of acetyl
    chloride pass the condenser, 0.014 % of the 3.29 kmol/h formed, against ADR 0062's 0.0006 %
    on the HCl alone and the script's R-101 share of 0.00094 kmol/h (its 0.0093 kmol/h of
    carrier saturated at 268 K; the per-source 0.0033 kmol/h adds the still's nitrogen, which is
    not R-101's): the model is lower because the gas the dose displaces early carries little
    acetyl chloride, which forms over the dosing. The condenser's duty is 0.024 kW (the script's
    upper bound for R-101's gas, saturated over the end's upper phase: 0.17 kW). L-3's carrier
    is modelled; the still's nitrogen remains a separate source.
  - methyltriphenylphosphonium-bromide-1 (R101 given a sweep dose of 10 Nm3 of nitrogen a batch
    over 0.5 h after the methyl bromide dose, and a vent `{inerts: [N2], vapour: {components:
    [MEBR, TOL]}}`): at the vessel's 230 kPa(a) and 333 K the sweep takes 0.0123 kmol (1.2 kg)
    of methyl bromide and 0.036 kmol (3.4 kg) of toluene a batch, which the reaction, still
    running, partly consumes meanwhile. The entry's hand split DG101 (90 %, 15.4 kg a batch)
    also counts F-101's 38 Nm3 of pressing gas at 300 kPa(a) and the depressurising, outside
    R101; a scratch copy that models the sweep must move that split's basis accordingly.
- Negative: still no pressure balance (the vessel stays at its stream pressure, so a
  depressurising is not modelled), no mass-transfer limit (the gas leaves saturated), and a
  content at its boiling point is refused. The head space's own vapour is not in the liquid's
  balance; its gas at the end leaves dry.
- Limitations:
  - the head space is padded once, at the start; a continuous purge is a dose of inerts
    (`dosing`, with `start` and `time`), not a pad;
  - the heat of absorption is a constant per kmol; it is not in the screening's MTSR (released
    as the gas forms, like a heat of solution in ADR 0063);
  - the freezing check takes the pure component's melting point (no freezing-point depression
    by the condensate's other components) and a utility's supply temperature only through the
    vent condenser's `energy_port` stream or the still's `condenser_port` stream (a still has
    no condenser outlet temperature); a condenser modelled as its own block (a `Cooling` step
    such as potassium-tert-butoxide-1's E201) is not checked;
  - `process simulate` still refuses a vented batch.
- Follow-ups: a pressure balance (a closed, padded vessel such as methyltriphenylphosphonium-
  bromide-1's R-101, its depressurising); mass-transfer limits; a reflux at the boiling point.
  This ADR covers core#179's head space, inert sweep and purge gas, item 2 (degassing of a
  dissolved charge or dose) and item 4 (heat of absorption), and potassium-tert-butoxide-1
  L-9's freezing check of the condensers it names (R101's vent condenser and ST101's still
  condenser: on a scratch copy with tert-butanol's `melting_point: 298.3` and the tempered
  water's supply at 293.15 K both warn); a cooler block that condenses (E201), a pressure
  balance and mass transfer, a content at its boiling point and `process simulate` for a
  vented batch stay open.

## Evidence

- core#179 and its comments; process-library acetyl-chloride-1 L-3, methyltriphenylphosphonium-
  bromide-1 L-3, copper-i-chloride-1 L-3, potassium-tert-butoxide-1 L-9; this ADR's PR.
- `src/chemeascode/domains/process/schema.py` (`Vent`, `HeadSpace`, `HeatOfAbsorption`,
  `VentVapour.henry`, `Component.melting_point`), `stirred_tank.py` (`solve_batch`,
  `_inert_doses`, `head_space_rates`, `_head_space_results`, `pad_stream`, `vent_gas_rate`),
  `vent_vapour.py` (`VentPhase.degassing`, `k_values`, `GAS_ASSUMPTIONS`), `model.py`
  (`_gas_rules`, `_freezing_rule`), `reactors.py` (`vent_entry`, `_vent_lines`),
  `domains/safety/reaction_hazards.py` (`_forms_gas`, the pad and inerts left out).
- `tests/test_vent_gas.py`: the closed forms, a dose of air, the condenser passing a Henry
  gas, the schema, propagate with a pad and with a sweep dose, the rules and the freezing check,
  the screening.
