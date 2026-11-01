"""Regenerate the viewer's API fixtures from the real responses of a cheme-as-code (core) checkout.

Run it with the Python environment of that checkout (the `serve` extra brings FastAPI); the
viewer is `viewer/` of that checkout, so from here:

    uv run --project .. --extra serve python scripts/regen-fixtures.py --demo ../../plantcode-demo

It never writes to the plant repositories: each one is copied into a temporary directory and
served from there with FastAPI's TestClient (no port, no background server).

- `tests/fixtures/layout-demo.json`: `/api/layout` of example-dexpi-plant's `layout/` (that
  repository was retired on 2026-10-24; `--demo` takes a checkout cloned from its archived bundle).
- `tests/fixtures/layout-demo-clash.json`: the same for a copy with an area `B-1` (kind
  `building`) added to `layout/site-plan.yaml` and P4711 moved to `[38, 34, 0]` (into building
  B-1, not placed in it).
The ASU is the process library's `processes/asu-1` (formerly the example-asu repository): `--asu`
and `--asu-files` take that plant folder, or a process-library checkout (its `processes/asu-1`
is used).

- `tests/fixtures/layout-asu.json`: `/api/layout` of the ASU with its generated model
  (`layout/plant-model.yaml`), copied from the core checkout's frozen
  `tests/data/api-layout-asu.json`; with `--asu`, served from that ASU plant folder instead.
- With `--asu-files <ASU plant folder>` (the one the frozen ASU model was built from):
  `tests/fixtures/api/lifting-study-asu.csv`, `/api/file` of its `layout/lifting-study.csv`
  (`cheme layout lifting --write`); `tests/fixtures/api/cable-schedule-asu.csv`, its
  `electrical/cable-schedule.csv` (`cheme layout cables --write`);
  `tests/fixtures/api/tree-asu.json`, the `layout/`, `electrical/` and
  `equipment/datasheets/` entries of its `/api/tree`; `tests/fixtures/api/datasheets-asu.json`,
  `/api/yaml` of each datasheet by path (without the schema); and `tests/fixtures/layout-asu-penetration.json`,
  the `model.penetrations` and the wall-penetration `model_findings` of `/api/layout` for a copy
  with the declared casing opening AIR-2002 left out of `layout/structures.yaml` and the model
  rebuilt (the ASU declares all its casing openings, so its own model has no sleeve).
- With `--asu-datasheets <ASU plant folder>` (core with `GET /api/datasheets`; `--only-datasheets`
  writes nothing else): `tests/fixtures/api/datasheets-index-asu.json`, `/api/datasheets` of a
  copy after `cheme datasheets fill --dimensions` and `cheme datasheets drawing --write`, edited
  so every case shows (see `datasheet_fixtures`); `datasheet-details-asu.json`,
  `/api/datasheets/{tag}` of each sheet by tag (without `source`); `datasheet-drawings-asu.json`,
  `/api/datasheets/{tag}.svg` without and with `generated=true` (`<TAG>.svg`, `<TAG>.generated.svg`,
  the latter only where it differs) for `DRAWING_TAGS`, with the `X-Cheme-Drawing` headers; and
  `datasheets-snapshot-keys.json`, the manifest keys `cheme export-static` writes for them.
- `tests/fixtures/layout-mep.json` and `tests/fixtures/api/mto-mep.json`: `/api/layout` and
  `/api/mto` of a small plant made here from core's test data (`tests/data/layout_cabling.xml`):
  a vessel and a pump by a rack, a substation (an MCC and a control room) and a ventilated hall
  with an air handling unit, so the model has trays, junction boxes, cables and ducts; with the
  template's example rates.
- `tests/fixtures/api/mto-asu.json`: `/api/mto` of the frozen ASU model (above) with the
  template's example rates (`estimate/rates.yaml`, `example: true`); `mto-asu.csv` and
  `estimate-asu.csv` what `cheme assess mto --csv` and `assess estimate --csv` print for it
  (the viewer's CSV downloads must be the same files).
- `tests/fixtures/api/lca-asu.json`: `/api/lca` of the ASU plant folder (`--asu`: its
  `lca/` with construction and a scenario, example factors), committed once in a fresh git
  repository; `lca-asu.csv` what `cheme assess lca --csv` prints for it.
- `tests/fixtures/api/control-separation.json`: `/api/control` of core's
  `examples/process-separation`, committed once in a fresh git repository
  (`--only-control` writes only it).
- `tests/fixtures/api/issues-separation.json`: `/api/issues` of the same example with
  `issues: {repository: ChemE-as-Code/process-library, label: "process:separation", forms}` in
  `plant.yaml` and the stage set to `basic`, `chemeascode.integrations.github.list_issues`
  monkeypatched to return `ISSUE_ITEMS` (GitHub API answers as core's `tests/test_issues.py`
  writes them: every type, gate, status and waiting state, one closed, one untyped, one with
  two gates, one with a mistyped gate `Basic`); and
  `issues-unavailable.json`, the 503 (status and body) of core's GitHub reader without a
  token; `repo-issues.json`, its `/api/repo` (`has_issues: true`). Core with `GET /api/issues`. `--only-issues` writes only these.
- `tests/fixtures/api/tea-asu.json`: `/api/tea` of the ASU plant folder (`--asu`: its
  `estimate/tea.yaml`, an LCOP decision with scenarios and a Monte Carlo), committed once in a
  fresh git repository. `tea-blocks.json`: `/api/tea` of core's `examples/process-blocks` (one
  feed, steam, a product and waste water) with `BLOCKS_TEA` (modelled on core's
  `tests/test_assessment_tea.py` `premises()`: EUR, a cash cost decision, `example: true`,
  labour, tax, a ramp-up, a chemical, a catalyst replacement, a priced emission, working capital
  in days, scenarios and a Monte Carlo), so the page is not ASU-shaped. `--only-tea` (with
  `--asu`) writes only these two.
- `tests/fixtures/api/interlocks-asu.json`: `/api/interlocks` of the ASU plant folder (`--asu`:
  its `control/cause-effect.yaml`), committed once in a fresh git repository.
- `tests/fixtures/api/simulation-asu.json`: `/api/simulation` of the ASU plant folder
  (`--asu-files`: its `process/simulation.yaml`, the warm end and the double column with the
  purification, main exchanger and expander excluded), committed once in a fresh git repository;
  it has no run record (`process/simulation-run.json`), so `run` is null.
- `tests/fixtures/api/simulation-run.json`, `simulation-stale.json`, `simulation-failed.json` and
  `streams-simulation.json`: core's `examples/process-simulation` (compressor, aftercooler,
  splitter) committed in a fresh git repository and filled with `cheme process simulate --fill`'s
  code driven by core's stand-in solver (`tests/test_process_simulate.py` `fake`: DWSIM does not
  run): `/api/simulation` and `/api/streams` after the fill (the run record current), then
  `/api/simulation` with K1's efficiency changed (the record stale), and of a fresh copy whose
  run did not converge (no stream values written).
- `tests/fixtures/api/reactions-ammonia.json` and `streams-ammonia.json`: `/api/reactions` and
  `/api/streams` of core's `examples/process-ammonia` (one equilibrium reaction in the loop's
  reactor R1), committed once in a fresh git repository; `reactions-ammonia-unbalanced.json` the
  same with the stoichiometry edited to `NH3: 3` in the working tree (element balance and its
  finding).
- `tests/fixtures/api/reactions-shift.json`: `/api/reactions` of core's `examples/process-shift`
  (the water-gas shift with a power-law rate on the Fe-Cr catalyst of `process/catalysts.yaml`,
  in the fixed bed R1, `reactor: pfr`), committed once in a fresh git repository: the rate law
  with `rate_law` (expression, units, k(T)), `kinetics` (the catalyst, its reactions and units,
  its findings) and the solved bed of R1 (`reactors[].bed` with its profile).
- `tests/fixtures/api/reactions-coox.json`: `/api/reactions` of core's CO oxidation test plant
  (`tests/test_serve_catalysis.py`): reaction COOX with a three-step mechanism and its
  `microkinetics` at the outlet S2 of reactor R (coverages, TOF, degree of rate control,
  orders), and UNUSED, a mechanism no block runs (`missing`).
- `tests/fixtures/api/kinetics-shift.json`: `/api/kinetics` of `examples/process-shift` with
  `experiments/kinetics/wgs.yaml` (12 rates of the example's own law and their default fit
  over 1 - Q/K) and `broken.yaml` (does not validate: `problem`); `library-shift.json`,
  `/api/library` of the same plant (23 entries; the shift's components, WGS and FE_CR
  `in_plant`). `--only-reactions` writes only the reactions fixtures and these.
- `tests/fixtures/api/*.json`: `/api/repo`, `tree`, `streams`, `yaml` (the flowsheet),
  `validate` and `impact` of cheme-as-code's `examples/process-nested`, committed once in a fresh git
  repository (fixed author and dates, so the commit id is stable) and then edited (the
  flowsheet's title changed, the sheets not rebuilt), so `validate` and `impact` have findings to show; and
  `diff-bfd.json`, `/api/diff` of the BFD against HEAD after `cheme process build`.
"""

