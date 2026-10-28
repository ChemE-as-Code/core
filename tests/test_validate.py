from pathlib import Path

from lxml import etree
from pydexpi.loaders.public import load_xml_with_report

from chemeascode.foundation.workspace import Workspace
from chemeascode.project.validate import validate_pid, validate_workspace
from tests.conftest import REFERENCE


def _rules(findings):
    return {f.rule for f in findings}


def test_reference_has_no_errors():
    findings, model = validate_pid(REFERENCE)
    assert model is not None
    assert not [f for f in findings if f.level == "error"]
    # The vendored file leaves most objects without an id.
    assert "cheme.object-without-id" in _rules(findings)


def test_duplicate_id_and_dangling_reference_are_located(tmp_path: Path):
    text = REFERENCE.read_text(encoding="utf-8")
    text = text.replace('objects="#GlobeValve1"', 'objects="#Nowhere"', 1)
    text = text.replace('id="Tank1"', 'id="CentrifugalPump1"', 1)
    path = tmp_path / "bad.xml"
    path.write_text(text, encoding="utf-8")
    findings, _ = validate_pid(path)
    errors = [f for f in findings if f.level == "error"]
    assert "cheme.duplicate-id" in _rules(errors)
    dangling = [f for f in errors if "Nowhere" in f.message]
    assert dangling and dangling[0].line and dangling[0].line > 1


def test_syntax_error_stops_early(tmp_path: Path):
    path = tmp_path / "cut.xml"
    path.write_text(REFERENCE.read_text(encoding="utf-8")[:4000], encoding="utf-8")
    findings, model = validate_pid(path)
    assert model is None
    assert [f.rule for f in findings] == ["xml.syntax"]


def test_not_drawn_item_is_warned(tmp_path: Path):
    text = REFERENCE.read_text(encoding="utf-8")
    text = text.replace('<References objects="#Tank1" property="Represents"/>', "", 1)
    path = tmp_path / "undrawn.xml"
    path.write_text(text, encoding="utf-8")
    findings, _ = validate_pid(path)
    assert any(f.rule == "cheme.not-drawn" and f.ids == ["Tank1"] for f in findings)


def test_workspace_cross_checks_equipment(plant: Path):
    (plant / "equipment" / "equipment-list.yaml").write_text(
        "equipment:\n"
        "  - {tag: T4750, type: Tank}\n"
        "  - {tag: P4711, type: ReciprocatingPump}\n"
        "  - {tag: X9999, type: Tank}\n",
        encoding="utf-8",
    )
    report = validate_workspace(Workspace(plant))
    by_rule = {}
    for finding in report.findings:
        by_rule.setdefault(finding.rule, []).append(finding)
    assert [f.ids for f in by_rule["cheme.equipment-not-on-pid"]] == [["X9999"]]
    assert {i for f in by_rule["cheme.equipment-not-listed"] for i in f.ids} == {
        "H1007",
        "H1008",
        "P4712",
    }
    assert by_rule["cheme.equipment-type-mismatch"][0].ids == ["P4711"]
    assert not report.failed()


def test_yaml_schema_errors_fail(plant: Path):
    (plant / "piping" / "line-list.yaml").write_text(
        "lines:\n  - {number: L1, to: T1, colour: red}\n", encoding="utf-8"
    )
    report = validate_workspace(Workspace(plant))
    messages = [f.message for f in report.findings if f.rule == "yaml.schema"]
    assert any("from" in m for m in messages) and any("colour" in m for m in messages)
    assert report.failed()


# ---------------------------------------------------------------------------
# Model rules: segment ends, DN, labels
# ---------------------------------------------------------------------------


def _mutated(tmp_path: Path, *edits: tuple[str, str, str]) -> Path:
    """The reference P&ID with each (anchor, old, new) applied: *old* after *anchor*, once."""
    text = REFERENCE.read_text(encoding="utf-8")
    for anchor, old, new in edits:
        start = text.index(anchor)
        at = text.index(old, start)
        text = text[:at] + new + text[at + len(old) :]
    path = tmp_path / "mutated.xml"
    path.write_text(text, encoding="utf-8")
    return path


