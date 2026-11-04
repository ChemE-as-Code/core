# Electrolysis duties: schedules, the anolyte reservoir and dosing

`process/duties.yaml` (schema `cheme/electrolysis-duties/v1`) states how a cell of
`process/cells.yaml` is operated over time against the reservoir its anolyte circulates
through. `cheme process duty` integrates each duty and reports the pH, inventory, product,
charge, energy, dosing and bleed over time, the time to the stated pH threshold, and the time
spent outside the measured conditions. The code is
`chemeascode.domains.process.electrolysis_duty` (model `electrolysis-duty` v1) with the anolyte
models of `chemeascode.domains.chemistry.anolyte`; the decision is
[ADR 0043](../adr/0043-dynamic-electrolysis-duties-and-anolyte-models.md). It builds on the
[measured cell performance](electrochemical-measurements.md) and the
[membrane block](electrochemical-cells.md) of ADR 0041.

## The file

```yaml
schema: cheme/electrolysis-duties/v1
kind: electrolysis_duties
duties:
  - id: D-150
    title: 150 mA/cm2 on 1 L of 1 M KOH
    cell: BPM-1                      # an id of process/cells.yaml
    cells_in_series: 1               # default: the cell's
    stacks: 1                        # stacks in parallel on the one reservoir
    schedule: {kind: constant_current, current_density: {value: 150, unit: mA/cm2}}
    reservoir:
      volume: {value: 1, unit: L}
      composition: {hydroxide: {value: 1, unit: mol/L}}   # also carbonate, bicarbonate, co2
      cation: K+
      model: well-mixed-carbonate    # an anolyte model id; there is no default
      degassing:                     # optional; without it CO2 degassing is off (info)
        kla: {value: 2, unit: 1/h, source: "..."}
        co2_partial_pressure: {value: 0.0004, unit: atm, source: "air"}
    dosing:
      kind: on_threshold             # none | on_threshold | continuous
      trigger_ph: 12.5
      stop_ph: 13.0
      concentration: {value: 5, unit: mol/L}
      rate: {value: 10, unit: mL/h}
      density: {value: 1.22, unit: kg/L, source: "..."}   # optional: the solution's mass
    bleed: {rate: {value: 2, unit: mL/h}}
    makeup_water: {rate: {value: 2, unit: mL/h}}
    threshold: {ph: 12, source: "the stated design criterion"}
    horizon: {value: 2000, unit: h}
    minimum_inventory: {volume: {value: 0.5, unit: L}}   # or cation: {value, unit: mol}
    tolerance: 1.0e-8                # relative, optional
    operating_map: {wde: [0.5, 0.995], volume: [0.1, 10], volume_unit: L, resolution: [16, 10]}
```

Schedules:

| kind | gives | notes |
| --- | --- | --- |
| `constant_current` | `current` (A per cell) or `current_density` | |
| `piecewise` | `points: [[t, I], ...]` in `time_unit` and `unit` (A or A/m2, mA/cm2) | `interpolation: step` (held) or `linear`; the first point at 0, the last value holds |
| `power` | `points: [[t, P], ...]`, P of all the duty's cells (W, kW) | `P = N U(j) j A` solved for j inside the measured range; outside it there is no current |
| `on_off` | `period`, `duty_fraction`, `current` when on | `start: on` or `off` |

`N` is the cells in series times the stacks, all on the one reservoir.

## What is computed

At each instant the cell's voltage `U(j)`, the Faradaic efficiency of its product `FE(j)`, the
water dissociation efficiency `WDE(j)` and the carbon share `C_x(j)` of the co-ion current come
from `MeasuredPerformance.at(j)` for a measured cell (interpolated between the measured points,
never extrapolated) or from a specified cell's constants (`voltage`, `faradaic_efficiency`,
`membrane.water_dissociation_efficiency`, `membrane.co_ion_crossover`) within its
`operating_range`. Per cell, with the current `I`:

- OH- into the anolyte from the bipolar membrane: `WDE I / F`;
- OH- consumed at the anode (oxygen evolution): `I / F`;
- the co-ion current `(1 - WDE) I / F`: the cation leaving the anolyte (share `1 - C_x`) and
  carbon entering it as HCO3- (share `C_x`), or the ions and shares of the membrane block;
- the product formed: `FE I nu / (n F)`; the power `U I`.

