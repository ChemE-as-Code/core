"""The Python authoring API for generator scripts: load a sheet, add items, save it.

Run a generator with ``cheme run scripts/draft_<sheet>.py pid/<sheet>.xml``. The builders
write the same XML ``cheme fragment`` prints (they call the same functions), insert it into
the loaded sheet and keep no other state: the file stays the only state, ``save()`` writes it
and formats it, ``cheme validate`` checks it.
"""

from __future__ import annotations

import math
import re
import warnings
from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import dataclass, field
from functools import wraps
from pathlib import Path
from typing import Any

from lxml import etree

from chemeascode.domains.piping.authoring._xml import (
    check_id,
    extent,
    fmt_num,
    point_xy,
    points_of,
    rotate,
    string,
)
from chemeascode.domains.piping.authoring.builders import (
    BUBBLE_SHAPES,
    OFFPAGE_SHAPES,
    equipment_fragment,
    instrument_fragment,
    note_fragment,
    offpage_fragment,
)
from chemeascode.domains.piping.authoring.fragment import (
    BRANCH,
    VALVE_SHAPES,
    Fragment,
    FragmentError,
    _label,
    _pipe,
    _segment,
    _SheetInfo,
    _symbol_at,
    _tee,
    _valve,
    dn_number,
    point_xy_of,
)
from chemeascode.domains.piping.show import Sheet as _Index
from chemeascode.domains.piping.show import ShowError, data_value, short_class

XY = tuple[float, float]


class AuthoringError(Exception):
    """The builder cannot do what was asked; the message says why."""


# -- route items --------------------------------------------------------------------------------


@dataclass(frozen=True)
class Port:
    """A place a pipe can attach: a node of an item, drawn at *xy*."""

    item: str
    node: str
    xy: XY

    def ref(self) -> str:
        return f"{self.item}:{self.node}"


@dataclass
class Valve:
    """An inline valve in a :func:`line` route. Without *at* it sits mid-leg."""

    id: str
    cls: str = "GlobeValve"
    at: XY | None = None
    tag: str | None = None
    dn: str | float | None = None


@dataclass
class Tee:
    """A tee in a :func:`line` route: the segment ends at it and the next one starts there.

    After the line is built, :attr:`branch` is the port a branch line starts (or ends) at.
    """

    id: str
    at: XY | None = None
    branch_side: str | None = None
    branch_dn: str | float | None = None
    tag: str | None = None
    branch: Port | None = field(default=None, init=False)


@dataclass
class OffPage:
    """An off-page connector as the first (``in``) or last (``out``) item of a route."""

    direction: str
    at: XY
    id: str | None = None
    note: str | None = None
    note_at: XY | None = None
    rotation: float | None = None


def valve(
    id: str,  # the XML attribute's name
    cls: str = "GlobeValve",
    *,
    at: XY | None = None,
    tag: str | None = None,
    dn: str | float | None = None,
) -> Valve:
    """An inline valve for a :func:`line` route (``fragment valve``)."""
    if cls not in VALVE_SHAPES:
        raise AuthoringError(f"valve class {cls!r}: one of {', '.join(VALVE_SHAPES)}")
    return Valve(check_id(id, "valve id"), cls, at, tag, dn)


def tee(
    id: str,
    *,
    at: XY | None = None,
    branch: str | None = None,
    branch_dn: str | float | None = None,
    tag: str | None = None,
) -> Tee:
    """A tee for a :func:`line` route (``fragment tee``); *branch*: up, down, left or right."""
    if branch is not None and branch not in BRANCH:
        raise AuthoringError(f"tee {id}: branch {branch!r}: one of {', '.join(BRANCH)}")
    return Tee(check_id(id, "tee id"), at, branch, branch_dn, tag)


def offpage(
    direction: str,
    *,
    at: XY,
    id: str | None = None,
    note: str | None = None,
    note_at: XY | None = None,
    rotation: float | None = None,
) -> OffPage:
    """An off-page connector to start (``in``) or end (``out``) a :func:`line` route."""
    if direction not in OFFPAGE_SHAPES:
        raise AuthoringError(f"off-page direction {direction!r}: in or out")
    return OffPage(direction, at, id, note, note_at, rotation)


@dataclass
class Nozzle:
    """A nozzle of :func:`equipment`: *at* is (dx, dy) from the equipment position, sheet mm."""

    name: str
    at: XY
    dn: str | float | None = None


@dataclass
class Marker:
    """A shape drawn on an :func:`equipment` symbol: a column's packed bed or tray.

    *dy* is sheet mm from the symbol centre along its axis (Y down, rotated with the symbol);
    *scale_y* is the marker's ScaleY (its ScaleX is the symbol's). ``"NAME:dy[:SY][:m]"``
    strings, as ``cheme fragment equipment --marker`` takes, work too.
    """

    shape: str
    dy: float
    scale_y: float = 1.0
    mirrored: bool = False


@dataclass
class Equipment:
    """What :func:`equipment` added: its id and a :class:`Port` per nozzle name."""

    id: str
    tag: str
    ports: dict[str, Port]

    def __getitem__(self, name: str) -> Port:
        try:
            return self.ports[name]
        except KeyError:
            raise AuthoringError(
                f"{self.tag} has no nozzle {name!r}; nozzles: {', '.join(self.ports) or 'none'}"
            ) from None


@dataclass
class Line:
    """What :func:`line` added: the system, its segments, label positions and any notes."""

    id: str
    number: str
    segments: list[str]
    route: list[XY]
    labels: dict[str, XY]
    notes: list[str] = field(default_factory=list)


# -- the sheet ----------------------------------------------------------------------------------


class _NotOnDisk(type(Path())):  # type: ignore[misc]
    """The sheet's path for messages; reading it fails, so labels take the cached text from the
    data in memory rather than from the file on disk."""

    def read_bytes(self) -> bytes:  # type: ignore[override]
        raise OSError("the sheet in memory is not written yet")


class _Info(_SheetInfo):
    """What the fragment kinds read from ``--sheet``, from the sheet in memory."""

    def __init__(self, sheet: Sheet):
        self.path = _NotOnDisk(sheet.path)
        self.sheet = sheet.index
        self.shapes = sheet.shapes
        self.positions = sheet.node_positions


_PLANT_ORDER = ("ActuatingSystems", "PipingNetworkSystems", "ProcessInstrumentationFunctions")


