"""The bundled skills are generic: none names a tag, line, structure or zone of the example
plants (their decisions live in each plant's own DESIGN.md and YAML, not in cheme-as-code)."""

import json
import re
from pathlib import Path

from chemeascode.templates.install import bundled_files

DATA = Path(__file__).parent / "data"


def example_names() -> set[str]:
    """Equipment tags, line numbers, structure, building, rack and zone ids of the example
    plants frozen in ``tests/data`` (the ASU layout fixture and its process model)."""
    data = json.loads((DATA / "api-layout-asu.json").read_text(encoding="utf-8"))
    model = data["model"]
    names = {item["tag"] for item in model["equipment"]}
    names |= {pipe["line"] for pipe in model["pipes"]}
    names |= {s["id"] for s in model["structures"]}
    names |= {z["id"] for z in model["zones"]}
    names |= {b["id"] for b in model["buildings"]} | {r["id"] for r in model["racks"]}
    for path in (DATA / "process-asu").rglob("*.yaml"):
        names |= set(re.findall(r"\b[A-Z]{1,4}-\d{3,4}[A-Z]?\b", path.read_text(encoding="utf-8")))
    # short generic ids (B1, PR1, ...) are too common to be the example's own
    return {name for name in names if re.search(r"\d{3}", name)}


def test_no_bundled_skill_names_an_example_plant():
    names = example_names()
    assert len(names) > 50  # the fixture holds the example's tags
    pattern = re.compile(r"(?<![\w-])(" + "|".join(map(re.escape, sorted(names))) + r")(?![\w-])")
    found = []
    for skill, files in bundled_files().items():
        for name, path in files.items():
            if path.suffix not in (".md", ".yaml", ".yml", ".txt", ".py", ".json", ".xml"):
                continue
            for k, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
                for match in pattern.finditer(line):
                    found.append(f"{skill}/{name}:{k}: {match.group(1)}")
    assert not found, "bundled skills name example plant ids:\n" + "\n".join(found[:40])
