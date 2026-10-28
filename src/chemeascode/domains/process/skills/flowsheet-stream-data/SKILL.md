---
name: flowsheet-stream-data
description: What a stream carries, design cases and why a balance has several, recycles, first-pass line sizing from velocity, and operating versus design conditions. Use when interpreting or reviewing a stream table, heat and material balance or the basis for line sizes and design pressure.
---

# Stream data and balances

## Purpose and when to use

A PFD is a picture of the mass and energy balance (Moran, *An Applied Guide to Process and Plant
Design*, Elsevier 2015, Ch 3). This skill is the engineering background to the numbers; skill
`process-design` is how they are entered and checked (`cheme process streams`,
`cheme process energy`, `cheme validate`).

## Required inputs and missing inputs

The design case each number belongs to, its unit and basis, and where it came from. A value
nobody knows is `assumed` in the YAML, with the reason in `DESIGN.md`.

## Workflow and tools

A stream carries at minimum flow, temperature, pressure, phase and composition. In core each value
has its provenance (given, assumed, calculated). `cheme process streams` prints the table with a
provenance letter per value and the balance of every block; `--case` selects a case.

Beyond that, engineering guidance only; core has no calculation for the following.

- **Design cases.** A plant runs inside bounds set by its control system, spends time outside them
  in commissioning and maintenance, and must stay safe beyond them. Compute several cases: the
  important feed and demand ranges permutated, a unit out of service, degraded feed, ambient
  extremes, and start-up, shutdown and maintenance where they need modes or services normal
  operation never uses (Moran Ch 7, Ch 8). A flow given without its case is ambiguous.
- **Recycles.** Solved by iteration, not inspection; nested recycles are normal. Flows inside a
  loop can be far larger than the fresh feed suggests, so a unit sized from the feed alone is
  undersized. A loop broken to make the arithmetic tractable should be said to be broken.
  `cheme process simulate` solves recycles (skill `process-simulation`).
- **Checking.** Use checksums per unit and a second engineer; assume an unchecked balance contains
  a mistake (Moran Ch 8).
- **Line size at first pass** from superficial velocity (volumetric flow over internal area) and
  rules of thumb (Moran Ch 9): pumped water-like liquid below about 1.5 m/s; gravity-fed
  water-like liquid below about 1 m/s; liquid with settleable solids about 1 to 1.5 m/s; air-like
  gas about 20 m/s. Design two-phase flow out where possible, since it is hard to predict and its
  pressure drop can exceed single-phase by orders of magnitude. A hydraulic calculation uses all
  three drawings: valve counts from the P&ID, bends and tees from the arrangement, static head and
  vessel pressures from the PFD.
- **Operating versus design conditions.** Design conditions are the limits equipment, gaskets,
  seats and relief devices must survive. A common convention is design pressure at least 10 % or
  about 25 psi above maximum operating pressure, whichever is greater, with design temperature at
  or above maximum operating temperature plus a margin (Parisher and Rhea, *Pipe Drafting and
  Design* 4e, Elsevier 2022, Ch 7). Project standards override it; present it as a convention.

## Validation and failure handling

`cheme validate` reports balances that do not close (`cheme.process-balance`) and those that
cannot be evaluated. A failing balance is a design finding to record in `DESIGN.md`, not a reason
to change numbers. Velocity and margin figures above are not checked by cheme.

## Outputs and provenance

Give a number with its unit, its design case and its source. Say when a value is a rule of thumb
rather than a calculation; that matters more than the number.

## Required human judgment

Choice of cases, acceptance of rule-of-thumb sizing, and design margins.

## References

- Moran 2015, Ch 3, Ch 7-9. Parisher and Rhea 2022, Ch 7.
- Retained as general method: cases, recycles, checksums. Needs review before operational use:
  the velocity figures and the 10 % / 25 psi margin are first-pass conventions only.
