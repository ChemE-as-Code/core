"""Calculated stream values and the phase exported into the generated DEXPI sheets."""

import shutil
from pathlib import Path

import pytest
import yaml
from pydexpi.loaders.public import load_xml_file
from pydexpi.loaders.xml_serializer import DexpiXmlSerializer

from chemeascode.domains.process.sheets import build
from chemeascode.foundation.workspace import Workspace
from chemeascode.project.validate import validate_workspace

ASU = Path(__file__).parent / "data" / "process-asu"
SOURCE = "cheme process props: thermo 0.6.1, PR"
#: ASU-1 values (cheme process props on the ASU repository): molar mass, density, enthalpy.
VALUES = {
    "S7": (32.0326, 1.48758, -10.8572),
    "S8": (32.0326, 38.9548, 178.868),
    "S9": (28.0145, 5.88982, -39.7153),
    "S9B": (28.0145, 9.70856, 375.419),
    "S17": (28.2443, 1.31097, -8.90734),
}


def _calc(value, unit, fingerprint=None):
    q = {"value": value, "unit": unit, "provenance": "calculated", "source": SOURCE}
    return q | ({"fingerprint": fingerprint} if fingerprint else {})


@pytest.fixture
def asu(tmp_path):
    shutil.copytree(ASU, tmp_path / "asu")
    ws = Workspace(tmp_path / "asu")
    path = ws.root / "process/flowsheet.yaml"
    data = yaml.safe_load(path.read_text())
    data["units"]["enthalpy_reference"] = {"state": "ideal_gas", "temperature": 298.15}
    for stream in data["streams"]:
        if stream["id"] not in VALUES:
            continue
        mw, rho, h = VALUES[stream["id"]]
        state = stream["state"]["design"]
        state["calculated"] = {
            "molar_mass": _calc(mw, "kg/kmol"),
            "density": _calc(rho, "kg/m3"),
            "enthalpy": _calc(h, "kJ/kmol"),
        }
        state["phase"] = {
            "value": "two-phase" if stream["id"] == "S8" else "vapor",
            "vapor_fraction": 0.4 if stream["id"] == "S8" else 1.0,
            "provenance": "calculated",
            "source": SOURCE,
        }
    path.write_text(yaml.safe_dump(data, sort_keys=False))
    return ws


def _states(model):
    out = {}
    for ms in model.conceptualModel.materialStates:
        st = ms.state
        out[ms.identifier] = {
            "density": [(q.case, q.value.value, q.value.unit, q.provenance) for q in st.density],
            "h": [
                (q.case, q.value.value, q.value.unit, q.displayText) for q in st.specificEnthalpy
            ],
            "phases": [
                (p.identifier, p.description.singleLanguageStrings[0].value) for p in ms.phases
            ],
            "text": st.description.singleLanguageStrings[0].value,
        }
    return out


def _round_trip(ws, tmp_path):
    first = load_xml_file(ws.root / "process/PFD.xml")
    DexpiXmlSerializer().save(first, str(tmp_path), "rt")
    return _states(first), _states(load_xml_file(tmp_path / "rt.xml"))


def test_asu_pfd_carries_densities_molar_masses_and_phases_through_a_round_trip(asu, tmp_path):
    import pydexpi.pydexpi_classes.pydexpi_classes as C

    assert not build(asu, force=True).failed
    before, after = _round_trip(asu, tmp_path)
    assert before == after
    for sid, (mw, rho, h) in VALUES.items():
        state = after[sid]
        assert state["density"] == [
            ("design", rho, C.DensityUnit.KILOGRAMPERMETRECUBED, C.QuantityProvenance.CALCULATED)
        ]
        # DEXPI's specificEnthalpy is per mass: kJ/kmol / (kg/kmol); the display keeps kJ/kmol
        [(case, value, unit, shown)] = state["h"]
        assert value == pytest.approx(h / mw) and shown == f"{h:g} kJ/kmol"
        assert unit == C.MassSpecificEnergyUnit.KILOJOULEPERKILOGRAM
        assert f"calculated molar_mass (design) = {mw:g} kg/kmol" in state["text"]
        phases = [p for p, _ in state["phases"]]
        assert phases == (["vapor", "liquid"] if sid == "S8" else ["vapor"])
        assert "design: " in state["phases"][0][1] and SOURCE in state["phases"][0][1]
    assert "vapour fraction 0.4" in after["S8"]["phases"][0][1]
    report = validate_workspace(asu)
    # pyDEXPI's validation accepts the values and their bindings (the fixture has no P&IDs)
    errors = [f.format() for f in report.findings if f.level == "error" and "process/" in f.file]
    assert not errors


def test_stale_calculated_values_are_not_exported(asu, tmp_path):
    path = asu.root / "process/flowsheet.yaml"
    data = yaml.safe_load(path.read_text())
    s17 = next(s for s in data["streams"] if s["id"] == "S17")["state"]["design"]
    s17["calculated"]["density"]["fingerprint"] = "0" * 16  # inputs changed since the flash
    s17["phase"]["fingerprint"] = "0" * 16
    path.write_text(yaml.safe_dump(data, sort_keys=False))
    assert not build(asu, force=True).failed
    _, after = _round_trip(asu, tmp_path)
    state = after["S17"]
    assert state["density"] == [] and state["phases"] == []
    assert "stale, not exported (design): density, phase" in state["text"]
    # values that are not stale still go out
    assert state["h"] and "molar_mass" in state["text"]
    assert after["S7"]["density"]
