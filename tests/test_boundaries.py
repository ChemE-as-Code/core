"""The import rules of docs/framework/architecture.md, checked on every module's source.

Every ``import`` in ``src/chemeascode`` counts, including those inside functions. A rule that
today's code still breaks is listed in ``EXCEPTIONS`` with the reason; an exception that is no
longer needed fails the test, so the list only shrinks.
"""

from __future__ import annotations

import ast
import subprocess
import sys
from pathlib import Path

import pytest

SRC = Path(__file__).resolve().parents[1] / "src"
PACKAGE = SRC / "chemeascode"

#: Which domains each domain may import (architecture.md, "Allowed domain-to-domain imports").
DOMAINS = {
    "requirements": set(),
    "chemistry": {"requirements"},
    "experiments": {"requirements", "chemistry"},
    "process": {"requirements", "chemistry", "experiments"},
    "equipment": {"requirements", "process"},
    "piping": {"process", "equipment"},
    "control": {"process", "equipment", "piping"},
    "safety": {"chemistry", "process", "equipment", "piping", "control"},
    "assessment": {"requirements", "process", "equipment"},
    "spatial": {"equipment", "piping", "control", "safety"},
}
#: Optional or interface-only libraries, and the layers that may import them.
LIBRARIES = {
    "typer": {"interfaces.cli"},
    "fastapi": {"interfaces.api"},
    "uvicorn": {"interfaces.api"},
}
#: Libraries of an extra: imported inside functions only, never at module level.
LAZY_ONLY = {
    "fastapi",
    "uvicorn",
    "thermo",
    "chemicals",
    "resvg_py",
    "pint",
    "rdkit",
    "bw2data",
    "bw2calc",
    "cantera",
    # the IDAES worker's (integrations/idaes_worker.py), which runs in its own Python (ADR 0039)
    "idaes",
    "pyomo",
}

#: (importing module, imported module or library) -> why the rule is broken for now.
EXCEPTIONS = {
    ("chemeascode.foundation.workspace", "typer"): (
        "check_requirement prints the finding and exits; the CLI should get its own wrapper "
        "around requirement_problem"
    ),
    ("chemeascode.integrations.git", "chemeascode.domains.piping.render"): (
        "the git textconv driver prints a readable projection of a P&ID: piping logic that "
        "belongs in domains/piping, with integrations/git.py keeping only the git setup"
    ),
    ("chemeascode.foundation.workspace", "chemeascode.schemas"): (
        "Workspace.parsed_lists validates each engineering list against its domain's schema "
        "through the catalogue's LIST_SCHEMAS; the callers (project.status, process.streams) "
        "could pass the schemas in instead"
    ),
}


def _module_name(path: Path) -> str:
    parts = path.relative_to(SRC).with_suffix("").parts
    return ".".join(parts[:-1] if parts[-1] == "__init__" else parts)


def _sources() -> list[Path]:
    """Every Python module of the package; template data and skill resources are not code."""
    found = []
    for path in sorted(PACKAGE.rglob("*.py")):
        parts = path.relative_to(PACKAGE).parts
        if parts[:2] == ("templates", "project") or "skills" in parts:
            continue
        found.append(path)
    return found


def _imports(path: Path) -> list[tuple[str, bool]]:
    """``(module, lazy)`` for every import in *path*; relative imports resolved."""
    name = _module_name(path)
    package = name if path.name == "__init__.py" else name.rpartition(".")[0]
    tree = ast.parse(path.read_text(encoding="utf-8"))
    top = {id(node) for node in tree.body}
    found = []
    for node in ast.walk(tree):
        lazy = id(node) not in top
        if isinstance(node, ast.Import):
            found += [(alias.name, lazy) for alias in node.names]
        elif isinstance(node, ast.ImportFrom):
            if node.level:
                base = package.split(".")[: len(package.split(".")) - node.level + 1]
                module = ".".join([*base, node.module] if node.module else base)
            else:
                module = node.module or ""
            if node.module is None or module == "chemeascode":
                # ``from chemeascode import x``: x is a submodule
                found += [(f"{module}.{alias.name}", lazy) for alias in node.names]
            else:
                found.append((module, lazy))
    return found


def _layer(module: str) -> str:
    """``foundation``, ``domains.<d>``, ``project``, ``interfaces.cli``, ``interfaces.api``,
    ``integrations``, ``templates``, ``schemas`` or ``root``."""
    parts = module.split(".")[1:]
    if not parts or parts[0] in {"__main__"}:
        return "root"
    if parts[0] in {"domains", "interfaces"} and len(parts) > 1:
        return f"{parts[0]}.{parts[1]}"
    return parts[0]


