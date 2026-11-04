---
name: heat-integration-minimum-utility-targets
description: The problem table that gives a process's minimum heating and cooling and the pinch location, threshold problems with no pinch, and choosing the minimum approach temperature against capital, with typical values and their conditions. Use when calculating or checking energy targets.
---

# Minimum utility targets

## Purpose and when to use

The minimum hot and cold utility are the least heating and cooling a process can need at a chosen
minimum approach. They come from the stream data before any exchanger is placed, which is why they
are targets rather than results (Ray and Das, *Process Equipment and Plant Design*, Elsevier 2020,
§5.4.1). Part of the family `heat-integration`.

## Required inputs and missing inputs

Stream table (`heat-integration-stream-data`) for one operating case, and dTmin. If the user gives
no dTmin, ask for it or state the assumed value beside every dependent number; do not choose one
and report the result as the target.

## Workflow and tools

For a solved plant, `cheme process pinch --dt-min X` gives these targets from the recorded
simulation run, with the current utility demand beside them (see `heat-integration`); for
stream data you assemble yourself, use the function below. The problem table algorithm is
implemented in the Python function
`chemeascode.domains.process.heat_integration.pinch.pinch_analysis(streams, dt_min)`
(temperatures in K, CP in kW/K, duties in kW); it returns minimum hot and cold utility, the pinch
and the grand composite curve, and no network. The method it follows (Ray and Das §5.4.1, §5.10):

1. Shift temperatures: lower hot-stream temperatures by dTmin/2, raise cold-stream temperatures by
   dTmin/2.
2. Balance each interval: split the shifted range at every shifted supply and target; the net
   requirement is the sum of cold CPs minus the sum of hot CPs present, times the width. Positive
   is a deficit, negative a surplus.
3. Cascade downwards from the hottest interval with nothing entering.
4. Find the most negative cumulative flow in the cascade (not the most negative single interval)
   and add its magnitude as heat at the top. If no flow is negative, the minimum hot utility is
   zero.
5. Read: heat added at the top is the minimum hot utility; heat leaving the bottom is the minimum
   cold utility; the shifted temperature of the zero-flow boundary is the shifted pinch. The hot
   pinch is the shifted pinch plus dTmin/2, the cold pinch minus dTmin/2. If the only zero is at the
   top or bottom boundary there is no pinch (threshold problem).

Source discrepancy: one source's worded description says to add the most negative balance of a
single interval, while its worked problem correctly adds the most negative cumulative flow
(§5.4.1 against §5.10). Quoting the worded rule can give a wrong target.

Threshold problems have no pinch: as the composites are brought closer one utility falls to zero at
a threshold approach, and closing further saves nothing because the other utility's total stays
the same (§5.7). Only one utility is needed. A small change in dTmin can turn a threshold problem
into an ordinary pinch problem (§5.10).

Choosing dTmin: it is an economic choice, not a physical constant. A small value cuts utility
cost and raises area; a large one does the opposite; total annualised cost has a minimum. Exchanger
pressure-drop pumping cost usually pushes the optimum up a little (§5.2, §5.3.1). A network can be
targeted for minimum utility, minimum total area (assuming pure counter-current exchange) and
minimum number of units (§5.3.1).

Typical values quoted by Ray and Das (§5.3.2), each with its condition:

| Basis | Typical dTmin | Condition |
|---|---|---|
| Shell-and-tube | usually not below about 10 degC | even a single-pass unit is not truly counter-current |
| Plate | about 5 degC | |
| Plate-fin | about 1-2 degC | |
| Refining | 30-40 degC | low film coefficients, near-parallel composites, fouling |
| Petrochemical and chemical | 10-20 degC | lighter, cleaner fluids |
| Cryogenic | 3-5 degC | clean, low-viscosity fluids, special exchangers |

Cautions: the exchanger-type values apply only to exchangers near the pinch; the source adds that
further constraints apply where boiling or condensing happens at the closest approach, without
saying which way they push. The same source gives separate process-to-utility approaches (steam
heating, refrigeration, flue gas, cooling water) and says utility loads should respect those, not
the process dTmin (§5.3.2). Experience values give workable retrofit targets but should still be
checked quantitatively.

## Validation and failure handling

A cascade with nothing added at the top satisfies the energy balance only; adding the minimum hot
utility is what makes the driving forces feasible (§5.4.1). Check that hot-stream and cold-stream
duties in the table balance with the utilities found. `pinch_analysis` raises `ValueError` for
invalid streams; it does not decide whether the streams are right.

## Outputs and provenance

Minimum hot and cold utility, pinch temperatures or "threshold problem", dTmin and its basis, the
stream table, and whether the numbers came from hand calculation or the function.

## Required human judgment

The project's dTmin and its basis. Sources are silent on shell-count targeting, per-stream
contributions to dTmin for streams with very different film coefficients, and a worked cost
optimisation of dTmin beyond illustrative curves; ask for the project's basis rather than supplying
one.

## References

- Ray and Das, *Process Equipment and Plant Design*, Elsevier 2020, §5.2, §5.3.1, §5.3.2, §5.4.1, §5.7, §5.10.
- `src/chemeascode/domains/process/heat_integration/pinch.py`.

Retained as general method (stated by the cited textbook): the problem table, threshold behaviour,
the economic nature of dTmin. Needs review before operational use: the typical dTmin values
(book experience values, not a standard).
