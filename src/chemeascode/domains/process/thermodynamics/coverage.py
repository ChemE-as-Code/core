"""Binary interaction parameter coverage of a mixture for a phase.py model.

thermo, and so :func:`~chemeascode.domains.process.thermodynamics.phase.phase_determination`,
uses zero for a binary parameter its database lacks. :func:`interaction_parameter_coverage`
says, for every pair of a component set and the model's parameter sets, which pairs have a
sourced parameter (and its source and values), which are **missing** (the calculation then uses
zero) and which zeros the user has **accepted** (recorded with ``accepted_zeros``). A sourced
value that happens to be zero stays ``sourced``.

Parameter sets by model (as phase.py uses them):

- Peng-Robinson: ``kij`` of thermo's ``ChemSep PR`` table;
- Redlich-Kwong-Soave: ``kij`` of the ChemSep SRK file ``cheme data fetch chemsep-srk``
  installs (every pair missing while it is not installed);
- Redlich-Kwong: no database, every pair missing;
- NRTL: ``bij`` and ``alphaij`` of ``ChemSep NRTL``; Wilson: ``aij`` and ``bij`` of
  ``ChemSep Wilson``; a pair counts as sourced when the table has it in both orders;
- UNIFAC: per pair of UNIFAC main groups in the mixture, thermo's original UNIFAC group
  interaction parameters (``UFIP``, both directions); a component without UNIFAC groups is
  reported as missing;
- an activity-coefficient model's vapour equation of state: its ``kij`` as above; the ideal gas
  has none.

The parameters of the DWSIM route are DWSIM's own database, which this module does not inspect.
Needs the ``props`` extra; thermo is imported inside the functions.
"""

from __future__ import annotations

import json
from collections.abc import Iterable
from typing import Any, Literal

from pydantic import BaseModel, Field

PairStatus = Literal["sourced", "missing", "accepted_zero"]


class PairCoverage(BaseModel):
    """One pair of one parameter set."""

    parameter_set: str = Field(description="e.g. 'Peng-Robinson kij', 'NRTL', 'UNIFAC groups'")
    pair: tuple[str, str] = Field(description="Component ids as given (UNIFAC: main groups)")
    cas: tuple[str, str] | None = Field(default=None, description="CAS numbers of the pair")
    status: PairStatus
    source: str | None = Field(default=None, description="Where a sourced value comes from")
    values: dict[str, Any] = Field(default_factory=dict, description="The sourced values")
    note: str = ""


class InteractionCoverage(BaseModel):
    """The binary parameter coverage of a mixture for one model."""

    model: dict[str, str] = Field(description="The phase.py thermodynamic_model")
    components: list[str]
    pairs: list[PairCoverage] = Field(default_factory=list)
    notes: list[str] = Field(default_factory=list)

    def by_status(self, status: PairStatus) -> list[PairCoverage]:
        return [p for p in self.pairs if p.status == status]

    @property
    def sourced(self) -> list[PairCoverage]:
        return self.by_status("sourced")

    @property
    def missing(self) -> list[PairCoverage]:
        """Pairs the calculation sets to zero although nobody accepted it."""
        return self.by_status("missing")

    @property
    def accepted_zero(self) -> list[PairCoverage]:
        return self.by_status("accepted_zero")

    def missing_note(self, skip_sets: Iterable[str] = ()) -> str | None:
        """One sentence naming the missing pairs (except those of *skip_sets*), or None."""
        skip = set(skip_sets)
        missing = [p for p in self.missing if p.parameter_set not in skip]
        if not missing:
            return None
        return (
            f"{len(missing)} binary parameter pair(s) without a sourced value, not accepted as "
            "zero; the calculation uses zero for them: "
            + "; ".join(f"{p.parameter_set} {p.pair[0]} / {p.pair[1]}" for p in missing)
        )

    def lines(self) -> list[str]:
        """One line per pair, for a report."""
        out = []
        for p in self.pairs:
            text = f"{p.parameter_set}: {p.pair[0]} / {p.pair[1]}: {p.status}"
            if p.source:
                text += f" ({p.source}"
                if p.values:
                    text += "; " + ", ".join(f"{k}={_fmt(v)}" for k, v in p.values.items())
                text += ")"
            if p.note:
                text += f" -- {p.note}"
            out.append(text)
        return out


def _fmt(value: Any) -> str:
    if isinstance(value, float):
        return f"{value:.6g}"
    if isinstance(value, list | tuple):
        return "[" + ", ".join(_fmt(v) for v in value) + "]"
    return str(value)


def _thermo_version() -> str:
    import thermo

    return getattr(thermo, "__version__", "?")


