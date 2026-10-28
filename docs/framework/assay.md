# Petroleum assays and pseudocomponents

`process/assays.yaml` holds sourced assays of petroleum fractions (naphtha and heavier).
`cheme process assay` characterises each one into pseudocomponents with named correlations,
refuses an assay that is insufficient or would need extrapolation, and flashes the
pseudocomponents with Peng-Robinson through thermo inside a benchmarked claim. The code is in
`domains/process/thermodynamics/assay.py`; the decision is ADR 0026. The pure-component
routes (`cheme process phase`, `cheme process simulate`) do not take pseudocomponents.

## The file

```yaml
schema: cheme/assay/v1
kind: assays
assays:
  - id: HN-1
    title: heavy naphtha, unit 2 rundown
    source: "lab report LR-2026-114, ASTM D2892 TBP and D4052 density"
    temperature_unit: °C            # K, °C or °F, of the curve or the cuts
    distillation:
      method: TBP                   # or D86: exactly 0, 10, 30, 50, 70, 90, 100 %
      points: [[0, 70], [10, 85], [30, 100], [50, 115], [70, 130], [90, 150], [100, 175]]
    specific_gravity: 0.745         # or api_gravity, density_15C (kg/m3), or watson_k
    molar_mass: 108                 # measured, optional: a check
    pseudocomponents: 8             # cuts of equal liquid volume (default 8)
  - id: SUR-1
    source: "assay table 3 of ..."
    temperature_unit: K
    cuts:                           # instead of a curve: each cut with its own gravity
      - {name: C7 cut, liquid_volume_percent: 50, boiling_point: 371.5, specific_gravity: 0.688}
      - {name: C8 cut, liquid_volume_percent: 50, boiling_point: 398.8, specific_gravity: 0.707}
```

`cheme schema process-assays` prints the JSON schema.

## Characterisation

Every step is deterministic and named in `assay.CORRELATIONS`, and every pseudocomponent
property records which one gave it (`provenance`):

| Step | Method |
|---|---|
| D86 to TBP | API Technical Data Book procedure 3A1.1 (Daubert 1994), as in Riazi (2005) ASTM MNL50 |
| cuts | equal liquid volumes of the TBP curve, linear between the points; a cut's normal boiling point is the curve's mean over its volume |
| cut gravities | one Watson K per curve, from the fraction's specific gravity and the volume-weighted cube roots of the cut boiling points (the cut gravities reproduce the fraction's exactly), or the assay's `watson_k` |
| molar mass, Tc, Pc, C/H weight ratio | Riazi and Daubert (1987), Ind. Eng. Chem. Res. 26, 755 (Tb-SG coefficients) |
| acentric factor | Lee-Kesler (`chemicals.acentric.LK_omega`) |
| ideal-gas heat capacity | Lastovka and Shaw (2013), through thermo, from the similarity variable of the C/H composition |
| mass and mole fractions | from the cut volumes, gravities and molar masses |

The correlations were checked against published worked examples: Riazi (2005) Example 3.3 and
the API 3A1.1 example for the D86 conversion, and Ahmed's Example 2.2 for Riazi-Daubert. On the
n-alkanes C6 to C10, Riazi-Daubert gives Tc within 1 %, Pc within 4 %, molar mass within 4 % and
the C/H ratio within 2 % of the measured values (`tests/test_assay.py`).

## Refusals

| Rule | When |
|---|---|
| `cheme.assay-insufficient` | neither or both of curve and cuts; a curve not from 0 to 100 %, with fewer than 5 points (D86: not the 7 standard points), not increasing; no density (and no Watson K) or more than one; cuts that do not add up to 100 %, or with a fraction density |
| `cheme.assay-extrapolation` | a pseudocomponent with a normal boiling point outside 80-650 °F, a specific gravity outside 0.63-0.97, a molar mass outside 70-300 g/mol, or a reduced boiling point above 0.8 (`assay.RANGES`) |
| `cheme.assay-inconsistent` | warning: the pseudocomponents' molar mass misses a measured one by more than 5 %; info: a `watson_k` the density overrides |
| `cheme.assay-schema`, `cheme.assay-duplicate-id` | the file does not follow the schema; two assays with one id |

