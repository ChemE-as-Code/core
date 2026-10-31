"""The flowsheet and ``process/simulation.yaml`` as a simulator model: plain JSON, SI units.

The model names compounds (id, CAS, the simulator name where given), feeds (temperature K,
pressure Pa, mass flow kg/s, mole fractions), unit operations with their inlets and outlets in
port order and their specifications, and the energy streams attached to them. It knows nothing
about DWSIM: ``chemeascode.integrations.dwsim`` turns it into a DWSIM flowsheet.

What cannot be simulated is refused with a finding, and then no model is made for the case:
a step whose class maps to no unit operation, a missing or contradictory specification, a feed
without temperature, pressure, flow or composition, a solid component (``phase: solid``,
``cheme.process-sim-solid``: no solid phase in the simulation). A recycle loop is torn at one of its
streams (``tear_streams``, else chosen) and solved iteratively.

Each unit has a basis (:data:`UNIT_BASIS`): predictive, shortcut or specified. A component
separator is specified (its recoveries are given); one without ``basis_source`` is
``cheme.process-sim-specified-unsourced`` (warning), and a ``basis`` that contradicts the unit
kind is refused. The bases stay out of the model and its fingerprint
(:attr:`Translation.bases`); the run record and the viewer show them beside each unit.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import yaml
from pydantic import ValidationError

from chemeascode.domains.process import FLOWSHEET_FILE
from chemeascode.domains.process.model import End, Process, stream_flows
from chemeascode.domains.process.schema import DUTY_UNITS, FLOW_UNITS, Quantity, StreamDef
from chemeascode.domains.process.simulation import SIMULATION_FILE, SOURCE
from chemeascode.domains.process.simulation.backends import IDAES, IDAES_PACKAGES
from chemeascode.domains.process.simulation.backends import model_findings as backend_findings
from chemeascode.domains.process.simulation.schema import (
    KineticCoupling,
    Simulation,
    UnitSpec,
)
from chemeascode.domains.process.thermodynamics.electrolytes import (
    dissolved_electrolytes,
    refusal_hint,
)
from chemeascode.foundation.findings import Finding
from chemeascode.foundation.provenance import value_fingerprint, written_by
from chemeascode.foundation.units import (
    UnitError,
    convert_units,
    pressure_kind,
    to_kelvin,
    to_kpa_abs,
)
from chemeascode.foundation.yamlsource import _compose, _yaml_line, syntax_finding

#: DEXPI step classes (and their subclasses) by unit operation; the first match wins. A heat
#: exchanging step with two streams in and two out is a ``heat_exchanger``.
UNITS = (
    ("compressor", ("Compressing",)),
    ("pump", ("Pumping",)),
    ("cooler", ("RemovingThermalEnergy",)),
    ("heater", ("SupplyingThermalEnergy", "ExchangingThermalEnergy")),
    ("valve", ("SteeringFlow",)),
    ("mixer", ("Mixing",)),
    ("splitter", ("SplittingMaterial",)),
    ("flash", ("SeparatingByFlash", "SeparatingByPhaseSeparation")),
    ("shortcut_column", ("Distilling",)),
    (
        "component_separator",
        (
            "SeparatingMechanically",
            "SeparatingByPhysicalProcess",
            "SeparatingByElectromagneticForce",
        ),
    ),
)
#: Material streams in (min, max) and out (min, max) per unit, as DWSIM connects them (mixer:
#: six inlets, splitter: three outlets, vessel: six inlets).
SHAPES = {
    "compressor": (1, 1, 1, 2),
    "expander": (1, 1, 1, 1),
    "pump": (1, 1, 1, 1),
    "heater": (1, 1, 1, 2),
    "cooler": (1, 1, 1, 2),
    "valve": (1, 1, 1, 1),
    "mixer": (1, 6, 1, 1),
    "splitter": (1, 1, 2, 3),
    "flash": (1, 6, 2, 2),
    "heat_exchanger": (2, 2, 2, 2),
    "shortcut_column": (1, 1, 2, 2),
    "distillation_column": (1, 6, 2, 9),
    "component_separator": (1, 1, 2, 2),
    "multi_stream_exchanger": (3, 12, 3, 12),
    "conversion_reactor": (1, 1, 1, 2),
    "equilibrium_reactor": (1, 1, 1, 2),
    "gibbs_reactor": (1, 1, 1, 2),
    "kinetic_pfr": (1, 1, 1, 1),
}
#: The reactors, by the flowsheet's reactor model.
REACTORS = {
    "conversion": "conversion_reactor",
    "equilibrium": "equilibrium_reactor",
    "gibbs": "gibbs_reactor",
}
#: A fixed bed (``reactor: pfr``): no native DWSIM unit; cheme-as-code solves the bed and
#: couples it to the DWSIM solve as an external unit (:mod:`.coupling`).
KINETIC = "kinetic_pfr"
#: Units with a duty or power, and so an energy stream (the column has two).
ENERGY_UNITS = (
    "compressor",
    "expander",
    "pump",
    "heater",
    "cooler",
    "flash",
    "shortcut_column",
    "distillation_column",
    "component_separator",
    *REACTORS.values(),
    KINETIC,
)
#: Which way a unit's single energy stream runs: into the unit (power, heat added) or out of it
#: (heat removed, power produced); None: either. Columns take one of each.
DIRECTION = {
    "compressor": True,
    "pump": True,
    "heater": None,
    "cooler": False,
    "expander": False,
    "flash": None,
    "component_separator": False,
    **dict.fromkeys((*REACTORS.values(), KINETIC)),
}
#: How each unit kind's outlet follows from its inlets (schema ``UnitBasis``): ``specified``
#: where the engineer states the result (a component separator's recoveries, a splitter's
#: fractions, a conversion reactor's conversions), ``shortcut`` for the Fenske-Underwood-
#: Gilliland column, ``predictive`` where the property package and the unit's equations give
#: it. Kept out of the simulator model (and so out of its fingerprint); the translation and the
#: run record carry it (:attr:`Translation.bases`).
UNIT_BASIS = {
    "compressor": "predictive",
    "expander": "predictive",
    "pump": "predictive",
    "heater": "predictive",
    "cooler": "predictive",
    "valve": "predictive",
    "mixer": "predictive",
    "splitter": "specified",
    "flash": "predictive",
    "heat_exchanger": "predictive",
    "shortcut_column": "shortcut",
    "distillation_column": "predictive",
    "component_separator": "specified",
    "multi_stream_exchanger": "predictive",
    "conversion_reactor": "specified",
    "equilibrium_reactor": "predictive",
    "gibbs_reactor": "predictive",
    # a fixed bed solved by cheme-as-code from its rate laws, coupled as an external unit
    "kinetic_pfr": "predictive",
}
#: Units whose specified result is a separation, and so needs its source.
SPECIFIED_SPLITS = ("component_separator",)
#: Units with a reboiler and a condenser.
COLUMNS = ("shortcut_column", "distillation_column")
#: Outlet roles of the separating units, in DWSIM's outlet order.
ROLES = {
    "flash": ("vapor", "liquid"),
    "shortcut_column": ("distillate", "bottoms"),
    "distillation_column": ("distillate", "bottoms"),
    **dict.fromkeys(REACTORS.values(), ("vapor", "liquid")),
}
#: Port id words that name a role.
ROLE_WORDS = {
    "vapor": {"vapor", "vapour", "gas", "top", "overhead", "overheads", "v"},
    "liquid": {"liquid", "liq", "bottom", "bottoms", "l"},
    "distillate": {"distillate", "top", "overhead", "overheads", "tops", "d"},
    "bottoms": {"bottom", "bottoms", "residue", "b"},
}
#: Units whose second outlet takes the condensate of their cooling.
CONDENSING = ("compressor", "heater", "cooler")
#: Port id words that name the condensate outlet.
CONDENSATE_WORDS = {"condensate", "cond", "drain", "drains", "water", "liquid", "liq"}
#: The outlets of a condensing unit, in the order the worker connects them.
CONDENSATE_ROLES = ["gas", "condensate"]
#: Mole fractions below this are left out of a feed.
TRACE = 1e-12
#: Property packages with binary interaction parameters (kij) that simulation.yaml can set.
EOS_PACKAGES = ("Peng-Robinson (PR)", "Peng-Robinson 1978 (PR78)", "Soave-Redlich-Kwong (SRK)")


def ours(value: Any) -> bool:
    """Whether *value* was written by ``cheme process simulate`` (and so may be rewritten,
    and is never an input)."""
    return written_by(value, SOURCE)


#: What ``cheme process simulate --fill`` writes: material streams' state, energy streams' duty.
WRITTEN = ("temperature", "pressure", "flow", "composition", "duty")


def translation(process: Process, case: str) -> Translation | None:
    """:func:`translate` of *case* with ``process/simulation.yaml`` as it is now, once per
    loaded *process* and *case* (no simulator needed); None without a simulation file or when
    the case does not translate (simulate reports why)."""
    cache = process.__dict__.setdefault("_translations", {})
    if case not in cache:
        found = None
        try:
            sim, doc, _ = load(process.root)
            if sim is not None:
                found = translate(process, sim, doc, case)
        except Exception:  # noqa: BLE001 - a model that does not translate is simulate's to report
            found = None
        cache[case] = found if found is not None and found.model is not None else None
    return cache[case]


def prime(process: Process) -> None:
    """Translate every case of *process* now, while ``process.root`` holds its simulation file
    (a copy that is removed after loading, as ``cheme serve`` loads a revision); only when a
    stream holds values simulate wrote, the only ones :func:`stale_fields` translates for."""
    for case in (c.id for c in process.flowsheet.cases):
        if any(
            ours(getattr(s.state.get(case), n, None))
            for s in process.flowsheet.streams
            for n in WRITTEN
        ):
            translation(process, case)


def stale_fields(process: Process, stream: StreamDef, case: str) -> list[str]:
    """The fields of *stream* in *case* simulate wrote whose model changed since: the case now
    translates to a model with another fingerprint (feeds, specs, property package), the stream
    is no longer one the simulator calculates, or the case no longer translates."""
    state = stream.state.get(case)
    mine = [n for n in WRITTEN if state is not None and ours(getattr(state, n))]
    if not mine:
        return []
    model = translation(process, case)
    if model is None:
        return mine
    simulated = (
        stream.id in model.energies if stream.kind == "energy" else stream.id in model.outlets
    )
    if not simulated:
        return mine
    return [n for n in mine if getattr(state, n).fingerprint != model.fingerprint]


def reactor_unit(node: Any) -> str | None:
    """The reactor a block or step is (its ``reactor:`` model, else a conversion reactor when
    it names reactions); None when it is none."""
    model = getattr(node, "reactor", None)
    if model in ("pfr", "cstr", "batch"):
        return KINETIC  # solved by cheme-as-code, coupled to DWSIM as an external unit
    if model:
        return REACTORS[model]
    return REACTORS["conversion"] if getattr(node, "reactions", None) else None


def unit_of(class_name: str, inlets: int = 1) -> str | None:
    """The unit operation for a DEXPI step class with *inlets* material streams in; None when
    the class does not say."""
    from chemeascode.domains.process.build import C, step_class

    cls = step_class(class_name)
    if cls is None:
        return None
    for unit, names in UNITS:
        bases = tuple(b for b in (getattr(C, n, None) for n in names) if b is not None)
        if issubclass(cls, bases):
            exchanging = getattr(C, "ExchangingThermalEnergy", None)
            if unit == "heater" and inlets >= 2 and exchanging and issubclass(cls, exchanging):
                return "heat_exchanger" if inlets == 2 else "multi_stream_exchanger"
            return unit
    return None


def _words(port: str) -> set[str]:
    return {w for w in re.split(r"[^a-z0-9]+", port.lower()) if w}


def wanted_roles(unit: str, spec: UnitSpec) -> tuple[str, ...]:
    """What the outlets of a flash or column carry, in DWSIM's order; a rigorous column's
    depend on its condenser."""
    if unit == "distillation_column":
        return {
            "partial": ("vapor", "distillate", "bottoms"),
            "none": ("vapor", "bottoms"),
        }.get(spec.condenser, ("distillate", "bottoms"))
    return ROLES[unit]


def _roles(unit: str, spec: UnitSpec, ports: list[str]) -> tuple[list[str] | None, str]:
    """The outlet ports of a flash or column in DWSIM's order (vapour, liquid; distillate,
    bottoms), or None and why not."""
    wanted = wanted_roles(unit, spec)
    given = {p: r for p, r in spec.outlets.items() if p in ports}
    if given:
        if set(given.values()) != set(wanted) or len(given) != len(ports):
            return (
                None,
                f"outlets must name each connected outlet port once as {' and '.join(wanted)}",
            )
        return [next(p for p, r in given.items() if r == role) for role in wanted], ""
    found = []
    for role in wanted:
        match = [p for p in ports if _words(p) & ROLE_WORDS[role]]
        if len(match) != 1:
            return (
                None,
                f"cannot tell from the port ids ({', '.join(ports)}) which outlet is {role}",
            )
        found.append(match[0])
    if len(set(found)) != len(found):
        return None, f"the port ids ({', '.join(ports)}) do not tell the outlets apart"
    return found, ""


def _condensate(unit: str, spec: UnitSpec, ports: list[str]) -> tuple[list[str] | None, str]:
    """The two outlets of a condensing unit as (gas, condensate), or None and why not. The
    condensate port is named by ``outlets`` (``condensate`` or ``liquid``; or the other port
    named ``gas`` or ``vapor``), else by a word of its id; the gas port may carry any id."""
    if unit == "compressor" and spec.outlet_temperature is None:
        return None, "a second outlet takes condensate, which needs coolers (outlet_temperature)"
    if unit == "compressor" and (spec.stages or 1) > 6:
        return None, f"{spec.stages} stages: DWSIM joins at most six condensate drains"
    named = {p: r for p, r in spec.outlets.items() if p in ports}
    wet = [p for p, r in named.items() if r in ("condensate", "liquid")]
    dry = [p for p, r in named.items() if r in ("gas", "vapor")]
    if len(wet) > 1 or len(dry) > 1 or set(wet) & set(dry):
        return None, "outlets names more than one condensate (or gas) port"
    if wet:
        found = wet
    elif dry:
        found = [p for p in ports if p != dry[0]]
    else:
        found = [p for p in ports if _words(p) & CONDENSATE_WORDS]
    if len(found) != 1:
        return None, (
            f"cannot tell from the port ids ({', '.join(ports)}) which outlet is the condensate"
        )
    return [next(p for p in ports if p != found[0]), found[0]], ""


def _pairs(spec: UnitSpec, inlets: list[str], outlets: list[str]) -> tuple[list[str] | None, str]:
    """The outlet ports of a heat exchanger in the order of its inlet ports, or None and why."""
    if spec.pairs:
        if set(spec.pairs) != set(inlets) or set(spec.pairs.values()) != set(outlets):
            return None, "pairs must map each connected inlet port to its outlet port"
        return [spec.pairs[p] for p in inlets], ""
    side = {"in", "out", "inlet", "outlet"}
    keys = {o: _words(o) - side for o in outlets}
    found = []
    for p in inlets:
        match = [o for o, k in keys.items() if k and k == _words(p) - side]
        if len(match) != 1:
            return None, f"cannot tell from the port ids which outlet belongs to inlet {p}"
        found.append(match[0])
    return found, ""


def load(root: Path) -> tuple[Simulation | None, Any, list[Finding]]:
    """``process/simulation.yaml`` of the repository at *root*, its node tree and its findings;
    (None, None, []) when the file does not exist."""
    path = root / SIMULATION_FILE
    if not path.is_file():
        return None, None, []
    text = path.read_text(encoding="utf-8")
    try:
        data = yaml.safe_load(text) or {}
    except yaml.YAMLError as failure:
        return None, None, [syntax_finding(SIMULATION_FILE, failure, text)]
    doc = _compose(path)
    try:
        return Simulation.model_validate(data), doc, []
    except ValidationError as failure:
        return (
            None,
            doc,
            [
                Finding(
                    SIMULATION_FILE,
                    "error",
                    "cheme.process-sim-schema",
                    f"{'.'.join(str(p) for p in e['loc']) or 'file'}: {e['msg']}",
                    line=_yaml_line(doc, list(e["loc"])),
                    hint="see `cheme schema process-simulation`",
                )
                for e in failure.errors()
            ],
        )


@dataclass
class Translation:
    """The model of one case, or the findings why there is none."""

    model: dict[str, Any] | None = None
    findings: list[Finding] = field(default_factory=list)
    #: Material streams the simulator calculates (every one but the feeds).
    outlets: list[str] = field(default_factory=list)
    #: Energy stream id -> the unit and the key of its result the stream carries
    #: (``duty_kW``; the column's ``condenser_kW`` and ``reboiler_kW``).
    energies: dict[str, tuple[str, str]] = field(default_factory=dict)
    #: The energy streams of :attr:`energies` that run into their unit (the others out of it):
    #: a duty is written only where its sign agrees (:func:`.run._into_unit`).
    entering: set[str] = field(default_factory=set)
    fingerprint: str = ""
    #: Unit id -> ``{"basis", "source", "operating_basis"}`` (:data:`UNIT_BASIS`, the spec's
    #: ``basis``, ``basis_source`` and ``operating_basis``): not part of the model.
    bases: dict[str, dict[str, Any]] = field(default_factory=dict)


def fingerprint(model: dict[str, Any]) -> str:
    """The input fingerprint of every value calculated from *model*: without the first guesses
    of the recycles, which change the path to the solution, not the solution."""
    data = {k: v for k, v in model.items() if k not in ("recycles", "units")}
    data["units"] = [
        {**u, "spec": {k: v for k, v in u["spec"].items() if k != "mw_guess"}}
        for u in model.get("units", [])
    ]
    if model.get("recycles"):  # a model without a loop keeps the fingerprint it had before
        data["recycles"] = [{**r, "guess": None} for r in model["recycles"]]
    return value_fingerprint(data)


def property_package_findings(
    sim: Simulation, sim_doc: Any = None, require_selection: bool = False
) -> list[Finding]:
    """The supported-method contract for ``property_package``:

    - ``cheme.process-sim-property-package`` (error): a package the DWSIM route does not run
      (``methods.simulation_packages()``, the worker's ``PACKAGES``);
    - ``cheme.process-sim-method-selection`` (warning): ``method_selection.facts`` do not give
      a recommendation (missing or invalid facts);
    - ``cheme.process-sim-method-not-recommended`` (warning): the recorded selection does not
      recommend the package, and no substitution reason is recorded;
    - ``cheme.process-sim-method-substituted`` (info): it does not, and the recorded reason
      accepts it;
    - ``cheme.process-sim-method-unrecorded`` (info, only with *require_selection*, for
      maturity checks): no ``method_selection`` is recorded.
    """
    from chemeascode.domains.process.thermodynamics.methods import (
        method_for_package,
        simulation_packages,
    )
    from chemeascode.domains.process.thermodynamics.model_selection import select_thermo_model
    from chemeascode.domains.process.thermodynamics.rules import InsufficientFactsError

    found: list[Finding] = []

    def add(level: str, rule: str, message: str, loc: list[Any], hint: str) -> None:
        found.append(
            Finding(
                SIMULATION_FILE,
                level,  # type: ignore[arg-type]
                f"cheme.process-{rule}",
                message,
                line=_yaml_line(sim_doc, loc) if sim_doc is not None else None,
                ids=[sim.property_package],
                hint=hint,
            )
        )

    package = sim.property_package
    if sim.simulator == IDAES:
        _idaes_package_findings(sim, add, require_selection)
        return found
    supported = simulation_packages()
    if method_for_package(package) is None:
        add(
            "error",
            "sim-property-package",
            f"property package {package!r} is not one the DWSIM route runs",
            ["property_package"],
            "use one of " + ", ".join(supported) + " (methods.yml); a recommended model the "
            "route does not run has an explicit substitute there",
        )
        return found
    selection = sim.method_selection
    if selection is None:
        if require_selection:
            add(
                "info",
                "sim-method-unrecorded",
                f"no method_selection recorded for property package {package!r}",
                ["property_package"],
                "record method_selection.facts (thermodynamic-model-selection) so the package "
                "is checked against the recommendation",
            )
        return found
    try:
        result = select_thermo_model(selection.facts)
    except InsufficientFactsError as err:
        add(
            "warning",
            "sim-method-selection",
            "method_selection.facts do not give a recommendation; missing: "
            + ", ".join(err.missing_facts),
            ["method_selection", "facts"],
            "add the missing facts (thermodynamic-model-selection asks for each)",
        )
        return found
    except ValueError as err:
        add(
            "warning",
            "sim-method-selection",
            f"method_selection.facts are invalid: {err}",
            ["method_selection", "facts"],
            "give the facts as select_thermo_model takes them",
        )
        return found
    recommended = [m.simulation.package for m in result.methods if m.simulation.executable]
    if package in recommended:
        return found
    offered = {
        m.simulation.substitution.package: m
        for m in reversed(result.methods)
        if m.simulation.substitution is not None
    }
    if package in offered:
        why = (
            f"a substitution for {offered[package].recommended} "
            f"(loses: {offered[package].simulation.substitution.loses})"
        )
    else:
        why = "neither recommended nor the table's substitute for a recommended model"
    if selection.substitution:
        add(
            "info",
            "sim-method-substituted",
            f"property package {package!r} is {why}; accepted: {selection.substitution}",
            ["method_selection", "substitution"],
            "the substitution stays visible; review it with the property method",
        )
        return found
    choices = recommended or sorted(offered)
    add(
        "warning",
        "sim-method-not-recommended",
        f"property package {package!r} is {why}; the recorded selection "
        f"({result.selected_outcome}) recommends {', '.join(result.models)}",
        ["property_package"],
        (
            "use " + " or ".join(choices) + ", or record method_selection.substitution with "
            "the reason the package is accepted"
            if choices
            else "no package the DWSIM route runs is recommended or a substitute for this "
            "regime (unsupported); record method_selection.substitution only with a reviewed "
            "reason"
        ),
    )
    return found


def _idaes_package_findings(sim: Simulation, add: Any, require_selection: bool) -> None:
    """:func:`property_package_findings` for the IDAES backend: a package it does not build is
    ``sim-property-package``; the recorded selection is compared by method (methods.yml id), as
    the IDAES packages are no DWSIM packages; no package of it is benchmarked
    (``sim-method-unbenchmarked``, info)."""
    from chemeascode.domains.process.thermodynamics.model_selection import select_thermo_model
    from chemeascode.domains.process.thermodynamics.rules import InsufficientFactsError

    package = sim.property_package
    entry = IDAES_PACKAGES.get(package)
    if entry is None:
        add(
            "error",
            "sim-property-package",
            f"property package {package!r} is not one the IDAES backend runs",
            ["property_package"],
            "use one of " + ", ".join(IDAES_PACKAGES) + " (simulation/backends.py), or "
            "simulator: dwsim",
        )
        return
    add(
        "info",
        "sim-method-unbenchmarked",
        f"property package {package!r} (IDAES backend; {entry['note']}) is not benchmarked by "
        "cheme-as-code: its results are not predictive",
        ["property_package"],
        "compare a run with a reference (a benchmarked package, measured data) before relying "
        "on it",
    )
    selection = sim.method_selection
    if selection is None:
        if require_selection:
            add(
                "info",
                "sim-method-unrecorded",
                f"no method_selection recorded for property package {package!r}",
                ["property_package"],
                "record method_selection.facts (thermodynamic-model-selection) so the package "
                "is checked against the recommendation",
            )
        return
    try:
        result = select_thermo_model(selection.facts)
    except (InsufficientFactsError, ValueError) as err:
        add(
            "warning",
            "sim-method-selection",
            f"method_selection.facts do not give a recommendation: {err}",
            ["method_selection", "facts"],
            "add or correct the facts (thermodynamic-model-selection asks for each)",
        )
        return
    recommended = [m.method for m in result.methods]
    if entry["method"] in recommended:
        return
    why = (
        f"method {entry['method']}, which the recorded selection ({result.selected_outcome}) "
        f"does not recommend (it recommends {', '.join(result.models)})"
    )
    if selection.substitution:
        add(
            "info",
            "sim-method-substituted",
            f"property package {package!r} is {why}; accepted: {selection.substitution}",
            ["method_selection", "substitution"],
            "the substitution stays visible; review it with the property method",
        )
    else:
        add(
            "warning",
            "sim-method-not-recommended",
            f"property package {package!r} is {why}",
            ["property_package"],
            "use a recommended method, or record method_selection.substitution with the reason "
            "the package is accepted",
        )
    return


def translate(process: Process, sim: Simulation, sim_doc: Any, case: str) -> Translation:
    """The simulator model of *case*, or the findings why it cannot be made."""
    fs = process.flowsheet
    out = Translation()
    out.findings += property_package_findings(sim, sim_doc)
    refused = any(f.level == "error" for f in out.findings)

    def add(level: str, rule: str, message: str, where: tuple[str, list[Any]], ids, hint=""):
        nonlocal refused
        file, loc = where
        doc = sim_doc if file == SIMULATION_FILE else process.flowsheet_doc
        out.findings.append(
            Finding(
                file,
                level,  # type: ignore[arg-type]
                f"cheme.process-{rule}",
                message,
                line=_yaml_line(doc, loc) if doc is not None else None,
                ids=list(ids),
                hint=hint,
            )
        )
        refused |= level == "error"

    index = {s.id: j for j, s in enumerate(fs.streams)}
    steps = {s.id: j for j, s in enumerate(fs.steps)}
    blocks = {b.id: j for j, b in enumerate(fs.blocks)}

    def at(node: str) -> tuple[str, list[Any]]:
        if node in sim.specs:
            return SIMULATION_FILE, ["specs", node]
        if node in steps:
            return FLOWSHEET_FILE, ["steps", steps[node]]
        return FLOWSHEET_FILE, ["blocks", blocks.get(node, 0)]

    left_out = set(sim.exclude)
    nodes = {
        n.id: n
        for n in [*fs.steps, *(b for b in fs.blocks if not process.inside(b.id))]
        if not any(process.within(n.id, x) for x in left_out)
    }

    def descend(end: End | None) -> End | None:
        """A block end, as the step port that delegates it."""
        seen = 0
        while end is not None and process.kinds.get(end.node) == "block" and seen <= len(nodes):
            inner = next(
                (
                    End(n.id, p.id)
                    for n in process.inside(end.node)
                    for p in n.ports
                    if p.delegates == end.port
                ),
                None,
            )
            if inner is None:
                return end
            end, seen = inner, seen + 1
        return end

    #: node -> [(port position, port id, stream)], material streams in and out
    ins: dict[str, list[tuple[int, str, StreamDef]]] = {n: [] for n in nodes}
    outs: dict[str, list[tuple[int, str, StreamDef]]] = {n: [] for n in nodes}
    #: node -> [(stream index, stream, whether it enters the node)], energy streams
    energy: dict[str, list[tuple[int, StreamDef, bool]]] = {n: [] for n in nodes}
    feeds: list[StreamDef] = []
    for i, stream in enumerate(fs.streams):
        a, b = (descend(e) for e in process.ends(stream))
        if stream.kind == "information" or a is None or b is None:
            continue
        if stream.kind == "energy":
            for e, entering in ((a, False), (b, True)):
                if e.node in nodes:
                    energy[e.node].append((i, stream, entering))
            continue
        for e, side in ((a, outs), (b, ins)):
            if e.node in nodes:
                ports = [p.id for p in nodes[e.node].ports]
                where = ports.index(e.port) if e.port in ports else 0
                side[e.node].append((where, e.port, stream))
            elif process.kinds.get(e.node) == "block" and not any(
                process.within(e.node, x) for x in left_out
            ):
                add(
                    "error",
                    "sim-unmapped",
                    f"stream {stream.id} ends at block port {e.node}.{e.port}, which no step "
                    "port delegates",
                    (FLOWSHEET_FILE, ["streams", i]),
                    [stream.id],
                    "connect the stream to a step port, or delegate the block port",
                )
        if a.node not in nodes and b.node not in nodes:
            continue  # outside the simulated part
        if a.node not in nodes:
            feeds.append(stream)  # from a feed, or from a step left out
        else:
            out.outlets.append(stream.id)

    # -- unit operations ------------------------------------------------------------------------
    units: list[dict[str, Any]] = []
    for node_id, node in nodes.items():
        spec = sim.specs.get(node_id, UnitSpec())
        inside = sorted(ins[node_id], key=lambda x: x[0])
        connected = sorted(outs[node_id], key=lambda x: x[0])
        unit = spec.unit or reactor_unit(node) or unit_of(node.class_, len(inside))
        if unit == "shortcut_column" and spec.stages is not None:
            if spec.unit == "shortcut_column":
                add(
                    "error",
                    "sim-spec",
                    f"{node_id} (shortcut_column): stages is a rigorous column's spec",
                    at(node_id),
                    [node_id],
                    f"remove specs.{node_id}.stages, or give unit: distillation_column",
                )
                continue
            unit = "distillation_column"
        if unit is None:
            add(
                "error",
                "sim-unmapped",
                f"{node_id} (class {node.class_}) maps to no unit operation",
                at(node_id),
                [node_id],
                f"give specs.{node_id}.unit in {SIMULATION_FILE} (one of "
                + ", ".join(SHAPES)
                + ")",
            )
            continue
        lo_in, hi_in, lo_out, hi_out = SHAPES[unit]
        if not (lo_in <= len(inside) <= hi_in and lo_out <= len(connected) <= hi_out):
            add(
                "error",
                "sim-unmapped",
                f"{node_id} ({unit}): {len(inside)} material stream(s) in, {len(connected)} "
                f"out; the unit takes {_range(lo_in, hi_in)} in and {_range(lo_out, hi_out)} out",
                at(node_id),
                [node_id],
                "split the step into several (e.g. cascaded splitters or mixers), or give "
                f"specs.{node_id}.unit",
            )
            continue
        in_ports = [p for _, p, _ in inside]
        out_ports = [p for _, p, _ in connected]
        stream_at = {p: s.id for _, p, s in connected}
        order, why, roles = out_ports, "", []
        if unit in (*REACTORS.values(), KINETIC) and len(out_ports) == 1:
            roles = ["vapor"]  # the worker adds the liquid outlet and checks it stays empty
        elif unit in ROLES:
            # side draws are named in the spec; the rest are the column's products
            drawn = [p for p in out_ports if p in spec.side_draws]
            order, why = _roles(unit, spec, [p for p in out_ports if p not in drawn])
            if order is not None:
                roles = list(wanted_roles(unit, spec))
                order += drawn
        elif unit in ("heat_exchanger", "multi_stream_exchanger"):
            order, why = _pairs(spec, in_ports, out_ports)
        elif unit in CONDENSING and len(out_ports) == 2:
            order, why = _condensate(unit, spec, out_ports)
            roles = list(CONDENSATE_ROLES)
        if order is None:
            add(
                "error",
                "sim-spec",
                f"{node_id} ({unit}): {why}",
                at(node_id),
                [node_id],
                f"give specs.{node_id}."
                + (
                    "pairs: {inlet port: outlet port}"
                    if "exchanger" in unit
                    else "outlet_temperature (the coolers that condense), or remove the second "
                    "outlet"
                    if unit == "compressor" and spec.outlet_temperature is None
                    else "outlets: {port: condensate}"
                    if unit in CONDENSING
                    else "outlets: {port: " + " | ".join(wanted_roles(unit, spec)) + "}"
                ),
            )
            continue
        kind_basis = UNIT_BASIS.get(unit)
        if spec.basis is not None and kind_basis is not None and spec.basis != kind_basis:
            add(
                "error",
                "sim-spec",
                f"{node_id} ({unit}): basis {spec.basis}, but a {unit} is {kind_basis}",
                at(node_id),
                [node_id],
                f"remove specs.{node_id}.basis, or model the step with a unit that is {spec.basis}",
            )
            continue
        if unit in SPECIFIED_SPLITS and not (spec.basis_source or "").strip():
            add(
                "warning",
                "sim-specified-unsourced",
                f"{node_id} ({unit}): the recoveries are specified, not predicted, and name no "
                "source; a converged simulation does not show they are attainable",
                at(node_id),
                [node_id],
                f"give specs.{node_id}.basis_source (vendor data, a cited module, a DESIGN.md "
                "decision) and operating_basis (the conditions they hold for)",
            )
        out.bases[node_id] = {
            "basis": spec.basis or kind_basis,
            **({"source": spec.basis_source} if spec.basis_source else {}),
            **({"operating_basis": spec.operating_basis} if spec.operating_basis else {}),
        }
        connected_streams = [s for _, _, s in inside + connected]
        values = _spec(
            process,
            node,
            unit,
            spec,
            out_ports,
            add,
            at(node_id),
            in_ports,
            connected_streams,
            case,
        )
        if values is None:
            continue
        cooled = unit == "compressor" and spec.outlet_temperature is not None
        energies = _energy(node_id, unit, energy[node_id], out, add, cooled)
        if energies is None:
            continue
        absent = [
            role
            for role, gone in (
                ("condenser", unit == "distillation_column" and spec.condenser == "none"),
                ("reboiler", unit == "distillation_column" and not spec.reboiler),
            )
            if gone
        ]
        for role in absent:
            stream = energies.pop(role, None)
            if stream is not None:
                out.energies.pop(stream, None)
                add(
                    "info",
                    "sim-energy-ignored",
                    f"energy stream {stream} at {node_id}: the column has no {role}; not simulated",
                    at(node_id),
                    [stream],
                    "remove the stream, or give the column its " + role,
                )
        units.append(
            {
                "id": node_id,
                "type": unit,
                "inlets": [s.id for _, _, s in inside],
                "outlets": [stream_at[p] for p in order],
                # roles for the units the worker connects by them (a flash's and a shortcut
                # column's order is fixed, and their model, so their fingerprint, stays as it was)
                **(
                    {"roles": roles}
                    if unit == "distillation_column"
                    or unit in CONDENSING
                    or unit in (*REACTORS.values(), KINETIC)
                    else {}
                ),
                "energies": energies,
                "spec": values,
            }
        )

    by_id = {u["id"]: u for u in units}
    for u in units:
        link = u["spec"].get("heat_integration")
        if not link:
            continue
        other = by_id.get(link["condenser_of"])
        if (
            other is None
            or other is u
            or other["type"] != "distillation_column"
            or other["spec"].get("condenser") == "none"
        ):
            add(
                "error",
                "sim-spec",
                f"{u['id']}: heat_integration.condenser_of {link['condenser_of']} is no other "
                "simulated rigorous column with a condenser",
                at(u["id"]),
                [u["id"]],
                "name the step of the column whose condenser heats this reboiler",
            )

    tears, why = _tears(units, sim.tear_streams)
    if tears is None:
        add(
            "error",
            "sim-recycle",
            why,
            (SIMULATION_FILE, ["tear_streams"]),
            sim.tear_streams,
            "name one stream of every recycle loop in tear_streams, or leave it out",
        )
        tears = []
    for sid in tears:
        add(
            "info",
            "sim-recycle",
            f"recycle loop torn at stream {sid}: solved iteratively "
            + ("(IDAES tear stream)" if sim.simulator == IDAES else "(DWSIM Recycle)")
            + ("" if sim.tear_streams else ", chosen by cheme-as-code"),
            (FLOWSHEET_FILE, ["streams", index[sid]]),
            [sid],
            "its values in the flowsheet, if any, are the first guess; tear_streams chooses "
            "another stream",
        )

    # -- feeds and compounds --------------------------------------------------------------------
    comps = process.components()
    streams_by_id = {s.id: s for s in fs.streams}
    streams: list[dict[str, Any]] = []
    used: set[str] = set()
    for stream in feeds:
        i = index[stream.id]
        state = stream.state.get(case)
        # values an earlier run simulated are inputs where they come from a part left out
        earlier_ok = process.kinds.get(process.end(stream.from_).node) != "feed"
        lacking = [
            name
            for name in ("temperature", "pressure", "flow", "composition")
            if state is None
            or getattr(state, name) is None
            or (ours(getattr(state, name)) and not earlier_ok)
        ]
        if lacking:
            add(
                "error",
                "sim-feed-incomplete",
                f"feed stream {stream.id} ({case}) lacks {', '.join(lacking)}",
                (FLOWSHEET_FILE, ["streams", i, "state", case] if state else ["streams", i]),
                [stream.id],
                "give them (provenance given or assumed)",
            )
            continue
        assert state is not None and state.composition is not None
        kelvin = to_kelvin(state.temperature.value, state.temperature.unit or fs.units.temperature)
        unit = state.pressure.unit or fs.units.pressure
        kpa = to_kpa_abs(state.pressure.value, unit)
        flows = stream_flows(process, stream, case)
        fractions = _mole_fractions(state.composition, comps)
        problems = []
        if kelvin is None:
            problems.append("temperature unit")
        if kpa is None:
            problems.append(f"pressure unit {unit} (not absolute)")
        if flows.total is None:
            problems += flows.missing
        if fractions is None:
            problems.append("molar masses for the mass fractions")
        if problems:
            add(
                "error",
                "sim-feed-incomplete",
                f"feed stream {stream.id} ({case}): cannot convert {', '.join(problems)}",
                (FLOWSHEET_FILE, ["streams", i, "state", case]),
                [stream.id],
                "use K or °C, an absolute pressure unit, and give the molar masses in "
                "process/materials.yaml",
            )
            continue
        assert kelvin is not None and kpa is not None and flows.total is not None and fractions
        used |= set(fractions)
        streams.append(
            {
                "id": stream.id,
                "kind": "material",
                "feed": {
                    "temperature_K": kelvin,
                    "pressure_Pa": kpa * 1000.0,
                    "mass_flow_kg_s": flows.total / 3600.0,
                    "mole_fractions": fractions,
                },
            }
        )
    streams += [{"id": s, "kind": "material", "feed": None} for s in out.outlets]
    recycles = [
        {"stream": sid, "guess": _guess(process, streams_by_id[sid], case, comps, sim)}
        for sid in tears
    ]
    streams += [{"id": e, "kind": "energy", "feed": None} for e in out.energies]
    for u in units:
        if u["type"] in (*REACTORS.values(), KINETIC):
            used |= set(u["spec"].get("components", []))
            used |= {n for r in u["spec"].get("reactions", []) for n in r["stoichiometry"]}
    unknown = sorted(n for n in used if n not in comps)
    for name in unknown:
        add(
            "error",
            "sim-feed-incomplete",
            f"component {name} is not in process/materials.yaml",
            (FLOWSHEET_FILE, ["streams"]),
            [name],
            "add it to process/materials.yaml with its CAS number",
        )
    for name in sorted(n for n in used if getattr(comps.get(n), "phase", None) == "solid"):
        add(
            "error",
            "sim-solid",
            f"component {name} is a solid (phase: solid): the simulation has no solid phase "
            "and would treat it as a fluid",
            (FLOWSHEET_FILE, ["streams"]),
            [name],
            "leave the crystallizer, filter and slurry streams out of process/simulation.yaml "
            "(cheme process propagate solves them)",
        )
    for u in units:
        keys = [u["spec"].get("light_key"), u["spec"].get("heavy_key")]
        keys += [
            (u["spec"].get(e) or {}).get("component") for e in ("condenser_spec", "reboiler_spec")
        ]
        for key, name in zip(
            ("light_key", "heavy_key", "condenser_spec", "reboiler_spec"), keys, strict=True
        ):
            if name is not None and name not in used:
                add(
                    "error",
                    "sim-spec",
                    f"{u['id']} ({u['type']}): {key} {name} is in no feed",
                    at(u["id"]),
                    [u["id"]],
                    "choose a key component the feeds carry",
                )
    guess = [comps[n].molar_mass for n in used if n in comps and comps[n].molar_mass]
    for u in units:
        if u["type"] == "distillation_column":
            # where mass flows start from; a solver hint, not an input (out of the fingerprint)
            u["spec"]["mw_guess"] = sum(guess) / len(guess) if guess else 28.96
    compounds = [
        {"id": c.id, "cas": c.cas, "name": sim.components.get(c.id), "title": c.name}
        for c in comps.values()
        if c.id in used
    ]
    # no property package of the route models ions: a salt, acid or base in water would be
    # computed as a neutral molecule (electrolytes.yml: apparent_electrolytes, and by formula
    # ionic_elements)
    salts = dissolved_electrolytes(
        [c["cas"] for c in compounds],
        {comps[c["id"]].cas: comps[c["id"]].formula for c in compounds},
        {c["cas"]: c["title"] for c in compounds},
    )
    if salts:
        cas = {e.cas for e in salts}
        add(
            "error",
            "sim-electrolyte",
            f"{', '.join(e.name for e in salts)} with water: the DWSIM route has no electrolyte "
            f"property package and would compute {'them' if len(salts) > 1 else 'it'} as a "
            "neutral molecule",
            (SIMULATION_FILE, ["property_package"]),
            [c["id"] for c in compounds if c["cas"] in cas],
            refusal_hint(salts) + "; a mass balance with specified splits needs no property "
            "package (basis: specified)",
        )
    pairs = []
    for k, p in enumerate(sim.interaction_parameters):
        stray = [c for c in p.components if c not in used]
        pair = sorted(p.components)
        if sim.property_package not in EOS_PACKAGES:
            why = f"the {sim.property_package} package has none"
        elif p.components[0] == p.components[1]:
            why = f"{p.components[0]} with itself"
        elif stray:
            why = f"{', '.join(stray)} in no feed"
        elif any(q["components"] == pair for q in pairs):
            why = "given twice"
        else:
            pairs.append({"components": pair, "kij": p.kij.value})
            continue
        add(
            "error",
            "sim-spec",
            f"interaction parameter {' / '.join(p.components)}: {why}",
            (SIMULATION_FILE, ["interaction_parameters", k]),
            list(p.components),
            "kij are for the equation-of-state packages ("
            + ", ".join(EOS_PACKAGES)
            + ") and two different components of the feeds",
        )
    if refused:
        return out
    out.model = {
        "case": case,
        "property_package": sim.property_package,
        "compounds": compounds,
        "streams": streams,
        "units": units,
        "recycles": recycles,
    }
    if pairs:  # a model without them keeps the fingerprint it had before
        # in a fixed order: reordering the list or a pair changes nothing
        out.model["interaction_parameters"] = sorted(pairs, key=lambda q: q["components"])
    if sim.simulator == IDAES:  # a DWSIM model keeps the fingerprint it had before
        out.model["simulator"] = IDAES
        found = backend_findings(out.model, sim, sim_doc)
        if found:
            out.findings += found
            out.model = None
            return out
    out.fingerprint = fingerprint(out.model)
    return out


def _energy(
    node_id: str,
    unit: str,
    attached: list[tuple[int, StreamDef, bool]],
    out: Translation,
    add,
    cooled: bool = False,
) -> dict[str, str | None] | None:
    """The energy streams of one unit by role (``energy``; the column's ``reboiler`` and
    ``condenser``; a *cooled* compressor's ``energy`` and ``cooling``), or None after adding
    why they do not fit."""
    if unit not in ENERGY_UNITS:
        for i, e, _ in attached:
            add(
                "info",
                "sim-energy-ignored",
                f"energy stream {e.id} at {node_id} ({unit}): the unit has no duty; not simulated",
                (FLOWSHEET_FILE, ["streams", i]),
                [e.id],
                f"attach it to a unit with a duty or power, or give specs.{node_id}.unit",
            )
        return {}
    direction = DIRECTION.get(unit)
    two_way = unit in COLUMNS or cooled
    if not two_way and direction is not None:
        for i, e, entering in [x for x in attached if x[2] != direction]:
            add(
                "info",
                "sim-energy-ignored",
                f"energy stream {e.id} at {node_id} ({unit}): runs "
                + ("into" if entering else "out of")
                + " the unit, its duty "
                + ("into" if direction else "out of")
                + " it; not simulated",
                (FLOWSHEET_FILE, ["streams", i]),
                [e.id],
                "the duty of a second service (cooling water of a machine, pump power of a "
                "cooler) is not simulated; give it yourself",
            )
        attached = [x for x in attached if x[2] == direction]
    if unit in COLUMNS:
        roles = {
            "reboiler": [x for x in attached if x[2]],
            "condenser": [x for x in attached if not x[2]],
        }
        keys = {"reboiler": "reboiler_kW", "condenser": "condenser_kW"}
    elif cooled:
        roles = {
            "energy": [x for x in attached if x[2]],
            "cooling": [x for x in attached if not x[2]],
        }
        keys = {"energy": "duty_kW", "cooling": "cooling_kW"}
    else:
        roles = {"energy": attached}
        keys = {"energy": "duty_kW"}
    found: dict[str, str | None] = {}
    ok = True
    for role, items in roles.items():
        for i, e, _ in items[1:]:
            add(
                "error",
                "sim-unmapped",
                f"{node_id} ({unit}) has more than one {role} energy stream ({items[0][1].id}, "
                f"{e.id})",
                (FLOWSHEET_FILE, ["streams", i]),
                [node_id, e.id],
                "keep one energy stream per duty",
            )
            ok = False
        found[role] = items[0][1].id if items else None
        for i, e, entering in items[:1]:
            if e.id in out.energies:
                add(
                    "error",
                    "sim-unmapped",
                    f"energy stream {e.id} connects two units ({out.energies[e.id][0]}, {node_id})",
                    (FLOWSHEET_FILE, ["streams", i]),
                    [e.id],
                    "give each unit its own energy stream",
                )
                ok = False
            out.energies[e.id] = (node_id, keys[role])
            (out.entering.add if entering else out.entering.discard)(e.id)
    return found if ok else None


def _mole_fractions(comp: Any, comps: dict[str, Any]) -> dict[str, float] | None:
    values = {k: v for k, v in comp.values.items() if v > TRACE}
    if comp.basis == "mass_fraction":
        if any(not getattr(comps.get(k), "molar_mass", None) for k in values):
            return None
        values = {k: v / comps[k].molar_mass for k, v in values.items()}
    total = sum(values.values())
    if total <= 0:
        return None
    return {k: v / total for k, v in values.items()}


def _tears(units: list[dict[str, Any]], given: list[str]) -> tuple[list[str] | None, str]:
    """Streams to tear so that no material loop is left: *given*, checked, or the streams that
    close a loop in a depth-first walk in flowsheet order. None and why when *given* leave a
    loop or name a stream between no two units."""
    source = {s: u["id"] for u in units for s in u["outlets"]}
    inside = {s for u in units for s in u["inlets"] if s in source}
    if given:
        stray = [s for s in given if s not in inside]
        if stray:
            return None, f"tear_streams: {', '.join(stray)} run between no two simulated units"
        if len(set(given)) != len(given):
            return None, "tear_streams names a stream twice"
        if loop := _loop(units, set(given)):
            return None, "tear_streams leave a recycle loop: " + " -> ".join(loop)
        return list(given), ""
    after = {u["id"]: [s for s in u["outlets"] if s in inside] for u in units}
    into = {s: u["id"] for u in units for s in u["inlets"] if s in inside}
    state: dict[str, int] = {}  # 1 on the path, 2 done
    tears: list[str] = []

    def walk(node: str) -> None:
        state[node] = 1
        for s in after[node]:
            nxt = into[s]
            if state.get(nxt) == 1:
                tears.append(s)
            elif nxt not in state:
                walk(nxt)
        state[node] = 2

    for u in units:
        if u["id"] not in state:
            walk(u["id"])
    return tears, ""


def _loop(units: list[dict[str, Any]], torn: set[str]) -> list[str]:
    """The units of one material loop left after tearing *torn*; empty when there is none."""
    source = {s: u["id"] for u in units for s in u["outlets"] if s not in torn}
    after = {u["id"]: {source[s] for s in u["inlets"] if s in source} for u in units}
    left = dict(after)
    while True:
        ready = [u for u, before in left.items() if not (before & set(left))]
        if not ready:
            return sorted(left)
        for u in ready:
            del left[u]
        if not left:
            return []


def _guess(
    process: Process, stream: StreamDef, case: str, comps: dict[str, Any], sim: Simulation
) -> dict | None:
    """The first guess of a tear stream, in SI: ``guesses:`` in simulation.yaml, else its values
    in the flowsheet (any provenance, the last simulation's included); None without either."""
    fs = process.flowsheet
    state = sim.guesses.get(stream.id) or stream.state.get(case)
    if state is None:
        return None
    guess: dict[str, Any] = {}
    if state.temperature is not None:
        guess["temperature_K"] = to_kelvin(
            state.temperature.value, state.temperature.unit or fs.units.temperature
        )
    if state.pressure is not None:
        kpa = to_kpa_abs(state.pressure.value, state.pressure.unit or fs.units.pressure)
        guess["pressure_Pa"] = kpa * 1000.0 if kpa is not None else None
    alone = stream.model_copy(update={"state": {case: state}})
    total = stream_flows(process, alone, case).total if state.flow is not None else None
    if total is not None:
        guess["mass_flow_kg_s"] = total / 3600.0
    if state.composition is not None:
        guess["mole_fractions"] = _mole_fractions(state.composition, comps)
    guess = {k: v for k, v in guess.items() if v is not None}
    return guess or None


def _product(spec: Any, end: str, fail: Any, kw: Any, kelvin: Any, fs: Any) -> dict | None:
    """One end's specification of a rigorous column as DWSIM takes it: ``type`` (DWSIM's spec
    type), ``value``, ``unit`` (DWSIM's unit string) and ``component``."""
    if spec is None:
        return None
    given = [
        n
        for n in ("reflux_ratio", "flow", "mole_fraction", "duty", "temperature")
        if getattr(spec, n) not in (None, {})
    ]
    if len(given) != 1:
        fail(
            f"{end}_spec: give exactly one of reflux_ratio, flow, mole_fraction, duty, temperature"
        )
        return None
    if spec.reflux_ratio is not None:
        if end != "condenser":
            fail("reflux_ratio is a condenser spec")
            return None
        return {"type": "Stream_Ratio", "value": spec.reflux_ratio, "unit": "", "component": None}
    if spec.flow is not None:
        unit = spec.flow.unit or fs.units.flow
        basis, factor = FLOW_UNITS.get(unit, (None, 1.0))
        if basis == "mass":
            return {
                "type": "Product_Mass_Flow_Rate",
                "value": spec.flow.value * factor,
                "unit": "kg/h",
                "component": None,
            }
        if basis == "mole":
            return {
                "type": "Product_Molar_Flow_Rate",
                "value": spec.flow.value * factor,
                "unit": "kmol/h",
                "component": None,
            }
        fail(f"{end}_spec.flow: unit {unit} is neither a mass nor a molar flow")
        return None
    if spec.mole_fraction:
        if len(spec.mole_fraction) != 1:
            fail(f"{end}_spec.mole_fraction names one component")
            return None
        name, value = next(iter(spec.mole_fraction.items()))
        if not 0 < value < 1:
            fail(f"{end}_spec.mole_fraction {value:g} is not between 0 and 1")
            return None
        return {"type": "Component_Fraction", "value": value, "unit": "M", "component": name}
    if spec.duty is not None:
        value = kw(spec.duty)
        return (
            None
            if value is None
            else {"type": "Heat_Duty", "value": abs(value), "unit": "kW", "component": None}
        )
    value = kelvin(spec.temperature)
    return (
        None
        if value is None
        else {"type": "Temperature", "value": value, "unit": "K", "component": None}
    )


def _flow_of(q: Quantity, fs: Any, fail: Any) -> dict[str, Any]:
    """A flow as ``{"value", "basis"}``: kg/h (mass) or kmol/h (molar)."""
    unit = q.unit or fs.units.flow
    basis, factor = FLOW_UNITS.get(unit, (None, 1.0))
    if basis not in ("mass", "mole"):
        fail(f"flow unit {unit} is neither a mass nor a molar flow")
        return {"value": 0.0, "basis": "mole"}
    return {"value": q.value * factor, "basis": basis}


def _range(lo: int, hi: int) -> str:
    return str(lo) if lo == hi else f"{lo} to {hi}"


def _reactor_spec(
    process: Process,
    node: Any,
    unit: str,
    spec: UnitSpec,
    fail: Any,
    kelvin: Any,
    delta_pa: Any,
    add: Any,
    where: tuple[str, list[Any]],
    streams: list[StreamDef],
    case: str | None,
) -> dict[str, Any]:
    """The specs of a reactor: its mode, outlet temperature, pressure drop and reactions (from
    process/reactions.yaml and the flowsheet step), or the Gibbs reactor's components.
    *streams*: its material streams, block ports resolved."""
    from chemeascode.domains.chemistry.reactions import key_component

    outlet_t = spec.outlet_temperature
    outlets = [s for s in streams if (e := process.end(s.from_)) and e.node == node.id]
    if spec.mode is None and outlet_t is None and case is not None:
        # the outlet temperature the flowsheet gives (what propagate takes the equilibrium at)
        given = [
            q
            for s in outlets
            if (q := getattr(s.state.get(case), "temperature", None)) is not None and not ours(q)
        ]
        if len(given) == 1:
            outlet_t = given[0]
            add(
                "info",
                "sim-default",
                f"{node.id} ({unit}): mode outlet_temperature at the flowsheet's outlet "
                f"temperature ({outlet_t.value:g})",
                where,
                [node.id],
                f"give specs.{node.id}.mode (isothermal, adiabatic) to simulate otherwise",
            )
    mode = spec.mode or ("outlet_temperature" if outlet_t is not None else "isothermal")
    if mode == "outlet_temperature" and outlet_t is None:
        fail("mode outlet_temperature without outlet_temperature")
    if mode != "outlet_temperature" and spec.outlet_temperature is not None:
        fail(f"outlet_temperature with mode {mode}", "give mode: outlet_temperature, or remove it")
    if spec.pressure_drop is None:
        add(
            "info",
            "sim-default",
            f"{node.id} ({unit}): pressure_drop not given, 0 used",
            where,
            [node.id],
            f"give specs.{node.id}.pressure_drop",
        )
    kelvin_out = kelvin(outlet_t) if mode == "outlet_temperature" else None
    values: dict[str, Any] = {
        "mode": mode,
        "outlet_temperature_K": kelvin_out,
        "pressure_drop_Pa": delta_pa(spec.pressure_drop) or 0.0,
    }
    reactions, unknown = process.reactions_of(node.id)
    if unknown:
        fail(f"reactions {', '.join(unknown)} are not declared in process/reactions.yaml")
    approach = getattr(node, "approach", 0.0) or 0.0
    if unit == "gibbs_reactor":
        if approach:
            fail("DWSIM's Gibbs reactor takes no approach", "remove approach, or use equilibrium")
        # as propagate: the templates' components and those the streams' compositions name
        names: list[str] = []
        for stream in streams:
            template = process.templates().get(stream.template or "")
            names += [n for n in (template.components if template else []) if n not in names]
            comp = getattr(stream.state.get(case), "composition", None) if case else None
            names += [n for n in (comp.values if comp else {}) if n not in names]
        if not names:
            fail("its streams name no components: the Gibbs reactor's components are not known")
        return values | {"components": names}
    if not reactions:
        fail("names no reactions", "give reactions: [ID, ...] on the step")
    entries = []
    if getattr(node, "selectivity", None) is not None:
        fail(
            "DWSIM takes a conversion per reaction; this step gives a selectivity",
            "give the step conversion: per reaction (cheme process reactors prints the "
            "extents), or leave it to cheme process propagate",
        )
        return values
    for r in reactions:
        key = key_component(r) or next(n for n, v in r.stoichiometry.items() if v < 0)
        entry: dict[str, Any] = {
            "id": r.id,
            "stoichiometry": dict(r.stoichiometry),
            "phase": r.phase or "vapor",
            "base": key,
        }
        if unit == "conversion_reactor":
            rate = node.conversion.get(r.id, r.conversion.value if r.conversion else None)
            if rate is None or key_component(r) is None:
                fail(f"reaction {r.id} has no conversion (and key component)")
                continue
            entry |= {"type": "conversion", "conversion": rate}
        else:
            k = r.equilibrium_constant
            if r.phase == "liquid" or (k is not None and k.basis != "partial_pressure"):
                fail(
                    f"reaction {r.id}: DWSIM takes the equilibrium constant on partial pressures; "
                    f"this one is {'liquid-phase' if r.phase == 'liquid' else 'on ' + k.basis}",
                    "simulate the step as a conversion reactor, or leave it to cheme process "
                    "propagate",
                )
                continue
            if k is not None and kelvin_out is not None and not k.covers(kelvin_out + approach):
                fail(
                    f"reaction {r.id}: {kelvin_out + approach:.6g} K is outside its "
                    "equilibrium_constant temperature_range",
                    "give a correlation for this temperature, or remove the range",
                )
            # DWSIM's expression language: log is the natural logarithm; an expression it does
            # not parse falls back to its own Gibbs energies without a message, so only + - * /
            # and log are written (each checked against DWSIM 9.0.5)
            expression = (
                f"{k.a!r} + {k.b!r}/T + {k.c!r}*log(T) + {k.d!r}*T" if k is not None else ""
            )
            entry |= {"type": "equilibrium", "approach_K": approach, "ln_k": expression}
        entries.append(entry)
    return values | {"reactions": entries}


def _kinetic_spec(process: Process, node: Any, spec: UnitSpec, fail: Any) -> dict[str, Any]:
    """The spec of a fixed bed coupled to the DWSIM solve as an external unit
    (:mod:`.coupling`): its reactions (each with a rate law), the outer loop's settings, and
    the fingerprint of everything the bed's solution depends on besides its inlet (bed,
    catalyst, rate laws, ideal-gas data, molar masses), so that a changed rate law makes the
    simulated values stale. The bed sets the outlet temperature and the pressure drop."""
    from chemeascode.domains.process.fixed_bed import BedError, bed_of

    given = [
        name
        for name in ("mode", "outlet_temperature", "pressure_drop", "duty")
        if getattr(spec, name) is not None
    ]
    if given:
        what = "bed" if getattr(node, "reactor", None) == "pfr" else node.reactor
        fail(
            f"{', '.join(given)}: the {what} model sets the outlet of a kinetic reactor",
            f"remove {', '.join(given)} from specs.{node.id}; the step's {what} decides",
        )
    if getattr(node, "reactor", None) in ("cstr", "batch"):
        return _tank_spec(process, node, spec, fail)
    try:
        reactions, catalyst = bed_of(process, node)
    except BedError as failure:
        fail(str(failure), "give the step bed:, catalyst: and reactions: (see the reactions skill)")
        return {}
    if not reactions:
        fail("names no reactions", "give reactions: [ID, ...] on the step")
    lacking = [r.id for r in reactions if r.rate is None]
    if lacking:
        fail(
            f"no rate law for reaction {', '.join(lacking)}",
            "give each reaction a rate: in process/reactions.yaml",
        )
    liquid = [r.id for r in reactions if r.phase not in (None, "vapor")]
    if liquid:
        fail(
            f"the bed model is ideal gas; reaction {', '.join(liquid)} is not a vapour reaction",
            "use a conversion or equilibrium reactor for liquid-phase reactions",
        )
    comps = process.components()
    names = sorted(
        {n for r in reactions for n in r.stoichiometry}
        | {n for r in reactions if r.rate for n in r.rate.species()}
    )
    data = process.ideal_gas()
    settings = spec.coupling or KineticCoupling()
    inputs = {
        "bed": node.bed.model_dump(mode="json"),
        "catalyst": catalyst.physical.model_dump(mode="json") if catalyst.physical else None,
        "reactions": [r.inputs_dump() for r in reactions],
        "ideal_gas": {n: data[n].model_dump(mode="json") if data.get(n) else None for n in names},
        "molar_mass": {c.id: c.molar_mass for c in comps.values()},
    }
    if node.bed.time_on_stream and catalyst.deactivation:  # an aged bed: its law enters
        inputs["deactivation"] = catalyst.deactivation.model_dump(mode="json")
    return {
        "coupling": "external-unit",
        "model": "cheme fixed bed (1D pseudo-homogeneous plug flow, ideal gas)",
        "reactions": [
            {"id": r.id, "stoichiometry": dict(r.stoichiometry), "phase": "vapor"}
            for r in reactions
        ],
        "tolerance": settings.tolerance,
        "temperature_tolerance": settings.temperature_tolerance,
        "max_iterations": settings.max_iterations,
        "bed_fingerprint": value_fingerprint(inputs),
    }


def _tank_spec(process: Process, node: Any, spec: UnitSpec, fail: Any) -> dict[str, Any]:
    """The spec of a stirred tank or batch coupled to the DWSIM solve as an external unit
    (:mod:`.coupling`), as :func:`_kinetic_spec` for a bed: its reactions, the loop's settings
    and the fingerprint of what the tank's solution depends on besides its inlet."""
    kind = node.reactor
    field_name = "tank" if kind == "cstr" else "batch"
    if getattr(node, field_name) is None:
        fail(
            f"reactor {kind} without {field_name}:",
            f"give the step {field_name}: (reactions skill)",
        )
        return {}
    reactions, unknown = process.reactions_of(node.id)
    if unknown or not reactions:
        fail("names no declared reactions", "give reactions: [ID, ...] on the step")
        return {}
    if lacking := [r.id for r in reactions if r.rate is None]:
        fail(f"no rate law for reaction {', '.join(lacking)}", "give each reaction a rate:")
        return {}
    phases = {r.phase or "vapor" for r in reactions}
    if len(phases) > 1 or "mixed" in phases:
        fail("gas-phase and liquid-phase reactions together", "one phase per tank")
        return {}
    from chemeascode.domains.process.stirred_tank import TankError, tank_inputs

    names = sorted({n for r in reactions for n in r.stoichiometry})
    try:
        inputs = tank_inputs(process, node, reactions, names)
    except TankError as failure:
        fail(str(failure), "give the step's catalyst its deactivation law")
        return {}
    settings = spec.coupling or KineticCoupling()
    phase = phases.pop()
    return {
        "coupling": "external-unit",
        "model": (
            f"cheme stirred tank{'s' if kind == 'cstr' and node.tank.count > 1 else ''} "
            f"(ideal mixing, {phase})"
            if kind == "cstr"
            else f"cheme batch (the charge's composition at the end, {phase})"
        ),
        "reactions": [
            {"id": r.id, "stoichiometry": dict(r.stoichiometry), "phase": phase} for r in reactions
        ],
        "tolerance": settings.tolerance,
        "temperature_tolerance": settings.temperature_tolerance,
        "max_iterations": settings.max_iterations,
        "bed_fingerprint": value_fingerprint(inputs),
    }


def _spec(
    process: Process,
    node: Any,
    unit: str,
    spec: UnitSpec,
    out_ports: list[str],
    add: Any,
    where: tuple[str, list[Any]],
    in_ports: list[str] | None = None,
    streams: list[StreamDef] | None = None,
    case: str | None = None,
) -> dict[str, Any] | None:
    """The SI specifications of one unit (*out_ports*: the ports of its connected outlets, in
    order), or None after adding why they do not fit."""
    fs = process.flowsheet
    ok = True
    here = f"specs.{node.id} in {SIMULATION_FILE}"

    def fail(message: str, hint: str = "") -> None:
        nonlocal ok
        add("error", "sim-spec", f"{node.id} ({unit}): {message}", where, [node.id], hint or here)
        ok = False

    def pa(q: Quantity | None) -> float | None:
        if q is None:
            return None
        kpa = to_kpa_abs(q.value, q.unit or fs.units.pressure)
        if kpa is None:
            fail(
                f"pressure unit {q.unit or fs.units.pressure} is not absolute",
                f"give an absolute unit (kPa(a), bar(a)) under {here}",
            )
            return None
        return kpa * 1000.0

    def delta_pa(q: Quantity | None) -> float | None:
        if q is None:
            return None
        unit_ = pressure_kind(q.unit or fs.units.pressure)[0]
        if q.value < 0:
            fail(f"pressure difference {q.value:g} is negative", f"give it positive ({here})")
            return None
        try:
            return convert_units(q.value, unit_, "Pa")
        except UnitError:
            fail(
                f"pressure difference unit {q.unit} is unknown", f"use Pa, kPa, bar or MPa ({here})"
            )
            return None

    def kelvin(q: Quantity | None) -> float | None:
        if q is None:
            return None
        value = to_kelvin(q.value, q.unit or fs.units.temperature)
        if value is None:
            fail(f"temperature unit {q.unit} is unknown", f"use K or °C ({here})")
        return value

    def delta_k(q: Quantity) -> float:
        unit = q.unit or "K"
        if unit not in ("K", "°C"):
            fail(f"temperature difference unit {unit} is unknown", f"use K ({here})")
        return q.value

    def kw(q: Quantity | None) -> float | None:
        if q is None:
            return None
        factor = DUTY_UNITS.get(q.unit or fs.units.duty)
        if factor is None:
            fail(f"duty unit {q.unit} is unknown", f"use W, kW or MW ({here})")
            return None
        return q.value * factor

    def efficiency(q: Quantity | None) -> float | None:
        if q is None:
            return None
        value = q.value / 100.0 if q.unit == "%" else q.value
        if not 0 < value <= 1:
            fail(f"efficiency {q.value:g}{q.unit or ''} is not between 0 and 1")
        return value

    def one_of(*names: str) -> None:
        given = [n for n in names if getattr(spec, n) is not None]
        if len(given) != 1:
            fail(
                f"give exactly one of {', '.join(names)}"
                + (f" (given: {', '.join(given)})" if given else ""),
            )

    values: dict[str, Any] = {}
    if unit in ("compressor", "pump"):
        one_of("outlet_pressure", "pressure_increase")
        if spec.efficiency is None:
            fail("efficiency is not given", f"give specs.{node.id}.efficiency (adiabatic, 0 to 1)")
        values = {
            "outlet_pressure_Pa": pa(spec.outlet_pressure),
            "pressure_increase_Pa": delta_pa(spec.pressure_increase),
            "efficiency": efficiency(spec.efficiency),
        }
        if unit == "compressor" and (spec.stages or spec.outlet_temperature):
            # a machine with intercoolers: stages of equal pressure ratio, each cooled to the
            # outlet temperature (the last by the aftercooler)
            if spec.outlet_temperature is None:
                fail(
                    "stages without outlet_temperature",
                    f"give specs.{node.id}.outlet_temperature (after each intercooler)",
                )
            values |= {
                "stages": spec.stages or 1,
                "outlet_temperature_K": kelvin(spec.outlet_temperature),
                "cooler_pressure_drop_Pa": delta_pa(spec.pressure_drop) or 0.0,
            }
    elif unit in ("heater", "cooler"):
        one_of("outlet_temperature", "duty")
        if unit == "cooler" and spec.duty is not None and spec.duty.value > 0:
            fail(
                f"duty {spec.duty.value:g} adds heat",
                "a cooler's duty is the heat added, so negative; or make the step a heater",
            )
        if spec.pressure_drop is None:
            add(
                "info",
                "sim-default",
                f"{node.id} ({unit}): pressure_drop not given, 0 used",
                where,
                [node.id],
                f"give specs.{node.id}.pressure_drop",
            )
        values = {
            "outlet_temperature_K": kelvin(spec.outlet_temperature),
            "duty_kW": kw(spec.duty),
            "pressure_drop_Pa": delta_pa(spec.pressure_drop) or 0.0,
        }
    elif unit == "expander":
        one_of("outlet_pressure", "pressure_drop")
        if spec.efficiency is None:
            fail("efficiency is not given", f"give specs.{node.id}.efficiency (adiabatic, 0 to 1)")
        values = {
            "outlet_pressure_Pa": pa(spec.outlet_pressure),
            "pressure_drop_Pa": delta_pa(spec.pressure_drop),
            "efficiency": efficiency(spec.efficiency),
        }
    elif unit == "flash":
        values = {"temperature_K": kelvin(spec.temperature), "pressure_Pa": pa(spec.pressure)}
    elif unit == "heat_exchanger":
        one_of("hot_outlet_temperature", "cold_outlet_temperature", "duty")
        if spec.duty is not None and spec.duty.value <= 0:
            fail("duty is the heat exchanged, so positive")
        for side in ("hot", "cold"):
            if getattr(spec, f"{side}_pressure_drop") is None:
                add(
                    "info",
                    "sim-default",
                    f"{node.id} ({unit}): {side}_pressure_drop not given, 0 used",
                    where,
                    [node.id],
                    f"give specs.{node.id}.{side}_pressure_drop",
                )
        values = {
            "hot_outlet_temperature_K": kelvin(spec.hot_outlet_temperature),
            "cold_outlet_temperature_K": kelvin(spec.cold_outlet_temperature),
            "duty_kW": kw(spec.duty),
            "hot_pressure_drop_Pa": delta_pa(spec.hot_pressure_drop) or 0.0,
            "cold_pressure_drop_Pa": delta_pa(spec.cold_pressure_drop) or 0.0,
        }
    elif unit == "shortcut_column":
        if spec.condenser == "none":
            fail("condenser: none is for rigorous columns", "give stages for a rigorous column")
        comps = process.components()
        lacking = [
            n
            for n in (
                "light_key",
                "heavy_key",
                "light_key_in_bottoms",
                "heavy_key_in_distillate",
                "reflux_ratio",
                "condenser_pressure",
                "reboiler_pressure",
            )
            if getattr(spec, n) is None
        ]
        if lacking:
            fail(f"{', '.join(lacking)} not given")
        for key in ("light_key", "heavy_key"):
            name = getattr(spec, key)
            if name is not None and name not in comps:
                fail(f"{key} {name} is not a component of process/materials.yaml")
        if spec.light_key is not None and spec.light_key == spec.heavy_key:
            fail("light_key and heavy_key are the same component")
        values = {
            "light_key": spec.light_key,
            "heavy_key": spec.heavy_key,
            "light_key_in_bottoms": spec.light_key_in_bottoms,
            "heavy_key_in_distillate": spec.heavy_key_in_distillate,
            "reflux_ratio": spec.reflux_ratio,
            "condenser_pressure_Pa": pa(spec.condenser_pressure),
            "reboiler_pressure_Pa": pa(spec.reboiler_pressure),
            "condenser": spec.condenser,
        }
    elif unit == "distillation_column":
        condensing, reboiling = spec.condenser != "none", spec.reboiler
        needed = ["stages", "condenser_pressure", "reboiler_pressure"]
        needed += ["condenser_spec"] if condensing else []
        needed += ["reboiler_spec"] if reboiling else []
        needed += ["vapor_flow"] if spec.condenser == "partial" else []
        lacking = [n for n in needed if getattr(spec, n) is None]
        if lacking:
            fail(f"{', '.join(lacking)} not given")
        for name, present in (
            ("condenser_spec", condensing),
            ("reboiler_spec", reboiling),
            ("vapor_flow", spec.condenser == "partial"),
        ):
            if not present and getattr(spec, name) is not None:
                fail(f"{name} is given, but the column has no " + name.split("_")[0])
        stages = spec.stages or 0
        if 0 < stages < 3:
            fail(f"{stages} stages: a column needs three or more")
        # stage 1 is the condenser where there is one, the last stage the reboiler
        lo = 2 if condensing else 1
        hi = stages - 1 if reboiling else stages
        ports = in_ports or []
        if spec.feed_stages:
            given = {p: spec.feed_stages.get(p) for p in ports}
        elif spec.feed_stage is not None and len(ports) == 1:
            given = {ports[0]: spec.feed_stage}
        else:
            given = dict.fromkeys(ports)
        missing = [p for p, st in given.items() if st is None]
        if missing and spec.feed_stage is not None and len(ports) > 1:
            fail(
                f"feed_stage names one stage, the column has {len(ports)} feeds",
                f"give specs.{node.id}.feed_stages: {{inlet port: stage}}",
            )
        elif missing:
            fail(
                f"feed stage not given for inlet {', '.join(missing)}",
                f"give specs.{node.id}.feed_stage (one feed) or feed_stages: {{port: stage}}",
            )
        wrong = [p for p, st in given.items() if st is not None and not lo <= st <= hi]
        if wrong and stages:
            fail(f"feed stage of {', '.join(wrong)} is not between {lo} and {hi}")
        draws = []
        for port in [p for p in out_ports if p in spec.side_draws]:
            draw = spec.side_draws[port]
            if stages and not lo <= draw.stage <= stages:
                fail(f"side draw {port} at stage {draw.stage} is not between {lo} and {stages}")
            draws.append(
                {"stage": draw.stage, "phase": draw.phase, **_flow_of(draw.flow, fs, fail)}
            )
        unknown = sorted(set(spec.side_draws) - set(out_ports))
        if unknown:
            fail(f"side_draws name {', '.join(unknown)}, no connected outlet port")
        values = {
            "stages": spec.stages,
            "feed_stages": [given.get(p) for p in ports],
            "condenser_pressure_Pa": pa(spec.condenser_pressure),
            "reboiler_pressure_Pa": pa(spec.reboiler_pressure),
            "condenser": spec.condenser,
            "reboiler": reboiling,
            "condenser_spec": _product(spec.condenser_spec, "condenser", fail, kw, kelvin, fs)
            if condensing
            else None,
            "reboiler_spec": _product(spec.reboiler_spec, "reboiler", fail, kw, kelvin, fs)
            if reboiling
            else None,
            "vapor_flow": _flow_of(spec.vapor_flow, fs, fail) if spec.vapor_flow else None,
            "side_draws": draws,
        }
        if spec.heat_integration is not None:
            if not reboiling:
                fail("heat_integration heats a reboiler; the column has none")
            approach = spec.heat_integration.min_approach
            values["heat_integration"] = {
                "condenser_of": spec.heat_integration.condenser_of,
                "min_approach_K": delta_k(approach) if approach else 1.0,
            }
        top, bottom = values["condenser_pressure_Pa"], values["reboiler_pressure_Pa"]
        if top and bottom and bottom < top:
            fail("reboiler_pressure is below condenser_pressure")
    elif unit == "component_separator":
        comps = process.components()
        if not spec.recoveries:
            fail(
                "recoveries are not given",
                f"give specs.{node.id}.recoveries: {{component: fraction}}",
            )
        unknown = [c for c in spec.recoveries if c not in comps]
        if unknown:
            fail(f"recoveries name {', '.join(unknown)}, not in process/materials.yaml")
        wrong = [c for c, v in spec.recoveries.items() if not 0 <= v <= 1]
        if wrong:
            fail(f"recoveries of {', '.join(wrong)} are not between 0 and 1")
        target = spec.recovery_outlet or (out_ports[0] if out_ports else None)
        if target not in out_ports:
            fail(f"recovery_outlet {target} is no connected outlet port ({', '.join(out_ports)})")
        values = {
            "recoveries": dict(spec.recoveries),
            "recovery_outlet": out_ports.index(target) if target in out_ports else 0,
        }
    elif unit == "multi_stream_exchanger":
        ports = in_ports or []
        extra = sorted(set(spec.outlet_temperatures) - set(ports))
        extra += sorted(set(spec.pressure_drops) - set(ports))
        if extra:
            fail(f"outlet_temperatures or pressure_drops name {', '.join(extra)}, no inlet port")
        free = [p for p in ports if p not in spec.outlet_temperatures]
        if len(free) > 1:
            fail(
                f"outlet temperatures missing for {', '.join(free)}; at most one stream is left "
                "to the energy balance",
                f"give specs.{node.id}.outlet_temperatures: {{inlet port: temperature}}",
            )
        sides = []
        for p in ports:
            temperature = spec.outlet_temperatures.get(p)
            drop = spec.pressure_drops.get(p)
            if drop is None:
                add(
                    "info",
                    "sim-default",
                    f"{node.id} ({unit}): pressure drop of {p} not given, 0 used",
                    where,
                    [node.id],
                    f"give specs.{node.id}.pressure_drops.{p}",
                )
            sides.append(
                {
                    "outlet_temperature_K": kelvin(temperature) if temperature else None,
                    "pressure_drop_Pa": delta_pa(drop) or 0.0,
                }
            )
        values = {"sides": sides}
    elif unit in REACTORS.values():
        values = _reactor_spec(
            process, node, unit, spec, fail, kelvin, delta_pa, add, where, streams or [], case
        )
    elif unit == KINETIC:
        values = _kinetic_spec(process, node, spec, fail)
    elif unit == "valve":
        one_of("outlet_pressure", "pressure_drop")
        values = {
            "outlet_pressure_Pa": pa(spec.outlet_pressure),
            "pressure_drop_Pa": delta_pa(spec.pressure_drop),
        }
    elif unit == "splitter":
        split = dict(spec.split or getattr(node, "split", {}) or {})
        ports = [p.id for p in node.ports if p.direction == "out" and p.kind == "material"]
        hint = "give split: {outlet port: fraction} for all connected outlets but one"
        if set(split) - set(ports):
            fail(f"split names ports {', '.join(sorted(set(split) - set(ports)))} it lacks", hint)
        if any(v < 0 for v in split.values()):
            fail("split fractions must not be negative", hint)
        dead = [p for p in split if p not in out_ports and split[p] > 0]
        if dead:
            fail(f"split sends flow to unconnected port(s) {', '.join(dead)}", hint)
        split = {p: v for p, v in split.items() if p in out_ports}
        missing = [p for p in out_ports if p not in split]
        if len(missing) > 1 or (len(missing) == 1 and sum(split.values()) > 1):
            fail("split fractions are missing for " + ", ".join(missing), hint)
        elif missing:
            split[missing[0]] = round(1.0 - sum(split.values()), 12)
        elif abs(sum(split.values()) - 1.0) > 1e-9:
            fail(f"split fractions add up to {sum(split.values()):g}, not 1", hint)
        values = {"fractions": [split.get(p, 0.0) for p in out_ports]}
    if unit != "distillation_column":
        rigorous = [
            name
            for name, used in (
                ("reboiler: false", not spec.reboiler),
                ("heat_integration", spec.heat_integration is not None),
                ("vapor_flow", spec.vapor_flow is not None),
                ("side_draws", bool(spec.side_draws)),
            )
            if used
        ]
        if rigorous:
            fail(
                f"{', '.join(rigorous)}: for rigorous columns only",
                "give stages for a rigorous column, or remove them",
            )
    if spec.mode is not None and unit not in (*REACTORS.values(), KINETIC):
        fail("mode is for reactors only", "remove mode, or give the step reactions:")
    if spec.coupling is not None and unit != KINETIC:
        fail("coupling is for kinetic reactors (reactor: pfr) only", "remove coupling")
    if spec.drive_efficiency is not None:
        if unit not in ("compressor", "pump", "expander"):
            fail("drive_efficiency is for compressors, pumps and expanders")
        else:
            values["drive_efficiency"] = efficiency(spec.drive_efficiency)
    values = {k: v for k, v in values.items() if v is not None}
    return values if ok else None
