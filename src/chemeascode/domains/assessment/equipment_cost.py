"""The equipment estimate from published cost correlations (``cheme assess equipment``).

Each item of the equipment list is costed by the purchased and bare module cost correlations
of Turton et al. (CAPCOST, Appendix A of "Analysis, Synthesis, and Design of Chemical
Processes", 5th ed., 2018), package data ``data/turton-capcost.yaml`` with the source of every
row:

1. **correlation**: chosen from the item's DEXPI class (a pump: centrifugal unless the class
   says reciprocating or positive displacement; a shell and tube exchanger: fixed tube sheet
   unless the class says U-tube, floating head or kettle; a vessel vertical unless the list
   gives a length and no height; a column: a tower shell; ...), or named by the project
   (``estimate/cost-basis.yaml`` items). The choice is stated per item;
2. **size** A (volume m3, area m2, shaft or fluid power kW, gas flow m3/s, duty kW): from the
   project (``size``, with its source), else the item's datasheet (``type_specific``,
   ``operating`` or ``design``: ``volume_m3``, ``area_m2`` or ``heat_transfer_area_m2``,
   ``shaft_power_kw`` or ``power_kw``, ``fluid_power_kw``, ``gas_flow_m3_s`` or ``flow_m3_s``,
   ``duty_kw``; the size source carries the value's own source, ``ASSUMED`` when the
   datasheet marks it ``assumed: true``, and ``draft`` for a draft datasheet, listed in an info
   finding), else, for a volume, the list's ``dimensions`` (pi/4 D^2 H over the overall
   height or length: an upper bound, marked ASSUMED); else the item is not covered (a
   finding). Outside the correlation's range of A it is not costed (a finding), never
   extrapolated;
3. **purchased cost** at the base: log10 Cp0 = K1 + K2 log10 A + K3 (log10 A)^2 (US dollars,
   CEPCI 397, 2001);
4. **bare module cost** CBM = Cp0 (B1 + B2 Fm Fp), or Cp0 FBM where the source gives FBM: the
   pressure factor from the list's ``design_pressure_barg`` (a vessel's from its diameter),
   the material factor from the list's ``material`` when it reads as carbon steel or stainless
   steel only. A factor held for one machine kind only (the compressor FBM: centrifugal) is
   not applied to a class naming another kind (axial, reciprocating), and is marked ASSUMED
   for a class naming none. A factor the package data lacks comes from the project (``fm``, ``fp``,
   ``fbm`` with ``factor_source``), else the item has its purchased cost only (a finding);
5. **escalation** by the project's cost index (``cost_index``: value, year, source):
   cost x index / 397. cheme-as-code holds no current index: without one the costs stay at 2001.

The project may also give an item's own cost (a quotation: ``cost``, ``currency``, ``year``,
``source``) or leave it out with a reason (``exclude``). The bare module cost includes the
installation materials and labour and the indirect costs of the item (Turton, chapter 7), so
the bulk factor estimate of the take-off (:mod:`.estimate`) must not be added on top for the
same scope. The result states its estimate class (AACE International Recommended Practice
18R-97) and which items it covers.
"""

from __future__ import annotations

import csv
import io
import json
import math
from dataclasses import asdict, dataclass, field
from functools import cache
from pathlib import Path
from typing import Any

import yaml
from pydantic import ValidationError

from chemeascode.domains.assessment.schemas import CostBasis
from chemeascode.foundation.findings import Finding
from chemeascode.foundation.provenance import SourceRevision, source_revision
from chemeascode.foundation.workspace import LIST_FILES

DATA = Path(__file__).parent / "data" / "turton-capcost.yaml"
BASIS_FILE = LIST_FILES["cost_basis"]
EQUIPMENT_FILE = LIST_FILES["equipment"]
COST_CSV = "estimate/equipment-cost.csv"
COST_MD = "estimate/equipment-cost.md"
#: AACE International Recommended Practice 18R-97: expected accuracy range by class
#: (low, high), the wider and narrower ends of each.
AACE_RANGES = {
    5: ("-20 % to -50 %", "+30 % to +100 %"),
    4: ("-15 % to -30 %", "+20 % to +50 %"),
    3: ("-10 % to -20 %", "+10 % to +30 %"),
    2: ("-5 % to -15 %", "+5 % to +20 %"),
    1: ("-3 % to -10 %", "+3 % to +15 %"),
}
AACE = (
    "AACE International Recommended Practice No. 18R-97, Cost Estimate Classification System "
    "- as Applied in Engineering, Procurement, and Construction for the Process Industries"
)
#: Datasheet keys giving each correlation attribute, in order of preference.
SIZE_KEYS = {
    "volume": ("volume_m3",),
    "area": ("area_m2", "heat_transfer_area_m2"),
    "shaft_power": ("shaft_power_kw", "power_kw"),
    "fluid_power": ("fluid_power_kw",),
    "gas_flow": ("gas_flow_m3_s", "flow_m3_s"),
    "duty": ("duty_kw",),
    "catalyst_mass": ("catalyst_mass_kg",),
    "catalyst_volume": ("catalyst_volume_m3",),
}
COLUMNS = (
    "tag",
    "type",
    "correlation",
    "size",
    "unit",
    "size_source",
    "cp0_base",
    "fp",
    "fm",
    "fbm",
    "cbm_base",
    "index_ratio",
    "purchased",
    "bare_module",
    "status",
    "notes",
)