class Sheet:
    """A P&ID sheet loaded for authoring: the XML tree, its ids, shapes and node positions."""

    def __init__(self, path: Path, index: _Index):
        self.path = Path(path)
        self.index = index
        self.root = index.root
        self.shapes: dict[str, str] = {}
        self.node_positions: dict[str, str] = {}
        self.notes: list[str] = []
        for element in self.root.iter("Object"):
            self._learn(element)
        self.plant = self.root.find(".//Object[@type='Plant/PlantModel']")
        self.diagram = self.root.find(".//Object[@type='Core/Diagram.Diagram']")
        self.catalogue = self.root.find(".//Object[@type='Core/Diagram.ShapeCatalogue']")
        if self.plant is None or self.diagram is None:
            raise AuthoringError(
                f"{path}: no PlantModel or Diagram; start from the empty sheet "
                "(.claude/skills/dexpi-xml/snippets/empty-sheet.xml)"
            )

    @classmethod
    def load(cls, path: str | Path) -> Sheet:
        """Load *path* (e.g. the empty sheet a generator starts from)."""
        path = Path(path)
        try:
            return cls(path, _Index.load(path, str(path)))
        except (ShowError, OSError) as failure:
            raise AuthoringError(str(failure)) from failure

    def save(self, path: str | Path | None = None, *, fmt: bool = True) -> Path:
        """Write the sheet (to *path*, default where it was loaded from) and format it.

        The sheet is formatted in memory first: if pyDEXPI refuses it, *path* is left as it was
        and the refused output is kept as ``<path stem>.refused.xml`` to look at. XML comments
        and processing instructions do not survive formatting: each one dropped is a warning
        (``UserWarning``) and a note in :attr:`notes`. cheme-as-code's own ``<!-- cheme-... -->``
        provenance comments are kept (:data:`~chemeascode.domains.piping.fmt.PROVENANCE_PREFIX`).
        """
        from chemeascode.domains.piping.fmt import (
            FormatRefused,
            dropped_markup,
            dropped_note,
            format_bytes,
        )

        target = Path(path) if path is not None else self.path
        target.parent.mkdir(parents=True, exist_ok=True)
        etree.indent(self.root, space="  ")
        # the whole document: comments before the root (provenance) are siblings of it
        data = etree.tostring(self.root.getroottree(), xml_declaration=True, encoding="UTF-8")
        if fmt:
            try:
                data, _ = format_bytes(data)
            except FormatRefused as refusal:
                refused = target.with_name(f"{target.stem}.refused.xml")
                refused.write_bytes(data)
                raise AuthoringError(
                    f"{target}: not written, pyDEXPI refuses the result: {refusal}; the "
                    f"refused output is in {refused}"
                ) from refusal
            dropped = dropped_markup(self.root)  # lines as in the file loaded
            if dropped:
                note = f"{target}: cheme fmt {dropped_note(dropped)}"
                self.notes.append(note)
                warnings.warn(note, stacklevel=2)
        target.write_bytes(data)
        return target

    # -- what is on the sheet -------------------------------------------------------------------

    def _learn(self, element: etree._Element) -> None:
        kind = element.get("type")
        object_id = element.get("id")
        if kind == "Core/Diagram.Shape" and object_id:
            name = data_value(element, "Name")
            if name:
                self.shapes.setdefault(name, object_id)
        elif kind == "Plant/Diagram.PipingNodePosition" and object_id:
            node = element.find("References[@property='Node']")
            if node is not None and node.get("objects", "").split():
                self.node_positions.setdefault(
                    node.get("objects").split()[0].lstrip("#"), object_id
                )

    def _index_tree(self, element: etree._Element) -> None:
        for child in element.iter():
            if not isinstance(child.tag, str):
                continue
            if child.tag == "Object":
                if child.get("id"):
                    self.index.by_id.setdefault(child.get("id"), child)
                self._learn(child)
            elif child.tag == "References":
                prop = child.get("property", "")
                for target in child.get("objects", "").split():
                    target = target.lstrip("#")
                    if prop == "Represents":
                        self.index.drawings.setdefault(target, []).append(child.getparent())
                    else:
                        self.index.incoming.setdefault(target, []).append((child, prop))

    def has(self, object_id: str) -> bool:
        return object_id in self.index.by_id

    def find(self, object_id: str) -> etree._Element:
        element = self.index.by_id.get(object_id)
        if element is None:
            raise AuthoringError(f"{self.path}: no object {object_id}")
        return element

    def shape(self, name: str) -> str:
        """The catalogue id of shape *name* (``CENTRIFUGAL_PUMP_SHAPE``) or the id itself."""
        if name in self.shapes:
            return self.shapes[name]
        element = self.index.by_id.get(name)
        if element is not None and element.get("type") == "Core/Diagram.Shape":
            return name
        known = ", ".join(sorted(self.shapes)) or "none"
        raise AuthoringError(
            f"{self.path}: no shape {name!r} in the ShapeCatalogue; shapes: {known}"
        )

    def use_shape(self, name: str) -> str:
        """Like :meth:`shape`, but adds a missing shape from the template's catalogue.

        *name* may be lower case (``column-tray``); a sheet made from an older template then
        gets e.g. ``COLUMN_TRAY_SHAPE`` copied into its ShapeCatalogue on first use.
        """
        import copy as _copy

        from chemeascode.domains.piping.authoring.shapes import catalogue, normalise_name

        try:
            return self.shape(name)
        except AuthoringError:
            if not re.fullmatch(r"[A-Za-z0-9_\- ]+", name):
                raise
            normalised = normalise_name(name)
            if normalised in self.shapes:
                return self.shapes[normalised]
            template = catalogue().get(normalised)
            if template is None or template.get("id") in self.index.by_id:
                raise
            self.add_shape(_copy.deepcopy(template))
            return template.get("id")

    def shape_extent(self, shape_id: str) -> tuple[float, float, float, float] | None:
        element = self.index.by_id.get(shape_id)
        return extent(element) if element is not None else None

    def position(self, node_id: str) -> XY | None:
        """Where node *node_id* is drawn (its PipingNodePosition), or None."""
        position = self.index.by_id.get(self.node_positions.get(node_id, ""))
        if position is None:
            return None
        value = position.find("Data[@property='Position']/AggregatedDataValue")
        return point_xy(value) if value is not None else None

    def text_boxes(self) -> list[tuple[float, float, float, float]]:
        """Approximate boxes of the texts drawn on the sheet (not the title block or border)."""
        boxes = []
        for text in self.diagram.iter("Object"):
            if text.get("type") != "Core/Diagram.Text":
                continue
            if any(
                a.get("type") in ("Core/Diagram.Border", "Core/Diagram.Label")
                for a in text.iterancestors("Object")
            ):
                continue
            value = text.find("Data[@property='Position']/AggregatedDataValue")
            xy = point_xy(value) if value is not None else None
            if xy is None:
                continue
            try:
                size = float(text.findtext("Data[@property='Size']/Double") or 2.5)
            except ValueError:
                size = 2.5
            content = text.findtext("Data[@property='Text']/String") or ""
            x0, y0, x1, y1 = text_box(content, xy, size)
            reference = text.find("Data[@property='Alignment']/DataReference")
            align = reference.get("data", "") if reference is not None else ""
            shift = (x1 - x0) / 2
            if ".Left" in align:
                x0, x1 = x0 + shift, x1 + shift
            elif ".Right" in align:
                x0, x1 = x0 - shift, x1 - shift
            boxes.append((x0, y0, x1, y1))
        return boxes

    def _drawn(self) -> Iterator[etree._Element]:
        """The objects drawn on the sheet, outside the border (title block) and labels."""
        for element in self.diagram.iter("Object"):
            if any(
                a.get("type") in ("Core/Diagram.Border", "Core/Diagram.Label")
                for a in element.iterancestors("Object")
            ):
                continue
            yield element

    def symbol_boxes(self) -> list[tuple[float, float, float, float]]:
        """Boxes (sheet mm) of the symbols drawn on the sheet: each ShapeUsage's catalogue
        shape, scaled, rotated and moved to its position."""
        boxes = []
        for usage in self._drawn():
            if usage.get("type") != "Core/Diagram.ShapeUsage":
                continue
            reference = usage.find("References[@property='Shape']")
            shape_id = (reference.get("objects", "") if reference is not None else "").split()
            at = point_xy_of(usage)
            local = self.shape_extent(shape_id[0].lstrip("#")) if shape_id else None
            if at is None or local is None:
                continue

            def number(prop: str, default: float, usage: etree._Element = usage) -> float:
                try:
                    return float(usage.findtext(f"Data[@property='{prop}']/Double") or default)
                except ValueError:
                    return default

            sx, sy, turn = number("ScaleX", 1.0), number("ScaleY", 1.0), number("Rotation", 0.0)
            x0, y0, x1, y1 = local
            corners = [
                rotate(x * sx, y * sy, turn) for x, y in ((x0, y0), (x1, y0), (x1, y1), (x0, y1))
            ]
            xs = [at[0] + c[0] for c in corners]
            ys = [at[1] + c[1] for c in corners]
            boxes.append((min(xs), min(ys), max(xs), max(ys)))
        return boxes

    def line_paths(self) -> list[list[XY]]:
        """The polylines drawn on the sheet: pipes (ConnectorLines, through their node
        positions and inner points) and other lines (PolyLines: measuring, signal lines)."""
        paths: list[list[XY]] = []
        for element in self._drawn():
            kind = element.get("type")
            if kind == "Core/Diagram.ConnectorLine":
                ends = []
                for prop in ("Source", "Target"):
                    reference = element.find(f"References[@property='{prop}']")
                    target = (reference.get("objects", "") if reference is not None else "").split()
                    position = self.index.by_id.get(target[0].lstrip("#")) if target else None
                    ends.append(point_xy_of(position) if position is not None else None)
                inner = element.find("Data[@property='InnerPoints']")
                middle = [] if inner is None else [p for p in map(point_xy, points_of(inner)) if p]
                if ends[0] is not None and ends[1] is not None:
                    paths.append([ends[0], *middle, ends[1]])
            elif kind == "Core/Diagram.PolyLine":
                path = [p for p in map(point_xy, points_of(element)) if p is not None]
                if len(path) > 1:
                    paths.append(path)
        return paths

    def symbol_at(self, object_id: str) -> XY | None:
        """Where the symbol of *object_id* is drawn (its own ShapeUsage), or None."""
        for drawing in self.index.drawings.get(object_id, []):
            found = _symbol_at(drawing)
            if found:
                return found
        return None

    def port(self, key: str | Port, node: str | None = None) -> Port:
        """A pipe end: a nozzle id (its node), ``ITEM:NODE``, or an item and one of its nodes."""
        if isinstance(key, Port):
            return key
        if node is None and ":" in key:
            key, node = key.split(":", 1)
        item = self.find(key)
        if node is None:
            nodes = [n for n in item.iter("Object") if n.get("type") == "Plant/Piping.PipingNode"]
            if short_class(item) == "PipingNode":
                owner = next(
                    (a for a in item.iterancestors("Object") if short_class(a) != "PipingNode"),
                    None,
                )
                if owner is None or not owner.get("id"):
                    raise AuthoringError(f"{key}: a node without an identified owner")
                item, nodes = owner, [item]
            if len(nodes) != 1:
                raise AuthoringError(
                    f"{key} has {len(nodes)} nodes: name one, e.g. {key}:{nodes[0].get('id')}"
                    if nodes
                    else f"{key} has no PipingNode"
                )
            node = nodes[0].get("id")
        node_element = self.find(node)
        if item not in node_element.iterancestors():
            raise AuthoringError(f"{node} is not a node of {item.get('id')}")
        xy = self.position(node)
        if xy is None:
            raise AuthoringError(f"{node} has no PipingNodePosition on {self.path}: draw it")
        return Port(item.get("id"), node, xy)

    # -- inserting ------------------------------------------------------------------------------

    @contextmanager
    def atomic(self) -> Iterator[None]:
        """Undo everything added inside the block when it raises: a builder that fails halfway
        leaves the sheet (tree, ids, shapes, node positions, notes) as it was, so a corrected
        retry with the same ids works."""
        index = self.index
        saved = (
            dict(index.by_id),
            {k: list(v) for k, v in index.incoming.items()},
            {k: list(v) for k, v in index.drawings.items()},
            dict(self.shapes),
            dict(self.node_positions),
            list(self.notes),
        )
        owners = [o for o in (self.plant, self.diagram, self.catalogue) if o is not None]
        children = {id(o): list(o) for o in owners}
        grandchildren = {id(c): list(c) for o in owners for c in o if c.tag == "Components"}
        try:
            yield
        except BaseException:
            for owner in owners:
                kept = {id(c) for c in children[id(owner)]}
                for child in list(owner):
                    if id(child) not in kept:
                        owner.remove(child)
                    elif id(child) in grandchildren:
                        old = {id(g) for g in grandchildren[id(child)]}
                        for grandchild in list(child):
                            if id(grandchild) not in old:
                                child.remove(grandchild)
            (by_id, incoming, drawings, shapes, positions, notes) = saved
            index.by_id.clear()
            index.by_id.update(by_id)
            index.incoming.clear()
            index.incoming.update(incoming)
            index.drawings.clear()
            index.drawings.update(drawings)
            for mine, before in (
                (self.shapes, shapes),
                (self.node_positions, positions),
            ):
                mine.clear()
                mine.update(before)
            self.notes[:] = notes
            raise

    def _container(self, owner: etree._Element, prop: str) -> etree._Element:
        found = owner.find(f"Components[@property='{prop}']")
        if found is None:
            found = etree.SubElement(owner, "Components", property=prop)
        return found

    def check_new(self, *elements: etree._Element) -> None:
        """Refuse elements whose ids exist on the sheet (or twice among them)."""
        seen: set[str] = set()
        for element in elements:
            for child in element.iter("Object"):
                object_id = child.get("id")
                if not object_id:
                    continue
                if object_id in self.index.by_id or object_id in seen:
                    raise AuthoringError(
                        f"{self.path}: id {object_id} exists already; choose another id"
                    )
                seen.add(object_id)

    def add_conceptual(self, prop: str, element: etree._Element) -> None:
        """Put a plant object into ``<Components property=prop>`` of the PlantModel."""
        self.check_new(element)
        self._container(self.plant, prop).append(element)
        self._index_tree(element)

    def add_drawing(self, element: etree._Element) -> None:
        """Put a drawing (RepresentationGroup, Static) into the Diagram's Groups."""
        self.check_new(element)
        self._container(self.diagram, "Groups").append(element)
        self._index_tree(element)

    def add_shape(self, element: etree._Element) -> None:
        if self.catalogue is None:
            raise AuthoringError(f"{self.path}: no ShapeCatalogue")
        self.check_new(element)
        self._container(self.catalogue, "Shapes").append(element)
        self._index_tree(element)

    def _info(self) -> _Info:
        return _Info(self)

    def _parts(self, made: Fragment) -> dict[str, list[etree._Element]]:
        """The parts of a fragment as elements: ``CONCEPTUAL``, ``DRAWING``, ``SHAPE``, ..."""
        parts: dict[str, list[etree._Element]] = {}
        for part in made.parts:
            if part.xml:
                parts.setdefault(part.title, []).append(etree.fromstring(part.xml))
        self.notes += made.notes
        return parts

    # -- builders as methods --------------------------------------------------------------------

    def equipment(self, *args: Any, **kwargs: Any) -> Equipment:
        return equipment(self, *args, **kwargs)

    def line(self, *args: Any, **kwargs: Any) -> Line:
        return line(self, *args, **kwargs)

    def instrument(self, *args: Any, **kwargs: Any) -> str:
        return instrument(self, *args, **kwargs)

    def note(self, *args: Any, **kwargs: Any) -> str:
        return note(self, *args, **kwargs)

    def label(self, *args: Any, **kwargs: Any) -> str:
        return label(self, *args, **kwargs)


