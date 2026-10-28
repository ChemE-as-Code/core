"""A candidate attainable region of a reaction network: which compositions of the key component
and a product ideal reactors, run in series and mixed, can reach from the feed (Glasser,
Hildebrandt and Crowe, Ind. Eng. Chem. Res. 26 (1987) 1803).

In the plane of the key's and the product's flows relative to the key's feed (``x = F_key /
F_key0``, ``y = F_P / F_key0``; concentrations relative to the feed's at constant density),
isothermal at the inlet's temperature and pressure, the candidates are:

- the plug-flow trajectory from the feed;
- the stirred-tank locus from the feed (every space time);
- plug-flow trajectories from points of that locus (a CSTR followed by a PFR);
- and mixing of any of these points: their convex hull.

The region is the convex hull of these points. Its highest product yield lies on a vertex and
says which structure reaches it. It is a candidate: these constructions give the attainable
region of the textbook cases (series and Van de Vusse kinetics), but no check here proves that
no other reactor network leaves it (the region's necessary conditions are not tested), and only
the two coordinates are followed. Pure Python; the reactor models of :mod:`.reactor_choice` and
:mod:`.stirred_tank`.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field
from typing import Any

from chemeascode.domains.process.fixed_bed import _dopri_step
from chemeascode.domains.process.reactor_choice import ChoiceError
from chemeascode.domains.process.stirred_tank import TankError, _mixture, solve_cstr

#: Space times of each locus, relative to the feed's characteristic time (logarithmic).
POINTS = 50
#: Plug flows started from every this many points of the stirred-tank locus.
EVERY = 2
#: Integration steps of all plug flows together at most (a stiff network stops there, noted).
MAX_STEPS = 400_000


@dataclass
class RegionPoint:
    x: float  # F_key / F_key0
    y: float  # F_product / F_key0
    origin: str  # how it is reached


@dataclass
class AttainableRegion:
    key: str
    product: str
    temperature: float
    pressure: float
    pfr: list[RegionPoint] = field(default_factory=list)
    cstr: list[RegionPoint] = field(default_factory=list)
    cstr_pfr: list[list[RegionPoint]] = field(default_factory=list)
    hull: list[RegionPoint] = field(default_factory=list)
    notes: list[str] = field(default_factory=list)

    def best(self) -> RegionPoint | None:
        """The vertex of the highest product yield; among vertices within 0.2 % of it (the
        sampling's resolution) the simplest structure: plug flow, then one tank, then a tank
        followed by plug flow."""
        if not self.hull:
            return None
        top = max(p.y for p in self.hull)
        near = [p for p in self.hull if p.y >= top - 2e-3 * abs(top)]

        def simplicity(p: RegionPoint) -> int:
            if p.origin.startswith(("feed", "the feed")):
                return 0
            return 1 if ", PFR" not in p.origin else 2

        return min(near, key=lambda p: (simplicity(p), -p.y))

    def as_dict(self) -> dict[str, Any]:
        def points(items: list[RegionPoint]) -> list[dict[str, Any]]:
            return [{"x": p.x, "y": p.y, "origin": p.origin} for p in items]

        best = self.best()
        return {
            "key": self.key,
            "product": self.product,
            "temperature_K": self.temperature,
            "pressure_kPa": self.pressure,
            "axes": {
                "x": f"F_{self.key} / F_{self.key},0",
                "y": f"F_{self.product} / F_{self.key},0",
            },
            "best": points([best])[0] if best else None,
            "hull": points(self.hull),
            "pfr": points(self.pfr),
            "cstr": points(self.cstr),
            "cstr_pfr": [points(path) for path in self.cstr_pfr],
            "notes": self.notes,
        }


def _hull(points: list[RegionPoint]) -> list[RegionPoint]:
    """The convex hull (Andrew's monotone chain), counter-clockwise, without collinear points."""
    pts = sorted(points, key=lambda p: (p.x, p.y))
    if len(pts) <= 2:
        return pts

    def cross(o: RegionPoint, a: RegionPoint, b: RegionPoint) -> float:
        return (a.x - o.x) * (b.y - o.y) - (a.y - o.y) * (b.x - o.x)

    lower: list[RegionPoint] = []
    for p in pts:
        while len(lower) >= 2 and cross(lower[-2], lower[-1], p) <= 1e-15:
            lower.pop()
        lower.append(p)
    upper: list[RegionPoint] = []
    for p in reversed(pts):
        while len(upper) >= 2 and cross(upper[-2], upper[-1], p) <= 1e-15:
            upper.pop()
        upper.append(p)
    return lower[:-1] + upper[:-1]


def region(
    reactions: list[Any],
    feed: Mapping[str, float],
    temperature: float,
    pressure: float,
    key: str,
    product: str,
    data: Mapping[str, Any],
    liquid: Any = None,
    catalyst_loading: float | None = None,
) -> AttainableRegion:
    """The candidate attainable region of *feed* (kmol/h) through *reactions* (see the module
    docstring). Raises ChoiceError naming what is missing."""
    from chemeascode.domains.process.schema import Tank

    names = list(dict.fromkeys([*feed, *(n for r in reactions for n in r.stoichiometry)]))
    try:
        mix = _mixture(reactions, names, data, liquid, {}, catalyst_loading)
    except TankError as failure:
        raise ChoiceError(str(failure)) from failure
    if feed.get(key, 0.0) <= 0:
        raise ChoiceError(f"the key {key} is not fed")
    if product == key or not any(r.stoichiometry.get(product, 0) > 0 for r in reactions):
        raise ChoiceError(f"{product} is formed by none of the reactions")
    nu = mix.nu()
    m = len(reactions)
    ki, pi = names.index(key), names.index(product)
    f0 = [feed.get(n, 0.0) / 3600.0 for n in names]
    q0 = mix.volume_flow(dict(zip(names, f0, strict=True)), temperature, pressure)
    try:
        mult = mix.multipliers(1.0)
        r0 = mix.rates(f0, temperature, pressure)
    except ValueError as failure:
        raise ChoiceError(str(failure)) from failure
    consumption = -sum(nu[ki][j] * mult[j] * r0[j] for j in range(m))
    if consumption <= 0:
        raise ChoiceError(f"the feed does not convert {key}")
    t_char = (f0[ki] / q0) / consumption
    # the space times of the reactor-choice curves: 1/100 to 1000 times the characteristic time
    taus = [t_char * 10 ** (-2 + 5 * k / (POINTS - 1)) for k in range(POINTS)]
    result = AttainableRegion(key, product, temperature, pressure)
    result.notes.append(
        "a candidate region (PFR, CSTR, CSTR then PFR, and mixing), isothermal at the inlet; "
        "not proven complete"
    )
    if any(not r.rate.covers(temperature) for r in reactions):
        result.notes.append(f"{temperature:.6g} K is outside a rate law's temperature range")
    budget = [MAX_STEPS]

    def point(f: list[float], origin: str) -> RegionPoint:
        # y as the reactor choice's yield: the product formed per kmol of the key fed
        return RegionPoint(f[ki] / f0[ki], (f[pi] - f0[pi]) / f0[ki], origin)

    def derivatives(state: list[float]) -> list[float]:
        rates = mix.rates(state[:-2], temperature, pressure)
        return [
            *(sum(nu[i][j] * mult[j] * rates[j] for j in range(m)) for i in range(len(names))),
            0.0,
            0.0,
        ]

    def plug_flow(start: list[float], label: str) -> list[RegionPoint]:
        """The PFR from *start* (kmol/s), recorded at each of *taus* (on the feed's flow)."""
        state = [*start, temperature, pressure]
        path = [point(start, label + " (no volume)")]
        volume, h = 0.0, taus[0] * q0 / 10
        for tau in taus:
            target = tau * q0
            while volume < target * (1 - 1e-12):
                if budget[0] <= 0:
                    note = f"the plug flows stopped after {MAX_STEPS} steps (a stiff network)"
                    if note not in result.notes:
                        result.notes.append(note)
                    return path  # no point at a space time the integration did not reach
                budget[0] -= 1
                step = min(h, target - volume)
                new, error = _dopri_step(derivatives, state, step)
                scale = [
                    max(abs(a), abs(b), 1e-12 * f0[ki])
                    for a, b in zip(state[:-2], new[:-2], strict=True)
                ] + [1.0, 1.0]
                err = max(abs(e) / s for e, s in zip(error, scale, strict=True))
                if err > 1e-8 and step > 1e-14 * target:
                    h = step * max(0.2, 0.9 * (1e-8 / err) ** 0.2)
                    continue
                state = [max(v, 0.0) if i < len(names) else v for i, v in enumerate(new)]
                volume += step
                h = step * 2
            path.append(point(state[:-2], f"{label}, PFR tau {tau:.4g} s"))
        return path

    try:
        result.pfr = plug_flow(f0, "feed")
        cstr_states: list[tuple[float, list[float]]] = []
        failed: list[str] = []
        for tau in taus:
            tank = Tank(
                residence_time=tau,
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
            cstr_states.append((tau, f))
            result.cstr.append(point(f, f"CSTR tau {tau:.4g} s"))
        if failed:
            result.notes.append(
                f"CSTR: {len(failed)} space time(s) not solved, e.g. {failed[0]}: the region may "
                "miss part of the tank locus"
            )
        for tau, f in cstr_states[::EVERY]:
            result.cstr_pfr.append(plug_flow(f, f"CSTR tau {tau:.4g} s"))
    except ValueError as failure:
        raise ChoiceError(f"along a reactor: {failure}") from failure
    every = [point(f0, "the feed"), *result.pfr, *result.cstr]
    every += [p for path in result.cstr_pfr for p in path]
    result.hull = _hull(every)
    return result


def node_region(
    root: Any, node: str, product: str, key: str | None = None, case: str | None = None
) -> AttainableRegion:
    """:func:`region` for reactor *node* of the plant at *root*, as
    :func:`.reactor_choice.node_choice` reads it."""
    from chemeascode.domains.process.reactor_choice import _node_inputs

    reactions, moles, kelvin, kpa, key, data, liquid, loading = _node_inputs(root, node, key, case)
    return region(reactions, moles, kelvin, kpa, key, product, data, liquid, loading)


# -- the plot -----------------------------------------------------------------------------------


def region_svg(found: AttainableRegion) -> str:
    """The region as SVG: the hull shaded, the PFR and CSTR paths, the CSTR-then-PFR paths
    thin, the best vertex marked (tooltip: how to reach it). Light and dark."""
    from chemeascode.domains.process.reactor_choice import _SERIES

    w, h, left, top, bottom, right = 620, 360, 60, 34, 46, 150
    pw, ph = w - left - right, h - top - bottom
    every = [*found.hull, *found.pfr, *found.cstr]
    y_max = max([p.y for p in every] + [1e-9])
    y_top = max(0.2, 0.2 * -(-y_max // 0.2))

    def px(x: float) -> float:
        return left + pw * min(max(x, 0.0), 1.0)

    def py(y: float) -> float:
        return top + ph * (1 - min(max(y, 0.0), y_top) / y_top)

    def path(points: list[RegionPoint]) -> str:
        return " ".join(
            f"{'M' if i == 0 else 'L'}{px(p.x):.1f},{py(p.y):.1f}" for i, p in enumerate(points)
        )

    (l0, d0), (l1, d1), (l2, d2) = _SERIES
    style = f"""<style>
  svg {{ background: #fcfcfb; font-family: system-ui, sans-serif; }}
  .title {{ font-size: 13px; font-weight: 600; fill: #0b0b0b; }}
  .label, .legend {{ font-size: 11px; fill: #52514e; }}
  .tick {{ font-size: 10px; fill: #52514e; }}
  .grid {{ stroke: #e5e4e0; stroke-width: 1; }}
  .region {{ fill: {l0}; fill-opacity: 0.12; stroke: {l0}; stroke-width: 1;
             stroke-dasharray: 4 3; }}
  .pfr {{ fill: none; stroke: {l0}; stroke-width: 2; }}
  .cstr {{ fill: none; stroke: {l1}; stroke-width: 2; }}
  .series {{ fill: none; stroke: {l2}; stroke-width: 1; }}
  .mark {{ fill: #0b0b0b; stroke: #fcfcfb; stroke-width: 2; }}
  @media (prefers-color-scheme: dark) {{
    svg {{ background: #1a1a19; }}
    .title {{ fill: #f0efec; }}
    .label, .legend, .tick {{ fill: #c3c2b7; }}
    .grid {{ stroke: #33332f; }}
    .region {{ fill: {d0}; stroke: {d0}; }}
    .pfr {{ stroke: {d0}; }}
    .cstr {{ stroke: {d1}; }}
    .series {{ stroke: {d2}; }}
    .mark {{ fill: #f0efec; stroke: #1a1a19; }}
  }}
</style>"""
    body = [
        f'<text class="title" x="{left}" y="{top - 14}">Attainable region of '
        f"{found.product} (candidate)</text>"
    ]
    for k in range(6):  # five intervals of the yield axis
        v = y_top * k / 5
        body.append(
            f'<line class="grid" x1="{left}" x2="{left + pw}" y1="{py(v):.1f}" y2="{py(v):.1f}"/>'
        )
        body.append(
            f'<text class="tick" x="{left - 6}" y="{py(v) + 4:.1f}" '
            f'text-anchor="end">{v:.2g}</text>'
        )
    for k in range(6):
        body.append(
            f'<text class="tick" x="{px(k / 5):.1f}" y="{top + ph + 16}" '
            f'text-anchor="middle">{k / 5:.1f}</text>'
        )
    body.append(
        f'<text class="label" x="{left + pw / 2}" y="{h - 8}" text-anchor="middle">'
        f"F {found.key} / F {found.key},0</text>"
    )
    body.append(
        f'<text class="label" transform="translate({left - 42},{top + ph / 2}) '
        f'rotate(-90)" text-anchor="middle">F {found.product} / F {found.key},0</text>'
    )
    if found.hull:
        body.append(
            f'<path class="region" d="{path(found.hull)} Z"><title>the candidate '
            "region: every point inside is reached by mixing</title></path>"
        )
    for series in found.cstr_pfr:
        body.append(f'<path class="series" d="{path(series)}"><title>CSTR then PFR</title></path>')
    body.append(f'<path class="pfr" d="{path(found.pfr)}"><title>PFR</title></path>')
    body.append(f'<path class="cstr" d="{path(found.cstr)}"><title>CSTR</title></path>')
    best = found.best()
    if best is not None:
        body.append(
            f'<circle class="mark" cx="{px(best.x):.1f}" cy="{py(best.y):.1f}" r="5">'
            f"<title>highest yield {best.y:.3f}: {best.origin}</title></circle>"
        )
    lx = left + pw + 20
    for k, (cls, name) in enumerate(
        (
            ("pfr", "PFR"),
            ("cstr", "CSTR"),
            ("series", "CSTR then PFR"),
            ("region", "region (mixing)"),
        )
    ):
        y = top + 8 + 18 * k
        body.append(f'<line class="{cls}" x1="{lx}" x2="{lx + 18}" y1="{y}" y2="{y}"/>')
        body.append(f'<text class="legend" x="{lx + 24}" y="{y + 4}">{name}</text>')
    return (
        f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 {w} {h}" width="{w}" '
        f'height="{h}" role="img"><title>Attainable region of {found.product} from '
        f"{found.key} (candidate)</title>\n{style}\n" + "\n".join(body) + "\n</svg>\n"
    )
