"""Risk matrices (``cheme/risk-matrix/v1``) and the one lookup of a band.

A matrix declares its bands (lowest risk first: that list is the band order), its likelihood
and severity grades, the categories a consequence is rated in, and the cells: for every
severity and likelihood code, the band, shared by all categories or given per category. The
lookup (:func:`lookup`) only reads a cell. It never multiplies codes, interpolates, sorts bands
by name or falls back to a band: a missing input, an unknown code or a missing cell is a
problem, not a result.

Rules (``cheme.risk-matrix-*``), each finding naming the file, line, rule and a hint:

- ``risk-matrix-schema``: the file is not valid YAML or does not follow the schema;
- ``risk-matrix-duplicate``: a band, grade or category declared twice, or a key given twice
  in one mapping (two cells for one severity and likelihood: YAML keeps only the last);
- ``risk-matrix-unknown-code``: a cell under a severity or likelihood code the matrix does not
  declare, or a category description of an undeclared category;
- ``risk-matrix-unknown-band``: a cell naming no declared band;
- ``risk-matrix-incomplete``: a category without a band for some severity and likelihood.

A matrix with an error gives no bands at all (:attr:`LoadedMatrix.usable`).
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import yaml
from pydantic import ValidationError

from chemeascode.domains.safety.schemas import RiskMatrix
from chemeascode.foundation.findings import Finding
from chemeascode.foundation.provenance import value_fingerprint
from chemeascode.foundation.yamlsource import _yaml_line

#: The example matrix of the package (``cheme init`` writes it as ``safety/risk-matrix.yaml``).
EXAMPLE_MATRIX = Path(__file__).parent / "data" / "risk-matrix-example.yaml"
MATRIX_FILE = "safety/risk-matrix.yaml"


@dataclass(frozen=True)
class Lookup:
    """The band of one rating, or why there is none."""

    band: str | None
    #: The band's position in the matrix's order, 0 the lowest risk.
    rank: int | None = None
    #: ``missing`` (no severity or likelihood given), ``unknown-category``,
    #: ``unknown-severity``, ``unknown-likelihood`` or ``no-cell``; empty when there is a band.
    problem: str = ""
    message: str = ""


@dataclass
class LoadedMatrix:
    """A matrix file: its model (None when it does not load) and its findings."""

    path: str
    model: RiskMatrix | None
    findings: list[Finding] = field(default_factory=list)
    #: The matrix's fingerprint (:func:`matrix_fingerprint`); empty when it does not load.
    fingerprint: str = ""

    @property
    def usable(self) -> bool:
        """It loads and has no error: bands may be looked up."""
        return self.model is not None and not any(f.level == "error" for f in self.findings)


def matrix_fingerprint(matrix: RiskMatrix) -> str:
    """The fingerprint of everything the matrix states (comments and layout are not part of
    it): any change to a band, a grade, a description or a cell changes it. Its acceptance
    (``status``, ``accepted_by``) is not part of it, so accepting the criteria changes no band
    (and a matrix written before those fields keeps its fingerprint)."""
    return value_fingerprint(
        matrix.model_dump(mode="json", by_alias=True, exclude={"status", "accepted_by"})
    )


def duplicate_keys(document: Any, file: str, rule: str) -> list[Finding]:
    """A finding for every key a YAML mapping of the node tree *document* repeats (YAML
    keeps the last one and silently drops the others)."""
    found: list[Finding] = []

    def walk(node: Any, where: list[str]) -> None:
        if isinstance(node, yaml.MappingNode):
            seen: set[str] = set()
            for key, value in node.value:
                name = key.value if isinstance(key, yaml.ScalarNode) else str(key)
                if name in seen:
                    at = ".".join([*where, name])
                    found.append(
                        Finding(
                            file,
                            "error",
                            rule,
                            f"{at} is given twice; only the last one would be read",
                            line=key.start_mark.line + 1,
                            ids=[name],
                            key=at,
                            hint="keep one entry",
                        )
                    )
                seen.add(name)
                walk(value, [*where, name])
        elif isinstance(node, yaml.SequenceNode):
            for i, item in enumerate(node.value):
                walk(item, [*where, str(i)])

    walk(document, [])
    return found


def category_cells(matrix: RiskMatrix, category: str) -> dict[str, dict[str, str]] | None:
    """The cells of *category*: its own, else the matrix's."""
    for cat in matrix.categories:
        if cat.id == category:
            return cat.cells if cat.cells is not None else matrix.cells
    return None


