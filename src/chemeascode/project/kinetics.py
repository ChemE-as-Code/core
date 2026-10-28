"""Kinetic data of a plant repository: fit a rate law to a data file, or sample a mechanism into
one (:mod:`chemeascode.domains.experiments.kinetic_fit`, with the reactions and components of
``process/``)."""

from __future__ import annotations

import json
import math
from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import Any

import yaml
from pydantic import ValidationError

from chemeascode.domains.experiments.kinetic_fit import (
    Fit,
    KineticData,
    fit_lhhw,
    fit_power_law,
    sample_mechanism,
)


class KineticsProblem(ValueError):
    """A data file that does not load, or a reaction or component that is missing."""


def load_data(path: Path) -> KineticData:
    try:
        return KineticData.model_validate(yaml.safe_load(path.read_text(encoding="utf-8")) or {})
    except (OSError, yaml.YAMLError, ValidationError) as failure:
        raise KineticsProblem(f"{path}: {failure}") from failure


def fit_file(
    root: Path,
    path: Path,
    form: str = "power_law",
    orders_of: Sequence[str] = (),
    orders: Mapping[str, float] | None = None,
    adsorbed: Sequence[str] = (),
    power: float = 1.0,
    reverse: bool = False,
) -> Fit:
    """A rate law fitted to the data file *path* of the plant at *root*: a power law with an
    order for each of *orders_of* (default: the reaction's reactants), or an LHHW law with the
    numerator *orders* and the adsorbed components; *reverse* adds (1 - Q/K) with K of the
    reaction (its equilibrium constant or the components' ideal-gas data). A file of integral
    data (conversions) fits a power law on concentrations through its reactors: the reactants'
    orders fixed at their coefficients (or *orders*), those of *orders_of* fitted."""
    from chemeascode.domains.chemistry.equilibrium import reaction_ln_k
    from chemeascode.domains.process.microkinetic_report import load_chemistry

    data = load_data(path)
    chemistry = load_chemistry(Path(root))
    reaction = chemistry.reactions.by_id().get(data.reaction) if chemistry.reactions else None
    if reaction is None:
        raise KineticsProblem(f"reaction {data.reaction} is not in process/reactions.yaml")
    if data.integral:
        from chemeascode.domains.experiments.kinetic_fit import fit_integral

        if reverse or form != "power_law":
            raise KineticsProblem("integral data fit a forward power law only (no --reverse, lhhw)")
        fixed = {n: -v for n, v in reaction.stoichiometry.items() if v < 0} | dict(orders or {})
        try:
            return fit_integral(data, reaction.stoichiometry, fixed, list(orders_of))
        except ValueError as failure:
            raise KineticsProblem(str(failure)) from failure
    reactants = [n for n, v in reaction.stoichiometry.items() if v < 0]
    ln_k = None
    if reverse and not reaction.reversible:
        raise KineticsProblem(f"reaction {reaction.id} is not reversible: no (1 - Q/K)")
    if reverse:
        ideal = {c.id: c.ideal_gas for c in chemistry.components().values()}

        def ln_k(t: float) -> float:
            return reaction_ln_k(reaction, ideal, t)

        ln_k(data.points[0].temperature)  # a ValueError names what is missing
    if form == "power_law":
        return fit_power_law(data, list(orders_of) or reactants, reaction.stoichiometry, ln_k)
    if form == "lhhw":
        return fit_lhhw(
            data,
            dict(orders) if orders else dict.fromkeys(reactants, 1.0),
            list(adsorbed) or reactants,
            power,
            reaction.stoichiometry,
            ln_k,
        )
    raise KineticsProblem(f"form {form!r}: power_law or lhhw")


def sample_file(
    root: Path,
    reaction: str,
    temperatures: Sequence[float],
    pressures: Mapping[str, Sequence[float]],
    sites_per_kg: float,
    product: str | None = None,
) -> KineticData:
    """A data set of *reaction*'s mechanism over a grid of conditions (see
    :func:`~chemeascode.domains.experiments.kinetic_fit.sample_mechanism`)."""
    from chemeascode.domains.process.microkinetic_report import load_chemistry

    chemistry = load_chemistry(Path(root))
    found = chemistry.reactions.by_id().get(reaction) if chemistry.reactions else None
    if found is None or found.mechanism is None:
        raise KineticsProblem(f"reaction {reaction} has no mechanism")
    product = product or next(n for n, v in found.stoichiometry.items() if v > 0)
    comps = chemistry.components()
    gas = sorted({n for s in found.mechanism.steps for n in s.gas()})
    lacking = [n for n in gas if not getattr(comps.get(n), "molar_mass", None)]
    if lacking:
        raise KineticsProblem("no molar_mass for " + ", ".join(lacking))
    return sample_mechanism(
        found.mechanism,
        {n: comps[n].molar_mass for n in gas},
        product,
        found.stoichiometry[product],
        temperatures,
        pressures,
        sites_per_kg,
        reaction,
    )


