"""``cheme chemistry props`` (a thin wrapper of domains/chemistry/properties.py) and the
safety domain's OSHA hazard data. No network: the CLI test asks only thermo."""

from __future__ import annotations

import json

import pytest
from typer.testing import CliRunner

from chemeascode.domains.safety.hazard_data import from_osha_record
from chemeascode.interfaces.cli import app

runner = CliRunner()


def test_props_offline_through_thermo_names_the_source():
    pytest.importorskip("thermo")
    result = runner.invoke(
        app, ["chemistry", "props", "water", "-p", "temperature_boil", "--source", "Thermo"]
    )
    assert result.exit_code == 0, result.output
    assert result.output.startswith("temperature_boil: 373.") and "K [Thermo]" in result.output


def test_props_json_and_not_found_exit_1():
    pytest.importorskip("thermo")
    result = runner.invoke(
        app,
        ["chemistry", "props", "water", "-p", "viscosity", "-p", "idlh", "--source", "Thermo"]
        + ["--temperature", "25", "--temperature-unit", "°C", "--json"],
    )
    assert result.exit_code == 1
    found = json.loads(result.output)
    assert found[0]["source"] == "Thermo" and found[0]["value"] == pytest.approx(0.89, abs=0.05)
    assert found[1]["value"] is None and "not found" in found[1]["error"]


@pytest.mark.parametrize(
    "args",
    [["-p", "colour"], ["-p", "viscosity", "--source", "Nowhere"]],
)
def test_props_refuses_unknown_names(args):
    result = runner.invoke(app, ["chemistry", "props", "water", *args])
    assert result.exit_code == 2


def test_hazard_data_converts_to_si_and_keeps_the_source():
    record = {
        "name": "acetone",
        "cas": "67-64-1",
        "flash_point": {"value": -4.0, "units": "°F"},
        "lower_explosive_limit": {"value": 2.5, "units": "%"},
        "upper_explosive_limit": {"value": 12.8, "units": "ppm"},
        "nfpa_fire_rating": 3.0,
        "osha_twa": {"value": 1000.0, "units": "ppm"},
        "source_url": "https://www.osha.gov/chemicaldata/476",
    }
    found = from_osha_record("67-64-1", record)
    assert found.flash_point_K == pytest.approx(253.15)
    assert found.lower_explosive_limit_vol_pct == 2.5
    assert found.upper_explosive_limit_vol_pct is None and "UEL" in found.notes[0]
    assert found.exposure_limits == {"osha_twa": {"value": 1000.0, "units": "ppm"}}
    assert found.source_url.endswith("/476")


def test_hazard_data_flash_point_range_takes_the_lower_end():
    record = {"flash_point": {"value": 100.0, "units": "°F", "range": [100.0, 162.0]}}
    found = from_osha_record("1-11-1", record)
    assert found.flash_point_K == pytest.approx(310.928, abs=1e-3)
    assert found.flash_point_range_K[1] == pytest.approx(345.372, abs=1e-3)
