"""cheme process: schema v1, BFD/PFD generation, layout, provenance, balances (phase A)."""

import copy
import shutil
from pathlib import Path

import pytest
import yaml

from chemeascode.domains.process import GENERATOR_VERSION
from chemeascode.domains.process.build import place
from chemeascode.domains.process.model import balances, load, rules
from chemeascode.domains.process.sheets import build, check_sheet, edited, is_cycle_cut
from chemeascode.foundation.workspace import Workspace
from chemeascode.project.validate import validate_workspace

EXAMPLES = Path(__file__).resolve().parents[1] / "examples"


@pytest.fixture
def recycle(tmp_path):
    shutil.copytree(
        EXAMPLES / "process-recycle", tmp_path / "plant", ignore=shutil.ignore_patterns("build")
    )
    return Workspace(tmp_path / "plant")


@pytest.fixture
def blocks(tmp_path):
    shutil.copytree(
        EXAMPLES / "process-blocks", tmp_path / "blocks", ignore=shutil.ignore_patterns("build")
    )
    return Workspace(tmp_path / "blocks")


def _edit(ws, change):
    path = ws.root / "process/flowsheet.yaml"
    data = yaml.safe_load(path.read_text())
    change(data)
    path.write_text(yaml.safe_dump(data, sort_keys=False))


def _rules(ws):
    process, found = load(ws.root)
    assert process is not None, [f.format() for f in found]
    return found + rules(process)


def _stream(data, sid):
    return next(s for s in data["streams"] if s["id"] == sid)


def test_examples_build_and_validate_clean(recycle, blocks):
    for ws in (recycle, blocks):
        assert not build(ws, force=True).failed
        report = validate_workspace(ws)
        assert not [f.format() for f in report.findings if f.level != "info"]


def test_committed_example_sheets_are_current():
    for name in ("process-recycle", "process-blocks"):
        report = validate_workspace(Workspace(EXAMPLES / name))
        bad = [f for f in report.findings if f.rule.startswith("cheme.generated-")]
        assert not bad, [f.format() for f in bad]


def test_rebuild_is_byte_identical(recycle):
    build(recycle, force=True)
    first = (recycle.root / "process/PFD.xml").read_bytes()
    (recycle.root / "process/PFD.xml").unlink()
    build(recycle)
    assert (recycle.root / "process/PFD.xml").read_bytes() == first


def test_values_round_trip_with_provenance_and_case(recycle):
    from pydexpi.loaders.public import load_xml_with_report

    build(recycle, force=True)
    model = load_xml_with_report((recycle.root / "process/PFD.xml").read_bytes()).model
    streams = {c.id: c for c in model.conceptualModel.processConnections}
    flow = streams["S1"].massFlow[0]
    assert (flow.value.value, flow.case, flow.provenance.name) == (1000.0, "design", "SPECIFIED")
    assert streams["S2"].pressure[0].provenance.name == "ESTIMATED"
    assert "represents: S1" in streams["S1"].description.singleLanguageStrings[0].value


def test_pfd_nests_steps_and_delegates_ports_bfd_hides_internal(recycle):
    from pydexpi.loaders.public import load_xml_with_report

    build(recycle, force=True)
    pfd = load_xml_with_report((recycle.root / "process/PFD.xml").read_bytes()).model
    sep = next(s for s in pfd.conceptualModel.processSteps if s.id == "SEP")
    assert {s.id for s in sep.subProcessSteps} == {"C1", "E1"}
    c1 = next(s for s in sep.subProcessSteps if s.id == "C1")
    delegate = next(p for p in c1.ports if p.identifier == "in")
    assert delegate.superReference.identifier == "in" and delegate.connectorReference.id == "S2"
    bfd = load_xml_with_report((recycle.root / "process/BFD.xml").read_bytes()).model
    shown = {c.id for c in bfd.conceptualModel.processConnections}
    assert "S6" not in shown and {"S1", "S2", "S3", "S4", "S5", "Q1"} == shown
    assert "S6" in {c.id for c in pfd.conceptualModel.processConnections}


def test_refinement_keeps_stream_ids_and_balances(recycle, blocks):
    p_ref, _ = load(recycle.root)
    p_blk, _ = load(blocks.root)
    crossing = {s.id for s in p_ref.flowsheet.streams if p_ref.crossing(s)}
    assert crossing == {s.id for s in p_blk.flowsheet.streams}
    by_ref = {b.node: (b.status, b.inlet, b.outlet) for b in balances(p_ref) if b.kind == "block"}
    by_blk = {b.node: (b.status, b.inlet, b.outlet) for b in balances(p_blk) if b.kind == "block"}
    assert by_ref == by_blk == {"MIX": ("ok", 1500.0, 1500.0), "SEP": ("ok", 1500.0, 1500.0)}


