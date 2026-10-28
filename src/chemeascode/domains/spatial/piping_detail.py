"""Piping detail of the 3D model: valve bodies with their operators and flanges, transmitters,
pipe shoes and guides on the steel, and the jacketing of insulated pipes.

Pure geometry on the model document after routing; every part is detail (``lod: 2``): the
clash checks and the router never see it. Sizes follow the pipe's outside diameter (OD, m):

- **Valves** (``inline`` of kind ``valve``, ``check_valve``, ``safety_valve``): two flanges
  (about EN 1092-1 PN 16, ASSUMED) and a body between them (a sphere for ball and globe valves,
  a short cylinder for gate and check valves, a thin disc for a butterfly valve). The operator
  stands on a stem ``up`` (vertical on a horizontal pipe, else horizontal across it): a lever
  on a quarter-turn valve up to DN 150, a gearbox with a handwheel above, a handwheel on a yoke
  for gate and globe valves; a control valve (``Control`` in its DEXPI class) has a diaphragm
  actuator on a yoke, a motor-operated one (``Motor``/``Operated``) an actuator box with its
  motor and handwheel. A safety valve has a bonnet and cap up the stem and an outlet with its
  flange to the side.
- **Instruments** in line: a transmitter on a stand (:func:`shape_details.transmitter`).
- **Supports** (:func:`supports`): where a horizontal pipe crosses a horizontal steel member
  (a rack beam, a structure beam) with its bottom at most 0.15 m above the steel's top: a
  shoe, and on every third support of a pipe on a rack a guide (two stops on the beam).
- **Support steel** (:func:`support_proposals`): where a level run spans farther between its
  supports (or from them to its ends) than the DN's span (``pipe-spans.yaml``), a ``t_post``
  from grade, or a ``stub`` on the steel below (at most ``support_stub_max_m`` below, not
  another line's support steel), at even spacing under the run (``source:
  generated``, ``review_needed``); not on a rack tier (``intermediate_supports`` of the rack
  answer those). Declared support steel (``pipe_supports`` of ``layout/structures.yaml``)
  carries shoes like any beam; the proposals do not until pinned.
- **Jacketing** (:func:`jacket`): ``cold`` (vapour-tight cladding), ``hot`` or ``personnel``
  for a pipe with insulation, from the line list's insulation text.
"""

from __future__ import annotations

import math
import re
from typing import Any

Vec = tuple[float, float, float]

#: A support where a pipe's bottom is at most this far above the steel, m.
SUPPORT_GAP = 0.15
#: Every n-th support of a pipe on a rack is a guide.
GUIDE_EVERY = 3
SHOE_HEIGHT = 0.1
#: The cap width of a stub on steel (as ``structures.SUPPORT_CAP``), m.
SUPPORT_CAP_WIDTH = 0.3


def _add(a: Vec, b: Vec, t: float = 1.0) -> Vec:
    return (a[0] + b[0] * t, a[1] + b[1] * t, a[2] + b[2] * t)


def _cross(a: Vec, b: Vec) -> Vec:
    return (a[1] * b[2] - a[2] * b[1], a[2] * b[0] - a[0] * b[2], a[0] * b[1] - a[1] * b[0])


def _unit(v: Vec) -> Vec:
    n = math.sqrt(v[0] ** 2 + v[1] ** 2 + v[2] ** 2)
    return (v[0] / n, v[1] / n, v[2] / n) if n > 1e-12 else (0.0, 0.0, 1.0)


def _cyl(pid: str, a: Vec, b: Vec, r: float, material: str) -> dict[str, Any]:
    return {
        "id": pid,
        "kind": "cylinder",
        "material": material,
        "start": a,
        "end": b,
        "radius": r,
        "lod": 2,
    }


def _flange(od: float) -> tuple[float, float]:
    from chemeascode.domains.spatial.shape_details import flange_size

    radius, thick, _ = flange_size(od)
    return radius, thick


