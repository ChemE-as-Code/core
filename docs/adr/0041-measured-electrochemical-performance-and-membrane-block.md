# 0041. Measured electrochemical performance from a processed series, and a membrane block

- **Status:** Accepted
- **Date:** 2026-11-06 (proposed 2026-11-04)

## Context

[ADR 0023](0023-electrochemical-cell-contract.md) made `process/cells.yaml` a contract with
**specified** performance: the cell voltage and the Faradaic efficiencies are inputs, and the
Faraday balance does exact bookkeeping on them. The CO2 electrolysis demonstrator (core#136,
process-library#329) starts from a measured series instead: a bench cell run at several
current densities, with replicates, whose raw data are cell voltages (chronopotentiometry),
outlet gas flows (mass-flow meter, sccm), gas chromatograph mole fractions and the titration of
the anolyte. A design case then needs the cell's voltage and efficiencies at its own operating
current density, with the measured spread, and the dynamic and sizing work that follows
(core#138, #139) needs the same lookup.

Two questions were open. Where the processing lives: a script in each plant or reproduction
(what process-library#329 did first), a step of the cell model, or a domain function of its
own. And how a bipolar-membrane cell states that part of its current is carried by co-ions
rather than by water dissociation, without mixing that efficiency into the Faradaic one.

## Decision

- A new optional plant file kind `experiments/electrochemistry/<id>.yaml`, schema
  `cheme/electrochemical-measurements/v1` (`kind: electrochemical_measurements`, catalogue key
  `electrochemical-measurements`), owned by `domains/experiments/electrochemistry.py`: the
  bench cell (area, temperature, electrolyte, membrane), the `voltage_basis` (`cell`,
  `cell_ir_corrected`, `electrode_vs_reference`, required), the products (electrons, electrode,
  reaction, thermoneutral voltage), the gas measurement (flow unit, standard conditions, flow
  position and correction, inlet), the titration method, points with replicates and the
  validity range. Standard conditions of a volumetric flow are required, never assumed.
- The processing is a deterministic domain function (`evaluate`, `measurement_report`, model
  `electrochemical-measurements` v1): Faradaic efficiency per product from the flow and mole
  fraction, partial current densities, the charge balance, the water dissociation efficiency
  from the Warder double end-point titration (the paper's equations), power, the heat at an
  isothermal boundary, the carbon balance; mean, sample sd and n per point. Findings are
  `cheme.electrochem-*`; `cheme validate` reports them. `cheme experiments electrochem FILE
  [--json] [--plot DIR]` prints the result and writes hand-written SVG plots only for the
  inputs that support them.
- `MeasuredPerformance.at(j)` is the one interface to measured performance: piecewise-linear
  interpolation of the point means (and sds) in the current density; outside the validity
  range or beyond the measured points it returns no value, with the bounds and the reason.
  Nothing in core extrapolates a measured series.
- `process/cells.yaml` stays `cheme/electrochemical-cells/v1` and gains optional fields:
  `performance: measured` with `measurements: {file, product, side_products}` looks the voltage
  and efficiencies up at `I / active_area`; a measured cell outside the measurement's range is
  refused (`cheme.cell-operating-range`, error), a stated value that disagrees beyond the sd is
  `cheme.cell-measured-conflict`; for maturity it is specified and sourced (never predictive).
  An optional `membrane:` block (kind, bias, water dissociation efficiency, co-ion split)
  reports the co-ion fluxes and the anolyte hydroxide deficit `(1 - WDE) N I / F` beside the
  Faraday balance, which it never changes. This extends ADR 0023, which stays accepted.
- One existing field is loosened: `side_reactions[].current_fraction` was required and becomes
  optional in `cheme/electrochemical-cells/v1` (a tool validating `cells.yaml` against the
  published schema no longer requires it). A specified cell whose side reaction has none is no
  longer a `cheme.cell-schema` error but is refused at evaluation with
  `cheme.cell-input-missing`; a measured cell takes it from the measurement's side product
  that names the reaction. Files that give it read as before.
- The charge balance of a measured series is per electrode: each product names its
  `electrode`, the full current passes both, so the Faradaic efficiencies of the cathode's and
  of the anode's products are summed and checked (`fe-sum-high` above `max(1 + 3 sd, 1.05)`,
  `fe-sum-low` below 0.9) apart. A product's thermoneutral voltage is that of its overall
  reaction, so only one electrode's products may give one, and the heat sums over those. A
  measured cell takes its efficiencies from one electrode (the product's reaction must be the
  cell's), and scales measured efficiencies that add up to more than 1, within the
  measurement's tolerance, to add up to 1 rather than refusing them.
- The Faradaic efficiency (current to products at the electrodes) and the water dissociation
  efficiency (current the bipolar membrane carries by dissociating water) are separate
  quantities in every file, result and plot.

## Consequences

- Positive: a plant or a reproduction states its raw series once, in a file with provenance and
  a fingerprint; the design case, the reproduction and later dynamic and sizing tools read the
  same numbers through one function, with the spread and the validity range attached.
- Positive: a cell can say that it is measured and where its numbers come from, and the
  refusal outside the measured range is explicit rather than a warning.
- Negative: the measured series is interpolated linearly; there is no polarisation model, so
  a design point between widely spaced points carries the interpolation error, and the
  interpolated sd is an approximation. Instrument uncertainty is not propagated.
- Negative: the heat counts only the products' reaction enthalpies; pH gradients, the
  neutralisation of crossed-over ions and heats of dilution are left out. The titration method
  counts one charge per crossing ion, as the source paper does.
- Follow-ups: dynamic duties and reservoir dosing from the hydroxide deficit (core#138, done: ADR
  0043), stack sizing from `MeasuredPerformance` (core#139, done: ADR 0044); a temperature or
  electrolyte dimension of the lookup when a series measures more than one.

## Evidence

- core#137; tracker core#136; first user process-library#329.
- `src/chemeascode/domains/experiments/electrochemistry.py`,
  `src/chemeascode/domains/process/electrochemical_cell.py`,
  `src/chemeascode/interfaces/cli/experiments.py` (`electrochem`).
- `tests/test_electrochemical_measurements.py`, `tests/test_electrochemical_cell.py`,
  `tests/data/electrochemical/co2-bpm/`.
- `docs/framework/electrochemical-measurements.md`, `docs/framework/electrochemical-cells.md`.
