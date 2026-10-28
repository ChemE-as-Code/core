"""The supported-method contract: which thermodynamic models each execution route runs.

``methods.yml`` (package data next to this module) lists every model the selection tree
(``model_selection_rules.yml``) can recommend and, per route, whether it is executable:

- ``phase``: :func:`chemeascode.domains.process.thermodynamics.phase.phase_determination`, a
  thermo flash (``cheme process phase``);
- ``simulation``: the DWSIM worker (``integrations/dwsim_worker.py`` ``PACKAGES``,
  ``cheme process simulate``).

A method a route does not run is never replaced silently: :func:`route_support` names the
nearest executable substitute from the table, marked as a substitution with what it loses, or
says that none exists. The table also holds each route's declared limitations and the coverage
decisions for electrolytes, solid equilibrium and petroleum pseudocomponents (electrolytes:
a method's ``electrolyte`` entry names the qualified systems of ``electrolytes.yml`` that run
its liquid model through ``cheme process electrolyte``, a route outside ``ROUTES``). It holds no
model parameters and claims no application range beyond what a test benchmarks: a simulation
package's benchmarked range (:class:`SimulationClaim`, :func:`simulation_claim`) names its
components, phases, temperature-pressure boxes, tolerances, the simulator version and the
interaction parameters the benchmark read from the simulator; :func:`outside_claim` says why a
state lies outside it (``cheme maturity``, requirement ``predictive.property-regime``).
"""

from __future__ import annotations

from functools import cache
from importlib.resources import files
from typing import Any, Literal

import yaml
from pydantic import BaseModel, ConfigDict, Field

#: The table, package data next to this module.
METHODS_FILE = files("chemeascode.domains.process.thermodynamics") / "methods.yml"

Route = Literal["phase", "simulation"]
ROUTES: tuple[Route, ...] = ("phase", "simulation")
CoverageStatus = Literal["supported", "limited", "external_integration", "unsupported"]


class _Model(BaseModel):
    model_config = ConfigDict(extra="forbid")


class PhaseRoute(_Model):
    """How phase.py runs a method: the ``thermodynamic_model`` it takes."""

    model: dict[str, str]
    interaction_parameters: str = ""
    note: str = ""


class Box(_Model):
    """A temperature-pressure box a component is claimed in."""

    temperature_K: tuple[float, float] = Field(description="K, min and max")
    pressure_kPa: tuple[float, float] = Field(description="kPa(a), min and max")


class ClaimInteractionParameters(_Model):
    source: str
    #: "CAS&CAS" (sorted) -> kij as the worker read it from the package
    kij: dict[str, float]
    #: "CAS&CAS" (sorted) -> an activity-coefficient package's pair entry as the worker read it
    #: (NRTL, UNIQUAC: A12, A21, B12, B21, C12, C21 and NRTL's alpha12), component 1 the first
    #: CAS number of the key
    activity: dict[str, dict[str, float]] = Field(default_factory=dict)


class ClaimBenchmark(_Model):
    test: str
    reference: str


class SimulationClaim(_Model):
    """The application range a test benchmarks for one simulation package: which components,
    phases and temperature-pressure boxes, which properties within which tolerances, on which
    simulator version and with which interaction parameters. A state is inside the claim when
    every component present is a claimed one, it is one component or the claim holds mixtures,
    and the state lies in a box of each of them."""

    simulator: str
    simulator_version: str = Field(description="The version benchmarked (major.minor.patch)")
    components: dict[str, str] = Field(description="CAS number -> name")
    mixtures: bool = Field(
        default=True,
        description="Whether mixtures of the claimed components are claimed; false: each "
        "component alone only (a state with more than one component is outside)",
    )
    phases: list[str]
    regions: dict[str, list[Box]] = Field(description="CAS number -> the boxes it is claimed in")
    properties: list[str] = Field(description="What the tolerances hold for inside the boxes")
    not_claimed: list[str] = Field(default_factory=list)
    tolerances: dict[str, float]
    interaction_parameters: ClaimInteractionParameters
    package_settings: dict[str, str] = Field(default_factory=dict)
    benchmark: ClaimBenchmark
    notes: list[str] = Field(default_factory=list)