from __future__ import annotations

import argparse
import json
import os
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

import chemeascode
from fastapi.testclient import TestClient
from chemeascode.interfaces.api.serve import create_app

VIEWER = Path(__file__).resolve().parents[1]
FIXTURES = VIEWER / "tests" / "fixtures"
GIT_ENV = {
    "GIT_AUTHOR_NAME": "Fixture",
    "GIT_AUTHOR_EMAIL": "fixture@example.com",
    "GIT_COMMITTER_NAME": "Fixture",
    "GIT_COMMITTER_EMAIL": "fixture@example.com",
    "GIT_AUTHOR_DATE": "2026-01-01T00:00:00+00:00",
    "GIT_COMMITTER_DATE": "2026-01-01T00:00:00+00:00",
}


#: The time a recorded run says it ran: fixed, so the fixtures do not change with every run of this
#: script (the viewer only shows it).
RUN_AT = "2026-10-28T12:00:00Z"


def write(path: Path, data: object) -> None:
    if isinstance(data, dict) and isinstance(data.get("run"), dict) and "run_at" in data["run"]:
        data = {**data, "run": {**data["run"], "run_at": RUN_AT}}
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, indent=2, ensure_ascii=False) + "\n", encoding="utf-8", newline="\n")
    print(f"wrote {path.relative_to(VIEWER)}")


def client_for(root: Path) -> TestClient:
    return TestClient(create_app(root, None, allowed_hosts=["testserver"]))


def get(client: TestClient, url: str) -> object:
    response = client.get(url)
    if response.status_code != 200:
        raise SystemExit(f"{url}: {response.status_code} {response.text}")
    return response.json()


def copy_plant(source: Path, target: Path, keep_git: bool = False) -> Path:
    """Copy a plant repository; its git history only with *keep_git* (a temporary copy)."""
    skipped = ["build", "node_modules", ".venv"] + ([] if keep_git else [".git"])
    shutil.copytree(source, target, ignore=shutil.ignore_patterns(*skipped))
    return target


def asu_plant(path: Path) -> Path:
    """The ASU plant folder: *path* itself, or `processes/asu-1` of a process-library checkout."""
    path = path.resolve()
    nested = path / "processes" / "asu-1"
    if not (path / "plant.yaml").is_file() and (nested / "plant.yaml").is_file():
        path = nested
    if not (path / "plant.yaml").is_file():
        raise SystemExit(f"{path}: no plant.yaml; pass the ASU plant folder (process-library processes/asu-1)")
    return path


def replace_once(path: Path, old: str, new: str) -> None:
    text = path.read_text(encoding="utf-8")
    if text.count(old) != 1:
        raise SystemExit(f"{path}: expected one {old!r}; the plant changed, update this script")
    path.write_text(text.replace(old, new), encoding="utf-8")


def layout_fixtures(demo: Path, tmp: Path) -> None:
    plain = copy_plant(demo, tmp / "demo")
    write(FIXTURES / "layout-demo.json", get(client_for(plain), "/api/layout"))

    clash = copy_plant(demo, tmp / "demo-clash")
    site_plan = clash / "layout" / "site-plan.yaml"
    a310 = "  - {id: A-310, title: Tank bund T4750, box: [49, 18, 56, 30], kind: storage}\n"
    b1 = "  - {id: B-1, title: Process building plot, box: [26, 26, 40, 36], kind: building}\n"
    replace_once(site_plan, a310, a310 + b1)
    placement = clash / "layout" / "equipment-placement.yaml"
    replace_once(placement, "    position: [16, 24.5, 0]\n", "    position: [38, 34, 0]\n")
    write(FIXTURES / "layout-demo-clash.json", get(client_for(clash), "/api/layout"))


def asu_fixture(core: Path, asu: Path | None, tmp: Path) -> None:
    target = FIXTURES / "layout-asu.json"
    if asu:
        root = copy_plant(asu, tmp / "asu")
        write(target, get(client_for(root), "/api/layout"))
        return
    frozen = core / "tests" / "data" / "api-layout-asu.json"
    if not frozen.is_file():
        print(f"no {frozen}: {target.relative_to(VIEWER)} left as it is")
        return
    write(target, json.loads(frozen.read_text(encoding="utf-8")))


def asu_datasheets(client: TestClient, tree: list[dict]) -> None:
    """`/api/yaml` of each of the ASU's `equipment/datasheets/<TAG>.yaml`, by path (the datasheets
    view reads them; the schema of the answer is left out, it is the same for every sheet)."""
    out = {}
    for entry in tree:
        path = entry["path"]
        if entry["type"] == "file" and path.startswith("equipment/datasheets/") and path.endswith(".yaml"):
            doc = get(client, f"/api/yaml?path={path}")
            out[path] = {"data": doc["data"], "kind": doc["kind"], "schema": None}
    write(FIXTURES / "api" / "datasheets-asu.json", out)


