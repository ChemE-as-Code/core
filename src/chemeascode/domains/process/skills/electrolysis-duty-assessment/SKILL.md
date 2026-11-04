---
name: electrolysis-duty-assessment
description: Assess dynamic duties of an electrolysis cell and its anolyte reservoir in process/duties.yaml - current, power or on/off schedules, the reservoir volume and composition, the anolyte model, dosing on a pH trigger or continuous, bleed and make-up, a stated pH threshold and horizon - then run cheme process duty for the time to the threshold, dosing, product, energy and the time outside the measured range, compare duties at equal delivered product and draw the time plots and operating map. Use when a bipolar-membrane or other electrolyser's anolyte loses hydroxide, when a reservoir, dosing or schedule is sized, or when duties are compared.
---

# Electrolysis duty assessment

## Purpose and when to use

`process/duties.yaml` (schema `cheme/electrolysis-duties/v1`) states how a cell of
`process/cells.yaml` is operated over time against the reservoir its anolyte circulates
through; `cheme process duty` integrates each duty. Use this skill to answer: how long does the
anolyte stay above a stated pH at this schedule and reservoir, how much hydroxide must be dosed,
what a bleed does, which of two schedules or reservoirs is better for the same product, and
where a schedule leaves the conditions the cell was measured at. It follows the skill
`electrochemical-cell-modelling` (the cell, its measured performance and membrane block).

## Required inputs and missing inputs

- A cell in `process/cells.yaml` with a **bipolar membrane block**: measured
  (`performance: measured`, its measurement giving voltage, FE, WDE and the carbon share of the
  co-ion current) or specified (voltage, Faradaic efficiency, `water_dissociation_efficiency`,
  `co_ion_crossover`, and an `operating_range.current_density`).
- The schedule (current, current density, power, on/off) and the horizon.
- The reservoir: volume, initial composition (hydroxide, carbonate, bicarbonate, CO2 in mol/L),
  cation, the anolyte model id (`well-mixed-carbonate`); degassing only with a sourced `k_L a`
  and the CO2 partial pressure over the reservoir.
- **The pH threshold, stated explicitly with its source**: a design criterion (for example the
  pH below which the anode material is not qualified), never a guessed corrosion onset. Ask for
  it; never pick a default.
- Dosing (solution concentration, rate, trigger and stop pH, density for its mass), bleed and
  make-up water, a minimum inventory where the plant has one.

Do not invent a WDE, a co-ion split, a `k_L a` or a threshold: ask, or leave the input out and
expect the refusal or the info finding.

## Workflow and tools

1. Check the cell first: `cheme process cell` and, for a measured cell,
   `cheme experiments electrochem FILE`; fix their errors.
2. Write the duty (`cheme schema process-duties`; docs/framework/electrolysis-duties.md):

   ```yaml
   - id: D-150
     cell: BPM-1
     schedule: {kind: constant_current, current_density: {value: 150, unit: mA/cm2}}
     reservoir:
       volume: {value: 1, unit: L}
       composition: {hydroxide: {value: 1, unit: mol/L}}
       model: well-mixed-carbonate
     threshold: {ph: 12, source: "anode qualified above pH 12 (design basis D-007)"}
     horizon: {value: 2000, unit: h}
   ```

3. Run `cheme process duty [ID] [--json]`. Read the time to the specified pH threshold, the
   end reason, the charge, energy, product, dosing, final pH, the time outside the measured
   range and outside the model's validity, and `feasible`.
4. Size the reservoir or the dosing with `--plot DIR`: the operating map shows the time to the
   threshold over WDE and reservoir volume (set the axes in `operating_map:`), the time plots
   the transient. Add `dosing:` (on a pH trigger above the threshold) or a `bleed:` with
   `makeup_water:` and rerun.
5. **Compare duties at equal delivered product**:
   `cheme process duty --compare A,B --co KG` integrates each to the same product (within the
   tolerance, default 1e-3 of the target). Never compare duties over equal time or equal
   charge when they make different amounts: a duty that makes less always looks better.

Keep measured observations and simulated transients apart: in the operating map the measured
WDE points are markers labelled "measured", the cells and lines are simulated. A simulated time
to threshold is not a measurement of one.

## Validation and failure handling

- `cheme.duty-out-of-range` (warning): the schedule leaves the measured current density or
  temperature range; the transient stops at the first exit and the time outside is reported.
  Never quote a duty with time outside the measured range as feasible; keep the schedule
  inside, or have the missing point measured. The same rule reports time with the anolyte
  outside the model's validity (pH, ionic strength, temperature).
- `cheme.duty-cell-missing`, `cheme.duty-model-unknown`, `cheme.duty-model-species`
  (refused): the cell lacks an input, the model id is unknown (there is no default), or the
  membrane's co-ions are not the model's. Supply the input; do not switch models silently.
- `cheme.duty-threshold-reached` (info) gives the time; `cheme.duty-horizon-reached` (info)
  says the threshold is not reached: extend the horizon to find the time.
- `cheme.duty-dosing-saturated`, `cheme.duty-inventory-low` (warnings): the dosing cannot keep
  up, the bleed empties the reservoir, or more cation left than the reservoir held.
- `cheme.duty-dosing-chatter` (warning): the dosing band is too narrow for its rate; widen
  `stop_ph - trigger_ph` (a tolerance change does not help).
- `cheme.duty-not-converged` (error): loosen `tolerance`, shorten the horizon or check inputs.
- `cheme.duty-target-not-reached` (warning, compare): the duty ended before the target.
- For a result that matters, rerun with `tolerance` halved: the time to the threshold should
  not move beyond the precision you quote.

## Outputs and provenance

`process/duties.yaml`, reviewed in the diff; `cheme process duty --json` records the duty
model and the anolyte model (ids, versions, assumptions, limitations), the measured range
(`measured_range`: current density, temperature, power, measured WDE), the events, the time series and the sha256 of every input, the measurement file included. Plots
are written only where asked and are not plant files. Quote a time to threshold as "time to
the specified pH threshold X (the criterion's source)", with the model's limitations
(concentration-basis pH of an ideal solution).

## Required human judgment

- The threshold and its basis, the horizon and the minimum inventory.
- Whether the measured series applies to the plant cell (scale, electrolyte, ageing) and
  whether the reservoir is well mixed.
- Whether the concentration-basis pH of an ideal solution is close enough to the measured pH at
  the anolyte's ionic strength for the decision at hand.
- The dosing strategy, the dosing solution and the bleed's disposal.

## References

- `cheme process duty`, `cheme schema process-duties`; docs/framework/electrolysis-duties.md;
  ADR 0041, ADR 0043.
- Skills `electrochemical-cell-modelling`, `experiment-reproduction`.
- Prats Vergel et al., Nat. Chem. Eng. 2025 (the anolyte balance); process-library#329 (its
  reproduction and validation).