@cache
def capcost() -> dict[str, Any]:
    """The package data (``data/turton-capcost.yaml``)."""
    return yaml.safe_load(DATA.read_text(encoding="utf-8"))


def purchased_cost(correlation: str, size: float) -> float:
    """Cp0 of *correlation* at attribute *size*, US dollars at the base CEPCI (no range check)."""
    k1, k2, k3 = capcost()["correlations"][correlation]["K"]
    x = math.log10(size)
    return 10 ** (k1 + k2 * x + k3 * x * x)


def vessel_pressure_factor(p_barg: float, diameter_m: float) -> float:
    """Fp of a process vessel (Turton Table A.2): ((P + 1) D / (2 (850 - 0.6 (P + 1))) +
    0.00315) / 0.0063, at least 1."""
    p = p_barg + 1
    return max(1.0, (p * diameter_m / (2 * (850 - 0.6 * p)) + 0.00315) / 0.0063)


def pressure_factor(c: list[float], p_barg: float) -> float:
    """log10 Fp = C1 + C2 log10 P + C3 (log10 P)^2."""
    x = math.log10(p_barg)
    return 10 ** (c[0] + c[1] * x + c[2] * x * x)


def choose(type_: str, dimensions: Any) -> tuple[str | None, str]:
    """The correlation for a DEXPI class, and why (see the module text)."""
    t = (type_ or "").lower()
    if "pump" in t:
        if "reciprocating" in t or "piston" in t or "plunger" in t:
            return "pump_reciprocating", "reciprocating pump by its class"
        if any(w in t for w in ("positive", "screw", "gear", "rotary", "diaphragm")):
            return "pump_positive_displacement", "positive displacement pump by its class"
        return "pump_centrifugal", "centrifugal pump (the class names no other kind)"
    if "compressor" in t:
        if "rotary" in t or "screw" in t:
            return "compressor_rotary", "rotary compressor by its class"
        return "compressor", "centrifugal, axial or reciprocating compressor"
    if "fan" in t:
        return "fan_centrifugal_radial", "centrifugal radial fan (ASSUMED kind)"
    if "steamturbine" in t:
        return "turbine_steam", "steam turbine by its class"
    if "gasturbine" in t:
        return "turbine_axial_gas", "axial gas turbine by its class"
    if "expander" in t or "turbine" in t:
        return "expander_radial", "radial expander (ASSUMED: a process expander)"
    if "fired" in t or "furnace" in t:
        return "heater_fired", "nonreactive fired heater"
    if "aircool" in t:
        return "hx_air_cooler", "air cooler by its class"
    if "spiral" in t:
        return "hx_spiral_plate", "spiral plate exchanger by its class"
    if "plate" in t and ("exchanger" in t or "heat" in t):
        return "hx_flat_plate", "flat plate exchanger (ASSUMED for a plate exchanger class)"
    if "doublepipe" in t:
        return "hx_double_pipe", "double pipe exchanger by its class"
    if "kettle" in t or "reboiler" in t:
        return "hx_kettle", "kettle reboiler by its class"
    if "utube" in t:
        return "hx_u_tube", "U-tube exchanger by its class"
    if "floatinghead" in t:
        return "hx_floating_head", "floating head exchanger by its class"
    # a reactor before the tubular exchanger and the tank: a StirredTankReactor or a
    # TubularReactor is a reactor, as the datasheet fill classifies it, not a storage tank or
    # an exchanger by area
    if "reactor" in t or "converter" in t:
        return _vessel(
            dimensions,
            " (a reactor costed as its pressure vessel; internals and catalyst not included)",
        )
    if "tubular" in t or "shellandtube" in t or t == "heatexchanger":
        return "hx_fixed_tube", "fixed tube sheet exchanger (ASSUMED: the class names no other)"
    if "column" in t or "tower" in t:
        return "tower", "tower shell (internals not included)"
    if "tank" in t:
        if "floating" in t:
            return "tank_floating_roof", "floating roof tank by its class"
        return "tank_fixed_roof", "API fixed roof tank (ASSUMED: the class names no roof)"
    if "vessel" in t or "drum" in t or "separator" in t:
        return _vessel(dimensions, "")
    return None, f"no correlation of the package data for the class {type_ or '(none)'}"


