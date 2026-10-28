# Reviews

One file per review: `YYYY-MM-DD-<topic>.md` (skill `review`). A record is a snapshot: it is not
edited after it is committed; the next review carries its open findings forward.

## Front matter

Every record starts with YAML front matter (`cheme schema review`), which `kind: review`
gates in `checks/checks.yaml` read:

```yaml
---
topic: design                      # what the gate asks for: design, o2-safety, hazop, ...
reviewed_commit: <sha>             # the commit whose files were reviewed
scope: [pid/P-01.xml, DESIGN.md]   # files or directories reviewed
reviewer: <name>
reviewer_kind: human               # human | agent (independent) | self (the author's own review)
branch: <branch reviewed>          # optional
merge: pending                     # optional: the merge commit to the default branch
approved_by: <name>                # optional: a human who approved a self review
---
```

`branch` and `merge` say where the reviewed work is: stage work is on `stage/<stage>-<topic>`,
`merge` is `pending` until a human or the reviewer (not the author) merges it to the default
branch, where the stage's sign-off takes effect.

A review gate fails when a file of `scope` changed after `reviewed_commit`, so a review always
covers the drawings as they are. A change of nothing but digests (full sha256 fingerprints or
commit ids, such as the model fingerprint in a regenerated `layout/lifting-study.md`) is not a
change: the review stays current.

Optionally, `basis:` lists other files the review rests on without reviewing them, each with the
revision used (a commit sha, or `sha256:<hex>` of the file) and how the review relates to it
(`derived-from`, `represents`, `analyses` or `depends-on`, the default):

```yaml
basis:
  - {path: process/flowsheet.yaml, revision: <sha>, relation: analyses}
```

`cheme impact` lists the records whose scope or basis changed since, as review needed
(info). It never changes a record or marks it invalid.

## Findings

```markdown
## Findings
| id | sheet | item | finding | severity | status | proposed action |
|---|---|---|---|---|---|---|
| 2026-10-18-design#1 | P-01 | P-101A/B | no suction strainer | medium | open | add one |
## Previous findings
| id | finding | severity | status | evidence |
|---|---|---|---|---|
| 2026-10-01-design#4 | T-101 has no vent | high | closed 521473c | vent drawn, see crop |
```

- **Id**: `<file stem>#<n>`, unique across the repository and never reused.
- **Severity**: `critical`, `high`, `medium`, `low`.
- **Status**: `open`, `closed <commit>` (the fixing commit is required), `accepted: <reason, by
  whom>`, or `superseded by <id>`. No "partly closed": split the finding.
- **Previous findings** (required): every finding of an earlier review of an overlapping scope
  that is not closed or accepted, with its current status and evidence. A finding's status is
  the one in the latest record that lists it.

## Listing open findings

`cheme status` counts and lists the open findings (`--json`: `reviews.open`). By hand:

```sh
grep -h '| open |' reviews/*.md
```

then drop the ids that a later record's Previous findings lists as closed, accepted or
superseded. `cheme validate` reports an open finding the newest record does not carry
forward (`cheme.review-previous-missing`) and ids or statuses outside the format.