def test_recycle_routed_below_and_no_block_overlap(recycle):
    process, _ = load(recycle.root)
    for view in ("bfd", "pfd"):
        placed = place(process, view)
        assert "S4" in placed.feedback
        bottom = max(n.y + n.height for n in placed.nodes.values())
        assert max(y for _, y in placed.routes["S4"]) > bottom
        tops = [n for k, n in placed.nodes.items() if process.kinds[k] != "step"]
        for i, a in enumerate(tops):
            for b in tops[i + 1 :]:
                apart = (
                    a.x + a.width <= b.x
                    or b.x + b.width <= a.x
                    or (a.y + a.height <= b.y or b.y + b.height <= a.y)
                )
                assert apart, (a.id, b.id)


def _overlaps(routes):
    """Pairs of routes with collinear, overlapping horizontal runs (indistinguishable lines)."""
    runs = [
        (eid, a[1], min(a[0], b[0]), max(a[0], b[0]))
        for eid, points in routes.items()
        for a, b in zip(points, points[1:], strict=False)
        if a[1] == b[1]
    ]
    return [
        (r[0], s[0])
        for i, r in enumerate(runs)
        for s in runs[i + 1 :]
        if r[0] != s[0] and r[1] == s[1] and min(r[3], s[3]) - max(r[2], s[2]) > 1e-6
    ]


def test_routes_leaving_and_entering_a_gap_do_not_share_a_run(recycle):
    from chemeascode.domains.process.layout import LEdge, LNode, layout

    nodes = [
        LNode("A", 30, 20, outs=["o1", "o2"]),
        LNode("B", 30, 20, ins=["i1", "i2"], outs=["o1"]),
        LNode("C", 30, 20, ins=["i1", "i2"], outs=["o1"]),
    ]
    edges = [
        LEdge("E1", "A", "o1", "B", "i1"),
        LEdge("E4", "C", "o1", "B", "i2"),  # recycle into B at the height of A.o2
        LEdge("E2", "A", "o2", "C", "i2"),  # skips B, leaves A at the same height
        LEdge("E3", "B", "o1", "C", "i1"),
    ]
    layout(nodes, edges)
    assert not _overlaps({e.id: e.points for e in edges})
    process, _ = load(recycle.root)
    for view in ("bfd", "pfd"):
        assert not _overlaps(place(process, view).routes), view


ASU = Path(__file__).parent / "data/process-asu"


def _segments(points):
    return list(zip(points, points[1:], strict=False))


def _crossings(lines):
    """Proper crossings of a horizontal and a vertical run of two different lines."""
    runs = [(k, s) for k, pts in lines.items() for s in _segments(pts)]
    count = 0
    for i, (k, (a, b)) in enumerate(runs):
        for m, (c, d) in runs[i + 1 :]:
            if k == m:
                continue
            if a[0] == b[0] and c[1] == d[1]:
                (v0, v1), (h0, h1) = (a, b), (c, d)
            elif a[1] == b[1] and c[0] == d[0]:
                (v0, v1), (h0, h1) = (c, d), (a, b)
            else:
                continue
            x, y = v0[0], h0[1]
            if min(h0[0], h1[0]) < x < max(h0[0], h1[0]) and min(v0[1], v1[1]) < y < max(
                v0[1], v1[1]
            ):
                count += 1
    return count


def _through(seg, n):
    """Whether *seg* runs through the inside of node *n*."""
    (a, b), e = seg, 0.01
    return (
        max(min(a[0], b[0]), n.x + e) < min(max(a[0], b[0]), n.x + n.width - e)
        or min(a[0], b[0]) == max(a[0], b[0])
        and n.x + e < a[0] < n.x + n.width - e
    ) and (
        max(min(a[1], b[1]), n.y + e) < min(max(a[1], b[1]), n.y + n.height - e)
        or min(a[1], b[1]) == max(a[1], b[1])
        and n.y + e < a[1] < n.y + n.height - e
    )


def _foreign(process, placed):
    """(line, node) pairs where a stream or delegation runs through a step or block it does not
    belong to (a stream may run inside the block that holds its steps)."""
    bad = []
    lines = {**placed.routes, **placed.delegations}
    for key, points in lines.items():
        holders = {process.container(key.split(".")[0])} if key in placed.delegations else set()
        stream = next((s for s in process.flowsheet.streams if s.id == key), None)
        if stream is not None:
            for end in (stream.from_, stream.to):
                holders.add(process.container(end.split(".")[0]))
        for node_id, node in placed.nodes.items():
            if node_id in holders:
                continue
            if any(_through(s, node) for s in _segments(points)):
                bad.append((key, node_id))
    return bad


