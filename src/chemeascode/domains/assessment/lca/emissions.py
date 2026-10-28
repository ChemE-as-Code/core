"""Emissions the flowsheet does not carry: combustion, equipment leaks, storage tanks, flares,
effluent and non-routine operation (``emission_estimates:`` of ``lca/lca.yaml``,
pre-release issue 176).

A steady-state flowsheet gives the emissions of the streams that leave as ``emission: true``
products; NOx from a fired heater, VOC leaking from flanges and valves, tank breathing losses or
COD in an effluent are not in it. :func:`estimate` computes them from activity data and the
study's emission factors, each with its source, per hour of operation (the dataset's basis):

- ``combustion``: activity (fuel, kg or energy; ``lhv`` converts) x factor per substance;
- ``equipment-leaks``: per component type, count x factor per component (kg/h) x (1 - LDAR
  reduction) x hours under pressure / operating hours, the total speciated by the mass
  composition of the scope's stream over ``components``. The counts come from the P&ID's
  take-off (``estimate/mto.csv``: valves, relief valves, flanges) and the equipment list (one
  seal per pump and per compressor), unless ``counts:`` replaces them;
- ``storage-tank``: a declared ``loss`` fraction of the throughput, or a loss ``rate`` (kg/h,
  kg/a) calculated elsewhere, speciated;
- ``flare``: the unburned slip (1 - ``efficiency``) of the gas flared, speciated, plus products
  per gas flared (``factors``);
- ``effluent``: concentration after the declared treatment x the water flow (``density``
  converts a mass flow to a volume) x (1 - ``removal``);
- ``non-routine``: a declared ``fraction`` of other estimates or simulated emissions, written
  apart as ``emission:<substance>.non-routine`` (phase ``non-routine``).

The factors are the study's: cheme-as-code packages no emission factor. A factor may instead
name an entry of a packaged factor set (``data/emission-factors/<id>.yaml``, kind
``emission_factors``: the registry entry with version, licence and attribution); the packaged
sets are placeholders until their values are read from the source and their terms are checked,
and a factor that names one refuses to run.

:func:`incomplete` is the completeness check ``cheme.lci-emissions-incomplete``: a combustion
unit or a fuel feed, a storage tank or a wastewater outlet with neither an estimate nor a
declared exclusion (``emission_exclusions:``).
"""

from __future__ import annotations

import re
from collections.abc import Callable
from dataclasses import dataclass, field
from fnmatch import fnmatchcase
from functools import cache
from pathlib import Path
from typing import Any

import yaml

from chemeascode.domains.assessment.lca.schemas import (
    NON_ROUTINE,
    EmissionEstimate,
    EmissionExclusion,
    EmissionFactor,
    EmissionFactorSet,
    LcaFile,
)
from chemeascode.domains.assessment.mto import MtoRow, matches
from chemeascode.domains.equipment.schemas.equipment import EquipmentItem
from chemeascode.domains.process.model import Process, stream_flows
from chemeascode.foundation.uncertainty import Uncertainty
from chemeascode.foundation.units import LCI_UNITS, lci_convert

DATA = Path(__file__).with_name("data") / "emission-factors"

#: The provenance of an estimated exchange.
ESTIMATED = "estimated"
#: The rules of this module's findings.
RULE_ESTIMATE = "cheme.lci-emission-estimate"
RULE_FACTOR = "cheme.lci-emission-factor"
RULE_COUNTS = "cheme.lci-emission-counts"
RULE_SIMULATED = "cheme.lci-emission-simulated"
RULE_ADDED = "cheme.lci-emission-added"
RULE_SCOPE = "cheme.lci-emission-scope"
RULE_INCOMPLETE = "cheme.lci-emissions-incomplete"

