# Safety: HAZOP studies

| path | what |
|---|---|
| `safety/hazop/<study-id>/study.yaml` | one HAZOP study (`cheme schema hazop-study`): the one authoritative file, edited by the team and by agents |
| `safety/risk-matrix.yaml` | the risk matrix the studies rate against (`cheme schema risk-matrix`). **The one `cheme init` writes is example data** (`example: true`): replace it with your company's matrix before anything is assessed. A matrix is `status: proposed` until the team accepts it (`status: accepted`, `accepted_by:`); a study rated against a proposed matrix stays a draft |
| `build/hazop/<study-id>.md`, `.html` | the report, derived from the study (`cheme safety hazop report`); never edited |
| `reviews/<date>-hazop-<study-id>.md` | the review record of the study (skill `review`, `cheme safety hazop review`) |

There is no study until you start one: `cheme safety hazop init H-01 --title "..." --input
pid/P-01.xml --input control/cause-effect.yaml`. A new study is a draft and has no judgements.

## The study file

```yaml
schema: cheme/hazop-study/v1
kind: hazop-study
id: H-01                         # = the directory name
title: Feed vessel and transfer pump
scope: what the study covers, and what it does not
modes: [{id: normal, title: Normal operation}]
analysed:                        # the files analysed, at the revision analysed (cheme safety hazop stamp)
  - {path: pid/P-01.xml, revision: 'sha256:...', relation: analyses}
risk_matrix: safety/risk-matrix.yaml
assessment_basis: how risk is ranked (initial before safeguards, residual with them)
nodes:
  - id: N1                       # stable ids: never renumbered, never reused
    title: V-101 and pump suction
    design_intent: ...
    members: [V-101, LT-102, {tag: 80-P-101, sheet: P-01}]
    status: accepted             # proposed (default) until the team accepts it
    deviations:
      - id: N1-LL
        guide_word: less         # "no" (quoted or not), more, less, as-well-as, part-of, reverse, other-than, early, late, before, after
        parameter: level
        scenarios:
          - id: S1
            cause: ...
            consequence: ...
            refs: [V-101, P-101]
            safeguards: [SG1]    # ids of safeguards: below
            actions: [A1]        # ids of actions: below
            status: accepted
            risk:
              initial:           # before the safeguards, per category of the matrix
                - {category: people, severity: "3", likelihood: C, basis: ..., status: accepted}
              residual:          # with them, as the team judges it; never derived by a tool
                - {category: people, severity: "3", likelihood: A, basis: ..., status: accepted}
safeguards:
  - {id: SG1, title: Interlock I-01 stops P-101, kind: interlock, interlock: I-01, refs: [LT-102], status: accepted}
actions:
  - {id: A1, text: ..., owner: ..., status: open}   # proposed, open, closed, rejected (+ response)
```

- **Ids** are what the team, the actions and the review records refer to. Insert and reorder
  freely: the order is display order only.
- **Plant references** are tags as printed on the P&IDs (equipment, instrument, piping item,
  line number); add `sheet:` where a tag alone is ambiguous, or name a DEXPI object by
  `{sheet, object}`. Interlocks are declared in `control/cause-effect.yaml` and referred to by
  id, not copied.
- **Who decided**: everything is `status: proposed` until the team accepts it. Agents propose;
  only the team writes `accepted`. The calculated `band:` of a rating is written by `cheme
  safety hazop rate --write` (with the matrix and input fingerprint) and never by hand.
- **Unrated is explicit**: a scenario without ratings, a rating without a code or a basis, a
  band not looked up yet are listed as unresolved, never filled in.
- `extensions:` (on the study, a node or a scenario) holds other tools' data by tool name;
  cheme-as-code keeps it and does not read it.

## Workflow

1. **Scope and source revision.** `cheme safety hazop init`, then the scope, the operating
   modes, the team and the assessment basis. `analysed:` records the revision of every P&ID and
   control file the study analyses.
2. **Nodes and design intent.** Split the plant into nodes; give each its members and design
   intent. Skill `hazop-study`.
3. **Deviations.** For each node, the guide words that make sense with each parameter of its
   intent (flow, pressure, temperature, level, composition, ...).
4. **Causes and consequences.** One scenario per credible cause and consequence; a deviation
   without a credible cause says so in `notes:`.
5. **Safeguards.** The ones the P&IDs and the cause and effect actually have, by tag or
   interlock id.
6. **Assessment and recommendations.** The team rates severity and likelihood per category,
   initial and, where it credits safeguards, residual, each with its basis; `cheme safety hazop
   rate H-01 --write` looks the bands up; a band whose matrix policy requires an action asks for
   one. Skill `hazop-assessment`.
7. **Human review.** `cheme safety hazop check H-01`, `cheme safety hazop report H-01`, then a
   review record (`cheme safety hazop review H-01` prepares it; skill `hazop-review`).
8. **Revisions.** When a P&ID or the C&E changes, `cheme validate` reports
   `hazop-input-changed`: reassess the nodes it touches, rate again (`--target N1`), record
   the new revisions (`cheme safety hazop stamp H-01 --write`) and review again.

## Commands

| | |
|---|---|
| `cheme safety hazop init ID [--title T] [--input F]... [--matrix F]` | a draft study |
| `cheme safety hazop check [ID] [--json]` | the study's findings and state: `invalid`, `draft`, `assessed` (complete, current, accepted), `reviewed` (and a current human review) |
| `cheme safety hazop rate ID [--target NODE\|SCENARIO] [--write] [--json]` | the band of every rating from the matrix; `--write` records them, nothing else changes |
| `cheme safety hazop report ID` | `build/hazop/ID.md` and `.html` |
| `cheme safety hazop stamp ID [--input F]... [--write]` | the analysed inputs' recorded and current revisions (a file by its sha256, a committed directory by the commit); `--write` records the current ones |
| `cheme safety hazop review ID [--write]` | a review record to complete, in the format of `reviews/` |

`cheme validate` checks every study: ids, references inside the study, tags against the lists
and P&IDs, interlocks against the C&E, matrix codes, stale bands, actions, changed inputs.

A study that is `assessed` is complete and consistent, not approved. Stage gates ask for what a
stage needs, e.g. in `checks/checks.yaml`:

```yaml
- {id: hazop-basic, title: HAZOP assessed and reviewed, stage: basic, kind: hazop,
   require: [assessed, inputs-current, no-example]}
- {id: hazop-review, title: HAZOP human review, stage: basic, kind: review, topic: hazop,
   require_kind: [human]}
```

The tools look bands up in the matrix; they do not estimate frequencies, infer severities,
credit safeguards or model consequences. Those judgements are the team's.
