"""The uncertainty of a reactor's result from the uncertainty of its reaction data
(``cheme process reactor-uncertainty NODE``): Monte Carlo over the reactions' ``uncertainty``
blocks, through the reactor's own model, nothing written.

Each draw multiplies, per reaction, the rate law's A and Ea (``rate.uncertainty``), the heat of
reaction, the equilibrium constant K (on ln K: ``ln K + ln m``) and the conversion (clipped to
1), each by a multiplier of its distribution (:func:`foundation.uncertainty.draw`, one
generator seeded for repeatability), and solves the step again: a fixed bed
(:func:`.fixed_bed.solve_node`), a stirred tank or batch (:func:`.stirred_tank.solve_node`), or
a conversion reactor. A conversion reactor given by ``selectivity:`` is evaluated as cheme
process propagate evaluates it (:func:`.chemistry.reactions.selectivity_outlet`), from the key's
conversion (clipped to 1) and the selectivities, each multiplied by a draw of its
``selectivity.uncertainty``. Per draw it records the conversion of the key (the first fed
reactant, a selectivity's own key), the outlet flow of each component, the outlet temperature
and the highest temperature (a bed's hot spot, a batch's peak); the report gives their
deterministic value, mean, 5th, 50th and 95th percentile. Draws that do not solve are counted
and named, not dropped silently. Equilibrium and Gibbs reactors are not sampled here.

Only what the step's model reads is sampled: A and Ea and, where a rate law has ``reverse:
equilibrium``, K for a fixed bed, tank or batch; the heat of reaction for a liquid-phase
adiabatic tank or batch only (a gas's comes from the ideal-gas data, an isothermal one's
temperatures do not depend on it); the conversion for a conversion reactor; the
``selectivity:``'s own uncertainty, and nothing of its reactions, for a selectivity reactor.
Other uncertain fields are listed as ``not_used`` with the reason, and a step with nothing used
is refused. A selectivity without an uncertainty of its own is not given one: no spread is
assumed from its provenance.
"""

from __future__ import annotations

import copy
import random
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any

from chemeascode.foundation.uncertainty import draw

SAMPLED = ("pfr", "cstr", "batch", "semibatch", "conversion", "selectivity")
#: One draw's result: the conversion of the key, the outlet and the highest temperature (K),
#: the outlet flow of each component (kmol/h).
Solved = tuple[float, float | None, float | None, dict[str, float]]


class SamplingError(ValueError):
    """The reactor cannot be sampled as asked."""


@dataclass
class Spread:
    deterministic: float | None
    mean: float | None = None
    p5: float | None = None
    p50: float | None = None
    p95: float | None = None


@dataclass
class ReactorUncertainty:
    node: str
    model: str
    key: str
    samples: int
    seed: int
    conversion: Spread
    outlet_temperature: Spread
    highest_temperature: Spread
    failed: int = 0
    failures: list[str] = field(default_factory=list)
    #: what was sampled: "reaction.field"
    sampled: list[str] = field(default_factory=list)
    #: uncertain fields the model does not use, with the reason: not sampled
    not_used: dict[str, str] = field(default_factory=dict)
    #: the outlet flow of each component, kmol/h
    outlet: dict[str, Spread] = field(default_factory=dict)

    def as_dict(self) -> dict[str, Any]:
        return asdict(self)


def _perturbed(reaction: Any, rng: random.Random) -> Any:
    """A copy of *reaction* with each uncertain value multiplied by a draw."""
    import math

    update: dict[str, Any] = {}
    if reaction.rate is not None and reaction.rate.uncertainty is not None:
        u = reaction.rate.uncertainty
        k = reaction.rate.k.model_copy(
            update={
                "A": reaction.rate.k.A * draw(u.A, rng),
                "Ea": reaction.rate.k.Ea * draw(u.Ea, rng),
            }
        )
        update["rate"] = reaction.rate.model_copy(update={"k": k})
    if reaction.heat_of_reaction is not None and reaction.heat_of_reaction.uncertainty:
        h = reaction.heat_of_reaction
        update["heat_of_reaction"] = h.model_copy(
            update={"value": h.value * draw(h.uncertainty, rng)}
        )
    if reaction.equilibrium_constant is not None and reaction.equilibrium_constant.uncertainty:
        kq = reaction.equilibrium_constant
        m = draw(kq.uncertainty, rng)
        update["equilibrium_constant"] = kq.model_copy(
            update={"a": kq.a + math.log(m) if m > 0 else kq.a}
        )
    if reaction.conversion is not None and reaction.conversion.uncertainty:
        c = reaction.conversion
        value = min(max(c.value * draw(c.uncertainty, rng), 1e-9), 1.0)
        update["conversion"] = c.model_copy(update={"value": value})
    return reaction.model_copy(update=update) if update else reaction