def stem_of(direction: Vec) -> Vec:
    """The stem of a valve on a pipe along *direction*: up on a horizontal pipe, else
    horizontal across the pipe."""
    if abs(direction[2]) < 0.7:
        return (0.0, 0.0, 1.0)
    return _unit(_cross(direction, (0.0, 1.0, 0.0))) if abs(direction[1]) < 0.9 else (1.0, 0, 0)


def valve_parts(item: dict[str, Any], od: float) -> list[dict[str, Any]]:
    """The detail of an in-line valve (see the module text), in the site frame."""
    pid = item["id"]
    p = tuple(item["point"])
    d = _unit(tuple(item["direction"]))
    cls = item.get("dexpi_class") or ""
    kind = item.get("kind")
    up = stem_of(d)
    flange_r, thick = _flange(od)
    butterfly = "Butterfly" in cls
    length = 0.3 * od + 0.06 if butterfly else max(0.15, 1.6 * od + 0.08)
    a, b = _add(p, d, -length / 2), _add(p, d, length / 2)
    parts = [
        _cyl(f"{pid}/flange-1", a, _add(a, d, thick), flange_r, "flange"),
        _cyl(f"{pid}/flange-2", _add(b, d, -thick), b, flange_r, "flange"),
    ]
    r = od / 2
    if butterfly:
        parts.append(
            _cyl(f"{pid}/body", _add(a, d, thick), _add(b, d, -thick), 1.15 * flange_r, "valve")
        )
    elif "Ball" in cls or "Globe" in cls or kind == "safety_valve":
        parts.append(
            {
                "id": f"{pid}/body",
                "kind": "sphere",
                "material": "valve",
                "centre": p,
                "radius": 1.25 * r + 0.02,
                "lod": 2,
            }
        )
        parts.append(_cyl(f"{pid}/body-ends", a, b, 0.9 * r + 0.01, "valve"))
    else:
        parts.append(_cyl(f"{pid}/body", a, b, 1.2 * r + 0.015, "valve"))
    if kind == "check_valve":
        parts.append(_cyl(f"{pid}/cover", p, _add(p, up, 1.35 * r + 0.04), 0.7 * r + 0.02, "valve"))
        return parts
    if kind == "safety_valve":
        top = _add(p, up, 3.0 * r + 0.25)
        parts.append(_cyl(f"{pid}/bonnet", _add(p, up, r), top, 0.55 * r + 0.03, "valve"))
        parts.append(_cyl(f"{pid}/cap", top, _add(top, up, 0.08), 0.35 * r + 0.02, "valve"))
        side = _unit(_cross(d, up))
        out = _add(p, side, 2.0 * r + 0.15)
        outlet_od = 1.5 * od
        o_r, o_t = _flange(outlet_od)
        parts.append(_cyl(f"{pid}/outlet", p, _add(out, side, -o_t), outlet_od / 2, "valve"))
        parts.append(_cyl(f"{pid}/outlet-flange", _add(out, side, -o_t), out, o_r, "flange"))
        return parts
    across = _unit(_cross(d, up))
    if "Control" in cls:
        yoke = _add(p, up, r + 0.25 + od)
        parts.append(_cyl(f"{pid}/yoke", _add(p, up, r), yoke, 0.03 + 0.1 * r, "steel"))
        disc = 0.12 + 1.2 * od
        parts.append(
            {
                "id": f"{pid}/actuator-lower",
                "kind": "cap",
                "material": "actuator",
                "centre": _add(yoke, up, 0.06),
                "axis": tuple(-c for c in up),
                "radius": disc,
                "depth": 0.06,
                "lod": 2,
            }
        )
        parts.append(
            {
                "id": f"{pid}/actuator-upper",
                "kind": "cap",
                "material": "actuator",
                "centre": _add(yoke, up, 0.06),
                "axis": up,
                "radius": disc,
                "depth": 0.1 + 0.2 * disc,
                "lod": 2,
            }
        )
        return parts
    if "Motor" in cls or "Operated" in cls:
        box = _add(p, up, r + 0.35)
        parts.append(_cyl(f"{pid}/stem", _add(p, up, r), box, 0.03, "steel"))
        parts.append(
            {
                "id": f"{pid}/actuator",
                "kind": "box",
                "material": "actuator",
                "centre": _add(box, up, 0.15),
                "size": (0.35, 0.3, 0.3),
                "rotation_deg": math.degrees(math.atan2(d[1], d[0])) % 360,
                "lod": 2,
            }
        )
        parts.append(
            _cyl(f"{pid}/motor", _add(box, across, 0.15), _add(box, across, 0.45), 0.1, "motor")
        )
        return parts
    quarter = any(k in cls for k in ("Ball", "Butterfly", "Plug"))
    dn = item.get("dn")
    large = od > 0.17 if dn is None else dn > 150
    if quarter and not large:
        top = _add(p, up, r + 0.08)
        parts.append(_cyl(f"{pid}/stem", _add(p, up, r), top, 0.015, "steel"))
        lever = 2.5 * od + 0.15
        parts.append(_cyl(f"{pid}/lever", top, _add(top, d, lever), 0.015, "handwheel"))
        return parts
    height = r + (0.25 if quarter else 0.2 + 2.2 * od)
    top = _add(p, up, height)
    parts.append(_cyl(f"{pid}/stem", _add(p, up, r), top, 0.02 + 0.05 * r, "steel"))
    wheel = 0.1 + 0.6 * od
    if quarter:  # a gearbox with its handwheel on the side
        parts.append(
            {
                "id": f"{pid}/gearbox",
                "kind": "box",
                "material": "actuator",
                "centre": _add(top, up, 0.08),
                "size": (0.25, 0.2, 0.16),
                "rotation_deg": math.degrees(math.atan2(d[1], d[0])) % 360,
                "lod": 2,
            }
        )
        hub = _add(_add(top, up, 0.08), across, 0.25)
        parts.append(
            {
                "id": f"{pid}/handwheel",
                "kind": "torus",
                "material": "handwheel",
                "centre": hub,
                "axis": across,
                "radius": wheel,
                "tube": 0.015,
                "lod": 2,
            }
        )
        return parts
    parts.append(
        {
            "id": f"{pid}/handwheel",
            "kind": "torus",
            "material": "handwheel",
            "centre": top,
            "axis": up,
            "radius": wheel,
            "tube": 0.015,
            "lod": 2,
        }
    )
    parts.append(
        _cyl(f"{pid}/spoke-1", _add(top, d, -wheel), _add(top, d, wheel), 0.01, "handwheel")
    )
    parts.append(
        _cyl(
            f"{pid}/spoke-2", _add(top, across, -wheel), _add(top, across, wheel), 0.01, "handwheel"
        )
    )
    return parts


