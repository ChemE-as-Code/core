---
name: review
description: Review the plant repository or a change to it - run validation and the engineering-step checks, look at the rendered sheets, the 3D layout's plan and section drawings and the diff, and write findings to reviews/. Use when asked to review, check, or sign off a stage or a branch, or to review the layout.
---

# Reviewing

## Purpose and when to use

Review the plant repository or a branch and write the findings to `reviews/`. Sign off a stage
only when asked (step 7).

## Required inputs and missing inputs

The commit to review and, for a branch, the default branch to diff against. What you cannot
check goes under "Not checked" in the record.

## Workflow and tools

1. `cheme validate` and `cheme check`. Every failing check and every error is a finding.
   Read the last line of `validate`: it names the sheets, lists and cross-checks it ran; what it
   did not compare goes under "Not checked". `cheme check` prints the gates and writes
   nothing. Title blocks: `cheme.template-metadata` (sample or placeholder data such as
   `Model name="example"`, `DEXPI Example C01`, `A. P. Prover`), `cheme.titleblock-approval`
   (an approver, approval date or status "approved" without a sign-off of the current stage in
   `checks/status.json`, a checker without a review record in `reviews/`) and
   `cheme.titleblock-sheet` (SheetNumber or title disagree with `plant.yaml`) are findings;
   a sheet must never show an approval nobody gave. `--ignore RULE` / `--only RULE` filter the
   report; never filter with `grep -v`.
2. For a branch: `cheme diff main --list` gives one line per changed plant item with its
   counts (`--verbose` adds each change and the drawing that shows it, `--flat` one line per
   object); `cheme diff main` writes `build/diff.html` to look at. Does every change have a
   reason in the commit messages and `PROGRESS.md`? Is any changed item `not drawn`?
3. **Drawing** of each changed sheet (each sheet, before a sign-off). Look for overlaps,
   crossings and misplaced labels with evidence, not by impression:
   - `cheme validate` prints one `drawing <sheet>: N line-through-label, N line-crossing,
     N label-overlap, N label-far-from-owner` line per sheet (`(+N accepted)` for accepted ones).
     Each finding carries `[crop X0,Y0,X1,Y1]` and `[id ...]`: render it with
     `cheme render pid/<sheet>.xml --png --crop <crop> --scale 8` and look.
     `cheme render pid/<sheet>.xml --png --findings` marks them all on the sheet.
   - **Quote the counts** in the record's `## Drawing` section, e.g.
     `P-04: 0 line-through-label, 1 line-crossing (accepted: D-023), 2 label-far-from-owner`.
     Every remaining finding is either a finding of the review or accepted with a reason (an
     `accept:` entry in `checks/checks.yaml` with the finding's id; errors cannot be accepted,
     only fixed). A statement such as "no
     overlaps" is only allowed with these counts at 0.
   - The lint does not see everything (an ambiguous but not overlapping tag, a symbol too small
     to read, a wrong arrow; `--emphasise-inline` draws valves and actuators larger for reading,
     not for judging their size). Sweep each sheet in tiles: `cheme render pid/<sheet>.xml --png
     --tiles auto` (or `--tiles 4x3`) writes `build/<sheet>_tile-<row><column>.png` and prints
     each tile's `--crop ... --scale ...` (with `--findings`, accepted findings are grey and
     marked `(accepted)`). Read every tile and name the tiles in the record (`P-04: A1-C3 read`);
     what you did not read goes under "Not checked".
4. **Engineering review** of each changed sheet. Render the changed regions, `cheme render
   pid/<sheet>.xml --png --crop X0,Y0,X1,Y1` (`cheme show <tag>` prints the drawing's region
   as `at X0,Y0,X1,Y1 mm`; the PNG is `build/<sheet>_crop-X0-Y0-X1-Y1.png`, and `--rev main`
   with the same crop gives the before picture), and read the XML of what you doubt: isolation valves around
   equipment that is maintained, check valves on pump discharges, relief for anything that can
   be blocked in, drains and vents at low and high points, instruments for what the design basis
   says is controlled (`cheme show <instrument tag>` prints its loop, signal and actuating
   chain), DN consistent along each line and with the line list (and with literal labels:
   `cheme.label-literal`). Off-page texts and trip notes name other tags in plain text:
   `cheme.offpage-mismatch` and `cheme.label-tag-unknown` warn when one names a wrong
   line, sheet or tag; the `cheme.label-tag` infos list what each such text names, so check
   they say what is meant. Note what you checked and what you could not.
