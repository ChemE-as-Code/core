"""The reaction library: every entry consistent (elements, heats of reaction against the
formation data, catalysts), current with its source, equilibria against the literature, and
cheme chemistry library adding entries to a plant without touching what it has."""

import math
import re
import subprocess
import sys
from pathlib import Path

import pytest
import yaml
from typer.testing import CliRunner

from chemeascode.domains.chemistry.equilibrium import equilibrate_real, reaction_ln_k
from chemeascode.domains.chemistry.reactions import Reactions
from chemeascode.domains.chemistry.reactions import rules as reaction_rules
from chemeascode.domains.chemistry.thermochemistry import ln_k, reaction_enthalpy
from chemeascode.domains.process.model import load, rules
from chemeascode.domains.process.reaction_library import (
    Conflict,
    LibraryEntry,
    add_entry,
    entries,
    library_view,
    strongest_basis,
)
from chemeascode.interfaces.cli import app

ROOT = Path(__file__).resolve().parents[1]
#: (component, data) the library leaves out: chemicals and thermo know no value
GAPS = {("MA", "ideal_gas"), ("S2", "critical")}


def test_there_are_the_processes():
    assert len(entries()) == 23
    assert {"ammonia", "methanol", "steam_reforming", "sulfuric_acid", "nitric_acid"} <= set(
        entries()
    )


@pytest.mark.parametrize("eid", sorted(entries()))
def test_every_entry_is_consistent(eid):
    entry = entries()[eid]
    formulas = {c.id: c.formula for c in entry.components}
    data = {c.id: c.ideal_gas for c in entry.components}
    reactions = Reactions.model_validate(
        {
            "schema": "cheme/reactions/v1",
            "kind": "reactions",
            "reactions": [r.model_dump() for r in entry.reactions],
        }
    )
    problems = [f.message for f in reaction_rules(reactions, None, formulas) if f.level != "info"]
    assert not problems
    for reaction in entry.reactions:
        assert set(reaction.stoichiometry) <= set(formulas)
        given = reaction.heat_of_reaction
        if given is not None:
            calculated = reaction_enthalpy(reaction.stoichiometry, data, 298.15)
            assert given.value == pytest.approx(calculated, rel=0.02, abs=1000)
        if reaction.catalyst:
            assert reaction.catalyst in {c.id for c in entry.catalysts}
    for component in entry.components:
        for name in ("ideal_gas", "critical"):
            if (component.id, name) not in GAPS:
                assert getattr(component, name) is not None, (component.id, name)
    lo, hi = entry.window.temperature
    for cat in entry.catalysts:
        assert cat.window is not None and cat.window.provenance == "assumed"
    for component in entry.components:
        ideal = component.ideal_gas
        if ideal is not None and ideal.temperature_range is not None:
            # every reaction temperature of the entry is inside its heat capacity's range
            assert ideal.temperature_range[1] >= min(hi, 1000.0) - 1e-6, component.id


def test_the_library_is_current():
    pytest.importorskip("chemicals")
    pytest.importorskip("numpy")
    done = subprocess.run(
        [sys.executable, str(ROOT / "scripts" / "build_reaction_library.py"), "--check"],
        check=False,
        capture_output=True,
        text=True,
    )
    assert done.returncode == 0, done.stdout + done.stderr


def _data(eid):
    entry = entries()[eid]
    return {c.id: c.ideal_gas for c in entry.components}, {
        c.id: c.critical for c in entry.components
    }


def test_shift_and_reforming_equilibria():
    ideal, _ = _data("ht_shift")
    wgs = entries()["ht_shift"].reactions[0].stoichiometry
    t = 1000.0
    twigg = math.exp(
        5693.5 / t + 1.077 * math.log(t) + 5.44e-4 * t - 1.125e-7 * t**2 - 49170 / t**2 - 13.148
    )
    assert math.exp(ln_k(wgs, ideal, t)) == pytest.approx(twigg, rel=0.03)
    ideal, _ = _data("steam_reforming")
    smr = entries()["steam_reforming"].reactions[0].stoichiometry
    assert 24 < math.exp(ln_k(smr, ideal, 1000.0)) < 30  # bar^2, about 27