def _vessel(dims: Any, what: str) -> tuple[str, str]:
    """The vessel correlation for the list's *dims*, and why (*what* added to the reason)."""
    # as the 3D model reads the sizes: a diameter with a length is a horizontal shell (its
    # height, if given, is the top of the shell above the saddles' foot)
    if dims is not None and dims.length and (dims.diameter or not dims.height):
        return "vessel_horizontal", "horizontal vessel (the list gives a length)" + what
    return "vessel_vertical", "vertical vessel" + what


def material_of(text: str | None) -> str | None:
    """``CS`` or ``SS`` when the list's material reads as carbon steel or stainless steel only;
    None otherwise (a combination, another alloy, aluminium)."""
    if not text:
        return None
    t = text.lower().replace("-", " ")
    words = set(t.replace("/", " ").replace(",", " ").split())
    cs = "cs" in words or "carbon steel" in t
    ss = (
        "ss" in words
        or "stainless" in t
        or any(w.startswith(("1.43", "1.44", "1.45", "304", "316", "321")) for w in words)
    )
    other = any(
        w in t
        for w in (
            "alumin",
            "nickel",
            "inconel",
            "monel",
            "hastelloy",
            "titan",
            "copper",
            "brass",
            "bronze",
        )
    )
    if other or cs == ss:
        return None
    return "CS" if cs else "SS"


def _number(value: Any) -> float | None:
    from chemeascode.domains.equipment.datasheets import _number as number

    return number(value)


def datasheet_size(sheet: Any, attribute: str) -> tuple[float | None, str]:
    """The attribute's value from a datasheet, and where it comes from: the key, the value's
    own source, ``ASSUMED`` when the datasheet marks it ``assumed: true``, and ``draft`` when
    the datasheet is still a draft (its values are not confirmed)."""
    if sheet is None:
        return None, ""
    for part in ("type_specific", "operating", "design"):
        values = getattr(sheet, part, None) or {}
        for key in SIZE_KEYS.get(attribute, ()):
            if key in values:
                value = values[key]
                assumed, origin = False, ""
                if isinstance(value, dict):  # {value, unit, source, assumed} in type_specific
                    assumed = bool(value.get("assumed"))
                    origin = str(value.get("source") or "").strip()
                    value = value.get("value")
                elif hasattr(value, "assumed"):  # a Quantity in operating or design
                    assumed, origin = bool(value.assumed), (value.source or "").strip()
                found = _number(value)
                if found is not None and found > 0:
                    where = f"{'draft ' if getattr(sheet, 'draft', False) else ''}datasheet"
                    text = f"{where} {part}.{key}"
                    origin = " ".join(origin.split())
                    if assumed:
                        text += f" (ASSUMED: {origin or 'no basis given'})"
                    elif origin:
                        text += f" ({origin})"
                    return found, text
    return None, ""


@dataclass
class CostLine:
    """One item of the equipment estimate (see :data:`COLUMNS`)."""

    tag: str
    type: str
    correlation: str | None = None
    size: float | None = None
    unit: str = ""
    size_source: str = ""
    cp0_base: float | None = None
    fp: float | None = None
    fm: float | None = None
    fbm: float | None = None
    cbm_base: float | None = None
    index_ratio: float | None = None
    purchased: float | None = None
    bare_module: float | None = None
    status: str = ""
    notes: str = ""
    #: A catalyst fill's price year: its cost is of that year, not of the cost index's.
    price_year: int | None = None
    #: A catalyst fill priced in another currency than the estimate's: its cost in that
    #: currency (purchased and bare module stay empty, so it is in no total).
    own_cost: float | None = None
    currency: str = ""

    def row(self) -> dict[str, str]:
        def num(v: float | None, digits: int = 3) -> str:
            return "" if v is None else f"{round(v, digits):g}"

        def money(v: float | None) -> str:
            return "" if v is None else f"{v:.0f}"

        return {
            "tag": self.tag,
            "type": self.type,
            "correlation": self.correlation or "",
            "size": num(self.size),
            "unit": self.unit,
            "size_source": self.size_source,
            "cp0_base": money(self.cp0_base),
            "fp": num(self.fp),
            "fm": num(self.fm),
            "fbm": num(self.fbm),
            "cbm_base": money(self.cbm_base),
            "index_ratio": num(self.index_ratio, 4),
            "purchased": money(self.purchased),
            "bare_module": money(self.bare_module),
            "status": self.status,
            "notes": self.notes,
        }


