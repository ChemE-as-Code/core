"""The electrochemical cell contract (``process/cells.yaml``) and its Faraday
balance (domains/process/electrochemical_cell.py), qualified against published data.

Reference data (independent of the code; see docs/framework/electrochemical-cells.md):

- dfH at 298.15 K, kJ/mol, CODATA Key Values for Thermodynamics (Cox, Wagman, Medvedev 1989):
  H2O(l) -285.830 +- 0.040, Cl-(aq) -167.080 +- 0.10, OH-(aq) -230.015 +- 0.040; and, with the
  props extra, ATcT's dfH(H2O, l) through ``chemicals`` as a second source;
- US DOE, Technical Targets for PEM Electrolysis (stack): 1.9 V -> 51 kWh/kg H2 (2022 status),
  1.8 V -> 48 (2026), 1.6 V -> 43 (ultimate), published as integers. They equal U 2F / M(H2) at
  a current efficiency of 1 (assumed in the fixture), although the table's footnote e says they
  include a 2.5 % H2 crossover loss (at 0.975 they would round to 52 / 49 / 44): the comparison
  checks the electricity per kg against the DOE's arithmetic, not the efficiency;
- HHV of hydrogen 141.88 MJ/kg (US DOE Hydrogen Analysis Resource Center, "Lower and Higher
  Heating Values of Hydrogen and Other Fuels");
- EU BREF chlor-alkali (Brinkmann et al. 2014, EUR 26844 EN, doi:10.2791/13138): the
  electrochemical unit, 1.128 t NaOH and about 28 kg H2 per t Cl2 (section 2.1); a bipolar
  membrane cell at about 3.0 V and 6.0 kA/m2 with a current efficiency above 95 %
  (4.3.2.3.2); rectifier and transformer efficiency 94-98 % (3.3.4.3.1); bipolar membrane
  cells 2 279-2 865 AC kWh/t Cl2 (Table 3.10).

Tolerances: a published integer is matched by rounding; a value derived from the CODATA data is
matched within the propagated uncertainty of those data (for U_tn: 0.04 kJ/mol / 2F = 0.0002 V,
taken as 0.0005 V); balances close to 1e-9 relative.
"""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
from pathlib import Path

import pytest
import yaml
from typer.testing import CliRunner

from chemeascode.domains.process.electrochemical_cell import (
    FARADAY,
    MODEL,
    cell_bases,
    cell_report,
)
from chemeascode.interfaces.cli import app

DATA = Path(__file__).resolve().parent / "data" / "electrochemical"
runner = CliRunner()

M_H2 = 2 * 1.008  # kg/kmol, the formula's (domains/chemistry/formulas.py)
M_CL2 = 2 * 35.45
HHV_H2 = 141.88e3  # kJ/kg, DOE Hydrogen Analysis Resource Center


def _plant(tmp_path: Path, name: str) -> Path:
    root = tmp_path / name
    shutil.copytree(DATA / name, root)
    return root


def _edit(root: Path, path: str, edit) -> None:
    file = root / path
    data = yaml.safe_load(file.read_text(encoding="utf-8"))
    edit(data)
    file.write_text(yaml.safe_dump(data, sort_keys=False, allow_unicode=True), encoding="utf-8")


def _cell(root: Path, edit) -> None:
    _edit(root, "process/cells.yaml", lambda d: edit(d["cells"][0]))


def _only(root: Path):
    report = cell_report(root)
    assert len(report.cells) == 1
    return report, report.cells[0]


def _line(root: Path, text: str) -> int:
    lines = (root / "process" / "cells.yaml").read_text(encoding="utf-8").splitlines()
    return next(i for i, line in enumerate(lines, start=1) if text in line)


def _rules(report, level: str | None = None) -> set[str]:
    return {f.rule for f in report.findings if level is None or f.level == level}


def _closes(cell) -> None:
    """Charge, elements and energy close; the heat is power minus reaction enthalpy."""
    assert cell.charge["residual_a"] == pytest.approx(
        0.0, abs=1e-9 * cell.charge["stack_current_a"]
    )
    assert all(abs(v) < 1e-12 for v in cell.elements_residual_kmol_h.values())
    assert cell.energy_residual_kw == pytest.approx(0.0, abs=1e-12)
    assert cell.heat_duty_kw == pytest.approx(cell.power_kw - cell.reaction_enthalpy_kw)


# -- water electrolysis -------------------------------------------------------------------------


def test_water_electrolysis_reference(tmp_path):
    root = _plant(tmp_path, "water-electrolysis")
    report, cell = _only(root)
    assert not cell.refused and not _rules(report, "error") and not _rules(report, "warning")
    # thermoneutral voltage: 285.830 kJ/mol / 2F; the tabulated 1.481 V
    assert cell.thermoneutral_voltage_v == pytest.approx(285830 / (2 * FARADAY), rel=1e-12)
    assert cell.thermoneutral_voltage_v == pytest.approx(1.481, abs=5e-4)
    # Faraday: 20 kA, 2 electrons, FE 1 -> I / 2F mol/s of H2
    h2_kmol_h = 20000 / (2 * FARADAY) * 3.6
    assert cell.formed_kmol_h["H2"] == pytest.approx(h2_kmol_h, rel=1e-12)
    assert cell.formed_kmol_h["O2"] == pytest.approx(h2_kmol_h / 2, rel=1e-12)
    assert cell.formed_kmol_h["H2O"] == pytest.approx(-h2_kmol_h, rel=1e-12)
    assert cell.products["H2"]["home"] == "cathode" and cell.products["O2"]["home"] == "anode"
    assert cell.current_density_a_m2 == pytest.approx(20000)  # 2.0 A/cm2
    _closes(cell)
    # electricity counted once: 38 kW = 20 kA x 1.9 V; per kg H2 it is P alone, never P + Q
    assert cell.power_kw == pytest.approx(38.0)
    specific = cell.electricity_kwh_per_kg["H2"]["formed"]
    assert specific == pytest.approx(cell.power_kw / (h2_kmol_h * M_H2), rel=1e-12)
    assert round(specific) == 51  # DOE 2022 status: 1.9 V -> 51 kWh/kg
    assert cell.voltage_efficiency["reversible"] == pytest.approx(1.229 / 1.9)