def inline_parts(document: dict[str, Any]) -> None:
    """Add ``parts`` to the in-line items of *document* (valves and instruments)."""
    from chemeascode.domains.spatial.shape_details import transmitter

    pipes = {p["id"]: p for p in document.get("pipes", [])}
    for item in document.get("inline", []):
        pipe = pipes.get(item.get("pipe"))
        od = pipe["od"] if pipe else 0.1
        kind = item.get("kind")
        if kind in ("valve", "check_valve", "safety_valve"):
            item["parts"] = valve_parts({**item, "dn": pipe.get("dn") if pipe else None}, od)
        elif kind == "instrument":
            floor = 0.0
            found = transmitter(
                item["id"], tuple(item["point"]), stem_of(tuple(item["direction"])), floor
            )
            item["parts"] = [_dict(part) for part in found]


def _dict(part: Any) -> dict[str, Any]:
    names = (
        "start",
        "end",
        "radius",
        "radius_end",
        "centre",
        "axis",
        "depth",
        "size",
        "rotation_deg",
        "tube",
        "lod",
    )
    entry = {"id": part.id, "kind": part.kind, "material": part.material}
    entry.update({n: getattr(part, n) for n in names if getattr(part, n) is not None})
    return entry


# ---------------------------------------------------------------------------
# Supports
# ---------------------------------------------------------------------------


