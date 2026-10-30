"""Rules on the generated 3D model (``layout/plant-model.yaml``).

They run on the model document alone (plus the site plan's separations and the routing intent
where given), so ``cheme layout build``, ``layout report``, ``validate`` and the API share
them. Every finding names the model file, the ids of the objects involved and their 3D ``box``
(``[x0, y0, z0, x1, y1, z1]``, site metres) for the viewer to highlight.

A pipe is a capsule (its axis, radius OD / 2 + insulation); a steel member a capsule of half its
larger section size; equipment parts and envelopes the solids of
:mod:`chemeascode.domains.spatial.geometry3d`.

Rules (``cheme.layout-...``, level):

- ``clash-pipe`` (warning): two pipes closer than their radii plus ``spacing_m``; pipes that
  meet (a tee, a shared end) are not compared within a metre of where they meet;
- ``clash-pipe-equipment`` (warning): a pipe through an equipment part, except the first and
  last run at the item it connects to and the runs that leave that item's outline from a
  nozzle under or inside it (a bottom nozzle in a skirt leaves through the skirt's opening);
- ``clash-pipe-steel`` (warning): a pipe through a steel member (resting on a beam touches);
- ``clash-equipment-steel`` (error): an equipment part through a steel member;
- ``headroom`` (warning): a pipe's bottom over a road below ``headroom_road_m``, or in an
  escape route below ``headroom_walkway_m``;
- ``buried-cover`` (warning): a buried run (below) with less soil cover over its top than its
  ``buried.cover_m``, or under a road less than ``max(cover_m, road_cover_m)`` (1.2 m,
  ASSUMED); its vertical runs (the risers through grade) are left out. Key ``<pipe>+<road>``
  under a road, else ``<pipe>``;
- ``access-blocked`` (warning): a pipe, member or other item in a bundle-pull, motor-removal
  or access envelope (an item's own pipes may cross its access space);
- ``zone-crossing`` (warning): a pipe through a keep-clear, laydown or maintenance zone;
- ``rack-fill`` (warning): pipes on a rack tier (OD + insulation + spacing) wider than it, at
  its most crowded cross-section (the router's ``routing.rack_fill``; a model without it adds
  up every pipe on the tier);
- ``nozzle-unconnected`` (info): a nozzle on a segment without a route;
- ``pipe-disconnected`` (error): a pipe end (a pinned or ``via`` route's above all) more than
  :data:`CONNECT_TOL` from what its ``ends`` say it connects to: its nozzle's face, another
  pipe of its tee, connector pair or shared component, the placed item, the line it ends on;
- ``gravity-fall`` (info): a gravity line (``gravity: true`` or a ``gravity_fluids`` fluid)
  with a level run;
- ``separation`` (warning): a separation of the site plan naming a zone, measured in plan to
  the zone's volumes.

A pipe declared ``buried`` in ``piping/routing.yaml`` (the model's ``buried``) is in the ground
where its top lies at or below grade (:data:`GRADE`): those runs (:func:`buried_run`) are not
under the road or escape-route headroom, and meet no steel, equipment part, envelope or zone
volume that lies wholly above grade (a foundation or pit below grade still clashes); its runs
above grade are pipes like any other.

The cable tray rules (``tray-fill``, ``tray-separation``, ``clash-tray``, ``cable-missing``,
``cable-unrouted``) are in :func:`chemeascode.domains.spatial.trays.tray_findings`, the HVAC rules
(``hvac-capacity``, ``duct-unrouted``, ``clash-duct``) in
:func:`chemeascode.domains.spatial.hvac.hvac_findings`.

The engineering rules (wall penetrations, rack tiers, vent outlets, pipe spans, operability,
escape, lifting, equipment spacing) are in :mod:`chemeascode.domains.spatial.engineering_rules`.
"""

from __future__ import annotations

import math
from typing import Any

from chemeascode.domains.spatial.geometry3d import (
    TOUCH,
    Box,
    Capsule,
    Index,
    dist,
    part_solid,
    point_segment,
    segment_box,
    segment_distance,
    segment_segment,
)
from chemeascode.domains.spatial.schemas import FORBIDDEN_ZONES, RoutingRules
from chemeascode.foundation.findings import Finding
from chemeascode.foundation.workspace import LAYOUT_MODEL_FILE

Vec = tuple[float, float, float]
#: How far a pipe end may lie from what it connects to (the model's millimetres), m.
CONNECT_TOL = 0.01
#: At most this many findings of one rule are reported one by one; the rest are counted.
LIMIT = 200
#: Grade, m: a buried pipe's runs whose top is at or below it are in the ground.
GRADE = 0.0


def buried_run(pipe: dict[str, Any], a: Any, b: Any, r: float) -> bool:
    """Whether the run *a*-*b* of *pipe* (radius *r*, insulation included) is in the ground:
    the pipe is declared ``buried`` and the run's top is at or below :data:`GRADE`."""
    return pipe.get("buried") is not None and max(a[2], b[2]) + r <= GRADE + TOUCH


