import json
from pathlib import Path

import pytest
from typer.testing import CliRunner

from chemeascode.domains.process.activated_sludge import review
from chemeascode.interfaces.cli import app

DATA = Path(__file__).parent / "data" / "activated-sludge"


@pytest.fixture(params=["a2o", "mle"])
def snapshot(request):
    return json.loads((DATA / f"{request.param}_inputs.json").read_bytes())


def test_complete_waterline_matches_preserved_reference(snapshot):
    baseline = json.loads((DATA / "results.json").read_bytes())[snapshot["name"]]
    expected = {}
    for name, value in baseline.items():
        if isinstance(value, dict):
            expected.update({f"{name}.{key}": item for key, item in value.items()})
        else:
            expected[name] = value
    result = review(snapshot)
    assert not result["deferred"]
    assert result["calculated"].keys() == expected.keys()
    for name, value in expected.items():
        assert result["calculated"][name]["value"] == pytest.approx(value, rel=1e-12)
    assert all(check["status"] == "closed" for check in result["water_balances"].values())


def test_missing_settler_profile_preserves_independent_metrics(snapshot):
    del snapshot["clarifier"]["layer_tss_mg_L"]
    full = review(snapshot)
    assert set(full["deferred"]) == {
        "clarifier_inventory_kg_TSS",
        "total_inventory_kg_TSS",
        "system_tss_srt_d",
    }
    assert "layer_tss_mg_L" in full["deferred"]["system_tss_srt_d"]["reason"]
    assert "reactor_only_tss_srt_d" in full["calculated"]
    assert "nominal_bio_hrt_h" in full["calculated"]
    assert "clarifier_solids_loading_kg_TSS_m2_d" in full["calculated"]


@pytest.mark.parametrize("stream,key", [("EFFLUENT", "tss_mg_L"), ("WAS", "flow_m3_d")])
def test_missing_external_loss_defers_both_srts(snapshot, stream, key):
    snapshot["streams"][stream][key] = None
    result = review(snapshot)
    assert {"reactor_only_tss_srt_d", "system_tss_srt_d"} <= result["deferred"].keys()
    assert {"nominal_bio_hrt_h", "clarifier_solids_loading_kg_TSS_m2_d"} <= result[
        "calculated"
    ].keys()
    if key == "flow_m3_d":
        assert result["water_balances"]["external"]["status"] == "not-evaluable"


def test_wrong_clarifier_feed_is_not_published_as_a_loading(snapshot):
    snapshot["streams"]["TO_CLARIFIER"]["flow_m3_d"] += snapshot["streams"]["INTERNAL"]["flow_m3_d"]
    result = review(snapshot)
    assert result["water_balances"]["clarifier"]["status"] == "inconsistent"
    assert {
        "clarifier_feed_per_area_m3_m2_d",
        "clarifier_feed_kg_TSS_d",
        "clarifier_solids_loading_kg_TSS_m2_d",
    } <= result["deferred"].keys()
    assert {"effluent_overflow_m3_m2_d", "nominal_bio_hrt_h"} <= result["calculated"].keys()


def test_missing_area_and_zero_loss_keep_independent_results(snapshot):
    del snapshot["clarifier"]["area_m2"]
    for name in ("EFFLUENT", "WAS"):
        snapshot["streams"][name]["tss_mg_L"] = 0
    result = review(snapshot)
    assert "zero external TSS loss" in result["deferred"]["reactor_only_tss_srt_d"]["reason"]
    assert {"system_tss_srt_d", "effluent_overflow_m3_m2_d"} <= result["deferred"].keys()
    assert {"nominal_bio_hrt_h", "clarifier_feed_kg_TSS_d"} <= result["calculated"].keys()


def test_command_reports_partial_metrics_without_writing(snapshot, tmp_path):
    del snapshot["clarifier"]["layer_tss_mg_L"]
    path = tmp_path / "snapshot.json"
    before = json.dumps(snapshot).encode()
    path.write_bytes(before)
    run = CliRunner().invoke(app, ["process", "activated-sludge-review", str(path)])
    assert run.exit_code == 0, run.output
    payload = json.loads(run.stdout)
    assert payload["calculated"]["nominal_bio_hrt_h"]["unit"] == "h"
    assert "system_tss_srt_d" in payload["deferred"]
    assert path.read_bytes() == before
