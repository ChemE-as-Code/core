"""Tiered LCI generation: ``cheme assess lci-estimate`` builds a Tier 0
(stoichiometric) or Tier 1 (sourced conceptual) dataset from the reactions, a yield and the
versioned defaults, with the element balance mandatory and the tier capping maturity and DQR.

The validation against a full design uses ``examples/process-ammonia`` (the only example in
core whose flowsheet makes a pure product by reaction): a Tier 0 estimate of the same synthesis
against the loop's feeds and purge, per kg of NH3.
"""

import re
import shutil
import subprocess
import sys
from pathlib import Path

import pytest
import yaml
from pydantic import ValidationError
from typer.testing import CliRunner

from chemeascode.domains.assessment.flows import Terminal
from chemeascode.domains.assessment.lca.balance import element_balance
from chemeascode.domains.assessment.lca.estimate import (
    _Exchanges,
    compare_with_design,
    design_energy,
    estimate_yaml,
    lci_estimate,
    tier_defaults,
    tier_findings,
)
from chemeascode.domains.assessment.lca.quality import rating
from chemeascode.domains.assessment.lca.report import _Datasets, load_dataset
from chemeascode.domains.assessment.lca.schemas import Generation, LciDataset, LciEstimate
from chemeascode.domains.chemistry.formulas import molar_mass
from chemeascode.domains.process.screening_balance import (
    load_chemistry,
    stoichiometric_balance,
)
from chemeascode.interfaces.cli import app

EXAMPLES = Path(__file__).parents[1] / "examples"
TIER0 = {"schema": "cheme/lci_estimate/v1", "kind": "lci_estimate", "id": "nh3-t0", "tier": 0}
AMMONIA = {**TIER0, "product": "NH3", "reactions": ["NH3_SYN"], "location": "GLO", "year": 2026}


def _repo(tmp_path: Path, example: str, spec: dict) -> Path:
    root = tmp_path / example
    shutil.copytree(EXAMPLES / example, root)
    (root / "lca").mkdir(exist_ok=True)
    (root / "lca" / "estimate.yaml").write_text(yaml.safe_dump(spec, sort_keys=False))
    return root


def _exchange(dataset: LciDataset, key: str):
    return next(e for e in dataset.exchanges if e.key == key)


def test_tier0_ammonia_from_the_stoichiometry_and_the_defaults(tmp_path: Path) -> None:
    result = lci_estimate(_repo(tmp_path, "process-ammonia", AMMONIA))
    assert result.loaded, [f.format() for f in result.findings]
    dataset = result.dataset
    m_n2, m_h2, m_nh3 = molar_mass("N2"), molar_mass("H2"), molar_mass("NH3")
    # N2 + 3 H2 -> 2 NH3 at the default efficiency 0.95 (Hischier et al. 2005)
    n2 = _exchange(dataset, "feed:N2")
    assert n2.amount == pytest.approx(m_n2 / (2 * m_nh3) / 0.95)
    assert _exchange(dataset, "feed:H2").amount == pytest.approx(3 * m_h2 / (2 * m_nh3) / 0.95)
    # the unconverted 5 %: 0.2 % of the input to air, the rest to wastewater treatment
    assert _exchange(dataset, "emission:N2").amount == pytest.approx(0.002 * n2.amount)
    assert _exchange(dataset, "wastewater:N2").amount == pytest.approx(0.048 * n2.amount)
    assert _exchange(dataset, "input:electricity").amount == pytest.approx(0.3333)
    assert _exchange(dataset, "input:heat").amount == pytest.approx(0.5556)
    generation = dataset.generation
    assert generation.tier == 0 and generation.maturity_cap == "sourced"
    assert generation.defaults == f"cheme tier-defaults {tier_defaults().version}"
    assert set(generation.defaults_used) == {
        "yield",
        "loss-air",
        "loss-water",
        "loss-waste",
        "electricity",
        "heat",
    }
    assert generation.balance.closed and set(generation.balance.elements) == {"N", "H"}
    assert generation.dqr_floor == pytest.approx(10 / 3, abs=1e-3)
    # every exchange taking a default is assumed and cites its rule (and an unconfirmed one
    # says so)
    for exchange in dataset.exchanges:
        if exchange.pedigree.rule.startswith("cheme tier-defaults"):
            assert exchange.provenance == "assumed" and "cheme tier-defaults" in exchange.source
    assert "[ASSUMED]" in _exchange(dataset, "input:electricity").source
    assert dataset.system_boundary.infrastructure == "excluded"
    assert result.output == "lca/datasets/nh3-t0.yaml"
    assert tier_findings(dataset, result.output)[0].rule == "cheme.lci-tier"