def _beams(document: dict[str, Any]) -> list[tuple[str, Vec, Vec, float, float, bool]]:
    """Horizontal steel members: (id, start, end, top of steel, flange width, on a rack); a
    proposed (not pinned) support's crossbar is none."""
    return [beam[:6] for beam in _owned_beams(document)]  # type: ignore[misc]


def _owned_beams(
    document: dict[str, Any],
) -> list[tuple[str, Vec, Vec, float, float, bool, dict[str, Any] | None]]:
    """:func:`_beams` with the declared support steel each member belongs to (None for a
    rack's or a structure's)."""
    found = []
    owners: list[tuple[list[dict[str, Any]], bool, dict[str, Any] | None]] = [
        (s.get("parts", []), False, None) for s in document.get("structures", [])
    ]
    owners += [(r.get("parts", []), True, None) for r in document.get("racks", [])]
    owners += [
        (s.get("parts", []), False, s)
        for s in document.get("support_steel", [])
        if s.get("source") != "generated"
    ]
    for parts, rack, support in owners:
        for part in parts:
            if part.get("kind") != "member" or part.get("lod") == 2:
                continue
            a, b = tuple(part["start"]), tuple(part["end"])
            if abs(a[2] - b[2]) > 1e-6 or math.dist(a[:2], b[:2]) < 1e-6:
                continue
            if part.get("material") != "steel":
                continue  # handrails
            bw, h = part.get("profile") or (0.3, 0.3)
            found.append((part["id"], a, b, a[2] + h / 2, bw, rack, support))
    return found


def _cross2(a: Vec, b: Vec, c: Vec, d: Vec) -> tuple[float, float] | None:
    """Where plan segments *ab* and *cd* cross: the parameters along each, None if not."""
    rx, ry = b[0] - a[0], b[1] - a[1]
    sx, sy = d[0] - c[0], d[1] - c[1]
    den = rx * sy - ry * sx
    if abs(den) < 1e-12:
        return None
    qx, qy = c[0] - a[0], c[1] - a[1]
    t = (qx * sy - qy * sx) / den
    u = (qx * ry - qy * rx) / den
    if -1e-9 <= t <= 1 + 1e-9 and -1e-9 <= u <= 1 + 1e-9:
        return t, u
    return None


