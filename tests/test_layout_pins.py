"""``cheme layout pin`` edits the layout files as text: block style, flow style and comments
stay, the entry lands in the list it belongs to, and nothing invalid is written."""

from pathlib import Path

import pytest
import yaml

from chemeascode.domains.spatial.pins import PinError, pin
from chemeascode.domains.spatial.schemas import PlacementList, StructureList


def _stair(local: str = "stair-to-L2") -> dict:
    return {
        "id": f"S1/{local}",
        "source": "generated",
        "from": "L1",
        "to": "L2",
        "side": "south",
        "offset": 0.0,
        "width": 0.9,
        "flights": 1,
    }


def _ladder() -> dict:
    return {
        "id": "S1/ladder-to-L2",
        "source": "generated",
        "from": "L1",
        "to": "L2",
        "at": [0.5, 4.5],
        "facing": "north",
        "base": [0.5, 4.5, 4.0],
    }


def _level() -> dict:
    return {
        "id": "L2-out",
        "source": "generated",
        "title": "outside",
        "elevation": 8.0,
        "kind": "platform",
        "extent": [0.0, -1.7, 6.0, -0.2],
    }


def _model(stairs=(), ladders=(), levels=()) -> dict:
    return {
        "structures": [
            {
                "id": "S1",
                "levels": list(levels),
                "stairs": list(stairs),
                "ladders": list(ladders),
            }
        ]
    }


BLOCK = """\
# frames
structures:
  - id: S1
    origin: [22, 19]
    spans_x: [6]
    spans_y: [5]
    stairs:
      - id: ST1
        from: grade
        to: L1
        side: south  # the main stair
    ladders:
      - id: LD0
        from: grade
        to: L1
        at: [5.5, 0.5]

    levels:
      - id: L1
        elevation: 4
      - {id: L2, elevation: 8, kind: platform}
  - id: S2
    origin: [0, 0]
    spans_x: [4]
    spans_y: [4]
    levels:
      - {id: L1, elevation: 4}
"""

FLOW = """\
structures:
  - {id: S1, origin: [22, 19], spans_x: [6], spans_y: [5], stairs: [{id: ST1, from: grade, to: L1, side: south}], ladders: [{id: LD0, from: grade, to: L1, at: [5.5, 0.5]}], levels: [{id: L1, elevation: 4}, {id: L2, elevation: 8, kind: platform}]}  # one line
"""  # noqa: E501

MULTILINE_FLOW = """\
structures:
  - id: S1
    origin: [22, 19]
    spans_x: [6]
    spans_y: [5]
    stairs: [
      {id: ST1, from: grade, to: L1, side: south},  # main
    ]
    ladders: [{id: LD0, from: grade, to: L1, at: [5.5, 0.5]}]
    levels: [{id: L1, elevation: 4}, {id: L2, elevation: 8, kind: platform}]
"""

MISSING = """\
structures:
  - id: S1
    origin: [22, 19]
    spans_x: [6]
    spans_y: [5]
    stairs: []
    levels:
      - id: L1
        elevation: 4
      - id: L2
        elevation: 8
        kind: platform
        extent: [0, 0, 6, 5]   # the whole frame
"""


def _write(root: Path, text: str) -> Path:
    path = root / "layout" / "structures.yaml"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text)
    return path


def _frame(path: Path) -> dict:
    data = yaml.safe_load(path.read_text())
    StructureList.model_validate(data)  # the file still validates
    return data["structures"][0]


