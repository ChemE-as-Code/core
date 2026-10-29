"""``cheme crossings``: show every crossing of two drawn lines by a gap in one of them.

A P&ID shows that two lines cross without joining by breaking one of them for a short gap. The
rule here: a pipe runs through and an instrument line (signal, measuring, pilot line) is
broken where they cross; of two lines of the same kind the horizontal one runs through and the
vertical one is broken. A gap is drawn as on the reference sheets: the line's ConnectorLine is
split into pieces in the same group, the first keeping the Source, the last the Target.

The command first joins the pieces of every gap drawn in the line that should run through (a
gap already in the right line stays as it is), then cuts the gap the rule asks for at every
crossing without one. Gaps away from a
crossing, slanted segments, corners and tees are left alone. Pure XML transform like ``cheme
move``: written back as read except for the change, then ``cheme fmt``.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from pathlib import Path

from lxml import etree

from chemeascode.domains.piping.authoring._xml import fmt_num, point_xy, points
from chemeascode.domains.piping.authoring.edit import (
    Document,
    EditResult,
    finish,
    in_catalogue,
)

CONNECTOR = "Core/Diagram.ConnectorLine"
GAP = 3.0
TOL = 0.05
#: A cut keeps at least this much line on either side of its gap (mm).
STUB = 0.5

Point = tuple[float, float]


@dataclass
class Piece:
    """One ConnectorLine: its points (Source and Target node positions included)."""

    element: etree._Element
    owner: str
    kind: str  # "pipe" or "instrument"
    pts: list[Point]
    has_source: bool
    has_target: bool
    cuts: list[tuple[int, Point]] = field(default_factory=list)

    @property
    def group(self) -> etree._Element:
        return self.element.getparent()


def _owner(element: etree._Element, types: dict[str, str]) -> tuple[str, str]:
    """The object the line draws and whether it is a pipe."""
    for ancestor in element.iterancestors("Object"):
        reference = ancestor.find("References[@property='Represents']")
        if reference is not None:
            owner = reference.get("objects", "").split()[0].lstrip("#")
            kind = "pipe" if types.get(owner, "").endswith(".Pipe") else "instrument"
            return owner, kind
    return "", "instrument"


def _node_positions(root: etree._Element) -> dict[str, Point]:
    found: dict[str, Point] = {}
    for o in root.iter("Object"):
        if not o.get("type", "").endswith("NodePosition"):
            continue
        value = o.find("Data[@property='Position']/AggregatedDataValue")
        xy = point_xy(value) if value is not None else None
        if xy is None:
            continue
        found[o.get("id", "")] = xy
        node = o.find("References[@property='Node']")
        if node is not None:
            found.setdefault(node.get("objects", "").lstrip("#"), xy)
    return found


def _ref(element: etree._Element, prop: str) -> etree._Element | None:
    return element.find(f"References[@property='{prop}']")


def _inner(element: etree._Element) -> list[Point]:
    data = element.find("Data[@property='InnerPoints']")
    if data is None:
        return []
    return [xy for v in data.findall("AggregatedDataValue") if (xy := point_xy(v)) is not None]


def _pieces(root: etree._Element) -> list[Piece]:
    types = {o.get("id"): o.get("type", "") for o in root.iter("Object") if o.get("id")}
    nodes = _node_positions(root)
    found = []
    for element in root.iter("Object"):
        if element.get("type") != CONNECTOR or in_catalogue(element):
            continue
        pts = _inner(element)
        source, target = _ref(element, "Source"), _ref(element, "Target")
        if source is not None:
            xy = nodes.get(source.get("objects", "").lstrip("#"))
            if xy is None:
                continue  # a line whose start is not drawn: leave it alone
            pts.insert(0, xy)
        if target is not None:
            xy = nodes.get(target.get("objects", "").lstrip("#"))
            if xy is None:
                continue
            pts.append(xy)
        if len(pts) < 2:
            continue
        owner, kind = _owner(element, types)
        found.append(Piece(element, owner, kind, pts, source is not None, target is not None))
    return found


def _axis(p: Point, q: Point) -> str | None:
    if abs(p[1] - q[1]) < TOL and abs(p[0] - q[0]) >= TOL:
        return "h"
    if abs(p[0] - q[0]) < TOL and abs(p[1] - q[1]) >= TOL:
        return "v"
    return None


def _segments(pieces: list[Piece]) -> list[tuple[Piece, int, str, Point, Point]]:
    out = []
    for piece in pieces:
        for i, (p, q) in enumerate(zip(piece.pts, piece.pts[1:], strict=False)):
            axis = _axis(p, q)
            if axis:
                out.append((piece, i, axis, p, q))
    return out


def _inside(value: float, a: float, b: float) -> bool:
    return min(a, b) + TOL < value < max(a, b) - TOL


def _met(point: Point, ends: list[Point]) -> bool:
    """Is *point* the end of two pieces (its own and another)?"""
    return sum(abs(e[0] - point[0]) < TOL and abs(e[1] - point[1]) < TOL for e in ends) >= 2


def _crossing_line(point: Point, axis: str, owner: str, segments) -> Piece | None:
    """The line of another object running across *axis* through *point* (interior), if any."""
    x, y = point
    for piece, _, other, p, q in segments:
        if piece.owner == owner or other == axis:
            continue
        if other == "h" and abs(p[1] - y) < TOL and _inside(x, p[0], q[0]):
            return piece
        if other == "v" and abs(p[0] - x) < TOL and _inside(y, p[1], q[1]):
            return piece
    return None


def _set_inner(element: etree._Element, xy: list[Point]) -> None:
    data = element.find("Data[@property='InnerPoints']")
    if not xy:
        if data is not None:
            element.remove(data)
        return
    new = points("InnerPoints", xy)
    if data is not None:
        element.replace(data, new)
        return
    source = _ref(element, "Source")
    element.insert(element.index(source) + 1 if source is not None else 0, new)


def _referenced(root: etree._Element, object_id: str) -> bool:
    needle = f"#{object_id}"
    return any(needle in (r.get("objects") or "").split() for r in root.iter("References"))


def _heal(doc: Document, gap: float) -> int:
    """Join the pieces of every gap that sits on a crossing; the number joined."""
    joined = 0
    while True:
        pieces = _pieces(doc.root)
        segments = _segments(pieces)
        by_group: dict[etree._Element, list[Piece]] = {}
        for piece in pieces:
            by_group.setdefault(piece.group, []).append(piece)
        pairs, used = [], set()
        for group in by_group.values():
            for a in group:
                if a.has_target or id(a) in used:
                    continue
                for b in group:
                    if b is a or b.has_source or id(b) in used or b.owner != a.owner:
                        continue
                    # a piece without Source or Target may be drawn either way round
                    ways = [b.pts] + ([b.pts[::-1]] if not b.has_target else [])
                    for bpts in ways:
                        end, start = a.pts[-1], bpts[0]
                        axis = _axis(a.pts[-2], end)
                        if axis is None or axis != _axis(start, bpts[1]):
                            continue
                        length = abs(start[0] - end[0]) + abs(start[1] - end[1])
                        if length > gap + 0.6 or (length >= TOL and _axis(end, start) != axis):
                            continue
                        middle = ((end[0] + start[0]) / 2, (end[1] + start[1]) / 2)
                        other = _crossing_line(middle, axis, a.owner, segments)
                        # a gap already in the line the rule breaks stays
                        if other is None or _loses(a, axis, other):
                            continue
                        if not _referenced(doc.root, b.element.get("id", "")):
                            pairs.append((a, b, bpts))
                            used.update((id(a), id(b)))
                            break
                    if id(a) in used:
                        break
        if not pairs:
            return joined
        for a, b, bpts in pairs:
            merged = a.pts[:-1] + bpts[1:]
            inner = merged[1 if a.has_source else 0 : len(merged) - (1 if b.has_target else 0)]
            _set_inner(a.element, inner)
            target = _ref(b.element, "Target")
            if target is not None:
                a.element.append(target)
            b.group.remove(b.element)
            joined += 1


def _drop_fillers(doc: Document, gap: float) -> int:
    """Remove the short pieces that fill a gap the rule asks for: a straight piece without
    Source or Target, no longer than a gap, lying on a crossing where its line is the one
    broken, between two pieces of its own line that end at its ends."""
    pieces = _pieces(doc.root)
    segments = _segments(pieces)
    ends: dict[tuple[etree._Element, str], list[Point]] = {}
    for piece in pieces:
        ends.setdefault((piece.group, piece.owner), []).extend((piece.pts[0], piece.pts[-1]))
    dropped = 0
    for piece in pieces:
        if piece.has_source or piece.has_target or len(piece.pts) != 2:
            continue
        p, q = piece.pts
        axis = _axis(p, q)
        if axis is None or abs(p[0] - q[0]) + abs(p[1] - q[1]) > gap + 0.6:
            continue
        middle = ((p[0] + q[0]) / 2, (p[1] + q[1]) / 2)
        other = _crossing_line(middle, axis, piece.owner, segments)
        if other is None or not _loses(piece, axis, other):
            continue
        siblings = ends[(piece.group, piece.owner)]
        if (
            _met(p, siblings)
            and _met(q, siblings)
            and not _referenced(doc.root, piece.element.get("id", ""))
        ):
            piece.group.remove(piece.element)
            dropped += 1
    return dropped


def _loses(piece: Piece, axis: str, other: Piece) -> bool:
    """Is *piece* (on *axis*) the line broken where it crosses *other*?"""
    if piece.kind != other.kind:
        return piece.kind == "instrument"
    return axis == "v"


def _plan_cuts(pieces: list[Piece], gap: float, result: EditResult) -> int:
    segments = _segments(pieces)
    horizontal = [s for s in segments if s[2] == "h"]
    vertical = [s for s in segments if s[2] == "v"]
    planned = 0
    half = gap / 2
    for hp, hi, _, h0, h1 in horizontal:
        for vp, vi, _, v0, v1 in vertical:
            if hp.owner == vp.owner:
                continue
            x, y = v0[0], h0[1]
            if not (min(h0[0], h1[0]) + TOL < x < max(h0[0], h1[0]) - TOL):
                continue
            if not (min(v0[1], v1[1]) + TOL < y < max(v0[1], v1[1]) - TOL):
                continue
            loser, index, p, q = (vp, vi, v0, v1) if _loses(vp, "v", hp) else (hp, hi, h0, h1)
            room = min(abs(x - p[0]) + abs(y - p[1]), abs(x - q[0]) + abs(y - q[1]))
            if room < half + STUB:
                result.notes.append(
                    f"crossing at {fmt_num(x)},{fmt_num(y)} too close to a bend or end of "
                    f"{loser.element.get('id')} for a {fmt_num(gap)} mm gap: left as is"
                )
                continue
            loser.cuts.append((index, (x, y)))
            planned += 1
    return planned


def _new_id(root: etree._Element) -> str:
    while True:
        candidate = f"id_{uuid.uuid4().hex}"
        if root.find(f".//Object[@id='{candidate}']") is None:
            return candidate


def _cut(doc: Document, piece: Piece, gap: float) -> int:
    """Split *piece* at its planned cuts; the number of gaps cut."""
    half = gap / 2
    pts = piece.pts
    runs: list[list[Point]] = []
    current = [pts[0]]
    done = 0
    for i in range(len(pts) - 1):
        p, q = pts[i], pts[i + 1]
        dx = (q[0] > p[0]) - (q[0] < p[0])
        dy = (q[1] > p[1]) - (q[1] < p[1])
        along = sorted(
            {abs(c[0] - p[0]) + abs(c[1] - p[1]) for index, c in piece.cuts if index == i}
        )
        # crossings closer than a gap share one longer gap (a line under a bundle of lanes)
        spans: list[list[float]] = []
        for distance in along:
            if spans and distance - spans[-1][1] < gap + 2 * STUB:
                spans[-1][1] = distance
            else:
                spans.append([distance, distance])
        for first, last in spans:
            current.append((p[0] + dx * (first - half), p[1] + dy * (first - half)))
            runs.append(current)
            current = [(p[0] + dx * (last + half), p[1] + dy * (last + half))]
            done += 1
        current.append(q)
    if not done:
        return 0
    runs.append(current)
    element = piece.element
    parent = element.getparent()
    position = parent.index(element)
    source, target = _ref(element, "Source"), _ref(element, "Target")
    for n, run in enumerate(runs):
        first, final = n == 0, n == len(runs) - 1
        if first:
            new = element
        else:
            new = etree.fromstring(etree.tostring(element))
            new.set("id", _new_id(doc.root))
            new.tail = element.tail
            parent.insert(position + n, new)
        if not first and _ref(new, "Source") is not None:
            new.remove(_ref(new, "Source"))
        if not final and _ref(new, "Target") is not None:
            new.remove(_ref(new, "Target"))
        start = 1 if first and source is not None else 0
        end = len(run) - (1 if final and target is not None else 0)
        _set_inner(new, run[start:end])
    return done


def apply_crossings(
    path: Path,
    *,
    gap: float = GAP,
    write: bool = True,
    name: str | None = None,
    fmt: bool = True,
) -> EditResult:
    """Join the gaps on crossings, then cut one gap per crossing by the rule."""
    if not gap > 0:
        raise ValueError(f"--gap must be positive, got {gap}")
    doc = Document.load(path, name)
    result = EditResult(doc.name)
    dropped = _drop_fillers(doc, gap)
    joined = _heal(doc, gap)
    pieces = _pieces(doc.root)
    _plan_cuts(pieces, gap, result)
    cut = sum(_cut(doc, p, gap) for p in pieces if p.cuts)
    result.notes = list(dict.fromkeys(result.notes))
    result.changes.append(
        f"{doc.name}: {dropped} gap filler(s) removed, {joined} gap(s) joined, {cut} gap(s) cut "
        f"({fmt_num(gap)} mm; pipes run through instrument lines, horizontal through vertical)"
    )
    if not dropped and not joined and not cut:
        result.changes[-1] = f"{doc.name}: every crossing already shown by the rule"
        return result
    return finish(doc, result, write=write, fmt=fmt)
