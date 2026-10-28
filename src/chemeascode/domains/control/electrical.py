"""The electrical list (``electrical/electrical-list.yaml``, kind ``electrical``): the motor list,
cable sizes and which instruments and valves need a cable.

- **Motors** (:func:`motor_list`) are derived from the equipment list: every item whose DEXPI
  class has a driver (pumps, compressors, blowers, fans, agitators, mixers, air coolers, ...;
  not turbines, expanders, nor a machine of ``dimensions.variant`` ``compander`` or
  ``expander``, which drive themselves). The power comes from the list's ``motors`` entry,
  else from the item's datasheet (``type_specific`` or ``operating``: ``motor_kw``,
  ``motor_power_kw``, ``driver_kw``, ``driver_power_kw``, ``rated_power_kw`` or ``power_kw``),
  else it is missing (finding ``cheme.electrical-motor-power``). The voltage is the entry's,
  else MV above ``defaults.mv_above_kw``, else LV; the room the entry's, else the default room
  of that voltage, else the first room of kind ``mcc`` (LV) or ``switchgear`` (MV).
- **Cable sizes** (:func:`power_cable`, :func:`field_cable`, :func:`multipair_cable`) come from
  the package table ``data/cables.yaml`` (every row ASSUMED): a power cable carries the motor's
  full-load current (a feeder's load current, at its own power factor and without a motor's
  efficiency) with the table's derating, an instrument has a single-pair (transmitter,
  positioner) or three-pair (on/off valve) field cable to its junction box, and a junction box
  a multipair cable to the control room with spare pairs.
- **Instruments** (:func:`instrument_functions`): the instrument functions a loaded P&ID draws,
  with what they measure (``SensingLocation``) and whether they sit in the field: a function
  with a sensor that is not located ``Field`` (a local gauge) needs a cable. **Actuated
  valves** (:func:`actuated_valve`) are known by their tag letters (``FV``, ``LV``, ``XV``,
  ``SDV``, ...; not hand, safety, relief or check valves) or a DEXPI class with ``Control`` or
  ``Operated``.

``cheme validate`` runs :func:`cross_check_electrical`: a motor or feeder entry naming no
equipment-list tag, a room, substation or junction box that does not exist, duplicate ids, and
the motors without a power.

Where the cables run (trays, junction box positions, lengths) is the 3D model's:
:mod:`chemeascode.domains.spatial.trays`.
"""

from __future__ import annotations

import fnmatch
import math
import re
from dataclasses import dataclass
from functools import cache
from pathlib import Path
from typing import Any

import yaml

from chemeascode.foundation.findings import Finding
from chemeascode.foundation.workspace import LIST_FILES, Workspace
from chemeascode.foundation.yamlsource import _compose, _yaml_line

DATA = Path(__file__).parent / "data" / "cables.yaml"
ELECTRICAL_FILE = LIST_FILES["electrical"]
#: DEXPI classes whose items have an electric driver (by the end of the class name).
DRIVEN = re.compile(
    r"(Pump|Compressor|Blower|Fan|Agitator|Mixer|Stirrer|Centrifuge|Conveyor|Crusher|Mill|"
    r"Extruder|Kneader|AirCooledHeatExchanger|AirCooler|CoolingTower)$"
)
#: Classes and machine variants that drive themselves (an expander drives its compressor).
SELF_DRIVEN = re.compile(r"Turbine|Expander|Engine")
SELF_DRIVEN_VARIANTS = ("compander", "expander")
#: Datasheet keys of a driver's rated power, kW, in this order.
POWER_KEYS = (
    "motor_kw",
    "motor_power_kw",
    "driver_kw",
    "driver_power_kw",
    "rated_power_kw",
    "power_kw",
)
#: Tag letters of an on/off valve (one cable of three pairs: solenoid and limit switches).
ON_OFF = re.compile(r"^(X|U|K|Z|SD|BD|ESD|ES|HS)[A-Z]*V$")
#: Tag letters of an actuated valve (a positioner or a solenoid): ends in V; hand, safety,
#: relief, self-acting and check valves excluded.
ACTUATED = re.compile(r"^(?!H)[A-Z]{1,4}V$")
NOT_ACTUATED = re.compile(r"(SV|RV|CV|VV)$")


@cache
def cable_table() -> dict[str, Any]:
    """The package table ``data/cables.yaml``."""
    return yaml.safe_load(DATA.read_text(encoding="utf-8"))


