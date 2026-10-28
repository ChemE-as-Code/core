from pathlib import Path

from lxml import etree

from chemeascode.domains.piping.show import Sheet, element_spans, show
from tests.conftest import REFERENCE

SMALL = b"""<?xml version="1.0"?>
<!-- a comment with <Object> inside -->
<Model>
  <Object id="A" type="Plant/ProcessEquipment.Tank" note="a > b">
    <Data property="TagName"><String>T-1</String></Data>
    <Object id="B" type="Plant/ProcessEquipment.ProcessNozzle"/>
  </Object>
  <Object id="C"
          type="Plant/Piping.Pipe">
    <References objects="#B" property="SourceItem"/>
    <References objects="#Gone" property="TargetItem"/>
  </Object>
</Model>
"""


def test_element_spans_follow_document_order():
    root = etree.fromstring(SMALL)
    elements = [e for e in root.iter() if isinstance(e.tag, str)]
    spans = element_spans(SMALL)
    assert len(spans) == len(elements)
    by_id = {e.get("id"): span for e, span in zip(elements, spans, strict=True) if e.get("id")}
    assert by_id == {"A": (4, 7), "B": (6, 6), "C": (8, 12)}
    assert spans[0] == (3, 13)  # <Model>


def test_show_lists_references_both_ways(tmp_path: Path):
    path = tmp_path / "s.xml"
    path.write_bytes(SMALL)
    lines, found = show("B", [(path, "pid/s.xml")])
    assert found
    assert lines[0] == "pid/s.xml:6 ProcessNozzle B"
    assert "  owner: A (Tank T-1) pid/s.xml:4" in lines
    assert "    pid/s.xml:10 C (Pipe) SourceItem" in lines

    lines, _ = show("C", [(path, "pid/s.xml")])
    assert "    pid/s.xml:10 SourceItem -> B (ProcessNozzle) pid/s.xml:6" in lines
    assert "    pid/s.xml:11 TargetItem -> Gone (missing: no object has this id)" in lines


def test_show_by_tag_loosely_and_suggestions(tmp_path: Path):
    path = tmp_path / "s.xml"
    path.write_bytes(SMALL)
    assert show("t1", [(path, "s.xml")])[0][0] == "s.xml:4-7 Tank A [T-1]"
    lines, found = show("T-2", [(path, "s.xml")])
    assert not found
    assert lines[-1] == "Did you mean: T-1?"


def test_show_reference_instrument_and_line():
    sheet = Sheet.load(REFERENCE, "ref.xml")
    (instrument,) = sheet.find("PICSA 4712.02")
    assert sheet.tag(instrument) == "PICSA-4712.02"
    assert sheet.find("PICSA-4712.02") == sheet.find("PICSA4712.02") == [instrument]

    lines, found = show("47124", [(REFERENCE, "ref.xml")])
    assert found
    text = "\n".join(lines)
    assert "PipingNetworkSystem PipingNetworkSystem4 [47124]" in lines[0]
    assert "segments (3):" in text
    assert "item PipeReducer1 (PipeReducer C3)" in text
    assert "node PipingNode15 DN 50" in text
    assert "ends: SwingCheckValve1.PipingNode13 DN 80 -> PipeReducer1.PipingNode15 DN 50" in text
    assert lines[2].startswith("  drawn by: ") and "(RepresentationGroup)" in lines[2]


def test_show_prints_the_drawing_region():
    lines, found = show("PipeTee1", [(REFERENCE, "ref.xml")])
    assert found
    assert lines[2].endswith(" at 268.999,153.999,269.001,154 mm"), lines[2]


def test_show_unloadable_sheet_still_works(tmp_path: Path):
    path = tmp_path / "bad.xml"
    path.write_text("<Model><Object id='X' type='Plant/Thing'/></Model>")
    lines, found = show("X", [(path, "bad.xml")])
    assert found and lines[0] == "bad.xml:1 Thing X"
    path.write_text("<Model><Object")
    lines, found = show("X", [(path, "bad.xml")])
    assert not found and lines[0].startswith("bad.xml: not well-formed XML")


