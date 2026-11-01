---
name: process-simulation
description: Solve the flowsheet in DWSIM, or for a bounded scope in the optional IDAES backend (heat and material balance), with cheme process simulate - write process/simulation.yaml (simulator, property package, step specs), check the deviations from the given and assumed values, and fill the missing stream values. Use when outlet temperatures, pressures, flows or compositions of compressors, exchangers, flash drums, columns or recycle loops are needed, or when assumed stream values should be checked against a rigorous calculation.
---

# Process simulation

## Purpose and when to use

`cheme process simulate` builds a DWSIM flowsheet from `process/flowsheet.yaml` and
`process/simulation.yaml`, solves it headless and writes the results back as `calculated` values.
Use it once the flowsheet's steps, streams and feeds stand (`process-design`) and stream values
downstream of the feeds are needed or assumed: outlet states of compressors, pumps, expanders,
heaters and coolers, valves, mixers and splitters, flash drums, two-stream heat exchangers,
shortcut and rigorous columns, and recycle loops. `cheme process propagate` covers only
pass-through, mixer and splitter balances; simulate covers the energy balance and separations.

## Required inputs and missing inputs

- Every feed stream with temperature, absolute pressure, flow and composition (given or
  assumed). A missing one is `sim-feed-incomplete`: ask for it or mark an assumption.
- Components in `process/materials.yaml` with CAS numbers; a component DWSIM does not find by
  CAS needs its DWSIM name under `components:`.
- The property package (`property_package:`), from `thermodynamic-model-selection`, never
  chosen silently. Supported: Peng-Robinson (PR), Peng-Robinson 1978 (PR78),
  Soave-Redlich-Kwong (SRK), NRTL, UNIQUAC, Steam Tables (IAPWS-IF97), CoolProp
  (`cheme process methods`; another name is `sim-property-package`). Record the selection's
  facts as `method_selection: {facts: {...}}` in every new `simulation.yaml` (a comment per
  fact with its reason; an uncertain fact stated as such, chosen conservatively): the
  translation re-runs the selection and flags a package it does not recommend, and
  `cheme maturity` counts a package without a recorded selection as missing
  (`predictive.property-package`). A model the worker does not run has at most an explicit
  substitute (`methods[...].simulation.substitution`); use it only with approval and record
  why as `method_selection.substitution`. Electrolytes, solids and petroleum
  pseudocomponents are not supported by this route; a salt, acid or base of `electrolytes.yml`
  (listed, or any compound of an alkali or alkaline-earth metal) together with water is refused (`cheme.process-sim-electrolyte`). Keep such a step as a
  specified split and take brine properties from `cheme process electrolyte` (aqueous NaCl
  only). Where
  DWSIM's binary interaction parameter of PR, PR78 or SRK is not fitted to the data that
  matter (argon/oxygen near pure O2, for example), set the pair under
  `interaction_parameters: [{components: [AR, O2], kij: {value: ..., provenance: ...,
  source: ...}}]`, with the data it comes from.
- The specs of every step (`cheme schema process-simulation` lists them per unit):
  outlet pressure and efficiency of machines, outlet temperature or duty of heaters and
  coolers, the flash temperature or pressure (none: adiabatic), the exchanger's hot or cold
  outlet temperature, the column's keys or stages and end specs. Each spec is a quantity with
  provenance: an efficiency taken from experience is `assumed` with its source. Ask for what
  the design basis does not state; do not invent specs.
- DWSIM: the Docker image (`docker build --platform linux/amd64 -t cheme-dwsim:9.0.5 -f
  docker/dwsim/Dockerfile .` in the cheme-as-code repository) or `CHEME_DWSIM_PATH`. Without
  it, `sim-unavailable`: report it, do not estimate the values instead.

## The optional IDAES backend

`simulator: idaes` in `process/simulation.yaml` solves the flowsheet in IDAES (idaes-pse with
IPOPT) instead of DWSIM; the choice lives in the file, not on the command line, because it is
an input of every simulated value. It needs `CHEME_IDAES_PYTHON`, a separate Python with
idaes-pse and `idaes get-extensions` (else `sim-unavailable`). Its scope is bounded:

