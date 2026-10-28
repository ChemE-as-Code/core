"""Stream properties: a small adapter over ``thermo`` (optional extra ``props``).

``flash(inputs)`` returns molar mass, phase and vapour fraction, density and enthalpy for one
stream state (temperature, absolute pressure, composition), with the property package of the
process (:mod:`.property_packages`: recorded in materials.yaml ``property_method.package``, or
chosen from the streams' components). The release-1 package, ``air-pr-chemsep``:

- vapour-liquid equilibrium, phase and vapour fraction: Peng-Robinson (thermo ``PRMIX``, both
  phases), binary interaction parameters ``ChemSep PR`` from thermo's ``IPDB``;
- vapour density: Peng-Robinson; liquid density: COSTALD (``chemicals.volume.COSTALD_mixture``,
  Hankinson-Thomson); a two-phase state gets no density;
- enthalpy: thermo's reference, ideal gas at 298.15 K and 101.325 kPa, in kJ/kmol.

That package is claimed only inside :data:`VALIDATED` (see ``tests/test_process_props.py`` and
its reference data with sources); every package only inside its own validated range (per
component and pair where it declares them). A state outside it, an absolute pressure that is not
positive, a component or pair outside the claim (the message names the nearest other package and
what it lacks), a stream holding a solid component (``phase: solid``: a slurry or a cake, never
flashed as a fluid), or a liquid of a component below its melting point is refused: nothing is
written, and existing calculated values stay and show as stale once their inputs changed
(``cheme.process-calculated-stale``). A vapour-only package refuses liquid, two-phase and VLE
results.

A stream whose phase is given or assumed as ``vapor`` or ``liquid`` while the flash puts it in
the other phase (or two-phase), as a saturated vapour a hundredth of a kelvin on the wrong side
of its dew point, is calculated phase-constrained: ``flash(inputs, phase=...)`` evaluates that
phase's root of the Peng-Robinson equation of state at T and P (liquid density still COSTALD).
It is refused when the EOS has no such root (beyond the spinodal; ``property-phase``) or when the
root is metastable beyond :data:`METASTABLE_TOLERANCE`, its molar Gibbs energy above the stable
flash's by more than that fraction of RT (``property-metastable``).

Everything but :class:`Adapter` works without thermo: ``validate`` computes fingerprints with it.
"""

from __future__ import annotations

import atexit
import hashlib
import json
import math
import sys
import warnings
from dataclasses import dataclass, field
from typing import Any

from chemeascode.domains.process import property_packages as packages
from chemeascode.domains.process.model import Process
from chemeascode.domains.process.property_packages import AIR, EOS, KIJ, Choice, Package
from chemeascode.domains.process.schema import ApplicationRange, PropertyMethod
from chemeascode.foundation.units import to_kelvin, to_kpa_abs

#: CAS numbers the release-1 method is validated for (package ``air-pr-chemsep``).
SUPPORTED_CAS = AIR.components
#: What the reference tests cover; nothing outside it is claimed.
VALIDATED = AIR.validated
#: The release-1 models (EOS and KIJ, imported above, are re-exported with them).
PHASE_MODELS = AIR.phase_models
__all__ = ["EOS", "KIJ", "PHASE_MODELS", "SUPPORTED_CAS", "VALIDATED"]
#: The enthalpy reference thermo's values are on.
ENTHALPY_REFERENCE = {"state": "ideal_gas", "temperature": 298.15, "pressure": 101.325}
#: Mole fraction below which a component is dropped (zeros in a template).
TRACE = 1e-12
#: How far a phase-constrained root may be metastable: (G_root - G_stable) / RT, the molar Gibbs
#: energy of the constrained phase above that of the stable flash at the same T, P and
#: composition. 0.01 is about 0.1 K across the saturation line of nitrogen or oxygen near
#: 1.3 bar(a) (dG/RT ~ h_vap dT / (R T^2)); further from it the given phase is a finding.
METASTABLE_TOLERANCE = 0.01
#: Universal gas constant, J/(mol K).
R_GAS = 8.314462618


class Unsupported(Exception):
    """A state the method does not support or is not claimed for; *rule* is the finding rule."""

    def __init__(self, rule: str, message: str) -> None:
        super().__init__(message)
        self.rule = rule


@dataclass
class Inputs:
    """One stream state, on the method's basis."""

    temperature: float  # K
    pressure: float  # kPa(a)
    fractions: dict[str, float]  # component id -> mole fraction, normalised, no traces