def supports(document: dict[str, Any]) -> list[dict[str, Any]]:
    """Shoes and guides of the pipes on the steel (see the module text)."""
    beams = _beams(document)
    found: list[dict[str, Any]] = []
    for pipe in document.get("pipes", []):
        r = pipe["od"] / 2
        ins = pipe.get("insulation_mm", 0.0) / 1000
        points = [tuple(p) for p in pipe["points"]]
        count = 0
        for a, b in zip(points, points[1:], strict=False):
            if abs(a[2] - b[2]) > 1e-6 or math.dist(a[:2], b[:2]) < 1e-6:
                continue
            bottom = a[2] - r
            along = _unit((b[0] - a[0], b[1] - a[1], 0.0))
            hits = []
            for beam_id, c, d, tos, flange, rack in beams:
                outer = bottom - ins - tos
                if not (
                    -0.01 <= outer <= SUPPORT_GAP or -0.01 <= bottom - tos <= SUPPORT_GAP + ins
                ):
                    continue
                cut = _cross2(a, b, c, d)
                if cut is None:
                    continue
                hits.append((cut[0], beam_id, tos, flange, rack))
            for t, beam_id, tos, _flange, rack in sorted(hits):
                count += 1
                x, y = a[0] + (b[0] - a[0]) * t, a[1] + (b[1] - a[1]) * t
                kind = "guide" if rack and count % GUIDE_EVERY == 0 else "shoe"
                sid = f"{pipe['id']}/support-{count}"
                top = max(bottom, tos + 0.02)
                height = max(top - tos, SHOE_HEIGHT)
                rotation = math.degrees(math.atan2(along[1], along[0])) % 360
                parts = [
                    {
                        "id": f"{sid}/shoe",
                        "kind": "box",
                        "material": "steel",
                        "centre": (x, y, tos + height / 2),
                        "size": (0.3, min(2 * r, 0.2) + 0.04, height),
                        "rotation_deg": rotation,
                        "lod": 2,
                    }
                ]
                if kind == "guide":
                    for n, side in enumerate((-1, 1), 1):
                        off = r + ins + 0.04
                        parts.append(
                            {
                                "id": f"{sid}/stop-{n}",
                                "kind": "box",
                                "material": "steel",
                                "centre": (
                                    x - along[1] * side * off,
                                    y + along[0] * side * off,
                                    tos + 0.05,
                                ),
                                "size": (0.1, 0.02, 0.1),
                                "rotation_deg": rotation,
                                "lod": 2,
                            }
                        )
                found.append(
                    {
                        "id": sid,
                        "refs": {"lines": [pipe["line"]], "segments": [pipe["segment"]]},
                        "source": "generated",
                        "kind": kind,
                        "pipe": pipe["id"],
                        "on": beam_id,
                        "point": (x, y, tos),
                        "parts": parts,
                    }
                )
    return found


# ---------------------------------------------------------------------------
# Spans and support steel
# ---------------------------------------------------------------------------

#: Within this in plan (and 2 m in height) of a level run a support counts for it, m.
SUPPORT_NEAR = 0.3


def level_stretches(points: list[Vec]) -> tuple[list[tuple[float, float, bool]], list[tuple]]:
    """The arcs ``(s0, s1, level)`` of each piece of a polyline, and its level stretches
    ``(k, j)``: runs of consecutive level pieces (indices of the first and last piece)."""
    arcs, s = [], 0.0
    for a, b in zip(points, points[1:], strict=False):
        length = math.dist(a, b)
        arcs.append((s, s + length, abs(a[2] - b[2]) < 1e-6 and length > 1e-6))
        s += length
    stretches: list[tuple[int, int]] = []
    k = 0
    while k < len(arcs):
        if not arcs[k][2]:
            k += 1
            continue
        j = k
        while j + 1 < len(arcs) and arcs[j + 1][2]:
            j += 1
        stretches.append((k, j))
        k = j + 1
    return arcs, stretches


def support_arcs(
    points: list[Vec], arcs: list[tuple[float, float, bool]], k: int, j: int, on: list[Vec]
) -> list[float]:
    """Arcs along the level stretch *k*..*j* of *points* of the support points *on* under it."""
    found = []
    for p in on:
        for m in range(k, j + 1):
            a, b = points[m], points[m + 1]
            d, t = _point_segment((p[0], p[1], a[2]), a, b)
            if d <= SUPPORT_NEAR and abs(p[2] - a[2]) < 2.0:
                found.append(arcs[m][0] + t * (arcs[m][1] - arcs[m][0]))
                break
    return found


def _point_segment(p: Vec, a: Vec, b: Vec) -> tuple[float, float]:
    from chemeascode.domains.spatial.geometry3d import point_segment

    return point_segment(p, a, b)


def steel_below(document: dict[str, Any], at: tuple[float, float], top: float) -> float | None:
    """The top of the highest horizontal steel member (a beam of a rack or structure, declared
    support steel) under the plan point *at* below *top* (at least 0.3 m below), or None."""
    found = members_below(document, at, top)
    return found[0][0] if found else None