#: DEXPI classes (globs on the equipment list's ``type``) the completeness check reads as a
#: combustion unit, a flare and a storage tank. A convention of cheme: a type outside them is
#: not looked for (declare its estimate all the same). A reformer counts as fired (a primary
#: steam reformer is); an unfired one (adiabatic pre-reformer, autothermal reformer) is
#: declared in ``emission_exclusions:`` with that reason.
COMBUSTION_TYPES = (
    "*Furnace*",
    "*Boiler*",
    "*Burner*",
    "*FiredHeater*",
    "*GasTurbine*",
    "*Incinerator*",
    "*Oxidiser*",
    "*Oxidizer*",
    "*CombustionChamber*",
    "*SteamGenerator*",
    "*Reformer*",
    "*ProcessHeater*",
    "*Kiln*",
)
FLARE_TYPES = ("*Flare*",)
STORAGE_TYPES = ("*Tank*", "*Silo*")
#: Which leak component type a take-off row (``estimate/mto.csv``) or an equipment item counts
#: as. A convention of cheme (ASSUMED): a valve whose DEXPI class names safety or relief is a
#: relief valve, every other valve a valve, every flange a flange; one seal per pump and per
#: compressor (``counts:`` replaces a count, e.g. for double seals or multi-stage machines).
_RELIEF = re.compile(r"safety|relief", re.IGNORECASE)

#: Mass units of a factor's numerator, kg per unit.
_MASS = {"kg": 1.0, "g": 1e-3, "mg": 1e-6, "t": 1000.0}
#: The units ``lhv`` may be given in, MJ/kg per unit (unset: MJ/kg).
LHV_UNITS = {
    "": 1.0,
    "MJ/kg": 1.0,
    "GJ/t": 1.0,
    "kJ/g": 1.0,
    "kJ/kg": 1e-3,
    "MJ/t": 1e-3,
    "GJ/kg": 1e3,
    "kWh/kg": 3.6,
}
#: The units ``density`` may be given in, kg/m3 per unit (unset: kg/m3).
DENSITY_UNITS = {
    "": 1.0,
    "kg/m3": 1.0,
    "g/L": 1.0,
    "kg/L": 1e3,
    "t/m3": 1e3,
    "g/cm3": 1e3,
    "g/mL": 1e3,
}

Problem = Callable[..., None]


# -- factor sets --------------------------------------------------------------------------------


def factor_sets() -> list[str]:
    """The ids of the packaged emission factor sets."""
    return sorted(p.stem for p in DATA.glob("*.yaml"))


@cache
def factor_set(name: str) -> EmissionFactorSet | None:
    """The packaged emission factor set *name* (None when there is none)."""
    path = DATA / f"{name}.yaml"
    if not path.is_file():
        return None
    return EmissionFactorSet.model_validate(yaml.safe_load(path.read_text(encoding="utf-8")))


@dataclass
class Resolved:
    """A factor ready to use: value, unit, source and uncertainty."""

    value: float
    unit: str
    source: str
    uncertainty: Uncertainty | None = None


def resolve(factor: EmissionFactor) -> tuple[Resolved | None, str]:
    """The value of *factor*, from the study or a verified packaged set; else why not."""
    if factor.set is None:
        return Resolved(factor.value or 0.0, factor.unit, factor.source, factor.uncertainty), ""
    found = factor_set(factor.set)
    if found is None:
        return None, f"no packaged emission factor set {factor.set} (sets: " + (
            ", ".join(factor_sets()) + ")"
        )
    if found.status != "verified":
        return None, (
            f"the packaged factor set {factor.set} is a placeholder and holds no values "
            f"({found.todo.strip()})"
        )
    entry = found.factor(factor.id or "")
    if entry is None:
        return None, f"factor set {factor.set} has no factor {factor.id}"
    source = f"{found.source.title} {found.source.version}, {entry.table}" if found.source else ""
    return Resolved(entry.value, entry.unit, source, factor.uncertainty or entry.uncertainty), ""


def _split(unit: str) -> tuple[float, str] | None:
    """The numerator's kg per unit and the basis of a factor unit ``<mass>/<basis>``."""
    mass, _, basis = unit.partition("/")
    if mass not in _MASS or not basis:
        return None
    return _MASS[mass], basis


