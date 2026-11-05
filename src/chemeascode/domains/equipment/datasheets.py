"""Equipment datasheets, ``equipment/datasheets/<TAG>.yaml``, against the equipment list."""

from __future__ import annotations

import math
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import yaml
from pydantic import ValidationError

from chemeascode.domains.equipment.schemas.datasheet import Datasheet, Quantity
from chemeascode.foundation.findings import Finding
from chemeascode.foundation.workspace import LAYOUT_MODEL_FILE, Workspace, schema_hint
from chemeascode.foundation.yamlsource import _compose, _yaml_line

DATASHEET_DIR = "equipment/datasheets"


def datasheet_paths(workspace: Workspace) -> list[Path]:
    folder = workspace.root / DATASHEET_DIR
    if not folder.is_dir():
        return []
    return sorted(
        p
        for p in (*folder.glob("*.yaml"), *folder.glob("*.yml"))
        if p.is_file() and workspace.contains(p)
    )


@dataclass
class Loaded:
    name: str
    path: Path
    sheet: Datasheet | None
    findings: list[Finding]


def load(workspace: Workspace, path: Path) -> Loaded:
    name = workspace.relative(path)
    try:
        data = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    except yaml.YAMLError as failure:
        mark = getattr(failure, "problem_mark", None)
        finding = Finding(
            name,
            "error",
            "yaml.syntax",
            str(failure).splitlines()[0],
            line=mark.line + 1 if mark else None,
        )
        return Loaded(name, path, None, [finding])
    try:
        return Loaded(name, path, Datasheet.model_validate(data), [])
    except ValidationError as failure:
        document = _compose(path)
        return Loaded(
            name,
            path,
            None,
            [
                Finding(
                    name,
                    "error",
                    "yaml.schema",
                    f"{'.'.join(str(p) for p in error['loc'])}: {error['msg']}",
                    line=_yaml_line(document, error["loc"]),
                    hint=schema_hint("see `cheme schema datasheet`", error),
                )
                for error in failure.errors()
            ],
        )


def _number(value: Any) -> float | None:
    if isinstance(value, Quantity):
        value = value.value
    if isinstance(value, bool):
        return None
    if isinstance(value, int | float):
        return float(value)
    try:
        return float(str(value).split()[0])
    except (ValueError, IndexError):
        return None


# -- open fields and their markers ----------------------------------------------------------------

#: A field waiting for the supplier's data (``value: supplier``, with ``source`` or ``reason``
#: naming what is awaited, e.g. the enquiry).
SUPPLIER = "supplier"
#: A field that does not apply to this item (``value: not_applicable`` with a ``reason``).
NOT_APPLICABLE = "not_applicable"
MARKERS = (SUPPLIER, NOT_APPLICABLE)
#: The sections of a datasheet whose fields are values (with ``value``/``unit``/``source``).
VALUE_SECTIONS = ("operating", "design", "materials", "dimensions", "weights", "type_specific")


def field_state(entry: Any) -> str:
    """``tbd``, ``supplier``, ``not_applicable`` or ``value``: what a datasheet field holds."""
    if isinstance(entry, Quantity):
        value: Any = entry.value
    elif isinstance(entry, dict):
        value = entry.get("value")
    else:
        value = entry
    if isinstance(value, str):
        text = value.strip()
        if text.upper().startswith("TBD"):
            return "tbd"
        if text.lower() in MARKERS:
            return text.lower()
    return "value"


def _entry_text(entry: Any, key: str) -> str:
    if isinstance(entry, Quantity):
        return str(getattr(entry, key, "") or "")
    if isinstance(entry, dict):
        return str(entry.get(key) or "")
    return ""


#: Keys whose text explains a field (where it comes from, why): never an open field themselves.
_TEXT_KEYS = frozenset(
    ("source", "reason", "reference", "location_source", "note", "notes", "basis", "comment")
)
#: The list sections of a datasheet that hold values too (``nozzles[].dn``,
#: ``sizing_basis[].value``).
LIST_SECTIONS = ("nozzles", "sizing_basis")


def _walk(node: Any, where: list[str | int], found: list[tuple[list[str | int], str, Any]]) -> None:
    if isinstance(node, dict) and "value" in node:
        state = field_state(node)
        if state != "value":
            found.append((where, state, node))
        return
    if isinstance(node, dict):
        for key, entry in node.items():
            if str(key) not in _TEXT_KEYS:
                _walk(entry, [*where, str(key)], found)
    elif isinstance(node, list):
        for index, entry in enumerate(node):
            _walk(entry, [*where, index], found)
    else:
        state = field_state(node)
        if state != "value":
            found.append((where, state, node))


def open_fields(data: dict[str, Any]) -> list[tuple[list[str | int], str, Any]]:
    """The fields of a datasheet (its parsed YAML) that hold no value yet: ``(path, state,
    entry)`` with state ``tbd``, ``supplier`` or ``not_applicable``, in file order. Every value
    counts, at any depth: the fields of the value sections, a nested ``type_specific`` table,
    ``nozzles[].dn`` and ``sizing_basis[].value``; a path holds keys and list indices."""
    found: list[tuple[list[str | int], str, Any]] = []
    for section in (*VALUE_SECTIONS, *LIST_SECTIONS):
        fields = data.get(section)
        if section in LIST_SECTIONS and isinstance(fields, list):
            _walk(fields, [section], found)
        elif isinstance(fields, dict):
            for key, entry in fields.items():
                _walk(entry, [section, str(key)], found)
    order = {name: i for i, name in enumerate(data)}
    found.sort(key=lambda f: order.get(f[0][0], len(order)))
    return found


def field_path(where: list[str | int]) -> str:
    """A path of :func:`open_fields` as text: ``type_specific.npsh_required_m``,
    ``nozzles[0].dn``."""
    text = ""
    for step in where:
        text += f"[{step}]" if isinstance(step, int) else (f".{step}" if text else step)
    return text


def marker_problem(state: str, entry: Any) -> str | None:
    """Why a ``supplier`` or ``not_applicable`` field is not complete, or None."""
    reason = _entry_text(entry, "reason").strip()
    source = _entry_text(entry, "source").strip()
    if state == NOT_APPLICABLE and not reason:
        return "not_applicable needs a reason (why the field does not apply to this item)"
    if state == SUPPLIER and not (reason or source):
        return "supplier needs a source or reason (what is awaited, e.g. the enquiry)"
    return None