def test_the_written_dataset_reloads_and_states_every_provenance(tmp_path: Path) -> None:
    root = _repo(tmp_path, "process-ammonia", AMMONIA)
    result = lci_estimate(root)
    text = estimate_yaml(result)
    assert text.startswith("# A Tier 0 LCI estimate")
    data = yaml.safe_load(text)
    assert all("provenance" in e for e in data["exchanges"])
    assert list(data)[:8] == [
        "schema",
        "kind",
        "id",
        "title",
        "description",
        "scope",
        "basis",
        "generation",
    ]
    (root / result.output).parent.mkdir(parents=True, exist_ok=True)
    (root / result.output).write_text(text)
    loaded = load_dataset(root, result.output)
    assert isinstance(loaded, LciDataset)
    assert loaded.model_dump() == result.dataset.model_dump()


def test_tier0_against_the_ammonia_design(tmp_path: Path) -> None:
    """The validation study: Tier 0 against the full design (the loop of process-ammonia).

    Reactants fed: -5.2 % (the design loses 9.9 % of its makeup N2 and H2 in the purge, the
    Tier 0 default 5 %); the unconverted input that leaves: -52 %. The design has no energy
    terminals, so electricity and heat are not compared; argon (an inert) is not estimated."""
    spec = {**AMMONIA, "losses": {"fate": {"N2": "air", "H2": "air"}, "reason": "purged gas"}}
    root = _repo(tmp_path, "process-ammonia", spec)
    result = lci_estimate(root)
    assert "Gendorf 2000" in result.dataset.description  # the dated energy defaults say so
    comparison = compare_with_design(result.dataset, root)
    errors = {d.quantity: d.error for d in comparison.deviations}
    assert errors["feed:N2"] == pytest.approx(-0.052, abs=0.002)
    assert errors["feed:H2"] == pytest.approx(-0.052, abs=0.002)
    assert errors["loss:N2"] == pytest.approx(-0.522, abs=0.005)
    assert errors["loss:H2"] == pytest.approx(-0.522, abs=0.005)
    low, high = comparison.error_range()
    assert -0.53 < low < -0.51 and -0.06 < high < -0.04
    assert any("AR" in n for n in comparison.notes)
    assert any("no energy terminals" in n for n in comparison.notes)


def _energy(key: str, direction: str, kwh_per_hour: float, title: str = "") -> Terminal:
    return Terminal(key, title or key, direction, per_hour=kwh_per_hour)


def test_the_energy_comparison_counts_only_supplies_of_electricity_and_heat() -> None:
    """A synthetic design (the only example has no energy terminals): inputs named electricity
    or power, steam or heat are summed; heat rejection, cooling, exported power and unnamed
    carriers are listed as not compared, never added to the consumption."""
    terminals_ = [
        _energy("feed:grid", "input", 200.0, "Grid electricity"),
        _energy("feed:compressor_power", "input", 100.0),
        _energy("feed:lp_steam", "input", 500.0),
        _energy("feed:fired_heater", "input", 300.0, "Fired heat"),
        _energy("feed:cooling_water", "input", 900.0, "Cooling duty"),
        _energy("product:heat_rejection", "output", 700.0),
        _energy("product:exported_electricity", "output", 50.0),
        _energy("feed:mystery", "input", 10.0),
    ]
    supplied, other = design_energy(terminals_, made=100.0)
    assert supplied == {"input:electricity": pytest.approx(3.0), "input:heat": pytest.approx(8.0)}
    assert set(other) == {
        "feed:cooling_water",
        "product:heat_rejection",
        "product:exported_electricity",
        "feed:mystery",
    }
    assert other["feed:cooling_water"] == pytest.approx(9.0)