def test_show_lists_parts_with_what_connects_to_them():
    lines, _ = show("T4750", [(REFERENCE, "ref.xml")])
    parts = [line for line in lines if line.startswith("    Nozzles: ")]
    assert len(parts) == 7
    assert any("(InstrumentNozzle N7)" in p and "SensingLocation" in p for p in parts)


def _section(lines: list[str], title: str) -> list[str]:
    """The lines of one ``  title...`` section of a description."""
    start = next(i for i, line in enumerate(lines) if line.startswith(f"  {title}"))
    end = next(
        (i for i in range(start + 1, len(lines)) if not lines[i].startswith("   ")), len(lines)
    )
    return lines[start:end]


def test_show_follows_the_instrument_chain_from_a_valve():
    lines, _ = show("GlobeValve1", [(REFERENCE, "ref.xml")])
    chain = "\n".join(_section(lines, "instrumentation"))
    assert "instrumentation (1 function(s)):" in chain
    assert "(ProcessInstrumentationFunction PICSA-4712.02)" in chain
    assert "loop: (no id) (InstrumentationLoopFunction 4712.02)" in chain
    assert "actuates: ActuatingFunction1" in chain
    assert "system: ActuatingSystem1 (ActuatingSystem PV4712.02)" in chain
    assert "actuator: ControlledActuator1" in chain
    assert "valve: GlobeValve1 (GlobeValve C1)" in chain
    assert "senses: ProcessSignalGeneratingFunction2" in chain and "BlindFlange2" in chain
    assert "signal: SignalConveyingFunction1" in chain and "-> ActuatingFunction1" in chain
    signal = next(line for line in chain.splitlines() if "signal: " in line)
    assert "drawn by " in signal and " at 365,98,365,98 mm" in signal

    # The same chain from either end, and from the actuating system in between.
    for key in ("PICSA-4712.02", "ActuatingSystem1", "SignalConveyingFunction1"):
        other, _ = show(key, [(REFERENCE, "ref.xml")])
        assert _section(other, "instrumentation") == _section(lines, "instrumentation"), key


def test_show_equipment_lists_nozzle_connections_and_what_only_it_needs():
    lines, _ = show("H1008", [(REFERENCE, "ref.xml")])
    connections = "\n".join(_section(lines, "connections"))
    assert (
        "Nozzle10 (ProcessNozzle N1): segment PipingNetworkSegment15 (PipingNetworkSegment S7)"
        " of line 47126" in connections
    )
    assert "other end: PipeTee4 (PipeTee C8) in PipingNetworkSegment14" in connections
    assert "other end: Tank1 (Tank T4750) nozzle Nozzle12 (ProcessNozzle N6)" in connections
    assert "other end: open" in connections  # 47140 starts nowhere on this sheet
    only = "\n".join(_section(lines, "only for H1008"))
    assert "segment PipingNetworkSegment15 (PipingNetworkSegment S7) of line 47126" in only
    assert "branch tee PipeTee4 (PipeTee C8)" in only and "serves only this" in only
    assert "line PipingNetworkSystem10 (PipingNetworkSystem 47140)" in only
    assert "line PipingNetworkSystem11 (PipingNetworkSystem 47141)" in only
    assert "GlobeValve3 (GlobeValve C1) is in the instrument chain of" in only
    assert "cheme show TICSA-4750.03" in only
    assert "47127" not in only  # it runs on to the tank

    # P4711's suction line comes from another sheet: nothing exists only for the pump.
    lines, _ = show("P4711", [(REFERENCE, "ref.xml")])
    assert "FlowInPipeOffPageConnector1" in "\n".join(_section(lines, "connections"))
    assert not any(line.startswith("  only for") for line in lines)

    lines, _ = show("T4750", [(REFERENCE, "ref.xml")])
    connections = "\n".join(_section(lines, "connections"))
    assert "Nozzle18 (ProcessNozzle N3): nothing" in connections
    assert (
        "Nozzle17 (InstrumentNozzle N7): instrument ProcessSignalGeneratingFunction3" in connections
    )
    assert "TICSA-4750.03" in "\n".join(_section(lines, "instrumentation"))
