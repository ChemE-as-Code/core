"""SVG figures of electrolysis duties (:mod:`.electrolysis_duty`), hand-written like those of
the measured series: per duty the aligned time plots (current, voltage, pH with the stated
threshold, cumulative product, dosing; one quantity and one axis per panel, all on one time
axis) and the operating map (time to the threshold over water dissociation efficiency and
reservoir volume, a single-hue heat map) with the measured WDE points as markers, labelled
"measured", apart from the simulated cells and lines, and the measured WDE range shaded.

Simulated transients are lines; measured observations are markers. Light and dark
(``prefers-color-scheme``), tooltips (``<title>``) on the marks.
"""

from __future__ import annotations

import math
from html import escape

from chemeascode.domains.process.electrolysis_duty import (
    DutyReport,
    DutyResult,
    OperatingMapResult,
    operating_map,
)

_W = 720
_LEFT, _RIGHT, _TOP = 72, 24, 40
_PANEL, _GAP = 104, 22
#: sequential blue, light -> dark (the reference palette's steps 150 .. 700)
_RAMP = ("#b7d3f6", "#86b6ef", "#5598e7", "#2a78d6", "#1c5cab", "#104281", "#0d366b")
_STYLE = """<style>
  svg { background: #fcfcfb; font-family: system-ui, sans-serif; }
  .title { font-size: 13px; font-weight: 600; fill: #0b0b0b; }
  .label, .legend, .note { font-size: 11px; fill: #52514e; }
  .tick { font-size: 10px; fill: #52514e; }
  .grid { stroke: #e5e4e0; stroke-width: 1; }
  .axis { stroke: #a3a29b; stroke-width: 1; }
  .line { fill: none; stroke: #2a78d6; stroke-width: 2; stroke-linejoin: round; }
  .threshold { stroke: #52514e; stroke-width: 1.5; stroke-dasharray: 6 4; fill: none; }
  .event { stroke: #a3a29b; stroke-width: 1; stroke-dasharray: 2 3; }
  .outside { fill: #e5e4e0; opacity: 0.7; }
  .hit { fill: transparent; stroke: none; }
  .measured { fill: #eb6834; stroke: #fcfcfb; stroke-width: 2; }
  .duty { fill: none; stroke: #0b0b0b; stroke-width: 2; }
  .none { fill: #f0efec; }
  .cell { stroke: #fcfcfb; stroke-width: 1; }
  @media (prefers-color-scheme: dark) {
    svg { background: #1a1a19; }
    .title { fill: #f0efec; }
    .label, .legend, .tick, .note { fill: #c3c2b7; }
    .grid { stroke: #33332f; }
    .axis { stroke: #6e6d66; }
    .line { stroke: #3987e5; }
    .threshold { stroke: #c3c2b7; }
    .event { stroke: #6e6d66; }
    .outside { fill: #33332f; }
    .measured { fill: #d95926; stroke: #1a1a19; }
    .duty { stroke: #f0efec; }
    .none { fill: #383835; }
    .cell { stroke: #1a1a19; }
  }
</style>"""


def _ticks(lo: float, hi: float) -> list[float]:
    if hi <= lo:
        hi = lo + (abs(lo) or 1.0)
    raw = (hi - lo) / 5
    power = 10 ** math.floor(math.log10(raw))
    step = next(m * power for m in (1, 2, 2.5, 5, 10) if m * power >= raw)
    start = math.floor(lo / step + 1e-9) * step
    out = [round(start, 12)]
    while out[-1] < hi - step * 1e-6 or len(out) < 2:
        out.append(round(start + len(out) * step, 12))
    return out


def _svg(width: int, height: int, title: str, body: list[str]) -> str:
    return (
        f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 {width} {height}" '
        f'width="{width}" height="{height}" role="img"><title>{escape(title)}</title>\n'
        + _STYLE
        + "\n"
        + "\n".join(body)
        + "\n</svg>\n"
    )