def _found(path: Path, rule: str):
    findings, model = validate_pid(path)
    assert model is not None
    return [f for f in findings if f.rule == rule]


def test_reference_has_no_model_rule_findings():
    findings, _ = validate_pid(REFERENCE)
    rules = _rules(findings)
    for rule in ("cheme.segment-ends", "cheme.dn-mismatch", "cheme.label-stale"):
        assert rule not in rules


def _segment_end(tmp_path: Path, segment: str, prop: str, target: str) -> Path:
    """The reference with *segment*'s own ``References property=prop`` pointing at *target*.

    A segment's own references follow those of its pipes, so its one is the last in its block.
    """
    text = REFERENCE.read_text(encoding="utf-8")
    start = text.index(f'id="{segment}"')
    end = text.index('id="PipingNetworkS', start + 1)
    at = text.rindex(f'property="{prop}"', start, end)
    at = text.rindex("<References ", start, at)
    close = text.index("/>", at) + 2
    text = text[:at] + f'<References objects="#{target}" property="{prop}"/>' + text[close:]
    path = tmp_path / "mutated.xml"
    path.write_text(text, encoding="utf-8")
    return path


_SEGMENT_RULES = (
    "pydexpi_segment_connectivity",
    "pydexpi_segment_reference_nodes_and_items_match",
)


def test_segment_end_that_is_not_its_pipe_end(tmp_path: Path):
    # PipingNetworkSegment2 holds only Pipe2: Nozzle2/PipingNode3 -> Nozzle3/PipingNode4.
    path = _segment_end(tmp_path, "PipingNetworkSegment2", "TargetNode", "PipingNode3")
    findings, _ = validate_pid(path)
    ends = [f for f in findings if f.rule == "cheme.segment-ends"]
    # One defect, one finding: pyDEXPI's two rules on segment ends are reported through it.
    assert len(ends) == 1
    assert not [f for f in findings if f.rule in _SEGMENT_RULES]
    finding = ends[0]
    assert finding.level == "error"
    assert finding.ids == ["PipingNetworkSegment2"]
    assert "Nozzle3/PipingNode3" in finding.message and "PipingNode4" in finding.message
    assert all(rule in finding.message for rule in _SEGMENT_RULES)
    lines = path.read_text(encoding="utf-8").splitlines()
    assert 'objects="#PipingNode3" property="TargetNode"' in lines[finding.line - 1]
    assert finding.hint


def test_segment_end_on_another_item(tmp_path: Path):
    path = _segment_end(tmp_path, "PipingNetworkSegment2", "SourceItem", "Nozzle1")
    findings = _found(path, "cheme.segment-ends")
    assert [f.ids for f in findings] == [["PipingNetworkSegment2"]]
    assert "SourceItem" in findings[0].message and "Nozzle1/PipingNode3" in findings[0].message


def test_segment_may_end_at_the_outlet_of_its_last_item(tmp_path: Path):
    # The reference ends PipingNetworkSegment4 at SwingCheckValve1's outlet (PipingNode13), not
    # where Pipe6 enters it (PipingNode12): fine, the valve is one of the segment's items. A node
    # of another item is not.
    assert not _found(REFERENCE, "cheme.segment-ends")
    path = _segment_end(tmp_path, "PipingNetworkSegment4", "TargetNode", "PipingNode11")
    assert [f.ids for f in _found(path, "cheme.segment-ends")] == [["PipingNetworkSegment4"]]


def test_segment_ends_do_not_depend_on_pipe_order(tmp_path: Path):
    # DEXPI 2.0.1 does not order a segment's Connections: listing PipingNetworkSegment3's pipes
    # out of flow order is only pyDEXPI's Recommended linear-order warning.
    root = etree.parse(str(REFERENCE)).getroot()
    segment = root.find(".//Object[@id='PipingNetworkSegment3']")
    pipes = [p for p in segment.iter("Object") if p.get("type") == "Plant/Piping.Pipe"]
    assert len(pipes) >= 2
    first, last = pipes[0], pipes[-1]
    first_parent, last_parent = first.getparent(), last.getparent()
    first_at, last_at = first_parent.index(first), last_parent.index(last)
    first_parent.remove(first)
    last_parent.remove(last)
    first_parent.insert(first_at, last)
    last_parent.insert(last_at, first)
    path = tmp_path / "reordered.xml"
    path.write_bytes(etree.tostring(root, xml_declaration=True, encoding="UTF-8"))
    findings, model = validate_pid(path)
    assert model is not None
    rules = _rules(findings)
    assert "pydexpi_segment_linear_order" in rules
    assert "cheme.segment-ends" not in rules
    assert not [f for f in findings if f.level == "error"]