EO_MATERIALS = """schema: cheme/process/v1
kind: materials
components:
  - {id: C2H4, name: Ethylene, formula: C2H4, cas: 74-85-1}
  - {id: O2, name: Oxygen, formula: O2, cas: 7782-44-7}
  - {id: EO, name: Ethylene oxide, formula: C2H4O, cas: 75-21-8}
  - {id: CO2, name: Carbon dioxide, formula: CO2, cas: 124-38-9}
  - {id: H2O, name: Water, formula: H2O, cas: 7732-18-5}
"""
EO_REACTIONS = """schema: cheme/reactions/v1
kind: reactions
reactions:
  - {id: EPOX, stoichiometry: {C2H4: -1, O2: -0.5, EO: 1}}
  - {id: BURN, stoichiometry: {C2H4: -1, O2: -3, CO2: 2, H2O: 2}}
"""
EO = {
    **TIER0,
    "id": "eo-t0",
    "product": "EO",
    "reactions": ["EPOX", "BURN"],
    "key": "C2H4",
    "selectivity": {"EO": 0.8, "CO2": 0.4},
    "origin": "fossil",
}


def _eo_repo(tmp_path: Path, spec: dict, reactions: str = EO_REACTIONS) -> Path:
    root = tmp_path / "eo"
    (root / "process").mkdir(parents=True)
    (root / "lca").mkdir()
    shutil.copy(EXAMPLES / "reaction-evidence-ethyl-acetate" / "plant.yaml", root / "plant.yaml")
    (root / "process" / "materials.yaml").write_text(EO_MATERIALS)
    (root / "process" / "reactions.yaml").write_text(reactions)
    (root / "lca" / "estimate.yaml").write_text(yaml.safe_dump(spec, sort_keys=False))
    return root


def test_several_reactions_by_selectivity_need_every_byproducts_fate(tmp_path: Path) -> None:
    result = lci_estimate(_eo_repo(tmp_path, EO))
    assert not result.loaded
    (finding,) = [f for f in result.findings if f.level == "error"]
    assert finding.rule == "cheme.lci-estimate" and "CO2" in finding.message
    spec = {**EO, "byproducts": {"CO2": {"fate": "air"}, "H2O": {"fate": "wastewater"}}}
    result = lci_estimate(_eo_repo(tmp_path / "2", spec))
    assert result.loaded, [f.format() for f in result.findings]
    dataset = result.dataset
    # 1 kmol C2H4 converted: 0.8 EO, 0.2 burnt to 0.4 CO2 and 0.4 H2O
    m_eo = molar_mass("C2H4O")
    assert _exchange(dataset, "feed:C2H4").amount == pytest.approx(
        molar_mass("C2H4") / (0.8 * m_eo) / 0.95
    )
    assert _exchange(dataset, "emission:CO2").amount == pytest.approx(
        0.4 * molar_mass("CO2") / (0.8 * m_eo)
    )
    # no selectivity_source: what follows from the selectivities is assumed, not calculated
    assert _exchange(dataset, "emission:CO2").provenance == "assumed"
    assert _exchange(dataset, "feed:C2H4").provenance == "assumed"
    assert _exchange(dataset, "emission:CO2").link.elementary.origin == "fossil"
    sourced = {**spec, "selectivity_source": {"source": "test source, table 4"}}
    dataset = lci_estimate(_eo_repo(tmp_path / "3", sourced)).dataset
    assert _exchange(dataset, "emission:CO2").provenance == "calculated"
    assert "test source, table 4" in _exchange(dataset, "emission:CO2").source
    assert set(dataset.generation.balance.elements) == {"C", "H", "O"}
    assert element_balance(dataset).closed