- units: heater, cooler, valve, pump, mixer, splitter, flash (one inlet), conversion reactor
  (one outlet, vapour- or liquid-phase conversion reactions), recycles; compressor and expander
  with `IDAES Peng-Robinson` only;
- `property_package`: `IDAES ideal VLE` or `IDAES Peng-Robinson` (every kij 0), for benzene,
  toluene, hydrogen and methane only (hydrogen and methane vapour only);
- not: columns, two-sided exchangers, component separators, equilibrium, Gibbs and kinetic
  reactors, intercooled compressors, saturation feeds, interaction parameters, `--save`.

Anything outside it is `sim-backend-unsupported` (error) at translation: switch to DWSIM, do
not approximate the step. The IDAES packages are not benchmarked (`sim-method-unbenchmarked`,
info): say that their values are not predictive. Switching `simulator` makes filled values
`sim-stale`. A run of the small HDA recycle loop took about four minutes locally. Example:
`examples/process-hda-idaes`; details in the cheme-as-code docs (`docs/framework/idaes.md`).

## Workflow and tools

1. Write `process/simulation.yaml`:

   ```yaml
   schema: cheme/simulation/v1
   kind: simulation
   property_package: Peng-Robinson (PR)
   # always record the selection the package rests on (thermodynamic-model-selection),
   # with the reason for each fact; `cheme maturity` counts a package without one as missing
   method_selection:
     facts:
       is_polar: false              # C3 to C5 n-alkanes: nonpolar
       is_electrolyte: false        # no ions
       has_pseudocomponents: false  # pure compounds with CAS numbers, no assay fractions
       liquid_liquid_expected: false     # light alkanes are fully miscible
       vapor_association_expected: false # no carboxylic acids or HF
       pressure_value: 12           # the highest pressure of the flowsheet (the feed)
       pressure_unit: bar(a)
     # substitution: "<why a package the facts do not recommend is used; accepted by whom>"
   specs:
     K1: {outlet_pressure: {value: 8, provenance: given}, efficiency: {value: 0.78, provenance: assumed, source: vendor typical}}
     E1: {outlet_temperature: {value: 35, provenance: given}, pressure_drop: {value: 0.2, unit: bar, provenance: assumed}}
     C1:
       light_key: C3
       heavy_key: NC4
       light_key_in_bottoms: 0.01
       heavy_key_in_distillate: 0.02
       reflux_ratio: 3.5
       condenser_pressure: {value: 5.2, provenance: assumed}
       reboiler_pressure: {value: 5.5, provenance: assumed}
   ```

   Steps map to unit operations by their DEXPI class; give `unit:` where the class does not
   say. Wet gas cooled below its dew point needs a drain: give the cooler (or the intercooled
   compressor) a second outlet port `condensate` to a product, else the water stays in the gas.
   Give machines a `drive_efficiency` (motor and gear) when their energy stream stands
   for electric power (utility balances, LCA). `exclude: [step or block ids]` simulates the rest: the streams from the excluded part
   need their values (given or assumed). Use it to simulate what the units cover while a part
   (a double column with side draws) is still assumed. Give each heater, cooler and column an
   energy stream to a utility terminal (`category: utility`, with `utility: {kind,
   supply_temperature, return_temperature, min_approach}` where the design basis states
   them), so the run checks the utility levels and counts every duty once. Adsorbers and membranes are
   component separators (`recoveries`): a specified split (`basis: specified`), not a
   prediction; give `basis_source` (vendor data, a cited module, a DESIGN.md decision) and
   `operating_basis` (the conditions it holds for), else `sim-specified-unsourced` (warning).
   The run record marks such a unit `basis: specified` with a note: report its converged
   result as the stated split, never as a predicted one (which techniques core predicts:
   skill `separation-method-selection`). An adsorber's recoveries can follow from
   `process/adsorption.yaml` (`cheme process adsorption`, skill `unit-ops-adsorption-and-drying`):
   when they agree, the model basis reports it `adsorption-equilibrium`, calculated but not
   simulated. A main heat exchanger is a multi-stream exchanger
   (`outlet_temperatures` for all streams but one). Flash and column outlets are recognised by port ids (`vapour`, `liquid`, `top`,
   `bottom`), exchanger sides by matching ids (`hot_in`/`hot_out`); else give `outlets:` or
   `pairs:`.
