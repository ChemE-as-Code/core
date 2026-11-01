"""Catalyst deactivation: the activity laws, a bed and a stirred tank
solved at a time on stream (the end of run), and what they refuse."""

import math
import shutil
from pathlib import Path
from types import SimpleNamespace

import pytest
import yaml

from chemeascode.domains.chemistry.catalysts import Deactivation
from chemeascode.domains.process.model import load, rules
from chemeascode.domains.process.propagate import run

EXAMPLES = Path(__file__).resolve().parents[1] / "examples"


def test_activity_laws():
    first = Deactivation(law="first_order", kd=1e-4, provenance="assumed")
    assert first.activity(8760) == pytest.approx(math.exp(-0.876))
    second = Deactivation(law="power", kd=1e-4, order=2, provenance="assumed")
    assert second.activity(8760) == pytest.approx(1 / (1 + 0.876))
    assert Deactivation(lifetime=3, provenance="assumed").activity(1e5) == 1.0
    with pytest.raises(ValueError, match="needs kd"):
        Deactivation(law="power", provenance="assumed")
    # unset, the law leaves the dump (and the fingerprints) as before
    assert set(Deactivation(lifetime=3, provenance="given").model_dump()) == {
        "lifetime",
        "mechanisms",
        "regeneration",
        "provenance",
        "source",
    }


@pytest.fixture
def shift(tmp_path):
    root = tmp_path / "shift"
    shutil.copytree(EXAMPLES / "process-shift", root, ignore=shutil.ignore_patterns("build"))
    return root


def _set(root: Path, hours: float | None, kd: float = 2e-5) -> None:
    path = root / "process/catalysts.yaml"
    data = yaml.safe_load(path.read_text())
    data["catalysts"][0]["deactivation"] = {
        "law": "first_order",
        "kd": kd,
        "provenance": "assumed",
        "source": "vendor curve",
    }
    path.write_text(yaml.safe_dump(data, sort_keys=False))
    path = root / "process/flowsheet.yaml"
    data = yaml.safe_load(path.read_text())
    reactor = next(n for key in ("blocks", "steps") for n in data.get(key) or [] if n.get("bed"))
    reactor["bed"].pop("time_on_stream", None)
    if hours is not None:
        reactor["bed"]["time_on_stream"] = hours
    path.write_text(yaml.safe_dump(data, sort_keys=False))


def _co(root: Path) -> float:
    data = yaml.safe_load((root / "process/flowsheet.yaml").read_text())
    out = next(s for s in data["streams"] if s["id"] == "S2")["state"]["design"]
    return out["composition"]["values"]["CO"]


def _fill(root: Path):
    process, found = load(root)
    assert process is not None, [f.format() for f in found]
    return run(SimpleNamespace(root=root), process, "design", write=True)


def test_an_aged_bed_converts_less(shift):
    _set(shift, None)
    _fill(shift)
    fresh = _co(shift)
    _set(shift, 3 * 8760.0)
    _fill(shift)
    aged = _co(shift)
    assert aged > fresh  # less CO converted at the end of run
    process, _ = load(shift)
    assert not any(f.rule == "cheme.process-calculated-stale" for f in rules(process))
    _set(shift, 3 * 8760.0, kd=4e-5)  # another law: the outlet is stale
    process, _ = load(shift)
    assert any(f.rule == "cheme.process-calculated-stale" for f in rules(process))


def test_time_on_stream_needs_a_law(shift):
    path = shift / "process/flowsheet.yaml"
    data = yaml.safe_load(path.read_text())
    reactor = next(n for key in ("blocks", "steps") for n in data.get(key) or [] if n.get("bed"))
    reactor["bed"]["time_on_stream"] = 1000.0
    path.write_text(yaml.safe_dump(data, sort_keys=False))
    found = [
        f.message for f in _fill(shift).findings if f.rule == "cheme.process-propagate-reactor"
    ]
    assert any("deactivation law" in m for m in found)


def test_a_tank_with_an_aged_catalyst():
    from chemeascode.domains.chemistry.liquid import Liquid
    from chemeascode.domains.chemistry.reactions import Reactions
    from chemeascode.domains.process.schema import Tank
    from chemeascode.domains.process.stirred_tank import solve_cstr

    reactions = Reactions.model_validate(
        {
            "schema": "cheme/reactions/v1",
            "kind": "reactions",
            "reactions": [
                {
                    "id": "R1",
                    "stoichiometry": {"A": -1, "B": 1},
                    "phase": "liquid",
                    "rate": {
                        "form": "power_law",
                        "basis": "catalyst_mass",
                        "driving": "concentration",
                        "k": {"A": 0.001},
                        "orders": {"A": 1},
                        "provenance": "assumed",
                    },
                }
            ],
        }
    ).reactions
    tank = Tank(volume=1.0, catalyst_loading=2.0, provenance="assumed")
    liquid = Liquid({"A": 0.1, "B": 0.1})
    fresh = solve_cstr(reactions, {"A": 36.0}, 350.0, 101.325, tank, {}, liquid)
    half = solve_cstr(reactions, {"A": 36.0}, 350.0, 101.325, tank, {}, liquid, activity=0.5)
    k_tau = 0.001 * 2.0 * 1.0 / 0.001  # k W / Q0
    assert 1 - fresh.outlet["A"] / 36.0 == pytest.approx(k_tau / (1 + k_tau))
    assert 1 - half.outlet["A"] / 36.0 == pytest.approx(0.5 * k_tau / (1 + 0.5 * k_tau))
