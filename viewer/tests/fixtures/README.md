# Test fixtures

- `layout-shapes.json`: hand-made `/api/layout` payload with shapes and cases the demo lacks
  (spheres, rotated buildings, size objects, findings without flags).
- `layout-demo.json`: the real `/api/layout` response for example-dexpi-plant's `layout/`.
- `layout-demo-clash.json`: the same for a copy of the demo with an area `B-1` (kind `building`)
  added to `layout/site-plan.yaml` and P4711 moved to `[38, 34, 0]` (into building B-1, not
  placed in it).
- `layout-asu.json`: the real `/api/layout` of the ASU (the process library's `processes/asu-1`,
  P&IDs P-01..P-04) with its generated 3D model (`model`: equipment with parts, nozzles and
  envelopes; 214 routed pipes, each with its routing `reason` and `ends`, 147 of them pinned
  (each pinned rack run with its `racks` and `tier`); 110 in-line items, a component two segments share once with both
  segments in its refs; the 15 x 9 x 53 m cold box frame with its declared stairs, ladders and
  walls and the fire walls; 8 declared platforms, 28 zones, racks PR1-PR3 with
  `intermediate_supports` and, on PR2 / PR3, their own `bent_spacing_m`; the MAC house with its
  overhead crane and the substation building; tank stairs and column davits as solids; cable
  trays, tray tiers, junction boxes, cables and the cable schedule; air handling units,
  ventilated rooms and ducts; 4 unrouted segments and the routing summary with `reasons` and
  `battery_limits`), `zones`, `model_findings` and 15 `separations`. It is core's frozen
  `tests/data/api-layout-asu.json`, byte for byte (with pipe supports, step-overs, proposed
  rack ladders and the findings of the engineering rules; declared `operator`s on 26 in-line
  valves and 11 transmitter tappings, the casing hatch H1, the transformer fire wall FW-TR,
  every casing opening declared, so no penetration; 288 posts in `support_steel` (259
  declared, 29 proposed `<pipe>/SP-<arc>`) and 17 valve access platforms among the structures
  (8 declared `VP-1` .. `VP-9`, 9 proposed `VP-<valve tag>`); since the ASU's ninth layout
  review the E-4101 bundle-pull zone `Z-PULL-E4101` and the GOX-4002 S12 supports as T-posts
  from grade; since the eighth: the LOX / LIN tanks T-4101 /
  T-4102 on a 0.5 m `plinth` (a concrete solid under each, the spiral stair from grade), the
  intercooler package E-4101 as a 6 x 2.8 x 3.2 m box and K-1101 with a `lift_weight` among its
  `dimensions`).
- `layout-asu-penetration.json`: `model.penetrations` and the wall-penetration
  `model_findings` of `/api/layout` for a copy of the ASU without its declared casing opening
  AIR-2002 (the model rebuilt), merged into `layout-asu.json` by the tests that need a sleeve.