def test_an_unbalanced_reaction_is_refused(tmp_path: Path) -> None:
    wrong = EO_REACTIONS.replace("{C2H4: -1, O2: -0.5, EO: 1}", "{C2H4: -1, O2: -1, EO: 1}")
    spec = {**EO, "byproducts": {"CO2": {"fate": "air"}, "H2O": {"fate": "wastewater"}}}
    result = lci_estimate(_eo_repo(tmp_path, spec, wrong))
    assert result.dataset is None
    assert [f.rule for f in result.findings if f.level == "error"] == ["cheme.lci-unbalanced"]
    assert "O in" in result.findings[-1].message


def test_tier1_takes_yield_and_energy_from_sources(tmp_path: Path) -> None:
    with pytest.raises(ValidationError, match="Tier 1 estimate takes yield, electricity, heat"):
        LciEstimate.model_validate({**AMMONIA, "tier": 1})
    spec = {
        **AMMONIA,
        "tier": 1,
        "yield": {"value": 0.98, "source": "test source, table 1"},
        "electricity": {"value": 0.1, "source": "test source, table 2"},
        "heat": {"value": 0.0, "source": "test source, table 2"},
        "exchanges": [
            {
                "key": "input:catalyst",
                "type": "input",
                "amount": 1e-5,
                "unit": "kg",
                "source": "test source, p. 3",
            }
        ],
    }
    result = lci_estimate(_repo(tmp_path, "process-ammonia", spec))
    assert result.loaded, [f.format() for f in result.findings]
    dataset = result.dataset
    assert _exchange(dataset, "feed:N2").provenance == "calculated"
    assert _exchange(dataset, "input:electricity").provenance == "given"
    assert _exchange(dataset, "input:catalyst").origin == "literature"
    assert dataset.generation.defaults_used == ["loss-air", "loss-water", "loss-waste"]
    assert dataset.generation.pedigree_floor == list(tier_defaults().floors[1])
    # the catalyst has no component: its mass is outside the balance, and the finding says so
    outside = [f for f in result.findings if f.rule == "cheme.lci-mass-outside-balance"]
    assert len(outside) == 1 and "input:catalyst" in outside[0].message
    assert outside[0].level == "warning"
    assert "Gendorf" not in dataset.description


def test_the_tier_caps_maturity_and_records_its_balance() -> None:
    base = {"tier": 0, "method": "stoichiometric", "balance": {"closed": True, "tolerance": 1e-6}}
    assert Generation.model_validate({**base, "maturity_cap": "sourced"}).tier == 0
    with pytest.raises(ValidationError, match="supports calculation maturity 'sourced' at most"):
        Generation.model_validate({**base, "maturity_cap": "balanced"})
    with pytest.raises(ValidationError, match="records its element balance"):
        Generation.model_validate({"tier": 0, "method": "stoichiometric"})
    # Tier 2 and up is the flowsheet path: no cap
    assert Generation.model_validate({"tier": 2, "method": "flowsheet"}).balance is None


def test_tier_findings_catch_edits_that_break_the_tier(tmp_path: Path) -> None:
    root = _repo(tmp_path, "process-ammonia", AMMONIA)
    dataset = lci_estimate(root).dataset

    def edited(key: str, **update) -> LciDataset:
        exchanges = [e.model_copy(update=update) if e.key == key else e for e in dataset.exchanges]
        return dataset.model_copy(update={"exchanges": exchanges})

    def rules(d: LciDataset, maturity: str | None = None) -> list[str]:
        return [f.rule for f in tier_findings(d, "x.yaml", maturity) if f.level == "error"]

    assert rules(dataset) == []
    assert rules(edited("feed:N2", amount=0.5)) == ["cheme.lci-unbalanced"]
    assert rules(edited("input:heat", provenance="given")) == ["cheme.lci-default-not-assumed"]
    better = _exchange(dataset, "input:heat").pedigree.model_copy(update={"scores": [1] * 5})
    assert rules(edited("input:heat", pedigree=better)) == ["cheme.lci-tier-quality"]
    assert rules(dataset, "concept") == []
    assert rules(dataset, "screening") == ["cheme.lci-tier-maturity"]