def asu_files(asu: Path, tmp: Path) -> None:
    """The ASU's lifting study and cable schedule, its datasheet, layout and electrical file
    entries, and a penetration case."""
    root = copy_plant(asu, tmp / "asu-files")
    client = client_for(root)
    for study, name in (("layout/lifting-study.csv", "lifting-study-asu.csv"), ("electrical/cable-schedule.csv", "cable-schedule-asu.csv")):
        response = client.get(f"/api/file?path={study}")
        if response.status_code != 200:
            raise SystemExit(f"{study}: {response.status_code} {response.text}")
        path = FIXTURES / "api" / name
        path.write_text(response.text, encoding="utf-8")
        print(f"wrote {path.relative_to(VIEWER)}")
    tree = get(client, "/api/tree")
    keep = ("layout/", "electrical/", "equipment/datasheets/")
    dirs = ("layout", "electrical", "equipment", "equipment/datasheets")
    write(FIXTURES / "api" / "tree-asu.json", [e for e in tree if e["path"].startswith(keep) or e["path"] in dirs])
    asu_datasheets(client, tree)

    opened = copy_plant(asu, tmp / "asu-penetration")
    replace_once(
        opened / "layout" / "structures.yaml",
        # sill 7.95 m since asu-1 D-046 (the AIR-2002 sleeve raised with its pinned route)
        "        - {id: AIR-2002, side: north, offset: 7.75, width: 0.65, height: 0.65, sill: 7.95, kind: opening}\n",
        "",
    )
    # exit 1: the model is written, with error findings (a pinned branch off its tee)
    built = subprocess.run([sys.executable, "-m", "chemeascode", "layout", "build", "--force"], cwd=opened, capture_output=True)
    if built.returncode not in (0, 1):
        raise SystemExit(built.stderr.decode() or built.stdout.decode())
    data = get(client_for(opened), "/api/layout")
    findings = [f for f in data["model_findings"] if f["rule"] == "cheme.layout-wall-penetration"]
    if not data["model"].get("penetrations") or not findings:
        raise SystemExit("the ASU copy without AIR-2002 has no penetration: update this script")
    write(FIXTURES / "layout-asu-penetration.json", {"model": {"penetrations": data["model"]["penetrations"]}, "model_findings": findings})


# The small plant of mep_fixtures: core's cabling and HVAC test plant in one (tests/test_electrical_
# trays.py and tests/test_hvac_ducts.py of cheme-as-code).
MEP_FILES = {
    "equipment/equipment-list.yaml": """\
equipment:
  - {tag: V-101, type: PressureVessel, sheet: P-01, dimensions: {diameter: 2, height: 8}}
  - {tag: P-101, type: CentrifugalPump, sheet: P-01,
     dimensions: {length: 1.6, width: 0.7, height: 1.0}}
""",
    "piping/line-list.yaml": """\
lines:
  - {number: 80-P-101, from: V-101, to: P-101, nominal_diameter: DN80, fluid: Water}
  - {number: 50-P-102, from: P-101, to: BL, nominal_diameter: DN50, fluid: Water}
""",
    "control/instrument-list.yaml": """\
instruments:
  - {tag: PT-101, service: discharge pressure, sheet: P-01}
  - {tag: LT-102, service: level, sheet: P-01}
  - {tag: PI-103, service: local gauge, sheet: P-01}
  - {tag: FIC-104, service: discharge flow, sheet: P-01}
""",
    "layout/site-plan.yaml": """\
site: {name: MEP test plant, width: 40, depth: 30}
areas:
  - {id: A1, box: [2, 2, 38, 28]}
racks:
  - {id: PR-1, points: [[5, 15], [35, 15]], width: 3, levels: [5]}
""",
    "layout/equipment-placement.yaml": """\
equipment:
  - {tag: V-101, position: [10, 10, 0]}
  - {tag: P-101, position: [14, 10, 0], rotation_deg: 90}
""",
    "layout/building.yaml": """\
buildings:
  - {id: SUB-1, origin: [30, 20], width: 6, depth: 5,
     levels: [{id: GF, elevation: 0, height: 4}], walls: all}
  - id: H-1
    origin: [18, 2]
    width: 16
    depth: 10
    levels: [{id: GF, elevation: 0, height: 6}]
    walls: all
    openings:
      - {id: LV1, side: west, offset: 3, width: 2, height: 1.5, sill: 3, kind: louvre}
      - {id: LV2, side: east, offset: 3, width: 2, height: 1.5, sill: 3, kind: louvre}
      - {id: D1, side: south, offset: 8, width: 1.2, height: 2.2, kind: door}
""",
    "electrical/electrical-list.yaml": """\
rooms:
  - {id: MCC-1, kind: mcc, building: SUB-1}
  - {id: CR-1, kind: control, building: SUB-1}
motors:
  - {driven: P-101, power_kw: 15, source: vendor data}
""",
    "layout/hvac.yaml": """\
units:
  - {id: AHU-1, building: H-1, position: [21, 7], rotation_deg: 90, capacity_m3h: 8000,
     intake: LV1, exhaust: LV2}
rooms:
  - {id: HALL, building: H-1, unit: AHU-1, air_changes_per_h: 6,
     basis: "heat load of the machines (ASSUMED)"}
""",
}


def mep_fixtures(core: Path, tmp: Path) -> None:
    from chemeascode.templates.install import init

    root = tmp / "mep"
    init(root, "MEP test plant")
    shutil.copy(core / "tests" / "data" / "layout_cabling.xml", root / "pid" / "P-01.xml")
    for name, text in MEP_FILES.items():
        (root / name).parent.mkdir(parents=True, exist_ok=True)
        (root / name).write_text(text, encoding="utf-8")
    subprocess.run([sys.executable, "-m", "chemeascode", "layout", "build"], cwd=root, check=True, capture_output=True)
    git(root, "init", "-q", "-b", "main")
    git(root, "add", ".")
    git(root, "commit", "-q", "-m", "MEP test plant")
    client = client_for(root)
    write(FIXTURES / "layout-mep.json", get(client, "/api/layout"))
    write(FIXTURES / "api" / "mto-mep.json", get(client, "/api/mto"))


def asu_mto_fixture(tmp: Path) -> None:
    """`/api/mto` of the frozen ASU model (the layout fixture's), priced with the example rates."""
    from chemeascode.templates.install import init

    model = json.loads((FIXTURES / "layout-asu.json").read_text(encoding="utf-8"))["model"]
    root = tmp / "asu-mto"
    init(root, "ASU take-off")
    # JSON is YAML: the model as the API sent it.
    (root / "layout" / "plant-model.yaml").write_text(json.dumps(model, indent=1) + "\n", encoding="utf-8")
    git(root, "init", "-q", "-b", "main")
    git(root, "add", ".")
    git(root, "commit", "-q", "-m", "ASU model")
    write(FIXTURES / "api" / "mto-asu.json", get(client_for(root), "/api/mto"))
    for command, name in (("mto", "mto-asu.csv"), ("estimate", "estimate-asu.csv")):
        out = subprocess.run([sys.executable, "-m", "chemeascode", "assess", command, "--csv"], cwd=root, check=True, capture_output=True, text=True)
        path = FIXTURES / "api" / name
        path.write_text(out.stdout, encoding="utf-8")
        print(f"wrote {path.relative_to(VIEWER)}")


def lca_fixture(asu: Path, tmp: Path) -> None:
    """`/api/lca` of the ASU's LCA (operation, construction, a grid scenario)."""
    root = copy_plant(asu, tmp / "asu-lca")
    git(root, "init", "-q", "-b", "main")
    git(root, "add", ".")
    git(root, "commit", "-q", "-m", "ASU LCA")
    write(FIXTURES / "api" / "lca-asu.json", get(client_for(root), "/api/lca"))
    out = subprocess.run([sys.executable, "-m", "chemeascode", "assess", "lca", "--csv"], cwd=root, check=True, capture_output=True, text=True)
    path = FIXTURES / "api" / "lca-asu.csv"
    path.write_text(out.stdout, encoding="utf-8")
    print(f"wrote {path.relative_to(VIEWER)}")