@pytest.mark.parametrize("text", [BLOCK, FLOW, MULTILINE_FLOW, MISSING])
@pytest.mark.parametrize(
    ("model", "key", "local"),
    [
        (_model(stairs=[_stair()]), "stairs", "stair-to-L2"),
        (_model(ladders=[_ladder()]), "ladders", "ladder-to-L2"),
        (_model(levels=[_level()]), "levels", "L2-out"),
    ],
)
def test_a_pinned_stair_ladder_or_level_lands_in_its_own_list(tmp_path, text, model, key, local):
    path = _write(tmp_path, text)
    before = yaml.safe_load(text)["structures"][0]
    target = f"S1/{local}"
    pin(tmp_path, model, target)
    after = _frame(path)
    assert after[key][-1]["id"] == local
    assert len(after.get(key) or []) == len(before.get(key) or []) + 1
    for other in ("stairs", "ladders", "levels"):  # nothing else changed
        if other != key:
            assert after.get(other) == before.get(other)
    comments = [line[line.index("#") :] for line in text.splitlines() if "#" in line]
    assert all(comment in path.read_text() for comment in comments)


def test_block_style_items_keep_their_comment_and_the_next_structure(tmp_path):
    path = _write(tmp_path, BLOCK)
    pin(tmp_path, _model(stairs=[_stair()]), "S1/stair-to-L2")
    text = path.read_text()
    assert "        side: south  # the main stair\n      - {id: stair-to-L2," in text
    data = yaml.safe_load(text)
    assert [s["id"] for s in data["structures"]] == ["S1", "S2"]
    assert data["structures"][1] == yaml.safe_load(BLOCK)["structures"][1]


def test_pin_refuses_an_id_the_structure_already_declares(tmp_path):
    text = BLOCK.replace("      - id: ST1\n", "      - id: stair-to-L2\n")
    path = _write(tmp_path, text)
    with pytest.raises(PinError, match="already declares stair-to-L2"):
        pin(tmp_path, _model(stairs=[_stair()]), "S1/stair-to-L2")
    assert path.read_text() == text


def test_pin_refuses_to_write_a_file_that_fails_its_schema(tmp_path):
    path = _write(tmp_path, BLOCK)
    stair = _stair() | {"to": "L9"}  # no such level: the schema rejects the result
    with pytest.raises(PinError, match="invalid"):
        pin(tmp_path, _model(stairs=[stair]), "S1/stair-to-L2")
    assert path.read_text() == BLOCK


PLACEMENT_BLOCK = """\
equipment:
  - tag: V-1
    position: [0, 0, 0]
    nozzles:
      - {id: N1, angle_deg: 0, elevation: 3}  # top
  - tag: P-1
    position: [5, 0, 0]
"""


@pytest.mark.parametrize(
    "text",
    [
        PLACEMENT_BLOCK,
        "equipment:\n  - {tag: V-1, position: [0, 0, 0]}  # flow\n"
        "  - {tag: P-1, position: [5, 0, 0]}\n",
        PLACEMENT_BLOCK.replace(
            "    position: [0, 0, 0]\n",
            "    position: [0, 0, 0]\n    access:\n      platforms: []\n      notes: none\n",
        ),
        PLACEMENT_BLOCK.replace(
            "    position: [0, 0, 0]\n", "    position: [0, 0, 0]\n    access:  # to do\n"
        ),
    ],
)
def test_a_pinned_platform_sets_the_placement_access(tmp_path, text):
    path = tmp_path / "layout" / "equipment-placement.yaml"
    path.parent.mkdir(parents=True)
    path.write_text(text)
    model = {
        "equipment": [{"tag": "V-1", "position": [0, 0, 0], "rotation_deg": 0.0}],
        "platforms": [
            {
                "id": "V-1/platform-1",
                "tag": "V-1",
                "source": "generated",
                "item_elevation": 3.0,
                "width": 1.0,
                "ladder": {"base": [0.0, 1.5, 0.0]},
            }
        ],
    }
    pin(tmp_path, model, "V-1/platform-1")
    data = yaml.safe_load(path.read_text())
    PlacementList.model_validate(data)
    first, second = data["equipment"]
    notes = {"notes": "none"} if "notes: none" in text else {}  # the other keys stay
    assert first["access"] == {"platforms": [{"elevation": 3.0}], "ladder_side": 90.0, **notes}
    assert second == {"tag": "P-1", "position": [5, 0, 0]}
    assert first.get("nozzles") == yaml.safe_load(text)["equipment"][0].get("nozzles")