# -- equipment, instruments, notes, labels ------------------------------------------------------


def _dn(value: str | float | None) -> str | None:
    if value is None:
        return None
    try:
        return dn_number(str(value))
    except FragmentError as failure:
        raise AuthoringError(str(failure)) from failure


def _ident(text: str, prefix: str = "") -> str:
    cleaned = re.sub(r"[^A-Za-z0-9_]", "", text)
    if not prefix and (not cleaned or not re.match(r"[A-Za-z_]", cleaned)):
        cleaned = f"_{cleaned}"
    return f"{prefix}{cleaned}"


def _atomic[F: Any](builder: F) -> F:
    """Run *builder* (whose first argument is the sheet) in :meth:`Sheet.atomic`."""

    @wraps(builder)
    def run(sheet: Sheet, *args: Any, **kwargs: Any) -> Any:
        with sheet.atomic():
            return builder(sheet, *args, **kwargs)

    return run  # type: ignore[return-value]


@_atomic
def equipment(
    sheet: Sheet,
    cls: str,
    tag: str,
    *,
    shape: str,
    at: XY,
    nozzles: list[Nozzle | tuple[Any, ...]] = (),  # type: ignore[assignment]
    id: str | None = None,
    rotation: float = 0.0,
    scale: float | tuple[float, float] = 1.0,
    label_at: XY | None = None,
    standard: str = "Din2448",
    markers: list[Marker | str | tuple[Any, ...]] = (),  # type: ignore[assignment]
) -> Equipment:
    """Add equipment *cls* (``CentrifugalPump``, ``Tank``, ...) tagged *tag*, drawn as *shape*.

    *nozzles*: :class:`Nozzle` or ``(name, (dx, dy), dn)`` tuples, offsets from *at*. Returns
    the nozzle ports for :func:`line` routes: ``pump["N1"]``.

    *scale*: one factor or ``(ScaleX, ScaleY)``, e.g. ``(1.0, 1.4)`` for a tall column.
    *markers*: :class:`Marker`, ``(shape, dy[, scale_y[, mirrored]])`` tuples or
    ``"NAME:dy[:SY][:m]"`` strings, drawn on the symbol (packed beds, trays). A shape missing
    from the sheet's catalogue is copied from the template's.
    """
    object_id = id or _ident(tag)
    shape_id = sheet.use_shape(shape)
    from chemeascode.domains.piping.authoring.fragment_items import _marker_spec

    marker_specs = []
    for marker in markers:
        if isinstance(marker, str):
            try:
                name, dy, marker_sy, mirrored = _marker_spec(marker)
            except FragmentError as failure:
                raise AuthoringError(str(failure).replace("--marker ", "marker ")) from failure
            marker = Marker(name, dy, marker_sy, mirrored)
        elif not isinstance(marker, Marker):
            marker = Marker(*marker)
        marker_specs.append(
            (
                sheet.use_shape(marker.shape),
                float(marker.dy),
                float(marker.scale_y),
                bool(marker.mirrored),
            )
        )
    specs = []
    for nozzle in nozzles:
        if not isinstance(nozzle, Nozzle):
            nozzle = Nozzle(*nozzle)
        specs.append((nozzle.name, (float(nozzle.at[0]), float(nozzle.at[1])), _dn(nozzle.dn)))
    try:
        made = equipment_fragment(
            object_id,
            cls,
            tag,
            shape_id,
            (float(at[0]), float(at[1])),
            specs,
            rotation=rotation,
            scale=scale,
            label_at=label_at,
            standard=standard,
            extent=sheet.shape_extent(shape_id),
            markers=marker_specs,
        )
    except (FragmentError, ValueError) as failure:
        raise AuthoringError(str(failure)) from failure
    parts = sheet._parts(made)
    sheet.check_new(*parts["CONCEPTUAL"], *parts["DRAWING"])
    sheet.add_conceptual("TaggedPlantItems", parts["CONCEPTUAL"][0])
    sheet.add_drawing(parts["DRAWING"][0])
    ports = {
        name: Port(f"{object_id}_{name}", f"{object_id}_{name}_Node", (at[0] + dx, at[1] + dy))
        for name, (dx, dy), _ in specs
    }
    return Equipment(object_id, tag, ports)


