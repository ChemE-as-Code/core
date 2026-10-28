"""Steel in the 3D model: open frames (``layout/structures.yaml``), building walls, pipe rack
bents, and access platforms with ladders around vertical items.

Pure geometry. Every solid is a model part (``member``: a straight section from ``start`` to
``end`` with ``profile`` [b, h] and ``section``; ``box``; ``cylinder``; ``annulus``: a ring
sector, a platform around a vessel) in the site frame. Section sizes are simple defaults by
span, marked ASSUMED: cheme-as-code does not design steel (no loads, no stress).

- **Frames**: a column at every grid point up to the top level; beams along both grid
  directions at each level (only over a platform's ``extent``); a grating per level; bracing
  ``x`` (both diagonals) or ``k`` (to the middle of the beam above) on a side's bays, per
  storey; a handrail at 1.1 m along the outer edges of each level, open where a stair's
  landing or a ladder's head arrives and along an edge another level of the same floor joins
  (:func:`_level_rails`); stairs outside a side
  (switchback flights of at most :data:`MAX_FLIGHT_RISE`, risers of at most :data:`MAX_RISER`
  with the going from the step pace :data:`STEP_PACE`, landings); ladders with a cage above
  :data:`CAGE_ABOVE`, a climb over :data:`LADDER_SINGLE_FLIGHT` in staggered flights of at most
  :data:`LADDER_FLIGHT` with rest landings (ISO 14122-3/-4, ASSUMED); enclosure walls just
  outside the frame.
- **Buildings**: wall panels on the clad sides, cut around the openings; on a clad building a
  roof, door leaves, roller shutters, louvre blades and windows in the openings, and a declared
  overhead crane (runway girders; bridge, carriages, crab and hook as detail).
- **Bunds**: four concrete walls of the area's ``wall_height`` along the inside of its box.
- **Racks**: a bent every ``rack_bent_spacing_m`` (or the rack's ``bent_spacing_m``) along
  each rack: two columns up to the top tier and a beam at each tier (top of steel at the
  tier elevation); a caged access ladder at each free end (declared ``ladders``, else
  proposed).
- **Access proposals** (``source: generated``, ``review_needed``, with a ``reason``): a stair for a
  level at or above :data:`STAIR_ABOVE` or in regular ``use`` that has no connected stair down (none
  where no position reaches the level: that stair is placed by hand); caged ladders for a level with
  fewer than :data:`WAYS_DOWN` connected ways down remote from each other (arriving at least
  :data:`ESCAPE_REMOTE` of the floor's diagonal apart). A way is connected when its top landing (a
  ladder's top) is within :data:`CONNECT` (:data:`LADDER_REACH`) in plan of the level it serves and
  its foot on the level below (or grade) that itself has a connected way down to grade, as the
  escape check counts; a proposed stair stacks on the declared one only where that connects, else it
  stands at a side the level's extent reaches, and starts from the highest level below whose grating
  its foot lands on. In a structure closed by a casing (an enclosure on every side that is no fire
  wall) a level inside the casing (below the top of its walls, its extent inside the frame) cannot
  be stood on: it gets a platform outside the casing (``<level>-out``, :data:`OUTSIDE_PLATFORM` wide
  along the side its extent runs longest on, outside the wall; the casing roof's level on that side
  gets one too, joining it across the wall's top), and the stairs and ladders proposed reach those,
  outside the platforms; a ladder for a casing roof stands just outside the wall. Stairs on a walled
  side stand outside the wall. A proposal never takes an id the structure declares. Guard rails have
  a top rail, and as detail (``lod: 2``) a mid rail, a toe plate and posts; stairs have handrails.
- **Platforms**: declared in a placement's ``access:``, else proposed (``source: generated``,
  ``review_needed: true``) for a vertical vessel, column or filter with nozzles (or valves
  close to its shell) more than :data:`PLATFORM_ABOVE` above its base: nozzles within
  :data:`PLATFORM_GROUP` of each other share a platform whose floor is :data:`NOZZLE_ABOVE_FLOOR`
  below the lowest of them, covering their angles (plus :data:`ARC_MARGIN` either side; all
  round when they spread over more than 270 degrees), with a caged ladder from the level below:
  the lowest one's beside its platform, every other one's standing on the walkway of the
  platform below just before the start of its own arc (the arc below is widened to take its
  foot; :func:`_ladder_angles`).
"""

from __future__ import annotations

import itertools
import math
import re
from typing import Any

from chemeascode.domains.spatial.schemas import SIDES

Vec = tuple[float, float, float]

#: HEB sections by the longest span they carry, m -> (name, b, h) in m. ASSUMED defaults.
BEAMS = ((4.0, "HEB200", 0.2, 0.2), (6.0, "HEB300", 0.3, 0.3), (9.0, "HEB400", 0.3, 0.4))
BEAM_LARGEST = ("HEB500", 0.3, 0.5)
COLUMNS = ((6.0, "HEB300", 0.3, 0.3), (9.0, "HEB400", 0.3, 0.4))
COLUMN_LARGEST = ("HEB500", 0.3, 0.5)
BRACE = ("L100x10", 0.1, 0.1)
HANDRAIL = ("RHS50x50", 0.05, 0.05)
HANDRAIL_HEIGHT = 1.1
GRATING = 0.03
#: Highest rise of one stair flight between landings, m (ISO 14122-3: at most 3 m; OSHA
#: 1910.25 asks a landing every 3.7 m). ASSUMED until the site's standard replaces it.
MAX_FLIGHT_RISE = 3.0
#: Highest riser of a stair step, m: with the going from :data:`STEP_PACE` the pitch stays at
#: most about 37 degrees and the going at least 0.25 m (ISO 14122-3 prefers 30 to 38 degrees;
#: OSHA 1910.25 asks treads of 0.241 m or more). ASSUMED.
MAX_RISER = 0.19
#: Step pace of a stair, g + 2h, m: the middle of ISO 14122-3's 0.60 to 0.66 m. ASSUMED.
STEP_PACE = 0.63
#: A ladder this tall or more has a cage (or a fall-arrest system), m (ISO 14122-4 asks
#: protection above 3 m of climb). ASSUMED.
CAGE_ABOVE = 3.0
#: The tallest climb of a single-flight fixed ladder, m; a taller one is split into staggered
#: flights of at most :data:`LADDER_FLIGHT` with a rest landing between them (ISO 14122-4:
#: single flight up to 10 m, multiple flights at most 6 m each). ASSUMED until the site's
#: standard replaces it.
LADDER_SINGLE_FLIGHT = 10.0
#: The tallest flight of a multiple-flight ladder, m (ISO 14122-4). ASSUMED.
LADDER_FLIGHT = 6.0
#: How far the flights of a multiple-flight ladder stand apart, m (rail centre to rail centre
#: across, room for the rest landing between them). ASSUMED.
LADDER_STAGGER = 0.75
LADDER_WIDTH = 0.45
PLATFORM_ABOVE = 2.5
PLATFORM_GROUP = 1.5
NOZZLE_ABOVE_FLOOR = 1.0
ARC_MARGIN = 30.0
PLATFORM_WIDTH = 1.0
MIDRAIL_HEIGHT = 0.55
TOE_PLATE = 0.1
#: Handrail posts at most this far apart, m.
POST_PITCH = 1.8
#: A level this high or higher (m) is reached by a stair, not a ladder (ASSUMED).
STAIR_ABOVE = 6.0
#: Ways down every platform needs (ASSUMED).
WAYS_DOWN = 2
#: Width of a platform proposed outside a casing wall, m (ASSUMED).
OUTSIDE_PLATFORM = 1.5
#: Walking surfaces closer than this in plan join (a stair landing onto a platform, two
#: platforms across a casing wall's top), m.
CONNECT = 0.3
#: A ladder's top within this in plan of a level's grating reaches it, m.
LADDER_REACH = 0.8
#: A level this far below the top of a casing's walls is inside it, m.
CASING_EDGE = 0.05
#: Two ways down a floor count as two only when they arrive at it at least this fraction of the
#: floor's diagonal apart in plan (the default of ``escape_remote_fraction`` in the layout
#: criteria; NFPA 101 7.5.1.3.2, ASSUMED for open platforms).
ESCAPE_REMOTE = 0.5
#: The longest walk in plan from a point of a floor in one direction only (a dead end) before
#: two of its ways down lie in alternative directions, m (the default of ``dead_end_m`` in the
#: layout criteria, ASSUMED).
DEAD_END = 7.5
#: Two ways down are alternative escape directions from a point where they lie at least this
#: many degrees apart as seen from it (Approved Document B Vol. 2, 2.10 and Diagram 2.1).
ALTERNATIVE_DEG = 45.0
#: Nominal size -> real depth h of the HEA sections (EN 10365), mm.
_HEA_DEPTHS = {
    **{n: n - d for n, d in ((100, 4), (120, 6), (140, 7), (160, 8), (180, 9), (200, 10))},
    **{n: n - 10 for n in (220, 240, 260, 280, 300, 320, 340, 360, 400, 450, 500, 550, 600)},
    **{n: n - 10 for n in (650, 700, 800, 900, 1000)},
}
# fmt: off
#: Nominal size (the depth h) -> flange width b of the IPE sections (EN 10365), mm.
_IPE_WIDTHS = {
    100: 55, 120: 64, 140: 73, 160: 82, 180: 91, 200: 100, 220: 110, 240: 120, 270: 135,
    300: 150, 330: 160, 360: 170, 400: 180, 450: 190, 500: 200, 550: 210, 600: 220,
}
# fmt: on
_HEB = (100, 120, 140, 160, 180, 200, 220, 240, 260, 280, 300, 320, 340, 360, 400, 450, 500)
_HEB += (550, 600, 650, 700, 800, 900, 1000)
#: Nominal size (the depth h) -> flange width b of the UPN channels (EN 10365), mm.
_UPN_WIDTHS = {100: 50, 120: 55, 140: 60, 160: 65, 180: 70, 200: 75, 220: 80, 240: 85}
_UPN_WIDTHS |= {260: 90, 280: 95, 300: 100}
#: ``(b, h)`` in m of the sections a declared section may name, by the name without blanks in
#: upper case: the rolled sections of EN 10365 (HE sections are 300 mm wide from size 300 up;
#: ``C`` is a UPN channel), equal angles, square hollow sections and flat bars (b the thickness,
#: h the width, as the model's handrails and treads) -- the sections of the material take-off's
#: ``steel-sections.yaml``, which has a mass per metre for each.
SECTION_SIZES: dict[str, tuple[float, float]] = {
    **{f"HEB{n}": (min(n, 300) / 1000, n / 1000) for n in _HEB},
    **{f"HEA{n}": (min(n, 300) / 1000, h / 1000) for n, h in _HEA_DEPTHS.items()},
    **{f"IPE{n}": (b / 1000, n / 1000) for n, b in _IPE_WIDTHS.items()},
    **{f"{p}{n}": (b / 1000, n / 1000) for n, b in _UPN_WIDTHS.items() for p in ("UPN", "C")},
    **{f"L{a}X{t}": (a / 1000, a / 1000) for a, t in ((50, 5), (60, 6), (70, 7), (80, 8))},
    **{f"L{a}X{t}": (a / 1000, a / 1000) for a, t in ((90, 9), (100, 10), (120, 12), (150, 15))},
    **{f"RHS{a}X{a}": (a / 1000, a / 1000) for a in (40, 50, 60)},
    **{f"FL{w}X{t}": (t / 1000, w / 1000) for w, t in ((40, 8), (70, 12), (100, 5), (100, 10))},
}


def section_size(name: str) -> tuple[float, float] | None:
    """``(b, h)`` of the section *name* (blanks and case ignored), None when it is not in
    :data:`SECTION_SIZES`."""
    return SECTION_SIZES.get(name.replace(" ", "").upper())


def section(spans: list[float], table: tuple, largest: tuple, given: str | None) -> tuple:
    """``(name, b, h)`` of a section: *given* (its size from :data:`SECTION_SIZES`; the schemas
    reject a name that is not there), else by the longest span."""
    if given:
        size = section_size(given)
        if size is None:
            raise ValueError(f"unknown steel section {given!r}")
        return (given, *size)
    longest = max(spans) if spans else 0.0
    for limit, name, b, h in table:
        if longest <= limit + 1e-9:
            return (name, b, h)
    return largest


class Frame:
    """A rectangle's own frame: origin, rotation by a multiple of 90 degrees."""

    def __init__(self, origin: tuple[float, float], rotation_deg: float, z: float = 0.0) -> None:
        self.ox, self.oy = origin
        a = math.radians(rotation_deg)
        self.c, self.s = round(math.cos(a), 12), round(math.sin(a), 12)
        self.rotation = rotation_deg % 360
        self.z = z

    def site(self, u: float, v: float, w: float = 0.0) -> Vec:
        return (self.ox + u * self.c - v * self.s, self.oy + u * self.s + v * self.c, self.z + w)

    def local(self, x: float, y: float) -> tuple[float, float]:
        """The frame coordinates of the site point ``(x, y)``."""
        dx, dy = x - self.ox, y - self.oy
        return (dx * self.c + dy * self.s, -dx * self.s + dy * self.c)

    def box(
        self, pid: str, u0: float, v0: float, w0: float, u1: float, v1: float, w1: float, mat: str
    ) -> dict[str, Any]:
        """A box part spanning [u0, u1] x [v0, v1] x [w0, w1] of the frame."""
        centre = self.site((u0 + u1) / 2, (v0 + v1) / 2, (w0 + w1) / 2)
        return {
            "id": pid,
            "kind": "box",
            "material": mat,
            "centre": centre,
            "size": (abs(u1 - u0), abs(v1 - v0), abs(w1 - w0)),
            "rotation_deg": self.rotation,
        }

    def member(self, pid: str, a: Vec, b: Vec, sec: tuple, mat: str = "steel") -> dict[str, Any]:
        """A member between frame points *a* and *b* with section *sec* (name, b, h)."""
        return {
            "id": pid,
            "kind": "member",
            "material": mat,
            "start": self.site(*a),
            "end": self.site(*b),
            "profile": (sec[1], sec[2]),
            "section": sec[0],
        }


def _bracing(structure: Any, side: str) -> str:
    bracing = structure.bracing
    if isinstance(bracing, str):
        return bracing
    return bracing.get(side, "none")


def _side_line(side: str, width: float, depth: float) -> tuple[Vec, Vec, Vec]:
    """For a side: its left end and right end seen from outside (frame coordinates, z 0) and
    the outward normal."""
    return {
        "south": ((0.0, 0.0, 0.0), (width, 0.0, 0.0), (0.0, -1.0, 0.0)),
        "east": ((width, 0.0, 0.0), (width, depth, 0.0), (1.0, 0.0, 0.0)),
        "north": ((width, depth, 0.0), (0.0, depth, 0.0), (0.0, 1.0, 0.0)),
        "west": ((0.0, depth, 0.0), (0.0, 0.0, 0.0), (-1.0, 0.0, 0.0)),
    }[side]


def _cum(spans: list[float]) -> list[float]:
    found = [0.0]
    for span in spans:
        found.append(found[-1] + span)
    return found


def _clip(lo: float, hi: float, a: float, b: float) -> tuple[float, float] | None:
    x0, x1 = max(lo, a), min(hi, b)
    return (x0, x1) if x1 - x0 > 1e-9 else None