def test_pin_refuses_when_the_text_edit_does_not_give_the_expected_data(tmp_path):
    """A list given once and reused by an alias: appending to the anchored text changes both
    structures, so the data check refuses and nothing is written."""
    text = """\
structures:
  - id: S1
    origin: [0, 0]
    spans_x: [6]
    spans_y: [5]
    levels: &lv
      - {id: L1, elevation: 4}
      - {id: L2, elevation: 8, kind: platform}
    stairs: &st
      - {id: ST1, from: grade, to: L1, side: south}
  - id: S2
    origin: [20, 0]
    spans_x: [6]
    spans_y: [5]
    levels: *lv
    stairs: *st
"""
    path = _write(tmp_path, text)
    with pytest.raises(PinError, match="nothing written"):
        pin(tmp_path, _model(stairs=[_stair()]), "S1/stair-to-L2")
    assert path.read_text() == text


@pytest.mark.parametrize(
    "notes",
    ["reached from C:\\tank\\new walkway", "first line\nsecond line\n", 'a "quoted" word', "yes"],
)
def test_a_pinned_platform_keeps_free_text_notes_exactly(tmp_path, notes):
    """The other keys of a declared access are copied with every
    escape."""
    import json

    text = PLACEMENT_BLOCK.replace(
        "    position: [0, 0, 0]\n",
        f"    position: [0, 0, 0]\n    access: {{platforms: [], notes: {json.dumps(notes)}}}\n",
    )
    path = tmp_path / "layout" / "equipment-placement.yaml"
    path.parent.mkdir(parents=True)
    path.write_text(text)
    model = {
        "equipment": [{"tag": "V-1", "position": [0, 0, 0], "rotation_deg": 0.0}],
        "platforms": [
            {
                "id": "V-1/platform-1",
                "tag": "V-1",
                "source": "generated",
                "item_elevation": 3.0,
                "width": 1.0,
                "ladder": {"base": [0.0, 1.5, 0.0]},
            }
        ],
    }
    pin(tmp_path, model, "V-1/platform-1")
    access = yaml.safe_load(path.read_text())["equipment"][0]["access"]
    assert access["notes"] == notes


@pytest.mark.parametrize("style", ["|", ">-"])
def test_a_platform_pins_over_an_access_ending_in_a_block_note(tmp_path, style):
    """A block scalar as the last key of the access keeps its
    newline."""
    text = PLACEMENT_BLOCK.replace(
        "    position: [0, 0, 0]\n",
        "    position: [0, 0, 0]\n    access:\n      platforms: []\n"
        f"      notes: {style}\n        reached from the deck\n        by the north ladder\n",
    )
    notes = yaml.safe_load(text)["equipment"][0]["access"]["notes"]
    path = tmp_path / "layout" / "equipment-placement.yaml"
    path.parent.mkdir(parents=True)
    path.write_text(text)
    model = {
        "equipment": [{"tag": "V-1", "position": [0, 0, 0], "rotation_deg": 0.0}],
        "platforms": [
            {
                "id": "V-1/platform-1",
                "tag": "V-1",
                "source": "generated",
                "item_elevation": 3.0,
                "width": 1.0,
                "ladder": {"base": [0.0, 1.5, 0.0]},
            }
        ],
    }
    pin(tmp_path, model, "V-1/platform-1")
    first = yaml.safe_load(path.read_text())["equipment"][0]
    assert first["access"]["notes"] == notes and first["access"]["platforms"] == [
        {"elevation": 3.0}
    ]
    assert first["nozzles"] == yaml.safe_load(text)["equipment"][0]["nozzles"]


