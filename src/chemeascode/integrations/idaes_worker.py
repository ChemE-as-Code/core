"""The IDAES worker: reads ``{"model": ..., "details": bool}`` (JSON) on stdin, builds the
flowsheet as an IDAES/Pyomo model, initializes it unit by unit (a sequential decomposition with
the tear streams the model names), solves it as one equation system with IPOPT and prints the
result (JSON, one line) in the shape of the DWSIM worker's (:mod:`.dwsim_worker`).

Self-contained (standard library, idaes-pse and Pyomo only): it runs in the Python that
``CHEME_IDAES_PYTHON`` names, never inside cheme-as-code, which does not import IDAES or Pyomo.
IPOPT is the one ``idaes get-extensions`` installs.

The property packages are IDAES's generic (modular) framework, configured from the component
data IDAES ships with its example packages (:data:`COMPONENTS`): the worker copies nothing, it
reads the entries of ``BT_ideal``, ``BT_PR`` and ``HC_PR`` at run time. None of them is
benchmarked by cheme-as-code (``methods.yml`` holds no claim for the IDAES route).

API names as in IDAES 2.13 and Pyomo 6.10.
"""

from __future__ import annotations

import contextlib
import copy
import io
import json
import math
import os
import re
import sys
import tempfile
from typing import Any

#: Property package name (simulation.yaml) -> how the worker builds it: the phases' equation of
#: state, and per CAS number the IDAES example package and its component entry.
PACKAGES = {
    "IDAES ideal VLE": {
        "eos": "ideal",
        "components": {
            "71-43-2": ("BT_ideal", "benzene"),
            "108-88-3": ("BT_ideal", "toluene"),
            "1333-74-0": ("HC_PR", "hydrogen"),
            "74-82-8": ("HC_PR", "methane"),
        },
    },
    "IDAES Peng-Robinson": {
        "eos": "PR",
        "components": {
            "71-43-2": ("BT_PR", "benzene"),
            "108-88-3": ("BT_PR", "toluene"),
            "1333-74-0": ("HC_PR", "hydrogen"),
            "74-82-8": ("HC_PR", "methane"),
        },
    },
}
#: Units the worker builds, by package equation of state: an isentropic machine needs entropies,
#: which the ideal package's aromatics do not have in IDAES's data.
UNITS = {
    "ideal": (
        "heater",
        "cooler",
        "valve",
        "pump",
        "mixer",
        "splitter",
        "flash",
        "conversion_reactor",
    ),
    "PR": (
        "heater",
        "cooler",
        "valve",
        "pump",
        "compressor",
        "expander",
        "mixer",
        "splitter",
        "flash",
        "conversion_reactor",
    ),
}
#: Reaction phase (cheme-as-code) -> IDAES phase.
REACTION_PHASES = {"vapor": "Vap", "liquid": "Liq"}
#: The state bounds of every package (the example packages' own are narrower than a plant).
BOUNDS = {
    "flow_mol": (0, 100, 1e6),
    "temperature": (150.0, 300.0, 1500.0),
    "pressure": (5e3, 1e5, 1e8),
}
#: Mole fractions in a feed below this are raised to it (and the feed renormalised): the
#: package's logarithms take no zero.
TRACE = 1e-8
#: Sequential-decomposition passes for the tear streams before the simultaneous solve: an
#: initialization only (each pass initializes every unit, seconds each); IPOPT closes the loop.
TEAR_PASSES = 2


def _example(name: str) -> dict[str, Any]:
    import importlib

    module = importlib.import_module(f"idaes.models.properties.modular_properties.examples.{name}")
    return module.configuration


#: How far below its critical temperature a component's subcritical correlations are held.
CRITICAL_MARGIN = 1e-3