@dataclass
class Result:
    molar_mass: float  # kg/kmol
    phase: str  # vapor, liquid, two-phase
    vapor_fraction: float
    density: float | None  # kg/m3; None for two-phase
    enthalpy: float  # kJ/kmol on ENTHALPY_REFERENCE
    #: Phase-constrained (``flash(inputs, phase=...)``): the phase of the stable flash, which
    #: differs from :attr:`phase`, and the root's (G - G_stable) / RT; None when unconstrained.
    stable_phase: str | None = None
    metastability: float | None = None

    @property
    def constrained(self) -> bool:
        return self.stable_phase is not None


@dataclass
class Gathered:
    inputs: Inputs | None
    missing: list[str] = field(default_factory=list)
    problems: list[tuple[str, str]] = field(default_factory=list)


def gather(process: Process, stream: Any, case: str) -> Gathered:
    """The flash inputs of *stream* in *case*, or what is missing or wrong with them."""
    fs = process.flowsheet
    state = stream.state.get(case)
    if stream.kind != "material":
        return Gathered(None, [f"{stream.id} is a {stream.kind} stream"])
    if state is None:
        return Gathered(None, [f"{stream.id} state for case {case}"])
    missing = []
    problems: list[tuple[str, str]] = []
    kelvin = kpa = None
    if state.temperature is None:
        missing.append("temperature")
    else:
        kelvin = to_kelvin(state.temperature.value, state.temperature.unit or fs.units.temperature)
    if state.pressure is None:
        missing.append("pressure")
    else:
        unit = state.pressure.unit or fs.units.pressure
        kpa = to_kpa_abs(state.pressure.value, unit)
        if kpa is None:
            problems.append(
                ("property-unsupported", f"pressure unit {unit} is not absolute (no ambient given)")
            )
        elif kpa <= 0:
            problems.append(
                ("property-unsupported", f"absolute pressure {kpa:g} kPa(a) is not positive")
            )
    if state.composition is None:
        missing.append("composition")
    if missing or problems or kelvin is None or kpa is None:
        return Gathered(None, missing, problems)
    comp = state.composition
    comps = process.components()
    values = {k: v for k, v in comp.values.items() if v > TRACE}
    held = sorted(k for k in values if getattr(comps.get(k), "phase", None) == "solid")
    if held:
        return Gathered(
            None,
            problems=[
                (
                    "property-unsupported",
                    f"it holds the solid {', '.join(held)} (phase: solid): the property routes "
                    "have no solid phase (methods.yml solid_equilibrium)",
                )
            ],
        )
    if comp.basis == "mass_fraction":
        lacking = [k for k in values if not getattr(comps.get(k), "molar_mass", None)]
        if lacking:
            return Gathered(None, [f"molar_mass of {k}" for k in lacking])
        values = {k: v / comps[k].molar_mass for k, v in values.items()}
    total = sum(values.values())
    if total <= 0:
        return Gathered(None, ["composition (all zero)"])
    fractions = {k: v / total for k, v in values.items()}
    return Gathered(Inputs(kelvin, kpa, fractions))


# -- method, range, fingerprints ----------------------------------------------------------------


def method_config(process: Process) -> PropertyMethod:
    """The recorded method (materials.yaml ``property_method``), or the release-1 default."""
    method = process.materials.property_method if process.materials else None
    return method or PropertyMethod()


def stream_mixtures(process: Process) -> list[set[str]]:
    """The CAS sets of the streams' compositions (every case; ``""`` for a component without a
    CAS number), or of the components when no stream has a composition."""
    comps = process.components()
    found: list[set[str]] = []
    for stream in process.flowsheet.streams:
        if stream.kind != "material":
            continue
        for state in stream.state.values():
            comp = state.composition
            if comp is None:
                continue
            cas = {
                getattr(comps.get(k), "cas", "") or "" for k, v in comp.values.items() if v > TRACE
            }
            if cas and cas not in found:
                found.append(cas)
    if not found and comps:
        found.append({c.cas or "" for c in comps.values()})
    return found


def choose_package(process: Process) -> Choice:
    """The process's property package and why (:func:`.property_packages.choose`)."""
    method = method_config(process)
    return packages.choose(
        method.package,
        legacy=method.status == "configured" and method.package is None,
        mixtures=stream_mixtures(process),
    )


def package_of(process: Process) -> Package:
    """The process's property package; :class:`Unsupported` when it names an unknown one."""
    choice = choose_package(process)
    if choice.package is None:
        raise Unsupported("property-unsupported", choice.reason)
    return choice.package


