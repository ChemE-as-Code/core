"""``cheme init`` writes exactly the files listed in ``data/init-manifest.txt``.

The manifest holds one ``<sha256>  <relative path>`` line per file a fresh ``init`` writes. It
pins the project template and the bundled skills, wherever their sources live in the package.
The cheme-as-code minor version substituted into ``plant.yaml`` is put back to its placeholder
before hashing, so a version bump does not change the manifest.

After an intended template or skill change, regenerate it::

    uv run python tests/test_init_golden.py > tests/data/init-manifest.txt
"""

from __future__ import annotations

import hashlib
import sys
import tempfile
from pathlib import Path

import pytest

from chemeascode.templates.install import _minor_version, init

MANIFEST = Path(__file__).parent / "data" / "init-manifest.txt"
NAME = "Golden Plant"


def manifest_of(target: Path) -> str:
    """The manifest lines for the files ``init`` writes into *target* (which must be empty)."""
    written = init(target, NAME)
    requires = f"cheme-as-code>={_minor_version()}".encode()
    lines = []
    for path in sorted(written, key=lambda p: p.relative_to(target).as_posix()):
        data = path.read_bytes()
        if path.name == "plant.yaml":
            data = data.replace(requires, b"cheme-as-code>={{cheme_minor}}")
        lines.append(f"{hashlib.sha256(data).hexdigest()}  {path.relative_to(target).as_posix()}")
    return "\n".join(lines) + "\n"


def test_init_writes_the_golden_tree(tmp_path):
    assert manifest_of(tmp_path / "plant") == MANIFEST.read_text(encoding="utf-8")


def test_init_installs_skills_under_dot_claude(tmp_path):
    names = {line.split("  ", 1)[1] for line in MANIFEST.read_text(encoding="utf-8").splitlines()}
    skills = {n.split("/")[2] for n in names if n.startswith(".claude/skills/")}
    skills.remove("NOTICE.md")
    assert skills == {
        "dexpi-xml",
        "layout-yaml",
        "pipe-routing",
        "structures-access",
        "area-classification",
        "hazop-study",
        "hazop-assessment",
        "hazop-review",
        "lists-sync",
        "pid-draft",
        "pid-edit",
        "process-design",
        "phase-calculation",
        "process-simulation",
        "thermodynamic-model-selection",
        "separation-method-selection",
        "property-retrieval",
        "materials",
        "reactions",
        "reaction-evidence-search",
        "route-selection",
        "review",
        "mto-estimate",
        "lca",
        "lci-estimate",
        "tea",
        "electrical-cabling",
        "control-loops",
        "control-sequences",
        "control-narrative",
        "hvac-ducts",
        "datasheets",
        "skid-design",
        "electrochemical-cell-modelling",
        "electrolysis-duty-assessment",
        "experiment-reproduction",
        "flowsheet-development",
        "flowsheet-diagram-types",
        "flowsheet-process-model-vocabulary",
        "flowsheet-stream-data",
        "heat-integration",
        "heat-integration-flowsheet-review",
        "heat-integration-minimum-utility-targets",
        "heat-integration-multiple-utilities",
        "heat-integration-network-design",
        "heat-integration-pinch-analysis",
        "heat-integration-stream-data",
        "tech-gas-acid-gas-removal",
        "tech-gas-dehydration",
        "tech-gas-inlet-and-separation",
        "tech-gas-lng-liquefaction",
        "tech-gas-ngl-recovery",
        "tech-gas-nitrogen-and-mercury",
        "tech-gas-processing",
        "tech-gas-sulfur-recovery",
        "tech-heavy-chem-air-separation",
        "tech-heavy-chem-chlor-alkali",
        "tech-heavy-chem-kraft-pulping",
        "tech-heavy-chem-nitric-acid-and-fertilizers",
        "tech-heavy-chem-pigments-and-minerals",
        "tech-heavy-chem-reaction-families",
        "tech-heavy-chem-sulfuric-acid",
        "tech-heavy-chemicals",
        "tech-petchem-ammonia-and-urea",
        "tech-petchem-aromatics",
        "tech-petchem-methanol-and-syngas",
        "tech-petchem-olefins",
        "tech-petchem-oxygenates",
        "tech-petchem-polymers",
        "tech-petchem-styrene-and-phenol",
        "tech-petrochemicals",
        "tech-refining",
        "tech-refining-catalytic-cracking",
        "tech-refining-crude-and-vacuum-distillation",
        "tech-refining-hydrogen-and-sulfur",
        "tech-refining-hydroprocessing",
        "tech-refining-reforming-and-isomerisation",
        "tech-refining-residue-upgrading",
        "tech-refining-treating-and-blending",
        "unit-operations",
        "unit-ops-absorption-and-stripping",
        "unit-ops-adsorption-and-drying",
        "unit-ops-distillation",
        "unit-ops-evaporation",
        "unit-ops-heat-transfer",
        "unit-ops-liquid-liquid-extraction",
        "unit-ops-phase-separation",
        "unit-ops-reactors",
        "unit-ops-refrigeration",
        "utility-air-and-inert-gas",
        "utility-boiler-feed-water",
        "utility-cooling-water",
        "utility-fuel-systems",
        "utility-steam-and-condensate",
        "utility-systems",
        "control-safeguarding-and-interlocks",
        "hazop-equipment-causes",
        "pid-design",
        "pid-design-compressors",
        "pid-design-control-valve-selection",
        "pid-design-control-valve-station",
        "pid-design-heat-exchangers",
        "pid-design-instrumentation",
        "pid-design-isolation-vents-drains",
        "pid-design-materials-and-spec-breaks",
        "pid-design-pressure-relief",
        "pid-design-pumps",
        "pid-design-vessels-and-tanks",
        "pid-review-commissioning-readiness",
        "pid-review-design-review",
        "process-safety",
        "relief-scenarios",
        "safeguard-crediting",
    }
    assert all(f".claude/skills/{s}/SKILL.md" in names for s in skills)


