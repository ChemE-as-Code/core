"""Tags named in literal texts and off-page texts (``chemeascode.domains.piping.tagrefs``)."""

from pathlib import Path
from types import SimpleNamespace

import pytest

from chemeascode.domains.piping.tagrefs import cross_check_tags, expand, instrument_loop, shape


def _data(prop: str, value: str) -> str:
    return f'<Data property="{prop}"><String>{value}</String></Data>'


def _text(object_id: str, owner: str, text: str, x: float = 10, y: float = 20) -> str:
    """A drawing that represents *owner* with one literal text."""
    return f"""
    <Object id="{object_id}" type="Core/Diagram.RepresentationGroup">
      <References objects="#{owner}" property="Represents"/>
      <Components property="Elements">
        <Object id="{object_id}_T" type="Core/Diagram.Text">
          {_data("Text", text)}
          <Data property="Position"><AggregatedDataValue type="Core/Diagram.Point">
            <Data property="X"><Double>{x}</Double></Data>
            <Data property="Y"><Double>{y}</Double></Data>
          </AggregatedDataValue></Data>
        </Object>
      </Components>
    </Object>"""


def _line(object_id: str, number: str, items: str = "", ends: str = "") -> str:
    return f"""
    <Object id="{object_id}" type="Plant/Piping.PipingNetworkSystem">
      {_data("LineNumber", number)}
      <Components property="Segments">
        <Object id="{object_id}_S1" type="Plant/Piping.PipingNetworkSegment">
          {ends}
          <Components property="Items">{items}</Components>
        </Object>
      </Components>
    </Object>"""


def _connector(object_id: str, direction: str = "In") -> str:
    return (
        f'<Object id="{object_id}" type="Plant/Piping.Flow{direction}PipeOffPageConnector">'
        f'<Components property="Nodes"><Object id="{object_id}_N" type="Plant/Piping.PipingNode"/>'
        "</Components></Object>"
    )


def _instrument(object_id: str, category: str, functions: str, number: str) -> str:
    return (
        f'<Object id="{object_id}" type="Plant/Instrumentation.ProcessInstrumentationFunction">'
        + _data("ProcessInstrumentationFunctionCategory", category)
        + _data("ProcessInstrumentationFunctions", functions)
        + _data("ProcessInstrumentationFunctionNumber", number)
        + "</Object>"
    )


def _equipment(object_id: str, tag: str, kind: str = "Tank") -> str:
    kind = f"Plant/ProcessEquipment.{kind}"
    return f'<Object id="{object_id}" type="{kind}">{_data("TagName", tag)}</Object>'


def _sheet(path: Path, model: str, drawings: str) -> Path:
    path.write_text(
        f"""<?xml version="1.0" encoding="utf-8"?>
<Model><Object id="Model" type="Core/EngineeringModel"><Components property="ConceptualModel">
<Object id="Plant" type="Plant/PlantModel"><Components property="Items">{model}</Components>
</Object></Components>
<Components property="Diagram"><Object id="D" type="Core/Diagram.Diagram">
<Components property="Groups">{drawings}</Components></Object></Components></Object></Model>""",
        encoding="utf-8",
    )
    return path


def _repo(tmp_path: Path, p04_text: str, note: str, p03_text: str = "to P-04 T-4102"):
    """P-03: LN-3001 with a tee where LIN-3001 starts; P-04: LIN-3001 from P-03, tank, pumps."""
    p03 = _sheet(
        tmp_path / "P-03.xml",
        _line("Line_LN", "LN-3001", items='<Object id="Tee_LN" type="Plant/Piping.PipeTee"/>')
        + _line(
            "Line_LIN",
            "LIN-3001",
            items=_connector("OPC_LIN_out", "Out"),
            ends='<References objects="#Tee_LN" property="SourceItem"/>',
        )
        + _line("Line_AIR", "AIR-3005"),
        _text("OPC_LIN_out_D", "OPC_LIN_out", p03_text),
    )
    p04 = _sheet(
        tmp_path / "P-04.xml",
        _line("Line_LIN", "LIN-3001", items=_connector("OPC_LIN_in"))
        + _equipment("T4102", "T-4102")
        + _equipment("P4102A", "P-4102A", "CentrifugalPump")
        + _equipment("P4102B", "P-4102B", "CentrifugalPump")
        + _instrument("LIA4108", "L", "IA", "4108")
        + _instrument("TSLL4114", "T", "SLL", "4114"),
        _text("OPC_LIN_in_D", "OPC_LIN_in", p04_text) + _text("TSLL_D", "TSLL4114", note, 50, 60),
    )
    p02 = _sheet(tmp_path / "P-02.xml", _line("Line_RG", "RG-2001"), "")
    sheets = [(p, f"pid/{p.name}", p.stem) for p in (p02, p03, p04)]
    lists = {
        "equipment": SimpleNamespace(equipment=[SimpleNamespace(tag="E-3101")]),
        "lines": SimpleNamespace(lines=[SimpleNamespace(number="GOX-4001")]),
        "instruments": SimpleNamespace(instruments=[SimpleNamespace(tag="PIC-4101")]),
    }
    found = cross_check_tags(sheets, lists, ["P-01", "P-02", "P-03", "P-04"])
    return [f for f in found if f.level != "info"], [f for f in found if f.level == "info"]


