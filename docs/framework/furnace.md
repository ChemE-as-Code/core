# Furnace energy basis: high-temperature solid reactions

`cheme process furnace` computes the energy basis of a furnace in which solids react at high
temperature. It covers one bounded case: **the calcination of limestone in a lime kiln**,
`CaCO3(calcite) -> CaO(s) + CO2(g)`. The fluid-only routes of cheme-as-code (the thermo flash
of `cheme process phase`/`props`, the DWSIM simulation) have no solid phase, so they cannot
give a furnace's duty, and they never do: the furnace basis uses condensed-phase data and its
own element and energy balances (`domains/process/furnace.py`, contract
`furnace-energy-basis/1`, file schema `cheme/furnaces/v1`; see
[ADR 0021](../adr/0021-furnace-energy-basis-for-solid-reactions.md)).

## Boundary

The furnace is one box around the solids, the gas and the heat source, at steady state.

| Crosses the boundary | Declared as | Notes |
|---|---|---|
| solid feed | `feed`: mass flow, temperature, mass fractions of `CaCO3`, `MgO`, `SiO2`, `Al2O3`, `Fe2O3`, `H2O` (moisture) | inert oxides do not react; moisture evaporates into the off-gas |
| degree of calcination | `conversion` (fraction of the CaCO3 fed that decomposes) | **given, never predicted**; lime grade is not claimed |
| product solids | `product_temperature` | CaO, residual CaCO3, inerts (and fuel ash) |
| off-gas | `off_gas_temperature`, `pressure` (default 101.325 kPa(a)) | calcination CO2, combustion products, excess air, moisture |
| heat | `fuel` (gas by mole fractions, or an ultimate analysis with its LHV) with `air` (`excess` or `mass_flow`), or `electric` | a measured flow or power is checked (closure), an absent one is solved |
| losses | `losses.heat` (kW) or `losses.fraction` of the heat input | required: no closure without them |

The energy balance is on 298.15 K and the elements in their reference states:

    heat input + sensible heat of what enters
      = reaction enthalpy of calcination (298.15 K) + evaporation of the feed moisture
        + sensible heat of the product solids + sensible heat of the off-gas + losses

where the heat input is the fuel's lower heating value times its flow (the LHV is defined at
298.15 K with water as vapour) or the electric power. A fuel is burnt completely (no CO);
sulfur burns to SO2. The model also gives the element balance (every element in equals out),
the product and off-gas compositions (calcination and fuel CO2 apart, wet and dry), the
specific heat use per tonne of product and, with a `calcining_temperature`, whether
calcination can proceed there against the off-gas CO2 partial pressure.

## Thermochemical data

NASA Glenn polynomials (B. J. McBride, S. Gordon, M. A. Reno, *Coefficients for Calculating
Thermodynamic and Transport Properties of Individual Species*, NASA TM-4513, 1993) as Cantera
ships them (`nasa_gas.yaml`, `nasa_condensed.yaml`, extra `cantera`), read through
`integrations/cantera.py`. Every result records, per component, the NASA species, the phase,
the data note (source and date code) and the temperature range, plus the Cantera version.

| Component | NASA species (phase) | Range, K | Data note |
|---|---|---|---|
| CaCO3 | `CaCO3(caL)` (calcite) | 298.15-1200 | BAR 89 (Barin 1989) |
| CaO | `CaO(s)`; `CaO(L)` not modelled | 300-3200 (melting) | J 6/73 (JANAF) |
| SiO2 | `SiO2(Lqz)` alpha quartz, `SiO2(hqz)` beta quartz | 200-847, 847-1696 | J 6/67 |
| MgO, Al2O3, Fe2O3 | `MgO(s)`, `AL2O3(a)`, `Fe2O3(s)` | 300-3105, 300-2327, 300-2500 | J12/74, J12/79, J 6/65 |
| moisture | `H2O(L)` | 273.15-600 | L 8/89 |
| gases | CO2, H2O, N2, O2, Ar, SO2, CH4, C2H6, C3H8, CO, H2 | from 200 (SO2 300) | as in the file |

