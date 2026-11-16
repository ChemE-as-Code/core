"""2D drawings of the 3D model: plot plan, level plans and sections, as SVG (lxml).

Drawn from the model document alone (``layout/plant-model.yaml``), on an A1 sheet (841 x 594
mm) at the largest standard scale (1:50 .. 1:5000) that fits the drawn region, with a title
block from ``plant.yaml`` (plant name, project number, client, site, revision), a north arrow
(plans), a scale bar and a 10 m coordinate grid with bubbles. SVG units are sheet millimetres.

- **Plan** (``kind="plan"``): seen from above, north up. Parts are drawn by their envelope
  (``lod`` absent or 1) plus the detail that shows in a plan (gratings and stair treads,
  handrails, flanges); proposed stairs, ladders and step-overs dashed. With a z range ``[z0,
  z1)`` (or a level of a structure or building: from its elevation to the next higher level)
  only what reaches into the range is drawn solid; what lies wholly below is dashed and grey,
  what lies wholly above is left out (pipes, ducts and trays piece by piece: a run that rises
  out of the range is drawn up to where it leaves it). Areas, roads, racks (outline and
  bents), buildings (walls), structures (columns, grid with bubbles, spans dimensioned),
  equipment outlines from their parts with tags (dished heads as half ellipses), platforms,
  pipes (axis lines as wide as their OD, line numbers), cable trays (outlines as wide as the
  tray, power and instrument in their own colours, ids) and junction boxes, HVAC ducts
  (outlines as wide as the duct, a colour per system: supply, extract, outdoor air, exhaust,
  ids), air handling units and terminals, in-line items, zones (hatched).
- **Section** (``kind="section"``) at ``x=`` (looking west: y to the right) or ``y=`` (looking
  north: x to the right), ``depth`` m thick (default 6 m, centred on the cut): everything
  in the slab projected; pipes crossing the cut as circles of their OD (insulation as a second
  circle), pipes along it as bands, pipes running away from it inside the slab seen end on (a
  circle; a band where they also run across); cable trays crossing the cut or seen end on as
  their width x depth, along it as bands; ducts likewise (width x height about their
  centreline, a cross where they are cut), air handling units; the
  grade line, rack tiers and structure levels with their elevations.

An optional crop ``[x0, y0, x1, y1]`` (site m; in a section the horizontal axis and z) limits the
drawn region.
"""

from __future__ import annotations

import math
from typing import Any

from lxml import etree

SVG = "http://www.w3.org/2000/svg"
SHEET = (841.0, 594.0)
MARGIN = 10.0
TITLE_H = 40.0
SCALES = (50, 100, 200, 250, 500, 1000, 1250, 2000, 2500, 5000)
GRID = 10.0
COLOURS = {
    "area": "#f3f6ee",
    "road": "#d9d9d9",
    "rack": "#7a5c3e",
    "building": "#555555",
    "steel": "#8a4b2a",
    "equipment": "#1f4e79",
    "pipe": "#2e7d32",
    "insulation": "#a5d6a7",
    "inline": "#c62828",
    "zone": "#ef6c00",
    "platform": "#6d6d6d",
    "below": "#b0b0b0",
    "tray_power": "#c2185b",
    "tray_instrument": "#1565c0",
    "junction_box": "#1565c0",
    "duct_supply": "#00838f",
    "duct_extract": "#6a1b9a",
    "duct_outdoor": "#558b2f",
    "duct_exhaust": "#8d6e63",
    "ahu": "#00695c",
}
ZONE_COLOURS = {
    "hazardous": "#d32f2f",
    "oxygen_enriched": "#1976d2",
    "oxygen_deficient": "#7b1fa2",
    "keep_clear": "#ef6c00",
    "laydown": "#8d6e63",
    "maintenance": "#f9a825",
    "escape": "#2e7d32",
}


