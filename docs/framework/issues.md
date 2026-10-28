# Issues: actions, holds, queries and changes

A plant's open work is tracked as GitHub issues, the way an engineering project keeps an action
tracker, a hold list and a technical-query log. `plant.yaml` says where:

```yaml
issues:
  repository: ChemE-as-Code/process-library
  label: "process:asu-1"
  forms: {action: 1-action-item.yml, hold: 2-engineering-hold.yml,
          tq: 3-technical-query.yml, change: 4-design-change.yml}
```

`cheme issues` lists them by the gate they must be closed before. `GET /api/issues` serves the
same data to the viewer, and the gates of kind `issues` (checks.yaml) fail while one is open for
the stage. Code: `project/issues.py`, `integrations/github.py`.

## The labels

The labels are the contract between the issue forms, core, the viewer and the Process Atlas.

| label | meaning |
|---|---|
| `type:action` | an **action item** from a review, a HAZOP or a design meeting |
| `type:hold` | an **engineering hold**: a value or decision the design does not have yet (vendor data, a client decision), with what is assumed meanwhile |
| `type:tq` | a **technical query** to another discipline, a vendor or the client, with a proposed answer |
| `type:change` | a **design change** (management of change): what changes, the documents affected, the re-reviews needed |
| `gate:concept`, `gate:basic`, `gate:detail` | the stage gate it must be **closed before**. An item still open for an earlier stage blocks the later gates too |
| `discipline:<d>` | process, control, piping, mechanical, electrical, layout, safety, civil |
| `source:<s>` | design-review, hazop, layout-review, control-review, vendor, client, internal |
| `status:in-progress`, `status:for-verification` | being worked on; done and waiting for **verification** by the originator or reviewer. An open issue without either is *open*; a closed one is *closed*, i.e. verified |
| `waiting:input`, `waiting:work` | on hold for vendor, client or HAZOP / LOPA input; for another issue or branch |
| `process:<id>` | the plant (one repository may hold several) |

An issue is closed only once its close-out evidence (files changed, a review record, a
decision) is verified, as an action tracker's close-out.

## The gate

```yaml
- id: issues-basic
  title: No open item to close before the basic engineering gate
  stage: basic
  kind: issues
  types: []          # all types; e.g. [action, hold]
```

It fails while an issue of the plant with `gate:basic` (or `gate:concept`) is open. It is n/a
when `plant.yaml` declares no `issues:`. It reads GitHub live, with `GITHUB_TOKEN`, `GH_TOKEN`
or the GitHub CLI's login. Without one, or without network, it **fails as "not evaluated"**: a
stage is never signed off on items nobody could see.

A label never lets a gate slip: an issue with two `gate:` labels (one left over from an edit)
counts at the earlier gate, and a `gate:` that is no stage of the plant (`gate:Basic`) blocks
every gate until it is corrected. The issues are read once per run and kept for two minutes, a
failure too, so `cheme check` and the server ask GitHub once, not once per gate.

The token is only ever sent to `api.github.com`, and redirects are not followed: the endpoint
is not configurable in `plant.yaml`, so a plant someone else wrote cannot send your token to
another host. `web:` (default `https://github.com`) sets the base of the links only.

## New issues

`GET /api/issues` returns `new`: a link per type that opens the repository's issue form with
the plant's label and the form's `process` field filled in. The viewer adds the sheet or tag it
is showing to the form's `refs` field. Without `forms:` the link opens the template chooser.

## Not modelled

Due dates, owners as persons, priorities beyond the gate, and notifications stay with GitHub.
cheme-as-code only reads issues, never writes them.