def _resolve_sensing(sheet: Sheet, sensing: Any) -> tuple[str | None, XY | None]:
    if sensing is None:
        return None, None
    if isinstance(sensing, Port):
        return sensing.item, sensing.xy
    if isinstance(sensing, Line):
        return sensing.segments[0], None
    from chemeascode.domains.piping.authoring.fragment_items import _is, _positions_in

    if isinstance(sensing, Equipment):
        sensing = sensing.id
    element = sheet.find(sensing)
    if short_class(element) == "PipingNetworkSystem":
        # A line id: the measuring point is on one of its segments.
        segment = next(
            (
                child.get("id")
                for child in element.iter("Object")
                if short_class(child) == "PipingNetworkSegment"
            ),
            None,
        )
        if segment is None:
            raise AuthoringError(f"sensing {sensing}: the line has no segment to measure on")
        return segment, None
    if not _is(element, "SensingLocation"):
        raise AuthoringError(
            f"sensing {sensing} is a {short_class(element)}, not a sensing location: use one of "
            "its nozzles (an instrument connection), a segment or an inline item"
        )
    xy = sheet.position(sensing) or sheet.symbol_at(sensing)
    if xy is None:
        # A nozzle given by id: its InstrumentationNodePosition (pasted from a fragment) or
        # the drawn position of its piping node.
        found = [
            point_xy_of(p) for d in sheet.index.drawings.get(sensing, []) for p in _positions_in(d)
        ]
        found += [
            sheet.position(node.get("id"))
            for node in element.iter("Object")
            if short_class(node) == "PipingNode" and node.get("id")
        ]
        xy = next((point for point in found if point), None)
    return sensing, xy