# The TEA premises of core's examples/process-blocks (per hour 1000 kg feed and 350 kWh steam
# in, 400 kg product and 600 kg waste water out): core's test premises, with a cash cost
# decision, labour, tax, a ramp-up, a chemical per feed (variable_opex), a catalyst replacement
# every 3 years (events), a priced emission on the waste water, working capital in days,
# scenarios and a Monte Carlo. The numbers are an example (example: true).
BLOCKS_TEA = {
    "schema": "cheme/tea/v1",
    "kind": "tea",
    "example": True,
    "currency": "EUR",
    "cost_year": 2025,
    "decision": {
        "question": "Proceed to basic engineering with the blocks plant?",
        "metric": "cash_cost",
        "threshold": 600,
        "confidence": 0.9,
        "alternatives": ["toll manufacturing at a contract producer"],
    },
    "basis": {
        "product": "PROD",
        "specification": "95 wt% ethanol",
        "boundary": "feed to product tank",
        "scale": "3,200 t/a product",
        "location": "NL",
    },
    "capex": {
        "isbl": {"source": "given", "value": {"value": 5.0e6, "source": "fixture: a factored estimate", "year": 2025}, "estimate_class": 4},
        "osbl": {"value": 0.3, "source": "fixture: offsites at 30 % of ISBL"},
        "owners_cost": {"value": 0.1, "source": "fixture: owner's cost"},
        "contingency": {"value": 0.2, "source": "fixture: process and project contingency"},
    },
    "operation": {"hours_per_year": 8000, "life_years": 20, "ramp_up": [0.5, 0.8], "source": "fixture"},
    "prices": [
        {"key": "feed:FEED", "value": 50, "unit": "t", "status": "QUOTED", "source": "fixture: supplier quote", "year": 2025},
        {"key": "feed:STEAM", "value": 30, "unit": "MWh", "source": "fixture: site steam tariff", "year": 2025},
        {"key": "product:PROD", "value": 900, "unit": "t", "source": "fixture: market price", "year": 2024},
    ],
    "free": [{"key": "product:WATER", "reason": "to the site's treatment"}],
    "variable_opex": [
        {
            "id": "naoh",
            "title": "Caustic soda for neutralisation",
            "per": "feed:FEED",
            "amount": {"value": 0.002, "source": "fixture: 2 kg NaOH per t of feed"},
            "unit": "kg NaOH",
            "value": 0.45,
            "status": "QUOTED",
            "source": "fixture: supplier quote",
            "year": 2025,
            "category": "chemical",
        }
    ],
    "emissions": {
        "price": {"value": 80, "source": "fixture: EU ETS allowance", "year": 2025},
        "sources": [{"id": "wastewater", "key": "product:WATER", "factor": {"value": 0.05, "source": "fixture: t CO2-eq per t of waste water treated"}, "unit": "t"}],
    },
    "events": [
        {
            "id": "catalyst",
            "title": "Catalyst replacement",
            "kind": "replacement",
            "cost": {"value": 150000, "source": "fixture: vendor quote for one charge", "year": 2025},
            "every_years": 3,
            "downtime_days": 5,
            "source": "fixture: catalyst life 3 years",
        }
    ],
    "fixed_opex": {
        "maintenance": {"value": 0.03, "source": "fixture: 3 % of fixed capital"},
        "labour": {
            "operators": {"value": 5, "source": "fixture: one position, five crews"},
            "cost_per_operator": {"value": 65000, "source": "fixture: NL operator, loaded", "year": 2025},
            "supervision": {"value": 0.2, "source": "fixture"},
        },
    },
    "finance": {
        "discount_rate": {"value": 0.08, "source": "fixture: real hurdle rate"},
        "tax_rate": {"value": 0.25, "source": "fixture: NL corporate tax"},
        "depreciation_years": 10,
        "construction": [0.4, 0.6],
        "working_capital_days": {
            "feed_inventory": {"value": 30, "source": "fixture"},
            "receivables": {"value": 45, "source": "fixture"},
            "payables": {"value": 30, "source": "fixture"},
            "source": "fixture: days of the first full year's flows",
        },
    },
    "uncertainty": {"iterations": 400, "seed": 7, "defaults": {"ASSUMED": {"gsd2": 1.2}}},
    "scenarios": [
        {"id": "dear-feed", "title": "Feed at twice the price", "prices": {"feed:FEED": 100}, "source": "fixture"},
        {"id": "overrun", "title": "Capital overrun of 30 %", "scale": {"capex:isbl": 1.3}, "source": "fixture"},
    ],
}


def tea_fixtures(core: Path, asu: Path, tmp: Path) -> None:
    """`/api/tea` of the ASU's TEA, and of core's process-blocks with `BLOCKS_TEA`."""
    import yaml

    root = copy_plant(asu, tmp / "asu-tea")
    git(root, "init", "-q", "-b", "main")
    git(root, "add", ".")
    git(root, "commit", "-q", "-m", "ASU TEA")
    write(FIXTURES / "api" / "tea-asu.json", get(client_for(root), "/api/tea"))

    blocks = copy_plant(core / "examples" / "process-blocks", tmp / "blocks-tea")
    (blocks / "estimate").mkdir(exist_ok=True)
    (blocks / "estimate" / "tea.yaml").write_text(yaml.safe_dump(BLOCKS_TEA, sort_keys=False), encoding="utf-8")
    git(blocks, "init", "-q", "-b", "main")
    git(blocks, "add", ".")
    git(blocks, "commit", "-q", "-m", "Blocks TEA")
    client = client_for(blocks)
    if not get(client, "/api/repo").get("has_tea"):
        raise SystemExit("process-blocks: /api/repo does not report has_tea; update this script")
    write(FIXTURES / "api" / "tea-blocks.json", get(client, "/api/tea"))