def test_dn_mismatch_across_a_pipe(tmp_path: Path):
    path = _mutated(tmp_path, ('id="PipingNode4"', "<String>80</String>", "<String>50</String>"))
    findings = _found(path, "cheme.dn-mismatch")
    assert len(findings) == 1
    assert findings[0].ids == ["Pipe2", "PipingNode3", "PipingNode4"]
    assert "DN80" in findings[0].message and "DN50" in findings[0].message
    assert findings[0].line and findings[0].line > 1


def test_a_correct_reducer_has_no_dn_mismatch():
    # PipeReducer1 changes DN between its own nodes (80 in, 50 out); the pipes on either side
    # match the node they join, so nothing is reported.
    model = load_xml_with_report(REFERENCE.read_bytes(), strict=True).model
    reducer = next(
        component
        for system in model.conceptualModel.pipingNetworkSystems
        for segment in system.segments
        for component in segment.items
        if component.id == "PipeReducer1"
    )
    diameters = {node.nominalDiameterNumericalValueRepresentation for node in reducer.nodes}
    assert len(diameters) == 2
    assert not _found(REFERENCE, "cheme.dn-mismatch")


def test_dn_mismatch_at_a_reducer_port(tmp_path: Path):
    # Pipe7 runs from SwingCheckValve1/PipingNode13 (DN80) into the reducer's inlet PipingNode14:
    # making the inlet DN50 puts the DN change on the pipe, not inside the reducer.
    path = _mutated(tmp_path, ('id="PipingNode14"', "<String>80</String>", "<String>50</String>"))
    assert [f.ids for f in _found(path, "cheme.dn-mismatch")] == [
        ["Pipe7", "PipingNode13", "PipingNode14"]
    ]


def test_stale_label(tmp_path: Path):
    path = _mutated(tmp_path, ('property="ApproverName"', "A. P. Prover", "Someone Else"))
    findings = _found(path, "cheme.label-stale")
    assert len(findings) == 1
    finding = findings[0]
    assert finding.ids == ["PlantMetaData1"]
    assert "'A. P. Prover'" in finding.message and "'Someone Else'" in finding.message
    lines = path.read_text(encoding="utf-8").splitlines()
    assert "A. P. Prover" in lines[finding.line - 1]


def test_stale_label_with_a_short_template(tmp_path: Path):
    # The valve label "66KL21-80" comes from a template of PipingComponentName and "-"; renaming
    # the valve makes it stale, while the reference itself is not.
    path = _mutated(
        tmp_path, ('id="ButterflyValve1"', "<String>66KL21</String>", "<String>66KL22</String>")
    )
    findings = _found(path, "cheme.label-stale")
    assert [f.ids for f in findings] == [["ButterflyValve1"]]
    assert "66KL21-80" in findings[0].message


def test_label_whose_template_cannot_be_rendered(tmp_path: Path):
    # A mistyped AttributeName renders nothing; it is reported, not skipped.
    path = _mutated(
        tmp_path,
        ("<String>ApproverName</String>", "ApproverName", "NoSuchAttr"),
    )
    findings = _found(path, "cheme.label-stale")
    assert len(findings) == 1
    finding = findings[0]
    assert finding.ids == ["PlantMetaData1"]
    assert "cannot be rendered" in finding.message
    assert "PlantMetaData1.NoSuchAttr is not an attribute of" in finding.message
    assert finding.line


# ---------------------------------------------------------------------------
# Lists against P&IDs
# ---------------------------------------------------------------------------


def _by_rule(report):
    by_rule: dict[str, list] = {}
    for finding in report.findings:
        by_rule.setdefault(finding.rule, []).append(finding)
    return by_rule