@dataclass
class EquipmentEstimate:
    """The equipment estimate: one line per listed item, the findings and the basis."""

    lines: list[CostLine] = field(default_factory=list)
    findings: list[Finding] = field(default_factory=list)
    currency: str = "USD"
    base_cepci: float = 397.0
    base_year: int = 2001
    index: dict[str, Any] | None = None
    estimate_class: int = 5
    own_costs: list[dict[str, Any]] = field(default_factory=list)
    source: SourceRevision = field(default_factory=lambda: SourceRevision(None))

    def totals(self) -> dict[str, Any]:
        return {
            "purchased": round(sum(line.purchased or 0.0 for line in self.lines), 0),
            "bare_module": round(sum(line.bare_module or 0.0 for line in self.lines), 0),
            "items": len(self.lines),
            "bare_module_items": sum(1 for line in self.lines if line.bare_module is not None),
            "purchased_only": sum(
                1 for line in self.lines if line.purchased is not None and line.bare_module is None
            ),
            "own_cost": len(self.own_costs),
            "excluded": sum(1 for line in self.lines if line.status.startswith("excluded")),
            "not_covered": sum(1 for line in self.lines if line.status == "not covered"),
            "own_currency": sum(1 for line in self.lines if line.own_cost is not None),
        }

    def uncovered(self) -> list[str]:
        """Tags with no cost: neither the correlation, the project's cost nor an exclusion."""
        return [line.tag for line in self.lines if line.status == "not covered"]

    def payload(self) -> dict[str, Any]:
        return {
            "currency": self.currency,
            "base": {"cepci": self.base_cepci, "year": self.base_year},
            "index": self.index,
            "estimate_class": self.estimate_class,
            "accuracy": dict(zip(("low", "high"), AACE_RANGES[self.estimate_class], strict=True)),
            "totals": self.totals(),
            "lines": [asdict(line) for line in self.lines],
            "own_costs": self.own_costs,
            "findings": [asdict(f) for f in self.findings],
            "source": self.source.as_dict(),
        }

    def to_json(self) -> str:
        return json.dumps(self.payload(), indent=2)


def _finding(level: str, rule: str, message: str, tag: str, hint: str, file: str = BASIS_FILE):
    return Finding(file, level, f"cheme.{rule}", message, ids=[tag], hint=hint, key=tag)  # type: ignore[arg-type]


def estimate_equipment(
    equipment: Any, datasheets: dict[str, Any], basis: CostBasis | None
) -> EquipmentEstimate:
    """The equipment estimate of a parsed equipment list, its parsed datasheets by tag and the
    parsed cost basis (None: none)."""
    data = capcost()
    result = EquipmentEstimate(
        base_cepci=float(data["base_cepci"]["value"]),
        base_year=int(data["base_cepci"]["year"]),
        estimate_class=basis.estimate_class if basis is not None else 5,
    )
    given = {item.tag: item for item in (basis.items if basis is not None else [])}
    ratio = None
    if basis is not None and basis.cost_index is not None:
        index = basis.cost_index
        ratio = index.value / result.base_cepci
        result.index = index.model_dump(mode="json", exclude_none=True)
    else:
        result.findings.append(
            Finding(
                BASIS_FILE,
                "warning",
                "cheme.estimate-no-index",
                "no cost_index in estimate/cost-basis.yaml: the equipment costs stay at the "
                f"correlations' base (CEPCI {result.base_cepci:g}, {result.base_year})",
                hint="give cost_index: {value, year, source} (the CEPCI of the estimate's year, "
                "from where it is published)",
            )
        )
    for item in getattr(equipment, "equipment", None) or ():
        tag = item.tag.strip()
        mine = given.get(tag)
        line = CostLine(tag, item.type or "")
        result.lines.append(line)
        if mine is not None and mine.exclude:
            line.status = f"excluded: {mine.exclude}"
            continue
        if mine is not None and mine.cost is not None:
            line.status = "project cost"
            line.notes = f"{mine.cost:g} {mine.currency} {mine.year} ({mine.status}): {mine.source}"
            result.own_costs.append(
                {
                    "tag": tag,
                    "cost": mine.cost,
                    "currency": mine.currency,
                    "year": mine.year,
                    "status": mine.status,
                    "source": mine.source,
                }
            )
            continue
        _cost(line, item, datasheets.get(tag), mine, ratio, data, result.findings)
    drafts = [line.tag for line in result.lines if line.size_source.startswith("draft ")]
    if drafts:
        result.findings.append(
            Finding(
                BASIS_FILE,
                "info",
                "cheme.estimate-draft-size",
                f"{len(drafts)} item(s) sized from a draft datasheet, not yet confirmed: "
                + ", ".join(drafts),
                ids=drafts,
                hint="complete the datasheet and remove draft: true, or give size with "
                "size_source in estimate/cost-basis.yaml",
            )
        )
    return result


