# 0021. A furnace energy basis for high-temperature solid reactions from condensed-phase data, never a fluid flash

- **Status:** Proposed
- **Date:** 2026-10-27

## Context

Process-library candidates (silicon carbide by the Acheson process, alumina by the Bayer process
with its calciner, acetylene through calcium carbide and lime) need the energy of a furnace in
which solids react at high temperature (pre-release issue 370, under pre-release issues 81 and 137). The execution
routes cheme-as-code has are fluid-only: the thermo flash of `cheme process phase`/`props` has
no solid phase and DWSIM's translation has no solid compounds (`methods.yml`, regime
`solid_equilibrium`: unsupported). A fluid flash of a stream holding CaCO3 or CaO would return
a number with no physical meaning, and the flowsheet's energy balance of a reacting block needs
enthalpies on the elements that `props` does not give. Gas-phase reactor models (Gibbs, fixed
bed) are not furnace models either.

Options considered: (a) add solids to the flowsheet's stream and property contract, which
touches every balance, the simulation translation and the property claims; (b) a separate,
bounded furnace contract with its own element and energy balance on condensed-phase data;
(c) only a sourced specific-energy inventory, with no calculation.

## Decision

cheme-as-code computes the energy basis of a solid-reaction furnace as a separate contract,
`furnace-energy-basis/1`, from the file `process/furnaces.yaml` (schema `cheme/furnaces/v1`),
in `domains/process/furnace.py`, through `cheme process furnace [ID] [--json]`:

- One bounded reaction is qualified: limestone calcination, `calcination-caco3`. Any other
  reaction or feed component is refused with `cheme.furnace-unsupported`; a new reaction is
  added only with its own reference case.
- The furnace is a box: declared solid feed, degree of calcination (given, never predicted),
  product and off-gas temperatures, a fuel with air or electric power, and losses. The model
  reports the element balance, product and off-gas composition, reaction enthalpy and the
  furnace energy closure; with the heat input given it checks the residual, without it solves
  the heat input.
- Thermochemistry comes from an established data set through an integration, never from
  equations in a skill: the NASA Glenn polynomials of gas and condensed species that Cantera
  ships, read by `integrations/cantera.py` (extra `cantera`). Each result records species,
  phase, data note, range and the Cantera version. A temperature outside a species' data is
  refused (`cheme.furnace-data-range`), never extrapolated.
- No duty of a furnace is ever taken from a fluid flash; the furnace module imports neither
  thermo nor the phase or props modules (tested).
- `method: specific-energy` is a labelled conceptual fallback: a sourced specific heat use (or
  the lime BREF's range by kiln type) times the product flow, with an info finding saying so.
- Capability: `methods.yml` gains the regime `high_temperature_solid_reaction` (phase and
  simulation unsupported) with an optional `elsewhere` map (`furnace: limited`).
  `cheme maturity` adds the not-required `balanced.furnace-energy` when the file exists; it never
  supports `predictive`.

## Consequences

- Positive: a plant can state a lime kiln's or calciner's fuel or power, CO2 split and energy
  closure with sources and tolerances, checked against a published kiln balance, without
  pretending a fluid flash covers solids.
- Positive: the flowsheet, simulation and property contracts stay unchanged; existing
  repositories need no edit (the file is optional, and `cheme maturity` lists the requirement
  only when it exists).
- Negative: the furnace is not a flowsheet unit. Its numbers are not propagated into
  `process/flowsheet.yaml`; a block that represents it can name it (`block:`), and the user
  carries the heat input over as a sourced value.
- Negative: the energy basis needs the `cantera` extra, which has no wheels for Python 3.15 yet;
  without it the result is `cheme.furnace-extra` and only the fallback works.
- Known limitations: carbothermal reduction (SiC, CaC2), dolomite, magnesite and alumina
  calcination are not covered; conversion, temperatures and grade are inputs. The equilibrium
  check uses the NASA data's standard pressure of 1 bar (TM-4513), not the 1 atm Cantera's
  converted files declare; no independent experimental equilibrium data are checked.

## Evidence

- pre-release issue 370; `src/chemeascode/domains/process/furnace.py`, `src/chemeascode/integrations/cantera.py`,
  `cheme process furnace` in `src/chemeascode/interfaces/cli/process.py`,
  `src/chemeascode/domains/process/thermodynamics/methods.yml`,
  `src/chemeascode/project/maturity.py` (`balanced.furnace-energy`).
- `tests/test_furnace.py` with `tests/data/furnaces-lime-kiln.yaml` (kiln No. 1 of Sagastume
  Gutiérrez et al., Applied Thermal Engineering 51 (2013) 273-280); `docs/framework/furnace.md`.
