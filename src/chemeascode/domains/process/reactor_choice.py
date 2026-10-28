"""Which ideal reactor suits a reaction network: yield and selectivity of a product against the
conversion of the key component, for an isothermal plug-flow reactor, one stirred tank and N
stirred tanks in series, over a range of space times (Levenspiel's comparison).

For a reactor step with rate laws (``cheme process reactor-choice NODE --product P``), at the
inlet's temperature and pressure:

- PFR: ``dF/dV = nu M r`` integrated along the volume (Dormand-Prince, as the fixed bed), with
  ``M`` 1 for a rate per m3 or the ``catalyst_loading`` for a rate per kg;
- CSTR and N CSTRs: :func:`.stirred_tank.solve_cstr` at each total space time (``tau / N`` per
  tank);
- per point the space time ``tau = V / Q0`` (s), the conversion ``X`` of the key, the molar
  selectivity ``S = F_p formed / F_key converted`` and the yield ``Y = F_p formed / F_key in``;
- along the PFR, the instantaneous selectivity ``dF_p / -dF_key``: the plot that shows whether
  a high or a low key concentration favours the product (parallel reactions of different
  orders), and how fast a series product is lost.

The space times run from 1/100 to 1000 times the feed's characteristic time ``c_key / -r_key``
(60 points, logarithmic). The comparison is of ideal reactors: isothermal, no mixing between
plug flow and perfect mixing, the rate laws inside their ranges (a point outside is noted).
:func:`choice_svg` draws it (yield and instantaneous selectivity against conversion).
"""

from __future__ import annotations

import math
from collections.abc import Mapping
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from chemeascode.domains.process.fixed_bed import _dopri_step
from chemeascode.domains.process.stirred_tank import TankError, _mixture, solve_cstr

POINTS = 60
#: Steps of the PFR integration at most (a stiff network stops there, noted).
MAX_STEPS = 200_000


class ChoiceError(ValueError):
    """The comparison cannot be made as asked."""


@dataclass
class Curve:
    """One reactor configuration's points: (tau s, conversion, selectivity, yield)."""

    configuration: str
    points: list[tuple[float, float, float | None, float]] = field(default_factory=list)

    def best(self) -> tuple[float, float, float | None, float] | None:
        """The point of the largest yield."""
        return max(self.points, key=lambda p: p[3], default=None)


@dataclass
class ReactorChoice:
    node: str
    key: str
    product: str
    temperature: float  # K
    pressure: float  # kPa(a)
    curves: list[Curve]
    #: along the PFR: (conversion, instantaneous selectivity dF_p / -dF_key)
    instantaneous: list[tuple[float, float]] = field(default_factory=list)
    notes: list[str] = field(default_factory=list)

    def as_dict(self) -> dict[str, Any]:
        def point(p: tuple[float, float, float | None, float]) -> dict[str, Any]:
            return {"tau_s": p[0], "conversion": p[1], "selectivity": p[2], "yield": p[3]}

        return {
            "node": self.node,
            "key": self.key,
            "product": self.product,
            "temperature_K": self.temperature,
            "pressure_kPa": self.pressure,
            "curves": [
                {
                    "configuration": c.configuration,
                    "best": point(b) if (b := c.best()) else None,
                    "points": [point(p) for p in c.points],
                }
                for c in self.curves
            ],
            "instantaneous": [{"conversion": x, "selectivity": s} for x, s in self.instantaneous],
            "notes": self.notes,
        }

    def csv(self) -> str:
        lines = ["configuration,tau_s,conversion,selectivity,yield"]
        for c in self.curves:
            for tau, x, s, y in c.points:
                lines.append(
                    f"{c.configuration},{tau:.6g},{x:.6g},{'' if s is None else f'{s:.6g}'},{y:.6g}"
                )
        return "\n".join(lines) + "\n"


