# 0043. Dynamic electrolysis duties with an anolyte model interface, on a concentration basis

- **Status:** Accepted
- **Date:** 2026-11-06 (proposed 2026-11-04)

## Context

[ADR 0041](0041-measured-electrochemical-performance-and-membrane-block.md) gave a cell of
`process/cells.yaml` its measured voltage and efficiencies at one current density, and the
anolyte hydroxide deficit `(1 - WDE) N I / F` of a bipolar-membrane cell as a steady rate.
What a design needs next (core#138, tracker core#136) is the duty over time: a current or power
schedule, the reservoir the anolyte circulates through, its pH falling as hydroxide is lost and
carbon taken up, dosing and bleed, and how long the anolyte stays above a stated pH. Duties
should be compared fairly, and operation outside the measured conditions must be visible.

The reference model is that of Prats Vergel et al. (Nat. Chem. Eng. 2025), reproduced in
process-library#329: a finite-rate model of CO2 hydration and the carbonate equilibria with
moles in the tank as the state. The reproduction found (#329 D1) that its pH stop is taken on
the H+ *amount* (`-log10 n_H`), which is the pH only at 1 L: at 10 L it stops at pH 13, 10 %
early. The published figure is consistent with a concentration basis (10 L = 10 x 1 L).

Options considered: run the authors' script (scipy, and their volume-dependent stop); port the
finite-rate kinetics (rate constants with no stated source for this anolyte, a stiff system);
or an equilibrium speciation on conserved quantities. And for the code: one hard-wired KOH
balance in the duty, or an interface with a registry so a later model (activities, chloride,
finite-rate CO2 uptake) plugs in without changing the duty. The base dependencies have no
ODE solver; `fixed_bed._dopri_step` clamps the bed's own states.

## Decision

- A new optional plant file `process/duties.yaml`, schema `cheme/electrolysis-duties/v1`
  (`kind: electrolysis_duties`, catalogue key `process-duties`), owned by
  `domains/process/electrolysis_duty.py`: per duty the cell (an id of `process/cells.yaml`),
  optional cells in series and stacks, the schedule (`constant_current`, `piecewise`,
  `power`, `on_off`), the reservoir (volume, initial composition, cation, anolyte model id,
  optional degassing with `k_L a` and the CO2 partial pressure), dosing (`none`,
  `on_threshold`, `continuous`), bleed, make-up water, the **stated pH threshold** (a design
  criterion; reports call it "time to a specified pH threshold", never a corrosion onset), the
  horizon, the minimum inventory and an optional tolerance and operating-map axes.
- The cell's performance at each instant comes from `MeasuredPerformance.at(j)` for a measured
  cell (voltage, the product's FE, WDE, the carbon share of the co-ion current) or from a
  specified cell's constants within its operating range. A power schedule is solved for `j`
  inside the measured range only. Nothing is extrapolated: the transient stops at the first
  exit from the measured range (current density or temperature), the scheduled operating time
  outside is summed, and such a duty is not feasible.
- An anolyte model is chosen by id from a registry (`domains/chemistry/anolyte.py`); the
  protocol states its id and version, state, accepted species, `initial`, `rates`, `losses`,
  `speciate`, its validity (ionic strength, pH, temperature), assumptions and limitations. An
  unknown id is `cheme.duty-model-unknown`; there is no default model. Time outside the model's
  validity is reported and also makes a duty not feasible. The duty reads a model's state by
  the names it declares (`cation` in mol and `volume` in L required, `carbon` reported when
  present), never by position, and stops when any conserved inventory (mol) of it is
  exhausted.
- The first model is `well-mixed-carbonate` v1 (`domains/chemistry/carbonate.py`): moles of
  the cation and of total inorganic carbon and the volume as conserved quantities,
  instantaneous carbonate equilibrium from the charge balance (Kw 1e-14, pK1 6.37, pK2 10.32
  at 25 °C, ideal solution), CO2 degassing above saturation only when `k_L a` is stated. Its pH
  is on a **concentration basis**, so the time to a threshold at volume-independent fluxes
  scales exactly with the volume. We do not port the authors' finite-rate kinetics: at the pH
  of interest (12 and above) the carbon is almost all CO3-2 and their rates are fast against
  the fluxes, so equilibrium agrees with their concentration-basis result (322.30 h at 1 L,
  ours within 1e-5); a finite-rate model needs sourced rate constants and a stiff solver, and
  can be registered later as another model.
- The KOH/carbonate anolyte stays out of the qualified NaCl electrolyte route
  (`electrolytes.py`, `electrolytes.yml` unchanged); a test keeps it so.
- Duties are integrated by a small generic adaptive Dormand-Prince 5(4) integrator with dense
  output and event location in `foundation/ode.py` (pure Python, no subject knowledge):
  events for the threshold, the minimum inventory, an exhausted inventory, dosing on and off,
  a product target; the schedule's breakpoints and range crossings split the integration. Its
  caps are reported, never silent: more than 100 000 on/off periods over the horizon is a
  schema error, more than 20 000 dosing switches stops the transient with
  `cheme.duty-dosing-chatter`.
- `compare_duties` compares duties **at equal delivered product**: each runs until its
  cumulative product equals the target, within a stated relative tolerance (default 1e-3), or
  is reported as not reaching it. `cheme process duty [--json] [--plot DIR] [--compare ID,ID
  --co KG]` is the thin command; plots are hand-written SVG, measured observations drawn as
  markers and simulated transients as lines. Findings are `cheme.duty-*`; `cheme validate`
  reports those that need no integration.

## Consequences

- Positive: a design states its duty once, with provenance and a fingerprint of every input;
  the time to a stated pH, the dosing a schedule needs and the effect of the reservoir volume
  follow from the same measured series the steady cell uses, with the measured range enforced.
- Positive: comparisons at equal delivered product do not favour a duty that simply makes
  less; the constant-efficiency limit (equal charge, equal deficit) is a test.
- Negative: the pH is a concentration-basis pH of an ideal solution; at 1 mol/L ionic strength
  activity coefficients are far from 1, so it is not a measured pH. The constants are at
  25 °C. The model has no chloride, formate or solids, and supersaturated CO2 stays in
  solution without degassing.
- Negative: the cell's performance is quasi-steady at each instant and does not depend on the
  reservoir's changing composition; the transient after a range exit is not computed.
- Negative: the pure-Python integrator is slower than a compiled one; operating maps with
  frequent dosing switches take seconds.
- Follow-ups: an activity-based or finite-rate anolyte model; temperature dependence of the
  constants; stack sizing from the duties (core#139, done: ADR 0044).

## Evidence

- core#138; tracker core#136; process-library#329 (D1, V1).
- `src/chemeascode/domains/process/electrolysis_duty.py`,
  `src/chemeascode/domains/process/electrolysis_plots.py`,
  `src/chemeascode/domains/chemistry/anolyte.py`, `src/chemeascode/domains/chemistry/carbonate.py`,
  `src/chemeascode/foundation/ode.py`, `src/chemeascode/interfaces/cli/process.py` (`duty`).
- `tests/test_electrolysis_duty.py`, `tests/test_carbonate.py`, `tests/test_ode.py`,
  `tests/data/electrochemical/co2-duty/`.
- `docs/framework/electrolysis-duties.md`.
