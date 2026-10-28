"""#48: crossing-minimised layout inside blocks; nested blocks drawn inside their parent."""

import shutil
from pathlib import Path

import pytest
import yaml

from chemeascode.domains.process.build import place
from chemeascode.domains.process.layout import LEdge, LNode, layout
from chemeascode.domains.process.model import balances, load, rules
from chemeascode.domains.process.sheets import build
from chemeascode.foundation.workspace import Workspace
from chemeascode.project.validate import validate_workspace
from tests.test_process import _crossings, _label_hits, _overlaps, _segments, _through

EXAMPLES = Path(__file__).resolve().parents[1] / "examples"


@pytest.fixture
def nested(tmp_path):
    shutil.copytree(
        EXAMPLES / "process-nested", tmp_path / "nested", ignore=shutil.ignore_patterns("build")
    )
    return Workspace(tmp_path / "nested")


def _edit(ws, change):
    path = ws.root / "process/flowsheet.yaml"
    data = yaml.safe_load(path.read_text())
    change(data)
    path.write_text(yaml.safe_dump(data, sort_keys=False))


def _rules(ws):
    process, found = load(ws.root)
    assert process is not None, [f.format() for f in found]
    return found + rules(process)


def _block(data, bid):
    return next(b for b in data["blocks"] if b["id"] == bid)


def test_ports_are_ordered_by_where_their_lines_go():
    """Inside a block, a node's ports follow the heights of the nodes they connect to, so two
    lines from one side do not cross (declared order A.o1 -> lower node, A.o2 -> upper; the
    nodes are pinned, so reordering the layer cannot help)."""

    def run(order_ports):
        nodes = [
            LNode("A", 30, 30, outs=["o1", "o2"]),
            LNode("B", 30, 14, ins=["i"], x=100, y=10, pinned=True),
            LNode("C", 30, 14, ins=["i"], x=100, y=60, pinned=True),
        ]
        edges = [LEdge("E1", "A", "o1", "C", "i"), LEdge("E2", "A", "o2", "B", "i")]
        layout(nodes, edges, grid_feedback=True, order_ports=order_ports)
        return nodes[0].outs, _crossings({e.id: e.points for e in edges})

    assert run(False) == (["o1", "o2"], 1)
    assert run(True) == (["o2", "o1"], 0)


def test_nested_example_builds_and_validates_clean(nested):
    assert not build(nested, force=True).failed
    report = validate_workspace(nested)
    assert not [f.format() for f in report.findings if f.level != "info"]
    assert not [f for f in report.findings if f.rule == "cheme.process-parent"]


def test_committed_nested_example_is_current():
    report = validate_workspace(Workspace(EXAMPLES / "process-nested"))
    bad = [f for f in report.findings if f.rule.startswith("cheme.generated-")]
    assert not bad, [f.format() for f in bad]


def test_nested_block_is_a_sub_step_with_delegated_ports(nested):
    from pydexpi.loaders.public import load_xml_with_report

    build(nested, force=True)
    pfd = load_xml_with_report((nested.root / "process/PFD.xml").read_bytes()).model
    model = pfd.conceptualModel
    assert {s.id for s in model.processSteps} == {"FEED", "STEAM", "MIX", "SEP", "PROD", "WATER"}
    sep = next(s for s in model.processSteps if s.id == "SEP")
    assert {s.id for s in sep.subProcessSteps} == {"E2", "COL"}
    col = next(s for s in sep.subProcessSteps if s.id == "COL")
    assert {s.id for s in col.subProcessSteps} == {"C1", "E1"}
    c1_in = next(
        p
        for p in next(s for s in col.subProcessSteps if s.id == "C1").ports
        if p.identifier == "in"
    )
    assert c1_in.superReference.id == "COL_in"
    assert c1_in.superReference.superReference.id == "SEP_in"
    s5 = next(c for c in model.processConnections if c.id == "S5")  # inside SEP: COL -> E2
    assert (s5.source.id, s5.target.id) == ("COL_bottom", "E2_in")
    bfd = load_xml_with_report((nested.root / "process/BFD.xml").read_bytes()).model
    assert {s.id for s in bfd.conceptualModel.processSteps} == {
        "FEED",
        "STEAM",
        "MIX",
        "SEP",
        "PROD",
        "WATER",
    }
    shown = {c.id for c in bfd.conceptualModel.processConnections}
    assert shown == {"S1", "S2", "S3", "S4", "S7", "Q1"}


def _box(n):
    return (n.x, n.y, n.x + n.width, n.y + n.height)


def _contains(outer, inner):
    a, b = _box(outer), _box(inner)
    return a[0] < b[0] and a[1] < b[1] and b[2] < a[2] and b[3] < a[3]


def test_nested_block_is_drawn_inside_its_parent(nested):
    process, _ = load(nested.root)
    pfd = place(process, "pfd")
    nodes = pfd.nodes
    assert _contains(nodes["SEP"], nodes["COL"]) and _contains(nodes["SEP"], nodes["E2"])
    assert _contains(nodes["COL"], nodes["C1"]) and _contains(nodes["COL"], nodes["E1"])
    assert not _contains(nodes["COL"], nodes["E2"])
    assert set(pfd.routes) == {s.id for s in process.flowsheet.streams}
    # every delegation hop is drawn: step to nested block, nested block to parent
    assert {"C1.in", "COL.in", "E2.out", "COL.top"} <= set(pfd.delegations)
    assert not _overlaps({**pfd.routes, **pfd.delegations})
    assert not _label_hits(process, pfd)
    # no line runs through a node it does not belong to (a block holds what is inside it)
    for key, points in {**pfd.routes, **pfd.delegations}.items():
        stream = next((s for s in process.flowsheet.streams if s.id == key), None)
        ends = [stream.from_, stream.to] if stream else [key]
        holders = set()
        for end in ends:
            node = end.split(".")[0]
            holders |= {node, *process.ancestors(node)}
        for node_id, node in nodes.items():
            if node_id not in holders:
                assert not any(_through(s, node) for s in _segments(points)), (key, node_id)
    bfd = place(process, "bfd")
    assert "COL" not in bfd.nodes and "C1" not in bfd.nodes


def test_nested_balances_count_the_inside(nested):
    process, _ = load(nested.root)
    found = {b.node: (b.status, b.inlet, b.outlet) for b in balances(process) if b.kind == "block"}
    assert found["SEP"] == ("ok", 1500.0, 1500.0)
    assert found["COL"] == ("ok", 1500.0, 1500.0)


@pytest.mark.parametrize(
    ("change", "rule"),
    [
        # COL.top no longer delegates SEP.top: S3 leaves SEP at a port that delegates nothing
        (lambda d: _block(d, "COL")["ports"][2].pop("delegates"), "cheme.process-delegation"),
        (
            lambda d: _block(d, "COL")["ports"][2].update(delegates="nope"),
            "cheme.process-delegation",
        ),
        (lambda d: _block(d, "SEP").update(parent="COL"), "cheme.process-parent"),
        (
            lambda d: _block(d, "MIX")["ports"][0].update(delegates="in"),
            "cheme.process-delegation",
        ),
    ],
)
def test_nested_rules(nested, change, rule):
    _edit(nested, change)
    found = [f for f in _rules(nested) if f.rule == rule and f.level == "error"]
    assert found, rule
    assert all(f.hint or f.message for f in found)
