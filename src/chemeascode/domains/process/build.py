"""``cheme process build``: the BFD and PFD sheets generated from the process YAML.

Each sheet is a DEXPI 2.0.1 ``ProcessModel`` with a drawing, built from pyDEXPI's classes and
written by its serializer (the pattern of pyDEXPI's ``make_synthetic_process.py``):

- **BFD**: feeds (``Source``), products (``Sink``) and blocks with their ports; the streams that
  cross a block boundary, a step end shown at the block port it delegates. Each connection keeps
  the YAML stream id and names what it represents (``represents: S1``) in its description.
  With ``bfd.aggregate`` parallel streams between two nodes (same kind and direction) are one
  connection with its first stream's id (``represents: S2 S3``) and no values.
- **PFD**: the same blocks with their steps nested (``subProcessSteps``); a step port where a
  boundary stream enters delegates its block port (``superReference``/``subReference``), and the
  stream keeps running between the block ports, as DEXPI's hierarchy wants; internal streams run
  between step ports.

Stream values become ``QualifiedValue`` s carrying the case (``case``), ``scope`` design and the
provenance (given: specified, assumed: estimated, calculated: calculated; a measured origin:
observed) with the provenance, its origin and the source in their description. Calculated values
(``state.calculated``) and the phase go into the stream's ``MaterialState`` (see
:func:`_calculated`). Stale values (``cheme.process-calculated-stale``: state, composition,
duty and calculated alike) are left out. A molar or normal-volume flow becomes per-component molar
flows or a mass flow (DEXPI's volume flow is the actual one; see :func:`_stream_values`). Each
sheet records what it was built from: an XML comment and a DEXPI note with the generator and
schema versions, the view, the case and the SHA-256 of the canonical input, and the comment also
the SHA-256 of the canonical generated XML (see :mod:`.provenance`).
"""

from __future__ import annotations

import enum
import inspect
import math
import typing
from dataclasses import dataclass, field, replace
from typing import Any, cast

import pydexpi.pydexpi_classes.pydexpi_classes as C

from chemeascode.domains.process import GENERATOR_VERSION, SCHEMA
from chemeascode.domains.process.layout import Area, LEdge, LNode, layout, spread
from chemeascode.domains.process.model import Process
from chemeascode.domains.process.schema import FLOW_UNITS, PRESSURE_UNITS, StreamDef
from chemeascode.domains.process.symbols import JUNCTION, Symbol, step_drawing

VIEWS = ("bfd", "pfd")
VIEW_TITLES = {"bfd": "Block flow diagram", "pfd": "Process flow diagram"}

_BLACK = C.Color(r=0, g=0, b=0)
_GREY = C.Color(r=90, g=90, b=90)
_LINE = C.Stroke(color=_BLACK, dashStyle=C.DashStyle.SOLID, width=0.35)
_THIN = C.Stroke(color=_GREY, dashStyle=C.DashStyle.SOLID, width=0.25)
_DASH = C.Stroke(color=_BLACK, dashStyle=C.DashStyle.DASH, width=0.25)
_TERMINAL = C.Stroke(color=_BLACK, dashStyle=C.DashStyle.SOLID, width=0.25)
#: PFD: process (material) lines heavier than the equipment, process areas (blocks holding
#: steps) a light dash-dot boundary.
_PROCESS = C.Stroke(color=_BLACK, dashStyle=C.DashStyle.SOLID, width=0.5)
_AREA_GREY = C.Color(r=130, g=130, b=130)
_AREA = C.Stroke(color=_AREA_GREY, dashStyle=C.DashStyle.LONGDASHSHORTDASH, width=0.25)
_FILL = C.Stroke(color=_BLACK, dashStyle=C.DashStyle.SOLID, width=0.1)

_PROVENANCE = {
    "given": C.QuantityProvenance.SPECIFIED,
    "assumed": C.QuantityProvenance.ESTIMATED,
    "calculated": C.QuantityProvenance.CALCULATED,
}
#: Origins with a DEXPI provenance of their own (the others take their class's).
_ORIGIN = {"measured": C.QuantityProvenance.OBSERVED}


def _provenance(q: Any) -> Any:
    """The DEXPI provenance of the value *q*: its origin's, else its class's."""
    return _ORIGIN.get(q.origin or "") or _PROVENANCE[q.provenance]


def _class(q: Any) -> str:
    """The provenance of *q* as the sheets write it: ``given``, or ``given, measured``."""
    return f"{q.provenance}, {q.origin}" if q.origin else q.provenance


def step_class(name: str) -> type | None:
    """The DEXPI process step class called *name* (``ProcessStep`` or a subclass)."""
    cls = getattr(C, name, None)
    if inspect.isclass(cls) and issubclass(cls, C.ProcessStep):
        return cls
    return None


def method_enum(annotation: Any) -> type[enum.Enum] | None:
    """The enum of a step class's ``method`` field: the annotation itself, or the enum in a
    union such as ``Pumping``'s ``PumpingMethod | Undefined | None``."""
    for candidate in (annotation, *typing.get_args(annotation)):
        if inspect.isclass(candidate) and issubclass(candidate, enum.Enum):
            return candidate
    return None


def step_method(annotation: Any, wanted: str | None) -> Any:
    """The member of a step class's ``method`` enum *wanted* names (name or value, any case);
    without one, ``Unspecified`` or ``Generic``; None where the field has no enum."""
    methods = method_enum(annotation)
    if methods is None:
        return None
    members = list(methods)
    for member in members:
        if wanted and wanted.lower() in (member.name.lower(), str(member.value).lower()):
            return member
    if wanted:
        return None
    fallback = [m for m in members if m.name in ("UNSPECIFIED", "GENERIC")]
    return (fallback or members)[0]


def _text(value: str) -> C.MultiLanguageString:
    return C.MultiLanguageString(
        singleLanguageStrings=[C.SingleLanguageString(language="en", value=value)]
    )


def _label(id_: str, text: str, x: float, y: float, size: float = 3.0, align: str = "CENTERCENTER"):
    return C.Text(
        id=id_,
        text=text,
        position=C.Point(x=round(x, 3), y=round(y, 3)),
        alignment=getattr(C.TextAlignment, align),
        color=_BLACK,
        font="Arial",
        size=size,
        rotation=0.0,
    )


def _box(id_: str, x0: float, y0: float, x1: float, y1: float, stroke=_LINE) -> C.Static:
    corners = [(x0, y0), (x1, y0), (x1, y1), (x0, y1), (x0, y0)]
    return C.Static(
        id=f"{id_}_Static",
        elements=[
            C.PolyLine(
                id=f"{id_}_Outline",
                points=[C.Point(x=round(x, 3), y=round(y, 3)) for x, y in corners],
                stroke=stroke,
            )
        ],
    )


def _symbol(id_: str, symbol: Symbol, area: tuple[float, float, float, float]) -> C.Static:
    """*symbol* scaled to fit *area* (x0, y0, x1, y1) and centred in it, in the PFD's black."""
    k, fitted = _fit(symbol, area)

    def at(x: float, y: float) -> C.Point:
        px, py = fitted(x, y)
        return C.Point(x=px, y=py)

    elements: list[Any] = []
    for n, item in enumerate(symbol.primitives, 1):
        stroke = C.Stroke(
            color=_BLACK,
            dashStyle=getattr(C.DashStyle, item["dash"].upper(), C.DashStyle.SOLID),
            width=min(item["width"], _LINE.width),
        )
        if "line" in item:
            elements.append(
                C.PolyLine(
                    id=f"{id_}_{n}", points=[at(x, y) for x, y in item["line"]], stroke=stroke
                )
            )
        else:
            elements.append(
                C.Ellipse(
                    id=f"{id_}_{n}",
                    center=at(*item["ellipse"]),
                    fillStyle=C.FillStyle.TRANSPARENT,
                    horizontalSemiAxis=round(item["rx"] * k, 3),
                    verticalSemiAxis=round(item["ry"] * k, 3),
                    rotation=item["rotation"],
                    stroke=stroke,
                )
            )
    return C.Static(id=f"{id_}_Static", elements=elements)


def _shell(cls: type, id_: str) -> Any:
    # DEXPI makes Port.connectorReference and ProcessConnection.source/target required
    # references to each other: the connection is built empty, completed once its ports exist.
    return cls.model_construct(id=id_)


def _quantity(id_: str, value: float, unit: Any, case: str, q: Any, shown: str):
    """The QualifiedValue of the YAML quantity *q* (its provenance, origin and source)."""
    prov = _class(q)
    return C.QualifiedValue(
        id=id_,
        value=C.PhysicalQuantity(value=value, unit=unit),
        case=case,
        scope=C.Scope.DESIGN,
        provenance=_provenance(q),
        displayText=shown,
        description=_text(f"{prov}; source: {q.source}") if q.source else _text(prov),
    )


# -- the graph of one view ----------------------------------------------------------------------


@dataclass
class Conn:
    """One connection drawn on a view: a YAML stream, between DEXPI ports."""

    stream: StreamDef
    src: tuple[str, str]  # (node, port) of the DEXPI source (outermost)
    dst: tuple[str, str]
    represents: list[str] = field(default_factory=list)
    #: The block the connection is drawn in (None: the top level).
    level: str | None = None


