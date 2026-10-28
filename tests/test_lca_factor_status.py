"""The factor status of every exchange, ``--strict`` and the gate's ``factors-published``
(pre-release issue 322): a result computed with example, assumed, proxy or estimated factors, or
with a gap, is never passed as a published one.

The plant is ``examples/process-blocks`` with the study of ``test_lca_coverage``.
"""

import copy
import json
from pathlib import Path

import pytest
from typer.testing import CliRunner

from chemeascode.domains.assessment.lca.gates import lca_gate
from chemeascode.domains.assessment.lca.report import factor_status, manifest, unpublished
from chemeascode.interfaces.cli import app
from tests.test_lca_coverage import FACTORS, SCOPE, _report, _write, blocks  # noqa: F401

runner = CliRunner()


def test_published_factors_pass(blocks: Path) -> None:  # noqa: F811
    report = _report(blocks)
    assert factor_status(report) == {
        "feed:FEED": "PUBLISHED",
        "feed:STEAM": "PUBLISHED",
        "product:WATER": "PUBLISHED",
        "product:PROD": "none",
    }
    assert unpublished(report) == []
    assert lca_gate(blocks, ["factors-published"]) == []
    assert manifest(report)["result"]["factors_published"] is True


def test_the_weakest_status_of_an_exchange_counts(blocks: Path) -> None:  # noqa: F811
    factors = copy.deepcopy(FACTORS)
    factors["factors"][1]["status"] = "ESTIMATE"
    factors["factors"][1]["basis"] = "derived by the project"
    factors["factors"][1]["validity"] = "this plant"
    factors["factors"][2]["status"] = "ASSUMED"
    report = _report(blocks, factors=factors)
    found = factor_status(report)
    assert (found["feed:STEAM"], found["product:WATER"]) == ("ESTIMATE", "ASSUMED")
    assert unpublished(report) == [
        "feed:STEAM: factor status ESTIMATE",
        "product:WATER: factor status ASSUMED",
    ]
    problems = lca_gate(blocks, ["factors-published"])
    assert problems == [
        "2 exchanges rest on unpublished factors: feed:STEAM: factor status ESTIMATE, "
        "product:WATER: factor status ASSUMED"
    ]
    assert manifest(report)["result"]["factor_status"]["feed:STEAM"] == "ESTIMATE"


def test_example_factors_are_never_published(blocks: Path) -> None:  # noqa: F811
    report = _report(blocks, factors={**copy.deepcopy(FACTORS), "example": True})
    assert set(factor_status(report).values()) == {"example", "none"}
    assert lca_gate(blocks, ["factors-published"])


def test_a_gap_is_weaker_than_any_factor(blocks: Path) -> None:  # noqa: F811
    factors = copy.deepcopy(FACTORS)
    factors["factors"][1]["values"].pop("water")
    report = _report(blocks, factors=factors)
    assert factor_status(report)["feed:STEAM"] == "gap"
    assert "feed:STEAM: factor status gap" in unpublished(report)


def test_a_proxy_mapping_is_a_proxy(blocks: Path) -> None:  # noqa: F811
    scope = copy.deepcopy(SCOPE)
    scope["flows"][0]["proxy"] = "a related feed"
    report = _report(blocks, scope=scope)
    assert factor_status(report)["feed:FEED"] == "PROXY"


def test_strict_fails_and_names_each_exchange(blocks: Path, monkeypatch) -> None:  # noqa: F811
    monkeypatch.chdir(blocks)
    assert runner.invoke(app, ["assess", "lca", "--strict"]).exit_code == 0
    factors = copy.deepcopy(FACTORS)
    factors["factors"][0]["status"] = "ASSUMED"
    _write(blocks, SCOPE, factors)
    shown = runner.invoke(app, ["assess", "lca", "--strict"])
    assert shown.exit_code == 1
    assert (
        "error cheme.lca-factor-status: --strict: feed:FEED: factor status ASSUMED" in shown.stderr
    )
    # the result itself is still shown; without --strict a screening result exits 0
    assert "feed:FEED" in shown.stdout
    assert runner.invoke(app, ["assess", "lca"]).exit_code == 0
    payload = json.loads(runner.invoke(app, ["assess", "lca", "--json"]).stdout)
    assert payload["factor_status"]["baseline"]["feed:FEED"] == "ASSUMED"
    assert payload["factors_published"] is False


def test_the_requirement_is_valid_in_checks() -> None:
    from chemeascode.foundation.schemas.checks import Check

    gate = {"id": "lca-pub", "title": "LCA on published data", "stage": "basic", "kind": "lca"}
    Check.model_validate({**gate, "require": ["factors-published"]})
    with pytest.raises(ValueError, match="requires only"):
        Check.model_validate({**gate, "kind": "mto", "require": ["factors-published"]})


def test_an_example_factor_inside_a_dataset_is_example(blocks: Path) -> None:  # noqa: F811
    import dataclasses

    report = _report(blocks, factors={**copy.deepcopy(FACTORS), "example": True})
    # a dataset's contribution joins all of its sources: a packaged method and a factor
    report.impacts = [
        dataclasses.replace(i, source_id="method:ipcc2021,open-test", status="PUBLISHED")
        for i in report.impacts
    ]
    assert factor_status(report)["feed:FEED"] == "example"
    report.impacts = [dataclasses.replace(i, source_id="method:ipcc2021") for i in report.impacts]
    assert factor_status(report)["feed:FEED"] == "PUBLISHED"


def test_strict_keeps_the_balance_output(blocks: Path, monkeypatch) -> None:  # noqa: F811
    monkeypatch.chdir(blocks)
    plain = runner.invoke(app, ["assess", "lca", "--balance"])
    strict = runner.invoke(app, ["assess", "lca", "--balance", "--strict"])
    assert strict.exit_code == 0, strict.output
    assert strict.stdout == plain.stdout
    factors = copy.deepcopy(FACTORS)
    factors["factors"][0]["status"] = "ASSUMED"
    _write(blocks, SCOPE, factors)
    strict = runner.invoke(app, ["assess", "lca", "--balance", "--strict"])
    assert strict.exit_code == 1 and strict.stdout == plain.stdout
    assert "cheme.lca-factor-status" in strict.stderr
