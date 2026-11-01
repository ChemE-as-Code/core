"""Catalysts (process/catalysts.yaml), rate laws (power law, LHHW), the catalyst rules of the
flowsheet, rates in cheme process reactors and cheme chemistry kinetics."""

import math
import shutil
from pathlib import Path

import pytest
from typer.testing import CliRunner

from chemeascode.domains.chemistry.catalysts import Catalysts
from chemeascode.domains.chemistry.catalysts import rules as catalyst_rules
from chemeascode.domains.chemistry.kinetics.records import FilteredKinetics
from chemeascode.domains.chemistry.rates import RateLaw, driving_forces, rate, rate_law_from_record
from chemeascode.domains.chemistry.reactions import Reactions
from chemeascode.domains.chemistry.reactions import rules as reaction_rules
from chemeascode.domains.process.model import load, rules
from chemeascode.domains.process.reactors import reactor_report
from chemeascode.interfaces.cli import app

EXAMPLES = Path(__file__).resolve().parents[1] / "examples"
WGS = {"CO": -1, "H2O": -1, "CO2": 1, "H2": 1}


def _law(**kw):
    base = {
        "form": "power_law",
        "basis": "catalyst_mass",
        "driving": "partial_pressure",
        "k": {"A": 2.0, "Ea": 50000.0},
        "orders": {"CO": 1, "H2O": 0.5},
        "provenance": "assumed",
    }
    return RateLaw.model_validate(base | kw)


# -- rate laws ----------------------------------------------------------------------------------


def test_power_law():
    law = _law()
    y = {"CO": 0.1, "H2O": 0.4, "CO2": 0.0, "H2": 0.0}
    t, p = 600.0, 2000.0  # 20 bar: p_CO 2 bar, p_H2O 8 bar
    expected = 2.0 * math.exp(-50000.0 / (8.314462618 * t)) * 2.0 * 8.0**0.5
    assert rate(law, WGS, y, t, p) == pytest.approx(expected)


def test_lhhw_divides_by_the_adsorption_terms():
    law = _law(
        form="lhhw",
        adsorption=[
            {"A": 0.5, "exponents": {"CO": 1}},
            {"A": 0.1, "dH": -20000, "exponents": {"H2O": 1}},
        ],
        power=2,
    )
    y = {"CO": 0.1, "H2O": 0.4}
    t, p = 600.0, 2000.0
    k = 2.0 * math.exp(-50000.0 / (8.314462618 * t)) * 2.0 * 8.0**0.5
    denominator = 1 + 0.5 * 2.0 + 0.1 * math.exp(20000 / (8.314462618 * t)) * 8.0
    assert rate(law, WGS, y, t, p) == pytest.approx(k / denominator**2)


def test_reverse_by_equilibrium_is_zero_at_equilibrium():
    law = _law(reverse="equilibrium")
    y = {"CO": 0.1, "H2O": 0.1, "CO2": 0.2, "H2": 0.2}
    ln_q = math.log(0.2 * 0.2 / (0.1 * 0.1))
    assert rate(law, WGS, y, 600.0, 2000.0, ln_q) == pytest.approx(0.0, abs=1e-15)
    assert rate(law, WGS, y, 600.0, 2000.0, ln_q + 1) > 0  # short of equilibrium: forward
    assert rate(law, WGS, y, 600.0, 2000.0, ln_q - 1) < 0  # past it: backward
    with pytest.raises(ValueError, match="equilibrium constant"):
        rate(law, WGS, y, 600.0, 2000.0)


def test_concentrations_are_ideal_gas():
    law = _law(driving="concentration")
    c = driving_forces(law, {"CO": 1.0}, 500.0, 831.4462618)
    assert c["CO"] == pytest.approx(0.2)  # P / (R T) = 831.45 / (8.3145 * 500) kmol/m3