def _connections(process: Process, view: str) -> tuple[list[Conn], list[Conn]]:
    """(top-level connections, connections inside blocks) of *view*: each stream between the
    ports its ends have in the innermost block holding both (a step or nested block port by the
    port it delegates)."""
    top: list[Conn] = []
    inner: list[Conn] = []
    for stream in process.flowsheet.streams:
        a, b = process.ends(stream)
        if a is None or b is None or a.node not in process.kinds or b.node not in process.kinds:
            continue
        level = process.level(a.node, b.node)
        if level is None and not process.crossing(stream) or level is not None and view != "pfd":
            continue
        ea, eb = process.lift(a, level), process.lift(b, level)
        if ea is None or eb is None or ea.node == level or eb.node == level:
            continue
        conn = Conn(stream, (ea.node, ea.port), (eb.node, eb.port), [stream.id], level)
        (top if level is None else inner).append(conn)
    if view == "bfd":
        top = _aggregated(process, top)
    return top, inner


def _aggregated(process: Process, conns: list[Conn]) -> list[Conn]:
    """*conns* with the parallel ones between node pairs the flowsheet aggregates
    (``bfd.aggregate``) merged: same nodes, direction and kind become one connection, between
    the ports of its first stream, with the first stream's id and every stream it represents."""
    options = process.flowsheet.bfd
    if options is None:
        return conns
    merged: dict[tuple[str, str, str], Conn] = {}
    out: list[Conn] = []
    for conn in conns:
        a, b = conn.src[0], conn.dst[0]
        key = (a, b, conn.stream.kind)
        first = merged.get(key)
        if first is not None:
            first.represents.append(conn.stream.id)
            continue
        if options.aggregates(a, b):
            merged[key] = conn
        out.append(conn)
    return out


def connection_streams(process: Process) -> dict[str, list[str]]:
    """The BFD connections by id (the id of the first stream each draws) and the streams each
    represents, in flowsheet order."""
    return {c.stream.id: list(c.represents) for c in _connections(process, "bfd")[0]}


# -- sizes and layout ---------------------------------------------------------------------------


def _text_width(text: str, size: float) -> float:
    return len(text) * size * 0.56


#: A step drawn with its class's symbol (:func:`step_symbol`): the symbol's height and the band
#: below it holding the step's id and title.
SYMBOL_HEIGHT = 16.0
SYMBOL_LABELS = 8.0


def _symbol_width(symbol: Symbol) -> float:
    """How wide a step draws *symbol* (at :func:`_symbol_height`)."""
    x0, y0, x1, y1 = symbol.extent()
    return _symbol_height(symbol) * (x1 - x0) / (y1 - y0)


def _symbol_height(symbol: Symbol) -> float:
    """How high a step draws *symbol*: twice :data:`SYMBOL_HEIGHT` for a tall one (a column)."""
    x0, y0, x1, y1 = symbol.extent()
    return SYMBOL_HEIGHT * (2.0 if (y1 - y0) > 1.5 * (x1 - x0) else 1.0)


#: PFD: the band above a step that holds its utility stubs (:func:`local_terminals`), and a
#: junction's width.
STUB_BAND = 11.0
JUNCTION_W = 10.0


def _drawing(process: Process, item_id: str, kind: str) -> Symbol | str | None:
    """How the PFD draws node *item_id*: a :class:`Symbol`, :data:`JUNCTION` or None (a box)."""
    if kind != "step":
        return None
    item = process.nodes[item_id]
    return step_drawing(item.class_, getattr(item, "symbol", None))


def local_terminals(process: Process, view: str) -> set[str]:
    """The utility terminals the PFD draws at each step they serve, as a short stub with the
    utility's id, instead of as a box with a line to every user: ``category: utility``, a
    ``utility:`` given, or only energy ports (power, a heat sink)."""
    if view != "pfd":
        return set()
    fs = process.flowsheet
    return {
        t.id
        for t in [*fs.feeds, *fs.products]
        if t.category == "utility"
        or t.utility is not None
        or (t.ports and all(p.kind == "energy" for p in t.ports))
    }


def _chain(process: Process, conn: Conn, local: set[str]) -> list[str]:
    """The port keys of a utility stub, from the block port the stream reaches (the end of the
    drawn connection) down the delegations to the step port it ends at."""
    a, b = process.ends(conn.stream)
    supply = conn.src[0] in local
    end = b if supply else a
    outer = conn.dst if supply else conn.src
    assert end is not None
    keys = [f"{end.node}.{end.port}"]
    node, port = end.node, process.port(end)
    while node != outer[0] and port is not None and port.delegates:
        home = process.home(node)
        if home is None:
            break
        node = home
        port = next((p for p in process.nodes[home].ports if p.id == port.delegates), None)
        if port is not None:
            keys.insert(0, f"{node}.{port.id}")
    return keys


def _fit(symbol: Symbol, area: tuple[float, float, float, float]):
    """The transform drawing *symbol* scaled to fit *area* and centred in it: (k, at)."""
    x0, y0, x1, y1 = symbol.extent()
    k = min((area[2] - area[0]) / (x1 - x0), (area[3] - area[1]) / (y1 - y0))
    cx, cy = (area[0] + area[2]) / 2, (area[1] + area[3]) / 2
    mx, my = (x0 + x1) / 2, (y0 + y1) / 2

    def at(x: float, y: float) -> tuple[float, float]:
        return (round(cx + (x - mx) * k, 3), round(cy + (y - my) * k, 3))

    return k, at


def _symbol_area(node: LNode) -> tuple[float, float, float, float]:
    """Where a step node draws its symbol: below its stub band, above its labels."""
    return (
        node.x + 4,
        node.y + node.port_top,
        node.x + node.width - 4,
        node.y + node.height - node.port_bottom,
    )


def _outline(symbol: Symbol, area: tuple[float, float, float, float]):
    """*symbol* fitted to *area* as absolute segments and ellipses (for contact points)."""
    k, at = _fit(symbol, area)
    segments, ellipses = [], []
    for item in symbol.primitives:
        if "line" in item:
            pts = [at(x, y) for x, y in item["line"]]
            segments += list(zip(pts, pts[1:], strict=False))
        else:
            ellipses.append(
                (at(*item["ellipse"]), item["rx"] * k, item["ry"] * k, item["rotation"])
            )
    return segments, ellipses


def _contact(symbol: Symbol, area, axis: str, value: float, side: str) -> float | None:
    """Where the line ``x = value`` (*axis* ``x``) or ``y = value`` meets the fitted *symbol*
    first coming from *side* (``top``, ``left``, ``right``): its y or x; None if it misses."""
    segments, ellipses = _outline(symbol, area)
    hits: list[float] = []
    for (ax, ay), (bx, by) in segments:
        if axis == "x" and min(ax, bx) <= value <= max(ax, bx) and ax != bx:
            hits.append(ay + (by - ay) * (value - ax) / (bx - ax))
        elif axis == "x" and ax == bx == value:
            hits += [ay, by]
        elif axis == "y" and min(ay, by) <= value <= max(ay, by) and ay != by:
            hits.append(ax + (bx - ax) * (value - ay) / (by - ay))
        elif axis == "y" and ay == by == value:
            hits += [ax, bx]
    for (cx, cy), rx, ry, rotation in ellipses:
        if rotation % 180 == 90:
            rx, ry = ry, rx
        elif rotation % 180:
            continue
        if axis == "x" and rx > 0 and abs(value - cx) <= rx:
            h = ry * math.sqrt(max(0.0, 1 - ((value - cx) / rx) ** 2))
            hits += [cy - h, cy + h]
        elif axis == "y" and ry > 0 and abs(value - cy) <= ry:
            h = rx * math.sqrt(max(0.0, 1 - ((value - cy) / ry) ** 2))
            hits += [cx - h, cx + h]
    if not hits:
        return None
    return max(hits) if side == "right" else min(hits)


#: A step's title is wrapped into lines of about this many characters (at most three).
WRAP = 26
TITLE_SIZE, TITLE_LEADING = 2.2, 2.9


def wrap(text: str, width: int = WRAP, lines: int = 3) -> list[str]:
    """*text* in at most *lines* lines of about *width* characters, broken between words."""
    out: list[str] = []
    for word in text.split():
        if out and len(out[-1]) + 1 + len(word) <= width:
            out[-1] += " " + word
        elif len(out) < lines:
            out.append(word)
        else:
            out[-1] += " " + word
    return out or [""]


def _labels_height(title: str) -> float:
    """The band below a symbol holding the step's id and its wrapped title."""
    return 4.6 + TITLE_LEADING * len(wrap(title))


def _node_size(title: str, ident: str, kind: str, ports: int) -> tuple[float, float]:
    if kind == "step":
        lines = wrap(title)
        width = max(
            30.0,
            max(_text_width(line, TITLE_SIZE) for line in lines) + 8,
            _text_width(ident, 2.6) + 8,
        )
        height = max(14.0, ports * 6.0 + 4, _labels_height(title) + 6.0)
        return round(width, 1), round(height, 1)
    width = max(36.0, _text_width(title, 2.8) + 8, _text_width(ident, 2.2) + 8)
    height = max(18.0 if kind not in ("feed", "product") else 14.0, ports * 7.0 + 4)
    return round(width, 1), round(height, 1)