- `api/lifting-study-asu.csv`: the ASU's committed `layout/lifting-study.csv` (`cheme layout
  lifting --write`, for the same model) as `/api/file` serves it; `api/tree-asu.json`: the
  `layout/`, `electrical/` and `equipment/datasheets/` entries of the ASU's `/api/tree`;
  `api/cable-schedule-asu.csv`: the ASU's committed `electrical/cable-schedule.csv` (`cheme
  layout cables --write`, the 130 cables of the same model); `api/datasheets-asu.json`:
  `/api/yaml` of each of those 39 datasheets by path (`schema` left out, the same for every sheet;
  4 drafts, assumed, TBD, supplier and not-applicable values, process streams in `type_specific`).
  cheme serve has no lifting, cable schedule or datasheet endpoint: the layout and datasheet views read these files.
- `api/datasheets-index-asu.json`, `api/datasheet-details-asu.json`, `api/datasheet-drawings-asu.json`
  and `api/datasheets-snapshot-keys.json` (`scripts/regen-fixtures.py --asu-datasheets`, core
  with `GET /api/datasheets`, core#95): a copy of the ASU after `cheme datasheets fill
  --dimensions` and `cheme datasheets drawing --write`, then edited so every case shows:
  V-2101A with structured materials (`material_class`, `standard`), weights (empty, operating
  and a `supplier` test weight), a full nozzle schedule (mark, service, rating, facing, flange
  standard, projection) and an assumed manway M1 the P&ID does not draw (two warnings), drawn
  again (current); V-2101B with a longer tangent length after the drawing (stale); V-3101 with an
  outside diameter the equipment list and the model disagree with (three warnings, stale);
  T-4102's drawing deleted (missing, the generated preview); P-4102B's datasheet deleted (an item
  without one). Committed once in a fresh git repository. The index (`/api/datasheets`, 38 sheets),
  each sheet's `/api/datasheets/{tag}` by tag (without `source`), the `.svg` answers of V-2101A,
  V-2101B, T-4102, C-3101, E-3101 and P-1101A with their `X-Cheme-Drawing` headers (and
  V-2101B's `generated=true` one, the only one that differs), and the manifest keys `cheme
  export-static` writes for them (with type and status).
- `api/maturity-asu.json`: `cheme maturity --json` (`maturity_payload`, core cec7e81) of a git copy of the process library's `processes/asu-1`: no level reached (`sourced.boundary` fails), the engineering requirements passing, `process.yaml` claiming `basic-engineering` (`claim_exceeds_evidence`), 14 review records.
- `api/status-asu.json`: `/api/status` of the ASU (13 review records, 9 open findings, none
  blocking) in a fresh git repository: the plant committed on `main`, a commit on a branch
  `stage/basic`, and a `checks/status.json` with two made-up sign-offs (the ASU has none, its
  file is the 0.3 kind): `concept` of the `main` commit (human review) and `basic` of the branch
  commit (agent review, `on_default_branch` false); the working tree on that branch.
  `api/reviews-asu.json`: the text of each `reviews/*.md` (README.md too) as `/api/file` serves
  it. `tests/reviews.test.ts` checks that the viewer derives the same open findings from these
  records as core does.
- `api/simulation-asu.json`: `/api/simulation` of the ASU (its `process/simulation.yaml`: the
  warm end and the double column, the purification, main exchanger and expander excluded, nested
  column specs), committed once in a fresh git repository; the ASU records no run, so `run` is
  null and `stale` null.
- `api/simulation-run.json`, `api/simulation-stale.json`, `api/simulation-failed.json` and
  `api/streams-simulation.json`: core's `examples/process-simulation` (compressor K1, aftercooler
  E1, splitter X1) filled with `cheme process simulate --fill`'s code (`run(..., write=True)`)
  and core's stand-in solver (`tests/test_process_simulate.py` `fake`; DWSIM does not run):
  `/api/simulation` and `/api/streams` after the fill (the run current, 17 values filled), then
  with K1's efficiency changed to 0.7 (the run stale, `process/simulation.yaml` changed), and a
  fresh copy whose run did not converge (`E1: not calculated`, no stream values). `run_at` and
  `tool` are those of the regeneration.
- `api/reactions-bed-cooled.json`, `-inlet`, `-isothermal`, `-failed` (`scripts/regen-fixtures.py --only-beds`,
  viewer#32): `/api/reactions` of core's `examples/process-shift` with R1's bed replaced: cooled tubes
  (800 x 0.1 m, coolant 620 K, U 30 W/(m2 K); an interior hot spot of 648.15 K at the sampled point
  12800 kg) with FE_CR's window narrowed to 583.15-640 K; cooled harder (the inlet hottest);
  isothermal; cooled without a coolant (not solved: `missing` names why). `api/reactions-bed-sim.json`
  and `api/simulation-bed-run.json`, `-stale`, `-failed`: core's kinetic coupling test plant
  (`tests/test_process_simulate_kinetic.py`, an adiabatic ammonia bed without pressure drop) with its
  run recorded by `cheme process simulate --fill`'s code and that test's stand-in for DWSIM: current,
  stale after the catalyst mass changed, and a fresh copy whose outer loop does not settle.
- `api/reactions-ammonia.json` and `api/streams-ammonia.json`: `/api/reactions` and `/api/streams`
  of core's `examples/process-ammonia` (NH3_SYN, an equilibrium reaction in the loop's reactor
  R1, its catalyst `FE_NH3` of `process/catalysts.yaml`, no rate law; the block LOOP around it), committed once; `api/reactions-ammonia-unbalanced.json` with the
  stoichiometry changed to `NH3: 3` in the working tree (unbalanced, with the element-balance,
  heat-of-reaction and balance findings).
- `layout-mep.json` and `api/mto-mep.json`: `/api/layout` and `/api/mto` of a small plant the
  script makes from core's test data (`tests/data/layout_cabling.xml`): a vessel and a pump by a
  rack, a substation with an MCC and a control room, a hall with an air handling unit, so the
  model has trays, a tray tier, a junction box, the cable schedule, a ventilated room and ducts.
- `api/equipment-estimate-asu.json`: the ASU's `cheme assess equipment --json` (core's
  `EquipmentEstimate.payload()`, core origin/main 2026-10-23, the ASU at origin/main with its
  `estimate/cost-basis.yaml`, CEPCI 797.9 for 2023) with `rev: null`, as
  `/api/estimate/equipment` answers it: 39 items, 3 bare module, 22 purchased only, 14 not
  covered, 37 findings. Made with core's `equipment_estimate(root).payload()` until the endpoint is in cheme serve (then by
  `scripts/regen-fixtures.py`).
- `api/mto-asu.json`: `/api/mto` of the frozen ASU model with the template's example rates;
  `api/mto-asu.csv` and `api/estimate-asu.csv` what `cheme assess mto --csv` and
  `assess estimate --csv` print for it (the viewer's downloads must equal them).
- `api/control-separation.json`: `/api/control` of core's `examples/process-separation` (core#140: a narrative, a control philosophy, five loops of which PIC-104 is a deliberate draft, two sequences, the low-low level trip I-01), committed once in a fresh git repository, so every file is drafted (`scripts/regen-fixtures.py --only-control`).
- `api/issues-separation.json`, `api/issues-unavailable.json` and `api/repo-issues.json` (`scripts/regen-fixtures.py --only-issues`, core with `GET /api/issues`): the same example with `issues:` (repository, label `process:separation`, four forms) in `plant.yaml` and the stage set to `basic`, committed once in a fresh git repository, `chemeascode.integrations.github.list_issues` stubbed with nine GitHub API items (every type, gate, status and waiting state; #4 closed, #7 untyped, #8 with two gates, #9 with a mistyped `gate:Basic` that blocks every gate): its `/api/issues`, the 503 of core's GitHub reader without a token (status and body), and its `/api/repo` (`has_issues: true`).
- `api/interlocks-asu.json`: `/api/interlocks` of the ASU plant folder (its
  `control/cause-effect.yaml`: I-01 / I-02, the low-low level trips of the LOX and LIN product
  pumps), committed once in a fresh git repository (`--asu`).
- `api/lca-asu-readiness-main.json` and `api/lca-asu-readiness.json`: `/api/lca` of the ASU,
  core's `lca_report(root).payload()` with the findings and `rev: null`, as cheme serve answers
  it, for the LCI readiness (viewer#36). `lca-asu-readiness.json`: core main cec7e81 (with the
  balance gates of core#174 and the emission estimates of core#176 merged) on the process
  library's `processes/asu-1` at main 09dcab8. `lca-asu-readiness-main.json` stands for a core
  before core#174 (core main bead66e on `processes/asu-1` at b15be15: the data quality rating,
  the publication minimum, the disposal findings; no `balance`, no emission findings).
  `api/dataset-asu.yaml` is the ASU's committed `lca/dataset.yaml` at 09dcab8 as `/api/file`
  serves it, `api/yaml-dataset-asu.json` the same as `/api/yaml` (`kind` and `schema` null).
  `api/lca-asu.json` (no `data_quality`, `water` or `balance`) stands for an older core.
- `api/*.json`: real `/api/repo`, `tree`, `streams`, `yaml?path=process/flowsheet.yaml`,
  `validate` and `impact` responses for cheme-as-code's `examples/process-nested`, committed in a
  fresh git repository with a fixed author and date (a stable commit id) and then edited (the
  flowsheet's title changed, the sheets not rebuilt), so `validate` reports `cheme.generated-outdated`
  and `impact` reports `cheme.review-needed`. The end-to-end mocks (`e2e/fixtures.ts`) serve
  `validate.json` and `impact.json`.
- `api/diff-bfd.json`: `/api/diff` of that example's BFD against HEAD after the same edit and
  `cheme process build` (changes with their plant `item`, and `items`).

`tests/apiContract.test.ts` checks that every field in these responses is known to the types in
`src/api.ts`, so a new API field fails a test instead of being dropped silently.

## Regenerate

After a change to the API, regenerate all of them from the cheme-as-code checkout this viewer is in
(`..` here) and an example-dexpi-plant checkout. The script runs in that checkout's Python environment,
serves copies of the plants in a temporary directory with FastAPI's TestClient (no server, no port)
and never writes to either repository:

```sh
uv run --project .. --extra serve python scripts/regen-fixtures.py --demo ../../plantcode-demo
```

Without `--demo` the demo layout fixtures are left as they are. The example-dexpi-plant repository was
retired on 2026-10-24, so the `layout-demo*.json` fixtures are kept as they are; to regenerate them,
clone the archived bundle (`git clone example-dexpi-plant-2026-10-24.bundle plantcode-demo`) and
pass that checkout to `--demo`. `layout-asu.json` is copied from
the core checkout's `tests/data/api-layout-asu.json`, or served from the ASU plant folder, the
process library's `processes/asu-1` (formerly the example-asu repository), with
`--asu ../process-library/processes/asu-1` (it must hold a built `layout/plant-model.yaml`; a
process-library checkout works too, its `processes/asu-1` is used). With
`--asu-files ../process-library/processes/asu-1` (the one core's fixture was built from) the lifting study, the
ASU tree entries, the penetration case, the review status and the ASU's simulation are written too. The simulation
run and reaction fixtures always come from the core checkout's examples (they need core's `tests/`
for the stand-in solver: `--core` must be a source checkout, not an installed package). Then run `npm test` and review the
diff: a changed field usually needs a change in `src/api.ts` and the views that read it.