def _drawn(spec: Any, rng: random.Random) -> tuple[float, dict[str, float]]:
    """The conversion (clipped to 1) and the selectivities of ``selectivity:`` *spec*, each
    multiplied by a draw of its uncertainty."""
    u = spec.uncertainty
    if u is None:
        return spec.conversion, dict(spec.products)
    conversion = min(max(spec.conversion * draw(u.conversion, rng), 1e-9), 1.0)
    products = {p: max(s * draw(u.products.get(p), rng), 0.0) for p, s in spec.products.items()}
    return conversion, products


def _selectivity_fields(spec: Any) -> list[str]:
    """The uncertain figures of ``selectivity:`` *spec*: ``selectivity.conversion``,
    ``selectivity.products.<id>``."""
    u = spec.uncertainty
    if u is None:
        return []
    found = ["selectivity.conversion"] if u.conversion is not None else []
    return found + [f"selectivity.products.{p}" for p in spec.products if p in u.products]


def _unused(reaction: Any, name: str, model: str, item: Any) -> str:
    """Why *model* (on step *item*) does not read the field *name* of *reaction*; "" when it
    does, so that its draws change the result."""
    kinetic = model in ("pfr", "cstr", "batch", "semibatch")
    given = f"a {model} reactor"
    if name == "rate":
        return "" if kinetic else f"{given} does not use the rate law"
    if name == "conversion":
        if model == "selectivity":
            return "a selectivity reactor takes the key's conversion from selectivity:"
        return "" if model == "conversion" else f"reactor {model} solves its rate laws"
    if name == "equilibrium_constant":
        if not kinetic:
            return f"{given} does not use K"
        if reaction.rate is None or reaction.rate.reverse != "equilibrium":
            return "the rate law has no reverse: equilibrium"
        return ""
    # heat_of_reaction: only a liquid tank's or batch's enthalpies use it (stirred_tank
    # _Mixture.heats), and of what is sampled only an adiabatic one's temperatures depend on it
    if not kinetic:
        return f"{given} solves no energy balance"
    if model == "pfr":
        return "a fixed bed takes the heat of reaction from the ideal-gas data"
    vessel = {"cstr": "tank", "semibatch": "semi-batch"}.get(model, "batch")
    if reaction.phase != "liquid":
        return f"a gas-phase {vessel} takes the heat of reaction from the ideal-gas data"
    spec = item.tank if model == "cstr" else item.batch
    if spec is None:
        return f"no {vessel} declared"
    if spec.heat != "adiabatic":
        return f"an isothermal {vessel}'s temperatures do not depend on it"
    return ""


def _uncertain(reaction: Any, model: str, item: Any) -> tuple[list[str], dict[str, str]]:
    """The uncertain fields of *reaction* that *model* uses (``reaction.field``), and those it
    does not, each with the reason: their draws would change nothing."""
    found: list[str] = []
    if reaction.rate is not None and reaction.rate.uncertainty is not None:
        u = reaction.rate.uncertainty
        found += [f"rate.{n}" for n in ("A", "Ea") if getattr(u, n) is not None]
    for name in ("heat_of_reaction", "equilibrium_constant", "conversion"):
        value = getattr(reaction, name)
        if value is not None and value.uncertainty is not None:
            found.append(name)
    used: list[str] = []
    unused: dict[str, str] = {}
    for name in found:
        why = _unused(reaction, name.split(".")[0], model, item)
        if why:
            unused[f"{reaction.id}.{name}"] = why
        else:
            used.append(f"{reaction.id}.{name}")
    return used, unused