@dataclass
class Placed:
    """Positions of every drawn node (absolute) and the route of every connection."""

    nodes: dict[str, LNode] = field(default_factory=dict)
    routes: dict[str, list[tuple[float, float]]] = field(default_factory=dict)
    feedback: set[str] = field(default_factory=set)
    #: delegation lines: (step port key, block port key) -> points
    delegations: dict[str, list[tuple[float, float]]] = field(default_factory=dict)
    bounds: tuple[float, float, float, float] = (0.0, 0.0, 0.0, 0.0)
    #: stream label anchors (centre bottom) and texts, placed clear of lines, nodes and labels
    labels: dict[str, tuple[float, float]] = field(default_factory=dict)
    texts: dict[str, str] = field(default_factory=dict)
    #: ports placed off their node's sides ("NODE.port" -> point): the ends of utility stubs
    port_points: dict[str, tuple[float, float]] = field(default_factory=dict)
    #: utility stubs: stream id -> (terminal id, flag point, point on the step)
    stubs: dict[str, tuple[str, tuple[float, float], tuple[float, float]]] = field(
        default_factory=dict
    )
    #: the nodes with utility stubs (in the band along their top)
    hosts: set[str] = field(default_factory=set)
    #: which side of its stub a stub's flag and label go: -1 left, 0 above (one stub), 1 right
    stub_side: dict[str, int] = field(default_factory=dict)
    #: the sheet (size, where the stream table goes) and the table
    sheet: Any = None
    table: Any = None

    def label_box(self, stream_id: str) -> tuple[float, float, float, float]:
        x, y = self.labels[stream_id]
        half = _text_width(self.texts[stream_id], LABEL_SIZE) / 2
        return (x - half, y - LABEL_SIZE - 0.2, x + half, y)

    def obstacles(self, process: Process) -> list[tuple[float, float, float, float]]:
        """Boxes a stream label must stay off: every node, but only the border and title band
        of a block that holds steps or nested blocks (its streams are labelled inside it)."""
        boxes = []
        holders = {process.home(s) for s in self.nodes}
        for node_id, n in self.nodes.items():
            x0, y0, x1, y1 = n.x, n.y, n.x + n.width, n.y + n.height
            if node_id in holders:
                band = PAD_TOP - 4.0
                title = _text_width(f"{node_id}  {process.nodes[node_id].title or ''}", 2.8)
                boxes += [(x0, y0, x1, y0), (x0, y1, x1, y1), (x0, y0, x0, y1), (x1, y0, x1, y1)]
                boxes.append((x0, y0, x0 + title + 3.0, y0 + band))
            else:  # a step's stub band holds only its stubs, flags and their labels
                boxes.append((x0, y0 + (STUB_BAND if node_id in self.hosts else 0.0), x1, y1))
        return boxes


PAD_X, PAD_TOP, PAD_BOTTOM = 14.0, 11.0, 7.0


def place(process: Process, view: str) -> Placed:
    """Lay out *view*: top-level nodes layered, PFD steps layered inside their blocks."""
    fs = process.flowsheet
    overrides = getattr(fs.layout, view)
    top, inner = _connections(process, view)
    local = local_terminals(process, view)
    stub_conns = [c for c in top if (c.src[0] in local) != (c.dst[0] in local)]
    top = [c for c in top if c not in stub_conns]
    chains = {c.stream.id: _chain(process, c, local) for c in stub_conns}
    hosts: dict[str, list[Conn]] = {}
    for c in stub_conns:
        hosts.setdefault(chains[c.stream.id][-1].split(".", 1)[0], []).append(c)
    placed = Placed()
    # the ports drawn on each node: those its connections end at, and those delegating a drawn
    # port of the block it sits in (outer blocks first)
    used_ports: dict[str, set[tuple[str, str]]] = {}
    for conn in top + inner:
        used_ports.setdefault(conn.src[0], set()).add(("out", conn.src[1]))
        used_ports.setdefault(conn.dst[0], set()).add(("in", conn.dst[1]))
    if view == "pfd":
        for item in sorted([*fs.blocks, *fs.steps], key=lambda n: len(process.ancestors(n.id))):
            home = process.home(item.id)
            for port in item.ports if home is not None else []:
                if port.delegates and (port.direction, port.delegates) in used_ports.get(home, ()):
                    used_ports.setdefault(item.id, set()).add((port.direction, port.id))

    def ports_of(node_id: str, direction: str) -> list[str]:
        node = process.nodes[node_id]
        connected = used_ports.get(node_id, set())
        return [
            p.id for p in node.ports if p.direction == direction and (direction, p.id) in connected
        ]

    def holds(node_id: str) -> bool:
        return (
            view == "pfd"
            and process.kinds.get(node_id) == "block"
            and bool(process.inside(node_id))
        )

    def inner_layout(block: Any, outer: LNode | None) -> tuple[Any, Any, Any]:
        """Steps and nested blocks of *block* laid out relative to its top left, with the
        block's boundary as two ghost nodes, so a delegation is routed like a stream and crosses
        no step. Without *outer* (the placed block) the layout gives the block's size and the
        order of its ports that suits its inside (written back to *block*'s ins and outs by the
        caller)."""
        size = (outer.width, outer.height) if outer is not None else None
        conns = [c for c in inner if c.level == block.id]
        if outer is not None:
            block_ins, block_outs = outer.ins, outer.outs
        else:
            block_ins, block_outs = ports_of(block.id, "in"), ports_of(block.id, "out")
        lnodes = []
        ledges = [LEdge(c.stream.id, c.src[0], c.src[1], c.dst[0], c.dst[1]) for c in conns]
        height = size[1] if size else 10.0
        ghost_in = LNode(f"{block.id}#in", 0.0, height, [], list(block_ins), ghost=True)
        ghost_out = LNode(f"{block.id}#out", 0.0, height, list(block_outs), [], ghost=True)
        ghost_out.last = True
        if size is not None:
            ghost_in.x, ghost_in.y, ghost_in.pinned = 0.0, 0.0, True
            ghost_out.x, ghost_out.y, ghost_out.pinned = size[0], 0.0, True
        for step in process.inside(block.id):
            drawn = used_ports.get(step.id, set())
            for port in step.ports:
                if (
                    port.delegates
                    and port.delegates in block_ins + block_outs
                    and (port.direction, port.id) in drawn
                ):
                    if port.direction == "in":
                        ledges.append(
                            LEdge(
                                f"{step.id}.{port.id}",
                                ghost_in.id,
                                port.delegates,
                                step.id,
                                port.id,
                            )
                        )
                    else:
                        ledges.append(
                            LEdge(
                                f"{step.id}.{port.id}",
                                step.id,
                                port.id,
                                ghost_out.id,
                                port.delegates,
                            )
                        )
            lnodes.append(sized(step, "step" if process.kinds[step.id] == "step" else "block"))
        every = [ghost_in, *lnodes, ghost_out]
        # routes stay below the title band and inside the block once its size is known
        area: Area = (0.0, PAD_TOP - 4.0, None, None)
        if size is not None:
            area = (0.0, PAD_TOP - 4.0, size[0], size[1] - 2.0)
        bounds = layout(
            every,
            ledges,
            origin=(PAD_X, PAD_TOP),
            gap_x=24.0,
            gap_y=16.0,
            skip="below",
            grid_feedback=True,
            area=area,
            order_ports=True,
        )
        return lnodes, ledges, (bounds, ghost_in.outs, ghost_out.ins)

    def sized(item: Any, kind: str) -> LNode:
        """*item* as a node: its own size, or a block holding steps or nested blocks sized
        (and its ports ordered) by its inside; a pin sets position (relative to the block it
        sits in) and size."""
        ins, outs = ports_of(item.id, "in"), ports_of(item.id, "out")
        w, h = _node_size(item.title or item.id, item.id, kind, max(len(ins), len(outs)))
        drawing = _drawing(process, item.id, kind)
        band = STUB_BAND if item.id in hosts else 0.0
        port_top, port_bottom = band, 0.0
        if isinstance(drawing, Symbol):
            labels = _labels_height(item.title or item.id)
            w = max(w, _symbol_width(drawing) + 8.0)
            h = max(h, _symbol_height(drawing) + labels + 2) + band
            port_top, port_bottom = band + 1.0, labels + 1.0
        elif drawing == JUNCTION:
            w, h = JUNCTION_W, max(8.0, (max(len(ins), len(outs)) - 1) * 6.0 + 8.0) + band
        else:
            h += band
        nested = holds(item.id)
        if nested:
            b, ins, outs = inner_layout(item, None)[2]
            w = max(w, b[2] + PAD_X)
            h = max(h, b[3] + PAD_BOTTOM)
        node = LNode(
            item.id,
            w,
            h,
            ins,
            outs,
            fixed_ports=nested,
            port_top=port_top,
            port_bottom=port_bottom,
        )
        pin = overrides.get(item.id)
        if pin is not None and pin.pinned:
            if kind != "step":
                node.width = pin.width or node.width
                node.height = pin.height or node.height
            if pin.x is not None and pin.y is not None:
                node.x, node.y, node.pinned = pin.x, pin.y, True
        return node

    nodes: list[LNode] = []
    for kind, items in (("feed", fs.feeds), ("block", fs.blocks), ("product", fs.products)):
        for item in items:
            if process.home(item.id) is None and item.id not in local:
                nodes.append(sized(item, kind))
    edges = [LEdge(c.stream.id, c.src[0], c.src[1], c.dst[0], c.dst[1]) for c in top]
    bounds = layout(nodes, edges, origin=(20.0, 40.0))
    for node in nodes:
        placed.nodes[node.id] = node
    for edge in edges:
        placed.routes[edge.id] = edge.points
        if edge.feedback:
            placed.feedback.add(edge.id)
    # blocks' insides, outer blocks first, to absolute coordinates; delegation lines from block
    # port to step (nested block) port
    queue = [n for n in nodes if n.fixed_ports]
    while queue:
        holder = queue.pop(0)
        outer = placed.nodes[holder.id]
        lnodes, ledges, _ = inner_layout(process.nodes[holder.id], holder)
        for node in lnodes:
            absolute = replace(node, x=outer.x + node.x, y=outer.y + node.y)
            placed.nodes[node.id] = absolute
            if node.fixed_ports:
                queue.append(node)
        for edge in ledges:
            points = _clean([(outer.x + x, outer.y + y) for x, y in edge.points])
            if "#" in edge.src or "#" in edge.dst:
                placed.delegations[edge.id] = points
                continue
            placed.routes[edge.id] = points
            if edge.feedback:
                placed.feedback.add(edge.id)
    for edge_id, points in list(placed.routes.items()):
        pin = overrides.get(edge_id)
        if pin is not None and pin.pinned and pin.waypoints and len(points) >= 2:
            placed.routes[edge_id] = _clean([points[0], *pin.waypoints, points[-1]])
    _place_stubs(process, placed, stub_conns, chains, hosts, local)
    xs = [n.x for n in placed.nodes.values()] + [n.x + n.width for n in placed.nodes.values()]
    ys = [n.y for n in placed.nodes.values()] + [n.y + n.height for n in placed.nodes.values()]
    for pts in placed.routes.values():
        xs += [p[0] for p in pts]
        ys += [p[1] for p in pts]
    placed.bounds = (min(xs), min(ys), max(xs), max(ys)) if xs else bounds
    conns = top + stub_conns + inner
    placed.texts = {c.stream.id: " ".join(c.represents) for c in conns}
    if view == "pfd":
        from chemeascode.domains.process import pfd_sheet

        drawn = {c.stream.id for c in conns if len(c.represents) == 1}
        placed.table = pfd_sheet.stream_table(
            process,
            [s.id for s in fs.streams if s.id in drawn and s.kind == "material"],
            [s.id for s in fs.streams if s.id in drawn and s.kind == "energy"],
            fs.default_case(),
        )
    else:
        from chemeascode.domains.process.pfd_sheet import Table

        placed.table = Table()
    _on_sheet(placed, fixed=any(p.pinned for p in overrides.values()))
    _place_labels(placed, process)
    return placed


