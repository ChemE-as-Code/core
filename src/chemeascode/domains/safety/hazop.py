"""HAZOP studies: ``safety/hazop/<study-id>/study.yaml`` (``cheme/hazop-study/v1``).

One authoritative file per study (:mod:`chemeascode.domains.safety.schemas`); reports are
derived from it (:mod:`chemeascode.domains.safety.hazop_report`). This module loads a study,
checks it against itself, the plant and its risk matrix, looks its bands up and writes them
back, and tells how far the study is.

Rules (``cheme.hazop-*``), each finding naming the file, line, rule and a hint:

- ``hazop-schema`` (error): not valid YAML or not ``cheme/hazop-study/v1``;
- ``hazop-duplicate-id`` (error): an id given twice (nodes, deviations, scenarios, safeguards,
  actions and modes share one namespace), or a key given twice in one mapping;
- ``hazop-id`` (warning): the study id is not its directory's name;
- ``hazop-unknown-ref`` (error): a scenario's safeguard, action or mode, or a node's mode,
  that the study does not declare;
- ``hazop-unknown-tag`` (warning): a plant reference whose tag no list holds and no sheet
  draws; ``hazop-unknown-sheet`` (error) a sheet id ``plant.yaml`` does not declare;
  ``hazop-not-on-sheet`` (warning) a tag or DEXPI object that sheet does not hold;
- ``hazop-unknown-interlock`` (error): a safeguard's interlock that
  ``control/cause-effect.yaml`` does not hold; ``hazop-safeguard-unresolved`` (warning): a
  control, alarm, interlock, relief or check-valve safeguard that names no device or interlock;
- ``hazop-matrix`` (error): ratings, but no usable matrix (the matrix's own findings are
  ``cheme.risk-matrix-*``); ``hazop-matrix-example`` (info): the matrix is example data;
- ``hazop-unknown-code`` (error): a rating's category, severity or likelihood the matrix does
  not have; ``hazop-rating-duplicate`` (error): a category rated twice in one list;
- ``hazop-frequency`` (error or info): a rating's ``frequency:`` link that gives no likelihood:
  no or an invalid library, an unknown record or event type, a matrix without
  ``max_frequency`` (error); an event type without a record per item or a record per a length
  (info: the likelihood is given by hand); ``hazop-likelihood-derived`` (warning): a linked
  rating whose likelihood is not the one its record gives (``rate --write`` sets it);
- ``hazop-band-stale`` (warning): a calculated band whose rating or matrix changed since;
  ``hazop-band-edited`` (error): a calculated band that is not what the matrix gives for its
  inputs (edited by hand);
- ``hazop-action-required`` (warning): a scenario in a band whose matrix policy requires an
  action, with none; ``hazop-action-state`` (warning): a closed or rejected action without its
  response, or an action no scenario refers to;
- ``hazop-input-changed`` (warning): an analysed input that changed since the revision the
  study records: the affected nodes need reassessment;
- ``hazop-unresolved`` (info): what keeps the study a draft: proposals, unrated scenarios,
  incomplete ratings, bands not yet looked up, a rating without its basis, no analysed inputs;
  ``hazop-example`` (info): the study is an example (``example: true``) and stays a draft.

Structural validity is not safety approval: the findings say whether the file is consistent,
complete and current, never whether the plant is safe. Completion and review are asked for by
gates (``kind: hazop``, ``kind: review`` with ``topic: hazop``).
"""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass, field
from pathlib import Path, PurePosixPath
from typing import Any, Literal

import yaml
from pydantic import ValidationError

from chemeascode.domains.safety.frequencies import Derived, LoadedLibrary, derive, load_library
from chemeascode.domains.safety.risk_matrix import (
    LoadedMatrix,
    band_rank,
    duplicate_keys,
    load_matrix,
    lookup,
)
from chemeascode.domains.safety.schemas import (
    STUDY_SCHEMA,
    HazopStudy,
    PlantRef,
    Rating,
    Scenario,
)
from chemeascode.foundation import gitinfo, provenance
from chemeascode.foundation.findings import Finding, Level
from chemeascode.foundation.workspace import Workspace
from chemeascode.foundation.yamlsource import _yaml_line

STUDIES_DIR = "safety/hazop"
STUDY_FILE = "study.yaml"
#: The start of the ``source`` of every band the lookup writes.
RATE_SOURCE = "cheme safety hazop rate"
#: The safeguard kinds that act through a device, so name one.
DEVICE_KINDS = frozenset({"control", "alarm", "interlock", "relief", "check-valve"})

#: How far a study is: ``invalid`` (errors), ``draft`` (something unresolved), ``assessed``
#: (complete and current, every judgement accepted), ``reviewed`` (assessed, and a current human
#: review record covers it and its analysed inputs).
State = Literal["invalid", "draft", "assessed", "reviewed"]


def study_path(study_id: str) -> str:
    return f"{STUDIES_DIR}/{study_id}/{STUDY_FILE}"


def study_paths(workspace: Workspace) -> list[Path]:
    """Every ``safety/hazop/*/study.yaml``, by directory name."""
    base = workspace.root / STUDIES_DIR
    return sorted(base.glob(f"*/{STUDY_FILE}")) if base.is_dir() else []


@dataclass
class LoadedStudy:
    """A study file: its model (None when it does not load), YAML nodes and findings."""

    path: str
    model: HazopStudy | None
    document: Any = None
    findings: list[Finding] = field(default_factory=list)
    matrix: LoadedMatrix | None = None
    frequencies: LoadedLibrary | None = None


def load_study(root: Path, path: str) -> LoadedStudy:
    """Load the study *path* (from *root*) and its matrix; only the schema is checked here."""
    text = (root / path).read_text(encoding="utf-8")
    try:
        document = yaml.compose(text)
        data = yaml.safe_load(text)
    except yaml.YAMLError as failure:
        mark = getattr(failure, "problem_mark", None)
        return LoadedStudy(
            path,
            None,
            findings=[
                Finding(
                    path,
                    "error",
                    "cheme.hazop-schema",
                    f"not valid YAML: {str(failure).splitlines()[0]}",
                    line=mark.line + 1 if mark is not None else None,
                    hint="fix the YAML syntax",
                )
            ],
        )
    findings = duplicate_keys(document, path, "cheme.hazop-duplicate-id")
    try:
        study = HazopStudy.model_validate(data or {})
    except ValidationError as failure:
        for error in failure.errors():
            loc = list(error["loc"])
            findings.append(
                Finding(
                    path,
                    "error",
                    "cheme.hazop-schema",
                    f"{'.'.join(str(p) for p in loc) or 'file'}: {error['msg']}",
                    line=_yaml_line(document, loc),
                    key=".".join(str(p) for p in loc),
                    hint=f"see cheme schema hazop-study ({STUDY_SCHEMA})",
                )
            )
        return LoadedStudy(path, None, document, findings)
    matrix = load_matrix(root, study.risk_matrix) if study.risk_matrix else None
    library = load_library(root, study.frequencies) if study.frequencies else None
    return LoadedStudy(path, study, document, findings, matrix, library)


