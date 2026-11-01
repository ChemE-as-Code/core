"""Fill the EF 3.1 identities of the elementary-flow crosswalk from the official package.

Usage::

    uv run python scripts/fill_ef31_uuids.py PACKAGE --mapping MAPPING \\
        --package-version "EF 3.1 reference package, <version>, <download URL>" [--write]

``PACKAGE`` is the EF 3.1 reference package as downloaded from the European Commission
(eplca.jrc.ec.europa.eu; ILCD format, a zip or its unpacked folder). ``MAPPING`` is a candidate
mapping from the ecoinvent biosphere to EF 3.1 in the randonneur format, e.g.
``randonneur_data/data/ecoinvent-3.9.1-biosphere-EF-3.1-biosphere.gz`` of the PyPI package
``randonneur_data`` (CC BY 4.0, Chris Mutel, from the UNEP GLAD mappings plus manual and
algorithmic matches; it is not complete).

For every flow and sub-compartment of ``src/chemeascode/domains/assessment/lca/data/
elementary-flows.yaml`` the mapping proposes an EF 3.1 flow by the crosswalk's biosphere3 UUID.
A proposal is kept only when the official package holds a flow of that UUID, an elementary
flow whose name and categories are the mapping's, and whose reference unit is known (kg, or m3
for a flow the crosswalk counts in m3). The UUID, name, categories and unit then come from the
package, never from the mapping. Everything is printed for review (in particular the
sub-compartment each EF 3.1 category stands for); ``--write`` adds the ``ef-3.1`` blocks and the
package version to the crosswalk, keeping its comments. A flow without a verified proposal
stays ``uuid: null`` and is listed: add it by hand from the package, never by guessing.
"""

from __future__ import annotations

import argparse
import gzip
import json
import re
import sys
import zipfile
from collections.abc import Iterator
from pathlib import Path
from xml.etree import ElementTree

import yaml

ROOT = Path(__file__).resolve().parents[1]
CROSSWALK = ROOT / "src/chemeascode/domains/assessment/lca/data/elementary-flows.yaml"
LIST = "ef-3.1"


def _local(tag: str) -> str:
    return tag.rsplit("}", 1)[-1]


def _find(node: ElementTree.Element, *path: str) -> ElementTree.Element | None:
    """The first descendant along *path* of local tag names (namespaces ignored)."""
    for name in path:
        node = next((c for c in node.iter() if c is not node and _local(c.tag) == name), None)
        if node is None:
            return None
    return node


def _documents(package: Path, folder: str) -> Iterator[tuple[str, bytes]]:
    """(file name, content) of the XML documents in the package's *folder* (flows, ...)."""
    if package.is_dir():
        for path in package.rglob("*.xml"):
            if path.parent.name == folder:
                yield path.name, path.read_bytes()
        return
    with zipfile.ZipFile(package) as archive:
        for name in archive.namelist():
            parts = name.split("/")
            if len(parts) >= 2 and parts[-2] == folder and name.endswith(".xml"):
                yield parts[-1], archive.read(name)


def _reference_units(package: Path) -> dict[str, str]:
    """Each flow property's reference unit name, by flow property UUID."""
    groups: dict[str, str] = {}
    for _, content in _documents(package, "unitgroups"):
        root = ElementTree.fromstring(content)
        uuid, ref = _find(root, "UUID"), _find(root, "referenceToReferenceUnit")
        if uuid is None or ref is None:
            continue
        for unit in (u for u in root.iter() if _local(u.tag) == "unit"):
            name = _find(unit, "name")
            if unit.get("dataSetInternalID") == (ref.text or "").strip() and name is not None:
                groups[uuid.text.strip()] = (name.text or "").strip()
    units: dict[str, str] = {}
    for _, content in _documents(package, "flowproperties"):
        root = ElementTree.fromstring(content)
        uuid, group = _find(root, "UUID"), _find(root, "referenceToReferenceUnitGroup")
        if uuid is not None and group is not None and group.get("refObjectId") in groups:
            units[uuid.text.strip()] = groups[group.get("refObjectId")]
    return units


def package_flows(package: Path) -> dict[str, dict]:
    """The package's elementary flows by UUID: name, categories, unit, scaling, version."""
    units = _reference_units(package)
    flows: dict[str, dict] = {}
    for _, content in _documents(package, "flows"):
        root = ElementTree.fromstring(content)
        uuid, name = _find(root, "UUID"), _find(root, "baseName")
        kind = _find(root, "typeOfDataSet")
        if uuid is None or name is None or kind is None:
            continue
        if (kind.text or "").strip() != "Elementary flow":
            continue
        categorisation = _find(root, "elementaryFlowCategorization")
        categories = []
        if categorisation is not None:
            found = [c for c in categorisation if _local(c.tag) == "category"]
            found.sort(key=lambda c: int(c.get("level", "0")))
            categories = [(c.text or "").strip() for c in found]
        ref = _find(root, "referenceToReferenceFlowProperty")
        unit, scaling = None, None
        for prop in (p for p in root.iter() if _local(p.tag) == "flowProperty"):
            if ref is not None and prop.get("dataSetInternalID") == (ref.text or "").strip():
                target = _find(prop, "referenceToFlowPropertyDataSet")
                mean = _find(prop, "meanValue")
                unit = units.get(target.get("refObjectId")) if target is not None else None
                scaling = float(mean.text) if mean is not None and mean.text else None
        version = _find(root, "dataSetVersion")
        flows[uuid.text.strip()] = {
            "name": (name.text or "").strip(),
            "categories": categories,
            "unit": unit,
            "scaling": scaling,
            "version": (version.text or "").strip() if version is not None else "",
        }
    return flows


