---
name: control-narrative
description: Draft the process narrative (process/narrative.md) and the control philosophy (control/philosophy.md) of a plant, section by section, referring to the operating cases, loops, sequences and interlocks by id instead of repeating their values. Use when a plant has its flowsheet and wants its operation described, before HAZOP, or when cheme.control-incomplete, -unresolved, -ref or -document findings name either file.
---

# Process narrative and control philosophy

## Purpose and when to use

Describe how the process operates and how its controls meet the operating objectives, in words
an operator, a HAZOP team and a control engineer read the same way. The narrative goes section
by section (purpose, boundaries, normal conditions, operating modes, material and energy flow);
the philosophy covers the objectives, the control hierarchy, normal and disturbed operation,
what the operator does versus what runs automatically, and the equipment and utility failures.
Use it once the flowsheet exists (skill `process-design`), and keep it current as the loops
(skill `control-loops`) and sequences (skill `control-sequences`) are defined. Control
documentation is optional: write it when the plant needs it, not as empty pages.

## Required inputs and missing inputs

- `process/flowsheet.yaml`: the blocks and steps (the sections' `blocks`), the operating cases
  (`cases`), the stream values. `process/design-basis.yaml`: capacity, feeds, products,
  utilities.
- The equipment and instrument lists, the P&IDs where drawn, `control/cause-effect.yaml`.
- What only people know: the operating objectives and their priority, the turndown and the
  modes the plant must run in, how the operator is meant to intervene, which utility failures
  matter. Ask; record an answer you did not get under `unresolved` and as an assumption in
  `DESIGN.md`, never as a fact.

## Workflow and tools

1. **Sections.** In the front matter of `process/narrative.md` (`cheme schema narrative`) list
   the sections in flow order: `id`, `title`, `equipment` (tags), `blocks` (flowsheet block and
   step ids), `cases`, `modes`, and the `loops`, `sequences` and `interlocks` that belong to
   them. Under a heading `## <id> <title>` per section write its purpose, boundaries (from
   which stream to which), normal operation (by case), modes and open points.
2. **Philosophy.** In `control/philosophy.md` (`cheme schema control_philosophy`) list the
   `objectives` (each with the loops that serve it) and the `failures` (loss of instrument
   air, power, cooling water, steam, a machine trip: the designed `response`, with the loops,
   sequences and interlocks involved). Keep the six headings of the template: Operating
   objectives, Control hierarchy, Normal operation and disturbances, Operator and automatic
   actions, Equipment and utility failures, Assumptions and open points.
3. **Refer, do not repeat.** Name the case (`design`), the loop (`FIC-101`), the trip (`I-01`)
   and the decision (`D-012`); do not copy a setpoint or a trip value into the prose, where it
   would go stale unseen. A value that exists nowhere yet belongs in its record (a loop target,
   the C&E), not in the text.
4. **Say what it is.** Mark proposed behaviour as proposed and assumptions as assumptions
   (`unresolved`, `DESIGN.md`). Nothing in these files says the design is approved or
   implemented; the review records do (`cheme control report` shows the status).
5. **Check.** `cheme validate`, then `cheme control report` for the status of each file.

## Validation and failure handling

- `cheme.control-document` (error): the front matter is not valid YAML or not the schema.
- `cheme.control-ref`: a loop, sequence, interlock, case or block that does not exist (fix the
  id or create the record); `cheme.control-unknown-tag`: a tag in no list and on no sheet.
- `cheme.control-incomplete` (info): a section without its heading, a missing philosophy topic,
  a narrative without sections in its front matter; `cheme.control-unresolved`: each open
  point. A file still unchanged from the template is not checked.
- `cheme.control-stale`: an entry of `basis:` changed since its revision: reread the source,
  update the text, then the revision.
- The prose is not checked for meaning. Reading it against the records is the reviewer's job.

## Outputs and provenance

`process/narrative.md` and `control/philosophy.md`, committed. Record the sources the text rests
on under `basis:` (`{path, revision, relation}`) when it depends on a particular revision of a
study or the flowsheet. Review status (drafted, reviewed, accepted) comes from a review record
whose `scope` covers the file (skill `review`).

## Required human judgment

The operating objectives and their priority, the modes the plant runs in, what the operator is
expected to decide, and the response to each failure are engineering decisions. Draft them,
mark them proposed, and have a process and a control engineer review them. Do not invent
operating experience.

## References

- `docs/framework/control.md` of cheme-as-code: the formats, conventions and checks.
- Skills `control-loops`, `control-sequences`, `process-design`, `review`.
- Worked example: `examples/process-separation` of cheme-as-code.