def dump_study(study: HazopStudy) -> str:
    """*study* as YAML in worksheet order, without the fields left at their defaults except
    ``status`` (so a proposal says so). Loading it gives *study* back."""
    data = study.model_dump(mode="json", by_alias=True, exclude_defaults=True)
    data = {"schema": study.schema_, "kind": study.kind, **data}

    def keep_status(model: Any, out: Any) -> None:
        if isinstance(out, dict) and hasattr(model, "status"):
            out.setdefault("status", model.status)

    for i, node in enumerate(study.nodes):
        keep_status(node, data["nodes"][i])
        for j, dev in enumerate(node.deviations):
            for k, scen in enumerate(dev.scenarios):
                out = data["nodes"][i]["deviations"][j]["scenarios"][k]
                keep_status(scen, out)
                for which in ("initial", "residual"):
                    for m, rating in enumerate(getattr(scen.risk, which, None) or []):
                        keep_status(rating, out["risk"][which][m])
                        if rating.band is not None:
                            out["risk"][which][m]["band"] = rating.band.model_dump(mode="json")
    for key in ("safeguards", "actions"):
        for i, entry in enumerate(getattr(study, key)):
            keep_status(entry, data[key][i])
    return yaml.safe_dump(data, sort_keys=False, allow_unicode=True, width=100)


# ---------------------------------------------------------------------------
# Ratings and bands
# ---------------------------------------------------------------------------


def band_fingerprint(
    matrix_fingerprint: str,
    rating: Rating,
    severity: str | None = None,
    likelihood: str | None = None,
    category: str | None = None,
) -> str:
    """The input fingerprint of a band: the matrix, the category and the codes it was looked up
    from (the rating's, or *category*, *severity* and *likelihood* when given)."""
    return provenance.value_fingerprint(
        {
            "matrix": matrix_fingerprint,
            "category": rating.category if category is None else category,
            "severity": rating.severity if severity is None else severity,
            "likelihood": rating.likelihood if likelihood is None else likelihood,
        }
    )


def _looked_up_in(rating: Rating, categories: Iterable[str] = ()) -> str | None:
    """The category the band's ``inputs`` say it was looked up in: the one they record, else
    (a band written before they recorded it) the rating's or the one of *categories* whose
    fingerprint matches. None when the fingerprint is not the one of the inputs it records:
    the lookup did not write it."""
    band = rating.band
    if band is None or band.inputs is None:
        return None
    i = band.inputs
    candidates = [i.category] if i.category is not None else [rating.category, *categories]
    for category in candidates:
        fingerprint = band_fingerprint(i.matrix, rating, i.severity, i.likelihood, category)
        if band.fingerprint == fingerprint:
            return category
    return None


#: ``current``: the recorded band is what the matrix gives now; ``missing``: none recorded yet;
#: ``stale``: recorded from other inputs or another matrix; ``edited``: recorded with these
#: inputs but not the matrix's band; ``foreign``: a band ``cheme safety hazop rate`` did not
#: write (its ``source`` names another tool or none), which it never overwrites;
#: ``unresolved``: no band can be looked up (``problem``).
RowState = Literal["current", "missing", "stale", "edited", "foreign", "unresolved"]


@dataclass
class RatingRow:
    """One rating of one scenario, with the band the matrix gives and the one recorded."""

    node: str
    scenario: str
    which: str  # initial or residual
    index: int
    rating: Rating
    loc: list[Any]
    band: str | None
    problem: str
    message: str
    state: RowState
    fingerprint: str = ""
    #: The category the recorded band was looked up in (None: no ``inputs`` to tell, or tampered).
    looked_up_in: str | None = None

    @property
    def tampered(self) -> bool:
        """Whether the band's fingerprint is not the one of the inputs it records: it was not
        written by the lookup (a band without ``inputs`` cannot tell, and is not). A category
        changed since is no tampering: that band is stale."""
        band = self.rating.band
        return band is not None and band.inputs is not None and self.looked_up_in is None

    @property
    def recorded(self) -> str | None:
        return self.rating.band.value if self.rating.band is not None else None


@dataclass
class LikelihoodRow:
    """A rating linked to the frequency library, and the likelihood the library gives it."""

    scenario: str
    which: str
    rating: Rating
    loc: list[Any]
    derived: Derived

    @property
    def changes(self) -> bool:
        return self.derived.code is not None and self.derived.code != self.rating.likelihood


def likelihood_rows(loaded: LoadedStudy) -> list[LikelihoodRow]:
    """Every rating with a ``frequency:`` link, with the likelihood its record gives."""
    study, matrix, library = loaded.model, loaded.matrix, loaded.frequencies
    if study is None:
        return []
    rows = []
    for ni, node in enumerate(study.nodes):
        for di, dev in enumerate(node.deviations):
            for si, scen in enumerate(dev.scenarios):
                for which in ("initial", "residual"):
                    for ri, rating in enumerate(getattr(scen.risk, which, None) or []):
                        if rating.frequency is None:
                            continue
                        if library is None:
                            derived = Derived(
                                None, None, "the study names no frequencies:", "error"
                            )
                        elif library.model is None:
                            derived = Derived(None, None, f"{library.path} does not load", "error")
                        elif matrix is None or matrix.model is None or not matrix.usable:
                            derived = Derived(None, None, "no usable risk matrix", "error")
                        else:
                            derived = derive(library.model, matrix.model, rating.frequency)
                        loc = ["nodes", ni, "deviations", di, "scenarios", si, "risk", which, ri]
                        rows.append(LikelihoodRow(scen.id, which, rating, loc, derived))
    return rows


def rating_rows(loaded: LoadedStudy) -> list[RatingRow]:
    """Every rating of the study with its lookup (none without a usable matrix)."""
    study, matrix = loaded.model, loaded.matrix
    if study is None:
        return []
    usable = matrix is not None and matrix.usable and matrix.model is not None
    model = matrix.model if matrix is not None else None
    categories = [c.id for c in model.categories] if model is not None else []
    rows = []
    for ni, node in enumerate(study.nodes):
        for di, dev in enumerate(node.deviations):
            for si, scen in enumerate(dev.scenarios):
                for which in ("initial", "residual"):
                    for ri, rating in enumerate(getattr(scen.risk, which, None) or []):
                        loc = ["nodes", ni, "deviations", di, "scenarios", si, "risk", which, ri]
                        if not usable:
                            result_band, problem, message, fp = None, "matrix", "no matrix", ""
                        else:
                            assert matrix is not None and matrix.model is not None
                            found = lookup(
                                matrix.model, rating.category, rating.severity, rating.likelihood
                            )
                            result_band, problem, message = found.band, found.problem, found.message
                            fp = band_fingerprint(matrix.fingerprint, rating)
                        recorded = rating.band
                        looked_up_in = _looked_up_in(rating, categories)
                        if recorded is not None and not recorded.source.startswith(RATE_SOURCE):
                            state: RowState = "foreign"
                        elif result_band is None:
                            state = "unresolved"
                        elif recorded is None:
                            state = "missing"
                        elif recorded.inputs is not None and looked_up_in is None:
                            state = "foreign"  # tampered
                        elif recorded.fingerprint != fp:
                            state = "stale"
                        elif recorded.value != result_band:
                            state = "edited"
                        else:
                            state = "current"
                        rows.append(
                            RatingRow(
                                node.id,
                                scen.id,
                                which,
                                ri,
                                rating,
                                loc,
                                result_band,
                                problem,
                                message,
                                state,
                                fp,
                                looked_up_in,
                            )
                        )
    return rows


def worst_band(loaded: LoadedStudy, rows: Iterable[RatingRow]) -> str | None:
    """The highest band of *rows* in the matrix's own order (never by name or by codes)."""
    matrix = loaded.matrix.model if loaded.matrix is not None else None
    best: tuple[int, str] | None = None
    for row in rows:
        if matrix is None or row.band is None:
            continue
        rank = band_rank(matrix, row.band)
        if rank is not None and (best is None or rank > best[0]):
            best = (rank, row.band)
    return best[1] if best else None