def members_below(
    document: dict[str, Any], at: tuple[float, float], top: float
) -> list[tuple[float, str, dict[str, Any] | None]]:
    """The horizontal steel members under the plan point *at* below *top* (at least 0.3 m
    below), highest first: ``(top of steel, member id, the declared support steel it belongs
    to or None)``."""
    found = []
    for mid, a, b, tos, flange, _, support in _owned_beams(document):
        if tos > top - 0.3:
            continue
        d, _ = _point_segment((at[0], at[1], a[2]), a, b)
        if d <= flange / 2 + 0.05:
            found.append((tos, mid, support))
    found.sort(key=lambda m: (-m[0], m[1]))
    return found


def lines_served(document: dict[str, Any], support: dict[str, Any]) -> set[str]:
    """The line numbers of the pipes support steel *support* carries (its ``serves``: pipe ids,
    or line numbers)."""
    by_id = {p["id"]: p.get("line") for p in document.get("pipes", [])}
    return {str(by_id.get(s) or s) for s in support.get("serves") or []}


def _stub_base(
    document: dict[str, Any],
    at: tuple[float, float],
    top: float,
    pipe: dict[str, Any],
    stub_max: float,
) -> float | None:
    """Where a proposed post under *pipe* may stand on steel: the top of the highest member
    below it when that is at most *stub_max* below *top* and is no support steel of another
    line (a T-post sized for its own line); else None (a T-post from grade)."""
    found = members_below(document, at, top)
    if not found:
        return None
    tos, _, support = found[0]
    if top - tos > stub_max + 1e-6:
        return None
    if support is not None and str(pipe.get("line") or pipe["id"]) not in lines_served(
        document, support
    ):
        return None
    return tos


def _on_rack_tier(pipe: dict[str, Any], z_bottom: float, racks: dict[str, Any]) -> bool:
    return any(
        abs(z_bottom - level) < 0.05
        for rack in (racks.get(r) for r in pipe.get("racks") or [])
        if rack is not None
        for level in rack.get("levels", [])
    )


#: Offsets along its pipe a proposed post tries, in turn, to keep clear of other pipes, m.
POST_SHIFTS = (0.0, 0.25, -0.25, 0.5, -0.5, 0.75, -0.75, 1.0, -1.0, 1.5, -1.5)
#: Half the width of a proposed post's column (HEB200), m.
POST_HALF = 0.1


def post_id(pipe_id: str, arc: float) -> str:
    """The id of a support post proposed under pipe *pipe_id* at *arc* m along it (its nominal
    place, before any shift clear of other pipes): ``<pipe>/SP-<arc, 0.1 m>``. Derived from
    what it serves and where, so a rebuild with the same route gives the same id and an id is
    never handed to another post."""
    return f"{pipe_id}/SP-{arc:.1f}"


def _post_clash(
    document: dict[str, Any],
    own: str,
    at: tuple[float, float],
    top: float,
    base: float,
    width: float,
    across_deg: float,
    clearance: float,
) -> tuple[str, float] | None:
    """The nearest other pipe closer than *clearance* to a proposed post's column or crossbar
    (a pipe resting on the crossbar's top is carried by it, not a clash): ``(pipe id, gap)``."""
    from chemeascode.domains.spatial.geometry3d import segment_segment

    x, y = at
    a = math.radians(across_deg)
    dx, dy = math.cos(a) * width / 2, math.sin(a) * width / 2
    column = ((x, y, base), (x, y, top - 2 * POST_HALF))
    bar_z = top - POST_HALF
    bar = ((x - dx, y - dy, bar_z), (x + dx, y + dy, bar_z))
    worst = None
    for pipe in document.get("pipes", []):
        if pipe["id"] == own:
            continue
        r = pipe.get("od", 0.0) / 2 + pipe.get("insulation_mm", 0.0) / 1000
        points = [tuple(p) for p in pipe.get("points") or []]
        for p, q in zip(points, points[1:], strict=False):
            if min(p[2], q[2]) - r > top + 1.0 or max(p[2], q[2]) + r < base - 1.0:
                continue
            gap = segment_segment(column[0], column[1], p, q) - r - POST_HALF
            level = abs(p[2] - q[2]) < 1e-6
            resting = level and -1e-3 <= (p[2] - r) - top <= SHOE_HEIGHT + 0.05
            if not resting:
                gap = min(gap, segment_segment(bar[0], bar[1], p, q) - r - POST_HALF)
            if gap < clearance - 1e-9 and (worst is None or gap < worst[1]):
                worst = (pipe["id"], gap)
    return worst