def reviews_fixture(asu: Path, tmp: Path) -> None:
    """`/api/status` of the ASU with its review records, and two stage sign-offs.

    The ASU has no sign-off (its checks/status.json is the 0.3 kind, gates only), so the copy gets
    a checks/status.json with two: `concept` of the commit on main, and `basic` of a commit on a
    branch `stage/basic` that is not merged (`on_default_branch` false). The working tree is on
    that branch. The records' text goes to `api/reviews-asu.json` (path -> `/api/file` text).
    """
    root = copy_plant(asu, tmp / "asu-reviews")
    git(root, "init", "-q", "-b", "main")
    git(root, "add", ".")
    git(root, "commit", "-q", "-m", "ASU")
    on_main = subprocess.run(["git", "rev-parse", "HEAD"], cwd=root, check=True, capture_output=True, text=True).stdout.strip()
    git(root, "checkout", "-q", "-b", "stage/basic")
    (root / "PROGRESS.md").write_text((root / "PROGRESS.md").read_text(encoding="utf-8") + "\nBasic engineering signed off on its branch.\n", encoding="utf-8")
    git(root, "commit", "-q", "-am", "Basic engineering ready for sign-off")
    on_branch = subprocess.run(["git", "rev-parse", "HEAD"], cwd=root, check=True, capture_output=True, text=True).stdout.strip()
    stages = {
        "concept": {
            "commit": on_main,
            "date": "2026-10-18T16:20:00+00:00",
            "signed_by": "A. Engineer",
            "branch": "main",
            "review": "reviews/2026-10-18-basic-engineering.md",
            "reviewer_kind": "human",
        },
        "basic": {
            "commit": on_branch,
            "date": "2026-10-23T09:05:00+00:00",
            "signed_by": "A. Engineer",
            "branch": "stage/basic",
            "review": "reviews/2026-10-23-layout-review9.md",
            "reviewer_kind": "agent",
        },
    }
    (root / "checks" / "status.json").write_text(json.dumps({"stages": stages, "checks": []}, indent=2) + "\n", encoding="utf-8")
    git(root, "commit", "-q", "-am", "Sign off concept and basic")
    client = client_for(root)
    write(FIXTURES / "api" / "status-asu.json", get(client, "/api/status"))
    records = {}
    for entry in get(client, "/api/tree"):
        path = entry["path"]
        if entry["type"] == "file" and path.startswith("reviews/") and path.count("/") == 1 and path.endswith(".md"):
            records[path] = client.get("/api/file", params={"path": path}).text
    write(FIXTURES / "api" / "reviews-asu.json", records)


def interlocks_fixture(asu: Path, tmp: Path) -> None:
    """`/api/interlocks` of the ASU (its `control/cause-effect.yaml`: two low-low level trips)."""
    root = copy_plant(asu, tmp / "asu-interlocks")
    git(root, "init", "-q", "-b", "main")
    git(root, "add", ".")
    git(root, "commit", "-q", "-m", "ASU interlocks")
    write(FIXTURES / "api" / "interlocks-asu.json", get(client_for(root), "/api/interlocks"))


def simulation_asu_fixture(asu: Path, tmp: Path) -> None:
    """`/api/simulation` of the ASU (its `process/simulation.yaml`; no run recorded)."""
    root = copy_plant(asu, tmp / "asu-simulation")
    git(root, "init", "-q", "-b", "main")
    git(root, "add", ".")
    git(root, "commit", "-q", "-m", "ASU simulation")
    data = get(client_for(root), "/api/simulation")
    if data["run"] is not None:
        raise SystemExit("the ASU now records a simulation run: update this script and the fixture README")
    write(FIXTURES / "api" / "simulation-asu.json", data)


def simulation_run_fixtures(core: Path, tmp: Path) -> None:
    """A recorded simulation run of core's `examples/process-simulation`, from `cheme process
    simulate --fill`'s code with core's stand-in solver (DWSIM does not run here): current, stale
    (K1's efficiency changed after the run) and not converged."""
    import yaml
    from chemeascode.domains.process.model import load as load_process
    from chemeascode.domains.process.simulation.run import run
    from chemeascode.foundation.workspace import Workspace

    sys.path.insert(0, str(core))
    from tests.test_process_simulate import fake  # the stand-in solver of core's tests

    def plant(name: str) -> Path:
        root = copy_plant(core / "examples" / "process-simulation", tmp / name)
        git(root, "init", "-q", "-b", "main")
        git(root, "add", ".")
        git(root, "commit", "-q", "-m", "Simulation example")
        return root

    def fill(root: Path, solver) -> None:
        process, _ = load_process(root)
        run(Workspace(root), process, "design", write=True, solver=solver)

    root = plant("process-simulation")
    fill(root, fake)
    client = client_for(root)
    out = FIXTURES / "api"
    data = get(client, "/api/simulation")
    if data["run"] is None or data["stale"] is not False:
        raise SystemExit("process-simulation: no current run recorded; update this script")
    write(out / "simulation-run.json", data)
    write(out / "streams-simulation.json", get(client, "/api/streams"))

    sim = root / "process" / "simulation.yaml"
    spec = yaml.safe_load(sim.read_text(encoding="utf-8"))
    spec["specs"]["K1"]["efficiency"]["value"] = 0.7
    sim.write_text(yaml.safe_dump(spec, sort_keys=False), encoding="utf-8")
    data = get(client, "/api/simulation")
    if data["stale"] is not True:
        raise SystemExit("process-simulation: the edited spec does not make the run stale; update this script")
    write(out / "simulation-stale.json", data)

    failed = plant("process-simulation-failed")
    fill(failed, lambda model, save: fake(model, save, converged=False))
    data = get(client_for(failed), "/api/simulation")
    if not data["run"] or data["run"]["converged"] is not False:
        raise SystemExit("process-simulation: the failed run is not recorded; update this script")
    write(out / "simulation-failed.json", data)


def reactions_fixtures(core: Path, tmp: Path) -> None:
    """`/api/reactions` (and `/api/streams`) of core's `examples/process-ammonia`; and with the
    stoichiometry made unbalanced in the working tree."""
    root = copy_plant(core / "examples" / "process-ammonia", tmp / "process-ammonia")
    git(root, "init", "-q", "-b", "main")
    git(root, "add", ".")
    git(root, "commit", "-q", "-m", "Ammonia example")
    client = client_for(root)
    out = FIXTURES / "api"
    write(out / "reactions-ammonia.json", get(client, "/api/reactions"))
    write(out / "streams-ammonia.json", get(client, "/api/streams"))
    replace_once(root / "process" / "reactions.yaml", "{N2: -1, H2: -3, NH3: 2}", "{N2: -1, H2: -3, NH3: 3}")
    data = get(client, "/api/reactions")
    if not data["balance"]["findings"]:
        raise SystemExit("process-ammonia: the unbalanced reaction has no finding; update this script")
    write(out / "reactions-ammonia-unbalanced.json", data)

    shift = copy_plant(core / "examples" / "process-shift", tmp / "process-shift")
    git(shift, "init", "-q", "-b", "main")
    git(shift, "add", ".")
    git(shift, "commit", "-q", "-m", "Shift example")
    data = get(client_for(shift), "/api/reactions")
    if not (data["kinetics"]["catalysts"] and data["reactions"][0]["rate_law"]):
        raise SystemExit("process-shift: no catalyst or rate law served; update this script")
    write(out / "reactions-shift.json", data)

    # The catalysis results: core's test plants of tests/test_serve_catalysis.py (a CO oxidation
    # mechanism at its reactor's outlet; rates of the shift example's own law, with a file that
    # does not validate).
    sys.path.insert(0, str(core))
    from tests.test_serve_catalysis import _co_oxidation, _kinetic_data

    coox = _co_oxidation(tmp)
    git(coox, "init", "-q", "-b", "main")
    git(coox, "add", ".")
    git(coox, "commit", "-q", "-m", "CO oxidation")
    data = get(client_for(coox), "/api/reactions")
    if not any(r["microkinetics"] and r["microkinetics"]["missing"] is None for r in data["reactions"]):
        raise SystemExit("coox: no microkinetic analysis served; update this script")
    write(out / "reactions-coox.json", data)
    measured = copy_plant(core / "examples" / "process-shift", tmp / "process-shift-kinetics")
    _kinetic_data(measured)
    git(measured, "init", "-q", "-b", "main")
    git(measured, "add", ".")
    git(measured, "commit", "-q", "-m", "Shift example with kinetic data")
    client = client_for(measured)
    data = get(client, "/api/kinetics")
    if not any(f["fit"] for f in data["files"]):
        raise SystemExit("process-shift: no kinetic fit served; update this script")
    write(out / "kinetics-shift.json", data)
    write(out / "library-shift.json", get(client, "/api/library"))