def open_tbd(workspace: Workspace) -> dict[str, list[str]]:
    """Per tag of a datasheet that is not a draft, its fields still ``TBD`` (``supplier`` and
    ``not_applicable`` fields with their source or reason are not open: such a sheet can be
    final)."""
    found: dict[str, list[str]] = {}
    for path in datasheet_paths(workspace):
        try:
            data = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
        except yaml.YAMLError:
            continue
        if not isinstance(data, dict) or data.get("draft"):
            continue
        keys = [field_path(p) for p, state, _ in open_fields(data) if state == "tbd"]
        if keys:
            found[str(data.get("tag") or path.stem).strip()] = keys
    return found


def check_datasheets(workspace: Workspace, equipment: Any | None) -> list[Finding]:
    """Schema findings for every datasheet, and (with the parsed *equipment* list)
    ``cheme.datasheet-not-listed`` and ``cheme.datasheet-mismatch``."""
    findings: list[Finding] = []
    listed = {item.tag.strip(): item for item in equipment.equipment} if equipment else None
    for path in datasheet_paths(workspace):
        loaded = load(workspace, path)
        findings += loaded.findings
        sheet = loaded.sheet
        if sheet is None:
            continue
        document = _compose(path)
        tag = sheet.tag.strip()
        raw = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
        tbd: list[list[str | int]] = []
        for where, state, entry in open_fields(raw):
            problem = marker_problem(state, entry)
            if problem:
                findings.append(
                    Finding(
                        loaded.name,
                        "error",
                        "cheme.datasheet-marker",
                        f"{tag} {field_path(where)}: {problem}",
                        line=_yaml_line(document, where),
                        ids=[tag],
                        hint="value: supplier with source: <the enquiry or data awaited>, or "
                        "value: not_applicable with reason: <why>",
                    )
                )
            if state == "tbd":
                tbd.append(where)
        if tbd and not sheet.draft:
            findings.append(
                Finding(
                    loaded.name,
                    "warning",
                    "cheme.datasheet-open",
                    f"{tag} is final (no draft: true) with fields still TBD: "
                    + ", ".join(field_path(w) for w in tbd[:6])
                    + (f" and {len(tbd) - 6} more" if len(tbd) > 6 else ""),
                    line=_yaml_line(document, tbd[0]),
                    ids=[tag],
                    hint="give each a value with its source, or mark it value: supplier (with "
                    "the source awaited) or value: not_applicable (with a reason); else keep "
                    "draft: true",
                )
            )
        findings += _sheet_findings(loaded.name, document, sheet)
        if path.stem != tag:
            findings.append(
                Finding(
                    loaded.name,
                    "warning",
                    "cheme.datasheet-name",
                    f"datasheet of {tag} is named {path.name}",
                    line=_yaml_line(document, ["tag"]),
                    ids=[tag],
                    hint=f"name it {DATASHEET_DIR}/{tag}.yaml",
                )
            )
        if listed is None:
            continue
        item = listed.get(tag)
        if item is None:
            findings.append(
                Finding(
                    loaded.name,
                    "warning",
                    "cheme.datasheet-not-listed",
                    f"datasheet of {tag}, which is not in the equipment list",
                    line=_yaml_line(document, ["tag"]),
                    ids=[tag],
                    hint="fix the tag, or add the item to equipment/equipment-list.yaml",
                )
            )
            continue
        for key, field, unit in (
            ("pressure_barg", "design_pressure_barg", "barg"),
            ("temperature_degc", "design_temperature_degc", "degC"),
        ):
            listed_value = getattr(item, field)
            sheet_value = _number(sheet.design.get(key)) if key in sheet.design else None
            if listed_value is None or sheet_value is None:
                continue
            if abs(listed_value - sheet_value) > 1e-9:
                findings.append(
                    Finding(
                        loaded.name,
                        "warning",
                        "cheme.datasheet-mismatch",
                        f"{tag}: design {key} {sheet_value:g} {unit} here, "
                        f"{listed_value:g} {unit} in the equipment list",
                        line=_yaml_line(document, ["design", key]),
                        ids=[tag],
                        hint="change both in the same commit",
                    )
                )
        if sheet.type and item.type and sheet.type != item.type:
            findings.append(
                Finding(
                    loaded.name,
                    "warning",
                    "cheme.datasheet-mismatch",
                    f"{tag}: type {sheet.type} here, {item.type} in the equipment list",
                    line=_yaml_line(document, ["type"]),
                    ids=[tag],
                    hint="use the equipment list's DEXPI class",
                )
            )
    return findings


#: How far a datasheet nozzle location may differ from the layout model's: deg, m.
NOZZLE_ANGLE_TOLERANCE_DEG = 1.0
NOZZLE_ELEVATION_TOLERANCE_M = 0.05


def declares_nozzle_locations(workspace: Workspace) -> bool:
    """Whether any datasheet gives a nozzle's orientation, face or elevation."""
    for path in datasheet_paths(workspace):
        sheet = load(workspace, path).sheet
        if sheet is not None and any(
            n.orientation_deg is not None
            or n.elevation_m is not None
            or n.offset_m is not None
            or n.face
            for n in sheet.nozzles
        ):
            return True
    return False