#: The words a proposal's reason ends with when no place in its span keeps clear of the other
#: pipes: it is not offered for ``cheme layout pin``.
BY_HAND = "place it by hand"
#: The tallest stub a proposal stands on steel (as the criterion ``support_stub_max_m``), m.
STUB_MAX = 1.5


def support_proposals(
    document: dict[str, Any], clearance: float = 0.1, stub_max: float = STUB_MAX
) -> list[dict[str, Any]]:
    """Support steel proposed under the level runs that span farther than their table allows
    (see the module text): ``ModelSupportSteel`` entries without parts, ids
    :func:`post_id` (``<pipe>/SP-<arc>``). A post keeps *clearance* m from the pipes it does not
    carry: it moves along its pipe (:data:`POST_SHIFTS`) to the first place clear of them, and
    says so in its reason; with none clear it stays and its reason names the pipe. It is a
    ``stub`` on the steel below only when that steel is at most *stub_max* m below its top and
    is not the support steel of another line; else a ``t_post`` from grade.
    """
    from chemeascode.domains.piping.pipe_data import is_liquid, max_span

    on: dict[str, list[Vec]] = {}
    for support in document.get("supports", []):
        on.setdefault(support["pipe"], []).append(tuple(support["point"]))
    racks = {r["id"]: r for r in document.get("racks", [])}
    # a declared (pinned) support steel keeps its id; a proposal never takes one
    taken = {s.get("id") for s in document.get("support_steel", [])}
    found: list[dict[str, Any]] = []
    for pipe in document.get("pipes", []):
        points = [tuple(p) for p in pipe["points"]]
        if len(points) < 2:
            continue
        liquid = is_liquid(pipe.get("fluid"))
        limit = max_span(pipe.get("dn"), liquid)
        r = pipe["od"] / 2 + pipe.get("insulation_mm", 0.0) / 1000
        arcs, stretches = level_stretches(points)
        for k, j in stretches:
            s0, s1 = arcs[k][0], arcs[j][1]
            z = points[k][2]
            if _on_rack_tier(pipe, z - r, racks):
                continue  # intermediate rack steel carries it
            stops = sorted({s0, s1, *support_arcs(points, arcs, k, j, on.get(pipe["id"], []))})
            for lo, hi in zip(stops, stops[1:], strict=False):
                if hi - lo <= limit + 1e-6:
                    continue
                n = math.ceil((hi - lo) / limit - 1e-9) - 1
                for i in range(1, n + 1):
                    nominal = lo + (hi - lo) * i / (n + 1)
                    top = round(z - r - SHOE_HEIGHT, 3)
                    if top < 0.3:
                        continue  # on sleepers at grade
                    sid = post_id(pipe["id"], nominal)
                    if sid in taken:
                        continue  # declared (pinned) under that id
                    taken.add(sid)
                    placed = None
                    for shift in POST_SHIFTS:
                        s = nominal + shift
                        if not lo + 0.3 <= s <= hi - 0.3 and shift:
                            continue  # stays inside its span, clear of the ends and supports
                        m = next(m for m in range(k, j + 1) if arcs[m][1] >= s - 1e-9)
                        a, b = points[m], points[m + 1]
                        t = (s - arcs[m][0]) / max(arcs[m][1] - arcs[m][0], 1e-9)
                        x, y = a[0] + (b[0] - a[0]) * t, a[1] + (b[1] - a[1]) * t
                        base = _stub_base(document, (x, y), top, pipe, stub_max)
                        across = math.degrees(math.atan2(b[1] - a[1], b[0] - a[0])) + 90.0
                        width = 1.0 if base is None else SUPPORT_CAP_WIDTH
                        clash = _post_clash(
                            document,
                            pipe["id"],
                            (x, y),
                            top,
                            base if base is not None else 0.0,
                            width,
                            across,
                            clearance,
                        )
                        candidate = (shift, x, y, base, across, clash)
                        if placed is None:
                            placed = candidate
                        if clash is None:
                            placed = candidate
                            break
                    assert placed is not None
                    shift, x, y, base, across, clash = placed
                    dn = pipe.get("dn")
                    size = f"DN {dn:g}" if dn else "DN ?"
                    note = ""
                    if clash is not None:
                        note = (
                            f"; it passes {max(clash[1], 0.0):.2f} m from pipe {clash[0]} "
                            f"(< {clearance:g} m) wherever it stands in this span: {BY_HAND}"
                        )
                    elif shift:
                        note = (
                            f"; moved {shift:+.2f} m along the pipe to keep {clearance:g} m "
                            "from the pipes it does not carry"
                        )
                    found.append(
                        {
                            "id": sid,
                            "refs": {"lines": [pipe["line"]], "segments": [pipe["segment"]]},
                            "source": "generated",
                            "kind": "stub" if base is not None else "t_post",
                            "at": (round(x, 3), round(y, 3)),
                            "top": top,
                            "base": base if base is not None else 0.0,
                            "width": 1.0,
                            "rotation_deg": round(across % 180, 3),
                            "serves": [pipe["id"]],
                            "review_needed": True,
                            "reason": f"pipe {pipe['id']} ({pipe['line']}, {size}) spans "
                            f"{hi - lo:.1f} m there (> {limit:g} m, ASSUMED table){note}",
                        }
                    )
    return found