def _place_stubs(
    process: Process,
    placed: Placed,
    stub_conns: list[Conn],
    chains: dict[str, list[str]],
    hosts: dict[str, list[Conn]],
    local: set[str],
) -> None:
    """Each utility stream as a short vertical stub on the step it serves (its host): from a
    flag at the top of the host's stub band down to the symbol (the box), the block ports it
    passes through on the way; several stubs on one host spread over the symbol's width."""
    for host, conns in hosts.items():
        node = placed.nodes.get(host)
        if node is None:
            continue
        drawing = _drawing(process, host, process.kinds.get(host, ""))
        if isinstance(drawing, Symbol):
            area = _symbol_area(node)
            segments, ellipses = _outline(drawing, area)
            sx = [p[0] for seg in segments for p in seg]
            sx += [c[0] + s * rx for c, rx, _, _ in ellipses for s in (-1, 1)]
            x0, x1 = min(sx), max(sx)
        elif drawing == JUNCTION:
            x0 = x1 = node.x + node.width / 2
        else:
            x0, x1 = node.x + 3.0, node.x + node.width - 3.0
        conns = sorted(conns, key=lambda c: (c.src[0] not in local, c.stream.id))
        for fraction, c in zip(spread(len(conns)), conns, strict=True):
            placed.stub_side[c.stream.id] = 0 if len(conns) == 1 else (-1 if fraction < 0.5 else 1)
            x = round(x0 + (x1 - x0) * fraction, 3)
            y = node.y + STUB_BAND
            if isinstance(drawing, Symbol):
                y = _contact(drawing, _symbol_area(node), "x", x, "top") or node.y + node.port_top
            elif drawing == JUNCTION:
                y = node.y + node.height / 2
            flag = (x, round(node.y + 3.0, 3))
            touch = (x, round(y, 3))
            keys = chains[c.stream.id]
            for i, key in enumerate(keys):
                f = (i + 1) / len(keys)
                placed.port_points[key] = (x, round(flag[1] + (touch[1] - flag[1]) * f, 3))
            supply = c.src[0] in local
            terminal = c.src if supply else c.dst
            placed.port_points[f"{terminal[0]}.{terminal[1]}"] = flag
            first = placed.port_points[keys[0]]
            placed.routes[c.stream.id] = [flag, first] if supply else [first, flag]
            for outer, inner in zip(keys, keys[1:], strict=False):
                placed.delegations[inner] = [placed.port_points[outer], placed.port_points[inner]]
            placed.stubs[c.stream.id] = (terminal[0], flag, touch)
        placed.hosts.add(host)


def _on_sheet(placed: Placed, fixed: bool) -> None:
    """Choose the sheet and move the drawing into its drawing area (a layout with pins stays)."""
    from chemeascode.domains.process.pfd_sheet import choose_sheet

    sheet = choose_sheet(placed.bounds, placed.table, fixed=fixed)
    placed.sheet = sheet
    dx, dy = sheet.dx, sheet.dy
    if not dx and not dy:
        return

    def move(points: list[tuple[float, float]]) -> list[tuple[float, float]]:
        return [(round(x + dx, 3), round(y + dy, 3)) for x, y in points]

    for node in placed.nodes.values():
        node.x, node.y = round(node.x + dx, 3), round(node.y + dy, 3)
    placed.routes = {k: move(v) for k, v in placed.routes.items()}
    placed.delegations = {k: move(v) for k, v in placed.delegations.items()}
    placed.port_points = {k: move([v])[0] for k, v in placed.port_points.items()}
    placed.stubs = {k: (t, move([f])[0], move([p])[0]) for k, (t, f, p) in placed.stubs.items()}
    x0, y0, x1, y1 = placed.bounds
    placed.bounds = (x0 + dx, y0 + dy, x1 + dx, y1 + dy)


LABEL_SIZE = 2.2
#: The text size of a utility stub's flag (the utility's id).
FLAG_SIZE = 2.2


def _place_labels(placed: Placed, process: Process) -> None:
    """Each stream label at the first free candidate along its route: around the middle of the
    longest horizontal runs first (above, then below), then beside vertical runs. Free means off
    every line, node and label placed before; with none free, the one hitting fewest."""
    lines = [*placed.routes.values(), *placed.delegations.values()]
    segments = [(a, b) for pts in lines for a, b in zip(pts, pts[1:], strict=False)]
    boxes = placed.obstacles(process)
    for sid, (terminal, (x, y), (_, ty)) in placed.stubs.items():  # flags; stub labels beside
        fx0, fy0, fx1, fy1 = _flag_box(terminal, x, y, placed.stub_side[sid])
        boxes.append((fx0, fy0, fx1, fy1))
        side = placed.stub_side[sid] or 1
        half = _text_width(placed.texts.get(sid, sid), LABEL_SIZE) / 2
        lx, ly = x + side * (1.0 + half), (y + ty) / 2 + 1.1
        placed.labels[sid] = (round(lx, 3), round(ly, 3))
        boxes.append((lx - half - 0.3, ly - LABEL_SIZE - 0.2, lx + half + 0.3, ly + 0.1))

    def hits(box: tuple[float, float, float, float]) -> int:
        x0, y0, x1, y1 = box
        count = 0
        for a, b in segments:
            if max(x0, min(a[0], b[0])) <= min(x1, max(a[0], b[0])) and max(
                y0, min(a[1], b[1])
            ) <= min(y1, max(a[1], b[1])):
                count += 1
        for bx0, by0, bx1, by1 in boxes:
            if max(x0, bx0) <= min(x1, bx1) and max(y0, by0) <= min(y1, by1):
                count += 1
        return count

    for stream_id, points in placed.routes.items():
        if len(points) < 2 or stream_id in placed.stubs:
            continue
        half = _text_width(placed.texts.get(stream_id, stream_id), LABEL_SIZE) / 2
        runs = sorted(
            zip(points, points[1:], strict=False),
            key=lambda s: (s[0][1] != s[1][1], -abs(s[1][0] - s[0][0]) - abs(s[1][1] - s[0][1])),
        )
        candidates: list[tuple[float, float]] = []
        for a, b in runs:
            for f in (0.5, 0.3, 0.7, 0.15, 0.85):
                x, y = a[0] + (b[0] - a[0]) * f, a[1] + (b[1] - a[1]) * f
                if a[1] == b[1]:
                    candidates += [(x, y - 1.0), (x, y + 1.2 + LABEL_SIZE)]
                else:
                    candidates += [(x + 1.0 + half, y + 1.1), (x - 1.0 - half, y + 1.1)]
        best = None
        for x, y in candidates:
            box = (x - half - 0.3, y - LABEL_SIZE - 0.2, x + half + 0.3, y + 0.1)
            count = hits(box)
            if best is None or count < best[0]:
                best = (count, (round(x, 3), round(y, 3)), box)
            if count == 0:
                break
        assert best is not None
        placed.labels[stream_id] = best[1]
        boxes.append(best[2])


def _flag_box(terminal: str, x: float, y: float, side: int) -> tuple[float, float, float, float]:
    """The box of a utility flag's text at the top end (x, y) of its stub."""
    w = _text_width(terminal, FLAG_SIZE)
    if side == 0:
        return (x - w / 2 - 0.3, y - FLAG_SIZE - 1.0, x + w / 2 + 0.3, y - 0.6)
    x0 = x - 0.8 - w if side < 0 else x + 0.8
    return (x0 - 0.3, y - FLAG_SIZE / 2 - 0.4, x0 + w + 0.3, y + FLAG_SIZE / 2 + 0.4)


