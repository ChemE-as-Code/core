---
name: pid-review-design-review
description: Question-led review of a P&ID sheet before issue - stage, identification, equipment, lines, instrumentation, safety, utilities, cross-sheet consistency and operability - with pointers to the pid-design skills and a list of what the drawing cannot show. Use when asked whether a P&ID is complete or ready for review or issue.
---

# Reviewing a P&ID before issue

## Purpose and when to use

Asks "is this drawing finished for its purpose?". It does not certify compliance or safety. It is
a set of questions built from general engineering reasoning; each area points to the skill that
holds the sourced detail. Commissioning view: `pid-review-commissioning-readiness`.

## Required inputs and missing inputs

The sheet, its entries in the lists, the stage it is judged against (concept, review, construction
issue), and the project's own documentation standard. Ask for the standard; this skill does not
reproduce any. Completeness is relative to stage: an early revision judged against a
construction-issue expectation is a wrong review.

## Workflow and tools

Engineering guidance only; core has no calculation for this. Start with the mechanical checks:
`cheme validate` (sheet and list consistency, with what it compared), `cheme render` for the
sheet and tiles, `cheme status`. A clean run is not a review. Then ask, per area:

1. **Identification**: is every item and line tagged and in the lists (`lists-sync`)? Does the
   title block state revision and status truthfully (`pid-draft`)?
2. **Equipment**: does each item carry the data its class needs, and its nozzles connected or
   blanked? For pumps, compressors, vessels, exchangers see the member skills in `pid-design`.
3. **Lines**: size, class and service per line; size changes through fittings; class changes at a
   break (`pid-design-materials-and-spec-breaks`); lines leaving the sheet end at a connector
   saying where they go; no component leads nowhere.
4. **Isolation, vents and drains**: how is each item isolated and emptied
   (`pid-design-isolation-vents-drains`)?
5. **Instrumentation and control**: is each loop wired sensor to final element, with fail actions
   (`pid-design-control-valve-station`, `pid-design-instrumentation`)? Do trips share nothing with
   control?
6. **Safety**: where could each enclosure be overpressured, blocked in, backflowed, over-filled
   (`pid-design-pressure-relief`, `relief-scenarios`)? Where does each release go? Which
   hazard-study actions are closed (`hazop-review`)?
7. **Utilities and services**: are connections isolated against backflow and contamination
   (`utility-systems`)?
8. **Across sheets**, where reviews often fail: do line tags correspond on the next sheet, do
   cross-references resolve, and do control and shutdown loops correspond across sheets (Killcross,
   *Chemical and Process Plant Commissioning Handbook* 2e, Elsevier 2021, §7)?
9. **Operability**: what does the drawing support at turndown, start-up, planned and emergency
   shutdown and maintenance? These find different defects from mechanical checks.

## Validation and failure handling

List what the drawing cannot show, so silence is not read as a pass: legend consistency, notes,
holds, line weights, new-versus-existing marking, vendor package detail, and the outcome of a
hazard study. Elevation, pipe metallurgy and relief sizing are not on a P&ID either. Where a
sheet or class was not fully read, say the review is partial.

## Outputs and provenance

Findings by area with the objects worst affected (tag or line number), the stage assumed, the
unchecked list. Lead with whether the drawing is ready for the stated milestone and the one thing
that most blocks it.

## Required human judgment

Whether the drawing is ready, and every safety conclusion: a named reviewer decides; this skill
only prompts questions.

## References

Toghraei, *P&ID Development* (Wiley 2019), including its checklist chapter (§19); Killcross §7;
CCPS, *Guidelines for Engineering Design for Process Safety*. The question set is general
engineering reasoning, not derived from a published documentation standard; needs review before
operational use.