def _above_grade(solid: Any) -> bool:
    """Whether a solid (or a box ``[x0, y0, z0, x1, y1, z1]``) stands wholly above grade: its
    bottom at or above it; a steel member's (a capsule's) by its axis, so that a column
    standing on grade is above it."""
    if isinstance(solid, Capsule):
        return min(solid.a[2], solid.b[2]) >= GRADE - TOUCH
    box = solid.aabb if hasattr(solid, "aabb") else solid
    return box[2] >= GRADE - TOUCH


def _junction_label(key: str) -> str:
    """A junction key of the router in words: ``pid/P-04.xml:Tee_1`` the tee ``Tee_1`` on
    P-04, ``opc:LINE:k`` the off-page connector pair of LINE."""
    if key.startswith("opc:"):
        return f"the off-page connector pair of {key.split(':')[1]}"
    sheet, _, ref = key.rpartition(":")
    stem = sheet.rsplit("/", 1)[-1].removesuffix(".xml")
    return f"{ref} on {stem}" if stem else ref


def _box(*boxes: tuple[float, ...]) -> list[float]:
    return [
        round(min(b[0] for b in boxes), 3),
        round(min(b[1] for b in boxes), 3),
        round(min(b[2] for b in boxes), 3),
        round(max(b[3] for b in boxes), 3),
        round(max(b[4] for b in boxes), 3),
        round(max(b[5] for b in boxes), 3),
    ]


