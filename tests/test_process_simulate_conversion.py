"""Conversion reactors: the conversion DWSIM reached against the declared one.

DWSIM converts a reaction's key component in the inlet's reaction phase only; a liquid-phase
reactor whose inlet the package splits falls short of the declared conversion without a message
(the MTBE fixture, tests/test_process_simulate_energy_liquid.py: SRK converts 0.8146 with a
0.176 "vapour" inlet). These tests replay DWSIM results without DWSIM; the live check of the
shortfall is in the MTBE fixture's DWSIM-gated tests.
"""

from __future__ import annotations

import copy
import json

import pytest

from chemeascode.domains.process.model import load as load_process
from chemeascode.domains.process.simulation import conversion
from chemeascode.domains.process.simulation.run import run
from tests.test_process_simulate_energy_liquid import RECORDED, _plant

ETH = {
    "id": "ETH",
    "type": "conversion",
    "stoichiometry": {"IB": -1, "MEOH": -1, "MTBE": 1},
    "phase": "liquid",
    "base": "IB",
    "conversion": 1.0,
}


def _reactor(reactions, inlets=("S4",), outlets=("S6", "S5")) -> dict:
    return {
        "units": [
            {
                "id": "R1",
                "type": "conversion_reactor",
                "inlets": list(inlets),
                "outlets": list(outlets),
                "spec": {"reactions": reactions},
            }
        ]
    }


def _stream(flows: dict[str, float], vapor_fraction=None) -> dict:
    """A solved stream from kmol/h by component."""
    total = sum(flows.values())
    return {
        "molar_flow_mol_s": total / 3.6,
        "mole_fractions": {n: v / total if total else 0.0 for n, v in flows.items()},
        "vapor_fraction": vapor_fraction,
    }


def _short(converted: float, vapor_fraction: float = 0.176) -> dict:
    """RECORDED with the reactor converting *converted* of the isobutene (the SRK case)."""
    out = copy.deepcopy(RECORDED)
    s4 = out["streams"]["S4"]
    fed = {n: x * s4["molar_flow_mol_s"] * 3.6 for n, x in s4["mole_fractions"].items()}
    xi = converted * fed["IB"]
    liquid = {"IB": fed["IB"] - xi, "MEOH": fed["MEOH"] - xi, "MTBE": xi}
    s4["vapor_fraction"] = vapor_fraction
    for sid, flows in (("S5", liquid), ("S6", dict.fromkeys(liquid, 0.0))):
        out["streams"][sid] |= _stream(flows)
    return out


def test_one_liquid_inlet_reaches_the_declared_conversion():
    """The recorded Peng-Robinson run (one-liquid inlet): complete conversion, the extent all
    the isobutene fed (27.7776 mol/s = 99.9994 kmol/h), no finding."""
    reached = conversion.achieved(_reactor([ETH]), RECORDED)
    info = reached["R1"]
    key = info["keys"]["IB"]
    assert key["declared"] == 1.0 and key["achieved"] == pytest.approx(1.0, abs=1e-8)
    assert key["reactions"] == ["ETH"] and key["phases"] == ["liquid"]
    assert info["extents_kmol_h"]["ETH"] == pytest.approx(27.777619 * 3.6, rel=1e-6)
    assert info["conversions"]["ETH"] == pytest.approx(1.0, abs=1e-8)
    assert info["inlet"] == "S4" and info["inlet_vapor_fraction"] is None
    assert conversion.findings(reached, None) == []


def test_a_split_inlet_short_of_the_declared_conversion_is_an_error(tmp_path):
    ws = _plant(tmp_path)
    from chemeascode.domains.process.simulation.translate import load

    _, doc, _ = load(ws.root)
    reached = conversion.achieved(_reactor([ETH]), _short(0.8146))
    assert reached["R1"]["conversions"]["ETH"] == pytest.approx(0.8146, rel=1e-9)
    [finding] = conversion.findings(reached, doc)
    assert finding.rule == conversion.RULE and finding.level == "error"
    assert finding.file == "process/simulation.yaml" and finding.ids == ["R1"]
    lines = (ws.root / "process/simulation.yaml").read_text().splitlines()
    assert lines[finding.line - 2].strip() == "R1:"  # the first line of its specs
    assert "converted 0.8146 of IB (reaction ETH), 1 declared" in finding.message
    assert "inlet S4 is 0.176 vapour" in finding.message
    assert "one phase" in finding.hint and "phase: mixed" in finding.hint


def test_the_tolerance_separates_noise_from_a_phase_split():
    """PR78's 0.15 % shortfall is reported, a 0.05 % one is not."""
    assert conversion.findings(conversion.achieved(_reactor([ETH]), _short(0.9985, 0.0015)), None)
    assert not conversion.findings(conversion.achieved(_reactor([ETH]), _short(0.9995)), None)