@pytest.mark.parametrize(
    ("change", "message"),
    [
        ({"adsorption": [{"A": 1.0}]}, "no adsorption terms"),
        ({"form": "lhhw"}, "needs adsorption terms"),
        ({"temperature_range": (700, 600)}, "min < max"),
    ],
)
def test_rate_law_schema(change, message):
    with pytest.raises(ValueError, match=message):
        _law(**change)


def test_rate_law_from_a_record_converts_si_moles_to_kmol():
    record = FilteredKinetics(
        reaction="CH4 + OH = CH3 + H2O",
        reactants=["C", "[OH]"],
        products=["[CH3]", "O"],
        A=1.0e-12 * 6.02214076e23 * 1e-6,  # cm3/(molecule s) -> m3/(mol s)
        A_units="m^3/(mol*s)",
        n=2.0,
        Ea=10000.0,
        T_min=250.0,
        T_max=2000.0,
        confidence="HIGH",
        data_type="Experiment",
    )
    law = rate_law_from_record(record, {"C": "CH4", "[OH]": "OH"})
    assert law.orders == {"CH4": 1.0, "OH": 1.0}
    assert pytest.approx(record.A * 1000.0) == law.k.A  # second order: m3/(kmol s)
    assert (law.k.Ea, law.k.n, law.k.T_ref) == (10000.0, 2.0, 1.0)
    assert law.temperature_range == (250.0, 2000.0)
    assert law.basis == "volume" and law.driving == "concentration"
    assert "HIGH confidence" in law.source
    with pytest.raises(ValueError, match="no component id"):
        rate_law_from_record(record, {"C": "CH4"})


def test_rate_rules_in_reactions():
    reactions = Reactions.model_validate(
        {
            "schema": "cheme/reactions/v1",
            "kind": "reactions",
            "reactions": [
                {
                    "id": "R1",
                    "stoichiometry": WGS,
                    "rate": {
                        "form": "power_law",
                        "basis": "catalyst_mass",
                        "driving": "partial_pressure",
                        "k": {"A": 1.0},
                        "orders": {"CO": 1, "XX": 1},
                        "reverse": "equilibrium",
                        "provenance": "assumed",
                    },
                }
            ],
        }
    )
    formulas = {"CO": "CO", "H2O": "H2O", "CO2": "CO2", "H2": "H2"}
    found = {(f.rule, f.level) for f in reaction_rules(reactions, None, formulas)}
    assert ("cheme.reaction-rate", "error") in found  # XX is no component
    assert ("cheme.reaction-rate", "warning") in found  # reverse, but irreversible


# -- catalysts ----------------------------------------------------------------------------------


def _catalysts(**physical):
    return Catalysts.model_validate(
        {
            "schema": "cheme/catalysts/v1",
            "kind": "catalysts",
            "catalysts": [
                {
                    "id": "C1",
                    "active_phase": "Cu/ZnO",
                    "physical": {"provenance": "assumed", **physical},
                    "poisons": ["H2S", "chlorides"],
                },
                {"id": "C1", "active_phase": "Ni"},
            ],
        }
    )


def test_catalyst_rules():
    found = catalyst_rules(
        _catalysts(bulk_density=1300, particle_density=2000, bed_voidage=0.5), None, ["H2S"]
    )
    rules_found = {(f.rule, f.level) for f in found}
    assert ("cheme.catalyst-duplicate-id", "error") in rules_found
    assert ("cheme.catalyst-voidage", "warning") in rules_found  # 1 - 1300/2000 = 0.35
    assert [f.message for f in found if f.rule == "cheme.catalyst-poison"] == [
        "catalyst C1: poison chlorides is no declared component; it is not checked against the "
        "feeds"
    ]
    dense = catalyst_rules(_catalysts(bulk_density=2000, particle_density=1500), None, [])
    assert any(f.rule == "cheme.catalyst-density" for f in dense)