4a. **Layout review** (a record of `topic: layout`, its `scope` the `layout/` files,
   `piping/routing.yaml` and `layout/plant-model.yaml`; gates `layout-3d` and `layout-review`):
   - `cheme layout build --check` (the committed model is current) and `cheme layout
     report`: quote the counts in the record's `## Layout` section: lines routed / skipped /
     unrouted, the chains per method (every `direct` or `rack+direct` route is a finding or
     accepted with a reason) and per reason, the rack fill per tier, the model findings per
     rule (`layout-clash-*`, `-headroom`, `-access-blocked`, `-zone-crossing`, `-separation`,
     and the engineering rules `-wall-penetration`, `-tier`, `-vent-outlet`, `-free-span`,
     `-operability`, `-access-enclosed`, `-access-unconnected`, `-escape-ways`,
     `-escape-travel`, `-ladder-clearance`, `-walkway-riser`, `-landing-width`, `-egress-zone`, `-operator-unknown`, `-lifting`,
     `-laydown`, `-pad-overlap`, `-spacing`, `-building-spacing`, `-zone-source`, `-support-stub`,
     `-steel-in-way`, and the
     tray rules `-tray-zone`, `-tray-span`),
     platforms, stairs, ladders, valve access platforms (`VP-<valve tag>`), support steel
     (`support_steel`) and penetrations `review_needed`, and every `layout-pipe-disconnected`
     (error: a pipe end that does not meet its connection). For each engineering finding
     say whether it is fixed, accepted (with the reason) or open; their criteria are ASSUMED
     package values unless `criteria:` in the site plan cites the site's standard. An
     acceptance that quotes a length (a span, a run, a distance) must quote the current one:
     `cheme.accept-stale` (validate) names one whose value is out of date;
   - render and **read** the plot plan and at least two sections: `cheme layout render
     --plan --png` (`build/layout-plan.png`), `--section y=<across the main rack> --png` and
     `--section x=<through the tallest structure or cold box> --png`, plus crops around what
     you doubt (`--crop X0,Y0,X1,Y1`). Name each PNG in the record (the `layout-3d` gate looks
     for the plan and the sections there): `build/layout-plan.png`,
     `build/layout-section-y68.png`, ...;
   - check against the design basis and `DESIGN.md`: separations kept (measured with
     `cheme show <tag> --layout`, never estimated), roads and fire access, the air intake
     upwind of vents, pumps near their suction source, maintenance envelopes free, every
     elevated valve, instrument and manway reachable (skill `structures-access`), vent and
     relief outlets above the walking levels, pipes through walls only in declared openings,
     heavy items with a crane, a clear lane and laydown (`cheme layout lifting`: the
     working radius, load moment and capacity needed per lift), escape routes; the
     operators declared for valves and transmitters out of reach (`operators:` in
     `piping/routing.yaml`): a chain wheel only on a valve that is really used rarely;
     a rule that finds nothing is not proof: look in the sections for platforms, ladders and
     valves inside a casing, stair towers whose landings meet no platform, relief tailpipes
     under stairs and landings, trays over machines and in zones, crane pads on racks,
     buildings close together, and report what no rule saw as a finding (and the missing rule
     to cheme-as-code);
     zones declared and still ASSUMED (skill `area-classification`), lines over roads and
     walkways at their headroom, oxygen and cryogenic lines on their own tier or edge (skill
     `pipe-routing`);
   - what the model cannot show (stress, supports, structural design, the area classification
     study) goes under "Not checked" with who must do it.

## Validation and failure handling

Run `cheme validate` after writing the record: it reports left-out previous findings and bad
finding ids or statuses (`cheme.review-*`).

## Outputs and provenance

