# PC-SAFT parameters for feos (shipped)

The records the property package `water-methanol-pcsaft-liquid` uses
(`domains/process/property_packages.py`, ADR 0064), copied unchanged from the feos repository at
tag `v0.10.5` (commit `14d295637ebedf4b35d204f1b44d329b1897d14f`,
https://github.com/feos-org/feos):

- `pcsaft-esper2023.json`: the records of water (7732-18-5) and methanol (67-56-1) from
  `parameters/pcsaft/esper2023.json` (sha256 of the whole upstream file
  `87fdcd8733245d90cd6ad9e9d7d0583bd3f7ffb3c4d67a25197190f289e2a679`, 1842 records).
  T. Esper, G. Bauer, P. Rehner, J. Gross, PCP-SAFT parameters of pure substances using large
  experimental databases, Ind. Eng. Chem. Res. 62 (2023) 15300-15310,
  doi:10.1021/acs.iecr.3c02255.
- `pcsaft-rehner2023-binary.json`: the methanol-water record (`k_ij` = -0.0159473671673194) from
  `parameters/pcsaft/rehner2023_binary.json` (sha256 of the whole upstream file
  `8b7d008b2bdf7ec49542eb443e36078fbe46e2737775126589c1718dfa13c335`, 7848 records).
  P. Rehner, A. Bardow, J. Gross, Modeling mixtures with PCP-SAFT: insights from large-scale
  parametrization and group-contribution method for binary interaction parameters, Int. J.
  Thermophys. 44(12) (2023), doi:10.1007/s10765-023-03290-3.

The JSON is in the layout feos 0.9 and later reads (`Parameters.from_json`); feos 0.8 and
earlier used another (the upstream `parameters_old/`).

## Licence

The feos repository is licensed MIT OR Apache-2.0 (`license-mit`, `license-apache` here, copied
from the repository root at the same tag; `Cargo.toml`: `license = "MIT OR Apache-2.0"`). The
`parameters/` directory carries no licence or terms of its own, so the repository licence is
taken to cover it; the parameter publications are by the feos maintainers. Both licences allow
redistribution with the notice, which is why these records are shipped, unlike the ChemSep data
(ADR 0015). If the maintainers state other terms for the parameter files, follow those.

## Note on molar masses

The records' `molarweight` (water 18.011, methanol 32.026 g/mol) are the monoisotopic masses.
feos uses them only for mass-based properties, which cheme-as-code does not read: the package
converts molar densities with its own molar masses (`property_packages.WATER_METHANOL`).
