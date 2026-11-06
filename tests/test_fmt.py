import warnings
from pathlib import Path

import pytest
from lxml import etree

from chemeascode.domains.piping.fmt import FormatRefused, assign_ids, format_bytes, format_file
from tests.conftest import REFERENCE


def test_assign_ids_is_deterministic_and_readable():
    root = etree.fromstring(
        b'<Model><Object id="Tank1" type="Plant/ProcessEquipment.Tank">'
        b'<Components property="Nozzles"><Object type="Plant/ProcessEquipment.Nozzle"/>'
        b'<Object type="Plant/ProcessEquipment.Nozzle"/></Components></Object>'
        b'<Object type="Core/Diagram.RepresentationGroup">'
        b'<References objects="#Tank1" property="Represents"/></Object></Model>'
    )
    assert assign_ids(root) == 3
    assert [e.get("id") for e in root.iter("Object")] == [
        "Tank1",
        "Tank1_Nozzles1",
        "Tank1_Nozzles2",
        "Tank1_Drawing1",
    ]
    assert assign_ids(root) == 0


def test_format_is_idempotent_and_ids_every_object(tmp_path: Path):
    path = tmp_path / "P-01.xml"
    path.write_bytes(REFERENCE.read_bytes())
    first = format_file(path)
    assert first.changed and first.ids_assigned > 1000
    root = etree.parse(str(path)).getroot()
    assert all(e.get("id") for e in root.iter("Object"))
    assert not format_file(path).changed
    assert not format_file(path, check=True).changed


def test_format_keeps_the_conceptual_model():
    from pydexpi.toolkits.model_summary import summarize_model

    from chemeascode.domains.piping.render import load_model

    formatted, _ = format_bytes(REFERENCE.read_bytes())
    before = summarize_model(load_model(REFERENCE))
    after = summarize_model(load_model(formatted))
    assert [e.tag for e in before.equipment] == [e.tag for e in after.equipment]
    assert before.piping_component_count == after.piping_component_count
    assert [e.tag for e in before.instruments] == [e.tag for e in after.instruments]


def test_format_refuses_what_it_would_drop():
    text = REFERENCE.read_text(encoding="utf-8")
    broken = text.replace('objects="#GlobeValve1"', 'objects="#Nowhere"', 1).encode()
    with pytest.raises(FormatRefused, match="drop content"):
        format_bytes(broken)
    with pytest.raises(FormatRefused, match="well-formed"):
        format_bytes(text[:3000].encode())


def test_format_keeps_the_model_name_and_uri(tmp_path: Path):
    """fmt used to write name="example" uri="http://www.example.org" back on every run."""
    path = tmp_path / "P-02.xml"
    path.write_bytes(REFERENCE.read_bytes())
    format_file(path)
    text = path.read_text(encoding="utf-8").replace(
        '<Model name="example" uri="http://www.example.org">',
        '<Model name="ASU-1" uri="urn:asu-1">',
        1,
    )
    path.write_text(text, encoding="utf-8")
    assert not format_file(path, check=True).changed
    format_file(path)
    root = etree.parse(str(path)).getroot()
    assert (root.get("name"), root.get("uri")) == ("ASU-1", "urn:asu-1")
    assert not format_file(path).changed


TANK = b'<Object id="Tank1" type="Plant/ProcessEquipment.Tank">'


def _with(tmp_path: Path, inside_tank: bytes, before_tank: bytes = b"") -> Path:
    """A formatted copy of the reference with markup added to its Tank1."""
    path = tmp_path / "P-01.xml"
    path.write_bytes(REFERENCE.read_bytes())
    format_file(path)
    content = path.read_bytes()
    start = content.index(TANK)
    end = start + len(TANK)
    path.write_bytes(content[:start] + before_tank + TANK + inside_tank + content[end:])
    return path


def test_format_refuses_a_data_property_pydexpi_would_ignore(tmp_path: Path, monkeypatch):
    """An unknown Data property is a loader warning ('will be ignored'), not an error."""
    from typer.testing import CliRunner

    from chemeascode.interfaces.cli import app

    note = b'<Data property="MyCustomNote"><String>vendor X</String></Data>'
    path = _with(tmp_path, note)
    content = path.read_bytes()
    with pytest.raises(FormatRefused, match="myCustomNote.*will be ignored"):
        format_file(path)
    out = CliRunner().invoke(app, ["fmt", str(path)])
    assert out.exit_code == 1 and "refused" in out.output and "myCustomNote" in out.output
    assert path.read_bytes() == content