class _Rules:
    def __init__(self, model: dict[str, Any], rules: RoutingRules, routing: Any, plan: Any):
        self.model = model
        self.rules = rules
        self.routing = routing
        self.plan = plan
        self.findings: list[Finding] = []
        self._junctions: dict[tuple[str, str], list[Vec]] = {}
        self.counts: dict[str, int] = {}
        self.pipes = model.get("pipes", [])
        self.capsules: list[tuple[Capsule, dict[str, Any], int]] = []
        for pipe in self.pipes:
            r = pipe["od"] / 2 + pipe.get("insulation_mm", 0.0) / 1000
            points = [tuple(p) for p in pipe["points"]]
            for k, (a, b) in enumerate(zip(points, points[1:], strict=False)):
                if dist(a, b) > 1e-9:
                    self.capsules.append((Capsule(pipe["id"], a, b, r), pipe, k))
        self.pipe_index = Index(4.0)
        for capsule, pipe, k in self.capsules:
            self.pipe_index.add(capsule, (pipe, k))
        #: ``(pipe id, run index)`` of the buried runs (:func:`buried_run`).
        self.buried = {
            (pipe["id"], k)
            for capsule, pipe, k in self.capsules
            if buried_run(pipe, capsule.a, capsule.b, capsule.r)
        }
        self.steel = Index(4.0)
        for structure in model.get("structures", []):
            for part in structure["parts"]:
                solid = part_solid(part, structure["id"]) if part["kind"] == "member" else None
                if solid is not None:  # not the detail (mid rails, toe plates, posts)
                    self.steel.add(solid, part["id"])
        for rack in model.get("racks", []):
            for part in rack.get("parts", []):
                solid = part_solid(part, rack["id"])
                if solid is not None:
                    self.steel.add(solid, part["id"])
        for steel in model.get("support_steel", []):
            if steel.get("source") == "generated":
                continue  # a proposal: drawn under its pipe, checked once pinned
            for part in steel.get("parts", []):
                solid = part_solid(part, steel["id"]) if part["kind"] == "member" else None
                if solid is not None:
                    self.steel.add(solid, part["id"])
        for area in model.get("areas", []):
            for part in area.get("parts", []):  # a bund's walls
                solid = part_solid(part, area["id"])
                if solid is not None:
                    self.steel.add(solid, part["id"])
        self.parts = Index(4.0)
        self.bboxes = {item["tag"]: item["bbox"] for item in model.get("equipment", [])}
        for item in model.get("equipment", []):
            for part in item["parts"]:
                solid = part_solid(part, item["tag"])
                if solid is not None:
                    self.parts.add(solid, part["id"])
        # where each pipe ends at an item: pipe id -> {0: tag, 1: tag}
        self.ends: dict[str, dict[int, str]] = {}
        nozzle_points = []
        for item in model.get("equipment", []):
            for nozzle in item["nozzles"]:
                nozzle_points.append((tuple(nozzle["point"]), item["tag"], item["bbox"]))
        for pipe in self.pipes:
            for side, point in ((0, pipe["points"][0]), (1, pipe["points"][-1])):
                for p, tag, _ in nozzle_points:
                    if dist(tuple(point), p) < 1e-3:
                        self.ends.setdefault(pipe["id"], {})[side] = tag
                        break
                else:
                    for item in model.get("equipment", []):
                        x0, y0, z0, x1, y1, z1 = item["bbox"]
                        x, y, z = point
                        if (
                            x0 - 1e-3 <= x <= x1 + 1e-3
                            and y0 - 1e-3 <= y <= y1 + 1e-3
                            and z0 - 1e-3 <= z <= z1 + 1e-3
                        ):
                            self.ends.setdefault(pipe["id"], {})[side] = item["tag"]
                            break

    def add(
        self,
        level: str,
        rule: str,
        message: str,
        ids: list[str],
        box: list[float] | None,
        hint: str,
        key: str = "",
        measured: float | None = None,
    ) -> None:
        self.counts[rule] = self.counts.get(rule, 0) + 1
        if self.counts[rule] > LIMIT:
            return
        self.findings.append(
            Finding(
                LAYOUT_MODEL_FILE,
                level,  # type: ignore[arg-type]
                f"cheme.layout-{rule}",
                message,
                ids=ids,
                hint=hint,
                key=key,
                box=box,
                measured=None if measured is None else round(measured, 3),
            )
        )

    # -- clashes ------------------------------------------------------------------------

    def pipe_pipe(self) -> None:
        spacing = self.rules.spacing_m
        seen: set[tuple[str, str]] = set()
        for capsule, pipe, _ in self.capsules:
            for other, _, (opipe, _) in self.pipe_index.near(
                capsule.aabb, capsule.r + spacing + 1.5
            ):
                assert isinstance(other, Capsule)
                if opipe["id"] <= pipe["id"]:
                    continue
                pair = (pipe["id"], opipe["id"])
                if pair in seen:
                    continue
                if _touching(capsule, other) or self._at_junction(pipe, opipe, capsule, other):
                    continue
                gap = segment_segment(capsule.a, capsule.b, other.a, other.b)
                if gap < capsule.r + other.r + spacing - 0.01:
                    seen.add(pair)
                    self.add(
                        "warning",
                        "clash-pipe",
                        f"pipes {pipe['id']} ({pipe['line']}) and {opipe['id']} "
                        f"({opipe['line']}) are {max(0.0, gap - capsule.r - other.r):.2f} m "
                        f"apart (< {spacing:g} m spacing)",
                        [pipe["id"], opipe["id"]],
                        _box(capsule.aabb, other.aabb),
                        "move one with via points or a pin in piping/routing.yaml, or reroute",
                        key=f"{pipe['id']}+{opipe['id']}",
                    )

    def _at_junction(self, a: dict, b: dict, ca: Capsule, cb: Capsule) -> bool:
        """Whether runs *ca* and *cb* of pipes *a* and *b* come close only at the fitting where
        the two pipes meet (an end of one on the other: a tee, or a shared end)."""
        key = (a["id"], b["id"])
        points = self._junctions.get(key)
        if points is None:
            points = []
            for p, q in ((a, b), (b, a)):
                line = [tuple(x) for x in q["points"]]
                for end in (tuple(p["points"][0]), tuple(p["points"][-1])):
                    if any(
                        point_segment(end, s, e)[0] < 1e-3
                        for s, e in zip(line, line[1:], strict=False)
                    ):
                        points.append(end)
            self._junctions[key] = points
        reach = ca.r + cb.r + self.rules.spacing_m + 1.0
        return any(
            point_segment(j, ca.a, ca.b)[0] < reach and point_segment(j, cb.a, cb.b)[0] < reach
            for j in points
        )

    def pipe_equipment(self) -> None:
        seen: set[tuple[str, str]] = set()
        for capsule, pipe, k in self.capsules:
            last = len(pipe["points"]) - 2
            ends = self.ends.get(pipe["id"], {})
            skip = set()
            if k == 0 and 0 in ends:
                skip.add(ends[0])
            if k == last and 1 in ends:
                skip.add(ends[1])
            # the legs that leave the item's outline from a nozzle under or inside it (a bottom
            # nozzle in a skirt: the pipe passes the skirt's opening)
            points = pipe["points"]
            if 0 in ends and self._inside(ends[0], points[k]):
                skip.add(ends[0])
            if 1 in ends and self._inside(ends[1], points[k + 1]):
                skip.add(ends[1])
            # the legs onto and along the outline of the item the pipe ends at are its
            # connection (the approach to a placed relief valve or silencer along its face)
            if 1 in ends:
                j = len(points)
                while j > 0 and self._on_outline(ends[1], points[j - 1]):
                    j -= 1
                if j < len(points) and k >= j - 1:
                    skip.add(ends[1])
            if 0 in ends:
                j = -1
                while j + 1 < len(points) and self._on_outline(ends[0], points[j + 1]):
                    j += 1
                if j >= 0 and k <= j:
                    skip.add(ends[0])
            buried = (pipe["id"], k) in self.buried
            for solid, box, part_id in self.parts.near(capsule.aabb, 0.0):
                if solid.id in skip or (pipe["id"], solid.id) in seen:
                    continue
                if buried and _above_grade(solid):
                    continue
                if segment_distance(capsule.a, capsule.b, solid) < capsule.r - TOUCH:
                    seen.add((pipe["id"], solid.id))
                    self.add(
                        "warning",
                        "clash-pipe-equipment",
                        f"pipe {pipe['id']} ({pipe['line']}) runs through {solid.id} ({part_id})",
                        [pipe["id"], solid.id],
                        _box(capsule.aabb, box),
                        "add a via point around the item in piping/routing.yaml, or move it",
                        key=f"{pipe['id']}+{solid.id}",
                    )

    def _on_outline(self, tag: str, p: Any) -> bool:
        """Whether *p* lies within the closed box of item *tag* (its faces included)."""
        box = self.bboxes.get(tag)
        if box is None:
            return False
        return all(box[i] - 1e-3 <= p[i] <= box[i + 3] + 1e-3 for i in range(3))

    def _inside(self, tag: str, p: Any) -> bool:
        """Whether *p* lies strictly inside the plan outline of item *tag*, below its top."""
        box = self.bboxes.get(tag)
        if box is None:
            return False
        x0, y0, z0, x1, y1, z1 = box
        return x0 + 1e-6 < p[0] < x1 - 1e-6 and y0 + 1e-6 < p[1] < y1 - 1e-6 and p[2] < z1

    def pipe_steel(self) -> None:
        seen: set[tuple[str, str]] = set()
        for capsule, pipe, k in self.capsules:
            buried = (pipe["id"], k) in self.buried
            for solid, box, member in self.steel.near(capsule.aabb, 0.0):
                if (pipe["id"], member) in seen or (buried and _above_grade(solid)):
                    continue
                if segment_distance(capsule.a, capsule.b, solid) < capsule.r - TOUCH:
                    seen.add((pipe["id"], member))
                    self.add(
                        "warning",
                        "clash-pipe-steel",
                        f"pipe {pipe['id']} ({pipe['line']}) runs through steel {member}",
                        [pipe["id"], member],
                        _box(capsule.aabb, box),
                        "route it around the member (via points), or change the steel",
                        key=f"{pipe['id']}+{member}",
                    )

    def equipment_steel(self) -> None:
        seen: set[tuple[str, str]] = set()
        for member, mbox, member_id in self.steel.items:
            if not isinstance(member, Capsule):
                continue  # a bund wall: items stand inside it
            for solid, box, part_id in self.parts.near(mbox, 0.0):
                if (solid.id, member_id) in seen:
                    continue
                if segment_distance(member.a, member.b, solid) < member.r - TOUCH:
                    seen.add((solid.id, member_id))
                    self.add(
                        "error",
                        "clash-equipment-steel",
                        f"{solid.id} ({part_id}) and steel {member_id} intersect",
                        [solid.id, member_id],
                        _box(mbox, box),
                        "move the item or change the frame (spans, levels)",
                        key=f"{solid.id}+{member_id}",
                    )

    # -- headroom, access, zones ------------------------------------------------------------

    def roads(self) -> list[tuple[str, list[list[tuple[float, float]]]]]:
        """Each road's id with its polygons in plan (roads, and areas of kind ``road``)."""
        from chemeascode.domains.spatial.layout_validate import strip

        roads = []
        for road in self.model.get("roads", []):
            roads.append((road["id"], strip(road["points"], road["width"])))
        for area in self.model.get("areas", []):
            if area.get("kind") == "road":
                x0, y0, x1, y1 = area["box"]
                roads.append((area["id"], [[(x0, y0), (x1, y0), (x1, y1), (x0, y1)]]))
        return roads

    def headroom(self) -> None:
        from chemeascode.domains.spatial.layout_distances import _inside

        roads = self.roads()
        need = self.rules.headroom_road_m
        for pipe in self.pipes:
            r = pipe["od"] / 2 + pipe.get("insulation_mm", 0.0) / 1000
            worst: dict[str, float] = {}
            buried = pipe.get("buried") is not None
            for p in _samples([tuple(q) for q in pipe["points"]]):
                if buried and p[2] + r <= GRADE + TOUCH:
                    continue  # in the ground: the cover rule applies
                for road_id, polygons in roads:
                    if any(_inside((p[0], p[1]), poly) for poly in polygons):
                        bottom = p[2] - r
                        if bottom < need - TOUCH:
                            worst[road_id] = min(worst.get(road_id, math.inf), bottom)
            for road_id, bottom in sorted(worst.items()):
                self.add(
                    "warning",
                    "headroom",
                    f"pipe {pipe['id']} ({pipe['line']}) crosses road {road_id} with "
                    f"{bottom:.2f} m clear (< {need:g} m)",
                    [pipe["id"], road_id],
                    _pipe_box(pipe),
                    "raise the crossing (elevation or a rack tier in piping/routing.yaml)",
                    key=f"{pipe['id']}+{road_id}",
                )
        walk = self.rules.headroom_walkway_m
        for zone in self.model.get("zones", []):
            if zone["kind"] != "escape":
                continue
            for volume in zone["volumes"]:
                from chemeascode.domains.spatial.zones import volume_box

                x0, y0, z0, x1, y1, _ = volume_box(volume)
                band = Box(
                    zone["id"],
                    ((x0 + x1) / 2, (y0 + y1) / 2, z0 + walk / 2),
                    (x1 - x0, y1 - y0, walk),
                )
                for capsule, pipe, k in self.capsules:
                    if (pipe["id"], k) in self.buried and _above_grade(band):
                        continue
                    if segment_distance(capsule.a, capsule.b, band) < capsule.r - TOUCH:
                        self.add(
                            "warning",
                            "headroom",
                            f"pipe {pipe['id']} ({pipe['line']}) is lower than {walk:g} m over "
                            f"escape route {zone['id']}",
                            [pipe["id"], zone["id"]],
                            _pipe_box(pipe),
                            "raise it over the escape route",
                            key=f"{pipe['id']}+{zone['id']}",
                        )
                        break

    def buried_cover(self) -> None:
        from chemeascode.domains.spatial.layout_distances import _inside

        roads = self.roads()
        road_min = self.rules.road_cover_m
        for pipe in self.pipes:
            if pipe.get("buried") is None:
                continue
            declared = pipe["buried"].get("cover_m")
            r = pipe["od"] / 2 + pipe.get("insulation_mm", 0.0) / 1000
            points = [tuple(q) for q in pipe["points"]]
            # where (a road, or None off the roads) -> (shortfall, cover, need, point)
            worst: dict[str | None, tuple[float, float, float, Vec]] = {}
            for a, b in zip(points, points[1:], strict=False):
                if math.hypot(b[0] - a[0], b[1] - a[1]) < 1e-6:
                    continue  # a riser: it passes through the cover
                for p in _samples([a, b]):
                    cover = GRADE - (p[2] + r)
                    if cover < -TOUCH:
                        continue  # above grade here: not buried
                    on = [
                        road_id
                        for road_id, polygons in roads
                        if any(_inside((p[0], p[1]), poly) for poly in polygons)
                    ]
                    needs: list[tuple[str | None, float]] = [
                        (road_id, max(declared or 0.0, road_min)) for road_id in on
                    ]
                    if not on and declared is not None:
                        needs.append((None, declared))
                    for where, need in needs:
                        short = need - cover
                        if short > TOUCH and (where not in worst or short > worst[where][0]):
                            worst[where] = (short, cover, need, p)
            for where, (_, cover, need, p) in sorted(worst.items(), key=lambda item: item[0] or ""):
                if where is None:
                    what, basis = "", "its declared cover_m"
                elif declared is not None and declared >= road_min:
                    what, basis = f" under road {where}", "its declared cover_m"
                else:
                    what, basis = f" under road {where}", "rules.road_cover_m, ASSUMED"
                self.add(
                    "warning",
                    "buried-cover",
                    f"buried pipe {pipe['id']} ({pipe['line']}) has {max(cover, 0.0):.2f} m of "
                    f"cover{what} at [{p[0]:.1f}, {p[1]:.1f}], less than {need:g} m ({basis})",
                    [pipe["id"], *([where] if where else [])],
                    _box((p[0] - r, p[1] - r, p[2] - r, p[0] + r, p[1] + r, GRADE)),
                    "lay the run deeper (its elevation or pinned route in piping/routing.yaml), "
                    "or protect the crossing (a sleeve or slab) and accept the finding with the "
                    "reason; the site's least cover goes in rules.road_cover_m or buried.cover_m",
                    key=f"{pipe['id']}+{where}" if where else pipe["id"],
                    measured=max(cover, 0.0),
                )

    def access(self) -> None:
        for item in self.model.get("equipment", []):
            for envelope in item["envelopes"]:
                solid = Box(
                    item["tag"],
                    tuple(envelope["centre"]),
                    tuple(envelope["size"]),
                    envelope["rotation_deg"],
                )
                box = solid.aabb
                blockers = set()
                for capsule, pipe, k in self.capsules:
                    if not _overlap(capsule.aabb, box):
                        continue
                    if (pipe["id"], k) in self.buried and _above_grade(box):
                        continue
                    if (
                        envelope["kind"] == "access"
                        and item["tag"] in self.ends.get(pipe["id"], {}).values()
                    ):
                        continue
                    if segment_distance(capsule.a, capsule.b, solid) < capsule.r - TOUCH:
                        blockers.add(pipe["id"])
                for member, _, member_id in self.steel.near(box, 0.0):
                    if segment_distance(member.a, member.b, solid) < member.r - TOUCH:  # type: ignore[attr-defined]
                        blockers.add(member_id)
                for part, _, _ in self.parts.near(box, 0.0):
                    if part.id != item["tag"] and _solids_meet(part, solid):
                        blockers.add(part.id)
                if blockers:
                    shown = sorted(blockers)
                    self.add(
                        "warning",
                        "access-blocked",
                        f"{envelope['kind']} space of {item['tag']} is blocked by "
                        f"{', '.join(shown[:6])}"
                        + (f" and {len(shown) - 6} more" if len(shown) > 6 else ""),
                        [envelope["id"], *shown[:6]],
                        _box(box),
                        "keep the space free: reroute the pipes (via points) or move the item",
                        key=envelope["id"],
                    )

    def zones(self) -> None:
        from chemeascode.domains.spatial.zones import volume_solid

        for zone in self.model.get("zones", []):
            if zone["kind"] not in FORBIDDEN_ZONES or zone["kind"] == "escape":
                continue
            for volume in zone["volumes"]:
                solid = volume_solid(volume, zone["id"])
                for capsule, pipe, k in self.capsules:
                    if not _overlap(capsule.aabb, solid.aabb):
                        continue
                    if (pipe["id"], k) in self.buried and _above_grade(solid):
                        continue
                    if segment_distance(capsule.a, capsule.b, solid) < capsule.r - TOUCH:
                        self.add(
                            "warning",
                            "zone-crossing",
                            f"pipe {pipe['id']} ({pipe['line']}) runs through {zone['kind']} "
                            f"zone {zone['id']}",
                            [pipe["id"], zone["id"]],
                            _box(capsule.aabb, solid.aabb),
                            "route it around the zone (via points in piping/routing.yaml)",
                            key=f"{pipe['id']}+{zone['id']}",
                        )

    def rack_fill(self) -> None:
        widths = {rack["id"]: rack["width"] for rack in self.model.get("racks", [])}
        # the router's lanes: the most crowded cross-section along each rack tier (a line
        # split into several segments, or lines one after the other in one lane, counted once)
        fill = (self.model.get("routing") or {}).get("rack_fill")
        if fill:
            for entry in fill:
                rack, tier, total = entry["rack"], entry["tier"], entry["used_m"]
                width = widths.get(rack) or entry.get("width_m")
                if width and total > width + TOUCH:
                    self.add(
                        "warning",
                        "rack-fill",
                        f"rack {rack} tier {tier:g} m carries {total:.2f} m of pipe across "
                        f"its {width:g} m width at its most crowded section",
                        [rack],
                        None,
                        "widen the rack, add a tier, or move lines to another tier (routing tiers)",
                        key=f"{rack}@{tier:g}",
                    )
            return
        load: dict[tuple[str, float], list[str]] = {}
        used: dict[tuple[str, float], float] = {}
        for pipe in self.pipes:
            if pipe.get("tier") is None:
                continue
            for rack in pipe.get("racks", []):
                key = (rack, pipe["tier"])
                width = (
                    pipe["od"] + 2 * pipe.get("insulation_mm", 0.0) / 1000 + self.rules.spacing_m
                )
                used[key] = used.get(key, 0.0) + width
                load.setdefault(key, []).append(pipe["id"])
        for (rack, tier), total in sorted(used.items()):
            width = widths.get(rack)
            if width and total > width + TOUCH:
                self.add(
                    "warning",
                    "rack-fill",
                    f"rack {rack} tier {tier:g} m carries {total:.2f} m of pipe "
                    f"({len(load[(rack, tier)])} pipes) on {width:g} m",
                    [rack],
                    None,
                    "widen the rack, add a tier, or move lines to another tier (routing tiers)",
                    key=f"{rack}@{tier:g}",
                )

    def nozzles(self) -> None:
        routed = {p["segment"] for p in self.pipes}
        reasons = {u["segment"]: u["reason"] for u in self.model.get("unrouted", [])}
        for item in self.model.get("equipment", []):
            for nozzle in item["nozzles"]:
                segments = nozzle["refs"].get("segments") or []
                if not segments or any(s in routed for s in segments):
                    continue
                why = next((reasons[s] for s in segments if s in reasons), "no route")
                x, y, z = nozzle["point"]
                self.add(
                    "info",
                    "nozzle-unconnected",
                    f"nozzle {nozzle['id']} ({', '.join(nozzle['refs'].get('lines') or [])}) has "
                    f"no pipe: {why}",
                    [nozzle["id"]],
                    [x, y, z, x, y, z],
                    "see cheme layout report for the unrouted segments",
                    key=nozzle["id"],
                )

    def connectivity(self) -> None:
        """Every pipe end meets what it connects to (its ``ends``, absent in older models): its
        nozzle's face, another pipe of its junction (a tee, a connector pair, a shared
        component), the placed item, the line it ends on; within :data:`CONNECT_TOL`."""
        nozzles = {
            n["id"]: tuple(n["point"])
            for item in self.model.get("equipment", [])
            for n in item["nozzles"]
        }
        by_key: dict[str, list[dict[str, Any]]] = {}
        by_line: dict[str, list[dict[str, Any]]] = {}
        for pipe in self.pipes:
            by_line.setdefault(pipe["line"], []).append(pipe)
            for end in pipe.get("ends") or ():
                if end.get("kind") == "junction" and end.get("ref"):
                    by_key.setdefault(end["ref"], []).append(pipe)

        def gap_to(point: Vec, others: list[dict[str, Any]]) -> float:
            return min(
                point_segment(point, tuple(a), tuple(b))[0]
                for other in others
                for a, b in zip(other["points"], other["points"][1:], strict=False)
            )

        for pipe in self.pipes:
            ends = pipe.get("ends") or []
            if len(ends) != 2 or len(pipe["points"]) < 2:
                continue
            for side, end in enumerate(ends):
                point = tuple(pipe["points"][-1 if side else 0])
                kind, ref = end.get("kind"), end.get("ref")
                if kind == "nozzle":
                    target = nozzles.get(ref or "")
                    if target is None:
                        continue
                    gap, what = dist(point, target), f"nozzle {ref}"
                elif kind == "junction":
                    others = [o for o in by_key.get(ref or "", []) if o is not pipe]
                    others = [o for o in others if len(o["points"]) > 1]
                    if not others:
                        continue
                    gap = gap_to(point, others)
                    what = f"{_junction_label(ref or '')} ({', '.join(o['id'] for o in others)})"
                elif kind == "item":
                    box = self.bboxes.get(ref or "")
                    if box is None:
                        continue
                    gap = math.dist(
                        point, tuple(min(max(point[i], box[i]), box[i + 3]) for i in range(3))
                    )
                    what = f"item {ref}"
                elif kind == "line":
                    others = [o for o in by_line.get(ref or "", []) if len(o["points"]) > 1]
                    if not others:
                        continue
                    gap, what = gap_to(point, others), f"line {ref}"
                else:
                    continue
                if gap <= CONNECT_TOL:
                    continue
                name = "start" if side == 0 else "end"
                pinned = pipe.get("source") == "pinned" or pipe.get("method", "").startswith("via")
                hint = (
                    "pin the route again from the current model (cheme layout pin) or move "
                    "the pinned end in piping/routing.yaml onto that point"
                    if pinned
                    else "rebuild the model (cheme layout build); if it stays, pin a route "
                    "that meets it (piping/routing.yaml)"
                )
                x, y, z = point
                self.add(
                    "error",
                    "pipe-disconnected",
                    f"{'pinned ' if pipe.get('source') == 'pinned' else ''}pipe {pipe['id']} "
                    f"({pipe['line']}): its {name} at [{x:.3f}, {y:.3f}, {z:.3f}] is "
                    f"{gap:.3f} m from {what} it connects to",
                    [pipe["id"]],
                    [x, y, z, x, y, z],
                    hint,
                    key=f"{pipe['id']}+{name}",
                )

    def gravity(self) -> None:
        fluids = {f.strip().lower() for f in self.rules.gravity_fluids}
        lines = {
            entry.line for entry in (getattr(self.routing, "lines", None) or []) if entry.gravity
        }
        for pipe in self.pipes:
            if (
                pipe["line"] not in lines
                and (pipe.get("fluid") or "").strip().lower() not in fluids
            ):
                continue
            points = pipe["points"]
            level = any(
                abs(a[2] - b[2]) < 1e-3 and dist(tuple(a), tuple(b)) > 0.5
                for a, b in zip(points, points[1:], strict=False)
            )
            if level:
                self.add(
                    "info",
                    "gravity-fall",
                    f"gravity line {pipe['line']} ({pipe['id']}) has level runs (no fall)",
                    [pipe["id"]],
                    _pipe_box(pipe),
                    "pin a route with a fall (e.g. 1:100) in piping/routing.yaml",
                    key=pipe["id"],
                )

    def separations(self) -> None:
        if self.plan is None:
            return
        from chemeascode.domains.spatial.layout_distances import polygon_distance
        from chemeascode.domains.spatial.layout_validate import strip

        zones = {z["id"]: z for z in self.model.get("zones", [])}
        shapes: dict[str, list[list[tuple[float, float]]]] = {}
        for item in self.model.get("equipment", []):
            x0, y0, _, x1, y1, _ = item["bbox"]
            shapes[item["tag"]] = [[(x0, y0), (x1, y0), (x1, y1), (x0, y1)]]
        for key in ("areas",):
            for area in self.model.get(key, []):
                x0, y0, x1, y1 = area["box"]
                shapes.setdefault(area["id"], [[(x0, y0), (x1, y0), (x1, y1), (x0, y1)]])
        for building in self.model.get("buildings", []):
            x0, y0, x1, y1 = building["footprint"]
            shapes.setdefault(building["id"], [[(x0, y0), (x1, y0), (x1, y1), (x0, y1)]])
        for structure in self.model.get("structures", []):
            x0, y0, x1, y1 = structure["footprint"]
            shapes.setdefault(structure["id"], [[(x0, y0), (x1, y0), (x1, y1), (x0, y1)]])
        for road in [*self.model.get("roads", []), *self.model.get("racks", [])]:
            shapes.setdefault(road["id"], strip(road["points"], road["width"]))
        for zone_id, zone in zones.items():
            shapes[zone_id] = [_plan_polygon(v) for v in zone["volumes"]]
        for rule in self.plan.separations:
            names = (rule.from_, rule.to)
            if not any(n in zones for n in names) or rule.min_m is None:
                continue
            a, b = shapes.get(rule.from_), shapes.get(rule.to)
            if not a or not b:
                continue
            measured = min(polygon_distance(p, q) for p in a for q in b)
            if measured + 1e-6 >= rule.min_m:
                continue
            self.add(
                "warning",
                "separation",
                f"{rule.from_} to {rule.to}: {measured:.1f} m < {rule.min_m:g} m"
                + (f" ({rule.basis})" if rule.basis else ""),
                [rule.from_, rule.to],
                None,
                "move the source or the item, or record why the shorter distance is acceptable",
                key=f"{rule.from_}+{rule.to}",
            )

    def run(self) -> list[Finding]:
        self.pipe_pipe()
        self.pipe_equipment()
        self.pipe_steel()
        self.equipment_steel()
        self.headroom()
        self.buried_cover()
        self.access()
        self.zones()
        self.rack_fill()
        self.nozzles()
        self.connectivity()
        self.gravity()
        self.separations()
        from chemeascode.domains.spatial.engineering_rules import EngineeringRules

        EngineeringRules(self).run()
        for rule, count in sorted(self.counts.items()):
            if count > LIMIT:
                self.findings.append(
                    Finding(
                        LAYOUT_MODEL_FILE,
                        "info",
                        f"cheme.layout-{rule}",
                        f"{count - LIMIT} more {rule} findings not listed",
                        key=f"more-{rule}",
                    )
                )
        from chemeascode.domains.spatial.trays import tray_findings

        self.findings += tray_findings(self.model)
        from chemeascode.domains.spatial.hvac import hvac_findings

        self.findings += hvac_findings(self.model)
        return self.findings