@pytest.mark.parametrize(("volts", "published"), [(1.9, 51), (1.8, 48), (1.6, 43)])
def test_water_electrolysis_against_doe_targets(tmp_path, volts, published):
    """The DOE stack targets' kWh/kg at their cell voltages (published as integers)."""
    root = _plant(tmp_path, "water-electrolysis")
    _cell(root, lambda c: c["voltage"].update(value=volts))
    _, cell = _only(root)
    specific = cell.electricity_kwh_per_kg["H2"]["formed"]
    assert round(specific) == published
    # the footnote's 2.5 % crossover loss is not in the published figures: with it, one more
    assert round(specific / 0.975) == published + 1


def test_at_the_thermoneutral_voltage_no_heat_and_the_hhv(tmp_path):
    root = _plant(tmp_path, "water-electrolysis")
    _cell(root, lambda c: c["voltage"].update(value=285830 / (2 * FARADAY)))
    _, cell = _only(root)
    assert cell.heat_duty_kw == pytest.approx(0.0, abs=1e-9)
    # kWh/kg at U_tn is the enthalpy of water splitting per kg H2: the HHV (DOE: 141.88 MJ/kg);
    # 0.2 %: the HHV is on ATcT/NIST data and M(H2) 2.01588, this on CODATA and 2.016
    assert cell.electricity_kwh_per_kg["H2"]["formed"] * 3600 == pytest.approx(HHV_H2, rel=2e-3)
    _, below = _only(_lower_voltage(tmp_path, 1.40))
    assert below.heat_duty_kw < 0  # below U_tn the cell takes heat


def _lower_voltage(tmp_path: Path, volts: float) -> Path:
    root = _plant(tmp_path / "below", "water-electrolysis")
    _cell(root, lambda c: c["voltage"].update(value=volts))
    return root


def test_faradaic_loss_crossover_and_purge(tmp_path):
    """FE 0.975 (the DOE footnote's 2.5 % crossover loss, which its published kWh/kg do not
    reflect, see the module docstring): the extents fall by 2.5 %, the
    lost current becomes heat; 1 % of the hydrogen crosses to the anode and 0.5 % is purged:
    the outlets divide what is formed, the electricity per kg delivered rises accordingly."""
    root = _plant(tmp_path, "water-electrolysis")

    def edit(c):
        c["faradaic_efficiency"]["value"] = 0.975
        c["crossover"] = {"H2": 0.01}
        c["purge"] = {"H2": 0.005}

    _cell(root, edit)
    report, cell = _only(root)
    assert not _rules(report, "error")
    ideal = 20000 / (2 * FARADAY) * 3.6
    assert cell.formed_kmol_h["H2"] == pytest.approx(0.975 * ideal)
    assert cell.unassigned_current_fraction == pytest.approx(0.025)
    assert cell.charge["unassigned_a"] == pytest.approx(500.0)
    _closes(cell)
    h2 = cell.products["H2"]
    assert h2["crossover_kg_h"] == pytest.approx(0.01 * h2["formed_kg_h"])
    assert h2["outlet_kg_h"] == pytest.approx(0.985 * h2["formed_kg_h"])
    specific = cell.electricity_kwh_per_kg["H2"]
    assert specific["formed"] == pytest.approx(38.0 / (0.975 * ideal * M_H2))
    assert specific["delivered"] == pytest.approx(specific["formed"] / 0.985)
    # Q = N I (U - FE U_tn)
    assert cell.heat_duty_kw == pytest.approx(
        20.0 * (1.9 - 0.975 * cell.thermoneutral_voltage_v), rel=1e-12
    )


def test_thermoneutral_voltage_from_atct_through_chemicals(tmp_path):
    """A second, independent source of dfH(H2O, l): ATcT through ``chemicals`` (props extra)."""
    reaction = pytest.importorskip("chemicals.reaction")
    atct = reaction.Hfl("7732-18-5", method="ATCT_L")  # J/mol
    _, cell = _only(_plant(tmp_path, "water-electrolysis"))
    assert cell.thermoneutral_voltage_v == pytest.approx(-atct / (2 * FARADAY), abs=5e-4)


# -- chlor-alkali -------------------------------------------------------------------------------


def test_chlor_alkali_reference(tmp_path):
    root = _plant(tmp_path, "chlor-alkali")
    report, cell = _only(root)
    assert not cell.refused and not _rules(report, "error") and not _rules(report, "warning")
    # U_tn from the CODATA ion enthalpies: 445.790 kJ/mol / 2F
    dh = 2 * -230.015 - 2 * -167.080 - 2 * -285.830
    assert cell.heat_duty_kw is not None
    assert cell.thermoneutral_voltage_v == pytest.approx(dh * 1000 / (2 * FARADAY), abs=5e-4)
    assert cell.thermoneutral_voltage_v == pytest.approx(2.310, abs=1e-3)
    # the half-reactions add up to the overall reaction through the dissociated salts
    homes = {name: row["home"] for name, row in cell.products.items()}
    assert homes == {"Cl2": "anode", "H2": "cathode", "NaOH": "cathode"}
    # Faraday: 6 kA x 0.95 / 2F
    cl2 = 6000 * 0.95 / (2 * FARADAY) * 3.6
    assert cell.formed_kmol_h["Cl2"] == pytest.approx(cl2, rel=1e-12)
    _closes(cell)
    kg = cell.formed_kg_h
    # the BREF's electrochemical unit: 1.128 t NaOH and about 28 kg H2 per t Cl2
    assert kg["NaOH"] / kg["Cl2"] == pytest.approx(1.128, abs=5e-4)
    assert round(1000 * kg["H2"] / kg["Cl2"]) == 28
    # electricity per t Cl2 (DC at the cell): 3.0 V x 2F / (0.95 M_Cl2)
    dc = cell.electricity_kwh_per_kg["Cl2"]["formed"] * 1000
    assert dc == pytest.approx(3.0 * 2 * FARADAY / (0.95 * M_CL2) / 3600 * 1000, rel=1e-12)
    # as AC through rectifiers of 94-98 %, inside the BREF's bipolar membrane range
    for efficiency in (0.94, 0.98):
        assert 2279 <= dc / efficiency <= 2865
    # heat to remove: N I (U - FE U_tn), about 4.8 kW per m2 at 6 kA/m2
    assert cell.heat_duty_kw == pytest.approx(6.0 * (3.0 - 0.95 * cell.thermoneutral_voltage_v))
    # 90 °C against dH at 298.15 K: said, not hidden
    assert "cheme.cell-temperature" in _rules(report, "info")
    assert any("363.15 K" in text for text in cell.limitations)