def test_format_reports_the_comments_it_drops(tmp_path: Path):
    """Comments and processing instructions do not survive; each one is reported."""
    from typer.testing import CliRunner

    from chemeascode.interfaces.cli import app

    path = _with(
        tmp_path, b"<?vendor keep?>", b"<!-- KEEP: FV-104 fail-closed per vendor datasheet -->"
    )
    result = format_file(path, check=True)
    assert result.changed
    assert len(result.dropped) == 2
    assert result.dropped[0].startswith("line ") and "KEEP: FV-104" in result.dropped[0]
    assert "<?vendor keep?>" in result.dropped[1]
    out = CliRunner().invoke(app, ["fmt", str(path)])
    assert out.exit_code == 0
    assert "dropped 2 XML comment(s)" in out.output and "KEEP: FV-104" in out.output
    assert b"KEEP" not in path.read_bytes()
    assert not format_file(path).dropped


PROVENANCE = b'<!-- cheme-process {"view": "pfd"} -->'
LATER = b"<!-- cheme-test second -->"


def _top(path: Path) -> list[bytes]:
    """The lines of *path* before its root element, XML declaration (if any) left out."""
    lines = path.read_bytes().splitlines()
    lines = lines[1:] if lines[0].startswith(b"<?xml") else lines
    return lines[: next(i for i, line in enumerate(lines) if line.startswith(b"<Model"))]


def test_format_keeps_cheme_provenance_comments_and_reports_the_rest(tmp_path: Path):
    """A ``cheme-`` comment survives, after the XML declaration, in document order."""
    from typer.testing import CliRunner

    from chemeascode.domains.piping.fmt import kept_comments
    from chemeascode.domains.process import provenance
    from chemeascode.interfaces.cli import app

    path = _with(tmp_path, LATER, PROVENANCE + b"<!-- KEEP: vendor datasheet -->")
    result = format_file(path, check=True)
    assert len(result.dropped) == 1 and "KEEP: vendor datasheet" in result.dropped[0]
    out = CliRunner().invoke(app, ["fmt", str(path)])
    assert out.exit_code == 0, out.output
    assert "dropped 1 XML comment(s)" in out.output and "cheme-" not in out.output
    assert _top(path)[:2] == [PROVENANCE, LATER]  # pyDEXPI's banner after them
    assert b"KEEP" not in path.read_bytes()
    assert provenance.read(path.read_bytes()) == {"view": "pfd"}
    kept = [' cheme-process {"view": "pfd"} ', " cheme-test second "]
    assert kept_comments(path.read_bytes()) == kept
    again = format_file(path)
    assert not again.changed and not again.dropped


def test_authoring_writes_keep_cheme_provenance_comments(tmp_path: Path):
    from chemeascode.domains.piping.authoring import Sheet
    from chemeascode.domains.piping.authoring.edit import set_values

    path = _with(tmp_path, b"", PROVENANCE)
    result = set_values(path, "Tank1", [("CylinderLength", "5 Metre")])
    assert not any("dropped" in n for n in result.notes), result.notes
    assert _top(path)[0] == PROVENANCE

    path = _with(tmp_path, LATER, b"<!-- KEEP: vendor datasheet -->")
    sheet = Sheet.load(path)
    with pytest.warns(UserWarning, match=r"dropped 1 XML comment.*KEEP") as caught:
        sheet.save()
    assert all("cheme-test" not in str(w.message) for w in caught)
    assert _top(path)[0] == LATER


def test_authoring_writes_keep_a_provenance_comment_before_the_root(tmp_path: Path):
    """Where ``process.provenance.stamp`` puts it: a sibling of the root, not inside it."""
    from chemeascode.domains.piping.authoring import Sheet
    from chemeascode.domains.piping.authoring.edit import set_values
    from chemeascode.domains.piping.sheets import set_metadata

    path = _with(tmp_path, b"")
    stamped = PROVENANCE + b"\n" + path.read_bytes()
    path.write_bytes(stamped)
    set_values(path, "Tank1", [("CylinderLength", "5 Metre")])
    assert _top(path)[0] == PROVENANCE

    path.write_bytes(stamped)
    with warnings.catch_warnings():
        warnings.simplefilter("error")
        Sheet.load(path).save()
    assert _top(path)[0] == PROVENANCE

    written, _ = set_metadata(stamped, {"DrawingNumber": "P-01"})
    assert written.splitlines()[0] == PROVENANCE


def test_authoring_edits_pass_the_refusal_and_the_dropped_comments_on(tmp_path: Path):
    from chemeascode.domains.piping.authoring.edit import set_values

    path = _with(tmp_path, b'<Data property="MyCustomNote"><String>vendor X</String></Data>')
    result = set_values(path, "Tank1", [("CylinderLength", "5 Metre")])
    assert any("refused" in n and "written unformatted" in n for n in result.notes), result.notes
    assert b"MyCustomNote" in path.read_bytes()  # the edit is written, the note kept

    path = _with(tmp_path, b"", b"<!-- KEEP: vendor datasheet -->")
    result = set_values(path, "Tank1", [("CylinderLength", "5 Metre")])
    assert any("dropped 1 XML comment" in n and "KEEP" in n for n in result.notes), result.notes


