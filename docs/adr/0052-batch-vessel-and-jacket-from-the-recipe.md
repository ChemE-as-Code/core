# 0052. Batch vessels and jackets are sized in the recipe, from the reactor model's content

- **Status:** Proposed
- **Date:** 2026-11-05

## Context

Core sized a vessel as a cylinder and a residence time (`domains/equipment/sizing.py`). A batch
reactor's datasheet volume and duty stayed TBD, because they depend on the batch size and the
cycle (`equipment/fill.py`). With the semi-batch model (ADR 0050) and the recipe (ADR 0051),
both are known: the model gives the content per hour of the flowsheet's flows and the peak
duty per m3, and the recipe gives the batch size. A dosed exothermic step is often limited by
its jacket, and its heat-up and cool-down times are part of the cycle (core#158 package 3).

## Decision

- A unit procedure of `process/recipe.yaml` on a batch or semi-batch step may give a
  `vessel: {fill_fraction (0.8), aspect_ratio (1.0), nominal (true), volume, jacket,
  provenance, source}`.
  - The batch content is the model's volume per hour of flows times the hours of flows one
    batch makes, which is the batch size over the flowsheet's rate of the batch-size stream.
    This is declared data, so the content does not depend on the cycle time.
  - The vessel is the largest content (charge or end) over the fill fraction, rounded up to the
    R10 preferred numbers of ISO 3 in m3, or a given `volume`. A given volume that the batch
    fills beyond the fill fraction is `cheme.recipe-vessel` (warning).
  - The jacket is `{u W/(m2 K), area, coolant_temperature, heating_temperature}`. Its area is
    given, or else the wetted shell and flat bottom of the vessel at its aspect ratio. A flat
    bottom gives a lower bound of a dished head's area.
- **Jacket check**: the model's peak duty (isothermal; a semi-batch's `peak_cooling_duty`, a
  batch's `peak_heat_rate`, times the batch's end volume) is compared with
  `U A (T - T_coolant)` at the charge, the smallest wetted area. More duty than that is
  `cheme.recipe-jacket` (warning); without a coolant temperature it is info.
- **Heat-up and cool-down**: a `heat` or `cool` operation may give `temperatures: [start, end]`
  K instead of a duration. Its time is `C / (U A) ln((T_m - T_0) / (T_m - T_1))`, with the
  medium at a constant temperature, the heat capacity and wetted area of the charge before a
  dose, else those of the end's content. A medium that cannot reach the end temperature is
  `cheme.recipe-duration`.
- `cheme datasheets fill` writes a batch or semi-batch reactor's `volume_m3` and `duty_kw`
  (the peak duty, negative) from the recipe's vessel when there is one, with the input
  `recipe:<unit procedure>` in its fingerprint, so that a changed recipe makes them stale.
  Without a vessel they stay TBD.

## Consequences

- Positive: a batch reactor gets a volume and a jacket check. Heat-up and cool-down times are
  calculated, not guessed, and enter the cycle time.
- Negative: the jacket medium is taken at a constant temperature (no outlet temperature or
  flow of the medium). The peak duty is compared with the area at the charge, which is right
  for a semi-batch whose peak is early and conservative otherwise. There is no coil or
  external loop, no agitator power, and no U from film correlations (`u` is given, with its
  source).
- Limitations: no mechanical design; the preferred sizes are the R10 series, not a vendor's
  list.

## Evidence

- core#158 package 3; this ADR's PR (stacked on ADR 0051's).
- `src/chemeascode/domains/process/recipe.py` (`Vessel`, `Jacket`, `_content`, `_vessel`,
  `_jacket_time`, `preferred`, `wetted_area`), `domains/equipment/fill.py` (`_recipe_vessel`,
  input `recipe:`).
- `tests/test_recipe.py` (vessels and jackets), `tests/test_reactor_datasheet_tanks.py`.
- ISO 3:1973, Preferred numbers: series of preferred numbers (the R10 series).