A refused assay produces no pseudocomponent. Light ends (C5 and lighter) and heavy fractions are
outside the correlations' range and therefore refused.

## Identity, fingerprint, record

A characterisation carries `METHOD_VERSION` and a 16-hex fingerprint of the method version
and the assay's inputs (not its id, title or source). The pseudocomponent identity is
`pseudo:<fingerprint>:<n>`: the same identity means the same method and the same data.
`assay.comparability(a, b)` lists what differs between two characterisations; a flash result
carries the fingerprint it was made from.

`cheme process assay --fill` writes `process/assay-characterization.json` (schema
`cheme/assay-characterization/v1`): per assay the characterisation, the correlations with their
citations, the tool version, the time and the revision of the assay file. `cheme validate`
and `cheme process assay --check` report `cheme.assay-record-stale` for an entry made from
other inputs or by another method version; `--check` also reports an assay without an entry
(`cheme.assay-record-missing`, info). `--fill --prune` removes entries of removed assays.

## Flash and its claim

`cheme process assay --pressure P` adds the bubble and dew temperatures at `P` kPa(a);
`--temperature T --pressure P` adds a flash (phase, vapour fraction, enthalpy relative to the
ideal gas at 298.15 K). The flash is Peng-Robinson with kij = 0 between pseudocomponents. It
is claimed inside `assay.FLASH_CLAIM` only:

- states at 300-550 K and 50-500 kPa(a), pseudocomponents with normal boiling points of
  340-448 K and specific gravities of 0.66-0.875;
- bubble and dew temperatures within 2.0 K; enthalpy differences of liquid, saturated and
  vapour states from the liquid at 300 K within 20 kJ/kg; mixture molar mass within 3 %;
  liquid density at 15 °C from the cut gravities within 1 %;
- benchmark: two defined naphtha surrogates (n-hexane to n-decane; n-hexane to n-nonane with
  cyclohexane and toluene), each characterised from its cuts, against CoolProp 8.0.0's
  reference multi-fluid models (GERG-2008 parameters of Kunz and Wagner for the alkane pairs,
  Bell et al. 2016 for the pairs with cyclohexane or toluene). Largest deviations: 1.8 K,
  18.2 kJ/kg, 1.5 % and 0.15 %.

Not claimed: the Peng-Robinson liquid density (about 3 % low), states inside the two-phase
region, the liquid heat capacity on its own (enthalpy differences within the liquid are up to
6 % low, inside the absolute tolerance), mixtures with water, hydrogen or light gases. Results
outside the claim are computed and listed with the reason (`outside_claim`).

## A published naphtha

The characterisation is checked against a measured assay: TotalEnergies' Oman crude assay
(assay date 10 October 2020, [OMAN.pdf](https://trading.totalenergies.com/wp-content/uploads/2025/11/OMAN.pdf)),
whose crude TBP curve gives wt % and vol % distilled and whose naphtha cuts have measured
densities. The 80-175 °C heavy naphtha, characterised from the curve and its 742 kg/m3:

- mass basis: the cumulative mass fraction of the pseudocomponents at each cut boundary
  matches the assay's own wt % within 0.015 (both columns are published to 0.1 % of the crude);
- density: its Watson K predicts the measured density of the 80-150 °C cut (734 kg/m3) within
  2 kg/m3 (0.2 kg/m3 found), and the 80-150 °C cut's K that of the 80-175 °C cut;
- boiling: at 101.325 kPa its bubble point lies between the curve's initial and 50 % points
  and its dew point between the 50 % and final points; its flash states at 300 and 500 K lie
  inside the claim.

The same assay's 375-550 °C vacuum distillate is refused (`cheme.assay-extrapolation`), and
its 100-150 °C cut, with four curve points, as insufficient.

## Gaps

- No openly accessible measured naphtha assay with molar mass or phase-behaviour data (flash,
  enthalpy) was found: the published naphtha checks mass basis, density and the ordering of
  its boiling behaviour; the flash and enthalpy tolerances come from defined surrogates, not a
  real naphtha.
- Pseudocomponents are not accepted by `simulation.yaml`: a flowsheet with a petroleum fraction
  still cannot be simulated in DWSIM.
- Light ends and heavy fractions are refused rather than characterised.