@_atomic
def instrument(
    sheet: Sheet,
    tag: str,
    *,
    at: XY,
    sensing: str | Port | Line | Equipment | None = None,
    sensing_at: XY | None = None,
    signal_to: str | Valve | None = None,
    signal_points: list[XY] | None = None,
    location: str = "central",
    fail_action: str | None = None,
    id: str | None = None,
) -> str:
    """Add instrument function *tag* (``PIC-4101``) with its bubble at *at*; returns its id.

    *sensing*: what it measures (an id, a nozzle port, a line, equipment); the measuring line
    starts at *sensing_at* (default: the port, node or symbol of *sensing*; a line needs it).
    *signal_to*: a valve (control loop or trip: actuating system, actuator symbol on the valve,
    dashed signal line) or another instrument function id (a cascade).
    """
    object_id = id or _ident(tag, "Inst_")
    sensing_id, default_at = _resolve_sensing(sheet, sensing)
    if sensing_id is not None and sensing_at is None and default_at is None:
        raise AuthoringError(
            f"{tag}: give sensing_at=(x, y), the point on {sensing_id} the measuring line starts"
        )
    options: dict[str, Any] = {}
    if signal_to is not None:
        target = signal_to.id if isinstance(signal_to, Valve) else signal_to
        element = sheet.find(target)
        if short_class(element) == "ProcessInstrumentationFunction":
            options = {"signal_function": target, "function_at": sheet.symbol_at(target)}
        elif short_class(element).endswith("Valve"):
            options = {
                "signal_valve": target,
                "valve_at": sheet.symbol_at(target),
                "valve_tag": data_value(element, "PipingComponentNumber"),
                "actuator_shape": sheet.shapes.get("CONTROLLED_ACTUATOR_SHAPE"),
            }
        else:
            raise AuthoringError(
                f"signal_to {target}: a valve or an instrument function, not a "
                f"{short_class(element)}"
            )
    bubble = BUBBLE_SHAPES.get(location)
    try:
        made = instrument_fragment(
            object_id,
            tag,
            (float(at[0]), float(at[1])),
            sensing=sensing_id,
            sensing_at=sensing_at or default_at,
            location=location,
            bubble_shape=sheet.shapes.get(bubble[0]) if bubble else None,
            signal_points=signal_points,
            fail_action=fail_action,
            **options,
        )
    except (FragmentError, ValueError) as failure:
        raise AuthoringError(str(failure)) from failure
    parts = sheet._parts(made)
    sheet.check_new(*(e for elements in parts.values() for e in elements))
    sheet.add_conceptual("ProcessInstrumentationFunctions", parts["CONCEPTUAL"][0])
    sheet.add_drawing(parts["DRAWING"][0])
    for system in parts.get("SYSTEM", []):
        sheet.add_conceptual("ActuatingSystems", system)
    for drawing in parts.get("SYSTEM DRAWING", []):
        sheet.add_drawing(drawing)
    return object_id


@_atomic
def note(
    sheet: Sheet,
    text: str,
    *,
    at: XY,
    size: float = 2.5,
    align: str = "LeftCenter",
    id: str | None = None,
) -> str:
    """Add free text owned by no object (a remark, a trip description); returns its id."""
    object_id = id or _free_id(sheet, "Note")
    made = note_fragment(object_id, text, (float(at[0]), float(at[1])), size=size, align=align)
    sheet.add_drawing(sheet._parts(made)["DRAWING"][0])
    return object_id


def _free_id(sheet: Sheet, stem: str) -> str:
    n = 1
    while sheet.has(f"{stem}{n}"):
        n += 1
    return f"{stem}{n}"


@_atomic
def label(
    sheet: Sheet,
    for_id: str,
    attribute: str,
    *,
    at: XY | None = None,
    id: str | None = None,
) -> str:
    """Add a label showing *attribute* of *for_id* (``fragment label``) to its drawing."""
    sheet.find(for_id)
    label_id = id or f"{for_id}_{attribute}Label"
    try:
        made = _label(
            label_id,
            for_id,
            attribute,
            f"{at[0]},{at[1]}" if at is not None else None,
            sheet._info(),
        )
    except (FragmentError, ValueError) as failure:
        raise AuthoringError(str(failure)) from failure
    drawing = sheet._parts(made)["DRAWING"][0]
    owners = sheet.index.drawings.get(for_id, [])
    sheet.check_new(drawing)
    if owners:
        sheet._container(owners[0], "Groups").append(drawing)
        sheet._index_tree(drawing)
    else:
        sheet.add_drawing(drawing)
    return label_id


