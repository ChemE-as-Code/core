"""Recognisable equipment: the machine families and the level-2 detail of the others.

Pure geometry, used by :func:`chemeascode.domains.spatial.shapes.body`; every part is in the
item's own frame (x the shaft or axis, y across, z up from the item's bottom) and the module
text of :mod:`~chemeascode.domains.spatial.shapes` says what each part kind means.

Each machine has an **envelope** (``lod`` 1: a few cylinders and boxes the clash checks and
the router use, drawn from afar), **detail** (``lod`` 2: drawn close up only) and parts shared
by both (``lod`` None: plinth, baseplate, coupling guard, terminal box). The detail stays
within the envelope, and both stay within the item's overall sizes (the bounding box never
depends on the detail). Its nozzles go on the real flanges (:attr:`Body.flanges`), sized by the
nozzle's DN once it is known (:func:`fit_flange`).

- **End-suction centrifugal pump** (``end_suction``): a volute (a torus across the shaft with
  its cover) with an axial suction nozzle and flange at the front (-x) and a tangential
  discharge nozzle with its flange on top; casing foot, seal chamber, bearing housing and its
  foot; shaft and coupling under a guard; a motor with end shield, cooling ribs, fan cowl and
  grille, terminal box and feet; a baseplate with a drip rim on a concrete plinth (at grade).
  ``cryogenic``: the same pump with a longer distance piece and an insulated cold end around
  the casing. ``vertical_inline``: suction and discharge on one horizontal axis (own x), the
  casing under a motor stool and a vertical motor.
- **Blower**: an end-suction machine with a large volute, an inlet bell and a rectangular
  outlet.
- **Integrally geared compressor**: a gearbox with stage volutes on its front (and, with four
  stages, its back) face, each with an axial inlet (the back stages through an elbow up) and a
  tangential outlet up; intercooler shells; a motor (with a top-mounted cooler when there is
  room) behind a coupling guard; a lube oil console beside the motor.
- **Compander** (``expander``: with a brake instead of the booster): an expander and a booster
  volute either side of a bearing housing, with an oil console.
- **Vessels and columns**: base ring and anchor chairs on a skirt, the skirt's access opening,
  base plates under legs, lifting lugs, stiffening rings every 3 m on a column (and on a vessel
  taller than 8 m), manways with davits and a davit on a column's top head (:func:`manways`;
  the top davit is a solid, on the side free of nozzles with its arm stowed);
  horizontal drums: saddle base plates, lifting lugs, a manway on the front head.
- **Shell-and-tube exchangers**: body flanges at the bonnet, the channel and the rear head.
- **Plate exchangers**: tie bolts, a carrying bar and a guide bar.
- **Air coolers**: header boxes, a plenum per fan, fan rings, hubs, blades and motors.
- **Tanks**: ring wall, anchor chairs, a spiral stair with treads, stringers, a handrail and a
  mid rail (a caged ladder on a small tank), a roof handrail ring with mid rail, toe plate and
  posts, and a roof platform at the stair head. The stair stands outside the item's box, so
  its treads, landing, stringers and handrail (and a ladder's rails and cage) are solids
  (``lod`` None), as a structure's stair; its posts and mid rail are detail.
- **Foundations** at grade: a pedestal under a skirt, pads under legs and saddles, a slab
  under a box item (detail; the items stand on them).

:func:`nozzle_flange` gives a nozzle's neck and flange, :func:`transmitter` an instrument on its
stand, both in the site frame.
"""

from __future__ import annotations

import math
from typing import TYPE_CHECKING

from chemeascode.domains.spatial.shapes import Part, Vec, _box, _cap, _clamp, _cyl

if TYPE_CHECKING:
    from chemeascode.domains.spatial.shapes import Body

#: Height of a concrete foundation above grade under a non-machine item, m (ASSUMED).
FOUNDATION = 0.2
#: Stiffening ring pitch on a column, m.
RING_PITCH = 3.0
#: Spiral stair of a tank: clear width, gap to the shell, pitch (degrees), riser, m.
TANK_STAIR = (0.8, 0.12, 40.0, 0.2)
HANDRAIL = 1.1
MIDRAIL = 0.55
#: A column's top-head davit: the post's and the arm's height above the head's top, m.
DAVIT = (1.8, 1.75)


# ---------------------------------------------------------------------------
# Primitives
# ---------------------------------------------------------------------------


def _torus(
    pid: str,
    c: Vec,
    axis: Vec,
    radius: float,
    tube: float,
    material: str,
    lod: int | None = 2,
    ref: Vec | None = None,
    arc: tuple[float, float] | None = None,
) -> Part:
    return Part(
        pid,
        "torus",
        material,
        centre=c,
        axis=axis,
        radius=radius,
        tube=tube,
        ref=ref,
        arc_deg=arc,
        lod=lod,
    )


def _cone(pid: str, a: Vec, b: Vec, r0: float, r1: float, material: str, lod: int | None = 2):
    return Part(pid, "cone", material, start=a, end=b, radius=r0, radius_end=r1, lod=lod)


def _frustum(
    pid: str,
    c: Vec,
    size: Vec,
    top: tuple[float, float],
    material: str,
    lod: int | None = 2,
    rotation: float = 0.0,
) -> Part:
    return Part(
        pid, "frustum", material, centre=c, size=size, size_end=top, rotation_deg=rotation, lod=lod
    )


def _annulus(
    pid: str,
    c: Vec,
    inner: float,
    outer: float,
    depth: float,
    material: str,
    lod: int | None = 2,
    arc: tuple[float, float] | None = None,
) -> Part:
    return Part(
        pid,
        "annulus",
        material,
        centre=c,
        radius=inner,
        radius_end=outer,
        depth=depth,
        arc_deg=arc,
        lod=lod,
    )


def _at(a: Vec, d: Vec, t: float) -> Vec:
    return (a[0] + d[0] * t, a[1] + d[1] * t, a[2] + d[2] * t)


def _polar(radius: float, angle_deg: float, z: float) -> Vec:
    a = math.radians(angle_deg)
    return (radius * math.cos(a), radius * math.sin(a), z)


def _flanged(
    pid: str,
    face: Vec,
    direction: Vec,
    bore: float,
    flange: float,
    length: float,
    material: str = "casing",
    lod: int | None = 2,
) -> list[Part]:
    """A nozzle ending in a flange whose face is at *face*, pointing along *direction*:
    a neck of radius *bore* reaching *length* back from the face, then the flange."""
    thick = _clamp(0.12 * flange, 0.015, 0.06)
    back = _at(face, direction, -length)
    seat = _at(face, direction, -thick)
    return [
        _cyl(f"{pid}-nozzle", back, seat, bore, material, lod),
        _cyl(f"{pid}-flange", seat, face, flange, "flange", lod),
    ]


# ---------------------------------------------------------------------------
# Machines
# ---------------------------------------------------------------------------