def nozzle_location_findings(workspace: Workspace, model: dict[str, Any]) -> list[Finding]:
    """``cheme.datasheet-nozzle-layout``: a datasheet nozzle whose declared orientation,
    face or elevation differs from the nozzle of the generated layout model *model* (the parsed
    ``layout/plant-model.yaml``), so the document that goes to the supplier and the layout
    say the same. Orientation is the plan angle (deg from site east, counter-clockwise) of the
    nozzle axis for a side nozzle, of its offset from the item's centre for a top or bottom
    one; offset that plan distance; elevation the nozzle centre (where it leaves the shell)
    above the item's placement elevation. A nozzle the placement overrides (``basis:
    override`` in the model) without a location on its item's datasheet is reported too."""
    items = {
        str(item.get("tag") or item.get("id")): item
        for item in model.get("equipment") or ()
        if isinstance(item, dict)
    }
    findings: list[Finding] = []
    for path in datasheet_paths(workspace):
        loaded = load(workspace, path)
        sheet = loaded.sheet
        if sheet is None:
            continue
        tag = sheet.tag.strip()
        item = items.get(tag)
        nozzles = {
            str(n.get("name")): n for n in (item or {}).get("nozzles") or () if isinstance(n, dict)
        }
        document = None
        for index, nozzle in enumerate(sheet.nozzles):
            if (
                nozzle.orientation_deg is None
                and nozzle.elevation_m is None
                and nozzle.offset_m is None
                and not nozzle.face
            ):
                continue
            placed = nozzles.get(nozzle.name)
            problems: list[str] = []
            if placed is None:
                problems.append("the layout model has no such nozzle")
            else:
                dx, dy, dz = (float(v) for v in placed.get("direction") or (0, 0, 0))
                face = "top" if dz > 0.5 else "bottom" if dz < -0.5 else "side"
                if nozzle.face and nozzle.face != face:
                    problems.append(f"face {nozzle.face} here, {face} in the layout")
                base = placed.get("base") or placed.get("point")
                centre = (item or {}).get("position") or (0, 0, 0)
                ex, ey = float(base[0]) - float(centre[0]), float(base[1]) - float(centre[1])
                offset = math.hypot(ex, ey)
                if nozzle.orientation_deg is not None:
                    if face == "side":
                        angle = math.degrees(math.atan2(dy, dx)) % 360
                    else:  # the bearing of a top or bottom nozzle off the centre
                        angle = math.degrees(math.atan2(ey, ex)) % 360 if offset > 1e-3 else None
                    if angle is None:
                        problems.append("an orientation for a nozzle on the item's centre")
                    else:
                        off = abs((nozzle.orientation_deg - angle + 180) % 360 - 180)
                        if off > NOZZLE_ANGLE_TOLERANCE_DEG:
                            problems.append(
                                f"orientation {nozzle.orientation_deg:g} deg here, "
                                f"{angle:.1f} deg in the layout"
                            )
                if (
                    nozzle.offset_m is not None
                    and face != "side"
                    and abs(offset - nozzle.offset_m) > NOZZLE_ELEVATION_TOLERANCE_M
                ):
                    problems.append(
                        f"offset {nozzle.offset_m:g} m here, {offset:.3f} m in the layout"
                    )
                if nozzle.elevation_m is not None:
                    z0 = float(centre[2])
                    height = float(base[2]) - z0
                    if abs(height - nozzle.elevation_m) > NOZZLE_ELEVATION_TOLERANCE_M:
                        problems.append(
                            f"elevation {nozzle.elevation_m:g} m here, {height:.3f} m in the layout"
                        )
            if not problems:
                continue
            if document is None:
                document = _compose(path)
            findings.append(
                Finding(
                    loaded.name,
                    "warning",
                    "cheme.datasheet-nozzle-layout",
                    f"{tag} nozzle {nozzle.name}: " + "; ".join(problems),
                    line=_yaml_line(document, ["nozzles", index]),
                    ids=[tag],
                    hint="change the datasheet and layout/equipment-placement.yaml together, "
                    "then cheme layout build",
                    key=f"{tag}/{nozzle.name}",
                )
            )
        # a nozzle the placement overrides (the layout decided where it goes) must say so on
        # the datasheet too, or a supplier puts it where the P&ID draws it
        located = {
            n.name
            for n in sheet.nozzles
            if n.orientation_deg is not None
            or n.elevation_m is not None
            or n.offset_m is not None
            or n.face
        }
        listed = [n.name for n in sheet.nozzles]
        for name, placed in nozzles.items():
            if placed.get("basis") != "override" or name in located:
                continue
            if document is None:
                document = _compose(path)
            line = (
                _yaml_line(document, ["nozzles", listed.index(name)])
                if name in listed
                else _yaml_line(document, ["nozzles"])
            )
            findings.append(
                Finding(
                    loaded.name,
                    "warning",
                    "cheme.datasheet-nozzle-layout",
                    f"{tag} nozzle {name}: layout/equipment-placement.yaml places it, but the "
                    "datasheet gives no location",
                    line=line,
                    ids=[tag],
                    hint="give its face, orientation_deg, offset_m (top or bottom), elevation_m "
                    "and location_source from the layout",
                    key=f"{tag}/{name}/missing",
                )
            )
    return findings


def missing_datasheets(workspace: Workspace, equipment: Any) -> tuple[list[str], list[str]]:
    """Listed tags without a valid datasheet: ``(missing, invalid)``."""
    have: dict[str, bool] = {}
    for path in datasheet_paths(workspace):
        loaded = load(workspace, path)
        tag = loaded.sheet.tag.strip() if loaded.sheet else path.stem
        have[tag] = have.get(tag, False) or loaded.sheet is not None
    tags = [item.tag.strip() for item in equipment.equipment]
    missing = [t for t in tags if t not in have]
    invalid = [t for t in tags if t in have and not have[t]]
    return missing, invalid


def draft_datasheets(workspace: Workspace) -> list[str]:
    """Tags whose datasheet is still a generated draft (``draft: true``)."""
    found = []
    for path in datasheet_paths(workspace):
        loaded = load(workspace, path)
        if loaded.sheet is not None and loaded.sheet.draft:
            found.append(loaded.sheet.tag.strip())
    return found


# -- drafts ---------------------------------------------------------------------------------------

#: Fields a datasheet of a kind of item needs that the lists cannot give: by a word of the DEXPI
#: class, the keys (with their unit) left TBD. The size keys are those the equipment estimate
#: reads (``cheme assess equipment``).
TYPE_FIELDS: tuple[tuple[tuple[str, ...], tuple[tuple[str, str], ...]], ...] = (
    (
        ("pump",),
        (
            ("flow_m3_h", "m3/h"),
            ("differential_head_m", "m"),
            ("npsh_available_m", "m"),
            ("shaft_power_kw", "kW"),
        ),
    ),
    (("compressor", "blower"), (("fluid_power_kw", "kW"), ("shaft_power_kw", "kW"))),
    (("turbine", "expander"), (("fluid_power_kw", "kW"), ("shaft_power_kw", "kW"))),
    (("fan",), (("gas_flow_m3_s", "m3/s"), ("shaft_power_kw", "kW"))),
    (
        ("exchanger", "cooler", "condenser", "reboiler", "vaporizer", "vaporiser"),
        (("duty_kw", "kW"), ("area_m2", "m2")),
    ),
    (("heater", "furnace"), (("duty_kw", "kW"),)),
    (("column", "tower"), (("volume_m3", "m3"), ("number_of_stages", ""))),
    (
        ("reactor", "converter"),
        (
            ("catalyst_mass_kg", "kg"),
            ("catalyst_volume_m3", "m3"),
            ("volume_m3", "m3"),
            ("duty_kw", "kW"),
            ("pressure_drop_kpa", "kPa"),
        ),
    ),
    (("vessel", "drum", "tank", "separator"), (("volume_m3", "m3"),)),
)
#: Parts of DEXPI class names that hold a word of :data:`TYPE_FIELDS` but are no item of that
#: row: direct-contact coolers and cooling towers (no column stages, no exchanger area), a
#: frequency converter (no reactor), a turbine flow meter (no machine). They have no size row.
UNSIZED_CLASSES = ("coolingtower", "spraycooler", "frequencyconverter", "flowmeter")
DRAFT_HEADER = """\
# DRAFT datasheet generated by `cheme datasheets draft` from {sources}.
# Every value says where it comes from (source). TBD: not known yet, to be filled from the design
# (sizing, a supplier). assumed: true marks a value derived on an assumption: confirm it.
# Complete it, record the sizing basis, then remove `draft: true` (the datasheets gate does not
# count a draft). Schema: `cheme schema datasheet`.
"""