def _label_hits(process, placed):
    """Stream labels on a line, on a node (a block holding steps: on its border or title) or
    on another label."""
    lines = {**placed.routes, **placed.delegations}
    boxes = placed.obstacles(process)
    labels = {k: placed.label_box(k) for k in placed.labels}
    bad = []
    for key, (x0, y0, x1, y1) in labels.items():

        def hit(a, b, x0=x0, y0=y0, x1=x1, y1=y1):
            return max(x0, a[0]) <= min(x1, b[0]) and max(y0, a[1]) <= min(y1, b[1])

        on_line = any(
            hit((min(a[0], b[0]), min(a[1], b[1])), (max(a[0], b[0]), max(a[1], b[1])))
            for pts in lines.values()
            for a, b in _segments(pts)
        )
        on_box = any(hit(b[:2], b[2:]) for b in boxes)
        on_label = any(o != key and hit(b[:2], b[2:]) for o, b in labels.items())
        if on_line or on_box or on_label:
            bad.append(key)
    return bad


def _block_lines(process, placed, block):
    """The streams between steps of *block* and its delegation lines."""
    own = {
        k: v for k, v in placed.delegations.items() if process.container(k.split(".")[0]) == block
    }
    for stream in process.flowsheet.streams:
        a, b = process.ends(stream)
        if a and b and process.container(a.node) == process.container(b.node) == block:
            own[stream.id] = placed.routes[stream.id]
    return own


def _asu(tmp_path):
    shutil.copytree(ASU, tmp_path / "asu")
    process, found = load(tmp_path / "asu")
    assert process is not None, [f.format() for f in found]
    return process


def test_routes_run_through_no_foreign_step_or_block(recycle, tmp_path):
    for process in (load(recycle.root)[0], _asu(tmp_path)):
        for view in ("bfd", "pfd"):
            assert not _foreign(process, place(process, view)), view


def test_asu_cold_box_is_untangled(tmp_path):
    """The ASU PFD: delegations and in-block streams take short routes and cross little (74
    crossings before the grid router, 30 after, 16 with ports ordered by where their lines go,
    of them 9 in the cold box, 18 before); the BFD vent streams do not loop over the sheet."""
    process = _asu(tmp_path)
    pfd = place(process, "pfd")
    assert _crossings({**pfd.routes, **pfd.delegations}) <= 18
    assert _crossings(_block_lines(process, pfd, "CB")) <= 10
    assert not _overlaps({**pfd.routes, **pfd.delegations})
    bfd = place(process, "bfd")
    assert _crossings(bfd.routes) <= 10
    top = min(n.y for n in bfd.nodes.values())
    for stream in ("S12D", "S12E"):  # into VENT, the lowest product: no channel above
        assert min(y for _, y in bfd.routes[stream]) >= top, stream


def test_stream_labels_sit_clear_of_lines_nodes_and_labels(recycle, tmp_path):
    for process in (load(recycle.root)[0], _asu(tmp_path)):
        for view in ("bfd", "pfd"):
            placed = place(process, view)
            assert set(placed.labels) == set(placed.routes)
            assert not _label_hits(process, placed), view


def test_title_rename_moves_nothing_and_pins_survive(recycle):
    process, _ = load(recycle.root)
    before = {k: (n.x, n.y) for k, n in place(process, "bfd").nodes.items()}
    _edit(recycle, lambda d: d["blocks"][0].update(title="Feed mixing"))
    process, _ = load(recycle.root)
    after = {k: (n.x, n.y) for k, n in place(process, "bfd").nodes.items()}
    assert before == after
    _edit(
        recycle,
        lambda d: (
            d.setdefault("layout", {})
            .setdefault("bfd", {})
            .update({"SEP": {"x": 200.0, "y": 150.0}})
        ),
    )
    process, _ = load(recycle.root)
    assert (place(process, "bfd").nodes["SEP"].x, place(process, "pfd").nodes["SEP"].x) != (
        200.0,
        200.0,
    )  # per view: the BFD pin does not move the PFD block
    assert place(process, "bfd").nodes["SEP"].y == 150.0
    assert not build(recycle, force=True).failed
    assert place(load(recycle.root)[0], "bfd").nodes["SEP"].x == 200.0