def machine(item: Body) -> None:
    """The parts, flanges and envelopes of a pump, compressor or turbine by its variant."""
    variant = item.variant or "end_suction"
    if variant == "vertical_inline":
        _vertical_inline(item)
    elif variant == "integrally_geared":
        _geared(item)
    elif variant in ("compander", "expander"):
        _compander(item, variant == "expander")
    else:
        _end_suction(item, cold=variant == "cryogenic", blower=variant == "blower")
    d = item.dims
    L, W, H = d.length or 0.0, d.width or 0.0, d.height or 0.0
    if item.family == "pump":
        from chemeascode.domains.spatial.shapes import PUMP_ACCESS

        item.local_envelopes.append(
            ("access", (0.0, 0.0, H / 2), (L + 2 * PUMP_ACCESS, W + 2 * PUMP_ACCESS, H))
        )
    item.shell_bottom, item.shell_top = 0.0, H


def _base(item: Body, parts: list[Part], large: bool = False) -> float:
    """A concrete plinth at grade (inside the envelope) and a steel baseplate with a drip rim;
    the height of the baseplate's top."""
    d = item.dims
    L, W, H = d.length or 0.0, d.width or 0.0, d.height or 0.0
    if item.grade:
        plinth = _clamp(0.08 * H, 0.15, 0.5) if large else _clamp(0.15 * H, 0.1, 0.3)
    else:
        plinth = 0.0
    plate = _clamp(0.05 * H, 0.05, 0.15)
    if plinth > 0:
        parts.append(_box("plinth", (0.0, 0.0, plinth / 2), (L, W, plinth), "concrete"))
        pl, pw = 0.94 * L, 0.88 * W
    else:
        pl, pw = L, W
    parts.append(_box("baseplate", (0.0, 0.0, plinth + plate / 2), (pl, pw, plate), "steel"))
    top = plinth + plate
    rim, t = 0.04, 0.02
    z = top + rim / 2
    for k, (c, size) in enumerate(
        (
            ((0.0, -pw / 2 + t / 2, z), (pl, t, rim)),
            ((0.0, pw / 2 - t / 2, z), (pl, t, rim)),
            ((-pl / 2 + t / 2, 0.0, z), (t, pw - 2 * t, rim)),
            ((pl / 2 - t / 2, 0.0, z), (t, pw - 2 * t, rim)),
        ),
        1,
    ):
        parts.append(_box(f"drip-rim-{k}", c, size, "steel", lod=2))
    return top


def _motor(
    parts: list[Part],
    x0: float,
    x1: float,
    za: float,
    rm: float,
    base: float,
    top: float,
    half_width: float,
    cooler: bool = False,
) -> float:
    """A horizontal motor along x from *x0* (drive end) to *x1* (fan end) on axis height *za*:
    envelope, frame, end shield, ribs, fan cowl and grille, feet and terminal box (on top when
    it fits below *top*, else on the +y side); a top-mounted cooler when *cooler* and there is
    room. Returns the length of the motor."""
    ml = x1 - x0
    cowl = 0.2 * ml
    parts.append(_cyl("motor", (x0, 0.0, za), (x1, 0.0, za), 1.04 * rm, "motor", lod=1))
    parts.append(_cyl("motor-frame", (x0, 0.0, za), (x1 - cowl, 0.0, za), rm, "motor", lod=2))
    parts.append(
        _cap("motor-end-shield", (x0, 0.0, za), (-1.0, 0.0, 0.0), 0.85 * rm, 0.1 * rm, "motor", 2)
    )
    grille = min(0.02, 0.05 * cowl)
    parts.append(
        _cyl("fan-cowl", (x1 - cowl, 0.0, za), (x1 - grille, 0.0, za), 1.04 * rm, "motor", lod=2)
    )
    parts.append(
        _cap("fan-grille", (x1 - grille, 0.0, za), (1.0, 0.0, 0.0), 0.9 * rm, grille, "fan", 2)
    )
    k = 0
    for step in range(12):
        a = math.radians(15 + 30 * step)
        if math.sin(a) < -0.45:
            continue  # the feet are there
        k += 1
        y, z = rm * math.cos(a), za + rm * math.sin(a)
        parts.append(
            _cyl(f"rib-{k}", (x0 + 0.04 * ml, y, z), (x1 - cowl, y, z), 0.07 * rm, "motor", 2)
        )
    foot = za - 0.7 * rm - base
    if foot > 0.01:
        for n, x in enumerate((x0 + 0.18 * ml, x1 - cowl - 0.12 * ml), 1):
            parts.append(
                _box(
                    f"motor-foot-{n}",
                    (x, 0.0, base + foot / 2),
                    (0.1 * ml, 1.5 * rm, foot),
                    "motor",
                    lod=2,
                )
            )
    box = (0.32 * ml if ml < 4 * rm else 1.2 * rm, 0.55 * rm, 0.32 * rm)
    with_cooler = cooler and za + 1.5 * rm <= top + 1e-9
    if with_cooler:
        parts.append(
            _box(
                "motor-cooler",
                ((x0 + x1 - cowl) / 2, 0.0, za + 0.9 * rm + 0.25 * rm),
                (0.6 * (ml - cowl), 1.5 * rm, 0.5 * rm),
                "motor",
                lod=2,
            )
        )
    if not with_cooler and za + rm + box[2] <= top + 1e-9:
        centre = (x0 + 0.35 * ml, 0.0, za + rm + box[2] / 2 - 0.02 * rm)
        parts.append(_box("terminal-box", centre, box, "motor"))
    elif rm + box[2] <= half_width + 1e-9:
        centre = (x0 + 0.35 * ml, rm + box[2] / 2 - 0.02 * rm, za)
        parts.append(_box("terminal-box", centre, (box[0], box[2], box[1]), "motor"))
    return ml