def compare(
    reactions: list[Any],
    feed: Mapping[str, float],
    temperature: float,
    pressure: float,
    key: str,
    product: str,
    data: Mapping[str, Any],
    liquid: Any = None,
    tanks: int = 3,
    catalyst_loading: float | None = None,
    node: str = "",
) -> ReactorChoice:
    """The comparison (see the module docstring) of *feed* (kmol/h) at *temperature* K and
    *pressure* kPa through *reactions*. Raises ChoiceError naming what is missing."""
    from chemeascode.domains.process.schema import Tank

    names = list(dict.fromkeys([*feed, *(n for r in reactions for n in r.stoichiometry)]))
    try:
        mix = _mixture(reactions, names, data, liquid, {}, catalyst_loading)
    except TankError as failure:
        raise ChoiceError(str(failure)) from failure
    if key not in names or feed.get(key, 0.0) <= 0:
        raise ChoiceError(f"the key {key} is not fed")
    if product == key:
        raise ChoiceError("the product is the key component")
    if not any(r.stoichiometry.get(product, 0) > 0 for r in reactions):
        raise ChoiceError(f"{product} is formed by none of the reactions")
    nu = mix.nu()
    m = len(reactions)
    f0 = [feed.get(n, 0.0) / 3600.0 for n in names]  # kmol/s
    ki, pi = names.index(key), names.index(product)
    q0 = mix.volume_flow(dict(zip(names, f0, strict=True)), temperature, pressure)
    try:
        mult = mix.multipliers(1.0)
        r0 = mix.rates(f0, temperature, pressure)
    except ValueError as failure:
        raise ChoiceError(str(failure)) from failure
    consumption = -sum(nu[ki][j] * mult[j] * r0[j] for j in range(m))  # kmol/(m3 s)
    if consumption <= 0:
        raise ChoiceError(f"the feed does not convert {key} (its rate is zero or negative)")
    t_char = (f0[ki] / q0) / consumption
    taus = [t_char * 10 ** (-2 + 5 * k / (POINTS - 1)) for k in range(POINTS)]

    def measures(f: list[float]) -> tuple[float, float | None, float]:
        converted = f0[ki] - f[ki]
        formed = f[pi] - f0[pi]
        x = converted / f0[ki]
        return x, (formed / converted if converted > 1e-12 * f0[ki] else None), formed / f0[ki]

    result = ReactorChoice(node, key, product, temperature, pressure, [])
    result.notes.append(
        "ideal reactors at the inlet temperature (isothermal); rate laws as declared"
    )
    if any(not r.rate.covers(temperature) for r in reactions):
        result.notes.append(f"{temperature:.6g} K is outside a rate law's temperature range")
    # -- PFR: integrate along the volume, recording at each tau
    pfr = Curve("PFR")

    def derivatives(state: list[float]) -> list[float]:
        f = state[:-2]
        rates = mix.rates(f, temperature, pressure)
        dv = [sum(nu[i][j] * mult[j] * rates[j] for j in range(m)) for i in range(len(names))]
        return [*dv, 0.0, 0.0]

    state = [*f0, temperature, pressure]
    volume, h = 0.0, taus[0] * q0 / 10
    steps = 0
    for tau in taus:
        target = tau * q0
        while volume < target * (1 - 1e-12):
            steps += 1
            if steps > MAX_STEPS:
                result.notes.append(
                    f"PFR: stopped after {MAX_STEPS} steps at a space time of "
                    f"{volume / q0:.4g} s (a stiff network)"
                )
                break
            step = min(h, target - volume)
            try:
                new, error = _dopri_step(derivatives, state, step)
            except ValueError as failure:
                raise ChoiceError(
                    f"PFR at a space time of {volume / q0:.4g} s: {failure}"
                ) from failure
            scale = [
                max(abs(a), abs(b), 1e-12 * f0[ki])
                for a, b in zip(state[:-2], new[:-2], strict=True)
            ] + [1.0, 1.0]
            err = max(abs(e) / s for e, s in zip(error, scale, strict=True))
            if err > 1e-8 and step > 1e-14 * target:
                h = step * max(0.2, 0.9 * (1e-8 / err) ** 0.2)
                continue
            before = state
            state = [max(v, 0.0) if i < len(names) else v for i, v in enumerate(new)]
            volume += step
            h = step * 2
            d_key = before[ki] - state[ki]
            if d_key > 1e-14 * f0[ki]:
                result.instantaneous.append(
                    (1 - state[ki] / f0[ki], (state[pi] - before[pi]) / d_key)
                )
        if steps > MAX_STEPS:
            break
        pfr.points.append((tau, *measures(state[:-2])))
    result.curves.append(pfr)
    # -- stirred tanks
    for count in sorted({1, tanks}):
        curve = Curve("CSTR" if count == 1 else f"{count} CSTRs")
        failed: list[str] = []
        for tau in taus:
            tank = Tank(
                residence_time=tau / count,
                count=count,
                heat="isothermal",
                catalyst_loading=catalyst_loading,
                provenance="assumed",
            )
            try:
                solved = solve_cstr(reactions, feed, temperature, pressure, tank, data, liquid)
            except TankError as failure:
                failed.append(f"{tau:.4g} s ({failure})")
                continue
            f = [solved.outlet.get(n, 0.0) / 3600.0 for n in names]
            curve.points.append((tau, *measures(f)))
        if failed:
            result.notes.append(
                f"{curve.configuration}: {len(failed)} space time(s) not solved, e.g. {failed[0]}"
            )
        result.curves.append(curve)
    if len(result.instantaneous) > 4 * POINTS:
        step = len(result.instantaneous) / (4 * POINTS)
        result.instantaneous = [result.instantaneous[int(k * step)] for k in range(4 * POINTS)]
    return result


