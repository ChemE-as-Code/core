# Static viewer snapshots

`cheme export-static DIR` writes what the viewer asks `cheme serve` for, for one revision, as
plain files. The viewer's static data source reads them, so a plant can be inspected without a
server, for example embedded in the Process Atlas or attached to a review.

```sh
cheme export-static build/snapshot                 # the working tree
cheme export-static build/snapshot --rev v1.0      # a revision
cheme export-static build/snapshot --max-file-mb 5 # export larger files as text too
cheme export-static build/snapshot --exclude 'reviews/**' --exclude PROGRESS.md
```

`DIR` must be new, empty, or a snapshot written earlier (a `manifest.json` of
`cheme/viewer-snapshot/v1` and a `data/` directory holding only files named like the export
names them, `<hash>.json|.svg|.txt`; nothing else), which is then replaced. Any other
directory is refused (exit 2) and left untouched, and so are the plant repository itself, a
directory that contains it (`.`, `..` inside the repository) and a directory inside it other
than below `build/` (`build/snapshot` is fine, `build` itself is not). On a case-insensitive
filesystem (APFS, NTFS) these paths are compared ignoring case, so `Plant/PID` is refused like
`plant/pid`. The snapshot is written to a temporary directory next to `DIR`, with the
permissions of any new directory, and moved into place only once it is complete, so a failed
export leaves the previous snapshot as it was. If the previous snapshot cannot be deleted
after the new one is in place, the export still succeeds and prints a warning naming the
leftover directory.

## Layout

```
DIR/
  manifest.json   schema cheme/viewer-snapshot/v1: source, limits, skipped, excluded, withheld,
                  entries
  data/<hash>.json|.svg|.txt
```

`entries` maps a request key to `{file, status, type}`. The key is the endpoint without
`/api/`, then `?` and the query as raw `key=value` pairs sorted by key and joined with `&`;
empty values and `rev` are left out:

| request | key |
|---|---|
| `GET /api/repo` | `repo` |
| `GET /api/pid.svg?path=pid/P-01.xml` | `pid.svg?path=pid/P-01.xml` |
| `GET /api/streams?case=design` | `streams?case=design` |
| `GET /api/layout/plan.svg?level=L0` | `layout/plan.svg?level=L0` |
| `GET /api/estimate/equipment` | `estimate/equipment` |
| `GET /api/reactions?case=design` | `reactions?case=design` |
| `GET /api/datasheets/C-1101.svg` | `datasheets/C-1101.svg` |

`source` records the commit, whether the working tree had changes, the revision asked for and
the tool version, so a consumer can tell a stale snapshot from a current one.

## What is in it

`repo`, `branches`, `log` (last 50 commits), `tree`, `checks`, `interlocks` (a 404 is recorded
when the plant has no cause-and-effect list), `validate`, `impact`, `status` and `maturity`
(working tree only; `maturity` with `checked_at` null, so the snapshot stays deterministic, and
its whole validation run a second time), the drawing of every sheet, the stream table (and one per case), `layout`, `mto`, a plan
per level, `lca`, `tea` (when `repo` says `has_tea`), `estimate/equipment` (when `repo` says `has_equipment_estimate`),
`simulation` and `reactions` (when `repo` says `has_simulation`, `has_reactions`; also one per
case, `simulation?case=design`), `datasheets` with `datasheets/<TAG>` and
`datasheets/<TAG>.svg` of each (when `repo` says `has_datasheets`), and `yaml`
and `file` for every text file up to the size limit. Sheet XML is exported as its drawing, not
as text.

Left out, because a snapshot is one read-only revision: other revisions, diffs, running checks
(`POST /api/checks/run` and its session token), the history of a single file, sections at
arbitrary coordinates and files above the size limit (listed in `skipped`).

## Leaving files out

`--exclude GLOB` (repeatable) keeps files out of a snapshot that is published, for example
working notes, review records or agent instructions. A glob is matched against the
repo-relative path as `/api/tree` lists it, segment by segment:

| glob | matches |
|---|---|
| `PROGRESS.md` | that file at the root only (not `docs/PROGRESS.md`) |
| `docs/*` | files directly in `docs/`; `*` never crosses a `/` |
| `reviews/**` | `reviews/` and everything below it; `**` spans zero or more directories |
| `**/.gitattributes` | that name in any directory, the root included |

Globs are case-sensitive, like git paths, except where the repository's filesystem ignores
case (APFS, NTFS by default): there `progress.md` names `PROGRESS.md` and excludes it.

A matching path is left out of `tree` (and so is a directory that held only matching paths),
is not exported as `file` or `yaml`, and is left out of the file list and the findings of
`validate` and `impact`. Excluding a sheet file is an error: the drawing is the point of a
snapshot.

Every other answer computed from a matching file is withheld. The export records which files
each answer reads, and an answer (or error) that read a matching file is not written. It is
listed under `withheld` as `{endpoint, reason, files: []}`, where `reason` names the globs.
Excluding `equipment/**` withholds `estimate/equipment` and the stream table (it links the
equipment list, and the instrument list: excluding `control/instrument-list.yaml` withholds
it too). Excluding `estimate/tea.yaml` withholds `tea`. Excluding
`process/flowsheet.yaml` withholds `streams`, `simulation`, `reactions` and `library`. The
answers per case are then not exported either.

**BFD and PFD drawings are withheld with the flowsheet.** A `kind: bfd` or `kind: pfd` sheet is
generated from `process/flowsheet.yaml` and `process/materials.yaml`, and its drawing shows
their blocks, streams and materials. When either file is excluded, the `pid.svg` of every BFD
and PFD sheet is withheld (`reason`: a BFD/PFD drawing generated from files matching the
globs). The sheets stay listed in `repo` and `tree`; P&ID drawings are not affected.
`cheme export-static` prints each withheld answer.

There are three exceptions:

- `repo` is kept. It holds plant.yaml's name, stages and sheets, plus flags saying which kinds
  of files exist.
- `kinetics` leaves out the excluded data files of `experiments/kinetics/`.
- `datasheets` leaves out the excluded datasheets and drawings, and their
  `datasheets/<TAG>` answers. The kept answers do not name an excluded file: it is removed
  from their `source.fingerprints` and `source.dirty`.

Answers that are not filtered: `log` still holds the commit messages, a finding of `validate`
or `impact` on a kept file may name an excluded one, and `status`, `maturity` and `control`
are left out of a snapshot with excludes. Globs match the path as the tree lists it: a kept symlink in the
working tree that points to an excluded file is exported under its own name, so exclude the
link as well.

`manifest.json` records the globs, sorted, as `excluded` (`[]` without the option), so a
publisher can check a snapshot was exported for publication. The field is additive: the schema
stays `cheme/viewer-snapshot/v1`.

The answers are produced by the same `create_app` as `cheme serve`, called in process, so a
snapshot never differs from what the server would have answered.