def _subcritical(library: Any, prop: str) -> Any:
    """IDAES's *library* (``Perrys``, ``RPP4``) with its method *prop* evaluated at
    ``min(T, (1 - CRITICAL_MARGIN) Tc)`` (a smooth minimum): Perry's liquid density and the
    RPP4 (Wagner) vapour pressure take ``(1 - T/Tc)`` to a fractional power and have no real
    value above the critical temperature. A fixed temperature there (a heater outlet at 600 K
    for benzene) would make a constant of the model complex. Above Tc there is no liquid of the
    component; the held values enter only where the liquid's amount weights them, and the
    phase equilibrium evaluates the vapour pressure at the equilibrium temperature, below the
    mixture's dew point."""
    from idaes.core.util.math import smooth_min
    from pyomo.environ import units as pyunits

    original = getattr(library, prop)

    class Method:
        build_parameters = staticmethod(original.build_parameters)

        @staticmethod
        def return_expression(b: Any, cobj: Any, T: Any, *args: Any, **kwargs: Any) -> Any:
            T = pyunits.convert(T, to_units=pyunits.K)
            tc = cobj.temperature_crit
            held = tc * smooth_min(T / tc, 1 - CRITICAL_MARGIN, 1e-5)
            return original.return_expression(b, cobj, held, *args, **kwargs)

    class Library:
        pass

    setattr(Library, prop, Method)
    for name in dir(library):  # the library's other methods unchanged
        if not name.startswith("_") and name != prop:
            setattr(Library, name, getattr(library, name))
    return Library


def _ids(model: dict[str, Any]) -> dict[str, str]:
    """Compound id -> its component name in the package (the IDAES example's key)."""
    package = PACKAGES[model["property_package"]]
    names = {}
    for c in model["compounds"]:
        entry = package["components"].get(c["cas"])
        if entry is None:
            raise LookupError(
                f"compound {c['id']} (CAS {c['cas']}) is not in {model['property_package']}; "
                "it has " + ", ".join(k for _, k in package["components"].values())
            )
        names[c["id"]] = entry[1]
    return names


def configuration(model: dict[str, Any]) -> dict[str, Any]:
    """The generic property package of *model*: its compounds, from IDAES's example data."""
    from idaes.core import LiquidPhase, VaporPhase
    from idaes.models.properties.modular_properties.eos.ceos import Cubic, CubicType
    from idaes.models.properties.modular_properties.eos.ideal import Ideal
    from idaes.models.properties.modular_properties.phase_equil import SmoothVLE
    from idaes.models.properties.modular_properties.phase_equil.bubble_dew import (
        IdealBubbleDew,
        LogBubbleDew,
    )
    from idaes.models.properties.modular_properties.state_definitions import FTPx
    from pyomo.environ import units as pyunits

    package = PACKAGES[model["property_package"]]
    names = _ids(model)
    components = {}
    for c in model["compounds"]:
        source, key = package["components"][c["cas"]]
        components[key] = copy.deepcopy(_example(source)["components"][key])
        for prop in ("dens_mol_liq_comp", "pressure_sat_comp"):
            if prop in components[key]:
                components[key][prop] = _subcritical(components[key][prop], prop)
    # IDAES takes an elemental composition from all components or from none; its example
    # packages differ (HC_PR declares it, BT_PR does not), and the worker uses none
    if not all("elemental_composition" in entry for entry in components.values()):
        for entry in components.values():
            entry.pop("elemental_composition", None)
    if package["eos"] == "ideal":
        phases = {
            "Liq": {"type": LiquidPhase, "equation_of_state": Ideal},
            "Vap": {"type": VaporPhase, "equation_of_state": Ideal},
        }
        bubble_dew = IdealBubbleDew
        extra: dict[str, Any] = {}
    else:
        options = {"type": CubicType.PR}
        phases = {
            "Liq": {
                "type": LiquidPhase,
                "equation_of_state": Cubic,
                "equation_of_state_options": options,
            },
            "Vap": {
                "type": VaporPhase,
                "equation_of_state": Cubic,
                "equation_of_state_options": options,
            },
        }
        bubble_dew = LogBubbleDew
        # every pair 0: IDAES's example data hold no other value for these components
        keys = list(names.values())
        extra = {"parameter_data": {"PR_kappa": {(a, b): 0.0 for a in keys for b in keys}}}
    lo_f, mid_f, hi_f = BOUNDS["flow_mol"]
    lo_t, mid_t, hi_t = BOUNDS["temperature"]
    lo_p, mid_p, hi_p = BOUNDS["pressure"]
    return {
        "components": components,
        "phases": phases,
        "base_units": {
            "time": pyunits.s,
            "length": pyunits.m,
            "mass": pyunits.kg,
            "amount": pyunits.mol,
            "temperature": pyunits.K,
        },
        "state_definition": FTPx,
        "state_bounds": {
            "flow_mol": (lo_f, mid_f, hi_f, pyunits.mol / pyunits.s),
            "temperature": (lo_t, mid_t, hi_t, pyunits.K),
            "pressure": (lo_p, mid_p, hi_p, pyunits.Pa),
        },
        "pressure_ref": (101325.0, pyunits.Pa),
        "temperature_ref": (298.15, pyunits.K),
        "phases_in_equilibrium": [("Vap", "Liq")],
        "phase_equilibrium_state": {("Vap", "Liq"): SmoothVLE},
        "bubble_dew_method": bubble_dew,
        **extra,
    }