def _end_suction(item: Body, cold: bool = False, blower: bool = False) -> None:
    d = item.dims
    L, W, H = d.length or 0.0, d.width or 0.0, d.height or 0.0
    parts: list[Part] = []
    base = _base(item, parts)
    room = max(H - base, 0.1)
    if blower:
        neck = max(0.1, 0.08 * room)
        rv = min((room - 0.05 - neck) / 2, 0.45 * W, 0.3 * L)
    else:
        neck = max(0.12, 0.15 * room)
        rv = min((room - 0.05 - neck) / 2, 0.45 * W, 0.2 * L)
    rv = max(rv, 0.05)
    za = base + 0.05 + rv
    t = (0.55 if blower else 0.7) * rv  # the volute's width along the shaft
    ns = _clamp(0.6 * rv, 0.1, 0.4)  # the suction nozzle's length
    xf = -L / 2
    xv = xf + ns + t / 2
    rest = max(L / 2 - 0.02 - (xv + t / 2), 0.1)
    lb = (0.35 if cold else 0.18 if blower else 0.25) * rest
    lc = 0.12 * rest
    xb = xv + t / 2 + lb
    xm0, xm1 = xb + lc, L / 2 - 0.02
    rm = max(0.05, min(0.42 * W, za - base - 0.03, (H - za) / 1.45, 0.95 * rv))
    yd = -0.5 * rv
    # the envelope
    parts.append(_cyl("casing", (xf, 0.0, za), (xb, 0.0, za), rv, "casing", lod=1))
    # the volute and its nozzles
    rsb, rsf = (0.5 * rv, 0.62 * rv) if blower else (0.33 * rv, 0.55 * rv)
    tf = _clamp(0.08 * rv, 0.02, 0.06)
    parts.append(_cyl("suction-flange", (xf, 0.0, za), (xf + tf, 0.0, za), rsf, "flange", 2))
    eye = 0.42 * rv
    parts.append(
        _cone("suction-nozzle", (xf + tf, 0.0, za), (xv - t / 2, 0.0, za), rsb, eye, "casing")
    )
    parts.append(
        _cyl("volute-cover", (xv - t / 2, 0.0, za), (xv + t / 2, 0.0, za), 0.8 * rv, "casing", 2)
    )
    parts.append(_torus("volute", (xv, 0.0, za), (1.0, 0.0, 0.0), 0.62 * rv, 0.38 * rv, "casing"))
    if blower:
        parts.append(
            _box(
                "discharge",
                (xv, yd, (za + H) / 2),
                (0.85 * t, 0.9 * rv, H - za),
                "casing",
                lod=1,
            )
        )
        parts.append(
            _box(
                "discharge-duct",
                (xv, yd, (za + H - tf) / 2),
                (0.8 * t, 0.85 * rv, H - tf - za),
                "casing",
                lod=2,
            )
        )
        parts.append(
            _box("discharge-flange", (xv, yd, H - tf / 2), (0.85 * t, 0.9 * rv, tf), "flange", 2)
        )
    else:
        rdb, rdf = 0.26 * rv, 0.45 * rv
        parts.append(_cyl("discharge", (xv, yd, za), (xv, yd, H), rdf, "casing", lod=1))
        parts += _flanged("discharge", (xv, yd, H), (0.0, 0.0, 1.0), rdb, rdf, H - za)
    foot = za - 0.75 * rv - base
    if foot > 0.01:
        parts.append(
            _box(
                "casing-foot",
                (xv, 0.0, base + foot / 2),
                (0.5 * t, 1.1 * rv, foot),
                "casing",
                lod=2,
            )
        )
    x_seal = xv + t / 2 + 0.25 * lb
    parts.append(
        _cyl("seal-chamber", (xv + t / 2, 0.0, za), (x_seal, 0.0, za), 0.5 * rv, "casing", 2)
    )
    parts.append(_cyl("bearing-housing", (x_seal, 0.0, za), (xb, 0.0, za), 0.36 * rv, "casing", 2))
    bfoot = za - 0.3 * rv - base
    if bfoot > 0.01:
        parts.append(
            _box(
                "bearing-foot",
                (x_seal + 0.6 * (xb - x_seal), 0.0, base + bfoot / 2),
                (0.3 * (xb - x_seal), 0.9 * rv, bfoot),
                "casing",
                lod=2,
            )
        )
    if cold:
        top = min(H - 0.4 * neck, za + 1.12 * rv)
        x1 = xv + t / 2 + 0.3 * lb
        parts.append(
            _box(
                "cold-end",
                ((xf + tf + 0.02 + x1) / 2, 0.0, (base + 0.02 + top) / 2),
                (x1 - xf - tf - 0.02, min(2.24 * rv, W), top - base - 0.02),
                "insulation",
            )
        )
    # shaft, coupling and guard
    parts.append(_cyl("shaft", (xb, 0.0, za), (xm0, 0.0, za), max(0.015, 0.1 * rm), "steel", 2))
    parts.append(
        _cyl(
            "coupling",
            (xb + 0.3 * lc, 0.0, za),
            (xm0 - 0.3 * lc, 0.0, za),
            max(0.03, 0.3 * rm),
            "steel",
            2,
        )
    )
    guard = min(max(0.45 * rm, 0.4 * rv), za - base)
    parts.append(
        _box("coupling-guard", ((xb + xm0) / 2, 0.0, za), (lc, 2 * guard, 2 * guard), "guard")
    )
    ml = _motor(parts, xm0, xm1, za, rm, base, H, W / 2)
    item.local_parts = parts
    item.casing = (za, xf, xb, rv)
    item.flanges = {
        "suction": ((xf, 0.0, za), (-1.0, 0.0, 0.0)),
        "discharge": ((xv, yd, H), (0.0, 0.0, 1.0)),
        "drain": ((xv, 0.5 * rv, za - 0.87 * rv), (0.0, 0.0, -1.0)),
    }
    item.local_envelopes.append(("motor_removal", (L / 2 + ml / 2, 0.0, za), (ml, 2 * rm, 2 * rm)))


def _vertical_inline(item: Body) -> None:
    d = item.dims
    L, W, H = d.length or 0.0, d.width or 0.0, d.height or 0.0
    parts: list[Part] = []
    base = _base(item, parts)
    room = max(H - base, 0.1)
    rc = max(0.05, min(0.3 * L, 0.42 * W, 0.2 * room))
    hc = max(2.2 * rc, 0.25 * room)
    zn = base + 0.45 * hc
    rb, rf = 0.42 * rc, 0.62 * rc
    parts.append(_cyl("casing", (0.0, 0.0, base), (0.0, 0.0, base + hc), rc, "casing", lod=1))
    parts.append(_cyl("nozzles", (-L / 2, 0.0, zn), (L / 2, 0.0, zn), rf, "casing", lod=1))
    parts.append(
        _cyl("casing-body", (0.0, 0.0, base), (0.0, 0.0, base + hc), 0.85 * rc, "casing", 2)
    )
    parts.append(
        _torus(
            "volute", (0.0, 0.0, base + 0.55 * hc), (0.0, 0.0, 1.0), 0.6 * rc, 0.4 * rc, "casing"
        )
    )
    parts.append(
        _cyl(
            "casing-cover",
            (0.0, 0.0, base + hc - 0.08 * hc),
            (0.0, 0.0, base + hc),
            rc,
            "flange",
            2,
        )
    )
    parts += _flanged("suction", (-L / 2, 0.0, zn), (-1.0, 0.0, 0.0), rb, rf, L / 2)
    parts += _flanged("discharge", (L / 2, 0.0, zn), (1.0, 0.0, 0.0), rb, rf, L / 2)
    zs = base + hc + 0.12 * room
    parts.append(_cyl("stool", (0.0, 0.0, base + hc), (0.0, 0.0, zs), 0.55 * rc, "casing", None))
    rm = max(0.05, min(0.38 * W, 0.4 * L, 0.5 * (H - zs)))
    ml = H - zs
    cowl = 0.2 * ml
    parts.append(_cyl("motor", (0.0, 0.0, zs), (0.0, 0.0, H), 1.04 * rm, "motor", lod=1))
    parts.append(_cyl("motor-frame", (0.0, 0.0, zs), (0.0, 0.0, H - cowl), rm, "motor", 2))
    parts.append(
        _cyl("fan-cowl", (0.0, 0.0, H - cowl), (0.0, 0.0, H - 0.02), 1.04 * rm, "motor", 2)
    )
    parts.append(
        _cap("fan-grille", (0.0, 0.0, H - 0.02), (0.0, 0.0, 1.0), 0.9 * rm, 0.02, "fan", 2)
    )
    for k in range(12):
        x, y, _ = _polar(rm, 15 + 30 * k, 0.0)
        parts.append(
            _cyl(f"rib-{k + 1}", (x, y, zs + 0.05 * ml), (x, y, H - cowl), 0.07 * rm, "motor", 2)
        )
    if rm * 1.32 <= W / 2 + 1e-9:
        parts.append(
            _box(
                "terminal-box",
                (0.0, rm + 0.15 * rm, zs + 0.4 * ml),
                (0.5 * rm, 0.3 * rm, 0.5 * rm),
                "motor",
            )
        )
    item.local_parts = parts
    item.casing = (base + hc - rc, -0.5 * rc, 0.5 * rc, rc)
    item.flanges = {
        "suction": ((-L / 2, 0.0, zn), (-1.0, 0.0, 0.0)),
        "discharge": ((L / 2, 0.0, zn), (1.0, 0.0, 0.0)),
        "drain": ((0.0, 0.6 * rc, base + 0.05), (0.0, 0.0, -1.0)),
    }
    item.local_envelopes.append(("motor_removal", (0.0, 0.0, H + ml / 2), (2 * rm, 2 * rm, ml)))


