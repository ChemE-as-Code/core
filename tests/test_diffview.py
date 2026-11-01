from lxml import etree

from chemeascode.domains.piping.diffview import _represented_by, diff_sheet
from chemeascode.domains.piping.fmt import format_file

SHEET = b"""<Model>
  <Object type="Core/EngineeringModel" id="Model1">
    <Object type="Equipment/Pump" id="Pump1">
      <Object type="Equipment/Nozzle" id="Nozzle1"/>
    </Object>
    <Object type="Core/Diagram.Diagram" id="Drawing1">
      <References property="Represents" objects="#PlantModel1"/>
      <Object type="Core/Diagram.RepresentationGroup" id="Pump1_Drawing">
        <References property="Represents" objects="#Pump1"/>
        <Object type="Core/Diagram.ShapeUsage" id="Pump1_Shape"/>
      </Object>
      <Object type="Core/Diagram.Label" id="SheetLabel"/>
    </Object>
  </Object>
</Model>"""


def test_owner_of_drawing_is_the_represented_object_not_the_sheet():
    drawn, owner = _represented_by(etree.fromstring(SHEET))
    # What the diagram represents is the whole sheet: the SVG has no <g> for it.
    # The sheet's own label is drawn under its own id (render names it).
    assert drawn == {"Pump1", "SheetLabel"}
    assert owner["Pump1"] == "Pump1"
    assert owner["Nozzle1"] == "Pump1"
    assert owner["Pump1_Drawing"] == "Pump1"
    assert owner["Pump1_Shape"] == "Pump1"
    # Nothing maps to the whole-sheet object, or the entire sheet would be highlighted.
    assert "PlantModel1" not in owner.values()
    assert owner["SheetLabel"] == "SheetLabel"


PLANT_SHEET = b"""<Model>
  <Object type="Core/EngineeringModel" id="Model1">
    <Object type="Plant/PlantModel" id="PlantModel1">
      <Object type="Plant/Diagram.PlantMetaData" id="PlantMetaData1"/>
      <Object type="Plant/Instrumentation.InstrumentationLoopFunction" id="Loop1"/>
      <Object type="Plant/ProcessEquipment.CentrifugalPump" id="Pump1">
        <Object type="Plant/ProcessEquipment.ProcessNozzle" id="Nozzle1"/>
      </Object>
    </Object>
    <Object type="Core/Diagram.Diagram" id="Drawing1">
      <References property="Represents" objects="#PlantModel1"/>
      <Object type="Core/Diagram.RepresentationGroup" id="Pump1_Drawing">
        <References property="Represents" objects="#Pump1"/>
      </Object>
      <Object type="Core/Diagram.Label" id="TitleBlock">
        <Object type="Core/Diagram.AttributeRepresentation" id="TitleBlock_Date">
          <References property="Object" objects="#PlantMetaData1"/>
        </Object>
      </Object>
    </Object>
  </Object>
</Model>"""


def test_objects_under_the_plant_model_do_not_map_to_the_whole_sheet():
    drawn, owner = _represented_by(etree.fromstring(PLANT_SHEET))
    assert drawn == {"Pump1", "TitleBlock"}
    assert owner["Nozzle1"] == "Pump1"
    for object_id in ("PlantModel1", "Loop1", "Model1", "Drawing1"):
        assert object_id not in owner
    # The metadata is shown in the title block, so it maps there, not to the sheet.
    assert owner["PlantMetaData1"] == "TitleBlock"
    assert owner["TitleBlock_Date"] == "TitleBlock"
    assert set(owner.values()) == {"Pump1", "TitleBlock"}


def test_a_sheet_on_one_side_lists_every_object(plant):
    import re

    content = (plant / "pid" / "P-01.xml").read_bytes()
    added = diff_sheet(None, content, "pid/P-01.xml", "HEAD", "working tree")
    assert added.status == "added" and added.changes
    assert {c.kind for c in added.changes} == {"added"}
    assert added.new_highlight and set(added.new_highlight.values()) == {"added"}
    svg_ids = set(re.findall(r' id="([^"]+)"', added.new_svg))
    assert set(added.new_highlight) <= svg_ids
    assert set(added.new_owner.values()) <= svg_ids
    removed = diff_sheet(content, None, "pid/P-01.xml", "HEAD", "working tree")
    assert removed.status == "removed"
    assert {c.kind for c in removed.changes} == {"removed"}
    assert len(removed.changes) == len(added.changes)
    assert removed.old_highlight and not removed.new_highlight


def test_metadata_change_highlights_the_title_block(plant):
    import re

    format_file(plant / "pid" / "P-01.xml")  # stable ids, so only the date differs
    content = (plant / "pid" / "P-01.xml").read_bytes()
    assert b"2016-04-01" in content
    changed = diff_sheet(content, content.replace(b"2016-04-01", b"2026-10-17", 1), "p", "a", "b")
    assert [c.object_type for c in changed.changes] == ["PlantMetaData"]
    (title_block,) = set(changed.new_highlight)
    assert changed.new_highlight == changed.old_highlight == {title_block: "modified"}
    metadata_id = changed.changes[0].object_id
    assert changed.new_owner == changed.old_owner == {metadata_id: title_block}
    # The rendered SVG has a <g> with that id: the title block Label, not the whole sheet.
    groups = re.findall(r'<g class="([^"]+)" id="([^"]+)"', changed.new_svg)
    assert ("label", title_block) in groups
    assert not title_block.startswith("diagram-")


def _dangling_shape(content: bytes) -> bytes:
    """*content* with one Shape reference pointing nowhere: it loads, but does not draw."""
    import re

    return re.sub(
        rb'objects="#[^"]*" property="Shape"',
        b'objects="#NoSuchShape" property="Shape"',
        content,
        count=1,
    )


def test_a_side_that_does_not_load_is_reported_not_raised(plant):
    """A truncated sheet gives an error, the loaded side's drawing and no changes."""
    content = (plant / "pid" / "P-01.xml").read_bytes()
    result = diff_sheet(content, content[:5000], "pid/P-01.xml", "HEAD", "working tree")
    assert result.error.startswith("cannot compare: working tree does not load: XMLSyntaxError")
    assert "\n" not in result.error
    assert result.changes == [] and result.projection_diff == ""
    assert "<svg" in result.old_svg and result.new_svg == ""
    added = diff_sheet(None, content[:5000], "pid/P-01.xml", "HEAD", "working tree")
    assert added.status == "added" and added.error and not added.changes


def test_a_side_that_does_not_draw_still_lists_the_changes(plant):
    """A dangling Shape reference loads but breaks the SVG export: the diff is still made."""
    content = (plant / "pid" / "P-01.xml").read_bytes()
    result = diff_sheet(content, _dangling_shape(content), "pid/P-01.xml", "HEAD", "b")
    assert result.error.startswith("cannot draw b: AttributeError")
    assert "<svg" in result.old_svg and result.new_svg == ""
    assert result.changes and result.projection_diff
