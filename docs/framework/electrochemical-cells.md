# Electrochemical cells: Faraday balance, electricity and heat

`process/cells.yaml` (schema `cheme/electrochemical-cells/v1`) describes the electrochemical
cells of a process: electrolysers for hydrogen, chlor-alkali cells and similar units at steady
state. `cheme process cell` evaluates them, `cheme validate` reports their findings and
`cheme maturity` gives a flowsheet step a cell is linked to the model basis
`electrochemical-cell`. The code is `chemeascode.domains.process.electrochemical_cell`
(model `faraday-balance` v1); the decision is [ADR 0023](../adr/0023-electrochemical-cell-contract.md).

## Specified performance, not predictive electrochemistry

The cell voltage and the Faradaic (current) efficiencies are **inputs**: measured, vendor or
literature figures with their provenance and source. What follows from them is exact
bookkeeping (Faraday's law, the charge, element and energy balances). No polarisation curve,
Nernst equation or Butler-Volmer kinetics predicts a voltage; a cell with
`performance: predictive` is refused (`cheme.cell-unsupported`). `cheme maturity` therefore
counts a cell as specified: it can support `balanced`, never `predictive`.

## Measured performance

A cell with `performance: measured` takes its voltage and Faradaic efficiencies from a
measured series ([electrochemical measurements](electrochemical-measurements.md),
[ADR 0041](../adr/0041-measured-electrochemical-performance-and-membrane-block.md)) at its
current density `I / active_area`:

```yaml
  - id: BPM-1
    performance: measured
    reaction: CO2R
    electrons: 2
    current: {value: 0.75, unit: A, provenance: given, source: "..."}
    active_area: {value: 5, unit: cm2, provenance: given, source: "..."}   # required
    side_reactions:
      - {reaction: WS, electrons: 2}       # current_fraction from the measurement
    measurements:
      file: experiments/electrochemistry/rbpm-1m-koh.yaml
      product: CO                          # the measurement's product of the overall reaction
      side_products: [H2]                  # their FE -> the side reaction their entry names
    thermal: {kind: isothermal, temperature: {value: 25, unit: °C, provenance: given}}
```

- The values are the measurement's point means, interpolated linearly in the current density;
  the result names the file, the bracketing points and the standard deviations. Outside the
  measurement's validity range of current density or temperature (within 0.5 K), or beyond its
  measured points, the cell is **refused** (`cheme.cell-operating-range`, error): a measured
  cell is never extrapolated.
- `voltage`, `faradaic_efficiency` or a side reaction's `current_fraction` may be left out. A
  value given anyway that differs from the measured one by more than the replicates' standard
  deviation is `cheme.cell-measured-conflict` (warning); the measured value is used.
- A side product whose measurement entry names a reaction of `side_reactions` gives that
  reaction its current fraction; one that names none counts as unassigned current (heat),
  with an info finding and a limitation.
- The measurement's voltage basis must be a terminal voltage: electrode potentials against a
  reference are refused; an iR-corrected voltage is used with the limitation that the power
  and heat leave out the ohmic loss.
- The measured Faradaic efficiencies are of one electrode: the product's and the side
  products'. A product the measurement forms by another reaction than the cell's (or, with no
  `reaction:` there, one that is no product of the cell's reaction), or a side product at the
  other electrode, is refused (`cheme.cell-measurement`). A side product measured at 0 (below
  detection) gives its side reaction no extent.
- Measured efficiencies that add up to more than 1 at the cell's current density passed the
  measurement's own `fe-sum-high` check (a file with errors refuses the cell), so they are
  scaled to add up to 1 (`cheme.cell-measurement`, info; a limitation and
  `measurement.normalised_from` give the sum). Side fractions stated in `cells.yaml` on top of
  them are not scaled: above 1 in all, the cell is refused (`cheme.cell-charge`).
- A missing measurement file, one with error findings, or a product it does not have is
  `cheme.cell-measurement` (error, refused). For maturity a measured cell is specified (never
  predictive) and sourced when the measurement file states its `source`.

## Membrane

An optional `membrane:` block reports the transport across the membrane apart from the
Faraday balance, which it never changes:

```yaml
    membrane:
      kind: bipolar                        # bipolar | cation_exchange | anion_exchange | diaphragm | none
      bias: reverse
      water_dissociation_efficiency: {value: 0.94, provenance: given, source: "..."}   # or from the measurement
      co_ion_crossover: {K+: 0.34, HCO3-: 0.66}   # shares of the current not carried by water dissociation
      source: "..."
```

| Quantity | Relation |
| --- | --- |
| co-ion current | `(1 - WDE) N I` |
| co-ion flux of ion `i` (charge `z_i`) | `f_i (1 - WDE) N I / (abs(z_i) F)`, mol/s and kmol/h |
| anolyte hydroxide deficit | `(1 - WDE) N I / F`, mol/s and kmol/h |

A measured cell takes the water dissociation efficiency from its measurement (with its sd and
the measured carbon share of the co-ion current); a stated one that disagrees is
`cheme.cell-measured-conflict`. Shares that do not add up to 1, an unreadable ion or an
efficiency outside [0, 1] are `cheme.cell-membrane` errors; no efficiency at all is an info.
The water dissociation efficiency is not a Faradaic efficiency: it does not change the
extents, the products or the heat.

## The contract

```yaml
schema: cheme/electrochemical-cells/v1
kind: electrochemical_cells
cells:
  - id: MEM-1
    reaction: CA                       # overall reaction of process/reactions.yaml
    electrons: 2                       # per extent of it
    electrodes:
      anode: {species: {Cl-: -2, Cl2: 1, e-: 2}}
      cathode: {species: {H2O: -2, e-: -2, H2: 1, OH-: 2}}
    dissociation:                      # dissolved components as ions
      NaCl: {Na+: 1, Cl-: 1}
      NaOH: {Na+: 1, OH-: 1}
    cells: 1                           # in series, each carrying the current
    current: {value: 6, unit: kA, provenance: given, source: "..."}
    active_area: {value: 1, unit: m2, provenance: given, source: "..."}
    faradaic_efficiency: {value: 0.95, provenance: given, source: "..."}
    voltage: {value: 3.0, unit: V, provenance: given, source: "..."}
    side_reactions:                    # optional: Faradaic losses that form something
      - {reaction: OER, electrons: 4, current_fraction: {value: 2, unit: "%", provenance: given, source: "..."}}
    crossover: {H2: 0.01}              # fraction of a formed product leaving at the other electrode
    purge: {H2: 0.005}                 # fraction of a formed product purged
    thermal:
      kind: isothermal                 # adiabatic: not supported in v1
      temperature: {value: 90, unit: °C, provenance: given, source: "..."}
    operating_range: {temperature: [353.15, 363.15], current_density: [1400, 6500], source: "..."}
    flowsheet: {step: ELY, case: design, electricity: E1, heat: Q1}   # optional
```

Values are the process `Quantity` (value, unit, provenance, source, uncertainty, origin); the
reaction, its stoichiometry and `heat_of_reaction` are those of `process/reactions.yaml`, the
formulas and molar masses those of `process/materials.yaml`. Units: current A, kA, MA;
voltage V, mV; area m2, cm2; efficiencies as a fraction (no unit, `-`, `1`) or `%`;
temperature K or °C.

## What is calculated

For `N` cells in series carrying the current `I` at the voltage `U`:

| Quantity | Relation |
| --- | --- |
| extent of the overall reaction | `xi = FE N I / (n F)`, F = 96485.33212 C/mol (CODATA 2018) |
| extent of a side reaction | `xi_k = f_k N I / (n_k F)` |
| unassigned current | `1 - FE - sum f_k`: no net chemical change (recombination, shunt currents), becomes heat |
| electric power (DC, at the terminals) | `P = N U I`, counted once |
| thermoneutral voltage | `U_tn = dH / (n F)` |
| heat to remove at the isothermal boundary | `Q = P - sum xi dH` (negative: heat to supply) |
| electricity per kg of a product | `P / m_formed` and `P / m_delivered` |

`Q` is never added to the electricity: the energy balance is "electricity in = reaction
enthalpy + heat out", and the report shows its residual (zero). The electricity per kg is the
whole cell's electricity per kg of each product: for co-products (chlorine, caustic soda,
hydrogen) it is **not allocated**; allocation is the LCA's decision.

## Checks and refusals

Every finding names `process/cells.yaml`, the line, a rule id and a hint.

- **Refused** (error, no numbers): no current, no Faradaic efficiency, no voltage, no thermal
  boundary, a reaction without `heat_of_reaction` or a molar mass (`cheme.cell-input-missing`);
  `performance: predictive` or an adiabatic boundary (`cheme.cell-unsupported`); current
  fractions above 1 (`cheme.cell-charge`); an unknown or unbalanced reaction. Nothing is
  assumed in place of a missing input.
- **Electrodes**: each half-reaction balances its atoms and its charge (ions written as
  formula and charge, `OH-`, `Na+`, `SO4-2`; electrons `e-`); the anode releases electrons, the
  cathode takes them; scaled to `electrons`, the two add up to the overall reaction once the
  dissolved components are written as their ions (`cheme.cell-electrodes`). The home electrode
  of each product (where it, or one of its ions, is formed) decides where crossover sends it.
- **Operating range** (warning): the temperature or current density outside the declared
  range; (info) no range declared. The data are never extrapolated.
- **Temperature** (info): a heat of reaction taken at another temperature than the cell's; the
  sensible heat and the temperature dependence of dH are then left out and listed as a
  limitation.
- **Measured cells and membranes**: see the two sections above (`cheme.cell-measurement`,
  `cheme.cell-measured-conflict`, `cheme.cell-operating-range`, `cheme.cell-membrane`).
- **Flowsheet link**: the step exists; the electricity stream flows into it and carries `P`;
  the heat stream carries `Q` (out of the step when positive); one stream named for both is an
  error and any other energy stream at the step a warning (`cheme.cell-double-count`).

## Limitations

- Electrolyte properties (activities, heats of dilution, conductivity) are not modelled. The
  heats of reaction are those of `process/reactions.yaml` on their standard states; for brine
  and caustic at process concentrations they differ by the heats of dilution. Electrolyte
  thermodynamics is a linked dependency.
- No adiabatic boundary, temperature rise or stream enthalpies (v1).
- One current efficiency for the overall reaction: below 1 it reduces every product alike, and
  the current lost becomes heat, not chemistry. In a chlor-alkali cell the cathode forms H2 at
  about 100 %, while hydroxide back-migration forms hypochlorite, chlorate and O2 in the
  anolyte (the BREF, 1.4.2, gives 1.070–1.128 t NaOH/t Cl2 for this reason). The H2 and NaOH
  flows at a current efficiency below 1 are therefore approximate. The electricity per t Cl2
  is not affected. To include those reactions, declare them as side reactions with their
  current fractions.
- Several cells linked to one step: the step counts as sourced only when every one of them is
  (`cheme.cell-flowsheet` warns).
- Not a unit of the DWSIM simulation: a linked step is balanced with the cell's specified values.
- Rectifier, transformer and busbar losses are outside the cell (the power is DC at the
  terminals).

## Qualification

`tests/test_electrochemical_cell.py` checks the model against data that do not come from the code:

| Case | Reference | Result | Tolerance |
| --- | --- | --- | --- |
| water electrolysis: `U_tn` | dfH(H2O, l) = -285.830 kJ/mol, CODATA Key Values (Cox, Wagman, Medvedev 1989); ATcT through `chemicals` | 1.4812 V (tabulated 1.481 V) | 0.0005 V (the data's +-0.04 kJ/mol is 0.0002 V) |
| PEM cell, 1.9 / 1.8 / 1.6 V, FE 1 (assumed) | US DOE, *Technical Targets for PEM Electrolysis* (stack): 51 / 48 / 43 kWh/kg H2 | 50.52 / 47.86 / 42.54 kWh/kg | the published integer, by rounding (see below) |
| at `U = U_tn` | HHV of H2 141.88 MJ/kg (DOE Hydrogen Analysis Resource Center) | `Q = 0`, 141.78 MJ/kg | 0.2 % (molar mass and data source) |
| FE 0.975 with crossover and purge | the DOE footnote's 2.5 % crossover loss | extents x 0.975, `Q = N I (U - FE U_tn)` | 1e-12 relative |
| chlor-alkali: `U_tn` | dfH(Cl-, aq) -167.080, dfH(OH-, aq) -230.015, dfH(H2O, l) -285.830 kJ/mol (CODATA), infinite dilution | 2.3101 V | 0.0005 V |
| products per t Cl2 | EU BREF chlor-alkali (Brinkmann et al. 2014, EUR 26844 EN, doi:10.2791/13138), section 2.1: 1.128 t NaOH, about 28 kg H2 | 1.1283 t NaOH, 28.4 kg H2 | 0.0005 t; rounding to 1 kg |
| membrane cell at 3.0 V, 6 kA/m2, CE 0.95 (BREF 4.3.2.3.2) | BREF Table 3.10, bipolar membrane cells 2 279-2 865 AC kWh/t Cl2; rectifiers 94-98 % (3.3.4.3.1) | 2 387 DC kWh/t Cl2, 2 436-2 540 as AC | inside the range |

The DOE does not state a current efficiency, so the reference cell assumes 1 (`provenance:
assumed`). Its published kWh/kg are `U 2F / M(H2)` at that efficiency. Footnote e of the same
table says they include a 2.5 % H2 crossover loss, but with it they would round to
52 / 49 / 44 kWh/kg. The comparison therefore checks the electricity per kg against the DOE's
own arithmetic. It is not evidence for the efficiency.

Charge (residual current), elements (residual per element) and energy (`P - sum xi dH - Q`)
close to round-off in every case. The qualified range is what the table says: 1.6-1.9 V per
cell for water electrolysis, 3.0 V at 6 kA/m2 for a chlor-alkali membrane cell, heats of
reaction at 298.15 K. The chlor-alkali enthalpy is on the infinite-dilution standard state;
a cell at 90 °C with 32 wt-% caustic is reported with the `cheme.cell-temperature` limitation.

`cheme process cell --json` records the model id and version, the core version, the
assumptions, limitations, the qualified cases and the sha256 of every input file.