def _cost(
    line: CostLine,
    item: Any,
    sheet: Any,
    mine: Any,
    ratio: float | None,
    data: dict[str, Any],
    findings: list[Finding],
) -> None:
    tag = line.tag
    if mine is not None and mine.correlation:
        corr, why = mine.correlation, "named in estimate/cost-basis.yaml"
        if corr not in data["correlations"]:
            line.status = "not covered"
            line.notes = f"unknown correlation {corr}"
            findings.append(
                _finding(
                    "warning",
                    "estimate-equipment-uncovered",
                    f"{tag}: estimate/cost-basis.yaml names the unknown correlation {corr}",
                    tag,
                    "use a correlation id of the package data (cheme assess equipment "
                    "--json lists them)",
                )
            )
            return
    else:
        corr, why = choose(item.type, item.dimensions)
    if corr is None:
        line.status = "not covered"
        line.notes = why
        findings.append(
            _finding(
                "warning",
                "estimate-equipment-uncovered",
                f"{tag} ({item.type}): {why}",
                tag,
                "give its cost from a quotation (cost, currency, year, source), name a "
                "correlation, or exclude it with a reason in estimate/cost-basis.yaml",
            )
        )
        return
    row = data["correlations"][corr]
    line.correlation, line.unit = corr, row["unit"]
    notes = [why]
    size, source = (mine.size, mine.size_source) if mine is not None and mine.size else (None, "")
    if size is None:
        size, source = datasheet_size(sheet, row["attribute"])
    if size is None and row["attribute"] == "volume" and item.dimensions is not None:
        d = item.dimensions
        length = d.height if corr != "vessel_horizontal" else d.length
        length = length or d.height or d.length
        if d.diameter and length:
            size = math.pi / 4 * d.diameter**2 * length
            source = "list dimensions: pi/4 D^2 x overall height or length (ASSUMED upper bound)"
    if size is None:
        line.status = "not covered"
        line.notes = f"no {row['attribute']} ({row['unit']})"
        findings.append(
            _finding(
                "warning",
                "estimate-equipment-uncovered",
                f"{tag}: the {row['title']} correlation needs its {row['attribute']} "
                f"({row['unit']}), which neither its datasheet nor the cost basis gives",
                tag,
                f"give {' or '.join(SIZE_KEYS[row['attribute']])} in its datasheet "
                "(type_specific) or size with size_source in estimate/cost-basis.yaml",
            )
        )
        return
    line.size, line.size_source = round(size, 3), source
    if not row["min"] - 1e-9 <= size <= row["max"] + 1e-9:
        line.status = "not covered"
        line.notes = (
            f"{row['attribute']} {size:.3g} {row['unit']} outside {row['min']:g}..{row['max']:g}"
        )
        findings.append(
            _finding(
                "warning",
                "estimate-equipment-range",
                f"{tag}: {row['attribute']} {size:.3g} {row['unit']} is outside the "
                f"{row['title']} correlation's range {row['min']:g} to {row['max']:g} "
                f"{row['unit']}; not extrapolated",
                tag,
                "split it into units within the range (and say so), or give its cost from a "
                "quotation in estimate/cost-basis.yaml",
            )
        )
        return
    cp0 = purchased_cost(corr, size)
    line.cp0_base = cp0
    line.index_ratio = ratio
    line.purchased = cp0 * (ratio or 1.0)
    fbm, problem = _module_factor(line, item, mine, corr, data, notes)
    if fbm is None:
        line.status = "purchased only"
        line.notes = "; ".join([*notes, problem])
        findings.append(
            _finding(
                "warning",
                "estimate-equipment-partial",
                f"{tag}: purchased cost only, no bare module cost: {problem}",
                tag,
                "give fm, fp or fbm with factor_source in estimate/cost-basis.yaml (from the "
                "printed source for its material and pressure), or its cost from a quotation",
            )
        )
        return
    line.fbm = fbm
    line.cbm_base = cp0 * fbm
    line.bare_module = line.cbm_base * (ratio or 1.0)
    line.status = "bare module"
    line.notes = "; ".join(notes)


