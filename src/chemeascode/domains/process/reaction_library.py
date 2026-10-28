"""The reaction library: industrial processes as ready process files.

Each entry (``domains/process/data/library/<id>.yaml``, schema ``cheme/library/v1``, generated
by ``scripts/build_reaction_library.py`` from ``scripts/reaction_library.yaml``) holds the
components of a process (identity, molar mass, ideal-gas data and critical constants from
chemicals), its main and side reactions (stoichiometry, reversibility, heats of reaction where a
literature value is known, the catalyst), its typical catalysts (active phase, promoters,
support, operating window, poisons; provenance assumed), its operating window, with sources, and
its ``model_basis``: which reactor model the entry's own data supports (:class:`ModelBasis`).
Importing an entry brings chemistry, not a process model: an entry classified
``stoichiometry_only`` gives neither conversions, an equilibrium basis nor rate laws, and the
reactor model is sourced and chosen separately. :func:`add_entry` adds an entry to a plant
repository: the components, reactions and catalysts it does not have yet go into
``process/materials.yaml``, ``process/reactions.yaml`` and ``process/catalysts.yaml``, appended
after the existing items so the files keep their comments; an id the plant has with other data
is a conflict and nothing is written.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from functools import cache
from importlib import resources
from pathlib import Path
from typing import Any, Literal

import yaml
from pydantic import Field, model_validator

from chemeascode.domains.chemistry.catalysts import CATALYSTS_FILE, Catalyst
from chemeascode.domains.chemistry.catalysts import SCHEMA as CATALYSTS_SCHEMA
from chemeascode.domains.chemistry.reactions import REACTIONS_FILE, Reaction
from chemeascode.domains.chemistry.reactions import SCHEMA as REACTIONS_SCHEMA
from chemeascode.domains.process import MATERIALS_FILE, SCHEMA
from chemeascode.domains.process.schema import Component
from chemeascode.foundation.schema_base import Strict, unsupported_schema

LIBRARY_SCHEMA = "cheme/library/v1"

#: From weakest to strongest: what reactor model an entry's own data supports.
MODEL_BASES = ("stoichiometry_only", "conversion_selectivity", "equilibrium", "kinetic")
ModelBasisKind = Literal["stoichiometry_only", "conversion_selectivity", "equilibrium", "kinetic"]


class Window(Strict):
    temperature: tuple[float, float] = Field(description="K, min and max")
    pressure: tuple[float, float] = Field(description="kPa(a), min and max")


class ModelBasis(Strict):
    """Which reactor model the entry's own data supports (checked against the data):

    - ``stoichiometry_only``: stoichiometry, thermochemistry and catalyst windows; no
      conversion, selectivity, equilibrium basis or rate law: a reactor model must be sourced
      and chosen separately;
    - ``conversion_selectivity``: every reaction gives the conversion of its key component;
      ``provenance: given`` only when every conversion is given with a source;
    - ``equilibrium``: every reaction is reversible, in the gas phase, and has an equilibrium
      constant or the ideal-gas formation data of all its components over the entry's whole
      temperature window: an ideal-gas equilibrium limit, not a kinetic model;
    - ``kinetic``: every reaction has a rate law.
    """

    kind: ModelBasisKind
    provenance: Literal["given", "assumed"] | None = Field(
        default=None, description="conversion_selectivity: given (sourced) or assumed."
    )
    note: str = Field(default="", description="What the classification does not cover.")


class LibraryEntry(Strict):
    """One industrial process."""

    schema_: str = Field(alias="schema", description=f"Always {LIBRARY_SCHEMA}.")
    kind: Literal["library-entry"]
    id: str
    title: str
    window: Window
    components: list[Component]
    reactions: list[Reaction]
    model_basis: ModelBasis
    catalysts: list[Catalyst] = Field(default_factory=list)
    sources: list[str] = Field(default_factory=list)

    @model_validator(mode="after")
    def _version(self) -> LibraryEntry:
        if self.schema_ != LIBRARY_SCHEMA:
            raise ValueError(unsupported_schema(self.schema_, LIBRARY_SCHEMA))
        problem = basis_problem(self, self.model_basis)
        if problem:
            raise ValueError(f"library entry {self.id}: model_basis {problem}")
        return self


def basis_problem(entry: LibraryEntry, basis: ModelBasis) -> str:
    """Why *entry*'s data does not support *basis* ("" when it does)."""
    reactions = entry.reactions
    if basis.kind == "kinetic":
        lacking = [r.id for r in reactions if r.rate is None]
        return f"kinetic: no rate law for {', '.join(lacking)}" if lacking else ""
    if basis.kind == "conversion_selectivity":
        lacking = [r.id for r in reactions if r.conversion is None]
        if lacking:
            return f"conversion_selectivity: no conversion for {', '.join(lacking)}"
        if basis.provenance is None:
            return "conversion_selectivity: give provenance (given or assumed)"
        unsourced = [
            r.id
            for r in reactions
            if r.conversion is not None
            and (r.conversion.provenance != "given" or not r.conversion.source.strip())
        ]
        if basis.provenance == "given" and unsourced:
            return f"conversion_selectivity given: no sourced conversion for {', '.join(unsourced)}"
        return ""
    if basis.provenance is not None:
        return f"{basis.kind}: provenance is for conversion_selectivity only"
    if basis.kind == "equilibrium":
        lo, hi = entry.window.temperature
        data = {c.id: c.ideal_gas for c in entry.components}
        problems = []
        for r in reactions:
            if not r.reversible:
                problems.append(f"{r.id} is irreversible")
            elif r.phase in ("liquid", "mixed"):
                problems.append(f"{r.id} is a {r.phase}-phase reaction (no ideal-gas K)")
            elif r.equilibrium_constant is not None:
                if not (r.equilibrium_constant.covers(lo) and r.equilibrium_constant.covers(hi)):
                    problems.append(f"{r.id}: its equilibrium constant does not cover the window")
            else:
                gaps = [n for n in r.stoichiometry if data.get(n) is None]
                short = [
                    n
                    for n in r.stoichiometry
                    if (d := data.get(n)) is not None and not (d.covers(lo) and d.covers(hi))
                ]
                if gaps:
                    problems.append(f"{r.id}: no ideal-gas data for {', '.join(gaps)}")
                if short:
                    problems.append(
                        f"{r.id}: heat capacity of {', '.join(short)} does not cover "
                        f"{lo:g}-{hi:g} K"
                    )
        return "equilibrium: " + "; ".join(problems) if problems else ""
    return ""