def _stage(
    parts: list[Part],
    k: int,
    xv: float,
    y: float,
    z: float,
    rs: float,
    out: float,
    top: float,
    inlet_to: float | None,
    flanges: dict[str, tuple[Vec, Vec]],
) -> None:
    """Stage *k* (1-based): a volute in the plane x = *xv* on (y, z), its axial inlet facing
    *out* (-1 front, +1 back) and its tangential outlet up to *top*. A front inlet runs to
    x = *inlet_to*; a back one turns up through an elbow."""
    t = 0.6 * rs
    parts.append(
        _torus(f"stage-{k}-volute", (xv, y, z), (1.0, 0.0, 0.0), 0.62 * rs, 0.38 * rs, "casing")
    )
    parts.append(
        _cyl(f"stage-{k}-cover", (xv - t / 2, y, z), (xv + t / 2, y, z), 0.78 * rs, "casing", 2)
    )
    rb, rf = 0.38 * rs, 0.55 * rs
    face = xv + out * t / 2
    if out < 0:
        end = inlet_to if inlet_to is not None else face - 0.6 * rs
        parts += _flanged(f"stage-{k}-inlet", (end, y, z), (-1.0, 0.0, 0.0), rb, rf, face - end)
        flanges[f"inlet-{k}"] = ((end, y, z), (-1.0, 0.0, 0.0))
    else:
        stub = face + 0.25 * rs
        bend = 0.55 * rs
        parts.append(_cyl(f"stage-{k}-inlet-stub", (face, y, z), (stub, y, z), rb, "casing", 2))
        parts.append(
            _torus(
                f"stage-{k}-inlet-elbow",
                (stub, y, z + bend),
                (0.0, -1.0, 0.0),
                bend,
                rb,
                "casing",
                ref=(0.0, 0.0, -1.0),
                arc=(0.0, 90.0),
            )
        )
        high = min(top, z + bend + rf + 0.4 * rs)
        start = (stub + bend, y, z + bend)
        parts += _flanged(
            f"stage-{k}-inlet", (stub + bend, y, high), (0.0, 0.0, 1.0), rb, rf, high - start[2]
        )
        flanges[f"inlet-{k}"] = ((stub + bend, y, high), (0.0, 0.0, 1.0))
    yo = y - 0.5 * rs if y < 0 else y + 0.5 * rs
    parts += _flanged(
        f"stage-{k}-outlet", (xv, yo, top), (0.0, 0.0, 1.0), 0.25 * rs, 0.4 * rs, top - z
    )
    flanges[f"outlet-{k}"] = ((xv, yo, top), (0.0, 0.0, 1.0))


def _geared(item: Body) -> None:
    d = item.dims
    L, W, H = d.length or 0.0, d.width or 0.0, d.height or 0.0
    parts: list[Part] = []
    base = _base(item, parts, large=True)
    room = max(H - base, 0.2)
    rm = max(0.05, min(0.3 * W, 0.38 * room))
    zm = base + rm + 0.08 * room
    xm0, xm1 = 0.14 * L, L / 2 - 0.02
    gx0, gx1 = -0.2 * L, 0.07 * L
    gh = 0.62 * room
    parts.append(
        _box(
            "gearbox",
            ((gx0 + gx1) / 2, 0.0, base + gh / 2),
            (gx1 - gx0, 0.62 * W, gh),
            "casing",
            lod=2,
        )
    )
    parts.append(
        _box(
            "gearbox-split",
            ((gx0 + gx1) / 2, 0.0, base + 0.55 * gh),
            (gx1 - gx0 + 0.06, 0.62 * W + 0.06, 0.05),
            "flange",
            lod=2,
        )
    )
    parts.append(
        _box(
            "gearbox-cover",
            ((gx0 + gx1) / 2, 0.0, base + gh + 0.03),
            (0.4 * (gx1 - gx0), 0.3 * W, 0.06),
            "casing",
            lod=2,
        )
    )
    stages = 4 if L >= 6 else 2
    rs1 = max(0.05, min(0.2 * W, 0.24 * room, 0.1 * L))
    zp = min(base + 0.8 * gh, H - rs1 - 0.15 * room)
    flanges: dict[str, tuple[Vec, Vec]] = {}
    reach = 0.0
    back_end = gx1
    for k in range(stages):
        rs = rs1 * 0.85**k
        t = 0.6 * rs
        front = k < 2
        y = (-1 if k % 2 == 0 else 1) * (0.22 if front else 0.25) * W
        xv = gx0 - t / 2 - 0.02 if front else gx1 + t / 2 + 0.02
        _stage(
            parts,
            k + 1,
            xv,
            y,
            zp,
            rs,
            -1.0 if front else 1.0,
            H,
            -L / 2 if k == 0 else None,
            flanges,
        )
        reach = max(reach, abs(y) + rs)
        if not front:
            back_end = max(back_end, xv + t / 2 + 0.25 * rs + 1.6 * rs)
    parts.append(
        _box(
            "stages",
            ((-L / 2 + back_end) / 2, 0.0, (base + H) / 2),
            (back_end + L / 2, min(2 * reach, W), H - base),
            "casing",
            lod=1,
        )
    )
    rc = max(0.05, min(0.12 * W, 0.16 * room))
    for n, side in enumerate((-1, 1)[: stages - 1], 1):
        y = side * (0.5 * W - rc - 0.02)
        x0, x1 = -0.47 * L, -0.22 * L - 0.6 * rs1
        if x1 - x0 < 2.5 * rc:
            continue
        z = base + rc + 0.02
        parts.append(
            _cyl(f"intercooler-{n}", (x0 + 0.3 * rc, y, z), (x1 - 0.3 * rc, y, z), rc, "shell", 2)
        )
        parts.append(
            _cap(
                f"intercooler-{n}-head-front",
                (x0 + 0.3 * rc, y, z),
                (-1.0, 0.0, 0.0),
                rc,
                0.3 * rc,
                "shell",
                2,
            )
        )
        parts.append(
            _cap(
                f"intercooler-{n}-head-back",
                (x1 - 0.3 * rc, y, z),
                (1.0, 0.0, 0.0),
                rc,
                0.3 * rc,
                "shell",
                2,
            )
        )
    guard = min(0.5 * rm, zm - base)
    parts.append(
        _box(
            "coupling-guard", ((gx1 + xm0) / 2, 0.0, zm), (xm0 - gx1, 2 * guard, 2 * guard), "guard"
        )
    )
    ml = _motor(parts, xm0, xm1, zm, rm, base, H, W / 2, cooler=True)
    y0, y1 = rm + 0.05 * W, 0.49 * W
    if y1 - y0 > 0.1:
        cx0, cx1 = xm0 + 0.05 * L, xm0 + 0.25 * L
        ch = 0.3 * room
        yc = (y0 + y1) / 2
        parts.append(
            _box(
                "lube-oil-console",
                ((cx0 + cx1) / 2, -yc, base + ch / 2),
                (cx1 - cx0, y1 - y0, ch),
                "casing",
            )
        )
        for n, x in enumerate((cx0 + 0.2 * (cx1 - cx0), cx0 + 0.45 * (cx1 - cx0)), 1):
            parts.append(
                _cyl(
                    f"lube-oil-pump-{n}",
                    (x, -yc, base + ch),
                    (x, -yc, base + ch + 0.35 * ch),
                    0.18 * (y1 - y0),
                    "motor",
                    2,
                )
            )
        parts.append(
            _cyl(
                "lube-oil-filter",
                (cx0 + 0.78 * (cx1 - cx0), -yc, base + ch),
                (cx0 + 0.78 * (cx1 - cx0), -yc, base + ch + 0.5 * ch),
                0.15 * (y1 - y0),
                "shell",
                2,
            )
        )
    item.local_parts = parts
    item.casing = (zp, -L / 2, gx1, rs1)
    order = [f"inlet-{k + 1}" for k in range(stages)]
    order += [f"outlet-{stages}"] + [f"outlet-{k + 1}" for k in range(stages - 1)]
    item.flanges = {name: flanges[name] for name in order}
    item.local_envelopes.append(("motor_removal", (L / 2 + ml / 2, 0.0, zm), (ml, 2 * rm, 2 * rm)))


