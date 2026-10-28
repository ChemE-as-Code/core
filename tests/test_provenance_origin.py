"""Optional ``origin`` refining the provenance class (pre-release issue 111).

A process quantity or composition (and a spec of ``process/simulation.yaml``), a datasheet
quantity and an LCA exchange may say what kind of figure the value is: given ``measured``,
``vendor`` or ``literature``; assumed ``design-rule``, ``estimate`` or ``literature``;
calculated ``simulated`` or ``correlation``. The class stays what the tools read. A pairing
outside these is ``cheme.provenance-origin``; no fingerprint sees the field; simulate, props
and the datasheet fill write it on their values; the datasheet draft and the DEXPI sheets carry
it; the LCA's ``uncertainty.defaults`` may be keyed by it.
"""

import shutil
from pathlib import Path
from typing import get_args

import pytest
import yaml
from pydantic import ValidationError

from chemeascode.domains.assessment.lca.report import lca_report
from chemeascode.domains.assessment.lca.schemas import StudyUncertainty
from chemeascode.domains.equipment.datasheets import draft_datasheet
from chemeascode.domains.equipment.schemas.datasheet import Datasheet
from chemeascode.domains.equipment.schemas.datasheet import Quantity as DatasheetQuantity
from chemeascode.domains.equipment.schemas.equipment import EquipmentItem
from chemeascode.domains.process.model import load as load_process
from chemeascode.domains.process.schema import CompositionValue, Quantity
from chemeascode.domains.process.simulation.run import run
from chemeascode.foundation.schema_base import ORIGIN_CLASSES, Origin
from chemeascode.foundation.uncertainty import Uncertainty
from chemeascode.foundation.workspace import Workspace
from chemeascode.project.validate import validate_workspace
from tests.test_process_simulate import AIR, _state, fake, plant  # noqa: F401 - the fixture
from tests.test_quantity_uncertainty import _fingerprints, _study, blocks  # noqa: F401

EXAMPLES = Path(__file__).parents[1] / "examples"
#: An origin that fits each class.
FITTING = {"given": "measured", "assumed": "estimate", "calculated": "simulated"}


# -- the field ----------------------------------------------------------------------------------


def test_every_origin_refines_a_class() -> None:
    assert set(ORIGIN_CLASSES) == set(get_args(Origin))
    assert {c for classes in ORIGIN_CLASSES.values() for c in classes} == {
        "given",
        "assumed",
        "calculated",
    }


@pytest.mark.parametrize("origin", get_args(Origin))
def test_a_value_takes_an_origin(origin: str) -> None:
    q = Quantity.model_validate({"value": 2.0, "provenance": "given", "origin": origin})
    assert q.origin == origin
    c = CompositionValue.model_validate(
        {"basis": "mole_fraction", "values": {"N2": 1}, "provenance": "given", "origin": origin}
    )
    assert c.origin == origin
    assert DatasheetQuantity.model_validate({"value": 2.0, "origin": origin}).origin == origin


def test_an_unknown_origin_is_refused() -> None:
    with pytest.raises(ValidationError, match="measured"):
        Quantity.model_validate({"value": 2.0, "provenance": "given", "origin": "guess"})


def test_unset_it_is_not_written() -> None:
    q = Quantity(value=2.0, provenance="given")
    assert q.origin is None and "origin" not in q.model_dump(exclude_none=True)


# -- the check ----------------------------------------------------------------------------------


def _origin_findings(root: Path) -> list:
    found = validate_workspace(Workspace(root)).findings
    return [f for f in found if f.rule == "cheme.provenance-origin"]


def test_an_origin_that_does_not_fit_warns(tmp_path: Path) -> None:
    root = tmp_path / "blocks"
    shutil.copytree(EXAMPLES / "process-blocks", root)
    path = root / "process" / "flowsheet.yaml"
    text = path.read_text()
    old = "flow: {value: 1000, basis: mass, provenance: given, source: basis of design}"
    assert text.count(old) == 1
    path.write_text(text.replace(old, old[:-1] + ", origin: measured}"))
    assert not _origin_findings(root)
    path.write_text(text.replace(old, old[:-1] + ", origin: simulated}"))
    found = _origin_findings(root)
    assert len(found) == 1 and found[0].level == "warning"
    assert found[0].file == "process/flowsheet.yaml" and found[0].ids == ["S1"]
    assert found[0].message == (
        "streams.0.state.design.flow: origin simulated does not refine provenance given"
    )
    assert found[0].line == text[: text.index(old)].count("\n") + 1
    assert "calculated" in found[0].hint


