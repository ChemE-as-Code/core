---
name: process-safety
description: Hub for process-safety questions about why a protective device or safeguard is there, which cause it answers and what a drawing cannot settle - relief scenarios, crediting safeguards, equipment-specific HAZOP causes, hazardous-area classification and the HAZOP study skills. Use first when the question is about hazards rather than about what is drawn, then follow to the member skill.
---

# Process safety (hub)

## Purpose and when to use

Other skills say what belongs on a drawing or in a model. The process-safety skills ask why: which
cause a device answers, whether something protects against that cause, and what the drawing,
the model or the files cannot settle. A hazard is a property of the plant, its fluids and its
operation; a P&ID or a flowsheet shows a fraction of that, so many answers end in a design
basis, a study or a datasheet that the project does not hold. Saying so is a valid answer.
This skill indexes its members and sets what may be claimed. Engineering guidance only; core has
no calculation for relief sizing, layer independence or hazard identification.

## Required inputs and missing inputs

The question, the part of the plant concerned (tags, lines) and the documents that exist: P&IDs,
`control/cause-effect.yaml`, `process/design-basis.yaml`, `DESIGN.md`, any HAZOP study, relief
study or area classification. Ask for the ones that decide the answer rather than assuming them.

## Workflow and tools

Engineering guidance only; core has no calculation for this. Members, by flat name:

| Skill | Use it for |
|---|---|
| `relief-scenarios` | Why a relief device is there, which cause governs its size, when none is required |
| `safeguard-crediting` | Whether something counts as an independent protection layer against a given cause |
| `hazop-equipment-causes` | Which deviations and causes are credible for pumps, compressors, separators, heaters, exchangers, reactors, tanks |
| `area-classification` | Release sources, zones in `layout/zones.yaml`, purged and pressurised enclosures |
| `hazop-study`, `hazop-assessment`, `hazop-review` | Drafting, rating and reviewing a HAZOP study file with `cheme safety hazop ...` |

Working rules for every member:

- Name the layer under discussion: process design, basic control, alarms and operator action,
  instrumented shutdown, relief devices, containment. Relief is the last resort; a design that
  reaches for it before the inner layers deserves a comment (CCPS, *Guidelines for Engineering
  Design for Process Safety*, AIChE, section 2.1.2 and chapter 14).
- Separate what is drawn from what is decided. A drawing shows that a device exists and where it
  connects; it does not show the sizing case, the credited scenario or whether the case was
  judged credible.
- Do not present a reading as a study. A hazard study is a team activity with a record; one can
  prepare for it, compare a drawing with it and point out what stays open. A produced list is a
  starting point for a team, and a review of this kind does not ensure that every hazard has been
  found (CCPS, section 10.1.5).
- Node definitions and severity or likelihood scales are team decisions. Neither source gives a
  calibration; use only the project's own risk matrix (`hazop-assessment`) and never convert
  scales between studies.

## Validation and failure handling

A statement that a layer is independent, a plant is safe or a device is adequate cannot be
validated here; report it as a question. When a source is silent (vessels outside the equipment
types in `hazop-equipment-causes`, columns beyond a starting set), say so instead of reasoning by
analogy. `cheme validate` and `cheme safety hazop check` test references and consistency, not
safety.

## Outputs and provenance

Say which skill and which source section a statement rests on, which documents were read and at
which revision, and what stays open. Numeric thresholds quoted in member skills are marked for
manual review and are not design values.

## Required human judgment

Everything that decides safety: governing relief case, credited safeguards, independence,
integrity targets, zone classification, acceptance of residual risk. These belong to the HAZOP
team, a relief and area-classification study and a competent person.

## References

- CCPS, *Guidelines for Engineering Design for Process Safety* (AIChE): section 2.1.2, section
  10.1.5, chapter 14. General method; the statements are re-expressed and need review before
  operational use.
- IEC 61882:2016, HAZOP application guide.