def scenario_band(
    loaded: LoadedStudy, rows: list[RatingRow], scenario: str
) -> tuple[str, str | None]:
    """``(which, band)``: the worst band over the categories rated, each category at its
    residual rating where the team gave one that has a band and at its initial rating otherwise
    (never lower for want of a complete residual rating); ``which`` is ``residual`` when any
    residual rating counts."""
    mine = [r for r in rows if r.scenario == scenario]
    residual = {r.rating.category: r for r in mine if r.which == "residual" and r.band}
    counted = list(residual.values()) + [
        r for r in mine if r.which == "initial" and r.rating.category not in residual
    ]
    return ("residual" if residual else "initial"), worst_band(loaded, counted)


# ---------------------------------------------------------------------------
# The plant the study refers to
# ---------------------------------------------------------------------------


@dataclass
class PlantContext:
    """What a study's references are checked against. ``None``: that source is not available,
    and references to it are not checked."""

    #: Every tag a list holds or a sheet draws.
    tags: set[str] | None = None
    #: The sheet ids of ``plant.yaml``.
    sheet_ids: set[str] = field(default_factory=set)
    #: Tags drawn on each loaded sheet, by sheet id.
    sheet_tags: dict[str, set[str]] = field(default_factory=dict)
    #: DEXPI object ids of each loaded sheet, by sheet id.
    sheet_objects: dict[str, set[str]] = field(default_factory=dict)
    #: Interlock ids of ``control/cause-effect.yaml``.
    interlocks: set[str] | None = None


def plant_context(
    workspace: Workspace, sheets: dict[str, tuple[Any, Any]], parsed: dict[str, Any]
) -> PlantContext:
    """The context of *workspace* from the loaded *sheets* (``{file: (model, SheetIndex)}``)
    and the *parsed* lists, as ``validate_workspace`` has them."""
    from chemeascode.domains.control.interlocks import known_tags
    from chemeascode.domains.piping.sheet_query import sheet_id_of, sheet_items

    context = PlantContext()
    try:
        context.sheet_ids = {s.id for s in workspace.config().sheets}
    except Exception:  # noqa: BLE001 - plant.yaml problems are validate's own finding
        context.sheet_ids = set()
    if sheets or any(k in parsed for k in ("equipment", "instruments", "lines", "piping_items")):
        context.tags = set(known_tags(sheets, parsed))
    for name, (model, index) in sheets.items():
        sheet_id = sheet_id_of(workspace, name)
        context.sheet_tags[sheet_id] = {item.tag for item in sheet_items(model, name)}
        context.sheet_objects[sheet_id] = set(getattr(index, "ids", {}) or {})
    interlocks = parsed.get("interlocks")
    if interlocks is not None:
        context.interlocks = {str(i.id).strip() for i in interlocks.interlocks}
    return context


# ---------------------------------------------------------------------------
# Rules
# ---------------------------------------------------------------------------


def _shown(ids: list[str], limit: int = 6) -> str:
    return ", ".join(ids[:limit]) + (f" and {len(ids) - limit} more" if len(ids) > limit else "")


