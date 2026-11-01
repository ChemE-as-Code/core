"""Comparability of a scenario with the baseline, read from the factors' structured scope
(docs/framework/lci-comparison-basis.md).

For each background a scenario replaces, the baseline factor and the scenario factor are compared
on the declared dimensions (:class:`.schemas.FactorScope` and the reference year):

- ``like-for-like``: every compared dimension is declared and equal on both sides, nothing
  dropped, no declared proxy, no foreign geography kept;
- ``proxy``: the numbers can be set side by side as a screening sensitivity, but a *soft*
  dimension differs (delivery point, GWP basis, grid average vs residual mix, data year), a
  dimension is not declared on one side, the scenario declares a background a proxy, or it keeps
  a background of another geography;
- ``not comparable``: a *hard* dimension differs (basis, gases, consumption vs generation
  accounting), or an exchange the baseline characterises is a gap here (the total does not
  stand).

Declaring a difference as ``proxy:`` discloses it; it never turns a hard difference into a
comparable one. Nothing is inferred from free text.
"""

from __future__ import annotations

from typing import Any

from chemeascode.domains.assessment.lca.schemas import Factor, FactorFile, FactorScope

LIKE_FOR_LIKE = "like-for-like"
PROXY = "proxy"
NOT_COMPARABLE = "not comparable"
BASELINE_VERDICT = "baseline"
VERDICTS = (LIKE_FOR_LIKE, PROXY, NOT_COMPARABLE)

#: A difference makes the totals not comparable at all (different quantity measured).
HARD = ("basis", "gases", "accounting")
#: A difference is a bias that a declared uplift or caveat can bound: a proxy.
SOFT = ("delivery", "gwp", "mix", "year")
DIMENSIONS = (*HARD, *SOFT)


def effective_scope(factors: FactorFile | None, factor_id: str) -> tuple[FactorScope, int | None]:
    """The scope of *factor_id* (its source's, overridden by its own) and the year it is
    compared on: its declared ``data_year``, else its ``year`` as given
    (``year`` is never reinterpreted); an empty scope when the factor or its scope is unknown."""
    if factors is None:
        return FactorScope(), None
    factor: Factor | None = next((f for f in factors.factors if f.id == factor_id), None)
    if factor is None:
        return FactorScope(), None
    source = factors.source(factor)
    base = source.scope if source is not None and source.scope is not None else FactorScope()
    return base.merged(factor.scope), (
        factor.data_year if factor.data_year is not None else factor.year
    )


def year_field(factors: FactorFile | None, factor_id: str) -> str | None:
    """Which year *factor_id* is compared on: ``data_year`` where declared, else ``year``."""
    factor = next((f for f in factors.factors if f.id == factor_id), None) if factors else None
    if factor is None:
        return None
    return "data_year" if factor.data_year is not None else "year"


def source_id(factors: FactorFile | None, factor_id: str) -> str | None:
    """The id of the source *factor_id* cites, if any."""
    if factors is None:
        return None
    factor = next((f for f in factors.factors if f.id == factor_id), None)
    source = factors.source(factor) if factor is not None else None
    return source.id if source is not None else None


def differences(
    base: tuple[FactorScope, int | None],
    other: tuple[FactorScope, int | None],
    same_source: bool = False,
) -> list[dict[str, Any]]:
    """The dimensions on which two (scope, year) pairs are not shown equal: ``differs`` (both
    declared, unequal) or ``undeclared`` (one side, or both, leave it unset). GWP is only
    compared when neither side is CO2 only, where it does not apply. With *same_source* (both
    factors cite one source, one methodology), a dimension both leave unset is not a
    difference: whatever it is, it is the same on both sides."""
    (a, ya), (b, yb) = base, other
    found = []
    for dim in DIMENSIONS:
        if dim == "year":
            left, right = ya, yb
        else:
            left, right = getattr(a, dim), getattr(b, dim)
        if dim == "gwp" and "co2" in (a.gases, b.gases):
            continue
        if left is not None and left == right:
            continue
        if same_source and dim != "year" and left is None and right is None:
            continue
        kind = "differs" if left is not None and right is not None else "undeclared"
        found.append(
            {
                "dimension": dim,
                "baseline": left,
                "scenario": right,
                "kind": kind,
                "severity": "hard" if dim in HARD and kind == "differs" else "soft",
            }
        )
    return found


def verdict(report: Any, scenario: str) -> dict[str, Any]:
    """The comparability of *scenario* with the baseline of a computed *report*:
    ``{"verdict", "reasons", "compared"}``. The baseline is its own reference."""
    if scenario == "baseline":
        return {"verdict": BASELINE_VERDICT, "reasons": [], "compared": []}
    scope = report.scope
    spec = next((s for s in scope.scenarios if s.id == scenario), None) if scope else None
    if spec is None:
        return {
            "verdict": PROXY,
            "reasons": ["scenario not declared in lca/lca.yaml"],
            "compared": [],
        }
    hard: list[str] = []
    soft: list[str] = []
    compared = []
    if scope.backend == "factors":
        for old, new in sorted(spec.factors.items()):
            sid = source_id(report.factors, old)
            diffs = differences(
                effective_scope(report.factors, old),
                effective_scope(report.factors, new),
                same_source=sid is not None and sid == source_id(report.factors, new),
            )
            pair: dict[str, Any] = {"baseline": old, "scenario": new, "differences": diffs}
            fields = (year_field(report.factors, old), year_field(report.factors, new))
            if "data_year" in fields:
                # which year each side was compared on (only where a data year is declared:
                # other records keep their bytes)
                pair["years"] = {"baseline": fields[0], "scenario": fields[1]}
            compared.append(pair)
            for d in diffs:
                text = f"{new} against {old}: {d['dimension']} " + (
                    f"differs ({d['baseline']} / {d['scenario']})"
                    if d["kind"] == "differs"
                    else "is not declared on "
                    + (
                        "either side"
                        if d["baseline"] is None and d["scenario"] is None
                        else "one side"
                    )
                    + f" ({d['baseline']} / {d['scenario']})"
                )
                if d["dimension"] == "year" and "years" in pair:
                    text += f" [{fields[0]} / {fields[1]}]"
                (hard if d["severity"] == "hard" else soft).append(text)
    elif spec.databases:
        soft.append(
            "Brightway databases replaced: their scope is not declared in a structured form"
        )
    lost = report.comparability(scenario)
    if lost:
        hard.append(
            "no background for "
            + (
                ", ".join(sorted({k for keys in lost.values() if keys for k in keys}))
                or "any contribution"
            )
            + ": the total does not stand"
        )
    if spec.electricity in ("residual-mix", "contractual", "on-site"):
        soft.append(f"electricity procurement is {spec.electricity}, not a grid average")
    if spec.proxy:
        soft.append("declared proxy: " + ", ".join(sorted(spec.proxy)))
    if any(f.rule == "cheme.lca-scenario-geography" and scenario in f.ids for f in report.findings):
        soft.append("keeps a background of another geography than the scenario's")
    if hard:
        result = NOT_COMPARABLE
    elif soft:
        result = PROXY
    else:
        result = LIKE_FOR_LIKE
    return {"verdict": result, "reasons": [*hard, *soft], "compared": compared}
