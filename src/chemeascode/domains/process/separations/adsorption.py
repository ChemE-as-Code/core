"""Adsorber performance from ``process/adsorption.yaml``: an equilibrium TSA cycle, or an
external performance model's results checked against the flowsheet.

A ``component_separator`` in ``process/simulation.yaml`` closes the balances around recoveries
the engineer states. This module gives an adsorber a basis that is not just stated:

- ``performance: calculated``, ``technique: tsa``: core's equilibrium TSA cycle. Per layer, the
  key components' loadings follow from sourced isotherms (Langmuir, dual-site Langmuir, Sips,
  Toth, with their temperature dependence; competitive extended Langmuir or Sips within a
  layer) at the feed state, and the residual loading from the purge gas. The key front leaves
  the bed at the stoichiometric time less the unused bed (half the measured mass transfer
  zone, after Collins' length-of-unused-bed method). The cycle balance at cyclic steady state
  gives the product and waste flows and so every component's recovery (the void gas and the
  co-adsorbed carrier lost per cycle); the regeneration heat is the sensible heat of adsorbent
  and vessel plus the heat of desorption, carried by the hot purge with an ideal thermal
  front; the purge also has to carry the desorbed key components at their equilibrium
  partial pressure at the regeneration temperature. An isotherm is evaluated only inside its
  stated temperature and partial-pressure range: outside, the calculation is refused.
- ``performance: external``: the recoveries and utilities of a model core does not run (a
  vendor tool, a published PSA cycle). Core checks the feed lies in the model's stated
  operating range, closes the balance and checks the product specification; the performance
  itself stays the external model's.
- ``performance: calculated`` with ``technique: psa`` is refused: core has no PSA cycle model.

Either way the result is compared with the split ``process/simulation.yaml`` gives the
simulator, so that the model basis (:mod:`..model_basis`) can tell an independently calculated
split from a stated one. Nothing here requires the file: without it, a sourced split stays the
conceptual representation (:mod:`.coverage`).
"""

from __future__ import annotations

import json
import math
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any

import yaml
from pydantic import ValidationError

from chemeascode.domains.process.model import GAS_CONSTANT, Process, stream_flows
from chemeascode.domains.process.separations.schema import (
    ISOTHERM_PARAMETERS,
    SCHEMA,
    Adsorption,
    AdsorptionUnit,
    Isotherm,
    Layer,
    Value,
)
from chemeascode.foundation.findings import Finding
from chemeascode.foundation.provenance import SourceRevision, source_revision, value_fingerprint
from chemeascode.foundation.units import to_kelvin, to_kpa_abs
from chemeascode.foundation.yamlsource import _compose, _yaml_line, syntax_finding

ADSORPTION_FILE = "process/adsorption.yaml"
INPUTS = (ADSORPTION_FILE, "process/flowsheet.yaml", "process/materials.yaml")
#: Version of the calculation: part of each unit's fingerprint.
MODEL_VERSION = "equilibrium-tsa/1"
_R = GAS_CONSTANT / 1000  # kJ/(mol K)

#: What the equilibrium TSA calculation assumes; listed with every calculated result.
ASSUMPTIONS = (
    "local adsorption equilibrium; each key component's front leaves the bed at the "
    "stoichiometric time less the length of unused bed, half the measured mass transfer zone "
    "(a symmetric breakthrough curve)",
    "isothermal adsorption step at the feed temperature: the thermal front of the heat of "
    "adsorption is not modelled",
    "cyclic steady state: each adsorption step starts from a bed in equilibrium with the purge "
    "gas at the feed temperature and the regeneration pressure (cooled before the switch)",
    "regeneration: the whole bed reaches the regeneration temperature; the hot purge carries the "
    "heat with an ideal thermal front (it leaves at the feed temperature until the bed is "
    "heated); heat losses and the heat capacity of the gas in the voids are not included",
    "a key component is held by the layer that lists it in removes; one bed is on feed at a time",
)
#: Fixed units: unit -> (kind, factor to the internal unit).
_UNITS: dict[str, tuple[str, float]] = {
    "s": ("time", 1 / 3600),
    "min": ("time", 1 / 60),
    "h": ("time", 1.0),
    "d": ("time", 24.0),
    "a": ("time", 8760.0),
    "m": ("length", 1.0),
    "mm": ("length", 0.001),
    "kg/m3": ("density", 1.0),
    "kJ/(kg K)": ("heat_capacity", 1.0),
    "kJ/kg/K": ("heat_capacity", 1.0),
    "J/(kg K)": ("heat_capacity", 0.001),
    "J/kg/K": ("heat_capacity", 0.001),
    "kJ/(kmol K)": ("molar_heat_capacity", 1.0),
    "kJ/kmol/K": ("molar_heat_capacity", 1.0),
    "J/(mol K)": ("molar_heat_capacity", 1.0),
    "J/mol/K": ("molar_heat_capacity", 1.0),
    "kJ/mol": ("molar_energy", 1.0),
    "J/mol": ("molar_energy", 0.001),
    "kmol/h": ("molar_flow", 1.0),
    "mol/s": ("molar_flow", 3.6),
    "kJ/K": ("heat_capacity_total", 1.0),
    "-": ("fraction", 1.0),
    "mol/mol": ("fraction", 1.0),
    "%": ("fraction", 0.01),
    "ppm": ("fraction", 1e-6),
    "ppb": ("fraction", 1e-9),
}
_PRESSURE_UNIT = {"Pa": 0.001, "kPa": 1.0, "bar": 100.0}  # to kPa


class UnknownCase(ValueError):
    """The case asked for is not declared in the flowsheet."""


# -- isotherms -----------------------------------------------------------------------------------


def _affinity(iso: Isotherm, b0: float, energy: float, temperature: float) -> float:
    """b in 1/kPa at *temperature* (K)."""
    return b0 * math.exp(energy / (_R * temperature)) / _PRESSURE_UNIT[iso.pressure_unit]


