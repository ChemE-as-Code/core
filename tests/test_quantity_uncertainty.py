"""Optional ``uncertainty`` on process quantities (pre-release issue 112): the LCA's model, shared.

A quantity or composition of ``process/flowsheet.yaml`` (and a spec of
``process/simulation.yaml``) may give an ``uncertainty`` of the shape ``lca.yaml`` uses. It
enters no fingerprint, and ``cheme assess lca`` samples a feed's or product's flow with it
instead of the study's default for the flow's provenance.
"""

import json
import shutil
from pathlib import Path

import pytest
import yaml
from pydantic import ValidationError

from chemeascode.domains.assessment.lca import schemas as lca_schemas
from chemeascode.domains.assessment.lca.report import lca_report
from chemeascode.domains.equipment.fill import stream_fingerprint
from chemeascode.domains.process import propagate, props
from chemeascode.domains.process.model import load
from chemeascode.domains.process.schema import CompositionValue, Quantity
from chemeascode.domains.process.simulation import translate
from chemeascode.foundation.uncertainty import Uncertainty

EXAMPLES = Path(__file__).parents[1] / "examples"


# -- the field ----------------------------------------------------------------------------------


def test_one_model_for_lca_and_process() -> None:
    assert lca_schemas.Uncertainty is Uncertainty


@pytest.mark.parametrize(
    "spec",
    [
        {"gsd2": 1.2},
        {"distribution": "lognormal", "pedigree": [1, 2, 1, 3, 2]},
        {"distribution": "triangular", "low": 0.9, "high": 1.1},
        {"distribution": "uniform", "low": 0.95, "high": 1.05, "source": "vendor"},
        {"distribution": "normal", "cv": 0.05},
    ],
)
def test_a_quantity_takes_an_uncertainty(spec: dict) -> None:
    q = Quantity.model_validate({"value": 2.0, "provenance": "assumed", "uncertainty": spec})
    assert q.uncertainty == Uncertainty(**spec)
    c = CompositionValue.model_validate(
        {"basis": "mole_fraction", "values": {"N2": 1}, "provenance": "given", "uncertainty": spec}
    )
    assert c.uncertainty == Uncertainty(**spec)


@pytest.mark.parametrize(
    ("spec", "match"),
    [
        ({}, "gsd2 or pedigree"),
        ({"distribution": "triangular", "low": 0.9}, "low <= 1 <= high"),
        ({"distribution": "triangular", "low": 1.1, "high": 1.2}, "low <= 1 <= high"),
        ({"gsd2": 0.5}, "greater than or equal to 1"),
        ({"gsd2": 1.2, "spread": 2}, "Extra inputs"),
    ],
)
def test_a_wrong_uncertainty_is_refused(spec: dict, match: str) -> None:
    with pytest.raises(ValidationError, match=match):
        Quantity.model_validate({"value": 2.0, "provenance": "assumed", "uncertainty": spec})


def test_the_schema_documents_it(monkeypatch) -> None:
    from typer.testing import CliRunner

    from chemeascode.interfaces.cli import app

    shown = CliRunner().invoke(app, ["schema", "process-flowsheet"])
    assert shown.exit_code == 0
    schema = json.loads(shown.output)
    field = schema["$defs"]["Quantity"]["properties"]["uncertainty"]
    assert field["default"] is None and "cheme assess lca" in field["description"]
    assert "uncertainty" in schema["$defs"]["CompositionValue"]["properties"]
    assert "triangular" in json.dumps(schema["$defs"]["Uncertainty"])
    # the simulation specs reuse the quantity
    shown = CliRunner().invoke(app, ["schema", "process-simulation"])
    assert "uncertainty" in json.loads(shown.output)["$defs"]["Quantity"]["properties"]


# -- fingerprints -------------------------------------------------------------------------------