def test_chlor_alkali_side_reaction_takes_current(tmp_path):
    """Oxygen evolution at the anode (2 H2O -> O2 + 4 H+ + 4 e-, written with the cell's water and
    the cathode's hydroxide: 2 H2O -> O2 + 2 H2 overall) takes 2 % of the current."""
    root = _plant(tmp_path, "chlor-alkali")
    _edit(
        root,
        "process/materials.yaml",
        lambda d: d["components"].append({"id": "O2", "name": "Oxygen", "formula": "O2"}),
    )
    _edit(
        root,
        "process/reactions.yaml",
        lambda d: d["reactions"].append(
            {
                "id": "WS",
                "stoichiometry": {"H2O": -2, "O2": 1, "H2": 2},
                "heat_of_reaction": {"value": 571660, "provenance": "given", "source": "CODATA"},
            }
        ),
    )

    def edit(c):
        c["side_reactions"] = [
            {
                "reaction": "WS",
                "electrons": 4,
                "current_fraction": {"value": 2, "unit": "%", "provenance": "assumed"},
            }
        ]

    _cell(root, edit)
    report, cell = _only(root)
    assert not _rules(report, "error")
    assert cell.extents["WS"] == pytest.approx(0.02 * 6000 / (4 * FARADAY) * 3.6)
    assert cell.unassigned_current_fraction == pytest.approx(0.03)
    _closes(cell)
    assert "cheme.cell-unsourced" in _rules(report, "info")
    assert cell_bases(report) == {}  # no flowsheet link: no basis


# -- refusals and failures ----------------------------------------------------------------------


@pytest.mark.parametrize("missing", ["faradaic_efficiency", "voltage", "current", "thermal"])
def test_missing_inputs_are_refused(tmp_path, missing):
    root = _plant(tmp_path, "water-electrolysis")
    _cell(root, lambda c: c.pop(missing))
    report, cell = _only(root)
    assert cell.refused and cell.power_kw is None and not cell.formed_kmol_h
    found = [f for f in report.findings if f.rule == "cheme.cell-input-missing"]
    assert found and found[0].level == "error" and found[0].line == _line(root, "- id: PEM-1")
    assert found[0].file == "process/cells.yaml" and found[0].hint


def test_missing_heat_of_reaction_is_refused(tmp_path):
    root = _plant(tmp_path, "water-electrolysis")
    _edit(root, "process/reactions.yaml", lambda d: d["reactions"][0].pop("heat_of_reaction"))
    report, cell = _only(root)
    assert cell.refused
    assert any("heat_of_reaction" in f.message for f in report.findings if f.level == "error")


@pytest.mark.parametrize(
    ("edit", "rule"),
    [
        (lambda c: c.update(performance="predictive"), "cheme.cell-unsupported"),
        (lambda c: c["thermal"].update(kind="adiabatic"), "cheme.cell-unsupported"),
        (lambda c: c.update(reaction="NOPE"), "cheme.cell-reaction"),
        (lambda c: c["faradaic_efficiency"].update(value=1.2), "cheme.cell-charge"),
    ],
)
def test_unsupported_and_inconsistent_cells_are_refused(tmp_path, edit, rule):
    root = _plant(tmp_path, "water-electrolysis")
    _cell(root, edit)
    report, cell = _only(root)
    assert cell.refused and rule in _rules(report, "error")


def test_current_fractions_above_one(tmp_path):
    root = _plant(tmp_path, "water-electrolysis")

    def edit(c):
        c["side_reactions"] = [
            {
                "reaction": "WS",
                "electrons": 2,
                "current_fraction": {"value": 0.1, "provenance": "assumed"},
            }
        ]
        c["faradaic_efficiency"]["value"] = 0.95

    _cell(root, edit)
    report, cell = _only(root)
    assert cell.refused and "cheme.cell-charge" in _rules(report, "error")


@pytest.mark.parametrize(
    ("edit", "rule"),
    [
        (lambda c: c.update(electrons=4), "cheme.cell-electrodes"),
        (
            lambda c: c["electrodes"]["cathode"]["species"].update({"H+": -1}),
            "cheme.cell-charge-balance",
        ),
        (lambda c: c["electrodes"]["anode"]["species"].update({"e-": -2}), "cheme.cell-electrodes"),
        (
            lambda c: c["electrodes"]["anode"]["species"].update({"O2": 1}),
            "cheme.cell-element-balance",
        ),
        (lambda c: c.update(crossover={"H2O": 0.1}), "cheme.cell-crossover"),
    ],
)
def test_electrode_and_split_errors(tmp_path, edit, rule):
    root = _plant(tmp_path, "water-electrolysis")
    _cell(root, edit)
    report, cell = _only(root)
    assert rule in _rules(report, "error"), [f.format() for f in report.findings]
    if rule != "cheme.cell-crossover":  # a wrong electron count gives no numbers
        assert cell.refused and cell.power_kw is None