def mapping_targets(path: Path) -> dict[str, dict]:
    """The randonneur mapping's target by source (biosphere3) UUID; one target each."""
    opener = gzip.open if path.suffix == ".gz" else open
    with opener(path, "rt", encoding="utf-8") as handle:
        data = json.load(handle)
    found: dict[str, list[dict]] = {}
    for verb in ("replace", "update"):
        for row in data.get(verb, []):
            if "target" in row and "uuid" in row.get("source", {}):
                found.setdefault(row["source"]["uuid"], []).append(row["target"])
    return {k: v[0] for k, v in found.items() if len(v) == 1}


def _same(a: str, b: str) -> bool:
    return a.strip().casefold() == b.strip().casefold()


def propose(crosswalk: dict, flows: dict[str, dict], targets: dict[str, dict]):
    """(verified ef-3.1 blocks by crosswalk id, problems): a block per flow with the
    sub-compartments whose proposal the package confirms."""
    blocks: dict[str, dict] = {}
    problems: list[str] = []
    for flow in crosswalk["flows"]:
        bio = flow["biosphere3"]
        for sub, bio_uuid in bio["uuid"].items():
            where = f"{flow['id']} {flow['compartment']}/{sub}"
            target = targets.get(bio_uuid)
            if target is None:
                problems.append(f"{where}: the mapping proposes no EF 3.1 flow")
                continue
            official = flows.get(target.get("uuid", ""))
            if official is None:
                problems.append(f"{where}: {target.get('uuid')} is not in the package")
                continue
            if not _same(official["name"], target.get("name", "")):
                problems.append(f"{where}: package name {official['name']!r} is not the mapping's")
                continue
            if [c.casefold() for c in official["categories"]] != [
                c.casefold() for c in target.get("context", [])
            ]:
                problems.append(f"{where}: package categories differ from the mapping's")
                continue
            unit, scaling = official["unit"], official["scaling"]
            if (
                scaling != 1.0
                or unit not in ("kg", "m3")
                or (unit == "m3") != (bio["unit"] == "m3")
            ):
                problems.append(f"{where}: reference unit {unit!r} (x{scaling}) not handled")
                continue
            block = blocks.setdefault(
                flow["id"], {"name": official["name"], "unit": unit, "uuid": {}, "categories": {}}
            )
            if unit == "m3":
                block["per_kg"] = bio.get("per_kg", 1.0)
            if block["name"] != official["name"] or block["unit"] != unit:
                problems.append(f"{where}: another EF 3.1 flow than its other sub-compartments")
                continue
            block["uuid"][sub] = target["uuid"]
            block["categories"][sub] = official["categories"]
    return blocks, problems


def _block_lines(block: dict) -> list[str]:
    lines = [f"    {LIST}:", f"      name: {json.dumps(block['name'], ensure_ascii=False)}"]
    lines.append(f"      unit: {block['unit']}")
    if "per_kg" in block:
        lines.append(f"      per_kg: {block['per_kg']}")
    lines.append("      uuid:")
    lines += [f"        {sub}: {uuid}" for sub, uuid in block["uuid"].items()]
    lines.append("      categories:")
    lines += [
        f"        {sub}: {json.dumps(cats, ensure_ascii=False)}"
        for sub, cats in block["categories"].items()
    ]
    return lines


def write(text: str, blocks: dict[str, dict], version: str) -> str:
    """*text* (the crosswalk) with the ef-3.1 blocks after each flow and the package version
    in ``source``, its comments kept."""
    lines = text.splitlines()
    out: list[str] = []
    current: str | None = None

    def close() -> None:
        if current in blocks:
            while out and not out[-1].strip():
                out.pop()
            out.extend(_block_lines(blocks[current]))

    for line in lines:
        match = re.match(r"  - id: (\S+)", line)
        if match or (current and line and not line.startswith("    ") and not match):
            close()
            current = match.group(1) if match else None
        if line.startswith(f"  {LIST}:") and current is None:
            line = f"  {LIST}: {json.dumps(version, ensure_ascii=False)}"
        if current and line.startswith(f"    {LIST}:"):
            raise SystemExit(f"{current} already has an {LIST} block: edit it by hand")
        out.append(line)
    close()
    return "\n".join(out) + "\n"


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("package", type=Path, help="the EF 3.1 reference package (zip or folder)")
    parser.add_argument("--mapping", type=Path, required=True, help="randonneur mapping (.gz)")
    parser.add_argument(
        "--package-version", required=True, help="the package's name, version and download URL"
    )
    parser.add_argument("--crosswalk", type=Path, default=CROSSWALK)
    parser.add_argument("--write", action="store_true", help="write the crosswalk")
    args = parser.parse_args(argv)
    text = args.crosswalk.read_text(encoding="utf-8")
    flows = package_flows(args.package)
    if not flows:
        print(f"no elementary flows found in {args.package}", file=sys.stderr)
        return 1
    blocks, problems = propose(yaml.safe_load(text), flows, mapping_targets(args.mapping))
    for flow_id, block in blocks.items():
        for sub, uuid in block["uuid"].items():
            cats = " / ".join(block["categories"][sub])
            print(f"{flow_id} {sub}: {uuid}  {block['name']} [{block['unit']}]  {cats}")
    for problem in problems:
        print(f"TODO {problem}", file=sys.stderr)
    if args.write:
        args.crosswalk.write_text(write(text, blocks, args.package_version), encoding="utf-8")
        print(f"wrote {args.crosswalk}: review the categories each sub-compartment maps to")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
