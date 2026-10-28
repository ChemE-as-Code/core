"""Recognisable equipment (``domains/spatial/shape_details.py``): the machine families and
the level-2 detail of the others, the level-of-detail split and the nozzles on real flanges."""

import dataclasses
import math

import pytest

from chemeascode.domains.spatial import shape_details
from chemeascode.domains.spatial.geometry3d import part_solid
from chemeascode.domains.spatial.shapes import Dims, body, variant_for


def as_dict(part):
    return {k: v for k, v in dataclasses.asdict(part).items() if v is not None}


def ids(item, lod=None):
    return [p.id for p in item.parts() if lod is None or p.lod == lod]


def inside(item, tol=1e-6):
    """Every part's solid (envelope and detail) lies within the item's bounding box."""
    x0, y0, z0, x1, y1, z1 = item.bbox()
    for part in item.parts():
        solid = part_solid(as_dict(part), detail=part.lod == 2)
        assert solid is not None, part.id
        a = solid.aabb
        assert a[0] >= x0 - tol and a[1] >= y0 - tol and a[2] >= z0 - tol, part.id
        assert a[3] <= x1 + tol and a[4] <= y1 + tol and a[5] <= z1 + tol, part.id


MACHINES = [
    ("pump", Dims(length=2.6, width=1.0, height=1.3), "CentrifugalPump", "end_suction"),
    ("pump", Dims(length=1.6, width=0.9, height=1.4, variant="cryogenic"), None, "cryogenic"),
    (
        "pump",
        Dims(length=1, width=0.8, height=1.8, orientation="vertical"),
        None,
        "vertical_inline",
    ),
    (
        "compressor",
        Dims(length=12, width=6, height=5),
        "CentrifugalCompressor",
        "integrally_geared",
    ),
    ("compressor", Dims(length=4, width=3, height=3), "CentrifugalBlower", "blower"),
    ("turbine", Dims(length=3, width=3, height=3), "Turbine", "compander"),
    ("turbine", Dims(length=3, width=2, height=2, variant="expander"), None, "expander"),
]


@pytest.mark.parametrize(("family", "dims", "cls", "variant"), MACHINES)
def test_machines_split_into_envelope_and_detail_within_their_box(family, dims, cls, variant):
    item = body(family, dims, (10, 20, 0), 30, type_name=cls)
    assert item.variant == variant
    assert ids(item, 1) and ids(item, 2)  # an envelope and detail
    assert all(p.lod in (None, 1, 2) for p in item.parts())
    inside(item)
    assert item.flanges  # nozzles go on real flanges
    for _point, direction in item.flanges.values():
        assert abs(sum(c * c for c in direction) - 1) < 1e-9


def test_variants_by_class_orientation_and_override():
    assert variant_for("pump", "CentrifugalPump", None) == "end_suction"
    assert variant_for("pump", None, Dims(orientation="vertical")) == "vertical_inline"
    assert variant_for("pump", None, Dims(variant="cryogenic", orientation="vertical")) == (
        "cryogenic"
    )
    assert variant_for("compressor", "AxialCompressor", None) == "machine"
    assert variant_for("compressor", "RadialFan", None) == "blower"
    assert variant_for("turbine", "SteamTurbine", None) == "machine"
    assert variant_for("vessel", "Vessel", None) is None
    assert variant_for("pump", None, Dims(variant="blower")) == "end_suction"  # not a pump's
    plain = body("compressor", Dims(length=6, width=3, height=3), type_name="AxialCompressor")
    envelope = [p.id for p in plain.parts() if p.lod != 2]
    assert envelope == ["base", "casing", "motor", "coupling"]  # the plain machine


def test_end_suction_pump_looks_like_one():
    pump = body("pump", Dims(length=2.6, width=1.0, height=1.3), (0, 0, 0))
    detail = set(ids(pump, 2))
    assert {
        "volute",
        "volute-cover",
        "suction-flange",
        "discharge-flange",
        "bearing-housing",
        "seal-chamber",
        "shaft",
        "coupling",
        "fan-cowl",
        "fan-grille",
        "motor-frame",
        "drip-rim-1",
        "motor-foot-1",
    } <= detail
    assert sum(i.startswith("rib-") for i in detail) >= 6
    parts = {p.id: p for p in pump.parts()}
    assert parts["plinth"].material == "concrete" and parts["plinth"].lod is None
    assert parts["coupling-guard"].material == "guard"
    suction, discharge = pump.flanges["suction"], pump.flanges["discharge"]
    assert suction[0][0] == pytest.approx(-1.3) and suction[1] == (-1.0, 0.0, 0.0)  # axial
    assert discharge[0][2] == pytest.approx(1.3) and discharge[1] == (0.0, 0.0, 1.0)  # on top
    assert discharge[0][1] != 0  # tangential: off the shaft's plane
    off = body("pump", Dims(length=2.6, width=1.0, height=1.3), (0, 0, 3), grade=False)
    assert "plinth" not in ids(off)  # not at grade: no plinth