def _allowed(source: str, target: str) -> bool:
    if source == target or target in {"root"}:
        return target != "root" or source == "root"
    if target == "schemas":
        # the catalogue re-exports every owner's schemas, so only the layers above the domains
        # may read it; a domain imports its own schema module or that of a domain it may import
        return source in {"root", "project"} or source.startswith("interfaces.")
    if source == "root":
        return True
    if source == "foundation":
        return False
    if source == "integrations":
        return target == "foundation"
    if source == "templates":
        return target == "foundation"
    if source.startswith("domains."):
        if target in {"foundation", "integrations"}:
            return True
        return target.startswith("domains.") and target.split(".")[1] in DOMAINS[source[8:]]
    if source == "project":
        return target in {"foundation", "integrations"} or target.startswith("domains.")
    if source.startswith("interfaces."):
        return not target.startswith("interfaces.") and target != "root"
    if source == "schemas":
        return target == "foundation" or target.startswith("domains.")
    raise AssertionError(f"no rule for layer {source}")


def _violations() -> dict[tuple[str, str], str]:
    found: dict[tuple[str, str], str] = {}
    for path in _sources():
        source = _module_name(path)
        for target, lazy in _imports(path):
            where = f"{path.relative_to(SRC)}: {source} imports {target}"
            library = target.split(".")[0]
            owners = LIBRARIES.get(library, set())
            if library in LAZY_ONLY and not lazy and _layer(source) not in owners:
                found[(source, library)] = f"{where} at module level"
            if library in LIBRARIES and not any(
                _layer(source) == layer for layer in LIBRARIES[library]
            ):
                found[(source, library)] = where
            if library != "chemeascode":
                continue
            if (_layer(source), _layer(target)) == ("interfaces.cli", "interfaces.api") and lazy:
                continue  # `cheme serve` starts the API inside the command
            if not _allowed(_layer(source), _layer(target)):
                key = next(
                    (
                        k
                        for k in EXCEPTIONS
                        if k[0] == source and (target == k[1] or target.startswith(k[1] + "."))
                    ),
                    (source, target),
                )
                found[key] = where
    return found


def test_imports_follow_the_layer_rules():
    violations = _violations()
    unexpected = sorted(where for key, where in violations.items() if key not in EXCEPTIONS)
    assert not unexpected, "\n".join(unexpected)


def test_every_exception_is_still_needed():
    violations = _violations()
    stale = sorted(f"{a} -> {b}" for a, b in EXCEPTIONS if (a, b) not in violations)
    assert not stale, "no longer needed, remove from EXCEPTIONS: " + ", ".join(stale)


@pytest.mark.parametrize(
    ("source", "target", "allowed"),
    [
        ("domains.piping", "domains.process", True),
        ("domains.process", "domains.piping", False),
        ("foundation", "domains.process", False),
        ("domains.safety", "project", False),
        ("interfaces.cli", "interfaces.api", False),
        ("project", "domains.spatial", True),
        ("integrations", "foundation", True),
        ("schemas", "domains.control", True),
        ("interfaces.cli", "schemas", True),
        ("domains.spatial", "schemas", False),
        ("foundation", "schemas", False),
    ],
)
def test_layer_rules(source, target, allowed):
    assert _allowed(source, target) is allowed


def _imports_upward(source: str, target: str) -> bool:
    """Whether module *source*, in foundation or a domain, imports *target* from interfaces,
    project or templates. Independent of ``_allowed`` and ``EXCEPTIONS``."""
    if not source.startswith(("chemeascode.foundation", "chemeascode.domains")):
        return False
    if target != "chemeascode" and not target.startswith("chemeascode."):
        return False
    layer = _layer(target)
    return layer.startswith("interfaces") or layer in {"project", "templates"}


@pytest.mark.parametrize(
    ("source", "target", "upward"),
    [
        ("chemeascode.domains.safety.hazop", "chemeascode.project.validate", True),
        ("chemeascode.domains.process.model", "chemeascode.interfaces.cli.process", True),
        ("chemeascode.foundation.workspace", "chemeascode.templates.install", True),
        ("chemeascode.domains.piping.render", "chemeascode.domains.process.model", False),
        ("chemeascode.domains.process.model", "chemeascode.foundation.units", False),
        ("chemeascode.project.validate", "chemeascode.interfaces.cli", False),
        ("chemeascode.domains.process.model", "project", False),
    ],
)
def test_imports_upward_detects_a_synthetic_violation(source, target, upward):
    assert _imports_upward(source, target) is upward