def test_catalyst_schema():
    with pytest.raises(ValueError, match="min < max"):
        Catalysts.model_validate(
            {
                "schema": "cheme/catalysts/v1",
                "kind": "catalysts",
                "catalysts": [
                    {
                        "id": "C",
                        "active_phase": "Ni",
                        "window": {"temperature": [900, 600], "provenance": "assumed"},
                    }
                ],
            }
        )
    with pytest.raises(ValueError, match="not supported"):
        Catalysts.model_validate({"schema": "cheme/catalysts/v2", "kind": "catalysts"})


# -- the flowsheet ------------------------------------------------------------------------------


@pytest.fixture
def ammonia(tmp_path):
    root = tmp_path / "nh3"
    shutil.copytree(EXAMPLES / "process-ammonia", root, ignore=shutil.ignore_patterns("build"))
    return root


def _rules(root):
    process, found = load(root)
    assert process is not None, [f.format() for f in found]
    return found + rules(process)


def test_the_example_converter_is_inside_its_catalyst_window(ammonia):
    assert not [f for f in _rules(ammonia) if f.rule == "cheme.process-catalyst"]


def test_unknown_catalyst(ammonia):
    path = ammonia / "process/flowsheet.yaml"
    path.write_text(path.read_text().replace("catalyst: FE_NH3", "catalyst: NOPE"))
    found = [f for f in _rules(ammonia) if f.rule == "cheme.process-catalyst"]
    assert found and found[0].level == "error" and "NOPE" in found[0].message
    (ammonia / "process/catalysts.yaml").unlink()
    found = [f for f in _rules(ammonia) if f.rule == "cheme.process-catalyst"]
    assert found and "does not exist" in found[0].message


def test_catalyst_window_and_poisons(ammonia):
    path = ammonia / "process/flowsheet.yaml"
    path.write_text(
        path.read_text().replace(
            "value: 743.15, provenance: assumed", "value: 843.15, provenance: assumed"
        )
    )
    cats = ammonia / "process/catalysts.yaml"
    cats.write_text(cats.read_text().replace("poisons: [H2O,", "poisons: [AR, H2O,"))
    found = [f for f in _rules(ammonia) if f.rule == "cheme.process-catalyst"]
    assert any("outside catalyst FE_NH3's temperature window" in f.message for f in found)
    assert any("carries AR, a poison" in f.message for f in found)
    assert {f.level for f in found} == {"warning"}


def test_rate_measured_on_another_catalyst(ammonia):
    reactions = ammonia / "process/reactions.yaml"
    reactions.write_text(
        reactions.read_text()
        + "    rate: {form: power_law, basis: catalyst_mass, driving: partial_pressure,\n"
        "           k: {A: 1.0e-3, Ea: 1.5e5}, orders: {N2: 1}, reverse: equilibrium,\n"
        "           catalyst: RU_NH3, provenance: assumed}\n"
    )
    found = [f for f in _rules(ammonia) if f.rule == "cheme.process-catalyst"]
    assert any("measured on RU_NH3" in f.message for f in found)
    report = reactor_report(ammonia)
    r1 = next(r for r in report.reactors if r["node"] == "R1")
    entry = r1["reactions"][0]
    assert entry["rate_unit"] == "kmol/(kg s)"
    assert entry["rate"] == pytest.approx(0.0, abs=1e-6)  # the outlet is at equilibrium


def test_catalysts_file_schema_error_has_a_line(ammonia):
    cats = ammonia / "process/catalysts.yaml"
    cats.write_text(cats.read_text().replace("active_phase:", "active_phaze:"))
    found = [f for f in _rules(ammonia) if f.rule == "cheme.catalyst-schema"]
    assert found and found[0].file == "process/catalysts.yaml" and found[0].line


# -- cheme chemistry kinetics -------------------------------------------------------------------