def test_chlor_alkali_without_dissociation_does_not_add_up(tmp_path):
    root = _plant(tmp_path, "chlor-alkali")
    _cell(root, lambda c: c.pop("dissociation"))
    report, _ = _only(root)
    found = [f for f in report.findings if f.rule == "cheme.cell-electrodes"]
    assert found and "do not add up" in found[0].message


def test_operating_range_and_voltage_warnings(tmp_path):
    root = _plant(tmp_path, "water-electrolysis")

    def edit(c):
        c["current"]["value"] = 40  # 4 A/cm2: outside 0.5-3.0 A/cm2
        c["voltage"]["value"] = 1.2  # below the reversible 1.229 V

    _cell(root, edit)
    report, _ = _only(root)
    assert {"cheme.cell-operating-range", "cheme.cell-voltage"} <= _rules(report, "warning")
    _cell(root, lambda c: c.pop("operating_range"))
    report, cell = _only(root)
    assert "cheme.cell-operating-range" in _rules(report, "info")
    assert any("operating range" in text for text in cell.limitations)


def test_schema_errors_name_the_line(tmp_path):
    root = _plant(tmp_path, "water-electrolysis")
    _cell(root, lambda c: c.update(colour="red"))
    report = cell_report(root)
    assert not report.cells
    assert [(f.rule, f.line) for f in report.findings] == [
        ("cheme.cell-schema", _line(root, "colour:"))
    ]


# -- flowsheet link: electricity and heat counted once ------------------------------------------

FLOWSHEET = {
    "schema": "cheme/process/v1",
    "kind": "flowsheet",
    "feeds": [
        {"id": "WATER", "ports": [{"id": "out", "direction": "out"}]},
        {"id": "GRID", "ports": [{"id": "q", "direction": "out", "kind": "energy"}]},
    ],
    "products": [
        {"id": "HYD", "ports": [{"id": "in", "direction": "in"}]},
        {"id": "OXY", "ports": [{"id": "in", "direction": "in"}]},
        {"id": "CW", "ports": [{"id": "q", "direction": "in", "kind": "energy"}]},
    ],
    "blocks": [
        {
            "id": "ELY",
            "reactions": ["WS"],
            "ports": [
                {"id": "water", "direction": "in"},
                {"id": "power", "direction": "in", "kind": "energy"},
                {"id": "h2", "direction": "out"},
                {"id": "o2", "direction": "out"},
                {"id": "heat", "direction": "out", "kind": "energy"},
            ],
        }
    ],
    "streams": [
        {"id": "S1", "from": "WATER.out", "to": "ELY.water"},
        {"id": "S2", "from": "ELY.h2", "to": "HYD.in"},
        {"id": "S3", "from": "ELY.o2", "to": "OXY.in"},
        {
            "id": "E1",
            "kind": "energy",
            "from": "GRID.q",
            "to": "ELY.power",
            "state": {"design": {"duty": {"value": 38.0, "provenance": "calculated"}}},
        },
        {
            "id": "Q1",
            "kind": "energy",
            "from": "ELY.heat",
            "to": "CW.q",
            "state": {"design": {"duty": {"value": 8.3758, "provenance": "calculated"}}},
        },
    ],
}


def _linked(tmp_path: Path, **link) -> Path:
    root = _plant(tmp_path, "water-electrolysis")
    (root / "process" / "flowsheet.yaml").write_text(yaml.safe_dump(FLOWSHEET), encoding="utf-8")
    _cell(root, lambda c: c.update(flowsheet={"step": "ELY", **link}))
    return root


def test_linked_streams_carry_power_and_heat_once(tmp_path):
    root = _linked(tmp_path, electricity="E1", heat="Q1")
    report, cell = _only(root)
    assert not [f.format() for f in report.findings if f.rule.startswith("cheme.cell-flow")]
    assert not _rules(report, "warning") and not _rules(report, "error")
    basis = cell_bases(report)["ELY"]
    # the fixture's current efficiency of 1 is assumed: specified, but not sourced
    assert (basis.basis, basis.predictive, basis.sourced) == ("electrochemical-cell", False, False)
    assert "assumed or without a source" in basis.detail
    assert basis.file == "process/cells.yaml"
    _source_efficiency(root)
    basis = cell_bases(cell_report(root))["ELY"]
    assert (basis.basis, basis.predictive, basis.sourced) == ("electrochemical-cell", False, True)


def _source_efficiency(root: Path) -> None:
    _cell(
        root,
        lambda c: c["faradaic_efficiency"].update(provenance="given", source="test: measured"),
    )


def test_two_cells_at_one_step(tmp_path):
    """A step two cells are linked to is sourced only when both are, and the link is said."""
    root = _linked(tmp_path, electricity="E1", heat="Q1")
    _source_efficiency(root)

    def second(d):
        d["cells"].append({**d["cells"][0], "id": "PEM-2"})
        d["cells"][1]["faradaic_efficiency"] = {"value": 1.0, "provenance": "assumed"}

    _edit(root, "process/cells.yaml", second)
    report = cell_report(root)
    assert any(
        f.rule == "cheme.cell-flowsheet" and "PEM-1" in f.message and "PEM-2" in f.message
        for f in report.findings
        if f.level == "warning"
    )
    assert cell_bases(report)["ELY"].sourced is False