#: The declared bed of the shift example's R1, replaced by each variant of `bed_fixtures`.
SHIFT_BED = "      catalyst_mass: 40000\n      diameter: 3.0\n      heat: adiabatic\n      viscosity: 2.6e-5\n"
#: Variant -> R1's bed: cooled tubes with an interior hot spot, cooled harder (the inlet hottest),
#: isothermal, and cooled without a coolant (the bed cannot be solved).
SHIFT_BEDS = {
    "cooled": "      catalyst_mass: 40000\n      diameter: 0.1\n      tubes: 800\n      heat: cooled\n      coolant_temperature: 620\n      heat_transfer_coefficient: 30\n      viscosity: 2.6e-5\n",
    "inlet": "      catalyst_mass: 40000\n      diameter: 0.05\n      tubes: 3000\n      heat: cooled\n      coolant_temperature: 600\n      heat_transfer_coefficient: 150\n      viscosity: 2.6e-5\n",
    "isothermal": "      catalyst_mass: 40000\n      diameter: 3.0\n      heat: isothermal\n      viscosity: 2.6e-5\n",
    "failed": "      catalyst_mass: 40000\n      diameter: 3.0\n      heat: cooled\n      viscosity: 2.6e-5\n",
}


def bed_fixtures(core: Path, tmp: Path) -> None:
    """The fixed-bed results: `/api/reactions` of core's `examples/process-shift` with
    R1's bed replaced by each of `SHIFT_BEDS` (the cooled one with FE_CR's window narrowed to
    640 K, below its hot spot); and core's kinetic coupling test plant (`tests/
    test_process_simulate_kinetic.py`: an adiabatic ammonia bed, no pressure drop) with its run
    recorded by `cheme process simulate --fill`'s code and that test's stand-in for DWSIM:
    `/api/reactions`, `/api/simulation` after the run (current), with the bed's catalyst mass
    changed (stale) and of a fresh copy whose outer loop does not settle (not converged)."""
    out = FIXTURES / "api"
    for name, bed in SHIFT_BEDS.items():
        root = copy_plant(core / "examples" / "process-shift", tmp / f"shift-{name}")
        replace_once(root / "process" / "flowsheet.yaml", SHIFT_BED, bed)
        if name == "cooled":
            replace_once(root / "process" / "catalysts.yaml", "temperature: [583.15, 773.15]", "temperature: [583.15, 640]")
        git(root, "init", "-q", "-b", "main")
        git(root, "add", ".")
        git(root, "commit", "-q", "-m", f"Shift example, {name} bed")
        data = get(client_for(root), "/api/reactions")
        r1 = next(r for r in data["reactors"] if r["node"] == "R1")
        if (r1["bed"] is None) != (name == "failed"):
            raise SystemExit(f"process-shift {name}: bed {r1['bed'] is not None}, missing {r1['missing']}; update this script")
        write(out / f"reactions-bed-{name}.json", data)

    sys.path.insert(0, str(core))
    from chemeascode.domains.process.model import load as load_process
    from chemeascode.domains.process.simulation.run import run
    from chemeascode.foundation.workspace import Workspace
    from tests.test_process_simulate_kinetic import SIMULATION, _plant, stand_in

    def recorded(name: str, simulation: str = SIMULATION, drift: float = 0.0) -> Path:
        ws = _plant(tmp / name, simulation=simulation)
        git(ws.root, "init", "-q", "-b", "main")
        git(ws.root, "add", ".")
        git(ws.root, "commit", "-q", "-m", "Kinetic bed")
        process, _ = load_process(ws.root)
        calls: list = []
        run(ws, process, "design", write=True, solver=lambda m, s: stand_in(m, s, drift=drift, calls=calls))
        git(ws.root, "add", ".")
        git(ws.root, "commit", "-q", "-m", "Simulated")
        return ws.root

    root = recorded("kinetic")
    client = client_for(root)
    write(out / "reactions-bed-sim.json", get(client, "/api/reactions"))
    write(out / "simulation-bed-run.json", get(client, "/api/simulation"))
    replace_once(root / "process" / "flowsheet.yaml", "catalyst_mass: 2000", "catalyst_mass: 3000")
    data = get(client, "/api/simulation")
    if data["stale"] is not True:
        raise SystemExit("kinetic bed: the run is not stale after the bed changed; update this script")
    write(out / "simulation-bed-stale.json", data)
    root = recorded("kinetic-failed", SIMULATION + "specs:\n  R1:\n    coupling: {max_iterations: 3}\n", drift=5.0)
    data = get(client_for(root), "/api/simulation")
    if data["run"]["converged"] is not False:
        raise SystemExit("kinetic bed: the drifting loop converged; update this script")
    write(out / "simulation-bed-failed.json", data)


# The datasheet fixtures' drawings: one of each family and every drawing state.
DRAWING_TAGS = ("V-2101A", "V-2101B", "T-4102", "C-3101", "E-3101", "P-1101A")


def edit_yaml(path: Path, change) -> None:
    """Load the YAML file *path*, let *change* edit the data, write it back (comments are lost)."""
    import yaml

    data = yaml.safe_load(path.read_text(encoding="utf-8"))
    change(data)
    path.write_text(yaml.safe_dump(data, sort_keys=False, allow_unicode=True, width=100), encoding="utf-8")


def cheme(root: Path, *args: str) -> None:
    subprocess.run([sys.executable, "-m", "chemeascode", *args], cwd=root, check=True, capture_output=True)