def _reactions(fs: Any, k: int, u: dict[str, Any], names: dict[str, str], properties: Any) -> Any:
    """The reaction package of reactor *u*: its reactions' stoichiometry, no rate (a
    stoichiometric reactor takes the extents from the conversions)."""
    from idaes.models.properties.modular_properties.base.generic_reaction import (
        GenericReactionParameterBlock,
    )
    from pyomo.environ import units as pyunits

    rate_reactions = {}
    for r in u["spec"]["reactions"]:
        phase = REACTION_PHASES[r["phase"]]
        rate_reactions[r["id"]] = {
            "stoichiometry": {
                (phase, names[cid]): float(nu) for cid, nu in r["stoichiometry"].items()
            },
        }
    block = GenericReactionParameterBlock(
        property_package=properties,
        rate_reactions=rate_reactions,
        base_units={
            "time": pyunits.s,
            "length": pyunits.m,
            "mass": pyunits.kg,
            "amount": pyunits.mol,
            "temperature": pyunits.K,
        },
    )
    fs.add_component(f"reactions{k}", block)
    return block


class _Unit:
    """One unit of the model in the Pyomo flowsheet: its block and its ports, by stream."""

    def __init__(
        self,
        block: Any,
        inlets: list[Any],
        outlets: list[Any],
        phases: tuple[Any, list[str]] | None = None,
    ) -> None:
        self.block = block
        self.inlets = inlets
        self.outlets = outlets
        #: (state, phase per outlet) where each outlet is one phase of *state* (a flash)
        self.phases = phases