def _overlap(a: tuple[float, ...], b: tuple[float, ...]) -> bool:
    return all(min(a[i + 3], b[i + 3]) - max(a[i], b[i]) > -1e-9 for i in range(3))


def _touching(a: Capsule, b: Capsule) -> bool:
    """Whether two pipe runs meet end to end or at a tee (an end on the other's axis)."""
    for p in (a.a, a.b):
        if point_segment(p, b.a, b.b)[0] < 1e-3:
            return True
    return any(point_segment(p, a.a, a.b)[0] < 1e-3 for p in (b.a, b.b))


def _solids_meet(a: Any, b: Box) -> bool:
    """Whether a solid reaches into box *b* (sampled at the solid's box corners and centre)."""
    from chemeascode.domains.spatial.geometry3d import Cylinder, Sphere

    if isinstance(a, Cylinder | Capsule):
        return segment_distance(a.a, a.b, b) < a.r - TOUCH
    if isinstance(a, Sphere):
        return b.distance(a.centre) < a.r - TOUCH
    if isinstance(a, Box):
        aa, bb = a.aabb, b.aabb
        return all(min(aa[i + 3], bb[i + 3]) - max(aa[i], bb[i]) > TOUCH for i in range(3))
    return False


def _samples(points: list[Vec], step: float = 0.5) -> list[Vec]:
    found = []
    for a, b in zip(points, points[1:], strict=False):
        n = max(1, math.ceil(dist(a, b) / step))
        found += [tuple(a[i] + (b[i] - a[i]) * k / n for i in range(3)) for k in range(n + 1)]
    return found  # type: ignore[return-value]


