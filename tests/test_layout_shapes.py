"""The parametric equipment shapes of ``domains/spatial/shapes.py``."""

import math

import pytest

from chemeascode.domains.spatial.shapes import (
    Dims,
    body,
    family_for,
    shape_of,
)


def close(a, b, tol=1e-6):
    return all(abs(x - y) <= tol for x, y in zip(a, b, strict=True))


def test_families_from_dexpi_classes():
    assert family_for("ProcessColumn") == "column"
    assert family_for("PressureVessel") == "vessel"
    assert family_for("Tank") == "tank"
    assert family_for("TubularHeatExchanger") == "shell_tube"
    assert family_for("PlateHeatExchanger") == "plate_exchanger"
    assert family_for("AirCoolingSystem") == "air_cooler"
    assert family_for("CentrifugalPump") == "pump"
    assert family_for("ReciprocatingPump") == "pump"
    assert family_for("CentrifugalCompressor") == "compressor"
    assert family_for("Blower") == "compressor"
    assert family_for("Turbine") == "turbine"
    assert family_for("GasFilter") == "filter"
    assert family_for("Silencer") == "silencer"
    assert family_for("Stack") == "stack"
    assert family_for("Plant/ProcessEquipment.Tank") == "tank"
    assert family_for("SubmersiblePump") == "pump"  # by its ending
    assert family_for("ElectricHeater") == "generic"
    assert family_for(None) == "generic"


def test_shape_follows_the_dimensions():
    assert shape_of("vessel", Dims(diameter=2, height=6)) == "vertical_cylinder"
    assert shape_of("vessel", Dims(diameter=2, length=6)) == "horizontal_cylinder"
    assert shape_of("generic", Dims(diameter=2)) == "sphere"
    assert shape_of("pump", Dims(length=2, width=1, height=1)) == "box"
    assert shape_of("shell_tube", None) == "horizontal_cylinder"
    assert shape_of("pump", None) == "box"
    assert shape_of("pump", Dims(length=2, width=1, height=1), "vertical_cylinder") == (
        "vertical_cylinder"
    )


def test_a_column_has_skirt_heads_and_shell_within_its_height():
    column = body("column", Dims(diameter=4, height=25), (10, 20, 0), detail=False)
    parts = {p.id: p for p in column.parts()}
    assert list(parts) == ["skirt", "head-bottom", "shell", "head-top"]
    assert column.bbox() == (8, 18, 0, 12, 22, 25)
    skirt, shell, top = parts["skirt"], parts["shell"], parts["head-top"]
    assert skirt.start == (10, 20, 0) and skirt.end[2] == pytest.approx(3.0)
    assert shell.radius == 2 and shell.material == "shell"
    assert top.kind == "cap" and top.depth == pytest.approx(1.0)  # 2:1 ellipsoidal: D/4
    assert top.centre[2] + top.depth == pytest.approx(25)
    assert parts["head-bottom"].axis == (0, 0, -1)


def test_a_tank_has_a_flat_bottom_and_a_cone_roof():
    tank = body("tank", Dims(diameter=8, height=10), (0, 0, 0), detail=False)
    parts = {p.id: p for p in tank.parts()}
    assert list(parts) == ["shell", "roof"]
    assert parts["shell"].start == (0, 0, 0)
    assert parts["roof"].kind == "cone" and parts["roof"].end == (0, 0, 10)
    dome = body("tank", Dims(diameter=8, height=10, head="dome_roof"))
    envelope = [p for p in dome.parts() if p.lod is None]
    assert [p.kind for p in envelope][:2] == ["cylinder", "cap"]
    # besides the shell and roof only the stair, its landing and handrail are solids
    assert all(p.id.startswith("stair-") for p in envelope[2:])


def test_vertical_nozzle_anchors():
    vessel = body("vessel", Dims(diameter=2, height=8), (5, 5, 1))
    side = vessel.anchor(angle_deg=90, elevation=4)
    assert close(side.point, (5, 6, 5)) and close(side.direction, (0, 1, 0))
    top = vessel.anchor(face="top")
    assert close(top.point, (5, 5, 9)) and top.direction == (0, 0, 1)
    off_axis = vessel.anchor(face="top", offset=(0.6, 0))
    assert off_axis.point[2] < 9 and off_axis.point[0] == pytest.approx(5.6)
    bottom = vessel.anchor(face="bottom")
    assert bottom.direction == (0, 0, -1) and bottom.point[2] > 1  # under the skirt's top
    north = vessel.anchor(face="north", offset=(0, 1))
    assert close(north.direction, (0, 1, 0))
    middle = (vessel.shell_bottom + vessel.shell_top) / 2
    assert north.point[2] == pytest.approx(1 + middle + 1)