def _build_unit(fs: Any, k: int, u: dict[str, Any], properties: Any, names: dict[str, str]):
    """The IDAES unit model of *u* with its specifications fixed."""
    from idaes.models.unit_models import (
        Flash,
        Heater,
        Mixer,
        MomentumMixingType,
        PressureChanger,
        Separator,
        SplittingType,
        StoichiometricReactor,
    )
    from idaes.models.unit_models.pressure_changer import ThermodynamicAssumption
    from pyomo.environ import Constraint

    kind, spec = u["type"], u["spec"]
    name = f"u{k}"
    if kind in ("heater", "cooler"):
        b = Heater(property_package=properties, has_pressure_change=True)
        fs.add_component(name, b)
        if spec.get("outlet_temperature_K") is not None:
            b.outlet.temperature.fix(spec["outlet_temperature_K"])
        else:
            b.heat_duty.fix(1000.0 * spec["duty_kW"])
        b.deltaP.fix(-spec.get("pressure_drop_Pa", 0.0))
        return _Unit(b, [b.inlet], [b.outlet])
    if kind in ("valve", "pump", "compressor", "expander"):
        assumption = {
            "valve": ThermodynamicAssumption.adiabatic,
            "pump": ThermodynamicAssumption.pump,
            "compressor": ThermodynamicAssumption.isentropic,
            "expander": ThermodynamicAssumption.isentropic,
        }[kind]
        b = PressureChanger(
            property_package=properties,
            thermodynamic_assumption=assumption,
            compressor=kind in ("pump", "compressor"),
        )
        fs.add_component(name, b)
        if spec.get("outlet_pressure_Pa") is not None:
            b.outlet.pressure.fix(spec["outlet_pressure_Pa"])
        elif spec.get("pressure_increase_Pa") is not None:
            b.deltaP.fix(spec["pressure_increase_Pa"])
        else:
            b.deltaP.fix(-spec["pressure_drop_Pa"])
        if kind == "pump":
            b.efficiency_pump.fix(spec["efficiency"])
        elif kind != "valve":
            b.efficiency_isentropic.fix(spec["efficiency"])
        return _Unit(b, [b.inlet], [b.outlet])
    if kind == "mixer":
        ports = [f"in{i}" for i in range(len(u["inlets"]))]
        b = Mixer(
            property_package=properties,
            inlet_list=ports,
            momentum_mixing_type=MomentumMixingType.minimize,
        )
        fs.add_component(name, b)
        return _Unit(b, [getattr(b, p) for p in ports], [b.outlet])
    if kind == "splitter":
        ports = [f"out{i}" for i in range(len(u["outlets"]))]
        b = Separator(
            property_package=properties, outlet_list=ports, split_basis=SplittingType.totalFlow
        )
        fs.add_component(name, b)
        fractions = [float(f) for f in spec["fractions"]]
        for p, f in zip(ports[:-1], fractions[:-1], strict=False):
            b.split_fraction[0, p].fix(f)
        return _Unit(b, [b.inlet], [getattr(b, p) for p in ports])
    if kind == "flash":
        # IDAES's ideal separation (its default): each outlet is one phase of the drum's
        # outlet state, read from there (:func:`_phase_stream`)
        b = Flash(property_package=properties, has_heat_transfer=True, has_pressure_change=True)
        fs.add_component(name, b)
        if spec.get("temperature_K") is not None:
            b.control_volume.properties_out[0].temperature.fix(spec["temperature_K"])
        else:
            b.heat_duty.fix(0.0)
        if spec.get("pressure_Pa") is not None:
            b.control_volume.properties_out[0].pressure.fix(spec["pressure_Pa"])
        else:
            b.deltaP.fix(0.0)
        state = b.control_volume.properties_out[0]
        return _Unit(b, [b.inlet], [b.vap_outlet, b.liq_outlet], (state, ["Vap", "Liq"]))
    if kind == "conversion_reactor":
        reactions = _reactions(fs, k, u, names, properties)
        b = StoichiometricReactor(
            property_package=properties,
            reaction_package=reactions,
            has_heat_of_reaction=False,  # the enthalpies include the formation enthalpies
            has_heat_transfer=True,
            has_pressure_change=True,
        )
        fs.add_component(name, b)
        cv = b.control_volume
        mode = spec["mode"]
        if mode == "adiabatic":
            b.heat_duty.fix(0.0)
        elif mode == "outlet_temperature":
            b.outlet.temperature.fix(spec["outlet_temperature_K"])
        else:
            b.isothermal = Constraint(
                expr=cv.properties_out[0].temperature == cv.properties_in[0].temperature
            )
        b.deltaP.fix(-spec.get("pressure_drop_Pa", 0.0))
        # every reaction converts its base's inlet flow (in parallel, as DWSIM's one rank)
        conversions = {r["id"]: r for r in spec["reactions"]}

        def rule(blk: Any, rid: str) -> Any:
            r = conversions[rid]
            base = names[r["base"]]
            nu = abs(float(r["stoichiometry"][r["base"]]))
            inlet = cv.properties_in[0]
            fed = inlet.flow_mol * inlet.mole_frac_comp[base]
            return nu * b.rate_reaction_extent[0, rid] == float(r["conversion"]) * fed

        b.conversion = Constraint(list(conversions), rule=rule)
        return _Unit(b, [b.inlet], [b.outlet])
    raise LookupError(f"{u['id']}: the IDAES backend has no {kind}")