def node_choice(
    root: Path,
    node: str,
    product: str,
    key: str | None = None,
    tanks: int = 3,
    case: str | None = None,
) -> ReactorChoice:
    """:func:`compare` for reactor *node* of the plant at *root*: its reactions, its one inlet
    stream's flow, composition, temperature and pressure in *case* (default: the default
    case), the key by default the first fed reactant. Raises ChoiceError."""
    reactions, moles, kelvin, kpa, key, data, liquid, loading = _node_inputs(root, node, key, case)
    return compare(reactions, moles, kelvin, kpa, key, product, data, liquid, tanks, loading, node)


def _node_inputs(
    root: Path, node: str, key: str | None, case: str | None
) -> tuple[list[Any], dict[str, float], float, float, str, Any, Any, float | None]:
    """What a comparison of reactor *node* starts from: (reactions, inlet kmol/h, K, kPa(a),
    key, ideal-gas data, liquid, catalyst loading). Raises ChoiceError."""
    from chemeascode.domains.process.liquid_phase import liquid_of
    from chemeascode.domains.process.model import load, stream_flows
    from chemeascode.foundation.units import to_kelvin, to_kpa_abs

    process, found = load(Path(root))
    if process is None:
        raise ChoiceError("the process does not load: " + "; ".join(f.format() for f in found))
    fs = process.flowsheet
    if node not in process.nodes:
        raise ChoiceError(f"no block or step {node}")
    case = case or fs.default_case()
    reactions, unknown = process.reactions_of(node)
    if unknown or not reactions:
        raise ChoiceError(f"{node} names no declared reactions")
    inlets = [s for s in fs.streams if (e := process.ends(s)[1]) is not None and e.node == node]
    if len(inlets) != 1:
        raise ChoiceError(f"{node} has {len(inlets)} inlet streams; the comparison takes one")
    inlet = inlets[0]
    state = inlet.state.get(case)
    t = getattr(state, "temperature", None)
    p = getattr(state, "pressure", None)
    kelvin = to_kelvin(t.value, t.unit or fs.units.temperature) if t is not None else None
    kpa = to_kpa_abs(p.value, p.unit or fs.units.pressure) if p is not None else None
    if kelvin is None or kpa is None:
        raise ChoiceError(f"no inlet temperature and absolute pressure ({inlet.id})")
    flows = stream_flows(process, inlet, case)
    if flows.components is None:
        raise ChoiceError(f"no composition and flow of {inlet.id}: " + ", ".join(flows.missing))
    comps = process.components()
    lacking = sorted(
        n
        for n, kg in flows.components.items()
        if kg and not getattr(comps.get(n), "molar_mass", None)
    )
    if lacking:
        raise ChoiceError("no molar_mass for " + ", ".join(lacking))
    moles = {n: kg / comps[n].molar_mass for n, kg in flows.components.items() if kg}
    if key is None:
        key = next(
            (
                n
                for r in reactions
                for n, v in r.stoichiometry.items()
                if v < 0 and moles.get(n, 0) > 0
            ),
            None,
        )
        if key is None:
            raise ChoiceError("no reactant is fed")
    liquid = liquid_of(process) if any(r.phase == "liquid" for r in reactions) else None
    item = process.nodes[node]
    loading = getattr(getattr(item, "tank", None), "catalyst_loading", None) or getattr(
        getattr(item, "batch", None), "catalyst_loading", None
    )
    if loading is None and getattr(item, "bed", None) is not None:
        # a packed bed: kg of catalyst per m3 of bed, the catalyst's bulk density
        catalysts = process.catalysts.by_id() if process.catalysts else {}
        physical = getattr(catalysts.get(item.catalyst or ""), "physical", None)
        loading = getattr(physical, "bulk_density", None)
    return reactions, moles, kelvin, kpa, key, process.ideal_gas(), liquid, loading