def test_vertical_inline_and_cryogenic_pumps():
    inline = body("pump", Dims(length=1, width=0.8, height=1.8, orientation="vertical"))
    suction, discharge = inline.flanges["suction"], inline.flanges["discharge"]
    assert suction[0][2] == discharge[0][2] and suction[1] == (-1.0, 0.0, 0.0)
    motor = next(p for p in inline.parts() if p.id == "motor")
    assert motor.start[0] == motor.end[0] and motor.end[2] == pytest.approx(1.8)  # upright
    (removal,) = [e for e in inline.envelopes() if e.kind == "motor_removal"]
    assert removal.centre[2] > 1.8  # lifted out upwards
    cold = body("pump", Dims(length=1.6, width=0.9, height=1.4, variant="cryogenic"))
    assert next(p for p in cold.parts() if p.id == "cold-end").material == "insulation"


def test_integrally_geared_compressor_stages_and_package():
    k = body("compressor", Dims(length=12, width=6, height=5), type_name="CentrifugalCompressor")
    detail = ids(k, 2)
    assert sum(i.endswith("-volute") for i in detail) == 4
    assert "gearbox" in detail and "lube-oil-pump-1" in detail
    assert any(i.startswith("intercooler-") for i in detail)
    assert next(p for p in k.parts() if p.id == "stage-3-inlet-elbow").arc_deg == (0.0, 90.0)
    assert list(k.flanges)[:2] == ["inlet-1", "inlet-2"]
    left = k.pid_anchor("left", -1, 0)
    assert left.flange and left.point[0] == pytest.approx(-6)  # the first stage's inlet
    top = k.pid_anchor("top", 0, -1)
    assert top.flange and top.point[2] == pytest.approx(5)  # the last stage's outlet
    small = body("compressor", Dims(length=4, width=3, height=3), type_name="Compressor")
    assert sum(i.endswith("-volute") for i in ids(small, 2)) == 2


def test_vessel_and_column_detail():
    column = body("column", Dims(diameter=4, height=25), (0, 0, 0))
    detail = ids(column, 2)
    assert "foundation" in detail and "base-ring" in detail and "skirt-opening" in detail
    assert sum(i.startswith("anchor-chair-") for i in detail) >= 4
    assert sum(i.startswith("ring-") for i in detail) >= 6
    assert "lifting-lug-1" in detail
    shape_details.manways(column, [0.0, 90.0, 180.0])
    davit = {p.id: p for p in column.parts() if p.id.startswith("davit-")}
    assert set(davit) == {"davit-post", "davit-arm"}
    manways = [p for p in column.parts() if p.id.endswith("-flange") and "manway" in p.id]
    assert len(manways) == 3  # 1.2 m above the bottom tangent and every 8 m
    face = manways[0].end
    assert face[0] == pytest.approx(0, abs=1e-9) and face[1] < -2  # the free gap: 270 degrees
    vessel = body("vessel", Dims(diameter=1.5, height=4, support="legs"), (0, 0, 2), grade=False)
    assert "leg-1-base" in ids(vessel, 2) and "leg-1-pad" not in ids(vessel)
    drum = body("horizontal_vessel", Dims(diameter=3, length=10, height=4))
    shape_details.manways(drum, [])
    assert "manway-1-flange" in ids(drum, 2) and "saddle-1-base" in ids(drum, 2)


def test_exchangers_tanks_and_coolers():
    hx = body("shell_tube", Dims(diameter=1.6, length=8, height=2.4))
    assert {"flange-bonnet", "flange-channel", "flange-rear"} <= set(ids(hx, 2))
    plates = body("plate_exchanger", Dims(length=3, width=1.5, height=4))
    assert sum(i.startswith("tie-bolt-") for i in ids(plates, 2)) == 6
    cooler = body("air_cooler", Dims(length=8, width=4, height=5))
    kinds = {p.kind for p in cooler.parts() if p.lod == 2}
    assert {"frustum", "torus"} <= kinds
    tank = body("tank", Dims(diameter=8.2, height=12.6, head="cone_roof"))
    detail = ids(tank, 2)
    treads = [i for i in ids(tank) if i.startswith("stair-tread-")]
    assert len(treads) > 40 and "roof-handrail" in detail and "roof-platform" in detail
    assert "ring-wall" in detail and "stair-midrail-1" in detail
    small = body("tank", Dims(diameter=2, height=4, head="cone_roof"))
    assert "ladder-cage" in ids(small) and not [i for i in ids(small) if "tread" in i]