def test_a_simulation_spec_is_checked(tmp_path: Path) -> None:
    root = tmp_path / "sim"
    shutil.copytree(EXAMPLES / "process-simulation", root)
    path = root / "process" / "simulation.yaml"
    text = path.read_text()
    old = "efficiency: {value: 0.78, provenance: assumed,"
    assert text.count(old) == 1
    path.write_text(text.replace(old, old + " origin: vendor,"))
    found = _origin_findings(root)
    assert [(f.file, f.message) for f in found] == [
        (
            "process/simulation.yaml",
            "specs.K1.efficiency: origin vendor does not refine provenance assumed",
        )
    ]
    path.write_text(text.replace(old, old + " origin: design-rule,"))
    assert not _origin_findings(root)


# -- fingerprints -------------------------------------------------------------------------------


def _with_origin(node) -> None:
    """Give every quantity and composition below *node* (parsed YAML) an origin that fits."""
    if isinstance(node, dict):
        quantity = "value" in node and not isinstance(node["value"], str)  # not a phase
        if node.get("provenance") in FITTING and (quantity or "values" in node):
            node["origin"] = FITTING[node["provenance"]]
        for value in node.values():
            _with_origin(value)
    elif isinstance(node, list):
        for value in node:
            _with_origin(value)


@pytest.mark.parametrize(
    "example", ["process-ammonia", "process-recycle", "process-shift", "process-simulation"]
)
def test_no_fingerprint_sees_it(tmp_path: Path, example: str) -> None:
    root = tmp_path / example
    shutil.copytree(EXAMPLES / example, root)
    before = _fingerprints(root)
    for name in ("flowsheet.yaml", "simulation.yaml"):
        path = root / "process" / name
        if path.is_file():
            data = yaml.safe_load(path.read_text())
            _with_origin(data)
            path.write_text(yaml.safe_dump(data, sort_keys=False))
    assert "origin: measured" in (root / "process" / "flowsheet.yaml").read_text()
    assert _fingerprints(root) == before
    assert not _origin_findings(root)


# -- producers ----------------------------------------------------------------------------------


def test_simulate_writes_simulated(plant):  # noqa: F811 - the fixture
    process, _ = load_process(plant.root)
    assert run(plant, process, "design", write=True, solver=fake).written == 5
    s2 = _state(plant, "S2")
    assert {s2[k]["origin"] for k in ("temperature", "pressure", "flow", "composition")} == {
        "simulated"
    }
    assert s2["composition"]["values"] == AIR
    assert _state(plant, "W1")["duty"]["origin"] == "simulated"
    # a value simulate does not own is never touched
    assert "origin" not in _state(plant, "S1")["flow"]
    assert not _origin_findings(plant.root)
    # the origin is no input: the filled values are current
    process, _ = load_process(plant.root)
    check = run(plant, process, "design", write=False, solver=fake)
    assert not [f for f in check.findings if f.level != "info" or "not-filled" in f.rule]


# -- mappings -----------------------------------------------------------------------------------


def test_the_datasheet_draft_carries_it() -> None:
    item = EquipmentItem.model_validate(
        {"tag": "P4711", "type": "CentrifugalPump", "service": "Feed pump"}
    )
    measured = Quantity(value=25.0, provenance="given", origin="measured", source="TI-101")
    estimate = Quantity(value=6.0, provenance="assumed", origin="estimate", source="D-4")
    streams = [
        {
            "id": "S1",
            "direction": "in",
            "state": {"temperature": measured.model_dump(mode="json", exclude_none=True)},
        },
        {
            "id": "S2",
            "direction": "out",
            "state": {"pressure": estimate.model_dump(mode="json", exclude_none=True)},
        },
        {"id": "S3", "direction": "out", "state": {}},
    ]
    text = draft_datasheet(item, [], streams[:2], {"temperature": "degC", "pressure": "bar(a)"})
    data = yaml.safe_load(text)
    sheet = Datasheet.model_validate(data)
    inlet = sheet.operating.model_extra["inlet_temperature"]
    assert inlet.origin == "measured" and not inlet.assumed and inlet.value == 25.0
    outlet = data["operating"]["outlet_pressure"]
    assert outlet["origin"] == "estimate" and outlet["assumed"] is True
    # a stream value without one gives none
    plain = Quantity(value=25.0, provenance="given").model_dump(mode="json", exclude_none=True)
    streams[0]["state"] = {"temperature": plain}
    data = yaml.safe_load(draft_datasheet(item, [], streams[:1], {"temperature": "degC"}))
    assert "origin" not in data["operating"]["inlet_temperature"]


