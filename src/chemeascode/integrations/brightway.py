"""Characterisation through Brightway 2.5 (extra ``lca``: bw2data, bw2calc).

:func:`unit_scores` gives, for each requested activity of a Brightway project, its cradle-to-
gate impact per unit of its reference product in each method, and for each requested
biosphere flow its characterisation factor. It reads the project, it writes nothing into it:
no foreground database is created, so a user's project (ecoinvent, premise scenario databases)
stays as it was. The project directory is Brightway's own (``BRIGHTWAY2_DIR`` or the platform
default).

bw2data and bw2calc are imported inside the functions. They print progress bars and warnings
on import and calculation; both are silenced here.
"""

from __future__ import annotations

import contextlib
import hashlib
import io
import json
import warnings
from dataclasses import dataclass, field
from itertools import zip_longest
from typing import Any

EXTRA = "pip install 'cheme-as-code[lca]'"

#: Brightway's unit names -> (quantity kind, factor to the inventory unit of that kind).
UNITS = {
    "kilogram": ("mass", 1.0),
    "ton": ("mass", 1000.0),
    "kilowatt hour": ("energy", 1.0),
    "megajoule": ("energy", 1 / 3.6),
    "meter": ("length", 1.0),
    "kilometer": ("length", 1000.0),
    "square meter": ("area", 1.0),
    "cubic meter": ("volume", 1.0),
    "unit": ("count", 1.0),
    "ton kilometer": ("transport", 1.0),
}


class BrightwayUnavailable(RuntimeError):
    """bw2data or bw2calc is not installed."""


@dataclass
class ActivityRef:
    """An activity to find: database, name, and optionally reference product and location."""

    database: str
    name: str
    reference_product: str | None = None
    location: str | None = None


@dataclass
class FlowRef:
    """A biosphere flow to find: database, name and compartments; or, with *cas*, the flow of
    that CAS number in the compartment ``categories[0]`` (the sub-compartment ``categories``
    names first, else the unspecified one), fossil, non-fossil or from land-use change by
    *origin*. With *uuid* (the flow's biosphere3 identity, pre-release issue 175) the flow whose
    code is that UUID is taken first; CAS and name are the fallback for databases with other
    codes."""

    database: str
    name: str
    categories: tuple[str, ...] = ()
    cas: str | None = None
    origin: str = "fossil"
    uuid: str | None = None


def _cas(text: object) -> str:
    """A CAS number without spaces and the zero padding some databases add (000124-38-9)."""
    value = str(text or "").strip().replace(" ", "")
    head, _, rest = value.partition("-")
    return f"{head.lstrip('0') or '0'}-{rest}" if rest else value


def _origin_rank(name: str, origin: str) -> int:
    """0 for a flow name of the wanted origin, 1 for one that names none, 2 for the other one
    (ecoinvent: fossil / non-fossil; EF: (fossil) / (biogenic); also from soil or biomass)."""
    text = name.lower()
    luc = any(w in text for w in ("soil or biomass", "land use change", "land-use change"))
    if origin == "land-use-change":
        return 0 if luc else 2
    biogenic = not luc and any(w in text for w in ("non-fossil", "biogenic", "biomass"))
    fossil = "fossil" in text and "non-fossil" not in text
    if origin == "biogenic":
        return 0 if biogenic else (1 if not fossil else 2)
    return 0 if fossil else (1 if not (biogenic or luc) else 2)


@dataclass
class Scores:
    """Per-unit impacts by reference index, per method (a tuple of names)."""

    #: Method -> its unit, for the methods found.
    method_units: dict[tuple[str, ...], str] = field(default_factory=dict)
    #: Index of the reference -> (Brightway unit, {method: score per unit}).
    found: dict[int, tuple[str, dict[tuple[str, ...], float]]] = field(default_factory=dict)
    #: Index of the reference -> why it was not found (missing, ambiguous).
    problems: dict[int, str] = field(default_factory=dict)
    #: Problems of the whole call: no such project, unknown methods.
    errors: list[str] = field(default_factory=list)
    #: Code and display of each activity found, by index (for the results).
    labels: dict[int, str] = field(default_factory=dict)
    #: Index of a biosphere flow -> the methods that do not characterise it (factor 0).
    uncharacterised: dict[int, list[tuple[str, ...]]] = field(default_factory=dict)