def _compander(item: Body, expander: bool) -> None:
    d = item.dims
    L, W, H = d.length or 0.0, d.width or 0.0, d.height or 0.0
    parts: list[Part] = []
    base = _base(item, parts, large=True)
    room = max(H - base, 0.2)
    rs = max(0.05, min(0.3 * W, 0.3 * room, 0.18 * L))
    za = max(base + rs + 0.05, base + 0.45 * room)
    za = min(za, H - rs - 0.1 * room)
    hx = 0.15 * L
    parts.append(
        _box(
            "bearing-housing",
            (0.0, 0.0, (base + za + 0.3 * rs) / 2),
            (2 * hx, 0.5 * W, za + 0.3 * rs - base),
            "casing",
            lod=2,
        )
    )
    t = 0.6 * rs
    xe = -hx - t / 2 - 0.02
    xb = hx + t / 2 + 0.02
    parts.append(_cyl("rotor", (-L / 2, 0.0, za), (L / 2, 0.0, za), rs, "casing", lod=1))
    parts.append(
        _torus("expander-volute", (xe, 0.0, za), (1.0, 0.0, 0.0), 0.62 * rs, 0.38 * rs, "casing")
    )
    parts.append(
        _cyl("expander-cover", (xe - t / 2, 0.0, za), (xe + t / 2, 0.0, za), 0.8 * rs, "casing", 2)
    )
    rb, rf = 0.35 * rs, 0.52 * rs
    face = xe - t / 2
    parts += _flanged("expander-outlet", (-L / 2, 0.0, za), (-1.0, 0.0, 0.0), rb, rf, face + L / 2)
    yi = 0.5 * rs
    parts.append(_cyl("expander-inlet-env", (xe, yi, za), (xe, yi, H), 0.42 * rs, "casing", lod=1))
    parts += _flanged("expander-inlet", (xe, yi, H), (0.0, 0.0, 1.0), 0.28 * rs, 0.42 * rs, H - za)
    flanges: dict[str, tuple[Vec, Vec]] = {"inlet-1": ((xe, yi, H), (0.0, 0.0, 1.0))}
    outlets: dict[str, tuple[Vec, Vec]] = {"outlet-1": ((-L / 2, 0.0, za), (-1.0, 0.0, 0.0))}
    if expander:
        parts.append(
            _cyl("brake", (hx + 0.02, 0.0, za), (L / 2 - 0.05, 0.0, za), 0.75 * rs, "motor", 2)
        )
    else:
        parts.append(
            _torus("booster-volute", (xb, 0.0, za), (1.0, 0.0, 0.0), 0.62 * rs, 0.38 * rs, "casing")
        )
        parts.append(
            _cyl(
                "booster-cover", (xb - t / 2, 0.0, za), (xb + t / 2, 0.0, za), 0.8 * rs, "casing", 2
            )
        )
        parts += _flanged(
            "booster-inlet", (L / 2, 0.0, za), (1.0, 0.0, 0.0), rb, rf, L / 2 - xb - t / 2
        )
        yo = -0.5 * rs
        parts.append(
            _cyl("booster-outlet-env", (xb, yo, za), (xb, yo, H), 0.42 * rs, "casing", lod=1)
        )
        parts += _flanged(
            "booster-outlet", (xb, yo, H), (0.0, 0.0, 1.0), 0.28 * rs, 0.42 * rs, H - za
        )
        flanges["inlet-2"] = ((L / 2, 0.0, za), (1.0, 0.0, 0.0))
        outlets["outlet-2"] = ((xb, yo, H), (0.0, 0.0, 1.0))
    y0, y1 = 0.3 * W, 0.49 * W
    if y1 - y0 > 0.1 and za - rs > base:
        parts.append(
            _box(
                "oil-console",
                (-0.27 * L, -(y0 + y1) / 2, base + 0.15 * room),
                (0.22 * L, y1 - y0, 0.3 * room),
                "casing",
            )
        )
    item.local_parts = parts
    item.casing = (za, xe - t / 2, xb + t / 2, rs)
    item.flanges = {**flanges, **outlets}


# ---------------------------------------------------------------------------
# Detail of the other families
# ---------------------------------------------------------------------------


def detail(item: Body) -> None:
    """Add the level-2 detail of *item*'s family (see the module text)."""
    family = item.family
    if item.shape == "vertical_cylinder":
        if family == "tank":
            _tank(item)
        elif family in ("vessel", "column", "filter"):
            _vertical_vessel(item)
        elif item.grade:
            r = (item.dims.diameter or 0.0) / 2
            item.local_parts.append(
                _cyl("foundation", (0.0, 0.0, 0.0), (0.0, 0.0, FOUNDATION), 1.2 * r, "concrete", 2)
            )
    elif item.shape == "horizontal_cylinder":
        _horizontal_detail(item)
    elif item.shape == "box":
        if family == "plate_exchanger":
            _plate_exchanger(item)
        elif family == "air_cooler":
            _air_cooler(item)
        is_machine = family in ("pump", "compressor", "turbine") and item.variant != "machine"
        if item.grade and not is_machine:
            d = item.dims
            L, W = d.length or 0.0, d.width or 0.0
            item.local_parts.append(
                _box(
                    "foundation",
                    (0.0, 0.0, FOUNDATION / 2),
                    (L + 0.3, W + 0.3, FOUNDATION),
                    "concrete",
                    lod=2,
                )
            )


def _support(item: Body) -> str:
    ids = {p.id for p in item.local_parts}
    if "skirt" in ids:
        return "skirt"
    if any(i.startswith("leg-") for i in ids):
        return "legs"
    if any(i.startswith("saddle-") for i in ids):
        return "saddles"
    return "none"


def _lug(pid: str, angle: float, radius: float, z: float) -> Part:
    return _box(pid, _polar(radius + 0.1, angle, z), (0.22, 0.04, 0.28), "steel", 2, angle)