def claimed_range(process: Process) -> ApplicationRange:
    """The range the method is used in: the configured one, never wider than the package's
    validated range (:data:`VALIDATED` for the release-1 package)."""
    package = package_of(process)
    validated = package.validated
    method = method_config(process)
    own = method.application_range if method.status == "configured" else None
    if own is not None and (method.package or packages.LEGACY.id) != package.id:
        own = None  # recorded for another package
    if own is None:
        return validated

    def narrow(a, b):
        if a is None or b is None:
            return b
        return (max(a[0], b[0]), min(a[1], b[1]))

    pairs = validated.pairs
    if own.pairs is not None and pairs is not None:
        pairs = [p for p in own.pairs if p in pairs]
    return ApplicationRange(
        temperature=narrow(own.temperature, validated.temperature),
        pressure=narrow(own.pressure, validated.pressure),
        vle_pressure=narrow(own.vle_pressure, validated.vle_pressure),
        phases=[p for p in (own.phases or validated.phases) if p in validated.phases],
        components=[c for c in (own.components or validated.components) if c in package.components],
        component_regions=validated.component_regions,
        pairs=pairs,
        pair_limits=validated.pair_limits,
    )


def elsewhere(process: Process, cas: set[str], inputs: Inputs | None = None) -> str:
    """Which other package covers the mixture *cas* (at *inputs*), or the nearest package and,
    when it is another one, what it lacks: the tail of a refusal."""
    own = package_of(process)
    best: tuple[tuple[int, int, int], Package, list[str]] | None = None
    by_cas = _by_cas(process, inputs) if inputs is not None else None
    for package in packages.PACKAGES:
        gaps = packages.component_gaps(package, cas)
        regions: list[str] = []
        if not gaps and inputs is not None:
            if not packages.in_overall(package.validated, inputs.temperature, inputs.pressure):
                regions.append("the state is outside its overall range")
            regions += packages.region_gaps(
                package, cas, inputs.temperature, inputs.pressure, fractions=by_cas
            )
            regions += packages.limit_gaps(package, by_cas or {})
        if package is not own and not gaps and not regions:
            return (
                f"package {package.id} covers it, but this process uses {own.id} (one package "
                "per process: property_method.package in process/materials.yaml)"
            )
        key = (sum(g.startswith("component") for g in gaps), len(gaps), len(regions))
        if best is None or key < best[0] or (key == best[0] and package is own):
            best = (key, package, gaps + regions)
    assert best is not None
    if best[1] is own:
        return f"no package covers it; the nearest is this process's {own.id}"
    return f"no package covers it; the nearest, {best[1].id}, lacks " + "; ".join(best[2])


def range_problems(process: Process, inputs: Inputs) -> list[tuple[str, str]]:
    """Why *inputs* are outside the claimed range (rule, message); empty when inside."""
    package = package_of(process)
    claim = claimed_range(process)
    comps = process.components()
    found: list[tuple[str, str]] = []
    cas_set = {getattr(comps.get(n), "cas", "") or "" for n in inputs.fractions}
    for name in inputs.fractions:
        comp = comps.get(name)
        cas = getattr(comp, "cas", "")
        if comp is None or cas not in claim.components:
            found.append(
                (
                    "property-unsupported",
                    f"component {name} ({cas or 'no CAS'}) is outside the supported mixture "
                    f"({', '.join(package.name(c) for c in claim.components)})",
                )
            )
    if not found and claim.pairs is not None:
        gaps = packages.component_gaps(package, cas_set, claim)
        if gaps:
            found.append(
                (
                    "property-unsupported",
                    f"{', '.join(gaps)}: package {package.id} claims a mixture only when every "
                    "pair in it is benchmarked",
                )
            )
    if found:
        rule, message = found[0]
        found[0] = (rule, f"{message}; {elsewhere(process, cas_set, inputs)}")
    lo, hi = claim.temperature or (0.0, float("inf"))
    if not lo <= inputs.temperature <= hi:
        found.append(
            (
                "property-out-of-range",
                f"temperature {inputs.temperature:.2f} K outside the claimed {lo:g} to {hi:g} K",
            )
        )
    lo, hi = claim.pressure or (0.0, float("inf"))
    if not lo <= inputs.pressure <= hi:
        found.append(
            (
                "property-out-of-range",
                f"pressure {inputs.pressure:g} kPa(a) outside the claimed {lo:g} to {hi:g} kPa(a)",
            )
        )
    if not found:
        by_cas = _by_cas(process, inputs)
        limits = packages.limit_gaps(package, by_cas, claim)
        if limits:
            found.append(
                (
                    "property-out-of-range",
                    f"{', '.join(limits)}: package {package.id} claims these pairs only up to "
                    "the benchmarked mole fractions",
                )
            )
        regions = packages.region_gaps(
            package, cas_set, inputs.temperature, inputs.pressure, claim, by_cas
        )
        if regions:
            found.append(
                (
                    "property-out-of-range",
                    f"{inputs.temperature:.2f} K, {inputs.pressure:g} kPa(a) is outside the "
                    f"benchmarked region of package {package.id}: {'; '.join(regions)}",
                )
            )
    return found