# -- the plot -----------------------------------------------------------------------------------

#: Categorical slots 1-3 of the reference palette (light, dark): validated for all pairs.
_SERIES = (("#2a78d6", "#3987e5"), ("#eb6834", "#d95926"), ("#1baf7a", "#199e70"))
_W, _H = 720, 300
_LEFT, _RIGHT, _TOP, _BOTTOM = 56, 120, 34, 44


def _panel(
    x0: float,
    title: str,
    series: list[tuple[str, int, list[tuple[float, float]]]],
    ylabel: str,
    best: list[tuple[int, float, float, str]],
) -> list[str]:
    """One chart of the figure: x the conversion 0..1, y from 0 (or the next multiple of 0.2
    below the lowest value, at most down to -1) to 1 (or the next multiple of 0.2 above the
    highest, at most 5); values beyond are clipped. A line per series."""
    w = (_W - _LEFT - _RIGHT) / 2 - 20
    h = _H - _TOP - _BOTTOM
    values = [y for _, _, pts in series for _, y in pts]
    lowest, highest = min(values, default=0.0), max(values, default=1.0)
    low = max(-1.0, min(0.0, -0.2 * math.ceil(-lowest / 0.2 - 1e-9)))  # clipped below -1
    # above 1 where a product forms more than one kmol per kmol of the key (A -> 2 B)
    high = min(5.0, max(1.0, 0.2 * math.ceil(highest / 0.2 - 1e-9)))

    def px(x: float) -> float:
        return x0 + w * min(max(x, 0.0), 1.0)

    def py(y: float) -> float:
        return _TOP + h * (1 - (min(max(y, low), high) - low) / (high - low))

    out = [f'<text class="title" x="{x0:.1f}" y="{_TOP - 14}">{title}</text>']
    ticks = round((high - low) / 0.2)
    for k in range(0, ticks + 1, 1 if ticks <= 10 else 5):
        v = low + 0.2 * k
        out.append(
            f'<line class="grid" x1="{x0:.1f}" x2="{x0 + w:.1f}" y1="{py(v):.1f}" '
            f'y2="{py(v):.1f}"/>'
        )
        out.append(
            f'<text class="tick" x="{x0 - 6:.1f}" y="{py(v) + 4:.1f}" '
            f'text-anchor="end">{v + 0.0:.1f}</text>'
        )
    for k in range(6):
        out.append(
            f'<text class="tick" x="{px(k / 5):.1f}" y="{_TOP + h + 16:.1f}" '
            f'text-anchor="middle">{k / 5:.1f}</text>'
        )
    out.append(
        f'<line class="axis" x1="{x0:.1f}" x2="{x0 + w:.1f}" y1="{py(0):.1f}" y2="{py(0):.1f}"/>'
    )
    out.append(
        f'<text class="label" x="{x0 + w / 2:.1f}" y="{_H - 8}" '
        f'text-anchor="middle">conversion</text>'
    )
    out.append(
        f'<text class="label" transform="translate({x0 - 40:.1f},{_TOP + h / 2:.1f}) '
        f'rotate(-90)" text-anchor="middle">{ylabel}</text>'
    )
    for name, slot, points in series:
        if len(points) < 2:
            continue
        d = " ".join(
            f"{'M' if i == 0 else 'L'}{px(x):.1f},{py(y):.1f}" for i, (x, y) in enumerate(points)
        )
        out.append(f'<path class="line s{slot}" d="{d}"><title>{name}</title></path>')
    for slot, x, y, text in best:
        out.append(
            f'<circle class="mark s{slot}" cx="{px(x):.1f}" cy="{py(y):.1f}" r="4">'
            f"<title>{text}</title></circle>"
        )
    return out


