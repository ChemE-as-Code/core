"""Stage gates on the take-off and the estimate: ``kind: mto`` in ``checks/checks.yaml``.

Each item of the gate's ``require`` is one test:

- ``mto-current``: ``estimate/mto.csv`` exists and is what ``cheme assess mto`` gives for
  the committed ``layout/plant-model.yaml`` now (the take-off was rewritten after the model's
  last change);
- ``rates``: ``estimate/rates.yaml`` loads, is not an example, and prices every take-off row;
- ``estimate-current``: ``estimate/estimate.csv`` exists and is what ``cheme assess
  estimate`` gives now;
- ``equipment-current``: ``estimate/equipment-cost.csv`` exists and is what ``cheme assess
  equipment`` gives now;
- ``equipment-covered``: every equipment-list item is costed (a correlation with its bare
  module cost, or the project's own cost) or excluded with a reason, and the costs are
  escalated by a project cost index.

The checks are structural: whether the quantities and rates are *right* is the judgement of the
estimate's review (skill ``mto-estimate``).
"""

from __future__ import annotations

from pathlib import Path

from chemeascode.domains.assessment.estimate import (
    ESTIMATE_CSV,
    RATES_FILE,
    estimate_csv,
    load_rates,
    texts_estimate,
)
from chemeascode.domains.assessment.mto import MTO_CSV, model_takeoff, mto_csv
from chemeascode.foundation.workspace import LAYOUT_MODEL_FILE

REQUIREMENTS = (
    "mto-current",
    "rates",
    "estimate-current",
    "equipment-current",
    "equipment-covered",
)


def _read(root: Path, name: str) -> str | None:
    path = root / name
    return path.read_text(encoding="utf-8") if path.is_file() else None


def mto_gate(root: Path, require: list[str]) -> list[str]:
    """What fails of *require* for the repository at *root*; empty when the gate passes."""
    root = Path(root)
    problems: list[str] = _equipment(root, require)
    if not set(require) & {"mto-current", "rates", "estimate-current"}:
        return problems
    model_text = _read(root, LAYOUT_MODEL_FILE)
    takeoff = model_takeoff(model_text)
    if model_text is None:
        return [*problems, f"no {LAYOUT_MODEL_FILE}; run cheme layout build"]
    if "mto-current" in require:
        committed = _read(root, MTO_CSV)
        if committed is None:
            problems.append(f"no {MTO_CSV}; run cheme assess mto --write")
        elif committed != mto_csv(takeoff.rows):
            problems.append(
                f"{MTO_CSV} is not the take-off of the current model; run cheme assess mto --write"
            )
    rates_text = _read(root, RATES_FILE)
    if "rates" in require:
        rates, found = load_rates(rates_text)
        if rates is None:
            problems.append(found[0].message)
        elif rates.example:
            problems.append(f"{RATES_FILE} is an example (example: true); use the project's rates")
        else:
            result = texts_estimate(model_text, rates_text)
            unpriced = result.totals().get("unpriced_rows", 0) if result.lines else 0
            if unpriced:
                problems.append(f"{unpriced} take-off rows have no rate in {RATES_FILE}")
    if "estimate-current" in require:
        committed = _read(root, ESTIMATE_CSV)
        result = texts_estimate(model_text, rates_text)
        if committed is None:
            problems.append(f"no {ESTIMATE_CSV}; run cheme assess estimate --write")
        elif not result.lines or committed != estimate_csv(result):
            problems.append(
                f"{ESTIMATE_CSV} is not the estimate of the current take-off and rates; run "
                "cheme assess estimate --write"
            )
    return problems


def _equipment(root: Path, require: list[str]) -> list[str]:
    """The ``equipment-current`` and ``equipment-covered`` requirements."""
    if not set(require) & {"equipment-current", "equipment-covered"}:
        return []
    from chemeascode.domains.assessment.equipment_cost import (
        COST_CSV,
        cost_csv,
        equipment_estimate,
    )

    result = equipment_estimate(root)
    problems = []
    if "equipment-current" in require:
        committed = _read(root, COST_CSV)
        if committed is None:
            problems.append(f"no {COST_CSV}; run cheme assess equipment --write")
        elif committed != cost_csv(result):
            problems.append(
                f"{COST_CSV} is not the equipment estimate of the current lists and cost "
                "basis; run cheme assess equipment --write"
            )
    if "equipment-covered" in require:
        partial = [
            line.tag for line in result.lines if line.status in ("not covered", "purchased only")
        ]
        if partial:
            shown = ", ".join(partial[:3]) + (
                f" and {len(partial) - 3} more" if len(partial) > 3 else ""
            )
            problems.append(
                f"{len(partial)} items without a bare module or own cost: {shown}; complete "
                "their size, factors or cost in estimate/cost-basis.yaml, or exclude them "
                "with a reason"
            )
        if result.index is None:
            problems.append("estimate/cost-basis.yaml gives no cost_index: costs not escalated")
    return problems
