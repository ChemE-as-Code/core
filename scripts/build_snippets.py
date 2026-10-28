"""Extract the dexpi-xml skill's snippets from the DEXPI 2.0.1 reference P&ID.

Usage: uv run python scripts/build_snippets.py <path to DEXPI 2.0.1 reference_pid.xml>

The reference P&ID is (c) DEXPI e.V., CC BY 4.0 (DEXPI Specification 2.0.1). The snippets are
excerpts of it, formatted by `cheme fmt`; see the skill's NOTICE.md. Rerun this script rather
than editing the snippets by hand.
"""

from __future__ import annotations

import copy
import sys
from pathlib import Path

from lxml import etree

from chemeascode.domains.piping.authoring.shapes import ADDED_SHAPES
from chemeascode.domains.piping.fmt import format_bytes
from chemeascode.domains.piping.sheets import (
    PLACEHOLDER_DIAGRAM_NAME,
    PLACEHOLDER_MODEL_NAME,
    PLACEHOLDER_MODEL_URI,
    refresh_title_block,
)

OUT = Path(__file__).resolve().parents[1] / "src/chemeascode/domains/piping/skills/dexpi-xml"


def render_snippet(elements: etree._Element | list, note: str) -> str:
    """One excerpt, or several fragments each introduced by a ``(where, element)`` pair.

    The elements are copied verbatim (re-indented only), so segment ends keep the reference
    convention that ``cheme.segment-ends`` accepts.
    """
    if not isinstance(elements, list):
        elements = [(None, elements)]
    parts = []
    for where, element in elements:
        element = copy.deepcopy(element)
        element.tail = None
        etree.indent(element, space="  ")
        if where:
            parts.append(f"<!-- {where} -->\n")
        parts.append(etree.tostring(element, encoding="unicode", pretty_print=True))
    header = f"<!-- {note} Excerpt of the DEXPI 2.0.1 reference P&ID, CC BY 4.0."
    if len(elements) > 1:
        header += " Several fragments, not one document: paste each where its comment says."
    return header + " -->\n" + "".join(parts)


def fragments(text: str) -> list[etree._Element]:
    """Parse a snippet back into its top-level elements (the inverse of ``render_snippet``)."""
    wrapper = etree.fromstring(f"<snippet>{text}</snippet>".encode())
    return [child for child in wrapper if isinstance(child.tag, str)]


def _by_id(root: etree._Element, object_id: str) -> etree._Element:
    found = root.find(f".//Object[@id='{object_id}']")
    if found is None:
        raise SystemExit(f"no object {object_id} in the reference P&ID")
    return found


def skeleton(root: etree._Element) -> etree._Element:
    """The reference sheet emptied: metadata, border, title block and shape catalogue only.

    cheme-as-code's added shapes (``chemeascode.domains.piping.authoring.shapes``) follow the
    reference's in the catalogue.
    """
    root = copy.deepcopy(root)
    plant = root.find(".//Object[@type='Plant/PlantModel']")
    for components in list(plant.iterchildren("Components")):
        if components.get("property") != "MetaData":
            plant.remove(components)
    groups = root.find(".//Object[@type='Core/Diagram.Diagram']/Components[@property='Groups']")
    for group in list(groups):
        if group.get("type") == "Core/Diagram.RepresentationGroup":
            groups.remove(group)
    shapes = root.find(
        ".//Object[@type='Core/Diagram.ShapeCatalogue']/Components[@property='Shapes']"
    )
    shapes.extend(shape.element() for shape in ADDED_SHAPES if shape.template)
    return root


#: The row ``clean_title_block`` adds on top of the title block: (x0, x1, static text or None,
#: MetaData attribute shown or None).
_ROW = [
    (296.0, 314.0, "REVISION", None),
    (314.0, 344.0, None, "RevisionNumber"),
    (344.0, 358.4, None, "LastModificationDateRepresentation"),
    (358.4, 380.0, "STATUS", None),
    (380.0, 416.0, None, "ApprovalDescription"),
]
_ROW_TOP, _ROW_BOTTOM = 258.0, 263.0


def _without_ids(element: etree._Element) -> etree._Element:
    element = copy.deepcopy(element)
    for inner in element.iter("Object"):
        inner.attrib.pop("id", None)
    return element


def _set_double(element: etree._Element, path: str, value: float) -> None:
    element.find(path).text = repr(value)