def _q(
    value: Any, unit: str, source: str, assumed: bool = False, origin: str | None = None
) -> dict[str, Any]:
    entry: dict[str, Any] = {"value": value, "unit": unit, "source": source}
    if assumed:
        entry["assumed"] = True
    if origin:
        entry["origin"] = origin
    return entry


#: The reason a draft gives its size fields (a fill replaces it with its own).
DRAFT_SIZING_TBD = "sizing (DESIGN.md, a supplier)"
#: How a draft's vessel volume from the list's dimensions is marked (a fill recalculates it
#: from the sheet's dimensions).
DRAFT_VOLUME = "dimensions: pi/4 D^2 x"


def _tbd(unit: str, why: str) -> dict[str, Any]:
    return {"value": "TBD", "unit": unit, "source": f"TBD: {why}"}


def type_row(
    type_: str | None,
) -> tuple[tuple[str, ...], tuple[tuple[str, str], ...]] | None:
    """The row of :data:`TYPE_FIELDS` of DEXPI class *type_*: the first whose words its name
    holds; None for no row or an :data:`UNSIZED_CLASSES` class."""
    cls = (type_ or "").lower()
    if any(word in cls for word in UNSIZED_CLASSES):
        return None
    return next((row for row in TYPE_FIELDS if any(w in cls for w in row[0])), None)


def type_fields(type_: str | None) -> tuple[tuple[str, str], ...]:
    """The size fields (key, unit) a datasheet of DEXPI class *type_* needs
    (:func:`type_row`)."""
    row = type_row(type_)
    return row[1] if row else ()


def draft_datasheet(
    item: Any,
    nozzles: list[dict[str, Any]],
    streams: list[dict[str, Any]],
    units: dict[str, Any] | None = None,
    case: str | None = None,
    list_file: str = "equipment/equipment-list.yaml",
    model: dict[str, Any] | None = None,
) -> str:
    """The text of a draft datasheet of equipment-list *item* (see :data:`DRAFT_HEADER`):
    *nozzles* ``[{name, dn, lines, sheet}]`` from the P&IDs, *streams* ``[{id, title,
    direction: in|out, state}]`` of the flowsheet case *case* (the stream report's states,
    *units* its units), the main dimensions from the item's dimensions and the parsed layout
    *model* (:func:`~chemeascode.domains.equipment.outline.derived_dimensions`) and the empty
    weight the list gives."""
    from chemeascode.domains.equipment.outline import derived_dimensions

    units = units or {}
    tag = item.tag.strip()
    doc: dict[str, Any] = {"tag": tag, "type": item.type, "service": item.service or "TBD"}
    doc["draft"] = True
    operating: dict[str, Any] = {}
    unit_names = {"pressure": "pressure", "temperature": "temperature", "flow": "flow"}
    for direction in ("in", "out"):
        mine = [s for s in streams if s["direction"] == direction]
        if len(mine) != 1:
            continue
        stream = mine[0]
        for prop, kind in unit_names.items():
            entry = (stream.get("state") or {}).get(prop)
            if not entry or entry.get("value") is None:
                continue
            source = f"process/flowsheet.yaml stream {stream['id']}" + (
                f" (case {case})" if case else ""
            )
            given = entry.get("source")
            provenance = entry.get("provenance")
            if provenance or given:
                source += f", {provenance or ''}{': ' + given if given else ''}"
            operating[f"{'inlet' if direction == 'in' else 'outlet'}_{prop}"] = _q(
                entry["value"],
                str(units.get(kind) or ""),
                source,
                assumed=provenance == "assumed",
                origin=entry.get("origin"),
            )
    if not streams:
        operating["conditions"] = _tbd(
            "", "no flowsheet stream links this item (links: in process/flowsheet.yaml)"
        )
    doc["operating"] = operating
    design: dict[str, Any] = {}
    for key, field_name, unit in (
        ("pressure_barg", "design_pressure_barg", "barg"),
        ("temperature_degc", "design_temperature_degc", "degC"),
    ):
        value = getattr(item, field_name)
        design[key] = (
            _q(value, unit, list_file)
            if value is not None
            else _tbd(unit, f"no {field_name} in the equipment list")
        )
    doc["design"] = design
    doc["materials"] = {
        "main": {"value": item.material, "source": list_file}
        if item.material
        else _tbd("", "no material in the equipment list")
    }
    dimensions, weights = derived_dimensions(item, model, list_file)
    if dimensions:
        doc["dimensions"] = dimensions
    if weights:  # only what the list states: the gate's require: [weights] asks for the rest
        doc["weights"] = weights
    doc["nozzles"] = [
        {
            "name": n["name"],
            **({"dn": n["dn"]} if n.get("dn") is not None else {}),
            "lines": list(n.get("lines") or []),
            "source": n.get("sheet") or "P&ID",
        }
        for n in nozzles
    ]
    specific: dict[str, Any] = {}
    d = item.dimensions
    if d is not None:
        for name, unit in (
            ("diameter", "m"),
            ("height", "m"),
            ("length", "m"),
            ("width", "m"),
            ("depth", "m"),
            ("weight", "t"),
        ):
            value = getattr(d, name)
            if value is not None:
                key = f"{name}_{'t' if unit == 't' else 'm'}"
                told = d.source if unit == "m" else ""  # a tool's sizes, not the weight
                specific[key] = _q(
                    value,
                    unit,
                    f"{list_file} dimensions" + (f": {told}" if told else ""),
                    assumed=d.assumed and unit == "m",
                )
    for key, unit in type_fields(item.type):
        if key == "volume_m3" and d is not None and d.diameter and (d.height or d.length):
            # a diameter with a length is a horizontal shell (as the 3D model reads it):
            # its volume runs along the length, not the height over the saddles
            along = "length" if d.length else "height"
            length = d.length or d.height
            specific[key] = _q(
                round(math.pi / 4 * d.diameter**2 * length, 3),
                unit,
                f"{list_file} {DRAFT_VOLUME} {along} "
                "(overall, including heads and skirt: an upper bound)",
                assumed=True,
            )
        else:
            specific[key] = _tbd(unit, DRAFT_SIZING_TBD)
    if streams:
        specific["process_streams"] = [
            {
                "stream": s["id"],
                "direction": s["direction"],
                **({"title": s["title"]} if s.get("title") else {}),
                "source": "process/flowsheet.yaml" + (f" (case {case})" if case else ""),
            }
            for s in streams
        ]
    doc["type_specific"] = specific
    doc["sizing_basis"] = []
    doc["notes"] = item.notes or ""
    sources = [list_file]
    if nozzles:
        sources.append(", ".join(sorted({n.get("sheet") or "P&ID" for n in nozzles})))
    if streams:
        sources.append("process/flowsheet.yaml")
    header = DRAFT_HEADER.format(sources=", ".join(sources))
    return header + yaml.safe_dump(doc, sort_keys=False, allow_unicode=True, width=100)