class SimulationRoute(_Model):
    """How the DWSIM route runs a method: the ``property_package`` of simulation.yaml, and the
    range a test benchmarks for it (None: no range claimed)."""

    package: str
    interaction_parameters: str = ""
    note: str = ""
    application_range: SimulationClaim | None = None


class ElectrolyteRoute(_Model):
    """Where the electrolyte route (``electrolytes.yml``, ``cheme process electrolyte``) runs a
    method: for the listed systems only, inside each one's claimed range."""

    systems: list[str]
    note: str = ""


class SubstituteRef(_Model):
    method: str
    loses: str


class MethodDefinition(_Model):
    """One row of the table."""

    id: str
    name: str
    recommended_as: list[str] = Field(default_factory=list)
    limitations: list[str] = Field(default_factory=list)
    phase: PhaseRoute | None = None
    simulation: SimulationRoute | None = None
    electrolyte: ElectrolyteRoute | None = Field(
        default=None, description="The qualified electrolyte systems that run its liquid model"
    )
    substitutes: list[SubstituteRef] = Field(default_factory=list)
    no_substitute: str = ""

    def executable(self, route: Route) -> bool:
        return getattr(self, route) is not None


class RouteDefinition(_Model):
    title: str
    limitations: list[str]
    application_range: str


class RegimeStatus(_Model):
    status: CoverageStatus
    evidence: str


class RegimeDecision(_Model):
    """A coverage decision (supported / limited / external integration / unsupported)."""

    selection: str
    phase: RegimeStatus
    simulation: RegimeStatus
    #: Capabilities outside the two thermodynamic routes that cover the regime in part, by name
    #: (``furnace``: the furnace energy basis of ``domains/process/furnace.py``).
    elsewhere: dict[str, RegimeStatus] = {}


class MethodTable(_Model):
    meta: dict[str, Any]
    routes: dict[Route, RouteDefinition]
    regimes: dict[str, RegimeDecision]
    methods: list[MethodDefinition]

    def method(self, method_id: str) -> MethodDefinition:
        for m in self.methods:
            if m.id == method_id:
                return m
        raise KeyError(method_id)


class Substitution(_Model):
    """A stand-in for a method a route does not run: never applied without an engineer's
    approval, always reported as a substitution."""

    substitution: Literal[True] = True
    method: str = Field(description="Method id of the stand-in")
    name: str
    loses: str = Field(description="What the recommended method models that the stand-in does not")
    model: dict[str, str] | None = Field(default=None, description="phase: thermodynamic_model")
    package: str | None = Field(default=None, description="simulation: property_package")


class RouteSupport(_Model):
    """Whether one route runs one method, and if not, its explicit substitute (or why none)."""

    route: Route
    executable: bool
    model: dict[str, str] | None = Field(default=None, description="phase: thermodynamic_model")
    package: str | None = Field(default=None, description="simulation: property_package")
    interaction_parameters: str = ""
    note: str = ""
    substitution: Substitution | None = None
    reason: str = Field(default="", description="Why the route does not run it")


class MethodSupport(_Model):
    """A recommended model resolved against the contract."""

    recommended: str = Field(description="The model name as the selection tree gives it")
    method: str = Field(description="Method id in methods.yml")
    name: str
    limitations: list[str] = Field(default_factory=list)
    phase: RouteSupport
    simulation: RouteSupport
    electrolyte: ElectrolyteRoute | None = Field(
        default=None, description="The qualified electrolyte systems that run its liquid model"
    )


@cache
def method_table() -> MethodTable:
    """The packaged table (validated, cached)."""
    return MethodTable.model_validate(yaml.safe_load(METHODS_FILE.read_text(encoding="utf-8")))


def method_for_recommendation(recommended: str) -> MethodDefinition:
    """The table row of a model name the selection tree recommends; ``KeyError`` for a name the
    table does not list (tests keep the two files in step)."""
    for m in method_table().methods:
        if recommended in m.recommended_as:
            return m
    raise KeyError(recommended)


def _route_spec(m: MethodDefinition, route: Route) -> dict[str, Any]:
    spec = getattr(m, route)
    if route == "phase":
        return {"model": dict(spec.model)}
    return {"package": spec.package}