def test_foundation_and_domains_never_import_interfaces_project_or_templates():
    """Spelled out separately from the layer table, the rule most worth keeping."""
    found = [
        f"{_module_name(path)} imports {target}"
        for path in _sources()
        for target, _ in _imports(path)
        if _imports_upward(_module_name(path), target)
    ]
    assert not found, "\n".join(found)


def test_package_inits_import_nothing():
    """``chemeascode.foundation`` and every domain package ``__init__`` stay import-free, so
    importing a package never pulls in a dependency."""
    inits = [PACKAGE / "foundation" / "__init__.py"]
    inits += sorted((PACKAGE / "domains").glob("*/__init__.py"))
    found = [f"{path.relative_to(SRC)}: {target}" for path in inits for target, _ in _imports(path)]
    assert not found, "\n".join(found)


#: The modules that call pyDEXPI's model loader or serializer directly. Everything else loads
#: and exports DEXPI models through domains.piping.dexpi_io; process/sheets.py may not import
#: piping, and changing it would also change the BFD/PFD generator fingerprint.
DEXPI_IO = {"chemeascode.domains.piping.dexpi_io", "chemeascode.domains.process.sheets"}
DEXPI_IO_NAMES = {"load_xml_with_report", "DexpiXmlSerializer"}


def test_dexpi_models_load_and_export_through_one_module():
    found = []
    for path in _sources():
        source = _module_name(path)
        for node in ast.walk(ast.parse(path.read_text(encoding="utf-8"))):
            if not isinstance(node, ast.ImportFrom) or not (node.module or "").startswith(
                "pydexpi.loaders"
            ):
                continue
            names = {alias.name for alias in node.names} & DEXPI_IO_NAMES
            if names and source not in DEXPI_IO:
                found.append(f"{source} imports {', '.join(sorted(names))}")
    assert not found, "\n".join(found)


#: Imported in a fresh interpreter: the base package, foundation, every domain, and the
#: Python entry points a downstream application calls.
BASIC_IMPORTS = [
    "chemeascode",
    "chemeascode.foundation",
    *(
        _module_name(p)
        for p in sorted((PACKAGE / "foundation").glob("*.py"))
        if p.name != "__init__.py"
    ),
    *(f"chemeascode.domains.{d}" for d in DOMAINS),
    "chemeascode.domains.process.model",
    "chemeascode.domains.process.streams",
    "chemeascode.domains.process.thermodynamics.model_selection",
    "chemeascode.domains.process.thermodynamics.phase",
    "chemeascode.domains.process.separations.selection",
    "chemeascode.domains.process.heat_integration.pinch",
    "chemeascode.domains.process.electrochemical_cell",
    "chemeascode.domains.experiments.electrochemistry",
    "chemeascode.domains.process.electrolysis_duty",
    "chemeascode.domains.process.electrolysis_plots",
    "chemeascode.domains.equipment.electrolyser_stack",
    "chemeascode.domains.chemistry.anolyte",
    "chemeascode.domains.chemistry.carbonate",
    "chemeascode.domains.chemistry.properties",
    "chemeascode.integrations.rdkit",
    "chemeascode.schemas",
    "chemeascode.project.validate",
    "chemeascode.project.impact",
    "chemeascode.templates.install",
]
#: Optional extras (props, serve, png, units, chemistry) and the CLI library.
OPTIONAL = [
    "thermo",
    "chemicals",
    "fastapi",
    "starlette",
    "uvicorn",
    "resvg_py",
    "typer",
    "pint",
    "rdkit",
    "bw2data",
    "bw2calc",
    "cantera",
]


def test_basic_imports_load_no_optional_dependency():
    code = (
        "import sys\n"
        + "".join(f"import {name}\n" for name in BASIC_IMPORTS)
        + f"print(sorted(m for m in {OPTIONAL!r} if m in sys.modules))\n"
    )
    result = subprocess.run(
        [sys.executable, "-W", "error", "-c", code], check=False, capture_output=True, text=True
    )
    assert result.returncode == 0, result.stderr
    assert result.stdout.strip() == "[]", result.stdout
