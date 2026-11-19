---
name: unit-ops-adsorption-and-drying
description: Fixed adsorbent beds and gas/liquid driers - why a bed regenerated on line needs a partner, how each regeneration method changes the equipment, cycle time, breakthrough, flow direction and channelling. Use when an adsorber, guard bed or adsorbent drier is designed or reviewed. For a solids dryer (filter-dryer, vacuum dryer) see the core model named in the skill.
---

# Adsorption and drying

## Purpose and when to use

A fixed bed is the one mass-transfer operation not at steady state: the adsorption front moves
through the bed and the outlet stays clean only until it arrives (Ray and Das, *Process Equipment
and Plant Design*, Elsevier 2020, Ch 12). Use for beds and driers of that kind.

A solids dryer (filter-dryer, agitated vacuum dryer) is a different operation: it drives
volatiles off a wet cake. Core models it as `dryer:` on the flowsheet step (ADR 0057; skills
`process-design` and `separation-method-selection`). It takes `volatiles`, a
`residual_moisture` (`mass_fraction` or `per_kg_solid`, the design input), the drying
`temperature`, `outlets: {product, vapour}`, and optionally `energy:` (cake heat capacity,
latent heats, vessel heat capacity, efficiency, `port`), a `drying_rate` (kg/(m2 h) over the
recipe vessel's `heated_area`) or a `drying_time`, and a `cake_density` that sizes the vessel.
`cheme process propagate` solves it, and `cheme process crystallizers` reports the duty. A
recipe `dry` operation `from:` the step takes its time, and `cheme.recipe-basis` names the batch
size that makes the rate with the filter and dryer times in the cycle (1.12.0). The model has no
drying curve or sorption isotherm. Do not put a `recovery:` beside a `dryer:`
(`cheme.process-recovery`).

## Required inputs and missing inputs

Adsorbate and adsorbent, phase (gas or liquid), allowed outlet concentration, whether the bed is
regenerated on line, and the regeneration method. Establish regeneration before reporting
anything missing.

## Workflow and tools

For a concept, BFD or sourced inventory, give the adsorber or drier step a `recovery:` in
`process/flowsheet.yaml` (ADR 0070): `recovery: {outlets: {PORT: {COMPONENT: fraction of its
inlet flow}}, provenance, source}`. Leave out one outlet, which takes the rest. `cheme process
propagate` then writes the outlets' flows and compositions as calculated. Their temperatures
and pressures stay as given, there is no duty, and a design spec upstream reaches past the bed.
`cheme.process-recovery` checks the declaration. The split is specified, not predicted: cite
its source (see `separation-method-selection`). In a DWSIM run (`process-simulation`) the same
split is a `component_separator` in `process/simulation.yaml` (`recoveries`, `basis_source`,
`operating_basis`). When a predicted basis is needed, write
`process/adsorption.yaml` (`cheme schema process-adsorption`) and run `cheme process adsorption`:

- a TSA with `performance: calculated`: core's equilibrium cycle from sourced isotherms (each
  with the temperature and partial-pressure range it was measured over; outside it the
  calculation is refused, never extrapolated), a measured mass transfer zone, the bed, the cycle
  and the purge. It reports breakthrough time against the adsorption step, recoveries, product
  impurity, the regeneration heat and the purge it needs, and adsorbent replacement. Copy the
  recoveries it reports into the flowsheet `recovery:` (so propagate carries them) and, where
  the plant is simulated, into `specs.<id>.recoveries` of `process/simulation.yaml`. Only the
  simulation.yaml split is compared (`adsorption-split` warning if it differs). When it agrees
  and the inputs are sourced, the model basis is `adsorption-equilibrium`, calculated but not
  simulated. A flowsheet `recovery:` alone is not compared, and the basis stays a stated split;
- a PSA (or a vendor TSA) with `performance: external`: the cited model's recoveries and
  utilities with its operating range. Core checks the range, the balance and the
  specification, not the performance. Core has no PSA cycle model.

Not modelled: the thermal front, heat losses, water on alumina (keep that layer a sourced split)
and, without a co-adsorbed component's isotherm, its loss and competition.

A bed regenerated on line needs a partner (two minimum, more if regeneration is longer than
adsorption), because a bed being regenerated is not adsorbing. A non-regenerative guard bed
changed out at turnaround, or a bed on intermittent duty, is legitimately single. The beds are
switched, so the valve manifold and sequence are part of the unit.

| Regeneration | What it adds |
|---|---|
| Temperature swing | Regeneration gas heater and route, cooler and separator for desorbate, cooling step before return; cycles of hours |
| Pressure swing | Little heat; fast-cycling valves, a blowdown path, often a vacuum pump; not for liquids |
| Displacement purge | Supply of displacing fluid and a later separation to recover it |
| Inert purge | Purge gas supply and large purge flow; only for weakly held species |

A liquid-phase bed on temperature swing is drained before the hot gas and refilled afterwards; a
liquid bed on displacement or liquid purge is never emptied.

Cycle: adsorption plus desorption plus changeover; a first assumption is desorption equal to
adsorption. Adsorption stops before breakthrough at the downstream tolerance (often 1 to 5 % of
inlet concentration, as the source reads).

Design points: downflow is normal, upflow only where velocity is low enough not to fluidise the
bed; channelling is a distribution and packing problem (inlet distributor, even loading, bed
diameter at least 20 to 30 and length at least 100 particle diameters); gas superficial velocity
typically 0.25 to 0.6 m/s; fines raise pressure drop over life, so a differential pressure
measurement is useful; in gas service a temperature wave travels with the concentration wave, so
outlet temperature rise can indicate breakthrough; porous adsorbents conduct heat badly, and
carbon beds in air carry a fire risk; two beds in series let the lead bed saturate fully.

## Validation and failure handling

Questions for a design: a regenerated bed with no standby; equipment the chosen regeneration needs
and the design lacks (a pressure-swing unit correctly has no regeneration heater); a liquid bed on
temperature swing with no drain and fill; no differential pressure across the bed; a switching
manifold that cannot isolate a bed for regeneration.

## Outputs and provenance

State the regeneration method, cycle basis and breakthrough criterion with the source for each
number. Record in `DESIGN.md`.

## Required human judgment

Adsorbent selection, regeneration method, and fire or inerting provisions for carbon need a person.

## References

- Ray and Das, *Process Equipment and Plant Design*, Elsevier 2020, Ch 12.
- `separation-method-selection`.
- Retained as general method: regeneration table logic, partner-bed argument, flow direction.
- Needs review before operational use: numeric ranges (cycle 8 to 24 h was dropped as unsourced
  beyond the book; velocities, aspect ratios, 1 to 5 % breakthrough).