# -- lines --------------------------------------------------------------------------------------


def _angle(a: XY, b: XY) -> float:
    return math.degrees(math.atan2(b[1] - a[1], b[0] - a[0])) % 360


def _on_leg(p: XY, a: XY, b: XY, tolerance: float = 0.05) -> bool:
    length = math.dist(a, b)
    if length == 0:
        return False
    cross = abs((b[0] - a[0]) * (p[1] - a[1]) - (b[1] - a[1]) * (p[0] - a[0])) / length
    along = ((p[0] - a[0]) * (b[0] - a[0]) + (p[1] - a[1]) * (b[1] - a[1])) / length
    return cross <= tolerance and 0 < along < length


def text_box(text: str, at: XY, size: float) -> tuple[float, float, float, float]:
    """A generous box around a CenterCenter text: 0.62 x size per character, 1.2 x size high."""
    width, height = 0.62 * size * max(len(text), 1), 1.2 * size
    return (at[0] - width / 2, at[1] - height / 2, at[0] + width / 2, at[1] + height / 2)


def segment_hits_box(a: XY, b: XY, box: tuple[float, float, float, float]) -> bool:
    """Whether the straight segment a-b passes through *box* (Liang-Barsky clipping)."""
    x0, y0, x1, y1 = box
    dx, dy = b[0] - a[0], b[1] - a[1]
    low, high = 0.0, 1.0
    for p, q in ((-dx, a[0] - x0), (dx, x1 - a[0]), (-dy, a[1] - y0), (dy, y1 - a[1])):
        if p == 0:
            if q < 0:
                return False
            continue
        t = q / p
        if p < 0:
            low = max(low, t)
        else:
            high = min(high, t)
        if low > high:
            return False
    return True


LABEL_SIZE = 3.0
LABEL_GAP = 1.5


def _overlaps(a: tuple[float, ...], b: tuple[float, ...]) -> bool:
    return a[0] < b[2] and b[0] < a[2] and a[1] < b[3] and b[1] < a[3]


def place_line_labels(
    route: list[XY],
    texts: list[str],
    size: float = LABEL_SIZE,
    obstacles: list[tuple[float, float, float, float]] | None = None,
    lines: list[list[XY]] | None = None,
    symbols: list[tuple[float, float, float, float]] | None = None,
) -> tuple[list[XY], bool]:
    """Positions for *texts* (stacked) next to a leg of *route*, never on the route.

    Tries both sides of every leg, longest first, preferring a place that also keeps clear of
    *obstacles* (boxes of texts already on the sheet), *symbols* (boxes of equipment, valve and
    other symbols) and *lines* (other polylines: pipes, signal lines); failing that, one clear
    of the symbols and lines only. Returns the positions and whether they are clear of the
    route (False: the first try, which touches it).
    """
    legs = [(route[i], route[i + 1]) for i in range(len(route) - 1)]
    legs = [leg for leg in legs if math.dist(*leg) > 0]
    order = sorted(legs, key=lambda leg: -math.dist(*leg))
    step = size * 1.2 + 0.4
    widths = [0.62 * size * max(len(t), 1) for t in texts]
    stack = step * len(texts)
    candidates: list[list[XY]] = []
    for a, b in order:
        mx, my = (a[0] + b[0]) / 2, (a[1] + b[1]) / 2
        horizontal = abs(b[0] - a[0]) >= abs(b[1] - a[1])
        for offset in (0.0, -0.25, 0.25):
            cx = mx + offset * (b[0] - a[0])
            cy = my + offset * (b[1] - a[1])
            if horizontal:
                n = len(texts)
                above = [(cx, cy - LABEL_GAP - step * (n - i - 0.5)) for i in range(n)]
                below = [(cx, cy + LABEL_GAP + step * (i + 0.5)) for i in range(n)]
                candidates += [above, below]
            else:
                reach = max(widths) / 2 + LABEL_GAP + 0.5
                top = cy - stack / 2 + step / 2
                candidates.append([(cx - reach, top + step * i) for i in range(len(texts))])
                candidates.append([(cx + reach, top + step * i) for i in range(len(texts))])

    other_legs = [(path[i], path[i + 1]) for path in lines or [] for i in range(len(path) - 1)]

    def clear(
        candidate: list[XY],
        others: list[tuple[float, float, float, float]],
        crossing: list[tuple[XY, XY]],
    ) -> bool:
        boxes = [text_box(t, xy, size) for t, xy in zip(texts, candidate, strict=True)]
        margin = [(x0 - 0.5, y0 - 0.5, x1 + 0.5, y1 + 0.5) for x0, y0, x1, y1 in boxes]
        if any(segment_hits_box(p, q, box) for p, q in legs + crossing for box in margin):
            return False
        return not any(_overlaps(box, other) for box in margin for other in others)

    drawn = list(symbols or [])
    for others, crossing in (
        ((obstacles or []) + drawn, other_legs),
        (drawn, other_legs),
        ([], []),
    ):
        for candidate in candidates:
            if clear(candidate, others, crossing):
                return candidate, True
    return (candidates[0] if candidates else [route[0]] * len(texts)), False


def _points(xy: list[XY]) -> str | None:
    return ";".join(f"{x!r},{y!r}" for x, y in xy) if xy else None


@dataclass
class _Stop:
    """A point of the route a pipe ends or starts at (an item's node), or a bend."""

    xy: XY
    kind: str  # "start", "end", "bend", "valve", "tee"
    spec: Any = None


