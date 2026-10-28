---
name: flowsheet-development
description: How a process gets from feed to product and what a flowsheet at a given design stage should contain - design envelope and cases, unit-operation sequence, recycles, utilities, scale-up and inherent safety. Use when deciding the shape of a flowsheet before or while writing process/flowsheet.yaml.
---

# Flowsheet development

## Purpose and when to use

A flowsheet is the tool that decides what the plant will be, so its shape follows the decisions
still open. This skill is the method; skill `process-design` is how the result is written as
YAML and built with `cheme process build`. Skill `flowsheet-diagram-types` says which drawing
carries what, and `flowsheet-process-model-vocabulary` names steps precisely.

The PFD, the P&ID and the general arrangement divide the work and none substitutes for another
(Moran, *An Applied Guide to Process and Plant Design*, Elsevier 2015, Ch 6): the PFD integrates
the mass and energy balance, the P&ID integrates control and the system, the general arrangement
integrates physical and hydraulic constraints. All three exist from the earliest stage; what
changes with the stage is the detail each carries. An early P&ID is a complete drawing at coarser
resolution, not a draft of a later one.

## Required inputs and missing inputs

- Feed quantity and quality, product specification, ambient conditions, each as a range with a
  likelihood rather than a single number (Moran Ch 7).
- The design stage the answer is pitched at.
- Reaction evidence where there is a reaction (skills `reaction-evidence-search`,
  `route-selection`, `reactions`).

A missing range is asked for or recorded as `assumed` with the reason in `DESIGN.md`.

## Workflow and tools

Engineering guidance only; core has no calculation for the judgments below. The deterministic
parts are in `process-design` (build, balances, stream table) and `process-simulation`
(`cheme process simulate`, which solves recycles in DWSIM).

1. Start from the design envelope, not from a flowsheet. Permutate the important ranges into a
   handful of design cases (for example high flow with weak feed, low flow with strong feed) and
   carry them all (Moran Ch 7); in the YAML these are `cases:`.
2. Name the unit operations from feed to product in flow order, as steps rather than equipment.
   A block is a process section until you decide how the step is done.
3. Close the recycles early. A recycle returns a stream to the feed of a step it already passed,
   so it needs iteration, and its ratio drives the size of the reactor and the separation behind
   it. A flowsheet whose recycles are not closed cannot be sized (Moran Ch 6, Ch 8).
4. Decide pumped or gravity flow, because it changes layout, elevations and equipment (Moran Ch 9).
5. Add the utilities each step needs; a step with no heating, cooling or power connection is
   incomplete (skill `utility-systems`).
6. Add control and safeguarding last, when the material path is settled.

Judgment that changes the answer (Moran unless noted):

- Simplicity is a design objective: a simpler plant is easier to operate, commission and maintain
  and is usually cheaper.
- Scale up versus parallel trains is a turndown question; parallel units can be switched off as
  demand falls and keep the inventory in any one unit smaller.
- Inherent safety (less inventory, a less hazardous material, milder conditions, limiting the
  effect) is preferred to added protective equipment, which costs money and can itself fail.
- A rule of thumb encodes experience of real plants of that kind. Scale-up by more than about a
  factor of five, design from bench-scale data without full-scale reference, or a first plant of
  its type is first-principles territory, where confidence in every number drops.
- Three significant figures is generous; the data rarely supports more.
- A batch process cannot be summarised by a P&ID as a continuous one can, because its state
  changes with time; it needs documents that show the sequence.

## Validation and failure handling

Nothing here is checked by cheme. `cheme validate` checks the YAML and balances once the flowsheet
is written; it does not check that the sequence, recycles or scale-up judgment are sound. An
unclosed recycle shows up as a balance that cannot be evaluated or does not close; record it as a
design finding in `DESIGN.md` instead of adjusting numbers.

## Outputs and provenance

Name the stage the answer is pitched at, the design cases behind it and the data you do not have.
A flowsheet without its envelope looks more certain than it is. Keep what a drawing shows (fact)
apart from what the process implies (reasoning).

## Required human judgment

The design cases, the scale-up route, the inherent-safety trade-offs and the stage of detail are
the team's decisions.

## References

- Moran, *An Applied Guide to Process and Plant Design*, Elsevier 2015, Ch 6-9 (drawings and
  stages, design envelope and cases, recycles and balances, pumped versus gravity flow). Statements
  above are general method that a reader can verify against this book.
- Needs review before operational use: the factor-of-five scale-up threshold is quoted as
  "about" in the source and is not a limit.