def _by_cas(process: Process, inputs: Inputs) -> dict[str, float]:
    """The mole fractions of *inputs* by CAS number (components without one left out)."""
    comps = process.components()
    found: dict[str, float] = {}
    for name, x in inputs.fractions.items():
        cas = getattr(comps.get(name), "cas", "") or ""
        if cas:
            found[cas] = found.get(cas, 0.0) + x
    return found


#: Range fields added with property packages: left out of the fingerprint while unset, so the
#: values of a method recorded before them stay current. ``package`` and ``benchmark`` are a label
#: and evidence (the package's models and range are in the other fields): never in it.
_ADDED_RANGE_FIELDS = ("component_regions", "pairs", "pair_limits")


def method_fingerprint(method: PropertyMethod) -> str:
    data = method.model_dump(mode="json", exclude={"status", "package", "benchmark"})
    claim = data.get("application_range")
    if claim:
        for key in _ADDED_RANGE_FIELDS:
            if claim.get(key) is None:
                claim.pop(key, None)
        for boxes in (claim.get("component_regions") or {}).values():
            for box in boxes:
                if box.get("max_mole_fraction") is None:
                    box.pop("max_mole_fraction", None)
    return hashlib.sha256(json.dumps(data, sort_keys=True).encode()).hexdigest()[:16]


def fingerprint(
    process: Process, stream: Any, case: str, constrained: str | None = None
) -> str | None:
    """The input fingerprint of *stream*'s calculated values in *case*: temperature, pressure,
    composition and the recorded method, and the phase for values calculated phase-constrained
    (*constrained*, the given phase). None when an input is missing."""
    found = gather(process, stream, case)
    if found.inputs is None:
        return None
    inputs = found.inputs
    data = {
        "T_K": round(inputs.temperature, 6),
        "P_kPa": round(inputs.pressure, 6),
        "x": {k: round(v, 9) for k, v in sorted(inputs.fractions.items())},
        "method": method_fingerprint(method_config(process)),
    }
    if constrained is not None:
        data["phase_root"] = constrained
    return hashlib.sha256(json.dumps(data, sort_keys=True).encode()).hexdigest()[:16]


def stale(process: Process, stream: Any, case: str) -> list[str]:
    """Names of *stream*'s calculated values in *case* whose fingerprint no longer matches,
    including the values written by ``cheme process propagate`` and ``cheme process simulate``
    (state and duty)."""
    from chemeascode.domains.process import propagate
    from chemeascode.domains.process.simulation import translate

    state = stream.state.get(case)
    if state is None:
        return []
    marked = {name: q.fingerprint for name, q in state.calculated.items() if q.fingerprint}
    if state.phase is not None and state.phase.fingerprint:
        marked["phase"] = state.phase.fingerprint
    found = propagate.stale_fields(process, stream, case)
    found += translate.stale_fields(process, stream, case)
    if not marked:
        return found
    current = {fingerprint(process, stream, case)}
    given = constraining_phase(state)
    if given is not None:  # values calculated on the given phase's root stay current with it
        current.add(fingerprint(process, stream, case, constrained=given))
    return [name for name, fp in marked.items() if fp not in current] + found


def constraining_phase(state: Any) -> str | None:
    """The phase a state's properties are calculated in when the flash disagrees: a given or
    assumed ``vapor`` or ``liquid`` (None for none, a calculated phase or two-phase)."""
    phase = getattr(state, "phase", None)
    if phase is None or phase.provenance == "calculated" or phase.value == "two-phase":
        return None
    return phase.value


# -- the thermo adapter -------------------------------------------------------------------------


def versions() -> dict[str, str]:
    from importlib.metadata import version

    return {name: version(name) for name in ("thermo", "chemicals")}


def _close_thermo_db() -> None:
    """Close the sqlite connection thermo opens on import (``thermo.unifac``, per thread) and
    never closes, which otherwise prints ``ResourceWarning: unclosed database`` at exit."""
    storage = getattr(sys.modules.get("thermo.unifac"), "thread_local_storage", None)
    conn = getattr(storage, "conn", None)
    if conn is not None:
        conn.close()
        storage.conn = None


