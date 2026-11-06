# 0046. feos (PC-SAFT) as an optional property backend, first for liquid water-methanol density

- **Status:** Proposed
- **Date:** 2026-11-06

## Context

The property packages of `cheme process props` (`domains/process/property_packages.py`) all run
on thermo's Peng-Robinson. No package covers water or methanol, and Peng-Robinson with COSTALD is
weak for associating liquids: COSTALD puts liquid methanol 4-8 % and water at 330-450 K 2-6 % off its
reference equation of state. feos (https://github.com/feos-org/feos, MIT OR Apache-2.0, abi3
wheels for Python 3.10 and later) implements PC-SAFT with association, published parameters for
1842 substances (Esper et al. 2023) and fitted binary interaction parameters (Rehner et al. 2023).

Before adopting it, cheme-as-code benchmarked feos 0.10.5 with those parameters against
measured data (the NIST ThermoML files cited in `tests/data/water_methanol_references.yaml`):

- **Liquid density** of water and methanol, pure and mixed: within 1 % of the reference
  equations and the measured mixture densities, except cold water-rich liquid (pure water +3 % at
  300 K) and mixtures above about 420 K.
- **Methanol-water VLE**: bubble pressures off by up to 19 % (dilute methanol at 315 K) and 8 %
  at 353-397 K, where Peng-Robinson with the ChemSep kij gives -3 to +2 %. Not better.
- **Excess enthalpy** of methanol-water (Dettmann et al. 2006): the wrong sign at every point at
  or below 370 K, off by up to 1.6 kJ/mol.
- **Aqueous LLE, predicted** (water + n-butyl acetate, water + 1-butanol, and the bundled
  extraction system water + 1-propanol + n-butyl acetate): far off, e.g. 80 times too much ester
  in water; the water + 1-butanol split closes between 298 and 313 K instead of at 398 K. The
  LLE-fitted set of
  Veith et al. (ACS Omega 2 (2017) 8982, Table 2) comes closest: 13-38 % too little butanol in
  water at 288-318 K, close at 366 K, and no upper critical solution temperature.

The results were posted to feos for information (feos-org/feos#406, #407).

## Decision

- feos is an optional backend: the extra `saft` (`feos==0.10.5`, pinned exactly, since its 0.x
  API and parameter format change between minor versions). It is imported only in
  `integrations/feos.py` and inside functions; `tests/test_boundaries.py` lists it.
- A property package names its adapter (`Package.adapter`): `thermo` (`props.Adapter`) or
  `feos` (`props_feos.FeosAdapter`); `props.adapter_for(process)` picks it, and every caller
  (`cheme process props`, the datasheet fill) goes through it. `Package.enthalpy` says whether a
  package claims enthalpy; `Result.enthalpy` is None where it does not, and nothing energy-based
  (enthalpy, exergy, exchanger duties) is calculated from such a package.
- The first feos package, `water-methanol-pcsaft-liquid`, claims **liquid density only**, in the
  boxes its benchmark holds within 1 % (`tests/test_property_packages_pcsaft.py`). Because
  PC-SAFT's bubble pressures miss by up to the benchmarked 20 % (`bubble_pressure_rel`), the
  adapter calls a state liquid only at (1 + 0.20) times PC-SAFT's bubble pressure or above;
  closer to it, a stream counts as liquid only when its phase is given or assumed, and then down
  to the bubble pressure divided by 1.20 (phase-constrained below the bubble pressure). Vapour,
  two-phase, VLE, enthalpy, entropy and viscosity are refused.
- The parameter records the package uses are shipped (`thermodynamics/data/feos/`, unchanged
  records from the feos repository at v0.10.5, with its licences and a SOURCE.md). The parameter
  directory has no licence of its own, so the repository's MIT OR Apache-2.0 is taken to cover
  it; this differs from the ChemSep data (ADR 0015), whose terms are unclear. The package converts
  molar to mass density with its own molar masses: the records' `molarweight` are monoisotopic.
- PC-SAFT is not added to the liquid-liquid extraction (ADR 0019): no available parameter set
  passes a qualification against independent tie lines, and a binary system cannot drive
  `cheme process extract`.

## Consequences

- Positive: water-methanol liquid streams (methanol synthesis crude, distillation feeds and
  bottoms, storage) get benchmarked densities, where until now they were refused; the claim says
  exactly where.
- Positive: a further PC-SAFT package is data plus a benchmark test; the adapter, the parameter
  layout and the routing exist.
- Negative: two property backends; a package that claims no enthalpy is a new case for every
  energy calculation (each refuses it explicitly).
- Negative: the shipped parameter subset must follow feos's parameter format when the pin moves.
- Known limitations: no VLE, enthalpy or LLE from PC-SAFT; water-rich liquid below 323 K is
  claimed only up to 0.64 mole fraction water, and pure water only from 360 K; a stream near its
  bubble point needs its phase given or assumed.

## Evidence

- `pyproject.toml` (extra `saft`), `src/chemeascode/integrations/feos.py`,
  `src/chemeascode/domains/process/props_feos.py`, `props.py` (`adapter_for`, `versions`,
  `method_label`), `property_packages.py` (`WATER_METHANOL`), `fill.py`,
  `domains/equipment/fill.py` (exchanger duty).
- `src/chemeascode/domains/process/thermodynamics/data/feos/SOURCE.md`.
- `tests/test_property_packages_pcsaft.py`, `tests/data/water_methanol_references.yaml`.
- feos-org/feos#406 (methanol-water VLE), feos-org/feos#407 (aqueous LLE, tp_flash).
