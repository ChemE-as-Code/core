"""cheme crossings: one gap per crossing of two drawn lines, in the line the rule breaks."""

from pathlib import Path

from lxml import etree
from typer.testing import CliRunner

from chemeascode.domains.piping.authoring.crossings import apply_crossings
from chemeascode.interfaces.cli import app

runner = CliRunner()

PIPE = "Plant/Piping.Pipe"
SIGNAL = "Plant/Instrumentation.SignalConveyingFunction"


def _line(pieces: list[list[tuple[float, float]]], ids: list[str]) -> str:
    out = []
    for piece_id, pts in zip(ids, pieces, strict=True):
        values = "".join(
            '<AggregatedDataValue type="Core/Diagram.Point">'
            f'<Data property="X"><Double>{x}</Double></Data>'
            f'<Data property="Y"><Double>{y}</Double></Data></AggregatedDataValue>'
            for x, y in pts
        )
        out.append(
            f'<Object id="{piece_id}" type="Core/Diagram.ConnectorLine">'
            f'<Data property="InnerPoints">{values}</Data></Object>'
        )
    return "".join(out)


def _sheet(tmp_path: Path, lines: dict[str, tuple[str, list[list[tuple[float, float]]]]]) -> Path:
    """A sheet with one drawn line per object: {object id: (type, pieces)}."""
    model = "".join(f'<Object id="{oid}" type="{kind}"/>' for oid, (kind, _) in lines.items())
    drawing = "".join(
        f'<Object id="G_{oid}" type="Core/Diagram.RepresentationGroup">'
        f'<Components property="Groups"><Object id="S_{oid}" type="Core/Diagram.Static">'
        f'<Components property="Elements">'
        f"{_line(pieces, [f'L_{oid}_{n}' for n in range(len(pieces))])}"
        f"</Components></Object></Components>"
        f'<References objects="#{oid}" property="Represents"/></Object>'
        for oid, (_, pieces) in lines.items()
    )
    xml = (
        '<?xml version="1.0" encoding="utf-8"?>\n'
        f'<Model><Components property="Model">{model}</Components>'
        f'<Components property="Diagram">{drawing}</Components></Model>\n'
    )
    path = tmp_path / "P-01.xml"
    path.write_text(xml, encoding="utf-8")
    return path


def _pieces(path: Path, oid: str) -> list[list[tuple[float, float]]]:
    root = etree.parse(str(path)).getroot()
    group = root.find(f".//Object[@id='S_{oid}']/Components")

    def xy(value: etree._Element) -> tuple[float, float]:
        return (
            float(value.findtext("Data[@property='X']/Double")),
            float(value.findtext("Data[@property='Y']/Double")),
        )

    return [
        [xy(v) for v in line.findall("Data[@property='InnerPoints']/AggregatedDataValue")]
        for line in group.findall("Object")
    ]


def _run(path: Path) -> str:
    return apply_crossings(path, write=True, fmt=False).changes[0]


def test_signal_breaks_where_it_crosses_a_pipe(tmp_path):
    path = _sheet(
        tmp_path,
        {
            "P1": (PIPE, [[(0, 10), (40, 10)]]),
            "S1": (SIGNAL, [[(20, 0), (20, 30)]]),
        },
    )
    _run(path)
    assert _pieces(path, "P1") == [[(0, 10), (40, 10)]]
    assert _pieces(path, "S1") == [[(20, 0), (20, 8.5)], [(20, 11.5), (20, 30)]]


def test_a_vertical_pipe_runs_through_a_horizontal_signal(tmp_path):
    path = _sheet(
        tmp_path,
        {
            "P1": (PIPE, [[(20, 0), (20, 30)]]),
            "S1": (SIGNAL, [[(0, 10), (40, 10)]]),
        },
    )
    _run(path)
    assert _pieces(path, "P1") == [[(20, 0), (20, 30)]]
    assert _pieces(path, "S1") == [[(0, 10), (18.5, 10)], [(21.5, 10), (40, 10)]]


def test_a_gap_in_the_horizontal_moves_to_the_vertical(tmp_path):
    path = _sheet(
        tmp_path,
        {
            "S1": (SIGNAL, [[(0, 10), (18.5, 10)], [(21.5, 10), (40, 10)]]),
            "S2": (SIGNAL, [[(20, 0), (20, 30)]]),
        },
    )
    assert "1 gap(s) joined, 1 gap(s) cut" in _run(path)
    assert _pieces(path, "S1") == [[(0, 10), (40, 10)]]
    assert _pieces(path, "S2") == [[(20, 0), (20, 8.5)], [(20, 11.5), (20, 30)]]


def test_a_gap_already_in_the_vertical_stays(tmp_path):
    path = _sheet(
        tmp_path,
        {
            "S1": (SIGNAL, [[(0, 10), (40, 10)]]),
            "S2": (SIGNAL, [[(20, 0), (20, 8.5)], [(20, 11.5), (20, 30)]]),
        },
    )
    assert "already shown" in _run(path)


def test_a_line_under_a_bundle_gets_one_gap(tmp_path):
    path = _sheet(
        tmp_path,
        {
            "A": (SIGNAL, [[(0, 10), (40, 10)]]),
            "B": (SIGNAL, [[(0, 13), (40, 13)]]),
            "C": (SIGNAL, [[(0, 16), (40, 16)]]),
            "V": (SIGNAL, [[(20, 0), (20, 30)]]),
        },
    )
    _run(path)
    assert _pieces(path, "V") == [[(20, 0), (20, 8.5)], [(20, 17.5), (20, 30)]]


def test_a_filler_in_the_gap_is_removed(tmp_path):
    path = _sheet(
        tmp_path,
        {
            "H": (SIGNAL, [[(0, 10), (40, 10)]]),
            "V": (SIGNAL, [[(20, 0), (20, 8.5)], [(20, 11.5), (20, 8.5)], [(20, 11.5), (20, 30)]]),
        },
    )
    assert "1 gap filler(s) removed" in _run(path)
    assert _pieces(path, "V") == [[(20, 0), (20, 8.5)], [(20, 11.5), (20, 30)]]


def test_second_run_changes_nothing(tmp_path):
    path = _sheet(
        tmp_path,
        {
            "S1": (SIGNAL, [[(0, 10), (18.5, 10)], [(21.5, 10), (40, 10)]]),
            "S2": (SIGNAL, [[(20, 0), (20, 30)]]),
            "P1": (PIPE, [[(0, 20), (40, 20)]]),
        },
    )
    _run(path)
    again = apply_crossings(path, write=False, fmt=False)
    assert again.diff == ""


def test_check_exits_1_until_the_sheet_follows_the_rule(tmp_path):
    path = _sheet(
        tmp_path,
        {
            "P1": (PIPE, [[(0, 10), (40, 10)]]),
            "S1": (SIGNAL, [[(20, 0), (20, 30)]]),
        },
    )
    assert runner.invoke(app, ["crossings", str(path), "--check", "--no-fmt"]).exit_code == 1
    assert runner.invoke(app, ["crossings", str(path), "--no-fmt"]).exit_code == 0
    assert runner.invoke(app, ["crossings", str(path), "--check", "--no-fmt"]).exit_code == 0