def study_findings(
    workspace: Workspace, loaded: LoadedStudy, context: PlantContext | None = None
) -> list[Finding]:
    """Every ``cheme.hazop-*`` finding of *loaded* (with its matrix's own findings), its plant
    references checked against *context* when given."""
    findings = list(loaded.findings)
    study, doc, file = loaded.model, loaded.document, loaded.path
    if study is None:
        return findings

    def add(
        level: Level,
        rule: str,
        message: str,
        loc: list[Any],
        ids: list[str],
        hint: str,
        key: str = "",
    ) -> None:
        findings.append(
            Finding(
                file,
                level,
                f"cheme.hazop-{rule}",
                message,
                line=_yaml_line(doc, loc),
                ids=ids,
                hint=hint,
                key=key,
            )
        )

    if study.example:
        add(
            "info",
            "example",
            f"study {study.id} is an example (example: true), not an assessment of this plant",
            ["example"],
            [study.id],
            "an example stays a draft; start the plant's own study with cheme safety hazop init",
            key="example",
        )
    directory = PurePosixPath(file).parent.name
    if study.id != directory:
        add(
            "warning",
            "id",
            f"study id {study.id} is not its directory's name ({directory})",
            ["id"],
            [study.id],
            f"name the directory {STUDIES_DIR}/{study.id}/, or give the study id {directory}",
        )

    # One namespace for every id of the study.
    declared: dict[str, list[Any]] = {}

    def declare(entity: str, loc: list[Any]) -> None:
        if entity in declared:
            add(
                "error",
                "duplicate-id",
                f"id {entity} is given twice (first on line {_yaml_line(doc, declared[entity])})",
                loc,
                [entity],
                "give every node, deviation, scenario, safeguard, action and mode its own id; "
                "ids are never reused, also not after deleting an entry",
                key=f"{entity}@{_yaml_line(doc, loc)}",
            )
        else:
            declared[entity] = loc

    for i, mode in enumerate(study.modes):
        declare(mode.id, ["modes", i, "id"])
    for i, sg in enumerate(study.safeguards):
        declare(sg.id, ["safeguards", i, "id"])
    for i, act in enumerate(study.actions):
        declare(act.id, ["actions", i, "id"])
    for ni, node in enumerate(study.nodes):
        declare(node.id, ["nodes", ni, "id"])
        for di, dev in enumerate(node.deviations):
            if dev.id is not None:
                declare(dev.id, ["nodes", ni, "deviations", di, "id"])
            for si, scen in enumerate(dev.scenarios):
                declare(scen.id, ["nodes", ni, "deviations", di, "scenarios", si, "id"])

    modes = {m.id for m in study.modes}
    safeguards = {s.id: s for s in study.safeguards}
    actions = {a.id: a for a in study.actions}
    referenced_actions: set[str] = set()

    def check_refs(
        owner: str, kind: str, names: list[str], known: Iterable[str], loc: list[Any]
    ) -> None:
        known = set(known)
        for j, name in enumerate(names):
            if name not in known:
                add(
                    "error",
                    "unknown-ref",
                    f"{owner}: {kind} {name} is not declared in the study",
                    [*loc, j],
                    [owner, name],
                    f"declare it under {kind}s: (known: {_shown(sorted(known)) or 'none'})",
                    key=f"{owner}:{kind}:{name}",
                )

    def check_plant(owner: str, refs: list[PlantRef], loc: list[Any]) -> None:
        if context is None:
            return
        for j, ref in enumerate(refs):
            at = [*loc, j]
            if ref.sheet is not None:
                if ref.sheet not in context.sheet_ids:
                    add(
                        "error",
                        "unknown-sheet",
                        f"{owner}: sheet {ref.sheet} is not declared in plant.yaml",
                        at,
                        [owner, ref.sheet],
                        "name a sheet id of plant.yaml (P-01)",
                        key=f"{owner}:{ref.text()}",
                    )
                    continue
                drawn = context.sheet_tags.get(ref.sheet)
                objects = context.sheet_objects.get(ref.sheet)
                if ref.tag is not None and drawn is not None and ref.tag not in drawn:
                    add(
                        "warning",
                        "not-on-sheet",
                        f"{owner}: {ref.tag} is not drawn on sheet {ref.sheet}",
                        at,
                        [owner, ref.tag],
                        "fix the tag or the sheet (cheme show <tag> finds it)",
                        key=f"{owner}:{ref.text()}",
                    )
                if ref.object is not None and objects is not None and ref.object not in objects:
                    add(
                        "warning",
                        "not-on-sheet",
                        f"{owner}: sheet {ref.sheet} has no object {ref.object}",
                        at,
                        [owner, ref.object],
                        "name the object by its XML id (cheme show <id>)",
                        key=f"{owner}:{ref.text()}",
                    )
                if ref.tag is None or drawn is not None:
                    continue
            if ref.tag is not None and context.tags is not None and ref.tag not in context.tags:
                add(
                    "warning",
                    "unknown-tag",
                    f"{owner}: {ref.tag} is in no list and on no sheet",
                    at,
                    [owner, ref.tag],
                    "fix the tag (as printed on the P&ID); a study refers to the plant as "
                    "drawn and never invents equipment",
                    key=f"{owner}:{ref.text()}",
                )

    for i, sg in enumerate(study.safeguards):
        loc = ["safeguards", i]
        check_plant(f"safeguard {sg.id}", sg.refs, [*loc, "refs"])
        if sg.interlock is not None:
            if context is not None and context.interlocks is not None:
                if sg.interlock not in context.interlocks:
                    add(
                        "error",
                        "unknown-interlock",
                        f"safeguard {sg.id}: interlock {sg.interlock} is not in "
                        "control/cause-effect.yaml",
                        [*loc, "interlock"],
                        [sg.id, sg.interlock],
                        "name an interlock id of control/cause-effect.yaml, or declare the "
                        "interlock there first (skill: the C&E belongs to control)",
                    )
            elif context is not None:
                add(
                    "error",
                    "unknown-interlock",
                    f"safeguard {sg.id}: interlock {sg.interlock}, but the plant has no "
                    "control/cause-effect.yaml",
                    [*loc, "interlock"],
                    [sg.id, sg.interlock],
                    "declare the interlock in control/cause-effect.yaml",
                )
        if sg.kind == "interlock" and sg.interlock is None:
            add(
                "warning",
                "safeguard-unresolved",
                f"safeguard {sg.id} is an interlock but names none of control/cause-effect.yaml",
                [*loc, "kind"],
                [sg.id],
                "give interlock: <id>; the trip itself is declared in the cause and effect",
            )
        elif sg.kind in DEVICE_KINDS and not sg.refs and sg.interlock is None:
            add(
                "warning",
                "safeguard-unresolved",
                f"safeguard {sg.id} ({sg.kind}) names no device",
                [*loc],
                [sg.id],
                "give refs: [<tag>] of the instrument, valve or relief device on the P&ID",
            )

    for ni, node in enumerate(study.nodes):
        nloc = ["nodes", ni]
        check_refs(f"node {node.id}", "mode", node.modes, modes, [*nloc, "modes"])
        check_plant(f"node {node.id}", node.members, [*nloc, "members"])
        for di, dev in enumerate(node.deviations):
            for si, scen in enumerate(dev.scenarios):
                sloc = [*nloc, "deviations", di, "scenarios", si]
                owner = f"scenario {scen.id}"
                check_refs(owner, "mode", scen.modes, modes, [*sloc, "modes"])
                check_refs(owner, "safeguard", scen.safeguards, safeguards, [*sloc, "safeguards"])
                check_refs(owner, "action", scen.actions, actions, [*sloc, "actions"])
                referenced_actions.update(scen.actions)
                check_plant(owner, scen.refs, [*sloc, "refs"])
                for which in ("initial", "residual"):
                    seen: set[str] = set()
                    for ri, rating in enumerate(getattr(scen.risk, which, None) or []):
                        if rating.category in seen:
                            add(
                                "error",
                                "rating-duplicate",
                                f"{owner}: {which} risk rates {rating.category} twice",
                                [*sloc, "risk", which, ri, "category"],
                                [scen.id, rating.category],
                                "one rating per category",
                                key=f"{scen.id}:{which}:{rating.category}",
                            )
                        seen.add(rating.category)

    for i, act in enumerate(study.actions):
        loc = ["actions", i]
        if act.status in ("closed", "rejected") and not act.response.strip():
            add(
                "warning",
                "action-state",
                f"action {act.id} is {act.status} without a response",
                [*loc, "status"],
                [act.id],
                "say how it was closed (the change, its commit) or why it was rejected, and by "
                "whom, under response:",
                key=f"{act.id}:response",
            )
        if act.id not in referenced_actions:
            add(
                "warning",
                "action-state",
                f"action {act.id} belongs to no scenario",
                loc,
                [act.id],
                "list it under the actions: of the scenario that raised it",
                key=f"{act.id}:orphan",
            )

    findings += _risk_findings(loaded, add)
    if loaded.frequencies is not None:
        findings += loaded.frequencies.findings
    for row in likelihood_rows(loaded):
        owner = f"scenario {row.scenario} ({row.which}, {row.rating.category})"
        key = f"{row.scenario}:{row.which}:{row.rating.category}"
        if row.derived.problem:
            add(
                row.derived.level,
                "frequency",
                f"{owner}: no likelihood from the frequency library: {row.derived.problem}",
                [*row.loc, "frequency"],
                [row.scenario, row.rating.category],
                "fix the link, or give the likelihood with its basis and drop frequency:"
                if row.derived.level == "error"
                else "give the likelihood by hand with its basis (or link another record)",
                key=f"{key}:frequency",
            )
        elif row.changes:
            record = row.derived.record
            assert record is not None
            add(
                "warning",
                "likelihood-derived",
                f"{owner}: likelihood {row.rating.likelihood or 'none'}, but {record.id} "
                f"({record.value}/yr) gives {row.derived.code}",
                [*row.loc, "likelihood"],
                [row.scenario, row.rating.category],
                f"cheme safety hazop rate {study.id} --target {row.scenario} --write sets it "
                "(a likelihood with a frequency link is derived, never typed)",
                key=f"{key}:likelihood",
            )
    findings += input_findings(workspace, loaded)
    findings += _unresolved(workspace, loaded)
    return findings