def test_the_default_pedigree_and_the_rating_respect_the_floor(tmp_path: Path) -> None:
    dataset = lci_estimate(_repo(tmp_path, "process-ammonia", AMMONIA)).dataset
    floor = dataset.generation.pedigree_floor
    for exchange in dataset.exchanges:
        assert all(s >= f for s, f in zip(exchange.pedigree.scores, floor, strict=True))
    assert rating(dataset).dqr >= dataset.generation.dqr_floor


def test_a_study_reading_the_estimate_is_told_its_tier(tmp_path: Path) -> None:
    root = _repo(tmp_path, "process-ammonia", AMMONIA)
    result = lci_estimate(root)
    (root / result.output).parent.mkdir(parents=True, exist_ok=True)
    (root / result.output).write_text(estimate_yaml(result))
    (root / "process.yaml").write_text("maturity: screening\n")
    # with a flowsheet the manifest's maturity rests on the design: a screening dataset the
    # study reads as a background does not cap it
    datasets = _Datasets(root, run=None)
    assert isinstance(datasets.load(result.output), LciDataset)
    rules = [f.rule for f in datasets.findings]
    assert "cheme.lci-tier" in rules and "cheme.lci-tier-maturity" not in rules
    # without one the manifest describes the process by its datasets: the tier caps it
    (root / "process" / "flowsheet.yaml").unlink()
    datasets = _Datasets(root, run=None)
    datasets.load(result.output)
    assert "cheme.lci-tier-maturity" in [f.rule for f in datasets.findings]


def test_the_estimate_checks_the_manifest_maturity_of_a_process_without_a_flowsheet(
    tmp_path: Path,
) -> None:
    root = _repo(tmp_path, "process-ammonia", AMMONIA)
    (root / "process.yaml").write_text("maturity: screening\n")
    assert "cheme.lci-tier-maturity" not in [f.rule for f in lci_estimate(root).findings]
    (root / "process" / "flowsheet.yaml").unlink()
    result = lci_estimate(root)
    assert "cheme.lci-tier-maturity" in [f.rule for f in result.findings]
    assert not result.loaded
    (root / "process.yaml").write_text("maturity: concept\n")
    assert lci_estimate(root).loaded


def test_a_fate_for_a_component_the_scheme_does_not_have_is_refused(tmp_path: Path) -> None:
    losses = {"fate": {"N3": "air"}, "reason": "purged gas"}
    result = lci_estimate(_repo(tmp_path, "process-ammonia", {**AMMONIA, "losses": losses}))
    assert not result.loaded
    assert any(f.rule == "cheme.lci-estimate" and "N3" in f.message for f in result.findings)
    stale = {**AMMONIA, "byproducts": {"H2O": {"fate": "wastewater"}}}
    result = lci_estimate(_repo(tmp_path / "2", "process-ammonia", stale))
    assert not result.loaded
    assert any(f.rule == "cheme.lci-estimate" and "H2O" in f.message for f in result.findings)


def test_the_defaults_are_sourced_and_versioned() -> None:
    defaults = tier_defaults()
    assert re.fullmatch(r"\d+\.\d+\.\d+", defaults.version)
    for entry in defaults.values.values():
        assert entry.status in ("confirmed", "ASSUMED") and len(entry.source) > 20
        assert len(entry.pedigree) == 5
    values = defaults.values
    assert (values["yield"].value, values["yield"].status) == (0.95, "confirmed")
    assert (values["loss-air"].value, values["loss-air"].status) == (0.002, "confirmed")
    # 1.2 MJ electricity and 2 MJ heat per kg: not confirmed in an open copy, so ASSUMED
    assert values["electricity"].status == values["heat"].status == "ASSUMED"
    assert not values["infrastructure"].apply


