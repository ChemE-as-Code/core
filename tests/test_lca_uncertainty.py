"""Monte Carlo uncertainty, pedigree scores, sensitivity, and elementary emissions.

The plant is ``examples/process-blocks`` (see ``test_lca.py``): per t of product, 2500 kg of
feed (0.5 kg CO2-eq/kg: 1250) and 875 kWh of steam (220.5).
"""

import math
import shutil
from pathlib import Path

import numpy as np
import pytest
import yaml

from chemeascode.domains.assessment.lca.report import lca_report, results_markdown, uncertainty_csv
from chemeascode.domains.assessment.lca.schemas import Uncertainty
from chemeascode.domains.assessment.lca.uncertainty import (
    PEDIGREE,
    pedigree_gsd2,
    sample,
    spearman,
)

EXAMPLE = Path(__file__).parents[1] / "examples" / "process-blocks"


def _factor(id_: str, unit: str, gwp: float, **extra) -> dict:
    return {
        "id": id_,
        "unit": unit,
        "values": {"gwp": gwp},
        "status": "ASSUMED",
        "source": "test",
        "year": 2025,
        **extra,
    }


FACTORS = {
    "schema": "cheme/lca/v1",
    "kind": "lca_factors",
    "categories": [{"id": "gwp", "unit": "kg CO2-eq", "elementary": "ipcc2021-gwp100"}],
    "factors": [_factor("feed", "kg", 0.5), _factor("steam", "MJ", 0.07)],
}


def _scope(**extra) -> dict:
    return {
        "schema": "cheme/lca/v1",
        "kind": "lca",
        "functional_unit": {"product": "PROD", "amount": 1, "unit": "t"},
        "allocation": {"method": "none"},
        "flows": [
            {"key": "feed:FEED", "factor": "feed", "source": "test", "uncertainty": {"gsd2": 1.2}},
            {"key": "feed:STEAM", "factor": "steam", "source": "test"},
            {"key": "product:WATER", "free": True, "source": "test"},
        ],
        "uncertainty": {"iterations": 2000, "seed": 7},
        **extra,
    }


def _write(root: Path, scope: dict, factors: dict | None = None) -> None:
    (root / "lca").mkdir(exist_ok=True)
    (root / "lca" / "lca.yaml").write_text(yaml.safe_dump(scope, sort_keys=False))
    (root / "lca" / "factors.yaml").write_text(yaml.safe_dump(factors or FACTORS, sort_keys=False))


@pytest.fixture
def blocks(tmp_path: Path) -> Path:
    root = tmp_path / "blocks"
    shutil.copytree(EXAMPLE, root)
    return root


# -- distributions ------------------------------------------------------------------------------


def test_pedigree_gsd2() -> None:
    assert pedigree_gsd2([1, 1, 1, 1, 1], 1.05) == pytest.approx(1.05)
    expected = math.exp(
        math.sqrt(
            math.log(1.05) ** 2
            + sum(
                math.log(f[s - 1]) ** 2
                for f, s in zip(PEDIGREE.values(), [2, 3, 1, 4, 5], strict=True)
            )
        )
    )
    assert pedigree_gsd2([2, 3, 1, 4, 5]) == pytest.approx(expected)
    assert pedigree_gsd2([5, 5, 5, 5, 5]) > pedigree_gsd2([2, 2, 2, 2, 2]) > 1.05


@pytest.mark.parametrize(
    ("spec", "check"),
    [
        (
            {"gsd2": 1.5},
            lambda m: (
                np.median(m) == pytest.approx(1, abs=0.02)
                and np.mean((m > 1 / 1.5) & (m < 1.5)) == pytest.approx(0.95, abs=0.01)
            ),
        ),
        (
            {"pedigree": [1, 1, 1, 1, 1], "basic": 1.2},
            lambda m: np.mean((m > 1 / 1.2) & (m < 1.2)) == pytest.approx(0.95, abs=0.01),
        ),
        (
            {"distribution": "normal", "cv": 0.1},
            lambda m: (
                m.mean() == pytest.approx(1, abs=0.01) and m.std() == pytest.approx(0.1, rel=0.05)
            ),
        ),
        (
            {"distribution": "uniform", "low": 0.8, "high": 1.2},
            lambda m: m.min() >= 0.8 and m.max() <= 1.2,
        ),
        (
            {"distribution": "triangular", "low": 0.5, "high": 2.0},
            lambda m: m.min() >= 0.5 and m.max() <= 2.0,
        ),
    ],
)
def test_distributions(spec: dict, check) -> None:
    multipliers = sample(Uncertainty(**spec), 20000, np.random.default_rng(1))
    assert check(multipliers)


