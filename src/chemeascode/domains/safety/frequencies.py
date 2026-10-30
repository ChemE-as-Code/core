"""The likelihood of a rating from the project's frequency library (``cheme/frequencies/v1``).

A rating may link to a record or an event type of the study's library (``Rating.frequency``).
Its likelihood is then derived, never estimated: the record's value (an event type: its
screening value, the highest of its records, LOPA initiating-event records first when there are
any, so the value is conservative and never an average) placed in the matrix's likelihood
grades by their ``max_frequency``. A record that is per a length or a joint, an event type
without records or a matrix without frequency bounds gives no likelihood: that is a problem
named for the team, not a default.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

import yaml
from pydantic import ValidationError

from chemeascode.domains.safety.schemas import (
    FrequencyLibrary,
    FrequencyRecord,
    FrequencyRef,
    RiskMatrix,
)
from chemeascode.foundation.findings import Finding, Level
from chemeascode.foundation.provenance import file_fingerprint


@dataclass
class LoadedLibrary:
    path: str
    model: FrequencyLibrary | None
    fingerprint: str = ""
    findings: list[Finding] = field(default_factory=list)


def load_library(root: Path, path: str) -> LoadedLibrary:
    """The library *path* (from *root*); a missing or invalid file is a finding, not an error."""
    file = root / path
    if not file.is_file():
        message = f"no frequency library {path}"
        return LoadedLibrary(path, None, findings=[_problem(path, message)])
    try:
        model = FrequencyLibrary.model_validate(
            yaml.safe_load(file.read_text(encoding="utf-8")) or {}
        )
    except (yaml.YAMLError, ValidationError) as failure:
        message = f"{path} does not load: {str(failure).splitlines()[0]}"
        return LoadedLibrary(path, None, findings=[_problem(path, message)])
    return LoadedLibrary(path, model, file_fingerprint(file))


def _problem(path: str, message: str) -> Finding:
    return Finding(
        path,
        "error",
        "cheme.hazop-frequency",
        message,
        hint="see cheme schema frequencies; the study names it under frequencies:",
    )


@dataclass(frozen=True)
class Derived:
    """A rating's likelihood from its frequency link: the code and the record behind it, or the
    problem that leaves it open."""

    code: str | None
    record: FrequencyRecord | None
    problem: str = ""
    #: ``error``: a link or matrix to fix; ``info``: the library has no value for it, so the
    #: likelihood is given by hand.
    level: Level = "info"


def screening(
    library: FrequencyLibrary, ref: FrequencyRef
) -> tuple[FrequencyRecord | None, str, Level]:
    """The record a link gives (the record itself, or an event type's screening record), or the
    problem and its level."""
    if ref.record is not None:
        record = next((r for r in library.records if r.id == ref.record), None)
        if record is None:
            return None, f"no record {ref.record} in the frequency library", "error"
        return record, "", "info"
    if ref.event_type not in library.event_types:
        return None, f"no event type {ref.event_type} in the frequency library", "error"
    records = [r for r in library.records if r.event_type == ref.event_type and r.per is None]
    lopa = [r for r in records if library.sources[r.source].basis == "lopa_ief"]
    pool = lopa or records
    if not pool:
        return None, f"event type {ref.event_type} has no record per item", "info"
    return max(pool, key=lambda r: r.value), "", "info"


def likelihood_code(matrix: RiskMatrix, value: float) -> str | None:
    """The matrix's likelihood grade of *value* per year (None: the matrix has no bounds)."""
    grades = matrix.likelihood
    if all(g.max_frequency is None for g in grades):
        return None
    return next(
        (str(g.code) for g in grades if g.max_frequency is None or value < g.max_frequency),
        None,
    )


def derive(library: FrequencyLibrary, matrix: RiskMatrix, ref: FrequencyRef) -> Derived:
    record, problem, level = screening(library, ref)
    if record is None:
        return Derived(None, None, problem, level)
    if record.per is not None:
        return Derived(None, record, f"record {record.id} is per {record.per}: give the likelihood")
    code = likelihood_code(matrix, record.value)
    if code is None:
        if any(g.max_frequency is not None for g in matrix.likelihood):
            why = f"{record.id} ({record.value}/yr) is above the matrix's highest max_frequency"
            return Derived(None, record, why, "error")
        return Derived(None, record, "the risk matrix gives no max_frequency", "error")
    return Derived(code, record)