def _vertical_vessel(item: Body) -> None:
    d = item.dims
    D = d.diameter or 0.0
    r = D / 2
    z0, z1 = item.shell_bottom, item.shell_top
    parts = item.local_parts
    support = _support(item)
    ft = FOUNDATION if item.grade else 0.0
    if support == "skirt":
        if item.grade:
            parts.append(
                _cyl("foundation", (0.0, 0.0, 0.0), (0.0, 0.0, ft), 1.25 * r, "concrete", 2)
            )
        parts.append(_cyl("base-ring", (0.0, 0.0, ft), (0.0, 0.0, ft + 0.04), 1.1 * r, "steel", 2))
        chairs = max(4, min(24, 4 * math.ceil(math.pi * D / 4.8)))
        for k in range(chairs):
            a = 360.0 * k / chairs + 180.0 / chairs
            parts.append(
                _box(
                    f"anchor-chair-{k + 1}",
                    _polar(r + 0.07, a, ft + 0.19),
                    (0.14, 0.2, 0.3),
                    "steel",
                    2,
                    a,
                )
            )
        skirt = z0 - item.head_depths[0]
        if skirt > 1.2:
            zc = ft + min(0.9, 0.45 * skirt)
            a = 300.0
            parts.append(
                _cyl(
                    "skirt-opening-ring",
                    _polar(r - 0.02, a, zc),
                    _polar(r + 0.06, a, zc),
                    0.34,
                    "steel",
                    2,
                )
            )
            parts.append(
                _cyl(
                    "skirt-opening",
                    _polar(r - 0.01, a, zc),
                    _polar(r + 0.065, a, zc),
                    0.3,
                    "opening",
                    2,
                )
            )
    elif support == "legs":
        for k in range(4):
            x, y, _ = _polar(0.8 * r, 45 + 90 * k, 0.0)
            leg = max(0.04, 0.05 * D)
            if item.grade:
                parts.append(
                    _box(f"leg-{k + 1}-pad", (x, y, ft / 2), (5 * leg, 5 * leg, ft), "concrete", 2)
                )
            parts.append(
                _box(
                    f"leg-{k + 1}-base", (x, y, ft + 0.01), (3.5 * leg, 3.5 * leg, 0.02), "steel", 2
                )
            )
    elif item.grade:
        parts.append(_cyl("foundation", (0.0, 0.0, 0.0), (0.0, 0.0, ft), 1.15 * r, "concrete", 2))
    for n, a in enumerate((90.0, 270.0), 1):
        parts.append(_lug(f"lifting-lug-{n}", a, r, z1 - 0.15))
    if item.family == "column" or (d.height or 0.0) > 8:
        z = z0 + 1.5
        k = 0
        while z < z1 - 1.0:
            k += 1
            parts.append(
                _cyl(f"ring-{k}", (0.0, 0.0, z - 0.02), (0.0, 0.0, z + 0.02), r + 0.07, "steel", 2)
            )
            z += RING_PITCH


def manways(item: Body, avoid: list[float]) -> None:
    """Manways with davits on a vertical vessel or column (one at mid shell on a vessel; on a
    column one above the bottom tangent and every 8 m up), at the angle (own frame, degrees
    ccw) farthest from the nozzle angles *avoid*; on a horizontal drum, one on its front
    head. Needs a shell of at least 1 m."""
    D = item.dims.diameter or 0.0
    if D < 1.0:
        return
    r = D / 2
    if item.shape == "horizontal_cylinder" and item.family == "horizontal_vessel":
        x0 = item.ends[0]
        h = item.head_depths[0]
        zc = item.shell_bottom + 0.3 * r
        start = (x0 - 0.9 * h, 0.0, zc)
        face = (x0 - h - 0.3, 0.0, zc)
        item.local_parts.extend(_manway("manway-1", start, face, (-1.0, 0.0, 0.0), (0.0, 1.0, 0.0)))
        return
    if item.shape != "vertical_cylinder" or item.family not in ("vessel", "column"):
        return
    angle = _free_angle(avoid)
    z0, z1 = item.shell_bottom, item.shell_top
    if item.family == "column":
        heights = []
        z = z0 + 1.2
        while z < z1 - 0.8:
            heights.append(z)
            z += 8.0
    else:
        heights = [(z0 + z1) / 2] if z1 - z0 > 1.2 else []
    if item.family == "column":
        item.local_parts.extend(_top_davit(item, angle))
    for k, z in enumerate(heights, 1):
        a = math.radians(angle)
        out = (math.cos(a), math.sin(a), 0.0)
        side = (-math.sin(a), math.cos(a), 0.0)
        start = _polar(r - 0.02, angle, z)
        face = _polar(r + 0.3, angle, z)
        item.local_parts.extend(_manway(f"manway-{k}", start, face, out, side))


def _top_davit(item: Body, angle: float) -> list[Part]:
    """The davit on a column's top head, on the side free of nozzles (*angle*, the manways'):
    a post near the shell edge and its arm stowed along the edge (it swings over the top
    nozzles only for a lift). Steel the pipes must keep clear of, so a solid (``lod`` None)."""
    r = (item.dims.diameter or 0.0) / 2
    z1 = item.shell_top
    depth = item.head_depths[1]
    top = z1 + depth
    reach = 0.75 * r
    zb = z1 + depth * math.sqrt(max(1 - (reach / r) ** 2, 0.0)) - 0.05
    x, y, _ = _polar(reach, angle, 0.0)
    a = math.radians(angle)
    along = (-math.sin(a), math.cos(a))  # stowed: ccw along the shell edge
    arm = min(0.5 * r, 1.2)
    tip = (x + along[0] * arm, y + along[1] * arm, top + DAVIT[1])
    return [
        _cyl("davit-post", (x, y, zb), (x, y, top + DAVIT[0]), 0.05, "steel"),
        _cyl("davit-arm", (x, y, top + DAVIT[1]), tip, 0.04, "steel"),
    ]


def _free_angle(avoid: list[float]) -> float:
    """The middle of the largest gap between *avoid* (degrees); 225 without any."""
    ordered = sorted({round(a % 360, 3) for a in avoid})
    if not ordered:
        return 225.0
    best, at = -1.0, 225.0
    for k, a in enumerate(ordered):
        b = ordered[(k + 1) % len(ordered)] + (360 if k + 1 == len(ordered) else 0)
        if b - a > best + 1e-9:
            best, at = b - a, (a + (b - a) / 2) % 360
    return round(at, 3)


def _manway(pid: str, start: Vec, face: Vec, out: Vec, side: Vec) -> list[Part]:
    """A DN 600 manway from *start* (inside the shell) to its cover at *face*, pointing
    *out*, with a davit beside it on the *side*."""
    parts = [
        _cyl(f"{pid}-neck", start, _at(face, out, -0.06), 0.31, "shell", 2),
        _cyl(f"{pid}-flange", _at(face, out, -0.06), face, 0.42, "flange", 2),
    ]
    post = _at(_at(face, out, -0.15), side, 0.55)
    low = (post[0], post[1], post[2] - 0.5)
    high = (post[0], post[1], post[2] + 0.7)
    parts.append(_cyl(f"{pid}-davit-post", low, high, 0.035, "steel", 2))
    tip = (face[0] + out[0] * 0.05, face[1] + out[1] * 0.05, high[2])
    parts.append(_cyl(f"{pid}-davit-arm", high, tip, 0.03, "steel", 2))
    return parts