5. Write `reviews/<YYYY-MM-DD>-<topic>.md` (format in `reviews/README.md`). It starts with front
   matter that a `kind: review` gate reads; `reviewed_commit` is `git rev-parse HEAD` of what you
   reviewed, `reviewer_kind` is `self` when you review your own work, `agent` for an independent
   agent and `human` only for a person:
   ```markdown
   ---
   topic: design                      # the gate's topic: design, o2-safety, hazop, ...
   reviewed_commit: <sha>
   scope: [pid/P-01.xml, DESIGN.md]   # files or directories reviewed
   reviewer: <name or agent>
   reviewer_kind: human | agent | self
   branch: <branch reviewed>
   merge: pending                     # or the merge commit to the default branch
   ---
   # Review: <topic>
   ## Findings
   | id | sheet | item | finding | severity | status | proposed action |
   |---|---|---|---|---|---|---|
   | <file stem>#1 | P-01 | T-101 | ... | high | open | ... |
   ## Previous findings
   | id | finding | severity | status | evidence |
   |---|---|---|---|---|
   | 2026-10-01-design#3 | ... | medium | closed 521473c | vent drawn, crop build/P-01_crop-... |
   ## Drawing
   <per sheet: the `drawing <sheet>:` counts from validate, each accepted finding with its
   reason, the tiles read>
   ## Layout
   <layout reviews: the layout report counts, the plan and section PNGs read, accepted model
   findings with their reason>
   ## Checked and fine
   ## Not checked
   ```
   - **Ids** are `<this file's name without .md>#<n>` (`2026-10-18-design#1`), never reused,
     unique across the repository.
   - **Severity**: `critical`, `high`, `medium` or `low`. A sign-off is refused while a
     critical or high finding is open, or is closed by a commit that is not in HEAD's
     history.
   - **Status**, one of: `open`; `closed <commit>` (the commit that fixed it; required);
     `accepted: <reason, by whom>`; `superseded by <id>`. There is no "partly closed": split the
     finding into a closed one and a new open one.
   - **Previous findings** is required: list every finding of earlier reviews of an overlapping
     scope that is not closed or accepted yet, with its current status and the evidence (a
     commit, a crop, a validate line). Find them with
     `grep -h '| open |' reviews/*.md` and the earlier records' Previous findings sections;
     `cheme status` lists the open ones. `cheme validate` reports a carried-over finding
     you left out (`cheme.review-previous-missing`), bad ids and statuses
     (`cheme.review-finding-id`, `review-finding-status`).
   - A record is a snapshot: do not edit it after it is committed. The next review records
     the new status of each finding.
6. Do not fix findings in the same commit as the review; each fix is its own change. **Closing
   a finding**: fix it in its own commit, then the next review lists it under Previous findings
   as `closed <that commit>` with the evidence that it is fixed.

## Required human judgment

7. **Signing off a stage** (only when asked to sign off): you may not sign off your own review.
   The sign-off rests on a record by someone else: a human, or an independent agent
   (`reviewer_kind: agent`); a `self` record needs `approved_by: <human>`. A `kind: validate`
   gate with `fail_on: warning` and the drawing `rules` (see `checks/checks.yaml`) fails while a
   drawing finding is neither fixed nor accepted. A `kind: maturity` gate fails while
   `cheme maturity` puts the plant's calculation maturity below its `require` level (or, with
   `max_claim: true`, while `process.yaml` claims a design maturity above the evidence); it never sets the review status. Then
   `cheme check --stage <stage> --write --review reviews/<record>.md` runs the gates of every
   stage up to `<stage>` and writes its entry to `checks/status.json` (commit, date, signer,
   branch, review). It refuses, and writes nothing, when the tree is not committed, a gate
   fails, the record is the signer's own or a critical/high finding is open: fix that, do not
   work around it. Commit `status.json` alone, as the last commit of the stage. Do not run
   `--write` in an ordinary review, and never edit `status.json` by hand.
8. **Branch and merge.** Stage work is on a branch `stage/<stage>-<topic>`. The record names it
   in `branch:` and quotes `cheme diff main --list`; `merge:` is `pending` until the branch
   is merged, then the merge commit (the next review records it). The sign-off commit is the
   last on the branch, and the stage counts as signed off only once it is on the default
   branch. A human or the reviewer merges, never the author; the author's summary says whether
   a merge is pending.

## References

- `reviews/README.md` (record format), `checks/checks.yaml` (gates, accepted findings),
  `checks/status.json` (sign-offs)
- skills `layout-yaml`, `pipe-routing`, `structures-access`, `area-classification` (layout
  review)
