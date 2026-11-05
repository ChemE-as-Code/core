---
name: electrochemical-cell-modelling
description: Model an electrolyser or other electrochemical cell in process/cells.yaml - overall and side reactions with their electrons, electrode half-reactions, current, area, voltage and Faradaic efficiency as specified data or looked up in a measured series (performance measured), the membrane block (water dissociation efficiency, co-ion crossover, anolyte hydroxide deficit), the thermal boundary and the operating range - then run cheme process cell and link the cell to its flowsheet step. Use when a process has an electrolyser, chlor-alkali or CO2 electrolysis cell, or when its current, voltage, efficiencies or measurements change.
---

# Electrochemical cell modelling

## Purpose and when to use

`process/cells.yaml` (schema `cheme/electrochemical-cells/v1`) describes the electrochemical
cells of a process and `cheme process cell` gives their Faraday balance: extents, products per
outlet, charge and element balances, electric power, thermoneutral voltage, the heat to remove
at an isothermal boundary and the electricity per kg of product. Use this skill when a process
has an electrolyser (water, chlor-alkali, CO2 reduction) or when a cell's current, voltage,
efficiencies, membrane or measurements change. Core does not predict cell performance: the
voltage and efficiencies are **specified** (given with their source) or **measured** (looked up
in a measured series); `performance: predictive` is refused.

## Required inputs and missing inputs

- The overall reaction in `process/reactions.yaml` with its `heat_of_reaction` (skill
  `reactions`) and the electrons per extent; side reactions (hydrogen evolution beside CO2
  reduction, oxygen at a chlorine anode) with theirs. Components with formulas in
  `process/materials.yaml`.
- The anode and cathode half-reactions (ions as formula and charge, `e-`), and the
  dissociation of dissolved salts, so that the electron count is checked.
- The current per cell, the cells in series, the active area, the thermal boundary
  (`isothermal` with the temperature).
- Specified performance: the voltage at the terminals and the Faradaic efficiency (and side
  reactions' current fractions), each `given` with its source, and the operating range they
  hold for.
- Measured performance: a measurement file `experiments/electrochemistry/<id>.yaml` (skill
  `experiment-reproduction`), the product the overall reaction forms and the side products.
- A membrane cell: the membrane kind and bias, the water dissociation efficiency (given, or
  from the measurement) and the co-ion split of the current it does not carry by water
  dissociation (`{K+: 0.34, HCO3-: 0.66}`).

Never assume a voltage, an efficiency or a water dissociation efficiency; ask, or mark the
value `assumed` with its basis and expect `cheme.cell-unsourced`.

## Workflow and tools

1. Write the reactions and materials first (skills `materials`, `reactions`).
2. Write the cell (`cheme schema process-cells`). Specified:

   ```yaml
   - id: PEM-1
     reaction: WS
     electrons: 2
     electrodes: {anode: {species: {H2O: -1, O2: 0.5, H+: 2, e-: 2}},
                  cathode: {species: {H+: -2, e-: -2, H2: 1}}}
     current: {value: 20, unit: kA, provenance: given, source: "..."}
     active_area: {value: 1, unit: m2, provenance: given, source: "..."}
     faradaic_efficiency: {value: 0.98, provenance: given, source: "..."}
     voltage: {value: 1.9, unit: V, provenance: given, source: "..."}
     thermal: {kind: isothermal, temperature: {value: 80, unit: °C, provenance: given}}
     operating_range: {temperature: [323.15, 363.15], current_density: [5000, 30000], source: "..."}
   ```

   Measured: `performance: measured`, `measurements: {file, product, side_products}`, the
   current and the active area, and no voltage or efficiency of its own; the side reactions
   without `current_fraction` (the measurement's side products give it):

   ```yaml
   - id: BPM-1
     performance: measured
     reaction: CO2R
     electrons: 2
     current: {value: 0.75, unit: A, provenance: given, source: "..."}
     active_area: {value: 5, unit: cm2, provenance: given, source: "..."}
     side_reactions: [{reaction: WS, electrons: 2}]
     measurements: {file: experiments/electrochemistry/rbpm.yaml, product: CO, side_products: [H2]}
     membrane: {kind: bipolar, bias: reverse, co_ion_crossover: {K+: 0.34, HCO3-: 0.66}, source: "..."}
     thermal: {kind: isothermal, temperature: {value: 25, unit: °C, provenance: given}}
   ```

3. Run `cheme process cell` (`--json` for the record) and fix the findings; `cheme validate`
   reports them too.
4. Link the cell to its flowsheet step (`flowsheet: {step, electricity, heat}`) and write the
   cell's power and heat duty on the two energy streams; electricity is counted once, never as
   heat as well.
5. Carry the membrane's anolyte hydroxide deficit (kmol/h) and the co-ion fluxes to the
   electrolyte management (dosing, reservoir, purge); they are not in the Faraday balance.

Keep two quantities apart throughout:

- **Faradaic efficiency (FE)**: the share of the current that forms a product at the
  electrodes. It sets the extents, the products and the heat.
- **Water dissociation efficiency (WDE)**: the share of the current a bipolar membrane carries
  by dissociating water; the rest is carried by co-ions (K+ to the cathode, HCO3- or CO3-2 to
  the anode), which shifts the electrolytes' composition. It changes neither the extents nor
  the heat.

## Validation and failure handling

- `cheme.cell-input-missing`, `cheme.cell-unsupported` (refused): a missing current, voltage,
  efficiency, thermal boundary or heat of reaction; a measured cell without an active area;
  `predictive` or an adiabatic boundary. Supply the input; nothing is assumed in its place.
- `cheme.cell-operating-range`: specified, outside the declared range (warning); measured,
  outside the measurement's current density or temperature range (error, refused). Measure
  the point or move the operating point: a measured series is never extrapolated.
- `cheme.cell-measured-conflict` (warning): a value in the cell differs from the measured one
  by more than the replicates' standard deviation; remove it from the cell or check the data.
- `cheme.cell-measurement`: the measurement file is missing or has errors (run
  `cheme experiments electrochem FILE`), or lacks the product; (info) a side product forms
  no side reaction and its current is counted as heat.
- `cheme.cell-membrane`: co-ion shares not adding up to 1, an unreadable ion, a WDE outside
  [0, 1] (error); no WDE (info: no co-ion fluxes).
- `cheme.cell-electrodes`, `cheme.cell-element-balance`, `cheme.cell-charge-balance`: the
  half-reactions do not add up or do not balance.
- `cheme.cell-flowsheet-duty`, `cheme.cell-double-count`: the linked streams do not carry the
  cell's power and heat, or energy is counted twice.

## Outputs and provenance

`process/cells.yaml`, reviewed in the diff; `cheme process cell --json` records the model, the
core version, the assumptions, limitations and the sha256 of every input, the measurement file
included. A measured cell names the file, the bracketing points and the standard deviations;
for `cheme maturity` it is specified (never predictive) and sourced when the measurement has a
source.

## Required human judgment

- The reaction set and which side reactions are worth declaring.
- Whether a specified or measured value applies to the design cell (scale, electrolyte,
  temperature, current density, ageing); a lab series describes the lab cell.
- The co-ion split of a membrane, when it is not measured.
- What the heat duty and the hydroxide deficit mean for cooling and electrolyte management.

## References

- `cheme process cell`, `cheme schema process-cells`; docs/framework/electrochemical-cells.md;
  ADR 0023, ADR 0041.
- Skills `reactions`, `materials`, `experiment-reproduction`, `process-design`.