# ---------------------------------------------------------------------------
# Cable sizes
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class CableType:
    """A cable's type: what the schedule prints and the tray fill counts."""

    system: str  # power, instrument
    size: str  # e.g. "4C x 50 mm2", "2 x 3C x 240 mm2", "1 pr x 1.5 mm2", "24 pr x 0.5 mm2"
    od_mm: float
    count: int = 1  # parallel cables
    voltage_v: float | None = None
    current_a: float | None = None
    pairs: int | None = None
    basis: str = ""

    @property
    def area_mm2(self) -> float:
        """The cross-section the cables take on a tray, mm2."""
        return self.count * math.pi * self.od_mm**2 / 4


def full_load_current(power_kw: float, voltage_v: float) -> float:
    """A three-phase motor's full-load current, A (the table's power factor and efficiency)."""
    table = cable_table()
    return (
        power_kw * 1000 / (math.sqrt(3) * voltage_v * table["power_factor"] * table["efficiency"])
    )


def load_current(power_kw: float, voltage_v: float, power_factor: float) -> float:
    """A three-phase load's current at *power_factor*, A: a feeder (heater, package), with no
    motor efficiency. Three-phase only: a single-phase load (a 230 V socket outlet) draws more
    for its power."""
    return power_kw * 1000 / (math.sqrt(3) * voltage_v * power_factor)


def power_cable(
    power_kw: float | None, voltage_v: float, power_factor: float | None = None
) -> CableType:
    """The power cable of a consumer of *power_kw* at *voltage_v* (LV or MV table): a motor's
    full-load current, or with *power_factor* a feeder's load current. Without a power, the
    smallest size of the table (marked in ``basis``)."""
    table = cable_table()
    group = table["lv"] if voltage_v <= table["lv"]["max_voltage_v"] else table["mv"]
    cores = group["cores"]
    sizes = group["sizes"]
    if power_kw is None:
        mm2, _, od = sizes[0]
        return CableType(
            "power",
            f"{cores}C x {mm2:g} mm2",
            od,
            voltage_v=voltage_v,
            basis=f"power unknown: smallest size assumed; {group['basis']}",
        )
    current = (
        full_load_current(power_kw, voltage_v)
        if power_factor is None
        else load_current(power_kw, voltage_v, power_factor)
    )
    derating = table["derating"]
    for mm2, rating, od in sizes:
        if rating * derating >= current:
            return CableType(
                "power",
                f"{cores}C x {mm2:g} mm2",
                od,
                voltage_v=voltage_v,
                current_a=round(current, 1),
                basis=group["basis"],
            )
    mm2, rating, od = sizes[-1]
    count = math.ceil(current / (rating * derating))
    return CableType(
        "power",
        f"{count} x {cores}C x {mm2:g} mm2",
        od,
        count=count,
        voltage_v=voltage_v,
        current_a=round(current, 1),
        basis=group["basis"],
    )


def field_cable(kind: str) -> CableType:
    """The field cable of an instrument (``transmitter``), a ``control_valve`` or an
    ``on_off_valve``, to its junction box."""
    table = cable_table()["instrument"]
    row = table["field"][kind]
    return CableType(
        "instrument",
        f"{row['pairs']} pr x 1.5 mm2",
        row["od_mm"],
        pairs=row["pairs"],
        basis=table["basis"],
    )


def multipair_cable(pairs: int, spare: float) -> CableType:
    """The multipair cable of a junction box with *pairs* in use and *spare* (fraction) more;
    parallel cables of the largest size when none holds them."""
    table = cable_table()["instrument"]
    need = max(1, math.ceil(pairs * (1 + spare)))
    for size, od in table["multipair"]:
        if size >= need:
            return CableType(
                "instrument", f"{size} pr x 0.5 mm2", od, pairs=size, basis=table["basis"]
            )
    size, od = table["multipair"][-1]
    count = math.ceil(need / size)
    return CableType(
        "instrument",
        f"{count} x {size} pr x 0.5 mm2",
        od,
        count=count,
        pairs=size * count,
        basis=table["basis"],
    )


# ---------------------------------------------------------------------------
# Motors
# ---------------------------------------------------------------------------


@dataclass
class MotorEntry:
    """A motor of the motor list, with where its power comes from."""

    tag: str
    driven: str
    power_kw: float | None
    voltage_v: float
    room: str | None
    basis: str  # list, datasheet, missing
    assumed: bool = False
    source: str = ""
    skip: str | None = None
    kind: str = "motor"  # motor, feeder
    power_factor: float | None = None  # a feeder's (its cable current); None: a motor's
    power_factor_assumed: bool = False  # a feeder's default 1.0, not given in the list
    item: str | None = None  # the placed tag it is at
    point: tuple[float, float, float] | None = None