def activity_in(
    amount: float, unit: str, basis: str, lhv: float | None, density: float | None
) -> tuple[float | None, str]:
    """*amount* of *unit* expressed in *basis*: within a quantity kind, or mass to energy by the
    lower heating value *lhv* (MJ/kg), mass to volume by the *density* (kg/m3)."""
    if basis not in LCI_UNITS or unit not in LCI_UNITS:
        return None, f"cannot express {unit} in {basis}"
    have, want = LCI_UNITS[unit][0], LCI_UNITS[basis][0]
    if have == want:
        return lci_convert(amount, unit, basis), ""
    pair = (have, want)
    if pair in (("mass", "energy"), ("energy", "mass")):
        if lhv is None or lhv <= 0:
            return None, f"a factor per {basis} of an activity in {unit} needs lhv (MJ/kg)"
        if have == "mass":
            return lci_convert(lci_convert(amount, unit, "kg") * lhv, "MJ", basis), ""
        return lci_convert(lci_convert(amount, unit, "MJ") / lhv, "kg", basis), ""
    if pair in (("mass", "volume"), ("volume", "mass")):
        if density is None or density <= 0:
            return None, f"a factor per {basis} of an activity in {unit} needs density (kg/m3)"
        if have == "mass":
            return lci_convert(lci_convert(amount, unit, "kg") / density, "m3", basis), ""
        return lci_convert(lci_convert(amount, unit, "m3") * density, "kg", basis), ""
    return None, f"cannot express {unit} ({have}) in {basis} ({want})"


# -- estimates ----------------------------------------------------------------------------------


@dataclass
class Estimated:
    """One substance one estimate emits, kg per hour of operation."""

    key: str
    substance: str
    amount: float
    entry: EmissionEstimate
    source: str
    streams: list[str] = field(default_factory=list)
    uncertainty: Uncertainty | None = None

    @property
    def phase(self) -> str:
        return "non-routine" if self.key.endswith(NON_ROUTINE) else "operation"


@dataclass
class Context:
    """What the estimates read: the flowsheet in its case, the dataset's terminal exchanges
    (amount and unit by key) with their components (kg/h), the take-off and the equipment
    (None: absent), the operating hours a year (None: no ``operation``) and the simulated
    emissions (kg/h by ``emission:<component>``)."""

    process: Process
    case: str
    exchanges: dict[str, tuple[float, str]]
    components: dict[str, dict[str, float] | None]
    takeoff: list[MtoRow] | None
    equipment: list[EquipmentItem] | None
    hours: float | None
    simulated: dict[str, float] = field(default_factory=dict)


class _Refused(Exception):
    """An estimate that cannot be computed: the finding's message."""

    def __init__(self, message: str, rule: str = RULE_ESTIMATE, hint: str = "") -> None:
        super().__init__(message)
        self.rule, self.hint = rule, hint


def _flow(entry: EmissionEstimate, ctx: Context) -> tuple[float | None, str, dict | None, list]:
    """The activity (amount, unit per hour), the speciating components (kg/h) and the streams."""
    amount: float | None = None
    unit = ""
    components: dict[str, float] | None = None
    streams: list[str] = []
    if entry.exchange is not None:
        if entry.exchange not in ctx.exchanges:
            raise _Refused(
                f"emission estimate {entry.id}: {entry.exchange} is no feed or product of the "
                f"dataset (case {ctx.case})",
                hint="name a feed:<id> or product:<id> of process/flowsheet.yaml",
            )
        amount, unit = ctx.exchanges[entry.exchange]
        components = ctx.components.get(entry.exchange)
        streams.append(entry.exchange)
    elif entry.stream is not None:
        stream = next((s for s in ctx.process.flowsheet.streams if s.id == entry.stream), None)
        if stream is None or stream.kind != "material":
            raise _Refused(
                f"emission estimate {entry.id}: {entry.stream} is no material stream of the "
                "flowsheet",
                hint="name a stream id of process/flowsheet.yaml",
            )
        flows = stream_flows(ctx.process, stream, ctx.case)
        amount, unit, components = flows.total, "kg", flows.components
        streams.append(entry.stream)
        if amount is None and entry.activity is None:
            raise _Refused(
                f"emission estimate {entry.id}: stream {entry.stream} has no flow in case "
                f"{ctx.case} ({', '.join(flows.missing)})",
                hint="complete the stream state, or give activity: {value, unit, source}",
            )
    if entry.activity is not None:
        amount, unit = entry.activity.value, entry.activity.unit
    return amount, unit, components, streams