These, times `N`, with the dosing (cation and OH- of the solution, its volume), the make-up
water and the bleed (at the reservoir's composition), are the fluxes the anolyte model
integrates. The cumulative hydroxide deficit is `(1 - WDE) Q / F`, the charge `Q` over all
cells.

The integration is the adaptive Dormand-Prince 5(4) method of `foundation/ode.py` with events:

- the stated pH threshold (ends the duty; reported as the **time to the specified pH
  threshold**, a design criterion, not a corrosion onset);
- the minimum inventory (volume or cation), or an empty reservoir;
- dosing on at `trigger_ph` and off at `stop_ph`;
- the product target of a comparison.

The schedule's breakpoints and the times the current density crosses the measured range split
the integration. **The transient stops at the first exit from the measured range** (current
density or temperature): the state after it is not computed. The scheduled operating time
outside the range is summed (to the horizon when the transient stopped at an exit). Time with
the anolyte outside the model's validity (pH, ionic strength, temperature) is summed too.

A duty is **feasible** when it runs to its horizon (or reaches a comparison's target) without
reaching the threshold or the minimum inventory, entirely inside the measured range and the
model's validity, and the integration converged.

## The anolyte model `well-mixed-carbonate` v1

An independent, concentration-basis implementation of the anolyte balance of Prats Vergel et
al. (Nat. Chem. Eng. 2025), on conserved quantities with instantaneous equilibrium speciation
instead of the authors' finite-rate kinetics:

- state: moles of the cation and of total inorganic carbon `C_T`, and the volume;
- `[H+]` from the charge balance `[M+] + [H+] = [OH-] + [HCO3-] + 2 [CO3-2]` with
  Kw = 1e-14, pK1 = 6.37, pK2 = 10.32 at 25 °C, solved on `log10 [H+]` (bracketed Newton);
- CO2 degassing `k_L a V ([CO2] - 0.034 p_CO2)` above saturation only, when `k_L a` is given.

Its validity: ionic strength 0-1.5 mol/L, pH 2-14.5, 293.15-303.15 K. Its limitations: an
ideal solution (concentrations, not activities: at 1 mol/L ionic strength the pH is a
concentration-basis pH, not an activity pH), constants at 25 °C, no other ions or solids,
supersaturated CO2 stays in solution without degassing.

Because the pH is on concentrations, the time to a threshold scales exactly with the reservoir
volume at fixed fluxes. The authors' published script stops on `-log10` of the H+ *amount*,
which is the pH only at 1 L (process-library#329 D1: at 10 L it stops at pH 13). Against the
#329 reproduction (200 mA/cm2, 5 cm2, 1 M KOH, C_x 0.66, WDE 0.95) this model gives 322.30 h to
pH 12 at 1 L and 3223.0 h at 10 L, as the authors' model on a concentration basis
(`tests/test_electrolysis_duty.py`). Apart from that reproduction, the validation condition of
#329 V1 (20 mL of 0.1 M KOH, 100 mA/cm2) gives 1.54 h, inside the envelope 1.31-1.87 h around
the measured 1.47 h.

The NaCl electrolyte route (`cheme process electrolyte`, `electrolytes.yml`) does not compute
KOH or carbonate solutions and refuses them; the anolyte model is the only place they are
handled.

## Comparing duties

`cheme process duty --compare A,B --co 0.5` (`compare_duties`) integrates each duty until its
cumulative product equals 0.5 kg. A duty reaches the target when it delivers it to within the
relative tolerance (`--tolerance`, default 1e-3 of the target); a duty whose horizon,
threshold, inventory or measured range ends it first is reported as not reaching it
(`cheme.duty-target-not-reached`). Per duty: the elapsed time, charge, energy, time outside
the measured range, final pH, dosing used and the cumulative hydroxide deficit. The duties
are named in `--compare`, not as positional ids (both is an error); `--plot DIR` draws the
compared transients, each up to the target.

## Plots

`--plot DIR` writes per duty:

- `duty-<id>.svg`: aligned time plots, one quantity per panel on one time axis: current,
  voltage, pH with the stated threshold, product delivered, hydroxide dosed; events dotted,
  the time after a range exit shaded "not simulated". Lines are simulated.
- `map-<id>.svg`: the operating map, time to the threshold over WDE (constant) and reservoir
  volume (log), with the duty's schedule and dosing; the measured WDE points of the
  measurement file as markers labelled "measured", the duty's own point, and the WDE outside
  the measured points shaded. Axis ranges come from `operating_map:` in the duty.

## Findings

| rule | level | when |
| --- | --- | --- |
| `cheme.duty-schema` | error | the file does not follow the schema, a unit or a value out of range, a dosing trigger not above the threshold, an on/off schedule of more than 100 000 periods over the horizon |
| `cheme.duty-cell-missing` | error | the cell is not in `process/cells.yaml` or lacks what the duty needs (voltage, FE, a bipolar membrane with WDE and co-ion split from the membrane block or the measurement's titration, area, product), its membrane block is invalid (co-ion shares not in 0..1 or not adding up to 1, WDE outside 0..1), or its measurement has errors |
| `cheme.duty-model-unknown` | error | no anolyte model of that id |
| `cheme.duty-model-species` | error | a co-ion or anode reaction the model does not carry, or a model whose state names no `cation` (mol) and `volume` (L) |
| `cheme.duty-out-of-range` | warning | operation outside the measured range, or the anolyte outside the model's validity (info: a specified cell without a current density range) |
| `cheme.duty-threshold-reached` | info | the time to the stated threshold |
| `cheme.duty-horizon-reached` | info | the threshold is not reached within the horizon |
| `cheme.duty-inventory-low` | warning | the minimum inventory is reached, the reservoir empties, or a conserved inventory (cation, carbon) is exhausted: the transient stops there |
| `cheme.duty-dosing-saturated` | warning | the threshold is reached while dosing, or dosing never reaches its stop pH |
| `cheme.duty-dosing-chatter` | warning | threshold dosing switched on and off more than 20 000 times (a band `stop_ph - trigger_ph` too narrow for the dosing rate); the transient stops there |
| `cheme.duty-not-converged` | error | the integration failed |
| `cheme.duty-degassing` | info | no CO2 degassing stated |
| `cheme.duty-compare` | error | compared duties form different products |
| `cheme.duty-target-not-reached` | warning | a compared duty ends before the target |

`cheme validate` reports the schema, cell and model findings without integrating: every error
`cheme process duty` refuses a duty on before it integrates (units, ranges, the cell and its
membrane, the anolyte model and its species). `--json` records the model ids and versions (the
duty's and the anolyte model's), their assumptions and limitations, the range each duty is
checked against (`measured_range`: current density, temperature, the power of all cells for a
power schedule, the measured WDE), and the source revision with the sha256 of every input, the
measurement file included.
