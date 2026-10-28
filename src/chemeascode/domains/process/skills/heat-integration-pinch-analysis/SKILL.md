---
name: heat-integration-pinch-analysis
description: Composite curves, the minimum approach temperature, the pinch and why it splits a process in two, and the three rules a network must obey to reach minimum utility. Use when interpreting a pinch or judging whether an exchanger wastes energy.
---

# Pinch analysis

## Purpose and when to use

The pinch is where a process is thermally tightest. Finding it gives the least heating and cooling
the process can need, and shows which exchangers would waste energy wherever they sit (Ray and
Das, *Process Equipment and Plant Design*, Elsevier 2020, §5.3-§5.4.2). Part of the family
`heat-integration`.

## Required inputs and missing inputs

A stream table (`heat-integration-stream-data`) for one operating case and a chosen minimum
approach temperature dTmin. If the user gives no dTmin, ask for it or state the assumed value next
to every number that depends on it.

## Workflow and tools

Engineering guidance only for the interpretation below. The numbers can be calculated with the
Python function `pinch_analysis` (see `heat-integration`), which returns targets only.

Composite curves:

1. Build each composite interval by interval. Split the temperature range at every supply and
   target temperature; in each interval the enthalpy change is the width times the sum of the CPs
   of the streams present. Start at zero at the lowest temperature and add upwards (§5.3). This holds
   for the hot composite too.
2. Read the two composites as one hot and one cold stream exchanging heat counter-currently.
3. Slide the cold composite along the enthalpy axis until the smallest vertical gap equals dTmin.
   The enthalpy datum is arbitrary.

Then: the horizontal overlap is the recoverable heat; the cold composite's overhang at the hot end
is the minimum hot utility; the hot composite's overhang at the cold end is the minimum cold
utility. A smaller dTmin gives more recovery and less utility but more area (see
`heat-integration-minimum-utility-targets`). Shifting a composite vertically means changing stream
temperatures, a process change, not a targeting step (§5.3).

The pinch is the point of closest approach; normally there is one. Exchangers near it run on the
smallest driving forces and tend to be the largest and dearest (§5.4). It splits the process into
two independent problems (§5.4.2): above it the process is a net heat sink (only process exchange
and hot utility belong there); below it a net heat source (only process exchange and cold
utility). The hot and cold streams have their own pinch temperatures, dTmin apart.

The three rules. A network reaches minimum utility only if (§5.4.2): no heat crosses the pinch; no
cold utility is used above it; no hot utility is used below it. The penalty is doubled: every
kilowatt moved from above to below must be restored as extra hot utility above and removed as
extra cold utility below, as with extra reboiler duty reappearing as condenser duty in a column.
A cooler above the pinch or a heater below it has the same effect. Real networks nearly always
break the rules somewhere (§5.4.2); a rule broken deliberately, to save an exchanger or for safety
or control, is a trade-off, not a mistake (see `heat-integration-network-design`).

Retrofit: look for exchangers, heaters and coolers that break the three rules and correct them. In
refinery crude preheat trains this typically raises the furnace inlet temperature and saves fuel
(§5.4.2).

## Validation and failure handling

A pinch that depends on an assumed dTmin or an extrapolated stream is a provisional pinch; say so.
A problem with one utility equal to zero has no pinch (threshold problem; see
`heat-integration-minimum-utility-targets`).

## Outputs and provenance

Minimum hot and cold utility, pinch temperatures (hot and cold side), the dTmin and stream table
they rest on, and any exchanger flagged as crossing the pinch with the reason it may be deliberate.

## Required human judgment

The placement rules for heat pumps, heat engines, distillation columns and other units against the
pinch are not in the cited source; do not state them from here and ask whether the user has a
basis. Whether a rule is deliberately broken is a decision for the project team.

## References

- Ray and Das, *Process Equipment and Plant Design*, Elsevier 2020, §5.3, §5.4, §5.4.2.

Retained as general method (stated by the cited textbook): composite construction, the pinch
decomposition and the three rules. Needs review before operational use: the refinery retrofit
remark.