# -- main dimensions, nozzle schedule, drawing -----------------------------------------------------


def _sheet_findings(name: str, document: Any, sheet: Datasheet) -> list[Finding]:
    """A datasheet on its own: a nozzle listed twice (``cheme.datasheet-nozzle-duplicate``),
    a dimension or weight in a unit that is not read (``cheme.datasheet-unit``)."""
    from chemeascode.domains.equipment.outline import LENGTH_UNITS, WEIGHT_UNITS, unit_known

    tag = sheet.tag.strip()
    findings: list[Finding] = []
    seen: set[str] = set()
    for index, nozzle in enumerate(sheet.nozzles):
        mark = nozzle.mark or nozzle.name
        if mark in seen:
            findings.append(
                Finding(
                    name,
                    "warning",
                    "cheme.datasheet-nozzle-duplicate",
                    f"{tag}: nozzle {mark} is listed twice",
                    line=_yaml_line(document, ["nozzles", index]),
                    ids=[tag],
                    hint="one entry per nozzle; give a different mark to a second one",
                    key=f"{tag}/{mark}",
                )
            )
        seen.add(mark)
    checks: list[tuple[list[str | int], Any, dict[str, float]]] = []
    d = sheet.dimensions
    if d is not None:
        for key in (
            "inside_diameter",
            "outside_diameter",
            "tangent_length",
            "shaft_height",
            "overall_height",
            "overall_length",
            "overall_width",
        ):
            checks.append((["dimensions", key], getattr(d, key), LENGTH_UNITS))
        for part, keys in (
            ("support", ("height",)),
            ("tubes", ("outside_diameter", "length", "pitch")),
            ("plates", ("height", "width")),
            ("baseplate", ("length", "width")),
        ):
            group = getattr(d, part)
            for key in keys if group is not None else ():
                checks.append((["dimensions", part, key], getattr(group, key), LENGTH_UNITS))
    if sheet.weights is not None:
        for key in ("empty", "operating", "test"):
            checks.append((["weights", key], getattr(sheet.weights, key), WEIGHT_UNITS))
    for where, entry, units in checks:
        if entry is None or unit_known(entry, units):
            continue
        findings.append(
            Finding(
                name,
                "warning",
                "cheme.datasheet-unit",
                f"{tag} {field_path(where)}: unit {getattr(entry, 'unit', '')!r} is not read "
                "(the checks and the outline drawing leave it out)",
                line=_yaml_line(document, where),
                ids=[tag],
                hint=f"give it in {', '.join(u for u in units if u)}",
                key=f"{tag}/{field_path(where)}",
            )
        )
    return findings


def _sheets(workspace: Workspace) -> list[Loaded]:
    return [
        loaded for path in datasheet_paths(workspace) if (loaded := load(workspace, path)).sheet
    ]


class _Reporter:
    """Findings on one datasheet, its YAML composed once, when the first is reported."""

    def __init__(self, loaded: Loaded, tag: str, findings: list[Finding]) -> None:
        self.loaded = loaded
        self.tag = tag
        self.findings = findings
        self.document: Any = None

    def add(self, rule: str, message: str, where: list[str | int], hint: str, key: str) -> None:
        if self.document is None:
            self.document = _compose(self.loaded.path)
        self.findings.append(
            Finding(
                self.loaded.name,
                "warning",
                rule,
                f"{self.tag}{message}",
                line=_yaml_line(self.document, where),
                ids=[self.tag],
                hint=hint,
                key=f"{self.tag}/{key}",
            )
        )

    def dimension(self, rule: str, problem: str, where: list[str | int], hint: str) -> None:
        self.add(rule, f": {problem}", where, hint, f"{rule.rsplit('-', 1)[-1]}/{problem[:60]}")

    def nozzle(self, rule: str, message: str, where: list[str | int], hint: str, key: str) -> None:
        self.add(rule, f" {message}", where, hint, key)