class Sheet:
    """Paper: a drawing area mapping site metres (u, v) to sheet mm, v up."""

    def __init__(self, region: tuple[float, float, float, float], title: str, meta: dict[str, str]):
        u0, v0, u1, v1 = region
        if u1 - u0 < 1e-6:
            u1 = u0 + 1.0
        if v1 - v0 < 1e-6:
            v1 = v0 + 1.0
        self.region = (u0, v0, u1, v1)
        width = SHEET[0] - 2 * MARGIN
        height = SHEET[1] - 2 * MARGIN - TITLE_H - 10
        need = max((u1 - u0) * 1000 / width, (v1 - v0) * 1000 / height)
        self.scale = next((s for s in SCALES if s >= need), math.ceil(need / 1000) * 1000)
        self.k = 1000.0 / self.scale  # mm per m
        self.ox = MARGIN + (width - (u1 - u0) * self.k) / 2
        self.oy = MARGIN + 10 + (height - (v1 - v0) * self.k) / 2
        self.title = title
        self.meta = meta
        self.root = etree.Element(
            f"{{{SVG}}}svg",
            nsmap={None: SVG},
            width=f"{SHEET[0]:g}",
            height=f"{SHEET[1]:g}",
            viewBox=f"0 0 {SHEET[0]:g} {SHEET[1]:g}",
        )
        defs = self.sub(self.root, "defs")
        for kind, colour in ZONE_COLOURS.items():
            pattern = self.sub(
                defs,
                "pattern",
                id=f"hatch-{kind}",
                width="3",
                height="3",
                patternUnits="userSpaceOnUse",
                patternTransform="rotate(45)",
            )
            self.sub(
                pattern,
                "line",
                x1="0",
                y1="0",
                x2="0",
                y2="3",
                stroke=colour,
                **{"stroke-width": "0.4"},
            )
        self.sub(
            self.root,
            "rect",
            x="0",
            y="0",
            width=f"{SHEET[0]:g}",
            height=f"{SHEET[1]:g}",
            fill="#ffffff",
        )
        clip = self.sub(defs, "clipPath", id="area")
        self.sub(
            clip,
            "rect",
            x=f"{self.ox:.2f}",
            y=f"{self.oy:.2f}",
            width=f"{(u1 - u0) * self.k:.2f}",
            height=f"{(v1 - v0) * self.k:.2f}",
        )
        self.layers: dict[str, Any] = {}
        body = self.sub(self.root, "g", id="drawing", **{"clip-path": "url(#area)"})
        for name in (
            "grid",
            "areas",
            "zones",
            "roads",
            "buildings",
            "racks",
            "structures",
            "equipment",
            "platforms",
            "pipes",
            "trays",
            "ducts",
            "inline",
            "labels",
        ):
            self.layers[name] = self.sub(body, "g", id=name)

    @staticmethod
    def sub(parent: Any, tag: str, text: str | None = None, **attrs: str) -> Any:
        element = etree.SubElement(parent, f"{{{SVG}}}{tag}", {k: str(v) for k, v in attrs.items()})
        if text is not None:
            element.text = text
        return element

    def p(self, u: float, v: float) -> tuple[float, float]:
        u0, _, _, v1 = self.region
        return (self.ox + (u - u0) * self.k, self.oy + (v1 - v) * self.k)

    def points(self, pts: list[tuple[float, float]]) -> str:
        return " ".join(f"{x:.2f},{y:.2f}" for x, y in (self.p(u, v) for u, v in pts))

    def polygon(
        self,
        layer: str,
        pts,
        fill: str = "none",
        stroke: str = "#000",
        width: float = 0.25,
        dashed: bool = False,
        **attrs: str,
    ) -> Any:
        extra = {"stroke-dasharray": "1.5,1"} if dashed else {}
        return self.sub(
            self.layers[layer],
            "polygon",
            points=self.points(pts),
            fill=fill,
            stroke=stroke,
            **{"stroke-width": f"{width:g}"},
            **extra,
            **attrs,
        )

    def polyline(
        self, layer: str, pts, stroke: str, width: float, dashed: bool = False, **attrs: str
    ) -> Any:
        extra = {"stroke-dasharray": "1.5,1"} if dashed else {}
        return self.sub(
            self.layers[layer],
            "polyline",
            points=self.points(pts),
            fill="none",
            stroke=stroke,
            **{"stroke-width": f"{max(width, 0.18):.2f}", "stroke-linecap": "butt"},
            **extra,
            **attrs,
        )

    def circle(
        self,
        layer: str,
        u: float,
        v: float,
        r: float,
        fill: str = "none",
        stroke: str = "#000",
        width: float = 0.25,
        dashed: bool = False,
        **attrs,
    ) -> Any:
        x, y = self.p(u, v)
        extra = {"stroke-dasharray": "1.5,1"} if dashed else {}
        return self.sub(
            self.layers[layer],
            "circle",
            cx=f"{x:.2f}",
            cy=f"{y:.2f}",
            r=f"{max(r * self.k, 0.2):.2f}",
            fill=fill,
            stroke=stroke,
            **{"stroke-width": f"{width:g}"},
            **extra,
            **attrs,
        )

    def text(
        self,
        layer: str,
        u: float,
        v: float,
        text: str,
        size: float = 2.5,
        anchor: str = "middle",
        colour: str = "#000",
        **attrs,
    ) -> Any:
        x, y = self.p(u, v)
        return self.sub(
            self.layers[layer],
            "text",
            text,
            x=f"{x:.2f}",
            y=f"{y:.2f}",
            **{
                "font-size": f"{size:g}",
                "font-family": "sans-serif",
                "text-anchor": anchor,
                "fill": colour,
            },
            **attrs,
        )

    def finish(self, north: bool) -> str:
        u0, v0, u1, v1 = self.region
        x0, y0 = self.p(u0, v1)
        x1, y1 = self.p(u1, v0)
        self.sub(
            self.root,
            "rect",
            x=f"{x0:.2f}",
            y=f"{y0:.2f}",
            width=f"{x1 - x0:.2f}",
            height=f"{y1 - y0:.2f}",
            fill="none",
            stroke="#000",
            **{"stroke-width": "0.35"},
        )
        # 10 m grid with bubbles along the bottom and left edges
        grid = self.layers["grid"]
        start = math.ceil(u0 / GRID) * GRID
        u = start
        step = GRID * max(1, round(8 / (GRID * self.k)))  # at least 8 mm apart
        while u <= u1 + 1e-9:
            a, b = self.p(u, v0), self.p(u, v1)
            self.sub(
                grid,
                "line",
                x1=f"{a[0]:.2f}",
                y1=f"{a[1]:.2f}",
                x2=f"{b[0]:.2f}",
                y2=f"{b[1]:.2f}",
                stroke="#e0e0e0",
                **{"stroke-width": "0.15"},
            )
            self._bubble(a[0], a[1] + 4, f"{u:g}")
            u += step
        v = math.ceil(v0 / GRID) * GRID
        while v <= v1 + 1e-9:
            a, b = self.p(u0, v), self.p(u1, v)
            self.sub(
                grid,
                "line",
                x1=f"{a[0]:.2f}",
                y1=f"{a[1]:.2f}",
                x2=f"{b[0]:.2f}",
                y2=f"{b[1]:.2f}",
                stroke="#e0e0e0",
                **{"stroke-width": "0.15"},
            )
            self._bubble(a[0] - 4, a[1], f"{v:g}")
            v += step
        if north:
            self._north(SHEET[0] - MARGIN - 15, MARGIN + 18)
        self._scale_bar(MARGIN + 5, SHEET[1] - MARGIN - TITLE_H - 4)
        self._title()
        return etree.tostring(self.root, encoding="unicode", pretty_print=True)

    def _bubble(self, x: float, y: float, label: str) -> None:
        g = self.sub(self.root, "g", **{"class": "bubble"})
        self.sub(
            g,
            "circle",
            cx=f"{x:.2f}",
            cy=f"{y:.2f}",
            r="2.6",
            fill="#fff",
            stroke="#000",
            **{"stroke-width": "0.2"},
        )
        self.sub(
            g,
            "text",
            label,
            x=f"{x:.2f}",
            y=f"{y + 0.8:.2f}",
            **{"font-size": "1.8", "font-family": "sans-serif", "text-anchor": "middle"},
        )

    def _north(self, x: float, y: float) -> None:
        g = self.sub(self.root, "g", id="north-arrow")
        self.sub(
            g,
            "polygon",
            points=f"{x},{y - 10} {x - 4},{y + 4} {x},{y + 1} {x + 4},{y + 4}",
            fill="#000",
        )
        self.sub(
            g,
            "text",
            "N",
            x=f"{x}",
            y=f"{y - 12}",
            **{"font-size": "5", "font-family": "sans-serif", "text-anchor": "middle"},
        )

    def _scale_bar(self, x: float, y: float) -> None:
        g = self.sub(self.root, "g", id="scale-bar")
        length_m = next(
            (n for n in (1, 2, 5, 10, 20, 25, 50, 100, 200, 500) if n * self.k >= 40), 500
        )
        for i in range(5):
            self.sub(
                g,
                "rect",
                x=f"{x + i * length_m * self.k / 5:.2f}",
                y=f"{y:.2f}",
                width=f"{length_m * self.k / 5:.2f}",
                height="1.5",
                fill="#000" if i % 2 == 0 else "#fff",
                stroke="#000",
                **{"stroke-width": "0.2"},
            )
        self.sub(
            g,
            "text",
            f"0      {length_m:g} m    1:{self.scale}",
            x=f"{x:.2f}",
            y=f"{y - 1.5:.2f}",
            **{"font-size": "2.5", "font-family": "sans-serif"},
        )

    def _title(self) -> None:
        x = SHEET[0] - MARGIN - 180
        y = SHEET[1] - MARGIN - TITLE_H
        g = self.sub(self.root, "g", id="title-block")
        self.sub(
            g,
            "rect",
            x=f"{x}",
            y=f"{y}",
            width="180",
            height=f"{TITLE_H}",
            fill="#fff",
            stroke="#000",
            **{"stroke-width": "0.5"},
        )
        rows = [
            (self.title, 5.0),
            (self.meta.get("plant", ""), 3.5),
            (
                " | ".join(
                    v
                    for v in (
                        self.meta.get("project", ""),
                        self.meta.get("client", ""),
                        self.meta.get("site", ""),
                    )
                    if v
                ),
                2.8,
            ),
            (
                f"Scale 1:{self.scale} (A1)   Rev {self.meta.get('revision', 'A')}   "
                f"generated by cheme layout render from layout/plant-model.yaml",
                2.4,
            ),
        ]
        for i, (text, size) in enumerate(rows):
            self.sub(
                g,
                "text",
                text,
                x=f"{x + 4}",
                y=f"{y + 8 + i * 8}",
                **{"font-size": f"{size:g}", "font-family": "sans-serif"},
            )


# ---------------------------------------------------------------------------
# helpers
# ---------------------------------------------------------------------------


def _strip(points: list[list[float]], width: float) -> list[list[tuple[float, float]]]:
    from chemeascode.domains.spatial.layout_validate import strip

    return strip([tuple(p) for p in points], width)


def _rect(centre, size, rotation: float) -> list[tuple[float, float]]:
    a = math.radians(rotation)
    c, s = math.cos(a), math.sin(a)
    hx, hy = size[0] / 2, size[1] / 2
    return [
        (centre[0] + u * c - v * s, centre[1] + u * s + v * c)
        for u, v in ((-hx, -hy), (hx, -hy), (hx, hy), (-hx, hy))
    ]