def test_line_list_cross_check(plant: Path):
    (plant / "piping" / "line-list.yaml").write_text(
        "lines:\n"
        "  - {number: '47121', from: X, to: P4711/N1, nominal_diameter: DN80}\n"
        "  - number: '47124'\n"
        "    from: T4750/N2\n"
        "    to: P4712/N1\n"
        "    nominal_diameter: DN80\n"
        "    notes: reduced to DN50 at the pump\n"
        "    segments:\n"
        "      - {number: S2, nominal_diameter: DN80}\n"
        "      - {number: S3, nominal_diameter: DN25, notes: after the reducer}\n"
        "      - {number: S99, nominal_diameter: DN25}\n"
        "  - {number: '47126', from: P4712/N2, to: X, nominal_diameter: DN80}\n"
        "  - {number: '99999', from: A, to: B}\n",
        encoding="utf-8",
    )
    # At the first stage, listed lines without a sheet: are info, one summary line
    # (pre-release issue 17).
    concept = [f for f in validate_workspace(Workspace(plant)).findings if "not-on-pid" in f.rule]
    assert [(f.level, sorted(f.ids)) for f in concept] == [("info", ["47124/S99", "99999"])]
    config = plant / "plant.yaml"
    config.write_text(config.read_text().replace("stage: concept", "stage: basic"))
    report = validate_workspace(Workspace(plant))
    by_rule = _by_rule(report)
    not_on_pid = by_rule["cheme.line-not-on-pid"]
    assert sorted(f.ids[0] for f in not_on_pid) == ["47124/S99", "99999"]
    assert {f.line for f in not_on_pid} == {11, 13}
    assert {f.ids[0] for f in by_rule["cheme.line-not-listed"]} == {
        "47122",
        "47123",
        "47125",
        "47127",
        "47130",
        "47131",
        "47140",
        "47141",
    }
    not_listed = by_rule["cheme.line-not-listed"][0]
    assert not_listed.file == "pid/P-01.xml" and not_listed.line
    mismatch = {f.ids[0]: f for f in by_rule["cheme.line-dn-mismatch"]}
    assert set(mismatch) == {"47124/S3", "47126"}
    assert mismatch["47124/S3"].line == 10
    assert "DN50" in mismatch["47124/S3"].message
    assert not report.failed()
    assert "lines list vs P&IDs" in report.compared["cross_checks"]


def test_instrument_list_cross_check(plant: Path):
    (plant / "control" / "instrument-list.yaml").write_text(
        "instruments:\n  - {tag: PI-4712.01, notes: local gauge}\n  - {tag: PISA-4712.02}\n",
        encoding="utf-8",
    )
    report = validate_workspace(Workspace(plant))
    by_rule = _by_rule(report)
    assert [(f.ids, f.line) for f in by_rule["cheme.instrument-not-on-pid"]] == [
        (["PISA-4712.02"], 3)
    ]
    assert {f.ids[0] for f in by_rule["cheme.instrument-not-listed"]} == {
        "PICSA-4712.02",
        "HS-4750.01",
        "TICSA-4750.03",
    }
    assert all(f.line for f in by_rule["cheme.instrument-not-listed"])


def test_compared_summary(plant: Path):
    report = validate_workspace(Workspace(plant))
    line = report.compared_line()
    assert line.startswith("compared: 1 sheet(s) (pid/P-01.xml)")
    assert "equipment list vs P&IDs" in line and "instruments list vs P&IDs" in line
    only = validate_workspace(Workspace(plant), [plant / "pid" / "P-01.xml"])
    assert only.compared["cross_checks"] == []
    assert "only the files given" in only.compared_line()


def test_yaml_schema_errors_have_lines_and_numbers_need_no_quotes(plant: Path):
    (plant / "piping" / "line-list.yaml").write_text(
        "lines:\n"
        "  - {number: 47121, from: X, to: P4711/N1, nominal_diameter: 80}\n"
        "  - number: '47122'\n"
        "    from: X\n"
        "    to: Y\n"
        "    colour: red\n",
        encoding="utf-8",
    )
    report = validate_workspace(Workspace(plant))
    schema = [f for f in report.findings if f.rule == "yaml.schema"]
    # The unquoted number and DN are fine; only the unknown key is wrong, on its own line.
    assert [(f.message.split(":")[0], f.line) for f in schema] == [("lines.1.colour", 6)]


