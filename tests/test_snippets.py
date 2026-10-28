"""The dexpi-xml skill's snippets and the reference facts its text states."""

import importlib.util
import re
from pathlib import Path

import pytest
import yaml
from lxml import etree

from chemeascode.domains.piping.fmt import format_bytes

from .conftest import REFERENCE

ROOT = Path(__file__).resolve().parents[1]
SKILLS = ROOT / "src/chemeascode/domains/piping/skills"
SKILL = SKILLS / "dexpi-xml"
SNIPPETS = sorted((SKILL / "snippets").glob("*.xml"))
SEGMENT = "Plant/Piping.PipingNetworkSegment"


def _load_builder():
    spec = importlib.util.spec_from_file_location(
        "build_snippets", ROOT / "scripts/build_snippets.py"
    )
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


build_snippets = _load_builder()


@pytest.fixture(scope="module")
def reference() -> etree._Element:
    return etree.fromstring(format_bytes(REFERENCE.read_bytes())[0])


def _ref(element: etree._Element, prop: str) -> str | None:
    found = element.find(f"References[@property='{prop}']")
    return found.get("objects").lstrip("#") if found is not None else None


def _data(element: etree._Element, prop: str) -> str | None:
    return element.findtext(f"Data[@property='{prop}']/String")


def _point(element: etree._Element) -> tuple[float, float]:
    point = element.find("Data[@property='Position']/AggregatedDataValue")
    return tuple(float(point.findtext(f"Data[@property='{a}']/Double")) for a in "XY")


def _end_agrees(segment: etree._Element, side: str) -> bool:
    """XML mirror of cheme.segment-ends: the pipe's node, or an owned end item's node."""
    pipes = segment.findall("Components[@property='Connections']/Object")
    pipe = pipes[0] if side == "Source" else pipes[-1]
    item, node = _ref(segment, f"{side}Item"), _ref(segment, f"{side}Node")
    if item != _ref(pipe, f"{side}Item"):
        return False
    if node == _ref(pipe, f"{side}Node"):
        return True
    owned = segment.find(f"Components[@property='Items']/Object[@id='{item}']")
    return owned is not None and owned.find(f".//Object[@id='{node}']") is not None


def test_snippets_are_reproducible(tmp_path: Path):
    build_snippets.main(REFERENCE, tmp_path)
    written = sorted(p.relative_to(tmp_path) for p in tmp_path.rglob("*") if p.is_file())
    assert [Path("snippets") / p.name for p in SNIPPETS] + [Path("shapes.md")] == sorted(
        written, key=lambda p: (p.name == "shapes.md", str(p))
    )
    for relative in written:
        assert (tmp_path / relative).read_bytes() == (SKILL / relative).read_bytes(), relative


@pytest.mark.parametrize("path", SNIPPETS, ids=lambda p: p.name)
def test_every_snippet_fragment_parses(path: Path):
    text = path.read_text(encoding="utf-8")
    if path.name == "empty-sheet.xml":
        assert etree.fromstring(path.read_bytes()).tag == "Model"
        return
    fragments = build_snippets.fragments(text)
    assert fragments and all(f.tag == "Object" and f.get("id") for f in fragments)
    assert len(fragments) == 1 or "Several fragments" in text.splitlines()[0]


def test_snippets_are_verbatim_excerpts(reference: etree._Element):
    """No adaptation: every fragment equals the reference object of the same id."""
    for path in SNIPPETS:
        if path.name == "empty-sheet.xml":
            continue
        for fragment in build_snippets.fragments(path.read_text(encoding="utf-8")):
            original = reference.find(f".//Object[@id='{fragment.get('id')}']")
            assert etree.tostring(fragment, method="c14n") == etree.tostring(
                etree.fromstring(build_snippets.render_snippet(original, "x").split("\n", 1)[1]),
                method="c14n",
            ), (path.name, fragment.get("id"))


def test_snippet_segments_end_where_their_pipes_do():
    segments = [
        segment
        for path in SNIPPETS
        for fragment in build_snippets.fragments(path.read_text(encoding="utf-8"))
        for segment in [fragment, *fragment.iterfind(f".//Object[@type='{SEGMENT}']")]
        if segment.get("type") == SEGMENT
    ]
    assert len(segments) >= 4
    for segment in segments:
        for side in ("Source", "Target"):
            assert _end_agrees(segment, side), (segment.get("id"), side)
    by_id = {s.get("id"): s for s in segments}
    # The run continues where the tee-owning segment ends: consecutive segments share a node.
    run_in, run_out = by_id["PipingNetworkSegment11"], by_id["PipingNetworkSegment12"]
    assert _ref(run_in, "TargetNode") == _ref(run_out, "SourceNode")