@_atomic
def line(
    sheet: Sheet,
    number: str,
    *,
    dn: str | float,
    fluid: str | None = None,
    route: list[Any],
    id: str | None = None,
    standard: str = "Din2448",
    labels: bool = True,
    label_at: XY | None = None,
    data: dict[str, str] | None = None,
) -> Line:
    """Add line *number*: a PipingNetworkSystem with its segments, pipes and inline items.

    *route*: a start (a :class:`Port`, a nozzle id, ``ITEM:NODE``, or an ``offpage("in")``),
    then bends ``(x, y)``, :func:`valve` and :func:`tee` items in flow order, then an end (a
    port or an ``offpage("out")``). A valve or tee without ``at`` sits mid-leg; one with ``at``
    must lie on the leg. Each tee ends a segment; the next segment starts at it. The line
    number and DN labels are placed beside the longest leg, never on the route itself.
    """
    if len(route) < 2:
        raise AuthoringError(f"line {number}: the route needs a start and an end")
    line_id = check_id(id or _ident(number, "Line_"), "line id")
    size = _dn(dn)
    assert size is not None
    notes: list[str] = []

    def endpoint(spec: Any, which: str) -> tuple[Port | None, OffPage | None]:
        if isinstance(spec, OffPage):
            wanted = "in" if which == "start" else "out"
            if spec.direction != wanted:
                raise AuthoringError(
                    f"line {number}: the {which} of a route is an offpage({wanted!r})"
                )
            return None, spec
        if isinstance(spec, tuple):
            raise AuthoringError(f"line {number}: the route's {which} is a point, not a port")
        return sheet.port(spec), None

    start_port, start_off = endpoint(route[0], "start")
    end_port, end_off = endpoint(route[-1], "end")
    start_xy = start_port.xy if start_port else (float(start_off.at[0]), float(start_off.at[1]))
    end_xy = end_port.xy if end_port else (float(end_off.at[0]), float(end_off.at[1]))

    # 1. geometry: the route's points with the items placed on their legs.
    stops: list[_Stop] = [_Stop(start_xy, "start", start_port or start_off)]
    pending: list[Any] = []

    def flush(next_xy: XY) -> None:
        if not pending:
            return
        a = stops[-1].xy
        for i, spec in enumerate(pending, 1):
            t = i / (len(pending) + 1)
            xy = (a[0] + t * (next_xy[0] - a[0]), a[1] + t * (next_xy[1] - a[1]))
            stops.append(_Stop((round(xy[0], 4), round(xy[1], 4)), _kind(spec), spec))
        pending.clear()

    for spec in route[1:-1]:
        if isinstance(spec, Valve | Tee):
            if spec.at is None:
                pending.append(spec)
            else:
                xy = (float(spec.at[0]), float(spec.at[1]))
                flush(xy)
                stops.append(_Stop(xy, _kind(spec), spec))
        elif isinstance(spec, tuple) and len(spec) == 2:
            xy = (float(spec[0]), float(spec[1]))
            flush(xy)
            stops.append(_Stop(xy, "bend"))
        else:
            raise AuthoringError(
                f"line {number}: route item {spec!r} is not a bend (x, y), a valve() or a tee()"
            )
    flush(end_xy)
    stops.append(_Stop(end_xy, "end", end_port or end_off))
    geometry = [s.xy for s in stops]

    # Items with an explicit position must sit on the leg between their neighbours.
    for i, stop in enumerate(stops[1:-1], 1):
        if stop.kind in ("valve", "tee"):
            before, after = stops[i - 1].xy, stops[i + 1].xy
            if not _on_leg(stop.xy, before, after):
                raise AuthoringError(
                    f"line {number}: {stop.spec.id} at {fmt_num(stop.xy[0])},"
                    f"{fmt_num(stop.xy[1])} is not on the leg from {fmt_num(before[0])},"
                    f"{fmt_num(before[1])} to {fmt_num(after[0])},{fmt_num(after[1])}: add a bend"
                )

    # 2. the items: off-page connectors, valves, tees, each with its ports.
    info = sheet._info()
    built: dict[int, tuple[etree._Element, etree._Element, Port, Port]] = {}
    for i, stop in enumerate(stops):
        if stop.kind in ("valve", "tee"):
            rotation = _angle(stops[i - 1].xy, stops[i + 1].xy)
            spec = stop.spec
            at_text = f"{stop.xy[0]!r},{stop.xy[1]!r}"
            try:
                if stop.kind == "valve":
                    made = _valve(
                        spec.id,
                        spec.cls,
                        _dn(spec.dn) or size,
                        standard,
                        at_text,
                        rotation,
                        spec.tag,
                        info,
                    )
                else:
                    made = _tee(
                        spec.id,
                        size,
                        _dn(spec.branch_dn) or size,
                        standard,
                        at_text,
                        rotation,
                        spec.branch_side,
                        spec.tag,
                        info,
                    )
            except (FragmentError, ValueError) as failure:
                raise AuthoringError(f"line {number}: {failure}") from failure
            parts = sheet._parts(made)
            for shape in parts.get("SHAPE", []):
                if shape.get("id") not in sheet.index.by_id:
                    sheet.add_shape(shape)
            conceptual, drawing = parts["CONCEPTUAL"][0], parts["DRAWING"][0]
            sheet.check_new(conceptual, drawing)
            sheet._index_tree(conceptual)
            sheet._index_tree(drawing)
            n1, n2 = f"{spec.id}_N1", f"{spec.id}_N2"
            built[i] = (
                conceptual,
                drawing,
                Port(spec.id, n1, sheet.position(n1)),
                Port(spec.id, n2, sheet.position(n2)),
            )
            if stop.kind == "tee":
                spec.branch = Port(spec.id, f"{spec.id}_N3", sheet.position(f"{spec.id}_N3"))
        elif isinstance(stop.spec, OffPage):
            spec = stop.spec
            neighbour = stops[1].xy if i == 0 else stops[-2].xy
            flow = spec.rotation
            if flow is None:
                flow = _angle(stop.xy, neighbour) if i == 0 else _angle(neighbour, stop.xy)
            off_id = check_id(spec.id or f"{line_id}_{'From' if i == 0 else 'To'}", "off-page id")
            spec.id = off_id
            made = offpage_fragment(
                off_id,
                spec.direction,
                stop.xy,
                rotation=flow,
                shape_id=sheet.shapes.get(OFFPAGE_SHAPES[spec.direction][1]),
                note=spec.note,
                note_at=spec.note_at,
            )
            parts = sheet._parts(made)
            conceptual, drawing = parts["CONCEPTUAL"][0], parts["DRAWING"][0]
            sheet.check_new(conceptual, drawing)
            sheet._index_tree(conceptual)
            sheet._index_tree(drawing)
            port = Port(off_id, f"{off_id}_N1", stop.xy)
            built[i] = (conceptual, drawing, port, port)

    # 3. segments and pipes, split at the tees.
    segments: list[tuple[etree._Element, etree._Element]] = []
    segment_ids: list[str] = []
    current_source = start_port or built[0][3]
    items: list[tuple[etree._Element, etree._Element]] = []
    if 0 in built:
        items.append(built[0][:2])
    pipes: list[tuple[Port, Port, list[XY]]] = []
    bends: list[XY] = []
    source = current_source
    for i, stop in enumerate(stops[1:], 1):
        if stop.kind == "bend":
            bends.append(stop.xy)
            continue
        target = (end_port or built[i][2]) if stop.kind == "end" else built[i][2]
        pipes.append((source, target, bends))
        bends = []
        if i in built:
            items.append(built[i][:2])
        if stop.kind in ("tee", "end"):
            k = len(segments) + 1
            seg_id = f"{line_id}_S{k}"
            segments.append(
                _build_segment(
                    sheet,
                    info,
                    seg_id,
                    k,
                    current_source,
                    target,
                    pipes,
                    items,
                    size,
                    standard,
                    _extra_data(fluid, data),
                    notes,
                )
            )
            segment_ids.append(seg_id)
            pipes, items = [], []
            if stop.kind == "tee":
                current_source = built[i][3]
        source = built[i][3] if i in built else target

    # 4. the system and its labels.
    system = etree.Element("Object", id=line_id, type="Plant/Piping.PipingNetworkSystem")
    segs = etree.SubElement(system, "Components", property="Segments")
    for conceptual, _ in segments:
        segs.append(conceptual)
    system.append(string("LineNumber", number))
    for element in _segment_data(size, standard, fluid, data):
        system.append(element)
    drawing = etree.Element(
        "Object", id=f"{line_id}_Drawing", type="Core/Diagram.RepresentationGroup"
    )
    groups = etree.SubElement(drawing, "Components", property="Groups")
    for _, segment_drawing in segments:
        groups.append(segment_drawing)
    etree.SubElement(drawing, "References", objects=f"#{line_id}", property="Represents")
    for element in (system, drawing):
        for child in element.iter("Object"):
            if (
                child.get("id") in sheet.index.by_id
                and sheet.index.by_id[child.get("id")] is not child
            ):
                raise AuthoringError(f"{sheet.path}: id {child.get('id')} exists already")
    sheet._container(sheet.plant, "PipingNetworkSystems").append(system)
    sheet._container(sheet.diagram, "Groups").append(drawing)
    sheet._index_tree(system)
    sheet._index_tree(drawing)

    placed: dict[str, XY] = {}
    if labels:
        texts = [number, f"DN {size}"]
        if label_at is not None:
            step = LABEL_SIZE * 1.2 + 0.4
            spots = [label_at, (label_at[0], label_at[1] + step)]
        else:
            spots, clear = place_line_labels(
                geometry,
                texts,
                obstacles=sheet.text_boxes(),
                lines=sheet.line_paths(),  # its own pipes too: they follow the route
                symbols=sheet.symbol_boxes(),
            )
            if not clear:
                notes.append(
                    f"line {number}: no leg leaves room for its labels off the route; "
                    "pass label_at=(x, y)"
                )
        for attribute, spot in zip(
            ("LineNumber", "NominalDiameterRepresentation"), spots, strict=True
        ):
            label_id = f"{line_id}_{'Number' if attribute == 'LineNumber' else 'DN'}Label"
            made = _label(label_id, line_id, attribute, f"{spot[0]!r},{spot[1]!r}", info)
            element = sheet._parts(made)["DRAWING"][0]
            for size_value in element.iter("Data"):
                if size_value.get("property") == "Size":
                    size_value[0].text = repr(LABEL_SIZE)
            sheet.check_new(element)
            groups.append(element)
            sheet._index_tree(element)
            placed[attribute] = spot
    sheet.notes += [n for n in notes if n not in sheet.notes]
    return Line(line_id, number, segment_ids, geometry, placed, notes)


