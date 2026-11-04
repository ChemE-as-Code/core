"""The unallocated LCI dataset of one design case: ``cheme assess lca --dataset --case <id>``
(ADR 0045).

The plant's dataset ``lca/dataset.yaml`` is that of the flowsheet case ``lca/lca.yaml`` names
(``case:``, else the flowsheet's default case). Another computed case of the same flowsheet
gets a dataset of its own, derived the same way from that case's stream states
(:func:`.report.lca_report` with ``case=``), and an identity naming the case, so that two
datasets of one process never share an id, a title or a uuid:

- ``id``: ``<dataset id>-<case>``, the case id made an identifier (:func:`case_slug`);
- ``title``: ``<title>, case <case>`` (the dataset id stands in for an empty title);
- ``uuid``: ``uuid5(<the plant dataset's uuid>, "case:<case>")`` (:func:`case_uuid`), from the
  uuid ``lca/lca.yaml`` pins (``dataset: uuid:``) or the one cheme derives: the same base and
  case give the same uuid in every version, and the base dataset's uuid is unchanged.

The reference product, the functional unit, the basis and the documentation are the study's.
``--write --case`` writes it to ``lca/datasets/<dataset id>-<case>.yaml``
(:func:`case_dataset_path`), never over a file it did not generate for that case
(:func:`overwrite_finding`); ``--check --case`` compares it with what would be generated now
(:func:`stale_finding`). A case naming the study's own case is the plant's dataset itself:
``lca/dataset.yaml``, unchanged.
"""

from __future__ import annotations

import re
import uuid as _uuid
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING

import yaml

from chemeascode.domains.assessment.lca.documentation import NAMESPACE
from chemeascode.domains.assessment.lca.schemas import LciDataset
from chemeascode.foundation.findings import Finding

if TYPE_CHECKING:
    from chemeascode.domains.assessment.lca.report import LcaReport

#: Where a design case's dataset is written (beside the hand-written and estimated datasets).
CASE_DATASETS_DIR = "lca/datasets"
#: ``provenance.generator`` of every dataset ``cheme assess lca`` derives from the flowsheet.
GENERATOR = "cheme assess lca"


class UnknownCase(ValueError):
    """*case* is no case of the flowsheet; *cases* are the declared ones."""

    def __init__(self, case: str, cases: list[str]) -> None:
        self.case = case
        self.cases = list(cases)
        declared = ", ".join(self.cases) if self.cases else "none declared"
        super().__init__(f"case {case!r} is not a case of process/flowsheet.yaml ({declared})")


def case_slug(case: str) -> str:
    """*case* made an identifier: what is not ``[A-Za-z0-9_.-]`` becomes ``-``, lower case."""
    return re.sub(r"[^A-Za-z0-9_.\-]+", "-", case).strip("-").lower() or "case"


def case_uuid(base: str, case: str) -> str:
    """The uuid of the dataset of *case*: ``uuid5(base, "case:<case>")``, *base* being the
    plant dataset's uuid."""
    return str(_uuid.uuid5(_uuid.UUID(base), f"case:{case}"))


def with_case(dataset: LciDataset, case: str) -> LciDataset:
    """*dataset* (derived for *case*) with the identity of a design case's dataset: its id,
    title and uuid name the case; nothing else changes. *dataset* is documented
    (:func:`.documentation.document`), so it has the plant dataset's uuid."""
    base = dataset.uuid or str(_uuid.uuid5(NAMESPACE, dataset.id))
    return dataset.model_copy(
        update={
            "id": f"{dataset.id}-{case_slug(case)}",
            "title": f"{dataset.title or dataset.id}, case {case}",
            "uuid": case_uuid(base, case),
        }
    )


def case_dataset_path(dataset_id: str) -> str:
    """Where the design case's dataset with id *dataset_id* is written."""
    return f"{CASE_DATASETS_DIR}/{dataset_id}.yaml"