def datasheet_fixtures(asu: Path, tmp: Path) -> None:
    """`/api/datasheets`, `/api/datasheets/{tag}` and `/api/datasheets/{tag}.svg` of an ASU copy
    with its main dimensions filled and its outline drawings written, then edited so every case
    shows: a full schedule, structured materials and weights (V-2101A, drawn again), a stale
    drawing (V-2101B), a missing drawing (T-4102), a list item without a datasheet (P-4102B) and
    a dimension that disagrees with the equipment list (V-3101)."""
    root = copy_plant(asu, tmp / "asu-datasheets")
    sheets = root / "equipment" / "datasheets"
    cheme(root, "datasheets", "fill", "--dimensions")

    def rich(data: dict) -> None:
        data["materials"] = {
            "shell": {"value": "SA-516-70N", "material_class": "low_temperature_carbon_steel", "standard": "ASME II A", "source": "equipment/equipment-list.yaml (CS, low-temp impact tested)"},
            "heads": {"value": "SA-516-70N", "material_class": "low_temperature_carbon_steel", "standard": "ASME II A", "assumed": True, "source": "as the shell"},
            "internals": "SS 304 support grid",
        }
        data["weights"] = {
            "empty": {"value": 62.0, "unit": "t", "assumed": True, "source": "shell and heads at 28 mm (ASSUMED), adsorbent not included"},
            "operating": {"value": 158.0, "unit": "t", "assumed": True, "source": "empty + 96 t of 13X and alumina"},
            "test": {"value": "supplier", "unit": "t", "reason": "full of water, from the vessel supplier"},
        }
        services = {"N1": "Feed air inlet", "N2": "Dry air outlet", "N3": "Regeneration gas inlet", "N4": "Regeneration gas outlet", "N5": "Vent"}
        for nozzle in data["nozzles"]:
            name = nozzle["name"]
            if name in services:
                nozzle.update({"mark": name, "service": services[name], "rating": "PN16", "facing": "RF", "standard": "EN 1092-1", "projection_m": 0.6})
        data["nozzles"].append({"name": "M1", "mark": "M1", "service": "Manway", "dn": 600, "rating": "PN16", "facing": "RF", "face": "side", "orientation_deg": 90, "axial_m": 0.0, "elevation_m": 4.25, "projection_m": 0.5, "assumed": True, "source": "DESIGN.md (ASSUMED)"})

    edit_yaml(sheets / "V-2101A.yaml", rich)
    cheme(root, "datasheets", "drawing", "--write")

    def longer(data: dict) -> None:  # after the drawing: it is stale
        data["dimensions"]["tangent_length"]["value"] = 16.0

    edit_yaml(sheets / "V-2101B.yaml", longer)

    def wider(data: dict) -> None:  # not the equipment list's diameter
        data["dimensions"]["outside_diameter"]["value"] = 4.2

    edit_yaml(sheets / "V-3101.yaml", wider)
    (sheets / "T-4102.svg").unlink()
    (sheets / "P-4102B.yaml").unlink()
    (sheets / "P-4102B.svg").unlink()
    git(root, "init", "-q", "-b", "main")
    git(root, "add", ".")
    git(root, "commit", "-q", "-m", "ASU datasheets")

    client = client_for(root)
    out = FIXTURES / "api"
    if not get(client, "/api/repo")["has_datasheets"]:
        raise SystemExit("the ASU copy has no datasheets: update this script")
    index = get(client, "/api/datasheets")
    states = {s["tag"]: (s["has_drawing"], s["drawing_current"]) for s in index["datasheets"]}
    if states.get("V-2101B") != (True, False) or states.get("T-4102") != (False, False) or index["missing"] != ["P-4102B"]:
        raise SystemExit(f"the edited ASU copy does not show every drawing state: update this script ({states}, {index['missing']})")
    write(out / "datasheets-index-asu.json", index)
    # Each sheet's answer without its `source` (the index has the same inputs' fingerprints).
    write(out / "datasheet-details-asu.json", {s["tag"]: {k: v for k, v in get(client, f"/api/datasheets/{s['tag']}").items() if k != "source"} for s in index["datasheets"]})
    drawings = {}
    for tag in DRAWING_TAGS:
        for generated in (False, True):
            response = client.get(f"/api/datasheets/{tag}.svg", params={"generated": "true"} if generated else {})
            if response.status_code != 200:
                raise SystemExit(f"{tag}.svg: {response.status_code} {response.text}")
            name = f"{tag}{'.generated' if generated else ''}.svg"
            if generated and response.text == drawings[f"{tag}.svg"]["svg"]:
                continue  # the committed drawing is current (or there is none): the same SVG
            drawings[name] = {
                "drawing": response.headers["x-cheme-drawing"],
                "current": response.headers.get("x-cheme-drawing-current"),
                "svg": response.text,
            }
    write(out / "datasheet-drawings-asu.json", drawings)

    # What cheme export-static writes for the datasheets: the keys and the drawing's answer.
    from chemeascode.interfaces.api.export_static import export_static

    snapshot = tmp / "asu-datasheets-snapshot"
    export_static(root, snapshot)
    manifest = json.loads((snapshot / "manifest.json").read_text(encoding="utf-8"))
    keys = sorted(k for k in manifest["entries"] if k.startswith("datasheets"))
    write(out / "datasheets-snapshot-keys.json", {k: {"status": manifest["entries"][k]["status"], "type": manifest["entries"][k]["type"]} for k in keys})


def git(root: Path, *args: str) -> None:
    env = {**os.environ, **GIT_ENV}
    subprocess.run(["git", *args], cwd=root, env=env, check=True, capture_output=True)


def control_fixtures(core: Path, tmp: Path) -> None:
    """`/api/control` and `/api/repo` of core's `examples/process-separation` (a
    narrative, a control philosophy, five loops, two sequences, one trip), committed once in a
    fresh git repository: every file drafted, PIC-104 a deliberate draft with open points."""
    root = copy_plant(core / "examples" / "process-separation", tmp / "process-separation")
    git(root, "init", "-q", "-b", "main")
    git(root, "add", ".")
    git(root, "commit", "-q", "-m", "Control example")
    client = client_for(root)
    out = FIXTURES / "api"
    write(out / "control-separation.json", get(client, "/api/control"))
    repo = get(client, "/api/repo")
    if not isinstance(repo, dict) or not repo.get("has_control"):
        raise SystemExit("process-separation: /api/repo has no has_control (core older than the control records)")


def issue_item(number: int, title: str, labels: list[str], state: str = "open", closed: str | None = None) -> dict:
    """One issue as the GitHub REST API lists it (the fields core reads)."""
    return {
        "number": number,
        "title": title,
        "state": state,
        "labels": [{"name": name} for name in labels],
        "html_url": f"https://github.com/ChemE-as-Code/process-library/issues/{number}",
        "created_at": f"2026-10-{number:02d}T09:00:00Z",
        "updated_at": "2026-10-24T09:00:00Z",
        "closed_at": closed,
    }


ISSUE_LABEL = "process:separation"
ISSUE_ITEMS = [
    issue_item(1, "Confirm the feed composition with the client", [ISSUE_LABEL, "type:tq", "gate:concept", "discipline:process", "source:client", "status:for-verification"]),
    issue_item(2, "Reboiler duty is a placeholder until the vendor quotes", [ISSUE_LABEL, "type:hold", "gate:basic", "discipline:process", "discipline:mechanical", "source:vendor", "waiting:input"]),
    issue_item(3, "PIC-104: state the controller action and the fail position of PV-104", [ISSUE_LABEL, "type:action", "gate:basic", "discipline:control", "source:control-review", "status:in-progress"]),
    issue_item(4, "Add a low-low level trip on the flash drum", [ISSUE_LABEL, "type:action", "gate:concept", "discipline:safety", "source:hazop"], state="closed", closed="2026-10-20T12:00:00Z"),
    issue_item(5, "Replace the shortcut column by a rigorous one", [ISSUE_LABEL, "type:change", "gate:detail", "discipline:process", "source:design-review", "waiting:work"]),
    issue_item(6, "Check the relief load of the column overhead", [ISSUE_LABEL, "type:action", "discipline:safety", "source:internal"]),
    issue_item(7, "Tidy up the stream naming", [ISSUE_LABEL]),
    issue_item(8, "Size the flash drum demister", [ISSUE_LABEL, "type:action", "gate:basic", "gate:concept", "discipline:mechanical", "source:design-review"]),
    issue_item(9, "Agree the cooling water return temperature", [ISSUE_LABEL, "type:tq", "gate:Basic", "discipline:process", "source:client"]),
]