def test_the_dexpi_sheets_map_measured_to_observed(tmp_path: Path) -> None:
    import pydexpi.pydexpi_classes.pydexpi_classes as C

    from chemeascode.domains.process.build import build_model
    from chemeascode.domains.process.sheets import meta_for, process_entries

    root = tmp_path / "blocks"
    shutil.copytree(EXAMPLES / "process-blocks", root)
    path = root / "process" / "flowsheet.yaml"
    text = path.read_text()
    old = "flow: {value: 1000, basis: mass, provenance: given, source: basis of design}"
    composition = "values: {ETOH: 0.4, H2O: 0.6}, provenance: given,"
    path.write_text(
        text.replace(old, old[:-1] + ", origin: measured}").replace(
            composition, composition + " origin: literature,"
        )
    )
    ws = Workspace(root)
    process, _ = load_process(root)
    entry = process_entries(ws)[0]
    model, _ = build_model(process, entry.kind, meta_for(ws, entry, process))
    values = {}
    for obj in _objects(model):
        if isinstance(obj, C.QualifiedValue):
            values[obj.id] = obj
    flow, pressure = values["S1.design.flow"], values["S1.design.pressure"]
    assert flow.provenance == C.QuantityProvenance.OBSERVED
    assert "given, measured; source: basis of design" in str(flow.description)
    # without an origin, and with one DEXPI has no member for, the class's
    assert pressure.provenance == C.QuantityProvenance.SPECIFIED
    assert "measured" not in str(pressure.description)
    comp = values["S1.design.composition"]
    assert comp.provenance == C.QuantityProvenance.SPECIFIED
    assert "given, literature; basis mass_fraction" in str(comp.description)


def _objects(node, seen=None):
    """Every pydantic object reachable from *node* (the DEXPI model)."""
    from pydantic import BaseModel

    seen = set() if seen is None else seen
    if isinstance(node, BaseModel):
        if id(node) in seen:
            return
        seen.add(id(node))
        yield node
        for name in type(node).model_fields:
            yield from _objects(getattr(node, name, None), seen)
    elif isinstance(node, list | tuple):
        for value in node:
            yield from _objects(value, seen)
    elif isinstance(node, dict):
        for value in node.values():
            yield from _objects(value, seen)


# -- the LCA ------------------------------------------------------------------------------------


def test_the_study_defaults_take_origins() -> None:
    spec = StudyUncertainty.model_validate(
        {"defaults": {"given": {"gsd2": 1.1}, "measured": {"gsd2": 1.02}}}
    )
    assert spec.defaults["measured"] == Uncertainty(gsd2=1.02)
    with pytest.raises(ValidationError):
        StudyUncertainty.model_validate({"defaults": {"guess": {"gsd2": 1.1}}})


def test_the_origin_default_wins_over_the_provenance(blocks: Path) -> None:  # noqa: F811
    path = blocks / "process" / "flowsheet.yaml"
    text = path.read_text()
    old = "uncertainty: {gsd2: 1.2, source: flow meter}"
    assert text.count(old) == 1
    composition = "values: {ETOH: 0.4, H2O: 0.6}, provenance: given,"
    path.write_text(
        text.replace(old, "origin: measured").replace(
            composition, composition + " origin: measured,"
        )
    )
    _study(blocks)
    lca = blocks / "lca" / "lca.yaml"
    scope = yaml.safe_load(lca.read_text())
    scope["uncertainty"]["defaults"]["measured"] = {"gsd2": 1.2}
    lca.write_text(yaml.safe_dump(scope, sort_keys=False))
    report = lca_report(blocks)
    assert report.loaded, [f.format() for f in report.findings]
    exchanges = {e.key: e for e in report.inventory.dataset.exchanges}
    feed = exchanges["feed:FEED"]
    assert feed.origin == "measured" and feed.provenance == "given" and feed.uncertainty is None
    assert exchanges["feed:STEAM"].origin is None
    # a terminal whose values disagree gives none
    assert exchanges["product:WATER"].origin is None
    stats = report.uncertainty.statistics[0]
    # gsd2 1.2 on the feed (measured, not the given default 3.0), the steam within 0.9 .. 1.1
    assert stats.low == pytest.approx(220.5 + 1250 / 1.2, rel=0.03)
    assert stats.high == pytest.approx(220.5 + 1250 * 1.2, rel=0.03)