def test_rotation_turns_anchors_parts_and_boxes():
    drum = body("horizontal_vessel", Dims(diameter=2, length=8), (0, 0, 0), 90)
    assert close(drum.bbox(), (-1, -4, 0, 1, 4, 2))
    front = drum.anchor(face="front")
    assert close(front.direction, (0, -1, 0))  # the front end (own -x) now faces south
    assert front.point[1] == pytest.approx(-4) and front.point[2] == pytest.approx(1)
    top = drum.anchor(angle_deg=0, along=2)
    assert close(top.point, (0, -2, 2)) and close(top.direction, (0, 0, 1))
    side = drum.anchor(angle_deg=90, along=4)  # own +y is west after turning 90 degrees
    assert close(side.point, (-1, 0, 1)) and close(side.direction, (-1, 0, 0))
    shell = next(p for p in drum.parts() if p.id == "shell")
    assert shell.start[0] == pytest.approx(0) and shell.start[1] < 0 < shell.end[1]
    turned = body("generic", Dims(length=4, width=1, height=1), (0, 0, 0), 30)
    hx = (4 * math.cos(math.radians(30)) + 1 * math.sin(math.radians(30))) / 2
    assert turned.bbox()[3] == pytest.approx(hx)
    assert turned.parts()[0].rotation_deg == pytest.approx(30)
    east = turned.anchor(angle_deg=0, elevation=0.5)
    assert close(east.direction, (math.cos(math.radians(30)), math.sin(math.radians(30)), 0))


def test_horizontal_saddles_lift_the_shell():
    drum = body("vessel", Dims(diameter=2, length=8, height=3))
    assert drum.family == "horizontal_vessel" and drum.extent == (8, 2, 3)
    assert [p.id for p in drum.parts() if p.lod is None][-2:] == ["saddle-1", "saddle-2"]
    assert drum.anchor(angle_deg=180).point[2] == pytest.approx(1)


def test_shell_and_tube_bundle_pull_envelope():
    exchanger = body("shell_tube", Dims(diameter=1, length=6), (10, 0, 0), bundle_length=4.5)
    parts = [p.id for p in exchanger.parts() if p.lod is None]
    assert parts == ["bonnet", "channel", "shell", "head-back"]
    (pull,) = exchanger.envelopes()
    assert pull.kind == "bundle_pull" and pull.size == (4.5, 1, 1)
    assert pull.centre[0] == pytest.approx(10 - 3 - 2.25)  # in front of the channel end
    front = exchanger.anchor(face="front")
    assert front.point[0] == pytest.approx(7) and front.direction == (-1, 0, 0)
    default = body("shell_tube", Dims(diameter=1, length=6)).envelopes()[0]
    assert default.size[0] == pytest.approx(0.85 * 6)


def test_pump_parts_envelopes_and_nozzles():
    pump = body("pump", Dims(length=2, width=1, height=1.2), (5, 5, 0))
    assert pump.variant == "end_suction" and pump.grade
    envelope = [p.id for p in pump.parts() if p.lod != 2]
    assert envelope == [
        "plinth",
        "baseplate",
        "casing",
        "discharge",
        "coupling-guard",
        "motor",
        "terminal-box",
    ]
    materials = {p.material for p in pump.parts()}
    assert {"concrete", "steel", "casing", "flange", "guard", "motor"} <= materials
    kinds = {e.kind: e for e in pump.envelopes()}
    assert set(kinds) == {"motor_removal", "access"}
    assert kinds["access"].size == (4, 3, 1.2)
    assert kinds["motor_removal"].centre[0] > 6  # behind the driver end (own +x)
    suction = pump.pid_anchor("left", -1, 0)
    discharge = pump.pid_anchor("top", 0, -1)
    assert suction.flange and discharge.flange  # on the real flanges
    assert suction.direction == (-1, 0, 0) and discharge.direction == (0, 0, 1)
    assert suction.point[0] == pytest.approx(4) and 4 < discharge.point[0] < 5
    assert discharge.point[2] == pytest.approx(1.2)  # the discharge flange's face on top
    assert pump.pid_anchor("right", 1, 0) == discharge  # drawn right: the discharge as well
    assert pump.pid_anchor("bottom", 0, 1).direction == (0, 0, -1)  # a casing drain
    parts = {p.id: p for p in pump.parts()}
    face = parts["suction-flange"]
    assert face.start == pytest.approx(suction.point)  # the nozzle is on the flange's face
    assert parts["discharge-flange"].end == pytest.approx(discharge.point)
    volute = parts["volute"]
    assert volute.kind == "torus" and volute.axis == pytest.approx((1, 0, 0))  # across the shaft
    extra = pump.pid_anchor("top", 0, -1, spread=1)  # a second nozzle on top: on the casing
    assert not extra.flange and extra.point[2] < discharge.point[2]