def test_bundled_skills_live_with_their_owners():
    from chemeascode.templates.install import bundled_skills

    # <owner>/skills/<name>/
    owners = {name: Path(str(skill)).parents[1].name for name, skill in bundled_skills().items()}
    assert owners == {
        "dexpi-xml": "piping",
        "lists-sync": "piping",
        "pid-draft": "piping",
        "pid-edit": "piping",
        "process-design": "process",
        "phase-calculation": "process",
        "process-simulation": "process",
        "thermodynamic-model-selection": "process",
        "separation-method-selection": "process",
        "layout-yaml": "spatial",
        "pipe-routing": "spatial",
        "structures-access": "spatial",
        "area-classification": "safety",
        "hazop-study": "safety",
        "hazop-assessment": "safety",
        "hazop-review": "safety",
        "property-retrieval": "chemistry",
        "materials": "chemistry",
        "reactions": "chemistry",
        "reaction-evidence-search": "chemistry",
        "route-selection": "chemistry",
        "review": "project",
        "mto-estimate": "assessment",
        "lca": "assessment",
        "lci-estimate": "assessment",
        "tea": "assessment",
        "electrical-cabling": "control",
        "control-loops": "control",
        "control-sequences": "control",
        "control-narrative": "control",
        "hvac-ducts": "spatial",
        "datasheets": "equipment",
        "skid-design": "equipment",
        "electrochemical-cell-modelling": "process",
        "electrolysis-duty-assessment": "process",
        "experiment-reproduction": "experiments",
        "flowsheet-development": "process",
        "flowsheet-diagram-types": "process",
        "flowsheet-process-model-vocabulary": "process",
        "flowsheet-stream-data": "process",
        "heat-integration": "process",
        "heat-integration-flowsheet-review": "process",
        "heat-integration-minimum-utility-targets": "process",
        "heat-integration-multiple-utilities": "process",
        "heat-integration-network-design": "process",
        "heat-integration-pinch-analysis": "process",
        "heat-integration-stream-data": "process",
        "tech-gas-acid-gas-removal": "process",
        "tech-gas-dehydration": "process",
        "tech-gas-inlet-and-separation": "process",
        "tech-gas-lng-liquefaction": "process",
        "tech-gas-ngl-recovery": "process",
        "tech-gas-nitrogen-and-mercury": "process",
        "tech-gas-processing": "process",
        "tech-gas-sulfur-recovery": "process",
        "tech-heavy-chem-air-separation": "process",
        "tech-heavy-chem-chlor-alkali": "process",
        "tech-heavy-chem-kraft-pulping": "process",
        "tech-heavy-chem-nitric-acid-and-fertilizers": "process",
        "tech-heavy-chem-pigments-and-minerals": "process",
        "tech-heavy-chem-reaction-families": "process",
        "tech-heavy-chem-sulfuric-acid": "process",
        "tech-heavy-chemicals": "process",
        "tech-petchem-ammonia-and-urea": "process",
        "tech-petchem-aromatics": "process",
        "tech-petchem-methanol-and-syngas": "process",
        "tech-petchem-olefins": "process",
        "tech-petchem-oxygenates": "process",
        "tech-petchem-polymers": "process",
        "tech-petchem-styrene-and-phenol": "process",
        "tech-petrochemicals": "process",
        "tech-refining": "process",
        "tech-refining-catalytic-cracking": "process",
        "tech-refining-crude-and-vacuum-distillation": "process",
        "tech-refining-hydrogen-and-sulfur": "process",
        "tech-refining-hydroprocessing": "process",
        "tech-refining-reforming-and-isomerisation": "process",
        "tech-refining-residue-upgrading": "process",
        "tech-refining-treating-and-blending": "process",
        "unit-operations": "process",
        "unit-ops-absorption-and-stripping": "process",
        "unit-ops-adsorption-and-drying": "process",
        "unit-ops-distillation": "process",
        "unit-ops-evaporation": "process",
        "unit-ops-heat-transfer": "process",
        "unit-ops-liquid-liquid-extraction": "process",
        "unit-ops-phase-separation": "process",
        "unit-ops-reactors": "process",
        "unit-ops-refrigeration": "process",
        "utility-air-and-inert-gas": "process",
        "utility-boiler-feed-water": "process",
        "utility-cooling-water": "process",
        "utility-fuel-systems": "process",
        "utility-steam-and-condensate": "process",
        "utility-systems": "process",
        "control-safeguarding-and-interlocks": "control",
        "hazop-equipment-causes": "safety",
        "pid-design": "piping",
        "pid-design-compressors": "piping",
        "pid-design-control-valve-selection": "piping",
        "pid-design-control-valve-station": "piping",
        "pid-design-heat-exchangers": "piping",
        "pid-design-instrumentation": "piping",
        "pid-design-isolation-vents-drains": "piping",
        "pid-design-materials-and-spec-breaks": "piping",
        "pid-design-pressure-relief": "piping",
        "pid-design-pumps": "piping",
        "pid-design-vessels-and-tanks": "piping",
        "pid-review-commissioning-readiness": "piping",
        "pid-review-design-review": "piping",
        "process-safety": "safety",
        "relief-scenarios": "safety",
        "safeguard-crediting": "safety",
    }


def test_two_skills_of_one_name_are_refused(tmp_path, monkeypatch):
    import chemeascode.templates.install as install

    package = tmp_path / "chemeascode"
    for owner in ("domains/a", "domains/b"):
        skill = package / owner / "skills" / "same"
        skill.mkdir(parents=True)
        (skill / "SKILL.md").write_text("x")
    (package / "project").mkdir()
    monkeypatch.setattr(install, "files", lambda name: package)
    with pytest.raises(ValueError, match="'same'"):
        install.bundled_skills()


def test_init_keeps_a_locally_changed_skill_unless_forced(tmp_path):
    target = tmp_path / "plant"
    init(target, NAME)
    skill = target / ".claude/skills/review/SKILL.md"
    skill.write_text("local instructions\n")
    (target / "plant.yaml").unlink()
    init(target, NAME)
    assert skill.read_text() == "local instructions\n"
    init(target, NAME, force=True)
    assert skill.read_text() != "local instructions\n"


if __name__ == "__main__":
    with tempfile.TemporaryDirectory() as tmp:
        sys.stdout.write(manifest_of(Path(tmp) / "plant"))