def _percentile(values: list[float], q: float) -> float:
    ordered = sorted(values)
    pos = q * (len(ordered) - 1)
    lo = int(pos)
    hi = min(lo + 1, len(ordered) - 1)
    return ordered[lo] + (ordered[hi] - ordered[lo]) * (pos - lo)


def _spread(deterministic: float | None, values: list[float]) -> Spread:
    if not values:
        return Spread(deterministic)
    return Spread(
        deterministic,
        sum(values) / len(values),
        _percentile(values, 0.05),
        _percentile(values, 0.5),
        _percentile(values, 0.95),
    )


def sample_node(
    root: Path, node: str, samples: int = 200, seed: int = 1, case: str | None = None
) -> ReactorUncertainty:
    """The Monte Carlo of reactor *node* of the plant at *root* (see the module docstring).
    Raises SamplingError when the step cannot be sampled or nothing in it is uncertain."""
    from chemeascode.domains.chemistry.reactions import convert, selectivity_outlet
    from chemeascode.domains.process.model import load, stream_flows

    process, found = load(Path(root))
    if process is None:
        raise SamplingError("the process does not load: " + "; ".join(f.format() for f in found))
    if node not in process.nodes:
        raise SamplingError(f"no block or step {node}")
    item = process.nodes[node]
    model = getattr(item, "reactor", None) or "conversion"
    spec = getattr(item, "selectivity", None)
    if model == "conversion" and spec is not None:
        model = "selectivity"  # as propagate solves it
    if model not in SAMPLED:
        raise SamplingError(f"{node} is a {model} reactor: sampled are {', '.join(SAMPLED)}")
    case = case or process.flowsheet.default_case()
    reactions, unknown = process.reactions_of(node)
    if unknown or not reactions:
        raise SamplingError(f"{node} names no declared reactions")
    sampled: list[str] = _selectivity_fields(spec) if model == "selectivity" else []
    not_used: dict[str, str] = {}
    for r in reactions:
        used, unused = _uncertain(r, model, item)
        sampled += used
        not_used |= unused
    if not sampled:
        if not_used:
            raise SamplingError(
                f"nothing to sample: the {model} model of {node} does not use "
                + "; ".join(f"{name} ({why})" for name, why in not_used.items())
            )
        if model == "selectivity":
            raise SamplingError(
                f"neither the selectivity of {node} nor its reactions give an uncertainty: "
                "nothing to sample (give selectivity.uncertainty)"
            )
        raise SamplingError(f"no reaction of {node} gives an uncertainty: nothing to sample")
    fs = process.flowsheet
    inlets = [s for s in fs.streams if (e := process.ends(s)[1]) is not None and e.node == node]
    if model == "semibatch":  # the charge and its doses: solve_node splits them
        inlet: Any = inlets
    elif len(inlets) != 1:
        raise SamplingError(f"{node} has {len(inlets)} inlet streams; sampling takes one")
    else:
        inlet = inlets[0]
    comps = process.components()
    moles: dict[str, float] = {}
    for stream in inlets:
        flows = stream_flows(process, stream, case)
        if flows.components is None:
            raise SamplingError(f"no composition and flow of {stream.id}")
        for n, kg in flows.components.items():
            if kg:
                moles[n] = moles.get(n, 0.0) + kg / comps[n].molar_mass
    key = next(
        (n for r in reactions for n, v in r.stoichiometry.items() if v < 0 and moles.get(n, 0) > 0),
        None,
    )
    if model == "selectivity":
        key = spec.key if moles.get(spec.key, 0) > 0 else None
    if key is None:
        raise SamplingError("no reactant is fed")

    def solve(chosen: list[Any], figures: tuple[float, dict[str, float]] | None = None) -> Solved:
        """(conversion of the key, outlet T, highest T, outlet kmol/h) with *chosen* as the
        step's reactions and, for a selectivity reactor, *figures* (conversion, selectivities)
        as its selectivity."""
        if model == "selectivity":
            conversion, products = figures or (spec.conversion, spec.products)
            out = selectivity_outlet(chosen, key, conversion, products, moles)
            return 1 - out.get(key, 0.0) / moles[key], None, None, out
        work = copy.copy(process)
        by_id = {r.id: r for r in chosen}
        work.reactions = process.reactions.model_copy(
            update={"reactions": [by_id.get(r.id, r) for r in process.reactions.reactions]}
        )
        if model == "pfr":
            from chemeascode.domains.process.fixed_bed import solve_node

            result, _ = solve_node(work, item, inlet, case)
            return (
                1 - result.outlet.get(key, 0.0) / moles[key],
                result.temperature,
                result.hot_spot,
                result.outlet,
            )
        if model in ("cstr", "batch", "semibatch"):
            from chemeascode.domains.process.stirred_tank import solve_node as solve_tank

            result, _ = solve_tank(work, item, inlet, case)
            highest = max(
                [p[1] for p in result.profile] + [t["temperature_K"] for t in result.tanks],
                default=result.temperature,
            )
            conversion = 1 - result.outlet.get(key, 0.0) / moles[key]
            return conversion, result.temperature, highest, result.outlet
        original = {r.id: r for r in reactions}
        rates = {}
        for r in chosen:
            value = item.conversion.get(r.id, r.conversion.value if r.conversion else None)
            if value is not None and r.id in item.conversion and r.conversion is not None:
                # the step's own conversion, scaled by the reaction's sampled multiplier
                value = min(value * r.conversion.value / original[r.id].conversion.value, 1.0)
            rates[r.id] = value
        if any(v is None for v in rates.values()):
            raise SamplingError("a conversion reactor without a conversion of every reaction")
        out, _ = convert(chosen, rates, moles)  # type: ignore[arg-type]
        return 1 - out.get(key, 0.0) / moles[key], None, None, out

    try:
        base = solve(reactions)
    except ValueError as failure:
        raise SamplingError(f"{node} does not solve as declared: {failure}") from failure
    rng = random.Random(seed)
    values: list[Solved] = []
    failures: list[str] = []
    for _ in range(samples):
        chosen = [_perturbed(r, rng) for r in reactions]
        figures = _drawn(spec, rng) if model == "selectivity" else None
        try:
            values.append(solve(chosen, figures))
        except ValueError as failure:
            failures.append(str(failure))
    return ReactorUncertainty(
        node,
        model,
        key,
        samples,
        seed,
        _spread(base[0], [v[0] for v in values]),
        _spread(base[1], [v[1] for v in values if v[1] is not None]),
        _spread(base[2], [v[2] for v in values if v[2] is not None]),
        len(failures),
        list(dict.fromkeys(failures))[:5],
        sampled,
        not_used,
        {n: _spread(v, [d[3].get(n, 0.0) for d in values]) for n, v in base[3].items()},
    )