def test_kinetics_cli(monkeypatch):
    import chemeascode.domains.chemistry.kinetics.filter as filtering
    import chemeascode.domains.chemistry.kinetics.identification as identification
    import chemeascode.domains.chemistry.kinetics.retrieval as retrieval

    record = FilteredKinetics(
        reaction="CH4 + OH = CH3 + H2O",
        reactants=["C", "[OH]"],
        products=["[CH3]", "O"],
        A=6.0e5,
        n=2.0,
        Ea=10000.0,
        confidence="HIGH",
        data_type="Experiment",
    )
    smiles = {"methane": "C", "[OH]": "[OH]"}
    monkeypatch.setattr(identification, "resolve_smiles", lambda names: [smiles[n] for n in names])
    monkeypatch.setattr(
        retrieval, "retrieve_kinetics", lambda *a, **k: retrieval.KineticsRetrieval()
    )
    monkeypatch.setattr(filtering, "filter_kinetics", lambda *a, **k: record)
    shown = CliRunner().invoke(app, ["chemistry", "kinetics", "-r", "CH4=methane", "-r", "OH=[OH]"])
    assert shown.exit_code == 0, shown.output
    assert "rate:" in shown.output and '"form": "power_law"' not in shown.output
    assert 'form: "power_law"' in shown.output and '"CH4": 1.0' in shown.output
    bad = CliRunner().invoke(app, ["chemistry", "kinetics", "-r", "methane"])
    assert bad.exit_code == 2


# -- review fixes -------------------------------------------------------------------------------


def test_absent_species_with_negative_orders_or_as_a_reactant_are_refused():
    inhibited = _law(orders={"CO": 1, "CO2": -1})
    with pytest.raises(ValueError, match="CO2 is absent"):
        rate(inhibited, WGS, {"CO": 0.1, "H2O": 0.4}, 600.0, 2000.0)
    zero_order = _law(orders={"CO": 1}, reverse="equilibrium")
    with pytest.raises(ValueError, match="reactant H2O absent"):
        rate(zero_order, WGS, {"CO": 0.1, "CO2": 0.1, "H2": 0.1}, 600.0, 2000.0, 0.0)


def test_a_self_reaction_counts_its_reactant_twice():
    record = FilteredKinetics(
        reaction="OH + OH = H2O + O",
        reactants=["[OH]", "[OH]"],
        products=["O", "[O]"],
        A=1.0e6,
        order=2,
    )
    law = rate_law_from_record(record, {"[OH]": "OH"})
    assert law.orders == {"OH": 2.0}
    canonical = rate_law_from_record(record, {"CANON": "OH"}, canonical=lambda s: "CANON")
    assert canonical.orders == {"OH": 2.0}


def test_rate_with_an_approach_is_at_the_outlet_temperature(ammonia):
    reactions = ammonia / "process/reactions.yaml"
    reactions.write_text(
        reactions.read_text()
        + "    rate: {form: power_law, basis: catalyst_mass, driving: partial_pressure,\n"
        "           k: {A: 1.0e-3, Ea: 1.5e5}, orders: {N2: 1}, reverse: equilibrium,\n"
        "           provenance: assumed}\n"
    )
    r1 = next(r for r in reactor_report(ammonia).reactors if r["node"] == "R1")
    # at equilibrium at T + 20 K, short of it at T (exothermic): the rate is positive
    assert r1["reactions"][0]["rate"] > 0


def test_a_catalysts_typo_does_not_stop_the_process(ammonia):
    cats = ammonia / "process/catalysts.yaml"
    cats.write_text(cats.read_text().replace("bed_voidage: 0.42", "bed_voidage: 1.2"))
    process, found = load(ammonia)
    assert process is not None and not [f for f in found if f.level == "error"]
    assert any(f.rule == "cheme.catalyst-schema" for f in rules(process))