def time_plot(duty: DutyResult) -> str:
    """The aligned time plots of one duty (simulated: lines)."""
    s = duty.series
    t = s["t_h"]
    t_end = max(t[-1] if t else 0.0, 1e-9)
    if duty.ended == "measured-range-exit" and duty.horizon_h:
        t_end = max(t_end, duty.horizon_h)  # show the scheduled time that is not simulated
    panels: list[tuple[str, list[float | None]]] = [
        ("current per cell / A", s["current_a"]),
        ("cell voltage / V", s["voltage_v"]),
        ("anolyte pH (model) / -", s["ph"]),
        (
            f"{duty.product} delivered / kg"
            if any(v is not None for v in s["product_kg"])
            else f"{duty.product} delivered / mol",
            s["product_kg"] if any(v is not None for v in s["product_kg"]) else s["product_mol"],
        ),
        ("hydroxide dosed / mol", s["dosing_mol"]),
    ]
    width = _W - _LEFT - _RIGHT
    height = _TOP + len(panels) * (_PANEL + _GAP) + 40
    xt = _ticks(0.0, t_end)

    def px(x: float) -> float:
        return _LEFT + width * (x - xt[0]) / (xt[-1] - xt[0])

    body = [
        f'<text class="title" x="{_LEFT}" y="18">Duty {escape(duty.id)}: simulated transient '
        f"(cell {escape(duty.cell)}, {duty.performance})</text>",
        f'<text class="note" x="{_LEFT}" y="32">lines: simulated; dashed: the stated pH '
        f"threshold {duty.threshold_ph:g} (a design criterion); dotted: events</text>",
    ]
    exit_h = duty.first_exit_h
    switches = [e for e in duty.events if e["kind"] in ("dosing-on", "dosing-off")]
    marked = [e for e in duty.events if e not in switches or len(switches) <= 10]
    for k, (label, values) in enumerate(panels):
        top = _TOP + k * (_PANEL + _GAP) + 8
        pts = [(x, v) for x, v in zip(t, values, strict=True) if v is not None]
        ys = [v for _, v in pts] or [0.0]
        lo, hi = min(ys), max(ys)
        if k == 2:
            lo, hi = min(lo, duty.threshold_ph), max(hi, duty.threshold_ph)
        elif k in (0, 3, 4):
            lo = min(lo, 0.0)
        if hi - lo < 1e-12:
            hi = lo + (abs(lo) * 0.1 or 1.0)
        yt = _ticks(lo, hi)

        def py(y: float, top: float = top, yt: list[float] = yt) -> float:
            return top + _PANEL * (1 - (y - yt[0]) / (yt[-1] - yt[0]))

        if exit_h is not None and exit_h < xt[-1]:
            body.append(
                f'<rect class="outside" x="{px(exit_h):.1f}" y="{top}" '
                f'width="{px(xt[-1]) - px(exit_h):.1f}" height="{_PANEL}">'
                "<title>outside the measured range: not simulated</title></rect>"
            )
        for v in yt:
            body.append(
                f'<line class="grid" x1="{_LEFT}" x2="{_LEFT + width}" y1="{py(v):.1f}" '
                f'y2="{py(v):.1f}"/>'
            )
            body.append(
                f'<text class="tick" x="{_LEFT - 6}" y="{py(v) + 3:.1f}" '
                f'text-anchor="end">{v:g}</text>'
            )
        body.append(
            f'<line class="axis" x1="{_LEFT}" x2="{_LEFT + width}" y1="{top + _PANEL}" '
            f'y2="{top + _PANEL}"/>'
        )
        body.append(f'<text class="label" x="{_LEFT}" y="{top - 3}">{escape(label)}</text>')
        if k == 2:
            y = py(duty.threshold_ph)
            body.append(
                f'<path class="threshold" d="M{_LEFT},{y:.1f} H{_LEFT + width}"/>'
                f'<text class="note" x="{_LEFT + width - 4}" y="{y - 4:.1f}" text-anchor="end">'
                f"stated threshold pH {duty.threshold_ph:g}</text>"
            )
        if len(pts) > 1:
            d = " ".join(
                f"{'M' if i == 0 else 'L'}{px(x):.1f},{py(v):.1f}" for i, (x, v) in enumerate(pts)
            )
            body.append(f'<path class="line" d="{d}"/>')
        step = max(1, len(pts) // 60)
        for x, v in pts[::step]:
            body.append(
                f'<circle class="hit" cx="{px(x):.1f}" cy="{py(v):.1f}" r="5">'
                f"<title>{escape(label)}: {v:.5g} at {x:.5g} h (simulated)</title></circle>"
            )
        for event in marked:
            x = px(min(event["t_h"], xt[-1]))
            body.append(
                f'<line class="event" x1="{x:.1f}" x2="{x:.1f}" y1="{top}" '
                f'y2="{top + _PANEL}"><title>{escape(event["kind"])} at {event["t_h"]:.5g} h'
                "</title></line>"
            )
    bottom = _TOP + len(panels) * (_PANEL + _GAP) - _GAP + 8
    for v in xt:
        body.append(
            f'<text class="tick" x="{px(v):.1f}" y="{bottom + 14}" text-anchor="middle">'
            f"{v:g}</text>"
        )
    body.append(
        f'<text class="label" x="{_LEFT + width / 2:.1f}" y="{bottom + 30}" '
        'text-anchor="middle">time / h</text>'
    )
    return _svg(_W, height, f"Duty {duty.id}: simulated transient", body)


def map_plot(result: OperatingMapResult) -> str:
    """The operating map: time to the stated threshold (simulated, a heat map of seven
    log-spaced classes), the measured WDE points (markers) and the measured WDE range."""
    width, height = _W - _LEFT - 170, 320
    top = _TOP + 12
    columns, rows = len(result.wde), len(result.volume_l)
    w_lo, w_hi = result.wde[0], result.wde[-1]
    v_lo, v_hi = result.volume_l[0], result.volume_l[-1]
    found = [t for line in result.time_h for t in line if t is not None and t > 0]
    t_lo, t_hi = (min(found), max(found)) if found else (1.0, 10.0)
    if t_hi <= t_lo:
        t_hi = t_lo * 10
    edges = [t_lo * (t_hi / t_lo) ** (i / len(_RAMP)) for i in range(len(_RAMP) + 1)]

    def px(w: float) -> float:
        return _LEFT + width * (w - w_lo) / (w_hi - w_lo)

    def py(v: float) -> float:
        return top + height * (1 - math.log(v / v_lo) / math.log(v_hi / v_lo))

    def cls(t: float) -> int:
        return min(max(bisect_index(edges, t), 0), len(_RAMP) - 1)

    body = [
        f'<text class="title" x="{_LEFT}" y="18">Duty {escape(result.duty)}: time to the stated '
        f"pH threshold {result.threshold_ph:g} (simulated)</text>",
        f'<text class="note" x="{_LEFT}" y="32">cells: simulated at a constant WDE; markers: '
        "measured WDE; grey: not reached within the horizon "
        f"({result.horizon_h:g} h)</text>",
    ]
    cw = width / columns
    ch = height / rows
    for r, line in enumerate(result.time_h):
        for c, t in enumerate(line):
            x = _LEFT + c * cw
            y = top + height - (r + 1) * ch
            if t is None:
                fill = ' class="cell none"'
                text = "not reached within the horizon"
            else:
                fill = f' class="cell" fill="{_RAMP[cls(t)]}"'
                text = f"{t:.4g} h"
            body.append(
                f'<rect{fill} x="{x:.1f}" y="{y:.1f}" width="{cw:.1f}" height="{ch:.1f}">'
                f"<title>WDE {result.wde[c]:.4g}, {result.volume_l[r]:.4g} L: {text} "
                "(simulated)</title></rect>"
            )
    span = result.measured_wde_range
    if span is not None:
        for a, b in ((w_lo, span[0]), (span[1], w_hi)):
            if b > a:
                lo_x, hi_x = px(max(a, w_lo)), px(min(b, w_hi))
                body.append(
                    f'<rect class="outside" x="{lo_x:.1f}" y="{top}" width="{hi_x - lo_x:.1f}" '
                    f'height="{height}"><title>outside the measured WDE range '
                    f"{span[0]:.4g}-{span[1]:.4g}</title></rect>"
                )
    for v in _ticks(w_lo, w_hi):
        if w_lo - 1e-9 <= v <= w_hi + 1e-9:
            body.append(
                f'<text class="tick" x="{px(v):.1f}" y="{top + height + 14}" '
                f'text-anchor="middle">{v:g}</text>'
            )
    decade = 10 ** math.floor(math.log10(v_lo))
    while decade <= v_hi * 1.0001:
        for m in (1, 2, 5):
            v = m * decade
            if v_lo * 0.9999 <= v <= v_hi * 1.0001:
                body.append(
                    f'<text class="tick" x="{_LEFT - 6}" y="{py(v) + 3:.1f}" '
                    f'text-anchor="end">{v:g}</text>'
                )
        decade *= 10
    body.append(
        f'<text class="label" x="{_LEFT + width / 2:.1f}" y="{top + height + 32}" '
        'text-anchor="middle">water dissociation efficiency / -</text>'
    )
    body.append(
        f'<text class="label" transform="translate({_LEFT - 50},{top + height / 2:.1f}) '
        'rotate(-90)" text-anchor="middle">reservoir volume / L (log)</text>'
    )
    v = result.duty_wde
    if v is not None and w_lo <= v <= w_hi:
        body.append(
            f'<circle class="duty" cx="{px(v):.1f}" cy="{py(result.duty_volume_l):.1f}" r="7">'
            f"<title>this duty (simulated): WDE {v:.4g}, {result.duty_volume_l:.4g} L"
            "</title></circle>"
        )
    for j, wde, sd, pid in result.measured_wde:
        if w_lo <= wde <= w_hi and v_lo <= result.duty_volume_l <= v_hi:
            x, y = px(wde), py(result.duty_volume_l)
            spread = f" +- {sd:.3g}" if sd else ""
            body.append(
                f'<path class="measured" d="M{x:.1f},{y - 6:.1f} L{x + 6:.1f},{y:.1f} '
                f'L{x:.1f},{y + 6:.1f} L{x - 6:.1f},{y:.1f} Z"><title>measured WDE '
                f"{wde:.4g}{spread} at {j:g} A/m2 (point {escape(pid)})</title></path>"
            )
    lx = _LEFT + width + 20
    body.append(f'<text class="legend" x="{lx}" y="{top + 4}">time to threshold / h</text>')
    for i, colour in enumerate(_RAMP):
        y = top + 14 + i * 18
        body.append(f'<rect fill="{colour}" x="{lx}" y="{y}" width="16" height="14"/>')
        body.append(
            f'<text class="legend" x="{lx + 22}" y="{y + 11}">'
            f"{_num(edges[i])}-{_num(edges[i + 1])}</text>"
        )
    y = top + 14 + len(_RAMP) * 18 + 8
    body.append(f'<rect class="none" x="{lx}" y="{y}" width="16" height="14"/>')
    body.append(f'<text class="legend" x="{lx + 22}" y="{y + 11}">not reached</text>')
    y += 26
    body.append(
        f'<path class="measured" d="M{lx + 8},{y - 6} L{lx + 14},{y} L{lx + 8},{y + 6} '
        f'L{lx + 2},{y} Z"/><text class="legend" x="{lx + 22}" y="{y + 4}">measured WDE</text>'
    )
    y += 22
    body.append(
        f'<circle class="duty" cx="{lx + 8}" cy="{y}" r="6"/>'
        f'<text class="legend" x="{lx + 22}" y="{y + 4}">this duty (simulated)</text>'
    )
    y += 22
    body.append(
        f'<rect class="outside" x="{lx}" y="{y - 7}" width="16" height="14"/>'
        f'<text class="legend" x="{lx + 22}" y="{y + 4}">outside measured WDE</text>'
    )
    return _svg(_W, top + height + 48, f"Duty {result.duty}: operating map", body)


def _num(v: float) -> str:
    return f"{v:,.0f}" if v >= 1000 else f"{v:.3g}"


def bisect_index(edges: list[float], t: float) -> int:
    """The class of *t* between the *edges* (0 below the second edge)."""
    k = 0
    while k + 1 < len(edges) - 1 and t >= edges[k + 1]:
        k += 1
    return k


def duty_plots(report: DutyReport, maps: bool = True) -> dict[str, str]:
    """SVG figures by file name: ``duty-<id>.svg`` (aligned time plots) for every duty that
    was integrated and, with *maps*, ``map-<id>.svg`` (the operating map)."""
    figures: dict[str, str] = {}
    for duty in report.duties:
        if duty.refused or not duty.series:
            continue
        figures[f"duty-{duty.id}.svg"] = time_plot(duty)
        if maps and duty._inputs is not None:
            spec, cell = duty._inputs
            figures[f"map-{duty.id}.svg"] = map_plot(operating_map(spec, cell))
    return figures