def is_driven(item: Any) -> bool:
    """Whether equipment-list *item* has an electric driver (see the module text)."""
    cls = (item.type or "").strip()
    if not DRIVEN.search(cls) or SELF_DRIVEN.search(cls):
        return False
    variant = getattr(getattr(item, "dimensions", None), "variant", None)
    return variant not in SELF_DRIVEN_VARIANTS


def _number(value: Any) -> tuple[float | None, bool, str]:
    from chemeascode.domains.equipment.schemas.datasheet import Quantity

    assumed, source = False, ""
    if isinstance(value, Quantity):
        assumed, source, value = value.assumed, value.source, value.value
    elif isinstance(value, dict):
        assumed = bool(value.get("assumed"))
        source = str(value.get("source") or "")
        value = value.get("value")
    if isinstance(value, bool):
        return None, assumed, source
    if isinstance(value, int | float):
        return float(value), assumed, source
    try:
        return float(str(value).split()[0]), assumed, source
    except (ValueError, IndexError):
        return None, assumed, source


def datasheet_power(workspace: Workspace, tag: str) -> tuple[float, bool, str] | None:
    """The driver power of *tag* from its datasheet: ``(kW, assumed, source)``, or None."""
    from chemeascode.domains.equipment.datasheets import DATASHEET_DIR, load

    path = workspace.root / DATASHEET_DIR / f"{tag}.yaml"
    if not path.is_file():
        return None
    sheet = load(workspace, path).sheet
    if sheet is None:
        return None
    for section in (sheet.type_specific, sheet.operating):
        for key in POWER_KEYS:
            if key in section:
                kw, assumed, source = _number(section[key])
                if kw is not None and kw > 0:
                    where = f"{DATASHEET_DIR}/{tag}.yaml {key}"
                    return kw, assumed, f"{where}: {source}" if source else where
    return None


def _room_for(electrical: Any, voltage_v: float, mv: bool) -> str | None:
    if electrical is None:
        return None
    defaults = electrical.defaults
    wanted = defaults.mv_room if mv else defaults.lv_room
    if wanted:
        return wanted
    kind = "switchgear" if mv else "mcc"
    for room in electrical.rooms:
        if room.kind == kind:
            return room.id
    for room in electrical.rooms:
        if room.kind in ("mcc", "switchgear"):
            return room.id
    return None


def control_room(electrical: Any) -> str | None:
    """Where the instrument cables go: ``defaults.control_room``, else the first room of kind
    ``control``, else of kind ``rack_room``."""
    if electrical is None:
        return None
    if electrical.defaults.control_room:
        return electrical.defaults.control_room
    for kind in ("control", "rack_room"):
        for room in electrical.rooms:
            if room.kind == kind:
                return room.id
    return None


def motor_list(
    workspace: Workspace, equipment: Any, electrical: Any
) -> tuple[list[MotorEntry], list[Finding]]:
    """The motors and feeders of the plant (see the module text), and the findings on them."""
    findings: list[Finding] = []
    entries = {m.driven.strip(): m for m in getattr(electrical, "motors", None) or ()}
    defaults = electrical.defaults if electrical is not None else None
    lv = defaults.lv_voltage_v if defaults is not None else 400.0
    mv_v = defaults.mv_voltage_v if defaults is not None else 6600.0
    mv_above = defaults.mv_above_kw if defaults is not None else 200.0
    found: list[MotorEntry] = []
    listed = {item.tag.strip(): item for item in getattr(equipment, "equipment", None) or ()}
    tags = [tag for tag, item in listed.items() if is_driven(item)]
    tags += [tag for tag in entries if tag not in tags and tag in listed]
    for tag in tags:
        entry = entries.get(tag)
        power, assumed, source, basis = None, False, "", "missing"
        if entry is not None and entry.power_kw is not None:
            power, assumed, source, basis = entry.power_kw, entry.assumed, entry.source, "list"
        else:
            sheet = datasheet_power(workspace, tag)
            if sheet is not None:
                power, assumed, source = sheet
                basis = "datasheet"
        voltage = entry.voltage_v if entry is not None and entry.voltage_v else None
        if voltage is None:
            voltage = mv_v if power is not None and power > mv_above else lv
        mv = voltage > cable_table()["lv"]["max_voltage_v"]
        room = (entry.room if entry is not None else None) or _room_for(electrical, voltage, mv)
        found.append(
            MotorEntry(
                tag=(entry.tag if entry is not None and entry.tag else f"M-{tag}"),
                driven=tag,
                power_kw=power,
                voltage_v=voltage,
                room=room,
                basis=basis,
                assumed=assumed,
                source=source,
                skip=entry.skip if entry is not None else None,
                item=tag,
            )
        )
    for feeder in getattr(electrical, "feeders", None) or ():
        voltage = feeder.voltage_v or lv
        mv = voltage > cable_table()["lv"]["max_voltage_v"]
        found.append(
            MotorEntry(
                tag=feeder.tag,
                driven=feeder.item or feeder.tag,
                power_kw=feeder.power_kw,
                voltage_v=voltage,
                room=feeder.room or _room_for(electrical, voltage, mv),
                basis="list",
                assumed=feeder.assumed,
                source=feeder.source,
                kind="feeder",
                power_factor=feeder.power_factor or 1.0,
                power_factor_assumed=feeder.power_factor is None,
                item=feeder.item,
                point=feeder.point,
            )
        )
    return found, findings