def clean_title_block(root: etree._Element) -> etree._Element:
    """The skeleton without pyDEXPI's sample title block (pre-release issue 10).

    Every MetaData text is emptied (the sheet format stays), the status reads "for review",
    the Model and diagram get the placeholders ``cheme sheet new`` replaces, and the title
    block gains a row showing RevisionNumber, LastModificationDateRepresentation and the status
    (ApprovalDescription), which the reference title block does not show.
    """
    root.set("name", PLACEHOLDER_MODEL_NAME)
    root.set("uri", PLACEHOLDER_MODEL_URI)
    diagram = root.find(".//Object[@type='Core/Diagram.Diagram']")
    diagram.find("Data[@property='Name']/String").text = PLACEHOLDER_DIAGRAM_NAME
    metadata = root.find(".//Object[@type='Plant/Diagram.PlantMetaData']")
    for data in metadata.iterchildren("Data"):
        prop = data.get("property")
        if prop == "SheetFormat":
            continue
        if data.find("String") is not None:
            data.find("String").text = ""
        elif data.find("Integer") is not None:
            data.find("Integer").text = "1"
        for single in data.iterfind(".//AggregatedDataValue/Data/AggregatedDataValue"):
            language = single.findtext("Data[@property='Language']/String")
            value = single.find("Data[@property='Value']/String")
            if prop == "ApprovalDescription":
                value.text = {"en": "for review", "de": "zur Prüfung"}.get(language, "")
            else:
                value.text = ""

    label = root.find(".//Object[@type='Core/Diagram.Label']")
    elements = label.find("Components[@property='Elements']")
    texts = elements.findall("Object[@type='Core/Diagram.Text']")
    static = next(t for t in texts if t.find("Components[@property='Template']") is None)
    shown = next(t for t in texts if t.find("Components[@property='Template']") is not None)
    outline, cell = elements.findall("Object[@type='Core/Diagram.PolyLine']")[:2]
    for y in outline.iterfind("Data[@property='Points']/AggregatedDataValue/Data[@property='Y']"):
        if float(y.findtext("Double")) == _ROW_BOTTOM:  # the outline grows by the new row
            _set_double(y, "Double", _ROW_TOP)
    for x0, x1, literal, attribute in _ROW:
        poly = _without_ids(cell)
        points = poly.findall("Data[@property='Points']/AggregatedDataValue")
        for point, (x, y) in zip(
            points,
            [(x0, _ROW_BOTTOM), (x0, _ROW_TOP), (x1, _ROW_TOP), (x1, _ROW_BOTTOM)]
            + [(x0, _ROW_BOTTOM)],
            strict=True,
        ):
            _set_double(point, "Data[@property='X']/Double", x)
            _set_double(point, "Data[@property='Y']/Double", y)
        elements.append(poly)
        text = _without_ids(static if literal else shown)
        position = "Data[@property='Position']/AggregatedDataValue/Data[@property='{}']/Double"
        _set_double(text, position.format("X"), round(x0 + 1.2, 6))
        _set_double(text, position.format("Y"), _ROW_BOTTOM - 1.75)
        if literal:
            text.find("Data[@property='Text']/String").text = literal
        else:
            text.find(".//Data[@property='AttributeName']/String").text = attribute
            text.find("Data[@property='Text']/String").text = ""
        elements.append(text)
    return root