- **Reference state**: enthalpies include the formation enthalpy at 298.15 K; the standard
  pressure is 1 bar, as TM-4513 states (p. 2, "Standard States": ideal gas at 10^5 Pa,
  condensed species at the same pressure). Cantera's files, converted from Chemkin format,
  declare 1 atm; that declaration is not used. The standard pressure enters only the
  equilibrium check.
- **Phase changes**: a component with two phases uses the one whose range holds the
  temperature, so the alpha-beta quartz transition at 847 K is part of the sensible heat.
- **Validity**: a temperature outside every phase's range is refused (`furnace-data-range`),
  never extrapolated: calcite above 1200 K (its data end; a product leaving hotter must hold no
  residual CaCO3), lime above 3200 K (liquid lime). 298.15 K is allowed for the solids whose
  fits start at 300 K, because their formation enthalpies are defined there (2 K margin).
- **Dry air**: N2, O2, Ar and CO2 of the U.S. Standard Atmosphere 1976 (Table 3), normalised.

## Verification

`tests/test_furnace.py` (needs the extra `cantera`; the comparisons with the CRC data need
`props`):

| Check | Reference (independent of the NASA data) | Result | Tolerance and why |
|---|---|---|---|
| reaction enthalpy, 298.15 K | CRC Handbook formation enthalpies (calcite -1207.6, lime -634.9 kJ/mol) and ATcT CO2, through `chemicals` 1.5.2 | 178.3 vs 179.2 kJ/mol | 1 %: the spread between compilations of the calcite and lime formation enthalpies |
| Gibbs energy of reaction, 298.15 K | the same, with their entropies | 130.9 vs 131.5 kJ/mol | 1 % |
| heat of dissociation | lime BREF section 2.3.2.1: 3.2 GJ/t of lime | 3.18 GJ/t | 0.05 GJ/t: the BREF's two significant figures |
| methane LHV | `chemicals` combustion data on the ATcT formation enthalpy | 50.0 MJ/kg | 0.2 % |
| published kiln: elements | every element in equals out | closes to 1e-9 | implementation check |
| published kiln: product and off-gas mass | Sagastume Gutiérrez et al. 2013, Table 1: 1965 and 5249 kg/h | equal | 0.5 and 1 kg/h (rounding) |
| published kiln: off-gas CO2, H2O, SO2 | Table 4 x 230 kg/h fuel, plus 1312 kg/h calcination CO2 | within 0.7 % | 1 %: the paper's 0.693 kg H2O/kg against the 0.688 its own ultimate analysis gives |
| published kiln: reaction energy | Table 2: 1478 kW (1784 kJ/kg CaCO3) | 1476.7 kW | 1 %, as the reaction enthalpy |
| published kiln: sensible heat of lime and off-gas | Table 2 (124 and 763 kW on 273.15 K, constant heat capacities), shifted to 298.15 K with the paper's own heat capacities | +4.5 %, -7.7 % | 10 %: the paper's constant gas heat capacity (about 1.15 kJ/(kg K)) against 1.06 from the NASA data |
| published kiln: furnace energy closure | measured fuel heat 2555 kW against the outputs and the paper's wall loss 292 kW | residual +3 kW | 54 kW: the paper's own Table 2 does not close by that much (inputs 2603 kW, output rows 2657 kW) |
| published kiln: solved fuel flow | 230 kg/h measured | 229.7 kg/h | 1 % |
| published kiln: specific heat use | lime BREF Table 2.23, "other kilns" 3.5-7.0 GJ/t | 4.68 GJ/t | inside the range |

The published kiln is kiln No. 1 of A. Sagastume Gutiérrez, J. B. Cogollos Martínez,
C. Vandecasteele, *Energy and exergy assessments of a lime shaft kiln*, Applied Thermal
Engineering 51 (2013) 273-280, doi:10.1016/j.applthermaleng.2012.07.013: a fuel-oil-fired
vertical shaft kiln measured over 24 h. The input file is `tests/data/furnaces-lime-kiln.yaml`;
every number in it is the paper's or derived from it as its comments say (the degree of
calcination 0.9105 from the Table 1 mass loss; the LHV from the Table 2 fuel row). Known
weaknesses of the paper, which the tolerances above account for and nothing hides: the air of
its Table 4 is split with N2/O2 = 3.76 by mass (the molar ratio), so its stated excess air of
1.15 is 1.30 with dry air of the stated mass, and its O2 and N2 are not compared; its wall loss
is partly a balancing term; its sensible heats use constant heat capacities on a 273.15 K
reference (inferred from its limestone and air rows at 298 K, 21 and 27 kW).