def _srk_database() -> Any | None:
    """The installed ChemSep SRK table as a thermo database, or None."""
    from thermo.interaction_parameters import InteractionParameterDB

    from chemeascode.domains.process.thermodynamics.chemsep_srk import installed_srk_json

    path = installed_srk_json()
    if path is None:
        return None
    table = json.loads(path.read_text(encoding="utf-8"))
    database = InteractionParameterDB()
    database.tables["ChemSep RKS"] = table["data"]
    database.metadata["ChemSep RKS"] = table["metadata"]
    return database


def _eos_set(eos: str) -> tuple[str, Any, str | None, tuple[str, ...], str]:
    """(label, database, table, keys, source) of an equation of state's kij."""
    from thermo.interaction_parameters import IPDB

    from chemeascode.domains.process.thermodynamics.chemsep_srk import FETCH_COMMAND

    label = f"{eos} kij"
    if eos == "Peng-Robinson":
        return label, IPDB, "ChemSep PR", ("kij",), f"ChemSep PR, thermo {_thermo_version()}"
    if eos == "Redlich-Kwong-Soave":
        database = _srk_database()
        if database is None:
            return label, None, None, ("kij",), f"ChemSep SRK not installed ({FETCH_COMMAND})"
        return label, database, "ChemSep RKS", ("kij",), "ChemSep SRK (cheme data fetch)"
    return label, None, None, ("kij",), "no Redlich-Kwong database"


def _activity_set(model: str) -> tuple[str, Any, str, tuple[str, ...], str]:
    from thermo.interaction_parameters import IPDB

    table = {"NRTL": "ChemSep NRTL", "Wilson": "ChemSep Wilson"}[model]
    keys = ("bij", "alphaij") if model == "NRTL" else ("aij", "bij")
    return model, IPDB, table, keys, f"{table}, thermo {_thermo_version()}"


def _accepted(accepted_zeros: Iterable[tuple[str, str]]) -> set[frozenset[str]]:
    return {frozenset(pair) for pair in accepted_zeros}


def _pair_status(
    names: tuple[str, str],
    cas: tuple[str, str],
    accepted: set[frozenset[str]],
) -> PairStatus:
    keys = {frozenset(names), frozenset(cas)}
    return "accepted_zero" if keys & accepted else "missing"


def _component_pairs(
    label: str,
    database: Any,
    table: str | None,
    keys: tuple[str, ...],
    source: str,
    components: list[str],
    cas_numbers: list[str],
    accepted: set[frozenset[str]],
) -> list[PairCoverage]:
    out = []
    n = len(components)
    for i in range(n):
        for j in range(i + 1, n):
            names = (components[i], components[j])
            cas = (cas_numbers[i], cas_numbers[j])
            found = database is not None and all(
                database.has_ip_specific(table, list(order), key)
                for order in (cas, cas[::-1])
                for key in keys
            )
            if found:
                values: dict[str, Any] = {}
                for key in keys:
                    ij = database.get_ip_specific(table, list(cas), key)
                    ji = database.get_ip_specific(table, list(cas[::-1]), key)
                    values[key] = ij if ij == ji else [ij, ji]
                out.append(
                    PairCoverage(
                        parameter_set=label,
                        pair=names,
                        cas=cas,
                        status="sourced",
                        source=source,
                        values=values,
                    )
                )
                continue
            status = _pair_status(names, cas, accepted)
            note = (
                "zero accepted by the user"
                if status == "accepted_zero"
                else f"{source if database is None else 'not in ' + table}; the calculation "
                "uses zero"
            )
            out.append(
                PairCoverage(parameter_set=label, pair=names, cas=cas, status=status, note=note)
            )
    return out


def _unifac_pairs(
    components: list[str], groups: list[dict[int, int] | None], accepted: set[frozenset[str]]
) -> tuple[list[PairCoverage], list[str]]:
    from thermo.unifac import UFIP, UFMG, UFSG

    notes = []
    mains: dict[int, str] = {}
    for name, sub in zip(components, groups, strict=True):
        if not sub:
            notes.append(f"{name}: no UNIFAC groups assigned; UNIFAC cannot represent it")
            continue
        for subgroup in sub:
            main = UFSG[subgroup].main_group_id
            mains[main] = UFMG[main][0]
    out = []
    ids = sorted(mains)
    source = f"UNIFAC (original), thermo {_thermo_version()}"
    for a_pos, a in enumerate(ids):
        for b in ids[a_pos + 1 :]:
            names = (mains[a], mains[b])
            if b in UFIP.get(a, {}) and a in UFIP.get(b, {}):
                out.append(
                    PairCoverage(
                        parameter_set="UNIFAC groups",
                        pair=names,
                        status="sourced",
                        source=source,
                        values={"a_mn": UFIP[a][b], "a_nm": UFIP[b][a]},
                    )
                )
                continue
            status: PairStatus = "accepted_zero" if frozenset(names) in accepted else "missing"
            note = (
                "zero accepted by the user"
                if status == "accepted_zero"
                else "no group interaction parameter; the calculation uses zero"
            )
            out.append(
                PairCoverage(parameter_set="UNIFAC groups", pair=names, status=status, note=note)
            )
    return out, notes