def phase_root(flasher: Any, temperature: float, pressure: float, zs: list[float], phase: str):
    """thermo's *phase* (``vapor`` or ``liquid``) of *flasher* at *temperature* K and *pressure*
    Pa on that phase's root of the cubic EOS, or None when the EOS has only the other root there
    (beyond the spinodal: thermo would quietly fall back to it)."""
    template = flasher.gas if phase == "vapor" else flasher.liquid
    one = template.to(T=temperature, P=pressure, zs=zs)
    return one if hasattr(one.eos_mix, "V_g" if phase == "vapor" else "V_l") else None


class Adapter:
    """thermo, configured once per component set."""

    def __init__(self, process: Process) -> None:
        try:
            with warnings.catch_warnings():
                warnings.simplefilter("ignore")
                import thermo  # noqa: F401
        except ImportError as failure:
            raise Unsupported(
                "property-unsupported",
                "thermo is not installed: install cheme-as-code with the props extra "
                "(uv tool install 'cheme-as-code[props]')",
            ) from failure
        atexit.unregister(_close_thermo_db)  # once, however many adapters
        atexit.register(_close_thermo_db)
        self.process = process
        self.package = package_of(process)
        self._flashers: dict[tuple[str, ...], Any] = {}

    def _flasher(self, cas: tuple[str, ...]) -> Any:
        if cas not in self._flashers:
            with warnings.catch_warnings():
                warnings.simplefilter("ignore")
                from thermo import PRMIX, CEOSGas, CEOSLiquid, ChemicalConstantsPackage, FlashVL
                from thermo.interaction_parameters import IPDB

                constants, correlations = ChemicalConstantsPackage.from_IDs(list(cas))
                kijs = IPDB.get_ip_asymmetric_matrix("ChemSep PR", list(cas), "kij")
                kwargs = {
                    "Tcs": constants.Tcs,
                    "Pcs": constants.Pcs,
                    "omegas": constants.omegas,
                    "kijs": kijs,
                }
                gas = CEOSGas(PRMIX, kwargs, HeatCapacityGases=correlations.HeatCapacityGases)
                liquid = CEOSLiquid(PRMIX, kwargs, HeatCapacityGases=correlations.HeatCapacityGases)
                self._flashers[cas] = (
                    FlashVL(constants, correlations, liquid=liquid, gas=gas),
                    constants,
                )
        return self._flashers[cas]

    def _zs(self, fractions: dict[str, float]) -> tuple[tuple[str, ...], list[float]]:
        """Mole fractions over every component of the package (zeros included: thermo's FlashVL
        fails for a single component, and one flasher serves every stream)."""
        comps = self.process.components()
        cas = tuple(sorted(self.package.components))
        by_cas = {comps[n].cas: x for n, x in fractions.items()}
        return cas, [by_cas.get(c, 0.0) for c in cas]

    def _vle_claimed(self, what: str) -> None:
        """:class:`Unsupported` when the package claims no liquid (a vapour-only package)."""
        if "liquid" not in claimed_range(self.process).phases:
            raise Unsupported(
                "property-unsupported",
                f"{what}: package {self.package.id} claims vapour only (no liquid, two-phase or "
                "VLE results)",
            )

    def _supercritical(self, flasher: Any, constants: Any, inputs: Inputs, zs: list[float]):
        """For a vapour-only package: the phase object of a single-phase state on the only real
        root of the EOS above the pseudo-critical temperature (Kay: sum of x Tc), which thermo
        may label liquid; None otherwise."""
        tpc = sum(x * tc for x, tc in zip(zs, constants.Tcs, strict=True))
        if inputs.temperature < tpc:
            return None
        one = flasher.gas.to(T=inputs.temperature, P=inputs.pressure * 1000.0, zs=zs)
        roots = hasattr(one.eos_mix, "V_g") + hasattr(one.eos_mix, "V_l")
        return one if roots == 1 else None

    def saturation_temperature(
        self, pressure: float, fractions: dict[str, float], vapor_fraction: float = 0.0
    ) -> float:
        """Bubble (*vapor_fraction* 0) or dew (1) temperature in K at *pressure* kPa(a)."""
        self._vle_claimed("saturation temperature")
        cas, zs = self._zs(fractions)
        flasher, _ = self._flasher(cas)
        with warnings.catch_warnings():
            warnings.simplefilter("ignore")
            state = flasher.flash(P=pressure * 1000.0, VF=vapor_fraction, zs=zs)
        return float(state.T)

    def flash(self, inputs: Inputs, phase: str | None = None) -> Result:
        """Properties at *inputs*; :class:`Unsupported` when the method is not claimed there.

        With *phase* (``vapor`` or ``liquid``) and a stable flash in another phase, the
        properties of that phase's EOS root at T and P (:meth:`_constrained`)."""
        result, state = self._stable(inputs)
        if phase in (None, "two-phase", result.phase):
            return result
        return self._constrained(inputs, phase, result, state)[0]

    def _stable(self, inputs: Inputs) -> tuple[Result, Any]:
        problems = range_problems(self.process, inputs)
        if problems:
            raise Unsupported(*problems[0])
        cas, zs = self._zs(inputs.fractions)
        names = [self.package.name(c) for c in cas]
        flasher, constants = self._flasher(cas)
        with warnings.catch_warnings():
            warnings.simplefilter("ignore")
            from chemicals.volume import COSTALD_mixture

            try:
                state = flasher.flash(T=inputs.temperature, P=inputs.pressure * 1000.0, zs=zs)
            except Exception as failure:  # thermo raises plain exceptions on non-convergence
                raise Unsupported("property-unsupported", f"flash failed: {failure}") from failure
            vf = float(state.VF)
            phase = "vapor" if vf >= 1.0 - 1e-9 else "liquid" if vf <= 1e-9 else "two-phase"
            if phase == "liquid" and self.package.vapor_only:
                one = self._supercritical(flasher, constants, inputs, zs)
                if one is not None:
                    state, vf, phase = one, 1.0, "vapor"
        claim = claimed_range(self.process)
        if phase not in claim.phases:
            only = (
                f" (package {self.package.id} claims vapour only)"
                if (self.package.vapor_only)
                else ""
            )
            raise Unsupported("property-unsupported", f"phase {phase} is not claimed{only}")
        if phase != "vapor":
            lo, hi = claim.vle_pressure or claim.pressure or (0.0, float("inf"))
            if not lo <= inputs.pressure <= hi:
                raise Unsupported(
                    "property-out-of-range",
                    f"{phase} at {inputs.pressure:g} kPa(a): liquid and two-phase results are "
                    f"claimed from {lo:g} to {hi:g} kPa(a) only",
                )
            for name, x, tm in zip(names, zs, constants.Tms, strict=True):
                if x >= 0.5 and tm and inputs.temperature < tm:
                    raise Unsupported(
                        "property-unsupported",
                        f"liquid of {name} below its melting point {tm:g} K: solids are not "
                        "supported",
                    )
        mw = sum(x * m for x, m in zip(zs, constants.MWs, strict=True))
        density = None
        if phase == "vapor":
            if self.package.vapor_only:  # state may be the EOS root's phase object
                density = mw / float(state.V()) / 1000.0
            else:
                density = float(state.rho_mass())
        elif phase == "liquid":
            volume = COSTALD_mixture(
                zs, inputs.temperature, constants.Tcs, constants.Vcs, constants.omegas
            )
            density = mw / volume / 1000.0
        result = Result(
            molar_mass=mw,
            phase=phase,
            vapor_fraction=vf,
            density=density,
            enthalpy=float(state.H()),
        )
        return result, state

    def _constrained(
        self, inputs: Inputs, phase: str, stable: Result, state: Any
    ) -> tuple[Result, Any]:
        """The *phase* root of the EOS at *inputs* (a stable flash *stable*, *state* in another
        phase), and thermo's phase object; :class:`Unsupported` when the root does not exist
        (``property-phase``) or is metastable beyond :data:`METASTABLE_TOLERANCE`
        (``property-metastable``)."""
        if phase not in ("vapor", "liquid"):
            raise ValueError(f"no constrained flash for phase {phase!r}")
        cas, zs = self._zs(inputs.fractions)
        names = [self.package.name(c) for c in cas]
        flasher, constants = self._flasher(cas)
        where = f"{inputs.temperature:.3f} K, {inputs.pressure:g} kPa(a)"
        claim = claimed_range(self.process)
        if phase not in claim.phases:
            raise Unsupported("property-unsupported", f"phase {phase} is not claimed")
        if phase == "liquid":
            lo, hi = claim.vle_pressure or claim.pressure or (0.0, float("inf"))
            if not lo <= inputs.pressure <= hi:
                raise Unsupported(
                    "property-out-of-range",
                    f"liquid at {inputs.pressure:g} kPa(a): liquid results are claimed from "
                    f"{lo:g} to {hi:g} kPa(a) only",
                )
            for name, x, tm in zip(names, zs, constants.Tms, strict=True):
                if x >= 0.5 and tm and inputs.temperature < tm:
                    raise Unsupported(
                        "property-unsupported",
                        f"liquid of {name} below its melting point {tm:g} K: solids are not "
                        "supported",
                    )
        with warnings.catch_warnings():
            warnings.simplefilter("ignore")
            from chemicals.volume import COSTALD_mixture

            one = phase_root(flasher, inputs.temperature, inputs.pressure * 1000.0, zs, phase)
            if one is None:
                raise Unsupported(
                    "property-phase",
                    f"the Peng-Robinson equation of state has no {phase} root at {where} (beyond "
                    f"its spinodal); the flash gives {stable.phase}",
                )
            excess = (float(one.G()) - float(state.G())) / (R_GAS * inputs.temperature)
            if excess > METASTABLE_TOLERANCE:
                raise Unsupported(
                    "property-metastable",
                    f"the {phase} root at {where} is metastable beyond the tolerance: its Gibbs "
                    f"energy is {excess:.3g} RT above the stable {stable.phase} state's (allowed "
                    f"{METASTABLE_TOLERANCE:g} RT)",
                )
            if phase == "vapor":
                density = stable.molar_mass / float(one.V()) / 1000.0
            else:
                volume = COSTALD_mixture(
                    zs, inputs.temperature, constants.Tcs, constants.Vcs, constants.omegas
                )
                density = stable.molar_mass / volume / 1000.0
            enthalpy = float(one.H())
        result = Result(
            molar_mass=stable.molar_mass,
            phase=phase,
            vapor_fraction=1.0 if phase == "vapor" else 0.0,
            density=density,
            enthalpy=enthalpy,
            stable_phase=stable.phase,
            metastability=excess,
        )
        return result, one

    # -- sizing (cheme datasheets fill): the same flasher, each state range-checked --------

    def _checked(self, temperature: float, pressure: float, fractions: dict[str, float]) -> None:
        problems = range_problems(self.process, Inputs(temperature, pressure, fractions))
        if problems:
            raise Unsupported(*problems[0])

    def _vapor_state(self, inputs: Inputs, what: str) -> Any:
        """thermo's state at *inputs*, range-checked, :class:`Unsupported` unless vapour (for a
        vapour-only package: as :meth:`_stable` decides it)."""
        self._checked(inputs.temperature, inputs.pressure, inputs.fractions)
        state = self._raw(inputs.fractions, T=inputs.temperature, P=inputs.pressure * 1000.0)
        if float(state.VF) >= 1.0 - 1e-9:
            return state
        if self.package.vapor_only and float(state.VF) <= 1e-9:
            cas, zs = self._zs(inputs.fractions)
            flasher, constants = self._flasher(cas)
            with warnings.catch_warnings():
                warnings.simplefilter("ignore")
                one = self._supercritical(flasher, constants, inputs, zs)
            if one is not None:
                return one
        raise Unsupported("property-unsupported", f"{what} asked of a state that is not vapour")

    def _raw(self, fractions: dict[str, float], **spec: float) -> Any:
        cas, zs = self._zs(fractions)
        flasher, _ = self._flasher(cas)
        with warnings.catch_warnings():
            warnings.simplefilter("ignore")
            try:
                return flasher.flash(zs=zs, **spec)
            except Exception as failure:  # thermo raises plain exceptions on non-convergence
                raise Unsupported("property-unsupported", f"flash failed: {failure}") from failure

    def entropy(self, inputs: Inputs, phase: str | None = None) -> float:
        """Molar entropy at *inputs*, kJ/(kmol K), on thermo's ideal-gas reference; with
        *phase*, of that phase's EOS root where the flash gives another (as :meth:`flash`)."""
        if phase not in (None, "two-phase"):
            result, state = self._stable(inputs)
            if result.phase != phase:
                return float(self._constrained(inputs, phase, result, state)[1].S())
        if self.package.vapor_only:
            return float(self._vapor_state(inputs, "entropy").S())
        self._checked(inputs.temperature, inputs.pressure, inputs.fractions)
        state = self._raw(inputs.fractions, T=inputs.temperature, P=inputs.pressure * 1000.0)
        return float(state.S())

    def heat_capacity_ratio(self, inputs: Inputs) -> float:
        """Cp/Cv of a vapour at *inputs* (Peng-Robinson)."""
        return float(self._vapor_state(inputs, "Cp/Cv").Cp_Cv_ratio())

    def flash_ps(self, pressure: float, entropy: float, fractions: dict[str, float]) -> Result:
        """The state at *pressure* kPa(a) and molar *entropy* (an isentropic step)."""
        state = self._raw(fractions, P=pressure * 1000.0, S=entropy)
        return self.flash(Inputs(float(state.T), pressure, fractions))

    def flash_ph(self, pressure: float, enthalpy: float, fractions: dict[str, float]) -> Result:
        """The state at *pressure* kPa(a) and molar *enthalpy* kJ/kmol."""
        state = self._raw(fractions, P=pressure * 1000.0, H=enthalpy)
        return self.flash(Inputs(float(state.T), pressure, fractions))

    def bubble_pressure(self, temperature: float, fractions: dict[str, float]) -> float:
        """Bubble-point pressure (the vapour pressure of the liquid) at *temperature* K, kPa(a);
        refused outside the claimed temperature range and VLE pressure range."""
        self._vle_claimed("bubble pressure")
        state = self._raw(fractions, T=temperature, VF=0.0)
        pressure = float(state.P) / 1000.0
        self._checked(temperature, pressure, fractions)
        claim = claimed_range(self.process)
        lo, hi = claim.vle_pressure or claim.pressure or (0.0, float("inf"))
        if not lo <= pressure <= hi:
            raise Unsupported(
                "property-out-of-range",
                f"bubble pressure {pressure:g} kPa(a) outside the claimed VLE range {lo:g} to "
                f"{hi:g} kPa(a)",
            )
        return pressure

    def k_values(
        self, pressure: float, fractions: dict[str, float], vapor_fraction: float = 0.0
    ) -> tuple[float, dict[str, float]]:
        """Equilibrium ratios y/x by component id at the bubble (*vapor_fraction* 0) or dew (1)
        point of *fractions* at *pressure* kPa(a): ``(temperature K, {id: K})``. A component
        absent from the incipient phase (its fraction in *fractions* is 0, as in a sharp split)
        gets its infinite-dilution ratio from the fugacity coefficients of the two phases,
        ``K = phi_liquid / phi_vapour`` (the same Peng-Robinson equation of state)."""
        self._vle_claimed("equilibrium ratios")
        claim = claimed_range(self.process)
        lo, hi = claim.vle_pressure or claim.pressure or (0.0, float("inf"))
        if not lo <= pressure <= hi:
            raise Unsupported(
                "property-out-of-range",
                f"{pressure:g} kPa(a) outside the claimed VLE range {lo:g} to {hi:g} kPa(a)",
            )
        state = self._raw(fractions, P=pressure * 1000.0, VF=vapor_fraction)
        temperature = float(state.T)
        self._checked(temperature, pressure, fractions)
        comps = self.process.components()
        cas, _ = self._zs(fractions)
        ys, xs = list(state.gas.zs), list(state.liquid0.zs)
        phis: tuple[list[float], list[float]] | None = None
        found = {}
        for name in fractions:
            i = cas.index(comps[name].cas)
            if xs[i] > 0 and ys[i] > 0:
                found[name] = ys[i] / xs[i]
                continue
            if phis is None:
                with warnings.catch_warnings():
                    warnings.simplefilter("ignore")
                    phis = (list(state.liquid0.phis()), list(state.gas.phis()))
            phi_l, phi_v = phis[0][i], phis[1][i]
            if not (phi_l > 0 and phi_v > 0 and math.isfinite(phi_l / phi_v)):
                point = "dew" if vapor_fraction >= 0.5 else "bubble"
                raise Unsupported(
                    "property-unsupported", f"no equilibrium ratio of {name} at the {point} point"
                )
            found[name] = phi_l / phi_v
        return temperature, found

    def liquid_viscosity(
        self, temperature: float, fractions: dict[str, float]
    ) -> tuple[float, str]:
        """Liquid viscosity, Pa s, and its basis: thermo's pure-component correlations
        (``ViscosityLiquid``, method as named) mixed logarithmically by mole fraction. This is
        not part of the validated method: callers mark the value ASSUMED."""
        self._vle_claimed("liquid viscosity")
        cas, zs = self._zs(fractions)
        # the temperature and components of the claim (a liquid's viscosity is taken at
        # saturation, so no pressure is checked)
        claim = claimed_range(self.process)
        self._checked(temperature, (claim.pressure or (100.0, 100.0))[0], fractions)
        with warnings.catch_warnings():
            warnings.simplefilter("ignore")
            from thermo import ChemicalConstantsPackage

            _, correlations = ChemicalConstantsPackage.from_IDs(list(cas))
            log_mu, methods = 0.0, set()
            for x, model in zip(zs, correlations.ViscosityLiquids, strict=True):
                if x <= 0:
                    continue
                mu = model.T_dependent_property(temperature)
                if mu is None or mu <= 0:
                    raise Unsupported(
                        "property-unsupported",
                        f"no liquid viscosity correlation at {temperature:g} K",
                    )
                log_mu += x * math.log(mu)
                methods.add(str(model.method))
        basis = (
            f"thermo {versions()['thermo']} ViscosityLiquid ({', '.join(sorted(methods))}), "
            "logarithmic mole-fraction mixing; outside cheme-as-code's validated property method"
        )
        return math.exp(log_mu), basis
