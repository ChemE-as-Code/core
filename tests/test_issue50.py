"""#50: cheme process propagate derives compositions and flows through simple steps."""

import yaml
from typer.testing import CliRunner

from chemeascode.domains.process.model import balance_of, load, rules
from chemeascode.domains.process.propagate import behaviour, run
from chemeascode.foundation.workspace import Workspace
from chemeascode.interfaces.cli import app

MATERIALS = """\
schema: cheme/process/v1
kind: materials
components:
  - {id: N2, name: Nitrogen, cas: 7727-37-9, molar_mass: 28.014}
  - {id: O2, name: Oxygen, cas: 7782-44-7, molar_mass: 31.998}
templates:
  - {id: air, components: [N2, O2]}
"""

FLOWSHEET = """\
# propagate test: comments must survive --fill.
schema: cheme/process/v1
kind: flowsheet
feeds:
  - {id: AIR, ports: [{id: a, direction: out}]}
  - {id: NIT, ports: [{id: a, direction: out}]}
  - {id: FS, ports: [{id: a, direction: out}]}
products:
  - id: P
    ports:
      - {id: a, direction: in}
      - {id: b, direction: in}
      - {id: c, direction: in}
      - {id: d, direction: in}
blocks:
  - {id: K, class: Compressing, ports: [{id: in, direction: in}, {id: out, direction: out}]}
  - id: MX
    class: MixingSimple
    ports: [{id: a, direction: in}, {id: b, direction: in}, {id: out, direction: out}]
  - id: SP
    class: SplittingMaterial
    split: {x: 0.25}
    ports: [{id: in, direction: in}, {id: x, direction: out}, {id: y, direction: out}]
  - id: SEP
    class: Distilling
    ports: [{id: in, direction: in}, {id: top, direction: out}, {id: bot, direction: out}]
streams:
  - id: S1
    from: AIR.a
    to: K.in
    template: air
    state:
      design:
        flow: {value: 1000, provenance: assumed}
        composition: {basis: mole_fraction, values: {N2: 0.79, O2: 0.21}, provenance: assumed}
  - id: S2
    from: K.out
    to: MX.a
    template: air
  - id: S3
    from: NIT.a
    to: MX.b
    template: air
    state:
      design:
        flow: {value: 500, provenance: given}
        composition: {basis: mole_fraction, values: {N2: 1.0}, provenance: given}
  - id: S4
    from: MX.out
    to: SP.in
    template: air
  - id: S5
    from: SP.x
    to: P.a
    template: air
  - id: S6
    from: SP.y
    to: P.b
    template: air
    state:
      design:
        # outlet temperature known
        temperature: {value: 300, provenance: assumed}
  - id: S7
    from: FS.a
    to: SEP.in
    template: air
    state:
      design:
        flow: {value: 100, provenance: assumed}
        composition: {basis: mole_fraction, values: {N2: 0.79, O2: 0.21}, provenance: assumed}
  - id: S8
    from: SEP.top
    to: P.c
    template: air
  - id: S9
    from: SEP.bot
    to: P.d
    template: air
"""


def _plant(tmp_path, flowsheet=FLOWSHEET):
    root = tmp_path / "plant"
    (root / "process").mkdir(parents=True)
    (root / "plant.yaml").write_text("name: propagate-test\nstage: concept\nsheets: []\n")
    (root / "process/materials.yaml").write_text(MATERIALS)
    (root / "process/flowsheet.yaml").write_text(flowsheet)
    return Workspace(root)


def _run(ws, write=True):
    process, found = load(ws.root)
    assert process is not None, [f.format() for f in found]
    return run(ws, process, "design", write=write)


def _state(ws, sid):
    data = yaml.safe_load((ws.root / "process/flowsheet.yaml").read_text())
    stream = next(s for s in data["streams"] if s["id"] == sid)
    return stream.get("state", {}).get("design", {})


def test_behaviour_by_dexpi_class():
    assert behaviour("Compressing") == "pass-through"
    assert behaviour("Cooling") == "pass-through"
    assert behaviour("StaticMixing") == "mixer"
    assert behaviour("SplittingMaterial") == "splitter"
    assert behaviour("Distilling") == "separator"
    assert behaviour("Adsorbing") == "separator"
    assert behaviour("ReactingChemicals") == "reactor"
    assert behaviour("ProcessStep") is None


def test_pass_through_keeps_composition_and_flow(tmp_path):
    ws = _plant(tmp_path)
    result = _run(ws)
    s2 = _state(ws, "S2")
    assert s2["composition"]["values"] == {"N2": 0.79, "O2": 0.21}
    assert s2["composition"]["provenance"] == "calculated"
    assert s2["composition"]["source"] == "cheme process propagate: pass-through K from S1"
    assert len(s2["composition"]["fingerprint"]) == 16
    assert s2["flow"]["value"] == 1000
    assert s2["flow"]["provenance"] == "calculated"
    assert "S2 composition: pass-through K from S1" in result.lines
    assert (
        "# propagate test: comments must survive --fill."
        in (ws.root / "process/flowsheet.yaml").read_text()
    )