def load_constants(components: list[str]) -> tuple[Any, Any]:
    """thermo's constants and correlations; refuses what the route does not model: a
    component thermo does not identify (a pseudocomponent), one with a charge (an ion) and,
    with water, an apparent electrolyte of ``electrolytes.yml``, listed or found by formula
    (thermo would treat it as a neutral molecule)."""
    from thermo.chemical_package import ChemicalConstantsPackage

    from chemeascode.domains.process.thermodynamics.electrolytes import (
        dissolved_electrolytes,
        refusal_hint,
    )

    try:
        constants, correlations = ChemicalConstantsPackage.from_IDs(IDs=components)
    except ValueError as err:
        raise ValueError(
            f"{err}. The phase route takes compounds thermo identifies by name or CAS number; "
            "pseudocomponents (petroleum fractions) are not supported (methods.yml)."
        ) from err
    ions = [c for c, z in zip(components, constants.charges, strict=True) if z]
    if ions:
        raise ValueError(
            f"{', '.join(ions)}: charged species; electrolytes are not supported by the phase "
            "route (no electrolyte model, methods.yml)."
        )
    salts = dissolved_electrolytes(
        constants.CASs,
        dict(zip(constants.CASs, constants.formulas, strict=True)),
        dict(zip(constants.CASs, constants.names, strict=True)),
    )
    if salts:
        raise ValueError(
            f"{', '.join(e.name for e in salts)} with water: electrolytes are not supported by "
            "the phase route, which would compute them as neutral molecules (methods.yml); "
            + refusal_hint(salts)
            + "."
        )
    return constants, correlations


def coverage_from_constants(
    model: dict[str, str],
    components: list[str],
    constants: Any,
    accepted_zeros: Iterable[tuple[str, str]] = (),
) -> InteractionCoverage:
    """:func:`interaction_parameter_coverage` for thermo constants already loaded (``CASs``,
    ``UNIFAC_groups``), as phase.py has them."""
    accepted = _accepted(accepted_zeros)
    cas_numbers = list(constants.CASs)
    result = InteractionCoverage(model=dict(model), components=list(components))
    if len(components) < 2:
        return result
    sets: list[tuple[str, Any, str | None, tuple[str, ...], str]] = []
    if "eos_model" in model:
        sets.append(_eos_set(model["eos_model"]))
    else:
        liquid = model["liquid_phase_model"]
        if liquid == "UNIFAC":
            pairs, notes = _unifac_pairs(components, list(constants.UNIFAC_groups), accepted)
            result.pairs += pairs
            result.notes += notes
        else:
            sets.append(_activity_set(liquid))
        vapour = model["vapor_phase_model"]
        if vapour != "ideal_gas":
            sets.append(_eos_set(vapour))
    for label, database, table, keys, source in sets:
        result.pairs += _component_pairs(
            label, database, table, keys, source, components, cas_numbers, accepted
        )
    return result


def interaction_parameter_coverage(
    components: list[str],
    thermodynamic_model: dict[str, str] | Any,
    accepted_zeros: Iterable[tuple[str, str]] = (),
) -> InteractionCoverage:
    """Which binary parameters of *thermodynamic_model* (a phase.py model, as a dict or model
    object) are sourced, missing (zero used) or accepted as zero for *components* (names or CAS
    numbers). *accepted_zeros* are pairs (by the names given or CAS numbers; UNIFAC: main group
    names) whose zero the user has accepted. Raises ``ValueError`` for a component thermo does
    not identify (a pseudocomponent), a charged species (an ion) or an apparent electrolyte
    with water, and ``ImportError`` without the ``props`` extra."""
    try:
        import thermo  # noqa: F401
    except ImportError as err:
        raise ImportError(
            "interaction parameter coverage needs thermo: pip install 'cheme-as-code[props]'"
        ) from err
    if hasattr(thermodynamic_model, "model_dump"):
        thermodynamic_model = thermodynamic_model.model_dump(mode="json")
    constants, _ = load_constants(list(components))
    return coverage_from_constants(thermodynamic_model, components, constants, accepted_zeros)