def test_parallel_conversions_of_one_key_add_up():
    """Two reactions on N2's inlet flow (DWSIM's one rank, as propagate): 0.25 + 0.5 of it.
    The same stoichiometry twice: the extents are not identifiable, the key's conversion is."""
    syn = {
        "id": "SYN",
        "type": "conversion",
        "stoichiometry": {"N2": -1, "H2": -3, "NH3": 2},
        "phase": "vapor",
        "base": "N2",
        "conversion": 0.25,
    }
    model = _reactor([syn, syn | {"id": "SYN2", "conversion": 0.5}], ("S1",), ("S2",))
    fed = {"N2": 247.5, "H2": 742.5, "NH3": 0.0, "AR": 10.0}

    def outlet(x: float) -> dict:
        xi = x * fed["N2"]
        flows = {"N2": fed["N2"] - xi, "H2": fed["H2"] - 3 * xi, "NH3": 2 * xi, "AR": 10.0}
        return {"streams": {"S1": _stream(fed, 1.0), "S2": _stream(flows, 1.0)}}

    reached = conversion.achieved(model, outlet(0.75))
    key = reached["R1"]["keys"]["N2"]
    assert key["declared"] == pytest.approx(0.75) and key["achieved"] == pytest.approx(0.75)
    assert key["reactions"] == ["SYN", "SYN2"]
    assert "extents_kmol_h" not in reached["R1"]
    assert conversion.findings(reached, None) == []
    [finding] = conversion.findings(conversion.achieved(model, outlet(0.6)), None)
    assert "reaction SYN, SYN2" in finding.message and "0.75 declared" in finding.message
    assert "inlet S1 is 1 vapour" in finding.message  # the inlet's state, also one-phase
    # a one-phase inlet: no split to blame, the hint names the phase and the feasibility
    assert "is in that phase" in finding.hint and "co-reactant" in finding.hint


def test_independent_reactions_get_their_extents_and_conversions():
    """A -> B (0.3 of A) and A -> C (0.2 of A) in parallel: the key A converts 0.5."""
    a_b = {
        "id": "R-B",
        "type": "conversion",
        "stoichiometry": {"A": -1, "B": 1},
        "phase": "mixed",
        "base": "A",
        "conversion": 0.3,
    }
    a_c = a_b | {"id": "R-C", "stoichiometry": {"A": -1, "C": 1}, "conversion": 0.2}
    out = {
        "streams": {
            "S1": _stream({"A": 100.0, "B": 0.0, "C": 0.0}),
            "S2": _stream({"A": 50.0, "B": 30.0, "C": 20.0}),
        }
    }
    reached = conversion.achieved(_reactor([a_b, a_c], ("S1",), ("S2",)), out)
    info = reached["R1"]
    assert info["keys"]["A"]["declared"] == pytest.approx(0.5)
    assert info["extents_kmol_h"] == pytest.approx({"R-B": 30.0, "R-C": 20.0})
    assert info["conversions"] == pytest.approx({"R-B": 0.3, "R-C": 0.2})
    assert conversion.findings(reached, None) == []
    out["streams"]["S2"] = _stream({"A": 60.0, "B": 30.0, "C": 10.0})
    [finding] = conversion.findings(
        conversion.achieved(_reactor([a_b, a_c], ("S1",), ("S2",)), out), None
    )
    assert "feasible together" in finding.hint  # phase mixed: the whole inlet is converted


def test_reactors_that_cannot_be_compared_are_left_out():
    model = _reactor([ETH])
    assert conversion.achieved(model, RECORDED, skip={"R1"}) == {}
    gone = copy.deepcopy(RECORDED)
    del gone["streams"]["S6"]
    assert conversion.achieved(model, gone) == {}
    absent = _short(0.5)  # no isobutene fed: its conversion is not defined
    absent["streams"]["S4"]["mole_fractions"] = {"IB": 0.0, "MEOH": 1.0, "MTBE": 0.0}
    assert conversion.achieved(model, absent)["R1"]["keys"] == {}
    equilibrium = _reactor([ETH | {"type": "equilibrium"}])
    assert conversion.achieved(equilibrium, RECORDED) == {}


def _simulate(ws, out):
    process, _ = load_process(ws.root)
    result = run(ws, process, "design", write=True, solver=lambda model, save: out)
    entry = json.loads((ws.root / "process/simulation-run.json").read_text())["cases"]["design"]
    return result, entry


def test_simulate_reports_the_extents_and_records_the_shortfall(tmp_path):
    """Through cheme process simulate: the summary and the record show R1's extents and
    conversion; the shortfall is an error in the findings and the record (which fails
    predictive.converged: a run with errors)."""
    ws = _plant(tmp_path)
    result, entry = _simulate(ws, RECORDED)
    assert not [f for f in result.findings if f.rule == conversion.RULE]
    row = next(u for u in entry["units"] if u["id"] == "R1")
    assert row["results"]["extents_kmol_h"]["ETH"] == pytest.approx(99.9994, abs=1e-3)
    assert row["results"]["conversions"]["ETH"] == pytest.approx(1.0, abs=1e-8)
    assert any(line.startswith("R1:") and "conversions ETH 1" in line for line in result.lines)

    result, entry = _simulate(_plant(tmp_path / "srk"), _short(0.8146))
    [finding] = [f for f in result.findings if f.rule == conversion.RULE]
    assert finding.level == "error"
    recorded = [f for f in entry["findings"] if f["rule"] == conversion.RULE]
    assert recorded and recorded[0]["level"] == "error"
    row = next(u for u in entry["units"] if u["id"] == "R1")
    assert row["results"]["conversions"]["ETH"] == pytest.approx(0.8146, rel=1e-9)
    assert finding.message in row["warnings"]