def _module_factor(
    line: CostLine, item: Any, mine: Any, corr: str, data: dict[str, Any], notes: list[str]
) -> tuple[float | None, str]:
    """FBM of the item and the notes on how; None and why when a factor is missing."""
    if mine is not None and mine.fbm is not None:
        notes.append(f"FBM from {mine.factor_source}")
        return mine.fbm, ""
    module = data.get("bare_module", {}).get(corr)
    if module is None:
        return None, "the package data has no bare module factor for this correlation"
    material = material_of(item.material)
    if "FBM" in module:
        if mine is not None and mine.fm is not None:
            return None, "this correlation takes FBM directly: give fbm"
        kind, why = _kind(item.type, module.get("kinds"))
        if kind is None:
            return None, why
        if material is None or material not in module["FBM"]:
            return None, f"material {item.material!r} is not CS or SS only"
        notes.append(f"FBM {material}{why} ({module['table']})")
        return float(module["FBM"][material]), ""
    b1, b2 = module["B"]
    if mine is not None and mine.fm is not None:
        fm = mine.fm
        notes.append(f"Fm from {mine.factor_source}")
    else:
        table = data.get("material", {}).get(corr, {})
        if material is None or material not in table:
            return None, f"no material factor for {item.material!r} (only CS or SS)"
        fm = float(table[material])
        notes.append(f"Fm {material}")
    if mine is not None and mine.fp is not None:
        fp = mine.fp
        notes.append(f"Fp from {mine.factor_source}")
    else:
        fp, why = _fp(item, corr, data)
        if fp is None:
            return None, why
    line.fm, line.fp = round(fm, 4), round(fp, 4)
    return b1 + b2 * fm * fp, ""


#: Words of a DEXPI class that name a machine kind other than the one a factor is for.
OTHER_KINDS = ("axial", "reciprocating", "piston", "diaphragm", "rotary", "screw")


def _kind(type_: str | None, kinds: list[str] | None) -> tuple[str | None, str]:
    """The kind a bare module factor applies to (``kinds`` of the package row), from the
    item's class: the class names it (no note), or names no kind (``ASSUMED``, the note); or
    None and why when the class names another kind, whose factor the package does not hold."""
    if not kinds:
        return "", ""
    t = (type_ or "").lower()
    for kind in kinds:
        if kind in t:
            return kind, f" {kind}"
    other = next((w for w in OTHER_KINDS if w in t), None)
    if other is not None:
        return None, (
            f"the package's FBM is for a {' or '.join(kinds)} machine only, not {other} ({type_})"
        )
    return kinds[0], f" (ASSUMED {kinds[0]}: the class names no kind)"


def _fp(item: Any, corr: str, data: dict[str, Any]) -> tuple[float | None, str]:
    p = item.design_pressure_barg
    row = data.get("pressure", {}).get(corr)
    if p is None:
        return None, "no design_pressure_barg in the equipment list"
    if row is None:
        return None, "the package data has no pressure factor for this correlation"
    if row.get("vessel"):
        d = item.dimensions.diameter if item.dimensions is not None else None
        if d is None:
            return None, "a vessel's pressure factor needs its diameter (dimensions)"
        if p < -0.5:
            return None, "vacuum design (below -0.5 barg): give fp"
        return vessel_pressure_factor(p, d), ""
    low, high = row["range"]
    if p < low:
        return 1.0, ""
    if p > high:
        return None, f"design pressure {p:g} barg above the factor's range {low:g}..{high:g}"
    return pressure_factor(row["C"], p), ""


# -- formatting ---------------------------------------------------------------------------------


def cost_csv(result: EquipmentEstimate) -> str:
    buffer = io.StringIO()
    writer = csv.DictWriter(buffer, fieldnames=list(COLUMNS), lineterminator="\n")
    writer.writeheader()
    writer.writerows(line.row() for line in result.lines)
    return buffer.getvalue()


