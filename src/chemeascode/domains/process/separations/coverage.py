"""What core can represent downstream of a separation screening, per technique.

The screening (:mod:`.selection`) ranks methods; this table says, for each method it can name
(and the general separation techniques besides), how the separation can then be represented
in core:

- ``predictive``: the outlet compositions follow from a thermodynamic model (a flash or an
  equilibrium-stage column of ``process/simulation.yaml``, solved by the simulator with its
  property package; an extraction cascade of ``process/extraction.yaml``, solved by core with
  sourced NRTL parameters, :mod:`.extraction`; or a ``crystallizer:`` with ``basis:
  solubility`` in the flowsheet, solved by ``cheme process propagate`` from sourced solubility
  data, :mod:`..crystallization`): the split is calculated, not given;
- ``shortcut``: a short-cut method on given keys and relative volatilities
  (Fenske-Underwood-Gilliland, :mod:`.shortcut`; the ``shortcut_column`` unit);
- ``specified_split``: a ``component_separator`` with given recoveries (``basis: specified``
  in ``process/simulation.yaml``): the simulator only closes the balances around a split the
  engineer states, so its convergence says nothing about whether the split is attainable;
- ``none``: no representation in core; the technique stays conceptual (sourced approximations
  in ``DESIGN.md``) or is represented by its ``fallback`` with the stated loss.

``units`` are the ``process/simulation.yaml`` units, ``extraction`` (``process/extraction.yaml``)
or the flowsheet models ``crystallizer`` and ``solid_separation`` (keys of a block or step).
``representation`` is the best one core has for the technique as a whole; ``fallback`` names
what to use instead and what it leaves out; ``energy_integration`` says whether the heat
integration that defines an intensified technique is modelled (``modelled``), only estimated
by the screening (``screening_only``: the COP of :func:`.selection._compute_cop`) or not part
of the technique (``not_applicable``). ``tested`` names the core test that solves a flowsheet
with the units involved (empty: the units exist, but no test solves this arrangement).
``evidence`` follows from it: ``tested`` (a core test solves the arrangement), ``untested``
(the model form exists, no test solves the arrangement: a predictive representation is then
a model form, not an established capability, and consumers must not treat it as validated) or
``not_applicable`` (representation ``none``).

The table describes the code; it is no claim that a given flowsheet is physically valid: a
predictive column with a property package that misses an azeotrope predicts the wrong split.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any, Literal

Representation = Literal["predictive", "shortcut", "specified_split", "none"]
Evidence = Literal["tested", "untested", "not_applicable"]
EnergyIntegration = Literal["modelled", "screening_only", "not_applicable"]

#: Representations from the strongest to the weakest.
REPRESENTATIONS: tuple[Representation, ...] = ("predictive", "shortcut", "specified_split", "none")

_RIGOROUS = "tests/test_process_simulate.py::test_dwsim_solves_a_rigorous_column"
_SHORTCUT = "tests/test_process_simulate.py::test_dwsim_solves_the_separation_example"
_DOUBLE = "tests/test_process_simulate.py::test_dwsim_solves_the_double_column"
_SPLIT = "tests/test_process_simulate.py::test_dwsim_solves_the_cold_box"
_FLASH = "tests/test_process_simulate.py::test_dwsim_solves_the_separation_example"
_EXTRACTION = "tests/test_extraction.py::test_the_cascade_satisfies_the_stage_equations"
_ADSORPTION = "tests/test_adsorption_reference.py::test_the_reference_case_qualifies"
_AZEOTROPE = (
    "the azeotrope must be in the property package (an activity-coefficient model with "
    "fitted parameters; the default Peng-Robinson without kij does not predict it): check "
    "it with phase-calculation before trusting the split"
)


@dataclass(frozen=True)
class TechniqueCoverage:
    """One row of :data:`SEPARATION_COVERAGE`."""

    technique: str
    representation: Representation
    units: tuple[str, ...] = ()
    energy_integration: EnergyIntegration = "not_applicable"
    fallback: str = ""
    notes: str = ""
    tested: tuple[str, ...] = ()
    aliases: tuple[str, ...] = field(default=(), repr=False)

    @property
    def evidence(self) -> Evidence:
        """``tested`` when a core test solves the arrangement, ``untested`` when none does,
        ``not_applicable`` without a representation."""
        if self.representation == "none":
            return "not_applicable"
        return "tested" if self.tested else "untested"

    @property
    def status(self) -> str:
        """The representation with its evidence, e.g. ``predictive (untested arrangement)``."""
        if self.evidence == "untested":
            return f"{self.representation} (untested arrangement)"
        return self.representation

    def as_dict(self) -> dict[str, Any]:
        data = asdict(self)
        data.pop("aliases")
        data["units"] = list(self.units)
        data["tested"] = list(self.tested)
        data["evidence"] = self.evidence
        data["status"] = self.status
        return data


_ROWS = (
    # -- distillation and its arrangements ------------------------------------------------------
    TechniqueCoverage(
        "ConvDist",
        "predictive",
        ("distillation_column", "shortcut_column"),
        notes="Equilibrium-stage column (MESH, simulator); the shortcut_column and "
        "separations.shortcut give Fenske-Underwood-Gilliland stages and reflux.",
        tested=(_RIGOROUS, _SHORTCUT),
        aliases=("Conventional distillation", "Distillation"),
    ),
    TechniqueCoverage(
        "Distillation sequences",
        "predictive",
        ("distillation_column", "shortcut_column"),
        notes="One column per split, in the sequence the flowsheet draws.",
        tested=(_RIGOROUS,),
    ),
    TechniqueCoverage(
        "Vacuum distillation",
        "predictive",
        ("distillation_column",),
        notes="A column at the stated condenser and reboiler pressures; thermal degradation is "
        "not modelled.",
        tested=(_RIGOROUS,),
    ),
    TechniqueCoverage(
        "High pressure distillation column",
        "predictive",
        ("distillation_column",),
        notes="A column at the stated pressures; freezing (the reason it is proposed) is not "
        "checked by the column: no solid phase is modelled.",
        tested=(_DOUBLE,),
    ),
    TechniqueCoverage(
        "Preconcentration column",
        "predictive",
        ("distillation_column",),
        tested=(_RIGOROUS,),
    ),
    TechniqueCoverage(
        "Two columns with second distillate recycled back",
        "predictive",
        ("distillation_column",),
        notes="Two columns with a recycle (torn and solved iteratively).",
    ),
    TechniqueCoverage(
        "Partial condenser",
        "predictive",
        ("distillation_column", "flash"),
        notes="condenser: partial on a rigorous column, or a flash after a cooler.",
        tested=(_FLASH,),
    ),
    TechniqueCoverage(
        "PSD",
        "predictive",
        ("distillation_column",),
        notes="Two columns at two pressures with a recycle; " + _AZEOTROPE + ".",
        aliases=("Pressure-swing distillation",),
    ),
    TechniqueCoverage(
        "ED/AD",
        "predictive",
        ("distillation_column",),
        notes="A column with two feeds (feed_stages by inlet port) and the solvent recovery "
        "column; entrainer selection is not in core; " + _AZEOTROPE + ".",
        aliases=("Extractive distillation", "Azeotropic distillation"),
    ),
    TechniqueCoverage(
        "DWC",
        "predictive",
        ("distillation_column",),
        notes="As its thermodynamically equivalent thermally coupled arrangement: a "
        "prefractionator without condenser and reboiler (condenser: none, reboiler: false) and "
        "a main column with a side draw; the wall itself is not a unit.",
        aliases=("Dividing-wall column", "Divided wall column"),
    ),
    TechniqueCoverage(
        "TCD",
        "predictive",
        ("distillation_column",),
        energy_integration="modelled",
        notes="Thermally coupled columns by vapour/liquid interconnections, or a "
        "condenser-reboiler (heat_integration: condenser_of, duties and temperature difference "
        "checked).",
        tested=(_DOUBLE,),
        aliases=("Thermally coupled distillation (TCD)", "Thermally coupled distillation"),
    ),
    TechniqueCoverage(
        "Kaibel column",
        "predictive",
        ("distillation_column",),
        notes="As a thermally coupled arrangement with two side draws (see DWC).",
    ),
    TechniqueCoverage(
        "E-DWC",
        "predictive",
        ("distillation_column",),
        notes="As ED/AD in the thermally coupled arrangement of a DWC; " + _AZEOTROPE + ".",
    ),
    TechniqueCoverage(
        "A-DWC",
        "predictive",
        ("distillation_column",),
        notes="As ED/AD in the thermally coupled arrangement of a DWC; " + _AZEOTROPE + ".",
    ),
    TechniqueCoverage(
        "HPAD",
        "predictive",
        ("distillation_column", "compressor"),
        energy_integration="screening_only",
        fallback="the column alone (its condenser and reboiler duties), the heat pump as a "
        "separate compressor; the coupling of condenser and reboiler through the heat pump is "
        "not a unit, only the screening's COP estimate.",
        notes="Column predictive (untested arrangement); heat pump: screening estimate only "
        "(vapour recompression or a closed heat-pump cycle is not a unit).",
        aliases=("Heat pump assisted distillation",),
    ),
    TechniqueCoverage(
        "HIDiC",
        "none",
        (),
        energy_integration="screening_only",
        fallback="a distillation_column for the split, without the internal heat transfer "
        "between rectifying and stripping sections (which changes the internal flows): the "
        "energy saving rests on the screening's COP estimate only.",
        aliases=("Heat-integrated distillation column",),
    ),
    TechniqueCoverage(
        "CyDist",
        "none",
        (),
        fallback="a steady-state distillation_column; the cyclic (periodic) operation is "
        "dynamic and not modelled.",
        aliases=("Cyclic distillation",),
    ),
    TechniqueCoverage(
        "HiGee",
        "predictive",
        ("distillation_column",),
        notes="Equilibrium stages only: the rotating packed bed's mass transfer (HTU), rotor and "
        "drive are not modelled or sized.",
        aliases=("Rotating packed bed",),
    ),
    TechniqueCoverage(
        "MAD",
        "specified_split",
        ("distillation_column", "component_separator"),
        notes="The column is predictive; the membrane is a component_separator with given "
        "recoveries (no permeance or area model).",
        aliases=("Membrane assisted distillation (MAD)", "Membrane assisted distillation"),
    ),
    # -- other separation techniques ---------------------------------------------------------
    TechniqueCoverage(
        "Flash",
        "predictive",
        ("flash",),
        notes="Vapour-liquid equilibrium at the stated temperature and/or pressure.",
        tested=(_FLASH,),
        aliases=("Phase separation", "Flash drum"),
    ),
    TechniqueCoverage(
        "Evaporation",
        "predictive",
        ("heater", "flash"),
        notes="Vapour-liquid equilibrium; evaporator heat transfer is not rated.",
        tested=(_FLASH,),
    ),
    TechniqueCoverage(
        "(Steam) stripping",
        "predictive",
        ("distillation_column",),
        notes="A column without condenser and/or reboiler (condenser: none, reboiler: false) "
        "with the stripping gas as a second feed.",
        aliases=("Stripping", "Steam stripping"),
    ),
    TechniqueCoverage(
        "Absorption",
        "predictive",
        ("distillation_column",),
        notes="A column without condenser and reboiler (condenser: none, reboiler: false); no "
        "rate-based or reactive absorption.",
    ),
    TechniqueCoverage(
        "Liquid-liquid extraction",
        "predictive",
        ("extraction",),
        fallback="in the flowsheet and the simulation, a component_separator with given "
        "recoveries (specified split): cite the split_to_extract of `cheme process extract` "
        "as its basis_source; it stays specified for the maturity report.",
        notes="Countercurrent equilibrium stages on NRTL with sourced parameters "
        "(process/extraction.yaml, `cheme process extract`, separations.extraction), solved "
        "by core outside the simulation; qualified only for a bundled benchmarked LLE system "
        "inside its range. Solvent regeneration is a separate unit.",
        tested=(_EXTRACTION,),
        aliases=("Extraction", "LLE", "Solvent extraction"),
    ),
    TechniqueCoverage(
        "Membrane separation",
        "specified_split",
        ("component_separator",),
        fallback="no permeance, selectivity or membrane area model: give the recoveries with "
        "their source (vendor data, a published module at stated conditions).",
        aliases=("Membrane",),
    ),
    TechniqueCoverage(
        "Adsorption",
        "specified_split",
        ("component_separator",),
        fallback="give the recoveries with their source; for a TSA, process/adsorption.yaml "
        "calculates them (cheme process adsorption: equilibrium cycle from sourced isotherms, "
        "model basis adsorption-equilibrium) and the component_separator carries them into the "
        "simulation; no PSA cycle model (an external model's results only).",
        notes="In the simulation always a specified split; the equilibrium TSA cycle is "
        "calculated outside it (no thermal front, no breakthrough dynamics).",
        tested=(_SPLIT, _ADSORPTION),
        aliases=("PSA", "TSA", "Pressure swing adsorption", "Temperature swing adsorption"),
    ),
    TechniqueCoverage(
        "Crystallization",
        "predictive",
        ("crystallizer",),
        fallback="several solutes, impurities or a solubility outside the data: a "
        "component_separator (or crystallizer basis: yield) with recoveries given with their "
        "source.",
        notes="A crystallizer: (basis: solubility) solved by cheme process propagate: one "
        "solute in one solvent, anhydrous or a hydrate, cooling and/or evaporative, saturated "
        "mother liquor from sourced solubility data (interpolated, never extrapolated), with a "
        "specified filter or centrifuge and mother-liquor recycle; basis: yield imposes the "
        "yield (specified). No population balance, kinetics or several solutes; not part of "
        "the DWSIM simulation.",
        tested=(
            "tests/test_crystallization.py::test_felder_4_5_2_evaporative_crystallizer_filter_"
            "and_recycle",
            "tests/test_crystallization.py::test_geankoplis_12_11_1_decahydrate_yield",
        ),
        aliases=("Crystallisation",),
    ),
    TechniqueCoverage(
        "Drying",
        "specified_split",
        ("component_separator",),
        fallback="no dryer model (solids, drying curves): give the moisture split with its source.",
        aliases=("Dryer",),
    ),
    TechniqueCoverage(
        "Solid-fluid separation",
        "specified_split",
        ("solid_separation",),
        fallback="no filtration, centrifuge, cyclone or settling model: give the solid "
        "recovery and the liquid the cake holds with their source (solid_separation:); a gas "
        "with solids: a component_separator.",
        tested=(
            "tests/test_crystallization.py::test_a_filter_on_its_own_is_a_specified_solid_split",
        ),
        aliases=("Filtration", "Centrifugation", "Cyclone", "Settling"),
    ),
)

#: Technique -> its row; the techniques the screening names and the general ones.
SEPARATION_COVERAGE: dict[str, TechniqueCoverage] = {row.technique: row for row in _ROWS}
_BY_NAME: dict[str, TechniqueCoverage] = {
    name.casefold(): row for row in _ROWS for name in (row.technique, *row.aliases)
}


def coverage_of(technique: str) -> TechniqueCoverage | None:
    """The row of *technique* (its name or an alias, any case), or None when the table does
    not know it."""
    return _BY_NAME.get(technique.strip().casefold())


def representation_of(technique: str) -> dict[str, Any]:
    """The row of *technique* as a dict; a technique the table does not know is reported with
    ``representation: unknown`` rather than guessed."""
    row = coverage_of(technique)
    if row is None:
        return {
            "technique": technique,
            "representation": "unknown",
            "evidence": "not_applicable",
            "status": "unknown",
            "notes": "not in the separation coverage table "
            "(chemeascode.domains.process.separations.coverage)",
        }
    return row.as_dict()


def methods_named(node: Any) -> list[str]:
    """Every ``method`` named in a screening result (ranked methods, grouped per pair, and
    the high-level recommendations), in first-seen order."""
    found: list[str] = []

    def walk(item: Any) -> None:
        if isinstance(item, dict):
            method = item.get("method")
            if isinstance(method, str) and method not in found:
                found.append(method)
            for value in item.values():
                walk(value)
        elif isinstance(item, list):
            for value in item:
                walk(value)

    walk(node)
    return found


def coverage_table() -> list[dict[str, Any]]:
    """The whole table, one dict per technique (for docs and tooling)."""
    return [row.as_dict() for row in _ROWS]
