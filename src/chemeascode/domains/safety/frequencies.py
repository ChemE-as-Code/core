"""The likelihood of a rating from the project's frequency library (``cheme/frequencies/v1``).

A rating may link to a record or an event type of the study's library (``Rating.frequency``).
Its likelihood is then derived, never estimated: the record's value (an event type: its
screening value, the highest of its records, LOPA initiating-event records first when there are
any, so the value is conservative and never an average) placed in the matrix's likelihood
grades by their ``max_frequency``. A record that is per a length or a joint, an event type
without records or a matrix without frequency bounds gives no likelihood: that is a problem
named for the team, not a default.

The link may name modifiers of the library (``FrequencyRef.modifiers``): enabling conditions and
conditional modifiers, each a probability. The value placed in the grades is then the cause's
frequency times their product, the likelihood of the outcome as rated (LOPA's intermediate event
likelihood without any protection layer). A modifier limited to some categories (presence, not
for harm to the environment) applies only to ratings in them. The likelihood carries the most
restrictive publication label of the sources it rests on.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

import yaml
from pydantic import ValidationError

from chemeascode.domains.safety.schemas import (
    PUBLICATIONS,
    FrequencyLibrary,
    FrequencyRecord,
    FrequencyRef,
    Modifier,
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
    #: The outcome's frequency per year: the record's value times the modifiers'.
    value: float | None = None
    modifiers: tuple[Modifier, ...] = ()
    #: The most restrictive publication label of the sources (None: one is not labelled).
    publication: str | None = None

    def chain(self) -> str:
        """``F020 0.1 x M-IGN-1 0.03 = 0.003/yr``."""
        if self.record is None:
            return ""
        parts = [f"{self.record.id} {self.record.value:g}"]
        parts += [f"{m.id} {m.value:g}" for m in self.modifiers]
        tail = f" = {self.value:g}/yr" if self.modifiers and self.value is not None else "/yr"
        return " x ".join(parts) + tail


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


def _publication(library: FrequencyLibrary, sources: list[str]) -> str | None:
    labels = [library.sources[s].publication for s in sources]
    if any(label is None for label in labels):
        return None
    return max(labels, key=PUBLICATIONS.index) if labels else None


def derive(
    library: FrequencyLibrary, matrix: RiskMatrix, ref: FrequencyRef, category: str | None = None
) -> Derived:
    """The likelihood code of a rating in *category* linked by *ref*."""
    record, problem, level = screening(library, ref)
    if record is None:
        return Derived(None, None, problem, level)
    if record.per is not None:
        return Derived(None, record, f"record {record.id} is per {record.per}: give the likelihood")
    by_id = {m.id: m for m in library.modifiers}
    unknown = [m for m in ref.modifiers if m not in by_id]
    if unknown:
        return Derived(None, record, f"no modifier {', '.join(unknown)} in the library", "error")
    modifiers = tuple(by_id[m] for m in ref.modifiers)
    outside = [m.id for m in modifiers if m.categories and category not in m.categories]
    if outside:
        return Derived(
            None, record, f"modifier {', '.join(outside)} does not apply to {category}", "error"
        )
    value = record.value
    for modifier in modifiers:
        value *= modifier.value
    publication = _publication(library, [record.source, *(m.source for m in modifiers)])
    code = likelihood_code(matrix, value)
    if code is None:
        if any(g.max_frequency is not None for g in matrix.likelihood):
            why = f"{record.id} ({value:g}/yr) is above the matrix's highest max_frequency"
            return Derived(None, record, why, "error", value, modifiers, publication)
        return Derived(
            None, record, "the risk matrix gives no max_frequency", "error", value, modifiers
        )
    return Derived(code, record, "", "info", value, modifiers, publication)