_COLD = re.compile(r"cold|cryo|vacuum|chill|frost|anti[- ]?sweat|pur|pir|foam|glass", re.I)
_PERSONNEL = re.compile(r"personnel|burn|pp\b", re.I)


def jacket(insulation_mm: float, text: str | None) -> str | None:
    """The jacketing of an insulated pipe from the line list's insulation text: ``cold``,
    ``personnel`` or ``hot`` (the default); None without insulation."""
    if insulation_mm <= 0:
        return None
    text = text or ""
    if _COLD.search(text):
        return "cold"
    if _PERSONNEL.search(text):
        return "personnel"
    return "hot"


def operator_targets(model: dict[str, Any], name: str) -> list[dict[str, Any]]:
    """The in-line items (by tag or id) and nozzles (``TAG/NOZZLE``) a declared operator names."""
    found = [item for item in model.get("inline", []) if name in (item.get("tag"), item.get("id"))]
    if found:
        return found
    if "/" in name:
        tag, nozzle = name.split("/", 1)
        for item in model.get("equipment", []):
            if item.get("tag") != tag:
                continue
            for entry in item.get("nozzles", []):
                if nozzle in (entry.get("name"), (entry.get("refs") or {}).get("dexpi")):
                    found.append(entry)
    return found


def apply_operators(model: dict[str, Any], routing: Any) -> None:
    """Copy the operators of *routing* (``piping/routing.yaml``) onto the model's in-line items
    and nozzles they name, as ``operator``."""
    for op in getattr(routing, "operators", None) or ():
        entry = op.model_dump(mode="json", exclude_none=True, exclude={"item", "notes"})
        if not entry.get("basis"):
            entry.pop("basis", None)
        for target in operator_targets(model, op.item):
            target["operator"] = entry
