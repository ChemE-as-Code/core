# Electrochemical measurements: Faradaic efficiency, water dissociation and measured performance

`experiments/electrochemistry/<id>.yaml` (schema `cheme/electrochemical-measurements/v1`)
holds a measured series of one electrochemical cell: a bench cell run at several current
densities, each with replicates. `cheme experiments electrochem FILE` processes it, `cheme
validate` reports its findings, and a cell of `process/cells.yaml` with
`performance: measured` takes its voltage and efficiencies from it
([electrochemical cells](electrochemical-cells.md)). The code is
`chemeascode.domains.experiments.electrochemistry` (model `electrochemical-measurements` v1);
the decision is [ADR 0041](../adr/0041-measured-electrochemical-performance-and-membrane-block.md),
and [ADR 0042](../adr/0042-watertap-and-idaes-not-reused-for-electrochemical-cells.md) records
why no WaterTAP or IDAES model is used.

The module is generic: any electrolyser whose products are measured in the gas (or given as
Faradaic efficiencies) and, for a membrane cell, whose anolyte is titrated.

## The file

```yaml
schema: cheme/electrochemical-measurements/v1
kind: electrochemical_measurements
id: rbpm-1m-koh
title: Reverse-bias BPM cell, 1 M KOH
provenance: given                       # the data set as a whole
origin: measured
source: "citation and DOI of the data"
licence: "CC BY 4.0"
cell:
  active_area: {value: 5, unit: cm2}
  temperature: {value: 25, unit: °C}
  electrolyte: {name: 1 M KOH, concentration: {value: 1, unit: mol/L}}
  membrane: {kind: bipolar, bias: reverse, name: "..."}
voltage_basis: cell                     # cell | cell_ir_corrected | electrode_vs_reference
products:
  - {id: CO, electrons: 2, electrode: cathode, reaction: CO2R, thermoneutral_voltage: {value: 1.4664, unit: V}}
  - {id: H2, electrons: 2, electrode: cathode, reaction: WS, thermoneutral_voltage: {value: 1.4812, unit: V}}
gas:
  flow_unit: sccm                       # sccm | slpm | mol/s
  standard_conditions:                  # required for sccm and slpm; never assumed
    temperature: {value: 273.15, unit: K}
    pressure: {value: 101.325, unit: kPa}
  flow_position: outlet                 # outlet | inlet
  flow_correction: {factor: 1.0, source: "..."}
  inlet: {component: CO2, flow: 20}     # for the carbon balance
titration:
  method: warder-double-endpoint
  titrant_concentration: {value: 0.1, unit: mol/L}
  anolyte_volume: {value: 90, unit: mL}
  aliquot_volume: {value: 1, unit: mL}
points:
  - id: P100
    current_density: {value: 100, unit: mA/cm2}   # or current: {value: 0.5, unit: A}
    duration: {value: 3600, unit: s}
    replicates:
      - id: R1
        voltage: {value: 3.30}                     # or series: [[t s, U], ...] and window: [t0, t1]
        outlet_flow: 20.45                         # in gas.flow_unit
        fractions: {CO: {value: 12.78, unit: mol%}, H2: {value: 3.407, unit: mol%}, CO2: {value: 83.82, unit: mol%}}
        titration: {V0: 10.000, V1: 9.855, V2: 9.928}   # mL
        source: "file name in the data set"
validity:                               # optional; what is left out is derived from the points
  current_density: [500, 2000]          # A/m2
  temperature: [293.15, 303.15]         # K
  electrolyte: 1 M KOH
  duration: 3600                        # s, the longest run
  source: "..."
```

A replicate gives each product either as gas data (`fractions` with the `outlet_flow`) or as a
`faradaic_efficiency` directly, and the membrane either as a `titration` or as a
`water_dissociation_efficiency` directly. Units: current A, mA, kA; current density A/m2,
kA/m2, mA/cm2, A/cm2; area cm2, m2; duration s, min, h; voltage V, mV; fractions ppm, mol%,
%, a plain fraction; concentrations mol/L (M), mmol/L, mol/m3; volumes mL, L; pressure Pa,
kPa, bar, atm (absolute); temperature K, °C.

## What is calculated

Per replicate, with the current `I`, the current density `j` and the point's duration `t`:

| Quantity | Relation |
| --- | --- |
| molar outlet flow | `Ndot = c_corr V p_std / (R T_std)` (sccm, slpm; R = 8.314462618 J/(mol K)); mol/s as given |
| product flow | `Ndot_i = x_i Ndot` |
| Faradaic efficiency | `FE_i = n_i F Ndot_i / I`, F = 96485.33212 C/mol |
| partial current density | `j_i = FE_i j` |
| charge balance | `sum FE_i + unassigned = 1` |
| co-ions from the titration | `n_K = (V0 - V2) c V_anolyte / V_aliquot`, `n_C = (V2 - V1) c V_anolyte / V_aliquot` |
| water dissociation efficiency | `WDE = 1 - F (n_K + n_C) / (I t)`; carbon share of the co-ion current `n_C / (n_K + n_C)` |
| power | `P = U I` (terminal voltage only) |
| heat at an isothermal boundary | `Q = I (U - sum_i FE_i U_tn,i)`, when every product with an FE gives `U_tn` |
| carbon balance (with `gas.inlet`) | carbon fed = in products + unreacted (when its outlet fraction is measured) + into the anolyte (`n_C / t`) |

`V0` is the titrant to the second end point of the fresh anolyte, `V1` and `V2` to the first
and second end point after the run (Warder double end point; the equations are those of the
source paper's Methods, and count one charge per crossing ion, carbon as HCO3-). Per point,
every quantity has its mean, sample standard deviation and count; a point with one replicate
has no standard deviation.

**The Faradaic efficiency and the water dissociation efficiency are different quantities.**
The first is the share of the current that forms each product at the electrodes; the second
is the share of the current the bipolar membrane carries by dissociating water instead of by
co-ions. Neither corrects the other, and they are never combined.

## Measured performance: interpolated, never extrapolated

`MeasuredPerformance(report).at(j)` returns a `PerformancePoint`: the voltage, the Faradaic
efficiency per product, the water dissociation efficiency and the carbon share, each with its
standard deviation, interpolated linearly in the current density between the two bracketing
point means (`bracket`), with `in_range` and `extrapolated`. Outside the validity range, or
beyond the measured points when a declared range is wider, it returns no value, the bounds
and the reason. This is the interface the cell model (`performance: measured`) uses, and the
one dynamic duties and stack sizing will call.

## Checks

Every finding names the file, the line, a rule id `cheme.electrochem-*` and a hint.

| Rule | Level | When |
| --- | --- | --- |
| `schema` | error | the file does not follow the schema; a duplicate id; a product not declared; two points at one current density |
| `unit` | error | a unit the quantity does not take |
| `input-missing` | error | a standard flow without standard conditions; fractions without the outlet flow; a titration without the method block or the duration; a voltage series with no sample in its window |
| `fe-sum-high` | error | the Faradaic efficiencies of a point add up to more than `1 + 3 sd` (one replicate: more than 1.05) |
| `fe-sum-low` | warning | they add up to less than 0.9: an unmeasured product (liquids) or a flow error |
| `single-replicate` | info | a point with one replicate |
| `crossover-assumed` | warning | a membrane cell without a measured water dissociation efficiency |
| `voltage-basis` | info | electrode potentials against a reference: no polarisation curve, power or heat, and no cell voltage |
| `titration` | warning | volumes not in the order `V1 <= V2 <= V0` |
| `carbon-balance` | warning | carbon in and out differ by more than 5 % of the carbon fed |
| `flow-correction` | info | no meter correction stated: factor 1 |
| `flow-position` | warning | the flow was measured at the inlet and is taken as the outlet flow |
| `heat` | info | a product without a thermoneutral voltage: no heat |
| `validity` | info / warning | the range is derived from the points / a declared range extends beyond them |

## The command

`cheme experiments electrochem FILE [--json] [--plot DIR]` prints each point (voltage, FE per
product with the partial current density, the FE sum, the water dissociation efficiency, power
and heat, each as mean +- sd (n)), the limitations and the findings. It reads the file only;
inside a plant repository the paths are from its root, elsewhere from the file's folder.
`--json` records the model id and version, the core version, the assumptions and limitations,
the per-point and per-replicate results, the findings and the sha256 of the file. `--plot`
writes SVG figures (light and dark) for the inputs that support them: `polarisation.svg` (a
terminal voltage; `electrode-potential.svg`, labelled so, for `electrode_vs_reference`),
`faradaic-efficiency.svg` (per product and the sum), `partial-current-density.svg` and
`water-dissociation-efficiency.svg`, each with +- 1 sd bars. Exit 1 on an error finding, 2 when
the file does not exist.

## Limitations

- No polarisation model: between points the means and standard deviations are interpolated
  linearly; nothing outside the measured range is computed.
- The standard deviation is over the replicates; the uncertainty of the instruments (flow
  meter, gas chromatograph, titration) is not propagated.
- The heat counts only the products' reaction enthalpies. pH gradients, the neutralisation of
  crossed-over ions and heats of dilution are not included.
- One temperature and one electrolyte per file: the lookup has no temperature or concentration
  dimension.