def issues_fixtures(core: Path, tmp: Path) -> None:
    """`/api/issues` of core's `examples/process-separation` with `issues:` in plant.yaml (stage
    `basic`), GitHub replaced by ISSUE_ITEMS; and the 503 when GitHub cannot be read."""
    from chemeascode.integrations import github

    root = copy_plant(core / "examples" / "process-separation", tmp / "process-separation-issues")
    plant = root / "plant.yaml"
    replace_once(plant, "stage: concept\n", "stage: basic\n")
    plant.write_text(
        plant.read_text(encoding="utf-8")
        + "issues:\n  repository: ChemE-as-Code/process-library\n"
        + f'  label: "{ISSUE_LABEL}"\n'
        + "  forms: {action: 1-action-item.yml, hold: 2-engineering-hold.yml, tq: 3-technical-query.yml, change: 4-design-change.yml}\n",
        encoding="utf-8",
    )
    git(root, "init", "-q", "-b", "main")
    git(root, "add", ".")
    git(root, "commit", "-q", "-m", "Issues example")
    out = FIXTURES / "api"
    original, original_token = github.list_issues, github.token
    try:
        github.list_issues = lambda *args, **kwargs: [dict(item) for item in ISSUE_ITEMS]
        client = client_for(root)
        repo = get(client, "/api/repo")
        if not isinstance(repo, dict) or repo.get("has_issues") is not True:
            raise SystemExit("process-separation: /api/repo has no has_issues (core without GET /api/issues)")
        write(out / "repo-issues.json", repo)
        write(out / "issues-separation.json", get(client, "/api/issues"))

        # core's own reader without a token (none in the environment, no gh login)
        from chemeascode.project import issues as core_issues

        core_issues.clear_cache()  # core caches the answer (or the failure) per repository and label
        github.list_issues = original
        github.token = lambda: None
        response = client_for(root).get("/api/issues")
        if response.status_code != 503:
            raise SystemExit(f"/api/issues offline: {response.status_code}, expected 503")
        write(out / "issues-unavailable.json", {"status": response.status_code, "body": response.json()})
    finally:
        github.list_issues, github.token = original, original_token


def process_fixtures(core: Path, tmp: Path) -> None:
    root = copy_plant(core / "examples" / "process-nested", tmp / "process-nested")
    git(root, "init", "-q", "-b", "main")
    git(root, "add", ".")
    git(root, "commit", "-q", "-m", "Process example")
    # an uncommitted edit the sheets do not follow: generated-outdated and review-needed
    flowsheet = root / "process" / "flowsheet.yaml"
    text = flowsheet.read_text(encoding="utf-8")
    first_title = next(line for line in text.splitlines() if line.strip().startswith("title:"))
    replace_once(flowsheet, first_title + "\n", first_title + " (renamed)\n")

    client = client_for(root)
    out = FIXTURES / "api"
    write(out / "repo.json", get(client, "/api/repo"))
    write(out / "tree.json", get(client, "/api/tree"))
    write(out / "streams.json", get(client, "/api/streams"))
    write(out / "yaml-flowsheet.json", get(client, "/api/yaml?path=process/flowsheet.yaml"))
    write(out / "validate.json", get(client, "/api/validate"))
    write(out / "impact.json", get(client, "/api/impact"))

    # the same edit, rebuilt with `cheme process build`: the BFD's diff against HEAD
    rebuilt = copy_plant(root, tmp / "process-nested-rebuilt", keep_git=True)
    subprocess.run(
        [sys.executable, "-m", "chemeascode", "process", "build"],
        cwd=rebuilt,
        check=True,
        capture_output=True,
    )
    write(out / "diff-bfd.json", get(client_for(rebuilt), "/api/diff?path=process/BFD.xml&old=HEAD"))


def main() -> None:
    default_core = Path(chemeascode.__file__).resolve().parents[2]
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--core", type=Path, default=default_core, help="cheme-as-code (core) checkout")
    parser.add_argument("--demo", type=Path, help="example-dexpi-plant checkout (layout fixtures)")
    parser.add_argument("--asu", type=Path, help="ASU plant folder (process-library processes/asu-1, or the checkout) with a built layout model")
    parser.add_argument("--asu-files", type=Path, help="ASU plant folder (or process-library checkout): lifting study, datasheet entries, a penetration case, the review status, the simulation")
    parser.add_argument("--asu-datasheets", type=Path, help="ASU plant folder (or process-library checkout): the datasheet endpoints after fill --dimensions and drawing --write (core with /api/datasheets)")
    parser.add_argument("--only-reactions", action="store_true", help="write only the reactions fixtures (with the microkinetics, kinetic data and library ones)")
    parser.add_argument("--only-beds", action="store_true", help="write only the fixed-bed fixtures")
    parser.add_argument("--only-control", action="store_true", help="write only the control fixture")
    parser.add_argument("--only-issues", action="store_true", help="write only the issues fixtures (core with GET /api/issues)")
    parser.add_argument("--only-tea", action="store_true", help="with --asu: write only the TEA fixtures (tea-asu.json, tea-blocks.json)")
    parser.add_argument("--only-datasheets", action="store_true", help="with --asu-datasheets: write only the datasheet endpoint fixtures")
    args = parser.parse_args()
    print(f"chemeascode from {Path(chemeascode.__file__).parent}")
    with tempfile.TemporaryDirectory() as name:
        tmp = Path(name)
        if args.only_reactions:
            reactions_fixtures(args.core.resolve(), tmp)
            return
        if args.only_beds:
            bed_fixtures(args.core.resolve(), tmp)
            return
        if args.only_control:
            control_fixtures(args.core.resolve(), tmp)
            return
        if args.only_issues:
            issues_fixtures(args.core.resolve(), tmp)
            return
        if args.asu_datasheets:
            datasheet_fixtures(asu_plant(args.asu_datasheets), tmp)
            if args.only_datasheets:
                return
        if args.only_tea:
            if not args.asu:
                raise SystemExit("--only-tea needs --asu")
            tea_fixtures(args.core.resolve(), asu_plant(args.asu), tmp)
            return
        if args.demo:
            layout_fixtures(args.demo.resolve(), tmp)
        else:
            print("no --demo: layout fixtures left as they are")
        asu_fixture(args.core.resolve(), asu_plant(args.asu) if args.asu else None, tmp)
        if args.asu_files:
            asu_files(asu_plant(args.asu_files), tmp)
            reviews_fixture(asu_plant(args.asu_files), tmp)
            simulation_asu_fixture(asu_plant(args.asu_files), tmp)
        asu_mto_fixture(tmp)
        if args.asu:
            lca_fixture(asu_plant(args.asu), tmp)
            interlocks_fixture(asu_plant(args.asu), tmp)
            tea_fixtures(args.core.resolve(), asu_plant(args.asu), tmp)
        else:
            print("no --asu: the LCA, interlocks and TEA fixtures left as they are")
        mep_fixtures(args.core.resolve(), tmp)
        process_fixtures(args.core.resolve(), tmp)
        simulation_run_fixtures(args.core.resolve(), tmp)
        reactions_fixtures(args.core.resolve(), tmp)
        bed_fixtures(args.core.resolve(), tmp)
        control_fixtures(args.core.resolve(), tmp)
        issues_fixtures(args.core.resolve(), tmp)


if __name__ == "__main__":
    main()