GOOD_NOTE = "LALL-4108 / TSLL-4114 trip P-4102A/B"


def test_tokens():
    assert expand("P-4102A/B") == ["P-4102A", "P-4102B"]
    assert expand("K-4101") == ["K-4101"]
    assert shape("P-4102A") == ("P", 4) and shape("P-03") == ("P", 2)
    assert instrument_loop("LIA-4108") == instrument_loop("LALL-4108") == ("L", "4108")
    assert instrument_loop("PV-4112") is None  # a valve
    assert instrument_loop("P-4102A") is None  # equipment


def test_consistent_texts_raise_nothing_and_are_reported_as_info(tmp_path: Path):
    warnings, infos = _repo(tmp_path, "from P-03 LIN-3001 (subcooled)", GOOD_NOTE)
    assert warnings == []
    note = next(f for f in infos if "LALL-4108" in f.message)
    assert "LALL-4108 (instrument loop)" in note.message
    assert "P-4102A (equipment), P-4102B (equipment)" in note.message
    assert note.rule == "cheme.label-tag" and note.ids == ["TSLL4114"]


def test_line_named_by_a_neighbouring_code_is_an_offpage_mismatch(tmp_path: Path):
    warnings, _ = _repo(tmp_path, "from P-03 LN-3001 (subcooled)", GOOD_NOTE)
    assert [f.rule for f in warnings] == ["cheme.offpage-mismatch"]
    assert "names line LN-3001, but the connector is on line LIN-3001" in warnings[0].message
    assert warnings[0].ids == ["OPC_LIN_in", "LIN-3001"]
    assert warnings[0].file == "pid/P-04.xml" and warnings[0].line


def test_upstream_line_the_connector_line_branches_from_is_fine(tmp_path: Path):
    # LIN-3001 starts at a tee on LN-3001 on P-03; LN-3001 has another number, so it is read as
    # "branching off LN-3001", as "from P-04 GAN-4002" on UN-3001 in the ASU.
    warnings, _ = _repo(tmp_path, "from P-03 LN-3002", GOOD_NOTE)
    assert [f.rule for f in warnings] == ["cheme.label-tag-unknown"]  # LN-3002 is not a line
    warnings, _ = _repo(tmp_path, "from P-03 AIR-3005", GOOD_NOTE)
    assert len(warnings) == 1 and "which line LIN-3001 does not join on P-03" in warnings[0].message


def test_connector_naming_a_sheet_without_the_line(tmp_path: Path):
    warnings, _ = _repo(tmp_path, "from P-02 LIN-3001", GOOD_NOTE)
    assert [f.rule for f in warnings] == ["cheme.offpage-mismatch"]
    assert "names sheet P-02, which does not carry line LIN-3001" in warnings[0].message
    warnings, _ = _repo(tmp_path, "from P-07 LIN-3001", GOOD_NOTE)
    assert [f.rule for f in warnings] == ["cheme.label-tag-unknown"]
    assert "names sheet P-07, which plant.yaml does not declare" in warnings[0].message
    warnings, _ = _repo(tmp_path, "from P-03 LIN-3001", GOOD_NOTE, p03_text="to P-02 T-4102")
    assert ["P-02" in f.message for f in warnings] == [True]


@pytest.mark.parametrize(
    ("note", "unknown"),
    [
        ("LALL-4108 / TSLL-4114 trip P-4199A/B", ["P-4199A", "P-4199B"]),  # equipment, A/B
        ("LALL-4199 / TSLL-4114 trip P-4102A", ["LALL-4199"]),  # an instrument loop
        ("TSLL-4115 trips T-4102", ["TSLL-4115"]),  # an instrument
        ("see LIN-3009 and K-9", ["LIN-3009"]),  # a line; "K-9" has no known shape
        ("trip E-3101 and PIC-4101 (lists)", []),  # tags from the lists
        ("EN 13480, ISO-9001", []),  # not tag-like here
    ],
)
def test_unknown_tags_in_a_note(tmp_path: Path, note: str, unknown: list[str]):
    warnings, _ = _repo(tmp_path, "from P-03 LIN-3001", note)
    assert [f.rule for f in warnings] == ["cheme.label-tag-unknown"] * len(unknown)
    assert [f.ids[-1] for f in warnings] == unknown