def test_layout_pin_writes_overrides(recycle):
    from chemeascode.domains.process.streams import pin_layout

    process, _ = load(recycle.root)
    pin_layout(recycle, process, "pfd", None)
    data = yaml.safe_load((recycle.root / "process/flowsheet.yaml").read_text())
    assert set(data["layout"]["pfd"]) >= {"MIX", "SEP", "C1"}
    assert load(recycle.root)[0].flowsheet.layout.pfd["C1"].pinned


def test_hand_edit_gives_generated_edited_and_yaml_edit_only_outdated(recycle):
    build(recycle, force=True)
    _edit(recycle, lambda d: _stream(d, "S1")["state"]["design"]["flow"].update(value=1001))
    rules_found = {f.rule for f in validate_workspace(recycle).findings}
    assert "cheme.generated-outdated" in rules_found
    assert "cheme.generated-edited" not in rules_found
    path = recycle.root / "process/BFD.xml"
    path.write_bytes(path.read_bytes().replace(b"Aqueous feed", b"Aqueous feed!"))
    assert edited(path.read_bytes())
    found = [f for f in validate_workspace(recycle).findings if f.file == "process/BFD.xml"]
    assert any(f.rule == "cheme.generated-edited" and f.level == "error" for f in found)
    assert build(recycle).failed  # refuses over the hand edit without --force


def test_generator_version_change_is_reported(recycle):
    build(recycle, force=True)
    path = recycle.root / "process/BFD.xml"
    path.write_bytes(
        path.read_bytes().replace(
            f'"generator_version": "{GENERATOR_VERSION}"'.encode(), b'"generator_version": "0"'
        )
    )
    found = {f.rule for f in validate_workspace(recycle).findings}
    assert "cheme.generated-version" in found


def test_balance_imbalance_names_the_block(recycle):
    _edit(recycle, lambda d: _stream(d, "S5")["state"]["design"]["flow"].update(value=700))
    found = [f for f in _rules(recycle) if f.rule == "cheme.process-balance"]
    assert {f.ids[0] for f in found} >= {"SEP"} and all(f.level == "error" for f in found)


def test_balance_tolerance_abs_and_rel(recycle):
    _edit(recycle, lambda d: _stream(d, "S5")["state"]["design"]["flow"].update(value=604))
    assert not [f for f in _rules(recycle) if f.rule == "cheme.process-balance"]  # 0.5 %
    _edit(recycle, lambda d: d.update(tolerance={"abs": 1.0, "rel": 0.0}))
    assert [f for f in _rules(recycle) if f.rule == "cheme.process-balance"]


def test_missing_flow_is_not_evaluable_info(recycle):
    _edit(recycle, lambda d: _stream(d, "S4")["state"]["design"].pop("flow"))
    found = [f for f in _rules(recycle) if f.rule.startswith("cheme.process-balance")]
    assert found and {f.level for f in found} == {"info"}
    assert any("S4 flow" in f.message for f in found)


def test_unsupported_scope_and_internal_streams_cancel(recycle):
    process, _ = load(recycle.root)
    sep = next(b for b in balances(process) if b.node == "SEP")
    assert "S6" not in sep.streams_in + sep.streams_out
    _edit(recycle, lambda d: d["blocks"][1].update(balance_scope="dynamic"))
    assert any(f.rule == "cheme.process-balance-unsupported" for f in _rules(recycle))


def test_balance_of_every_case(blocks):
    """A second case is balanced too (pre-release issue 185): its imbalance names it, the default
    case stays clean, and the info findings are not repeated per case."""
    infos = sorted(f.message for f in _rules(blocks) if f.level == "info")

    def turndown(d):
        d["cases"].append({"id": "turndown", "description": "Turndown"})
        for s in d["streams"]:
            s["state"]["turndown"] = copy.deepcopy(s["state"]["design"])
        _stream(d, "S1")["state"]["turndown"]["flow"]["value"] = 9999

    _edit(blocks, turndown)
    found = _rules(blocks)
    errors = [f for f in found if f.rule == "cheme.process-balance"]
    assert errors and all("(turndown)" in f.message for f in errors)
    assert "MIX" in {f.ids[0] for f in errors}
    assert sorted(f.message for f in found if f.level == "info") == infos


