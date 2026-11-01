"""scripts/fill_ef31_uuids.py: EF 3.1 identities only as the official
package holds them. The package and mapping here are synthetic; their UUIDs are test values."""

from __future__ import annotations

import gzip
import importlib.util
import json
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location("fill_ef31", ROOT / "scripts/fill_ef31_uuids.py")
fill = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(fill)

MASS = "00000000-0000-4000-8000-0000000000aa"
KG_GROUP = "00000000-0000-4000-8000-0000000000bb"
SO2 = "00000000-0000-4000-8000-000000000001"
SO2_HIGH = "00000000-0000-4000-8000-000000000002"
CATS = ["Emissions", "Emissions to air", "Emissions to air, unspecified"]
NS = 'xmlns="http://lca.jrc.it/ILCD/Flow" xmlns:common="http://lca.jrc.it/ILCD/Common"'


def _flow(uuid: str, name: str, categories: list[str]) -> str:
    cats = "".join(
        f'<common:category level="{i}">{c}</common:category>' for i, c in enumerate(categories)
    )
    return (
        f"<flowDataSet {NS}><flowInformation><dataSetInformation><common:UUID>{uuid}"
        f'</common:UUID><name><baseName xml:lang="en">{name}</baseName></name>'
        "<classificationInformation><common:elementaryFlowCategorization>"
        f"{cats}</common:elementaryFlowCategorization></classificationInformation>"
        "</dataSetInformation><quantitativeReference><referenceToReferenceFlowProperty>0"
        "</referenceToReferenceFlowProperty></quantitativeReference></flowInformation>"
        "<modellingAndValidation><LCIMethod><typeOfDataSet>Elementary flow</typeOfDataSet>"
        "</LCIMethod></modellingAndValidation><flowProperties>"
        '<flowProperty dataSetInternalID="0">'
        f'<referenceToFlowPropertyDataSet refObjectId="{MASS}"/>'
        "<meanValue>1.0</meanValue></flowProperty></flowProperties></flowDataSet>"
    )


def _package(root: Path) -> Path:
    for folder in ("flows", "flowproperties", "unitgroups"):
        (root / "ILCD" / folder).mkdir(parents=True)
    (root / "ILCD/flowproperties/mass.xml").write_text(
        f'<flowPropertyDataSet xmlns:common="c"><common:UUID>{MASS}</common:UUID>'
        f'<referenceToReferenceUnitGroup refObjectId="{KG_GROUP}"/></flowPropertyDataSet>'
    )
    (root / "ILCD/unitgroups/kg.xml").write_text(
        f'<unitGroupDataSet xmlns:common="c"><common:UUID>{KG_GROUP}</common:UUID>'
        "<referenceToReferenceUnit>1</referenceToReferenceUnit><units>"
        '<unit dataSetInternalID="0"><name>g</name></unit>'
        '<unit dataSetInternalID="1"><name>kg</name></unit></units></unitGroupDataSet>'
    )
    (root / "ILCD/flows/a.xml").write_text(_flow(SO2, "sulfur dioxide", CATS))
    (root / "ILCD/flows/b.xml").write_text(_flow(SO2_HIGH, "sulfur dioxide", [*CATS[:2], "high"]))
    return root / "ILCD"


def _mapping(path: Path, crosswalk: dict) -> Path:
    so2 = next(f for f in crosswalk["flows"] if f["id"] == "sulfur-dioxide")["biosphere3"]["uuid"]
    absent = "00000000-0000-4000-8000-0000000000ff"

    def row(sub: str, uuid: str, name: str = "sulfur dioxide") -> dict:
        return {
            "source": {"uuid": so2[sub]},
            "target": {"uuid": uuid, "name": name, "context": CATS},
        }

    rows = [
        row("unspecified", SO2, "Sulfur dioxide"),
        row("non-urban-high-stack", SO2_HIGH),  # categories differ from the package's: not taken
        row("urban-close-to-ground", absent),  # a UUID the package does not hold: not taken
    ]
    with gzip.open(path, "wt", encoding="utf-8") as handle:
        json.dump({"replace": rows}, handle)
    return path


def test_only_what_the_package_confirms_is_written(tmp_path: Path) -> None:
    crosswalk_path = tmp_path / "elementary-flows.yaml"
    crosswalk_path.write_text(fill.CROSSWALK.read_text(encoding="utf-8"), encoding="utf-8")
    crosswalk = yaml.safe_load(crosswalk_path.read_text())
    package = _package(tmp_path / "pkg")
    mapping = _mapping(tmp_path / "map.gz", crosswalk)
    args = [str(package), "--mapping", str(mapping), "--crosswalk", str(crosswalk_path)]
    assert fill.main([*args, "--package-version", "test package 0.0", "--write"]) == 0
    text = crosswalk_path.read_text()
    assert "TODO(#26)" in text  # comments kept (the packaged file stays byte-stable)
    data = yaml.safe_load(text)
    assert data["source"]["ef-3.1"] == "test package 0.0"
    flows = {f["id"]: f for f in data["flows"]}
    ef = flows["sulfur-dioxide"]["ef-3.1"]
    assert ef["uuid"] == {"unspecified": SO2} and ef["unit"] == "kg"
    assert ef["name"] == "sulfur dioxide" and ef["categories"]["unspecified"] == CATS
    assert sum("ef-3.1" in f for f in flows.values()) == 1
    assert (
        flows["sulfur-dioxide"]["biosphere3"]
        == {f["id"]: f for f in crosswalk["flows"]}["sulfur-dioxide"]["biosphere3"]
    )
