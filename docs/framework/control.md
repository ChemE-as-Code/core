# Control foundations: narratives, loops and sequences

A plant repository can say how its process operates and how its controls meet the operating
objectives, in files next to the cause-and-effect list. It is documentation of control
*intent*: what the loops are, what they measure and move, which setpoints they hold, how the
plant is started up and shut down. It is not dynamic simulation, controller tuning, DCS or PLC
code, commissioning or SIL verification (see [Not modelled](#not-modelled)).

All of it is optional. `cheme init` writes templates of the four files (commented examples,
the philosophy's headings). A register without entries and a document that is still the
template, unchanged, count as not started: they get no findings, the report and
`GET /api/control` leave them out (`has_control` in `GET /api/repo` is false), and a plant
that does not document its control sees no empty pages. Any edit of a document starts it. The bundled skills `control-narrative`, `control-loops` and `control-sequences`
drive the work; each calls `cheme validate` and `cheme control report`.

| file | kind (`cheme schema ...`) | what |
|---|---|---|
| `process/narrative.md` | `narrative` (front matter) | the process sections: purpose, boundaries, normal conditions, operating modes, material and energy flow |
| `control/philosophy.md` | `control_philosophy` (front matter) | operating objectives, control hierarchy, normal and disturbed operation, operator versus automatic actions, equipment and utility failures |
| `control/loops.yaml` | `loops` | the regulatory control loops |
| `control/sequences.yaml` | `sequences` | startup, shutdown and abnormal-mode sequences with their permissives |
| `control/cause-effect.yaml` | `interlocks` | the trips (existing; a few optional fields added) |

Code: `domains/control/schemas.py` (the formats), `domains/control/register.py` (the checks),
`domains/control/documents.py` (front matter and headings), `domains/control/report.py` (the
reports), `foundation/reviews.py` `coverage` (review status). The worked example is
`examples/process-separation` (a depropanizer).

## The documents

The narrative and the philosophy are Markdown: the text explains. Their YAML front matter names,
by id, what the text is about, so that `cheme validate` can check it:

```markdown
---
schema: cheme/narrative/v1
sections:
  - id: FEED
    title: Feed let-down and flash
    equipment: [D-101]
    blocks: [FL, V1, D1]          # blocks and steps of process/flowsheet.yaml
    cases: [design]
    modes: [normal, startup, shutdown]
    loops: [FIC-101, LIC-102]
    sequences: [SEQ-START]
    interlocks: [I-01]
unresolved: [the column's own control is not described yet]
---

## FEED Feed let-down and flash
...
```

Each section needs a heading that starts with its id. The philosophy's front matter lists
`objectives` and `failures` (each with the loops, sequences and interlocks it rests on), and its
body has a heading for each topic: *Operating objectives*, *Control hierarchy*, *Normal
operation and disturbances*, *Operator and automatic actions*, *Equipment and utility failures*,
*Assumptions and open points*.

Values are not repeated in the prose: the operating case lives in `process/flowsheet.yaml`, the
setpoints in `control/loops.yaml`, the trips in the C&E. Write *proposed* behaviour as
proposed, and record what is open under `unresolved`. The text is never checked for meaning.

## The loop register

```yaml
schema: cheme/loops/v1
loops:
  - id: FIC-105                    # stable id, usually the loop tag
    title: Hot pentane flow (slave)
    section: PREHEAT               # a narrative section
    cases: [design]                # operating cases it is designed for
    variable: flow                 # flow, level, temperature, pressure, composition, speed, ratio, other
    measurement: [{tag: FT-105}]
    controller: FIC-105
    action: reverse
    final_elements:
      - {tag: FV-105, kind: valve, actuator: pneumatic, fail: closed}
    targets:
      - {kind: setpoint, value: 5000, unit: kg/h, provenance: assumed, source: hot oil circulation,
         cases: [design], stream: H1, property: flow}
    modes: [manual, auto, cascade]
    normal_mode: cascade
    transitions:
      - {from: auto, to: cascade, by: operator, condition: {loop: TIC-103, state: in auto}}
    links:
      - {type: cascade, loop: TIC-103}   # TIC-103's output is this loop's setpoint
    alarms:
      - {tag: FT-105, condition: FAL, response: check the hot oil pumps}
    interlocks: [I-01]             # related trips, by C&E id
    rationale: ...
    operator: ...                  # judgement the operator has to make
    unresolved: []
basis: [{path: process/flowsheet.yaml, revision: "sha256:...", relation: depends-on}]
```

### Conventions

- **Controller action.** `direct`: the output rises as the measurement rises; `reverse`: it
  falls. It says nothing about the valve.
- **Fail position.** `fail` is where the final element goes on loss of signal, power or motive
  air: `open`, `closed`, `last`, for a drive `stop`, for a heater `off`. It is independent of
  the controller's action.
- **Output and travel.** Controller output 0 to 100 % moves a final element over `travel`,
  by default `[0, 100]`: a rising output opens a valve, speeds up a drive, raises a heater's
  duty. `travel: [100, 0]` closes it as the output rises.
- **Split range.** Two or more final elements each give the `range` of the output they act on
  (`range: [0, 50]`, `range: [50, 100]`).
- **Unknown is not a default.** A value left out (`action`, `fail`, `variable`, a target's
  `value`) is not known yet. It is reported as `cheme.control-incomplete` until it is given;
  nothing assumes air-to-open or reverse action for you.
- **Links** are listed on the loop they act on: `cascade` (the master `loop` sets this loop's
  setpoint), `ratio` (the setpoint is `ratio` times the flow of `loop` or `tag`),
  `feedforward` (the measured disturbance `tag` adds to the output), `override` (this loop and
  `loop` drive the same element through a `select: low | high` selector). A cascade master
  needs no final element of its own.
- **Targets** carry their unit, provenance (`given`, `assumed`, `calculated`), source and
  optional origin as everywhere else ([contract.md](contract.md#values)), the operating modes
  and cases they apply to, and optionally the stream value of the case they are
  (`stream` with `property: flow | temperature | pressure`).

A loop is regulatory control. It is never a safeguard: protective functions are the interlocks
of the C&E, which `interlocks` refers to. When a loop measures or moves a tag of an interlock,
validate says so (`cheme.control-shared-element`, info) and concludes nothing: independence and
SIL are the HAZOP's and the SIL study's.

## Sequences

```yaml
schema: cheme/sequences/v1
sequences:
  - id: SEQ-START
    mode: startup                  # startup, shutdown, abnormal, normal, other
    section: FEED
    equipment: [D-101, E-101]
    permissives:                   # what must hold before it may start
      - {interlock: I-01, state: reset}
      - {all: [{loop: FIC-101, state: in manual}, {loop: LIC-102, state: in manual}]}
    interlocks: [I-01]             # the trips that protect it, by C&E id (not repeated)
    steps:
      - id: S1
        actions:
          - {loop: FIC-101, action: setpoint, setpoint: {value: 1200, unit: kg/h, provenance: assumed}}
          - {loop: FIC-101, action: auto, by: operator}
        complete: {tag: LT-102, state: "> 30 %", delay: {value: 30, unit: s}}
        timeout: {value: 30, unit: min}
        on_timeout: abort          # a step id, or abort
      - id: S2
        ...
        next: end                  # default: the step below
    abort:
      condition: {any: [{interlock: I-01, state: tripped}, {text: operator judges the column unstable}]}
      actions: [{tag: FV-101, action: close}]
      then: SEQ-STOP
    reset: {latching: true, manual: true, condition: {interlock: I-01, state: reset},
            restart: {sequence: SEQ-STOP, state: complete}}
```

An action is a tag `start`, `stop`, `open` or `close`; a loop put in `manual`, `auto` or
`cascade` or given a `setpoint`; another sequence `run`; or `text`. Start permissives are kept
apart from trips: the trips stay in the C&E and are named by id.

## Conditions

Permissives, step entry and completion, mode transitions, abort, reset and an interlock's
`logic` share one condition format:

| form | example |
|---|---|
| an item in a state | `{tag: LT-102, state: LAH}`, `{loop: FIC-101, state: in auto}`, `{interlock: I-01, state: reset}`, `{sequence: SEQ-STOP, state: complete}`, `{step: S2, state: complete}` |
| AND, OR | `{all: [...]}`, `{any: [...]}` |
| voting | `{vote: {k: 2, of: [a, b, c]}}` (2oo3) |
| a delay, a dead band | `delay: {value: 5, unit: s}`, `deadband: {value: 2, unit: "%"}` on any condition |
| logic the format does not model | `{text: ...}`, reported as `cheme.control-logic-text` and never interpreted |
| not known yet | `{unresolved: ...}` |

### The cause-and-effect list

Existing files load and render unchanged. An interlock may now also give, all optional:
`logic` (the trip condition when it is more than the single cause, e.g. 2oo3 with a delay; the
cause stays the matrix row), `delay`, `latching` (`true`/`false`; omitted: not stated),
`reset: manual | automatic` and `bypass` (whether and how it may be bypassed or inhibited).
The tags of `logic` are checked like the cause's.

## What validate checks

`cheme validate` runs the checks when the repository has any of the files (not for
`cheme validate <files>`, which says so). Every finding names the file, the line, a rule and a
hint, and has its own id for `accept:`.

| rule | level | when |
|---|---|---|
| `cheme.control-duplicate` | error | a loop, sequence, step, section, objective or failure id given twice |
| `cheme.control-document` | error | front matter that is not valid |
| `cheme.control-cycle` | error | loops whose setpoints depend on each other (cascade links in a ring), or a loop linked to itself. Ratio, override and feedforward links follow a measurement or select between outputs and may form rings: they are intentional feedback |
| `cheme.control-unknown-tag` | warning | a tag in no list and on no sheet (a renamed or removed tag); not checked while a sheet fails to load or a list is invalid |
| `cheme.control-ref` | warning | a loop, sequence, step, interlock, case, section, block or stream that does not exist; not checked against a file that is invalid (loops, sequences, C&E) or missing (sections without a narrative, cases without a flowsheet) |
| `cheme.control-conflict` | warning | contradicting definitions: two loops on one final element without an override, two loops naming one controller, a setpoint outside its own limits, a mode a loop does not have, a split range in which not every element has its range, or a single element with one (overlaps and gaps between ranges are not checked) |
| `cheme.control-unit` | warning | a value without unit or provenance, a unit that does not fit (a pressure without (a)/(g), a temperature not in K or °C, a flow in metres, a delay or timeout that is not a time, also an interlock's `delay` and the delays in its `logic`, checked for every C&E list). Without Pint (extra `units`) only K, °C, the (a)/(g) pressures, %, s, ms, min and h are known, and another unit passes unchecked |
| `cheme.control-case` | warning | a target that names a stream value of an operating case and differs from it: a temperature by more than 0.5 K, a pressure by more than 0.5 % (absolute against absolute, gauge against gauge), a flow by more than 0.5 %; info when the case has no value yet or the two cannot be compared (a gauge target against an absolute case value) |
| `cheme.control-unreachable` | warning | a sequence step that no step leads to |
| `cheme.control-incomplete` | info | a draft gap: a loop without variable, measurement, action, final element, fail position, target or modes; an alarm without an operator response; a step without completion condition or actions; a timeout without `on_timeout`; a sequence without abort or reset; a startup without permissives; a narrative section without its heading; a philosophy topic missing |
| `cheme.control-unresolved` | info | an open point the record states |
| `cheme.control-logic-text` | info | logic or an action given as text |
| `cheme.control-shared-element` | info | a loop measures or moves a tag of an interlock |
| `cheme.control-alarm-trip` | info | an alarm at a high-high or low-low condition: a trip, which belongs in the C&E |
| `cheme.control-stale` | info | an entry of `basis:` changed since the revision recorded |

The draft findings are info so that a concept-stage record can be incomplete. A stage gate
decides when they must be gone; the template's `checks/checks.yaml` has this one at detail
engineering (a plant without control records passes it):

```yaml
- id: control-complete
  title: Loops and sequences complete, every control reference resolved
  stage: detail
  kind: validate
  fail_on: info
  rules: [cheme.control-incomplete, cheme.control-unresolved, cheme.control-ref,
          cheme.control-unknown-tag, cheme.control-conflict, cheme.control-unit,
          cheme.control-case, cheme.control-cycle, cheme.control-duplicate,
          cheme.control-document, cheme.control-unreachable]
```

## Review status

Whether a control file is *drafted*, *reviewed* or *accepted* comes from the review records in
`reviews/` (`foundation.reviews.coverage`), never from a field of the file: the latest record
whose `scope` covers the file decides.

- **drafted**: no record covers it, or it changed since the record's `reviewed_commit`;
- **reviewed**: a current record covers it;
- **accepted**: a current record by a human (`reviewer_kind: human`, or a review
  `approved_by` one), with no finding of a blocking severity still open in any record that
  covers the file.

A record's `reviewed_commit` must be an ancestor of HEAD to count.

Accepted means the review records say so. It does not mean the controls are implemented,
verified or approved for construction.

## Reports and the viewer

`cheme control report` writes `build/control-loops.html` and `.csv` (the loop summary) and
`build/control-sequences.html` (each sequence with its permissives, steps, abort and reset),
next to the C&E matrix of `cheme cause-effect`. Each page shows the stable ids, the provenance
of each value, the review status of each file, the source commit and the findings.
`cheme control report --json` and `GET /api/control` return the same data
(`domains.control.report.control_report(root)`); the endpoint answers 404 when the plant has no
control records, so a viewer shows no empty page. `cheme export-static` records it, except in a
snapshot with `--exclude` (it names reviewers, like `status`).

## Not modelled

The format stays small on purpose. Not modelled, and not claimed:

- dynamic simulation, controller tuning, MPC, DCS or PLC code generation, commissioning;
- SIL assignment or verification, protection independence, safe operating limits: nothing is
  derived from the descriptive logic;
- a complete alarm-management lifecycle (rationalisation, priorities by consequence, alarm
  floods): alarms are listed with the operator response only;
- bypass and inhibit *records* (who bypassed what, when): `bypass` on an interlock states the
  design intent only;
- timers, counters, latches and arithmetic beyond `delay`, `deadband`, `vote` and the reset
  fields: write them as `text`, which stays visible as `cheme.control-logic-text`;
- whether an action is correct (a reverse-acting controller on a fail-closed valve, say): the
  process gain is not known to the format.
