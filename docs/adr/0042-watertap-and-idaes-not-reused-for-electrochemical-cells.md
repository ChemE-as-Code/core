# 0042. WaterTAP and IDAES are not reused for measured electrochemical cells

- **Status:** Accepted
- **Date:** 2026-11-06 (proposed 2026-11-04)

## Context

Core#137 asks to evaluate WaterTAP and IDAES reuse before a new dependency is added for
electrochemical cells. IDAES is already an optional out-of-process simulation backend
([ADR 0039](0039-idaes-as-an-optional-second-simulation-backend.md)). WaterTAP is an open
source water-treatment modelling library on top of IDAES and Pyomo (BSD-style licence by the
Regents of the University of California and the national laboratories; its `pyproject.toml`
requires `idaes-pse>=2.13.0` and `pyomo>=6.9.5`; release 1.8.0 of 2026-09-29 at the time of
writing). Its unit model index lists six electrochemical models
(`watertap/unit_models/`): 0D and 1D electrodialysis, 1D bipolar electrodialysis,
electrocoagulation, ElectroNP (zero order) and an electrolyzer.

What core#137 needs is the processing of a measured lab series (gas chromatography, flow meter,
chronopotentiometry and titration per replicate, means and spread per point) and a lookup of
the measured voltage and efficiencies at a design current density that never extrapolates.

What the two relevant WaterTAP models do, from their documentation:

- **Electrolyzer** ("developed for the simulation of a chlor-alkali membrane electrolyzer",
  not validated for other processes): steady state, isothermal, liquid phase only, MCAS
  property package only; Faraday's law with a fixed current efficiency; the cell voltage built
  as reversible voltage plus specified anode and cathode overpotentials and an ohmic term;
  membrane transport by fixed ion transport numbers; no Nernst equation, no kinetics or mass
  transfer limits, no undesired reactions.
- **1D bipolar electrodialysis**: acid and base production from salt solutions in a
  three-channel stack, with water dissociation in the bipolar membrane from a reduced-order
  framework (Mareev et al. 2020, a second-Wien-effect rate enhancement), only above the
  limiting current; it requires Na+, Cl-, H+ and OH- in the MCAS package, and several of its
  parameters are fitted (K_A "determined by best fit").

## Decision

- No WaterTAP dependency and no new IDAES use for core#137. The measurement processing and
  the measured-performance lookup are plain Python in `domains/experiments/electrochemistry.py`
  (ADR 0041), and the cell stays the Faraday balance of ADR 0023.
- Reasons: neither WaterTAP model processes measurements; both are equation-oriented unit
  models solved in Pyomo/IPOPT that predict performance from specified parameters
  (overpotentials, resistances, transport numbers, dissociation constants), which is the
  `performance: predictive` path core refuses today. The electrolyzer's scope is liquid-phase
  chlor-alkali (no gas products such as CO and H2 from a gas-diffusion electrode); the bipolar
  electrodialysis model describes a forward stack producing acid and base from NaCl, not a
  reverse-bias bipolar membrane between a CO2 cathode and an alkaline anolyte, and it needs
  Na+/Cl- chemistry. Taking either in would add idaes-pse, Pyomo and a solver to answer a
  question they are not built for.
- What could be reused later, through the IDAES worker of ADR 0039 and only as an optional
  route: the electrolyzer's voltage decomposition (reversible voltage, overpotentials, ohmic
  term) as a structure for a predictive cell once core has validated electrolyte
  thermodynamics; the bipolar electrodialysis model's water dissociation framework as a
  reference when a forward-bias stack is modelled. Either would need its own ADR, a qualified
  case and a benchmark before any claim.

## Consequences

- Positive: the base package stays free of IDAES, Pyomo and solvers; measured series are
  processed without a simulator, quickly and reproducibly, with every number traceable to a
  replicate.
- Negative: core has no predictive electrochemistry (polarisation, mass transfer, water
  dissociation kinetics); a design point outside a measured series cannot be computed, only
  refused.
- Follow-up: revisit when a predictive cell is requested (a new ADR superseding the refusal of
  `performance: predictive` in ADR 0023).

## Evidence

- WaterTAP unit model index: <https://watertap.readthedocs.io/en/latest/technical_reference/unit_models/index.html>;
  Electrolyzer: <https://watertap.readthedocs.io/en/latest/technical_reference/unit_models/electrolyzer.html>;
  1D bipolar electrodialysis: <https://watertap.readthedocs.io/en/latest/technical_reference/unit_models/electrodialysis_bipolar_1D.html>;
  repository and licence: <https://github.com/watertap-org/watertap> (`LICENSE.md`,
  `pyproject.toml`, `watertap/unit_models/`), read 2026-11-04.
- [ADR 0039](0039-idaes-as-an-optional-second-simulation-backend.md),
  [ADR 0041](0041-measured-electrochemical-performance-and-membrane-block.md), core#137.
