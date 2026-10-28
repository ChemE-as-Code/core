---
name: unit-ops-adsorption-and-drying
description: Fixed adsorbent beds and driers - why a bed regenerated on line needs a partner, how each regeneration method changes the equipment, cycle time, breakthrough, flow direction and channelling. Use when an adsorber, guard bed or drier is designed or reviewed.
---

# Adsorption and drying

## Purpose and when to use

A fixed bed is the one mass-transfer operation not at steady state: the adsorption front moves
through the bed and the outlet stays clean only until it arrives (Ray and Das, *Process Equipment
and Plant Design*, Elsevier 2020, Ch 12). Use for beds and driers of that kind.

## Required inputs and missing inputs

Adsorbate and adsorbent, phase (gas or liquid), allowed outlet concentration, whether the bed is
regenerated on line, and the regeneration method. Establish regeneration before reporting
anything missing.

## Workflow and tools

For a concept, BFD or sourced inventory, represent adsorption as a `component_separator` with
specified recoveries and their `basis_source` (see `separation-method-selection`): a sourced
split, labelled as stated, not predicted. When a predicted basis is needed, write
`process/adsorption.yaml` (`cheme schema process-adsorption`) and run `cheme process adsorption`:

- a TSA with `performance: calculated`: core's equilibrium cycle from sourced isotherms (each
  with the temperature and partial-pressure range it was measured over; outside it the
  calculation is refused, never extrapolated), a measured mass transfer zone, the bed, the cycle
  and the purge. It reports breakthrough time against the adsorption step, recoveries, product
  impurity, the regeneration heat and the purge it needs, and adsorbent replacement. Copy the
  recoveries it reports into the `component_separator`: the model basis then shows the split as
  calculated (`adsorption-equilibrium`), still outside the simulation;
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