def test_distribution_rules() -> None:
    from pydantic import ValidationError

    for bad, match in (
        ({}, "gsd2 or pedigree"),
        ({"gsd2": 1.2, "pedigree": [1, 1, 1, 1, 1]}, "gsd2 or pedigree"),
        ({"pedigree": [1, 2, 3, 4, 6]}, "1 to 5"),
        ({"distribution": "normal"}, "needs cv"),
        ({"distribution": "uniform", "low": 1.1, "high": 1.2}, "low <= 1 <= high"),
    ):
        with pytest.raises(ValidationError, match=match):
            Uncertainty(**bad)


def test_spearman() -> None:
    x = np.arange(100.0)
    assert spearman(x, x**3) == pytest.approx(1)
    assert spearman(x, -x) == pytest.approx(-1)
    assert spearman(x, np.ones(100)) == 0


# -- the study ----------------------------------------------------------------------------------


def test_monte_carlo_of_the_study(blocks: Path) -> None:
    scope = _scope()
    # the steam taken as exact: without it, its pedigree would vary it (pre-release issue 178)
    scope["flows"][1]["uncertainty"] = {"gsd2": 1.0}
    _write(blocks, scope)
    report = lca_report(blocks)
    assert report.loaded, [f.format() for f in report.findings]
    mc = report.uncertainty
    assert (mc.iterations, mc.seed) == (2000, 7)
    assert mc.varied == ["amount:feed:FEED"]
    stats = mc.statistics[0]
    assert stats.deterministic == pytest.approx(1470.5)
    # only the feed varies: the steam's 220.5 is a floor, the feed's median is unchanged
    assert stats.median == pytest.approx(1470.5, rel=0.01)
    assert stats.low > 220.5 and stats.low < stats.median < stats.high
    assert stats.low == pytest.approx(220.5 + 1250 / 1.2, rel=0.02)
    assert stats.sensitivity[0][0] == "amount:feed:FEED" and stats.sensitivity[0][1] > 0.99
    # the same seed, the same file
    csv = uncertainty_csv(report)
    assert csv.splitlines()[0].startswith("category,unit,deterministic,mean")
    assert csv == uncertainty_csv(lca_report(blocks))
    markdown = results_markdown(report)
    assert "## Uncertainty (baseline, Monte Carlo, 2000 iterations, seed 7)" in markdown
    assert "- amount:feed:FEED: +1.00" in markdown


def test_defaults_by_provenance_and_factor_uncertainty(blocks: Path) -> None:
    scope = _scope()
    scope["flows"][0].pop("uncertainty")
    scope["uncertainty"]["defaults"] = {"assumed": {"gsd2": 1.3}}
    factors = yaml.safe_load(yaml.safe_dump(FACTORS))
    factors["factors"][1]["uncertainty"] = {"distribution": "uniform", "low": 0.5, "high": 1.5}
    _write(blocks, scope, factors)
    mc = lca_report(blocks).uncertainty
    # the feed's flow is given (no default for given): its pedigree's lognormal
    # (pre-release issue 178); the steam's duty is assumed: the study's default
    assert mc.bases["amount:feed:FEED"] == "pedigree"
    assert mc.bases["amount:feed:STEAM"] == "study default"
    assert mc.bases["factor:steam"] == "given"
    assert {"amount:feed:STEAM", "factor:steam"} <= set(mc.varied)
    ranked = [name for name, _ in mc.statistics[0].sensitivity]
    assert "factor:steam" in ranked


def test_allocation_shares_move_with_the_coproducts(blocks: Path) -> None:
    scope = _scope(allocation={"method": "mass", "coproducts": ["WATER"]})
    scope["flows"] = [f for f in scope["flows"] if f["key"] != "product:WATER"]
    scope["flows"][0].pop("uncertainty")
    scope["uncertainty"]["defaults"] = {"assumed": {"gsd2": 1.5}}  # WATER's flow is assumed
    _write(blocks, scope)
    stats = lca_report(blocks).uncertainty.statistics[0]
    rho = dict(stats.sensitivity)
    # more water made: a smaller share for the product
    assert rho["amount:product:WATER"] < -0.3


# -- elementary emissions -----------------------------------------------------------------------


def _emitting(blocks: Path, origin: str = "fossil", cas: str = "74-82-8") -> None:
    """WATER released to air; its ethanol given methane's CAS number to have a factor."""
    materials = blocks / "process" / "materials.yaml"
    materials.write_text(materials.read_text().replace("cas: 64-17-5", f"cas: {cas}"))
    scope = _scope()
    del scope["uncertainty"]
    scope["flows"][2] = {"key": "product:WATER", "emission": True, "source": "test"}
    scope["flows"] += [
        {
            "key": "emission:ETOH",
            "elementary": {"compartment": "air", "origin": origin},
            "source": "test",
        },
        {"key": "emission:H2O", "free": True, "source": "test"},
    ]
    _write(blocks, scope)