def _horizontal_detail(item: Body) -> None:
    d = item.dims
    D, L = d.diameter or 0.0, d.length or 0.0
    r = D / 2
    zc = item.shell_bottom
    parts = item.local_parts
    saddles = [p for p in parts if p.id.startswith("saddle-")]
    for k, saddle in enumerate(saddles, 1):
        x = (saddle.centre or (0.0, 0.0, 0.0))[0]
        if item.grade:
            parts.append(
                _box(
                    f"saddle-{k}-pad",
                    (x, 0.0, FOUNDATION / 2),
                    (0.8, 1.05 * D, FOUNDATION),
                    "concrete",
                    2,
                )
            )
        z = FOUNDATION if item.grade else 0.0
        parts.append(
            _box(f"saddle-{k}-base", (x, 0.0, z + 0.015), (0.45, 0.95 * D, 0.03), "steel", 2)
        )
    for n, x in enumerate((-0.3 * L, 0.3 * L), 1):
        parts.append(
            _box(f"lifting-lug-{n}", (x, 0.0, zc + r + 0.1), (0.28, 0.04, 0.22), "steel", 2)
        )
    if item.family == "shell_tube":
        thick = 0.05 + 0.02 * D
        x0 = item.tangent[0]
        joints = [("flange-bonnet", item.ends[0]), ("flange-channel", x0)]
        if item.head_depths[1] > 0:
            joints.append(("flange-rear", item.tangent[1]))
        for name, x in joints:
            parts.append(
                _cyl(
                    name, (x - thick / 2, 0.0, zc), (x + thick / 2, 0.0, zc), 1.13 * r, "flange", 2
                )
            )


def _plate_exchanger(item: Body) -> None:
    d = item.dims
    L, W, H = d.length or 0.0, d.width or 0.0, d.height or 0.0
    parts = item.local_parts
    bolt = 0.02 + 0.01 * W
    for k, (y, z) in enumerate(
        ((s * 0.46 * W, f * H) for f in (0.12, 0.5, 0.88) for s in (-1, 1)), 1
    ):
        parts.append(
            _cyl(f"tie-bolt-{k}", (-L / 2 + 0.01, y, z), (L / 2 - 0.01, y, z), bolt, "steel", 2)
        )
    parts.append(_box("carrying-bar", (0.0, 0.0, 0.975 * H), (L - 0.02, 0.08, 0.05), "steel", 2))
    parts.append(
        _box("guide-bar", (0.0, 0.0, 0.025 * H + 0.02), (L - 0.02, 0.06, 0.04), "steel", 2)
    )


def _air_cooler(item: Body) -> None:
    d = item.dims
    L, W, H = d.length or 0.0, d.width or 0.0, d.height or 0.0
    parts = item.local_parts
    fans = [p for p in parts if p.id.startswith("fan-")]
    header = min(0.4, 0.06 * L)
    z_bundle = 0.55 * H
    for n, x in enumerate((-L / 2 + header / 2, L / 2 - header / 2), 1):
        parts.append(_box(f"header-{n}", (x, 0.0, z_bundle), (header, W, 0.22 * H), "casing", 2))
    for k, fan in enumerate(fans, 1):
        x = (fan.start or (0.0, 0.0, 0.0))[0]
        fr = fan.radius or 0.5
        z0, z1 = (fan.start or (0, 0, 0))[2], (fan.end or (0, 0, 0))[2]
        mid = (z0 + z1) / 2
        parts.append(
            _frustum(
                f"plenum-{k}",
                (x, 0.0, z0),
                (L / len(fans), W, mid - z0),
                (2.1 * fr, 2.1 * fr),
                "casing",
            )
        )
        parts.append(_torus(f"fan-ring-{k}", (x, 0.0, z1 - 0.05), (0.0, 0.0, 1.0), fr, 0.05, "fan"))
        parts.append(_cyl(f"fan-shroud-{k}", (x, 0.0, mid), (x, 0.0, z1 - 0.05), fr, "fan", 2))
        hub = (x, 0.0, mid + 0.35 * (z1 - mid))
        parts.append(_cyl(f"fan-hub-{k}", hub, (hub[0], 0.0, hub[2] + 0.12), 0.12 * fr, "steel", 2))
        for b in range(4):
            a = 45.0 + 90.0 * b
            c = (x + 0.5 * fr * math.cos(math.radians(a)), 0.5 * fr * math.sin(math.radians(a)))
            parts.append(
                _box(
                    f"fan-{k}-blade-{b + 1}",
                    (*c, hub[2] + 0.06),
                    (0.85 * fr, 0.12 * fr, 0.02),
                    "fan",
                    2,
                    a,
                )
            )
        parts.append(
            _cyl(f"fan-motor-{k}", (x, 0.0, mid - 0.05), (x, 0.0, hub[2]), 0.1 * fr, "motor", 2)
        )