def _shares(entry: EmissionEstimate, components: dict[str, float] | None) -> dict[str, float]:
    """Mass shares of the speciating components (``components:``, default all)."""
    if not components:
        raise _Refused(
            f"emission estimate {entry.id}: no composition to speciate by "
            f"({entry.stream or entry.exchange or 'no stream'})",
            hint="give the stream a composition (every component a molar_mass), or name a "
            "stream that has one",
        )
    names = entry.components or list(components)
    absent = [n for n in names if n not in components]
    if absent:
        raise _Refused(
            f"emission estimate {entry.id}: components {', '.join(absent)} are not in "
            f"{entry.stream or entry.exchange}",
            hint="list components of the stream's composition",
        )
    total = sum(components[n] for n in names)
    if total <= 0:
        raise _Refused(
            f"emission estimate {entry.id}: the speciating components have no flow",
            hint="check components: and the stream's composition",
        )
    return {n: components[n] / total for n in names if components[n] > 0}


def _slipping(entry: EmissionEstimate, components: dict[str, float] | None) -> dict[str, float]:
    """Mass fractions of the gas flared of the combustibles that slip unburned
    (``components:``): each its own share of the whole gas, not renormalised, so the inerts
    (N2, CO2, H2O) pass through and are no slip."""
    if not entry.components:
        raise _Refused(
            f"emission estimate {entry.id}: a flare's unburned slip needs components: (the "
            "combustibles); the inerts of the gas pass through",
            hint="list the combustible components of the gas flared, e.g. [CH4, C2H6, H2]",
        )
    _shares(entry, components)  # the same checks: a composition with these components
    total = sum((components or {}).values())
    return {n: components[n] / total for n in entry.components if components[n] > 0}


def _parameter(entry: EmissionEstimate, name: str, units: dict[str, float]) -> float | None:
    """*entry*'s ``lhv`` or ``density`` in MJ/kg or kg/m3; a unit outside *units* is refused,
    never read as the default."""
    given = getattr(entry, name)
    if given is None:
        return None
    if given.unit not in units:
        raise _Refused(
            f"emission estimate {entry.id}: {name} unit {given.unit!r} is not one of "
            + ", ".join(u for u in units if u),
            hint=f"give {name} in one of these units",
        )
    return given.value * units[given.unit]


def _lhv(entry: EmissionEstimate) -> float | None:
    return _parameter(entry, "lhv", LHV_UNITS)


def _density(entry: EmissionEstimate) -> float | None:
    return _parameter(entry, "density", DENSITY_UNITS)


def _factor(entry: EmissionEstimate, name: str, factor: EmissionFactor) -> Resolved:
    found, why = resolve(factor)
    if found is None:
        raise _Refused(
            f"emission estimate {entry.id}, factor {name}: {why}",
            RULE_FACTOR,
            "give value, unit and source of the factor in lca/lca.yaml, read from the source",
        )
    return found


def _per_basis(
    entry: EmissionEstimate, name: str, found: Resolved, amount: float | None, unit: str
) -> float:
    """kg/h of one factor applied to the activity *amount* *unit*."""
    split = _split(found.unit)
    if split is None:
        raise _Refused(
            f"emission estimate {entry.id}, factor {name}: unit {found.unit!r} is not "
            "<kg|g|mg|t>/<basis>",
            hint="e.g. g/GJ, kg/t, mg/L",
        )
    mass, basis = split
    if amount is None:
        raise _Refused(f"emission estimate {entry.id}: no activity")
    value, why = activity_in(amount, unit, basis, _lhv(entry), _density(entry))
    if value is None:
        raise _Refused(
            f"emission estimate {entry.id}, factor {name}: {why}",
            hint="give the conversion (lhv, density) with its source, or a factor per the "
            "activity's unit",
        )
    return value * found.value * mass


def _rate(entry: EmissionEstimate, found: Resolved, hours: float | None) -> float:
    """kg/h of a loss rate in kg/h or kg/a (per operating hour)."""
    split = _split(found.unit)
    if split is None or split[1] not in ("h", "a"):
        raise _Refused(
            f"emission estimate {entry.id}: rate unit {found.unit!r} is not <mass>/h or <mass>/a",
            hint="e.g. kg/a from the working and breathing losses",
        )
    mass, basis = split
    if basis == "h":
        return found.value * mass
    if not hours:
        raise _Refused(
            f"emission estimate {entry.id}: a rate per year needs operation.hours_per_year",
            hint="give operation: {hours_per_year, life_years}",
        )
    return found.value * mass / hours