@contextlib.contextmanager
def _quiet():
    with warnings.catch_warnings():
        warnings.simplefilter("ignore")
        with contextlib.redirect_stderr(io.StringIO()), contextlib.redirect_stdout(io.StringIO()):
            yield


def _modules() -> tuple[Any, Any]:
    try:
        with _quiet():
            import bw2calc
            import bw2data
    except ImportError as failure:
        raise BrightwayUnavailable(f"Brightway is not installed: {EXTRA}") from failure
    return bw2data, bw2calc


def _close_connections(bd: Any) -> None:
    """Close the SQLite connections bw2data holds in this thread: ``projects.db`` and the
    current project's databases (``config.sqlite3_databases``: the LCI and the parameters).
    bw2data opens them on import and on ``projects.set_current`` and never closes them; peewee
    keeps one per thread, so a thread that ends (a worker of ``cheme serve``) left them to the
    garbage collector (``ResourceWarning: unclosed database``). peewee reconnects on the next
    query, so closing after each call costs a reconnect, nothing more."""
    from bw2data.configuration import config

    for database in (bd.projects.db, *(db for _, db in config.sqlite3_databases)):
        with contextlib.suppress(Exception):  # one that cannot close is not ours to fix
            database.db.close()


@contextlib.contextmanager
def _session():
    """bw2data and bw2calc, quiet, with the connections opened meanwhile closed after."""
    bd, bc = _modules()
    try:
        with _quiet():
            yield bd, bc
    finally:
        _close_connections(bd)


def available() -> bool:
    """Whether bw2data and bw2calc import."""
    try:
        with _session():
            pass
    except BrightwayUnavailable:
        return False
    return True


def _is_flow(node_type: str | None) -> bool:
    """Whether a node of *node_type* is a biosphere flow (not a process or product)."""
    from bw2data import labels

    return (node_type or labels.process_node_default) not in labels.lci_node_types


def _production(node: Any) -> float:
    """The amount of the node's reference product its activity makes: negative for a
    treatment activity (ecoinvent: a waste is its reference product, produced -1)."""
    amounts = [exchange["amount"] for exchange in node.production()]
    return sum(amounts) if amounts else 1.0


def _factor(cfs: list, node: Any) -> float | None:
    """The method's factor of *node* (None when it has none). An entry is ``(flow, amount)`` or
    regionalised ``(flow, amount, location)``; a global one is preferred."""
    found: list[tuple[float, Any]] = []
    for entry in cfs:
        key, amount = entry[0], entry[1]
        if key != node.id and key != node.key:
            continue
        location = entry[2] if len(entry) > 2 else None
        if isinstance(amount, dict):
            amount = amount.get("amount", 0.0)
        found.append((float(amount), location))
    if not found:
        return None
    global_ = [amount for amount, location in found if location in (None, "GLO")]
    return global_[0] if global_ else found[0][0]


def _find_activity(bd: Any, ref: ActivityRef) -> tuple[Any | None, str]:
    from bw2data.backends.schema import ActivityDataset as AD

    query = AD.select().where(AD.database == ref.database, AD.name == ref.name)
    if ref.reference_product is not None:
        query = query.where(AD.product == ref.reference_product)
    if ref.location is not None:
        query = query.where(AD.location == ref.location)
    rows = [r for r in query if not _is_flow(r.type)]
    if not rows:
        return None, f"no activity {ref.name!r} in database {ref.database!r}"
    if len(rows) > 1:
        options = ", ".join(sorted({f"{r.product} [{r.location}]" for r in rows})[:6])
        return None, (
            f"{len(rows)} activities {ref.name!r} in {ref.database!r} ({options}); give "
            "reference_product and location"
        )
    return bd.get_node(id=rows[0].id), ""