def frame_structure(
    structure: Any, file: str, remote: float = ESCAPE_REMOTE, dead_end: float = DEAD_END
) -> dict[str, Any]:
    """The model entry of a steel frame (see the module text); *remote*: the fraction of a
    floor's diagonal its ways down stand apart, *dead_end*: the longest dead-end walk on a
    floor, m (:func:`access_proposals`)."""
    sid = structure.id
    f = Frame(structure.origin, structure.rotation_deg)
    outside = outside_platforms(structure)
    if outside:
        structure = structure.model_copy(
            update={"levels": [*structure.levels, *(lv for lv, _ in outside)]}
        )
    proposed = {lv.id: why for lv, why in outside}
    width, depth = structure.width, structure.depth
    gx, gy = _cum(structure.spans_x), _cum(structure.spans_y)
    levels = sorted(structure.levels, key=lambda lv: lv.elevation)
    top = levels[-1].elevation if levels else 0.0
    col = section(
        [max(structure.spans_x + structure.spans_y)],
        COLUMNS,
        COLUMN_LARGEST,
        structure.column_section,
    )
    beam = section(
        structure.spans_x + structure.spans_y, BEAMS, BEAM_LARGEST, structure.beam_section
    )
    parts: list[dict[str, Any]] = []
    if top > 0:
        for i, u in enumerate(gx):
            for j, v in enumerate(gy):
                parts.append(f.member(f"{sid}/col-{i}-{j}", (u, v, 0.0), (u, v, top), col))
    for level in levels:
        x0, y0, x1, y1 = level.extent or (0.0, 0.0, width, depth)
        z = level.elevation - beam[2] / 2
        lines_v = sorted({v for v in gy if y0 - 1e-9 <= v <= y1 + 1e-9} | {y0, y1})
        lines_u = sorted({u for u in gx if x0 - 1e-9 <= u <= x1 + 1e-9} | {x0, x1})
        for k, v in enumerate(lines_v):
            parts.append(f.member(f"{sid}/{level.id}/beam-x{k}", (x0, v, z), (x1, v, z), beam))
        for k, u in enumerate(lines_u):
            parts.append(f.member(f"{sid}/{level.id}/beam-y{k}", (u, y0, z), (u, y1, z), beam))
        e = level.elevation
        parts.append(f.box(f"{sid}/{level.id}/grating", x0, y0, e - GRATING, x1, y1, e, "grating"))
    storeys = [0.0, *[lv.elevation for lv in levels]]
    for side in SIDES:
        kind = _bracing(structure, side)
        if kind == "none" or top <= 0:
            continue
        left, right, _ = _side_line(side, width, depth)
        along = gx if side in ("south", "north") else gy
        for s, (z0, z1) in enumerate(zip(storeys, storeys[1:], strict=False)):
            for b, (p0, p1) in enumerate(zip(along, along[1:], strict=False)):
                a0 = _on_side(side, left, right, p0, width, depth)
                a1 = _on_side(side, left, right, p1, width, depth)
                pid = f"{sid}/brace-{side}-{s}-{b}"
                if kind == "x":
                    parts.append(f.member(pid + "a", (*a0, z0), (*a1, z1), BRACE))
                    parts.append(f.member(pid + "b", (*a1, z0), (*a0, z1), BRACE))
                else:
                    mid = ((a0[0] + a1[0]) / 2, (a0[1] + a1[1]) / 2)
                    parts.append(f.member(pid + "a", (*a0, z0), (*mid, z1), BRACE))
                    parts.append(f.member(pid + "b", (*a1, z0), (*mid, z1), BRACE))
    stairs = [_stair(f, structure, stair) for stair in structure.stairs]
    ladders = [
        {
            **_ladder(
                f,
                f"{sid}/{ladder.id}",
                (ladder.at[0], ladder.at[1]),
                structure.elevation(ladder.from_) or 0.0,
                structure.elevation(ladder.to) or 0.0,
                ladder.facing,
                {"file": file},
                inward=_ladder_inward(structure, ladder.from_, ladder.to),
            ),
            "from": ladder.from_,
            "to": ladder.to,
            "at": ladder.at,
            "facing": ladder.facing,
        }
        for ladder in structure.ladders
    ]
    more_stairs, more_ladders = access_proposals(f, structure, file, remote, dead_end)
    stairs += more_stairs
    ladders += more_ladders
    parts += _level_rails(f, structure, levels, stairs, ladders)
    walls = []
    if structure.enclosure is not None:
        enc = structure.enclosure
        sides = list(SIDES) if enc.walls == "all" else list(enc.walls)
        t = enc.thickness
        for side in SIDES:
            if side not in sides:
                continue
            left, right, normal = _side_line(side, width, depth)
            length = math.dist(left[:2], right[:2])
            ux, uy = (right[0] - left[0]) / length, (right[1] - left[1]) / length
            nx, ny, _ = normal
            # the south and north walls close the corners
            lo, hi = (-t, length + t) if side in ("south", "north") else (0.0, length)
            holes = [o for o in enc.openings if o.side == side]
            pieces = _cut(lo, hi, enc.height, holes)
            for k, (a, b, z0, z1) in enumerate(pieces):
                corners = [
                    (left[0] + ux * s + nx * d, left[1] + uy * s + ny * d)
                    for s in (a, b)
                    for d in (0.0, t)
                ]
                us, vs = [c[0] for c in corners], [c[1] for c in corners]
                walls.append(
                    f.box(
                        f"{sid}/wall-{side}" + (f"-{k}" if holes else ""),
                        min(us),
                        min(vs),
                        z0,
                        max(us),
                        max(vs),
                        z1,
                        enc.material,
                    )
                )
    corners = [f.site(u, v) for u, v in ((0, 0), (width, 0), (width, depth), (0, depth))]
    xs, ys = [c[0] for c in corners], [c[1] for c in corners]
    height = max([top, *(w["centre"][2] + w["size"][2] / 2 for w in walls)])
    return {
        "id": sid,
        "refs": {"file": file},
        "source": "declared",
        "title": structure.title,
        "origin": structure.origin,
        "rotation_deg": structure.rotation_deg,
        "width": width,
        "depth": depth,
        "footprint": (min(xs), min(ys), max(xs), max(ys)),
        "height": height,
        "grid_x": gx,
        "grid_y": gy,
        "levels": [
            {
                "id": lv.id,
                "title": lv.title,
                "elevation": lv.elevation,
                "kind": lv.kind,
                **({"extent": lv.extent} if lv.extent else {}),
                "use": _use(lv),
                **(
                    {
                        "source": "generated",
                        "review_needed": True,
                        "reason": proposed[lv.id][0],
                        "serves": proposed[lv.id][1],
                    }
                    if lv.id in proposed
                    else {}
                ),
            }
            for lv in levels
        ],
        "sections": {"column": col[0], "beam": beam[0], "brace": BRACE[0], "assumed": True},
        "parts": parts,
        "stairs": stairs,
        "ladders": ladders,
        "walls": walls,
        **(
            {"openings": [o.model_dump(mode="json") for o in structure.enclosure.openings]}
            if structure.enclosure is not None and structure.enclosure.openings
            else {}
        ),
        **({"serves": list(structure.serves)} if structure.serves else {}),
    }


def _cut(lo: float, hi: float, top: float, holes: Any) -> list[tuple[float, float, float, float]]:
    """The pieces ``(s0, s1, z0, z1)`` of a wall from *lo* to *hi* along its side and from 0 to
    *top*, cut around the openings *holes* (``offset``, ``width``, ``sill``, ``height``; they may
    overlap): the wall in strips between the openings' ends, each strip cut at the heights of the
    openings over it."""
    cuts = [
        (max(lo, o.offset), min(hi, o.offset + o.width), max(0.0, o.sill), o.sill + o.height)
        for o in holes
    ]
    cuts = [c for c in cuts if c[1] > c[0] + 1e-9 and c[2] < top - 1e-9]
    marks = sorted({lo, hi, *(c[0] for c in cuts), *(c[1] for c in cuts)})
    pieces: list[tuple[float, float, float, float]] = []
    for a, b in zip(marks, marks[1:], strict=False):
        if b <= a + 1e-9:
            continue
        over = sorted((z0, z1) for s0, s1, z0, z1 in cuts if s0 <= a + 1e-9 and s1 >= b - 1e-9)
        z = 0.0
        for z0, z1 in over:
            if z0 > z + 1e-9:
                pieces.append((a, b, z, z0))
            z = max(z, z1)
        if z < top - 1e-9:
            pieces.append((a, b, z, top))
    return pieces


#: The edge of a level (``handrail-<k>``) on each side of the frame.
EDGE_OF_SIDE = {"south": 0, "east": 1, "north": 2, "west": 3}


