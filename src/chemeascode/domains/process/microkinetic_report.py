"""``cheme chemistry microkinetics``: a reaction's mechanism (``process/reactions.yaml``) at
given conditions, with the plant's components (molar masses, formulas).

The steady coverages, the turnover frequency (TOF) of a product, the degree of rate control of
every step, the apparent activation energy and the reaction orders
(:mod:`chemeascode.domains.chemistry.microkinetics`); with ``cantera`` the same steady state
solved by Cantera (extra ``cantera``) as a check, and the Cantera YAML of the mechanism.
"""

from __future__ import annotations

from collections.abc import Mapping
from pathlib import Path
from typing import Any

from chemeascode.domains.chemistry.microkinetics import NoSteadyState, analyse, cantera_yaml


class NotAvailable(ValueError):
    """The reaction has no mechanism, or a component no molar mass, or the process no file."""


def load_chemistry(root: Path) -> Any:
    """The materials and reactions of the plant at *root*, with or without a flowsheet (an
    object with ``reactions``, ``components()`` and ``formulas()``)."""
    from types import SimpleNamespace

    import yaml
    from pydantic import ValidationError

    from chemeascode.domains.process import MATERIALS_FILE
    from chemeascode.domains.process.model import _load_reactions, load
    from chemeascode.domains.process.schema import Materials

    process, _ = load(root)
    if process is not None:
        return process
    comps: dict[str, Any] = {}
    path = root / MATERIALS_FILE
    if path.is_file():
        try:
            materials = Materials.model_validate(yaml.safe_load(path.read_text()) or {})
            comps = {c.id: c for c in materials.components}
        except (ValidationError, yaml.YAMLError):
            comps = {}
    reactions, _, _ = _load_reactions(root)
    from chemeascode.domains.chemistry.catalysts import CATALYSTS_FILE, Catalysts
    from chemeascode.domains.chemistry.catalysts import SCHEMA as CATALYSTS_SCHEMA
    from chemeascode.domains.process.model import _load_optional

    catalysts, _, _ = _load_optional(
        root, CATALYSTS_FILE, Catalysts, CATALYSTS_SCHEMA, "cheme.catalyst-schema", "catalysts"
    )
    return SimpleNamespace(
        root=root,
        reactions=reactions,
        catalysts=catalysts,
        components=lambda: comps,
        formulas=lambda: {c.id: c.formula for c in comps.values()},
    )


def microkinetic_report(
    root: Path,
    reaction: str,
    temperature: float,
    pressures: Mapping[str, float],
    product: str | None = None,
    cantera: bool = False,
    chemistry: Any = None,
) -> dict[str, Any]:
    """The analysis of *reaction*'s mechanism at *temperature* K and partial *pressures* (bar)
    for the TOF of *product* (default: the reaction's first product). Raises
    :class:`NotAvailable` naming what is missing."""
    process = chemistry or load_chemistry(Path(root))
    if process.reactions is None:
        raise NotAvailable("no valid process/reactions.yaml")
    found = process.reactions.by_id().get(reaction)
    if found is None:
        raise NotAvailable(f"reaction {reaction} is not declared")
    mech = found.mechanism
    if mech is None:
        raise NotAvailable(f"reaction {reaction} has no mechanism")
    product = product or next(n for n, v in found.stoichiometry.items() if v > 0)
    comps = process.components()
    gas = sorted({n for s in mech.steps for n in s.gas()})
    lacking = [n for n in gas if not getattr(comps.get(n), "molar_mass", None)]
    if lacking:
        raise NotAvailable("no molar_mass for " + ", ".join(lacking))
    masses = {n: comps[n].molar_mass for n in gas}
    pressures = {**dict.fromkeys(gas, 0.0), **pressures}
    try:
        state = analyse(
            mech,
            temperature,
            pressures,
            masses,
            product,
            [n for n, v in found.stoichiometry.items() if v < 0 and pressures.get(n, 0) > 0],
        )
    except NoSteadyState as failure:
        raise NotAvailable(str(failure)) from failure
    result: dict[str, Any] = {
        "reaction": reaction,
        "temperature_K": temperature,
        "pressures_bar": dict(pressures),
        "product": product,
        "tof_per_s": state.tof(product),
        "coverages": state.coverages,
        "step_rates_per_s": state.rates,
        "rate_control": state.rate_control,
        "apparent_activation_kJ_kmol": state.apparent_activation,
        "orders": state.orders,
        "mechanism_source": mech.source,
        "mechanism_provenance": mech.provenance,
    }
    if cantera:
        from chemeascode.integrations.cantera import run

        text = cantera_yaml(mech, process.formulas(), name=reaction)
        checked = run(text, temperature, pressures)
        result["cantera"] = {
            "version": checked["version"],
            "tof_per_s": checked["production"].get(product),
            "coverages": checked["coverages"],
        }
    return result


def report_text(result: Mapping[str, Any]) -> str:
    lines = [
        f"{result['reaction']} at {result['temperature_K']:g} K: TOF of {result['product']} "
        f"{result['tof_per_s']:.4g} 1/s per site",
        "coverages: "
        + ", ".join(
            f"{k} {v:.3g}" for k, v in sorted(result["coverages"].items(), key=lambda kv: -kv[1])
        ),
        "degree of rate control: "
        + ", ".join(f"{k} {v:.3f}" for k, v in result["rate_control"].items()),
        f"apparent activation energy {result['apparent_activation_kJ_kmol'] / 1000:.4g} kJ/mol",
    ]
    if result["orders"]:
        lines.append("orders: " + ", ".join(f"{k} {v:.3f}" for k, v in result["orders"].items()))
    if "cantera" in result:
        ct = result["cantera"]
        lines.append(f"Cantera {ct['version']}: TOF {ct['tof_per_s']:.4g} 1/s per site")
    return "\n".join(lines)