#: Detail (``lod: 2``) a plan shows besides the envelope: stairs and gratings, handrails and
#: flanges.
PLAN_DETAIL = ("grating", "handrail", "flange")


def in_plan(part: dict[str, Any]) -> bool:
    """Whether a plan draws *part*: the envelope (``lod`` absent or 1) and the detail of
    :data:`PLAN_DETAIL`."""
    return part.get("lod") != 2 or part.get("material") in PLAN_DETAIL


def _part_z(part: dict[str, Any]) -> tuple[float, float]:
    """Bottom and top elevation of a part (approximate for caps and annuli)."""
    from chemeascode.domains.spatial.geometry3d import part_solid

    solid = part_solid(part, detail=part.get("lod") == 2)
    if solid is None:
        return (0.0, 0.0)
    box = solid.aabb
    return (box[2], box[5])


def _state(z0: float, z1: float, cut: tuple[float, float] | None) -> str | None:
    """``solid``, ``below`` (dashed) or None (above the cut: not drawn)."""
    if cut is None:
        return "solid"
    if z1 < cut[0] - 1e-6:
        return "below"
    if z0 >= cut[1] - 1e-6:
        return None
    return "solid"


def _meta(meta: dict[str, str] | None) -> dict[str, str]:
    return dict(meta or {})


def model_extent(model: dict[str, Any]) -> tuple[float, float, float, float]:
    site = model.get("site")
    if site:
        return (0.0, 0.0, site["width"], site["depth"])
    xs, ys = [], []
    for item in model.get("equipment", []):
        x0, y0, _, x1, y1, _ = item["bbox"]
        xs += [x0, x1]
        ys += [y0, y1]
    if not xs:
        return (0.0, 0.0, 10.0, 10.0)
    return (min(xs) - 5, min(ys) - 5, max(xs) + 5, max(ys) + 5)


def level_range(model: dict[str, Any], level: str) -> tuple[float, float] | None:
    """``[z0, z1)`` of a structure or building level: its elevation (minus 0.1 m) up to the
    next higher level of the same owner (else 4 m higher; levels at the same elevation, split
    platforms, share the range); None when no level has that id."""
    for owner in [*model.get("structures", []), *model.get("buildings", [])]:
        levels = owner.get("levels", [])
        for lv in levels:
            if lv["id"] == level or f"{owner['id']}/{lv['id']}" == level:
                z = lv["elevation"]
                top = min(
                    (o["elevation"] for o in levels if o["elevation"] > z + 1e-6), default=z + 4
                )
                return (z - 0.1, top - 0.1)
    return None


# ---------------------------------------------------------------------------
# Plan
# ---------------------------------------------------------------------------