@pytest.mark.parametrize(("origin", "factor"), [("fossil", 29.8), ("biogenic", 27.0)])
def test_elementary_emissions_by_cas(blocks: Path, origin: str, factor: float) -> None:
    _emitting(blocks, origin)
    report = lca_report(blocks)
    assert report.loaded, [f.format() for f in report.findings]
    impact = next(i for i in report.impacts if i.key == "emission:ETOH")
    assert impact.factor == factor and impact.status == "PUBLISHED"
    assert impact.basis == f"ipcc2021-gwp100 (74-82-8, air, {origin})"
    assert impact.value == pytest.approx(600 * 0.0333333 * 2.5 * factor, rel=1e-5)


def test_elementary_problems(blocks: Path) -> None:
    _emitting(blocks, cas="64-17-5")  # ethanol: no factor in the method
    report = lca_report(blocks)
    assert any(f.rule == "cheme.lca-elementary-uncharacterised" for f in report.findings)
    factors = yaml.safe_load(yaml.safe_dump(FACTORS))
    factors["categories"][0].pop("elementary")
    (blocks / "lca" / "factors.yaml").write_text(yaml.safe_dump(factors))
    report = lca_report(blocks)
    assert not report.loaded
    assert any("names a packaged method" in f.message for f in report.findings)
    factors["categories"][0]["elementary"] = "nope-gwp"
    (blocks / "lca" / "factors.yaml").write_text(yaml.safe_dump(factors))
    assert any("unknown packaged methods" in f.message for f in lca_report(blocks).findings)


# -- review fixes -------------------------------------------------------------------------------


def test_degenerate_and_tied() -> None:
    from chemeascode.domains.assessment.lca.uncertainty import _ranks

    spec = Uncertainty(distribution="triangular", low=1, high=1)
    assert (sample(spec, 5, np.random.default_rng(1)) == 1).all()
    assert list(_ranks(np.array([3.0, 1.0, 3.0, 2.0]))) == [2.5, 0.0, 2.5, 1.0]


def test_reference_product_is_not_sampled(blocks: Path) -> None:
    scope = _scope()
    scope["uncertainty"]["defaults"] = {"given": {"gsd2": 1.2}, "assumed": {"gsd2": 1.2}}
    _write(blocks, scope)
    varied = lca_report(blocks).uncertainty.varied
    assert "amount:product:PROD" not in varied and "amount:feed:FEED" in varied
    # WATER is free: it cannot move the result
    assert "amount:product:WATER" not in varied


def test_cas_normalised_and_origin_ranked() -> None:
    from chemeascode.domains.assessment.lca.methods import factor, normalise_cas
    from chemeascode.integrations.brightway import _origin_rank

    assert normalise_cas(" 000124-38-9 ") == "124-38-9"
    assert factor("ipcc2021-gwp100", "000074-82-8", "air", "biogenic") == 27.0
    assert factor("ipcc2021-gwp20", "74-82-8", "air", "biogenic") == 79.7
    assert factor("ipcc2021-gwp100", "2551-62-4", "air", "fossil") == 25200.0
    fossil = ["Carbon dioxide, fossil", "Carbon dioxide (fossil)"]
    biogenic = ["Carbon dioxide, non-fossil", "carbon dioxide (biogenic)"]
    luc = "Carbon dioxide, from soil or biomass stock"  # land-use change (pre-release issue 175)
    assert all(_origin_rank(n, "fossil") == 0 for n in fossil)
    assert all(_origin_rank(n, "fossil") == 2 for n in [*biogenic, luc])
    assert all(_origin_rank(n, "biogenic") == 0 for n in biogenic)
    assert _origin_rank(luc, "biogenic") == 1 and _origin_rank(luc, "land-use-change") == 0
    assert factor("ipcc2021-gwp100", "124-38-9", "air", "land-use-change") == 1.0
    assert _origin_rank("Dinitrogen monoxide", "fossil") == 1


def test_elementary_in_an_unlinked_category_warns(blocks: Path) -> None:
    _emitting(blocks)
    factors = yaml.safe_load(yaml.safe_dump(FACTORS))
    factors["categories"].append({"id": "water", "unit": "m3"})
    for f in factors["factors"]:
        f["values"]["water"] = 0.0
    (blocks / "lca" / "factors.yaml").write_text(yaml.safe_dump(factors))
    report = lca_report(blocks)
    unlinked = [f for f in report.findings if f.rule == "cheme.lca-elementary-unlinked"]
    assert unlinked and "water" in unlinked[0].message