def _level_rails(
    f: Frame,
    structure: Any,
    levels: list[Any],
    stairs: list[dict[str, Any]],
    ladders: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    """The guard rails along the edges of each level (``<level>/handrail-<k>``, k = 0..3 from
    the south edge counter-clockwise; ``handrail-<k>-<j>`` for the pieces of a cut edge), open
    where a stair's landing at the level's elevation meets the edge (within :data:`CONNECT`),
    at the head of a ladder topping out at the level (on the edge its climber steps off over,
    the side it faces, :data:`LADDER_WIDTH` plus 0.1 m either side; the gap stands for the
    self-closing gate ISO 14122-3 asks there), and along the stretch of an edge another level of
    the same floor joins across (within :data:`CONNECT`)."""
    width, depth = structure.width, structure.depth
    floor = _floors(structure)
    landings = []  # (elevation, frame rectangle)
    for stair in stairs:
        for part in stair["parts"]:
            name = part["id"].rsplit("/", 1)[-1]
            if part["kind"] == "box" and name.startswith("landing-"):
                x0, y0, x1, y1 = part_rect(part)
                (u0, v0), (u1, v1) = f.local(x0, y0), f.local(x1, y1)
                top = part["centre"][2] + part["size"][2] / 2
                landings.append((top, (min(u0, u1), min(v0, v1), max(u0, u1), max(v0, v1))))
    heads = [
        (ladder["top"][2], f.local(*ladder["top"][:2]), ladder.get("facing")) for ladder in ladders
    ]
    parts: list[dict[str, Any]] = []
    for level in levels:
        x0, y0, x1, y1 = _full(level, width, depth)
        e = level.elevation
        # each edge: (start, end, the axis it runs along, its fixed coordinate, outward sign)
        edges = (
            ((x0, y0), (x1, y0), 0, y0, -1),
            ((x1, y0), (x1, y1), 1, x1, 1),
            ((x1, y1), (x0, y1), 0, y1, 1),
            ((x0, y1), (x0, y0), 1, x0, -1),
        )
        cuts: list[list[tuple[float, float]]] = [[] for _ in edges]
        for k, (_, _, axis, at, _) in enumerate(edges):
            lo, hi = (x0, x1) if axis == 0 else (y0, y1)
            for z, r in landings:
                if abs(z - e) > 1e-6:
                    continue
                across = (r[1], r[3]) if axis == 0 else (r[0], r[2])
                along = (r[0], r[2]) if axis == 0 else (r[1], r[3])
                gap = max(across[0] - at, 0.0, at - across[1])
                if gap <= CONNECT + 1e-9 and along[1] > lo and along[0] < hi:
                    cuts[k].append(along)
            for other in levels:
                if other.id == level.id or abs(other.elevation - e) > 1e-6:
                    continue
                if floor[other.id] != floor[level.id]:
                    continue
                ox0, oy0, ox1, oy1 = _full(other, width, depth)
                across = (oy0, oy1) if axis == 0 else (ox0, ox1)
                along = (ox0, ox1) if axis == 0 else (oy0, oy1)
                sign = edges[k][4]
                # the other level reaches the edge and goes on beyond it
                near = across[0] <= at + CONNECT if sign > 0 else across[1] >= at - CONNECT
                beyond = across[1] > at + 1e-6 if sign > 0 else across[0] < at - 1e-6
                if near and beyond and along[1] > lo and along[0] < hi:
                    cuts[k].append(along)
        for z, (u, v), facing in heads:
            if abs(z - e) > 1e-6 or facing not in EDGE_OF_SIDE:
                continue
            k = EDGE_OF_SIDE[facing]  # the climber steps off over the edge behind his back
            _, _, axis, at, _ = edges[k]
            lo, hi = (x0, x1) if axis == 0 else (y0, y1)
            c, d = (u, v) if axis == 0 else (v, u)
            if math.hypot(max(lo - c, 0.0, c - hi), d - at) <= LADDER_REACH + 1e-9:
                c = u if edges[k][2] == 0 else v
                half = LADDER_WIDTH / 2 + 0.1
                cuts[k].append((c - half, c + half))
        for k, (a, b, axis, _, _) in enumerate(edges):
            lo, hi = (x0, x1) if axis == 0 else (y0, y1)
            pieces = _free_runs(lo, hi, cuts[k])
            if len(pieces) == 1 and pieces[0] == (lo, hi):
                parts += _guard_rail(f, f"{structure.id}/{level.id}/handrail-{k}", a, b, e)
                continue
            forward = (b[axis] - a[axis]) > 0
            for j, (p0, p1) in enumerate(pieces if forward else pieces[::-1]):
                s0, s1 = (p0, p1) if forward else (p1, p0)
                pa = (s0, a[1]) if axis == 0 else (a[0], s0)
                pb = (s1, a[1]) if axis == 0 else (a[0], s1)
                parts += _guard_rail(f, f"{structure.id}/{level.id}/handrail-{k}-{j}", pa, pb, e)
    return parts


def _free_runs(
    lo: float, hi: float, cuts: list[tuple[float, float]], shortest: float = 0.05
) -> list[tuple[float, float]]:
    """The stretches of ``[lo, hi]`` outside the *cuts*, at least *shortest* long."""
    found, at = [], lo
    for a, b in sorted(cuts):
        if a - at >= shortest:
            found.append((at, min(a, hi)))
        at = max(at, b)
    if hi - at >= shortest:
        found.append((at, hi))
    return found


def _guard_rail(
    f: Frame, pid: str, a: tuple[float, float], b: tuple[float, float], floor: float
) -> list[dict[str, Any]]:
    """A guard rail from *a* to *b* (frame coordinates) on a floor at *floor*: the top rail at
    :data:`HANDRAIL_HEIGHT` (``pid``), and as detail a mid rail, a toe plate and posts at most
    :data:`POST_PITCH` apart (``pid-mid``, ``pid-toe``, ``pid-post-<k>``)."""
    rail = floor + HANDRAIL_HEIGHT
    parts = [f.member(pid, (*a, rail), (*b, rail), HANDRAIL, "handrail")]
    mid = f.member(
        f"{pid}-mid",
        (*a, floor + MIDRAIL_HEIGHT),
        (*b, floor + MIDRAIL_HEIGHT),
        ("FL40x8", 0.008, 0.04),
        "handrail",
    )
    toe = f.member(
        f"{pid}-toe",
        (*a, floor + TOE_PLATE / 2),
        (*b, floor + TOE_PLATE / 2),
        ("FL100x5", 0.005, TOE_PLATE),
        "steel",
    )
    parts += [{**mid, "lod": 2}, {**toe, "lod": 2}]
    length = math.dist(a, b)
    posts = max(1, math.ceil(length / POST_PITCH - 1e-9))
    for k in range(posts + 1):
        t = k / posts
        p = (a[0] + (b[0] - a[0]) * t, a[1] + (b[1] - a[1]) * t)
        post = f.member(
            f"{pid}-post-{k}", (*p, floor), (*p, rail), ("RHS40x40", 0.04, 0.04), "handrail"
        )
        parts.append({**post, "lod": 2})
    return parts


def _on_side(
    side: str, left: Vec, right: Vec, p: float, width: float, depth: float
) -> tuple[float, float]:
    """The frame point at grid coordinate *p* along a side (u for south/north, v otherwise)."""
    if side in ("south", "north"):
        return (p, left[1])
    return (left[0], p)


def stair_flights(rise: float) -> tuple[int, float, int, float]:
    """``(flights, rise of one flight, risers per flight, going)`` of a stair climbing *rise*
    m: the fewest flights of at most :data:`MAX_FLIGHT_RISE`, the fewest risers of at most
    :data:`MAX_RISER`, and the going from the step pace (g + 2h = :data:`STEP_PACE`)."""
    flights = max(1, math.ceil(rise / MAX_FLIGHT_RISE - 1e-9))
    h = rise / flights
    risers = max(1, math.ceil(h / MAX_RISER - 1e-9))
    return flights, h, risers, STEP_PACE - 2 * h / risers


def _stair(f: Frame, structure: Any, stair: Any) -> dict[str, Any]:
    """Switchback flights outside a side of the frame (see the module text)."""
    sid = f"{structure.id}/{stair.id}"
    z0 = structure.elevation(stair.from_) or 0.0
    z1 = structure.elevation(stair.to) or 0.0
    if z1 < z0:
        z0, z1 = z1, z0
    width, depth = structure.width, structure.depth
    left, right, normal = _side_line(stair.side, width, depth)
    length = math.dist(left[:2], right[:2])
    ux, uy = (right[0] - left[0]) / length, (right[1] - left[1]) / length
    nx, ny = normal[0], normal[1]
    w = stair.width
    out = stair_out(structure, stair, z0)
    flights, h, steps, going = stair_flights(z1 - z0)
    run = steps * going
    start = stair.offset if stair.offset is not None else 0.0
    parts: list[dict[str, Any]] = []
    stringer = ("C200", 0.075, 0.2)

    def at(s: float, lane: float, z: float) -> Vec:
        """Frame point: *s* along the side, *lane* metres out from its inner edge, height
        *z*."""
        lane += out
        return (left[0] + ux * s + nx * lane, left[1] + uy * s + ny * lane, z)

    points: list[Vec] = []
    for k in range(flights):
        lane0 = w * (k % 2)
        forward = k % 2 == 0
        s0, s1 = (start + w, start + w + run) if forward else (start + w + run, start + w)
        zb, zt = z0 + k * h, z0 + (k + 1) * h
        for edge, lane in (("a", lane0 + 0.05), ("b", lane0 + w - 0.05)):
            parts.append(
                f.member(
                    f"{sid}/flight-{k}/stringer-{edge}",
                    at(s0, lane, zb),
                    at(s1, lane, zt),
                    stringer,
                )
            )
        for edge, lane in (("a", lane0 + 0.05), ("b", lane0 + w - 0.05)):
            top = HANDRAIL_HEIGHT - 0.1
            rail = f.member(
                f"{sid}/flight-{k}/handrail-{edge}",
                at(s0, lane, zb + top),
                at(s1, lane, zt + top),
                HANDRAIL,
                "handrail",
            )
            mid = f.member(
                f"{sid}/flight-{k}/midrail-{edge}",
                at(s0, lane, zb + top / 2),
                at(s1, lane, zt + top / 2),
                ("FL40x8", 0.008, 0.04),
                "handrail",
            )
            parts += [{**rail, "lod": 2}, {**mid, "lod": 2}]
            for n, (s_, z_) in enumerate(((s0, zb), (s1, zt))):
                post = f.member(
                    f"{sid}/flight-{k}/post-{edge}{n}",
                    at(s_, lane, z_),
                    at(s_, lane, z_ + top),
                    ("RHS40x40", 0.04, 0.04),
                    "handrail",
                )
                parts.append({**post, "lod": 2})
        for n in range(1, steps):
            s = s0 + (s1 - s0) * n / steps
            centre = at(s, lane0 + w / 2, zb + h * n / steps)
            parts.append(_tread(f, f"{sid}/flight-{k}/tread-{n}", centre, (ux, uy), going, w))
        landing_s = s1 if forward else s1 - w
        lane_lo = 0.0
        a = at(landing_s, lane_lo, zt)
        b = at(landing_s + w, lane_lo + 2 * w, zt)
        parts.append(_flat(f, f"{sid}/landing-{k}", a, b, zt))
        if k == 0:
            base = at(start + w, lane0, zb)
            b0 = at(start, lane0 + 2 * w, zb)
            parts.append(_flat(f, f"{sid}/landing-base", base, b0, zb))
        points += [at(s0, lane0, zb), at(s1, lane0 + w, zt)]
    points += [at(start, 0.0, z0), at(start + w + run + w, 2 * w, z1)]
    site = [f.site(*p) for p in points]
    xs, ys = [p[0] for p in site], [p[1] for p in site]
    return {
        "id": sid,
        "refs": {"file": "layout/structures.yaml"},
        "source": "declared",
        "from": stair.from_,
        "to": stair.to,
        "side": stair.side,
        "offset": start,
        "width": w,
        "flights": flights,
        **({"out": round(out, 3)} if out > 1e-9 else {}),
        "box": (min(xs), min(ys), z0, max(xs), max(ys), z1 + HANDRAIL_HEIGHT),
        "parts": parts,
    }


def _use(level: Any) -> str:
    """How often a level is used: declared, else a deck regular, a platform occasional."""
    return level.use or ("regular" if level.kind == "deck" else "occasional")


def closed_enclosure(structure: Any) -> bool:
    """Whether *structure* is closed by a casing: enclosure walls on every side, no fire
    wall (as :func:`chemeascode.domains.spatial.floors.closed_casings`)."""
    enc = structure.enclosure
    if enc is None or enc.material == "fire_wall":
        return False
    return enc.walls == "all" or set(SIDES) <= set(enc.walls)


def _full(level: Any, width: float, depth: float) -> tuple[float, float, float, float]:
    return tuple(level.extent) if level.extent else (0.0, 0.0, width, depth)  # type: ignore[return-value]


def enclosed_levels(structure: Any) -> set[str]:
    """The levels of *structure* inside its casing: below the top of the walls with their
    extent inside the frame (nobody can stand there)."""
    if not closed_enclosure(structure):
        return set()
    width, depth = structure.width, structure.depth
    top = structure.enclosure.height
    found = set()
    for level in structure.levels:
        x0, y0, x1, y1 = _full(level, width, depth)
        e = CASING_EDGE
        inside = x0 >= -e and y0 >= -e and x1 <= width + e and y1 <= depth + e
        if inside and level.elevation < top - CASING_EDGE:
            found.add(level.id)
    return found


def stair_out(structure: Any, stair: Any, z0: float) -> float:
    """How far out from its side a stair's inner edge stands: declared, else outside the
    enclosure wall on that side (when the stair starts below the wall's top), else 0."""
    if getattr(stair, "out", None) is not None:
        return float(stair.out)
    enc = structure.enclosure
    if enc is None:
        return 0.0
    sides = list(SIDES) if enc.walls == "all" else list(enc.walls)
    if stair.side in sides and z0 < enc.height - 1e-9:
        return enc.thickness
    return 0.0


def _edge_along(side: str, extent: tuple[float, ...], width: float, depth: float) -> float:
    """How long the edge of *extent* on the frame's *side* is (0: it does not reach it)."""
    x0, y0, x1, y1 = extent
    e = 1e-6
    reaches = {
        "south": y0 <= e,
        "north": y1 >= depth - e,
        "west": x0 <= e,
        "east": x1 >= width - e,
    }[side]
    if not reaches:
        return 0.0
    return (x1 - x0) if side in ("south", "north") else (y1 - y0)


def _strip(
    side: str, extent: tuple[float, ...], width: float, depth: float, gap: float, wide: float
) -> tuple[float, float, float, float]:
    """A strip *wide* along *side* outside the frame, *gap* off it, as long as *extent*'s
    edge on that side."""
    x0, y0, x1, y1 = extent
    return {
        "south": (x0, -gap - wide, x1, -gap),
        "north": (x0, depth + gap, x1, depth + gap + wide),
        "west": (-gap - wide, y0, -gap, y1),
        "east": (width + gap, y0, width + gap + wide, y1),
    }[side]


def outside_platforms(structure: Any) -> list[tuple[Any, tuple[str, str]]]:
    """Platforms proposed outside the casing of *structure* (see the module text): for each
    floor inside the casing without a declared level outside it at its elevation, a strip
    :data:`OUTSIDE_PLATFORM` wide along the side its extent runs longest on, outside the wall;
    on that side also one at each casing-roof floor reaching it, joining the roof across the
    wall's top. Each with ``(reason, serves)``."""
    if not closed_enclosure(structure):
        return []
    from chemeascode.domains.spatial.schemas import StructureLevel

    width, depth = structure.width, structure.depth
    enc = structure.enclosure
    inside = enclosed_levels(structure)
    floor = _floors(structure, inside)
    known = {lv.id for lv in structure.levels}
    outside_at = {round(lv.elevation, 6) for lv in structure.levels if lv.id not in inside}
    groups: dict[int, list[Any]] = {}
    for level in sorted(structure.levels, key=lambda lv: (lv.elevation, lv.id)):
        groups.setdefault(floor[level.id], []).append(level)
    found: list[tuple[Any, tuple[str, str]]] = []
    sides_used: list[str] = []
    for level in sorted(structure.levels, key=lambda lv: (lv.elevation, lv.id)):
        if level.id in inside or level.elevation >= enc.height - CASING_EDGE:
            continue
        x0, y0, x1, y1 = _full(level, width, depth)
        for side, beyond in (
            ("north", y1 - depth),
            ("south", -y0),
            ("east", x1 - width),
            ("west", -x0),
        ):
            if beyond > 1e-6 and side not in sides_used:
                sides_used.append(side)  # a declared platform outside the casing
    for members in groups.values():
        if members[0].id not in inside or round(members[0].elevation, 6) in outside_at:
            continue
        edges = {
            side: sum(_edge_along(side, _full(lv, width, depth), width, depth) for lv in members)
            for side in ("north", "south", "east", "west")
        }
        side = max(edges, key=lambda k: (edges[k], -("north", "south", "east", "west").index(k)))
        if edges[side] <= 1e-9:
            side = "north"
        spans = [_full(lv, width, depth) for lv in members]
        if side in ("south", "north"):
            extent = (min(e[0] for e in spans), 0.0, max(e[2] for e in spans), depth)
        else:
            extent = (0.0, min(e[1] for e in spans), width, max(e[3] for e in spans))
        lid = f"{members[0].id}-out"
        if lid in known:
            continue
        names = ", ".join(lv.id for lv in members)
        level = StructureLevel.model_validate(
            {
                "id": lid,
                "title": f"Platform outside the casing at {members[0].elevation:g} m "
                f"({side} side, for {names})",
                "elevation": members[0].elevation,
                "kind": "platform",
                "extent": _strip(side, extent, width, depth, enc.thickness, OUTSIDE_PLATFORM),
            }
        )
        why = (
            f"level {names} at {members[0].elevation:g} m lies inside the casing (walls to "
            f"{enc.height:g} m): a platform outside it on the {side} side"
        )
        found.append((level, (why, members[0].id)))
        known.add(lid)
        if side not in sides_used:
            sides_used.append(side)
    # declared levels already outside the frame, by elevation and side (a roof landing the
    # plant declares, whatever its id)
    declared_out = set()
    for level in structure.levels:
        x0, y0, x1, y1 = _full(level, width, depth)
        for side, beyond in (
            ("north", y1 - depth),
            ("south", -y0),
            ("east", x1 - width),
            ("west", -x0),
        ):
            if beyond > 1e-6:
                declared_out.add((round(level.elevation, 6), side))
    for members in groups.values():
        if members[0].id in inside or members[0].elevation < enc.height - CASING_EDGE:
            continue
        for side in sides_used:
            if (round(members[0].elevation, 6), side) in declared_out:
                break  # the plant declares the landing on that side
            reach = [
                _full(lv, width, depth)
                for lv in members
                if _edge_along(side, _full(lv, width, depth), width, depth) > 1e-9
            ]
            lid = f"{members[0].id}-out"
            if not reach or lid in known:
                continue
            if side in ("south", "north"):
                extent = (min(e[0] for e in reach), 0.0, max(e[2] for e in reach), depth)
            else:
                extent = (0.0, min(e[1] for e in reach), width, max(e[3] for e in reach))
            names = ", ".join(lv.id for lv in members)
            level = StructureLevel.model_validate(
                {
                    "id": lid,
                    "title": f"Landing outside the casing at {members[0].elevation:g} m "
                    f"({side} side, joins {names})",
                    "elevation": members[0].elevation,
                    "kind": "platform",
                    "extent": _strip(side, extent, width, depth, enc.thickness, OUTSIDE_PLATFORM),
                }
            )
            why = (
                f"the casing roof {names} at {members[0].elevation:g} m: a landing outside the "
                f"casing on the {side} side for the stair from the platforms outside it"
            )
            found.append((level, (why, members[0].id)))
            known.add(lid)
            break
    return found


def _floors(structure: Any, inside: set[str] | None = None) -> dict[str, int]:
    """The floor of each level: levels at one elevation whose extents are within
    :data:`CONNECT` of each other share a floor, unless one of them is inside a casing and the
    other is not (the wall is between them)."""
    width, depth = structure.width, structure.depth
    inside = enclosed_levels(structure) if inside is None else inside
    levels = sorted(structure.levels, key=lambda lv: (lv.elevation, lv.id))
    floor: dict[str, int] = {}
    for i, level in enumerate(levels):
        floor[level.id] = i
    changed = True
    while changed:
        changed = False
        for a in levels:
            for b in levels:
                if floor[a.id] == floor[b.id] or abs(a.elevation - b.elevation) > 1e-6:
                    continue
                if (a.id in inside) != (b.id in inside):
                    continue
                ax0, ay0, ax1, ay1 = _full(a, width, depth)
                bx0, by0, bx1, by1 = _full(b, width, depth)
                c = CONNECT
                if ax0 <= bx1 + c and bx0 <= ax1 + c and ay0 <= by1 + c and by0 <= ay1 + c:
                    low = min(floor[a.id], floor[b.id])
                    for key, value in list(floor.items()):
                        if value in (floor[a.id], floor[b.id]):
                            floor[key] = low
                    changed = True
    return floor


def _side_offset(
    side: str, extent: tuple[float, float, float, float], width: float, depth: float
) -> float:
    """Where along *side* (from its left end seen from outside) an extent begins."""
    x0, y0, x1, y1 = extent
    return {"east": y0, "west": depth - y1, "south": x0, "north": width - x1}[side]


def part_rect(part: dict[str, Any]) -> tuple[float, float, float, float]:
    """The plan rectangle of a box part (turned by a multiple of 90 degrees)."""
    cx, cy, _ = part["centre"]
    dx, dy, _ = part["size"]
    if (part.get("rotation_deg") or 0.0) % 180 > 1e-6:
        dx, dy = dy, dx
    return (cx - dx / 2, cy - dy / 2, cx + dx / 2, cy + dy / 2)


def rect_gap(a: tuple[float, ...], b: tuple[float, ...]) -> float:
    """The plan distance between two rectangles (0 where they overlap)."""
    dx = max(a[0] - b[2], 0.0, b[0] - a[2])
    dy = max(a[1] - b[3], 0.0, b[1] - a[3])
    return math.hypot(dx, dy)


def point_rect(p: Any, r: tuple[float, ...]) -> float:
    return math.hypot(max(r[0] - p[0], 0.0, p[0] - r[2]), max(r[1] - p[1], 0.0, p[1] - r[3]))


def stair_landings(entry: dict[str, Any]) -> tuple[tuple[float, ...], tuple[float, ...]] | None:
    """The plan rectangles of a model stair's foot landing and top landing."""
    parts = {p["id"].rsplit("/", 1)[-1]: p for p in entry.get("parts", [])}
    base = parts.get("landing-base")
    top = parts.get(f"landing-{entry['flights'] - 1}")
    if base is None or top is None:
        return None
    return part_rect(base), part_rect(top)


def way_arrival(entry: dict[str, Any]) -> tuple[float, float, float, float] | None:
    """Where a model stair or ladder arrives at its upper level, as a plan rectangle: a
    stair's top landing, a ladder's top (a point)."""
    if "flights" in entry:
        landings = stair_landings(entry)
        return None if landings is None else landings[1]
    x, y = entry["top"][0], entry["top"][1]
    return (x, y, x, y)


def remote_ways(
    arrivals: list[tuple[float, ...]], rects: list[tuple[float, ...]], fraction: float
) -> bool:
    """Whether two of the ways arriving at a floor (*arrivals*, plan rectangles) are remote
    from each other: at least *fraction* of the diagonal of the floor (the bounds of its
    *rects*) apart in plan, so one incident does not block both."""
    if len(arrivals) < 2:
        return False
    return any(
        rect_gap(a, b) >= remote_distance(rects, fraction) - 1e-6
        for a, b in itertools.combinations(arrivals, 2)
    )


def remote_distance(rects: list[tuple[float, ...]], fraction: float) -> float:
    """*fraction* of the diagonal of the bounds of the plan rectangles *rects*, m."""
    if not rects:
        return 0.0
    dx = max(r[2] for r in rects) - min(r[0] for r in rects)
    dy = max(r[3] for r in rects) - min(r[1] for r in rects)
    return fraction * math.hypot(dx, dy)


def dead_end_walk(
    arrivals: list[tuple[float, ...]], rects: list[tuple[float, ...]], step: float = 0.5
) -> tuple[float, tuple[float, float]] | None:
    """The longest dead-end walk on a floor (the plan rectangles *rects*) whose ways down
    arrive at *arrivals* (plan rectangles), m, and the point it starts from: with one way the
    walk to it from the floor's farthest point; with two or more the walk in plan from a point
    to the nearest point where two of the ways lie :data:`ALTERNATIVE_DEG` or more apart as
    seen from it (Approved Document B Vol. 2, Diagram 2.1: the dead end runs up to the point
    where the angle between two exits reaches 45 degrees). The points from which two ways
    *a*, *b* lie at that angle or more apart are the two discs whose circles pass through *a*
    and *b* with the inscribed angle :data:`ALTERNATIVE_DEG`; the floor is sampled every
    *step* (and at its corners). The walk is the straight distance in plan (a direct distance,
    ADB Table 2.1 note 1), not around the floor's outline, and the angle is taken as seen from
    the point: on a narrow platform the 45 degrees are reached up to about its width past the
    nearer way, so the dead end found can be that much shorter than the walk to that way
    (screening). None without a way or a floor."""
    if not arrivals or not rects:
        return None
    if len(arrivals) == 1:
        a = arrivals[0]
        return max(
            ((point_rect(c, a), c) for r in rects for c in _rect_corners(r)),
            key=lambda t: t[0],
        )
    centres = [((a[0] + a[2]) / 2, (a[1] + a[3]) / 2) for a in arrivals]
    angle = math.radians(ALTERNATIVE_DEG)
    discs: list[tuple[float, float, float]] = []
    for (ax, ay), (bx, by) in itertools.combinations(centres, 2):
        d = math.hypot(bx - ax, by - ay)
        if d < 1e-6:
            continue
        radius = d / (2 * math.sin(angle))
        off = d / (2 * math.tan(angle))
        nx, ny = -(by - ay) / d, (bx - ax) / d
        mx, my = (ax + bx) / 2, (ay + by) / 2
        discs += [(mx + off * nx, my + off * ny, radius), (mx - off * nx, my - off * ny, radius)]
    if not discs:
        # all ways arrive at one point: one direction only, as with a single way
        return dead_end_walk(arrivals[:1], rects, step)

    def walk(p: tuple[float, float]) -> float:
        return max(min(math.hypot(p[0] - x, p[1] - y) - r for x, y, r in discs), 0.0)

    best = (0.0, (rects[0][0], rects[0][1]))
    for r in rects:
        nx_ = max(1, min(200, math.ceil((r[2] - r[0]) / step)))
        ny_ = max(1, min(200, math.ceil((r[3] - r[1]) / step)))
        for i in range(nx_ + 1):
            x = r[0] + (r[2] - r[0]) * i / nx_
            for j in range(ny_ + 1):
                p = (x, r[1] + (r[3] - r[1]) * j / ny_)
                w = walk(p)
                if w > best[0]:
                    best = (w, p)
    return best


def _rect_corners(r: tuple[float, ...]) -> tuple[tuple[float, float], ...]:
    return ((r[0], r[1]), (r[2], r[1]), (r[2], r[3]), (r[0], r[3]))


def _free_id(wanted: str, taken: set[str]) -> str:
    """*wanted*, or ``<wanted>-2``, ``-3``, ... when it is taken; the id is then taken."""
    found, n = wanted, 1
    while found in taken:
        n += 1
        found = f"{wanted}-{n}"
    taken.add(found)
    return found


def access_proposals(
    f: Frame,
    structure: Any,
    file: str,
    remote: float = ESCAPE_REMOTE,
    dead_end: float = DEAD_END,
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    """Stairs and caged ladders proposed for the levels of *structure* (``source:
    generated``, ``review_needed``; see the module text), by the rules the escape check
    applies: a way counts only when it reaches the floor and stands on a floor that itself has
    a way down to grade. A level at or above :data:`STAIR_ABOVE` or in regular use without
    such a stair gets a stair whose top landing reaches it (none where no position reaches
    it: placed by hand); a floor without :data:`WAYS_DOWN` such ways remote from each other
    (their arrivals at least *remote* of the floor's diagonal apart) gets caged ladders at the
    corners of its extent farthest from its other ways (a corner inside a casing moves out
    past the wall); where its ways still leave a dead end longer than *dead_end*
    (:func:`dead_end_walk`) up to two caged ladders more, at the corner nearest the dead end's
    far point. Levels inside a casing get none: the platforms outside it
    (:func:`outside_platforms`, already among the levels) are served instead. A proposal never
    takes an id the structure declares (``stair-to-<level>-2``, ...)."""
    levels = sorted(structure.levels, key=lambda lv: (lv.elevation, lv.id))
    if not levels:
        return [], []
    width, depth = structure.width, structure.depth
    inside = enclosed_levels(structure)
    floor = _floors(structure, inside)
    floor["grade"] = -1
    elevation = {lv.id: lv.elevation for lv in levels} | {"grade": 0.0}
    rects: dict[int, list[tuple[float, float, float, float]]] = {}
    for lv in levels:
        x0, y0, x1, y1 = _full(lv, width, depth)
        a, b = f.site(x0, y0), f.site(x1, y1)
        rect = (min(a[0], b[0]), min(a[1], b[1]), max(a[0], b[0]), max(a[1], b[1]))
        rects.setdefault(floor[lv.id], []).append(rect)
    casing = None
    if closed_enclosure(structure):
        a, b = f.site(0.0, 0.0), f.site(width, depth)
        casing = (min(a[0], b[0]), min(a[1], b[1]), max(a[0], b[0]), max(a[1], b[1]))
    top_of_casing = structure.enclosure.height if casing is not None else 0.0
    # the ways: (kind, floor of the foot, floor of the top, where it arrives at the top)
    links: list[tuple[str, int, int, tuple[float, ...]]] = []

    def link(kind: str, a: str, b: str, entry: dict[str, Any]) -> None:
        low, high = sorted((a, b), key=lambda x: elevation.get(x, 0.0))
        arrival = way_arrival(entry)
        if floor.get(high) is None or floor[high] == floor.get(low) or arrival is None:
            return
        links.append((kind, floor[low], floor[high], arrival))

    def reached() -> set[int]:
        """The floors with a way down to grade (through the floors below)."""
        found = {-1}
        changed = True
        while changed:
            changed = False
            for _, low_g, high_g, _ in links:
                if low_g in found and high_g not in found:
                    found.add(high_g)
                    changed = True
        return found

    def ways(group: int) -> list[tuple[str, tuple[float, ...]]]:
        down = reached()
        return [(k, at) for k, lo, hi, at in links if hi == group and lo in down]

    def reaches(entry: dict[str, Any], low: str, high: str) -> tuple[bool, bool]:
        """Whether a stair's foot lands on *low* and its top on *high*."""
        landings = stair_landings(entry)
        if landings is None:
            return False, False
        base, top = landings
        foot = low == "grade" or (
            low not in inside and min(rect_gap(base, r) for r in rects[floor[low]]) <= CONNECT
        )
        head = high not in inside and min(rect_gap(top, r) for r in rects[floor[high]]) <= CONNECT
        return foot, head

    def in_casing(at: tuple[float, float], z0: float) -> bool:
        if casing is None or z0 >= top_of_casing - CASING_EDGE:
            return False
        p = f.site(*at)
        return casing[0] < p[0] < casing[2] and casing[1] < p[1] < casing[3]

    def outside(at: tuple[float, float]) -> tuple[float, float]:
        """A point inside the casing moved out past its nearest wall (a ladder stands there
        with its top within :data:`LADDER_REACH` of the frame's edge)."""
        u, v = at
        out = structure.enclosure.thickness + LADDER_WIDTH / 2 + 0.1
        side = _outward(at, width, depth)
        return {
            "west": (-out, v),
            "east": (width + out, v),
            "south": (u, -out),
            "north": (u, depth + out),
        }[side]

    declared = list(structure.stairs)
    taken = {way.id for way in (*structure.stairs, *structure.ladders)}
    connected = []
    for stair in declared:
        low, high = sorted((stair.from_, stair.to), key=lambda x: elevation.get(x, 0.0))
        entry = _stair(f, structure, stair)
        if all(reaches(entry, low, high)):
            connected.append(stair)
            link("stair", stair.from_, stair.to, entry)
    for ladder in structure.ladders:
        low, high = sorted((ladder.from_, ladder.to), key=lambda x: elevation.get(x, 0.0))
        if low in inside or high in inside or in_casing(tuple(ladder.at), elevation[low]):
            continue
        drawn = _ladder(
            f,
            ladder.id,
            (ladder.at[0], ladder.at[1]),
            elevation[low],
            elevation[high],
            ladder.facing,
            {},
            inward=_ladder_inward(structure, low, high),
        )
        p, foot = drawn["top"], drawn["base"]
        if min(point_rect(p, r) for r in rects[floor[high]]) > LADDER_REACH:
            continue
        if low != "grade" and min(point_rect(foot, r) for r in rects[floor[low]]) > LADDER_REACH:
            continue
        link("ladder", ladder.from_, ladder.to, {"top": p})
    reference = connected[-1] if connected else (declared[-1] if declared else None)
    from chemeascode.domains.spatial.schemas import Stair

    stairs: list[dict[str, Any]] = []
    ladders: list[dict[str, Any]] = []
    seen: set[int] = set()
    for level in levels:
        group = floor[level.id]
        if group in seen or level.id in inside:
            continue
        seen.add(group)
        members = [lv for lv in levels if floor[lv.id] == group]
        below = [
            lv for lv in levels if lv.elevation < level.elevation - 1e-6 and lv.id not in inside
        ]
        regular = any(_use(lv) == "regular" for lv in members)
        has_stair = any(kind == "stair" for kind, _ in ways(group))
        if (level.elevation >= STAIR_ABOVE - 1e-9 or regular) and not has_stair:
            candidates: list[tuple[str, float, float | None]] = []
            if reference is not None:
                candidates.append((reference.side, reference.offset or 0.0, reference.out))
            order = ("east", "west", "south", "north")
            best: dict[str, tuple[float, float]] = {}
            for lv in members:
                extent = _full(lv, width, depth)
                x0, y0, x1, y1 = extent
                for side in order:
                    if _edge_along(side, extent, width, depth) <= 1e-9:
                        continue
                    beyond = max(
                        {"south": -y0, "north": y1 - depth, "east": x1 - width, "west": -x0}[side],
                        0.0,
                    )
                    if side not in best or beyond > best[side][1] + 1e-9:
                        best[side] = (_side_offset(side, extent, width, depth), beyond)
            for side in sorted(best, key=lambda k: (-best[k][1], order.index(k))):
                offset, beyond = best[side]
                out = beyond if beyond > 1e-9 else None
                candidates.append((side, max(offset, 0.0) + (0.5 if out else 0.0), out))
            chosen = None
            name = _free_id(f"stair-to-{level.id}", set(taken))
            down = reached()
            lowers = [lv.id for lv in reversed(below) if floor[lv.id] in down]
            for lower in [*lowers, "grade"]:
                for side, offset, out, shift in [
                    (*c, s) for c in candidates for s in (False, True)
                ]:
                    if shift:
                        # an odd number of flights tops out at the far end of its run: on a
                        # level shorter than the run, start it back by one run and a landing so
                        # its top landing comes out beside the level's edge
                        rise = level.elevation - elevation.get(lower, 0.0)
                        flights, _, risers, going = stair_flights(rise)
                        if flights % 2 == 0:
                            continue
                        run = risers * going
                        offset = round(offset - Stair.model_fields["width"].default - run, 3)
                    stair = Stair.model_validate(
                        {
                            "id": name,
                            "from": lower,
                            "to": level.id,
                            "side": side,
                            "offset": offset,
                            **({"out": round(out, 6)} if out is not None else {}),
                        }
                    )
                    entry = _stair(f, structure, stair)
                    foot, head = reaches(entry, lower, level.id)
                    if foot and head:
                        chosen = (stair, entry)
                        break
                if chosen is not None:
                    break
            # no position reaches the level: nothing is proposed (a stair that does not
            # connect would be no way down); the escape check asks for one placed by hand
            if chosen is not None:
                stair, entry = chosen
                taken.add(name)
                why = (
                    f"level {level.id} at {level.elevation:g} m"
                    + (
                        " (6 m or higher)"
                        if level.elevation >= STAIR_ABOVE - 1e-9
                        else " in regular use"
                    )
                    + " has no connected stair down"
                )
                entry.update(
                    source="generated", review_needed=True, reason=why, refs={"file": file}
                )
                stairs.append(entry)
                link("stair", stair.from_, level.id, entry)
        # a valve access platform (it serves valves) needs one way down
        needed = 1 if getattr(structure, "serves", None) else WAYS_DOWN
        corners = []
        for lv in members:
            x0, y0, x1, y1 = _full(lv, width, depth)
            inset = 0.5
            corners += [
                (x0 + inset, y0 + inset),
                (x1 - inset, y0 + inset),
                (x1 - inset, y1 - inset),
                (x0 + inset, y1 - inset),
            ]
        corners = [outside(c) if in_casing(c, 0.0) else c for c in corners]
        # up to two ladders more than needed where the ways leave a dead end over the limit
        for _ in range(needed + 2):
            found = ways(group)
            arrivals = [at for _, at in found]
            apart = needed == 1 or remote_ways(arrivals, rects[group], remote)
            dead = dead_end_walk(arrivals, rects[group]) if len(found) >= needed else None
            too_long = dead is not None and dead[0] > dead_end + 1e-6
            if len(found) >= needed and apart and not too_long:
                break
            if not corners:
                break
            if dead is not None and too_long and apart:
                # the corner nearest the dead end's far point
                far = dead[1]
                at = min(
                    corners,
                    key=lambda c, far=far: (
                        round(math.dist(f.site(*c)[:2], far), 6),
                        c[0],
                        c[1],
                    ),
                )
            else:
                at = min(
                    corners,
                    key=lambda c, arrivals=arrivals: (
                        -round(
                            min((point_rect(f.site(*c), r) for r in arrivals), default=0.0),
                            6,
                        ),
                        c[0],
                        c[1],
                    ),
                )
            corners.remove(at)
            site = f.site(*at)
            lower = next(
                (
                    lv.id
                    for lv in reversed(below)
                    if min(point_rect(site, r) for r in rects[floor[lv.id]]) <= 1e-6
                ),
                "grade",
            )
            facing = _outward(at, width, depth)
            plural = "s" if len(found) != 1 else ""
            if len(found) < needed:
                why = (
                    f"level {level.id} has {len(found)} connected way{plural} down; {needed} needed"
                )
            elif not apart:
                why = (
                    f"the ways down from level {level.id} are not remote from each other "
                    f"(less than {remote:g} of the floor's diagonal apart)"
                )
            else:
                why = (
                    f"a point of level {level.id} walks {dead[0]:.1f} m in one direction only "
                    f"to its ways down (a dead end longer than {dead_end:g} m)"
                )
            local = _free_id(f"ladder-to-{level.id}", taken)
            entry = _ladder(
                f,
                f"{structure.id}/{local}",
                at,
                elevation[lower],
                level.elevation,
                facing,
                {"file": file},
                "generated",
                _ladder_inward(structure, lower, level.id),
            )
            entry.update({"from": lower, "to": level.id, "at": at, "facing": facing})
            entry.update(review_needed=True, reason=why)
            ladders.append(entry)
            link("ladder", lower, level.id, entry)
    return stairs, ladders


def _outward(at: tuple[float, float], width: float, depth: float) -> str:
    """The side of the frame nearest a point (a ladder's climber faces away from it)."""
    distances = {
        "south": at[1],
        "north": depth - at[1],
        "west": at[0],
        "east": width - at[0],
    }
    return min(distances, key=lambda side: (distances[side], side))


def _tread(f: Frame, pid: str, centre: Vec, along: tuple[float, float], going: float, w: float):
    """A tread: *going* deep along the flight, *w* wide, 0.03 thick."""
    u0, v0 = (going, w) if abs(along[0]) > 0.5 else (w, going)
    return f.box(
        pid,
        centre[0] - u0 / 2,
        centre[1] - v0 / 2,
        centre[2] - GRATING,
        centre[0] + u0 / 2,
        centre[1] + v0 / 2,
        centre[2],
        "grating",
    )


def _flat(f: Frame, pid: str, a: Vec, b: Vec, z: float) -> dict[str, Any]:
    return f.box(
        pid,
        min(a[0], b[0]),
        min(a[1], b[1]),
        z - GRATING,
        max(a[0], b[0]),
        max(a[1], b[1]),
        z,
        "grating",
    )


_FACING = {"south": (0.0, -1.0), "north": (0.0, 1.0), "east": (1.0, 0.0), "west": (-1.0, 0.0)}


def _ladder_inward(structure: Any, a: str, b: str) -> tuple[float, float]:
    """The frame point the lower flights of a ladder between levels *a* and *b* of
    *structure* step towards: the middle of the lower one (of the frame, from grade)."""
    low = min((a, b), key=lambda x: structure.elevation(x) or 0.0)
    level = next((lv for lv in structure.levels if lv.id == low), None)
    if level is None:
        return (structure.width / 2, structure.depth / 2)
    x0, y0, x1, y1 = _full(level, structure.width, structure.depth)
    return ((x0 + x1) / 2, (y0 + y1) / 2)


def _ladder(
    f: Frame,
    pid: str,
    at: tuple[float, float],
    z0: float,
    z1: float,
    facing: str | tuple[float, float],
    refs: dict[str, Any],
    source: str = "declared",
    inward: tuple[float, float] | None = None,
    anchor: str = "top",
) -> dict[str, Any]:
    """Two rails at *at* (frame coordinates) from *z0* to *z1* + the handrail height; a cage
    on the climber's side above :data:`CAGE_ABOVE` of rise. A climb over
    :data:`LADDER_SINGLE_FLIGHT` is split into equal flights of at most :data:`LADDER_FLIGHT`,
    staggered :data:`LADDER_STAGGER` apart along the rungs towards *inward* (a frame point,
    e.g. the middle of the level the ladder starts from), with the top flight at *at*
    (*anchor* ``top``) or the lowest one (``foot``), each with its rails to the handhold above
    its top, its cage (a lower flight's up to the rest landing), and a rest landing
    (``rest-<k>``, a grating on the climber's side spanning both flights) where one flight
    ends and the next starts (``flight-<k>/rail-<n>``, ``flight-<k>/cage``). ``base`` is the
    foot of the lowest flight, ``top`` the head of the highest. *facing*: the side the
    climber's back points to, or a unit vector."""
    fx, fy = _FACING[facing] if isinstance(facing, str) else facing
    px, py = -fy, fx  # along the rungs
    if inward is not None and (inward[0] - at[0]) * px + (inward[1] - at[1]) * py < 0:
        px, py = -px, -py  # the other flights step towards the inside
    rail = ("FL70x12", 0.012, 0.07)
    rise = z1 - z0
    count = 1 if rise <= LADDER_SINGLE_FLIGHT + 1e-9 else math.ceil(rise / LADDER_FLIGHT - 1e-9)

    def offset(k: int) -> float:
        """How far flight *k* stands from *at* along the rungs."""
        return LADDER_STAGGER * (((count - 1 - k) if anchor == "top" else k) % 2)

    parts = []
    cage = rise > CAGE_ABOVE + 1e-9
    foot = head = at
    for k in range(count):
        shift = offset(k)
        c0 = (at[0] + px * shift, at[1] + py * shift)
        if k == 0:
            foot = c0
        head = c0
        zb, zt = z0 + rise * k / count, z0 + rise * (k + 1) / count
        name = pid if count == 1 else f"{pid}/flight-{k}"
        top = zt + HANDRAIL_HEIGHT
        for n, sign in enumerate((-1, 1)):
            p = (c0[0] + px * sign * LADDER_WIDTH / 2, c0[1] + py * sign * LADDER_WIDTH / 2)
            parts.append(f.member(f"{name}/rail-{n}", (*p, zb), (*p, top), rail))
        if cage:
            c = (c0[0] + fx * 0.35, c0[1] + fy * 0.35)
            parts.append(
                {
                    "id": f"{name}/cage",
                    "kind": "cylinder",
                    "material": "cage",
                    "start": f.site(c[0], c[1], zb + 2.3),
                    "end": f.site(c[0], c[1], top if k == count - 1 else zt),
                    "radius": 0.35,
                }
            )
        if k > 0:  # the rest landing between flight k - 1 and flight k
            other = offset(k - 1)
            lo = min(shift, other) - LADDER_WIDTH / 2 - 0.1
            hi = max(shift, other) + LADDER_WIDTH / 2 + 0.1
            corners = [
                (at[0] + px * s_ + fx * d, at[1] + py * s_ + fy * d)
                for s_ in (lo, hi)
                for d in (0.05, 0.8)
            ]
            us, vs = [q[0] for q in corners], [q[1] for q in corners]
            parts.append(
                f.box(
                    f"{pid}/rest-{k}",
                    min(us),
                    min(vs),
                    zb - GRATING,
                    max(us),
                    max(vs),
                    zb,
                    "grating",
                )
            )
    return {
        "id": pid,
        "refs": refs,
        "source": source,
        "base": f.site(foot[0], foot[1], z0),
        "top": f.site(head[0], head[1], z1),
        "cage": cage,
        "parts": parts,
    }


# ---------------------------------------------------------------------------
# Buildings and racks
# ---------------------------------------------------------------------------


#: Roof slab of a clad building, m (ASSUMED).
ROOF = 0.2


def building_parts(building: Any, top: float, thickness: float = 0.2) -> list[dict[str, Any]]:
    """Wall panels (:func:`building_walls`), and on a clad building a roof slab (``roof``,
    with a low ridge as detail), door leaves and roller shutters, louvre blades and windows in
    the openings (detail), and the declared crane (:func:`crane_parts`)."""
    parts = building_walls(building, top, thickness)
    f = Frame(building.origin, building.rotation_deg)
    width, depth = building.width, building.depth
    if building.walls != "none":
        parts.append(f.box(f"{building.id}/roof", 0.0, 0.0, top, width, depth, top + ROOF, "roof"))
        rise = 0.06 * min(width, depth)
        along_x = width >= depth
        centre = f.site(width / 2, depth / 2, top + ROOF)
        size = (width, depth, rise)
        ridge = (width, 0.2) if along_x else (0.2, depth)
        parts.append(
            {
                "id": f"{building.id}/roof-ridge",
                "kind": "frustum",
                "material": "roof",
                "centre": centre,
                "size": size,
                "size_end": ridge,
                "rotation_deg": f.rotation,
                "lod": 2,
            }
        )
    for k, opening in enumerate(building.openings, 1):
        parts += _opening_parts(f, building, opening, k, thickness)
    if building.crane is not None:
        parts += crane_parts(f, building, top)
    return parts


def _opening_parts(
    f: Frame, building: Any, opening: Any, k: int, thickness: float
) -> list[dict[str, Any]]:
    left, right, normal = _side_line(opening.side, building.width, building.depth)
    length = math.dist(left[:2], right[:2])
    ux, uy = (right[0] - left[0]) / length, (right[1] - left[1]) / length
    nx, ny, _ = normal
    a = min(length, opening.offset)
    b = min(length, opening.offset + opening.width)
    z0, z1 = opening.sill, opening.sill + opening.height
    name = f"{building.id}/{opening.id or f'opening-{k}'}"

    def panel(pid: str, s0: float, s1: float, w0: float, w1: float, d0: float, d1: float, mat):
        p0 = (left[0] + ux * s0 + nx * d0, left[1] + uy * s0 + ny * d0)
        p1 = (left[0] + ux * s1 + nx * d1, left[1] + uy * s1 + ny * d1)
        box = f.box(
            pid,
            min(p0[0], p1[0]),
            min(p0[1], p1[1]),
            w0,
            max(p0[0], p1[0]),
            max(p0[1], p1[1]),
            w1,
            mat,
        )
        return {**box, "lod": 2}

    mid = thickness / 2
    if opening.kind == "door":
        return [panel(f"{name}/leaf", a, b, z0, z1, mid - 0.025, mid + 0.025, "door")]
    if opening.kind == "roller_door":
        return [
            panel(f"{name}/shutter", a, b, z0, z1, mid - 0.03, mid + 0.03, "door"),
            panel(
                f"{name}/drum", a - 0.1, b + 0.1, z1, z1 + 0.5, thickness, thickness + 0.5, "door"
            ),
        ]
    if opening.kind == "window":
        return [panel(f"{name}/glass", a, b, z0, z1, mid - 0.01, mid + 0.01, "glass")]
    if opening.kind == "louvre":
        blades = []
        n = max(1, math.floor((z1 - z0) / 0.15))
        for j in range(n):
            z = z0 + (j + 0.5) * (z1 - z0) / n
            blades.append(
                panel(f"{name}/blade-{j + 1}", a, b, z - 0.01, z + 0.01, 0.0, thickness, "louvre")
            )
        return blades
    return []


def crane_parts(f: Frame, building: Any, top: float) -> list[dict[str, Any]]:
    """An overhead travelling crane: two runway girders along the building's longer side,
    1.5 m below the roof (or at ``rail_elevation``), and as detail the bridge girder across
    them at a third of the runway, its end carriages, the crab and the hook block."""
    crane = building.crane
    width, depth = building.width, building.depth
    rail = crane.rail_elevation if crane.rail_elevation is not None else top - 1.5
    along_x = width >= depth
    run, span = (width, depth) if along_x else (depth, width)
    girder = ("HEB600", 0.3, 0.6) if crane.capacity_t > 20 else ("HEB400", 0.3, 0.4)
    inset = 0.5

    def at(s: float, t: float, z: float) -> Vec:
        return (s, t, z) if along_x else (t, s, z)

    pid = f"{building.id}/crane"
    z = rail - girder[2] / 2
    parts = [
        f.member(f"{pid}/runway-{n}", at(0.2, t, z), at(run - 0.2, t, z), girder, "crane")
        for n, t in enumerate((inset, span - inset), 1)
    ]
    s = run / 3
    bridge = ("box", 0.5, max(0.6, 0.04 * span))
    zb = rail + 0.2 + bridge[2] / 2
    item = f.member(f"{pid}/bridge", at(s, inset, zb), at(s, span - inset, zb), bridge, "crane")
    parts.append({**item, "lod": 2})
    for n, t in enumerate((inset, span - inset), 1):
        carriage = f.member(
            f"{pid}/end-carriage-{n}",
            at(s - 1.2, t, rail + 0.2),
            at(s + 1.2, t, rail + 0.2),
            ("box", 0.4, 0.4),
            "crane",
        )
        parts.append({**carriage, "lod": 2})
    crab = f.site(*at(s, span / 2, zb + bridge[2] / 2 + 0.4))
    hook = f.site(*at(s, span / 2, rail - 2.5))
    parts.append(
        {
            "id": f"{pid}/crab",
            "kind": "box",
            "material": "crane",
            "centre": crab,
            "size": (1.4, 1.6, 0.8) if along_x else (1.6, 1.4, 0.8),
            "rotation_deg": f.rotation,
            "lod": 2,
        }
    )
    parts.append(
        {
            "id": f"{pid}/rope",
            "kind": "cylinder",
            "material": "steel",
            "start": (crab[0], crab[1], crab[2] - 0.4),
            "end": hook,
            "radius": 0.02,
            "lod": 2,
        }
    )
    parts.append(
        {
            "id": f"{pid}/hook-block",
            "kind": "box",
            "material": "crane",
            "centre": (hook[0], hook[1], hook[2] - 0.25),
            "size": (0.4, 0.3, 0.5),
            "rotation_deg": f.rotation,
            "lod": 2,
        }
    )
    return parts


def building_walls(building: Any, top: float, thickness: float = 0.2) -> list[dict[str, Any]]:
    """Wall panels of a building's clad sides, cut around its openings."""
    walls = building.walls
    sides = [] if walls == "none" else list(SIDES) if walls == "all" else list(walls)
    if not sides:
        return []
    f = Frame(building.origin, building.rotation_deg)
    width, depth = building.width, building.depth
    parts = []
    for side in SIDES:
        if side not in sides:
            continue
        left, right, normal = _side_line(side, width, depth)
        length = math.dist(left[:2], right[:2])
        ux, uy = (right[0] - left[0]) / length, (right[1] - left[1]) / length
        nx, ny, _ = normal
        pieces = _cut(0.0, length, top, [o for o in building.openings if o.side == side])
        for k, (a, b, z0, z1) in enumerate(pieces):
            p0 = (left[0] + ux * a, left[1] + uy * a)
            p1 = (left[0] + ux * b + nx * thickness, left[1] + uy * b + ny * thickness)
            parts.append(
                f.box(
                    f"{building.id}/wall-{side}-{k}",
                    min(p0[0], p1[0]),
                    min(p0[1], p1[1]),
                    z0,
                    max(p0[0], p1[0]),
                    max(p0[1], p1[1]),
                    z1,
                    building.wall_material,
                )
            )
    return parts


#: Thickness of a bund wall, m (ASSUMED).
BUND_WALL = 0.3


def bund_walls(area: Any, height: float) -> list[dict[str, Any]]:
    """The four concrete walls of a bund along the inside of its box."""
    x0, y0, x1, y1 = area.box
    f = Frame((0.0, 0.0), 0.0)
    t = BUND_WALL
    sides = {
        "south": (x0, y0, x1, y0 + t),
        "north": (x0, y1 - t, x1, y1),
        "west": (x0, y0 + t, x0 + t, y1 - t),
        "east": (x1 - t, y0 + t, x1, y1 - t),
    }
    return [
        f.box(f"{area.id}/wall-{side}", a, b, 0.0, c, d, height, "concrete")
        for side, (a, b, c, d) in sides.items()
    ]


def _rack_at(points: list[tuple[float, float]], s: float) -> tuple[float, float, float, float]:
    """``(x, y, ux, uy)``: the point at arc *s* along a rack's centreline and its direction."""
    run = 0.0
    x, y, ux, uy = points[0][0], points[0][1], 1.0, 0.0
    for a, b in zip(points, points[1:], strict=False):
        length = math.dist(a, b)
        if length > 1e-9:
            x, y = b
            ux, uy = (b[0] - a[0]) / length, (b[1] - a[1]) / length
        if run + length >= s - 1e-9 and length > 1e-9:
            t = (s - run) / length
            return a[0] + (b[0] - a[0]) * t, a[1] + (b[1] - a[1]) * t, ux, uy
        run += length
    return x, y, ux, uy


def rack_stations(rack: Any, spacing: float) -> tuple[list[float], list[float]]:
    """Arcs along *rack* of its bents (every *spacing*, or the rack's own ``bent_spacing_m``,
    evenly) and of the beams of its ``intermediate_supports`` between them (none without)."""
    spacing = getattr(rack, "bent_spacing_m", None) or spacing
    points = [tuple(p) for p in rack.points]
    total = sum(math.dist(a, b) for a, b in zip(points, points[1:], strict=False))
    count = max(1, round(total / spacing))
    bents = [total * k / count for k in range(count + 1)]
    extra = getattr(rack, "intermediate_supports", None)
    mids: list[float] = []
    if extra is not None:
        for s0, s1 in zip(bents, bents[1:], strict=False):
            n = max(1, math.ceil((s1 - s0) / extra.spacing_m - 1e-9))
            mids += [s0 + (s1 - s0) * j / n for j in range(1, n)]
    return bents, mids


#: A branch rack's tier this far below a tier of the rack it joins (or level with it) runs its
#: lanes through that tier's intermediate steel at the joint, m (a beam is about 0.4 m deep).
JOINT_DROP = 1.0


def rack_steel(rack: Any, spacing: float, others: Any = ()) -> list[dict[str, Any]]:
    """Bents along a rack (see the module text), and its intermediate steel where declared.
    An end bent standing inside one of the *others* racks (a branch rack's first bent at its
    joint, or both racks' end bents at a corner) is left out: the other rack's steel carries
    the joint, and its lanes run through there. A bent along the rack, where a branch joins
    it, stays."""
    if not rack.levels:
        return []
    from chemeascode.domains.spatial.layout_distances import _inside
    from chemeascode.domains.spatial.layout_validate import strip

    joints = [polygon for other in others for polygon in strip(other.points, other.width)]
    top = max(rack.levels)
    col = ("HEB300", 0.3, 0.3)
    beam = section([rack.width], BEAMS, BEAM_LARGEST, None)
    parts = []
    points = [tuple(p) for p in rack.points]
    stations, mids = rack_stations(rack, spacing)
    half = rack.width / 2 + col[1] / 2  # columns stand outside the usable width
    f = Frame((0.0, 0.0), 0.0)

    def ends_at(s: float) -> list[tuple[float, float]]:
        x, y, ux, uy = _rack_at(points, s)
        nx, ny = -uy, ux
        return [(x + nx * half, y + ny * half), (x - nx * half, y - ny * half)]

    skipped = set()
    for k, s in enumerate(stations):
        x, y, _, _ = _rack_at(points, s)
        end = k in (0, len(stations) - 1)
        if end and any(_inside((x, y), polygon) for polygon in joints):
            skipped.add(k)
            continue
        ends = ends_at(s)
        for side, (px, py) in enumerate(ends):
            parts.append(
                f.member(f"{rack.id}/bent-{k}/col-{side}", (px, py, 0.0), (px, py, top), col)
            )
        for level in sorted(rack.levels):
            z = level - beam[2] / 2
            parts.append(
                f.member(
                    f"{rack.id}/bent-{k}/beam-{level:g}",
                    (*ends[0], z),
                    (*ends[1], z),
                    beam,
                )
            )
    extra = getattr(rack, "intermediate_supports", None)
    if extra is None:
        return parts
    tiers = sorted(extra.levels if extra.levels is not None else rack.levels)
    across = section([rack.width], BEAMS, BEAM_LARGEST, extra.section)

    def in_joint(a: tuple[float, float], b: tuple[float, float], level: float) -> bool:
        """Whether a member from *a* to *b* (plan) on the tier *level* passes through another
        rack's strip where that rack has a tier just below it (within JOINT_DROP): where a
        branch rack joins, its lanes cross this rack's edge there."""
        n = max(2, math.ceil(math.dist(a, b) / 0.25))
        return any(
            _inside((a[0] + (b[0] - a[0]) * t / n, a[1] + (b[1] - a[1]) * t / n), polygon)
            for t in range(n + 1)
            for other in others
            if any(level - JOINT_DROP < z <= level + 1e-9 for z in other.levels)
            for polygon in strip(other.points, other.width)
        )

    for k, (s0, s1) in enumerate(zip(stations, stations[1:], strict=False)):
        inner = [s for s in mids if s0 < s < s1]
        along = section([s1 - s0], BEAMS, BEAM_LARGEST, extra.section)
        cuts = [s0, *inner, s1]
        for level in tiers:
            for side in (0, 1):
                for n, (a, b) in enumerate(zip(cuts, cuts[1:], strict=False)):
                    z = level - along[2] / 2
                    if in_joint(ends_at(a)[side], ends_at(b)[side], level):
                        continue
                    parts.append(
                        f.member(
                            f"{rack.id}/bay-{k}/stringer-{level:g}-{side}-{n}",
                            (*ends_at(a)[side], z),
                            (*ends_at(b)[side], z),
                            along,
                        )
                    )
            for j, s in enumerate(inner, 1):
                ends = ends_at(s)
                if in_joint(ends[0], ends[1], level):
                    continue
                z = level - across[2] / 2
                parts.append(
                    f.member(
                        f"{rack.id}/bay-{k}/mid-{j}/beam-{level:g}",
                        (*ends[0], z),
                        (*ends[1], z),
                        across,
                    )
                )
    return parts


#: The column and crossbar (cap) of a pipe support, ASSUMED.
SUPPORT_POST = ("HEB200", 0.2, 0.2)
#: A post's (stub's) cap plate along the crossbar direction, m (ASSUMED).
SUPPORT_CAP = 0.3


def support_steel(support: Any, base: float) -> list[dict[str, Any]]:
    """The parts of a pipe support (:class:`~chemeascode.domains.spatial.schemas.PipeSupport`
    or a proposal with the same fields) standing on *base*: its column up to the crossbar, and
    the crossbar (a cap on a post or stub), top of steel at ``top``, across at
    ``rotation_deg``."""
    sec = section([], (), SUPPORT_POST, support.section) if support.section else SUPPORT_POST
    x, y = support.at
    a = math.radians(support.rotation_deg)
    width = support.width if support.kind == "t_post" else SUPPORT_CAP
    dx, dy = math.cos(a) * width / 2, math.sin(a) * width / 2
    z = support.top - sec[2] / 2
    f = Frame((0.0, 0.0), 0.0)
    parts = [
        f.member(f"{support.id}/column", (x, y, base), (x, y, support.top - sec[2]), sec),
        f.member(
            f"{support.id}/{'crossbar' if support.kind == 't_post' else 'cap'}",
            (x - dx, y - dy, z),
            (x + dx, y + dy, z),
            sec,
        ),
    ]
    if base <= 1e-6:  # a footing at grade
        parts.append(
            f.box(
                f"{support.id}/footing", x - 0.3, y - 0.3, -0.4, x + 0.3, y + 0.3, 0.1, "concrete"
            )
        )
        parts[-1]["lod"] = 2
    return parts


def rack_ladders(rack: Any, others: Any, file: str) -> list[dict[str, Any]]:
    """The access ladders of a rack: its declared ``ladders``, else one proposed (``source:
    generated``, ``review_needed``) at each end that is no joint with another rack, from
    grade to the top tier, just beyond the end bent beside its first column."""
    if not rack.levels:
        return []
    from chemeascode.domains.spatial.layout_distances import _inside
    from chemeascode.domains.spatial.layout_validate import strip

    joints = [polygon for other in others for polygon in strip(other.points, other.width)]
    points = [tuple(p) for p in rack.points]
    top = max(rack.levels)
    if rack.ladders is not None:
        wanted = [(ladder.id, ladder.end, "declared") for ladder in rack.ladders]
    else:
        wanted = [(f"ladder-{end}", end, "generated") for end in ("start", "end")]
    f = Frame((0.0, 0.0), 0.0)
    found = []
    for name, end, source in wanted:
        a, b = (points[0], points[1]) if end == "start" else (points[-1], points[-2])
        if source == "generated" and any(_inside(a, polygon) for polygon in joints):
            continue  # the end joins another rack: reached from there
        length = math.dist(a, b) or 1.0
        ux, uy = (a[0] - b[0]) / length, (a[1] - b[1]) / length  # outward along the rack
        nx, ny = -uy, ux
        side = rack.width / 2 - 0.4
        at = (a[0] + ux * 0.6 + nx * side, a[1] + uy * 0.6 + ny * side)
        entry = _ladder(f, f"{rack.id}/{name}", at, 0.0, top, (ux, uy), {"file": file}, source, a)
        entry.update({"from": "grade", "to": f"{top:g}", "end": end})
        if source == "generated":
            entry.update(review_needed=True, reason=f"access to the tiers at the rack's {end}")
        found.append(entry)
    return found


# ---------------------------------------------------------------------------
# Platforms
# ---------------------------------------------------------------------------

PLATFORM_FAMILIES = ("vessel", "column", "filter")


def _arc(angles: list[float]) -> tuple[float, float] | None:
    """The smallest arc [from, to] (degrees ccw, 0..360) covering *angles* plus the margin;
    None (all round) when it would span more than 270 degrees."""
    ordered = sorted(a % 360 for a in angles)
    if not ordered:
        return None
    gaps = [
        (
            (ordered[(i + 1) % len(ordered)] - ordered[i]) % 360
            or (360 if len(ordered) == 1 else 0),
            i,
        )
        for i in range(len(ordered))
    ]
    gap, i = max(gaps)
    span = 360 - gap + 2 * ARC_MARGIN
    if span > 270:
        return None
    start = (ordered[(i + 1) % len(ordered)] - ARC_MARGIN) % 360
    return (round(start, 3), round((start + span) % 360, 3) or 360.0)


def platform_entry(
    item: dict[str, Any],
    index: int,
    floor: float,
    arc: tuple[float, float] | None,
    width: float,
    ladder_angle: float,
    below: float,
    source: str,
    refs: dict[str, Any],
    on: float | None = None,
    below_arc: tuple[float, float] | None = None,
) -> dict[str, Any]:
    """A platform around a vertical item at absolute elevation *floor* (see the module text);
    its ladder from *below* at *ladder_angle* (degrees ccw, site frame): just outside the
    platform, or with *on* (the width of the platform below, a circular one) standing on the
    middle of the walkway of the platform below, whose arc is *below_arc* (the flights of a
    tall climb step towards its middle)."""
    tag = item["tag"]
    x, y, z = item["position"]
    pid = f"{tag}/platform-{index}"
    parts = []
    radius = (item["dimensions"].get("diameter") or 1.0) / 2
    if item["shape"] == "vertical_cylinder":
        kind = "circular"
        inner, outer = radius + 0.1, radius + 0.1 + width
        parts.append(
            {
                "id": f"{pid}/grating",
                "kind": "annulus",
                "material": "grating",
                "centre": (x, y, floor),
                "radius": inner,
                "radius_end": outer,
                "depth": GRATING,
                **({"arc_deg": arc} if arc else {}),
            }
        )
        parts.append(
            {
                "id": f"{pid}/handrail",
                "kind": "annulus",
                "material": "handrail",
                "centre": (x, y, floor + HANDRAIL_HEIGHT),
                "radius": outer - 0.05,
                "radius_end": outer,
                "depth": 0.05,
                **({"arc_deg": arc} if arc else {}),
            }
        )
        for name, height, inner, depth, material in (
            ("midrail", floor + MIDRAIL_HEIGHT, outer - 0.04, 0.04, "handrail"),
            ("toe-plate", floor + TOE_PLATE, outer - 0.01, TOE_PLATE, "steel"),
        ):
            parts.append(
                {
                    "id": f"{pid}/{name}",
                    "kind": "annulus",
                    "material": material,
                    "centre": (x, y, height),
                    "radius": inner,
                    "radius_end": outer,
                    "depth": depth,
                    "lod": 2,
                    **({"arc_deg": arc} if arc else {}),
                }
            )
        a0, a1 = arc if arc else (0.0, 360.0)
        span = (a1 - a0) % 360 or 360.0
        posts = max(2, math.ceil(math.radians(span) * outer / POST_PITCH - 1e-9) + 1)
        for k in range(posts):
            a = math.radians(a0 + span * k / (posts - 1 if span < 360 else posts))
            p = (x + (outer - 0.025) * math.cos(a), y + (outer - 0.025) * math.sin(a))
            parts.append(
                {
                    "id": f"{pid}/post-{k}",
                    "kind": "cylinder",
                    "material": "handrail",
                    "start": (*p, floor),
                    "end": (*p, floor + HANDRAIL_HEIGHT),
                    "radius": 0.02,
                    "lod": 2,
                }
            )
    else:
        kind = "rectangular"
        x0, y0, _, x1, y1, _ = item["bbox"]
        f = Frame((0.0, 0.0), 0.0)
        g = 0.1
        for k, (u0, v0, u1, v1) in enumerate(
            (
                (x0 - g - width, y0 - g - width, x1 + g + width, y0 - g),
                (x0 - g - width, y1 + g, x1 + g + width, y1 + g + width),
                (x0 - g - width, y0 - g, x0 - g, y1 + g),
                (x1 + g, y0 - g, x1 + g + width, y1 + g),
            )
        ):
            parts.append(
                f.box(f"{pid}/grating-{k}", u0, v0, floor - GRATING, u1, v1, floor, "grating")
            )
        e = g + width
        ring = ((x0 - e, y0 - e), (x1 + e, y0 - e), (x1 + e, y1 + e), (x0 - e, y1 + e))
        for k, (a, b) in enumerate(zip(ring, ring[1:] + ring[:1], strict=False)):
            parts += _guard_rail(f, f"{pid}/handrail-{k}", a, b, floor)
        outer = max(x1 - x0, y1 - y0) / 2 + g + width
    a = math.radians(ladder_angle)

    def toward(arc_: tuple[float, float] | None, r: float) -> tuple[float, float]:
        """The point at *r* in the middle of *arc_* (the item's centre: all round)."""
        if arc_ is None:
            return (x, y)
        middle = math.radians(arc_[0] + ((arc_[1] - arc_[0]) % 360 or 360.0) / 2)
        return (x + math.cos(middle) * r, y + math.sin(middle) * r)

    if on is None or kind != "circular":
        # beside the platforms: a tall climb keeps its lowest flight here (on or beside the
        # floor below) and steps its upper flights towards the middle of this platform
        at = (x + math.cos(a) * (outer + 0.25), y + math.sin(a) * (outer + 0.25))
        inward, anchor = toward(arc, outer + 0.25), "foot"
    else:
        # on the walkway below, beside this platform's arc end: a tall climb keeps its top
        # flight here and steps its lower flights towards the middle of the arc below
        mid = radius + 0.1 + on / 2
        at = (x + math.cos(a) * mid, y + math.sin(a) * mid)
        inward, anchor = toward(below_arc, mid), "top"
    f = Frame((0.0, 0.0), 0.0)
    ladder = _ladder(
        f,
        f"{pid}/ladder",
        at,
        below,
        floor,
        (math.cos(a), math.sin(a)),
        {"tag": tag},
        source,
        inward,
        anchor,
    )
    entry: dict[str, Any] = {
        "id": pid,
        "refs": refs,
        "source": source,
        "tag": tag,
        "kind": kind,
        "elevation": floor,
        "item_elevation": floor - z,
        "width": width,
        "parts": parts,
        "ladder": ladder,
    }
    if arc is not None:
        entry["arc_deg"] = arc
    if source == "generated":
        entry["review_needed"] = True
    return entry


def platforms_for(
    item: dict[str, Any],
    access: Any,
    inline: list[dict[str, Any]],
    file: str,
) -> list[dict[str, Any]]:
    """Declared platforms of *item* (its placement's ``access``; ``platforms: []`` declares
    none), else proposals from its nozzles and the in-line valves near its shell (see the
    module text)."""
    x, y, z = item["position"]
    rotation = item["rotation_deg"]
    tag = item["tag"]
    radius = (item["dimensions"].get("diameter") or 0.0) / 2
    if access is not None:
        declared = sorted(access.platforms, key=lambda p: p.elevation)
        arcs: list[tuple[float, float] | None] = [
            None if p.arc_deg is None else tuple((a + rotation) % 360 for a in p.arc_deg)  # type: ignore[misc]
            for p in declared
        ]
        side = None if access.ladder_side is None else (access.ladder_side + rotation) % 360
        widths = [p.width for p in declared]
        angles = _ladder_angles(arcs, widths, radius, side)
        found = []
        below = z
        for k, platform in enumerate(declared):
            floor = z + platform.elevation
            found.append(
                platform_entry(
                    item,
                    k + 1,
                    floor,
                    arcs[k],
                    platform.width,
                    angles[k],
                    below,
                    "declared",
                    {"tag": tag, "file": file},
                    _upper_on(arcs, angles, widths, radius, k),
                    arcs[k - 1] if k else None,
                )
            )
            below = floor
        return found
    if item["family"] not in PLATFORM_FAMILIES or item["shape"] not in (
        "vertical_cylinder",
        "box",
    ):
        return []
    points: list[tuple[float, float, str]] = []  # (floor, angle, what)
    for nozzle in item["nozzles"]:
        px, py, pz = nozzle["point"]
        if pz - z > PLATFORM_ABOVE + 1e-9:
            angle = math.degrees(math.atan2(py - y, px - x)) % 360
            points.append((pz - NOZZLE_ABOVE_FLOOR, angle, nozzle["id"]))
    reach = radius + 2.0 if radius else 2.0
    for valve in inline:
        if valve.get("kind") not in ("valve", "check_valve", "safety_valve"):
            continue
        px, py, pz = valve["point"]
        if pz - z > PLATFORM_ABOVE + 1e-9 and math.hypot(px - x, py - y) <= reach:
            angle = math.degrees(math.atan2(py - y, px - x)) % 360
            points.append((pz - NOZZLE_ABOVE_FLOOR, angle, valve["id"]))
    if not points:
        return []
    points.sort()
    groups: list[list[tuple[float, float, str]]] = []
    for point in points:
        if groups and point[0] - groups[-1][0][0] <= PLATFORM_GROUP + 1e-9:
            groups[-1].append(point)
        else:
            groups.append([point])
    circular = item["shape"] == "vertical_cylinder"
    wanted = [[g[1] for g in group] for group in groups]
    arcs = [_arc(angles) if circular else None for angles in wanted]
    widths = [PLATFORM_WIDTH] * len(groups)
    top = item["bbox"][5]
    floors = [
        min(max(group[0][0], z + PLATFORM_ABOVE - NOZZLE_ABOVE_FLOOR), top) for group in groups
    ]
    # from the top down: a platform below takes in the foot of the ladder of the one above
    # (the ladder's half width and clearance either side, and on a climb of several flights
    # the lowest one's step towards the middle of the arc below); each ladder keeps the angle
    # chosen here
    angles = [0.0] * len(groups)
    for k in range(len(groups) - 1, 0, -1):
        angle = _ladder_angles(arcs[k - 1 : k + 1], widths[k - 1 : k + 1], radius, None)[1]
        angles[k] = angle
        if not circular:
            continue
        margin = _ladder_margin(radius, widths[k - 1])
        if not _covers(arcs[k - 1], angle, margin):
            wanted[k - 1] += [angle - margin, angle, angle + margin]
            arcs[k - 1] = _arc(wanted[k - 1])
        lower = arcs[k - 1]
        if lower is not None and floors[k] - floors[k - 1] > LADDER_SINGLE_FLIGHT + 1e-9:
            span = (lower[1] - lower[0]) % 360 or 360.0
            middle = lower[0] + span / 2
            toward = 1.0 if ((middle - angle + 180) % 360) - 180 >= 0 else -1.0
            mid = radius + 0.1 + widths[k - 1] / 2
            step = math.degrees(LADDER_STAGGER / mid) + margin
            if not _covers(lower, angle + toward * step, 0.0):
                wanted[k - 1].append(angle + toward * step)
                arcs[k - 1] = _arc(wanted[k - 1])
    angles[0] = _ladder_angles(arcs[:1], widths[:1], radius, None)[0]
    found = []
    below = z
    for k, group in enumerate(groups):
        floor = floors[k]
        refs = {"tag": tag, "file": file}
        entry = platform_entry(
            item,
            k + 1,
            floor,
            arcs[k],
            PLATFORM_WIDTH,
            angles[k],
            below,
            "generated",
            refs,
            _upper_on(arcs, angles, widths, radius, k),
            arcs[k - 1] if k else None,
        )
        entry["serves"] = sorted({g[2] for g in group})
        found.append(entry)
        below = floor
    return found


def _covers(arc: tuple[float, float] | None, angle: float, margin: float) -> bool:
    """Whether the arc (None: all round) holds *angle* at least *margin* degrees in."""
    if arc is None:
        return True
    span = (arc[1] - arc[0]) % 360 or 360.0
    return margin - 1e-9 <= (angle - arc[0]) % 360 <= span - margin + 1e-9


def _ladder_margin(radius: float, width: float) -> float:
    """Degrees between a ladder on the middle of a ring walkway (of an item of *radius*,
    *width* wide) and the end of an arc: half the ladder and 0.3 m clear."""
    mid = radius + 0.1 + width / 2
    return math.degrees((LADDER_WIDTH / 2 + 0.3) / mid)


def _ladder_angles(
    arcs: list[tuple[float, float] | None],
    widths: list[float],
    radius: float,
    side: float | None,
) -> list[float]:
    """The angle (degrees ccw, site frame) of the ladder of each platform of an item, lowest
    first: the declared *side*, else the lowest one's at the start of its arc and every other
    one's just beyond an end of its own arc (it stands on the platform below and the climber
    steps off beside the platform's end; the end the arc below reaches, else the one it needs
    the least widening for) or, for a platform all round, inside the end of the arc of the
    platform below (beside both platforms)."""
    found = []
    for k, arc in enumerate(arcs):
        if side is not None:
            found.append(side)
        elif k == 0:
            found.append((arc[0] + 5) % 360 if arc else 0.0)
        else:
            margin = _ladder_margin(radius, widths[k - 1])
            lower = arcs[k - 1]
            if arc is not None:

                def widening(a: float, lower: Any = lower, margin: float = margin) -> float:
                    if _covers(lower, a, margin):
                        return 0.0
                    return min((lower[0] - a) % 360, (a - lower[1]) % 360)

                ends = ((arc[0] - margin) % 360, (arc[1] + margin) % 360)
                found.append(min(ends, key=widening))
            elif lower is not None:
                found.append((lower[1] - margin) % 360)
            else:
                found.append(0.0)
    return found


def _upper_on(
    arcs: list[tuple[float, float] | None],
    angles: list[float],
    widths: list[float],
    radius: float,
    k: int,
) -> float | None:
    """The *on* of :func:`platform_entry` for platform *k*: the width of the platform below
    when its ladder stands on that walkway clear of the end of its own arc; None (the ladder
    outside the rings, the climber stepping off sideways) for the lowest platform and where the
    ladder would touch the platform (all round, rectangular, a ladder side inside its arc or
    less than half the ladder and 0.1 m beyond its end), so it never runs through a grating."""
    arc = arcs[k]
    if k == 0 or arc is None:
        return None
    mid = radius + 0.1 + widths[k - 1] / 2
    half = math.degrees((LADDER_WIDTH / 2 + 0.1) / mid)
    if ((arc[1] - arc[0]) % 360 or 360.0) + 2 * half >= 360.0 - 1e-9:
        return None  # the gap of the arc is narrower than the ladder: it touches either way
    if _covers(((arc[0] - half) % 360, (arc[1] + half) % 360), angles[k], 0.0):
        return None
    return widths[k - 1]


# ---------------------------------------------------------------------------
# Step-overs
# ---------------------------------------------------------------------------

#: A pipe whose top is at most this high above a walkway gets a step-over, m (ASSUMED).
STEP_OVER_MAX = 0.75
#: Clear width of a step-over, m (ASSUMED).
STEP_OVER_WIDTH = 0.8


def _walkways(model: dict[str, Any]) -> list[tuple[str, float, tuple[float, float, float, float]]]:
    """Where people walk: ``(id, floor, [x0, y0, x1, y1])`` of the escape zones' boxes and of
    the structures' level gratings."""
    found = []
    for zone in model.get("zones", []):
        if zone.get("kind") != "escape":
            continue
        for k, volume in enumerate(zone.get("volumes", [])):
            box = volume.get("box")
            if volume.get("shape") == "box" and box:
                found.append((f"{zone['id']}-{k}", box[2], (box[0], box[1], box[3], box[4])))
    for structure in model.get("structures", []):
        for part in structure.get("parts", []):
            if part["kind"] == "box" and part.get("material") == "grating":
                cx, cy, cz = part["centre"]
                dx, dy, dz = part["size"]
                if (part.get("rotation_deg") or 0.0) % 180 > 1e-6:
                    dx, dy = dy, dx
                rect = (cx - dx / 2, cy - dy / 2, cx + dx / 2, cy + dy / 2)
                found.append((part["id"].rsplit("/", 1)[0], cz + dz / 2, rect))
    return found


def _clip_segment(
    a: tuple[float, float], b: tuple[float, float], rect: tuple[float, float, float, float]
) -> tuple[float, float] | None:
    """The parameter range of segment *ab* inside *rect* (Liang-Barsky), None outside."""
    t0, t1 = 0.0, 1.0
    dx, dy = b[0] - a[0], b[1] - a[1]
    for p, q in (
        (-dx, a[0] - rect[0]),
        (dx, rect[2] - a[0]),
        (-dy, a[1] - rect[1]),
        (dy, rect[3] - a[1]),
    ):
        if abs(p) < 1e-12:
            if q < 0:
                return None
            continue
        t = q / p
        if p < 0:
            t0 = max(t0, t)
        else:
            t1 = min(t1, t)
    return (t0, t1) if t1 - t0 > 1e-9 else None


def step_overs(model: dict[str, Any]) -> list[dict[str, Any]]:
    """Step-overs proposed (``source: generated``, ``review_needed``) where a horizontal pipe
    whose top is at most :data:`STEP_OVER_MAX` above a walkway (an escape zone, a structure's
    grating) crosses it: two short flights and a grating over the pipe at the middle of the
    crossing, with handrails. They follow the route: a rebuild moves them with the pipe."""
    walkways = _walkways(model)
    found: list[dict[str, Any]] = []
    seen: set[tuple[str, str]] = set()
    f = Frame((0.0, 0.0), 0.0)
    for pipe in model.get("pipes", []):
        r = pipe["od"] / 2 + pipe.get("insulation_mm", 0.0) / 1000
        points = pipe["points"]
        for a, b in zip(points, points[1:], strict=False):
            if abs(a[2] - b[2]) > 1e-6 or math.dist(a[:2], b[:2]) < 1e-6:
                continue
            for walk, floor, rect in walkways:
                top = a[2] + r - floor
                if a[2] - r < floor - 0.05 or top > STEP_OVER_MAX + 1e-9:
                    continue
                clip = _clip_segment(a[:2], b[:2], rect)
                if clip is None or (pipe["id"], walk) in seen:
                    continue
                seen.add((pipe["id"], walk))
                t = (clip[0] + clip[1]) / 2
                x, y = a[0] + (b[0] - a[0]) * t, a[1] + (b[1] - a[1]) * t
                length = math.dist(a[:2], b[:2])
                ux, uy = (b[0] - a[0]) / length, (b[1] - a[1]) / length
                nx, ny = -uy, ux  # the walking direction, across the pipe
                deck = floor + top + 0.1
                rise = deck - floor
                steps = max(2, math.ceil(rise / MAX_RISER - 1e-9))
                going = 0.25
                half = r + 0.3
                pid = f"step-over-{len(found) + 1}"
                parts = []
                w = STEP_OVER_WIDTH
                rotation = math.degrees(math.atan2(ny, nx))
                parts.append(
                    _rotated(
                        pid + "/deck", (x, y, deck - GRATING / 2), (2 * half, w, GRATING), rotation
                    )
                )
                for sign in (-1, 1):
                    for k in range(1, steps):
                        d = half + (steps - k) * going - going / 2
                        c = (
                            x + nx * sign * d,
                            y + ny * sign * d,
                            floor + rise * k / steps - GRATING / 2,
                        )
                        parts.append(
                            _rotated(
                                f"{pid}/tread-{'ab'[sign > 0]}{k}", c, (going, w, GRATING), rotation
                            )
                        )
                reach = half + (steps - 1) * going
                for side in (-1, 1):
                    ox, oy = ux * side * w / 2, uy * side * w / 2
                    ends = [
                        (x - nx * reach + ox, y - ny * reach + oy, floor + HANDRAIL_HEIGHT),
                        (x - nx * half + ox, y - ny * half + oy, deck + HANDRAIL_HEIGHT),
                        (x + nx * half + ox, y + ny * half + oy, deck + HANDRAIL_HEIGHT),
                        (x + nx * reach + ox, y + ny * reach + oy, floor + HANDRAIL_HEIGHT),
                    ]
                    for k, (p0, p1) in enumerate(zip(ends, ends[1:], strict=False)):
                        rail = f.member(
                            f"{pid}/handrail-{'ab'[side > 0]}{k}", p0, p1, HANDRAIL, "handrail"
                        )
                        parts.append({**rail, "lod": 2})
                xs = [x - abs(nx) * reach - abs(ux) * w / 2, x + abs(nx) * reach + abs(ux) * w / 2]
                ys = [y - abs(ny) * reach - abs(uy) * w / 2, y + abs(ny) * reach + abs(uy) * w / 2]
                found.append(
                    {
                        "id": pid,
                        "refs": {
                            "lines": [pipe["line"]],
                            "segments": [pipe["segment"]],
                            **(
                                {"sheet": pipe["refs"]["sheet"]}
                                if pipe["refs"].get("sheet")
                                else {}
                            ),
                        },
                        "source": "generated",
                        "pipe": pipe["id"],
                        "walkway": walk,
                        "point": (x, y, floor),
                        "height": deck - floor,
                        "box": (xs[0], ys[0], floor, xs[1], ys[1], deck + HANDRAIL_HEIGHT),
                        "review_needed": True,
                        "parts": parts,
                    }
                )
    return found


def _rotated(pid: str, centre: Vec, size: Vec, rotation: float) -> dict[str, Any]:
    return {
        "id": pid,
        "kind": "box",
        "material": "grating",
        "centre": centre,
        "size": size,
        "rotation_deg": rotation % 360,
    }


# ---------------------------------------------------------------------------
# Valve access platforms
# ---------------------------------------------------------------------------

#: A proposed valve platform reaches this far along the pipe past its outer handwheels, m.
VALVE_PLATFORM_MARGIN = 1.0
#: Its near edge stands this far out from the pipe's insulation, m.
VALVE_PLATFORM_GAP = 0.1


def _unreached_valves(document: dict[str, Any], crit: Any) -> list[dict[str, Any]]:
    """The manual valves whose handwheel or lever no walking level reaches (none at most
    ``operator_max_height_m`` below it within ``operator_reach_m`` in plan; a stair flight is
    none) and that have no declared operator, outside the casings: ``{id, label, point
    (handwheel), axis (on the pipe), direction, r (pipe radius with insulation)}``."""
    from chemeascode.domains.spatial.engineering_rules import _part_point
    from chemeascode.domains.spatial.floors import casing_volumes, in_casing, walking_levels

    floors = [f for f in walking_levels(document) if f.kind != "stair"]
    volumes = casing_volumes(document)
    reach, high = crit.operator_reach_m, crit.operator_max_height_m
    pipes = {p["id"]: p for p in document.get("pipes", [])}
    found = []
    for item in document.get("inline", []):
        if item.get("kind") != "valve" or item.get("operator"):
            continue
        names = {p["id"].rsplit("/", 1)[-1]: p for p in item.get("parts") or []}
        if any(n in names for n in ("actuator", "actuator-lower", "motor", "yoke")):
            continue
        part = names.get("handwheel") or names.get("lever")
        point = _part_point(part) if part is not None else None
        if point is None or in_casing(point, volumes):
            continue
        if any(
            -0.05 <= point[2] - f.z <= high + 1e-6 and f.distance(point[0], point[1]) <= reach
            for f in floors
        ):
            continue
        pipe = pipes.get(item.get("pipe", ""))
        r = pipe["od"] / 2 + pipe.get("insulation_mm", 0.0) / 1000 if pipe else 0.1
        found.append(
            {
                "id": item["id"],
                "label": item.get("tag") or item["id"],
                "point": point,
                "axis": tuple(item["point"]),
                "direction": tuple(item["direction"]),
                "r": r,
            }
        )
    return found


def _orientation(direction: tuple[float, ...]) -> str:
    """``x`` or ``y`` for a level pipe along that axis, ``z`` for a vertical one, else ``-``."""
    dx, dy, dz = (abs(c) for c in direction)
    if dz > 0.99:
        return "z"
    if dz < 0.01 and dx > 0.99:
        return "x"
    if dz < 0.01 and dy > 0.99:
        return "y"
    return "-"


def _clusters(valves: list[dict[str, Any]], group: float, window: float) -> list[list[dict]]:
    """Valves of one orientation whose handwheels lie within *group* in plan of one another
    (single linkage), split so that one floor serves each (handwheels within *window* in
    height); a valve on a skewed pipe alone."""
    clusters: list[list[dict[str, Any]]] = []
    clusters += [[v] for v in valves if _orientation(v["direction"]) == "-"]
    for kind in ("x", "y", "z"):
        members = [v for v in valves if _orientation(v["direction"]) == kind]
        left = list(members)
        while left:
            seed = [left.pop(0)]
            k = 0
            while k < len(seed):
                p = seed[k]["point"]
                near = [v for v in left if math.dist(p[:2], v["point"][:2]) <= group + 1e-9]
                for v in near:
                    left.remove(v)
                seed += near
                k += 1
            seed.sort(key=lambda v: (-v["point"][2], v["id"]))
            while seed:  # one floor per handwheel height window, highest first
                top = seed[0]["point"][2]
                part = [v for v in seed if top - v["point"][2] <= window + 1e-9]
                seed = [v for v in seed if v not in part]
                clusters.append(sorted(part, key=lambda v: v["id"]))
    return sorted(clusters, key=lambda c: c[0]["id"])


def _blockers(document: dict[str, Any], rect: tuple[float, ...], z0: float, z1: float) -> list[str]:
    """What stands in the volume over *rect* from *z0* to *z1*: items, pipes, steel, walls."""
    from chemeascode.domains.spatial.geometry3d import Box as Solid3
    from chemeascode.domains.spatial.geometry3d import segment_distance

    x0, y0, x1, y1 = rect
    found = []
    for item in document.get("equipment", []):
        bx = item["bbox"]
        if bx[0] < x1 and bx[3] > x0 and bx[1] < y1 and bx[4] > y0 and bx[2] < z1 and bx[5] > z0:
            found.append(item["tag"])
    box = Solid3("v", ((x0 + x1) / 2, (y0 + y1) / 2, (z0 + z1) / 2), (x1 - x0, y1 - y0, z1 - z0))
    for pipe in document.get("pipes", []):
        r = pipe["od"] / 2 + pipe.get("insulation_mm", 0.0) / 1000
        points = [tuple(p) for p in pipe["points"]]
        if any(
            segment_distance(a, b, box) < r - 1e-6 for a, b in zip(points, points[1:], strict=False)
        ):
            found.append(pipe["id"])
    for owner in [*document.get("structures", []), *document.get("buildings", [])]:
        if owner.get("source") == "generated":
            continue
        fx0, fy0, fx1, fy1 = owner["footprint"]
        if fx0 < x1 and fx1 > x0 and fy0 < y1 and fy1 > y0:
            found.append(owner["id"])
    for rack in document.get("racks", []):
        from chemeascode.domains.spatial.layout_distances import _inside
        from chemeascode.domains.spatial.layout_validate import strip

        corners = [(x0, y0), (x1, y0), (x1, y1), (x0, y1), ((x0 + x1) / 2, (y0 + y1) / 2)]
        if any(_inside(c, poly) for poly in strip(rack["points"], rack["width"]) for c in corners):
            found.append(rack["id"])
    return sorted(set(found))


def _column_blockers(document: dict[str, Any], rect: tuple[float, ...], floor: float) -> list[str]:
    """What the columns of a valve platform over *rect* (one at each corner, as
    :func:`frame_structure` stands them) meet from grade up to under its *floor*: items, pipes
    (the pipe of the valve it serves too), steel, racks."""
    x0, y0, x1, y1 = rect
    _, b, h = section([max(x1 - x0, y1 - y0)], COLUMNS, COLUMN_LARGEST, None)
    half = max(b, h) / 2
    found: set[str] = set()
    for x, y in ((x0, y0), (x1, y0), (x0, y1), (x1, y1)):
        column = (x - half, y - half, x + half, y + half)
        found.update(_blockers(document, column, 0.0, floor - 0.3))
    return sorted(found)


def valve_platform_id(labels: list[str], taken: set[str] | None = None) -> str:
    """The id of a proposed valve access platform serving the valves *labels* (tags, else
    in-line item ids): ``VP-<first valve tag>`` in sorted order, characters other than letters,
    digits, ``-``, ``_`` and ``.`` as ``_``; ``-2``, ``-3``, ... after it when *taken* has it.
    Derived from what it serves, so a rebuild gives the same id and never hands one platform's
    id to another."""
    first = sorted(labels)[0] if labels else "valve"
    sid = "VP-" + re.sub(r"[^A-Za-z0-9_.-]", "_", first)
    if taken and sid in taken:
        sid = next(f"{sid}-{n}" for n in itertools.count(2) if f"{sid}-{n}" not in taken)
    return sid


def valve_platform_proposals(document: dict[str, Any], crit: Any, file: str) -> list[Any]:
    """Valve access platforms proposed for the manual valves no walking level reaches and no
    declared operator serves (see the module text), as structures
    (:class:`~chemeascode.domains.spatial.schemas.Structure`, :func:`valve_platform_id`
    ``VP-<valve tag>``): one platform level
    ``P1`` beside the pipes, ``valve_platform_depth_m`` wide, its floor
    ``valve_platform_operating_m`` below the highest handwheel, with a caged ladder on its far
    edge at the end away from the valves (from :data:`STAIR_ABOVE` the access proposals give
    it a stair). Each ``(structure, reason, blockers)``."""
    from chemeascode.domains.spatial.schemas import Structure

    valves = _unreached_valves(document, crit)
    if not valves:
        return []
    reach = crit.operator_reach_m
    depth = crit.valve_platform_depth_m
    operating = min(crit.valve_platform_operating_m, crit.operator_max_height_m)
    found = []
    # one floor serves the handwheels from it up to the operating height above it
    for cluster in _clusters(valves, crit.valve_platform_group_m, operating):
        top = max(v["point"][2] for v in cluster)
        floor = round(top - operating, 2)
        if floor < 0.3:
            continue
        kind = _orientation(cluster[0]["direction"])
        options = []
        if kind in ("x", "y"):
            a, c = (0, 1) if kind == "x" else (1, 0)  # along, across
            lo = min(v["point"][a] for v in cluster) - VALVE_PLATFORM_MARGIN
            hi = max(v["point"][a] for v in cluster) + VALVE_PLATFORM_MARGIN
            for sign in (1, -1):
                if sign > 0:
                    edge = max(v["axis"][c] + v["r"] for v in cluster) + VALVE_PLATFORM_GAP
                    span = (edge, edge + depth)
                else:
                    edge = min(v["axis"][c] - v["r"] for v in cluster) - VALVE_PLATFORM_GAP
                    span = (edge - depth, edge)
                reached = [v for v in cluster if abs(edge - v["point"][c]) <= reach + 1e-6]
                rect = (lo, span[0], hi, span[1]) if kind == "x" else (span[0], lo, span[1], hi)
                far = {("x", 1): "north", ("x", -1): "south", ("y", 1): "east", ("y", -1): "west"}
                options.append((reached, rect, far[(kind, sign)]))
        else:
            # a vertical (or skewed) pipe's valve: its stem across the pipe; the platform in
            # front of the handwheel, outside the pipe; one round the valves of a group
            rects, sides = [], []
            for v in cluster:
                sx, sy = v["point"][0] - v["axis"][0], v["point"][1] - v["axis"][1]
                norm = math.hypot(sx, sy) or 1.0
                sx, sy = sx / norm, sy / norm
                near = v["r"] + VALVE_PLATFORM_GAP
                if abs(sx) >= abs(sy):
                    x0 = v["axis"][0] + (near if sx > 0 else -near - depth)
                    rects.append((x0, v["point"][1] - 0.75, x0 + depth, v["point"][1] + 0.75))
                    sides.append("east" if sx > 0 else "west")
                else:
                    y0 = v["axis"][1] + (near if sy > 0 else -near - depth)
                    rects.append((v["point"][0] - 0.75, y0, v["point"][0] + 0.75, y0 + depth))
                    sides.append("north" if sy > 0 else "south")
            rect = (
                min(r[0] for r in rects),
                min(r[1] for r in rects),
                max(r[2] for r in rects),
                max(r[3] for r in rects),
            )
            options.append((list(cluster), rect, sides[0]))
        scored = []
        for reached, rect, side in options:
            if not reached:
                continue
            rect = tuple(round(q, 2) for q in rect)
            blockers = _blockers(document, rect, floor - 0.3, floor + 2.1)
            under = _column_blockers(document, rect, floor)
            n = len(set(blockers) | set(under))
            scored.append((-len(reached), n, reached, rect, side, blockers, under))
        if not scored:
            continue
        _, _, reached, rect, side, blockers, under = min(scored, key=lambda s: s[:2])
        found.append((reached, rect, side, floor, blockers, under))
    proposals = []
    # ids from the valves served (a declared structure keeps its own id; a proposal whose id a
    # declared one already has serves the same first valve: it is skipped by the caller's
    # unreached-valve test, or takes a suffix)
    taken = {s.get("id") for s in document.get("structures", [])}
    for reached, rect, side, floor, blockers, under in found:
        x0, y0, x1, y1 = rect
        width, length = x1 - x0, y1 - y0
        sid = valve_platform_id([v["label"] for v in reached], taken)
        taken.add(sid)
        names = ", ".join(v["label"] for v in reached)
        way: dict[str, Any] = {}
        if floor < STAIR_ABOVE - 1e-9:
            # a caged ladder on the far edge, at the end away from the valves (their standing
            # space stays free); from 6 m the access proposals give it a stair
            mx = sum(v["point"][0] for v in reached) / len(reached) - x0
            my = sum(v["point"][1] for v in reached) / len(reached) - y0
            u = 0.4 if mx > width / 2 else width - 0.4
            v_ = 0.4 if my > length / 2 else length - 0.4
            at = {
                "north": (u, length - 0.4),
                "south": (u, 0.4),
                "east": (width - 0.4, v_),
                "west": (0.4, v_),
            }[side]
            way["ladders"] = [
                {
                    "id": "ladder-to-P1",
                    "from": "grade",
                    "to": "P1",
                    "at": [round(at[0], 2), round(at[1], 2)],
                    "facing": side,
                }
            ]
        structure = Structure.model_validate(
            {
                "id": sid,
                "title": f"valve access platform for {names}",
                "origin": [x0, y0],
                "spans_x": [round(width, 2)],
                "spans_y": [round(length, 2)],
                "levels": [
                    {"id": "P1", "elevation": floor, "kind": "platform", "use": "occasional"}
                ],
                **way,
                "serves": [v["id"] for v in reached],
                "notes": "proposed by cheme layout build (ASSUMED sizes)",
            }
        )
        reason = (
            f"{len(reached)} valve(s) out of reach ({names}): no floor at most "
            f"{crit.operator_max_height_m:g} m below the handwheel within "
            f"{crit.operator_reach_m:g} m, no declared operator"
        )
        if blockers:
            reason += f"; check what stands in its way: {', '.join(blockers[:4])}"
        if under:
            reason += f"; its columns from grade stand in: {', '.join(under[:4])}"
        proposals.append((structure, reason, sorted(set(blockers) | set(under))))
    return proposals