def _risk_findings(loaded: LoadedStudy, add: Any) -> list[Finding]:
    """Matrix, code, band and policy findings (added through *add*), plus the matrix's own."""
    study, matrix = loaded.model, loaded.matrix
    assert study is not None
    extra: list[Finding] = []
    rows = rating_rows(loaded)
    if matrix is not None:
        extra += matrix.findings
        if matrix.model is not None and matrix.model.example:
            add(
                "info",
                "matrix-example",
                f"risk matrix {matrix.path} is example data ({matrix.model.id}), not your "
                "company's criteria",
                ["risk_matrix"],
                [matrix.model.id],
                "replace it with the project's risk matrix (its source procedure) before the "
                "study is assessed; gate hazop no-example asks for it",
                key="matrix-example",
            )
    proposed = matrix is not None and matrix.model is not None and matrix.model.status == "proposed"
    if proposed and not matrix.model.example:  # an example says so already
        add(
            "info",
            "unresolved",
            f"risk matrix {matrix.path} ({matrix.model.id}) is proposed: the team has not "
            "accepted its criteria",
            ["risk_matrix"],
            [matrix.model.id],
            "the owner's team accepts the matrix (status: accepted, accepted_by: <who, "
            "procedure>) or replaces it with the company's",
            key="matrix-proposed",
        )
    if rows and (matrix is None or not matrix.usable):
        why = (
            "the study names no risk_matrix"
            if matrix is None
            else f"{matrix.path} has errors (cheme.risk-matrix-*)"
        )
        add(
            "error",
            "matrix",
            f"{len(rows)} rating(s), but no band can be looked up: {why}",
            ["risk_matrix"],
            [],
            "name a valid matrix under risk_matrix: (schema: cheme schema risk-matrix)",
            key="matrix",
        )
        return extra
    for row in rows:
        owner = f"scenario {row.scenario} ({row.which}, {row.rating.category})"
        if row.problem.startswith("unknown"):
            add(
                "error",
                "unknown-code",
                f"{owner}: {row.message}",
                row.loc,
                [row.scenario, row.rating.category],
                "use the codes of the study's risk matrix; nothing is mapped or assumed",
                key=f"{row.scenario}:{row.which}:{row.rating.category}",
            )
        elif row.problem == "no-cell":
            add(
                "error",
                "unknown-code",
                f"{owner}: {row.message}",
                row.loc,
                [row.scenario, row.rating.category],
                "complete the matrix (cheme.risk-matrix-incomplete)",
                key=f"{row.scenario}:{row.which}:{row.rating.category}",
            )
        if row.state == "stale" or (row.state == "unresolved" and row.rating.band is not None):
            add(
                "warning",
                "band-stale",
                f"{owner}: band {row.recorded} was looked up from {_what_changed(row, matrix)}",
                [*row.loc, "band"],
                [row.scenario, row.rating.category],
                "reassess, then cheme safety hazop rate "
                f"{study.id} --target {row.scenario} --write",
                key=f"{row.scenario}:{row.which}:{row.rating.category}",
            )
        elif row.state == "foreign":
            add(
                "error",
                "band-edited",
                f"{owner}: band {row.recorded} was not written by {RATE_SOURCE} "
                + (
                    "(its fingerprint is not the one of the inputs it records)"
                    if row.tampered
                    else f"(source: {row.rating.band.source!r})"
                ),
                [*row.loc, "band"],
                [row.scenario, row.rating.category],
                "a band is only ever the lookup's result: delete it and run cheme safety hazop "
                f"rate {study.id} --target {row.scenario} --write",
                key=f"{row.scenario}:{row.which}:{row.rating.category}",
            )
        elif row.state == "edited":
            add(
                "error",
                "band-edited",
                f"{owner}: band {row.recorded} is not what the matrix gives ({row.band}); a "
                "calculated band is never edited by hand",
                [*row.loc, "band"],
                [row.scenario, row.rating.category],
                f"change the rating instead; cheme safety hazop rate {study.id} --target "
                f"{row.scenario} --write rewrites the band",
                key=f"{row.scenario}:{row.which}:{row.rating.category}",
            )
    matrix_model = matrix.model if matrix is not None else None
    if matrix_model is not None:
        policy = {b.id for b in matrix_model.bands if b.requires_action}
        for ni, node in enumerate(study.nodes):
            for di, dev in enumerate(node.deviations):
                for si, scen in enumerate(dev.scenarios):
                    which, band = scenario_band(loaded, rows, scen.id)
                    if band in policy and not scen.actions:
                        add(
                            "warning",
                            "action-required",
                            f"scenario {scen.id}: {which} risk {band} requires an action "
                            f"(matrix {matrix_model.id}), and the scenario has none",
                            ["nodes", ni, "deviations", di, "scenarios", si],
                            [scen.id, band],
                            "raise an action (the team decides; a proposal stays "
                            "status: proposed), or record the team's residual rating with its "
                            "basis",
                            key=f"{scen.id}:action",
                        )
    return extra


def _what_changed(row: RatingRow, matrix: LoadedMatrix | None) -> str:
    """What a stale band was looked up from that is no longer so."""
    band = row.rating.band
    inputs = band.inputs if band is not None else None
    if inputs is None:
        return "another rating or matrix"
    parts = []
    if row.looked_up_in is not None and row.looked_up_in != row.rating.category:
        parts.append(f"category {row.looked_up_in}")
    if (inputs.severity, inputs.likelihood) != (row.rating.severity, row.rating.likelihood):
        parts.append(f"severity {inputs.severity}, likelihood {inputs.likelihood}")
    if matrix is not None and inputs.matrix != matrix.fingerprint:
        parts.append(f"matrix {inputs.matrix}, now {matrix.fingerprint}")
    return " and ".join(parts) or "other inputs"


def input_findings(workspace: Workspace, loaded: LoadedStudy) -> list[Finding]:
    """``cheme.hazop-input-changed``: the analysed inputs that changed since the revision the
    study records. Only the declared inputs count: other changes to the repository do not."""
    study = loaded.model
    if study is None:
        return []
    found = []
    for i, basis in enumerate(study.analysed):
        changed = provenance.changed_since(workspace.root, basis.path, basis.revision)
        if changed == []:
            continue
        what = (
            f"{_shown(changed)} changed since {basis.revision[:19]}"
            if changed
            else f"revision {basis.revision[:19]} cannot be resolved here"
        )
        found.append(
            Finding(
                loaded.path,
                "warning",
                "cheme.hazop-input-changed",
                f"analysed input {basis.path}: {what}; the study may no longer describe it",
                line=_yaml_line(loaded.document, ["analysed", i]),
                ids=[basis.path],
                key=f"analysed:{basis.path}",
                hint="reassess the nodes it touches (cheme diff shows what changed), then "
                f"record the new revision: cheme safety hazop stamp {study.id} --write",
            )
        )
    return found


def _unresolved(workspace: Workspace, loaded: LoadedStudy) -> list[Finding]:
    """The ``cheme.hazop-unresolved`` infos: what keeps the study a draft."""
    study = loaded.model
    assert study is not None
    found: list[Finding] = []

    def add(message: str, loc: list[Any], ids: list[str], hint: str, key: str) -> None:
        found.append(
            Finding(
                loaded.path,
                "info",
                "cheme.hazop-unresolved",
                message,
                line=_yaml_line(loaded.document, loc),
                ids=ids,
                hint=hint,
                key=key,
            )
        )

    for key, missing, hint in (
        ("scope", not study.scope.strip(), "say what the study covers and what it does not"),
        ("nodes", not study.nodes, "propose the nodes (skill hazop-study)"),
        (
            "assessment_basis",
            not study.assessment_basis.strip(),
            "say how risk is ranked: initial and residual, what the team credits",
        ),
    ):
        if missing:
            add(
                f"the study has no {key.replace('_', ' ')} yet",
                [key] if key in _keys(loaded.document) else [],
                [],
                hint,
                key,
            )
    if not study.analysed:
        add(
            "the study declares no analysed inputs, so no change can ask for reassessment",
            ["analysed"] if "analysed" in _keys(loaded.document) else [],
            [],
            f"list the P&IDs and control files it analyses: cheme safety hazop stamp {study.id} "
            "--input pid/P-01.xml --write",
            "analysed",
        )
    proposed = proposals(study)
    if proposed:
        add(
            f"{len(proposed)} proposal(s) the team has not accepted: {_shown(proposed)}",
            [],
            proposed[:6],
            "the team reviews each and sets status: accepted (or changes or deletes it); an "
            "agent never accepts its own proposals",
            "proposals",
        )
    rows = rating_rows(loaded)
    rated = {r.scenario for r in rows if r.which == "initial"}
    for ni, node in enumerate(study.nodes):
        if not node.deviations:
            add(
                f"node {node.id} has no deviations yet",
                ["nodes", ni],
                [node.id],
                "work through the guide words and parameters of its design intent",
                f"{node.id}:deviations",
            )
        for di, dev in enumerate(node.deviations):
            for si, scen in enumerate(dev.scenarios):
                if scen.id not in rated:
                    add(
                        f"scenario {scen.id} has no initial risk rating",
                        ["nodes", ni, "deviations", di, "scenarios", si],
                        [scen.id],
                        "the team rates severity and likelihood per category (risk.initial), "
                        "each with its basis",
                        f"{scen.id}:unrated",
                    )
    for row in rows:
        owner = f"scenario {row.scenario} ({row.which}, {row.rating.category})"
        key = f"{row.scenario}:{row.which}:{row.rating.category}"
        if row.problem == "missing":
            add(
                f"{owner}: {row.message}",
                row.loc,
                [row.scenario],
                "give both codes, or leave the category out when nothing significant happens",
                f"{key}:codes",
            )
        elif row.state == "missing":
            add(
                f"{owner}: band not looked up yet",
                row.loc,
                [row.scenario],
                f"cheme safety hazop rate {study.id} --write",
                f"{key}:band",
            )
        if not row.rating.basis.strip() and row.problem != "missing":
            add(
                f"{owner}: no basis for severity {row.rating.severity} and likelihood "
                f"{row.rating.likelihood}",
                row.loc,
                [row.scenario],
                "state the outcome and the frequency argument under basis:",
                f"{key}:basis",
            )
    return found