_PLATFORM_MODEL = {
    "equipment": [{"tag": "V-1", "position": [0, 0, 0], "rotation_deg": 0.0}],
    "platforms": [
        {
            "id": "V-1/platform-1",
            "tag": "V-1",
            "source": "generated",
            "item_elevation": 3.0,
            "width": 1.0,
            "ladder": {"base": [0.0, 1.5, 0.0]},
        }
    ],
}


@pytest.mark.parametrize("style", ["|+", ">+", "|", ">"])
def test_a_platform_pins_after_an_item_ending_in_a_note_with_kept_blank_lines(tmp_path, style):
    """An item without access whose last key is a block note followed
    by a blank line (kept by ``|+``/``>+``) gets its access after the note, which stays as it
    was."""
    text = PLACEMENT_BLOCK.replace(
        "      - {id: N1, angle_deg: 0, elevation: 3}  # top\n",
        "      - {id: N1, angle_deg: 0, elevation: 3}  # top\n"
        f"    notes: {style}\n      reached from the deck\n\n",
    )
    before = yaml.safe_load(text)["equipment"]
    path = tmp_path / "layout" / "equipment-placement.yaml"
    path.parent.mkdir(parents=True)
    path.write_text(text)
    pin(tmp_path, _PLATFORM_MODEL, "V-1/platform-1")
    data = yaml.safe_load(path.read_text())
    PlacementList.model_validate(data)
    first, second = data["equipment"]
    assert first["notes"] == before[0]["notes"]
    assert first["access"] == {"platforms": [{"elevation": 3.0}], "ladder_side": 90.0}
    assert second == before[1]


@pytest.mark.parametrize("style", ["|+", ">+"])
def test_a_stair_pins_after_a_structure_ending_in_a_note_with_kept_blank_lines(tmp_path, style):
    """The same for a structure whose last key is such a note."""
    text = MISSING.replace("    stairs: []\n", "").replace(
        "        extent: [0, 0, 6, 5]   # the whole frame\n",
        "        extent: [0, 0, 6, 5]   # the whole frame\n"
        f"    notes: {style}\n      steel by others\n\n",
    ) + (
        "  - id: S2\n    origin: [0, 0]\n    spans_x: [4]\n    spans_y: [4]\n"
        "    levels:\n      - {id: L1, elevation: 4}\n"
    )
    before = yaml.safe_load(text)["structures"]
    path = _write(tmp_path, text)
    pin(tmp_path, _model(stairs=[_stair()]), "S1/stair-to-L2")
    data = yaml.safe_load(path.read_text())
    StructureList.model_validate(data)
    s1, s2 = data["structures"]
    assert s1["notes"] == before[0]["notes"] and s1["notes"].endswith("\n\n")
    assert [s["id"] for s in s1["stairs"]] == ["stair-to-L2"]
    assert s2 == before[1]


@pytest.mark.parametrize("style", ["|+", ">+"])
def test_a_rack_ladder_pins_after_a_rack_ending_in_a_block_title_with_kept_blank_lines(
    tmp_path, style
):
    """The same for a rack mapping in the site plan (its title)."""
    text = (
        "site: {width: 100, depth: 80}\n"
        "racks:\n"
        "  - id: R1\n"
        "    points: [[10, 10], [60, 10]]\n"
        "    width: 6\n"
        "    levels: [5, 7]\n"
        f"    title: {style}\n"
        "      main rack\n"
        "\n"
        "  - id: R2\n"
        "    points: [[10, 30], [60, 30]]\n"
        "    width: 6\n"
        "    levels: [5]\n"
    )
    before = yaml.safe_load(text)["racks"]
    path = tmp_path / "layout" / "site-plan.yaml"
    path.parent.mkdir(parents=True)
    path.write_text(text)
    model = {
        "racks": [
            {
                "id": "R1",
                "ladders": [{"id": "R1/ladder-start", "source": "generated", "end": "start"}],
            }
        ]
    }
    pin(tmp_path, model, "R1/ladder-start")
    r1, r2 = yaml.safe_load(path.read_text())["racks"]
    assert r1["title"] == before[0]["title"] and r1["title"].endswith("\n\n")
    assert r1["ladders"] == [{"id": "ladder-start", "end": "start"}]
    assert r2 == before[1]