def _extra_data(fluid: str | None, data: dict[str, str] | None) -> list[etree._Element]:
    extra = [string("FluidCode", fluid)] if fluid else []
    return extra + [string(prop, value) for prop, value in (data or {}).items()]


def _kind(spec: Any) -> str:
    return "valve" if isinstance(spec, Valve) else "tee"


def _segment_data(
    size: str, standard: str, fluid: str | None, data: dict[str, str] | None
) -> list[etree._Element]:
    from chemeascode.domains.piping.authoring._xml import enum
    from chemeascode.domains.piping.authoring.fragment import _standard

    notes: list[str] = []
    elements = [
        string("NominalDiameterNumericalValueRepresentation", size),
        string("NominalDiameterRepresentation", f"DN {size}"),
    ]
    std = _standard(size, standard, notes)
    if std:
        elements.append(enum("NominalDiameterStandard", std))
    elements.append(string("NominalDiameterTypeRepresentation", "DN"))
    if fluid:
        elements.append(string("FluidCode", fluid))
    for prop, value in (data or {}).items():
        elements.append(string(prop, value))
    return elements


def _build_segment(
    sheet: Sheet,
    info: _Info,
    seg_id: str,
    k: int,
    source: Port,
    target: Port,
    pipes: list[tuple[Port, Port, list[XY]]],
    items: list[tuple[etree._Element, etree._Element]],
    size: str,
    standard: str,
    data: list[etree._Element],
    notes: list[str],
) -> tuple[etree._Element, etree._Element]:
    made = _segment(seg_id, source.ref(), target.ref(), size, standard, f"S{k}", None, None)
    parts = sheet._parts(made)
    segment, drawing = parts["CONCEPTUAL"][0], parts["DRAWING"][0]
    for element in data:
        segment.append(element)
    connections = segment.find("Components[@property='Connections']")
    holder = segment.find("Components[@property='Items']")
    groups = drawing.find("Components[@property='Groups']")
    for container in (connections, holder, groups):
        for comment in [c for c in container if not isinstance(c.tag, str)]:
            container.remove(comment)
    for n, (a, b, bends) in enumerate(pipes, 1):
        try:
            pipe = _pipe(f"{seg_id}_P{n}", a.ref(), b.ref(), _points(bends), info)
        except FragmentError as failure:
            raise AuthoringError(f"{seg_id}: {failure}") from failure
        pipe_parts = sheet._parts(pipe)
        notes += [m for m in pipe.notes if "already connected" in m]
        connections.append(pipe_parts["CONCEPTUAL"][0])
        groups.append(pipe_parts["DRAWING"][0])
    for conceptual, item_drawing in items:
        holder.append(conceptual)
        groups.append(item_drawing)
    if not len(holder):
        segment.remove(holder)
    return segment, drawing