def test_balance_of_one_reaction_needs_no_selectivity() -> None:
    from chemeascode.domains.chemistry.reactions import Reaction

    reaction = Reaction(id="R", stoichiometry={"N2": -1, "H2": -3, "NH3": 2})
    balance = stoichiometric_balance([reaction], {"N2": "N2", "H2": "H2", "NH3": "NH3"}, "NH3", 1.0)
    assert sum(balance.fed.values()) == pytest.approx(1.0)
    assert balance.unconverted == {"H2": 0.0, "N2": 0.0}
    with pytest.raises(ValueError, match="do not form"):
        stoichiometric_balance([reaction], {"N2": "N2", "H2": "H2", "NH3": "NH3"}, "N2", 1.0)


def test_cli_writes_checks_and_compares(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    root = _repo(tmp_path, "process-ammonia", AMMONIA)
    monkeypatch.chdir(root / "process")  # any directory of the repository
    runner = CliRunner()
    check = runner.invoke(app, ["assess", "lci-estimate", "--check"])
    assert check.exit_code == 1
    written = runner.invoke(app, ["assess", "lci-estimate", "--write"])
    assert written.exit_code == 0, written.output
    assert (root / "lca/datasets/nh3-t0.yaml").read_text() == estimate_yaml(lci_estimate(root))
    assert runner.invoke(app, ["assess", "lci-estimate", "--check"]).exit_code == 0
    compared = runner.invoke(app, ["assess", "lci-estimate", "--compare"])
    assert compared.exit_code == 0
    assert re.search(r"feed:N2\s+0\.86573\s+0\.91304\s+-5\.2%", compared.stdout)


def test_imports_without_cli() -> None:
    code = (
        "import sys; import chemeascode.domains.assessment.lca.estimate; "
        "assert 'typer' not in sys.modules and 'fastapi' not in sys.modules"
    )
    subprocess.run([sys.executable, "-c", code], check=True)


def test_tier1_with_several_reactions_needs_a_selectivity_source() -> None:
    tier1 = {
        **EO,
        "tier": 1,
        "yield": {"value": 0.9, "source": "src1"},
        "electricity": {"value": 0.1, "source": "src2"},
        "heat": {"value": 0.2, "source": "src3"},
    }
    with pytest.raises(ValidationError, match="selectivity_source"):
        LciEstimate.model_validate(tier1)
    LciEstimate.model_validate({**tier1, "selectivity_source": {"source": "src4, table 1"}})


def test_unsourced_selectivity_with_a_given_yield_is_assumed(tmp_path: Path) -> None:
    spec = {
        **EO,
        "yield": {"value": 0.9, "source": "test source"},
        "byproducts": {"CO2": {"fate": "air"}, "H2O": {"fate": "wastewater"}},
    }
    dataset = lci_estimate(_eo_repo(tmp_path, spec)).dataset
    feed = _exchange(dataset, "feed:C2H4")
    assert feed.provenance == "assumed" and "selectivit" in feed.source
    assert "test source" in feed.source


def test_ranges_are_checked() -> None:
    cases = [
        ({"electricity": {"value": -1, "source": "src"}}, "electricity must not be negative"),
        ({"heat": {"value": -0.1, "source": "src"}}, "heat must not be negative"),
        ({"losses": {"air": {"value": 1.5, "source": "src"}}}, "fraction in \\[0, 1\\]"),
        ({"losses": {"air": {"value": -0.1, "source": "src"}}}, "fraction in \\[0, 1\\]"),
        ({**EO, "selectivity": {"EO": -0.8, "CO2": 0.4}}, "greater than or equal to 0"),
    ]
    for extra, message in cases:
        base = AMMONIA if "selectivity" not in extra else {}
        with pytest.raises(ValidationError, match=message):
            LciEstimate.model_validate({**base, **extra})
    LciEstimate.model_validate({**AMMONIA, "losses": {"air": {"value": 0, "source": "src"}}})


def test_the_default_split_warns_for_a_gas_and_stays_quiet_when_the_fate_is_given(
    tmp_path: Path,
) -> None:
    result = lci_estimate(_repo(tmp_path, "process-ammonia", AMMONIA))
    warnings = [f for f in result.findings if f.rule == "cheme.lci-loss-split"]
    assert {w.ids[0] for w in warnings} == {"N2", "H2"}
    assert all(w.level == "warning" and "losses.fate" in w.hint for w in warnings)
    assert "gas" in warnings[0].message and result.loaded
    fates = {"fate": {"N2": "air", "H2": "air"}, "reason": "purged gas"}
    result = lci_estimate(_repo(tmp_path / "2", "process-ammonia", {**AMMONIA, "losses": fates}))
    assert not [f for f in result.findings if f.rule == "cheme.lci-loss-split"]
    stated = {**AMMONIA, "losses": {"water": "wastewater"}}
    result = lci_estimate(_repo(tmp_path / "3", "process-ammonia", stated))
    assert not [f for f in result.findings if f.rule == "cheme.lci-loss-split"]


def test_a_liquid_by_the_default_split_does_not_warn(tmp_path: Path) -> None:
    root = _repo(tmp_path, "process-ammonia", AMMONIA)
    path = root / "process" / "materials.yaml"
    data = yaml.safe_load(path.read_text())
    for component in data["components"]:
        component["normal_boiling_point"] = 400.0
    path.write_text(yaml.safe_dump(data))
    result = lci_estimate(root)
    assert not [f for f in result.findings if f.rule == "cheme.lci-loss-split"]
    for component in data["components"]:
        component.pop("normal_boiling_point")
    path.write_text(yaml.safe_dump(data))
    unknown = [f for f in lci_estimate(root).findings if f.rule == "cheme.lci-loss-split"]
    assert unknown and "unknown volatility" in unknown[0].message


def test_the_heat_is_a_heat_flow_from_fossil_fuel(tmp_path: Path) -> None:
    dataset = lci_estimate(_repo(tmp_path, "process-ammonia", AMMONIA)).dataset
    heat = _exchange(dataset, "input:heat")
    assert heat.unit == "kWh" and heat.carrier.kind == "heat"
    assert "fossil fuel" in heat.title and "fossil fuel" in heat.carrier.source
    assert _exchange(dataset, "input:electricity").carrier.kind == "electricity"


def test_the_defaults_record_the_transport_distances_and_the_pages() -> None:
    values = tier_defaults().values
    assert (values["transport-lorry"].value, values["transport-lorry"].unit) == (100, "km")
    assert (values["transport-train"].value, values["transport-train"].unit) == (600, "km")
    assert not values["transport-lorry"].apply and not values["transport-train"].apply
    text = EXAMPLES.parent / "src/chemeascode/domains/assessment/lca/data/tier-defaults.yaml"
    raw = yaml.safe_load(text.read_text())["defaults"]
    assert "p. 60" in raw["transport-lorry"]["checked"]
    for name in ("yield", "loss-air", "loss-water", "loss-waste", "infrastructure"):
        assert raw[name]["checked"].endswith("p. 61")


def test_a_merged_exchange_keeps_the_source_id_both_agree_on(tmp_path: Path) -> None:
    root = _repo(tmp_path, "process-ammonia", AMMONIA)
    dataset = lci_estimate(root).dataset
    built = _Exchanges(load_chemistry(root), "fossil")
    base = _exchange(dataset, "feed:N2")
    built.add(base.model_copy(update={"source_id": "a"}))
    built.add(base.model_copy(update={"source_id": "a"}))
    assert built.items[base.key].source_id == "a"
    built.add(base.model_copy(update={"source_id": "b"}))
    assert built.items[base.key].source_id is None


def test_the_tier_info_is_for_tiers_0_and_1_only(tmp_path: Path) -> None:
    dataset = lci_estimate(_repo(tmp_path, "process-ammonia", AMMONIA)).dataset
    flow = dataset.generation.model_copy(update={"tier": 2})
    tier2 = dataset.model_copy(update={"generation": flow})
    assert "cheme.lci-tier" not in [f.rule for f in tier_findings(tier2, "x.yaml")]
