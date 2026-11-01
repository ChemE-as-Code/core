# 0027. Qualified electrolyte systems through Pitzer's equations in Cantera

- **Status:** Accepted
- **Date:** 2026-10-27

## Context

The thermodynamic model selection recommends Electrolyte NRTL or Pitzer for a polar
electrolyte, but neither execution route ran either (`methods.yml`, regime `electrolytes`):
the phase route (thermo) refused charged species, and the DWSIM route has no electrolyte
package. A salt given as an apparent component (sodium chloride in water) was not refused at all:
thermo and DWSIM would have computed it as a neutral molecule. Process-library entries with
brines, acids and bases (chlor-alkali, soda ash, sulfuric acid) need at least one
qualified electrolyte capability, and a loud refusal everywhere else.

Options considered: writing Pitzer's or eNRTL equations into a domain module; a new dependency
(pyEQL, PHREEQC, Reaktoro); DWSIM's electrolyte packages (not exposed by the worker, not
benchmarked); Cantera's `HMW-electrolyte` phase, an established implementation of Pitzer's
equations (Harvie-Moller-Weare formulation) in a library already behind the optional extra
`cantera`.

## Decision

- cheme-as-code runs electrolytes only for **qualified systems** listed in a versioned contract,
  `domains/process/thermodynamics/electrolytes.yml` (`meta.version`). Each system states its
  apparent components and species with charges and elements, the speciation, the composition
  and activity basis, the model with its parameters and their source, the application range
  (temperature, pressure, molality, and a separate range for the enthalpy), the claimed
  properties with tolerances and their basis, the benchmark test and references, and what is not
  claimed. The first system is NaCl-H2O: Silvester and Pitzer (1977) parameters, 273.15-373.15 K,
  up to 1000 kPa(a) and 6 mol/kg, relative enthalpy from 313.15 K, checked by
  `tests/test_electrolytes.py` against Hamer and Wu (1972) and Pitzer, Peiper and Busey (1984).
- The solver is Cantera's `HMW-electrolyte` phase, called through
  `integrations/cantera.py` (`hmw_state`); cheme-as-code writes no activity-coefficient
  equations. The water vapour pressure uses the IAPWS-95 saturation pressure from `chemicals`.
  The route needs the extras `cantera` and `props`.
- Only excess and relative properties are reported (mean ionic activity coefficient, osmotic
  coefficient, water activity and vapour pressure, relative apparent molar enthalpy); the
  species' standard states are set to zero in the solver input and do not enter them.
- `electrolytes.electrolyte_state` and `cheme process electrolyte` refuse every request outside
  the contract with an `ElectrolyteError` (rule `cheme.process-electrolyte-*`, a hint; exit code
  3): an unknown system or species, a charge imbalance, a state outside the range, a solution
  that boils at the given pressure. Each result carries the species, element and charge
  closure and its provenance.
- The phase route and the DWSIM translation refuse, together with water, the apparent
  electrolytes the contract lists and, by formula, any compound of an alkali or alkaline-earth
  metal (`ionic_elements`) (`cheme.process-sim-electrolyte`, error), instead of computing
  them as neutral molecules. A mass balance with specified splits needs no property model and
  stays possible.
- `methods.yml` records the electrolyte route as a method's `electrolyte` entry (Pitzer: NaCl-H2O)
  and the regime decision `electrolytes.elsewhere.electrolyte: limited` (the `elsewhere` map
  of ADR 0021); `phase` and `simulation` stay unsupported. The route is not one of `methods.ROUTES`.

## Consequences

- Positive: one bounded, benchmarked electrolyte capability, reported by `cheme process methods`
  and the model selection; salts in water no longer pass silently through neutral-fluid models.
- Positive: a new system is a contract entry with its parameters, sources, range and a benchmark
  test; no code change is needed for another binary Pitzer salt.
- Negative: the route is a point calculation of one liquid phase, not a flash, and does not
  enter `cheme process simulate`, the stream properties or the maturity requirements
  `predictive.*`; a simulated flowsheet with brine is still refused.
- Negative: the electrolyte route needs two extras; Cantera has no wheels for Python 3.15 yet.
- Known limitations: no solids (halite, ice), no weak electrolytes or speciation equilibria
  (acids such as H2SO4), no mixed electrolytes, no eNRTL. The 1977 parameters' relative enthalpy
  is not claimed below 313.15 K. The refusal by the phase and simulation routes is a list
  (`apparent_electrolytes`) plus a formula rule (`ionic_elements`: any compound of an alkali or
  alkaline-earth metal); an acid, ammonium salt or other electrolyte without such a metal that
  the list does not name, or a component without a known formula, is not refused.

## Evidence

- `src/chemeascode/domains/process/thermodynamics/electrolytes.yml`, `electrolytes.py`,
  `src/chemeascode/integrations/cantera.py`, `coverage.py` (phase-route refusal),
  `simulation/translate.py` (`cheme.process-sim-electrolyte`), `methods.yml`.
- `tests/test_electrolytes.py`, `tests/data/electrolytes/nacl-h2o-reference.yaml`.