def test_linked_duty_mismatch_and_double_counting(tmp_path):
    root = _linked(tmp_path, electricity="E1")  # Q1 at the step but not named
    report, _ = _only(root)
    assert "cheme.cell-double-count" in _rules(report, "warning")
    _cell(root, lambda c: c["flowsheet"].update(heat="E1"))
    report, _ = _only(root)
    assert "cheme.cell-double-count" in _rules(report, "error")

    def heat_as_power(d):  # the heat stream carries P + Q: electricity counted twice
        d["streams"][4]["state"]["design"]["duty"]["value"] = 38.0 + 8.3758

    root = _linked(tmp_path / "again", electricity="E1", heat="Q1")
    _edit(root, "process/flowsheet.yaml", heat_as_power)
    report, _ = _only(root)
    assert "cheme.cell-flowsheet-duty" in _rules(report, "warning")


def test_link_to_an_unknown_step(tmp_path):
    root = _linked(tmp_path)
    _cell(root, lambda c: c["flowsheet"].update(step="NOPE"))
    report, _ = _only(root)
    assert "cheme.cell-flowsheet" in _rules(report, "error")


def test_maturity_reports_the_cell_as_specified(tmp_path):
    from chemeascode.project.maturity import maturity_report

    root = _linked(tmp_path, electricity="E1", heat="Q1")
    _source_efficiency(root)
    report = maturity_report(root, through="predictive")
    units = {u["id"]: u for u in report.model_basis}
    assert units["ELY"]["basis"] == "electrochemical-cell"
    assert units["ELY"]["predictive"] is False and units["ELY"]["sourced"] is True


# -- the command and the function ---------------------------------------------------------------


def test_cli_json_is_the_report(tmp_path, monkeypatch):
    root = _plant(tmp_path, "chlor-alkali")
    monkeypatch.chdir(root)
    result = runner.invoke(app, ["process", "cell", "--json"])
    assert result.exit_code == 0, result.output
    payload = json.loads(result.stdout)
    assert payload == json.loads(cell_report(root).to_json())
    assert payload["model"] == MODEL and payload["qualified"]
    assert set(payload["source"]["fingerprints"]) >= {"process/cells.yaml"}
    monkeypatch.chdir(tmp_path)
    assert cell_report(root).cells[0].power_kw == pytest.approx(18.0)  # from elsewhere


def test_cli_exit_codes(tmp_path, monkeypatch):
    root = _plant(tmp_path, "water-electrolysis")
    _cell(root, lambda c: c.pop("voltage"))
    monkeypatch.chdir(root)
    result = runner.invoke(app, ["process", "cell"])
    assert result.exit_code == 1 and "refused" in result.stdout
    (root / "process" / "cells.yaml").unlink()
    assert runner.invoke(app, ["process", "cell"]).exit_code == 2


def test_validate_reports_cell_findings(tmp_path):
    from chemeascode.foundation.workspace import Workspace
    from chemeascode.project.validate import validate_workspace

    root = _plant(tmp_path, "water-electrolysis")
    _cell(root, lambda c: c.pop("faradaic_efficiency"))
    report = validate_workspace(Workspace(root))
    assert "process/cells.yaml" in report.files
    assert "cheme.cell-input-missing" in {f.rule for f in report.findings}


def test_import_needs_neither_typer_nor_fastapi():
    code = (
        "import sys; import chemeascode.domains.process.electrochemical_cell; "
        "assert 'typer' not in sys.modules and 'fastapi' not in sys.modules"
    )
    subprocess.run([sys.executable, "-c", code], check=True, env={**os.environ})


# -- measured performance and the membrane (co2-bpm: a synthetic measured series) --------------

SERIES = "experiments/electrochemistry/synthetic-bpm.yaml"


def _measured_point(root: Path, j: float):
    from chemeascode.domains.experiments.electrochemistry import (
        MeasuredPerformance,
        measurement_report,
    )

    return MeasuredPerformance(measurement_report(root, SERIES)).at(j)


def test_measured_cell_takes_voltage_and_efficiencies_from_the_measurement(tmp_path):
    """0.75 A on 5 cm2 = 1500 A/m2, halfway between the points at 1000 and 2000 A/m2: the
    voltage and Faradaic efficiencies are their means' midpoints, H2's efficiency becomes the
    current fraction of the side reaction WS, and the rest of the current is unassigned."""
    root = _plant(tmp_path, "co2-bpm")
    report, cell = _only(root)
    assert not cell.refused, cell.reasons
    assert not _rules(report, "error") and not _rules(report, "warning")
    at = _measured_point(root, 1500.0)
    assert at.bracket == ("P100", "P200")
    assert cell.current_density_a_m2 == pytest.approx(1500.0)
    assert cell.voltage_v == pytest.approx(at.voltage_v)
    fe_co, fe_h2 = at.faradaic_efficiency["CO"], at.faradaic_efficiency["H2"]
    assert cell.faradaic_efficiency == pytest.approx(fe_co)
    assert cell.extents["CO2R"] == pytest.approx(fe_co * 0.75 / (2 * FARADAY) * 3.6)
    assert cell.extents["WS"] == pytest.approx(fe_h2 * 0.75 / (2 * FARADAY) * 3.6)
    assert cell.unassigned_current_fraction == pytest.approx(1 - fe_co - fe_h2)
    _closes(cell)
    # U_tn of CO2 -> CO + 1/2 O2 from CODATA dfH(CO2, g) and dfH(CO, g)
    assert cell.thermoneutral_voltage_v == pytest.approx((393.51 - 110.53) * 1000 / (2 * FARADAY))
    assert cell.performance == "measured" and cell.sourced
    assert cell.measurement["file"] == SERIES and cell.measurement["bracket"] == ["P100", "P200"]
    assert any(SERIES in s for s in cell.sources)
    assert set(report.source.fingerprints) >= {"process/cells.yaml", SERIES}