def test_mixer_combines_flows_and_compositions(tmp_path):
    ws = _plant(tmp_path)
    _run(ws)
    s4 = _state(ws, "S4")
    assert s4["flow"]["value"] == 1500
    assert s4["composition"]["basis"] == "mole_fraction"
    assert s4["composition"]["source"].endswith("mixer MX from S2 S3")
    x = s4["composition"]["values"]
    assert abs(sum(x.values()) - 1) < 1e-5 and x["N2"] > 0.79
    process, _ = load(ws.root)
    assert balance_of(process, "MX", "design").status == "ok"
    assert balance_of(process, "MX", "design").components  # component balance evaluable


def test_splitter_splits_with_given_fractions_and_the_remainder(tmp_path):
    ws = _plant(tmp_path)
    _run(ws)
    s4, s5, s6 = _state(ws, "S4"), _state(ws, "S5"), _state(ws, "S6")
    assert s5["flow"]["value"] == 375
    assert s6["flow"]["value"] == 1125
    assert s6["temperature"]["value"] == 300  # the existing state is kept
    assert s5["composition"]["values"] == s6["composition"]["values"] == s4["composition"]["values"]
    process, _ = load(ws.root)
    assert balance_of(process, "SP", "design").status == "ok"


def test_separator_is_refused_not_solved(tmp_path):
    ws = _plant(tmp_path)
    result = _run(ws)
    assert _state(ws, "S8") == {} and _state(ws, "S9") == {}
    found = [f for f in result.findings if f.rule == "cheme.process-propagate-not-solved"]
    assert [f.ids for f in found] == [["SEP"]]
    assert "separator" in found[0].message and found[0].line and found[0].hint


def test_given_and_assumed_values_are_never_overwritten(tmp_path):
    text = FLOWSHEET.replace(
        "    to: MX.a\n    template: air\n",
        "    to: MX.a\n    template: air\n    state:\n      design:\n"
        "        composition: {basis: mole_fraction, values: {N2: 0.8, O2: 0.2}, "
        "provenance: assumed, source: hand}\n",
    )
    ws = _plant(tmp_path, text)
    _run(ws)
    s2 = _state(ws, "S2")
    assert s2["composition"] == {
        "basis": "mole_fraction",
        "values": {"N2": 0.8, "O2": 0.2},
        "provenance": "assumed",
        "source": "hand",
    }
    assert s2["flow"]["provenance"] == "calculated"  # the missing flow is still derived
    assert _state(ws, "S1")["composition"]["provenance"] == "assumed"
    assert _state(ws, "S3")["flow"] == {"value": 500, "provenance": "given"}


def test_second_fill_writes_nothing_and_check_is_clean(tmp_path):
    ws = _plant(tmp_path)
    _run(ws)
    before = (ws.root / "process/flowsheet.yaml").read_text()
    assert _run(ws).written == 0
    assert (ws.root / "process/flowsheet.yaml").read_text() == before
    check = _run(ws, write=False)
    assert not [f for f in check.findings if f.level != "info"]


def test_changed_inputs_make_propagated_values_stale(tmp_path, monkeypatch):
    ws = _plant(tmp_path)
    _run(ws)
    path = ws.root / "process/flowsheet.yaml"
    path.write_text(
        path.read_text().replace(
            "{N2: 0.79, O2: 0.21}, provenance: assumed}\n",
            "{N2: 0.7, O2: 0.3}, provenance: assumed}\n",
            1,
        )
    )
    process, _ = load(ws.root)
    stale = [f for f in rules(process) if f.rule == "cheme.process-calculated-stale"]
    assert {f.ids[0] for f in stale} == {"S2", "S4", "S5", "S6"}
    assert "propagate --fill" in stale[0].hint
    monkeypatch.chdir(ws.root)
    assert CliRunner().invoke(app, ["process", "propagate", "--check"]).exit_code == 1
    shown = CliRunner().invoke(app, ["process", "propagate", "--fill"])
    assert shown.exit_code == 0, shown.output
    assert _state(ws, "S2")["composition"]["values"] == {"N2": 0.7, "O2": 0.3}
    process, _ = load(ws.root)
    assert not [f for f in rules(process) if f.rule == "cheme.process-calculated-stale"]
    assert CliRunner().invoke(app, ["process", "propagate", "--check"]).exit_code == 0


def test_fill_or_check_is_required(tmp_path, monkeypatch):
    monkeypatch.chdir(_plant(tmp_path).root)
    assert CliRunner().invoke(app, ["process", "propagate"]).exit_code == 2