def test_reference_segment_ends_all_agree(reference: etree._Element):
    """The convention the skill states holds for every segment of the reference."""
    for segment in reference.iterfind(f".//Object[@type='{SEGMENT}']"):
        if segment.find("Components[@property='Connections']/Object") is None:
            continue
        for side in ("Source", "Target"):
            if _ref(segment, f"{side}Item") is not None:
                assert _end_agrees(segment, side), (segment.get("id"), side)


def test_bubble_geometry_matches_the_skill(reference: etree._Element):
    skill = (SKILL / "SKILL.md").read_text(encoding="utf-8")
    assert "13.5 mm wide, 7.5 mm high" in skill
    shape = reference.find(".//Object[@id='Shape16']")
    arcs = shape.findall(".//Object[@type='Core/Diagram.EllipseArc']")
    right = max(
        float(a.findtext(".//Data[@property='X']/Double"))
        + float(a.findtext("Data[@property='HorizontalSemiAxis']/Double"))
        for a in arcs
    )
    lines = shape.findall(".//Object[@type='Core/Diagram.PolyLine']")
    straight = {
        abs(float(x)) for line in lines for x in line.xpath(".//Data[@property='X']/Double/text()")
    }
    assert (right, straight) == (6.75, {3.0})
    drawing = reference.find(".//Object[@id='ProcessInstrumentationFunction1_Drawing1']")
    cx, cy = _point(drawing.find(".//Object[@type='Core/Diagram.ShapeUsage']"))
    offsets = {
        (x - cx, y - cy)
        for x, y in map(_point, drawing.iterfind("Components[@property='NodePositions']/Object"))
    }
    assert offsets == {(0, -3.75), (0, 3.75), (-6.75, 0), (6.75, 0)}
    for dx, dy in [("x - 6.75", "y"), ("x + 6.75", "y"), ("x", "y - 3.75"), ("x", "y + 3.75")]:
        assert f"({dx}, {dy})" in skill


def _line(reference: etree._Element, number: str):
    for system in reference.iterfind(".//Object[@type='Plant/Piping.PipingNetworkSystem']"):
        if _data(system, "LineNumber") == number:
            return system
    raise AssertionError(number)


def _tag_of(reference: etree._Element, object_id: str) -> str | None:
    found = reference.find(f".//Object[@id='{object_id}']")
    for owner in [found, *found.iterancestors("Object")]:
        if _data(owner, "TagName"):
            return _data(owner, "TagName")
    return None


def test_line_list_example_matches_the_reference(reference: etree._Element):
    """lists-sync's line 47126 example: real ends, and every segment with its own DN."""
    text = (SKILLS / "lists-sync/SKILL.md").read_text(encoding="utf-8")
    block = re.search(r"```yaml\n(.*?)```", text, re.S).group(1)
    (entry,) = yaml.safe_load(re.sub(r"(?m)^ {3}", "", block))
    system = _line(reference, entry["number"])
    segments = system.findall("Components[@property='Segments']/Object")
    first, *_ = segments
    ends = {_tag_of(reference, _ref(s, "TargetItem")) for s in segments} - {None}
    assert entry["from"] == _tag_of(reference, _ref(first, "SourceItem"))
    assert entry["to"] in ends
    line_dn = entry["nominal_diameter"]
    assert line_dn.replace("DN", "DN ") == _data(system, "NominalDiameterRepresentation")
    own_dn = {
        _data(s, "SegmentNumber"): _data(s, "NominalDiameterRepresentation").replace(" ", "")
        for s in segments
        if _data(s, "NominalDiameterRepresentation").replace(" ", "") != line_dn
    }
    assert {s["number"]: s["nominal_diameter"] for s in entry["segments"]} == own_dn
    # dexpi-xml's DN recipe names the same branch segments as the ones to leave alone.
    recipe = (SKILL / "SKILL.md").read_text(encoding="utf-8")
    assert "DN 25 segments S2 drain, S5 and S9 instrument" in re.sub(r"\s+", " ", recipe)
    assert sorted(own_dn) == ["S2", "S5", "S9"]