def leak_counts(
    entry: EmissionEstimate, takeoff: list[MtoRow] | None, equipment: list[EquipmentItem] | None
) -> dict[str, int]:
    """The components an equipment-leak estimate counts, by type: valves, relief valves and
    flanges of the take-off rows ``where`` matches, a seal per pump and compressor of the
    equipment ``equipment`` matches; ``counts:`` replaces a type's count."""
    counted: dict[str, int] = {}
    for _, kind, number in leak_items(entry, takeoff, equipment):
        counted[kind] = counted.get(kind, 0) + number
    counted.update(entry.counts)
    return {k: v for k, v in counted.items() if v > 0}


def leak_items(
    entry: EmissionEstimate, takeoff: list[MtoRow] | None, equipment: list[EquipmentItem] | None
) -> list[tuple[str, str, int]]:
    """What :func:`leak_counts` counts automatically, item by item: (``mto row <n>`` or the
    equipment tag, component type, count); the types ``counts:`` replaces are left out."""
    items: list[tuple[str, str, int]] = []

    def add(what: str, kind: str, number: int) -> None:
        if kind not in entry.counts:
            items.append((what, kind, number))

    if "mto" in entry.count_from:
        where = entry.where
        for index, row in enumerate(takeoff or [], start=1):
            if row.category == "valve":
                kind = "relief-valve" if _RELIEF.search(row.item) else "valve"
            elif row.category == "flange":
                kind = "flange"
            else:
                continue
            if where is not None and not (
                matches(where.item, row.item)
                and matches(where.pipe_class, row.pipe_class)
                and matches(where.spec, row.spec)
                and matches(where.group, row.group)
                and (where.dn_min is None or (row.dn is not None and row.dn >= where.dn_min))
                and (where.dn_max is None or (row.dn is not None and row.dn <= where.dn_max))
            ):
                continue
            add(
                f"mto row {index} ({row.item})",
                kind,
                round(row.quantity) if row.unit == "ea" else row.count,
            )
    if "equipment" in entry.count_from:
        for item in equipment or []:
            if entry.equipment and not any(fnmatchcase(item.tag, g) for g in entry.equipment):
                continue
            if "Pump" in item.type:
                add(item.tag, "pump-seal", 1)
            elif "Compressor" in item.type:
                add(item.tag, "compressor-seal", 1)
    return items


def _counted_twice(scope: LcaFile, ctx: Context, problem: Problem) -> None:
    """A warning for every component two equipment-leak estimates both count: its leaks
    would be estimated twice (narrow them with where:, equipment: or counts:)."""
    owners: dict[tuple[str, str], list[str]] = {}
    for entry in scope.emission_estimates:
        if entry.method != "equipment-leaks":
            continue
        for what, kind, number in leak_items(entry, ctx.takeoff, ctx.equipment):
            if number > 0:
                owners.setdefault((what, kind), []).append(entry.id)
    twice: dict[tuple[str, ...], list[str]] = {}
    for (what, kind), ids in owners.items():
        if len(ids) > 1:
            twice.setdefault(tuple(ids), []).append(f"{what} ({kind})")
    for ids, items in twice.items():
        problem(
            "warning",
            RULE_COUNTS,
            f"emission estimates {' and '.join(ids)} both count "
            + ", ".join(items[:5])
            + (f" and {len(items) - 5} more" if len(items) > 5 else "")
            + ": their leaks are estimated twice",
            f"id: {ids[0]}",
            "give each estimate its own components (where:, equipment:, count_from:), or "
            "counts: {<type>: 0} where another estimate counts them",
            list(ids),
        )