def lookup(
    matrix: RiskMatrix, category: str, severity: str | None, likelihood: str | None
) -> Lookup:
    """The band of *severity* and *likelihood* in *category* of *matrix*: the cell, nothing
    else. Check the matrix first (:func:`load_matrix`); a missing cell is reported, never
    filled in."""
    if severity is None or likelihood is None:
        missing = " and ".join(
            what for what, v in (("severity", severity), ("likelihood", likelihood)) if v is None
        )
        return Lookup(None, problem="missing", message=f"no {missing} given")
    if category not in {c.id for c in matrix.categories}:
        known = ", ".join(c.id for c in matrix.categories)
        return Lookup(
            None,
            problem="unknown-category",
            message=f"category {category!r} is not in matrix {matrix.id} ({known})",
        )
    if severity not in {s.code for s in matrix.severity}:
        known = ", ".join(s.code for s in matrix.severity)
        return Lookup(
            None,
            problem="unknown-severity",
            message=f"severity {severity!r} is not in matrix {matrix.id} ({known})",
        )
    if likelihood not in {g.code for g in matrix.likelihood}:
        known = ", ".join(g.code for g in matrix.likelihood)
        return Lookup(
            None,
            problem="unknown-likelihood",
            message=f"likelihood {likelihood!r} is not in matrix {matrix.id} ({known})",
        )
    band = ((category_cells(matrix, category) or {}).get(severity) or {}).get(likelihood)
    order = [b.id for b in matrix.bands]
    if band is None or band not in order:
        return Lookup(
            None,
            problem="no-cell",
            message=f"matrix {matrix.id} has no band for {category} severity {severity}, "
            f"likelihood {likelihood}",
        )
    return Lookup(band, rank=order.index(band))


def band_rank(matrix: RiskMatrix, band: str) -> int | None:
    """The position of *band* in the matrix's order (0: lowest risk), None when undeclared."""
    order = [b.id for b in matrix.bands]
    return order.index(band) if band in order else None


