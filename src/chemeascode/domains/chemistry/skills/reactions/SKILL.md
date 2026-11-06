---
name: reactions
description: Write the chemical reactions of a process in process/reactions.yaml (stoichiometry over the components of materials.yaml, conversion of a key component, heat of reaction, equilibrium constant, catalyst, sources), give components ideal-gas formation data, and name the reactions and the reactor model (conversion, equilibrium, gibbs) on the reactor steps of process/flowsheet.yaml, so that cheme validate balances elements and extents, cheme process propagate solves the reactors and cheme process reactors reports duties and the distance from equilibrium. Use when a process has a reactor, or a reaction, conversion or catalyst is added or changed.
---

# Reactions

## Purpose and when to use

Reactions are YAML, like the materials: `process/reactions.yaml` (schema
`cheme/reactions/v1`) holds each reaction's stoichiometry, and every reactor step or block
of `process/flowsheet.yaml` names the reactions that take place in it. With reactions named, a
reactor no longer fails the component balance: `cheme validate` checks that mass and every
element balance and that the reactions' extents explain each component's change, and
`cheme process propagate --fill` computes the outlet of a conversion reactor. Use this
skill whenever a process has a reactor, or a reaction, conversion or catalyst changes.

## Required inputs and missing inputs

- The components with a `formula` each (`materials`, `property-retrieval`): the element balance
  needs them, and `molar_mass` for the extents.
- Per reaction: the stoichiometry, which component the conversion refers to (`key`) and the
  conversion per pass where it is a design input, with its source.
- Optional: the heat of reaction (kJ per kmol of extent as written, negative when exothermic),
  the catalyst, literature references.
- For equilibrium and Gibbs reactors and for duties: each component's `ideal_gas` data
  (`cheme chemistry thermo NAME ...`, extra props: ATcT formation enthalpy, entropy and
  Poling's heat capacity, valid to 1000 K; `--fit 298.15,1500` fits the heat capacity to a
  wider range), or a reaction's own `equilibrium_constant` (`ln K = a + b/T + c ln T + d T`).

If the reaction set itself is open (side reactions, by-products, an equilibrium-limited step),
ask: that is the chemist's decision. Never invent a conversion; when none is known yet, leave
it out and give the reactor's outlet as `assumed`.

Where the route or its conditions still have to be found in the literature, gather the evidence
first (skill `reaction-evidence-search`, `process/reaction-evidence.yaml`). Choose the model
from it with skill `route-selection`: the model basis names the reactions written here, and
each value taken from the evidence cites its observation in `source`.

## Workflow and tools

0. For a known industrial process, start from the reaction library: `cheme chemistry library`
   lists 23 processes (ammonia, methanol, steam reforming, shift, methanation, ethylene oxide,
   sulfuric and nitric acid, Claus, Fischer-Tropsch, hydrotreating, styrene, acrylonitrile,
   propylene oxide, ethane cracking, vinyl chloride, formaldehyde, maleic anhydride, cumene,
   ethylbenzene, MTBE, HCN); `cheme chemistry library methanol` shows one, `--add` adds its
   components (with ideal-gas data and critical constants), reactions and typical catalysts to
   the plant's files without touching what is there (an id the plant has with other data is a
   conflict). The catalyst windows are typical ranges (assumed): confirm them for your licensor
   or vendor, and add the kinetics you have. Each entry shows its `model basis`: `equilibrium`
   (an ideal-gas equilibrium limit, no rate law) or `stoichiometry_only` (no conversion,
   selectivity, equilibrium basis or rate law). Importing an entry is chemistry, not a reactor
   model: choose and source that separately (a sourced conversion, an equilibrium reactor or a
   rate law with its source), never by inventing conversions or kinetics. `cheme maturity`
   reports which basis each reactor of the plant rests on.

1. Write `process/reactions.yaml` (schema: `cheme schema process-reactions`):

   ```yaml
   schema: cheme/reactions/v1
   kind: reactions
   reactions:
     - id: NH3_SYN
       equation: N2 + 3 H2 <=> 2 NH3          # for readers; not parsed
       stoichiometry: {N2: -1, H2: -3, NH3: 2} # reactants negative, products positive
       reversible: true
       conversion: {key: N2, value: 0.25, provenance: assumed, source: typical per pass}
       heat_of_reaction: {value: -91800, provenance: given, source: NIST WebBook}
       catalyst: promoted iron
       sources: ["doi:10.1002/14356007.a02_143.pub3"]
   ```