def route_support(method_id: str, route: Route) -> RouteSupport:
    """Whether *route* runs *method_id*; if not, the first substitute in the table it runs,
    marked as a substitution, or the reason there is none."""
    table = method_table()
    m = table.method(method_id)
    spec = getattr(m, route)
    if spec is not None:
        return RouteSupport(
            route=route,
            executable=True,
            interaction_parameters=spec.interaction_parameters,
            note=spec.note,
            **_route_spec(m, route),
        )
    for ref in m.substitutes:
        alt = table.method(ref.method)
        if alt.executable(route):
            return RouteSupport(
                route=route,
                executable=False,
                reason=f"{m.name} is not executable by the {route} route",
                substitution=Substitution(
                    method=alt.id, name=alt.name, loses=ref.loses, **_route_spec(alt, route)
                ),
            )
    why = m.no_substitute or "no method in the table that this route runs stands in for it"
    return RouteSupport(
        route=route,
        executable=False,
        reason=f"{m.name} is not executable by the {route} route; no substitution: {why}",
    )


def method_support(recommended: str) -> MethodSupport:
    """*recommended* (a model name of the selection tree) resolved for both routes."""
    m = method_for_recommendation(recommended)
    return MethodSupport(
        recommended=recommended,
        method=m.id,
        name=m.name,
        limitations=list(m.limitations),
        phase=route_support(m.id, "phase"),
        simulation=route_support(m.id, "simulation"),
        electrolyte=m.electrolyte,
    )


def simulation_packages() -> list[str]:
    """The property packages the DWSIM route runs, in table order (= the worker's PACKAGES)."""
    return [m.simulation.package for m in method_table().methods if m.simulation is not None]


def method_for_package(package: str) -> MethodDefinition | None:
    """The table row a simulation property package executes, or None for an unknown package."""
    for m in method_table().methods:
        if m.simulation is not None and m.simulation.package == package:
            return m
    return None


def method_for_phase_model(model: dict[str, str]) -> MethodDefinition | None:
    """The table row a phase.py ``thermodynamic_model`` executes, or None."""
    for m in method_table().methods:
        if m.phase is not None and m.phase.model == model:
            return m
    return None


def route_limitations(route: Route) -> list[str]:
    """What *route* declares it does not model."""
    return list(method_table().routes[route].limitations)


def application_range(route: Route) -> str:
    """The application range *route* claims ("no range claimed ..." where no test benchmarks
    one)."""
    return method_table().routes[route].application_range


def simulation_claim(package: str) -> SimulationClaim | None:
    """The benchmarked application range of simulation property package *package*, or None
    where methods.yml claims none."""
    m = method_for_package(package)
    return m.simulation.application_range if m is not None and m.simulation else None


def outside_claim(
    claim: SimulationClaim, temperature_K: float, pressure_kPa: float, cas: set[str | None]
) -> list[str]:
    """Why the state (temperature, pressure, the CAS numbers of the components present; None
    for one without) lies outside *claim*; empty when inside."""
    problems = [
        f"component {c or 'without a CAS number'} is not in the claim"
        for c in sorted(cas, key=lambda c: c or "")
        if c not in claim.components
    ]
    if problems:
        return problems
    if not claim.mixtures and len(cas) > 1:
        names = ", ".join(claim.components[c] for c in sorted(cas))  # type: ignore[arg-type]
        return [f"a mixture ({names}) is outside the claim, which holds each component alone"]
    for c in sorted(cas):  # type: ignore[arg-type]
        if not any(
            b.temperature_K[0] <= temperature_K <= b.temperature_K[1]
            and b.pressure_kPa[0] <= pressure_kPa <= b.pressure_kPa[1]
            for b in claim.regions[c]
        ):
            boxes = "; ".join(
                f"{b.temperature_K[0]:g}-{b.temperature_K[1]:g} K at "
                f"{b.pressure_kPa[0]:g}-{b.pressure_kPa[1]:g} kPa(a)"
                for b in claim.regions[c]
            )
            problems.append(
                f"{temperature_K:.6g} K, {pressure_kPa:.6g} kPa(a) is outside the boxes of "
                f"{claim.components[c]} ({boxes})"
            )
    return problems


def regime_decisions() -> dict[str, RegimeDecision]:
    """The coverage decisions for electrolytes, solid equilibrium and pseudocomponents."""
    return dict(method_table().regimes)