def matrix_rules(matrix: RiskMatrix, document: Any, file: str) -> list[Finding]:
    """Every ``cheme.risk-matrix-*`` finding of a loaded *matrix* (YAML nodes *document*)."""
    findings: list[Finding] = []

    def add(rule: str, message: str, loc: list[Any], ids: list[str], hint: str, key: str = ""):
        findings.append(
            Finding(
                file,
                "error",
                f"cheme.risk-matrix-{rule}",
                message,
                line=_yaml_line(document, loc),
                ids=ids,
                hint=hint,
                key=key,
            )
        )

    for where, entries, attr in (
        ("bands", matrix.bands, "id"),
        ("likelihood", matrix.likelihood, "code"),
        ("severity", matrix.severity, "code"),
        ("categories", matrix.categories, "id"),
    ):
        seen: set[str] = set()
        for i, entry in enumerate(entries):
            value = getattr(entry, attr)
            if value in seen:
                add(
                    "duplicate",
                    f"{where}: {value} is declared twice",
                    [where, i],
                    [value],
                    "give each one its own code",
                    key=f"{where}:{value}",
                )
            seen.add(value)
    bands = {b.id for b in matrix.bands}
    severities = [s.code for s in matrix.severity]
    likelihoods = [g.code for g in matrix.likelihood]
    categories = {c.id for c in matrix.categories}
    for i, grade in enumerate(matrix.severity):
        for cat in grade.descriptions:
            if cat not in categories:
                add(
                    "unknown-code",
                    f"severity {grade.code}: description of category {cat!r}, which the "
                    "matrix does not declare",
                    ["severity", i, "descriptions", cat],
                    [grade.code, cat],
                    f"declare it under categories, or name one of {', '.join(sorted(categories))}",
                    key=f"severity:{grade.code}:{cat}",
                )

    def check_cells(cells: dict[str, dict[str, str]], loc: list[Any], label: str) -> None:
        for sev, row in cells.items():
            if sev not in severities:
                add(
                    "unknown-code",
                    f"{label}: severity {sev!r} is not declared",
                    [*loc, sev],
                    [sev],
                    f"use a severity code ({', '.join(severities)})",
                    key=f"{label}:{sev}",
                )
            for lik, band in row.items():
                if lik not in likelihoods:
                    add(
                        "unknown-code",
                        f"{label}: likelihood {lik!r} (severity {sev}) is not declared",
                        [*loc, sev, lik],
                        [lik],
                        f"use a likelihood code ({', '.join(likelihoods)})",
                        key=f"{label}:{sev}:{lik}",
                    )
                if band not in bands:
                    add(
                        "unknown-band",
                        f"{label}: severity {sev}, likelihood {lik} names band {band!r}, which "
                        "is not declared",
                        [*loc, sev, lik],
                        [band],
                        f"name a band ({', '.join(b.id for b in matrix.bands)})",
                        key=f"{label}:{sev}:{lik}",
                    )

    if matrix.cells is not None:
        check_cells(matrix.cells, ["cells"], "cells")
    for i, cat in enumerate(matrix.categories):
        if cat.cells is not None:
            check_cells(cat.cells, ["categories", i, "cells"], f"category {cat.id} cells")
        cells = cat.cells if cat.cells is not None else matrix.cells
        missing = [
            f"{sev}/{lik}"
            for sev in severities
            for lik in likelihoods
            if ((cells or {}).get(sev) or {}).get(lik) is None
        ]
        if missing:
            shown = ", ".join(missing[:8]) + (
                f" and {len(missing) - 8} more" if len(missing) > 8 else ""
            )
            add(
                "incomplete",
                f"category {cat.id}: no band for severity/likelihood {shown}",
                ["categories", i],
                [cat.id],
                "give a band for every severity and likelihood code (under cells, or the "
                "category's own cells); no cell is ever assumed",
                key=f"category:{cat.id}",
            )
    return findings


def load_matrix(root: Path, path: str) -> LoadedMatrix:
    """Load and check the matrix *path* (from *root*)."""
    file = root / path
    if not file.is_file():
        return LoadedMatrix(
            path,
            None,
            [
                Finding(
                    path,
                    "error",
                    "cheme.risk-matrix-schema",
                    f"risk matrix {path} does not exist",
                    hint="write it (schema: cheme schema risk-matrix), or name the study's "
                    "matrix under risk_matrix:",
                )
            ],
        )
    text = file.read_text(encoding="utf-8")
    try:
        document = yaml.compose(text)
        data = yaml.safe_load(text)
    except yaml.YAMLError as failure:
        mark = getattr(failure, "problem_mark", None)
        return LoadedMatrix(
            path,
            None,
            [
                Finding(
                    path,
                    "error",
                    "cheme.risk-matrix-schema",
                    f"not valid YAML: {str(failure).splitlines()[0]}",
                    line=mark.line + 1 if mark is not None else None,
                    hint="fix the YAML syntax",
                )
            ],
        )
    findings = duplicate_keys(document, path, "cheme.risk-matrix-duplicate")
    try:
        matrix = RiskMatrix.model_validate(data or {})
    except ValidationError as failure:
        for error in failure.errors():
            loc = list(error["loc"])
            findings.append(
                Finding(
                    path,
                    "error",
                    "cheme.risk-matrix-schema",
                    f"{'.'.join(str(p) for p in loc) or 'file'}: {error['msg']}",
                    line=_yaml_line(document, loc),
                    key=".".join(str(p) for p in loc),
                    hint="see cheme schema risk-matrix",
                )
            )
        return LoadedMatrix(path, None, findings)
    findings += matrix_rules(matrix, document, path)
    return LoadedMatrix(path, matrix, findings, matrix_fingerprint(matrix))