def cost_markdown(result: EquipmentEstimate) -> str:
    data = capcost()
    t = result.totals()
    low, high = AACE_RANGES[result.estimate_class]
    index = result.index
    escalation = (
        f"escalated by the project's index {index['value']:g} ({index['year']}"
        + (f", {index['month']}" if index.get("month") else "")
        + f"; {index['source']}) / {result.base_cepci:g}"
        if index
        else f"NOT escalated: no cost index given, costs at CEPCI {result.base_cepci:g} "
        f"({result.base_year})"
    )
    lines = [
        "# Equipment estimate (published correlations)",
        "",
        f"Generated by `cheme assess equipment` from `{EQUIPMENT_FILE}`, the datasheets and "
        f"`{BASIS_FILE}`. Purchased and bare module costs from {data['source']} "
        f"(package data `domains/assessment/data/turton-capcost.yaml`, every row with its "
        f"table and cross-check), in {result.currency}, {escalation}.",
        "",
        f"**Estimate class {result.estimate_class}** ({AACE}): expected accuracy range "
        f"{low} low, {high} high. It covers the items costed below and nothing else: the "
        "bare module cost includes each item's installation (materials and labour) and "
        "indirect costs, so the bulk factor estimate of the take-off is not added on top for "
        "the same scope; site development, buildings, contingency and fees are not included.",
        "",
        "## Summary",
        "",
        f"| | {result.currency} |",
        "|---|---:|",
        f"| purchased equipment (correlation items) | {t['purchased']:.0f} |",
        f"| bare module (items with all factors) | {t['bare_module']:.0f} |",
        "",
        f"Items: {t['items']}; bare module {t['bare_module_items']}, purchased cost only "
        f"{t['purchased_only']}, the project's own cost {t['own_cost']}, excluded "
        f"{t['excluded']}, not covered {t['not_covered']}, in another currency (not in the "
        f"totals) {t['own_currency']}.",
        "",
        "## Items",
        "",
        "| item | type | correlation | A | unit | A from | Cp0 base | Fp | Fm | FBM | purchased "
        "| bare module | status | notes |",
        "|---|---|---|---:|---|---|---:|---:|---:|---:|---:|---:|---|---|",
    ]
    for line in result.lines:
        r = line.row()
        lines.append(
            f"| {r['tag']} | {r['type']} | {r['correlation']} | {r['size']} | {r['unit']} | "
            f"{r['size_source']} | {r['cp0_base']} | {r['fp']} | {r['fm']} | {r['fbm']} | "
            f"{r['purchased']} | {r['bare_module']} | {r['status']} | {r['notes']} |"
        )
    if result.own_costs:
        lines += ["", "## The project's own costs (not converted)", ""]
        for own in result.own_costs:
            lines.append(
                f"- {own['tag']}: {own['cost']:g} {own['currency']} {own['year']} "
                f"({own['status'] or 'status not given'}), {own['source']}"
            )
    if result.findings:
        lines += ["", "## Findings", ""] + [f"- {f.format()}" for f in result.findings]
    return "\n".join(lines) + "\n"


# -- the Python entry point ---------------------------------------------------------------------


def load_basis(text: str | None) -> tuple[CostBasis | None, list[Finding]]:
    if text is None:
        return None, []
    try:
        return CostBasis.model_validate(yaml.safe_load(text) or {}), []
    except (ValidationError, yaml.YAMLError) as failure:
        first = str(failure).splitlines()
        return None, [
            Finding(
                BASIS_FILE,
                "error",
                "cheme.estimate-cost-basis",
                f"{BASIS_FILE} does not load: {' '.join(first[:3])}",
                hint="cheme validate names the line",
            )
        ]


def catalyst_fills(
    root: Path, sheets: dict[str, Any], index: dict[str, Any] | None
) -> tuple[list[CostLine], list[Finding]]:
    """:func:`catalyst_fills_of` the process of the plant repository at *root* (none: no
    lines)."""
    from chemeascode.domains.process.model import has_process, load

    if not has_process(root):
        return [], []
    process, _ = load(root)
    return catalyst_fills_of(process, sheets, index)


#: The process files the catalyst fill lines are computed from (with the datasheets).
CATALYST_INPUTS = ("process/flowsheet.yaml", "process/catalysts.yaml")