def strongest_basis(entry: LibraryEntry) -> str:
    """The strongest :data:`MODEL_BASES` kind *entry*'s data supports (conversions as
    assumed)."""
    for kind in reversed(MODEL_BASES):
        provenance = "assumed" if kind == "conversion_selectivity" else None
        if not basis_problem(entry, ModelBasis(kind=kind, provenance=provenance)):  # type: ignore[arg-type]
            return kind
    return "stoichiometry_only"


@cache
def entries() -> dict[str, LibraryEntry]:
    """Every library entry by id."""
    folder = resources.files("chemeascode.domains.process") / "data" / "library"
    found = {}
    for item in sorted(folder.iterdir(), key=lambda p: p.name):
        if item.name.endswith(".yaml"):
            entry = LibraryEntry.model_validate(yaml.safe_load(item.read_text(encoding="utf-8")))
            found[entry.id] = entry
    return found


class Conflict(ValueError):
    """The plant has an id of the entry with other data."""


@dataclass
class Added:
    """What :func:`add_entry` added, by file, and what the plant had already."""

    added: dict[str, list[str]] = field(default_factory=dict)
    present: list[str] = field(default_factory=list)
    written: list[str] = field(default_factory=list)


#: file -> (its schema, its kind, its list key)
FILES = {
    MATERIALS_FILE: (SCHEMA, "materials", "components"),
    REACTIONS_FILE: (REACTIONS_SCHEMA, "reactions", "reactions"),
    CATALYSTS_FILE: (CATALYSTS_SCHEMA, "catalysts", "catalysts"),
}


def _same(kind: str, mine: dict[str, Any], theirs: Any) -> bool:
    """Whether the plant's item is the entry's: a component by its CAS number, a reaction by its
    stoichiometry (its catalyst and heat are the plant's to choose), a catalyst by its data."""
    if kind == "components":
        return bool(mine.get("cas")) and mine.get("cas") == theirs.cas
    if kind == "reactions":
        stoichiometry = {str(k): float(v) for k, v in (mine.get("stoichiometry") or {}).items()}
        return stoichiometry == {k: float(v) for k, v in theirs.stoichiometry.items()}
    return mine == theirs.model_dump(mode="json", exclude_defaults=True, by_alias=True)


def add_entry(root: Path, entry_id: str, write: bool = True) -> Added:
    """Add library entry *entry_id* to the plant repository at *root* (see the module
    docstring): every file is merged first, and only when all merge are they written. Raises
    KeyError for an unknown entry and :class:`Conflict` naming the ids the plant has with other
    data, a substance it has under another id, or a list it cannot append to."""
    entry = entries()[entry_id]
    result = Added()
    texts: dict[str, str] = {}
    problems = []
    for path, (_, _, key) in FILES.items():
        theirs = {
            "components": entry.components,
            "reactions": entry.reactions,
            "catalysts": entry.catalysts,
        }[key]
        if not theirs:
            continue
        file = root / path
        data = yaml.safe_load(file.read_text(encoding="utf-8")) if file.is_file() else None
        listed = [item for item in (data or {}).get(key) or [] if isinstance(item, dict)]
        mine = {item.get("id"): item for item in listed}
        by_cas = {item.get("cas"): item.get("id") for item in listed if item.get("cas")}
        new = []
        for item in theirs:
            if item.id in mine:
                if _same(key, mine[item.id], item):
                    result.present.append(item.id)
                else:
                    problems.append(f"{key[:-1]} {item.id} ({path})")
                continue
            other = by_cas.get(getattr(item, "cas", None)) if key == "components" else None
            if other is not None:
                problems.append(f"{item.name or item.id} (CAS {item.cas}) as {other} ({path})")
                continue
            new.append(item.model_dump(mode="json", exclude_defaults=True, by_alias=True))
        if new:
            texts[path] = _merged(file, path, new)  # a list it cannot append to raises here
            result.added[path] = [item["id"] for item in new]
    if problems:
        raise Conflict(
            "the plant has other data under the ids, or these substances under other ids: "
            + ", ".join(problems)
            + "; rename them or the entry's before adding"
        )
    if write:
        for path, text in texts.items():
            target = root / path
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_text(text, encoding="utf-8")
            result.written.append(path)
    return result