def _clean(points: list[tuple[float, float]]) -> list[tuple[float, float]]:
    out: list[tuple[float, float]] = []
    for x, y in points:
        p = (round(x, 3), round(y, 3))
        if not out or p != out[-1]:
            out.append(p)
    return out


# -- the DEXPI model ----------------------------------------------------------------------------


def _port_class(kind: str) -> type:
    return {"material": C.MaterialPort, "energy": C.EnergyPort, "information": C.InformationPort}[
        kind
    ]


def _connection_class(kind: str) -> type:
    return {"material": C.Stream, "energy": C.EnergyFlow, "information": C.InformationFlow}[kind]


def _stream_values(process: Process, stream: StreamDef) -> dict[str, list[Any]]:
    """The stream's QualifiedValues, by DEXPI property, one per case that gives the property.

    Stale values (``cheme.process-calculated-stale``) are left out (:func:`_calculated` lists
    them). A flow on a mole basis goes to ``moleFlow`` (``(case, flow, kmol/h)``, per component
    by :func:`_material_state`) where the case has a current mole-fraction composition, else to
    ``massFlow`` converted with the molar masses (:func:`.model.stream_flows`); a normal volume
    flow likewise, as the moles at the normal conditions: DEXPI's volume flow is the actual one.
    A flow that cannot be converted is not exported: ``notes`` says so."""
    from chemeascode.domains.process.model import GAS_CONSTANT, stream_flows
    from chemeascode.domains.process.props import stale

    fs = process.flowsheet
    values: dict[str, list[Any]] = {}
    for case, state in stream.state.items():
        sid = f"{stream.id}.{case}"
        old = set(stale(process, stream, case))
        if state.pressure is not None and "pressure" not in old:
            unit = state.pressure.unit or fs.units.pressure
            factor, kind = PRESSURE_UNITS.get(unit, (1.0, "absolute"))
            dexpi_unit = (
                C.PressureAbsoluteUnit.KILOPASCAL
                if kind == "absolute"
                else C.PressureGaugeUnit.KILOPASCAL
            )
            values.setdefault("pressure", []).append(
                _quantity(
                    f"{sid}.pressure",
                    round(state.pressure.value * factor, 9),
                    dexpi_unit,
                    case,
                    state.pressure,
                    f"{state.pressure.value:g} {unit}",
                )
            )
        if state.temperature is not None and "temperature" not in old:
            unit = state.temperature.unit or fs.units.temperature
            values.setdefault("temperature", []).append(
                _quantity(
                    f"{sid}.temperature",
                    state.temperature.value,
                    C.TemperatureUnit.KELVIN if unit == "K" else C.TemperatureUnit.DEGREECELSIUS,
                    case,
                    state.temperature,
                    f"{state.temperature.value:g} {unit}",
                )
            )
        if state.flow is not None and stream.kind == "material" and "flow" not in old:
            unit = state.flow.unit or fs.units.flow
            basis, factor = FLOW_UNITS.get(unit, ("mass", 1.0))
            shown = f"{state.flow.value:g} {unit}"
            kmol_h: float | None = state.flow.value * factor
            if basis == "normal_volume":
                nc = fs.units.normal_conditions
                kmol_h = None
                if nc is not None:
                    shown += f" (normal: {nc.temperature:g} K, {nc.pressure:g} kPa(a), {nc.basis})"
                    kmol_h = (
                        state.flow.value * factor * nc.pressure / (GAS_CONSTANT * nc.temperature)
                    )
            comp = state.composition if "composition" not in old else None
            if basis == "mass":
                values.setdefault("massFlow", []).append(
                    _quantity(
                        f"{sid}.flow",
                        round(state.flow.value * factor, 9),
                        C.MassFlowRateUnit.KILOGRAMPERHOUR,
                        case,
                        state.flow,
                        shown,
                    )
                )
            elif kmol_h is None:
                values.setdefault("notes", []).append(
                    f"flow not exported ({case}): {shown}, no units.normal_conditions"
                )
            elif comp is not None and comp.basis == "mole_fraction":
                values.setdefault("moleFlow", []).append((case, state.flow, kmol_h))
            elif (total := stream_flows(process, stream, case).total) is not None and comp:
                values.setdefault("massFlow", []).append(
                    _quantity(
                        f"{sid}.flow",
                        round(total, 9),
                        C.MassFlowRateUnit.KILOGRAMPERHOUR,
                        case,
                        state.flow,
                        f"{shown} = {total:.6g} kg/h with the components' molar masses",
                    )
                )
            else:
                values.setdefault("notes", []).append(
                    f"flow not exported ({case}): {shown}, no current composition and molar "
                    "masses to convert it to a mass flow"
                )
        if state.duty is not None and stream.kind == "energy" and "duty" not in old:
            unit = state.duty.unit or fs.units.duty
            values.setdefault("duty", []).append(
                _quantity(
                    f"{sid}.duty",
                    state.duty.value,
                    {"W": C.PowerUnit.WATT, "kW": C.PowerUnit.KILOWATT, "MW": C.PowerUnit.MEGAWATT}[
                        unit
                    ]
                    if unit in ("W", "kW", "MW")
                    else C.PowerUnit.KILOWATT,
                    case,
                    state.duty,
                    f"{state.duty.value:g} {unit}",
                )
            )
    return values


def _material_state(process: Process, stream: StreamDef, mole: list[Any]) -> Any:
    """A MaterialState holding the stream's current compositions (one QualifiedValue per case)
    and its molar flow by component (*mole*: ``(case, flow, kmol/h)``), or None when the stream
    gives neither."""
    from chemeascode.domains.process.props import stale

    template = process.templates().get(stream.template or "")
    order = list(template.components) if template else []
    moles, masses, mole_flows = [], [], []
    for case, state in stream.state.items():
        comp = state.composition
        if comp is None or "composition" in stale(process, stream, case):
            continue
        names = order + [n for n in comp.values if n not in order]
        vector = [comp.values.get(n, 0.0) for n in names]
        qv = C.QualifiedValue(
            id=f"{stream.id}.{case}.composition",
            value=C.PhysicalQuantityVector(values=vector, unit=C.RatioUnit.FRACTION),
            case=case,
            scope=C.Scope.DESIGN,
            provenance=_provenance(comp),
            displayText=", ".join(f"{n} {v:g}" for n, v in zip(names, vector, strict=True)),
            description=_text(
                f"{_class(comp)}; basis {comp.basis}; components "
                f"{' '.join(names)}" + (f"; source: {comp.source}" if comp.source else "")
            ),
        )
        (moles if comp.basis == "mole_fraction" else masses).append(qv)
        for flow_case, flow, kmol_h in mole:
            if flow_case == case and comp.basis == "mole_fraction":
                for name, x in zip(names, vector, strict=True):
                    mole_flows.append(
                        _quantity(
                            f"{stream.id}.{case}.moleFlow.{name}",
                            round(kmol_h / 3600.0 * x, 12),
                            C.MoleFlowRateUnit.KILOMOLEPERSECOND,
                            case,
                            flow,
                            f"{name}: {kmol_h * x:g} kmol/h",
                        )
                    )
    calc = _calculated(process, stream)
    if not moles and not masses and not any(calc.values()):
        return None
    composition = (
        C.Composition(
            id=f"{stream.id}.composition",
            display=C.CompositionDisplay.FRACTION
            if hasattr(C.CompositionDisplay, "FRACTION")
            else list(C.CompositionDisplay)[0],
            moleFractions=moles,
            massFractions=masses,
            moleFlow=mole_flows,
        )
        if moles or masses
        else None
    )
    state = C.MaterialStateType(
        id=f"{stream.id}.state",
        identifier=stream.id,
        label=stream.title or stream.id,
        description=_text("\n".join([f"State of stream {stream.id}", *calc["lines"]])),
        composition=composition,
        density=calc["density"],
        specificEnthalpy=calc["specificEnthalpy"],
    )
    return C.MaterialState(
        id=f"{stream.id}.material-state",
        identifier=stream.id,
        label=stream.title or stream.id,
        description=f"State of stream {stream.id}",
        state=state,
        phases=calc["phases"],
    )


#: Calculated values with a DEXPI ``MaterialStateType`` property: name -> (property, unit).
_CALCULATED_PROPERTIES = {
    "density": ("density", C.DensityUnit.KILOGRAMPERMETRECUBED, "kg/m3"),
    # DEXPI binds specificEnthalpy to mass units: kJ/kmol is divided by the molar mass
    "enthalpy": ("specificEnthalpy", C.MassSpecificEnergyUnit.KILOJOULEPERKILOGRAM, "kJ/kmol"),
}
_PHASES = {"vapor": ["vapor"], "liquid": ["liquid"], "two-phase": ["vapor", "liquid"]}
_PHASE_LABELS = {"vapor": "Vapour", "liquid": "Liquid"}


