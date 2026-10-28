---
name: hazop-review
description: Review and revise a HAZOP study - validate its references, inspect unresolved items, stale bands and changed analysed inputs (P&IDs, cause and effect, risk matrix), revise one node or scenario by its stable id without touching the rest, regenerate the report and prepare a review record in the reviews/ format for a human reviewer. Use before a HAZOP review or stage gate, after a P&ID or C&E change reported as hazop-input-changed, or when asked whether a study is complete or current.
---

# HAZOP review and revision

## Purpose and when to use

Keep a study consistent with the plant it analyses, and bring it to a human review. Use it
when `cheme validate` or `cheme impact` reports `hazop-input-changed` or a stale band, when a
node must be revised, before a `kind: hazop` or `kind: review` gate, and to prepare the review
record.

## Required inputs and missing inputs

- The study, its matrix, the analysed inputs (`analysed:`) and what changed in them
  (`cheme diff <revision> --list` for a P&ID; `git diff` for YAML).
- The reviewer: a person (or an independent agent) other than the study's author. The review
  record needs their name; ask, never fill it in.

## Workflow and tools

1. **Where the study stands**:
   ```sh
   cheme safety hazop check H-01   # findings and state: invalid, draft, assessed, reviewed
   cheme impact                    # also: changed analysed inputs, stale bands
   ```
   - `invalid`: errors (references, codes, schema): fix them first.
   - `draft`: unresolved items (`hazop-unresolved`, stale bands, required actions, changed
     inputs, example data); each finding says what to do.
   - `assessed`: complete, current, every entry accepted by the team; not yet reviewed.
   - `reviewed`: a current human review record covers the study and its analysed inputs.
2. **A changed input** (`hazop-input-changed`): find what changed (`cheme diff`), the nodes
   whose members or scenario refs it touches, and revise only those: their deviations,
   scenarios and safeguards, by id. Mark what you change or add `status: proposed`; the team
   accepts it again. Rate the revised scenarios (`cheme safety hazop rate H-01 --target N2
   --write`); unrelated rows stay as they are. Once the team has reassessed, record the new
   revisions: `cheme safety hazop stamp H-01 --write`. Never stamp without reassessment: it
   would hide the change.
3. **Revise one entry** by its stable id: edit it in place, never renumber or reuse ids; a
   removed scenario's id is not given to a new one. Moving entries changes only display order.
4. **Report**: `cheme safety hazop report H-01` writes `build/hazop/H-01.md` and `.html`
   (state, analysed inputs, matrix, unresolved items, worksheet, safeguards, actions, review).
5. **Review record**:
   ```sh
   cheme safety hazop review H-01           # print the draft record
   cheme safety hazop review H-01 --write   # reviews/<today>-hazop-H-01.md
   ```
   It holds the front matter (`topic: hazop`, the study directory as `scope`, its analysed
   inputs and matrix as `basis`, `reviewed_commit` = HEAD), an empty findings table and the open
   items. The reviewer fills in `reviewer`, writes the findings (skill `review`) and commits it.
   The record does not validate while `reviewer` is empty.
6. **Gates** (`checks/checks.yaml`): `kind: hazop` with `require: [assessed, inputs-current,
   actions-closed, no-example, reviewed]` as the stage needs, and `kind: review, topic: hazop,
   require_kind: [human]`. `cheme check` evaluates them.

## Comparing a drawing with a study

Engineering guidance only; core has no calculation for this. Two documents, each with real
authority and real limits; most poor comparisons borrow one's authority for the other's question.
This split is assembled from CCPS, *Guidelines for Engineering Design for Process Safety* (AIChE),
chapter 10, and Moran, *An Applied Guide to Process and Plant Design* (2015), chapters 3, 15 and
16, rather than stated by them: treat it as a considered argument.

- The P&ID is the study's master document (Moran 3): it shows what exists, what connects to what
  and what is missing from an arrangement. It is one input beside the control philosophy (including
  failure states), design calculations, equipment specifications, the general arrangement and the
  team.
- A drawing cannot settle: independence of a layer from its cause (see `safeguard-crediting`);
  whether a device is sized for the governing case (`relief-scenarios`); whether a valve reaches its
  drawn fail position; whether a function meets an integrity target; whether a detector detects the
  deviation; spatial escalation; phases where protection is absent (start-up, shutdown,
  maintenance); whether the team considered a scenario at all.
- A study does not ensure that all hazards were found (CCPS 10.1.5). "The study found no hazard"
  is not "there is no hazard", and "adequate because the study said so" is unsupported. Hazard
  evaluation recurs across design, construction and operation.
- A study is bound to the revision it analysed (`analysed:`). Before saying a drawing contradicts
  it, confirm both describe the same revision; otherwise report a possible version gap.
- Report three groups: what the drawing confirms, what it contradicts (offered as a question for the
  team unless the drawing alone settles it), and what it cannot speak to, usually the largest.

## Validation and failure handling

- Every finding of `cheme validate` names the study file, the line, the rule and a hint; the
  rule list is in the docstring of `chemeascode.domains.safety.hazop` (`cheme.hazop-*`) and
  `.risk_matrix` (`cheme.risk-matrix-*`).
- A change outside the analysed inputs does not touch the study. If the study should depend on
  another file, add it: `cheme safety hazop stamp H-01 --input <file> --write`.
- Structural validity is not approval: a study without findings is consistent and current,
  not safe.

## Outputs and provenance

Revised entries (proposed until accepted), rewritten bands of the revised scenarios, updated
`analysed:` revisions after reassessment, the report in `build/` and a review record draft.
The review record is a snapshot: it is not edited after it is committed.

## Required human judgment

Whether a change affects a scenario, whether the revised scenarios and ratings hold, and the
review itself are the team's and the reviewer's. Never write a reviewer's name, an approval
(`approved_by`), a closed action or a sign-off on anyone's behalf.

## References

- `safety/README.md`, `reviews/README.md`; skills `review`, `hazop-study`, `hazop-assessment`.
- IEC 61882:2016, clause on recording and follow-up.
- CCPS, *Guidelines for Engineering Design for Process Safety*, chapter 10 (10.1.4, 10.1.5); Moran 2015, chapters 3, 15, 16 (the drawing-versus-study split is the skill's own assembly; needs review before operational use). Skills `safeguard-crediting`, `relief-scenarios`, `process-safety`.