def test_membrane_reports_wde_apart_from_the_faradaic_efficiency(tmp_path):
    root = _plant(tmp_path, "co2-bpm")
    _, cell = _only(root)
    at = _measured_point(root, 1500.0)
    membrane = cell.membrane
    wde = at.water_dissociation_efficiency
    assert membrane["water_dissociation_efficiency"] == pytest.approx(wde)
    assert membrane["basis"] == "measured" and membrane["kind"] == "bipolar"
    # what the membrane does not carry by water dissociation, the co-ions carry
    deficit = (1 - wde) * 0.75 / FARADAY
    assert membrane["hydroxide_deficit_mol_s"] == pytest.approx(deficit)
    assert membrane["hydroxide_deficit_kmol_h"] == pytest.approx(deficit * 3.6)
    assert membrane["co_ion_flux_mol_s"]["K+"] == pytest.approx(0.34 * deficit)
    assert membrane["co_ion_flux_mol_s"]["HCO3-"] == pytest.approx(0.66 * deficit)
    assert membrane["measured_co_ion_carbon_fraction"] == pytest.approx(at.co_ion_carbon_fraction)
    # the membrane changes nothing in the Faraday balance
    _cell(root, lambda c: c.pop("membrane"))
    _, without = _only(root)
    assert without.membrane is None
    assert without.extents == cell.extents and without.heat_duty_kw == cell.heat_duty_kw
    assert "membrane" not in without.as_dict()


@pytest.mark.parametrize(
    ("edit", "rule"),
    [
        (lambda c: c["current"].update(value=1.5), "cheme.cell-operating-range"),  # 3000 A/m2
        (lambda c: c["current"].update(value=0.2), "cheme.cell-operating-range"),  # 400 A/m2
        (lambda c: c["thermal"]["temperature"].update(value=60), "cheme.cell-operating-range"),
        (lambda c: c.pop("active_area"), "cheme.cell-input-missing"),
        (lambda c: c.pop("measurements"), "cheme.cell-input-missing"),
        (lambda c: c.update(performance="specified"), "cheme.cell-measurement"),
        (
            lambda c: c["measurements"].update(file="experiments/nope.yaml"),
            "cheme.cell-measurement",
        ),
        (lambda c: c["measurements"].update(product="HCOOH"), "cheme.cell-measurement"),
    ],
)
def test_measured_cell_refusals(tmp_path, edit, rule):
    root = _plant(tmp_path, "co2-bpm")
    _cell(root, edit)
    report, cell = _only(root)
    assert cell.refused and rule in _rules(report, "error"), [f.format() for f in report.findings]
    assert cell.power_kw is None and not cell.extents


def test_measured_cell_is_never_extrapolated(tmp_path):
    root = _plant(tmp_path, "co2-bpm")
    _cell(root, lambda c: c["current"].update(value=1.5))
    report, cell = _only(root)
    found = next(f for f in report.findings if f.rule == "cheme.cell-operating-range")
    assert "never extrapolated" in found.message and "500-2000 A/m2" in found.hint
    # the line of the current's entry (its mapping starts on the line below the key)
    assert found.line in (_line(root, "current:"), _line(root, "current:") + 1)


def test_measurement_with_errors_refuses_the_cell(tmp_path):
    root = _plant(tmp_path, "co2-bpm")
    _edit(root, SERIES, lambda d: d["points"][0].update(current={"value": 1, "unit": "A"}))
    report, cell = _only(root)
    assert cell.refused and "cheme.cell-measurement" in _rules(report, "error")
    assert any("cheme experiments electrochem" in f.hint for f in report.findings)


def test_measured_conflicts(tmp_path):
    root = _plant(tmp_path, "co2-bpm")
    at = _measured_point(root, 1500.0)
    _cell(root, lambda c: c.update(voltage={"value": 3.0, "unit": "V", "provenance": "given"}))
    report, cell = _only(root)
    assert "cheme.cell-measured-conflict" in _rules(report, "warning")
    assert cell.voltage_v == pytest.approx(at.voltage_v)  # the measured value is used
    # within the replicates' standard deviation: no conflict
    near = at.voltage_v + 0.5 * at.voltage_sd_v
    _cell(root, lambda c: c["voltage"].update(value=near))
    report, _ = _only(root)
    assert "cheme.cell-measured-conflict" not in _rules(report)
    _cell(
        root,
        lambda c: c["membrane"].update(
            water_dissociation_efficiency={"value": 0.5, "provenance": "assumed"}
        ),
    )
    report, _ = _only(root)
    assert "cheme.cell-measured-conflict" in _rules(report, "warning")


def test_side_product_without_a_side_reaction_is_unassigned_current(tmp_path):
    root = _plant(tmp_path, "co2-bpm")
    _cell(root, lambda c: c.pop("side_reactions"))
    report, cell = _only(root)
    assert not cell.refused and "cheme.cell-measurement" in _rules(report, "info")
    assert cell.unassigned_current_fraction == pytest.approx(1 - cell.faradaic_efficiency)
    assert any("unassigned" in text for text in cell.limitations)


def test_unsourced_measurement_is_specified_but_not_sourced(tmp_path):
    root = _plant(tmp_path, "co2-bpm")
    _edit(root, SERIES, lambda d: d.update(source=""))
    _, cell = _only(root)
    assert not cell.refused and not cell.sourced


def test_measured_cell_basis(tmp_path):
    root = _plant(tmp_path, "co2-bpm")
    sheet = json.loads(json.dumps(FLOWSHEET))
    sheet["blocks"][0]["reactions"] = ["CO2R"]
    for stream in sheet["streams"]:
        stream.pop("state", None)
    (root / "process" / "flowsheet.yaml").write_text(yaml.safe_dump(sheet), encoding="utf-8")
    _cell(root, lambda c: c.update(flowsheet={"step": "ELY", "electricity": "E1", "heat": "Q1"}))
    basis = cell_bases(cell_report(root))["ELY"]
    assert (basis.basis, basis.predictive, basis.sourced) == ("electrochemical-cell", False, True)
    assert basis.detail.startswith("measured electrochemical cell BPM-1")
    assert "interpolated between measured points" in basis.limitations[0]