def _pipe_box(pipe: dict[str, Any]) -> list[float]:
    r = pipe["od"] / 2
    points = [tuple(p) for p in pipe["points"]]
    boxes = [segment_box(a, b, r) for a, b in zip(points, points[1:], strict=False)]
    return _box(*(boxes or [segment_box(points[0], points[0], r)]))


def _plan_polygon(volume: dict[str, Any]) -> list[tuple[float, float]]:
    if volume["shape"] == "box":
        x0, y0, _, x1, y1, _ = volume["box"]
        return [(x0, y0), (x1, y0), (x1, y1), (x0, y1)]
    x, y, _ = volume["centre"]
    r = volume["radius"]
    return [
        (x + r * math.cos(k * math.pi / 8), y + r * math.sin(k * math.pi / 8)) for k in range(16)
    ]


def model_rules(model: dict[str, Any], routing: Any = None, plan: Any = None) -> list[Finding]:
    """The findings of the rules above on a model document. Proposed structures (valve access
    platforms, ``source: generated``) are left out until they are pinned; the operability
    rule names them."""
    rules = routing.rules if routing is not None else RoutingRules()
    return _Rules(declared_view(model), rules, routing, plan).run()


def declared_view(model: dict[str, Any]) -> dict[str, Any]:
    """*model* as the rules see it: the proposed structures (``source: generated``) moved from
    ``structures`` to ``proposed_structures``."""
    structures = model.get("structures", [])
    if not any(s.get("source") == "generated" for s in structures):
        return model
    return {
        **model,
        "structures": [s for s in structures if s.get("source") != "generated"],
        "proposed_structures": [s for s in structures if s.get("source") == "generated"],
    }