def _keys(document: Any) -> set[str]:
    if isinstance(document, yaml.MappingNode):
        return {k.value for k, _ in document.value if isinstance(k, yaml.ScalarNode)}
    return set()


def proposals(study: HazopStudy) -> list[str]:
    """The ids of the nodes, scenarios, safeguards and actions still ``proposed``, and of the
    scenarios with a proposed rating."""
    out = [n.id for n in study.nodes if n.status == "proposed"]
    for _, _, scen in study.scenarios():
        ratings = (scen.risk.initial + scen.risk.residual) if scen.risk else []
        if scen.status == "proposed" or any(r.status == "proposed" for r in ratings):
            out.append(scen.id)
    out += [s.id for s in study.safeguards if s.status == "proposed"]
    out += [a.id for a in study.actions if a.status == "proposed"]
    return out


# ---------------------------------------------------------------------------
# State and review
# ---------------------------------------------------------------------------


@dataclass
class ReviewStatus:
    """The newest review record that covers the study, and whether it still holds."""

    record: str | None = None
    reviewer: str = ""
    reviewer_kind: str = ""
    reviewed_commit: str = ""
    #: Human: a human reviewer, or a self review a human approved.
    human: bool = False
    #: Nothing in its scope, and no analysed input of the study, changed since.
    current: bool = False
    detail: str = ""


def review_status(workspace: Workspace, loaded: LoadedStudy) -> ReviewStatus:
    """The newest ``topic: hazop`` review record whose scope covers the study's directory. It
    holds (``current``) when its commit is in HEAD's history, it has a findings section and no
    open blocking finding, and nothing in its scope or the study's analysed inputs changed
    since."""
    from chemeascode.foundation.reviews import (
        _overlaps,
        blocking_ids,
        load_records,
        scope_changes,
    )

    directory = str(PurePosixPath(loaded.path).parent)
    records = load_records(workspace)
    covering = [
        r
        for r in records
        if r.front is not None
        and r.front.topic.strip().lower() == "hazop"
        and _overlaps(r.front.scope, [directory])
    ]
    if not covering:
        return ReviewStatus(detail=f"no topic: hazop review record covers {directory}")
    record = covering[-1]
    front = record.front
    assert front is not None
    status = ReviewStatus(
        record.name,
        front.reviewer,
        front.reviewer_kind,
        front.reviewed_commit,
        human=front.reviewer_kind == "human" or bool(front.approved_by),
    )
    commit = gitinfo.resolve(workspace.root, front.reviewed_commit)
    if commit is None:
        status.detail = f"reviewed_commit {front.reviewed_commit} is not a commit here"
        return status
    if not gitinfo.is_ancestor(workspace.root, commit):
        status.detail = f"reviewed_commit {front.reviewed_commit[:12]} is not an ancestor of HEAD"
        return status
    if not record.has_section("Findings"):
        status.detail = f"{record.name} has no ## Findings section"
        return status
    blocking = sorted(blocking_ids(records, covering))
    if blocking:
        status.detail = f"{record.name}: open blocking findings {_shown(blocking)}"
        return status
    paths = list(front.scope)
    if loaded.model is not None:
        paths += [b.path for b in loaded.model.analysed]
    found = scope_changes(workspace.root, commit, paths)
    if found is None:
        status.detail = (
            f"{record.name}: cannot tell whether its scope or the analysed inputs changed since "
            f"{front.reviewed_commit[:12]} (git failed)"
        )
        return status
    changed = [p for p in found if p != record.name]
    status.current = not changed
    status.detail = (
        f"{record.name}: {front.reviewer_kind} review of {front.reviewed_commit[:12]}"
        if not changed
        else f"{record.name}: {_shown(changed)} changed since {front.reviewed_commit[:12]}"
    )
    return status


#: The rules that keep an otherwise valid study a draft.
DRAFT_RULES = frozenset(
    {
        "cheme.hazop-unresolved",
        "cheme.hazop-band-stale",
        "cheme.hazop-action-required",
        "cheme.hazop-input-changed",
        "cheme.hazop-matrix-example",
        "cheme.hazop-example",
        "cheme.hazop-safeguard-unresolved",
        "cheme.hazop-unknown-tag",
        "cheme.hazop-not-on-sheet",
        "cheme.hazop-action-state",
    }
)


def study_state(findings: list[Finding], review: ReviewStatus | None = None) -> State:
    """``invalid``, ``draft``, ``assessed`` or ``reviewed`` from the study's findings (and its
    review). Assessed means complete and current, not safe; reviewed needs a current human
    review record."""
    if any(f.level == "error" for f in findings):
        return "invalid"
    if any(f.rule in DRAFT_RULES for f in findings):
        return "draft"
    if review is not None and review.human and review.current:
        return "reviewed"
    return "assessed"


def workspace_studies(workspace: Workspace) -> list[LoadedStudy]:
    return [load_study(workspace.root, workspace.relative(p)) for p in study_paths(workspace)]


def hazop_findings(
    workspace: Workspace,
    sheets: dict[str, tuple[Any, Any]],
    parsed: dict[str, Any],
    targets: set[Path] | None = None,
) -> tuple[list[Finding], list[str]]:
    """The findings of every study (``cheme validate``) and the files read. A matrix several
    studies share reports its own findings once. *targets* (resolved paths): only the studies
    whose file or matrix is one of them, and without the references to the plant (its lists
    and sheets are not all read then)."""
    studies = workspace_studies(workspace)
    if targets is not None:
        root = workspace.root

        def targeted(loaded: LoadedStudy) -> bool:
            paths = [loaded.path] + ([loaded.matrix.path] if loaded.matrix else [])
            return any((root / p).resolve() in targets for p in paths)

        studies = [s for s in studies if targeted(s)]
    if not studies:
        return [], []
    context = plant_context(workspace, sheets, parsed) if targets is None else None
    findings: list[Finding] = []
    files: list[str] = []
    seen: set[str] = set()
    for loaded in studies:
        files.append(loaded.path)
        if loaded.matrix is not None and loaded.matrix.path not in files:
            files.append(loaded.matrix.path)
        for finding in study_findings(workspace, loaded, context):
            if finding.file != loaded.path:
                if finding.id in seen:
                    continue
                seen.add(finding.id)
            findings.append(finding)
    return findings, files


# ---------------------------------------------------------------------------
# rate: look the bands up, and write them back
# ---------------------------------------------------------------------------