def _state(port: Any) -> Any:
    """The state block data behind *port* (its temperature's owner)."""
    return port.vars["temperature"][0].parent_block()


def _num(x: Any) -> float | None:
    from pyomo.environ import value

    try:
        v = float(value(x))
    except Exception:  # noqa: BLE001 - an expression that cannot be evaluated
        return None
    return v if math.isfinite(v) else None


def _stream(sb: Any, names: dict[str, str], details: bool) -> dict[str, Any]:
    mw = _num(sb.mw)  # kg/mol
    flow = _num(sb.flow_mol)
    h = _num(sb.enth_mol)  # J/mol, formation enthalpies included
    by_key = {v: k for k, v in names.items()}
    result = {
        "temperature_K": _num(sb.temperature),
        "pressure_Pa": _num(sb.pressure),
        "mass_flow_kg_s": flow * mw if flow is not None and mw else None,
        "molar_flow_mol_s": flow,
        "mole_fractions": {by_key[j]: _num(sb.mole_frac_comp[j]) or 0.0 for j in by_key},
        "vapor_fraction": _num(sb.phase_frac["Vap"]),
        "mass_enthalpy_kJ_kg": h / mw / 1000.0 if h is not None and mw else None,
    }
    if details:
        result["molar_mass_kg_kmol"] = mw * 1000.0 if mw else None
        result["molar_enthalpy_kJ_kmol"] = h
        phases = {}
        for p, label in (("Vap", "vapor"), ("Liq", "liquid")):
            fraction = _num(sb.phase_frac[p])
            if fraction is None or fraction <= 1e-9:
                continue
            phases[label] = {
                "fraction": fraction,
                "molar_enthalpy_kJ_kmol": _num(sb.enth_mol_phase[p]),
                "mole_fractions": {
                    by_key[j]: _num(sb.mole_frac_phase_comp[p, j]) or 0.0
                    for j in by_key
                    if (p, j) in sb.mole_frac_phase_comp
                },
            }
        result["phases"] = phases
    return result


def _phase_stream(
    sb: Any, phase: str, names: dict[str, str], mws: dict[str, float], details: bool
) -> dict[str, Any]:
    """The stream that is phase *phase* of state *sb* alone (a flash outlet), in the shape of
    :func:`_stream`."""
    by_key = {v: k for k, v in names.items()}
    x = {
        by_key[j]: (_num(sb.mole_frac_phase_comp[phase, j]) or 0.0)
        if (phase, j) in sb.mole_frac_phase_comp
        else 0.0
        for j in by_key
    }
    mw = sum(x[c] * mws[c] for c in x)  # kg/mol
    flow = _num(sb.flow_mol_phase[phase])
    h = _num(sb.enth_mol_phase[phase])
    result = {
        "temperature_K": _num(sb.temperature),
        "pressure_Pa": _num(sb.pressure),
        "mass_flow_kg_s": flow * mw if flow is not None and mw else None,
        "molar_flow_mol_s": flow,
        "mole_fractions": x,
        "vapor_fraction": 1.0 if phase == "Vap" else 0.0,
        "mass_enthalpy_kJ_kg": h / mw / 1000.0 if h is not None and mw else None,
    }
    if details:
        result["molar_mass_kg_kmol"] = mw * 1000.0 if mw else None
        result["molar_enthalpy_kJ_kmol"] = h
        label = "vapor" if phase == "Vap" else "liquid"
        result["phases"] = {
            label: {"fraction": 1.0, "molar_enthalpy_kJ_kmol": h, "mole_fractions": dict(x)}
        }
    return result


