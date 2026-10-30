"""A rating's likelihood from the project's frequency library (domains/safety/frequencies.py,
``frequency:`` on a rating, ``cheme safety hazop rate``). The library here is synthetic: generic
ids and values, no source data. A real library is project data (safety/frequencies.yaml)."""

import shutil
from pathlib import Path

import pytest
import yaml
from pydantic import ValidationError

from chemeascode.domains.safety.frequencies import derive
from chemeascode.domains.safety.hazop import load_study, rate, study_findings
from chemeascode.domains.safety.risk_matrix import matrix_fingerprint
from chemeascode.domains.safety.schemas import FrequencyLibrary, FrequencyRef, RiskMatrix
from chemeascode.foundation.workspace import Workspace

ROOT = Path(__file__).resolve().parents[1]
EXAMPLE = ROOT / "examples" / "safety-hazop"
STUDY = "safety/hazop/H-01/study.yaml"
MATRIX = "safety/risk-matrix.yaml"

LIBRARY = """\
schema: cheme/frequencies/v1
kind: frequencies
example: true
source: synthetic test data
sources:
  lopa: {short: a LOPA table, basis: lopa_ief}
  qra: {short: a QRA manual, basis: qra_loc}
event_types:
  seal_leak: {label: Seal leak}
  pipe_break: {label: Pipe break}
  nothing: {label: Nothing recorded}
records:
  - {id: R1, event_type: seal_leak, value: 0.1, source: lopa}
  - {id: R2, event_type: seal_leak, value: 0.5, source: qra}
  - {id: R3, event_type: seal_leak, value: 0.03, source: lopa}
  - {id: R4, event_type: pipe_break, value: 1.0e-5, per: 100 m of pipe, source: lopa}
"""
#: Upper bounds of the example matrix's grades A to C (D: everything above).
BOUNDS = {
    "Not expected in the life of the plant": 1.0e-4,
    "Could happen once in the life of the plant": 1.0e-2,
    "Could happen several times in the life of the plant": 0.2,
}


def _edit(root: Path, old: str, new: str, path: str = STUDY) -> None:
    file = root / path
    text = file.read_text(encoding="utf-8")
    assert old in text, old
    file.write_text(text.replace(old, new, 1), encoding="utf-8")


def _bounded(root: Path) -> None:
    for description, bound in BOUNDS.items():
        _edit(root, f"{description}}}", f"{description}, max_frequency: {bound}}}", MATRIX)


@pytest.fixture
def plant(tmp_path: Path) -> Path:
    root = tmp_path / "plant"
    shutil.copytree(EXAMPLE, root, ignore=shutil.ignore_patterns("build"))
    (root / "safety" / "frequencies.yaml").write_text(LIBRARY, encoding="utf-8")
    _edit(
        root,
        "risk_matrix: safety/risk-matrix.yaml",
        "risk_matrix: safety/risk-matrix.yaml\nfrequencies: safety/frequencies.yaml",
    )
    _bounded(root)
    return root


def _models(root: Path):
    library = FrequencyLibrary.model_validate(yaml.safe_load(LIBRARY))
    matrix = RiskMatrix.model_validate(yaml.safe_load((root / MATRIX).read_text(encoding="utf-8")))
    return library, matrix


def test_an_event_type_takes_its_lopa_records_first_and_the_highest(plant):
    library, matrix = _models(plant)
    seal = derive(library, matrix, FrequencyRef(event_type="seal_leak"))
    assert (seal.code, seal.record.id) == ("C", "R1")  # R2 is higher, but a QRA value
    assert derive(library, matrix, FrequencyRef(record="R2")).code == "D"
    assert derive(library, matrix, FrequencyRef(record="R3")).code == "C"


@pytest.mark.parametrize(
    ("ref", "level", "said"),
    [
        ({"event_type": "nothing"}, "info", "no record per item"),
        ({"event_type": "pipe_break"}, "info", "no record per item"),
        ({"record": "R4"}, "info", "per 100 m of pipe"),
        ({"record": "R9"}, "error", "no record R9"),
        ({"event_type": "flood"}, "error", "no event type flood"),
    ],
)
def test_no_likelihood_is_given_without_a_record_per_item(plant, ref, level, said):
    library, matrix = _models(plant)
    found = derive(library, matrix, FrequencyRef(**ref))
    assert found.code is None and found.level == level and said in found.problem


def test_the_bounds_increase_and_do_not_change_the_matrix_fingerprint(plant, tmp_path):
    library, bounded = _models(plant)
    plain = RiskMatrix.model_validate(
        yaml.safe_load((EXAMPLE / MATRIX).read_text(encoding="utf-8"))
    )
    assert matrix_fingerprint(bounded) == matrix_fingerprint(plain)  # recorded bands stay current
    assert "no max_frequency" in derive(library, plain, FrequencyRef(record="R1")).problem
    data = yaml.safe_load((plant / MATRIX).read_text(encoding="utf-8"))
    data["likelihood"][1]["max_frequency"] = 1.0e-5  # below grade A's bound
    with pytest.raises(ValidationError, match="increasing"):
        RiskMatrix.model_validate(data)


def test_rate_writes_the_derived_likelihood_and_then_the_band(plant):
    _edit(
        plant,
        "                  likelihood: C\n                  basis: Pump seal",
        "                  likelihood: C\n                  frequency: {record: R2}\n"
        "                  basis: Pump seal",
    )
    before = (plant / STUDY).read_text(encoding="utf-8")
    loaded = load_study(plant, STUDY)
    rules = {f.rule for f in study_findings(Workspace(plant), loaded)}
    assert "cheme.hazop-likelihood-derived" in rules

    checked = rate(Workspace(plant), "H-01", write=False)
    assert [(r.scenario, r.derived.code) for r in checked.likelihoods] == [("S1", "D")]
    assert (plant / STUDY).read_text(encoding="utf-8") == before

    written = rate(Workspace(plant), "H-01", write=True)
    assert written.written
    after = (plant / STUDY).read_text(encoding="utf-8")
    changed = [b for a, b in zip(before.splitlines(), after.splitlines(), strict=True) if a != b]
    assert len(changed) == 2  # the likelihood and the band of that rating, nothing else
    assert changed[0].strip() == "likelihood: D" and "value: high" in changed[1]
    again = rate(Workspace(plant), "H-01", write=False)
    assert not again.likelihoods and not again.changes
    rules = {f.rule for f in study_findings(Workspace(plant), load_study(plant, STUDY))}
    assert "cheme.hazop-likelihood-derived" not in rules


def test_a_link_without_a_library_is_an_error_and_a_missing_record_is_info(plant):
    _edit(
        plant,
        "                  likelihood: C\n                  basis: Pump seal",
        "                  likelihood: C\n                  frequency: {event_type: nothing}\n"
        "                  basis: Pump seal",
    )
    found = study_findings(Workspace(plant), load_study(plant, STUDY))
    levels = {f.level for f in found if f.rule == "cheme.hazop-frequency"}
    assert levels == {"info"}  # the likelihood stays as the team gave it
    _edit(plant, "frequencies: safety/frequencies.yaml\n", "")
    found = study_findings(Workspace(plant), load_study(plant, STUDY))
    assert any(
        f.rule == "cheme.hazop-frequency" and f.level == "error" and "no frequencies" in f.message
        for f in found
    )
