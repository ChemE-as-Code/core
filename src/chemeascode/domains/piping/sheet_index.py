"""Where things are in one P&ID file: source lines of objects, references and drawn texts."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from lxml import etree


def _id_lines(root: etree._Element) -> dict[str, int]:
    lines: dict[str, int] = {}
    for element in root.iter("Object"):
        element_id = element.get("id")
        if element_id is not None and element.sourceline is not None:
            lines.setdefault(element_id, element.sourceline)
    return lines


#: The units a hand-written label may spell a DEXPI unit (the last part of its enum) with.
_UNIT_SPELLINGS: dict[str, tuple[str, ...]] = {
    "Bar": ("bar", "barg", "bar(g)", "bara", "bar(a)"),
    "Millibar": ("mbar",),
    "Pascal": ("pa",),
    "Kilopascal": ("kpa",),
    "Megapascal": ("mpa",),
    "DegreeCelsius": ("°c", "degc", "grdc"),
    "Kelvin": ("k",),
    "Metre": ("m",),
    "Millimetre": ("mm",),
    "MetreSquared": ("m2", "m^2"),
    "MetreCubed": ("m3", "m^3"),
    "MetreCubedPerHour": ("m3/h", "m^3/h"),
    "KilogramPerHour": ("kg/h",),
    "Kilowatt": ("kw",),
    "ReciprocalMinute": ("1/min", "rpm", "min-1"),
}


def _drawn_for(text: etree._Element) -> str | None:
    """The id of the object the RepresentationGroup around *text* represents."""
    for holder in (text, *text.iterancestors("Object")):
        target = holder.find("References[@property='Represents']")
        if target is not None and target.get("objects"):
            return target.get("objects").split()[0].lstrip("#")
    return None


@dataclass
class SheetIndex:
    """Where things are in one P&ID file, for findings on the loaded model."""

    name: str
    #: Line of each ``<Object id=...>``.
    ids: dict[str, int]
    #: Line of each ``<References property=...>`` of an object, by (object id, property).
    references: dict[tuple[str, str], int]
    #: Line of the cached ``Text`` of each ``Core/Diagram.Text``, by (text, x, y).
    texts: dict[tuple[str, float, float], int]
    #: The title block (``domains.piping.sheets.TitleBlock``): MetaData, Model name/uri, diagram
    #: Name.
    title_block: Any = None

    def line(self, *objects: Any) -> int | None:
        """The line of the first of *objects* (model objects or ids) the file has an id for."""
        for obj in objects:
            key = obj if isinstance(obj, str) else getattr(obj, "id", None)
            if key in self.ids:
                return self.ids[key]
        return None


_POSITION = "Data[@property='Position']/AggregatedDataValue/Data[@property='{}']/*"


def _index(name: str, root: etree._Element) -> SheetIndex:
    references: dict[tuple[str, str], int] = {}
    texts: dict[tuple[str, float, float], int] = {}
    for element in root.iter("Object"):
        element_id = element.get("id")
        if element_id is not None:
            for reference in element.iterchildren("References"):
                where = (element_id, reference.get("property", ""))
                references.setdefault(where, reference.sourceline or 0)
        if element.get("type") != "Core/Diagram.Text":
            continue
        cached = element.find("Data[@property='Text']/String")
        x, y = element.find(_POSITION.format("X")), element.find(_POSITION.format("Y"))
        if cached is None or x is None or y is None:
            continue
        try:
            position = (round(float(x.text or ""), 6), round(float(y.text or ""), 6))
        except ValueError:
            continue
        texts.setdefault((cached.text or "", *position), cached.sourceline or 0)
    return SheetIndex(name, _id_lines(root), references, texts)