def _leaks(entry: EmissionEstimate, ctx: Context, problem: Problem) -> tuple[float, str]:
    """kg/h of total leaks of an equipment-leak estimate and how they were counted."""
    if "mto" in entry.count_from and ctx.takeoff is None and not entry.counts:
        problem(
            "warning",
            RULE_COUNTS,
            f"emission estimate {entry.id}: no estimate/mto.csv, so no valve or flange is "
            "counted from the P&ID take-off",
            f"id: {entry.id}",
            "cheme assess mto --write, or give counts: per component type",
            [entry.id],
        )
    counts = leak_counts(entry, ctx.takeoff, ctx.equipment)
    unfactored = sorted(set(counts) - set(entry.factors))
    if unfactored:
        problem(
            "warning",
            RULE_COUNTS,
            f"emission estimate {entry.id}: "
            + ", ".join(f"{counts[k]} {k}" for k in unfactored)
            + " counted without a factor: their leaks are not estimated (a gap, not 0)",
            f"id: {entry.id}",
            "give a factor per component type (kg/h per component, with its source), or "
            "counts: {<type>: 0} when they are not in this service",
            [entry.id, *unfactored],
        )
    if not counts:
        problem(
            "warning",
            RULE_COUNTS,
            f"emission estimate {entry.id} counts no component",
            f"id: {entry.id}",
            "check count_from, where: and equipment:, or give counts:",
            [entry.id],
        )
    hours = ctx.hours
    pressurised = entry.hours_per_year.value if entry.hours_per_year else hours
    if pressurised is None or not hours:
        raise _Refused(
            f"emission estimate {entry.id}: equipment leaks need operation.hours_per_year",
            hint="give operation: {hours_per_year, life_years}",
        )
    if pressurised > 8784:
        raise _Refused(f"emission estimate {entry.id}: hours_per_year {pressurised:g} > 8784")
    total = 0.0
    parts = []
    for kind, factor in entry.factors.items():
        if kind not in counts:
            continue
        found = _factor(entry, kind, factor)
        split = _split(found.unit)
        if split is None or split[1] != "h":
            raise _Refused(
                f"emission estimate {entry.id}, factor {kind}: unit {found.unit!r} is not "
                "<mass>/h per component",
                hint="e.g. kg/h",
            )
        reduction = entry.ldar[kind].value if kind in entry.ldar else 0.0
        total += counts[kind] * found.value * split[0] * (1 - reduction)
        parts.append(
            f"{counts[kind]} {kind} x {found.value:g} {found.unit} ({found.source})"
            + (f" x (1 - LDAR {reduction:g}: {entry.ldar[kind].source})" if reduction else "")
        )
    ratio = pressurised / hours
    how = "; ".join(parts) + (
        f"; x {pressurised:g}/{hours:g} h ({entry.hours_per_year.source})"
        if entry.hours_per_year
        else ""
    )
    return total * ratio, how


def _compute(entry: EmissionEstimate, ctx: Context, problem: Problem) -> dict[str, tuple]:
    """Substance -> (kg/h, source text, uncertainty) of one estimate (not non-routine)."""
    amount, unit, components, streams = _flow(entry, ctx)
    out: dict[str, tuple[float, str, Uncertainty | None]] = {}

    def put(name: str, value: float, how: str, spread: Uncertainty | None) -> None:
        old = out.get(name)
        if old is None:
            out[name] = (value, how, spread or entry.uncertainty)
        else:
            out[name] = (old[0] + value, f"{old[1]}; {how}", entry.uncertainty)

    method = entry.method
    if method in ("combustion", "flare", "effluent"):
        for name, factor in entry.factors.items():
            found = _factor(entry, name, factor)
            value = _per_basis(entry, name, found, amount, unit)
            removed = entry.removal.get(name)
            if removed is not None:
                value *= 1 - removed.value
            how = f"{name} {found.value:g} {found.unit} ({found.source})" + (
                f" x (1 - removal {removed.value:g}: {removed.source})" if removed else ""
            )
            put(name, value, how, found.uncertainty)
    if method == "flare" and entry.efficiency is not None:
        gas, why = activity_in(amount or 0.0, unit, "kg", _lhv(entry), _density(entry))
        if gas is None:
            raise _Refused(f"emission estimate {entry.id}: the gas flared in kg: {why}")
        slip = (1 - entry.efficiency.value) * gas
        for name, share in _slipping(entry, components).items():
            put(
                name,
                slip * share,
                f"unburned slip (1 - efficiency {entry.efficiency.value:g}: "
                f"{entry.efficiency.source})",
                None,
            )
    if method == "storage-tank":
        if entry.rate is not None:
            found = _factor(entry, "rate", entry.rate)
            total = _rate(entry, found, ctx.hours)
            how = f"loss rate {found.value:g} {found.unit} ({found.source})"
            spread = found.uncertainty
        else:
            throughput, why = activity_in(amount or 0.0, unit, "kg", None, _density(entry))
            if throughput is None:
                raise _Refused(f"emission estimate {entry.id}: the throughput in kg: {why}")
            total = entry.loss.value * throughput
            how = f"loss {entry.loss.value:g} of the throughput ({entry.loss.source})"
            spread = None
        for name, share in _shares(entry, components).items():
            put(name, total * share, how, spread)
    if method == "equipment-leaks":
        shares = _shares(entry, components)
        total, how = _leaks(entry, ctx, problem)
        for name, share in shares.items():
            put(name, total * share, f"{entry.service} service: {how}", None)
    return {k: (*v, streams) for k, v in out.items()}