2. On the reactor step (or a block without steps), name the reactions, and give a conversion
   where this reactor's differs from the reaction's:

   ```yaml
   - {id: R1, block: LOOP, class: ReactingChemicals, reactions: [NH3_SYN],
      conversion: {NH3_SYN: 0.3}, ports: [...]}
   ```

   A block is reactive when anything inside it names reactions; a block with
   `balance_scope: reactive` and no reactions is checked on elements only.
3. Choose the reactor model on the step (`reactor:`):
   - `conversion` (the default when every reaction has a conversion): every reaction converts
     its fraction of the key component's *inlet* flow, all at once (as Aspen's RStoic).
     Series reactions on the converted stream need two reactor steps, unless the step gives a
     `selectivity:` instead: `{key: A, conversion: 0.8, products: {B: 0.7, C: 0.3},
     provenance, source}`, kmol of each product formed per kmol of the key converted, as
     papers and patents report it. The extents of parallel and series reactions follow;
     selectivities the reactions cannot give, or too few to fix every extent, are refused.
   - `equilibrium`: the named reactions reach equilibrium at the outlet stream's temperature
     (give it, `assumed`) and pressure, ideal gas; `approach: 20` takes K 20 K hotter (less
     conversion of an exothermic reaction; negative for an endothermic one). Mark the
     reactions `reversible: true`.
   - `gibbs` (no `reactions:`): the minimum Gibbs energy over every component of the streams'
     templates, ideal gas; inerts take no part.
   - `pfr`: a fixed catalyst bed, integrated along its catalyst mass from the reactions'
     `rate:` laws (1D plug flow, ideal gas): give `catalyst:` and `bed:` (`catalyst_mass`, or
     `volume`, or `tubes` x `diameter` x `length`; `heat`: `adiabatic`, `isothermal` or
     `cooled` with `coolant_temperature` and `heat_transfer_coefficient` in W/(m2 K); the gas
     `viscosity` in Pa s and a `diameter` for the Ergun pressure drop; `time_on_stream` in h
   solves it at that catalyst age, the rates times the deactivation law's activity: size the
   bed at the end of run; `diffusivity` in m2/s of the key reactant in the gas). With the
   catalyst's `particle_density` and `effective_diffusivity` (or `porosity` and `tortuosity`),
   the bed reports Weisz-Prater and Mears at its inlet and outlet (`process reactors`, bed
   `transport`) and notes a rate law that diffusion or the film limits. A rate measured on
   powder or in the kinetic regime is the catalyst's own: give it `scale: intrinsic`, and the
   bed multiplies it by the effectiveness factor at the plant's particle size. Propagate writes the
     outlet's composition, flow, temperature and pressure; the inlet needs its temperature and
     pressure. `examples/process-shift` is an adiabatic high-temperature shift bed.
     `cheme process simulate` couples the same bed to the DWSIM solve as an external unit
     (an outer loop, not a native DWSIM reactor; skill `process-simulation`).
   - `cstr`: stirred tanks from the reactions' `rate:` laws at the outlet composition: give
     `tank:` (`volume` m3 or `residence_time` s, V / Q0 on the inlet's volumetric flow, of each of
     `count` equal tanks in series; `heat`: `isothermal`, at the outlet's given temperature or
     else the inlet's, or `adiabatic`; `catalyst_loading` kg/m3 for rates per kg of catalyst).
     An adiabatic tank's temperature is the steady state nearest the inlet's; a tank can have
     others (ignition), so check the reported temperature against the expected regime.
   - `batch`: the inlet is the charge (its flow the charge per hour), the outlet its composition
     at the end: give `batch:` (`time` s, or `target: {key, conversion}`; `heat`;
     `catalyst_loading`). A target the reactions cannot reach (equilibrium, a reactant used up)
     is reported, not extrapolated. `process reactors` gives the profile, the heat released per
     kmol of charge and the largest heat release per m3.
   - `semibatch`: a liquid batch with feeds dosed into its charge (an exothermic reagent fed to
     a charge, the usual fine-chemical step): give `batch:` with `dosing: [{stream, time}]` (or
     `profile: [[s, share], ...]` of constant-rate segments, shares adding up to 1; `start` s
     delays a dose). Each dosed `stream` is an inlet of the step, its flow the amount dosed per
     hour of charge; the step's one other inlet is the charge. `time` or `target` is then the
     post-reaction after the last dose (neither: the batch ends with the dosing). `process
     reactors` gives the accumulation of the dosed reactant over time and its maximum, the
     cooling-failure temperature at the worst moment (the MTSR of a semi-batch, the dosing
     stopped) and, isothermal, the peak cooling duty per m3 of the final content, the reaction's
     heat and the doses' warming together. A slow reaction accumulates the reagent: dose more
     slowly, or raise the temperature within the rate law's range, until the accumulation is
     low. Not coupled to the DWSIM solve (its reactors take one inlet); `process propagate`
     solves it.
   - A liquid `batch` or `semibatch` that gives off a gas (HCl from a chlorination or
     phosgenation, CO2, HBr from a bromination) takes `batch.vent: {stream, components: [ids],
     fraction: {id: share}}` (ADR 0054): the listed components leave the liquid as they form,
     by the vent `stream`, an outlet of the step besides the liquid's (two outlets). They do
     not accumulate in the liquid and count in neither its volume, its concentrations nor its
     heat capacity, so they need no `liquid_molar_volume` or `liquid_heat_capacity`; a
     `fraction` below 1 keeps the rest dissolved (then it needs them). The share is of what
     each reaction forms: a reaction that consumes a vented gas (benzyl alcohol + HCl, Ac2O +
     HCl) takes it from the liquid (charged, dosed or the dissolved rest), never back from the
     vent. Write the `heat_of_reaction` with the gas formed as a gas at the vessel's
     temperature (as reaction calorimetry with off-gas measures it): the vent carries the gas's
     own enthalpy and no heat of desorption is added. A dosed gas (phosgene, Cl2, methyl
     nitrite) dissolves on entry like a liquid dose, with its `liquid_molar_volume` and
     `liquid_heat_capacity`, but no heat of absorption or condensation is added (HCl into water
     about -75 kJ/mol, phosgene about -24, Cl2 about -20): write the `heat_of_reaction` of the
     reactions that consume it with the dosed gas as a gas (as calorimetry with gas dosing
     measures it), so this heat is counted as the dose reacts. That keeps the MTSR
     conservative, but the cooling duty during dosing leaves out the absorption of the gas not
     yet reacted; on the dissolved basis both miss it. When only part is taken up, give the
     dose `absorbed: 0.9`: the rest passes straight through to the vent, warmed to the vessel's
     temperature (its ideal-gas cp, else left out and noted). `process propagate` writes both
     outlets (composition, flow, the liquid's temperature and pressure) and the balance closes
     over them; `process reactors` gives the vent's kmol/h and its peak rate in kmol/(s m3) of
     the final content, `cheme process recipe` the peak in kmol/s and m3/h per batch and what
     one batch gives off: size the off-gas line and scrubber from these. The vent stream's
     template must hold the vent's components and what a passing dose carries. A reactant
     listed in `vent.components` vents nothing of itself: only what the reactions form vents; a
     dosed gas that escapes is `absorbed`. Do not model the gas as a dissolved liquid component
     plus a degassing split: that overstates the volume and gives no off-gas profile.
   Tanks and batches hold gas-phase or liquid-phase reactions (one phase; a semi-batch liquid). A liquid needs
   `liquid_molar_volume` for concentrations and space times, and for an adiabatic tank or a
   liquid duty `liquid_heat_capacity` (kJ/(kmol K)) and each reaction's `heat_of_reaction`. A
   gas uses the ideal-gas data. `process simulate` couples them to the DWSIM solve as external
   units, like a fixed bed (skill `process-simulation`).
   **Liquid-phase reactions** (`phase: liquid`) reach equilibrium on their own
   `equilibrium_constant`, which names its `basis`: `mole_fraction` (ideal solution),
   `activity` (UNIFAC activity coefficients from the components' CAS numbers, extra `props`;
   `activity_model: ideal` at the top of `reactions.yaml` sets them to 1) or `concentration`
   (kmol/m3, from each component's `liquid_molar_volume` in m3/kmol). Ideal-gas formation data
   give the K of the gas and are not used for a liquid. One equilibrium step holds gas-phase or
   liquid-phase reactions, not both. Write K on the basis the source reports it, never
   converted silently (a K on mole fractions is not one on activities). The duty of a liquid
   reactor is on the ideal-gas basis without the heats of vaporization (`duty_basis` says so).
   Ideal gas is a limit: at high pressure real equilibria lie further to the fewer moles
   (ammonia at 450 C and 300 atm: 31 % ideal, 35.5 % measured). Give the components their
   `critical:` constants (`cheme chemistry thermo NAME` prints them) and the reactor
   `fugacity: peng_robinson` (Peng-Robinson, no interaction parameters: 34.4 % there); `approach`
   remains for the kinetic distance from equilibrium.
4. Give the reactor its catalyst: declare it in `process/catalysts.yaml` (schema
   `cheme schema process-catalysts`: active phase, promoters, support, `physical` (form,
   particle diameter in m, particle and bulk density, bed voidage, surface area), `window`
   (temperature K, pressure kPa(a)), `space_velocity` (`gas: dry` when a GHSV is quoted on
   dry gas), `poisons` by component id,
   `deactivation` (with `law: first_order | power`, `kd` in 1/h and `order`, the activity
   over time on stream), `price`, each block with provenance and source) and name it on the step
   (`catalyst: FE_NH3`). Kinetics go on the reaction as `rate:` (power law or LHHW, per kg of
   catalyst or per m3, on partial pressures in bar or concentrations in kmol/m3, for a liquid
   also on `mole_fraction` or `activity`, `reverse: equilibrium` for the (1 - Q/K) factor, Q on
   the basis of the reaction's K, `catalyst:` it was measured on, and its validity
   `temperature_range`). A fixed bed (`pfr`) is a gas: it refuses liquid-phase reactions. For an elementary gas-phase reaction, `cheme chemistry kinetics -r
   CH4=methane -r OH=[OH]` (network; RMG with `--rmg-endpoint`) prints a `rate:` from NIST and
   RMG with its confidence.
5. Where the catalytic mechanism is known, give the reaction a `mechanism:` (mean field): the
   `site_density` (mol/m2), the `adsorbates` (ids ending in `*`, e.g. `CO*`; formula = id
   without the `*`) and the elementary `steps` (stoichiometry over gas components, adsorbates and
   the free site `*`; `forward` and `reverse` rate constants per site in 1/s with pressures in
   bar, or `sticking` for an adsorption), with provenance and source. `cheme chemistry
   microkinetics ID -T 500 -p CO=0.01 -p O2=0.1` solves its steady state: coverages, TOF, the
   degree of rate control of every step (which step to improve), the apparent activation energy
   and the orders; `--cantera` checks it with Cantera, `--export mech.yaml` writes Cantera's
   input. Use it to judge a lumped `rate:` (its orders and Ea should match). A step may give
   `energies:` instead of rate constants (DFT reaction energy and barrier in eV, e.g. from
   Catalysis-Hub or a paper, with the DOI in `source`): transition state theory
   (k_B T/h prefactors); an adsorption keeps its `sticking` and desorbs over its binding energy.
   Treat DFT energies as assumed: errors of 0.1-0.2 eV change rates by orders of magnitude.
6. To get a lumped rate for a fixed bed, fit one: from measurements, write
   `experiments/kinetics/<name>.yaml` (schema `cheme schema kinetic-data`: the reaction, the
   basis, per point temperature, partial pressures in bar and rate, with provenance and source),
   or sample the mechanism (`cheme experiments sample-mechanism ID -T 480 -T 520 -p
   CO=0.008,0.0125 -p O2=0.08,0.125 --sites-per-kg 1e-4 --out experiments/kinetics/x.yaml`; the
   sites per kg from the dispersion), then `cheme experiments fit-rate FILE [--form lhhw
   --adsorb CO --power 2] [--reverse]`: the `rate:` to paste, each parameter with its 95 %
   interval. A fit holds inside its data's range only (`temperature_range` is set to it).
   Conversions measured in reactors (what papers report more often than rates) go into the
   same file as `integral:` points (`reactor: pfr | batch | cstr`, `temperature`, `time` s,
   the feed's `concentrations` in kmol/m3, `conversion` of the file's `key`): `fit-rate` fits
   a power law on concentrations through isothermal reactors of constant density (the
   reactants' orders fixed at their coefficients, `--order-of A` fits one), with intervals.
7. To choose the reactor type for a network with rate laws, run `cheme process
   reactor-choice NODE --product P [--key K] [--tanks 3] --svg build/choice.svg`: the yield and
   selectivity of P against the key's conversion for a PFR, one CSTR and N CSTRs in series
   (ideal, isothermal at the inlet), and the PFR's instantaneous selectivity. A series product
   peaks (the space time of its peak is printed); parallel reactions of a lower desired order
   favour mixing (a CSTR), of a higher order plug flow. It compares ideal reactors only: heat
   removal, mixing and the rate law's range decide the real choice. `--region-svg FILE` adds
   the candidate attainable region in the plane of the key and the product (PFR, CSTR, CSTR
   then PFR, and mixing: their convex hull) and names the structure of its highest yield (Van
   de Vusse kinetics: a CSTR before a PFR). It is a candidate, not a proven region.
8. For an exothermic reaction, run `cheme process reactor-hazards`: the adiabatic temperature
   rise, the MTSR after a cooling failure (a batch: all its charge; a CSTR: its unconverted
   key; a semi-batch: the dosed reactant at its largest accumulation, at the worst moment over
   the run, so a dosing-controlled step screens lower than its batch; a vented gas leaves as it
   forms and adds nothing to it), the MTT (the reactor's `hazard.mtt`, else the lowest boiling
   point of what boils in the liquid at the reactor's pressure: the normal boiling point from
   90 to 110 kPa(a), else Clausius-Clapeyron with `heat_of_vaporization`, which you give for
   a pressurised or vacuum reactor; a vent component, a dosed gas and a dissolved gas (under
   5 % of the liquid, boiling below the process temperature) are left out with a note, and
   with nothing else left set `hazard.mtt`; a solvent at reflux sets it, at or below the
   process temperature) and, with `hazard: {td24: K, provenance, source}` from calorimetry,
   Stoessel's criticality class (classes 3 to 5 are warnings); for a cooled bed, the hot spot's
   sensitivity to the coolant temperature. Never estimate a TD24: without one the class stays
   open (`cheme.reactor-hazard-missing`). With several reactions the output gives each one's
   dT_ad and MTSR; where a slow side reaction sets the MTSR and the main reaction is what you
   screen, say so with `hazard.reactions: [MAIN]` and give the reason in `source` (the side
   reaction's value stays in the output). A semi-batch prints its MTSR over the batch (an
   initiation charge, the end of each dosing segment). A vented batch reports its gas release
   at the MTSR (`cheme.reactor-hazard-vent`): give `hazard.vent_capacity` (m3/h at the vessel's
   pressure) from the vent sizing; the blocked-vent pressure is not screened. These are screening values for the HAZOP study, not a
   reaction-hazard assessment. A phase change is no reaction: a precipitation, dissolution or
   wash loss belongs in a `crystallizer:` on the step (`spectators:` for the other solutes of
   the liquor; skill `separation-method-selection`). Where one stays written as a reaction,
   give it `kind: phase-change` (one component into one other of the same formula, one of them
   `phase: solid`, is recognised as one unless it declares a `heat_of_reaction`): a step whose
   reactions are all phase changes is not screened (`cheme.reactor-hazard-phase-change`,
   info), and a step with both takes dT_ad and the MTT from its reactions alone (a semi-batch's MTSR is its model's, the phase changes' heat included; a note says so). A recognised phase change
   with a heat of reaction (a caustic dissolution, an acid dilution) stays screened, its heat
   in dT_ad.
9. Where the reaction data are uncertain (a fit's intervals, a literature range), give them:
   `rate.uncertainty: {A: {gsd2: 3}, Ea: {distribution: normal, cv: 0.05}}`, and an
   `uncertainty:` on `heat_of_reaction`, `equilibrium_constant` (of K) or `conversion` (the
   shared model: lognormal `gsd2` or `pedigree`, `normal` `cv`, `triangular`/`uniform` `low`
   and `high`); on a step's `selectivity:`, `uncertainty: {conversion: {gsd2: 1.1}, products:
   {B: {gsd2: 1.2}}}` (each figure its own, none assumed from the provenance; give only the
   selectivities that fix the extents, as independent draws of more break their balance).
   `cheme process reactor-uncertainty NODE [--samples 200] [--seed 1]` samples them through
   the step's reactor (bed, tank, batch, conversion, selectivity as propagate evaluates it)
   and prints the spread of the key's conversion, each component's outlet flow and the outlet
   and highest temperatures. Only what the model reads is sampled (a gas's heat of reaction
   comes from the ideal-gas data, a kinetic reactor ignores `conversion`, a selectivity step
   reads none of its reactions' figures, K counts only with `reverse: equilibrium`); the
   others are listed as not used (`not_used` in `--json`) with the reason, and with nothing
   used left the command exits 2 ("nothing to sample"). Nothing is written, and an
   uncertainty never makes an outlet stale.
10. Run `cheme process propagate --fill`, then `cheme validate`, then `cheme process reactors`:
   per reactor the extents, the heat of each reaction and ln K at the outlet, `ln(Q/K)`
   (0 at equilibrium, negative short of it), the rate at the outlet where there is a rate law,
   and the duty H(out) - H(in) on the elements basis (give every stream's temperature).

## Validation and failure handling

- `cheme.reaction-element-balance`: the atoms differ; correct the coefficients or a formula.
- `cheme.reaction-element-balance-not-evaluable` (info): a component has no `formula`.
- `cheme.reaction-component`, `cheme.reaction-conversion`: an undeclared component, or a
  conversion key that is no reactant.
- `cheme.process-reaction`: a step names an undeclared reaction, or a conversion of a
  reaction it does not name.
- `cheme.process-balance` on a reactive node: `element X ... in, ... out` means the streams
  lose or create atoms; `... not explained by reactions ...` means the streams balance but the
  declared reactions cannot produce that composition change (a missing side reaction, or a
  wrong assumed composition).
- `cheme.process-propagate-reactor`: the conversions consume more of a component than is
  fed, an equilibrium has no outlet temperature, a component lacks ideal_gas data, or a
  temperature is outside a heat capacity's range.
- `cheme.process-reactor`: a model that cannot be solved as declared (a conversion reactor
  without conversions, an equilibrium without reactions, a Gibbs reactor naming reactions,
  `approach` without equilibrium; an irreversible reaction at equilibrium is a warning).
- `cheme.process-catalyst`: an undeclared catalyst (error); a reactor stream outside the
  catalyst's temperature or pressure window, a poison in a feed, or a rate measured on another
  catalyst (warnings). `cheme.catalyst-*`: the catalysts file itself (densities, voidage,
  poisons that are no component). `cheme.reaction-rate`: a rate naming an undeclared
  component.
- `cheme.reaction-phase-basis` (warning): a K or rate on partial pressures for a liquid, on a
  liquid's mole fractions or activities for a gas, or on a liquid's basis without
  `phase: liquid`.
- `cheme.reaction-mechanism`: an elementary step that does not balance its atoms or its sites,
  or names an undeclared component.
- `cheme.process-heat-of-reaction` (warning): a given heat of reaction more than 2 % from
  the formation data; check the coefficients and the sources.

## Expected outputs and provenance

The edited YAML, reviewed in the diff. Every conversion and heat of reaction has a provenance
and a source; reactor outlets propagate writes are `calculated` and become stale when the
reaction, the conversion or the feed changes.

## Required human judgments

- The reaction set: main and side reactions, which are neglected, and their key components.
- Conversions and selectivities as design inputs, and the reactor model: a conversion reactor
  says nothing about equilibrium or kinetics, so check with `cheme process reactors` that a
  conversion is reachable (`ln(Q/K)` below 0) at the reactor's temperature and pressure.
- The approach to equilibrium, and whether the ideal-gas limit is good enough.
- The catalyst choice, its window and lifetime, and whether published kinetics apply to it
  (another catalyst, another particle size, transport limits).

## References

- `materials` (components and formulas), `property-retrieval`, `process-design` (the flowsheet),
  `reaction-evidence-search` and `route-selection` (the evidence behind the reactions).
- `cheme schema process-reactions`, `cheme schema process-flowsheet`.