def test_pid_sides_on_a_vertical_vessel():
    vessel = body("vessel", Dims(diameter=2, height=10))
    top = vessel.pid_anchor("top", 0, -1)
    assert top.direction == (0, 0, 1) and top.point[2] == pytest.approx(10)
    low = vessel.pid_anchor("left", -1, 0.8)
    high = vessel.pid_anchor("left", -1, -0.8)
    assert low.direction[0] == pytest.approx(-1) and low.point[2] < high.point[2]
    right = vessel.pid_anchor("right", 1, 0.0)
    assert right.direction[0] == pytest.approx(1)
    spread = vessel.pid_anchor("right", 1, 0.0, spread=1)
    assert spread.point != right.point and spread.point[2] == pytest.approx(right.point[2])


def test_a_flat_bottom_nozzle_leaves_the_shell_above_the_foundation():
    tank = body("tank", Dims(diameter=8, height=10), (0, 0, 0))
    drain = tank.pid_anchor("bottom", 0.5, 1)
    assert drain.direction == (1, 0, 0) and drain.point == pytest.approx((4, 0, 0.5))
    assert tank.pid_anchor("bottom", 0, 1).direction == pytest.approx((0, -1, 0))


def test_box_faces_and_defaults():
    box = body("generic", Dims(length=4, width=2, height=3), (0, 0, 0))
    assert box.anchor(face="top", offset=(1, 0.5)).point == (1, 0.5, 3)
    west = box.anchor(face="west", offset=(0.5, -1))
    assert west.point == (-2, 0.5, 0.5) and west.direction == (-1, 0, 0)
    assert box.anchor(face="front").point == box.anchor(face="west").point
    assert box.anchor(face="north").direction == (0, 1, 0)
    corner = box.anchor(angle_deg=90, elevation=1)
    assert close(corner.point, (0, 1, 1)) and close(corner.direction, (0, 1, 0))
    defaults = [box.default_anchor(i, 3).point for i in range(3)]
    assert len(set(defaults)) == 3 and all(p[2] == 3 for p in defaults)
    with pytest.raises(ValueError):
        box.anchor(face="up")


def test_missing_sizes_come_from_the_family_and_the_shape_falls_back():
    assert body("pump", None).extent == (1.8, 0.8, 1.0)
    assert body("column", Dims(diameter=3)).dims.height == 20
    odd = body("pump", Dims(diameter=1, height=2))  # a round pump: drawn as a plain cylinder
    assert odd.family == "generic" and odd.shape == "vertical_cylinder"
    assert body("plate_exchanger", Dims(length=1.5, width=0.8, height=1.8)).parts()[2].id == (
        "plates"
    )
    cooler = body("air_cooler", Dims(length=8, width=4, height=5))
    assert sum(p.id.startswith("fan-") and p.lod == 1 for p in cooler.parts()) == 2


def test_shapes_are_deterministic():
    a = body("column", Dims(diameter=4, height=25), (1, 2, 3), 33)
    b = body("column", Dims(diameter=4, height=25), (1, 2, 3), 33)
    assert a.parts() == b.parts() and a.envelopes() == b.envelopes()
    assert a.pid_anchor("left", -1, 0.3) == b.pid_anchor("left", -1, 0.3)