@pytest.mark.parametrize(
    ("change", "rule"),
    [
        (lambda d: d["units"].update(pressure="kPa"), "cheme.process-unit"),
        (lambda d: d["units"].update(pressure="kPa(g)"), "cheme.process-gauge-default"),
        (lambda d: d["units"].update(flow="Nm3/h"), "cheme.process-normal-conditions"),
        (
            lambda d: _stream(d, "S1")["state"]["design"]["flow"].update(basis="mole"),
            "cheme.process-basis",
        ),
        (
            lambda d: _stream(d, "S1")["state"]["design"]["composition"]["values"].update(ETOH=0.5),
            "cheme.process-composition-sum",
        ),
        (
            lambda d: _stream(d, "S1")["state"]["design"]["composition"]["values"].update(N2=0.0),
            "cheme.process-component",
        ),
        (
            lambda d: d["streams"].append(dict(_stream(d, "S1"), id="S1")),
            "cheme.process-duplicate-id",
        ),
        (lambda d: _stream(d, "S1").update(to="MIX.feed"), "cheme.process-port-reused"),
        (lambda d: d["steps"][0]["ports"][0].pop("delegates"), "cheme.process-delegation"),
        (lambda d: _stream(d, "S1").update(id="S 1"), "cheme.process-id"),
    ],
)
def test_rules(recycle, change, rule):
    _edit(recycle, change)
    assert rule in {f.rule for f in _rules(recycle)}


def test_explicit_gauge_pressure_is_accepted(recycle):
    _edit(recycle, lambda d: _stream(d, "S1")["state"]["design"]["pressure"].update(unit="kPa(g)"))
    assert not [f for f in _rules(recycle) if f.level == "error"]


def test_schema_errors_are_versioned(recycle):
    _edit(recycle, lambda d: d.update(schema="cheme/process/v9"))
    process, found = load(recycle.root)
    assert process is None and found[0].rule == "cheme.process-schema"
    assert "cheme/process/v1" in found[0].message


def test_schema_field_errors_name_the_schema_and_line(recycle):
    _edit(recycle, lambda d: _stream(d, "S2")["state"]["design"].update(presure={"value": 1}))
    process, found = load(recycle.root)
    bad = [f for f in found if f.rule == "cheme.process-schema"]
    assert process is None and bad, [f.format() for f in found]
    assert "cheme/process/v1" in bad[0].message and "presure" in bad[0].format()
    assert bad[0].line


def test_block_only_bfd_builds_and_renders(blocks):
    from chemeascode.domains.piping.render import render_file

    assert not build(blocks).failed
    out = render_file(blocks.root / "process/BFD.xml", blocks.root / "bfd.svg")
    assert "Feed preparation" in out.read_text()


def test_only_the_cycle_cut_warning_is_demoted(recycle):
    build(recycle, force=True)
    found, model = check_sheet(recycle.root / "process/PFD.xml", "process/PFD.xml")
    loads = [f for f in found if f.rule == "dexpi.load"]
    assert len(loads) == 1 and loads[0].level == "info"  # summarized: one line per sheet
    assert "reference cycles cut" in loads[0].message and loads[0].ids and loads[0].hint

    tail = ". Its unresolved required references are deferred to the reference pass."

    class Entry:
        message = "Cyclic dependency detected involving object FEED_out" + tail
        object_id = "FEED_out"

    assert is_cycle_cut(Entry(), model)
    Entry.message = "Some other warning about FEED_out"
    assert not is_cycle_cut(Entry(), model)
    Entry.object_id = "FEED"  # a step, not a port: stays a warning
    Entry.message = "Cyclic dependency detected involving object FEED" + tail
    assert not is_cycle_cut(Entry(), model)


def test_links_unresolved_are_info(recycle):
    found = [f for f in _rules(recycle) if f.rule == "cheme.process-link-unresolved"]
    assert found and {f.level for f in found} == {"info"}


def test_pid_files_exclude_process_sheets(recycle):
    assert recycle.pid_files() == [] or all(p.parent.name == "pid" for p in recycle.pid_files())
    assert {p.name for p in recycle.process_files()} == {"BFD.xml", "PFD.xml"}


def test_streams_cli_formats(recycle, monkeypatch):
    from typer.testing import CliRunner

    from chemeascode.interfaces.cli import app

    monkeypatch.chdir(recycle.root)
    runner = CliRunner()
    for flag, needle in (("--md", "| S1 |"), ("--csv", "S1,Feed"), ("--json", '"balances"')):
        result = runner.invoke(app, ["process", "streams", flag])
        assert result.exit_code == 0 and needle in result.output, result.output


def test_an_optional_step_method_is_looked_up_in_its_enum():
    import pydexpi.pydexpi_classes.pydexpi_classes as C

    from chemeascode.domains.process.build import step_method

    pumping = C.Pumping.model_fields["method"].annotation  # PumpingMethod | Undefined | None
    assert step_method(pumping, None) is C.PumpingMethod.UNSPECIFIED
    assert step_method(pumping, "centrifugalmotion") is C.PumpingMethod.CENTRIFUGALMOTION
    assert step_method(int | None, None) is None