def main(reference: Path, out: Path = OUT) -> None:
    """Write the snippets and ``shapes.md`` under ``out`` (the skill directory)."""
    formatted, _ = format_bytes(reference.read_bytes())
    root = etree.fromstring(formatted)

    def _write(name: str, elements: etree._Element | list, note: str) -> None:
        path = out / "snippets" / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(render_snippet(elements, note), encoding="utf-8")

    empty = clean_title_block(skeleton(root))
    (out / "snippets").mkdir(parents=True, exist_ok=True)
    canonical, _ = refresh_title_block(
        etree.tostring(empty, xml_declaration=True, encoding="UTF-8")
    )
    (out / "snippets" / "empty-sheet.xml").write_bytes(canonical)

    _write(
        "equipment-tank.xml",
        _by_id(root, "Tank1"),
        "Tank T4750 with chambers and nozzles: the conceptual object, under TaggedPlantItems.",
    )
    _write(
        "equipment-tank-drawing.xml",
        _by_id(root, "Tank1_Drawing1"),
        "How Tank1 is drawn: a RepresentationGroup under Diagram/Groups.",
    )
    _write(
        "equipment-pump.xml",
        _by_id(root, "CentrifugalPump1"),
        "Centrifugal pump P4711 with suction and discharge nozzles.",
    )
    _write(
        "equipment-pump-drawing.xml",
        _by_id(root, "CentrifugalPump1_Drawing1"),
        "How CentrifugalPump1 is drawn.",
    )
    _write(
        "piping-system-with-valve.xml",
        _by_id(root, "PipingNetworkSystem3"),
        "Line 47123: one segment, nozzle -> globe valve -> nozzle, under PipingNetworkSystems.",
    )
    _write(
        "piping-system-with-valve-drawing.xml",
        _by_id(root, "PipingNetworkSystem3_Drawing1"),
        "How line 47123 is drawn: label, pipes as ConnectorLines, valve symbol, node positions.",
    )
    _write(
        "instrument-function.xml",
        _by_id(root, "ProcessInstrumentationFunction1"),
        "An instrument function (PI-4712.01) under ProcessInstrumentationFunctions.",
    )
    _write(
        "instrument-function-drawing.xml",
        _by_id(root, "ProcessInstrumentationFunction1_Drawing1"),
        "How the instrument function is drawn: bubble (Shape16), label texts, measuring line."
        " The measuring line runs from #InstrumentationNodePosition1, which is not in this"
        " snippet: it sits in the drawing of the sensing location (BlindFlange1), see"
        " instrument-nozzle-drawing.xml.",
    )
    _write(
        "instrument-nozzle.xml",
        _by_id(root, "PipingNetworkSegment13"),
        "An instrument connection: branch segment from tee PipeTee3 through isolation valve"
        " BallValve3 to BlindFlange1, the SensingLocation of ProcessSignalGeneratingFunction1"
        " (PI-4712.01). Under the line's PipingNetworkSystem/Segments.",
    )
    _write(
        "instrument-nozzle-drawing.xml",
        _by_id(root, "PipingNetworkSegment13_Drawing1"),
        "How the instrument connection is drawn: pipe, valve, blind flange (Shape13) with its"
        " PipingNodePosition and the InstrumentationNodePosition1 the measuring line starts at.",
    )
    _write(
        "tee-branch.xml",
        [
            (
                "In PipingNetworkSystem6 (line 47126)/Segments: the run segment S3 that ENDS at"
                " PipeTee1 and therefore owns it. Its TargetNode is the tee's run-out node"
                " PipingNode30, where S4 starts (reference convention, accepted by"
                " cheme.segment-ends; a new segment may name the node its last pipe ends"
                " at instead)",
                _by_id(root, "PipingNetworkSegment11"),
            ),
            (
                "In PipingNetworkSystem6/Segments, after it: S4, the run continuing from the"
                " tee's run-out node",
                _by_id(root, "PipingNetworkSegment12"),
            ),
            (
                "In PipingNetworkSystem5 (line 47125)/Segments: the branch starts at the tee's"
                " third node (PipingNode19)",
                _by_id(root, "PipingNetworkSegment7"),
            ),
        ],
        "A tee: run segment ending at PipeTee1 (three PipingNodes: run in, run out, branch),"
        " run continuation, and a branch segment of another line starting at the tee.",
    )
    _write(
        "tee-branch-drawing.xml",
        [
            (
                "In PipingNetworkSystem6_Drawing1: the run segment's drawing, with the tee"
                " (Shape12, scale 0.0001, node positions 0.001 mm apart)",
                _by_id(root, "PipingNetworkSegment11_Drawing1"),
            ),
            (
                "In PipingNetworkSystem6_Drawing1: the continuation",
                _by_id(root, "PipingNetworkSegment12_Drawing1"),
            ),
            (
                "In PipingNetworkSystem5_Drawing1: the branch, starting at PipingNodePosition19",
                _by_id(root, "PipingNetworkSegment7_Drawing1"),
            ),
        ],
        "How the tee and both segments are drawn.",
    )

    _write(
        "actuating-system.xml",
        _by_id(root, "ActuatingSystem1"),
        "Actuating system PV4712.02: controlled actuator (fail close) operating GlobeValve1,"
        " under PlantModel/ActuatingSystems. The controller reaches it through an"
        " ActuatingFunction (References Systems), see signal-line.xml.",
    )
    _write(
        "actuating-system-drawing.xml",
        _by_id(root, "ActuatingSystem1_Drawing1"),
        "How the actuating system is drawn, under Diagram/Groups: number label, actuator symbol"
        " (Shape1) with its fail-action label and the InstrumentationNodePosition the signal"
        " line ends at.",
    )
    _write(
        "signal-line.xml",
        _by_id(root, "ProcessInstrumentationFunction2"),
        "Controller PICSA-4712.02: sensor, measuring line, the ActuatingFunction pointing at"
        " ActuatingSystem1 and the SignalConveyingFunction from the controller to it (the"
        " signal line), under ProcessInstrumentationFunctions.",
    )
    _write(
        "signal-line-drawing.xml",
        _by_id(root, "ProcessInstrumentationFunction2_Drawing1"),
        "How the controller is drawn: bubble, labels, measuring line (solid green) and the"
        " signal line (dashed blue ConnectorLine) from the bubble's InstrumentationNodePosition5"
        " to the actuator's InstrumentationNodePosition6 (in actuating-system-drawing.xml).",
    )
    _write(
        "offpage-connector.xml",
        [
            (
                "In PipingNetworkSystem1 (line 47121)/Segments: the segment STARTING at the"
                " FlowInPipeOffPageConnector, which it owns (Items); the first pipe and the"
                " segment start at its node",
                _by_id(root, "PipingNetworkSegment1"),
            ),
        ],
        "An off-page connector: line 47121 comes from another sheet.",
    )
    _write(
        "offpage-connector-drawing.xml",
        [
            (
                "In PipingNetworkSegment1_Drawing1: the arrow (Shape2, scale 0.7, tip at the"
                " node) and the node position the first pipe starts at",
                _by_id(root, "FlowInPipeOffPageConnector1_Drawing1"),
            ),
        ],
        "How the off-page connector is drawn.",
    )

    shapes = root.findall(".//Object[@type='Core/Diagram.Shape']")
    lines = [
        "# Shapes in the reference shape catalogue",
        "",
        'Reuse these by id (`<References objects="#ShapeN" property="Shape"/>` in a '
        "ShapeUsage). They are in `empty-sheet.xml` already.",
        "",
        "| id | name | used by |",
        "|---|---|---|",
    ]
    for shape in shapes:
        name = shape.findtext("Data[@property='Name']/String") or ""
        users = set()
        for usage in root.iterfind(f".//References[@objects='#{shape.get('id')}']"):
            for ancestor in usage.iterancestors("Object"):
                represents = ancestor.find("References[@property='Represents']")
                if represents is not None:
                    users.add(represents.get("objects", "").lstrip("#"))
                    break
        users = sorted(users)
        lines.append(f"| {shape.get('id')} | {name} | {', '.join(users)} |")
    lines += [
        "",
        "# Shapes cheme-as-code adds",
        "",
        "Those marked in `empty-sheet.xml` are in it (after the reference shapes); for any "
        "other, or a sheet made before one was added, `cheme fragment shape NAME --sheet "
        "pid/<sheet>.xml` prints the Shape "
        "to paste into its catalogue, or says it is there already. Most are ISO 10628-2 "
        "symbols with their registration number (`ISO10628:2012-<number>-A`); the few "
        "cheme-as-code draws itself carry their name instead (their ISO number is not checked), "
        "as the reference does for its shapes without a number. "
        "Never invent a number, nor borrow one from a symbol of another name. "
        "Ports are the symbol's connection points at scale 1 (sheet mm from its centre, Y "
        "down): place nozzles and pipe ends there, scaled and rotated with the symbol.",
        "",
        "| id | name | ISO 10628 number | meaning | scale on A3 | default for | ports "
        "| in empty-sheet.xml |",
        "|---|---|---|---|---|---|---|---|",
    ]
    for shape in ADDED_SHAPES:
        number = shape.registration if shape.iso else "name (drawn here, ISO number not checked)"
        ports = ", ".join(f"{p.key} {p.x:g},{p.y:g}" for p in shape.ports)
        lines.append(
            f"| {shape.shape_id} | {shape.name} | {number} | {shape.meaning} | {shape.scale} "
            f"| {', '.join(shape.classes)} | {ports} | {'yes' if shape.template else ''} |"
        )
    (out / "shapes.md").write_text("\n".join(lines) + "\n", encoding="utf-8")
    print(f"Snippets written to {out}")


if __name__ == "__main__":
    main(Path(sys.argv[1]))