def test_membrane_on_a_specified_cell(tmp_path):
    root = _plant(tmp_path, "water-electrolysis")
    _, before = _only(root)
    _cell(root, lambda c: c.update(membrane={"kind": "cation_exchange"}))
    report, cell = _only(root)
    assert "cheme.cell-membrane" in _rules(report, "info")  # no WDE: no fluxes
    assert cell.membrane["hydroxide_deficit_mol_s"] is None
    assert cell.extents == before.extents and cell.power_kw == before.power_kw

    def given(c):
        c["membrane"] = {
            "kind": "bipolar",
            "water_dissociation_efficiency": {"value": 90, "unit": "%", "provenance": "assumed"},
            "co_ion_crossover": {"K+": 1.0},
        }

    _cell(root, given)
    _, cell = _only(root)
    assert cell.membrane["basis"] == "given"
    assert cell.membrane["co_ion_flux_mol_s"]["K+"] == pytest.approx(0.1 * 20000 / FARADAY)
    _cell(root, lambda c: c["membrane"].update(co_ion_crossover={"K+": 0.5, "CO3-2": 0.4}))
    report, _ = _only(root)
    assert "cheme.cell-membrane" in _rules(report, "error")
    _cell(root, lambda c: c["membrane"].update(co_ion_crossover={"K+": 0.5, "CO3-2": 0.5}))
    _, cell = _only(root)
    # a doubly charged co-ion carries twice the charge per mol
    flux = cell.membrane["co_ion_flux_mol_s"]
    assert flux["CO3-2"] == pytest.approx(flux["K+"] / 2)


def test_specified_cells_report_as_before(tmp_path):
    """The fields for measured cells and membranes stay out of a specified cell's result."""
    for name in ("water-electrolysis", "chlor-alkali"):
        _, cell = _only(_plant(tmp_path, name))
        assert not {"performance", "measurement", "membrane"} & set(cell.as_dict())


SNAPSHOTS = DATA / "snapshots"


def _masked(payload: dict) -> dict:
    """The JSON report without what changes between releases and checkouts: the core version,
    the commit and the files' fingerprints (their names stay)."""
    payload["core_version"] = "<version>"
    source = payload["source"]
    source["commit"] = "<commit>"
    source["dirty"] = []
    source["fingerprints"] = dict.fromkeys(source["fingerprints"], "<sha256>")
    return payload


@pytest.mark.parametrize("name", ["water-electrolysis", "chlor-alkali"])
def test_specified_cells_output_is_unchanged(tmp_path, monkeypatch, name):
    """`cheme process cell` text and JSON of the specified fixtures against stored snapshots
    (taken on main before measured cells existed; core version, commit and fingerprints masked).
    Regenerate on an intended change with CHEME_UPDATE_SNAPSHOTS=1 and review the diff."""
    root = _plant(tmp_path, name)
    monkeypatch.chdir(root)
    text = runner.invoke(app, ["process", "cell"])
    assert text.exit_code == 0, text.output
    first, rest = text.stdout.split("\n", 1)
    assert first.startswith("model faraday-balance v1 (cheme/electrochemical-cells/v1), core ")
    shown = first.rsplit(" core ", 1)[0] + " core <version>\n" + rest
    payload = json.loads(runner.invoke(app, ["process", "cell", "--json"]).stdout)
    shown_json = json.dumps(_masked(payload), indent=2) + "\n"
    if os.environ.get("CHEME_UPDATE_SNAPSHOTS"):
        SNAPSHOTS.mkdir(exist_ok=True)
        (SNAPSHOTS / f"{name}.txt").write_text(shown, encoding="utf-8")
        (SNAPSHOTS / f"{name}.json").write_text(shown_json, encoding="utf-8")
    assert shown == (SNAPSHOTS / f"{name}.txt").read_text(encoding="utf-8")
    assert shown_json == (SNAPSHOTS / f"{name}.json").read_text(encoding="utf-8")


def _messages(report, rule: str, level: str = "error") -> list[str]:
    return [f.message for f in report.findings if f.rule == rule and f.level == level]


def test_measured_product_must_be_formed_by_the_cells_reaction(tmp_path):
    """H2 is formed by WS in the measurement: its Faradaic efficiency is no current efficiency
    of CO2R."""
    root = _plant(tmp_path, "co2-bpm")
    _cell(
        root,
        lambda c: (
            c["measurements"].update(product="H2", side_products=[]),
            c.pop("side_reactions"),
        ),
    )
    report, cell = _only(root)
    assert cell.refused and cell.power_kw is None
    (message,) = _messages(report, "cheme.cell-measurement")
    assert "forms H2 by reaction WS, not by the cell's reaction CO2R" in message
    # without reaction: in the measurement, the product must be one of the reaction's
    _edit(root, SERIES, lambda d: [p.pop("reaction") for p in d["products"]])
    report, cell = _only(root)
    assert cell.refused
    assert _messages(report, "cheme.cell-measurement") == [
        "cell BPM-1: H2 is no product of the cell's reaction CO2R: refused"
    ]
    _cell(root, lambda c: c["measurements"].update(product="CO"))
    report, cell = _only(root)
    assert not cell.refused, cell.reasons


def test_side_product_at_the_other_electrode_is_refused(tmp_path):
    root = _plant(tmp_path, "co2-bpm")
    _edit(
        root,
        SERIES,
        lambda d: (
            d["products"][1].update(electrode="anode"),
            d["products"][1].pop("thermoneutral_voltage"),
        ),
    )
    report, cell = _only(root)
    assert cell.refused
    (message,) = _messages(report, "cheme.cell-measurement")
    assert "side product H2 forms at the other electrode than CO (cathode)" in message