def dimension_findings(
    workspace: Workspace, equipment: Any | None, model: dict[str, Any] | None
) -> list[Finding]:
    """The main dimensions and the empty weight of every datasheet against the item's overall
    ``dimensions`` in the parsed *equipment* list (``cheme.datasheet-dimension-mismatch``) and
    against the generated layout *model* (``cheme.datasheet-dimension-layout``), by the
    tolerances of :mod:`chemeascode.domains.equipment.dimensions`: the same size stated twice
    (an overall size, the outside diameter, the empty weight) within :data:`~chemeascode.
    domains.equipment.dimensions.SAME`; an inside diameter within ``DIAMETER``; a tangent or
    tube length between ``SHORT`` and ``FIT`` of the overall size; plates, a baseplate and the
    shaft height not beyond it (``FIT``); head and support types the same."""
    from chemeascode.domains.equipment import dimensions as tolerance
    from chemeascode.domains.equipment.outline import (
        WEIGHT_UNITS,
        kind_of,
        model_item,
        number,
        text,
    )
    from chemeascode.domains.equipment.schemas.equipment import Dimensions

    listed = {item.tag.strip(): item for item in equipment.equipment} if equipment else {}
    findings: list[Finding] = []
    for loaded in _sheets(workspace):
        sheet = loaded.sheet
        assert sheet is not None
        d = sheet.dimensions
        tag = sheet.tag.strip()
        weight = number(sheet.weights.empty, WEIGHT_UNITS) if sheet.weights else None
        if d is None and weight is None:
            continue
        report = _Reporter(loaded, tag, findings).dimension

        od = number(d.outside_diameter) if d else None
        inner = number(d.inside_diameter) if d else None
        tangent = number(d.tangent_length) if d else None
        tubes = number(d.tubes.length) if d and d.tubes else None
        overall = {
            key: number(getattr(d, f"overall_{key}")) if d else None
            for key in ("height", "length", "width")
        }
        item = listed.get(tag)
        given = item.dimensions if item is not None else None
        hint = "change the datasheet and equipment/equipment-list.yaml together"
        rule = "cheme.datasheet-dimension-mismatch"
        if given is not None:
            pairs = [
                ("outside_diameter", od, given.diameter, "diameter"),
                ("overall_height", overall["height"], given.height, "height"),
                ("overall_length", overall["length"], given.length, "length"),
                ("overall_width", overall["width"], given.across, "width"),
            ]
            for key, mine, theirs, name in pairs:
                if (
                    mine is not None
                    and theirs is not None
                    and abs(mine - theirs) > tolerance.SAME * theirs
                ):
                    report(
                        rule,
                        f"{key} {mine:g} m here, {name} {theirs:g} m in the equipment list",
                        ["dimensions", key],
                        hint,
                    )
            # a round item with a length lies along it: its height is over the saddles
            along = given
            lying = given.diameter is not None and given.length is not None
            if lying and kind_of(sheet.type) not in ("column", "tank"):
                along = given.model_copy(update={"height": None})
            problems = tolerance.size_problems(
                along,
                lengths=[("tangent_length", tangent), ("tubes.length", tubes)],
                diameters=[(inner, "inside_diameter")] if inner else [],
                plates=[
                    ("PlateHeight", number(d.plates.height) if d and d.plates else None),
                    ("PlateWidth", number(d.plates.width) if d and d.plates else None),
                ],
            )
            if inner is not None and given.diameter is not None and inner > given.diameter:
                problems.append(
                    f"inside_diameter {inner:g} m is larger than the outside diameter "
                    f"{given.diameter:g} m"
                )
            for problem in problems:
                report(rule, problem + " (equipment list)", ["dimensions"], hint)
            for key, theirs in (("head", given.head), ("support", given.support)):
                entry = getattr(d, key, None) if d else None
                if key == "support" and entry is not None:
                    entry = entry.type
                mine_text = text(entry)
                if mine_text and theirs and mine_text != theirs and mine_text.upper() != "TBD":
                    report(
                        rule,
                        f"{key} {mine_text} here, {theirs} in the equipment list",
                        ["dimensions", key],
                        hint,
                    )
            if (
                weight is not None
                and given.weight is not None
                and abs(weight - given.weight) > tolerance.SAME * given.weight
            ):
                report(
                    rule,
                    f"empty weight {weight:g} t here, {given.weight:g} t in the equipment list",
                    ["weights", "empty"],
                    hint,
                )
        placed = model_item(model, tag)
        if placed is None or d is None:
            continue
        box = placed.get("bbox")
        if not (isinstance(box, list) and len(box) == 6):
            continue
        dx, dy, dz = (
            float(box[3]) - float(box[0]),
            float(box[4]) - float(box[1]),
            float(box[5]) - float(box[2]),
        )
        shape = placed.get("shape")
        horizontal = shape == "horizontal_cylinder"
        modelled = Dimensions.model_construct(
            diameter=None,
            height=None if horizontal else dz,
            length=max(dx, dy) if horizontal else None,
            width=None,
            depth=None,
        )
        rule = "cheme.datasheet-dimension-layout"
        hint = "rebuild the layout model (cheme layout build) after the equipment list follows"
        lengths = [("tangent_length", tangent), ("tubes.length", tubes)]
        problems = tolerance.size_problems(modelled, lengths=lengths)
        shell = next(
            (
                p
                for p in placed.get("parts") or ()
                if isinstance(p, dict) and p.get("id") == f"{tag}/shell" and p.get("radius")
            ),
            None,
        )
        if shell is not None and od is not None:
            shell_d = 2 * float(shell["radius"])
            if abs(od - shell_d) > tolerance.DIAMETER * shell_d:
                problems.append(f"outside_diameter {od:g} m, the model's shell {shell_d:g} m")
        extent = {"height": dz}
        if shape == "horizontal_cylinder":
            extent["length"] = max(dx, dy)
        elif shape == "box":
            extent.update(length=max(dx, dy), width=min(dx, dy))
        for key, size in extent.items():
            mine = overall.get(key)
            if mine is not None and abs(mine - size) > tolerance.SAME * size:
                problems.append(f"overall_{key} {mine:g} m, the model's {size:.3g} m")
        for problem in problems:
            report(rule, problem + f" ({LAYOUT_MODEL_FILE})", ["dimensions"], hint)
    return findings