def _with_uncertainty(node, spec: dict) -> None:
    """Give every quantity and composition below *node* (parsed YAML) the uncertainty *spec*."""
    if isinstance(node, dict):
        quantity = "value" in node and not isinstance(node["value"], str)  # not a phase
        if "provenance" in node and (quantity or "values" in node):
            node["uncertainty"] = spec
        for value in node.values():
            _with_uncertainty(value, spec)
    elif isinstance(node, list):
        for value in node:
            _with_uncertainty(value, spec)


def _fingerprints(root: Path) -> dict:
    """Every fingerprint the flowsheet's values feed: props, propagate, the equipment fill and
    the simulator model, in every case."""
    process, found = load(root)
    assert process is not None, found
    found = {}
    for case in (c.id for c in process.flowsheet.cases):
        for s in process.flowsheet.streams:
            found[f"{case}/{s.id}/props"] = props.fingerprint(process, s, case)
            found[f"{case}/{s.id}/stale"] = props.stale(process, s, case)
        derived = propagate.derive(process, case).values
        found[f"{case}/propagate"] = sorted((str(k), v.fingerprint) for k, v in derived.items())
        for node in process.nodes.values():
            for link in (lk for lk in node.links if lk.target == "equipment"):
                found[f"{case}/{link.ref}"] = stream_fingerprint(process, link.ref, case)
        sim, doc, _ = translate.load(root)
        if sim is not None:
            found[f"{case}/model"] = translate.translate(process, sim, doc, case).fingerprint
    return found


@pytest.mark.parametrize(
    "example", ["process-ammonia", "process-recycle", "process-shift", "process-simulation"]
)
def test_no_fingerprint_sees_it(tmp_path: Path, example: str) -> None:
    root = tmp_path / example
    shutil.copytree(EXAMPLES / example, root)
    before = _fingerprints(root)
    # the recorded fingerprints (props, propagate) are still current: none sees the unset field
    assert not [k for k, v in before.items() if k.endswith("/stale") and v]
    assert any(isinstance(v, str) for v in before.values())
    for name in ("flowsheet.yaml", "simulation.yaml"):
        path = root / "process" / name
        if path.is_file():
            data = yaml.safe_load(path.read_text())
            _with_uncertainty(data, {"distribution": "triangular", "low": 0.9, "high": 1.1})
            path.write_text(yaml.safe_dump(data, sort_keys=False))
    assert "uncertainty" in (root / "process" / "flowsheet.yaml").read_text()
    assert _fingerprints(root) == before


@pytest.mark.parametrize("example", ["process-blocks", "process-ammonia", "process-simulation"])
def test_the_sheets_keep_their_source_fingerprint(example: str) -> None:
    """The sheets' recorded ``source_sha256`` (the same as before the field existed) matches:
    an unchanged flowsheet is not reported outdated."""
    from chemeascode.foundation.workspace import Workspace
    from chemeascode.project.validate import validate_workspace

    found = validate_workspace(Workspace(EXAMPLES / example)).findings
    assert not [f.format() for f in found if f.rule.startswith("cheme.generated")]


# -- the LCA ------------------------------------------------------------------------------------


def _factor(id_: str, unit: str, gwp: float) -> dict:
    return {
        "id": id_,
        "unit": unit,
        "values": {"gwp": gwp},
        "status": "ASSUMED",
        "source": "test",
        "year": 2025,
    }