def _sites(iso: Isotherm, temperature: float) -> list[tuple[float, float]]:
    """(q_s mol/kg, b 1/kPa) of each site of a multi-site Langmuir isotherm:
    ``q_s = a0 + c0 T``, ``b = b0 exp(E / T)`` with E in K (Cmarik et al., NASA/TM-2017-219847)."""
    p = iso.parameters
    unit = _PRESSURE_UNIT[iso.pressure_unit]
    return [
        (
            p[f"a0_{j}"] + p[f"c0_{j}"] * temperature,
            p[f"b0_{j}"] * math.exp(p[f"E_{j}"] / temperature) / unit,
        )
        for j in range(1, len(p) // 4 + 1)
    ]


def _sips_terms(iso: Isotherm, temperature: float) -> tuple[float, float, float]:
    """(q_s mol/kg, b 1/kPa, exponent) of a Sips or Toth isotherm at *temperature*: the
    saturation capacity's exponent is ``chi (T/T_ref - 1)`` for Sips (Hefti et al. 2015, as in
    IDAES) and ``chi (1 - T/T_ref)`` for Toth (Do 1998)."""
    p = iso.parameters
    ratio = temperature / p["T_ref"]
    b = _affinity(iso, p["b0"], p["E"], temperature)
    if iso.model == "sips":
        q_s = p["q_s_ref"] * math.exp(p["chi"] * (ratio - 1))
        return q_s, b, p["n_ref"] + p["alpha"] * (ratio - 1)
    q_s = p["q_s_ref"] * math.exp(p["chi"] * (1 - ratio))
    return q_s, b, p["t_ref"] + p["alpha"] * (1 - p["T_ref"] / temperature)


def single_loading(iso: Isotherm, pressure: float, temperature: float) -> float:
    """Loading (mol/kg) of the pure component at partial *pressure* (kPa) and *temperature* (K)."""
    if pressure <= 0:
        return 0.0
    p = iso.parameters
    if iso.model == "langmuir":
        bp = _affinity(iso, p["b0"], p["E"], temperature) * pressure
        return p["q_s"] * bp / (1 + bp)
    if iso.model == "multi-site-langmuir":
        return sum(q_s * b * pressure / (1 + b * pressure) for q_s, b in _sites(iso, temperature))
    if iso.model == "dual-site-langmuir":
        total = 0.0
        for site in ("1", "2"):
            bp = _affinity(iso, p[f"b0{site}"], p[f"E{site}"], temperature) * pressure
            total += p[f"q_s{site}"] * bp / (1 + bp)
        return total
    q_s, b, exponent = _sips_terms(iso, temperature)
    if iso.model == "sips":
        term = (b * pressure) ** exponent
        return q_s * term / (1 + term)
    return q_s * b * pressure / (1 + (b * pressure) ** exponent) ** (1 / exponent)


def loadings(layer: Layer, pressures: dict[str, float], temperature: float) -> dict[str, float]:
    """Loading (mol/kg) of each component with an isotherm in *layer* at the partial
    *pressures* (kPa): competitive (extended Langmuir or Sips) among the components whose
    isotherms share the model when the layer's ``mixture`` is ``extended``, else each alone."""
    out: dict[str, float] = {}
    groups: dict[str, list[Isotherm]] = {}
    for iso in layer.isotherms:
        if layer.mixture == "extended" and iso.model in ("langmuir", "sips"):
            groups.setdefault(iso.model, []).append(iso)
        else:
            out[iso.component] = single_loading(iso, pressures.get(iso.component, 0.0), temperature)
    for model, members in groups.items():
        terms: dict[str, tuple[float, float]] = {}
        for iso in members:
            pressure = pressures.get(iso.component, 0.0)
            if model == "langmuir":
                q_s = iso.parameters["q_s"]
                term = _affinity(iso, iso.parameters["b0"], iso.parameters["E"], temperature)
                term *= pressure
            else:
                q_s, b, exponent = _sips_terms(iso, temperature)
                term = (b * pressure) ** exponent if pressure > 0 else 0.0
            terms[iso.component] = (q_s, term)
        denominator = 1 + sum(t for _, t in terms.values())
        for name, (q_s, term) in terms.items():
            out[name] = q_s * term / denominator
    return out


def equilibrium_pressure(iso: Isotherm, loading: float, temperature: float) -> float:
    """The partial pressure (kPa) in equilibrium with *loading* (mol/kg) of the pure component;
    inf when the loading exceeds what the isotherm reaches."""
    if loading <= 0:
        return 0.0
    low, high = 1e-12, 1e9
    if single_loading(iso, high, temperature) <= loading:
        return math.inf
    for _ in range(200):
        mid = math.sqrt(low * high)
        if single_loading(iso, mid, temperature) < loading:
            low = mid
        else:
            high = mid
        if high / low < 1 + 1e-10:
            break
    return math.sqrt(low * high)


# -- results ------------------------------------------------------------------------------------


@dataclass
class CaseResult:
    """One unit in one case."""

    case: str
    status: str  # ok, fail, refused
    feed: dict[str, Any] = field(default_factory=dict)
    layers: list[dict[str, Any]] = field(default_factory=list)
    recoveries: dict[str, float] = field(default_factory=dict)
    product: dict[str, Any] = field(default_factory=dict)
    waste: dict[str, Any] = field(default_factory=dict)
    closure: dict[str, Any] = field(default_factory=dict)
    regeneration: dict[str, Any] = field(default_factory=dict)
    specification: dict[str, Any] = field(default_factory=dict)
    utilities: list[dict[str, Any]] = field(default_factory=list)
    #: ``{rule, message}`` of each check the case fails
    failures: list[dict[str, str]] = field(default_factory=list)

    def fail(self, rule: str, message: str) -> None:
        self.failures.append({"rule": rule, "message": message})


@dataclass
class AdsorberResult:
    """One entry of ``process/adsorption.yaml``, evaluated in each case."""

    id: str
    technique: str
    performance: str
    #: qualified (every case inside the ranges and meeting the specification), fail, refused,
    #: unsupported
    status: str
    line: int | None = None
    model: str = ""
    cases: list[CaseResult] = field(default_factory=list)
    #: The split process/simulation.yaml gives the simulator against this basis.
    split: dict[str, Any] = field(default_factory=dict)
    replacement: dict[str, Any] = field(default_factory=dict)
    sources: list[str] = field(default_factory=list)
    assumptions: list[str] = field(default_factory=list)
    limitations: list[str] = field(default_factory=list)
    unsourced: list[str] = field(default_factory=list)
    fingerprint: str = ""

    @property
    def consistent(self) -> bool:
        """Qualified, and the simulator's split follows from it."""
        return self.status == "qualified" and self.split.get("status") == "consistent"

    def entry(self) -> dict[str, Any]:
        data = asdict(self)
        data["consistent"] = self.consistent
        return data


@dataclass
class AdsorptionReport:
    units: list[AdsorberResult]
    findings: list[Finding]
    source: SourceRevision | None = None

    def by_id(self) -> dict[str, AdsorberResult]:
        return {u.id: u for u in self.units}

    def as_dict(self) -> dict[str, Any]:
        from chemeascode.foundation.schemas.run import finding_dict

        return {
            "schema": SCHEMA,
            "model_version": MODEL_VERSION,
            "units": [u.entry() for u in self.units],
            "findings": [finding_dict(f) for f in self.findings],
            "source": self.source.as_dict() if self.source else None,
        }

    def to_json(self) -> str:
        return json.dumps(self.as_dict(), indent=2)


# -- loading ------------------------------------------------------------------------------------


def load(root: Path) -> tuple[Adsorption | None, Any, list[Finding]]:
    """``process/adsorption.yaml`` at *root*, its node tree and its schema findings;
    (None, None, []) when there is none."""
    path = root / ADSORPTION_FILE
    if not path.is_file():
        return None, None, []
    text = path.read_text(encoding="utf-8")
    try:
        data = yaml.safe_load(text) or {}
    except yaml.YAMLError as failure:
        return None, None, [syntax_finding(ADSORPTION_FILE, failure, text)]
    doc = _compose(path)
    try:
        parsed = Adsorption.model_validate(data)
    except ValidationError as failure:
        return (
            None,
            doc,
            [
                Finding(
                    ADSORPTION_FILE,
                    "error",
                    "cheme.adsorption-schema",
                    f"{'.'.join(str(p) for p in e['loc']) or 'file'}: {e['msg']}",
                    line=_yaml_line(doc, list(e["loc"])),
                    hint="see `cheme schema process-adsorption`",
                )
                for e in failure.errors()
            ],
        )
    if parsed.schema_ != SCHEMA:
        return (
            None,
            doc,
            [
                Finding(
                    ADSORPTION_FILE,
                    "error",
                    "cheme.adsorption-schema",
                    f"schema {parsed.schema_!r}, expected {SCHEMA}",
                    line=_yaml_line(doc, ["schema"]),
                    hint=f"set schema: {SCHEMA}",
                )
            ],
        )
    return parsed, doc, []


# -- evaluation ---------------------------------------------------------------------------------


class _Refused(Exception):
    """An input the calculation cannot use; the message names it."""

    def __init__(self, message: str, loc: list[Any], hint: str, rule: str = "adsorption-input"):
        super().__init__(message)
        self.loc, self.hint, self.rule = loc, hint, rule


class _Unit:
    """Evaluates one entry; collects its findings."""

    def __init__(self, process: Process, unit: AdsorptionUnit, index: int, doc: Any):
        self.process, self.unit, self.index, self.doc = process, unit, index, doc
        self.findings: list[Finding] = []
        self.unsourced: list[str] = []
        self.sources: list[str] = []

    def at(self, loc: list[Any]) -> int | None:
        return _yaml_line(self.doc, ["units", self.index, *loc])

    def add(self, level: str, rule: str, message: str, loc: list[Any], hint: str) -> None:
        self.findings.append(
            Finding(
                ADSORPTION_FILE,
                level,  # type: ignore[arg-type]
                f"cheme.{rule}",
                f"{self.unit.id}: {message}",
                line=self.at(loc),
                ids=[self.unit.id],
                hint=hint,
            )
        )

    def value(self, item: Value | None, kind: str, loc: list[Any]) -> float:
        """*item* in the internal unit of *kind*; records its provenance."""
        if item is None:
            raise _Refused(f"{'.'.join(map(str, loc))} is missing", loc, "give it")
        where = ".".join(map(str, loc))
        if item.provenance == "assumed" or not item.source.strip():
            self.unsourced.append(where)
        elif item.source not in self.sources:
            self.sources.append(item.source)
        if kind == "temperature":
            result = to_kelvin(item.value, item.unit)
        elif kind == "pressure":
            result = to_kpa_abs(item.value, item.unit)
        else:
            known = _UNITS.get(item.unit)
            result = item.value * known[1] if known and known[0] == kind else None
        if result is None:
            wanted = [u for u, (k, _) in _UNITS.items() if k == kind]
            if kind == "temperature":
                wanted = ["K", "°C"]
            if kind == "pressure":
                wanted = ["kPa(a)", "bar(a)", "MPa(a)"]
            raise _Refused(
                f"{where}: unit {item.unit!r} is not a {kind.replace('_', ' ')} unit here",
                loc,
                f"give {where} in {', '.join(wanted)}",
            )
        return result

    # -- the flowsheet side --

    def node_ports(self) -> tuple[Any, str, list[str]]:
        node = self.process.nodes.get(self.unit.id)
        if node is None or self.process.kinds.get(self.unit.id) not in ("block", "step"):
            raise _Refused(
                f"no block or step {self.unit.id} in process/flowsheet.yaml",
                ["id"],
                "name the adsorbing step or block",
                "adsorption-unknown-node",
            )
        outs = [p.id for p in node.ports if p.direction == "out" and p.kind == "material"]
        if len(outs) < 2:
            raise _Refused(
                f"{self.unit.id} has {len(outs)} material outlet(s); an adsorber has a product "
                "and a waste outlet",
                ["id"],
                "give the node a product and a waste (desorbed) outlet",
                "adsorption-unknown-node",
            )
        product = self.unit.product_outlet or outs[0]
        if product not in outs:
            raise _Refused(
                f"product_outlet {product!r} is not a material outlet of {self.unit.id}",
                ["product_outlet"],
                f"one of {', '.join(outs)}",
            )
        return node, product, outs

    def feed(self, case: str) -> dict[str, Any]:
        process = self.process
        streams = []
        for stream in process.flowsheet.streams:
            if stream.kind != "material":
                continue
            _, end = process.ends(stream)
            if end is not None and end.node == self.unit.id:
                streams.append(stream)
        if self.unit.feed_stream:
            streams = [s for s in streams if s.id == self.unit.feed_stream]
        if len(streams) != 1:
            raise _Refused(
                f"{len(streams)} material inlet(s) match"
                + (f" feed_stream {self.unit.feed_stream}" if self.unit.feed_stream else ""),
                ["feed_stream"],
                "give feed_stream: the stream the adsorber treats",
                "adsorption-feed",
            )
        stream = streams[0]
        state = stream.state.get(case)
        units = process.flowsheet.units
        temperature = pressure = None
        if state is not None and state.temperature is not None:
            temperature = to_kelvin(
                state.temperature.value, state.temperature.unit or units.temperature
            )
        if state is not None and state.pressure is not None:
            pressure = to_kpa_abs(state.pressure.value, state.pressure.unit or units.pressure)
        flows = stream_flows(process, stream, case)
        comps = process.components()
        missing = list(flows.missing)
        if temperature is None:
            missing.append(f"{stream.id} temperature")
        if pressure is None:
            missing.append(f"{stream.id} pressure (absolute)")
        moles: dict[str, float] = {}
        for name, kg in (flows.components or {}).items():
            mw = getattr(comps.get(name), "molar_mass", None)
            if kg and not mw:
                missing.append(f"molar_mass of {name}")
            elif kg:
                moles[name] = kg / mw
        if flows.components is not None and not missing and not moles:
            missing.append(f"{stream.id} flow (zero)")
        if flows.components is None or missing:
            raise _Refused(
                f"case {case}: the feed state is incomplete ({', '.join(missing)})",
                ["feed_stream"],
                f"give {stream.id}'s flow, composition, temperature and pressure in case {case} "
                "(or run cheme process propagate)",
                "adsorption-feed",
            )
        total = sum(moles.values())
        return {
            "stream": stream.id,
            "flow_kmol_h": total,
            "temperature_K": temperature,
            "pressure_kPa": pressure,
            "mole_fractions": {k: v / total for k, v in moles.items()},
        }


def _check_range(
    worker: _Unit, li: int, layer: Layer, pressures: dict[str, float], temperature: float, what: str
) -> None:
    """Refuse when an isotherm of *layer* is used outside its stated range (a zero partial
    pressure is exact for every model and needs no range)."""
    for ii, iso in enumerate(layer.isotherms):
        pressure = pressures.get(iso.component, 0.0)
        t_lo, t_hi = iso.valid.temperature
        p_lo, p_hi = iso.valid.partial_pressure
        outside = []
        if not t_lo <= temperature <= t_hi:
            outside.append(f"T = {temperature:.1f} K outside {t_lo:g}-{t_hi:g} K")
        if pressure > 0 and not p_lo <= pressure <= p_hi:
            outside.append(f"p = {pressure:.4g} kPa outside {p_lo:g}-{p_hi:g} kPa")
        if outside:
            raise _Refused(
                f"{iso.component} on {layer.adsorbent} at {what}: {'; '.join(outside)} "
                f"(the range of {iso.source or 'the isotherm'})",
                ["layers", li, "isotherms", ii, "valid"],
                "an isotherm is not extrapolated: give one measured over these conditions, or "
                "keep a sourced component_separator split",
                "adsorption-isotherm-range",
            )


def _check_parameters(worker: _Unit) -> None:
    for li, layer in enumerate(worker.unit.layers):
        if not layer.isotherms and layer.removes:
            raise _Refused(
                f"layer {li} ({layer.adsorbent}) removes {', '.join(layer.removes)} "
                "but gives no isotherm",
                ["layers", li, "isotherms"],
                "give a sourced isotherm for each key component",
                "adsorption-unsupported",
            )
        names = {iso.component for iso in layer.isotherms}
        for key in layer.removes:
            if key not in names:
                raise _Refused(
                    f"layer {li} removes {key} but has no isotherm for it",
                    ["layers", li, "removes"],
                    f"give an isotherm for {key} on {layer.adsorbent}",
                    "adsorption-unsupported",
                )
        for ii, iso in enumerate(layer.isotherms):
            if iso.model == "multi-site-langmuir":
                sites = max(1, len(iso.parameters) // 4)
                names = ("a0", "c0", "b0", "E")
                wanted = {f"{n}_{j}" for j in range(1, sites + 1) for n in names}
            else:
                wanted = set(ISOTHERM_PARAMETERS[iso.model])
            given = set(iso.parameters)
            if wanted != given:
                raise _Refused(
                    f"{iso.model} isotherm of {iso.component}: parameters "
                    f"{', '.join(sorted(given ^ wanted))} missing or unknown",
                    ["layers", li, "isotherms", ii, "parameters"],
                    f"a {iso.model} isotherm takes "
                    + ", ".join(
                        ISOTHERM_PARAMETERS.get(iso.model, ("a0_j", "c0_j", "b0_j", "E_j"))
                    ),
                )
            if not iso.source.strip():
                worker.unsourced.append(f"layers.{li}.isotherms.{ii}")
            elif iso.source not in worker.sources:
                worker.sources.append(iso.source)


def _tsa_case(worker: _Unit, case: str, feed: dict[str, Any]) -> CaseResult:
    unit = worker.unit
    cycle = unit.cycle
    if cycle is None:
        raise _Refused("a calculated TSA needs cycle", ["cycle"], "give cycle")
    if not unit.layers:
        raise _Refused("a calculated TSA needs layers", ["layers"], "give the adsorbent layers")
    _check_parameters(worker)
    v = worker.value
    t_ads = v(cycle.adsorption_time, "time", ["cycle", "adsorption_time"])
    t_heat_h = v(cycle.heating_time, "time", ["cycle", "heating_time"])
    t_cool_h = (
        v(cycle.cooling_time, "time", ["cycle", "cooling_time"]) if cycle.cooling_time else 0.0
    )
    t_switch_h = (
        v(cycle.switch_time, "time", ["cycle", "switch_time"]) if cycle.switch_time else 0.0
    )
    t_reg = v(cycle.regeneration_temperature, "temperature", ["cycle", "regeneration_temperature"])
    p_reg = v(cycle.regeneration_pressure, "pressure", ["cycle", "regeneration_pressure"])
    diameter = v(cycle.diameter, "length", ["cycle", "diameter"])
    purge = cycle.purge
    purge_flow = v(purge.flow, "molar_flow", ["cycle", "purge", "flow"])
    purge_cp = v(purge.heat_capacity, "molar_heat_capacity", ["cycle", "purge", "heat_capacity"])
    t_supply = v(purge.supply_temperature, "temperature", ["cycle", "purge", "supply_temperature"])
    vessel_cp = (
        v(cycle.vessel_heat_capacity, "heat_capacity_total", ["cycle", "vessel_heat_capacity"])
        if cycle.vessel_heat_capacity
        else 0.0
    )
    temp, p_ads = feed["temperature_K"], feed["pressure_kPa"]
    y_feed: dict[str, float] = feed["mole_fractions"]
    flow = feed["flow_kmol_h"]
    y_purge = {k: float(x) for k, x in purge.composition.items()}
    if abs(sum(y_purge.values()) - 1) > 1e-6:
        raise _Refused(
            f"purge composition sums to {sum(y_purge.values()):.6g}",
            ["cycle", "purge", "composition"],
            "give mole fractions that sum to 1",
        )
    if t_reg <= temp:
        raise _Refused(
            f"regeneration temperature {t_reg:.1f} K is not above the feed's {temp:.1f} K",
            ["cycle", "regeneration_temperature"],
            "a TSA regenerates hot",
        )
    area = math.pi / 4 * diameter**2
    p_feed = {k: y * p_ads for k, y in y_feed.items()}
    p_purge = {k: y * p_reg for k, y in y_purge.items()}
    keys: dict[str, int] = {}
    for li, layer in enumerate(unit.layers):
        for key in layer.removes:
            keys.setdefault(key, li)
    result = CaseResult(case, "ok", feed=feed)
    inventory: dict[str, float] = {}  # kmol per bed per cycle taken up from feed state
    desorption_heat = sensible = 0.0
    for li, layer in enumerate(unit.layers):
        loc = ["layers", li]
        length = v(layer.length, "length", [*loc, "length"])
        density = v(layer.bulk_density, "density", [*loc, "bulk_density"])
        cp = v(layer.heat_capacity, "heat_capacity", [*loc, "heat_capacity"])
        void = v(layer.void_fraction, "fraction", [*loc, "void_fraction"])
        volume = area * length
        mass = density * volume  # kg per bed
        _check_range(worker, li, layer, p_feed, temp, "the feed state")
        _check_range(worker, li, layer, p_purge, temp, "the purge gas after cooling")
        _check_range(worker, li, layer, p_purge, t_reg, "the regeneration temperature")
        q_feed = loadings(layer, p_feed, temp)
        q_cold = loadings(layer, p_purge, temp)  # regenerated and cooled: start of adsorption
        q_hot = loadings(layer, p_purge, t_reg)  # end of heating
        own = [k for k, at in keys.items() if at == li]
        held: dict[str, dict[str, Any]] = {}
        for key in own:
            feed_key = flow * y_feed.get(key, 0.0)  # kmol/h
            dq = q_feed.get(key, 0.0) - q_cold.get(key, 0.0)
            dc = (p_feed.get(key, 0.0) - p_purge.get(key, 0.0)) / (GAS_CONSTANT * temp)  # kmol/m3
            capacity = mass * dq / 1000 + void * volume * dc  # kmol per bed
            entry: dict[str, Any] = {
                "loading_feed_mol_kg": q_feed.get(key, 0.0),
                "loading_regenerated_mol_kg": q_cold.get(key, 0.0),
                "capacity_kmol": capacity,
            }
            if feed_key <= 0:
                entry["stoichiometric_time_h"] = math.inf
                entry["breakthrough_time_h"] = math.inf
            else:
                t_st = capacity / feed_key
                lub = 0.0
                if layer.mass_transfer_zone is not None:
                    mtz = v(layer.mass_transfer_zone, "length", [*loc, "mass_transfer_zone"])
                    lub = mtz / 2
                    entry["unused_bed_m"] = lub
                t_b = max(0.0, t_st * (1 - lub / length))
                entry["stoichiometric_time_h"] = t_st
                entry["breakthrough_time_h"] = t_b
                entry["margin"] = t_b / t_ads - 1
                if t_ads > t_b:
                    result.fail(
                        "adsorption-spec",
                        f"{key} breaks through layer {li} after {t_b:.3g} h, before the end of "
                        f"the {t_ads:.3g} h adsorption step",
                    )
            ii, iso = next((n, i) for n, i in enumerate(layer.isotherms) if i.component == key)
            leak = equilibrium_pressure(iso, q_cold.get(key, 0.0), temp)
            entry["product_mole_fraction"] = leak / p_ads
            held[key] = entry
            inventory[key] = inventory.get(key, 0.0) + feed_key * t_ads
            loaded_mol = (feed_key * t_ads) * 1000 / mass + q_cold.get(key, 0.0)  # mol/kg avg
            dh = v(
                iso.heat_of_adsorption,
                "molar_energy",
                [*loc, "isotherms", ii, "heat_of_adsorption"],
            )
            desorption_heat += mass * max(0.0, loaded_mol - q_hot.get(key, 0.0)) * dh
            # the desorbed key leaves the heated bed in equilibrium with the loading it had;
            # beyond the isotherm's highest pressure only that bound is used (conservative)
            p_top = min(iso.valid.partial_pressure[1], p_reg)
            if q_feed.get(key, 0.0) >= single_loading(iso, p_top, t_reg):
                entry["desorption_partial_pressure_kPa"] = None
                entry["desorption_mole_fraction"] = p_top / p_reg
                entry["desorption_bound"] = f"at least {p_top:g} kPa (the isotherm's range)"
            else:
                p_star = equilibrium_pressure(iso, q_feed.get(key, 0.0), t_reg)
                _check_range(worker, li, layer, {key: p_star}, t_reg, "desorption equilibrium")
                entry["desorption_partial_pressure_kPa"] = p_star
                entry["desorption_mole_fraction"] = p_star / p_reg
        # carriers: what the bed takes up between regenerated-cold and loaded states
        for ii, iso in enumerate(layer.isotherms):
            name = iso.component
            if name in own:
                continue
            uptake = mass * (q_feed.get(name, 0.0) - q_cold.get(name, 0.0)) / 1000
            inventory[name] = inventory.get(name, 0.0) + uptake
            dh = v(
                iso.heat_of_adsorption,
                "molar_energy",
                [*loc, "isotherms", ii, "heat_of_adsorption"],
            )
            desorption_heat += mass * max(0.0, q_feed.get(name, 0.0) - q_hot.get(name, 0.0)) * dh
        # the gas in the voids: at feed state at the end of feed, purge state after cooling
        for name in set(y_feed) | set(y_purge):
            if name in own:
                continue
            gas = void * volume * (p_feed.get(name, 0.0) - p_purge.get(name, 0.0))
            inventory[name] = inventory.get(name, 0.0) + gas / (GAS_CONSTANT * temp)
        sensible += mass * cp * (t_reg - temp)
        result.layers.append({"adsorbent": layer.adsorbent, "mass_kg": mass, "keys": held})
    sensible += vessel_cp * (t_reg - temp)
    bed_heat = sensible + desorption_heat  # kJ per bed per cycle
    # cycle balance (kmol per bed and cycle)
    fed = {k: flow * y * t_ads for k, y in y_feed.items()}
    purge_amount = purge_flow * (t_heat_h + t_cool_h)
    purged = {k: purge_amount * y for k, y in y_purge.items()}
    names = sorted(set(fed) | set(purged))
    # purge gas left in the voids enters the product when the bed goes back on feed
    product = {k: fed.get(k, 0.0) - inventory.get(k, 0.0) for k in names}
    for key in keys:
        if key in product:
            leak = max(
                e["keys"].get(key, {}).get("product_mole_fraction", 0.0) for e in result.layers
            )
            carriers = sum(n for k, n in product.items() if k not in keys)
            product[key] = leak * carriers
    negative = [k for k, n in product.items() if n < -1e-12 * max(1.0, fed.get(k, 0.0))]
    if negative:
        raise _Refused(
            f"case {case}: the bed takes up more {', '.join(negative)} per cycle than the feed "
            "brings (void gas or co-adsorption larger than the feed in one adsorption step)",
            ["cycle", "adsorption_time"],
            "check the bed size, the adsorption time and the purge composition",
        )
    waste = {k: fed.get(k, 0.0) + purged.get(k, 0.0) - product.get(k, 0.0) for k in names}
    scale = sum(fed.values()) + purge_amount
    short = [k for k, n in waste.items() if n < -1e-12 * scale]
    if short:
        raise _Refused(
            f"case {case}: the product carries more {', '.join(short)} per cycle than the feed "
            "and the purge bring (purge gas left in the voids larger than the waste)",
            ["cycle", "purge"],
            "check the purge composition and the regeneration pressure",
        )
    result.recoveries = {k: (product[k] / fed[k] if fed[k] > 0 else 0.0) for k in fed}
    total_product = sum(product.values())
    total_waste = sum(waste.values())
    result.product = {
        "flow_kmol_h": total_product / t_ads,
        "mole_fractions": {k: n / total_product for k, n in product.items()},
    }
    result.waste = {
        "flow_kmol_h": total_waste / t_ads,
        "mole_fractions": {k: n / total_waste for k, n in waste.items()},
        "purge_kmol_per_cycle": purge_amount,
    }
    residuals = {
        k: fed.get(k, 0.0) + purged.get(k, 0.0) - product.get(k, 0.0) - waste.get(k, 0.0)
        for k in names
    }
    result.closure = {
        "relative_residual": max(abs(r) for r in residuals.values()) / scale,
        "basis": "kmol per bed and cycle: feed + purge = product + waste; the waste is the "
        "balance remainder, so this holds by construction (a bookkeeping check, not "
        "independent evidence); product and waste are non-negative for every component",
    }
    # regeneration
    min_thermal = bed_heat / (purge_cp * (t_reg - temp))  # kmol of hot purge
    min_desorb = 0.0
    for entry in result.layers:
        for key, item in entry["keys"].items():
            y_out = item.get("desorption_mole_fraction") or 0.0
            if y_out > 0:
                min_desorb = max(min_desorb, inventory.get(key, 0.0) / min(1.0, y_out))
    hot_purge = purge_flow * t_heat_h
    heater_kw = purge_flow / 3600 * purge_cp * max(0.0, t_reg - t_supply)
    heater_kj = heater_kw * t_heat_h * 3600
    result.regeneration = {
        "bed_heat_kJ": bed_heat,
        "sensible_heat_kJ": sensible,
        "desorption_heat_kJ": desorption_heat,
        "hot_purge_kmol": hot_purge,
        "min_purge_thermal_kmol": min_thermal,
        "min_purge_desorption_kmol": min_desorb,
        "heater_duty_kW": heater_kw,
        "heater_energy_kWh_per_cycle": heater_kj / 3600,
        "specific_heater_energy_kJ_per_kmol_feed": heater_kj / (flow * t_ads),
        "regeneration_time_h": t_heat_h + t_cool_h + t_switch_h,
        "available_time_h": (cycle.beds - 1) * t_ads,
    }
    if hot_purge < min_thermal:
        result.fail(
            "adsorption-regeneration",
            f"the hot purge ({hot_purge:.4g} kmol) carries less heat than the bed needs "
            f"({min_thermal:.4g} kmol at {purge_cp:g} kJ/(kmol K))",
        )
    if hot_purge < min_desorb:
        result.fail(
            "adsorption-regeneration",
            f"the hot purge ({hot_purge:.4g} kmol) cannot carry the desorbed key components "
            f"at their equilibrium partial pressure ({min_desorb:.4g} kmol needed)",
        )
    if t_heat_h + t_cool_h + t_switch_h > (cycle.beds - 1) * t_ads * (1 + 1e-9):
        result.fail(
            "adsorption-regeneration",
            f"heating, cooling and switching take {t_heat_h + t_cool_h + t_switch_h:.3g} h, "
            f"more than the {(cycle.beds - 1) * t_ads:.3g} h the other bed(s) adsorb",
        )
    result.utilities = [
        {
            "name": "regeneration heat (purge heater)",
            "value": heater_kw,
            "unit": "kW",
            "basis": f"during the {t_heat_h:.3g} h heating of each bed",
        },
        {
            "name": "regeneration heat (purge heater)",
            "value": heater_kj / 3600 / t_ads,
            "unit": "kW",
            "basis": "average over the cycle",
        },
        {
            "name": "purge gas",
            "value": purge_amount / t_ads,
            "unit": "kmol/h",
            "basis": "average over the cycle",
        },
    ]
    _specification(worker, result, product, total_product)
    return result


def _specification(worker: _Unit, result: CaseResult, product: dict[str, float], total: float):
    for name, limit in worker.unit.specification.items():
        value = worker.value(limit, "fraction", ["specification", name])
        predicted = product.get(name, 0.0) / total if total > 0 else 0.0
        met = predicted <= value * (1 + 1e-9)
        result.specification[name] = {"limit": value, "predicted": predicted, "met": met}
        if not met:
            result.fail(
                "adsorption-spec",
                f"product {name} {predicted:.3g} mol/mol above the specification {value:.3g}",
            )
    for entry in result.layers:
        for key, item in entry["keys"].items():
            if key in result.specification and item.get("margin", 0.0) < 0:
                result.specification[key]["met"] = False


def _external_case(worker: _Unit, case: str, feed: dict[str, Any]) -> CaseResult:
    ext = worker.unit.external
    if ext is None:
        raise _Refused("performance: external needs external", ["external"], "give external")
    if not ext.source.strip():
        worker.unsourced.append("external.source")
    elif ext.source not in worker.sources:
        worker.sources.append(ext.source)
    result = CaseResult(case, "ok", feed=feed)
    rng = ext.operating_range
    outside = []
    t, p = feed["temperature_K"], feed["pressure_kPa"]
    if not rng.temperature[0] <= t <= rng.temperature[1]:
        outside.append(
            f"feed T = {t:.1f} K outside {rng.temperature[0]:g}-{rng.temperature[1]:g} K"
        )
    if not rng.pressure[0] <= p <= rng.pressure[1]:
        outside.append(f"feed p = {p:.1f} kPa outside {rng.pressure[0]:g}-{rng.pressure[1]:g} kPa")
    for name, (lo, hi) in rng.mole_fractions.items():
        y = feed["mole_fractions"].get(name, 0.0)
        if not lo <= y <= hi:
            outside.append(f"feed {name} {y:.4g} outside {lo:g}-{hi:g}")
    if outside:
        raise _Refused(
            f"case {case}: {'; '.join(outside)} (the operating range of {ext.model})",
            ["external", "operating_range"],
            "the external model's results hold only in its stated range",
            "adsorption-external-range",
        )
    missing = [k for k, y in feed["mole_fractions"].items() if y > 0 and k not in ext.recoveries]
    bad = [k for k, r in ext.recoveries.items() if not 0 <= r <= 1]
    if missing or bad:
        raise _Refused(
            "recoveries "
            + (f"missing for {', '.join(missing)}" if missing else "")
            + (f"; outside 0-1 for {', '.join(bad)}" if bad else ""),
            ["external", "recoveries"],
            "give the fraction of every feed component the model sends to the product",
            "adsorption-external-closure",
        )
    flow = feed["flow_kmol_h"]
    product = {k: flow * y * ext.recoveries[k] for k, y in feed["mole_fractions"].items()}
    waste = {k: flow * y - product[k] for k, y in feed["mole_fractions"].items()}
    result.recoveries = {k: ext.recoveries[k] for k in feed["mole_fractions"]}
    total = sum(product.values())
    result.product = {
        "flow_kmol_h": total,
        "mole_fractions": {k: n / total for k, n in product.items()} if total > 0 else {},
    }
    total_waste = sum(waste.values())
    result.waste = {
        "flow_kmol_h": total_waste,
        "mole_fractions": {k: n / total_waste for k, n in waste.items()} if total_waste else {},
    }
    result.closure = {
        "relative_residual": 0.0,
        "basis": "kmol/h: feed = product + waste, by construction from recoveries in 0-1 for "
        "every feed component",
    }
    result.utilities = [u.model_dump() for u in ext.utilities]
    _specification(worker, result, product, total)
    return result


def _split(worker: _Unit, result: AdsorberResult, outs: list[str], product: str, sim: Any) -> None:
    """Compare process/simulation.yaml's split of the unit with the calculated recoveries."""
    spec = sim.specs.get(worker.unit.id) if sim is not None else None
    if spec is None or not spec.recoveries:
        result.split = {
            "status": "not-compared",
            "detail": "process/simulation.yaml gives no recoveries for this unit",
        }
        return
    outlet = spec.recovery_outlet or outs[0]
    worst: tuple[float, str, str] = (0.0, "", "")
    rows = []
    for case in result.cases:
        for name, recovery in case.recoveries.items():
            calc = recovery if outlet == product else 1 - recovery
            given = float(spec.recoveries.get(name, 0.0))
            rows.append({"case": case.case, "component": name, "simulation": given, "basis": calc})
            if abs(given - calc) > worst[0]:
                worst = (abs(given - calc), name, case.case)
    tolerance = worker.unit.split_tolerance
    result.split = {
        "status": "consistent" if worst[0] <= tolerance else "differs",
        "recovery_outlet": outlet,
        "tolerance": tolerance,
        "largest_difference": worst[0],
        "rows": rows,
    }
    if worst[0] > tolerance:
        worker.add(
            "warning",
            "adsorption-split",
            f"process/simulation.yaml sends {worst[1]} to {outlet} with a recovery that differs "
            f"by {worst[0]:.4g} from this basis in case {worst[2]} (tolerance {tolerance:g}): the "
            "simulated split does not follow from it",
            ["split_tolerance"],
            f"set specs.{worker.unit.id}.recoveries to the recoveries `cheme process adsorption` "
            "reports, or change the basis",
        )


def evaluate(
    process: Process,
    data: Adsorption,
    doc: Any = None,
    sim: Any = None,
    case: str | None = None,
) -> tuple[list[AdsorberResult], list[Finding]]:
    """Every entry of *data* in every case (or only *case*), against the flowsheet and the
    simulation spec *sim* (None: none)."""
    cases = [c.id for c in process.flowsheet.cases]
    if case is not None:
        if case not in cases:
            raise UnknownCase(f"unknown case {case!r}; declared: {', '.join(cases)}")
        cases = [case]
    results: list[AdsorberResult] = []
    findings: list[Finding] = []
    seen: set[str] = set()
    for index, unit in enumerate(data.units):
        worker = _Unit(process, unit, index, doc)
        result = AdsorberResult(
            unit.id, unit.technique, unit.performance, "qualified", line=worker.at([])
        )
        if unit.id in seen:
            worker.add("error", "adsorption-schema", "listed twice", ["id"], "keep one entry")
        seen.add(unit.id)
        if unit.performance == "calculated":
            result.model = MODEL_VERSION
            result.assumptions = list(ASSUMPTIONS)
        else:
            result.model = (
                f"{unit.external.model} {unit.external.version}".strip() if unit.external else ""
            )
        try:
            if unit.performance == "calculated" and unit.technique == "psa":
                raise _Refused(
                    "core has no PSA cycle model (performance: calculated)",
                    ["performance"],
                    "give performance: external with the results of a cited PSA model, or keep "
                    "a sourced component_separator split in process/simulation.yaml",
                    "adsorption-unsupported",
                )
            _, product, outs = worker.node_ports()
            for case_id in cases:
                feed = worker.feed(case_id)
                if unit.performance == "calculated":
                    row = _tsa_case(worker, case_id, feed)
                else:
                    row = _external_case(worker, case_id, feed)
                row.status = "fail" if row.failures else "ok"
                result.cases.append(row)
            if any(r.status == "fail" for r in result.cases):
                result.status = "fail"
                for row in result.cases:
                    for failure in row.failures:
                        rule = failure["rule"]
                        worker.add(
                            "error",
                            rule,
                            f"case {row.case}: {failure['message']}",
                            ["cycle"] if rule == "adsorption-regeneration" else ["specification"],
                            "change the bed, the cycle or the purge; the calculated performance "
                            "does not meet the stated duty",
                        )
            _split(worker, result, outs, product, sim)
        except _Refused as refusal:
            result.status = "unsupported" if refusal.rule == "adsorption-unsupported" else "refused"
            result.cases = []
            worker.add("error", refusal.rule, str(refusal), refusal.loc, refusal.hint)
        result.sources = worker.sources
        result.unsourced = worker.unsourced
        if worker.unsourced:
            worker.add(
                "warning",
                "adsorption-unsourced",
                f"inputs without a source or assumed: {', '.join(worker.unsourced[:6])}"
                + (" ..." if len(worker.unsourced) > 6 else ""),
                [],
                "give each input with its source (paper, table, vendor datasheet)",
            )
        result.limitations = _limitations(unit, result)
        fed = {k for c in result.cases for k, y in c.feed.get("mole_fractions", {}).items() if y}
        for li, layer in enumerate(unit.layers if unit.performance == "calculated" else []):
            bare = sorted(fed - {i.component for i in layer.isotherms})
            if bare and result.cases:
                result.limitations.append(
                    f"layer {li} ({layer.adsorbent}): no isotherm for {', '.join(bare)}: treated "
                    "as not adsorbed (no co-adsorption loss, no competition with the key "
                    "components, whose capacity is then an upper bound)"
                )
        result.replacement = _replacement(worker, unit)
        result.fingerprint = value_fingerprint(
            {
                "model": MODEL_VERSION if unit.performance == "calculated" else result.model,
                "unit": unit.model_dump(mode="json", by_alias=True),
                "feeds": [c.feed for c in result.cases],
            }
        )
        results.append(result)
        findings += worker.findings
    return results, findings


def _replacement(worker: _Unit, unit: AdsorptionUnit) -> dict[str, Any]:
    """Adsorbent inventory and replacement rate: a consumable outside the cycle calculation."""
    if unit.performance != "calculated" or unit.cycle is None:
        return {}
    rows = []
    try:
        diameter = worker.value(unit.cycle.diameter, "length", ["cycle", "diameter"])
        for li, layer in enumerate(unit.layers):
            length = worker.value(layer.length, "length", ["layers", li, "length"])
            density = worker.value(layer.bulk_density, "density", ["layers", li, "bulk_density"])
            inventory = math.pi / 4 * diameter**2 * length * density * unit.cycle.beds
            row: dict[str, Any] = {"adsorbent": layer.adsorbent, "inventory_kg": inventory}
            if layer.life is not None:
                life = worker.value(layer.life, "time", ["layers", li, "life"]) / 8760
                row["life_a"] = life
                row["replacement_kg_per_a"] = inventory / life if life > 0 else None
            rows.append(row)
    except _Refused:
        return {}
    return {
        "layers": rows,
        "boundary": "adsorbent replacement and disposal are a consumable of the unit, outside "
        "the cycle calculation; capacity loss with ageing is not modelled",
    }


def _limitations(unit: AdsorptionUnit, result: AdsorberResult) -> list[str]:
    out = []
    if unit.performance == "external":
        out.append(
            "external performance model: core checks the operating range, the balance and the "
            "specification, not the performance itself"
        )
        return out
    for li, layer in enumerate(unit.layers):
        if layer.removes and layer.mass_transfer_zone is None:
            out.append(
                f"layer {li} ({layer.adsorbent}): no measured mass transfer zone, the bed is "
                "used to its stoichiometric capacity (optimistic)"
            )
        if layer.life is None:
            out.append(f"layer {li} ({layer.adsorbent}): no adsorbent life, no replacement rate")
        models = {iso.model for iso in layer.isotherms}
        if len(layer.isotherms) > 1 and (
            layer.mixture == "independent" or len(models) > 1 or models - {"langmuir", "sips"}
        ):
            out.append(
                f"layer {li} ({layer.adsorbent}): competition between "
                f"{', '.join(i.component for i in layer.isotherms)} is not modelled for "
                "single-component or mixed isotherm models"
            )
        if layer.mixture == "extended" and len(layer.isotherms) > 1:
            out.append(
                f"layer {li} ({layer.adsorbent}): extended (ideal competitive) mixture model, "
                "not checked against binary data"
            )
    absent = [k for k in unit.specification if not any(k in la.removes for la in unit.layers)]
    if absent:
        out.append(f"no layer removes {', '.join(absent)}: it passes with the carrier")
    out.append(
        "the thermal (heat of adsorption) front and the vessel's heat losses are not modelled"
    )
    return out


def adsorption_report(root: Path, case: str | None = None) -> AdsorptionReport:
    """``process/adsorption.yaml`` of the plant repository at *root*, evaluated in every case
    (or *case*). Writes nothing; input problems are findings."""
    from chemeascode.domains.process.model import load as load_process

    findings: list[Finding] = []
    data, doc, found = load(root)
    findings += found
    if data is None:
        return AdsorptionReport([], findings, source_revision(root, INPUTS))
    process, process_findings = load_process(root)
    if process is None:
        findings += [f for f in process_findings if f.level == "error"]
        return AdsorptionReport([], findings, source_revision(root, INPUTS))
    sim = None
    if (root / "process/simulation.yaml").is_file():
        from chemeascode.domains.process.simulation.translate import load as load_sim

        sim, _, _ = load_sim(root)
    units, unit_findings = evaluate(process, data, doc, sim, case)
    paths = [*INPUTS, *(["process/simulation.yaml"] if sim is not None else [])]
    return AdsorptionReport(units, findings + unit_findings, source_revision(root, paths))


def adsorption_text(report: AdsorptionReport) -> str:
    """The report as text, one block per unit."""
    if not report.units and not report.findings:
        return f"no {ADSORPTION_FILE}"
    lines: list[str] = []
    for unit in report.units:
        lines.append(
            f"{unit.id}: {unit.technique.upper()} {unit.performance} ({unit.model}) "
            f"{unit.status}; split {unit.split.get('status', '-')}"
        )
        for row in unit.cases:
            rec = ", ".join(f"{k} {v:.4f}" for k, v in sorted(row.recoveries.items()))
            lines.append(f"  case {row.case}: {row.status}; recovery to product: {rec}")
            for entry in row.layers:
                for key, item in entry["keys"].items():
                    lines.append(
                        f"    {entry['adsorbent']}: {key} breakthrough "
                        f"{item['breakthrough_time_h']:.3g} h (stoichiometric "
                        f"{item['stoichiometric_time_h']:.3g} h)"
                    )
            if row.regeneration:
                reg = row.regeneration
                lines.append(
                    f"    regeneration: bed heat {reg['bed_heat_kJ']:.4g} kJ/cycle, heater "
                    f"{reg['heater_duty_kW']:.4g} kW while heating, hot purge "
                    f"{reg['hot_purge_kmol']:.4g} kmol (needs {reg['min_purge_thermal_kmol']:.4g} "
                    f"thermal, {reg['min_purge_desorption_kmol']:.4g} desorption)"
                )
            for name, spec in row.specification.items():
                lines.append(
                    f"    spec {name}: {spec['predicted']:.3g} <= {spec['limit']:.3g}: "
                    f"{'met' if spec['met'] else 'NOT met'}"
                )
        for limitation in unit.limitations:
            lines.append(f"  limitation: {limitation}")
    lines += [f.format() for f in report.findings]
    return "\n".join(lines)
