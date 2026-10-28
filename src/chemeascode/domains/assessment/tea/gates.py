"""Stage gates on the TEA: ``kind: tea`` in ``checks/checks.yaml``.

Each item of the gate's ``require`` is one test:

- ``prices``: every feed and product with a flow has a price, or is listed free with a reason;
- ``no-example``: ``estimate/tea.yaml`` is not an example (``example: true``);
- ``class-stage``: the capital cost's AACE class is the one ``class_by_stage`` expects at the
  plant's stage (neither finer than the scope supports nor coarser than the stage needs);
- ``decision``: the analysis states its decision, and the baseline meets its threshold (with a
  Monte Carlo and a ``confidence``: with at least that probability);
- ``tea-current``: ``estimate/tea.md`` and the CSV files exist and are what ``cheme assess tea``
  gives now.

A TEA that does not compute fails every requirement.

The checks are structural: whether the premises are *right* is the judgement of the
analysis' review (skill ``tea``).
"""

from __future__ import annotations

from pathlib import Path

from chemeascode.domains.assessment.tea.report import (
    TEA_FILE,
    outputs,
    tea_report,
)

REQUIREMENTS = ("prices", "no-example", "class-stage", "decision", "tea-current")


def tea_gate(root: Path, require: list[str]) -> list[str]:
    """What fails of *require* for the repository at *root*; empty when the gate passes."""
    root = Path(root)
    report = tea_report(root)
    if not report.loaded:
        errors = [f for f in report.findings if f.level == "error"]
        return [errors[0].message if errors else "the TEA does not compute"]
    problems: list[str] = []
    if "prices" in require:
        unpriced = [
            f.key
            for f in report.flows
            if f.price is None and not f.free and f.rate > 0 and f.key != report.premises.main
        ]
        if unpriced:
            problems.append(f"no price and not listed free in {TEA_FILE}: {', '.join(unpriced)}")
    if "no-example" in require and report.example:
        problems.append(f"{TEA_FILE} is an example (example: true); use the project's premises")
    if "class-stage" in require and report.expected_class != report.claimed_class:
        problems.append(
            f"the capital cost is AACE class {report.claimed_class}; stage "
            f"{report.stage or '(none)'} expects class {report.expected_class or '(none)'}"
        )
    if "decision" in require:
        decision = report.tea.decision
        if decision is None:
            problems.append(f"{TEA_FILE} states no decision")
        elif report.meets() is None:
            problems.append(
                f"the decision's {decision.metric} cannot be computed for the baseline (cheme "
                "assess tea names what is missing)"
            )
        elif not report.meets():
            problems.append(
                f"the baseline does not meet the decision's {decision.metric} threshold"
            )
        elif decision.confidence is not None and report.uncertainty is not None:
            probability = report.uncertainty.probability
            if probability is None:
                problems.append(
                    f"the decision asks for {decision.confidence:.0%} confidence, but the Monte "
                    f"Carlo gives no P(meets) for its {decision.metric}"
                )
            elif probability < decision.confidence:
                problems.append(
                    f"P(meets) = {probability:.0%}, below the decision's confidence "
                    f"{decision.confidence:.0%}"
                )
    if "tea-current" in require:
        for name, text in outputs(report).items():
            path = root / name
            if not path.is_file():
                problems.append(f"no {name}; run cheme assess tea --write")
            elif path.read_text(encoding="utf-8") != text:
                problems.append(f"{name} is not current; run cheme assess tea --write")
    return problems