def test_a_tank_on_a_plinth_keeps_its_stair_from_grade():
    # a 0.5 m plinth: a concrete solid under the footprint (0.1 m wider), no ring wall, and the
    # spiral stair starts at grade (0.5 m below the tank's bottom), not on the plinth
    on = body("tank", Dims(diameter=8.2, height=12.6, head="cone_roof"), (0, 0, 0.5), plinth=0.5)
    parts = {p.id: p for p in on.parts()}
    plinth = parts["plinth"]
    assert plinth.lod is None and plinth.material == "concrete"
    assert plinth.start[2] == pytest.approx(0.0) and plinth.end[2] == pytest.approx(0.5)
    assert plinth.radius == pytest.approx(4.2)
    assert "ring-wall" not in parts
    first = min(p.centre[2] for i, p in parts.items() if i.startswith("stair-tread-"))
    assert first < 0.3  # the first tread one riser above grade
    landing = parts["stair-landing"].centre[2]
    flat = {
        p.id: p for p in body("tank", Dims(diameter=8.2, height=12.6, head="cone_roof")).parts()
    }
    assert landing == pytest.approx(flat["stair-landing"].centre[2] + 0.5)
    box = body("generic", Dims(length=2, width=1, height=1), (0, 0, 0.3), plinth=0.3)
    plinth = {p.id: p for p in box.parts()}["plinth"]
    assert plinth.size == pytest.approx((2.2, 1.2, 0.3)) and plinth.centre[2] == pytest.approx(0.15)


def test_tank_stair_and_ladder_are_solids_like_structure_stairs():
    """A spiral stair stands up to about 1 m outside the tank's box, so its treads, landing,
    stringers and handrail are solids (``lod`` None) the router and the clash checks see; only
    its posts and mid rail are detail."""
    tank = body("tank", Dims(diameter=8.2, height=12.6, head="cone_roof"))
    parts = {p.id: p for p in tank.parts()}
    solid = [i for i, p in parts.items() if i.startswith("stair-") and p.lod is None]
    assert sum(i.startswith("stair-tread-") for i in solid) > 40
    assert {"stair-landing", "stair-stringer-in-1", "stair-handrail-1"} <= set(solid)
    assert parts["stair-midrail-1"].lod == 2 and parts["stair-post-1"].lod == 2
    for i in solid:
        assert part_solid(as_dict(parts[i])) is not None, i
    x0, _, _, x1, _, _ = tank.bbox()
    outside = [i for i in solid if part_solid(as_dict(parts[i])).aabb[3] > x1 + 0.5]
    assert outside  # the stair stands outside the box: the bbox alone would miss it
    small = body("tank", Dims(diameter=2, height=4, head="cone_roof"))
    small_parts = {p.id: p for p in small.parts()}
    assert small_parts["ladder-cage"].lod is None and small_parts["ladder-rail-1"].lod is None


def _model_of(tag, item):
    from chemeascode.domains.spatial.model import _part

    return {
        "equipment": [
            {
                "id": tag,
                "tag": tag,
                "family": item.family,
                "shape": item.shape,
                "position": list(item.position),
                "rotation_deg": item.rotation_deg,
                "bbox": list(item.bbox()),
                "parts": [_part(tag, p) for p in item.parts()],
                "nozzles": [],
                "envelopes": [],
            }
        ],
        "racks": [],
        "structures": [],
        "zones": [],
        "areas": [],
        "pipes": [],
    }


def _clashes(model, points, od=0.1):
    from chemeascode.domains.spatial.model_rules import model_rules

    model["pipes"] = [
        {
            "id": "P/S1",
            "line": "L-1",
            "segment": "S1",
            "od": od,
            "insulation_mm": 0,
            "points": points,
            "method": "astar",
        }
    ]
    found = model_rules(model, None, None)
    return [f for f in found if f.rule == "cheme.layout-clash-pipe-equipment"]