def uncertainty_text(result: ReactorUncertainty) -> str:
    def row(name: str, s: Spread, fmt: str, unit: str) -> str:
        if s.mean is None:
            return f"  {name}: {'-' if s.deterministic is None else format(s.deterministic, fmt)}"
        return (
            f"  {name}: {format(s.deterministic, fmt)}{unit} as declared; mean {s.mean:{fmt}}, "
            f"5 % {s.p5:{fmt}}, median {s.p50:{fmt}}, 95 % {s.p95:{fmt}}{unit}"
        )

    lines = [
        f"{result.node} ({result.model}): {result.samples} draws (seed {result.seed}) of "
        + ", ".join(result.sampled),
        row(f"conversion of {result.key}", result.conversion, ".4g", ""),
    ]
    for name, spread in result.outlet.items():
        lines.append(row(f"outlet {name}", spread, ".4g", " kmol/h"))
    if result.outlet_temperature.deterministic is not None:
        lines.append(row("outlet temperature", result.outlet_temperature, ".1f", " K"))
        lines.append(row("highest temperature", result.highest_temperature, ".1f", " K"))
    for name, why in result.not_used.items():
        lines.append(f"  not sampled, the model does not use {name}: {why}")
    if result.failed:
        lines.append(f"  {result.failed} draw(s) did not solve: " + "; ".join(result.failures))
    lines.append("  nothing is written: the files keep their deterministic values")
    return "\n".join(lines)