def _iterations(log: str) -> int | None:
    found = re.findall(r"Number of Iterations\.*:\s*(\d+)", log)
    return int(found[-1]) if found else None


#: A tear stream without a first guess starts at this fraction of the feeds' molar flow, with
#: their mixed composition: a stream of the first feed alone may lack a reactant the reactor
#: downstream converts (no hydrogen for a hydrogenation), which leaves the first pass infeasible.
TEAR_GUESS_FRACTION = 0.1


def _feed_mix(
    model: dict[str, Any], names: dict[str, str], mws: dict[str, float]
) -> dict[str, Any]:
    """The feeds mixed: molar flow (mol/s) and mole fractions by compound id, the first feed's
    temperature and pressure."""
    flows = dict.fromkeys(names, 0.0)
    first: dict[str, Any] = {}
    for s in model["streams"]:
        feed = s.get("feed")
        if not feed or s.get("kind") != "material":
            continue
        first = first or feed
        x = {c: float(feed["mole_fractions"].get(c, 0.0)) for c in names}
        mw = sum(x[c] * mws[c] for c in names) / (sum(x.values()) or 1.0)
        total = float(feed["mass_flow_kg_s"]) / mw if mw else 0.0
        for c in names:
            flows[c] += total * x[c] / (sum(x.values()) or 1.0)
    total = sum(flows.values())
    return {
        "flow_mol": total,
        "mole_fractions": {c: f / total for c, f in flows.items()} if total else {},
        "temperature_K": first.get("temperature_K", 298.15),
        "pressure_Pa": first.get("pressure_Pa", 101325.0),
    }


def _tear_guess(
    guess: dict[str, Any] | None,
    mixed: dict[str, Any],
    names: dict[str, str],
    mws: dict[str, float],
) -> dict[str, Any]:
    """The Pyomo guesses of a tear stream's port: the model's first guess where it has one,
    else the mixed feeds (:func:`_feed_mix`) at :data:`TEAR_GUESS_FRACTION` of their flow."""
    guess = guess or {}
    fractions = guess.get("mole_fractions") or mixed["mole_fractions"]
    x = {c: max(float(fractions.get(c, 0.0)), TRACE) for c in names}
    total = sum(x.values())
    x = {c: v / total for c, v in x.items()}
    if guess.get("mass_flow_kg_s"):
        flow = float(guess["mass_flow_kg_s"]) / sum(x[c] * mws[c] for c in names)
    else:
        flow = max(TEAR_GUESS_FRACTION * mixed["flow_mol"], 1e-6)
    return {
        "flow_mol": {0: flow},
        "mole_frac_comp": {(0, names[c]): x[c] for c in names},
        "temperature": {0: float(guess.get("temperature_K", mixed["temperature_K"]))},
        "pressure": {0: float(guess.get("pressure_Pa", mixed["pressure_Pa"]))},
    }