@pytest.fixture
def blocks(tmp_path: Path) -> Path:
    """examples/process-blocks with an LCA (see test_lca_uncertainty.py): per t of product,
    2500 kg of feed (S1, given; 1250 kg CO2-eq) and 875 kWh of steam (Q1, assumed; 220.5)."""
    root = tmp_path / "blocks"
    shutil.copytree(EXAMPLES / "process-blocks", root)
    (root / "lca").mkdir()
    factors = {
        "schema": "cheme/lca/v1",
        "kind": "lca_factors",
        "categories": [{"id": "gwp", "unit": "kg CO2-eq"}],
        "factors": [_factor("feed", "kg", 0.5), _factor("steam", "MJ", 0.07)],
    }
    (root / "lca" / "factors.yaml").write_text(yaml.safe_dump(factors, sort_keys=False))
    path = root / "process" / "flowsheet.yaml"
    text = path.read_text()
    for old, new in (
        (
            "flow: {value: 1000, basis: mass, provenance: given, source: basis of design}",
            "flow: {value: 1000, basis: mass, provenance: given, source: basis of design, "
            "uncertainty: {gsd2: 1.2, source: flow meter}}",
        ),
        (
            "duty: {value: 350, provenance: assumed}",
            "duty: {value: 350, provenance: assumed, "
            "uncertainty: {distribution: triangular, low: 0.9, high: 1.1}}",
        ),
    ):
        assert text.count(old) == 1
        text = text.replace(old, new)
    path.write_text(text)
    return root


def _study(root: Path, feed: dict | None = None) -> None:
    scope = {
        "schema": "cheme/lca/v1",
        "kind": "lca",
        "functional_unit": {"product": "PROD", "amount": 1, "unit": "t"},
        "allocation": {"method": "none"},
        "flows": [
            {"key": "feed:FEED", "factor": "feed", "source": "test", **(feed or {})},
            {"key": "feed:STEAM", "factor": "steam", "source": "test"},
            {"key": "product:WATER", "free": True, "source": "test"},
        ],
        "uncertainty": {
            "iterations": 2000,
            "seed": 7,
            "defaults": {"given": {"gsd2": 3.0}, "assumed": {"gsd2": 3.0}},
        },
    }
    (root / "lca" / "lca.yaml").write_text(yaml.safe_dump(scope, sort_keys=False))


def test_the_flowsheet_uncertainty_overrides_the_default(blocks: Path) -> None:
    _study(blocks)
    report = lca_report(blocks)
    assert report.loaded, [f.format() for f in report.findings]
    exchanges = {e.key: e for e in report.inventory.dataset.exchanges}
    assert exchanges["feed:FEED"].uncertainty == Uncertainty(gsd2=1.2, source="flow meter")
    assert exchanges["feed:STEAM"].uncertainty == Uncertainty(
        distribution="triangular", low=0.9, high=1.1
    )
    # the rest is unchanged: no uncertainty of its own, the study's default applies
    assert exchanges["product:WATER"].uncertainty is None
    assert exchanges["product:PROD"].uncertainty is None
    stats = report.uncertainty.statistics[0]
    assert stats.deterministic == pytest.approx(1470.5)
    # gsd2 1.2 on the feed (not the default 3.0), the steam within 0.9 .. 1.1
    assert stats.low == pytest.approx(220.5 + 1250 / 1.2, rel=0.03)
    assert stats.high == pytest.approx(220.5 + 1250 * 1.2, rel=0.03)


def test_the_study_entry_wins_over_the_flowsheet(blocks: Path) -> None:
    _study(blocks, feed={"uncertainty": {"gsd2": 1.1}})
    exchanges = {e.key: e for e in lca_report(blocks).inventory.dataset.exchanges}
    assert exchanges["feed:FEED"].uncertainty == Uncertainty(gsd2=1.1)
    assert exchanges["feed:STEAM"].uncertainty.distribution == "triangular"


def test_streams_that_disagree_give_none() -> None:
    """A terminal summed from streams with different uncertainties takes the default."""
    from chemeascode.domains.assessment.flows import Terminal

    one, other = Uncertainty(gsd2=1.2), Uncertainty(gsd2=1.5)
    assert Terminal("k", "t", "input", uncertainties=[one, one]).uncertainty == one
    assert Terminal("k", "t", "input", uncertainties=[one, other]).uncertainty is None
    assert Terminal("k", "t", "input", uncertainties=[one, None]).uncertainty is None
    assert Terminal("k", "t", "input").uncertainty is None