@dataclass
class RateResult:
    """``cheme safety hazop rate``: the rows looked at and what writing would change."""

    study: str
    path: str
    matrix: str | None
    matrix_id: str | None
    rows: list[RatingRow]
    #: The rows whose recorded band writing changes (adds, rewrites or removes).
    changes: list[RatingRow]
    findings: list[Finding]
    written: bool = False
    #: Ratings whose likelihood the frequency library gives otherwise (set when written).
    likelihoods: list[LikelihoodRow] = field(default_factory=list)


def _target_scenarios(study: HazopStudy, target: str | None) -> set[str]:
    if target is None:
        return {s.id for _, _, s in study.scenarios()}
    found: set[str] = set()
    for node in study.nodes:
        for dev in node.deviations:
            for scen in dev.scenarios:
                if target in (node.id, dev.id, scen.id):
                    found.add(scen.id)
    if not found:
        raise ValueError(
            f"{target} is no node, deviation or scenario of study {study.id} (or has no scenarios)"
        )
    return found


def rate(
    workspace: Workspace, study_id: str, target: str | None = None, *, write: bool
) -> RateResult:
    """Look up the band of every rating of the study (or of the node, deviation or scenario
    *target*) in its matrix. With *write*, record the bands that are missing, stale or edited,
    and remove those that can no longer be looked up; nothing else in the file changes.

    Raises ValueError for a study that does not exist or does not load, or an unknown target.
    """
    path = study_path(study_id)
    if not (workspace.root / path).is_file():
        raise ValueError(f"no study {path}")
    loaded = load_study(workspace.root, path)
    if loaded.model is None:
        raise ValueError(f"{path} does not load; run cheme safety hazop check {study_id}")
    wanted = _target_scenarios(loaded.model, target)
    # Likelihoods linked to the frequency library first: the bands are looked up from them.
    likelihoods = [r for r in likelihood_rows(loaded) if r.scenario in wanted and r.changes]
    if write and likelihoods:
        file = workspace.root / path
        derived = {tuple(r.loc): ("likelihood", r.derived.code) for r in likelihoods}
        text = _read(file)
        _write(file, write_keys(text, yaml.compose(text), derived))
        loaded = load_study(workspace.root, path)
        if loaded.model is None:
            raise ValueError(f"{path} does not load after writing the likelihoods")
    rows = [r for r in rating_rows(loaded) if r.scenario in wanted]
    findings: list[Finding] = []
    matrix = loaded.matrix
    if matrix is None:
        findings.append(
            Finding(
                path,
                "error",
                "cheme.hazop-matrix",
                "the study names no risk_matrix",
                hint="name the matrix file under risk_matrix: (cheme schema risk-matrix)",
            )
        )
    elif not matrix.usable:
        findings += [f for f in matrix.findings if f.level == "error"]
    else:
        for finding in study_findings(workspace, loaded):
            relevant = finding.rule in (
                "cheme.hazop-unknown-code",
                "cheme.hazop-rating-duplicate",
                "cheme.hazop-band-edited",
                "cheme.hazop-frequency",
            ) or (finding.rule == "cheme.hazop-unresolved" and ":codes" in finding.key)
            if relevant and (not finding.ids or finding.ids[0] in wanted):
                findings.append(finding)
    usable = matrix is not None and matrix.usable
    changes = [
        r
        for r in rows
        if usable
        and (
            r.state in ("missing", "stale", "edited")
            or (r.state == "unresolved" and r.rating.band is not None)
        )
    ]
    result = RateResult(
        study_id,
        path,
        matrix.path if matrix else None,
        matrix.model.id if matrix and matrix.model else None,
        rows,
        changes,
        findings,
        likelihoods=likelihoods,
    )
    result.written = write and bool(likelihoods)
    if write and changes:
        assert matrix is not None and matrix.model is not None
        source = f"{RATE_SOURCE}: {matrix.model.id} ({matrix.path})"
        edits = {}
        for row in changes:
            band = (
                {
                    "value": row.band,
                    "provenance": "calculated",
                    "source": source,
                    "fingerprint": row.fingerprint,
                    "inputs": {
                        "matrix": matrix.fingerprint,
                        "category": row.rating.category,
                        "severity": row.rating.severity,
                        "likelihood": row.rating.likelihood,
                    },
                }
                if row.band is not None
                else None
            )
            edits[tuple(row.loc)] = band
        file = workspace.root / path
        # Positions from the text as it is on disk: a CRLF file shifts the translated ones.
        text = _read(file)
        _write(file, write_bands(text, yaml.compose(text), edits))
        result.written = True
    return result


def _node_at(document: Any, loc: Iterable[Any]) -> Any:
    node = document
    for step in loc:
        if isinstance(node, yaml.MappingNode):
            node = next(
                (v for k, v in node.value if isinstance(k, yaml.ScalarNode) and k.value == step),
                None,
            )
        elif isinstance(node, yaml.SequenceNode) and isinstance(step, int):
            node = node.value[step] if 0 <= step < len(node.value) else None
        else:
            return None
    return node


def _flow(data: dict[str, Any]) -> str:
    return yaml.safe_dump(data, default_flow_style=True, sort_keys=False, width=10**6).strip()


def _line_start(text: str, index: int) -> int:
    return text.rfind("\n", 0, index) + 1


def _line_end(text: str, index: int) -> int:
    """The index after the newline that ends the line holding the character before *index*
    (the last character of a node's content)."""
    end = text.find("\n", max(index - 1, 0))
    return len(text) if end < 0 else end + 1


def _content_end(node: Any) -> int:
    """The index just after the last character of *node*'s own text. PyYAML ends a block
    collection at the next token (the next key or item, after any comments), so its end is
    taken from its last child instead."""
    if isinstance(node, yaml.MappingNode) and not node.flow_style and node.value:
        return _content_end(node.value[-1][1])
    if isinstance(node, yaml.SequenceNode) and not node.flow_style and node.value:
        return _content_end(node.value[-1])
    if isinstance(node, yaml.ScalarNode) and node.style in ("|", ">"):
        return node.end_mark.index  # a block scalar ends at the start of the next line
    return node.end_mark.index


def write_bands(
    text: str, document: Any, edits: dict[tuple[Any, ...], dict[str, Any] | None]
) -> str:
    """*text* with the ``band:`` of each rating at a location of *edits* set (or removed for
    None). Only those entries change: every other line, comment and key order stays, and the
    file's line endings are kept."""
    return write_keys(text, document, {loc: ("band", band) for loc, band in edits.items()})


def write_keys(text: str, document: Any, edits: dict[tuple[Any, ...], tuple[str, Any]]) -> str:
    """*text* with one key of each rating at a location of *edits* set to its value (a mapping
    or a code; None removes the key), in place as :func:`write_bands` does."""
    eol = "\r\n" if "\r\n" in text else "\n"
    changes: list[tuple[int, int, str]] = []  # (start, end, replacement) as text indices
    for loc, (name, band) in edits.items():
        rating = _node_at(document, loc)
        if not isinstance(rating, yaml.MappingNode) or not rating.value:
            raise ValueError(f"rating at {'.'.join(map(str, loc))} is not a mapping")
        keys = [k.value if isinstance(k, yaml.ScalarNode) else None for k, _ in rating.value]
        at_band = keys.index(name) if name in keys else None
        value = _flow(band) if isinstance(band, dict) else _scalar(str(band or ""))
        new = f"{name}: {value}" if band is not None else ""
        if rating.flow_style:
            if at_band is not None:
                key, value = rating.value[at_band]
                if band is not None:
                    changes.append((key.start_mark.index, _content_end(value), new))
                elif at_band > 0:  # from the end of the entry before it
                    start = _content_end(rating.value[at_band - 1][1])
                    changes.append((start, _content_end(value), ""))
                elif len(rating.value) > 1:  # the first entry: up to the next key
                    following = rating.value[1][0].start_mark.index
                    changes.append((key.start_mark.index, following, ""))
                else:
                    changes.append((key.start_mark.index, _content_end(value), ""))
            elif band is not None:
                at = rating.end_mark.index - 1  # the closing brace
                while at > 0 and text[at - 1] in " \t\r\n":
                    at -= 1
                changes.append((at, at, f" {new}" if text[at - 1] == "," else f", {new}"))
            continue
        indent = " " * rating.value[0][0].start_mark.column
        if at_band is not None:
            key, value = rating.value[at_band]
            start = _line_start(text, key.start_mark.index)
            end = _line_end(text, _content_end(value))
            changes.append((start, end, f"{indent}{new}{eol}" if band is not None else ""))
        elif band is not None:
            at = _line_end(text, _content_end(rating.value[-1][1]))
            prefix = eol if at == len(text) and not text.endswith("\n") else ""
            changes.append((at, at, f"{prefix}{indent}{new}{eol}"))
    for start, end, replacement in sorted(changes, key=lambda c: (c[0], c[1]), reverse=True):
        text = text[:start] + replacement + text[end:]
    return text