def test_listed_numbers_and_tags_are_stripped(plant: Path):
    (plant / "piping" / "line-list.yaml").write_text(
        "lines:\n  - {number: '47126 ', from: a, to: b}\n", encoding="utf-8"
    )
    (plant / "control" / "instrument-list.yaml").write_text(
        "instruments:\n  - {tag: ' PICSA-4712.02'}\n", encoding="utf-8"
    )
    by_rule = _by_rule(validate_workspace(Workspace(plant)))
    assert "cheme.line-not-on-pid" not in by_rule
    assert "47126" not in {f.ids[0] for f in by_rule["cheme.line-not-listed"]}
    assert "cheme.instrument-not-on-pid" not in by_rule
    assert "PICSA-4712.02" not in {f.ids[0] for f in by_rule["cheme.instrument-not-listed"]}


def test_duplicate_list_entries_are_reported_and_each_checked(plant: Path):
    (plant / "piping" / "line-list.yaml").write_text(
        "lines:\n"
        "  - {number: '47121', from: a, to: b}\n"
        "  - number: '47124'\n"
        "    from: a\n"
        "    to: b\n"
        "    nominal_diameter: DN 80\n"
        "    segments:\n"
        "      - {number: S3, nominal_diameter: DN50}\n"
        "      - {number: S1, nominal_diameter: NPS 3}\n"
        "  - {number: '47124', from: a, to: b, nominal_diameter: DN 50}\n",
        encoding="utf-8",
    )
    (plant / "control" / "instrument-list.yaml").write_text(
        "instruments:\n  - {tag: PI-4712.01}\n  - {tag: PI-4712.01}\n", encoding="utf-8"
    )
    by_rule = _by_rule(validate_workspace(Workspace(plant)))
    [duplicate] = by_rule["cheme.line-duplicate"]
    assert duplicate.ids == ["47124"] and duplicate.line == 10
    assert "first on line 3" in duplicate.message
    mismatch = {(f.ids[0], f.line): f.message for f in by_rule["cheme.line-dn-mismatch"]}
    # Each entry is checked, at its own line and with its own DN.
    assert ("47124/S1", 9) in mismatch and "NPS 3" in mismatch[("47124/S1", 9)]
    assert ("47124", 10) in mismatch and "DN 50" in mismatch[("47124", 10)]
    assert ("47124", 3) not in mismatch
    [twice] = by_rule["cheme.instrument-duplicate"]
    assert twice.ids == ["PI-4712.01"] and twice.line == 3


def test_cross_checks_with_a_sheet_that_did_not_load(plant: Path):
    second = plant / "pid" / "P-02.xml"
    second.write_text(
        (plant / "pid" / "P-01.xml").read_text(encoding="utf-8").replace("47121", "47999"),
        encoding="utf-8",
    )
    first = plant / "pid" / "P-01.xml"
    first.write_text(first.read_text(encoding="utf-8") + "<broken", encoding="utf-8")
    (plant / "piping" / "line-list.yaml").write_text(
        "lines:\n  - {number: '47121', from: a, to: b}\n", encoding="utf-8"
    )
    report = validate_workspace(Workspace(plant))
    by_rule = _by_rule(report)
    assert "xml.syntax" in by_rule
    # 47121 may well be on the sheet that was not read: no not-on-pid warning, only info.
    assert all(f.level == "info" for f in by_rule.get("cheme.line-not-on-pid", []))
    assert all(f.level == "info" for f in by_rule.get("cheme.equipment-not-on-pid", []))
    assert report.compared["sheets"] == ["pid/P-02.xml"]
    assert report.compared["not_loaded"] == ["pid/P-01.xml"]
    line = report.compared_line()
    assert "1 sheet(s) (pid/P-02.xml), not loaded: pid/P-01.xml" in line
    assert "lines on unavailable sheets not reported missing (P-01 not loaded)" in line