def test_ammonia_equilibrium_from_the_library():
    ideal, critical = _data("ammonia")
    reaction = entries()["ammonia"].reactions[0]
    k = reaction_ln_k(reaction, ideal, 723.15)
    out, _ = equilibrate_real(
        [reaction.stoichiometry], [k], {"N2": 1.0, "H2": 3.0}, 300 * 101.325, 723.15, critical
    )
    assert 100 * out["NH3"] / sum(out.values()) == pytest.approx(35.5, abs=1.5)  # Larson and Dodge


MATERIALS = """\
# my plant's materials: this comment must survive
schema: cheme/process/v1
kind: materials
components:
  - {id: H2, name: Hydrogen, formula: H2, cas: 1333-74-0, molar_mass: 2.016}  # kept as it is
  - id: N2
    name: Nitrogen
    formula: N2
    cas: 7727-37-9
templates:
  - {id: gas, components: [H2, N2]}
"""


def _plant(tmp_path, materials=MATERIALS):
    root = tmp_path / "plant"
    (root / "process").mkdir(parents=True)
    (root / "plant.yaml").write_text("name: library\nstage: concept\nsheets: []\n")
    (root / "process/materials.yaml").write_text(materials)
    return root


def test_adding_an_entry_keeps_the_plant_files(tmp_path):
    root = _plant(tmp_path)
    result = add_entry(root, "ammonia")
    assert result.added["process/materials.yaml"] == ["NH3"]
    assert set(result.present) == {"N2", "H2"}
    text = (root / "process/materials.yaml").read_text()
    assert "# my plant's materials: this comment must survive" in text and "# kept as it is" in text
    assert "templates:" in text
    data = yaml.safe_load(text)
    assert [c["id"] for c in data["components"]] == ["H2", "N2", "NH3"]
    assert data["templates"] == [{"id": "gas", "components": ["H2", "N2"]}]
    assert (
        yaml.safe_load((root / "process/reactions.yaml").read_text())["reactions"][0]["id"]
        == "NH3_SYN"
    )
    cats = yaml.safe_load((root / "process/catalysts.yaml").read_text())
    assert [c["id"] for c in cats["catalysts"]] == ["FE_NH3", "RU_NH3"]
    # a second process: shared components and reactions are skipped, the rest appended
    add_entry(root, "methanol")
    data = yaml.safe_load((root / "process/materials.yaml").read_text())
    assert [c["id"] for c in data["components"]] == ["H2", "N2", "NH3", "CO", "CH3OH", "CO2", "H2O"]
    again = add_entry(root, "methanol")
    assert not again.added and not again.written
    # the reactions and catalysts load and check clean in the plant
    process_reactions = yaml.safe_load((root / "process/reactions.yaml").read_text())
    reactions = Reactions.model_validate(process_reactions)
    formulas = {c["id"]: c.get("formula", "") for c in data["components"]}
    assert not [f for f in reaction_rules(reactions, None, formulas) if f.level == "error"]


def test_a_conflicting_id_adds_nothing(tmp_path):
    root = _plant(tmp_path, MATERIALS.replace("cas: 1333-74-0", "cas: 0000-00-0"))
    with pytest.raises(Conflict, match="component H2"):
        add_entry(root, "ammonia")
    assert not (root / "process/reactions.yaml").exists()


def test_flow_and_empty_lists(tmp_path):
    root = _plant(tmp_path, "schema: cheme/process/v1\nkind: materials\ncomponents: []\n")
    add_entry(root, "sulfuric_acid")
    assert [
        c["id"] for c in yaml.safe_load((root / "process/materials.yaml").read_text())["components"]
    ] == ["SO2", "O2", "SO3"]
    flow = _plant(
        tmp_path / "flow",
        "schema: cheme/process/v1\nkind: materials\ncomponents: [{id: X, name: X}]\n",
    )
    with pytest.raises(Conflict, match="not a block list"):
        add_entry(flow, "sulfuric_acid")