# ---------------------------------------------------------------------------
# Instruments and actuated valves
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class InstrumentFunction:
    """An instrument function a P&ID draws: what it measures and where it sits."""

    tag: str
    id: str
    sheet: str
    sensing: str | None  # DEXPI id of the nozzle, segment, item it measures
    location: str | None  # CentralLocation, ControlPanel, Field
    sensor: bool  # it has a signal generating function (a sensor in the field)

    @property
    def cabled(self) -> bool:
        """A sensor in the field reporting elsewhere: it needs a cable."""
        return self.sensor and self.location != "Field"


def instrument_functions(model: Any, sheet: str) -> list[InstrumentFunction]:
    """Every instrument function of a loaded P&ID *model* (pyDEXPI), in model order."""
    from pydexpi.pydexpi_classes.pydexpi_classes import ProcessInstrumentationFunction
    from pydexpi.toolkits.display_name import instrument_tag
    from pydexpi.toolkits.model_toolkit import get_all_instances_in_model

    found = []
    for obj in get_all_instances_in_model(model):
        if not isinstance(obj, ProcessInstrumentationFunction):
            continue
        tag = (instrument_tag(obj) or "").strip()
        if not tag:
            continue
        sensing = None
        generators = list(obj.processSignalGeneratingFunctions or ())
        for generator in generators:
            target = getattr(generator, "sensingLocation", None)
            if target is not None and getattr(target, "id", None):
                sensing = target.id
                break
        location = getattr(obj, "location", None)
        location = getattr(location, "value", location)
        found.append(
            InstrumentFunction(
                tag=tag,
                id=obj.id or "",
                sheet=sheet,
                sensing=sensing,
                location=str(location) if location else None,
                sensor=bool(generators),
            )
        )
    return found


def actuated_valve(tag: str | None, dexpi_class: str = "") -> str | None:
    """``on_off_valve``, ``control_valve`` or None (no cable) for a valve of *tag* and class."""
    letters = (tag or "").split("-", 1)[0].strip().upper() if tag and "-" in tag else ""
    if "Operated" in dexpi_class or "Motor" in dexpi_class:
        return "on_off_valve"
    if letters and ACTUATED.match(letters) and not NOT_ACTUATED.search(letters):
        return "on_off_valve" if ON_OFF.match(letters) else "control_valve"
    if "Control" in dexpi_class:
        return "control_valve"
    return None


def matches(tag: str, patterns: list[str]) -> bool:
    """Whether *tag* matches one of *patterns* (a glob, or the tag itself)."""
    return any(
        fnmatch.fnmatchcase(tag, p) if any(c in p for c in "*?[") else tag == p.strip()
        for p in patterns
    )


# ---------------------------------------------------------------------------
# validate
# ---------------------------------------------------------------------------