def _merged(file: Path, path: str, items: list[dict[str, Any]]) -> str:
    """The text of *file* with *items* appended to its list after its last item (a new file
    when missing), so the rest of the file and its comments stay as they are."""
    from chemeascode.domains.process.fill import _last_line

    schema, kind, key = FILES[path]
    text = yaml.safe_dump(items, sort_keys=False, width=100, allow_unicode=True)
    if not file.is_file():
        return f"schema: {schema}\nkind: {kind}\n{key}:\n" + _indent(text, "  ")
    source = file.read_text(encoding="utf-8")
    if not source.endswith("\n"):
        source += "\n"
    node = yaml.compose(source)
    target = key_node = None
    if isinstance(node, yaml.MappingNode):
        for k, v in node.value:
            if isinstance(k, yaml.ScalarNode) and k.value == key:
                key_node, target = k, v
    lines = source.splitlines(keepends=True)
    if target is None:
        return source + f"{key}:\n" + _indent(text, "  ")
    empty_flow = isinstance(target, yaml.SequenceNode) and target.flow_style and not target.value
    null = isinstance(target, yaml.ScalarNode) and target.tag.endswith(":null")
    if empty_flow or null:
        # "key: []" or "key:" with nothing: written as a block list
        line = key_node.start_mark.line  # type: ignore[union-attr]
        head = lines[line][: key_node.end_mark.column + 1]  # type: ignore[union-attr]
        lines[line] = head.rstrip() + "\n"
        lines.insert(line + 1, _indent(text, "  "))
        return "".join(lines)
    if not isinstance(target, yaml.SequenceNode) or target.flow_style:
        raise Conflict(f"{path}: {key} is not a block list; write it as one to add to it")
    indent = " " * target.value[0].start_mark.column
    at = _last_line(target.value[-1]) + 1
    # "- " sits two columns before the item's own keys
    lines[at:at] = [_indent(text, indent[:-2] if len(indent) >= 2 else "")]
    return "".join(lines)


def _indent(text: str, prefix: str) -> str:
    return "".join(
        prefix + line if line.strip() else line for line in text.splitlines(keepends=True)
    )


def library_view(chemistry: Any = None) -> dict[str, Any]:
    """``GET /api/library``: every entry (window, components, reactions, catalysts, model
    basis, sources),
    each item marked ``in_plant`` when the plant has it (*chemistry*: its components, reactions
    and catalysts; None: no plant)."""
    comps = chemistry.components() if chemistry is not None else {}
    reactions = chemistry.reactions.by_id() if chemistry is not None and chemistry.reactions else {}
    catalysts = (
        chemistry.catalysts.by_id()
        if chemistry is not None and getattr(chemistry, "catalysts", None)
        else {}
    )
    by_cas = {c.cas: c.id for c in comps.values() if getattr(c, "cas", "")}
    out = []
    for entry in entries().values():
        out.append(
            {
                "id": entry.id,
                "title": entry.title,
                "window": entry.window.model_dump(mode="json"),
                "components": [
                    {
                        "id": c.id,
                        "name": c.name,
                        "cas": c.cas,
                        "formula": c.formula,
                        "in_plant": by_cas.get(c.cas),
                    }
                    for c in entry.components
                ],
                "reactions": [
                    {
                        "id": r.id,
                        "equation": r.equation,
                        "reversible": r.reversible,
                        "phase": r.phase,
                        "catalyst": r.catalyst or None,
                        "heat_of_reaction": r.heat_of_reaction.model_dump(mode="json")
                        if r.heat_of_reaction
                        else None,
                        "in_plant": r.id in reactions
                        and _same("reactions", reactions[r.id].model_dump(mode="json"), r),
                    }
                    for r in entry.reactions
                ],
                "catalysts": [
                    {
                        "id": c.id,
                        "name": c.name,
                        "active_phase": c.active_phase,
                        "promoters": c.promoters,
                        "support": c.support,
                        "window": c.window.model_dump(mode="json") if c.window else None,
                        "poisons": c.poisons,
                        "in_plant": c.id in catalysts,
                        # the plant's catalyst of this id has other data: --add refuses it
                        "differs": c.id in catalysts
                        and not _same(
                            "catalysts",
                            catalysts[c.id].model_dump(
                                mode="json", exclude_defaults=True, by_alias=True
                            ),
                            c,
                        ),
                    }
                    for c in entry.catalysts
                ],
                "model_basis": entry.model_basis.model_dump(mode="json", exclude_none=True),
                "sources": entry.sources,
            }
        )
    return {"entries": out}