def test_the_command(tmp_path, monkeypatch):
    listed = CliRunner().invoke(app, ["chemistry", "library"])
    assert listed.exit_code == 0 and "nitric_acid" in listed.output
    shown = CliRunner().invoke(app, ["chemistry", "library", "nitric_acid"])
    assert "NH3_OX: 4 NH3 + 5 O2 -> 4 NO + 6 H2O (PT_RH)" in shown.output
    assert CliRunner().invoke(app, ["chemistry", "library", "nope"]).exit_code == 2
    root = _plant(tmp_path)
    monkeypatch.chdir(root)
    added = CliRunner().invoke(app, ["chemistry", "library", "ammonia", "--add"])
    assert added.exit_code == 0 and "process/materials.yaml: added NH3" in added.output
    assert (
        "nothing to add"
        in CliRunner().invoke(app, ["chemistry", "library", "ammonia", "--add"]).output
    )
    as_json = CliRunner().invoke(app, ["chemistry", "library", "ammonia", "--json"])
    assert '"NH3_SYN"' in as_json.output


def test_an_added_entry_runs_in_a_flowsheet(tmp_path):
    """Methanol from the library: an equilibrium reactor with the real-gas option, clean."""
    from chemeascode.domains.process.propagate import run
    from chemeascode.foundation.workspace import Workspace

    root = _plant(tmp_path, "schema: cheme/process/v1\nkind: materials\ncomponents: []\n")
    add_entry(root, "methanol")
    (root / "process/flowsheet.yaml").write_text(
        """\
schema: cheme/process/v1
kind: flowsheet
units: {flow: kmol/h}
feeds: [{id: F, ports: [{id: out, direction: out}]}]
products: [{id: P, ports: [{id: in, direction: in}]}]
blocks:
  - id: R
    class: ReactingChemicals
    reactions: [MEOH_CO, WGS]
    reactor: equilibrium
    fugacity: peng_robinson
    catalyst: CU_ZNO
    ports: [{id: in, direction: in}, {id: out, direction: out}]
streams:
  - id: S1
    from: F.out
    to: R.in
    state:
      design:
        temperature: {value: 503.15, provenance: given}
        pressure: {value: 8000, provenance: given}
        flow: {value: 100, provenance: given}
        composition:
          basis: mole_fraction
          values: {CO: 0.25, H2: 0.7, CO2: 0.05, H2O: 0.0, CH3OH: 0.0}
          provenance: given
  - id: S2
    from: R.out
    to: P.in
    state:
      design:
        temperature: {value: 523.15, provenance: assumed}
        pressure: {value: 8000, provenance: assumed}
"""
    )
    process, found = load(root)
    assert process is not None, [f.format() for f in found]
    assert not [f.format() for f in rules(process) if f.level == "error"]
    result = run(Workspace(root), process, "design", write=True)
    assert result.written == 1, [f.format() for f in result.findings]
    out = yaml.safe_load((root / "process/flowsheet.yaml").read_text())["streams"][1]["state"][
        "design"
    ]
    assert out["composition"]["values"]["CH3OH"] > 0.1  # methanol at 250 C and 80 bar


# -- review fixes -------------------------------------------------------------------------------


def test_entries_share_their_components_and_reactions(tmp_path):
    # a hydrogen chain: every entry adds to the same plant
    root = _plant(tmp_path, "schema: cheme/process/v1\nkind: materials\ncomponents: []\n")
    for eid in ("steam_reforming", "ht_shift", "lt_shift", "methanation", "methanol"):
        add_entry(root, eid)
    data = yaml.safe_load((root / "process/reactions.yaml").read_text())
    assert [r["id"] for r in data["reactions"]].count("WGS") == 1
    # a component is one record across the library: its heat capacity covers every entry
    water = {
        e.id: next(c for c in e.components if c.id == "H2O")
        for e in entries().values()
        if any(c.id == "H2O" for c in e.components)
    }
    assert len({w.model_dump_json() for w in water.values()}) == 1
    assert water["steam_reforming"].ideal_gas.temperature_range[1] >= 1223.15


