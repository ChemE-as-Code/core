"""Piping detail of the 3D model (``domains/spatial/piping_detail.py``): valve bodies and
operators, supports on the steel, jacketing."""

import pytest

from chemeascode.domains.spatial.geometry3d import part_solid
from chemeascode.domains.spatial.piping_detail import (
    inline_parts,
    jacket,
    stem_of,
    supports,
    valve_parts,
)


def valve(cls, kind="valve", direction=(1, 0, 0), dn=None):
    item = {
        "id": "P/V1",
        "kind": kind,
        "dexpi_class": cls,
        "point": (0, 0, 3),
        "direction": direction,
    }
    if dn is not None:
        item["dn"] = dn
    return item


def ids(parts):
    return {p["id"].split("/", 2)[-1] for p in parts}


def test_valves_get_bodies_flanges_and_their_operators():
    gate = valve_parts(valve("GateValve"), 0.1143)
    assert {"flange-1", "flange-2", "body", "stem", "handwheel"} <= ids(gate)
    wheel = next(p for p in gate if p["id"].endswith("/handwheel"))
    assert wheel["kind"] == "torus" and wheel["axis"] == (0.0, 0.0, 1.0)
    assert wheel["centre"][2] > 3.2  # above the pipe on its stem
    assert all(p["lod"] == 2 for p in gate)  # detail only: never a solid
    assert all(part_solid(p) is None for p in gate)
    ball = valve_parts(valve("BallValve", dn=80), 0.0889)
    assert "lever" in ids(ball)
    big = valve_parts(valve("BallValve", dn=300), 0.3239)
    assert {"gearbox", "handwheel"} <= ids(big)
    control = valve_parts(valve("GlobeControlValve"), 0.1143)
    assert {"yoke", "actuator-lower", "actuator-upper"} <= ids(control)
    mov = valve_parts(valve("MotorOperatedGateValve"), 0.2191)
    assert {"actuator", "motor"} <= ids(mov)
    psv = valve_parts(valve("SpringLoadedGlobeSafetyValve", "safety_valve"), 0.0603)
    assert {"bonnet", "cap", "outlet", "outlet-flange"} <= ids(psv)
    check = valve_parts(valve("SwingCheckValve", "check_valve"), 0.1143)
    assert "cover" in ids(check) and "handwheel" not in ids(check)
    butterfly = valve_parts(valve("ButterflyValve", dn=100), 0.1143)
    body = next(p for p in butterfly if p["id"].endswith("/body"))
    assert body["end"][0] - body["start"][0] < 0.1  # a wafer


def test_a_valve_on_a_vertical_pipe_has_its_stem_across():
    up = stem_of((0, 0, 1))
    assert up[2] == pytest.approx(0) and abs(up[0]) + abs(up[1]) == pytest.approx(1)
    assert stem_of((1, 0, 0)) == (0.0, 0.0, 1.0)


def test_inline_parts_use_the_pipe_od():
    document = {
        "pipes": [{"id": "P/S1", "od": 0.2191, "dn": 200}],
        "inline": [
            {**valve("GlobeValve"), "pipe": "P/S1"},
            {**valve("Silencer", "silencer"), "id": "P/X", "pipe": "P/S1"},
        ],
    }
    inline_parts(document)
    first, silencer = document["inline"]
    flange = next(p for p in first["parts"] if p["id"].endswith("/flange-1"))
    assert flange["radius"] > 0.2191 / 2
    assert "parts" not in silencer


def test_pipes_rest_on_shoes_and_every_third_on_a_rack_is_a_guide():
    beams = [
        {
            "id": f"R/bent-{k}/beam-5",
            "kind": "member",
            "material": "steel",
            "start": [6.0 * k, -2, 4.8],
            "end": [6.0 * k, 2, 4.8],
            "profile": [0.3, 0.4],
        }
        for k in range(5)
    ]
    document = {
        "racks": [{"id": "R", "parts": beams}],
        "structures": [],
        "pipes": [
            {
                "id": "P/S1",
                "line": "L-1",
                "segment": "S1",
                "od": 0.1143,
                "insulation_mm": 0,
                "points": [[-1, 0, 5.0 + 0.1143 / 2], [25, 0, 5.0 + 0.1143 / 2]],
            },
            {
                "id": "P/S2",
                "line": "L-2",
                "segment": "S2",
                "od": 0.1143,
                "insulation_mm": 0,
                "points": [[-1, 1, 7.0], [25, 1, 7.0]],  # well above the beams: none
            },
        ],
    }
    found = supports(document)
    assert [s["kind"] for s in found] == ["shoe", "shoe", "guide", "shoe", "shoe"]
    first = found[0]
    assert first["pipe"] == "P/S1" and first["on"] == "R/bent-0/beam-5"
    assert first["point"] == pytest.approx((0, 0, 5.0))
    assert len(found[2]["parts"]) == 3  # a shoe and two stops
    assert supports(document) == found  # deterministic


def test_jacketing_follows_the_insulation_text():
    assert jacket(0, "cold (PUR)") is None
    assert jacket(80, "cold (PUR)") == "cold"
    assert jacket(50, "vacuum jacketed") == "cold"
    assert jacket(50, "hot, mineral wool") == "hot"
    assert jacket(30, "personnel protection") == "personnel"
