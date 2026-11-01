# 0023. Electrochemical cells as a versioned contract with specified performance

- **Status:** Accepted
- **Date:** 2026-10-27

## Context

Process-library entries for hydrogen by electrolysis and for chlor-alkali (process-library#117,
#121) need a cell that links current, products, electricity and heat. The flowsheet's reactors
(`reactor: conversion | equilibrium | gibbs | pfr | cstr | batch`) and the DWSIM translation
have no current, electron count, Faradaic efficiency or voltage, and a conversion reactor can
prescribe the chemistry but not the electricity or the heat it releases. Predictive
electrochemistry (polarisation curves, electrolyte activities) needs electrolyte
thermodynamics that core does not have yet. The options were a new `reactor:` kind
inside `process/flowsheet.yaml`, which changes the generator fingerprint of every sheet and
mixes cell data into the flowsheet, or a separate file that refers to the flowsheet.

## Decision

- A new optional plant file `process/cells.yaml`, schema `cheme/electrochemical-cells/v1`
  (`kind: electrochemical_cells`), owned by `domains/process/electrochemical_cell.py` and listed
  in the schema catalogue as `process-cells`. A cell names an overall reaction of
  `process/reactions.yaml`, the electrons per extent, its anode and cathode half-reactions
  (ions as formula and charge, `e-`), the dissociation of dissolved components, the cells in
  series, the current, the Faradaic efficiency and side reactions' current fractions, the
  voltage, crossover and purge fractions, the thermal boundary, the operating range and an
  optional link to a flowsheet step and its electricity and heat streams. Values reuse the
  process `Quantity` (provenance, source); heats of reaction, formulas and molar masses come
  from the reactions and materials files.
- The performance is **specified**. The voltage and efficiencies are inputs; the model
  (`faraday-balance` v1) does exact balances only: extents by Faraday's law, charge, elements,
  `P = N U I` counted once, `U_tn = dH / (n F)` and `Q = P - sum xi dH` at an isothermal
  boundary. `performance: predictive`, an adiabatic boundary and any missing current,
  efficiency, voltage, thermal boundary or heat of reaction are refused with an error finding
  (`cheme.cell-*`); nothing is assumed in their place.
- `cheme process cell` prints the result (`--json` with model, version, core version,
  assumptions, limitations, qualified cases and input fingerprints); `cheme validate` reports
  the findings; `cheme maturity` gives a linked step the model basis `electrochemical-cell`
  (not predictive, sourced when voltage and efficiencies are given with a source).

## Consequences

- Positive: electrolysis and chlor-alkali flowsheets can state their cells with provenance and
  get charge, element and energy closure, kWh per kg and the heat duty without double counting
  electricity; the flowsheet, its generator fingerprint and the DWSIM route are unchanged.
- Positive: the separation between specified data and prediction is explicit in the file
  (`performance:`) and in the maturity report.
- Negative: a cell is not a DWSIM unit; the linked step's streams must be written from the
  cell's result (the link checks them, it does not fill them).
- Known limitations: no electrolyte properties (heats of dilution, activities), no
  adiabatic boundary or temperature rise, no polarisation model; the qualification covers
  water electrolysis at 1.6-1.9 V and a chlor-alkali membrane cell at 3.0 V and 6 kA/m2
  (docs/framework/electrochemical-cells.md).

## Evidence

- `src/chemeascode/domains/process/electrochemical_cell.py`, `tests/test_electrochemical_cell.py`,
  `tests/data/electrochemical/`, `docs/framework/electrochemical-cells.md`.