def nozzle_findings(
    workspace: Workspace,
    pid: dict[str, list[dict[str, Any]]] | None,
    lines: Any | None,
    drawn: set[str] | None = None,
) -> list[Finding]:
    """The nozzle schedule of every datasheet against the nozzles the P&IDs draw for its item
    (*pid*: ``{tag: [{name, dn, lines, sheet}]}``; *drawn*: the tags drawn on a loaded sheet,
    default those of *pid*) and the parsed line list *lines*: ``cheme.datasheet-nozzle-pid``
    (a nozzle missing on either side, a different DN or different lines),
    ``cheme.datasheet-nozzle-line`` (a line the line list does not have and the P&ID does
    not draw at that nozzle: one it draws is the lines cross-check's)."""
    from chemeascode.domains.equipment.outline import number

    numbers = {line.number.strip() for line in lines.lines} if lines is not None else None
    drawn = set(pid or {}) if drawn is None else drawn
    findings: list[Finding] = []
    for loaded in _sheets(workspace):
        sheet = loaded.sheet
        assert sheet is not None
        tag = sheet.tag.strip()
        report = _Reporter(loaded, tag, findings).nozzle

        mine = {n.name: (i, n) for i, n in enumerate(sheet.nozzles)}
        if pid is not None and tag in drawn:
            theirs = {str(n["name"]): n for n in pid.get(tag, [])}
            hint = "the datasheet lists the nozzles the P&ID draws (cheme datasheets draft "
            hint += "--dry-run shows them)"
            for name, (index, nozzle) in mine.items():
                drawn_nozzle = theirs.get(name)
                if drawn_nozzle is None:
                    report(
                        "cheme.datasheet-nozzle-pid",
                        f"nozzle {name}: the P&ID draws no such nozzle on {tag}",
                        ["nozzles", index],
                        hint,
                        f"{name}/missing-on-pid",
                    )
                    continue
                dn = number(nozzle.dn, {"": 1.0}) if nozzle.dn is not None else None
                pid_dn = drawn_nozzle.get("dn")
                if dn is not None and pid_dn is not None and abs(dn - float(pid_dn)) > 1e-9:
                    report(
                        "cheme.datasheet-nozzle-pid",
                        f"nozzle {name}: DN {dn:g} here, DN {float(pid_dn):g} on "
                        f"{drawn_nozzle.get('sheet') or 'the P&ID'}",
                        ["nozzles", index, "dn"],
                        "change the datasheet and the P&ID together",
                        f"{name}/dn",
                    )
                pid_lines = set(drawn_nozzle.get("lines") or ())
                if nozzle.lines and pid_lines and set(nozzle.lines) != pid_lines:
                    report(
                        "cheme.datasheet-nozzle-pid",
                        f"nozzle {name}: lines {', '.join(sorted(nozzle.lines))} here, "
                        f"{', '.join(sorted(pid_lines))} on the P&ID",
                        ["nozzles", index, "lines"],
                        "list the line numbers the P&ID connects to it",
                        f"{name}/lines",
                    )
            # a datasheet without a schedule yet is not reported (the gate can require one)
            missing = sorted(set(theirs) - set(mine))
            if missing and mine:
                report(
                    "cheme.datasheet-nozzle-pid",
                    f"lists {len(mine)} of the {len(theirs)} nozzles the P&ID draws: "
                    f"{', '.join(missing)} missing",
                    ["nozzles"],
                    hint,
                    "missing",
                )
        if numbers is None:
            continue
        # a line the P&ID draws at the nozzle: the lines cross-check reports it if unlisted
        on_pid = {str(n["name"]): set(n.get("lines") or ()) for n in (pid or {}).get(tag, [])}
        for name, (index, nozzle) in mine.items():
            for line in nozzle.lines:
                if line.strip() not in numbers and line not in on_pid.get(name, set()):
                    report(
                        "cheme.datasheet-nozzle-line",
                        f"nozzle {name}: line {line} is not in the line list",
                        ["nozzles", index, "lines"],
                        "fix the line number, or add the line to piping/line-list.yaml",
                        f"{name}/{line}",
                    )
    return findings


def reference_findings(workspace: Workspace) -> list[Finding]:
    """``cheme.contract-ref`` (warning): a datasheet's ``operating.case`` that is no case of
    ``process/flowsheet.yaml``, or an ``operating.streams`` id that is no stream of it. The
    flowsheet is read only when a datasheet names a case or a stream; without one that loads,
    nothing is checked (validate reports the flowsheet)."""
    from chemeascode.domains.process.model import has_process
    from chemeascode.domains.process.model import load as load_process

    sheets = [
        loaded
        for loaded in _sheets(workspace)
        if loaded.sheet is not None
        and (loaded.sheet.operating.case is not None or loaded.sheet.operating.streams)
    ]
    if not sheets or not has_process(workspace.root):
        return []
    process, problems = load_process(workspace.root)
    if process is None or any(f.level == "error" for f in problems):
        return []
    cases = [c.id for c in process.flowsheet.cases]
    streams = {s.id for s in process.flowsheet.streams}
    findings: list[Finding] = []
    for loaded in sheets:
        assert loaded.sheet is not None
        operating = loaded.sheet.operating
        report = _Reporter(loaded, loaded.sheet.tag.strip(), findings)
        if operating.case is not None and operating.case not in cases:
            report.add(
                "cheme.contract-ref",
                f" operating.case: {operating.case!r} is no case of process/flowsheet.yaml",
                ["operating", "case"],
                f"declared cases: {', '.join(cases)}",
                f"case/{operating.case}",
            )
        for index, stream in enumerate(operating.streams):
            if stream not in streams:
                report.add(
                    "cheme.contract-ref",
                    f" operating.streams: {stream!r} is no stream of process/flowsheet.yaml",
                    ["operating", "streams", index],
                    "name a stream id of process/flowsheet.yaml, or cheme datasheets fill "
                    "rewrites the streams of a draft",
                    f"stream/{stream}",
                )
    return findings


def field_counts(data: dict[str, Any]) -> dict[str, int]:
    """How many fields of a datasheet (its parsed YAML) are ``assumed``, ``tbd``,
    ``supplier`` or ``not_applicable``."""
    counts = {"assumed": 0, "tbd": 0, "supplier": 0, "not_applicable": 0}
    for _, state, _ in open_fields(data):
        counts[state] += 1

    def walk(node: Any) -> None:
        if isinstance(node, dict):
            if node.get("assumed") is True:
                counts["assumed"] += 1
            for key, value in node.items():
                if str(key) not in _TEXT_KEYS:
                    walk(value)
        elif isinstance(node, list):
            for value in node:
                walk(value)

    for section in (*VALUE_SECTIONS, *LIST_SECTIONS):
        walk(data.get(section))
    return counts


# -- the outline drawing --------------------------------------------------------------------------


def drawing_path(workspace: Workspace, tag: str) -> Path:
    """``equipment/datasheets/<TAG>.svg``."""
    return workspace.root / DATASHEET_DIR / f"{tag}.svg"


def drawing_text(sheet: Datasheet, content: bytes, meta: dict[str, str]) -> str:
    """The outline drawing of *sheet* (whose file holds *content*), with the title block
    fields *meta*."""
    from chemeascode.domains.equipment.drawing import render_outline
    from chemeascode.foundation.provenance import content_fingerprint

    return render_outline(sheet, meta, content_fingerprint(content))