_PIPES = {
    "pipes": [{"id": "P-01/S1", "line": "L-1", "segment": "S1", "points": [[0, 0, 1], [4, 0, 1]]}]
}


def _routing(root: Path, text: str) -> Path:
    path = root / "piping" / "routing.yaml"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text)
    return path


def test_a_pinned_route_keeps_the_entrys_gravity_and_notes(tmp_path):
    """A replaced routing entry keeps what the route does not
    replace."""
    path = _routing(
        tmp_path,
        "lines:\n"
        "  - line: L-1\n    segment: S1\n    gravity: true  # must drain\n"
        "    notes: keep slope to T-1\n    via: [[1, 2, 3]]\n"
        "  - {line: L-2, rack: PR}\n",
    )
    pin(tmp_path, _PIPES, "L-1")
    first, second = yaml.safe_load(path.read_text())["lines"]
    assert first == {
        "line": "L-1",
        "segment": "S1",
        "route": [[0, 0, 1], [4, 0, 1]],
        "gravity": True,
        "notes": "keep slope to T-1",
    }
    assert second == {"line": "L-2", "rack": "PR"}


def test_a_route_pin_that_would_not_change_the_data_is_refused(tmp_path):
    """With ``lines`` given twice the text edit lands in the list the
    loader drops; the data check refuses instead of reporting a pin that changed nothing."""
    text = "lines:\n  - {line: L-9, rack: PR}\nlines:\n  - {line: L-8, rack: PR}\n"
    path = _routing(tmp_path, text)
    with pytest.raises(PinError, match="nothing written"):
        pin(tmp_path, _PIPES, "L-1")
    assert path.read_text() == text


def test_a_valve_platform_is_not_written_when_its_routes_cannot_be(tmp_path):
    """Pinning a valve platform checks the structures and the routing
    file before writing either, so a refusal leaves both as they were."""
    routing = _routing(tmp_path, "typo: 1\n")
    model = _PIPES | {
        "structures": [
            {
                "id": "VP-HV-1",
                "source": "generated",
                "origin": [0.0, 1.0],
                "grid_x": [0.0, 2.0],
                "grid_y": [0.0, 1.5],
                "levels": [{"id": "P1", "elevation": 3.0}],
                "serves": ["P-01/HV-1"],
            }
        ],
        "inline": [{"id": "P-01/HV-1", "pipe": "P-01/S1"}],
    }
    with pytest.raises(PinError, match="routing.yaml invalid"):
        pin(tmp_path, model, "VP-HV-1")
    assert not (tmp_path / "layout" / "structures.yaml").exists()
    assert routing.read_text() == "typo: 1\n"
    routing.write_text("")
    done = pin(tmp_path, model, "VP-HV-1")
    assert done.file == "layout/structures.yaml and piping/routing.yaml"
    assert done.what == ["VP-HV-1", "L-1 S1"]
    assert _frame(tmp_path / "layout" / "structures.yaml")["id"] == "VP-HV-1"
    assert yaml.safe_load(routing.read_text())["lines"][0]["route"] == [[0, 0, 1], [4, 0, 1]]


@pytest.mark.parametrize("intent", ["{line: L-1, rack: PR}", "{line: L-1, skip: later}"])
def test_a_route_pin_leaves_a_line_wide_entry_alone(tmp_path, intent):
    """An entry without a segment is the line's intent, not this
    segment's: a segment without a number appends its route and the line-wide entry stays."""
    path = _routing(tmp_path, f"lines:\n  - {intent}\n")
    pin(tmp_path, _PIPES, "L-1")
    first, second = yaml.safe_load(path.read_text())["lines"]
    assert first == yaml.safe_load(intent)
    assert second == {"line": "L-1", "segment": "S1", "route": [[0, 0, 1], [4, 0, 1]]}