def test_a_pipe_through_a_tank_stair_or_a_column_davit_is_a_clash():
    tank = body("tank", Dims(diameter=8.2, height=12.6, head="cone_roof"), (0, 0, 0))
    landing = next(p for p in tank.parts() if p.id == "stair-landing")
    x, y, z = landing.centre
    assert math.hypot(x, y) > 4.1 + 0.1  # outside the shell's box radius
    model = _model_of("T-1", tank)
    found = _clashes(model, [[x, y - 5, z], [x, y + 5, z]])
    assert found and "stair" in found[0].message
    column = body("column", Dims(diameter=4, height=25), (0, 0, 0))
    shape_details.manways(column, [0.0, 90.0, 180.0])
    post = next(p for p in column.parts() if p.id == "davit-post")
    px, py, _ = post.start
    zt = post.end[2] - 0.3
    found = _clashes(_model_of("C-1", column), [[px - 5, py, zt], [px + 5, py, zt]])
    assert found and "davit" in found[0].message


def test_column_top_davit_is_a_solid_stowed_on_the_free_side():
    """The davit on a column's top head stands about 1.8 m above the column's box: a solid,
    on the side free of nozzles, its arm stowed along the shell edge (not over the top
    nozzles, where the overhead vapour line leaves)."""
    column = body("column", Dims(diameter=4, height=25), (0, 0, 0))
    shape_details.manways(column, [0.0, 90.0, 180.0])  # free side: 270 degrees
    parts = {p.id: p for p in column.parts()}
    post, arm = parts["davit-post"], parts["davit-arm"]
    assert post.lod is None and arm.lod is None
    assert post.start[1] < -1.0 and abs(post.start[0]) < 1e-9  # at 270 degrees
    assert post.end[2] > column.bbox()[5] + 1.0  # above the top head
    for p in (arm.start, arm.end):
        assert math.hypot(p[0], p[1]) > 1.0  # clear of the top-head centre
    small = body("column", Dims(diameter=0.8, height=10), (0, 0, 0))
    shape_details.manways(small, [])
    assert "davit-post" not in {p.id for p in small.parts()}  # no manways, no davit


def test_machine_flanges_are_sized_by_the_nozzle_dn():
    """A machine's own flanges take the size of the nozzle's DN (as every other nozzle's
    flange), not of the volute: one DN gives one flange, and a large pipe is never wider than
    its flange."""
    pump = body("pump", Dims(length=2.6, width=1.0, height=1.3), (10, 20, 0), 30)
    od = 0.2191  # DN 200
    for name in ("suction", "discharge"):
        point, _ = pump.flanges[name]
        assert shape_details.fit_flange(pump, pump.to_site(point), od)
    parts = {p.id: p for p in pump.parts()}
    want = shape_details.flange_size(od)[0]
    assert parts["suction-flange"].radius == pytest.approx(want, abs=1e-6)
    assert parts["discharge-flange"].radius == pytest.approx(want, abs=1e-6)
    k = body("compressor", Dims(length=12, width=6, height=5), type_name="CentrifugalCompressor")
    point, _ = k.flanges["inlet-1"]
    assert shape_details.fit_flange(k, k.to_site(point), 1.422)  # DN 1400
    flange = next(p for p in k.parts() if p.id == "stage-1-inlet-flange")
    assert flange.radius > 1.422 / 2
    assert not shape_details.fit_flange(k, (99.0, 99.0, 99.0), 0.1)  # no flange there


def test_detail_is_never_a_solid_and_the_envelope_never_drawn_close_up():
    pump = body("pump", Dims(length=2, width=1, height=1.2))
    for part in pump.parts():
        data = as_dict(part)
        assert (part_solid(data) is None) == (part.lod == 2)
        assert (part_solid(data, detail=True) is None) == (part.lod == 1)


def test_nozzle_flange_and_transmitter():
    parts, face = shape_details.nozzle_flange("N1", (0, 0, 5), (1, 0, 0), 0.1143)
    neck, flange = parts
    assert face[0] == pytest.approx(0.15 + 0.1143 / 2) and flange.end == face
    assert flange.material == "flange" and flange.radius > neck.radius and neck.lod == 2
    inward, at = shape_details.nozzle_flange("N2", (1, 0, 1), (1, 0, 0), 0.2, inward=0.4)
    assert at == (1, 0, 1) and inward[0].start == pytest.approx((0.6, 0, 1))
    low = shape_details.transmitter("I1", (2, 0, 1.5), (1, 0, 0), 0.0)
    stand = next(p for p in low if p.id == "I1/stand")
    assert stand.start[2] == 0.0 and any(p.material == "instrument" for p in low)
    high = shape_details.transmitter("I2", (2, 0, 10.0), (1, 0, 0), 0.0)
    assert not [p for p in high if p.id.endswith("/stand")]


def test_detail_is_deterministic():
    for family, dims, cls, _ in MACHINES:
        a = body(family, dims, (1, 2, 0), 17, type_name=cls)
        b = body(family, dims, (1, 2, 0), 17, type_name=cls)
        assert a.parts() == b.parts() and a.flanges == b.flanges