def cross_check_electrical(workspace: Workspace, parsed: dict[str, Any]) -> list[Finding]:
    """The electrical list against the equipment list and itself (see the module text)."""
    electrical = parsed.get("electrical")
    if electrical is None:
        return []
    path = workspace.list_file("electrical")
    document = _compose(path) if path is not None else None
    name = ELECTRICAL_FILE
    findings: list[Finding] = []

    def add(level: str, rule: str, message: str, loc: list[Any], ids: list[str], hint: str):
        findings.append(
            Finding(
                name,
                level,  # type: ignore[arg-type]
                f"cheme.electrical-{rule}",
                message,
                line=_yaml_line(document, loc) if document is not None and loc else None,
                ids=ids,
                hint=hint,
            )
        )

    for section, key in (
        ("substations", "id"),
        ("rooms", "id"),
        ("transformers", "tag"),
        ("motors", "driven"),
        ("feeders", "tag"),
        ("junction_boxes", "tag"),
        ("instruments", "tag"),
    ):
        seen: set[str] = set()
        for k, entry in enumerate(getattr(electrical, section)):
            value = str(getattr(entry, key)).strip()
            if value in seen:
                add(
                    "error",
                    "duplicate",
                    f"{section}: {value} is listed twice",
                    [section, k],
                    [value],
                    "list each once",
                )
            seen.add(value)
    rooms = {room.id for room in electrical.rooms}
    substations = {s.id for s in electrical.substations}
    boxes = {jb.tag for jb in electrical.junction_boxes}
    equipment = parsed.get("equipment")
    listed = {i.tag.strip(): i for i in getattr(equipment, "equipment", None) or ()}

    def room_ref(value: str | None, loc: list[Any], owner: str) -> None:
        if value and value not in rooms:
            add(
                "error",
                "unknown-room",
                f"{owner}: room {value} is not in rooms",
                loc,
                [owner],
                f"rooms: {', '.join(sorted(rooms)) or 'none'}",
            )

    defaults = electrical.defaults
    for field in ("lv_room", "mv_room", "control_room"):
        room_ref(getattr(defaults, field), ["defaults", field], f"defaults.{field}")
    for k, room in enumerate(electrical.rooms):
        if room.substation and room.substation not in substations:
            add(
                "error",
                "unknown-substation",
                f"room {room.id}: substation {room.substation} is not in substations",
                ["rooms", k, "substation"],
                [room.id],
                f"substations: {', '.join(sorted(substations)) or 'none'}",
            )
    for k, transformer in enumerate(electrical.transformers):
        if transformer.substation and transformer.substation not in substations:
            add(
                "error",
                "unknown-substation",
                f"{transformer.tag}: substation {transformer.substation} is not in substations",
                ["transformers", k, "substation"],
                [transformer.tag],
                f"substations: {', '.join(sorted(substations)) or 'none'}",
            )
        for j, room in enumerate(transformer.feeds):
            room_ref(room, ["transformers", k, "feeds", j], transformer.tag)
    for k, motor in enumerate(electrical.motors):
        room_ref(motor.room, ["motors", k, "room"], motor.driven)
        if equipment is not None and motor.driven not in listed:
            add(
                "error",
                "unknown-tag",
                f"motor of {motor.driven}: no such equipment-list item",
                ["motors", k, "driven"],
                [motor.driven],
                "driven names the equipment-list tag the motor drives",
            )
    for k, feeder in enumerate(electrical.feeders):
        room_ref(feeder.room, ["feeders", k, "room"], feeder.tag)
    for k, jb in enumerate(electrical.junction_boxes):
        room_ref(jb.room, ["junction_boxes", k, "room"], jb.tag)
    for k, entry in enumerate(electrical.instruments):
        if entry.jb and entry.jb not in boxes:
            add(
                "error",
                "unknown-jb",
                f"{entry.tag}: junction box {entry.jb} is not in junction_boxes",
                ["instruments", k, "jb"],
                [entry.tag],
                f"junction boxes: {', '.join(sorted(boxes)) or 'none'}",
            )
    if equipment is not None:
        motors, _ = motor_list(workspace, equipment, electrical)
        index = {m.driven.strip(): k for k, m in enumerate(electrical.motors)}
        for motor in motors:
            if motor.kind != "motor" or motor.skip:
                continue
            loc: list[Any] = ["motors", index[motor.driven]] if motor.driven in index else []
            if motor.power_kw is None:
                add(
                    "warning",
                    "motor-power",
                    f"{motor.tag} (driving {motor.driven}) has no power: its cable is sized "
                    "by the smallest size",
                    loc,
                    [motor.driven],
                    f"give power_kw in {name} motors, or driver_kw in its datasheet",
                )
            if motor.room is None:
                add(
                    "warning",
                    "motor-room",
                    f"{motor.tag} (driving {motor.driven}) is fed from no room",
                    loc,
                    [motor.driven],
                    "declare a room of kind mcc (LV) or switchgear (MV), or room: on the motor",
                )
    return findings