2. `cheme validate`: `simulation.yaml` against its schema, specs for unknown steps.
3. `cheme process simulate --check`: solves and reports, writes nothing. Read every
   `sim-deviation` (a given or assumed value the simulation contradicts) and the summary lines
   (duties, power, minimum reflux, stages).
4. Start a column with the shortcut method (keys, reflux ratio); the minimum reflux ratio and
   stages it prints give the rigorous column (`stages`, `feed_stage`, `condenser_spec`,
   `reboiler_spec`) its first numbers. A reflux ratio below the minimum does not converge.
5. `cheme process simulate --fill [--save process/simulation.dwxmz]`, then
   `cheme process props --fill` for phase, density and enthalpy, `cheme process build`
   and `cheme validate`. Record the run in `PROGRESS.md`. `--fill` also writes
   `process/simulation-run.json` (generated, never edited: convergence, unit results, stream
   values, input fingerprints), which the viewer shows; commit it with the flowsheet.

## Validation and failure handling

- `sim-unmapped`: a step's class maps to no unit, a unit has the wrong number of streams, or
  energy streams do not fit; give `unit:` or split the step.
- `sim-spec`: a spec is missing, contradictory or out of range; the message names it.
- `sim-property-package` (error): the package is not one the worker runs; choose from the
  hint. `sim-method-not-recommended` (warning): the recorded `method_selection` does not
  recommend it; switch to a recommended package or record the approved reason as
  `method_selection.substitution` (then `sim-method-substituted`, info, stays visible).
  `sim-method-selection`: the recorded facts are incomplete or invalid; ask for the missing
  ones.
- `sim-not-converged` (exit 3): no stream value is written (the run is recorded). Check the specs for feasibility (reflux
  above the minimum, outlet temperatures that the duty can reach, a column spec its stages can
  meet), save the flowsheet with `--save` and open it in DWSIM to look.
- `sim-recycle` (info): where a loop was torn; give `tear_streams:` to tear elsewhere, and
  `guesses: {stream: {temperature, pressure, flow, composition}}` in `simulation.yaml` if it
  converges slowly. A guess is no stream value: never put one into the flowsheet as `assumed`,
  where it would stay and contradict the result.
- `sim-deviation`: never overwrite the given or assumed value to silence it. Either the
  assumption is wrong (change it, with a decision in `DESIGN.md`) or a spec is (change the
  spec); an engineer decides which.
- `sim-stale`: feeds, specs, package or DWSIM changed since the values were written; fill again.
- `sim-run-stale` (`--check`): `process/simulation-run.json` records a run from other inputs;
  fill again (`sim-run-missing`, info: no run recorded for the case yet).