def test_literal_label_that_repeats_the_data_is_info():
    findings, _ = validate_pid(REFERENCE)
    literal = {f.ids[0]: f for f in findings if f.rule == "cheme.label-literal"}
    valve = literal["SpringLoadedGlobeSafetyValve1"]
    assert valve.level == "info"
    assert "'DN = 25/50'" in valve.message and "DN25/DN50" in valve.message
    assert literal["PipeReducer1"].level == "info"  # "80/50", no "DN"
    assert literal["Nozzle17"].level == "info"  # a nozzle's "25"
    assert {f.level for f in literal.values()} == {"info"}
    lines = REFERENCE.read_text(encoding="utf-8").splitlines()
    assert "DN = 25/50" in lines[valve.line - 1]


def test_literal_label_that_contradicts_the_data_is_a_warning(tmp_path: Path):
    # The T4 case: the safety valve's inlet becomes DN40, its hand-written label still says 25.
    path = _mutated(
        tmp_path,
        ('id="PipingNode20"', "<String>25</String>", "<String>40</String>"),
        ('id="PipingNode20"', "<String>DN 25</String>", "<String>DN 40</String>"),
    )
    findings = _found(path, "cheme.label-literal")
    (warning,) = [f for f in findings if f.level == "warning"]
    assert warning.ids == ["SpringLoadedGlobeSafetyValve1"]
    assert "says DN 25/50, but the data says DN40/DN50" in warning.message
    assert "AttributeRepresentation" in warning.hint


def test_literal_label_quantities_and_strings(tmp_path: Path):
    from chemeascode.project.validate import _label_literal_rules

    sheet = b"""<Model>
  <Object id="V1" type="Plant/Piping.SpringLoadedGlobeSafetyValve">
    <Data property="PositionNumber"><String>SV 1</String></Data>
    <Data property="SetPressureHigh">
      <AggregatedDataValue type="Core/PhysicalQuantities.PhysicalQuantity">
        <Data property="Unit"><DataReference data="Core/PhysicalQuantities.PressureGaugeUnit.Bar"/>
        </Data>
        <Data property="Value"><Double>6.0</Double></Data>
      </AggregatedDataValue>
    </Data>
  </Object>
  <Object id="D" type="Core/Diagram.Diagram">
    <References objects="#M" property="Represents"/>
    <Object id="G" type="Plant/Diagram.SafetyValveOrFittingLabel">
      <References objects="#V1" property="Represents"/>
      <Object id="T1" type="Core/Diagram.Text"><Data property="Text"><String>P = 7 barg</String>
      </Data></Object>
      <Object id="T2" type="Core/Diagram.Text"><Data property="Text"><String>SV 1</String>
      </Data></Object>
      <Object id="T3" type="Core/Diagram.Text"><Data property="Text"><String>Ident</String>
      </Data></Object>
    </Object>
  </Object>
</Model>"""
    findings = _label_literal_rules("s.xml", etree.fromstring(sheet))
    assert [(f.level, f.line) for f in findings] == [("warning", 16), ("info", 18)]
    assert "SetPressureHigh = 6 Bar" in findings[0].message
    assert "PositionNumber SV 1" in findings[1].message


def _literal_sheet(dn_labels: dict[str, str], pressure_label: str = "") -> bytes:
    """A valve (nodes DN25/DN50, set pressure 6 bar) and a DN80 nozzle with literal labels."""

    def node(i: int, dn: str) -> str:
        return (
            f'<Object id="N{i}" type="Plant/Piping.PipingNode"><Data '
            f'property="NominalDiameterNumericalValueRepresentation"><String>{dn}</String>'
            "</Data></Object>"
        )

    texts = "".join(
        f'<Object id="G{i}" type="Plant/Diagram.Label"><References objects="#{target}" '
        f'property="Represents"/><Object id="T{i}" type="Core/Diagram.Text"><Data '
        f'property="Text"><String>{label}</String></Data></Object></Object>'
        for i, (label, target) in enumerate(dn_labels.items())
    )
    return f"""<Model>
  <Object id="V1" type="Plant/Piping.SpringLoadedGlobeSafetyValve">
    <Components property="Nodes">{node(1, "25")}{node(2, "50")}</Components>
    <Data property="SetPressureHigh">
      <AggregatedDataValue type="Core/PhysicalQuantities.PhysicalQuantity">
        <Data property="Unit"><DataReference data="Core/PhysicalQuantities.PressureGaugeUnit.Bar"/>
        </Data>
        <Data property="Value"><Double>6.0</Double></Data>
      </AggregatedDataValue>
    </Data>
  </Object>
  <Object id="Nozzle3" type="Plant/ProcessEquipment.ProcessNozzle">
    <Components property="Nodes">{node(3, "80")}</Components>
  </Object>
  <Object id="D" type="Core/Diagram.Diagram">
    <References objects="#M" property="Represents"/>{texts}
  </Object>
</Model>""".encode()