def _read(path: Path) -> str:
    """The text of *path* with its line endings as they are."""
    with path.open(encoding="utf-8", newline="") as handle:
        return handle.read()


def _write(path: Path, text: str) -> None:
    with path.open("w", encoding="utf-8", newline="") as handle:
        handle.write(text)


# ---------------------------------------------------------------------------
# init and stamp
# ---------------------------------------------------------------------------


def new_study(
    workspace: Workspace,
    study_id: str,
    title: str = "",
    inputs: Iterable[str] = (),
    matrix: str | None = None,
) -> str:
    """The text of a new draft study: the header, the analysed *inputs* at their current
    revision, and an empty worksheet; nothing in it is a judgement yet."""
    study = HazopStudy.model_validate(
        {
            "schema": STUDY_SCHEMA,
            "kind": "hazop-study",
            "id": study_id,
            "title": title,
            "risk_matrix": matrix,
            "analysed": [
                {
                    "path": p,
                    "revision": current_revision(workspace, p),
                    "relation": "analyses",
                }
                for p in (i.strip().removeprefix("./").rstrip("/") for i in inputs)
            ],
        }
    )
    analysed = "\n".join(
        "  - " + _flow({"path": b.path, "revision": b.revision, "relation": "analyses"})
        for b in study.analysed
    )
    return (
        f"# HAZOP study {study_id}: a DRAFT until the team has accepted every entry and a\n"
        "# human review record covers it (cheme safety hazop check). Schema: cheme schema\n"
        "# hazop-study; workflow: safety/README.md and the skill hazop-study.\n"
        f"schema: {STUDY_SCHEMA}\n"
        "kind: hazop-study\n"
        f"id: {study_id}\n"
        f"title: {_scalar(title)}\n"
        "scope: ''           # what the study covers, and what it does not\n"
        "modes: []           # [{id: normal, title: Normal operation}, {id: startup, ...}]\n"
        + (
            f"analysed:\n{analysed}\n"
            if analysed
            else "analysed: []        # cheme safety hazop stamp\n"
        )
        + f"risk_matrix: {matrix or 'null'}\n"
        "assessment_basis: '' # how risk is ranked: initial before safeguards, residual with them\n"
        "team: []            # [{name: ..., role: facilitator}]\n"
        "nodes: []\n"
        "safeguards: []\n"
        "actions: []\n"
    )


def _scalar(value: str) -> str:
    """*value* as a one-line YAML scalar."""
    return yaml.safe_dump(value, width=10**6).removesuffix("...\n").strip() if value else "''"


def current_revision(workspace: Workspace, path: str) -> str:
    """The revision to record for the analysed input *path*: ``sha256:`` of a file, the HEAD
    commit for a directory (which must have no uncommitted change, so the commit identifies
    it). Raises ValueError for anything else."""
    target = workspace.root / path
    if target.is_file():
        return provenance.file_fingerprint(target)
    if not target.is_dir() or not workspace.contains(target):
        raise ValueError(f"{path} is no file or directory of the repository")
    head = gitinfo.head(workspace.root)
    if head is None:
        raise ValueError(f"{path} is a directory: recording it needs a git commit")
    prefix = path.rstrip("/") + "/"
    found = gitinfo.dirty_paths(workspace.root)
    if found is None:
        raise ValueError(
            f"{path} is a directory and git cannot tell whether it has uncommitted changes "
            "(git status failed): run `git status` and fix the repository first"
        )
    dirty = [p for p in found if p.startswith(prefix)]
    if dirty:
        raise ValueError(
            f"{path} has uncommitted changes ({_shown(dirty)}): commit them first, so the "
            "commit identifies what was analysed"
        )
    return head


@dataclass
class Stamp:
    path: str
    old: str | None
    new: str | None  # None: the file does not exist


def stamp(
    workspace: Workspace, study_id: str, add: Iterable[str] = (), *, write: bool
) -> list[Stamp]:
    """The analysed inputs of the study at their current revision (:func:`current_revision`;
    one unchanged since its recorded revision keeps it), with the paths in *add* added; with
    *write*, record them (the ``analysed:`` block is rewritten, the
    rest of the file stays). Only after the team reassessed what changed."""
    path = study_path(study_id)
    file = workspace.root / path
    if not file.is_file():
        raise ValueError(f"no study {path}")
    loaded = load_study(workspace.root, path)
    if loaded.model is None:
        raise ValueError(f"{path} does not load; run cheme safety hazop check {study_id}")
    entries = [(b.path, b.revision, b.relation) for b in loaded.model.analysed]
    for extra in add:
        extra = extra.strip().removeprefix("./").rstrip("/")
        current_revision(workspace, extra)  # refuses what cannot be recorded
        if extra not in [e[0] for e in entries]:
            entries.append((extra, "", "analyses"))
    stamps = []
    for p, old, _ in entries:
        if not (workspace.root / p).exists():
            stamps.append(Stamp(p, old or None, None))
        elif old and provenance.changed_since(workspace.root, p, old) == []:
            stamps.append(Stamp(p, old, old))  # unchanged: the recorded revision stays
        else:
            stamps.append(Stamp(p, old or None, current_revision(workspace, p)))
    if write:
        text = _read(file)
        eol = "\r\n" if "\r\n" in text else "\n"
        lines = [
            "  - " + _flow({"path": p, "revision": s.new or old, "relation": relation}) + eol
            for (p, old, relation), s in zip(entries, stamps, strict=True)
        ]
        block = f"analysed:{eol}" + "".join(lines) if lines else f"analysed: []{eol}"
        _write(file, _replace_key(text, yaml.compose(text), "analysed", block))
    return stamps


def _replace_key(text: str, document: Any, key: str, block: str) -> str:
    """*text* with the top-level *key* (and its value) replaced by *block*, or *block* added
    at the end when there is no such key."""
    if not isinstance(document, yaml.MappingNode):
        raise ValueError("the study is not a mapping")
    for k, v in document.value:
        if isinstance(k, yaml.ScalarNode) and k.value == key:
            start = _line_start(text, k.start_mark.index)
            return text[:start] + block + text[_line_end(text, _content_end(v)) :]
    return text + ("" if text.endswith("\n") else "\n") + block


def scenario_of(study: HazopStudy, scenario_id: str) -> Scenario | None:
    return next((s for _, _, s in study.scenarios() if s.id == scenario_id), None)