def _calculated(process: Process, stream: StreamDef) -> dict[str, list[Any]]:
    """The stream's calculated values (``state.calculated``) and phase for its MaterialState.

    Density and enthalpy become ``QualifiedValue`` s of the state type (``density``,
    ``specificEnthalpy``, with the YAML provenance, one per case); DEXPI binds the specific
    enthalpy to mass units, so kJ/kmol is divided by the case's molar mass (the original value
    stays in the display text; without a molar mass it goes to the description). The phase
    becomes one ``MaterialStateType`` per phase present (identifier ``vapor``/``liquid``) in the
    material state's ``phases``, the case and vapour fraction in its description. DEXPI 2.0.1 has no
    property for the molar mass (or any other calculated value): those are recorded as
    ``calculated <name> (<case>) = <value> <unit>; ...`` lines in the state type's description.
    Stale values (``cheme.process-calculated-stale``) are not exported: a line
    ``stale, not exported (<case>): <names>`` says which were left out.
    """
    from chemeascode.domains.process.props import stale

    fs = process.flowsheet
    out: dict[str, list[Any]] = {"density": [], "specificEnthalpy": [], "phases": [], "lines": []}
    phase_cases: dict[str, list[str]] = {}
    for case, state in stream.state.items():
        old = set(stale(process, stream, case))
        if old:
            out["lines"].append(f"stale, not exported ({case}): {', '.join(sorted(old))}")
        molar_mass = state.calculated.get("molar_mass")
        if molar_mass is not None and ("molar_mass" in old or molar_mass.value <= 0):
            molar_mass = None
        for name, q in state.calculated.items():
            if name in old:
                continue
            source = f"; source: {q.source}" if q.source else ""
            mapped = _CALCULATED_PROPERTIES.get(name)
            unit = q.unit or (fs.units.enthalpy if name == "enthalpy" else "")
            value, note = q.value, source
            if name == "enthalpy" and mapped and unit == mapped[2]:
                if molar_mass is None:
                    mapped = None  # DEXPI's specificEnthalpy is per mass: no molar mass, no value
                else:
                    value = round(q.value / molar_mass.value, 9)
                    note = f"; from {q.value:g} kJ/kmol and molar mass {molar_mass.value:g} kg/kmol"
                    ref = fs.units.enthalpy_reference
                    if ref is not None:
                        note += f"; reference {ref.state} {ref.temperature:g} K" + (
                            f" {ref.pressure:g} kPa(a)" if getattr(ref, "pressure", None) else ""
                        )
                    note += source
            if mapped and unit == mapped[2]:
                out[mapped[0]].append(
                    C.QualifiedValue(
                        id=f"{stream.id}.{case}.{name}",
                        value=C.PhysicalQuantity(value=value, unit=mapped[1]),
                        case=case,
                        scope=C.Scope.DESIGN,
                        provenance=_provenance(q),
                        displayText=f"{q.value:g} {unit}",
                        description=_text(f"{_class(q)}{note}"),
                    )
                )
            else:
                out["lines"].append(
                    f"{_class(q)} {name} ({case}) = {q.value:g} {unit}".rstrip() + source
                )
        phase = state.phase
        if phase is not None and "phase" not in old:
            vf = (
                f", vapour fraction {phase.vapor_fraction:g}"
                if phase.vapor_fraction is not None
                else ""
            )
            source = f"; source: {phase.source}" if phase.source else ""
            for name in _PHASES[phase.value]:
                phase_cases.setdefault(name, []).append(
                    f"{case}: {phase.value}{vf}; {phase.provenance}{source}"
                )
    for name, cases in phase_cases.items():
        out["phases"].append(
            C.MaterialStateType(
                id=f"{stream.id}.phase.{name}",
                identifier=name,
                label=_PHASE_LABELS[name],
                description=_text("\n".join(cases)),
            )
        )
    return out


def build_model(process: Process, view: str, meta: dict[str, str]) -> tuple[Any, Placed]:
    """The DEXPI EngineeringModel of *view* (``bfd`` or ``pfd``) and its layout."""
    fs = process.flowsheet
    placed = place(process, view)
    top, inner = _connections(process, view)
    conns = top + inner

    comps = process.components()
    used_templates = {s.template for s in fs.streams if s.template}
    templates = [t for t in process.templates().values() if t.id in used_templates]
    used_comps = []
    for t in templates:
        used_comps += [c for c in t.components if c not in used_comps]
    dexpi_comps = {
        cid: C.PureMaterialComponent(
            id=f"Component_{cid}",
            identifier=cid,
            label=comps[cid].name if cid in comps else cid,
            chEBI_identifier=(comps[cid].chebi or None) if cid in comps else None,
        )
        for cid in used_comps
    }
    dexpi_templates = {}
    lists = []
    for t in templates:
        lst = C.ListOfMaterialComponents(
            id=f"ComponentList_{t.id}",
            component=[dexpi_comps[c] for c in t.components if c in dexpi_comps],
        )
        lists.append(lst)
        dexpi_templates[t.id] = C.MaterialTemplate(
            id=f"Template_{t.id}",
            identifier=t.id,
            label=t.title or t.id,
            description=_text(t.title or t.id),
            listOfComponents=lst,
            numberOfMaterialComponents=len(t.components),
            numberOfPhases=1,
        )

    shells = {c.stream.id: _shell(_connection_class(c.stream.kind), c.stream.id) for c in conns}
    ports: dict[str, Any] = {}  # "NODE.port" -> DEXPI port

    def make_port(node_id: str, port_id: str, connection: Any, template: Any = None) -> Any:
        node = process.nodes[node_id]
        decl = next(p for p in node.ports if p.id == port_id)
        cls = _port_class(decl.kind)
        kwargs: dict[str, Any] = {
            "id": f"{node_id}.{port_id}",
            "identifier": port_id,
            "nominalDirection": C.PortDirection.INLET
            if decl.direction == "in"
            else C.PortDirection.OUTLET,
            "connectorReference": connection,
        }
        if cls is C.MaterialPort and template is not None:
            kwargs["materialTemplateReference"] = template
        port = cls(**kwargs)
        ports[f"{node_id}.{port_id}"] = port
        return port

    for c in conns:
        template = dexpi_templates.get(c.stream.template or "")
        make_port(*c.src, shells[c.stream.id], template)
        make_port(*c.dst, shells[c.stream.id], template)
    delegates: dict[str, Any] = {}
    if view == "pfd":  # outer blocks first, so a delegated port exists before its delegate
        for step in sorted([*fs.blocks, *fs.steps], key=lambda n: len(process.ancestors(n.id))):
            home = process.home(step.id)
            for decl in step.ports if home is not None else []:
                key = f"{home}.{decl.delegates}"
                if not decl.delegates or key not in ports:
                    continue
                outer = ports[key]
                stream = outer.connectorReference
                template = getattr(outer, "materialTemplateReference", None)
                port = make_port(step.id, decl.id, stream, template)
                port.superReference = outer
                outer.subReference = [*outer.subReference, port]
                delegates[f"{step.id}.{decl.id}"] = port

    def owned(node_id: str) -> list[Any]:
        return [p for k, p in ports.items() if k.split(".", 1)[0] == node_id]

    def make_step(item: Any, cls: type, level: Any = None, subs: list[Any] | None = None) -> Any:
        kwargs: dict[str, Any] = {
            "id": item.id,
            "identifier": item.id,
            "label": item.title or item.id,
            "ports": owned(item.id),
        }
        if level is not None:
            kwargs["hierarchyLevel"] = level
        if subs:
            kwargs["subProcessSteps"] = subs
        field_info = cls.model_fields.get("method")
        if field_info is not None:
            kwargs["method"] = step_method(field_info.annotation, getattr(item, "method", None))
        if item.links:
            kwargs["description"] = _text(
                "links: " + ", ".join(f"{lk.target} {lk.ref}" for lk in item.links)
            )
        return cls(**kwargs)

    steps_dexpi: dict[str, Any] = {}
    top_steps = []
    for feed in fs.feeds:
        steps_dexpi[feed.id] = make_step(feed, C.Source)
        top_steps.append(steps_dexpi[feed.id])

    def make_block(block: Any) -> Any:
        """*block* with its steps and, on the PFD, its nested blocks as sub process steps."""
        subs = []
        if view == "pfd":
            for step in process.steps_of(block.id):
                steps_dexpi[step.id] = make_step(
                    step,
                    step_class(step.class_) or C.ProcessStep,
                    C.ProcessStepHierarchyLevel.UNITOPERATION,
                )
                subs.append(steps_dexpi[step.id])
            subs += [make_block(child) for child in process.children(block.id)]
        steps_dexpi[block.id] = make_step(
            block,
            step_class(block.class_) or C.ProcessStep,
            C.ProcessStepHierarchyLevel.PROCESSSECTION,
            subs,
        )
        return steps_dexpi[block.id]

    for block in fs.blocks:
        if process.home(block.id) is None:
            top_steps.append(make_block(block))
    for product in fs.products:
        steps_dexpi[product.id] = make_step(product, C.Sink)
        top_steps.append(steps_dexpi[product.id])

    states = []
    for c in conns:
        stream = c.stream
        # an aggregated connection carries no values: the streams' T, P and states differ, and
        # the stream table and balances read the streams themselves
        single = len(c.represents) == 1
        values = _stream_values(process, stream) if single else {}
        fields_: dict[str, Any] = {
            "identifier": stream.id,
            "label": stream.title or stream.id if single else " ".join(c.represents),
            "source": ports[f"{c.src[0]}.{c.src[1]}"],
            "target": ports[f"{c.dst[0]}.{c.dst[1]}"],
        }
        described = [f"represents: {' '.join(c.represents)}", *values.get("notes", [])]
        by_id = {s.id: s for s in fs.streams}
        links = [lk for sid in c.represents for lk in by_id[sid].links]
        if links:
            described.append("links: " + ", ".join(f"{lk.target} {lk.ref}" for lk in links))
        fields_["description"] = _text("; ".join(described))
        if stream.kind == "material" and not single:
            template = dexpi_templates.get(stream.template or "")
            if template is not None and all(
                by_id[s].template == stream.template for s in c.represents
            ):
                fields_["materialTemplateReference"] = template
        elif stream.kind == "material":
            template = dexpi_templates.get(stream.template or "")
            if template is not None:
                fields_["materialTemplateReference"] = template
            for key in ("massFlow", "volumeFlow", "pressure", "temperature"):
                if values.get(key):
                    fields_[key] = values[key]
            state = _material_state(process, stream, values.get("moleFlow", []))
            if state is not None:
                states.append(state)
                fields_["materialStateReference"] = state
        elif stream.kind == "energy" and values.get("duty"):
            fields_["duty"] = values["duty"]
        for name, value in fields_.items():
            setattr(shells[stream.id], name, value)

    note = C.Note(
        id="cheme_provenance",
        noteText=_text(
            f"generated by cheme process build (generator {GENERATOR_VERSION}, {SCHEMA}) "
            f"view {view}, case {meta.get('case', '')}, source-sha256 {meta.get('source', '')}"
        ),
    )
    fields_meta = {
        "drawingNumber": meta.get("sheet_id") or view.upper(),
        "drawingName": meta.get("sheet_title") or VIEW_TITLES[view],
        "drawingSubTitle": f"{VIEW_TITLES[view]}, case {meta.get('case', '')}",
        "projectName": meta.get("project_name"),
        "projectNumber": meta.get("project_number"),
        "revisionNumber": meta.get("revision"),
    }
    metadata = C.MetaData(
        id=f"MetaData_{view.upper()}",
        **{
            key: _text(value)
            if "MultiLanguageString" in str(C.MetaData.model_fields[key].annotation)
            else value
            for key, value in fields_meta.items()
            if value
        },
    )
    model = C.ProcessModel(
        id=f"ProcessModel_{view.upper()}",
        metaData=metadata,
        notes=[note],
        materialComponents=list(dexpi_comps.values()),
        listsOfMaterialComponents=lists,
        materialTemplates=list(dexpi_templates.values()),
        materialStates=states,
        processSteps=top_steps,
        processConnections=[shells[c.stream.id] for c in conns],
    )
    diagram = _diagram(process, view, model, placed, steps_dexpi, ports, delegates, conns, meta)
    engineering = C.EngineeringModel(
        id=f"EngineeringModel_{view.upper()}",
        conceptualModel=model,
        diagram=diagram,
        exportDateTime=C.Undefined(),
        originatingSystemName="cheme-as-code",
        originatingSystemVendorName="cheme-as-code",
        originatingSystemVersion=f"process generator {GENERATOR_VERSION}",
    )
    return engineering, placed