def test_a_block_catalyst_checks_the_block_boundary_in_every_case(ammonia):
    path = ammonia / "process/flowsheet.yaml"
    text = path.read_text().replace("    catalyst: FE_NH3\n", "")
    text = text.replace(
        "    class: ReactingChemicals\n    ports:\n      - {id: makeup, direction: in}",
        "    class: ReactingChemicals\n    catalyst: FE_NH3\n    ports:\n"
        "      - {id: makeup, direction: in}",
    )
    path.write_text(text)
    found = [f for f in _rules(ammonia) if f.rule == "cheme.process-catalyst"]
    # the makeup gas crosses the loop's boundary at 313 K, below the window
    assert any("stream S1 at 313.15 K" in f.message for f in found)


# -- catalyst references ---------------------------------------------------------------------------

MECHANISM = (
    "    mechanism:\n"
    "      site_density: 2.0e-5\n"
    "      adsorbates: ['N*']\n"
    "      steps:\n"
    "        - {{id: S1, stoichiometry: {{N2: -1, '*': -2, 'N*': 2}}, forward: {{A: 1.0}}}}\n"
    "      catalyst: {mech}\n"
    "      provenance: assumed\n"
)
RATE = (
    "    rate: {{form: power_law, basis: catalyst_mass, driving: partial_pressure,\n"
    "           k: {{A: 1.0e-3, Ea: 1.5e5}}, orders: {{N2: 1}}, reverse: equilibrium,\n"
    "           catalyst: {rate}, provenance: assumed}}\n"
)


def _references(root, reaction="FE_NH3", rate="FE_NH3", mech="FE_NH3"):
    from chemeascode.domains.process.sheets import catalyst_reference_findings

    path = root / "process/reactions.yaml"
    text = path.read_text().replace("catalyst: FE_NH3", f"catalyst: {reaction}")
    path.write_text(text + RATE.format(rate=rate) + MECHANISM.format(mech=mech))
    process, found = load(root)
    assert process is not None, [f.format() for f in found]
    return catalyst_reference_findings(process)


def test_known_catalyst_references_are_clean(ammonia):
    assert _references(ammonia) == []


@pytest.mark.parametrize(
    "where, field",
    [("reaction", "catalyst"), ("rate", "rate.catalyst"), ("mech", "mechanism.catalyst")],
)
def test_an_unknown_catalyst_id_is_one_warning_wherever_it_is(ammonia, where, field):
    (found,) = _references(ammonia, **{where: "NOPE"})
    assert (found.rule, found.level, found.file) == (
        "cheme.catalyst-unknown",
        "warning",
        "process/reactions.yaml",
    )
    assert found.message == f"reaction NH3_SYN: {field} 'NOPE' is no catalyst of " + (
        "process/catalysts.yaml"
    )
    assert found.ids == ["NH3_SYN", "NOPE"] and found.line and "FE_NH3" in found.hint


NH3_CATALYST = "'Promoted iron ammonia synthesis catalyst'"


def test_a_reaction_may_name_its_catalyst(ammonia):
    (found,) = _references(ammonia, reaction=NH3_CATALYST)
    assert (found.rule, found.level) == ("cheme.catalyst-by-name", "info")
    assert found.hint == "write its id: catalyst: FE_NH3"


def test_a_rate_law_names_its_catalyst_by_id(ammonia):
    (found,) = _references(ammonia, rate=NH3_CATALYST)
    assert found.rule == "cheme.catalyst-unknown" and found.hint == "write its id: FE_NH3"


def test_no_catalysts_file_no_reference_findings(ammonia):
    (ammonia / "process/catalysts.yaml").unlink()
    path = ammonia / "process/flowsheet.yaml"
    path.write_text(path.read_text().replace("    catalyst: FE_NH3\n", ""))
    assert _references(ammonia, reaction="anything", rate="NOPE", mech="NOPE") == []


def test_validate_reports_unknown_catalyst_references(ammonia, monkeypatch):
    path = ammonia / "process/reactions.yaml"
    path.write_text(path.read_text() + RATE.format(rate="NOPE"))
    monkeypatch.chdir(ammonia)
    result = CliRunner().invoke(app, ["validate"])
    assert "cheme.catalyst-unknown" in result.output and "rate.catalyst 'NOPE'" in result.output