def data_yaml(data: KineticData) -> str:
    """The text of a kinetic data file."""
    document = data.model_dump(mode="json", by_alias=True, exclude_defaults=False)
    head = "# Kinetic data (schema cheme/kinetic-data/v1): rates of one reaction.\n"
    return head + yaml.safe_dump(document, sort_keys=False, width=100)


def fit_text(fit: Fit) -> str:
    """The fitted law as a ``rate:`` entry to paste, with its parameters' 95 % intervals."""
    lines = [f"# {fit.points} points, R^2 of ln r {fit.r_squared:.4f}"]
    for name, (value, error) in fit.parameters.items():
        lo, hi = fit.interval(name)
        lines.append(f"#   {name} = {value:.6g} +- {error:.3g} (95 %: {lo:.6g} to {hi:.6g})")
    lines += [f"#   {note}" for note in fit.notes]
    lines.append("rate:")
    for key, value in fit.law.model_dump(mode="json", exclude_defaults=True).items():
        lines.append(f"  {key}: {json.dumps(value)}")
    return "\n".join(lines)


def _finite(value: float) -> float | None:
    return value if math.isfinite(value) else None


def fit_dict(fit: Fit) -> dict[str, Any]:
    """The fit as JSON-ready data (an infinite error or interval bound is null)."""
    return {
        "rate": fit.law.model_dump(mode="json"),
        "parameters": {
            n: {
                "value": v,
                "standard_error": _finite(e),
                "interval_95": [_finite(b) for b in fit.interval(n)],
            }
            for n, (v, e) in fit.parameters.items()
        },
        "r_squared": fit.r_squared,
        "points": fit.points,
        "residuals": fit.residuals,
        "notes": fit.notes,
    }


#: Where kinetic data files are.
DATA_DIR = "experiments/kinetics"


def kinetic_data_view(chemistry: Any, texts: Mapping[str, str]) -> dict[str, Any]:
    """``GET /api/kinetics``: every kinetic data file (*texts*: path -> text) with its points
    and its default fit (a power law in the reaction's reactants, over 1 - Q/K where the reaction
    is reversible and its equilibrium constant is known), or the problem with either."""
    from chemeascode.domains.chemistry.equilibrium import reaction_ln_k

    reactions = chemistry.reactions.by_id() if chemistry.reactions else {}
    ideal = {c.id: c.ideal_gas for c in chemistry.components().values()}
    files = []
    for path, text in sorted(texts.items()):
        entry: dict[str, Any] = {"file": path, "data": None, "fit": None, "problem": None}
        try:
            data = KineticData.model_validate(yaml.safe_load(text) or {})
        except yaml.YAMLError as failure:
            entry["problem"] = f"{path}: {str(failure).splitlines()[0]}"
            files.append(entry)
            continue
        except ValidationError as failure:
            errors = failure.errors()
            where = ".".join(str(part) for part in errors[0]["loc"]) or "the file"
            more = f" (and {len(errors) - 1} more)" if len(errors) > 1 else ""
            entry["problem"] = f"{path}: {where}: {errors[0]['msg']}{more}"
            files.append(entry)
            continue
        entry["data"] = data.model_dump(mode="json", by_alias=True)
        reaction = reactions.get(data.reaction)
        if reaction is None:
            entry["problem"] = f"reaction {data.reaction} is not in process/reactions.yaml"
            files.append(entry)
            continue
        if data.integral:  # conversions: a forward power law through the reactors
            from chemeascode.domains.experiments.kinetic_fit import fit_integral

            fixed = {n: -v for n, v in reaction.stoichiometry.items() if v < 0}
            try:
                fit = fit_integral(data, reaction.stoichiometry, fixed)
                entry["fit"] = {**fit_dict(fit), "reverse": False}
            except ValueError as failure:
                entry["problem"] = f"no fit: {failure}"
            files.append(entry)
            continue
        reactants = [n for n, v in reaction.stoichiometry.items() if v < 0]
        ln_k = None
        if reaction.reversible:
            try:
                reaction_ln_k(reaction, ideal, data.points[0].temperature)

                def ln_k(t: float, reaction: Any = reaction) -> float:
                    return reaction_ln_k(reaction, ideal, t)

            except ValueError:
                ln_k = None
        try:
            fit = fit_power_law(data, reactants, reaction.stoichiometry, ln_k)
            entry["fit"] = {**fit_dict(fit), "reverse": ln_k is not None}
        except ValueError as failure:
            if ln_k is None:
                entry["problem"] = f"no fit: {failure}"
            else:  # 1 - Q/K fails at a point (K out of range, at equilibrium): forward only
                try:
                    fit = fit_power_law(data, reactants, reaction.stoichiometry, None)
                    note = f"fitted forward only: over 1 - Q/K, {failure}"
                    entry["fit"] = {**fit_dict(fit), "reverse": False}
                    entry["fit"]["notes"] = [*entry["fit"]["notes"], note]
                except ValueError as again:
                    entry["problem"] = f"no fit: {again}"
        files.append(entry)
    return {"directory": DATA_DIR, "files": files}