def test_measured_efficiencies_above_1_within_tolerance_are_scaled(tmp_path):
    """FE sums of 1.012 and 1.018 pass the measurement's own check (below 1.05): the cell
    scales the measured shares to add up to 1 instead of refusing with cell-charge."""
    root = _plant(tmp_path, "co2-bpm")

    def raise_h2(d):
        for point, values in (("P100", (4.55, 4.72)), ("P200", (13.6, 12.2))):
            p = next(p for p in d["points"] if p["id"] == point)
            for rep, x in zip(p["replicates"], values, strict=True):
                rep["fractions"]["H2"]["value"] = x

    _edit(root, SERIES, raise_h2)
    from chemeascode.domains.experiments.electrochemistry import measurement_report

    assert not measurement_report(root, SERIES).errors
    at = _measured_point(root, 1500.0)
    total = at.faradaic_efficiency["CO"] + at.faradaic_efficiency["H2"]
    assert total > 1
    report, cell = _only(root)
    assert not cell.refused, cell.reasons
    assert "cheme.cell-charge" not in _rules(report)
    assert any(
        "scaled to add up to 1" in m for m in _messages(report, "cheme.cell-measurement", "info")
    )
    assert cell.faradaic_efficiency == pytest.approx(at.faradaic_efficiency["CO"] / total)
    assert cell.extents["WS"] == pytest.approx(
        at.faradaic_efficiency["H2"] / total * 0.75 / (2 * FARADAY) * 3.6
    )
    assert cell.unassigned_current_fraction == pytest.approx(0.0, abs=1e-12)
    assert cell.measurement["normalised_from"] == pytest.approx(total)
    _closes(cell)
    # a stated side fraction on top of the measured ones is still refused, naming the file
    _edit(
        root,
        "process/reactions.yaml",
        lambda d: d["reactions"].append(
            {**next(r for r in d["reactions"] if r["id"] == "WS"), "id": "WS2"}
        ),
    )
    _cell(
        root,
        lambda c: c["side_reactions"].append(
            {
                "reaction": "WS2",
                "electrons": 2,
                "current_fraction": {"value": 0.1, "provenance": "assumed"},
            }
        ),
    )
    report, cell = _only(root)
    found = next(f for f in report.findings if f.rule == "cheme.cell-charge")
    assert cell.refused and SERIES in found.hint


def test_measured_side_product_below_detection_forms_nothing(tmp_path):
    root = _plant(tmp_path, "co2-bpm")

    def no_h2(d):
        for p in d["points"]:
            for rep in p["replicates"]:
                rep["fractions"]["H2"] = {"value": 0, "unit": "mol%"}

    _edit(root, SERIES, no_h2)
    report, cell = _only(root)
    assert not cell.refused, cell.reasons
    assert "cheme.cell-charge" not in _rules(report)
    assert cell.extents["WS"] == 0.0
    _closes(cell)


def test_refused_measured_cell_has_no_membrane_info(tmp_path):
    """The measurement holds the titrations: a refused lookup does not ask for them."""
    root = _plant(tmp_path, "co2-bpm")
    for edit in (
        lambda c: c["current"].update(value=1.5),
        lambda c: c["measurements"].update(file="experiments/nope.yaml"),
    ):
        _cell(root, edit)
        report, cell = _only(root)
        assert cell.refused
        assert "cheme.cell-membrane" not in _rules(report)


def test_measured_cell_refuses_electrode_potentials(tmp_path):
    root = _plant(tmp_path, "co2-bpm")
    _edit(root, SERIES, lambda d: d.update(voltage_basis="electrode_vs_reference"))
    report, cell = _only(root)
    assert cell.refused
    (message,) = _messages(report, "cheme.cell-input-missing")
    assert "electrode potentials against a reference, not a cell voltage" in message


def test_measured_ir_corrected_voltage_is_a_limitation(tmp_path):
    root = _plant(tmp_path, "co2-bpm")
    _edit(root, SERIES, lambda d: d.update(voltage_basis="cell_ir_corrected"))
    _, cell = _only(root)
    assert not cell.refused and cell.measurement["voltage_basis"] == "cell_ir_corrected"
    assert any("iR-corrected" in text for text in cell.limitations)


@pytest.mark.parametrize(
    ("membrane", "text"),
    [
        (
            {
                "kind": "bipolar",
                "water_dissociation_efficiency": {"value": 0.9, "provenance": "assumed"},
                "co_ion_crossover": {"Kx": 1.0},
            },
            "co-ion Kx is no ion",
        ),
        (
            {
                "kind": "bipolar",
                "water_dissociation_efficiency": {"value": 1.2, "provenance": "assumed"},
            },
            "water dissociation efficiency 1.2 not in [0, 1]",
        ),
    ],
)
def test_membrane_errors(tmp_path, membrane, text):
    root = _plant(tmp_path, "water-electrolysis")
    _cell(root, lambda c: c.update(membrane=membrane))
    report, _ = _only(root)
    assert any(text in m for m in _messages(report, "cheme.cell-membrane"))


def test_side_reaction_without_fraction_on_a_specified_cell(tmp_path):
    root = _plant(tmp_path, "water-electrolysis")
    _cell(root, lambda c: c.update(side_reactions=[{"reaction": "WS", "electrons": 2}]))
    report, cell = _only(root)
    assert cell.refused and "cheme.cell-input-missing" in _rules(report, "error")


def test_cli_measured_cell(tmp_path, monkeypatch):
    root = _plant(tmp_path, "co2-bpm")
    monkeypatch.chdir(root)
    result = runner.invoke(app, ["process", "cell"])
    assert result.exit_code == 0, result.output
    assert f"measured: {SERIES} at 1500 A/m2 (between P100 and P200)" in result.stdout
    assert "membrane (bipolar, reverse bias): water dissociation efficiency" in result.stdout
    payload = json.loads(runner.invoke(app, ["process", "cell", "--json"]).stdout)
    assert payload == json.loads(cell_report(root).to_json())