def _text(entry: EmissionEstimate, how: str) -> str:
    return f"{ESTIMATED} ({entry.method}, emission_estimates {entry.id}): {entry.source}; {how}"


def estimate(scope: LcaFile, ctx: Context, problem: Problem) -> list[Estimated]:
    """The emissions of the study's ``emission_estimates:``, kg per hour of operation; what
    cannot be computed is an error finding (the estimate counts nothing, never a guess)."""
    found: list[Estimated] = []
    routine: dict[str, dict[str, float]] = {}
    ids = {e.id for e in scope.emission_estimates}
    non_routine = {e.id for e in scope.emission_estimates if e.method == "non-routine"}
    tags = {item.tag for item in ctx.equipment or []}
    _counted_twice(scope, ctx, problem)
    for entry in scope.emission_estimates:
        if ctx.equipment is not None:
            stray = [g for g in entry.equipment if not any(fnmatchcase(t, g) for t in tags)]
            if stray:
                problem(
                    "warning",
                    RULE_SCOPE,
                    f"emission estimate {entry.id}: equipment {', '.join(stray)} matches no "
                    "item of the equipment list",
                    f"id: {entry.id}",
                    "check the tags (globs) against equipment/equipment-list.yaml",
                    [entry.id],
                )
        if entry.method == "non-routine":
            continue
        try:
            computed = _compute(entry, ctx, problem)
        except _Refused as refused:
            problem(
                "error",
                refused.rule,
                str(refused),
                f"id: {entry.id}",
                refused.hint or "complete the estimate's parameters",
                [entry.id],
            )
            continue
        # what the inventory writes: a simulated component stays unless add: true
        routine[entry.id] = {
            name: v[0]
            for name, v in computed.items()
            if entry.add or f"emission:{name}" not in ctx.simulated
        }
        for name, (value, how, spread, streams) in computed.items():
            found.append(
                Estimated(
                    f"emission:{name}",
                    name,
                    value,
                    entry,
                    _text(entry, how),
                    [f"emission_estimates.{entry.id}", *streams],
                    spread,
                )
            )
    for entry in scope.emission_estimates:
        if entry.method != "non-routine":
            continue
        unknown = [
            o for o in entry.of if o not in ids and not (o.startswith("emission:") and ":" in o)
        ]
        if unknown:
            problem(
                "error",
                RULE_ESTIMATE,
                f"emission estimate {entry.id}: of names {', '.join(unknown)}, neither an "
                "estimate nor an emission:<component>",
                f"id: {entry.id}",
                "name estimate ids of emission_estimates or emission:<component> keys",
                [entry.id],
            )
            continue
        share = entry.fraction.value
        totals: dict[str, float] = {}
        for item in entry.of:
            if item in ids:
                base = routine.get(item, {})
                if not base:
                    why = (
                        "a non-routine estimate (no share of a share)"
                        if item in non_routine
                        else "it gives no emission that is written (refused, or every "
                        "substance left to the flowsheet's simulated amount)"
                    )
                    problem(
                        "warning",
                        RULE_ESTIMATE,
                        f"emission estimate {entry.id}: of {item}: nothing of it is counted: {why}",
                        f"id: {entry.id}",
                        "name estimates that write emissions, or emission:<component> keys",
                        [entry.id, item],
                    )
                    continue
            else:
                amount = ctx.simulated.get(item)
                if amount is None:
                    problem(
                        "warning",
                        RULE_ESTIMATE,
                        f"emission estimate {entry.id}: {item} is no emission of the "
                        "flowsheet: nothing of it is counted",
                        f"id: {entry.id}",
                        "name an emission:<component> the dataset has",
                        [entry.id],
                    )
                    continue
                base = {item.split(":", 1)[1]: amount}
            for name, value in base.items():
                totals[name] = totals.get(name, 0.0) + value
        for name, value in totals.items():
            found.append(
                Estimated(
                    f"emission:{name}{NON_ROUTINE}",
                    name,
                    value * share,
                    entry,
                    _text(
                        entry,
                        f"{share:g} of {', '.join(entry.of)} ({entry.fraction.source})",
                    ),
                    [f"emission_estimates.{entry.id}"],
                    entry.uncertainty,
                )
            )
    return found