#: A flow arrowhead: length and half width, mm.
ARROW_L, ARROW_W = 2.6, 0.85


def _arrow(id_: str, tip: tuple[float, float], frm: tuple[float, float]) -> Any:
    """A filled arrowhead with its tip at *tip*, pointing away from *frm*; None for no length."""
    dx, dy = tip[0] - frm[0], tip[1] - frm[1]
    d = math.hypot(dx, dy)
    if d < 1e-6:
        return None
    ux, uy = dx / d, dy / d
    bx, by = tip[0] - ux * ARROW_L, tip[1] - uy * ARROW_L
    corners = [tip, (bx - uy * ARROW_W, by + ux * ARROW_W), (bx + uy * ARROW_W, by - ux * ARROW_W)]
    return C.Polygon(
        id=id_,
        fillStyle=C.FillStyle.SOLID,
        points=[C.Point(x=round(x, 3), y=round(y, 3)) for x, y in corners],
        stroke=_FILL,
    )


def _polyline(id_: str, points: list[tuple[float, float]], stroke: Any) -> Any:
    return C.PolyLine(
        id=id_, points=[C.Point(x=round(x, 3), y=round(y, 3)) for x, y in points], stroke=stroke
    )


def _diagram(process, view, model, placed, steps_dexpi, ports, delegates, conns, meta) -> Any:
    from chemeascode.domains.process import pfd_sheet

    fs = process.flowsheet
    sheet = placed.sheet
    local = local_terminals(process, view)
    positions: dict[str, Any] = {}
    #: inlet ports whose arrowhead the node draws itself (at its symbol), or that need none
    carried: set[str] = set()

    def at(key: str, point: tuple[float, float]) -> Any:
        pos = C.PortNodePosition(
            id=f"Position_{key}",
            position=C.Point(x=round(point[0], 3), y=round(point[1], 3)),
            port=ports[key] if key in ports else delegates[key],
        )
        positions[key] = pos
        return pos

    def port_of(key: str) -> Any:
        return ports.get(key) or delegates.get(key)

    def stroke_of(key: str) -> Any:
        return _PROCESS if isinstance(port_of(key), C.MaterialPort) else _DASH

    def final(key: str) -> bool:
        """Whether the line ending at port *key* ends there (no delegation onward) and gets
        its arrowhead there."""
        port = port_of(key)
        return port is not None and not getattr(port, "subReference", None) and key not in carried

    def labels_of(item_id: str, title: str, cx: float, top: float) -> list[Any]:
        """The step's id and its title, wrapped, centred on *cx* below *top*."""
        texts = [_label(f"Label_{item_id}_id", item_id, cx, top + 2.8, 2.6)]
        for n, line in enumerate(wrap(title)):
            suffix = "" if n == 0 else f"_{n + 1}"
            texts.append(
                _label(
                    f"Label_{item_id}_title{suffix}",
                    line,
                    cx,
                    top + 6.2 + TITLE_LEADING * n,
                    TITLE_SIZE,
                )
            )
        return texts

    def node_group(item_id: str, kind: str, children: list[Any] | None = None) -> Any:
        # a utility drawn as stubs has no node of its own (a stand-in for the port lookups)
        node = placed.nodes.get(item_id) or LNode(item_id, 0.0, 0.0)
        item = process.nodes[item_id]
        own = [k for k in ports if k.split(".", 1)[0] == item_id]
        own += [k for k in delegates if k.split(".", 1)[0] == item_id and k not in own]
        node_positions = []
        for key in own:
            port_id = key.split(".", 1)[1]
            if key in placed.port_points:
                node_positions.append(at(key, placed.port_points[key]))
            elif port_id in node.ins + node.outs:
                node_positions.append(at(key, node.port_point(port_id)))
        title = item.title or item.id
        texts: list[Any] = []
        inner = bool(children)
        drawing = _drawing(process, item_id, kind)
        groups: list[Any]
        if item_id in local:  # a utility: a flag with its id at each stub
            for sid, (terminal, (fx, fy), _) in sorted(placed.stubs.items()):
                if terminal != item_id:
                    continue
                side = placed.stub_side.get(sid, 0)
                at_x = fx if side == 0 else fx + 0.8 * side
                align = {0: "CENTERBOTTOM", -1: "RIGHTCENTER", 1: "LEFTCENTER"}[side]
                at_y = fy - 0.8 if side == 0 else fy
                texts.append(
                    _label(f"Label_{item_id}_{sid}", item_id, at_x, at_y, FLAG_SIZE, align)
                )
            groups = []
        elif isinstance(drawing, Symbol):  # the symbol above its labels, ports joined by stubs
            area = _symbol_area(node)
            drawn = _symbol(f"Drawing_{item_id}_Symbol", drawing, area)
            texts += labels_of(item_id, title, node.x + node.width / 2, area[3])
            segments, ellipses = _outline(drawing, area)
            xs = [p[0] for seg in segments for p in seg]
            xs += [c[0] + s * rx for c, rx, _, _ in ellipses for s in (-1, 1)]
            elements: list[Any] = []
            for port_id in node.ins + node.outs:
                key = f"{item_id}.{port_id}"
                inlet = port_id in node.ins
                px, py = node.port_point(port_id)
                edge = _contact(drawing, area, "y", py, "left" if inlet else "right")
                sx = edge if edge is not None else (min(xs) if inlet else max(xs))
                stroke = stroke_of(key) if port_of(key) is not None else _THIN
                elements.append(
                    _polyline(f"Drawing_{item_id}_Stub_{port_id}", [(px, py), (sx, py)], stroke)
                )
                if inlet:
                    carried.add(key)
                    head = _arrow(f"Drawing_{item_id}_Arrow_{port_id}", (sx, py), (px, py))
                    if head is not None:
                        elements.append(head)
            groups = [drawn, C.Static(id=f"Drawing_{item_id}_Stubs", elements=elements)]
        elif drawing == JUNCTION:  # the streams meet on a short header
            cx = node.x + node.width / 2
            joins = [(f"{item_id}.{p}", node.port_point(p)) for p in node.ins + node.outs]
            joins += [
                (k, p) for k, p in placed.port_points.items() if k.split(".", 1)[0] == item_id
            ]
            elements = []
            for key, (px, py) in joins:
                carried.add(key)
                if px != cx:
                    elements.append(
                        _polyline(
                            f"Drawing_{item_id}_Stub_{key.split('.', 1)[1]}",
                            [(px, py), (cx, py)],
                            stroke_of(key),
                        )
                    )
            ys = sorted(
                {round(py, 3) for _, (px, py) in joins if px != cx} | {node.y + node.height / 2}
            )
            if len(ys) > 1:
                elements.append(
                    _polyline(f"Drawing_{item_id}_Header", [(cx, ys[0]), (cx, ys[-1])], _PROCESS)
                )
            if len(joins) > 2:
                for n, (_, (px, py)) in enumerate(joins):
                    if px != cx:
                        elements.append(
                            C.Ellipse(
                                id=f"Drawing_{item_id}_Dot_{n}",
                                center=C.Point(x=round(cx, 3), y=round(py, 3)),
                                fillStyle=C.FillStyle.SOLID,
                                horizontalSemiAxis=0.7,
                                verticalSemiAxis=0.7,
                                rotation=0.0,
                                stroke=_FILL,
                            )
                        )
            texts.append(
                _label(f"Label_{item_id}_id", item_id, cx, ys[0] - 1.6, 1.8, "CENTERBOTTOM")
            )
            groups = [C.Static(id=f"Drawing_{item_id}_Static", elements=elements)]
        elif kind in ("feed", "product"):  # a terminal: a flag pointing the way the flow goes
            x0, y0 = node.x, node.y
            x1, y1 = node.x + node.width, node.y + node.height
            tip = min(5.0, node.height / 2)
            mid = (y0 + y1) / 2
            outline = [(x0, y0), (x1 - tip, y0), (x1, mid), (x1 - tip, y1), (x0, y1), (x0, y0)]
            elements = [_polyline(f"Drawing_{item_id}_Outline", outline, _LINE)]
            for port_id in node.outs:  # a feed's ports on its pointed side: stubs to the tip
                px, py = node.port_point(port_id)
                half = (y1 - y0) / 2
                ex = x1 - tip * (abs(py - mid) / half) if half else x1
                if px - ex > 0.05:
                    elements.append(
                        _polyline(
                            f"Drawing_{item_id}_Stub_{port_id}",
                            [(ex, py), (px, py)],
                            stroke_of(f"{item_id}.{port_id}"),
                        )
                    )
            texts.append(
                _label(f"Label_{item_id}_id", item_id, (x0 + x1 - tip) / 2, mid - 2.6, 2.2)
            )
            texts.append(
                _label(f"Label_{item_id}_title", title, (x0 + x1 - tip) / 2, mid + 1.4, 2.5)
            )
            groups = [C.Static(id=f"Drawing_{item_id}_Static", elements=elements)]
        elif kind == "step" or not inner:  # a box: generic steps, blocks without steps
            top = node.y + (node.port_top if kind == "step" or view == "pfd" else 0.0)
            cx, cy = node.x + node.width / 2, (top + node.y + node.height) / 2
            if kind == "step":
                lines = wrap(title)
                y = cy - TITLE_LEADING * len(lines) / 2 + 1.2
                texts.append(_label(f"Label_{item_id}_id", item_id, cx, y - 1.2, 2.6))
                for n, line in enumerate(lines):
                    suffix = "" if n == 0 else f"_{n + 1}"
                    texts.append(
                        _label(
                            f"Label_{item_id}_title{suffix}",
                            line,
                            cx,
                            y + 2.6 + TITLE_LEADING * n,
                            TITLE_SIZE,
                        )
                    )
            else:
                texts.append(_label(f"Label_{item_id}_title", title, cx, cy + 1.4, 2.8))
                texts.append(_label(f"Label_{item_id}_id", item_id, cx, cy - 2.6, 2.2))
            groups = [
                _box(
                    f"Drawing_{item_id}",
                    node.x,
                    top,
                    node.x + node.width,
                    node.y + node.height,
                    _LINE,
                )
            ]
        else:  # a block holding steps: a process area, its title in the band above them
            texts.append(
                C.Text(
                    id=f"Label_{item_id}_title",
                    text=f"{item_id}  {title}",
                    position=C.Point(x=round(node.x + 2.5, 3), y=round(node.y + 5.0, 3)),
                    alignment=C.TextAlignment.LEFTCENTER,
                    color=_AREA_GREY,
                    font="Arial",
                    size=2.8,
                    rotation=0.0,
                )
            )
            groups = [
                _box(
                    f"Drawing_{item_id}",
                    node.x,
                    node.y,
                    node.x + node.width,
                    node.y + node.height,
                    _AREA if view == "pfd" else _LINE,
                )
            ]
        groups.append(C.Label(id=f"Drawing_{item_id}_Label", elements=texts))
        groups += children or []
        return C.RepresentationGroup(
            id=f"Drawing_{item_id}",
            represents=steps_dexpi[item_id],
            groups=groups,
            nodePositions=node_positions,
        )

    def delegation_group(key: str) -> Any:
        points = placed.delegations[key]
        port = delegates[key]
        outer_key = port.superReference.id
        step_pos = positions.get(key) or at(
            key, placed.nodes[key.split(".", 1)[0]].port_point(key.split(".", 1)[1])
        )
        outer_pos = positions[outer_key]
        inlet = port.nominalDirection == C.PortDirection.INLET
        line = C.ConnectorLine(
            id=f"Line_delegation_{key}",
            source=outer_pos if inlet else step_pos,
            target=step_pos if inlet else outer_pos,
            innerPoints=[C.Point(x=x, y=y) for x, y in points[1:-1]],
            stroke=stroke_of(key),
        )
        elements = [line]
        if inlet and final(key):
            route = [(outer_pos.position.x, outer_pos.position.y), *points[1:-1]]
            route.append((step_pos.position.x, step_pos.position.y))
            head = _arrow(f"Arrow_delegation_{key}", route[-1], _before(route))
            if head is not None:
                elements.append(head)
        return C.RepresentationGroup(
            id=f"Drawing_delegation_{key}",
            represents=port,
            groups=[C.Static(id=f"Drawing_delegation_{key}_Static", elements=elements)],
        )

    groups: list[Any] = []
    for feed in fs.feeds:
        groups.append(node_group(feed.id, "feed"))

    def block_group(block: Any) -> Any:
        children = []
        if view == "pfd":
            children = [node_group(s.id, "step") for s in process.steps_of(block.id)]
            children += [block_group(child) for child in process.children(block.id)]
        return node_group(block.id, "block", children)

    for block in fs.blocks:
        if process.home(block.id) is None:
            groups.append(block_group(block))
    for product in fs.products:
        groups.append(node_group(product.id, "product"))
    if view == "pfd":
        # delegation lines inside their step's (nested block's) group, once both positions exist
        by_id: dict[str, Any] = {}
        todo = list(groups)
        while todo:
            group = todo.pop()
            by_id[group.id] = group
            todo += [g for g in group.groups if isinstance(g, C.RepresentationGroup)]
        for key in placed.delegations:
            holder = by_id[f"Drawing_{key.split('.', 1)[0]}"]
            holder.groups = [*holder.groups, delegation_group(key)]
    for c in conns:
        points = placed.routes[c.stream.id]
        src_key, dst_key = f"{c.src[0]}.{c.src[1]}", f"{c.dst[0]}.{c.dst[1]}"
        src = positions.get(src_key)
        dst = positions.get(dst_key)
        if src is None or dst is None or len(points) < 2:
            continue
        stroke = _PROCESS if c.stream.kind == "material" else _DASH
        line = C.ConnectorLine(
            id=f"Line_{c.stream.id}",
            source=src,
            target=dst,
            innerPoints=[C.Point(x=x, y=y) for x, y in points[1:-1]],
            stroke=stroke,
        )
        elements = [line]
        if final(dst_key):
            head = _arrow(f"Arrow_{c.stream.id}", points[-1], _before(points))
            if head is not None:
                elements.append(head)
        lx, ly = placed.labels[c.stream.id]
        pin = getattr(fs.layout, view).get(c.stream.id)
        if pin is not None and pin.label is not None:
            lx, ly = lx + pin.label[0], ly + pin.label[1]
        text = " ".join(c.represents)
        groups.append(
            C.RepresentationGroup(
                id=f"Drawing_{c.stream.id}",
                represents=cast(
                    Any,
                    model.processConnections[
                        [s.id for s in model.processConnections].index(c.stream.id)
                    ],
                ),
                groups=[
                    C.Static(id=f"Drawing_{c.stream.id}_Static", elements=elements),
                    C.Label(
                        id=f"Drawing_{c.stream.id}_Label",
                        elements=[
                            _label(f"Label_{c.stream.id}", text, lx, ly, LABEL_SIZE, "CENTERBOTTOM")
                        ],
                    ),
                ],
            )
        )
    title = fs.title or meta.get("plant", "")
    groups += pfd_sheet.frame(sheet)
    if placed.table is not None and placed.table.columns:
        groups += pfd_sheet.draw_table(placed.table, *sheet.table_at, sheet.table_width)
    groups += pfd_sheet.title_block(
        sheet,
        {
            "title": title or VIEW_TITLES[view],
            "subtitle": VIEW_TITLES[view]
            + (
                f": {meta['sheet_title']}"
                if meta.get("sheet_title") and meta.get("sheet_title") != VIEW_TITLES[view]
                else ""
            ),
            "project": meta.get("project_name") or meta.get("plant", ""),
            "drawing": meta.get("sheet_id") or view.upper(),
            "case": meta.get("case", ""),
            "sheet": f"{sheet.name}, 1 of 1",
            "note": "generated from process/flowsheet.yaml by cheme process build -- do not edit",
        },
    )
    return C.Diagram(
        id=f"Diagram_{view.upper()}",
        name=meta.get("sheet_title") or VIEW_TITLES[view],
        represents=model,
        minX=0.0,
        minY=0.0,
        maxX=float(sheet.width),
        maxY=float(sheet.height),
        backgroundColor=C.Color(r=255, g=255, b=255),
        groups=groups,
    )


def _before(points: list[tuple[float, float]]) -> tuple[float, float]:
    """The last point of *points* before its end that differs from the end."""
    end = points[-1]
    for p in reversed(points[:-1]):
        if abs(p[0] - end[0]) > 1e-6 or abs(p[1] - end[1]) > 1e-6:
            return p
    return end