def variant_case(root: Path, case: str) -> str | None:
    """*case* when it is a flowsheet case other than the one ``lca/lca.yaml`` studies; None
    when it is that case. When the flowsheet does not load, *case* (the report then says what
    is wrong). Raises :class:`UnknownCase` for a case the flowsheet does not declare."""
    from chemeascode.domains.assessment.lca.inventory import LCA_FILE
    from chemeascode.domains.process.model import load

    process, _ = load(Path(root))
    if process is None:
        return case
    declared = [c.id for c in process.flowsheet.cases]
    if case not in declared:
        raise UnknownCase(case, declared)
    try:
        data = yaml.safe_load((Path(root) / LCA_FILE).read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, yaml.YAMLError):
        return case
    studied = data.get("case") if isinstance(data, dict) else None
    return None if case == (studied or process.flowsheet.default_case()) else case


@dataclass
class CaseDataset:
    """The dataset of one flowsheet case, as ``cheme assess lca --write --case`` writes it.

    ``path`` is ``lca/datasets/<id>.yaml`` (``lca/dataset.yaml`` for the study's own case), and
    ``text`` the file (empty, with ``path`` empty, when the case gives no dataset: the
    report's findings say why)."""

    case: str
    path: str
    text: str
    report: LcaReport

    @property
    def findings(self) -> list[Finding]:
        return self.report.findings

    @property
    def loaded(self) -> bool:
        return self.report.loaded and bool(self.text)


def case_dataset(root: Path, case: str) -> CaseDataset:
    """The unallocated LCI dataset of flowsheet *case* of the plant at *root* (foreground
    only: no factors or background needed). Raises :class:`UnknownCase` for an undeclared
    case and :class:`NotAPlantRepository` without ``plant.yaml``."""
    from chemeascode.domains.assessment.lca.report import DATASET_FILE, dataset_yaml, lca_report

    report = lca_report(Path(root), case=case)
    dataset = report.inventory.dataset if report.inventory is not None else None
    if dataset is None or not report.loaded:
        return CaseDataset(case, "", "", report)
    path = case_dataset_path(dataset.id) if report.variant_case else DATASET_FILE
    return CaseDataset(case, path, dataset_yaml(report), report)


def _rerun(case: str) -> str:
    return f"rerun cheme assess lca --write --case {case}"


def stale_finding(root: Path, result: CaseDataset) -> Finding | None:
    """The error ``cheme.lca-dataset-stale`` when the written file of *result* is missing or
    differs from what is generated now; None when it is current."""
    path = Path(root) / result.path
    try:
        written = path.read_text(encoding="utf-8") if path.is_file() else None
    except (OSError, UnicodeDecodeError):
        written = None
    if written == result.text:
        return None
    if written is None:
        message = f"{result.path} is not written (the dataset of case {result.case})"
    else:
        message = (
            f"{result.path} differs from the dataset of case {result.case} generated now: an "
            "input (the flowsheet, lca/lca.yaml, ...) or cheme changed since it was written"
        )
    return Finding(
        result.path,
        "error",
        "cheme.lca-dataset-stale",
        message,
        ids=[result.case],
        hint=_rerun(result.case) + " and commit it; never edit it by hand",
    )


def overwrite_finding(root: Path, result: CaseDataset) -> Finding | None:
    """The error ``cheme.lca-dataset-not-generated`` when ``--write --case`` would replace a
    file in ``lca/datasets/`` that is not the dataset cheme generated for that case (a
    hand-written or estimated dataset of the same id); None when it may be written."""
    path = Path(root) / result.path
    if not result.report.variant_case or not path.is_file():
        return None
    try:
        data = yaml.safe_load(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, yaml.YAMLError):
        data = None
    provenance = data.get("provenance") if isinstance(data, dict) else None
    if (
        isinstance(provenance, dict)
        and provenance.get("generator") == GENERATOR
        and provenance.get("case") == result.case
        and data.get("generation") is None
    ):
        return None
    return Finding(
        result.path,
        "error",
        "cheme.lca-dataset-not-generated",
        f"{result.path} exists and is not the dataset cheme assess lca generated for case "
        f"{result.case}: not overwritten",
        ids=[result.case],
        hint="move or rename that dataset (or give the flowsheet another title), then "
        + _rerun(result.case),
    )