def _find_flow(bd: Any, ref: FlowRef) -> tuple[Any | None, str]:
    from bw2data.backends.schema import ActivityDataset as AD

    if ref.uuid is not None:
        found = [
            r
            for r in AD.select().where(AD.database == ref.database, AD.code == ref.uuid)
            if _is_flow(r.type)
        ]
        if found:
            return bd.get_node(id=found[0].id), ""
    if ref.cas is not None:
        compartment = ref.categories[0] if ref.categories else "air"
        cas = _cas(ref.cas)
        rows = [
            r
            for r in AD.select().where(AD.database == ref.database)
            if _is_flow(r.type)
            and _cas(r.data.get("CAS number")) == cas
            and tuple(r.data.get("categories") or ())[:1] == (compartment,)
        ]
        if not rows:
            return None, f"no biosphere flow of CAS {ref.cas} to {compartment} in {ref.database!r}"

        def rank(r: Any) -> tuple[int, int, int, str]:
            categories = tuple(r.data.get("categories") or ())
            return (
                _origin_rank(r.name or "", ref.origin),
                0 if len(ref.categories) < 2 or categories == tuple(ref.categories) else 1,
                len(r.data.get("categories") or ()),
                r.name or "",
            )

        return bd.get_node(id=min(rows, key=rank).id), ""

    rows = [
        r
        for r in AD.select().where(AD.database == ref.database, AD.name == ref.name)
        if _is_flow(r.type)
        and (not ref.categories or tuple(r.data.get("categories") or ()) == tuple(ref.categories))
    ]
    if not rows:
        return None, f"no biosphere flow {ref.name!r} {list(ref.categories)} in {ref.database!r}"
    if len(rows) > 1:
        options = "; ".join(sorted({str(list(r.data.get("categories") or ())) for r in rows})[:6])
        return (
            None,
            f"{len(rows)} flows {ref.name!r} in {ref.database!r} ({options}); give categories",
        )
    return bd.get_node(id=rows[0].id), ""


def unit_scores(
    project: str,
    methods: list[tuple[str, ...]],
    activities: dict[int, ActivityRef],
    flows: dict[int, FlowRef],
) -> Scores:
    """Impacts per unit of each of *activities* and factors of *flows* in *methods*, from the
    Brightway *project*. Raises :class:`BrightwayUnavailable` without the extra."""
    result = Scores()
    with _session() as (bd, bc):
        if project not in bd.projects:
            result.errors.append(f"no Brightway project {project!r} (BRIGHTWAY2_DIR)")
            return result
        bd.projects.set_current(project)
        for method in methods:
            if method not in bd.methods:
                result.errors.append(f"no method {list(method)} in project {project!r}")
            else:
                result.method_units[method] = bd.methods[method].get("unit", "")
        if result.errors:
            return result
        nodes: dict[int, Any] = {}
        for index, ref in activities.items():
            if ref.database not in bd.databases:
                result.problems[index] = f"no database {ref.database!r} in project {project!r}"
                continue
            node, problem = _find_activity(bd, ref)
            if node is None:
                result.problems[index] = problem
                continue
            nodes[index] = node
            result.labels[index] = f"{node['name']} [{node.get('location', '')}]"
        if nodes:
            # One unit of each reference product: a demand of the production's sign (a
            # treatment activity, production -1, treats one unit for a demand of -1).
            demand = {
                index: {node.id: 1.0 if _production(node) >= 0 else -1.0}
                for index, node in nodes.items()
            }
            lca = bc.LCA({node.id: 1 for node in nodes.values()}, methods[0])
            lca.lci(factorize=len(nodes) > 1)
            scores: dict[int, dict[tuple[str, ...], float]] = {i: {} for i in nodes}
            for number, method in enumerate(methods):
                if number:
                    lca.switch_method(method)
                for index in nodes:
                    lca.lcia(demand=demand[index])
                    scores[index][method] = float(lca.score)
            for index, node in nodes.items():
                result.found[index] = (node.get("unit", ""), scores[index])
        for index, ref in flows.items():
            if ref.database not in bd.databases:
                result.problems[index] = f"no database {ref.database!r} in project {project!r}"
                continue
            node, problem = _find_flow(bd, ref)
            if node is None:
                result.problems[index] = problem
                continue
            factors: dict[tuple[str, ...], float] = {}
            for method in methods:
                factor = _factor(bd.Method(method).load(), node)
                if factor is None:
                    result.uncharacterised.setdefault(index, []).append(method)
                factors[method] = factor or 0.0
            result.found[index] = (node.get("unit", ""), factors)
            result.labels[index] = f"{node['name']} {list(node.get('categories') or ())}"
    return result


#: Metadata keys of ``bd.databases[name]`` that identify a database.
IDENTITY = ("provider", "version", "system_model")