def catalyst_fills_of(
    process: Any, sheets: dict[str, Any], index: dict[str, Any] | None
) -> tuple[list[CostLine], list[Finding]]:
    """The first catalyst fill of each reactor with a datasheet catalyst mass (or volume): one
    line ``<TAG>/catalyst`` priced from the catalyst its linked step names in
    ``process/catalysts.yaml`` (no installation factor: purchased = bare module). A price in
    another currency than USD, or of another year than the cost index, is not converted or
    escalated (a note says so); one in another currency is in no total (its line keeps the cost
    in that currency, and a warning says so)."""
    if process is None or process.catalysts is None:
        return [], []
    catalysts = process.catalysts.by_id()
    lines: list[CostLine] = []
    found: list[Finding] = []
    for tag, sheet in sheets.items():
        mass, mass_source = datasheet_size(sheet, "catalyst_mass")
        volume, volume_source = datasheet_size(sheet, "catalyst_volume")
        if mass is None and volume is None:
            continue
        names = {
            process.nodes[n].catalyst
            for n in process.nodes
            if getattr(process.nodes[n], "catalyst", None)
            and any(lk.target == "equipment" and lk.ref == tag for lk in process.nodes[n].links)
        }
        line = CostLine(f"{tag}/catalyst", "catalyst fill")
        lines.append(line)
        if len(names) != 1:
            line.status = "not covered"
            line.notes = (
                "no step linked to the item names a catalyst"
                if not names
                else "several catalysts: " + ", ".join(sorted(names))
            )
            continue
        name = names.pop()
        catalyst = catalysts.get(name)
        price = catalyst.price if catalyst is not None else None
        if price is None:
            line.status = "not covered"
            line.notes = f"catalyst {name} has no price in process/catalysts.yaml"
            found.append(
                _finding(
                    "info",
                    "estimate-catalyst-price",
                    f"{tag}: catalyst {name} has no price; its fill is not costed",
                    tag,
                    "give price: {value, unit, year, provenance, source} in process/catalysts.yaml",
                    "process/catalysts.yaml",
                )
            )
            continue
        per_kg = price.unit.endswith("/kg")
        size, unit, source = (mass, "kg", mass_source) if per_kg else (volume, "m3", volume_source)
        if size is None:
            line.status = "not covered"
            line.notes = (
                f"the price is per {'kg' if per_kg else 'm3'}; the datasheet gives no {unit}"
            )
            continue
        currency = price.unit.split("/")[0]
        line.size, line.unit, line.size_source = size, unit, source
        line.purchased = line.bare_module = size * price.value
        line.price_year = price.year
        notes = [
            f"{price.value:g} {price.unit} ({price.year}, {price.provenance}"
            + (f": {price.source}" if price.source else "")
            + ")",
            "initial fill, no installation factor",
        ]
        if currency != "USD":
            notes.append(f"in {currency}, not converted: not in the USD totals")
            line.own_cost, line.currency = line.purchased, currency
            line.purchased = line.bare_module = None
            line.status = f"own currency {currency}"
            found.append(
                _finding(
                    "warning",
                    "estimate-catalyst-currency",
                    f"{tag}: catalyst {name} is priced in {currency}; its first fill "
                    f"({line.own_cost:.0f} {currency}) is not converted and not in the USD "
                    "totals",
                    tag,
                    "price it in USD/kg or USD/m3 in process/catalysts.yaml; a TEA in "
                    f"{currency} of the price's year counts it as it is",
                    "process/catalysts.yaml",
                )
            )
        else:
            line.status = "catalyst price"
            if index is None or int(index.get("year", 0)) != price.year:
                notes.append(f"a {price.year} price, not escalated")
        line.notes = "; ".join(notes)
    return lines, found


def equipment_estimate(root: Path) -> EquipmentEstimate:
    """The equipment estimate of the plant repository at *root*."""
    from chemeascode.domains.equipment.datasheets import datasheet_paths, load
    from chemeascode.foundation.workspace import Workspace

    workspace = Workspace(Path(root))
    equipment = workspace.parsed_lists(("equipment",)).get("equipment")
    path = workspace.root / BASIS_FILE
    basis, problems = load_basis(path.read_text(encoding="utf-8") if path.is_file() else None)
    sheets = {}
    for sheet_path in datasheet_paths(workspace):
        loaded = load(workspace, sheet_path)
        if loaded.sheet is not None:
            sheets[loaded.sheet.tag.strip()] = loaded.sheet
    result = estimate_equipment(equipment, sheets, basis)
    lines, found = catalyst_fills(workspace.root, sheets, result.index)
    result.lines += lines
    result.findings += found
    if equipment is None:
        result.findings.insert(
            0,
            Finding(
                EQUIPMENT_FILE,
                "error",
                "cheme.estimate-no-equipment",
                f"no valid {EQUIPMENT_FILE}: nothing to cost",
                hint="cheme validate names the problem",
            ),
        )
    result.findings = problems + result.findings
    inputs = [
        EQUIPMENT_FILE,
        BASIS_FILE,
        *CATALYST_INPUTS,
        *(workspace.relative(p) for p in datasheet_paths(workspace)),
    ]
    result.source = source_revision(workspace.root, inputs)
    return result
