"""The PFD's sheet: an ISO A-size frame with zone markers, the title block and the stream table.

The PFD is drawn on the smallest sheet, landscape, that holds the flow diagram and the stream
table: ISO 216 A3 to A0 or an ISO 5457 elongated one (A3x3 to A0x3), the smallest area first;
beyond those, a sheet A0 high and as wide as the drawing. The frame follows ISO 5457
(20 mm margin on the left for filing, 10 mm elsewhere); the title block sits in the bottom right
corner (ISO 7200 fields: title, drawing number, case, sheet, generator). The stream table lists
the material streams with phase, temperature, pressure, mass flow and the mass flow of the main
components, and the energy streams with their duty, from the default case of
``process/flowsheet.yaml`` (stale values are left blank; assumed values are marked ``*``).

Everything is drawn as DEXPI graphics (``Static`` polylines and ``Label`` texts) in sheet
millimetres, Y down.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from typing import Any

import pydexpi.pydexpi_classes.pydexpi_classes as C

#: ISO 216 sheets and the ISO 5457 elongated ones, landscape (width, height) in mm, by area.
ISO_SHEETS = (
    ("A3", 420.0, 297.0),
    ("A2", 594.0, 420.0),
    ("A3x3", 891.0, 420.0),
    ("A1", 841.0, 594.0),
    ("A3x4", 1189.0, 420.0),
    ("A2x3", 1261.0, 594.0),
    ("A0", 1189.0, 841.0),
    ("A2x4", 1682.0, 594.0),
    ("A1x3", 1783.0, 841.0),
    ("A0x2", 1682.0, 1189.0),
    ("A1x4", 2378.0, 841.0),
    ("A0x3", 2523.0, 1189.0),
)
#: ISO 5457 frame margins: left (filing), top, right, bottom.
MARGIN_LEFT, MARGIN = 20.0, 10.0
#: Clearance between the frame and the drawing, and between the drawing and the table.
INSET, TABLE_GAP = 10.0, 12.0
#: The title block (bottom right, inside the frame).
TITLE_W, TITLE_H = 180.0, 36.0
#: Stream table geometry.
ROW_H, HEAD_W, MIN_COL_W, TEXT = 4.2, 44.0, 15.0, 2.0
#: The most component rows the table shows (the largest by total flow).
MAX_COMPONENTS = 14

_BLACK = C.Color(r=0, g=0, b=0)
_GREY = C.Color(r=110, g=110, b=110)
_FRAME = C.Stroke(color=_BLACK, dashStyle=C.DashStyle.SOLID, width=0.5)
_RULE = C.Stroke(color=_BLACK, dashStyle=C.DashStyle.SOLID, width=0.25)
_FINE = C.Stroke(color=_GREY, dashStyle=C.DashStyle.SOLID, width=0.18)


def text_width(text: str, size: float) -> float:
    return len(text) * size * 0.56


def _text(id_: str, text: str, x: float, y: float, size: float, align: str, grey: bool = False):
    return C.Text(
        id=id_,
        text=text,
        position=C.Point(x=round(x, 3), y=round(y, 3)),
        alignment=getattr(C.TextAlignment, align),
        color=_GREY if grey else _BLACK,
        font="Arial",
        size=size,
        rotation=0.0,
    )


def _line(id_: str, points: list[tuple[float, float]], stroke: Any) -> Any:
    return C.PolyLine(
        id=id_, points=[C.Point(x=round(x, 3), y=round(y, 3)) for x, y in points], stroke=stroke
    )


# -- the stream table -----------------------------------------------------------------------------


@dataclass
class Table:
    """The stream table's cells: a header column and one column per stream, in bands."""

    heads: list[str] = field(default_factory=list)
    #: (stream id, cells top to bottom, matching *heads* after the id row)
    columns: list[tuple[str, list[str]]] = field(default_factory=list)
    note: str = ""
    #: the caption of the id row
    title: str = "Stream"
    #: the energy streams' duties, a table of their own below this one
    duties: Table | None = None

    @property
    def rows(self) -> int:
        return len(self.heads) + 1

    def col_width(self) -> float:
        texts = [c for _, cells in self.columns for c in cells] + [s for s, _ in self.columns]
        return max(MIN_COL_W, max((text_width(t, TEXT) + 3.0 for t in texts), default=0.0))

    def head_width(self) -> float:
        return max(HEAD_W, max((text_width(h, TEXT) + 4.0 for h in self.heads), default=0.0))

    def bands(self, width: float) -> list[list[tuple[str, list[str]]]]:
        """The columns split into bands no wider than *width*."""
        per = max(1, int((width - self.head_width()) // self.col_width()))
        return [self.columns[i : i + per] for i in range(0, len(self.columns), per)]

    def size(self, width: float) -> tuple[float, float]:
        """(width, height) of the table drawn in bands no wider than *width*."""
        w = h = 0.0
        if self.columns:
            bands = self.bands(width)
            w = self.head_width() + max(len(b) for b in bands) * self.col_width()
            h = len(bands) * self.rows * ROW_H + (len(bands) - 1) * 4.0
        if self.duties is not None and self.duties.columns:
            dw, dh = self.duties.size(width)
            w, h = max(w, dw), h + (4.0 if h else 0.0) + dh
        return w, h + (5.0 if self.note and h else 0.0)


def _num(value: float) -> str:
    a = abs(value)
    if a == 0:
        return "0"
    if a >= 1000:
        return f"{value:,.0f}".replace(",", " ")
    if a >= 100:
        return f"{value:.0f}"
    if a >= 10:
        return f"{value:.1f}"
    if a >= 1:
        return f"{value:.2f}"
    if a >= 0.01:
        return f"{value:.3f}"
    return "<0.01"


def _mark(q: Any) -> str:
    return "*" if getattr(q, "provenance", None) == "assumed" else ""


def stream_table(process: Any, material: list[str], energy: list[str], case: str) -> Table:
    """The table of *material* and *energy* streams (ids, flowsheet order) in *case*."""
    from chemeascode.domains.process.model import stream_flows
    from chemeascode.domains.process.props import stale
    from chemeascode.domains.process.schema import DUTY_UNITS, PRESSURE_UNITS

    fs = process.flowsheet
    by_id = {s.id: s for s in fs.streams}
    flows: dict[str, Any] = {}
    totals: dict[str, float] = {}
    for sid in material:
        stream = by_id[sid]
        if "flow" in stale(process, stream, case) or "composition" in stale(process, stream, case):
            continue
        f = stream_flows(process, stream, case)
        flows[sid] = f
        for name, value in (f.components or {}).items():
            totals[name] = totals.get(name, 0.0) + value
    shown = [n for n, v in sorted(totals.items(), key=lambda kv: -kv[1]) if v > 0]
    hidden = len(shown) > MAX_COMPONENTS
    shown = shown[:MAX_COMPONENTS]
    gauge = any(
        PRESSURE_UNITS.get(
            (by_id[s].state.get(case).pressure.unit or fs.units.pressure), (1, "absolute")
        )[1]
        != "absolute"
        for s in material
        if by_id[s].state.get(case) and by_id[s].state.get(case).pressure
    )
    names = process.components()
    heads = [
        "Phase (vapour fraction)",
        "Temperature, °C",
        f"Pressure, bar{'' if gauge else '(a)'}",
        "Mass flow, kg/h",
        *(f"  {(names[n].name if n in names and names[n].name else n)[:24]}, kg/h" for n in shown),
    ]
    table = Table(heads=heads)
    for sid in material:
        stream = by_id[sid]
        state = stream.state.get(case)
        old = set(stale(process, stream, case)) if state else set()
        cells: list[str] = []
        phase = state.phase if state and "phase" not in old else None
        if phase is None:
            cells.append("")
        else:
            short = {"vapor": "V", "liquid": "L", "two-phase": "V/L"}[phase.value]
            vf = (
                f" ({phase.vapor_fraction:.2f})"
                if phase.value == "two-phase" and (phase.vapor_fraction is not None)
                else ""
            )
            cells.append(short + vf)
        t = state.temperature if state and "temperature" not in old else None
        if t is None:
            cells.append("")
        else:
            unit = t.unit or fs.units.temperature
            cells.append(_num(t.value - 273.15 if unit == "K" else t.value) + _mark(t))
        p = state.pressure if state and "pressure" not in old else None
        if p is None:
            cells.append("")
        else:
            factor, kind = PRESSURE_UNITS.get(p.unit or fs.units.pressure, (1.0, "absolute"))
            bar = p.value * factor / 100.0
            if gauge and kind == "absolute":
                bar -= 1.01325
            cells.append(_num(bar) + _mark(p))
        f = flows.get(sid)
        flow_mark = _mark(state.flow) if state and state.flow else ""
        cells.append(_num(f.total) + flow_mark if f and f.total is not None else "")
        for name in shown:
            value = (f.components or {}).get(name) if f else None
            cells.append(
                _num(value) if value else ("" if f is None or f.components is None else "-")
            )
        table.columns.append((sid, cells))
    duties = Table(heads=["Duty, kW"], title="Energy stream")
    for sid in energy:
        stream = by_id[sid]
        state = stream.state.get(case)
        if state is None or state.duty is None or "duty" in stale(process, stream, case):
            continue
        kw = state.duty.value * DUTY_UNITS.get(state.duty.unit or fs.units.duty, 1.0)
        duties.columns.append((sid, [f"{_num(kw)}{_mark(state.duty)}"]))
    table.duties = duties
    notes = [f"Case {case}, from process/flowsheet.yaml (cheme process streams)"]
    notes.append("* assumed (estimate); blank: not given or stale")
    if hidden:
        notes.append(f"the {MAX_COMPONENTS} largest components shown")
    table.note = "; ".join(notes)
    return table


def draw_table(table: Table, x0: float, y0: float, width: float) -> list[Any]:
    """The table's lines and texts (a ``Static`` and a ``Label``), top left at (x0, y0), the
    duties below the streams."""
    lines: list[Any] = []
    texts: list[Any] = []
    y = _draw_bands(table, x0, y0, width, "StreamTable", lines, texts)
    if table.duties is not None and table.duties.columns:
        y = _draw_bands(table.duties, x0, y, width, "DutyTable", lines, texts)
    if table.note:
        texts.append(_text("StreamTable_note", table.note, x0, y + 0.5, 1.8, "LEFTTOP", grey=True))
    return [
        C.Static(id="Drawing_StreamTable_Static", elements=lines),
        C.Label(id="Drawing_StreamTable_Label", elements=texts),
    ]


def _draw_bands(
    table: Table, x0: float, y0: float, width: float, key: str, lines: list, texts: list
) -> float:
    """Draw *table*'s bands from (x0, y0) into *lines* and *texts*; the y below the last."""
    hw, cw = table.head_width(), table.col_width()
    y = y0
    for b, band in enumerate(table.bands(width) if table.columns else []):
        rows = table.rows
        x1 = x0 + hw + len(band) * cw
        y1 = y + rows * ROW_H
        lines.append(
            _line(f"{key}_{b}_frame", [(x0, y), (x1, y), (x1, y1), (x0, y1), (x0, y)], _RULE)
        )
        lines.append(_line(f"{key}_{b}_head", [(x0, y + ROW_H), (x1, y + ROW_H)], _RULE))
        for r in range(2, rows):
            lines.append(
                _line(f"{key}_{b}_row_{r}", [(x0, y + r * ROW_H), (x1, y + r * ROW_H)], _FINE)
            )
        lines.append(_line(f"{key}_{b}_col_0", [(x0 + hw, y), (x0 + hw, y1)], _RULE))
        for c in range(1, len(band)):
            cx = x0 + hw + c * cw
            lines.append(_line(f"{key}_{b}_col_{c}", [(cx, y), (cx, y1)], _FINE))
        texts.append(
            _text(f"{key}_{b}_title", table.title, x0 + 1.5, y + ROW_H / 2, TEXT, "LEFTCENTER")
        )
        for r, head in enumerate(table.heads, 1):
            texts.append(
                _text(
                    f"{key}_{b}_h{r}",
                    head.strip(),
                    x0 + (4.0 if head.startswith(" ") else 1.5),
                    y + (r + 0.5) * ROW_H,
                    TEXT,
                    "LEFTCENTER",
                )
            )
        for c, (sid, cells) in enumerate(band):
            cx = x0 + hw + (c + 0.5) * cw
            texts.append(_text(f"{key}_{sid}", sid, cx, y + ROW_H / 2, TEXT, "CENTERCENTER"))
            for r, cell in enumerate(cells, 1):
                if cell:
                    texts.append(
                        _text(
                            f"{key}_{sid}_{r}",
                            cell,
                            cx,
                            y + (r + 0.5) * ROW_H,
                            TEXT,
                            "CENTERCENTER",
                        )
                    )
        y = y1 + 4.0
    return y


# -- the sheet ------------------------------------------------------------------------------------


@dataclass
class Sheet:
    """The chosen sheet and where the drawing, the table and the title block go."""

    name: str
    width: float
    height: float
    #: The drawing's translation (dx, dy) and the stream table's top left.
    dx: float = 0.0
    dy: float = 0.0
    table_at: tuple[float, float] = (0.0, 0.0)
    table_width: float = 0.0


def choose_sheet(
    bounds: tuple[float, float, float, float], table: Table, fixed: bool = False
) -> Sheet:
    """The smallest ISO sheet holding the drawing *bounds* and the *table*: beside the title
    block where it fits, else above it. With *fixed* (a pinned layout) the drawing is not
    moved, so the sheet also reaches its far corner."""
    x0, y0, x1, y1 = bounds
    dw, dh = x1 - x0, y1 - y0
    left, top = MARGIN_LEFT + INSET, MARGIN + INSET
    right, bottom = MARGIN + INSET, MARGIN + 5.0

    def fit(width: float, height: float) -> Sheet | None:
        inner_w = width - left - right
        if dw > inner_w + 1e-6:
            return None
        if fixed and (x1 > width - right or y0 < top):
            return None
        beside_w = inner_w - TITLE_W - 10.0
        drawing_top = y0 if fixed else top
        for beside in (True, False):
            limit = beside_w if beside else inner_w
            if limit <= HEAD_W + MIN_COL_W and table.columns:
                continue
            tw, th = table.size(limit)
            band = max(th, TITLE_H) if beside else th + (8.0 if th else 0.0) + TITLE_H
            avail = height - bottom - band - TABLE_GAP - drawing_top
            if (y1 - y0 if not fixed else y1 - drawing_top) > avail + 1e-6:
                continue
            dx = 0.0 if fixed else round(left + (inner_w - dw) / 2 - x0, 1)
            dy = 0.0 if fixed else round(top + max(0.0, (avail - dh) / 2) - y0, 1)
            # the table's bottom on the title block's (beside it) or above the title block
            table_y = height - bottom - (th if beside else th + 8.0 + TITLE_H)
            return Sheet("", width, height, dx, dy, (left, round(table_y, 1)), limit)
        return None

    for name, width, height in ISO_SHEETS:
        sheet = fit(width, height)
        if sheet is not None:
            sheet.name = name
            return sheet
    # beyond A0x3: A0 high, as wide (and if need be as high) as the drawing needs
    width = max(2523.0, math.ceil((max(dw, 0.0) + left + right + (x0 if fixed else 0.0)) / 10) * 10)
    height = 1189.0
    while True:
        sheet = fit(width, height)
        if sheet is not None:
            sheet.name = "A0 (elongated)"
            return sheet
        height += 100.0
        if height > 5000.0:  # pragma: no cover - a drawing no sheet holds
            return Sheet("A0 (elongated)", width, height)


def frame(sheet: Sheet) -> list[Any]:
    """The border, the trim line and the zone markers (columns 1.., rows A..)."""
    w, h = sheet.width, sheet.height
    x0, y0, x1, y1 = MARGIN_LEFT, MARGIN, w - MARGIN, h - MARGIN
    lines = [_line("Frame_border", [(x0, y0), (x1, y0), (x1, y1), (x0, y1), (x0, y0)], _FRAME)]
    texts = []
    cols = max(4, round((x1 - x0) / 100.0))
    rows = max(3, round((y1 - y0) / 100.0))
    for c in range(cols + 1):
        x = x0 + (x1 - x0) * c / cols
        if 0 < c < cols:
            lines.append(_line(f"Frame_col_{c}_top", [(x, y0), (x, y0 - 4.0)], _RULE))
            lines.append(_line(f"Frame_col_{c}_bottom", [(x, y1), (x, y1 + 4.0)], _RULE))
        if c < cols:
            mid = x + (x1 - x0) / cols / 2
            texts.append(
                _text(f"Frame_col_{c + 1}_t", str(c + 1), mid, y0 - 4.5, 2.5, "CENTERCENTER")
            )
            texts.append(
                _text(f"Frame_col_{c + 1}_b", str(c + 1), mid, y1 + 4.5, 2.5, "CENTERCENTER")
            )
    for r in range(rows + 1):
        y = y0 + (y1 - y0) * r / rows
        if 0 < r < rows:
            lines.append(_line(f"Frame_row_{r}_left", [(x0, y), (x0 - 4.0, y)], _RULE))
            lines.append(_line(f"Frame_row_{r}_right", [(x1, y), (x1 + 4.0, y)], _RULE))
        if r < rows:
            mid = y + (y1 - y0) / rows / 2
            letter = chr(ord("A") + r) if r < 26 else str(r)
            texts.append(_text(f"Frame_row_{letter}_l", letter, x0 - 5.0, mid, 2.5, "CENTERCENTER"))
            texts.append(_text(f"Frame_row_{letter}_r", letter, x1 + 5.0, mid, 2.5, "CENTERCENTER"))
    return [
        C.Static(id="Drawing_Frame_Static", elements=lines),
        C.Label(id="Drawing_Frame_Label", elements=texts),
    ]


def title_block(sheet: Sheet, fields: dict[str, str]) -> list[Any]:
    """The title block in the bottom right corner: *fields* title, subtitle, project, drawing,
    case, sheet size and the generator note."""
    x1, y1 = sheet.width - MARGIN, sheet.height - MARGIN
    x0, y0 = x1 - TITLE_W, y1 - TITLE_H
    split = x0 + 110.0
    r1, r2, r3 = y0 + 14.0, y0 + 22.0, y0 + 29.0
    lines = [
        _line("TitleBlock_frame", [(x0, y1), (x0, y0), (x1, y0), (x1, y1)], _FRAME),
        _line("TitleBlock_r1", [(x0, r1), (x1, r1)], _RULE),
        _line("TitleBlock_r2", [(x0, r2), (x1, r2)], _RULE),
        _line("TitleBlock_r3", [(x0, r3), (x1, r3)], _RULE),
        _line("TitleBlock_split", [(split, r1), (split, r3)], _RULE),
    ]
    title = fields.get("title", "")
    size = 3.5
    while size > 2.2 and text_width(title, size) > TITLE_W - 6:
        size -= 0.25
    subtitle = fields.get("subtitle", "")
    sub = 2.5
    while sub > 1.8 and text_width(subtitle, sub) > TITLE_W - 6:
        sub -= 0.1

    def cell(key: str, caption: str, value: str, x: float, y: float, width: float) -> list[Any]:
        vs = 2.5
        while vs > 1.6 and text_width(value, vs) > width - 4:
            vs -= 0.1
        return [
            _text(f"TitleBlock_{key}_caption", caption, x + 1.5, y + 1.6, 1.6, "LEFTCENTER", True),
            _text(f"TitleBlock_{key}", value, x + 1.5, y + 5.0, round(vs, 2), "LEFTCENTER"),
        ]

    texts = [
        _text("Label_title", title, x0 + 3.0, y0 + 5.0, round(size, 2), "LEFTCENTER"),
        _text("Label_subtitle", subtitle, x0 + 3.0, y0 + 10.5, round(sub, 2), "LEFTCENTER"),
        *cell("project", "PROJECT / PLANT", fields.get("project", ""), x0, r1, 110.0),
        *cell("drawing", "DRAWING NO", fields.get("drawing", ""), split, r1, TITLE_W - 110.0),
        *cell("case", "CASE", fields.get("case", ""), x0, r2, 110.0),
        *cell("sheet", "SHEET", fields.get("sheet", ""), split, r2, TITLE_W - 110.0),
        _text(
            "Label_case", fields.get("note", ""), x0 + 1.5, (r3 + y1) / 2, 1.7, "LEFTCENTER", True
        ),
    ]
    return [
        C.Static(id="Drawing_TitleBlock_Static", elements=lines),
        C.Label(id="Drawing_title", elements=texts),
    ]