def _tank(item: Body) -> None:
    d = item.dims
    D = d.diameter or 0.0
    r = D / 2
    z1 = item.shell_top
    parts = item.local_parts
    ft = 0.25 if item.grade else 0.0
    if item.grade and item.plinth <= 0:  # a declared plinth is the tank's foundation
        parts.append(_cyl("ring-wall", (0.0, 0.0, 0.0), (0.0, 0.0, ft), r + 0.35, "concrete", 2))
    chairs = max(8, round(math.pi * D / 1.5))
    for k in range(chairs):
        a = 360.0 * k / chairs
        parts.append(
            _box(
                f"anchor-chair-{k + 1}",
                _polar(r + 0.1, a, ft + 0.22),
                (0.2, 0.25, 0.45),
                "steel",
                2,
                a,
            )
        )
    # the stair starts on the ring wall, or at grade below a plinth
    base = -item.plinth if item.plinth > 0 else ft
    rise = z1 - base
    w, gap, pitch, riser = TANK_STAIR
    a_top = 200.0
    if rise > 3.0 and D >= 3.0:
        ri, ro = r + gap, r + gap + w
        rm = (ri + ro) / 2
        steps = max(2, math.ceil(rise / riser - 1e-9))
        h = rise / steps
        going = h / math.tan(math.radians(pitch))
        dtheta = math.degrees(going / rm)
        a0 = 200.0

        def angle(k: float) -> float:
            return a0 + k * dtheta

        for k in range(1, steps):
            a = angle(k)
            parts.append(
                _box(
                    f"stair-tread-{k}",
                    _polar(rm, a, base + k * h),
                    (w, 1.05 * going, 0.03),
                    "grating",
                    None,
                    a % 360,
                )
            )
        chord = 4
        marks = list(range(0, steps + 1, chord))
        if marks[-1] != steps:
            marks.append(steps)
        for j, (k0, k1) in enumerate(zip(marks, marks[1:], strict=False), 1):
            za, zb = base + k0 * h, base + k1 * h
            for name, radius, dz, rr, mat, lod in (
                ("stringer-in", ri + 0.03, -0.1, 0.045, "steel", None),
                ("stringer-out", ro - 0.03, -0.1, 0.045, "steel", None),
                ("handrail", ro, HANDRAIL - 0.1, 0.025, "handrail", None),
                ("midrail", ro, MIDRAIL - 0.05, 0.02, "handrail", 2),
            ):
                parts.append(
                    _cyl(
                        f"stair-{name}-{j}",
                        _polar(radius, angle(k0), za + dz),
                        _polar(radius, angle(k1), zb + dz),
                        rr,
                        mat,
                        lod,
                    )
                )
            parts.append(
                _cyl(
                    f"stair-post-{j}",
                    _polar(ro, angle(k0), za),
                    _polar(ro, angle(k0), za + HANDRAIL - 0.1),
                    0.02,
                    "handrail",
                    2,
                )
            )
        a_top = angle(steps) % 360
        parts.append(
            _box(
                "stair-landing", _polar(rm, a_top, z1), (w + gap, 1.0, 0.04), "grating", None, a_top
            )
        )
    elif rise > 0.5:
        a_top = 200.0
        out = _polar(1.0, a_top, 0.0)
        side = (-out[1], out[0])
        foot = _polar(r + 0.25, a_top, base)
        for n, s in enumerate((-1, 1), 1):
            p = (foot[0] + side[0] * s * 0.225, foot[1] + side[1] * s * 0.225)
            parts.append(_cyl(f"ladder-rail-{n}", (*p, base), (*p, z1 + HANDRAIL), 0.02, "steel"))
        if rise > 3.0:
            c = _polar(r + 0.6, a_top, 0.0)
            parts.append(
                _cyl(
                    "ladder-cage",
                    (c[0], c[1], base + 2.3),
                    (c[0], c[1], z1 + HANDRAIL),
                    0.35,
                    "cage",
                )
            )
    # the roof: handrail ring, mid rail, toe plate, posts and a platform at the stair head
    rr = r - 0.06
    parts.append(
        _annulus(
            "roof-handrail", (0.0, 0.0, z1 + HANDRAIL), rr - 0.025, rr + 0.025, 0.05, "handrail"
        )
    )
    parts.append(
        _annulus("roof-midrail", (0.0, 0.0, z1 + MIDRAIL), rr - 0.02, rr + 0.02, 0.04, "handrail")
    )
    parts.append(
        _annulus("roof-toe-plate", (0.0, 0.0, z1 + 0.12), rr - 0.005, rr + 0.005, 0.1, "steel")
    )
    posts = max(8, round(2 * math.pi * rr / 2.0))
    for k in range(posts):
        a = 360.0 * k / posts
        p = _polar(rr, a, 0.0)
        parts.append(
            _cyl(
                f"roof-post-{k + 1}",
                (p[0], p[1], z1),
                (p[0], p[1], z1 + HANDRAIL),
                0.02,
                "handrail",
                2,
            )
        )
    if r > 1.6:
        depth = item.head_depths[1]
        inner = r - 1.6
        rise_at = (
            depth * (1 - inner / r)
            if item.dims.head == "cone_roof"
            else depth * math.sqrt(max(1 - (inner / r) ** 2, 0.0))
        )
        zp = z1 + rise_at + 0.05
        parts.append(
            _box(
                "roof-platform",
                _polar(r - 0.8, a_top, zp - 0.02),
                (1.5, 1.2, 0.04),
                "grating",
                2,
                a_top,
            )
        )


# ---------------------------------------------------------------------------
# Nozzles and instruments (site frame)
# ---------------------------------------------------------------------------


def flange_size(od: float) -> tuple[float, float, float]:
    """``(flange radius, flange thickness, neck length)`` of a nozzle of outside diameter *od*
    (m): about EN 1092-1 PN 16 (ASSUMED), the neck about 150 mm + OD/2, at most 400 mm."""
    return (od / 2 * 1.35 + 0.045, 0.018 + 0.06 * od, _clamp(0.15 + od / 2, 0.15, 0.4))


def fit_flange(item: Body, point: Vec, od: float) -> bool:
    """Size the machine's own round flange whose face is at *point* (site frame) by the DN of
    the nozzle on it, outside diameter *od* (m), as :func:`flange_size` sizes any other nozzle's
    flange; whether there was one. The face stays where it is."""
    from dataclasses import replace

    radius = flange_size(od)[0]
    for k, part in enumerate(item.local_parts):
        if part.material != "flange" or part.kind != "cylinder":
            continue
        ends = [e for e in (part.start, part.end) if e is not None]
        if any(math.dist(item.to_site(e), point) < 1e-6 for e in ends):
            item.local_parts[k] = replace(part, radius=round(radius, 6))
            return True
    return False


def nozzle_flange(
    name: str, point: Vec, direction: Vec, od: float, inward: float = 0.0
) -> tuple[list[Part], Vec]:
    """The neck and flange of a nozzle leaving the surface at *point* along *direction*, and
    the face of its flange (where the pipe connects). With *inward* > 0 the flange stays at
    *point* and the neck reaches *inward* back into the item (a nozzle on a machine's
    envelope); else the neck stands out of the shell and the face moves out by its length."""
    flange, thick, neck = flange_size(od)
    if inward > 0:
        face = point
        back = _at(point, direction, -inward)
    else:
        face = _at(point, direction, neck)
        back = point
    seat = _at(face, direction, -thick)
    parts = [
        _cyl(f"{name}/neck", back, seat, od / 2, "shell", 2),
        _cyl(f"{name}/flange", seat, face, flange, "flange", 2),
    ]
    return parts, face


def transmitter(name: str, tapping: Vec, direction: Vec, floor: float) -> list[Part]:
    """A transmitter on a stand next to an instrument tapping at *tapping* (outward
    *direction*): an impulse line out and down to the head at about 1.2 m above *floor*, on a
    2-inch post with a base plate; a head higher than 2.5 m above the floor hangs on a bracket
    at the tapping instead."""
    horizontal = math.hypot(direction[0], direction[1])
    if horizontal > 0.3:
        ox, oy = direction[0] / horizontal, direction[1] / horizontal
    else:
        ox, oy = 1.0, 0.0
    out = (tapping[0] + ox * 0.6, tapping[1] + oy * 0.6, tapping[2])
    stand = tapping[2] - floor < 3.0
    head_z = floor + 1.2 if stand else tapping[2] - 0.3
    head = (out[0], out[1], head_z)
    parts = [
        _cyl(f"{name}/impulse-1", tapping, out, 0.01, "steel", 2),
        _cyl(f"{name}/impulse-2", out, (out[0], out[1], head_z + 0.12), 0.01, "steel", 2),
        _box(
            f"{name}/transmitter", (head[0], head[1], head_z), (0.12, 0.12, 0.16), "instrument", 2
        ),
        _cyl(
            f"{name}/transmitter-cap",
            (head[0], head[1], head_z + 0.08),
            (head[0], head[1], head_z + 0.14),
            0.055,
            "instrument",
            2,
        ),
    ]
    post = (head[0] + ox * 0.12, head[1] + oy * 0.12)
    if stand:
        parts.append(_cyl(f"{name}/stand", (*post, floor), (*post, head_z + 0.1), 0.03, "steel", 2))
        parts.append(
            _box(f"{name}/stand-base", (*post, floor + 0.01), (0.2, 0.2, 0.02), "steel", 2)
        )
    else:
        parts.append(
            _cyl(
                f"{name}/bracket",
                (*post, head_z),
                (tapping[0], tapping[1], head_z),
                0.02,
                "steel",
                2,
            )
        )
    return parts