- Energy checks of a converged run (independent of the duty balance DWSIM closes itself; the
  record keeps them under `energy`, `cheme process energy` prints them):
  `sim-temperature-cross` (an exchanger's hot and cold composites cross: the duties balance
  but no counter-current exchanger does it; change the outlet specs or split the duty),
  `sim-exchanger-approach` (below `min_approach`; declare it in `simulation.yaml`, or per
  exchanger spec, from the design basis: never chosen silently; `sim-approach-undeclared`,
  info, until then), `sim-exchanger-zones` (info: a stream changes phase, so the internal
  approach is not checked; say so in the review or check the zones in a rating tool),
  `sim-utility-level` (the utility terminal's declared temperatures cannot serve the duty),
  `sim-energy-unbalanced` (a unit's or the plant's enthalpy closure fails: check convergence
  and specs) and `sim-energy-unsupported` (info: a reactor whose property package's enthalpy
  reference is not verified, and units without an established duty sign; report it as
  unsupported, never estimate a residual) and `sim-energy-stated` (info: a component
  separator's imbalance, enthalpy out minus in from the solved streams, positive: heat it would
  have to take in; the plant closes with it as a stated residual, `stated_kW`; it is no utility
  and not the real unit's duty, so name it in the review and account for the real absorber's
  or dryer's duties separately). Reactors close on a heat-of-formation basis
  (`basis: formation` in the record): DWSIM's enthalpy flows plus `sum (n_out - n_in)
  dHf_298` on DWSIM's own formation enthalpies, which its reactor duty takes. What is
  verified (DWSIM 9.0.5, live tests): the reference state (each component's ideal gas at
  298.15 K = 0, no formation enthalpies) for Peng-Robinson, PR78 and SRK, not for NRTL; the
  duty identity for vapour ammonia synthesis at 10 bar, with conversion, equilibrium and
  Gibbs reactors under Peng-Robinson and the conversion reactor under PR78 and SRK; and a
  liquid-phase conversion reactor (MTBE synthesis, 298.15 K, 2000 kPa) under all three: a
  liquid's enthalpy is the package's departure from the ideal gas (about minus its heat of
  vaporization), so liquid streams need no correction. The liquid reaction heat under
  Peng-Robinson is within 2 % of a calorimetric value (10 % asserted) but about 17 % from a
  second one (published values span -33.8 to -39.8 kJ/mol); that accuracy is shown for this
  one reaction only, and the closure checks conservation, not accuracy. Other
  packages leave reactors unsupported. `sim-formation-data` compares the project's formation
  enthalpies with DWSIM's: a warning (and `predictive.formation-data` fails) where values
  declared in `materials.yaml` make a reaction heat that differs by more than 1 % of it (the
  data tolerance, about the spread between compilations: ammonia ATcT -45558 against JANAF
  -45898 kJ/kmol is 0.74 %); a smaller nonzero difference, chemicals' fallback values or a
  missing value are info and a recorded limitation: name them in the review. The record
  gives each component's difference in kJ/kmol. Give every reacting component
  `ideal_gas.dHf_298` with its source (`cheme chemistry thermo` prints chemicals'); on a
  warning, check both sources and say which value the design rests on, never edit a value
  to make a check pass.

Double columns (air separation): the HP column with `condenser: partial` (GAN as
`vapor_flow`, liquid nitrogen as distillate) and `reboiler: false`, LIN as a liquid side draw
from stage 2 (not the condenser stage); the LP column with `condenser: none`, the liquid
nitrogen fed to stage 1, GOX as a vapour side draw from the last stage, LOX by
`reboiler_spec`, and `heat_integration: {condenser_of: <HP column>}`. Read `sim-reboiler-unbalanced`
as the liquid the columns can (or cannot) make, `sim-approach` as a pressure problem. DWSIM's
column solver is sensitive: start with few stages (40 HP, about 60 LP) and the feeds placed as
in the example, then add stages; a column that does not converge is reported, never estimated.

Reactors are simulated from the flowsheet (skill `reactions`): a step with `reactions:` is a
conversion reactor, `reactor: equilibrium` and `reactor: gibbs` DWSIM's equilibrium and Gibbs
reactors (each with its own reaction set). Their spec is `mode` (`isothermal`, `adiabatic`, or
`outlet_temperature` with `outlet_temperature`) and `pressure_drop`. An equilibrium takes ln K
from the reaction's `equilibrium_constant`, else from DWSIM's own formation data, so it may
differ from `cheme process propagate` (ideal gas, the components' `ideal_gas` data): that
deviation is the check. A reactor with one outlet must stay all vapour (the run says when
liquid forms); give it a `liquid` outlet otherwise (a liquid-phase reactor: `vapor` and
`liquid` outlets). DWSIM converts a liquid-phase reaction's key component in the inlet's
liquid phase only: an inlet the package splits (Peng-Robinson and SRK can split a polar and a
hydrocarbon liquid into a spurious "vapour" far above their vapour pressures) reaches less
than the declared conversion (a `vapor` reaction likewise converts only the inlet's vapour,
`mixed` the whole inlet). simulate reports each conversion reactor's `extents` and
`conversions` from DWSIM's stream flows (summary and record) and raises
`sim-conversion-mismatch` (error) when a key component's conversion is more than 0.001 off the
declared one; with several reactions on one key the declared conversions add up on its inlet
flow. Bring the inlet to one phase (temperature or pressure ahead of the reactor) or declare
the reaction `phase: mixed`; a co-reactant that runs out before the key also falls short.

A fixed bed (`reactor: pfr` with `bed:` and `catalyst:`, rate laws in `reactions.yaml`) is a
`kinetic_pfr` unit, **coupled as an external unit, not a native DWSIM reactor**. DWSIM 9.0.5's
kinetic PFR cannot take cheme's rate laws without loss (no `(1 - Q/K)` term, no `(T/T_ref)^n`,
its own property package for partial pressures and enthalpies), so cheme-as-code solves the bed
(the same model as `cheme process propagate`: 1D pseudo-homogeneous plug flow, ideal gas,
effective particle rates, adiabatic, isothermal or cooled, Ergun pressure drop only with the
bed's diameter, viscosity and particle data) at the inlet DWSIM gives, and DWSIM sees a
conversion reactor with the bed's conversions, outlet temperature and pressure drop. An outer
loop repeats the DWSIM solve until the bed at the solved inlet reproduces DWSIM's outlet:
`specs.<id>.coupling` sets `tolerance` (relative, component flows and pressure; default 1e-4),
`temperature_tolerance` (K, 0.05) and `max_iterations` (DWSIM solves, 30). Not converged means
nothing is written. No `mode`, `outlet_temperature` or `pressure_drop` for it (the bed sets
them); one outlet, vapour-phase reactions only; a reaction whose reactants are all formed in the
bed (series reactions) cannot be written as an inlet conversion and is refused. The run record
marks every unit `coupling: native` or `external-unit`, the latter with its `outer_loop`
(iterations, residuals, the bed at the last inlet). `sim-coupling` (info) says how it converged;
`sim-coupling-energy` warns when DWSIM's property package needs a duty beyond 5 % of the reaction
heat to reach an adiabatic bed's outlet temperature (the ideal-gas bed and the package disagree
on the enthalpies, typical at high pressure).

A stirred tank or batch (`reactor: cstr` with `tank:`, `reactor: batch` with `batch:`) is coupled
the same way: cheme-as-code solves it (`domains/process/stirred_tank.py`) at the inlet DWSIM
gives, DWSIM sees a conversion reactor with its conversions and outlet temperature (isothermal
when the tank stays at its inlet's temperature), and the outer loop runs until they agree. A
liquid tank's reactions are liquid-phase in DWSIM too; a batch's outlet keeps the inlet's
pressure (its vessel's pressure is not the stream's).

Not simulated (keep these parts assumed and `exclude:` them): kinetic reactors other than a
fixed bed, a stirred tank or a batch, solids, a liquid side draw from the condenser stage. Evaporators and dryers need `unit:` (their heat duty matters; a component
separator would drop it). A unit simulates one duty: a machine's cooling water or a cooler's pump
power stays a given or assumed value.

## Outputs and provenance

Simulated streams get `temperature`, `pressure`, `flow` and `composition` (energy streams
their `duty`) with `provenance: calculated`, source `cheme process simulate: DWSIM
<version>, <property package>` (`IDAES <version>` with the IDAES backend) and a fingerprint of the simulator model. Given and assumed values
stay; `--save` writes the DWSIM flowsheet (`.dwxmz`, a generated file: commit it only if the
project wants it). The specs and their provenance in `simulation.yaml` are the record of what
was assumed.

## Required human judgment

The property package and its validity for the mixture and conditions; every assumed spec
(efficiencies, pressure drops, approach temperatures, reflux ratio, column stages and key
specs); whether a deviation means the assumption or the spec is wrong; whether a converged
recycle or column is physically sensible. A simulated value is no more certain than its specs.

## References

- `process-design`, `thermodynamic-model-selection`, `separation-method-selection`
- `cheme schema process-simulation`; examples `examples/process-simulation` and
  `examples/process-separation` in the cheme-as-code repository
- DWSIM: https://dwsim.org (GPL v3); the Fenske-Underwood-Gilliland shortcut and the rigorous
  column are DWSIM's
