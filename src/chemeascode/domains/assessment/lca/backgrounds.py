"""Packaged open background profiles (``data/backgrounds/<id>.yaml``), included by a study.

A profile is a ``lca_factors`` file whose sources permit the intended use, result publication
and the redistribution of its numbers (each says so in its ``sources:`` entry). A study adds one
with ``include: [<id>]`` in ``lca/factors.yaml``: :func:`resolve` merges the profile's sources,
categories and factors into the study's, each factor id prefixed ``<id>:``. A category of the
same id must be in the same unit; the study's own title and ``elementary:`` method win.
"""

from __future__ import annotations

from fnmatch import fnmatchcase
from functools import cache
from pathlib import Path

import yaml

from chemeascode.domains.assessment.lca.schemas import FactorFile, FactorScope

DATA = Path(__file__).with_name("data") / "backgrounds"
#: The structured scope of a packaged profile (``<id>.yaml``: ``sources:`` id -> scope,
#: ``factors:`` id glob -> scope, ``years:`` id glob -> ``data_year`` / ``publication_year``),
#: kept beside the profile so that the profile file, and with it every project's fingerprint of
#: it, stays byte-stable (pre-release issue 306). What the profile file itself declares wins field
#: by field.
SCOPES = Path(__file__).with_name("data") / "background_scopes"


def profiles() -> list[str]:
    """The ids of the packaged profiles."""
    return sorted(p.stem for p in DATA.glob("*.yaml"))


@cache
def profile(name: str) -> FactorFile | None:
    """The packaged profile *name* (None when there is none)."""
    path = DATA / f"{name}.yaml"
    if not path.is_file():
        return None
    found = FactorFile.model_validate(yaml.safe_load(path.read_text(encoding="utf-8")))
    return _scoped(found, SCOPES / f"{name}.yaml")


def _scoped(found: FactorFile, path: Path) -> FactorFile:
    """*found* with the scopes of the sidecar *path* applied (unchanged without one)."""
    if not path.is_file():
        return found
    data = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    by_source = {k: FactorScope.model_validate(v) for k, v in (data.get("sources") or {}).items()}
    by_factor = {k: FactorScope.model_validate(v) for k, v in (data.get("factors") or {}).items()}
    raw_years = data.get("years") or {}
    if not isinstance(raw_years, dict) or not all(
        isinstance(v, dict) and v for v in raw_years.values()
    ):
        raise ValueError(
            f"{path.name}: years: a mapping of factor id glob -> {{data_year, publication_year}}"
        )
    years: dict[str, dict] = raw_years
    unknown = (set(data) - {"sources", "factors", "years"}) | (
        set(by_source) - {s.id for s in found.sources}
    )
    unknown |= {
        g for g in (*by_factor, *years) if not any(fnmatchcase(f.id, g) for f in found.factors)
    }
    bad = {g: sorted(set(v) - {"data_year", "publication_year"}) for g, v in years.items()}
    if any(bad.values()):
        raise ValueError(f"{path.name}: years: only data_year and publication_year: {bad}")
    if unknown:
        raise ValueError(f"{path.name}: entries match nothing in the profile: {sorted(unknown)}")
    for source in found.sources:
        if source.id in by_source:
            source.scope = by_source[source.id].merged(source.scope)
    for factor in found.factors:
        match = next((s for g, s in by_factor.items() if fnmatchcase(factor.id, g)), None)
        if match is not None:
            factor.scope = match.merged(factor.scope)
        # declared years (pre-release issue 306): every matching entry counts; two that give one key
        # different values are an error; a value the profile file gives wins
        when: dict[str, int] = {}
        for glob, entry in years.items():
            if not fnmatchcase(factor.id, glob):
                continue
            for key, value in entry.items():
                if isinstance(value, bool) or not isinstance(value, int):
                    raise ValueError(f"{path.name}: years: {key} {value!r} is no year")
                if not 1900 <= value <= 2200:
                    raise ValueError(f"{path.name}: years: {key} {value!r} is no year")
                if when.setdefault(key, value) != value:
                    raise ValueError(
                        f"{path.name}: years: factor {factor.id} gets two values of {key}"
                    )
        for key, value in when.items():
            if getattr(factor, key) is None:
                setattr(factor, key, value)
        if factor.years_conflict():
            raise ValueError(f"{path.name}: factor {factor.id}: data_year after publication_year")
    return found


def resolve(factors: FactorFile) -> tuple[FactorFile, list[str]]:
    """*factors* with its included profiles merged in, and the problems (an unknown profile, a
    category in another unit, a factor naming an unknown category or source)."""
    problems: list[str] = []
    if not factors.include:
        return factors, problems
    sources = list(factors.sources)
    categories = list(factors.categories)
    merged = list(factors.factors)
    for name in factors.include:
        found = profile(name)
        if found is None:
            problems.append(f"no packaged profile {name} (profiles: {', '.join(profiles())})")
            continue
        for source in found.sources:
            same = next((s for s in sources if s.id == source.id), None)
            if same is None:
                sources.append(source)
            elif same.model_dump(exclude={"scope"}) != source.model_dump(exclude={"scope"}):
                problems.append(
                    f"source {source.id} of profile {name} differs from an entry of the same id: "
                    "give the study's own source another id"
                )
            else:
                # a copy of the packaged source keeps the packaged scope (its own fields win);
                # a new object: profile() is cached
                scope = (source.scope or FactorScope()).merged(same.scope)
                sources[sources.index(same)] = same.model_copy(
                    update={"scope": scope if scope.declared else None}
                )
        for category in found.categories:
            own = next((c for c in categories if c.id == category.id), None)
            if own is None:
                categories.append(category)
            elif own.unit != category.unit:
                problems.append(
                    f"category {category.id} is in {own.unit} here, {category.unit} in profile "
                    f"{name}"
                )
        merged += [f.model_copy(update={"id": f"{name}:{f.id}"}) for f in found.factors]
    ids = {c.id for c in categories}
    known_sources = {s.id for s in sources}
    for factor in merged:
        unknown = sorted(set(factor.values) - ids)
        if unknown:
            problems.append(f"factor {factor.id}: unknown categories {', '.join(unknown)}")
        if factor.source_id is not None and factor.source_id not in known_sources:
            problems.append(f"factor {factor.id}: source_id {factor.source_id} is not in sources")
    seen: set[str] = set()
    for factor in merged:
        if factor.id in seen:
            problems.append(f"factor id {factor.id} appears twice")
        seen.add(factor.id)
    return (
        factors.model_copy(
            update={"sources": sources, "categories": categories, "factors": merged, "include": []}
        ),
        problems,
    )