def render_plan(
    model: dict[str, Any],
    meta: dict[str, str] | None = None,
    cut: tuple[float, float] | None = None,
    crop: tuple[float, float, float, float] | None = None,
    title: str | None = None,
) -> str:
    """The plot plan, or a level plan with *cut* ``(z0, z1)`` (see the module text)."""
    region = crop or model_extent(model)
    name = title or ("Plot plan" if cut is None else f"Level plan z {cut[0]:g} .. {cut[1]:g} m")
    sheet = Sheet(region, name, _meta(meta))
    for area in model.get("areas", []):
        x0, y0, x1, y1 = area["box"]
        sheet.polygon(
            "areas",
            [(x0, y0), (x1, y0), (x1, y1), (x0, y1)],
            fill=COLOURS["area"],
            stroke="#9e9e9e",
            width=0.2,
            id=f"area-{area['id']}",
        )
        sheet.text("labels", x0 + 1, y1 - 2.5, area["id"], size=3, anchor="start", colour="#616161")
        for part in area.get("parts", []):  # a bund's walls
            sheet.polygon(
                "areas",
                _rect(part["centre"], part["size"], part["rotation_deg"]),
                fill="#9e9e9e",
                stroke="none",
                width=0,
            )
    for road in model.get("roads", []):
        for k, poly in enumerate(_strip(road["points"], road["width"])):
            sheet.polygon(
                "roads",
                poly,
                fill=COLOURS["road"],
                stroke="none",
                width=0,
                id=f"road-{road['id']}-{k}",
            )
    for zone in model.get("zones", []):
        _zone_plan(sheet, zone, cut)
    for building in model.get("buildings", []):
        x0, y0, x1, y1 = building["footprint"]
        state = _state(*building["heights"], cut)
        if state is None:
            continue
        sheet.polygon(
            "buildings",
            [(x0, y0), (x1, y0), (x1, y1), (x0, y1)],
            stroke=COLOURS["building"] if state == "solid" else COLOURS["below"],
            width=0.5,
            dashed=state == "below",
            id=f"building-{building['id']}",
        )
        for part in building.get("parts", []):
            if part.get("lod") == 2 or part["kind"] != "box" or part["material"] == "roof":
                continue
            sheet.polygon(
                "buildings",
                _rect(part["centre"], part["size"], part["rotation_deg"]),
                fill=COLOURS["building"],
                stroke="none",
                width=0,
            )
        sheet.text("labels", (x0 + x1) / 2, y1 - 2, building["id"], size=3)
    for rack in model.get("racks", []):
        for poly in _strip(rack["points"], rack["width"]):
            sheet.polygon(
                "racks",
                poly,
                stroke=COLOURS["rack"],
                width=0.3,
                dashed=True,
                id=f"rack-{rack['id']}",
            )
        for part in rack.get("parts", []):
            if "/col-" in part["id"]:
                x, y, _ = part["start"]
                b, h = part.get("profile") or (0.3, 0.3)
                sheet.polygon(
                    "racks",
                    _rect((x, y), (b, h), 0.0),
                    fill=COLOURS["rack"],
                    stroke="none",
                    width=0,
                )
        mid = rack["points"][len(rack["points"]) // 2 - 1 if len(rack["points"]) > 1 else 0]
        sheet.text(
            "labels",
            mid[0],
            mid[1] + rack["width"] / 2 + 1,
            rack["id"],
            size=2.5,
            colour=COLOURS["rack"],
        )
    for structure in model.get("structures", []):
        _structure_plan(sheet, structure, cut)
    for steel in model.get("support_steel", []):
        _support_plan(sheet, steel, cut)
    for rack in model.get("racks", []):
        for ladder in rack.get("ladders", []):
            _ladder_plan(sheet, ladder, COLOURS["rack"])
    for item in model.get("equipment", []):
        _equipment_plan(sheet, item, cut)
    for step in model.get("step_overs", []):
        x0, y0, z0, x1, y1, z1 = step["box"]
        if _state(z0, z1, cut) is None:
            continue
        sheet.polygon(
            "platforms",
            [(x0, y0), (x1, y0), (x1, y1), (x0, y1)],
            stroke=COLOURS["platform"],
            width=0.2,
            dashed=True,
            id=f"step-over-{step['id']}",
        )
    for platform in model.get("platforms", []):
        state = _state(platform["elevation"] - 0.05, platform["elevation"], cut)
        if state is None:
            continue
        for part in platform["parts"]:
            if part["kind"] == "annulus" and part["material"] == "grating":
                x, y, _ = part["centre"]
                sheet.circle(
                    "platforms",
                    x,
                    y,
                    part["radius_end"],
                    stroke=COLOURS["platform"],
                    width=0.2,
                    dashed=state == "below" or platform["source"] == "generated",
                )
            elif part["kind"] == "box":
                sheet.polygon(
                    "platforms",
                    _rect(part["centre"], part["size"], part["rotation_deg"]),
                    stroke=COLOURS["platform"],
                    width=0.2,
                    dashed=True,
                )
    for pipe in model.get("pipes", []):
        _pipe_plan(sheet, pipe, cut)
    for tray in model.get("trays") or []:
        _tray_plan(sheet, tray, cut)
    for box in model.get("junction_boxes") or []:
        state = _state(box["point"][2], box["point"][2], cut)
        if state is None:
            continue
        x, y, _ = box["point"]
        colour = COLOURS["below"] if state == "below" else COLOURS["junction_box"]
        sheet.polygon(
            "trays",
            _rect((x, y), (0.6, 0.25), 0.0),
            fill=colour,
            stroke=colour,
            width=0.2,
            id=f"jb-{box['id']}",
        )
        sheet.text("labels", x, y + 0.5, box["tag"], size=1.4, colour=colour)
    for unit in model.get("hvac_units") or []:
        x, y, z = unit["position"]
        state = _state(z, z + unit["size"][2], cut)
        if state is None:
            continue
        colour = COLOURS["below"] if state == "below" else COLOURS["ahu"]
        length, width, _ = unit["size"]
        sheet.polygon(
            "ducts",
            _rect((x, y), (length, width), unit["rotation_deg"]),
            stroke=colour,
            width=0.3,
            dashed=state == "below",
            id=f"ahu-{unit['id']}",
        )
        sheet.text("labels", x, y, unit["id"], size=1.8, colour=colour)
    for duct in model.get("ducts") or []:
        _duct_plan(sheet, duct, cut)
    for room in model.get("hvac_rooms") or []:
        for terminal in room["terminals"]:
            x, y, z = terminal["point"]
            state = _state(z, z, cut)
            if state is None:
                continue
            colour = COLOURS["below"] if state == "below" else COLOURS[f"duct_{terminal['system']}"]
            sheet.polygon(
                "ducts",
                _rect((x, y), (0.6, 0.6), 0.0),
                stroke=colour,
                width=0.15,
                dashed=state == "below",
                id=f"terminal-{terminal['id']}",
            )
    for item in model.get("inline", []):
        state = _state(item["point"][2], item["point"][2], cut)
        if state != "solid":
            continue
        x, y, _ = item["point"]
        sheet.circle(
            "inline",
            x,
            y,
            0.25,
            fill=COLOURS["inline"],
            stroke="none",
            width=0,
            id=f"inline-{item['id']}",
        )
    return sheet.finish(north=True)


def _zone_plan(sheet: Sheet, zone: dict[str, Any], cut) -> None:
    from chemeascode.domains.spatial.zones import volume_box

    kind = zone["kind"]
    colour = ZONE_COLOURS.get(kind, COLOURS["zone"])
    for k, volume in enumerate(zone["volumes"]):
        x0, y0, z0, x1, y1, z1 = volume_box(volume)
        if _state(z0, z1, cut) is None:
            continue
        attrs = {"id": f"zone-{zone['id']}-{k}", "fill-opacity": "0.8"}
        fill = f"url(#hatch-{kind})"
        if volume["shape"] == "box":
            sheet.polygon(
                "zones",
                [(x0, y0), (x1, y0), (x1, y1), (x0, y1)],
                fill=fill,
                stroke=colour,
                width=0.25,
                **attrs,
            )
        else:
            x, y, _ = volume["centre"]
            sheet.circle(
                "zones", x, y, volume["radius"], fill=fill, stroke=colour, width=0.25, **attrs
            )
        if k == 0:
            label = zone["id"] + (f" (zone {zone['zone']})" if zone.get("zone") is not None else "")
            sheet.text("labels", (x0 + x1) / 2, y0 - 1.2, label, size=2, colour=colour)


def _support_plan(sheet: Sheet, steel: dict[str, Any], cut) -> None:
    """A post or T-post under a pipe: its column as a square, its crossbar (cap) as a line;
    a proposal dashed."""
    state = _state(steel["base"], steel["top"], cut)
    if state is None:
        return
    colour = COLOURS["steel"] if state == "solid" else COLOURS["below"]
    dashed = steel.get("source") == "generated" or state == "below"
    for part in steel.get("parts", []):
        if part["kind"] != "member":
            continue
        a, b = part["start"], part["end"]
        if abs(a[0] - b[0]) < 1e-6 and abs(a[1] - b[1]) < 1e-6:
            half = (part.get("profile") or (0.2, 0.2))[0] / 2
            x, y = a[0], a[1]
            sheet.polygon(
                "structures",
                [
                    (x - half, y - half),
                    (x + half, y - half),
                    (x + half, y + half),
                    (x - half, y + half),
                ],
                stroke=colour,
                width=0.2,
                dashed=dashed,
            )
        else:
            sheet.polyline(
                "structures",
                [a[:2], b[:2]],
                stroke=colour,
                width=0.35,
                dashed=dashed,
                id=f"support-steel-{steel['id']}",
            )


def _structure_plan(sheet: Sheet, structure: dict[str, Any], cut) -> None:
    from chemeascode.domains.spatial.structures import Frame

    state = _state(0.0, structure["height"], cut)
    if state is None:
        return
    colour = COLOURS["steel"] if state == "solid" else COLOURS["below"]
    frame = Frame(tuple(structure["origin"]), structure["rotation_deg"])
    gx, gy = structure["grid_x"], structure["grid_y"]
    letters = "ABCDEFGHJKLMNPQRSTUVWXYZ"
    for i, u in enumerate(gx):
        a, b = frame.site(u, -1.5)[:2], frame.site(u, gy[-1] + 1.5)[:2]
        sheet.polyline(
            "structures", [a, b], stroke="#9e9e9e", width=0.15, **{"stroke-dasharray": "4,1,1,1"}
        )
        x, y = sheet.p(*frame.site(u, gy[-1] + 3.0)[:2])
        sheet._bubble(x, y, str(i + 1))
    for j, v in enumerate(gy):
        a, b = frame.site(-1.5, v)[:2], frame.site(gx[-1] + 1.5, v)[:2]
        sheet.polyline(
            "structures", [a, b], stroke="#9e9e9e", width=0.15, **{"stroke-dasharray": "4,1,1,1"}
        )
        x, y = sheet.p(*frame.site(-3.0, v)[:2])
        sheet._bubble(x, y, letters[j % len(letters)])
    # spans dimensioned along the south side
    for u0, u1 in zip(gx, gx[1:], strict=False):
        a, b = frame.site(u0, -4.5)[:2], frame.site(u1, -4.5)[:2]
        sheet.polyline("structures", [a, b], stroke="#000", width=0.15)
        mid = frame.site((u0 + u1) / 2, -5.5)[:2]
        sheet.text("labels", mid[0], mid[1], f"{u1 - u0:g}", size=2)
    for part in structure["parts"]:
        if part["kind"] != "member":
            continue
        z0, z1 = sorted((part["start"][2], part["end"][2]))
        s = _state(z0, z1, cut)
        if s is None:
            continue
        if (
            abs(part["start"][0] - part["end"][0]) < 1e-6
            and abs(part["start"][1] - part["end"][1]) < 1e-6
        ):
            b, h = part.get("profile") or (0.3, 0.3)
            sheet.polygon(
                "structures",
                _rect(part["start"][:2], (b, h), structure["rotation_deg"]),
                fill=colour,
                stroke="none",
                width=0,
            )
        elif cut is not None and s == "solid" and "/beam-" in part["id"]:
            sheet.polyline(
                "structures", [part["start"][:2], part["end"][:2]], stroke=colour, width=0.2
            )
        elif (
            cut is not None
            and s == "solid"
            and part.get("material") == "handrail"
            and part.get("lod") != 2  # the top rail
        ):
            sheet.polyline(
                "structures",
                [part["start"][:2], part["end"][:2]],
                stroke=COLOURS["platform"],
                width=0.12,
                **{"stroke-dasharray": "1,0.6"},
            )
    for wall in structure.get("walls", []):
        sheet.polygon(
            "structures",
            _rect(wall["centre"], wall["size"], wall["rotation_deg"]),
            fill="#bdbdbd",
            stroke=colour,
            width=0.2,
        )
    for stair in structure.get("stairs", []):
        x0, y0, z0, x1, y1, _ = stair["box"]
        if _state(z0, stair["box"][5], cut) is None:
            continue
        proposed = stair.get("source") == "generated"
        sheet.polygon(
            "structures",
            [(x0, y0), (x1, y0), (x1, y1), (x0, y1)],
            stroke=colour,
            width=0.2,
            dashed=proposed,
            id=f"stair-{stair['id']}",
        )
        for part in stair.get("parts", []):  # treads and landings
            if part["kind"] == "box":
                sheet.polygon(
                    "structures",
                    _rect(part["centre"], part["size"], part["rotation_deg"]),
                    stroke=colour,
                    width=0.08,
                )
    for ladder in structure.get("ladders", []):
        _ladder_plan(sheet, ladder, colour)
    x0, y0, x1, y1 = structure["footprint"]
    if structure.get("source") == "generated":  # a proposal (a valve access platform): dashed
        sheet.polygon(
            "structures",
            [(x0, y0), (x1, y0), (x1, y1), (x0, y1)],
            stroke=COLOURS["platform"],
            width=0.25,
            dashed=True,
            id=f"structure-{structure['id']}",
        )
    sheet.text("labels", (x0 + x1) / 2, (y0 + y1) / 2, structure["id"], size=2.5, colour=colour)


def _ladder_plan(sheet: Sheet, ladder: dict[str, Any], colour: str) -> None:
    """A ladder in plan: its rails and, caged, a circle; dashed when proposed."""
    x, y, _ = ladder["base"]
    proposed = ladder.get("source") == "generated"
    sheet.circle(
        "structures",
        x,
        y,
        0.35 if ladder.get("cage") else 0.25,
        stroke=colour,
        width=0.15,
        dashed=proposed,
        id=f"ladder-{ladder['id']}",
    )


def _equipment_plan(sheet: Sheet, item: dict[str, Any], cut) -> None:
    x0, y0, z0, x1, y1, z1 = item["bbox"]
    state = _state(z0, z1, cut)
    if state is None:
        return
    colour = COLOURS["equipment"] if state == "solid" else COLOURS["below"]
    dashed = state == "below"
    group = sheet.sub(sheet.layers["equipment"], "g", id=f"equipment-{item['tag']}")
    keep = sheet.layers["equipment"]
    sheet.layers["equipment"] = group
    for part in item["parts"]:
        if not in_plan(part):
            continue
        pz0, pz1 = _part_z(part)
        if _state(pz0, pz1, cut) is None:
            continue
        kind = part["kind"]
        thin = 0.15 if part.get("lod") == 2 else 0.3
        if kind in ("torus", "annulus"):
            x, y, _ = part["centre"]
            axis = part.get("axis") or (0.0, 0.0, 1.0)
            if kind == "annulus" or abs(axis[2]) > 0.99:
                outer = part["radius_end"] if kind == "annulus" else part["radius"] + part["tube"]
                sheet.circle("equipment", x, y, outer, stroke=colour, width=thin, dashed=dashed)
                continue
            solid_box = _plan_box(part)
            if solid_box is not None:
                sheet.polygon("equipment", solid_box, stroke=colour, width=thin, dashed=dashed)
            continue
        if kind == "frustum":
            size = part["size"]
            top = part.get("size_end") or size[:2]
            big = (max(size[0], top[0]), max(size[1], top[1]))
            sheet.polygon(
                "equipment",
                _rect(part["centre"], big, part.get("rotation_deg") or 0.0),
                stroke=colour,
                width=thin,
                dashed=dashed,
            )
            continue
        if kind in ("cylinder", "cone"):
            a, b = part["start"], part["end"]
            r = max(part["radius"], part.get("radius_end") or 0.0)
            if abs(a[0] - b[0]) < 1e-6 and abs(a[1] - b[1]) < 1e-6:
                sheet.circle("equipment", a[0], a[1], r, stroke=colour, width=thin, dashed=dashed)
            else:
                length = math.hypot(b[0] - a[0], b[1] - a[1])
                angle = math.degrees(math.atan2(b[1] - a[1], b[0] - a[0]))
                centre = ((a[0] + b[0]) / 2, (a[1] + b[1]) / 2)
                sheet.polygon(
                    "equipment",
                    _rect(centre, (length, 2 * r), angle),
                    stroke=colour,
                    width=thin,
                    dashed=dashed,
                )
        elif kind == "box":
            sheet.polygon(
                "equipment",
                _rect(part["centre"], part["size"], part["rotation_deg"]),
                stroke=colour,
                width=thin,
                dashed=dashed,
            )
        elif kind == "sphere":
            sheet.circle(
                "equipment",
                part["centre"][0],
                part["centre"][1],
                part["radius"],
                stroke=colour,
                width=thin,
                dashed=dashed,
            )
        elif kind == "cap":
            x, y, _ = part["centre"]
            if math.hypot(part["axis"][0], part["axis"][1]) < 1e-6:  # within its shell
                r = part["radius"]
                sheet.circle("equipment", x, y, r, stroke=colour, width=thin, dashed=dashed)
                continue
            sheet.polygon("equipment", _cap_plan(part), stroke=colour, width=thin, dashed=dashed)
    sheet.layers["equipment"] = keep
    sheet.text(
        "labels",
        (x0 + x1) / 2,
        (y0 + y1) / 2 - 0.4,
        item["tag"],
        size=2.2,
        colour=colour,
        **{"font-weight": "bold"},
    )


def _cap_plan(part: dict[str, Any]) -> list[tuple[float, float]]:
    """The plan outline of a dished head on a horizontal (or inclined) axis: a half ellipse
    from its centre, where it meets the shell, to its tip, as wide as the shell."""
    x, y, _ = part["centre"]
    ax, ay, _ = part["axis"]
    reach = math.hypot(ax, ay)
    ux, uy = ax / reach, ay / reach
    along = (part.get("depth") or 0.0) * reach  # an inclined axis: the depth foreshortened
    r = part["radius"]
    angles = [math.pi * (k / 12 - 0.5) for k in range(13)]
    return [
        (
            x + ux * along * math.cos(a) - uy * r * math.sin(a),
            y + uy * along * math.cos(a) + ux * r * math.sin(a),
        )
        for a in angles
    ]


def _plan_box(part: dict[str, Any]) -> list[tuple[float, float]] | None:
    """The plan outline of a part as its solid's box."""
    from chemeascode.domains.spatial.geometry3d import part_solid

    solid = part_solid(part, detail=True)
    if solid is None:
        return None
    x0, y0, _, x1, y1, _ = solid.aabb
    return [(x0, y0), (x1, y0), (x1, y1), (x0, y1)]


def _cut_runs(
    points: list[list[float]], cut, down: float = 0.0, up: float = 0.0
) -> list[tuple[str, list[list[float]]]]:
    """A run (pipe, duct, tray) cut by the plan's z range into pieces: ``(state, points)`` in
    order (``solid``, ``below``; the pieces above the cut are left out). A point of the
    centreline at z takes ``z - down`` .. ``z + up`` (the run's own size about it)."""
    if cut is None:
        return [("solid", [list(p) for p in points])]
    # where the centreline reaches into the range from below, and where it leaves it above
    levels = (cut[0] - up, cut[1] + down)
    runs: list[tuple[str | None, list[list[float]]]] = []
    for a, b in zip(points, points[1:], strict=False):
        dz = b[2] - a[2]
        ts = sorted(
            {0.0, 1.0} | {(z - a[2]) / dz for z in levels if abs(dz) > 1e-9 and a[2] != z != b[2]}
        )
        ts = [t for t in ts if 0.0 <= t <= 1.0]
        for t0, t1 in zip(ts, ts[1:], strict=False):
            p0 = [a[k] + (b[k] - a[k]) * t0 for k in range(3)]
            p1 = [a[k] + (b[k] - a[k]) * t1 for k in range(3)]
            mid = (p0[2] + p1[2]) / 2
            state = _state(mid - down, mid + up, cut)
            if runs and runs[-1][0] == state:
                runs[-1][1].append(p1)
            else:
                runs.append((state, [p0, p1]))
    return [(state, pts) for state, pts in runs if state is not None]


def _flat(points: list[list[float]]) -> list[tuple[float, float]]:
    """The plan points of a run without the repeats of its risers."""
    flat = [(points[0][0], points[0][1])]
    for p in points[1:]:
        if math.hypot(p[0] - flat[-1][0], p[1] - flat[-1][1]) > 1e-6:
            flat.append((p[0], p[1]))
    return flat


def _longest(pieces: list[tuple[str, list[tuple[float, float]]]]):
    """``(length, midpoint, state)`` of the longest plan segment, solid pieces first."""
    best = (0.0, None, None)
    for state in ("solid", "below"):
        for piece_state, flat in pieces:
            if piece_state != state:
                continue
            for a, b in zip(flat, flat[1:], strict=False):
                length = math.hypot(b[0] - a[0], b[1] - a[1])
                if length > best[0]:
                    best = (length, ((a[0] + b[0]) / 2, (a[1] + b[1]) / 2), state)
        if best[1] is not None:
            break
    return best


def _pipe_plan(sheet: Sheet, pipe: dict[str, Any], cut) -> None:
    """A pipe in plan: each piece in the cut a line as wide as its OD (a riser a circle), each
    piece below it dashed and grey; its line number on the longest run."""
    od = pipe["od"] + 2 * pipe.get("insulation_mm", 0.0) / 1000
    runs = _cut_runs(pipe["points"], cut, od / 2, od / 2)
    if not runs:
        return
    own = (pipe.get("class") or {}).get("colour") or COLOURS["pipe"]
    group = sheet.sub(
        sheet.layers["pipes"], "g", id=f"pipe-{pipe['id']}", **{"data-line": pipe["line"]}
    )
    keep = sheet.layers["pipes"]
    sheet.layers["pipes"] = group
    pieces = [(state, _flat(points)) for state, points in runs]
    # a riser seen in the cut is drawn once, solid, not over its dashed piece below the cut
    risers = {flat[0] for state, flat in pieces if state == "solid" and len(flat) == 1}
    for state, flat in pieces:
        colour = own if state == "solid" else COLOURS["below"]
        if len(flat) >= 2:
            sheet.polyline(
                "pipes", flat, stroke=colour, width=od * sheet.k, dashed=state == "below"
            )
        elif state == "solid" or flat[0] not in risers:  # a riser: its section
            x, y = flat[0]
            sheet.circle("pipes", x, y, od / 2, stroke=colour, width=0.2, dashed=state == "below")
    sheet.layers["pipes"] = keep
    best, at, state = _longest(pieces)
    if at is not None and best * sheet.k > 12:
        colour = own if state == "solid" else COLOURS["below"]
        sheet.text("labels", at[0], at[1] + od / 2 + 0.3, pipe["line"], size=1.6, colour=colour)


def _duct_plan(sheet: Sheet, duct: dict[str, Any], cut) -> None:
    """A duct in plan: its outline as wide as the duct (a riser its section) for each piece in
    the cut, dashed and grey below it, its id on the longest run."""
    h = duct["height"] / 2
    runs = _cut_runs(duct["points"], cut, h, h)
    if not runs:
        return
    group = sheet.sub(
        sheet.layers["ducts"], "g", id=f"duct-{duct['id']}", **{"data-system": duct["system"]}
    )
    keep = sheet.layers["ducts"]
    sheet.layers["ducts"] = group
    pieces = []
    for state, points in runs:
        colour = COLOURS["below"] if state == "below" else COLOURS[f"duct_{duct['system']}"]
        flat = _flat(points)
        pieces.append((state, flat))
        if len(flat) >= 2:
            for polygon in _strip([list(p) for p in flat], duct["width"]):
                sheet.polygon("ducts", polygon, stroke=colour, width=0.2, dashed=state == "below")
        else:  # a riser: its section
            sheet.polygon(
                "ducts",
                _rect(flat[0], (duct["width"], duct["height"]), 0.0),
                stroke=colour,
                width=0.2,
                dashed=state == "below",
            )
    sheet.layers["ducts"] = keep
    best, at, state = _longest(pieces)
    if at is not None and best * sheet.k > 15:
        colour = COLOURS["below"] if state == "below" else COLOURS[f"duct_{duct['system']}"]
        sheet.text(
            "labels", at[0], at[1] + duct["width"] / 2 + 0.4, duct["id"], size=1.3, colour=colour
        )


def _tray_plan(sheet: Sheet, tray: dict[str, Any], cut) -> None:
    """A cable tray in plan: its outline as wide as the tray for each piece in the cut, dashed
    and grey below it, its id on the longest run."""
    runs = _cut_runs(tray["points"], cut, 0.0, tray["depth"])
    if not runs:
        return
    group = sheet.sub(
        sheet.layers["trays"], "g", id=f"tray-{tray['id']}", **{"data-system": tray["system"]}
    )
    keep = sheet.layers["trays"]
    sheet.layers["trays"] = group
    pieces = []
    for state, points in runs:
        colour = COLOURS["below"] if state == "below" else COLOURS[f"tray_{tray['system']}"]
        flat = _flat(points)
        pieces.append((state, flat))
        if len(flat) >= 2:
            for polygon in _strip([list(p) for p in flat], tray["width"]):
                sheet.polygon("trays", polygon, stroke=colour, width=0.18, dashed=state == "below")
    sheet.layers["trays"] = keep
    best, at, state = _longest(pieces)
    if at is not None and best * sheet.k > 15:
        colour = COLOURS["below"] if state == "below" else COLOURS[f"tray_{tray['system']}"]
        sheet.text(
            "labels", at[0], at[1] - tray["width"] / 2 - 0.6, tray["id"], size=1.3, colour=colour
        )


# ---------------------------------------------------------------------------
# Section
# ---------------------------------------------------------------------------


def render_section(
    model: dict[str, Any],
    axis: str,
    at: float,
    depth: float = 6.0,
    meta: dict[str, str] | None = None,
    crop: tuple[float, float, float, float] | None = None,
    title: str | None = None,
) -> str:
    """A section at ``x=at`` or ``y=at`` (*axis*), *depth* m thick (see the module text)."""
    if axis not in ("x", "y"):
        raise ValueError("a section is at x= or y=")
    lo, hi = at - depth / 2, at + depth / 2
    i = 0 if axis == "x" else 1  # the cut's coordinate
    j = 1 - i  # the drawing's horizontal axis

    def inside(box: tuple[float, ...]) -> bool:
        return box[i + 3] >= lo - 1e-6 and box[i] <= hi + 1e-6

    extent = model_extent(model)
    top = 10.0
    for item in model.get("equipment", []):
        if inside(item["bbox"]):
            top = max(top, item["bbox"][5])
    for structure in model.get("structures", []):
        top = max(top, structure["height"])
    span = (extent[0], extent[2]) if j == 0 else (extent[1], extent[3])
    region = crop or (span[0], -2.0, span[1], top + 4)
    looking = "west" if axis == "x" else "north"
    name = title or f"Section {axis} = {at:g} m (depth {depth:g} m, looking {looking})"
    sheet = Sheet(region, name, _meta(meta))
    sheet.polyline(
        "grid", [(region[0], 0.0), (region[2], 0.0)], stroke="#000", width=0.5, id="grade"
    )
    for steel in model.get("support_steel", []):
        for part in steel.get("parts", []):
            if part["kind"] != "member":
                continue
            a, b = part["start"], part["end"]
            box = (min(a[0], b[0]), min(a[1], b[1]), 0, max(a[0], b[0]), max(a[1], b[1]), 0)
            if not inside(box):
                continue
            sheet.polyline(
                "structures",
                [(a[j], a[2]), (b[j], b[2])],
                stroke=COLOURS["steel"],
                width=max((part.get("profile") or (0.2, 0.2))[1] * sheet.k, 0.3),
                dashed=steel.get("source") == "generated",
            )
    for rack in model.get("racks", []):
        for part in rack.get("parts", []):
            a, b = part["start"], part["end"]
            box = (min(a[0], b[0]), min(a[1], b[1]), 0, max(a[0], b[0]), max(a[1], b[1]), 0)
            if not inside(box):
                continue
            sheet.polyline(
                "racks",
                [(a[j], a[2]), (b[j], b[2])],
                stroke=COLOURS["rack"],
                width=max((part.get("profile") or (0.3, 0.3))[1] * sheet.k, 0.3),
            )
        for level in rack["levels"]:
            pts = rack["points"]
            if any(lo - rack["width"] <= p[i] <= hi + rack["width"] for p in pts) or (
                min(p[i] for p in pts) <= at <= max(p[i] for p in pts)
            ):
                u = min(p[j] for p in pts) if len(pts) else 0
                sheet.text(
                    "labels",
                    u,
                    level + 0.3,
                    f"{rack['id']} +{level:.3f}",
                    size=1.8,
                    anchor="start",
                    colour=COLOURS["rack"],
                )
    for zone in model.get("zones", []):
        from chemeascode.domains.spatial.zones import volume_box

        colour = ZONE_COLOURS.get(zone["kind"], COLOURS["zone"])
        for k, volume in enumerate(zone["volumes"]):
            box = volume_box(volume)
            if not inside(box):
                continue
            sheet.polygon(
                "zones",
                [(box[j], box[2]), (box[j + 3], box[2]), (box[j + 3], box[5]), (box[j], box[5])],
                fill=f"url(#hatch-{zone['kind']})",
                stroke=colour,
                width=0.2,
                id=f"zone-{zone['id']}-{k}",
            )
    for area in model.get("areas", []):
        for part in area.get("parts", []):  # a bund's walls
            _part_section(sheet, part, inside, i, j, "#757575")
    for structure in model.get("structures", []):
        for part in [*structure["parts"], *structure.get("walls", [])]:
            _part_section(sheet, part, inside, i, j, COLOURS["steel"])
        for stair in structure.get("stairs", []):
            for part in stair["parts"]:
                _part_section(sheet, part, inside, i, j, COLOURS["steel"])
        for level in structure["levels"]:
            x0, y0, x1, y1 = structure["footprint"]
            box = (x0, y0, 0, x1, y1, 0)
            if inside(box):
                sheet.text(
                    "labels",
                    (x0, y0)[j] - 0.5,
                    level["elevation"] + 0.2,
                    f"{level['id']} +{level['elevation']:.3f}",
                    size=1.8,
                    anchor="end",
                    colour=COLOURS["steel"],
                )
    for item in model.get("equipment", []):
        if not inside(item["bbox"]):
            continue
        group = sheet.sub(sheet.layers["equipment"], "g", id=f"equipment-{item['tag']}")
        keep = sheet.layers["equipment"]
        sheet.layers["equipment"] = group
        for part in item["parts"]:
            _part_section(sheet, part, inside, i, j, COLOURS["equipment"], layer="equipment")
        sheet.layers["equipment"] = keep
        box = item["bbox"]
        sheet.text(
            "labels",
            (box[j] + box[j + 3]) / 2,
            box[5] + 0.6,
            item["tag"],
            size=2.2,
            colour=COLOURS["equipment"],
            **{"font-weight": "bold"},
        )
    for platform in model.get("platforms", []):
        for part in platform["parts"]:
            _part_section(sheet, part, inside, i, j, COLOURS["platform"], layer="platforms")
    for step in model.get("step_overs", []):
        for part in step["parts"]:
            _part_section(sheet, part, inside, i, j, COLOURS["platform"], layer="platforms")
    for structure in model.get("structures", []):
        for ladder in structure.get("ladders", []):
            for part in ladder["parts"]:
                _part_section(sheet, part, inside, i, j, COLOURS["steel"])
    for rack in model.get("racks", []):
        for ladder in rack.get("ladders", []):
            for part in ladder["parts"]:
                _part_section(sheet, part, inside, i, j, COLOURS["rack"], layer="racks")
    for tier in model.get("tray_tiers") or []:
        for part in tier["parts"]:
            _part_section(sheet, part, inside, i, j, COLOURS["rack"], layer="racks")
    for pipe in model.get("pipes", []):
        _pipe_section(sheet, pipe, lo, hi, at, i, j)
    for tray in model.get("trays") or []:
        _tray_section(sheet, tray, lo, hi, at, i, j)
    for unit in model.get("hvac_units") or []:
        for part in unit["parts"]:
            _part_section(sheet, part, inside, i, j, COLOURS["ahu"], layer="ducts")
    for duct in model.get("ducts") or []:
        _duct_section(sheet, duct, lo, hi, at, i, j)
    return sheet.finish(north=False)


def _duct_section(
    sheet: Sheet, duct: dict[str, Any], lo: float, hi: float, at: float, i: int, j: int
) -> None:
    """A duct in a section: a rectangle (width x height about its centreline) with its cross
    where it crosses the cut, a rectangle where it runs away from the cut in the slab (seen end
    on), a band where it runs along it."""
    colour = COLOURS[f"duct_{duct['system']}"]
    w, h = duct["width"], duct["height"]
    group = sheet.sub(
        sheet.layers["ducts"], "g", id=f"duct-{duct['id']}", **{"data-system": duct["system"]}
    )
    keep = sheet.layers["ducts"]
    sheet.layers["ducts"] = group
    points = duct["points"]
    for a, b in zip(points, points[1:], strict=False):
        if max(a[i], b[i]) < lo or min(a[i], b[i]) > hi or math.dist(a, b) < 1e-9:
            continue
        if abs(b[i] - a[i]) > 1e-6 and min(a[i], b[i]) <= at <= max(a[i], b[i]):
            t = (at - a[i]) / (b[i] - a[i])
            u = a[j] + (b[j] - a[j]) * t
            z = a[2] + (b[2] - a[2]) * t
            sheet.polygon(
                "ducts",
                [(u - w / 2, z - h / 2), (u + w / 2, z - h / 2), (u + w / 2, z + h / 2)]
                + [(u - w / 2, z + h / 2)],
                stroke=colour,
                width=0.25,
            )
            for v0, v1 in ((z - h / 2, z + h / 2), (z + h / 2, z - h / 2)):  # the duct's cross
                sheet.polyline("ducts", [(u - w / 2, v0), (u + w / 2, v1)], colour, 0.12)
            continue
        a, b = _in_slab(a, b, lo, hi, i)
        if math.hypot(b[j] - a[j], b[2] - a[2]) <= 1e-6:  # square to the cut: seen end on
            u, z = a[j], a[2]
            sheet.polygon(
                "ducts",
                [(u - w / 2, z - h / 2), (u + w / 2, z - h / 2), (u + w / 2, z + h / 2)]
                + [(u - w / 2, z + h / 2)],
                stroke=colour,
                width=0.2,
            )
        else:
            if abs(a[2] - b[2]) > 1e-6 and abs(a[j] - b[j]) <= 1e-6:  # a riser
                u0, u1 = a[j] - w / 2, a[j] + w / 2
                z0, z1 = min(a[2], b[2]), max(a[2], b[2])
            else:
                u0, u1 = min(a[j], b[j]), max(a[j], b[j])
                z0, z1 = min(a[2], b[2]) - h / 2, max(a[2], b[2]) + h / 2
            sheet.polygon(
                "ducts", [(u0, z0), (u1, z0), (u1, z1), (u0, z1)], stroke=colour, width=0.2
            )
    sheet.layers["ducts"] = keep
    if len(group) == 0:
        keep.remove(group)


def _tray_section(
    sheet: Sheet, tray: dict[str, Any], lo: float, hi: float, at: float, i: int, j: int
) -> None:
    """A cable tray in a section: a rectangle (width x depth) where it crosses the cut or runs
    away from it in the slab (seen end on), a band where it runs along it."""
    colour = COLOURS[f"tray_{tray['system']}"]
    w, d = tray["width"], tray["depth"]
    group = sheet.sub(
        sheet.layers["trays"], "g", id=f"tray-{tray['id']}", **{"data-system": tray["system"]}
    )
    keep = sheet.layers["trays"]
    sheet.layers["trays"] = group
    points = tray["points"]
    for a, b in zip(points, points[1:], strict=False):
        if max(a[i], b[i]) < lo or min(a[i], b[i]) > hi or math.dist(a, b) < 1e-9:
            continue
        if abs(b[i] - a[i]) > 1e-6 and min(a[i], b[i]) <= at <= max(a[i], b[i]):
            t = (at - a[i]) / (b[i] - a[i])
            u = a[j] + (b[j] - a[j]) * t
            z = a[2] + (b[2] - a[2]) * t
            sheet.polygon(
                "trays",
                [(u - w / 2, z), (u + w / 2, z), (u + w / 2, z + d), (u - w / 2, z + d)],
                stroke=colour,
                width=0.25,
            )
            continue
        a, b = _in_slab(a, b, lo, hi, i)
        if math.hypot(b[j] - a[j], b[2] - a[2]) <= 1e-6:  # square to the cut: seen end on
            u, z = a[j], a[2]
            sheet.polygon(
                "trays",
                [(u - w / 2, z), (u + w / 2, z), (u + w / 2, z + d), (u - w / 2, z + d)],
                stroke=colour,
                width=0.2,
            )
        else:
            if abs(a[2] - b[2]) > 1e-6 and abs(a[j] - b[j]) <= 1e-6:  # a riser: as wide as the tray
                u0, u1 = a[j] - w / 2, a[j] + w / 2
                z0, z1 = min(a[2], b[2]), max(a[2], b[2])
            else:
                u0, u1 = min(a[j], b[j]), max(a[j], b[j])
                z0, z1 = min(a[2], b[2]), max(a[2], b[2]) + d
            sheet.polygon(
                "trays", [(u0, z0), (u1, z0), (u1, z1), (u0, z1)], stroke=colour, width=0.2
            )
    sheet.layers["trays"] = keep
    if len(group) == 0:
        keep.remove(group)


def _in_slab(a, b, lo: float, hi: float, i: int) -> tuple[list[float], list[float]]:
    """The piece of segment *ab* whose coordinate *i* lies in ``[lo, hi]`` (it reaches in)."""
    if abs(b[i] - a[i]) <= 1e-9:
        return a, b
    t0, t1 = sorted(((lo - a[i]) / (b[i] - a[i]), (hi - a[i]) / (b[i] - a[i])))
    t0, t1 = max(t0, 0.0), min(t1, 1.0)
    return (
        [a[k] + (b[k] - a[k]) * t0 for k in range(3)],
        [a[k] + (b[k] - a[k]) * t1 for k in range(3)],
    )


def _part_section(
    sheet: Sheet,
    part: dict[str, Any],
    inside,
    i: int,
    j: int,
    colour: str,
    layer: str = "structures",
) -> None:
    from chemeascode.domains.spatial.geometry3d import part_solid

    solid = part_solid(part)
    if solid is None:
        return
    box = solid.aabb
    if not inside(box):
        return
    if part["kind"] == "member":
        a, b = part["start"], part["end"]
        w = (part.get("profile") or (0.1, 0.1))[1]
        sheet.polyline(
            layer, [(a[j], a[2]), (b[j], b[2])], stroke=colour, width=max(w * sheet.k, 0.2)
        )
        return
    if part["kind"] in ("cylinder", "cone") and part.get("material") != "cage":
        a, b = part["start"], part["end"]
        r = max(part["radius"], part.get("radius_end") or 0.0)
        if abs(a[i] - b[i]) > 1e-6 and abs(a[j] - b[j]) < 1e-6 and abs(a[2] - b[2]) < 1e-6:
            sheet.circle(layer, a[j], a[2], r, stroke=colour, width=0.3)  # axis across the cut
            return
    sheet.polygon(
        layer,
        [(box[j], box[2]), (box[j + 3], box[2]), (box[j + 3], box[5]), (box[j], box[5])],
        stroke=colour,
        width=0.25,
    )


def _pipe_section(
    sheet: Sheet, pipe: dict[str, Any], lo: float, hi: float, at: float, i: int, j: int
) -> None:
    r = pipe["od"] / 2
    ins = pipe.get("insulation_mm", 0.0) / 1000
    colour = (pipe.get("class") or {}).get("colour") or COLOURS["pipe"]
    points = pipe["points"]
    group = sheet.sub(
        sheet.layers["pipes"], "g", id=f"pipe-{pipe['id']}", **{"data-line": pipe["line"]}
    )
    keep = sheet.layers["pipes"]
    sheet.layers["pipes"] = group
    drawn = False
    for a, b in zip(points, points[1:], strict=False):
        if max(a[i], b[i]) < lo or min(a[i], b[i]) > hi or math.dist(a, b) < 1e-9:
            continue
        if abs(b[i] - a[i]) > 1e-6 and min(a[i], b[i]) <= at <= max(a[i], b[i]):
            t = (at - a[i]) / (b[i] - a[i])
            u = a[j] + (b[j] - a[j]) * t
            z = a[2] + (b[2] - a[2]) * t
            if ins > 0:
                sheet.circle(
                    "pipes", u, z, r + ins, fill=COLOURS["insulation"], stroke="none", width=0
                )
            sheet.circle("pipes", u, z, r, fill="#fff", stroke=colour, width=0.3)
            if not drawn:
                sheet.text("labels", u, z + r + ins + 0.25, pipe["line"], size=1.4, colour=colour)
            drawn = True
            continue
        a, b = _in_slab(a, b, lo, hi, i)
        if math.hypot(b[j] - a[j], b[2] - a[2]) <= 1e-6:  # square to the cut: seen end on
            sheet.circle("pipes", a[j], a[2], r + ins, stroke=colour, width=0.25)
        else:
            sheet.polyline(
                "pipes", [(a[j], a[2]), (b[j], b[2])], stroke=colour, width=2 * (r + ins) * sheet.k
            )
    sheet.layers["pipes"] = keep
    if len(group) == 0:
        keep.remove(group)


def plant_meta(workspace: Any) -> dict[str, str]:
    """Title block values from ``plant.yaml`` (name, project number, client, site, revision)."""
    try:
        config = workspace.config()
    except Exception:  # noqa: BLE001 - a broken plant.yaml: an empty title block
        return {}
    project = config.project
    meta = {"plant": config.name}
    if project is not None:
        meta.update(
            project=" ".join(v for v in (project.number, project.name) if v),
            client=project.client,
            site=project.site,
            revision=project.revision,
        )
    return meta


def svg_to_png(svg: str, scale: float = 4.0) -> bytes:
    """The drawing as PNG (the ``png`` extra: resvg), *scale* pixels per sheet mm."""
    from chemeascode.domains.piping.render import svg_to_png as rasterise

    return rasterise(svg, scale)