The refusal and failure cases are tested too: a carbothermal or dolomite feed
(`furnace-unsupported`), calcite above 1200 K, liquid lime and a feed below 298 K
(`furnace-data-range`), missing losses, two heat sources, an ultimate analysis without LHV,
fractions not summing to 1 and an unknown unit (`furnace-input`), too little air, an air excess
below 1, an off-gas hot enough that no fuel flow closes the balance and a calcining temperature
at which calcite is stable against the off-gas CO2 (`furnace-infeasible`), a measured fuel flow
that does not close (`furnace-closure`), inputs without source (`furnace-provenance`), and the
missing extra (`furnace-extra`). A subprocess test shows that evaluating a furnace loads
neither thermo nor the phase or props modules.

## Fallback: sourced specific energy

`method: specific-energy` is a **conceptual fallback, not a calculation**. The heat input is a
specific heat use per tonne of product times the product flow: `specific_energy` (GJ/t, with
its source), or the range of the declared `kiln_type` in the lime BREF (European Commission
JRC, *Best Available Techniques Reference Document for the Production of Cement, Lime and
Magnesium Oxide*, Schorcht et al., EUR 26129 EN, 2013, doi:10.2788/12850, Table 2.23, p. 223:
long rotary 6.0-9.2, preheater rotary 5.1-7.8, parallel flow regenerative 3.2-4.2, annular
shaft 3.3-4.9, mixed feed shaft 3.4-4.7, other 3.5-7.0 GJ/t; lime and dolime). The result says
so (`basis`, an info finding), carries only the solids balance and the calcination CO2, and
claims no temperature or grade. With `method: energy-balance` and a `kiln_type`, the
calculated specific heat use is compared with that range (info inside, warning outside).

## Calculation maturity and capability

- `cheme process methods` lists the regime `high_temperature_solid_reaction`: unsupported by
  the phase and simulation routes, `furnace: limited` (this calculation, for limestone
  calcination only).
- `cheme maturity` adds the requirement `balanced.furnace-energy` (not required) when
  `process/furnaces.yaml` exists: `pass` when every furnace is calculated and closes, `fail` on
  an error or an open closure, `unsupported` for a refused furnace, `missing` for a fallback
  only. Its assumptions and what it does not claim are listed as limitations. It never counts
  toward `predictive`: the degree of calcination is an input.

## Not covered

Carbothermal reduction (silicon carbide by the Acheson process, calcium carbide), dolomite or
magnesite calcination, alumina (gibbsite) calcination, hydrated lime, CO and NOx formation,
SO2 capture by the lime, temperature profiles, kinetics, heat transfer and lime reactivity.
For those keep a sourced specific-energy inventory and say so in the plant's `DESIGN.md`.

## Example

```yaml
schema: cheme/furnaces/v1
furnaces:
  - id: K-101
    kiln_type: parallel-flow-regenerative
    reaction: calcination-caco3
    feed:
      mass_flow: {value: 25, unit: t/h, source: "design basis"}
      temperature: {value: 25, unit: °C}
      composition: {fractions: {CaCO3: 0.97, MgO: 0.01, SiO2: 0.015, H2O: 0.005}, source: "quarry analysis"}
    conversion: {value: 98, unit: "%", source: "product specification: residual CO2"}
    product_temperature: {value: 80, unit: °C, source: "vendor"}
    off_gas_temperature: {value: 120, unit: °C, source: "vendor"}
    fuel:
      gas: {fractions: {CH4: 0.95, C2H6: 0.03, N2: 0.02}, source: "gas supplier"}
    air: {excess: {value: 1.2, unit: "1", source: "vendor"}}
    losses: {fraction: {value: 5, unit: "%", source: "vendor"}}
```

`cheme process furnace` then solves the fuel flow (no `fuel.mass_flow` given) and prints the
balance; `--json` gives every term with its provenance, the data used and the findings.