def test_the_pydexpi_banner_of_any_version_is_not_reported(tmp_path: Path):
    path = _with(tmp_path, b"")
    text = path.read_text(encoding="utf-8")
    banner = text.splitlines()[1] if text.startswith("<?xml") else text.splitlines()[0]
    assert banner.startswith("<!-- Generated with pyDEXPI"), banner
    path.write_text(text.replace(banner, "<!-- Generated with pyDEXPI 0.9.9 - elsewhere -->"))
    assert format_file(path, check=True).dropped == []


def test_sheet_save_reports_the_comments_it_drops(tmp_path: Path):
    """The Python authoring API formats on save: a dropped comment is a warning and a note."""
    from chemeascode.domains.piping.authoring import Sheet

    path = _with(tmp_path, b"", b"<!-- KEEP: vendor datasheet -->")
    sheet = Sheet.load(path)
    with pytest.warns(UserWarning, match="dropped 1 XML comment.*KEEP: vendor datasheet"):
        sheet.save()
    assert any("KEEP" in n for n in sheet.notes)
    assert b"KEEP" not in path.read_bytes()


def test_sheet_save_refuses_a_data_property_pydexpi_would_ignore(tmp_path: Path):
    from chemeascode.domains.piping.authoring import Sheet
    from chemeascode.domains.piping.authoring.sheet import AuthoringError

    path = _with(tmp_path, b'<Data property="MyCustomNote"><String>vendor X</String></Data>')
    content = path.read_bytes()
    with pytest.raises(AuthoringError, match="myCustomNote"):
        Sheet.load(path).save()
    assert path.read_bytes() == content


def test_sheet_meta_reports_the_comments_it_drops(plant: Path, monkeypatch):
    from typer.testing import CliRunner

    from chemeascode.interfaces.cli import app

    path = plant / "pid" / "P-01.xml"
    format_file(path)
    content = path.read_bytes()
    start = content.index(TANK)
    path.write_bytes(content[:start] + b"<!-- KEEP: vendor datasheet -->" + content[start:])
    monkeypatch.chdir(plant)
    out = CliRunner().invoke(app, ["sheet", "meta", "pid/P-01.xml", "Revision=B"])
    assert out.exit_code == 0, out.output
    assert "dropped 1 XML comment(s)" in out.output and "KEEP: vendor datasheet" in out.output


def test_fmt_leaves_generated_process_sheets_as_built(tmp_path: Path, monkeypatch):
    """A BFD/PFD from ``cheme process build`` (unindented, ADR 0048) is not reformatted by
    ``cheme fmt``, ``cheme fmt --check`` or ``cheme run --fmt``: it stays as built and validates
    clean, so "``cheme fmt <sheet>``, then ``cheme validate``" works on it."""
    import shutil

    from typer.testing import CliRunner

    from chemeascode.domains.piping.fmt import is_process_sheet
    from chemeascode.domains.process.sheets import build, edited
    from chemeascode.foundation.workspace import Workspace
    from chemeascode.interfaces.cli import app

    root = tmp_path / "plant"
    examples = Path(__file__).resolve().parents[1] / "examples"
    shutil.copytree(examples / "process-recycle", root, ignore=shutil.ignore_patterns("build"))
    assert not build(Workspace(root), force=True).failed
    monkeypatch.chdir(root)
    (root / "scripts").mkdir(exist_ok=True)
    (root / "scripts/noop.py").write_text("print('nothing to draw')\n", encoding="utf-8")
    runner = CliRunner()
    for sheet in ("process/BFD.xml", "process/PFD.xml"):
        built = (root / sheet).read_bytes()
        assert is_process_sheet(built)
        for args in (
            ["fmt", "--check", sheet],
            ["fmt", sheet],
            ["run", "--fmt", sheet, "scripts/noop.py"],
        ):
            out = runner.invoke(app, args)
            assert out.exit_code == 0, (args, out.output)
            assert "generated, not formatted (cheme process build)" in out.output, args
            assert (root / sheet).read_bytes() == built, args
        assert not format_file(root / sheet).changed
        assert not edited(built)
    report = runner.invoke(app, ["validate", "process/BFD.xml", "process/PFD.xml"])
    assert report.exit_code == 0 and "generated-edited" not in report.output, report.output
    # a P&ID is still formatted
    assert not is_process_sheet(REFERENCE.read_bytes())
