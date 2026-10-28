---
name: heat-integration
description: Hub for heat recovery across a whole process: stream data, pinch analysis, minimum utility targets, utility levels, heat exchanger network design and the review of an integrated flowsheet, with where the method is contested. Use when energy targets, the pinch, minimum heating and cooling or an exchanger network come up.
---

# Heat integration

## Purpose and when to use

Every process stream that has to be cooled could in principle heat one that has to be heated.
Each kilowatt passed between two process streams saves a kilowatt of hot utility and a
kilowatt of cold utility. Heat integration asks how far that can go, and at what capital cost,
before any network is drawn (Ray and Das, *Process Equipment and Plant Design*, Elsevier 2020,
§5.1). This skill is the index; read the member that matches the step:

| Skill | For |
|---|---|
| `heat-integration-stream-data` | Turning a flowsheet into hot and cold streams: supply and target temperatures, heat capacity flowrates, what to leave out, what counts as a utility |
| `heat-integration-pinch-analysis` | Composite curves, the minimum approach, the pinch and the three rules a network must obey to reach the minimum utility |
| `heat-integration-minimum-utility-targets` | The problem table, minimum heating and cooling, threshold problems, choosing the minimum approach against capital |
| `heat-integration-multiple-utilities` | The grand composite curve and placing several steam, cooling and refrigeration levels |
| `heat-integration-network-design` | Designing a network from the pinch outwards: matching, stream splitting, number of units, loops and paths |
| `heat-integration-flowsheet-review` | What an integrated plant looks like on a flowsheet, what integration costs in operation, what can and cannot be checked |

Use `process-design` for the flowsheet itself and `process-simulation` for solved heat and
material balances.

## Required inputs and missing inputs

The method runs on stream data: flows, heat capacities, and supply and target temperatures for
every stream that is heated or cooled, for a stated operating case. Equipment design
temperatures and pressures are mechanical limits, not supply or target temperatures; never
extract stream data from them. If the data are missing, ask for them or take them from a
solved simulation case, and say which case the numbers describe: targets differ between
operating cases.

## Workflow and tools

Engineering guidance only, with one partial exception.

- Core has no stream-data extraction, no utility-level placement and no network design.
- Core has no `cheme` command for pinch analysis. It has a Python function,
  `chemeascode.domains.process.heat_integration.pinch.pinch_analysis(streams, dt_min)`, that runs
  the problem table algorithm on streams you give it (K, kW/K or piecewise segments) and returns
  minimum hot and cold utility, the pinch temperatures and the grand composite curve. Its result
  is labelled `basis == "targets"`: no matches, areas, unit counts or utility levels. The
  function does not check your stream data.
- `cheme process simulate` audits each exchanger of a solved case for temperature crosses and
  for approaches below the declared minimum approach; that is a check of one exchanger, not a
  pinch analysis.

Never state a target you did not calculate from data you were given.

## Validation and failure handling

- From a drawing alone you can recognise integration (which exchangers are process-to-process,
  which are utility, how they are arranged and controlled), not judge it. Whether an exchanger
  crosses the pinch needs temperatures and duties.
- Stream data that are inconsistent between cases, or ones you had to assume, are reported as
  such beside every number that depends on them.

## Outputs and provenance

State the operating case, the stream table, the minimum approach used and where each came from.
A target is what is thermodynamically possible, not what the design should do. Record decisions
in `DESIGN.md`.

## Required human judgment

Whether to integrate at all, the minimum approach, which streams to exclude on safety, layout or
contamination grounds, and every trade between energy and operability are decisions for the
project team.

### Where the method is contested

The sources do not agree on when heat integration belongs; pass the disagreement on rather
than resolving it.

- For: pinch analysis is an essential tool for both new design and retrofit of energy-intensive
  plants, starting at the conceptual stage (Ray and Das §5.1; Coker, *Petroleum Refining Design
  and Applications Handbook* v2, Wiley 2021, glossary).
- Against, for new design: Moran, *An Applied Guide to Process and Plant Design*,
  Butterworth-Heinemann 2015, Ch 5 and Ch 18, argues that the data it needs do not exist at
  design stage; that energy is one criterion among safety, controllability, cost and start-up;
  that exchangers are not free; and that a highly integrated plant is harder to control,
  commission and maintain. He places its value in existing plants (debottlenecking,
  optimisation) and in late checks on large energy users.

Retrofit is common ground: Moran sees value only there, and Ray and Das use it there too (§5.3.2,
§5.4.2). Ray and Das themselves say safety overrides every match and that real constraints limit
the approach to relatively unconstrained systems (§5.3.1, §5.4.4).

### Terms to keep apart

- The minimum approach temperature (dTmin) is a chosen driving force. The pinch temperature is a
  location: where the hot and cold composites are closest. One source uses "pinch temperature"
  for dTmin (Ray and Das §5.3.1, §5.4); do not follow it.
- A temperature pinch inside one exchanger, where its own hot and cold curves nearly touch, is
  not the process pinch (Mokhatab, Poe and Mak, *Handbook of Natural Gas Transmission and
  Processing*, Elsevier 2015, §8.7).
- Water pinch (flow against contaminant concentration; Ray and Das §5.9, Moran Ch 18) is the
  same idea for water reuse; it is only a pointer here, not a method this family covers.

## References

- Ray and Das, *Process Equipment and Plant Design*, Elsevier 2020, §5.1, §5.3-§5.4.
- Moran, *An Applied Guide to Process and Plant Design*, Butterworth-Heinemann 2015, Ch 5, Ch 18.
- Coker, *Petroleum Refining Design and Applications Handbook* v2, Wiley 2021 (glossary).
- Mokhatab, Poe and Mak, *Handbook of Natural Gas Transmission and Processing*, Elsevier 2015, §8.7.
- `src/chemeascode/domains/process/heat_integration/pinch.py` (the targets function).

Retained as independently verifiable general method: the energy-saving principle and the
distinction between dTmin and the pinch. Needs review before operational use: the characterisation
of the sources' positions (check against the books) and the water-pinch pointer.