def solve(request: dict[str, Any]) -> dict[str, Any]:
    import idaes
    import pyomo.environ as pyo
    from idaes.core import FlowsheetBlock
    from idaes.core.solvers import get_solver
    from idaes.core.util.model_statistics import degrees_of_freedom
    from idaes.models.properties.modular_properties.base.generic_property import (
        GenericParameterBlock,
    )
    from idaes.models.unit_models import Feed, Product
    from pyomo.network import Arc, SequentialDecomposition

    model = request["model"]
    if model.get("property_package") not in PACKAGES:
        raise LookupError(
            f"property package {model.get('property_package')!r} is not supported; one of "
            + ", ".join(PACKAGES)
        )
    eos = PACKAGES[model["property_package"]]["eos"]
    names = _ids(model)
    m = pyo.ConcreteModel()
    m.fs = FlowsheetBlock(dynamic=False)
    m.fs.properties = GenericParameterBlock(**configuration(model))
    properties = m.fs.properties
    messages: list[str] = []
    notes: list[str] = []

    # material ports by stream: where it leaves (a unit's outlet or a feed) and where it enters
    sources: dict[str, Any] = {}
    sinks: dict[str, Any] = {}
    units: dict[str, _Unit] = {}
    for k, u in enumerate(model["units"]):
        if u["type"] not in UNITS[eos]:
            raise LookupError(
                f"{u['id']}: the IDAES backend has no {u['type']} with {model['property_package']}"
            )
        unit = _build_unit(m.fs, k, u, properties, names)
        units[u["id"]] = unit
        for sid, port in zip(u["inlets"], unit.inlets, strict=True):
            sinks[sid] = port
        for sid, port in zip(u["outlets"], unit.outlets, strict=True):
            sources[sid] = port
    mws = {c: _num(properties.get_component(names[c]).mw) for c in names}
    feeds: dict[str, Any] = {}
    for s in model["streams"]:
        if s["kind"] != "material":
            continue
        feed = s.get("feed")
        if feed:
            if feed.get("vapor_fraction") is not None:
                raise LookupError(f"{s['id']}: the IDAES backend takes no saturation feed")
            b = Feed(property_package=properties)
            m.fs.add_component(f"feed_{len(feeds)}", b)
            feeds[s["id"]] = b
            x = {c: max(float(feed["mole_fractions"].get(c, 0.0)), TRACE) for c in names}
            total = sum(x.values())
            x = {c: v / total for c, v in x.items()}
            mw = sum(x[c] * mws[c] for c in names)
            b.outlet.flow_mol.fix(float(feed["mass_flow_kg_s"]) / mw)
            b.outlet.temperature.fix(float(feed["temperature_K"]))
            b.outlet.pressure.fix(float(feed["pressure_Pa"]))
            for c in names:
                b.outlet.mole_frac_comp[0, names[c]].fix(x[c])
            sources[s["id"]] = b.outlet
        elif s["id"] in sources and s["id"] not in sinks:
            b = Product(property_package=properties)
            m.fs.add_component(f"product_{s['id']}".replace("-", "_").replace(".", "_"), b)
            sinks[s["id"]] = b.inlet
    arcs: dict[str, Any] = {}
    for sid, port in sources.items():
        if sid not in sinks:
            continue
        arc = Arc(source=port, destination=sinks[sid])
        m.fs.add_component(f"arc_{len(arcs)}", arc)
        arcs[sid] = arc
    pyo.TransformationFactory("network.expand_arcs").apply_to(m)

    dof = degrees_of_freedom(m)
    if dof != 0:
        raise ValueError(f"the IDAES model has {dof} degrees of freedom, not 0")

    def init(unit: Any) -> None:
        with contextlib.redirect_stdout(sys.stderr):
            unit.initialize()

    tears = [r for r in model.get("recycles", []) if r["stream"] in arcs]
    seq = SequentialDecomposition()
    seq.options.select_tear_method = "heuristic"
    seq.options.tear_method = "Direct"
    seq.options.iterLim = TEAR_PASSES
    if tears:
        seq.set_tear_set([arcs[r["stream"]] for r in tears])
        mixed = _feed_mix(model, names, mws)
        for r in tears:
            seq.set_guesses_for(sinks[r["stream"]], _tear_guess(r.get("guess"), mixed, names, mws))
    try:
        with contextlib.redirect_stdout(sys.stderr):
            seq.run(m, init)
    except Exception as failure:  # noqa: BLE001 - the simultaneous solve may still converge
        notes.append(f"initialization did not finish ({type(failure).__name__}: {failure})")

    solver = get_solver()
    with tempfile.TemporaryDirectory() as tmp:
        logfile = os.path.join(tmp, "ipopt.log")
        with contextlib.redirect_stdout(sys.stderr):
            results = solver.solve(m, tee=False, logfile=logfile, load_solutions=False)
        try:
            with open(logfile, encoding="utf-8", errors="replace") as handle:
                log = handle.read()
        except OSError:
            log = ""
    status = results.solver.termination_condition
    converged = status == pyo.TerminationCondition.optimal
    if converged or status in (
        pyo.TerminationCondition.maxIterations,
        pyo.TerminationCondition.locallyOptimal,
    ):
        m.solutions.load_from(results)
    if not converged:
        messages.append(f"IPOPT did not converge: {status}")

    #: stream id -> (state, phase) of the flash outlets
    phase_of: dict[str, tuple[Any, str]] = {}
    for u in model["units"]:
        unit = units[u["id"]]
        if unit.phases is not None:
            state, phases = unit.phases
            for sid, phase in zip(u["outlets"], phases, strict=True):
                phase_of[sid] = (state, phase)
    details = bool(request.get("details"))
    streams: dict[str, Any] = {}
    for s in model["streams"]:
        if s["kind"] != "material" or s.get("internal"):
            continue
        port = sources.get(s["id"])
        if port is None:
            continue
        if s["id"] in phase_of:
            state, phase = phase_of[s["id"]]
            streams[s["id"]] = _phase_stream(state, phase, names, mws, details)
        else:
            streams[s["id"]] = _stream(_state(port), names, details)
    results_by_unit: dict[str, Any] = {}
    for u in model["units"]:
        b, kind = units[u["id"]].block, u["type"]
        if kind in ("heater", "cooler", "flash"):
            results_by_unit[u["id"]] = {"duty_kW": _kw(b.heat_duty[0])}
        elif kind in ("pump", "compressor"):
            results_by_unit[u["id"]] = {"duty_kW": _kw(b.work_mechanical[0])}
        elif kind == "expander":
            w = _kw(b.work_mechanical[0])
            results_by_unit[u["id"]] = {"duty_kW": -w if w is not None else None}
        elif kind == "conversion_reactor":
            extents = {
                r["id"]: (_num(b.rate_reaction_extent[0, r["id"]]) or 0.0) * 3.6
                for r in u["spec"]["reactions"]
            }
            results_by_unit[u["id"]] = {"duty_kW": _kw(b.heat_duty[0]), "extents_kmol_h": extents}
            outlet = streams.get(u["outlets"][0]) or {}
            vapour = outlet.get("vapor_fraction")
            if vapour is not None and vapour < 1.0 - 1e-6 and outlet.get("mass_flow_kg_s"):
                liquid = (1.0 - vapour) * (outlet.get("molar_flow_mol_s") or 0.0) * 3.6
                messages.append(
                    f"{u['id']}: {liquid:.6g} kmol/h of liquid formed in the reactor, which has "
                    "one outlet; give the step a liquid outlet (port liquid) or change its "
                    "conditions"
                )
    energies: dict[str, Any] = {}
    for u in model["units"]:
        for _, sid in (u.get("energies") or {}).items():
            if sid is None:
                continue
            duty = (results_by_unit.get(u["id"]) or {}).get("duty_kW")
            energies[sid] = {"duty_kW": abs(duty) if duty is not None else None}
    return {
        "ok": True,
        "version": idaes.__version__,
        "solver": f"ipopt {'.'.join(str(v) for v in solver.version() or ())}".strip(),
        "converged": converged and not messages,
        "iterations": _iterations(log),
        "messages": messages,
        "notes": notes,
        "streams": streams,
        "energies": energies,
        "units": results_by_unit,
        "compounds": {},
        "save_error": None,
    }


def _kw(x: Any) -> float | None:
    v = _num(x)
    return v / 1000.0 if v is not None else None


def main() -> None:
    try:
        request = json.loads(sys.stdin.read())
        # IDAES and Pyomo log to stdout in places: the result is the last line only
        with contextlib.redirect_stdout(io.StringIO()) as chatter:
            result = solve(request)
        sys.stderr.write(chatter.getvalue())
    except Exception as failure:  # noqa: BLE001 - every failure goes back as JSON
        result = {"ok": False, "error": f"{type(failure).__name__}: {failure}"}
    sys.stdout.write(json.dumps(result) + "\n")


if __name__ == "__main__":
    main()