def workspace_model_rules(workspace: Any, model: dict[str, Any] | None = None) -> list[Finding]:
    """:func:`model_rules` on the committed model of *workspace* (or *model*), with its routing
    intent and site plan where they parse."""
    from chemeascode.domains.spatial.layout_validate import workspace_layout
    from chemeascode.domains.spatial.model import read

    if model is None:
        path = workspace.layout_model_file()
        if path is None:
            return []
        model = read(path.read_text(encoding="utf-8"))
        if model is None:
            return []
    from chemeascode.domains.spatial.lifting import capacity_findings
    from chemeascode.domains.spatial.trays import cable_entry_findings

    layout = workspace_layout(workspace, None)
    return (
        zone_findings(model, layout.zones)
        + model_rules(model, layout.routing, layout.site_plan)
        + capacity_findings(workspace, model, layout.routing, layout.site_plan)
        + cable_entry_findings(workspace, model)
    )


def zone_findings(model: dict[str, Any], zones: Any) -> list[Finding]:
    """``cheme.layout-zone-source`` for the zone sources of *zones* (a parsed
    ``layout/zones.yaml``) the model cannot place: the build reports them, and so do validate,
    the layout report and the API, so the ``zones`` requirement of a layout gate sees them."""
    from chemeascode.domains.spatial.zones import zone_entries

    if zones is None:
        return []
    return zone_entries(zones, model)[1]