# -- completeness -------------------------------------------------------------------------------


@dataclass
class EmissionSource:
    """A source of emissions the completeness check looks for: the method that estimates it,
    an equipment tag or a terminal key, and why it is one."""

    method: str
    tag: str = ""
    key: str = ""
    streams: tuple[str, ...] = ()
    why: str = ""

    @property
    def name(self) -> str:
        return self.tag or self.key


def _typed(item: EquipmentItem, globs: tuple[str, ...]) -> bool:
    return any(fnmatchcase(item.type, g) for g in globs)


def sources(
    process: Process,
    equipment: list[EquipmentItem] | None,
    mapping: dict[str, Any],
    streams: dict[str, list[str]],
) -> list[EmissionSource]:
    """The plant's combustion units and fuel feeds, flares, storage tanks and wastewater
    outlets whose emissions the flowsheet does not carry. A wastewater outlet sent to a
    treatment background (a factor, activity or dataset of its flows: entry) carries its
    emissions there and is not one; one released as an emission is, for what its components
    do not give (COD, N, P)."""
    found: list[EmissionSource] = []
    for item in equipment or []:
        if _typed(item, FLARE_TYPES):
            found.append(EmissionSource("flare", tag=item.tag, why=f"a {item.type}"))
        elif _typed(item, COMBUSTION_TYPES):
            found.append(EmissionSource("combustion", tag=item.tag, why=f"a {item.type}"))
        elif _typed(item, STORAGE_TYPES):
            found.append(EmissionSource("storage-tank", tag=item.tag, why=f"a {item.type}"))
    fs = process.flowsheet
    for node in fs.feeds:
        if node.category == "utility" and node.utility and node.utility.kind == "fuel":
            key = f"feed:{node.id}"
            found.append(
                EmissionSource(
                    "combustion", key=key, streams=tuple(streams.get(key, [])), why="a fuel feed"
                )
            )
    for node in fs.products:
        if node.category != "wastewater":
            continue
        key = f"product:{node.id}"
        flow = mapping.get(key)
        treated = flow is not None and not (flow.free or flow.emission or flow.resource)
        if not treated:
            found.append(
                EmissionSource(
                    "effluent",
                    key=key,
                    streams=tuple(streams.get(key, [])),
                    why="a wastewater outlet "
                    + ("released as its components" if flow is not None else "without treatment"),
                )
            )
    return found


#: The methods that cover a source of each method.
_COVERS = {
    "combustion": ("combustion", "flare"),
    "flare": ("flare", "combustion"),
    "storage-tank": ("storage-tank",),
    "effluent": ("effluent",),
}


def _covers(item: EmissionEstimate | EmissionExclusion, source: EmissionSource) -> bool:
    if item.method not in _COVERS.get(source.method, ()):
        return False
    stream = getattr(item, "stream", None)
    if source.tag:
        if isinstance(item, EmissionExclusion) and not item.equipment and item.exchange is None:
            return True
        return any(fnmatchcase(source.tag, g) for g in item.equipment)
    if isinstance(item, EmissionExclusion) and not item.equipment and item.exchange is None:
        return True
    return item.exchange == source.key or (stream is not None and stream in source.streams)


def incomplete(scope: LcaFile, found: list[EmissionSource]) -> list[EmissionSource]:
    """The sources of *found* with neither an estimate nor a declared exclusion."""
    declared = [*scope.emission_estimates, *scope.emission_exclusions]
    return [s for s in found if not any(_covers(item, s) for item in declared)]
