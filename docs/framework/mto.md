# Material take-off and estimate

`cheme assess mto` counts the bulk materials of the committed 3D model
(`layout/plant-model.yaml`, [layout-model.md](layout-model.md)); `cheme assess estimate`
prices them with the project's unit rates (`estimate/rates.yaml`, kind `rates`) by the factor
method. `GET /api/mto` serves both for a revision. Code: `domains/assessment/mto.py`,
`estimate.py`, `schemas.py`, `gates.py`, package data `domains/assessment/data/steel-sections.yaml`;
skill `mto-estimate`; tests `tests/test_assessment_mto.py` (counts against a small model counted
by hand).

The take-off reads the model as a file (the documented contract), so `assessment` imports no
`spatial` code. It is deterministic: the same model gives the same rows in the same order.
**cheme-as-code holds no prices**: every rate and factor comes from the plant repository, each with
`status` (`ASSUMED` or `QUOTED`), `source` and `year`. The file `cheme init` writes is an
example (`example: true`, currency `XXX`) and prices nothing.

## Take-off rows

One row per category, item, DN (and second DN), pipe class, spec and group, summed:

| category | unit | item | counted from the model |
|---|---|---|---|
| `pipe` | m | `pipe` | each `pipes[]` polyline's length, by `dn`, `class.code` and insulation (`spec`: `bare` or `insulation <mm> mm <jacket>`); `count`: pipes |
| `elbow` | ea | `elbow 90`, `elbow 45`, `bend <deg>` | every change of direction above 1 degree inside a pipe's polyline, and where two pipe ends meet at an angle (at the larger DN) |
| `tee` | ea | `tee`, `reducing tee` | a pipe end on another pipe's run (run: that pipe; `dn` the larger, `dn2` the smaller DN); three pipe ends at one point (run: the two largest); *n* > 3 ends: *n* - 2 tees |
| `reducer` | ea | `reducer` | two pipe ends of different DN at one point (`dn` x `dn2`); a placed `inline` reducer elsewhere (`dn` of its pipe) |
| `flange` | ea | `weld neck flange` | one pipe flange per `flange-<k>` and `outlet-flange` part of an `inline` item (two for a valve, check valve or safety valve without parts; the outlet flange at the DN of the item's other segment), and one per nozzle whose `point` is a pipe's end |
| `gasket` | ea | `gasket and bolt set` | one per flange (one per flanged joint) |
| `valve` | ea | the DEXPI class (`BallValve`, ...) | `inline` items of kind `valve`, `check_valve`, `safety_valve`, at their pipe's DN and class |
| `inline` | ea | the DEXPI class | the other `inline` items (silencers, filters, instruments) |
| `steel` | t | the section (`HEB300`, ...) | every `member` part: length x mass per metre (`steel-sections.yaml`); `spec`: the part's `material` (`steel`, `handrail`, `crane` for the runways), `length_m`: total length, `count`: members; the overhead crane itself (bridge, end carriages, crab) is a machine and not counted |
| `grating` | m2 | `grating` | plan area of `grating` parts (`box`: dx x dy; `annulus`: ring area over its arc) |
| `insulation` | m2 | `pipe insulation`, `equipment insulation` | outer surface of insulated pipes, pi (OD + 2 t) L; side surface of `insulation` cylinders |
| `concrete` | m3 | the part's name without numbers and sides (`plinth`, `foundation`, `ring-wall`, `saddle-pad`; `bund wall` in a bund area) | volume of `concrete` parts (`box`, `cylinder`, `annulus`) |

`group` says where a part is: `rack`, `structure`, `building`, `platform`, `step-over`,
`equipment`, `support`, `support-steel` (declared posts and T-posts under pipes), `area`, and
`stair` or `ladder` for the parts of a structure's, rack's or platform's stairs and ladders.
Proposed valve access platforms and proposed support steel (whole objects of `source:
generated`) are left out until they are pinned. Points closer than 2 mm are one point.

Not counted (the model does not draw them): unrouted lines, field-run small bore, vents and
drains not on the P&ID, olets and couplings, flanges at spool breaks, steel without a section
(shoes, guides, chairs, base plates, connections, tank and platform handrails drawn as rings or
cylinders), equipment insulation beyond the drawn cylinders, paving, piles, sumps. The estimate
carries them as factors or explicit rates.

Section masses (`steel-sections.yaml`): HEB, HEA, IPE, UPN (also written `C200`) and equal
angles at the EN 10365 nominal masses; RHS and flat bars named without a wall thickness at the
values given there (ASSUMED). A name is compared without blanks and in upper case. A member of
another section is left out and reported (`cheme.mto-section-unknown`, warning).

`estimate/mto.csv` columns: `category, item, dn, dn2, class, spec, group, count, quantity, unit,
length_m` (numbers to 3 decimals, empty when not applicable). `estimate/mto.md`: the totals,
one table per category, the findings, and the model's `provenance.output_sha256`.

## `estimate/rates.yaml` (kind `rates`)

```yaml
currency: EUR            # ISO 4217; XXX: no currency (the template's example)
cost_year: 2026
example: false           # true: example numbers, the estimate warns, gate `rates` fails
basis: "Class 4 estimate of the bulk materials, basic engineering"
rates:                   # the FIRST rate of a row's category whose where: matches prices it
  - {id: pipe-cs-small, category: pipe, unit: m, rate: ..., where: {dn_max: 50, class: "PN16"},
     status: QUOTED, source: "<supplier> quotation <ref>", year: 2026}
factors:
  - {id: piping-erection, kind: direct, factor: ..., applies_to: [pipe, elbow, flange, valve],
     status: ASSUMED, source: "<estimating handbook, edition>", year: 2025}
  - {id: engineering, kind: indirect, factor: ..., status: ASSUMED, source: ..., year: 2026}
  - {id: contingency, kind: contingency, factor: ..., status: ASSUMED, source: ..., year: 2026}
```

A rate's `unit` must be its category's (above). `where:` filters, all optional: `item` (glob),
`dn_min`, `dn_max`, `class` (glob on the pipe class), `spec` (glob), `group` (glob).
`cheme schema rates` prints the JSON Schema; `cheme validate` checks the file.

## The estimate

1. **materials**: each row x its rate (rounded to 0.01); a row without a rate stays unpriced;
2. **direct**: each `kind: direct` factor x the material cost of its `applies_to` categories
   (all materials when empty); direct cost = materials + direct factors;
3. **indirect**: each `kind: indirect` factor x the direct cost;
4. **contingency**: each `kind: contingency` factor x (direct + indirect).

Total = direct + indirect + contingency. Findings (file `estimate/rates.yaml`):
`cheme.estimate-example-rates` (warning), `cheme.estimate-unpriced` (warning, rows
without a rate), `cheme.estimate-rate-year` (info: rates and factors of another year than
`cost_year`, used without escalation), `cheme.estimate-rate-unused` (info: a rate no row
uses, usually shadowed by an earlier one), `cheme.estimate-no-rates` (error: no or an
invalid file).

`estimate/estimate.csv` columns: `section` (`material`, `direct`, `indirect`, `contingency`),
`id` (the take-off row's key, e.g. `pipe DN100 PN16 bare`, or the factor's id),
`description`, `quantity` (a factor's base cost), `unit`, `rate` (or the factor), `basis` (the
rate's or factor's id), `cost`, `status`, `source`, `year`.

## Commands

| command | does |
|---|---|
| `cheme assess mto [--csv \| --json] [--write \| --check]` | the take-off (Markdown by default); findings on stderr; exit 1 without a model |
| `cheme assess estimate [--csv \| --json] [--write \| --check]` | the estimate (Markdown by default); exit 1 without a model or valid rates |

`--write` writes `estimate/mto.csv` and `estimate/mto.md` (`estimate/estimate.csv` and `.md`);
`--check` writes nothing and exits 1 when they are not what the current files give. `--json`
is the payload below plus `source` (git commit, dirty inputs, fingerprints of the model and the
rates).

Python: `mto_report(root) -> MtoReport` (`rows`, `findings`, `takeoff`, `source`, `payload()`)
and `take_off(model_document) -> TakeOff`; `estimate_report(root) -> EstimateReport` and
`estimate(takeoff, RateFile) -> Estimate` (`lines`, `totals()`, `findings`).

## The gate `kind: mto`

`require` takes any of:

- `mto-current`: `estimate/mto.csv` is the take-off of the current `layout/plant-model.yaml`
  (byte for byte);
- `rates`: `estimate/rates.yaml` loads, is not an example, and prices every take-off row;
- `estimate-current`: `estimate/estimate.csv` is the estimate of the current model and rates.

The template's gate `mto` (stage basic) requires `mto-current`; a project adds `rates` and
`estimate-current` once it prices its plant. The gate does not judge the quantities or the
rates: that is the estimate review's (skill `mto-estimate`).

## `GET /api/mto?rev=`

The take-off of the committed model at `rev` (default: the working tree), read-only:

```json
{
  "rev": "<commit or null>",
  "model": "layout/plant-model.yaml",
  "model_sha256": "<the model's provenance.output_sha256>",
  "columns": ["category", "item", "dn", "dn2", "class", "spec", "group", "count", "quantity",
              "unit", "length_m"],
  "rows": [{"category": "pipe", "item": "pipe", "dn": 100.0, "dn2": null, "class": "PN16",
            "spec": "bare", "group": "", "count": 2, "quantity": 10.0, "unit": "m",
            "length_m": null, "key": "pipe DN100 PN16 bare"}],
  "totals": {"pipe": {"m": 812.4}, "steel": {"t": 299.5}},
  "findings": [{"file": "...", "level": "warning", "rule": "cheme.mto-section-unknown",
                "message": "...", "ids": ["XYZ1"], "hint": "..."}],
  "estimate": null
}
```

`estimate` is `null` without `estimate/rates.yaml` at that revision, else `{currency,
cost_year, example, model_sha256, totals: {materials, direct, indirect, contingency, total,
unpriced_rows}, lines: [{section, id, description, quantity, unit, rate, basis, cost, status,
source, year}], findings}` (`totals` empty and the error in `findings` when the rates do not
load). 404 without a model at that revision, 422 for a model that is not a YAML mapping.

## The equipment estimate (`cheme assess equipment`)

`domains/assessment/equipment_cost.py` costs every item of the equipment list from the
published purchased and bare module cost correlations of R. Turton, J. A. Shaeiwitz,
D. Bhattacharyya, W. B. Whiting, *Analysis, Synthesis, and Design of Chemical Processes*, 5th
ed., 2018, Appendix A (CAPCOST). The package data `domains/assessment/data/turton-capcost.yaml`
holds the rows used, each with its table (A.1 to A.4, Figure A.19) and the second
transcription it was cross-checked against; factors whose transcriptions disagree are left out
on purpose, so the project supplies them with their source or the item stays partly costed.

| step | how |
|---|---|
| correlation | from the DEXPI class (pump: centrifugal, reciprocating, positive displacement; compressor; fan; expander or turbine; exchanger: fixed tube sheet unless U-tube, floating head, kettle, double pipe, plate, spiral or air cooled; column: tower shell; tank: fixed or floating roof; vessel: vertical, horizontal with a length and no height), or `correlation` of the cost basis |
| size A | the cost basis's `size` (with `size_source`), else the datasheet (`type_specific`, `operating`, `design`: `volume_m3`, `area_m2`/`heat_transfer_area_m2`, `shaft_power_kw`/`power_kw`, `fluid_power_kw`, `gas_flow_m3_s`/`flow_m3_s`, `duty_kw`; the size source carries the value's `source`, `ASSUMED` when the datasheet marks it `assumed: true`, and `draft` for a draft datasheet, listed in the info finding `estimate-draft-size`), else a volume from the list's `dimensions` (pi/4 D^2 H, overall: an upper bound, ASSUMED) |
| purchased | log10 Cp0 = K1 + K2 log10 A + K3 (log10 A)^2, USD at CEPCI 397 (2001); outside A's range: `estimate-equipment-range`, not extrapolated |
| pressure factor | vessels and towers: ((P+1) D / (2 (850 - 0.6 (P+1))) + 0.00315) / 0.0063, at least 1; others log10 Fp = C1 + C2 log10 P + C3 (log10 P)^2 over the row's range, 1 below it; P = `design_pressure_barg` |
| material factor | `CS` or `SS` read from the list's `material` (only one of them, no other metal); else the cost basis's `fm` |
| bare module | CBM = Cp0 (B1 + B2 Fm Fp), or Cp0 FBM (compressors: the centrifugal FBM only; a class naming axial or reciprocating gets its purchased cost only, a class naming no kind the centrifugal FBM marked ASSUMED); a missing factor: `estimate-equipment-partial` (purchased cost only) unless the cost basis gives `fm`, `fp` or `fbm` with `factor_source` |
| escalation | x `cost_index.value` / 397 (the project's CEPCI with year and source); none: `estimate-no-index`, costs stay in 2001 dollars |

`estimate/cost-basis.yaml` (kind `cost_basis`, `cheme schema cost_basis`):

```yaml
cost_index: {value: <CEPCI>, year: <year>, source: "<where it is published>"}
estimate_class: 5        # AACE 18R-97
items:
  - {tag: E-101, size: 120, size_source: "DESIGN.md D-012, thermal rating"}
  - {tag: C-101, fm: 1.7, factor_source: "<book, table, page>"}
  - {tag: X-101, cost: 250000, currency: EUR, year: 2026, status: QUOTED, source: "<quotation>"}
  - {tag: F-101, exclude: "inside the package unit X-101"}
```

`estimate/equipment-cost.csv` columns: `tag, type, correlation, size, unit, size_source,
cp0_base, fp, fm, fbm, cbm_base, index_ratio, purchased, bare_module, status, notes` (status
`bare module`, `purchased only`, `project cost`, `excluded: <reason>`, `not covered`).
`estimate/equipment-cost.md` states the class and its expected accuracy range from AACE
International Recommended Practice 18R-97 (class 5: -20 % to -50 % low, +30 % to +100 % high;
class 4: -15 % to -30 %, +20 % to +50 %), the source, the escalation and the items covered.
The bare module cost includes each item's installation materials and labour and its indirect
costs, so the bulk factor estimate above is not added on top for the same scope. Python:
`equipment_estimate(root) -> EquipmentEstimate` (`lines`, `totals()`, `uncovered()`,
`findings`, `payload()`), `estimate_equipment(equipment, datasheets, basis)`.

The gate `kind: mto` takes `equipment-current` (the written CSV is current) and
`equipment-covered` (every item has a bare module cost, its own cost, or is excluded with a
reason, and a cost index is given).

## `GET /api/estimate/equipment?rev=`

The equipment estimate at `rev` (default: the working tree), read-only: `cheme assess
equipment --json` of the equipment list, `estimate/cost-basis.yaml` and the datasheets at that
revision, with `rev` (the commit, null for the working tree) in front (abridged, from the
ASU example plant):

```json
{
  "rev": "<commit or null>",
  "currency": "USD",
  "base": {"cepci": 397.0, "year": 2001},
  "index": {"value": 797.9, "year": 2023, "month": "annual", "source": "..."},
  "estimate_class": 5,
  "accuracy": {"low": "-20 % to -50 %", "high": "+30 % to +100 %"},
  "totals": {"purchased": 4002556.0, "bare_module": 2099909.0, "items": 39,
             "bare_module_items": 3, "purchased_only": 22, "own_cost": 0, "excluded": 0,
             "not_covered": 14},
  "lines": [{"tag": "C-1102", "type": "ProcessColumn", "correlation": "tower",
             "size": 349.895, "unit": "m3", "size_source": "datasheet type_specific.volume_m3 ...",
             "cp0_base": 215480.5, "fp": 1.3415, "fm": 1.0, "fbm": 4.6916,
             "cbm_base": 1010942.7, "index_ratio": 2.0098, "purchased": 433077.8,
             "bare_module": 2031816.6, "status": "bare module",
             "notes": "tower shell (internals not included); Fm CS"}],
  "own_costs": [{"tag": "...", "cost": 250000, "currency": "EUR", "year": 2026,
                 "status": "QUOTED", "source": "..."}],
  "findings": [{"file": "estimate/cost-basis.yaml", "level": "warning",
                "rule": "cheme.estimate-equipment-uncovered", "message": "F-1101 (GasFilter): ...",
                "line": null, "ids": ["F-1101"], "hint": "...", "key": "F-1101", "box": null,
                "crop": null, "accepted": null, "measured": null}],
  "source": {"commit": "<sha>", "dirty": [], "fingerprints": {"equipment/equipment-list.yaml":
             "sha256:..."}}
}
```

`index` is null without a `cost_index`; `source` names the inputs as served (at a revision
nothing is dirty). 404 without `equipment/equipment-list.yaml` or when it lists no items
(nothing to estimate), 422 for a list that does not load; a cost basis that does not load is
the first finding. `GET /api/repo` says `has_equipment_estimate` (the list lists items).