def test_files_without_a_final_newline_or_with_an_empty_key(tmp_path):
    root = _plant(
        tmp_path,
        MATERIALS.rstrip("\n")
        .replace("templates:\n  - {id: gas, components: [H2, N2]}", "")
        .rstrip(),
    )
    (root / "process/catalysts.yaml").write_text(
        "schema: cheme/catalysts/v1\nkind: catalysts\ncatalysts:\n"
    )
    add_entry(root, "ammonia")
    data = yaml.safe_load((root / "process/materials.yaml").read_text())
    assert [c["id"] for c in data["components"]] == ["H2", "N2", "NH3"]
    cats = yaml.safe_load((root / "process/catalysts.yaml").read_text())
    assert [c["id"] for c in cats["catalysts"]] == ["FE_NH3", "RU_NH3"]


def test_a_comment_after_the_list_stays_after_it(tmp_path):
    root = _plant(tmp_path, MATERIALS.replace("templates:\n", "# templates below\ntemplates:\n"))
    add_entry(root, "ammonia")
    text = (root / "process/materials.yaml").read_text()
    assert text.index("id: NH3") < text.index("# templates below") < text.index("templates:")


def test_the_same_substance_under_another_id_is_a_conflict(tmp_path):
    root = _plant(
        tmp_path, MATERIALS.replace("id: H2, name: Hydrogen", "id: hydrogen, name: Hydrogen")
    )
    with pytest.raises(Conflict, match="CAS 1333-74-0"):
        add_entry(root, "ammonia")


def test_a_failing_file_writes_none(tmp_path):
    root = _plant(tmp_path)
    before = (root / "process/materials.yaml").read_text()
    (root / "process/reactions.yaml").write_text(
        "schema: cheme/reactions/v1\nkind: reactions\n"
        "reactions: [{id: X, stoichiometry: {H2: -1, N2: 1}}]\n"
    )
    with pytest.raises(Conflict, match="not a block list"):
        add_entry(root, "ammonia")
    assert (root / "process/materials.yaml").read_text() == before
    assert not (root / "process/catalysts.yaml").exists()


@pytest.mark.parametrize("eid", sorted(entries()))
def test_every_entry_is_classified_as_strong_as_its_data_and_no_stronger(eid):
    """The model basis is checked against the data (no stronger claim loads) and equals the
    strongest basis the data support: no entry is under- or over-classified."""
    entry = entries()[eid]
    assert entry.model_basis.kind == strongest_basis(entry)
    assert entry.model_basis.note


def test_the_classification_of_the_library():
    kinds = {eid: e.model_basis.kind for eid, e in entries().items()}
    assert {k for k, v in kinds.items() if v == "equilibrium"} == {
        "ammonia",
        "ht_shift",
        "lt_shift",
        "methanation",
        "methanol",
        "steam_reforming",
        "styrene",
        "sulfuric_acid",
    }
    # no entry carries conversions or rate laws: none is conversion_selectivity or kinetic
    assert set(kinds.values()) == {"equilibrium", "stoichiometry_only"}


@pytest.mark.parametrize(
    ("eid", "kind", "message"),
    [
        ("ethylene_oxide", "equilibrium", "EO_SYN is irreversible"),
        ("mtbe", "equilibrium", "liquid-phase"),
        ("ammonia", "kinetic", "no rate law for NH3_SYN"),
        ("ammonia", "conversion_selectivity", "no conversion for NH3_SYN"),
    ],
)
def test_a_basis_stronger_than_the_data_does_not_load(eid, kind, message):
    data = entries()[eid].model_dump(mode="json", by_alias=True)
    data["model_basis"] = {"kind": kind}
    with pytest.raises(ValueError, match=message):
        LibraryEntry.model_validate(data)


def test_the_basis_is_listed_shown_and_served():
    listed = CliRunner().invoke(app, ["chemistry", "library"]).output
    assert re.search(r"^ammonia\s+equilibrium\s+Ammonia synthesis", listed, re.M)
    assert re.search(r"^ethylene_oxide\s+stoichiometry_only\s+", listed, re.M)
    shown = CliRunner().invoke(app, ["chemistry", "library", "cumene"]).output
    assert "model basis: stoichiometry_only (no conversion, selectivity" in shown
    served = {e["id"]: e for e in library_view()["entries"]}
    assert served["methanol"]["model_basis"]["kind"] == "equilibrium"