@dataclass
class DrawingState:
    """The outline drawing of one datasheet: its expected text and the file's state."""

    tag: str
    datasheet: str
    drawing: str
    text: str
    #: ``current``, ``stale`` or ``missing``.
    state: str


def drawing_states(workspace: Workspace, meta: dict[str, str]) -> list[DrawingState]:
    """The outline drawing of every valid datasheet, expected and as written."""
    found = []
    for loaded in _sheets(workspace):
        sheet = loaded.sheet
        assert sheet is not None
        tag = sheet.tag.strip()
        expected = drawing_text(sheet, loaded.path.read_bytes(), meta)
        path = drawing_path(workspace, tag)
        if not path.is_file():
            state = "missing"
        else:
            state = "current" if path.read_text(encoding="utf-8") == expected else "stale"
        found.append(DrawingState(tag, loaded.name, workspace.relative(path), expected, state))
    return found


def drawing_findings(workspace: Workspace, meta: dict[str, str]) -> list[Finding]:
    """``cheme.datasheet-drawing-stale`` (warning): an outline drawing that is not what the
    datasheet gives now. A datasheet without a drawing is not reported (the ``datasheets`` gate
    can require one)."""
    return [
        Finding(
            state.drawing,
            "warning",
            "cheme.datasheet-drawing-stale",
            f"{state.drawing} is not the outline drawing of {state.datasheet} as it is now",
            ids=[state.tag],
            hint=f"cheme datasheets drawing --tag {state.tag} --write",
        )
        for state in drawing_states(workspace, meta)
        if state.state == "stale"
    ]


# -- the gate --------------------------------------------------------------------------------------

#: What a ``kind: datasheets`` gate can require besides a final datasheet per item.
GATE_REQUIREMENTS = ("dimensions", "weights", "nozzle-schedule", "drawing-current")


def _given(entry: Any) -> bool:
    return (
        entry is not None
        and field_state(entry) != "tbd"
        and str(getattr(entry, "value", entry)).strip() != ""
    )


def main_dimensions_missing(sheet: Datasheet) -> list[str]:
    """The main dimensions of the item's family the datasheet does not give (a ``supplier``
    or ``not_applicable`` marker counts as given)."""
    from chemeascode.domains.equipment.outline import kind_of

    kind = kind_of(sheet.type)
    d = sheet.dimensions
    if d is None:
        return ["dimensions"]
    need: list[tuple[str, Any]] = []
    if kind in ("column", "tank", "vessel"):
        need = [
            ("outside_diameter or inside_diameter", d.outside_diameter or d.inside_diameter),
            ("tangent_length", d.tangent_length),
            ("head", d.head),
            ("support.type", d.support.type if d.support else None),
        ]
        if kind == "column":
            need.append(("sections", d.sections or None))
    elif kind == "shell_tube":
        tubes = d.tubes
        need = [
            ("inside_diameter", d.inside_diameter),
            ("tubes.length", tubes.length if tubes else None),
            ("tubes.count", tubes.count if tubes else None),
            ("tubes.outside_diameter", tubes.outside_diameter if tubes else None),
            ("tubes.passes", tubes.passes if tubes else None),
        ]
    elif kind == "plate":
        plates = d.plates
        need = [
            ("plates.height", plates.height if plates else None),
            ("plates.width", plates.width if plates else None),
            ("plates.count", plates.count if plates else None),
        ]
    elif kind == "machine":
        base = d.baseplate
        need = [
            ("baseplate.length", base.length if base else None),
            ("baseplate.width", base.width if base else None),
            ("shaft_height", d.shaft_height),
        ]
    else:
        need = [
            ("overall_height or overall_length", d.overall_height or d.overall_length),
        ]
    return [name for name, entry in need if not (entry == [] or _given_any(entry))]


def _given_any(entry: Any) -> bool:
    if isinstance(entry, list):
        return bool(entry)
    return _given(entry)


def weights_missing(sheet: Datasheet) -> list[str]:
    """The weights the datasheet does not give: empty and operating, and the test weight of
    a pressure-containing item."""
    from chemeascode.domains.equipment.outline import PRESSURE_KINDS, kind_of

    w = sheet.weights
    keys = ["empty", "operating"]
    if kind_of(sheet.type) in PRESSURE_KINDS:
        keys.append("test")
    return [k for k in keys if not _given(getattr(w, k) if w is not None else None)]


def datasheet_gate(workspace: Workspace, require: list[str], meta: dict[str, str]) -> list[str]:
    """The problems a ``kind: datasheets`` gate with ``require:`` (:data:`GATE_REQUIREMENTS`)
    finds on the valid datasheets: ``dimensions`` the main dimensions of each item's family,
    ``weights`` its weights, ``nozzle-schedule`` a located schedule (every nozzle with a DN
    and a face, a side nozzle with its orientation and elevation), ``drawing-current`` an
    outline drawing that is what ``cheme datasheets drawing`` writes."""

    def shown(items: dict[str, list[str]]) -> str:
        tags = sorted(items)
        text = "; ".join(f"{t} ({', '.join(items[t][:4])})" for t in tags[:6])
        return text + (f" and {len(tags) - 6} more" if len(tags) > 6 else "")

    problems: list[str] = []
    sheets = [loaded.sheet for loaded in _sheets(workspace) if loaded.sheet is not None]
    if "dimensions" in require:
        missing = {s.tag.strip(): m for s in sheets if (m := main_dimensions_missing(s))}
        if missing:
            problems.append(f"main dimensions missing: {shown(missing)}")
    if "weights" in require:
        missing = {s.tag.strip(): m for s in sheets if (m := weights_missing(s))}
        if missing:
            problems.append(f"weights missing: {shown(missing)}")
    if "nozzle-schedule" in require:
        missing = {}
        for s in sheets:
            open_ = [
                n.name
                for n in s.nozzles
                if n.dn is None
                or not n.face
                or n.face == "side"
                and (n.orientation_deg is None or n.elevation_m is None)
            ]
            if open_:
                missing[s.tag.strip()] = open_
        if missing:
            problems.append(f"nozzles without DN or location: {shown(missing)}")
    if "drawing-current" in require:
        states = drawing_states(workspace, meta)
        bad = {s.tag: [s.state] for s in states if s.state != "current"}
        if bad:
            problems.append(
                f"outline drawings not current: {shown(bad)}; run cheme datasheets drawing --write"
            )
    return problems