def databases(project: str, names: list[str]) -> dict[str, dict[str, Any] | None]:
    """For each of *names* in *project*: its identity metadata (:data:`IDENTITY`, the values the
    database records, "" when it records none) and its number of nodes, or None when the project
    has no such database. Raises :class:`BrightwayUnavailable` without the extra, and
    :class:`LookupError` without the project."""
    found: dict[str, dict[str, Any] | None] = {}
    with _session() as (bd, _):
        if project not in bd.projects:
            raise LookupError(f"no Brightway project {project!r} (BRIGHTWAY2_DIR)")
        bd.projects.set_current(project)
        for name in names:
            if name not in bd.databases:
                found[name] = None
                continue
            meta = bd.databases[name]
            found[name] = {
                **{key: str(meta.get(key) or "") for key in IDENTITY},
                "nodes": len(bd.Database(name)),
            }
    return found


def _amount(value: Any) -> float:
    return float(value.get("amount", 0.0)) if isinstance(value, dict) else float(value)


def _flow_label(bd: Any, flow: Any) -> str:
    """A characterised flow by its (database, code) key, the same in every project; an integer
    id (project-local) is resolved to its key."""
    if isinstance(flow, int):
        try:
            flow = bd.get_node(id=flow).key
        except Exception:  # noqa: BLE001 - an id the project cannot resolve
            return '"unresolved"'  # never a project-local id: the fingerprint stays portable
    return json.dumps(list(flow) if isinstance(flow, (tuple, list)) else flow, default=str)


def method_fingerprints(project: str, methods: list[tuple[str, ...]]) -> dict[str, str | None]:
    """For each of *methods* in *project*: a sha256 of its unit and characterisation factors
    (flow key and amount, sorted), or None when the project has no such method. The key is the
    method's names joined by ``" | "``. Raises :class:`BrightwayUnavailable` without the extra,
    and :class:`LookupError` without the project."""
    found: dict[str, str | None] = {}
    with _session() as (bd, _):
        if project not in bd.projects:
            raise LookupError(f"no Brightway project {project!r} (BRIGHTWAY2_DIR)")
        bd.projects.set_current(project)
        for method in methods:
            key = " | ".join(method)
            if method not in bd.methods:
                found[key] = None
                continue
            try:
                rows = sorted(
                    (
                        _flow_label(bd, entry[0]),
                        repr(float(_amount(entry[1]))),
                        str(entry[2]) if len(entry) > 2 else "",
                    )
                    for entry in bd.Method(method).load()
                )
            except (IndexError, TypeError, ValueError, KeyError):
                found[key] = None  # an unreadable method: no fingerprint, the run goes on
                continue
            text = json.dumps([bd.methods[method].get("unit", ""), rows])
            found[key] = "sha256:" + hashlib.sha256(text.encode()).hexdigest()
    return found


def versions() -> dict[str, str]:
    """The installed bw2data and bw2calc versions (major.minor), for a run's manifest."""
    from importlib.metadata import PackageNotFoundError, version

    found = {}
    for name in ("bw2data", "bw2calc"):
        try:
            found[name] = ".".join(version(name).split(".")[:2])
        except PackageNotFoundError:
            continue
    return found


def search(project: str, text: str, database: str | None = None, limit: int = 20) -> list[dict]:
    """Activities and biosphere flows of *project* whose name, product or location match
    *text*: database, name, reference product, location, unit, categories and whether it is a
    biosphere flow, to copy into ``lca/lca.yaml``. Without *database*, the results of the
    databases alternate, so one database cannot fill the list."""
    with _session() as (bd, _):
        if project not in bd.projects:
            raise LookupError(f"no Brightway project {project!r} (BRIGHTWAY2_DIR)")
        bd.projects.set_current(project)
        names = [database] if database else sorted(bd.databases)
        per_database = []
        for name in names:
            if name not in bd.databases:
                raise LookupError(f"no database {name!r} in project {project!r}")
            per_database.append(
                [
                    {
                        "database": name,
                        "name": node["name"],
                        "reference_product": node.get("reference product"),
                        "location": node.get("location"),
                        "unit": node.get("unit"),
                        "categories": list(node.get("categories") or ()),
                        "biosphere": _is_flow(node.get("type")),
                    }
                    for node in bd.Database(name).search(text, limit=limit)
                ]
            )
    found = [item for group in zip_longest(*per_database) for item in group if item]
    return found[:limit]
