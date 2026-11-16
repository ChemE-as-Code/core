# 0066. Wastewater results as calculated stream quantities

- **Status:** Proposed
- **Date:** 2026-11-09, revised 2026-11-16

## Decision

Core stores measured-basis outputs in each stream's `state.<case>.calculated` map. A quantity records the value, unit, calculated provenance, simulated origin, model source and input fingerprint. Volumetric liquid flow is distinct from the molecular mass-flow field. The water-quality example uses mg COD/L, mg N/L, mg P/L, mg TSS/L and m3/day.

The CLI, PFD stream inspector and native Stream table read the same state. The table can display additional columns defined by the available measurements. A missing value renders as an em dash and a calculated zero stays zero. The backend compares its declared files and flowsheet inputs to the run fingerprint. Generated output cells are excluded from the model fingerprint; editing the input or its code marks earlier results stale.

## Consequences

Given and assumed fields remain available beside the calculated fields. Existing molecular balance checks retain their mass-flow basis. Checking elemental balances for a dynamic wastewater model requires separate evidence for accumulation, solids and gaseous losses.