def _literal_levels(labels: dict[str, str]) -> dict[str, tuple[str, str]]:
    from chemeascode.project.validate import _label_literal_rules

    findings = _label_literal_rules("s.xml", etree.fromstring(_literal_sheet(labels)))
    return {f.message.split("'")[1]: (f.level, f.message) for f in findings}


def test_literal_label_reads_every_dn_in_the_text():
    found = _literal_levels(
        {
            "DN25/DN50": "V1",
            "DN 25 x DN 50": "V1",
            "DN25 / PN16": "V1",
            "DN = 25/50": "V1",
            "DN25/DN40": "V1",
        }
    )
    for label in ("DN25/DN50", "DN 25 x DN 50", "DN25 / PN16", "DN = 25/50"):
        assert found[label][0] == "info", found[label]
    level, message = found["DN25/DN40"]
    assert level == "warning" and "says DN 25/40, but the data says DN25/DN50" in message


def test_literal_label_bare_number_that_is_no_dn_is_not_a_warning():
    found = _literal_levels({"1": "Nozzle3", "1/2": "Nozzle3", "80": "Nozzle3", "50": "Nozzle3"})
    assert "1" not in found and "1/2" not in found  # nozzle number, imperial size
    assert found["80"][0] == "info" and "repeats DN80" in found["80"][1]
    level, message = found["50"]  # in the DN series, but it may still be a nozzle number
    assert level == "info" and "if it is a size, says DN 50" in message


def test_literal_label_quantity_in_parentheses():
    found = _literal_levels({"DN = 25/50 (7 barg)": "V1", "DN = 25/50 (6 barg)": "V1"})
    level, message = found["DN = 25/50 (7 barg)"]
    assert level == "warning" and "7 barg, but the data says SetPressureHigh = 6 Bar" in message
    level, message = found["DN = 25/50 (6 barg)"]
    assert level == "info" and "SetPressureHigh 6 barg" in message


def test_reference_safety_valve_label_dn25_dn50_is_no_warning(tmp_path: Path):
    path = _mutated(tmp_path, ("<String>DN = 25/50", "DN = 25/50", "DN25/DN50"))
    (finding,) = [
        f for f in _found(path, "cheme.label-literal") if f.ids == ["SpringLoadedGlobeSafetyValve1"]
    ]
    assert finding.level == "info"


def test_line_endpoints_are_compared_with_the_drawing(plant: Path):
    """pre-release issue 38: a listed from/to the drawn line does not reach, where it reaches
    another item."""
    (plant / "piping" / "line-list.yaml").write_text(
        "lines:\n"
        "  - {number: '47123', from: H1007/N2, to: H1008}\n"  # drawn H1007 -> T4750
        "  - {number: '47127', from: H1008/N2, to: T4750/N6}\n"  # as drawn
        "  - {number: '47130', from: battery limit, to: H1007/N3}\n"  # not a tag
        "  - {number: '47122', from: P4712, to: H1007}\n",  # drawn P4711 -> H1007
        encoding="utf-8",
    )
    found = _by_rule(validate_workspace(Workspace(plant))).get("cheme.line-endpoint-mismatch", [])
    by_line = {f.ids[0]: f for f in found}
    assert sorted(by_line) == ["47122", "47123"]
    wrong = by_line["47123"]
    assert wrong.level == "warning" and wrong.file == "piping/line-list.yaml" and wrong.line == 2
    assert "listed to H1008" in wrong.message and "H1007, T4750" in wrong.message
    assert wrong.ids == ["47123", "H1008", "T4750"]
    assert "listed from P4712" in by_line["47122"].message