def choice_svg(choice: ReactorChoice) -> str:
    """The comparison as an SVG figure: the yield of the product against the key's conversion
    per configuration (the largest yield marked), and the PFR's instantaneous selectivity.
    Light and dark (prefers-color-scheme), tooltips on the lines and marks."""

    def colours(column: int, indent: str) -> str:
        return "\n".join(
            f"{indent}.line.s{k} {{ stroke: {pair[column]}; }}\n"
            f"{indent}.mark.s{k} {{ fill: {pair[column]}; }}"
            for k, pair in enumerate(_SERIES)
        )

    style = f"""<style>
  svg {{ background: #fcfcfb; font-family: system-ui, sans-serif; }}
  .title {{ font-size: 13px; font-weight: 600; fill: #0b0b0b; }}
  .label, .legend {{ font-size: 11px; fill: #52514e; }}
  .tick {{ font-size: 10px; fill: #52514e; }}
  .grid {{ stroke: #e5e4e0; stroke-width: 1; }}
  .axis {{ stroke: #a3a29b; stroke-width: 1; }}
  .line {{ fill: none; stroke-width: 2; stroke-linejoin: round; }}
  .mark {{ stroke: #fcfcfb; stroke-width: 2; }}
{colours(0, "  ")}
  @media (prefers-color-scheme: dark) {{
    svg {{ background: #1a1a19; }}
    .title {{ fill: #f0efec; }}
    .label, .legend, .tick {{ fill: #c3c2b7; }}
    .grid {{ stroke: #33332f; }}
    .axis {{ stroke: #6e6d66; }}
    .mark {{ stroke: #1a1a19; }}
{colours(1, "    ")}
  }}
</style>"""
    series = []
    best = []
    for slot, curve in enumerate(choice.curves[: len(_SERIES)]):
        series.append((curve.configuration, slot, [(x, y) for _, x, _, y in curve.points]))
        b = curve.best()
        if b is not None:
            text = (
                f"{curve.configuration}: largest yield {b[3]:.3f} at conversion {b[1]:.3f}, "
                f"space time {b[0]:.4g} s"
            )
            best.append((slot, b[1], b[3], text))
    width = (_W - _LEFT - _RIGHT) / 2 - 20
    right = _LEFT + width + 60
    body = _panel(_LEFT, f"Yield of {choice.product}", series, f"yield of {choice.product}", best)
    body += _panel(
        right,
        "Instantaneous selectivity (PFR)",
        [("PFR", 0, list(choice.instantaneous))],
        f"d{choice.product} / -d{choice.key}",
        [],
    )
    legend_x = right + width + 24
    for k, curve in enumerate(choice.curves[: len(_SERIES)]):
        y = _TOP + 8 + 18 * k
        body.append(
            f'<line class="line s{k}" x1="{legend_x}" x2="{legend_x + 18}" y1="{y}" y2="{y}"/>'
        )
        body.append(
            f'<text class="legend" x="{legend_x + 24}" y="{y + 4}">{curve.configuration}</text>'
        )
    body.append(
        f'<text class="tick" x="{legend_x}" y="{_TOP + 8 + 18 * 4}">'
        f'<tspan x="{legend_x}">dots: largest</tspan>'
        f'<tspan x="{legend_x}" dy="13">yield</tspan></text>'
    )
    note = (
        f"{choice.key} converted to {choice.product}, {choice.temperature:.6g} K, "
        f"{choice.pressure:.6g} kPa(a), ideal isothermal reactors"
    )
    width_total = legend_x + 100
    return (
        f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 {width_total:.0f} {_H}" '
        f'width="{width_total:.0f}" height="{_H}" role="img">'
        f"<title>Reactor choice: {note}</title>\n{style}\n" + "\n".join(body) + "\n</svg>\n"
    )


def summary_text(choice: ReactorChoice) -> str:
    """The comparison as text: the largest yield of each configuration."""
    lines = [
        f"{choice.node}: yield of {choice.product} from {choice.key} at "
        f"{choice.temperature:.6g} K, {choice.pressure:.6g} kPa(a)"
    ]
    for curve in choice.curves:
        b = curve.best()
        if b is None:
            lines.append(f"  {curve.configuration}: no point")
            continue
        s = "" if b[2] is None else f", selectivity {b[2]:.4g}"
        lines.append(
            f"  {curve.configuration}: largest yield {b[3]:.4g} at conversion {b[1]:.4g}{s}, "
            f"space time {b[0]:.4g} s"
        )
    lines += [f"  note: {n}" for n in choice.notes]
    return "\n".join(lines)
