"""Cycle-aware layered layout of a flow diagram, with orthogonal routes.

1. Feedback edges are picked by the greedy Eades-Lin-Smyth heuristic (nodes in declaration
   order break ties), so every cycle loses at least one edge; they are drawn as recycle routes
   below the main flow.
2. The remaining acyclic graph is layered longest-path from its sources, left to right.
3. Nodes in a layer are ordered by barycentre sweeps (stable, so ties keep declaration order).
4. In ports sit on the left side, out ports on the right, spread evenly.
5. Every route is orthogonal and crosses no block: edges between neighbouring layers take a
   slot in their column gap, top-level recycles a channel below the drawing; skips, block
   boundary delegations and in-block recycles take the shortest free path on lanes between the
   nodes (:class:`GridRouter`), avoiding runs along other routes.

Overrides (``layout.bfd`` / ``layout.pfd`` in the flowsheet) pin a node's position and size or a
route's waypoints; everything else is laid out deterministically.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field

GAP_X = 34.0
GAP_Y = 22.0
CHANNEL = 6.0
#: The gap between the rows of a layout wrapped into rows (``layout(rows=...)``).
ROW_GAP = 44.0

#: Where routes may run: (x0, y0, x1, y1), None for a side that is free.
Area = tuple[float | None, float | None, float | None, float | None]


def spread(count: int) -> list[float]:
    """*count* fractions spaced evenly along a side: ``[1/3, 2/3]`` for two (pyDEXPI's former
    ``process_drawing.spread``)."""
    return [(index + 1) / (count + 1) for index in range(count)]


@dataclass
class LNode:
    id: str
    width: float
    height: float
    ins: list[str] = field(default_factory=list)
    outs: list[str] = field(default_factory=list)
    x: float = 0.0
    y: float = 0.0
    layer: int = 0
    pinned: bool = False
    #: Always in the last layer (a block's outlet boundary inside a PFD block).
    last: bool = False
    #: A boundary stand-in: routed to, never counted in the bounds.
    ghost: bool = False
    #: Keep the order of ins and outs (a block whose ports were ordered for its inside).
    fixed_ports: bool = False
    #: The part of the sides the ports are spread on: from ``port_top`` below the top to
    #: ``port_bottom`` above the bottom (a symbol between a stub band and its labels).
    port_top: float = 0.0
    port_bottom: float = 0.0

    def fraction(self, port: str) -> float:
        """Where *port* sits along its side, 0 (top) to 1 (bottom)."""
        side = self.ins if port in self.ins else self.outs
        return spread(len(side))[side.index(port)] if port in side else 0.5

    def port_point(self, port: str) -> tuple[float, float]:
        span = self.height - self.port_top - self.port_bottom
        if port in self.ins:
            fraction = spread(len(self.ins))[self.ins.index(port)]
            return (self.x, self.y + self.port_top + span * fraction)
        fraction = spread(len(self.outs))[self.outs.index(port)]
        return (self.x + self.width, self.y + self.port_top + span * fraction)


@dataclass
class LEdge:
    id: str
    src: str
    src_port: str
    dst: str
    dst_port: str
    feedback: bool = False
    points: list[tuple[float, float]] = field(default_factory=list)


def feedback_edges(order: list[str], edges: list[LEdge]) -> set[str]:
    """Ids of a small set of edges whose removal leaves the graph acyclic (Eades et al.)."""
    remaining = list(order)
    succ = {n: [e.dst for e in edges if e.src == n and e.dst != n] for n in order}
    pred = {n: [e.src for e in edges if e.dst == n and e.src != n] for n in order}
    left: list[str] = []
    right: list[str] = []
    alive = set(order)
    while alive:
        changed = True
        while changed:
            changed = False
            for n in [n for n in remaining if n in alive]:
                if not any(s in alive for s in succ[n]):
                    right.insert(0, n)
                    alive.discard(n)
                    changed = True
            for n in [n for n in remaining if n in alive]:
                if not any(p in alive for p in pred[n]):
                    left.append(n)
                    alive.discard(n)
                    changed = True
        if alive:
            best = max(
                (n for n in remaining if n in alive),
                key=lambda n: (
                    sum(s in alive for s in succ[n]) - sum(p in alive for p in pred[n]),
                    -remaining.index(n),
                ),
            )
            left.append(best)
            alive.discard(best)
    rank = {n: i for i, n in enumerate(left + right)}
    return {e.id for e in edges if e.src == e.dst or rank[e.src] >= rank[e.dst]}


def dfs_feedback(order: list[str], edges: list[LEdge]) -> set[str]:
    """Feedback edges by depth-first search from the nodes in declaration order (feeds first),
    edges in declaration order: an edge back to a node on the current path closes a cycle.
    This follows the process flow from the feeds, so recycles, not the main flow, are cut."""
    state: dict[str, int] = {}  # 1 on the path, 2 done
    back: set[str] = set()

    def visit(node: str) -> None:
        state[node] = 1
        for edge in edges:
            if edge.src != node:
                continue
            if state.get(edge.dst) == 1:
                back.add(edge.id)
            elif edge.dst not in state:
                visit(edge.dst)
        state[node] = 2

    for node in order:
        if node not in state:
            visit(node)
    return back


def layout(
    nodes: list[LNode],
    edges: list[LEdge],
    origin: tuple[float, float] = (20.0, 30.0),
    gap_x: float = GAP_X,
    gap_y: float = GAP_Y,
    skip: str = "above",
    grid_feedback: bool = False,
    area: Area | None = None,
    order_ports: bool = False,
    rows: int = 1,
    pull_sources: bool = False,
) -> tuple[float, float, float, float]:
    """Place unpinned *nodes* and route *edges* in place; returns the bounds (x0, y0, x1, y1).

    With *rows* above one the layers wrap into that many rows, read like text (left to right,
    then the next row below), on one grid of columns: a line between rows, and every recycle, is
    routed by :class:`GridRouter`. With *pull_sources* a node without inputs (a feed) sits in the
    layer just before its first consumer instead of the first layer, so it enters where it is
    used.

    With *order_ports* each node's ports are sorted by where their lines go (inside a block,
    where the grid router takes every route; the channel routes outside keep declared order).

    Edges between neighbouring layers take a slot in their column gap. Every other edge (skips,
    boundary delegations to ghost nodes, and recycles if *grid_feedback*) is routed by
    :class:`GridRouter` on the shortest orthogonal path that crosses no node and runs along no
    other route; routes stay inside *area* when given."""
    if not nodes:
        return (origin[0], origin[1], origin[0], origin[1])
    order = [n.id for n in nodes]
    by_id = {n.id: n for n in nodes}
    back = dfs_feedback(order, edges)
    for edge in edges:
        edge.feedback = edge.id in back
    forward = [e for e in edges if not e.feedback]
    # longest-path layering
    layer = dict.fromkeys(order, 0)
    for _ in range(len(order)):
        changed = False
        for e in forward:
            if layer[e.dst] < layer[e.src] + 1:
                layer[e.dst] = layer[e.src] + 1
                changed = True
        if not changed:
            break
    if pull_sources:
        fed = {e.dst for e in forward}
        for n in order:
            succ = [layer[e.dst] for e in forward if e.src == n]
            if n not in fed and succ and not by_id[n].pinned and not by_id[n].ghost:
                layer[n] = max(0, min(succ) - 1)
    final = max((layer[n] for n in order if not by_id[n].last), default=0) + 1
    for n in order:
        if by_id[n].last:
            layer[n] = max(layer[n], final)
    layers: dict[int, list[str]] = {}
    for n in order:
        by_id[n].layer = layer[n]
        layers.setdefault(layer[n], []).append(n)
    count = max(layers) + 1
    widths = [max((by_id[n].width for n in layers.get(k, [])), default=0.0) for k in range(count)]
    per = math.ceil(count / rows) if rows > 1 else count
    if per < count:  # one grid of columns for every row
        shared = [max(widths[k] for k in range(j, count, per)) for j in range(per)]
        widths = [shared[k % per] for k in range(count)]
        grid_feedback = True
    column_x = []
    x = origin[0]
    for k in range(count):
        if k % per == 0:
            x = origin[0]
        column_x.append(x)
        x += widths[k] + gap_x
    # Rounds of: barycentre ordering, coordinates, port order by where each port's line goes.
    # The port order changes the barycentres, so a second round settles both.
    for _ in range(2):
        layers = _order_layers(layers, count, by_id, forward)
        y = origin[1]
        for start in range(0, count, per):
            row = {k: v for k, v in layers.items() if start <= k < start + per}
            _coordinates(row, count, by_id, column_x, widths, (origin[0], y), gap_y)
            placed = [by_id[n] for v in row.values() for n in v if not by_id[n].ghost]
            y = max((n.y + n.height for n in placed), default=y) + ROW_GAP
        if order_ports:
            _order_ports(nodes, by_id, edges)
    _align_inlets(layers, count, by_id, forward, origin, gap_y)
    real = [n for n in nodes if not n.ghost] or nodes
    x0 = min(n.x for n in real)
    y0 = min(n.y for n in real)
    x1 = max(n.x + n.width for n in real)
    y1 = max(n.y + n.height for n in real)

    def gridded(e: LEdge) -> bool:
        src, dst = by_id[e.src], by_id[e.dst]
        if src.ghost or dst.ghost:
            return True
        if e.feedback:
            return grid_feedback
        return dst.layer != src.layer + 1 or src.layer // per != dst.layer // per

    slotted = [e for e in edges if not gridded(e)]
    _route(by_id, slotted, column_x, widths, gap_x, (x0, y0, x1, y1), skip)
    rest = [e for e in edges if gridded(e)]
    if rest:
        router = GridRouter([n for n in nodes if not n.ghost], column_x, widths, gap_x, gap_y, area)
        for e in slotted:
            router.add(e.points)
        rest.sort(key=lambda e: (_manhattan(by_id, e), e.id))
        for e in rest:
            src, dst = by_id[e.src], by_id[e.dst]
            points = router.route(src.port_point(e.src_port), dst.port_point(e.dst_port))
            if points is None:  # no free path: the channel route
                _route(by_id, [e], column_x, widths, gap_x, (x0, y0, x1, y1), skip)
                points = e.points
            e.points = points
            router.add(points)
    for e in edges:
        ghosts = by_id[e.src].ghost or by_id[e.dst].ghost
        for px, py in e.points[1:-1] if ghosts else e.points:
            x0, y0, x1, y1 = min(x0, px), min(y0, py), max(x1, px), max(y1, py)
    return (x0, y0, x1, y1)


#: Barycentre sweeps per round; the ordering with the fewest crossings wins.
SWEEPS = 8


def _order_layers(
    layers: dict[int, list[str]], count: int, by_id: dict[str, LNode], forward: list[LEdge]
) -> dict[int, list[str]]:
    """Order the nodes of each layer by the barycentre of their neighbours' ports in the layer
    before (down sweeps) or after (up sweeps); keep the sweep with the fewest crossings between
    neighbouring layers (ties: the earliest, so declaration order wins when nothing crosses)."""

    def crossings(order: dict[int, list[str]]) -> int:
        position = {n: i for k in order for i, n in enumerate(order[k])}
        total = 0
        for k in range(count - 1):
            pairs = sorted(
                (
                    position[e.src] + by_id[e.src].fraction(e.src_port),
                    position[e.dst] + by_id[e.dst].fraction(e.dst_port),
                )
                for e in forward
                if by_id[e.src].layer == k and by_id[e.dst].layer == k + 1
            )
            total += sum(
                1
                for i, a in enumerate(pairs)
                for b in pairs[i + 1 :]
                if a[0] < b[0] and a[1] > b[1]
            )
        return total

    best = {k: list(v) for k, v in layers.items()}
    fewest = crossings(best)
    for sweep in range(SWEEPS):
        if not fewest:
            break
        down = sweep % 2 == 0
        for k in range(1, count) if down else range(count - 2, -1, -1):
            ref = k - 1 if down else k + 1
            position = {n: i for i, n in enumerate(layers.get(ref, []))}

            def bary(n: str, position: dict[str, int] = position, row: int = k) -> float:
                near = [
                    position[e.src] + by_id[e.src].fraction(e.src_port)
                    if e.dst == n
                    else position[e.dst] + by_id[e.dst].fraction(e.dst_port)
                    for e in forward
                    if (e.dst == n and e.src in position) or (e.src == n and e.dst in position)
                ]
                if not near:
                    return float(layers[row].index(n)) + 0.5
                return sum(near) / len(near)

            layers[k] = sorted(layers.get(k, []), key=bary)
        found = crossings(layers)
        if found < fewest:
            best, fewest = {k: list(v) for k, v in layers.items()}, found
    return best


def _coordinates(
    layers: dict[int, list[str]],
    count: int,
    by_id: dict[str, LNode],
    column_x: list[float],
    widths: list[float],
    origin: tuple[float, float],
    gap_y: float,
) -> None:
    """Columns left to right, each centred on one mid line; a ghost spans the full height."""
    stacked = {k: [n for n in layers.get(k, []) if not by_id[n].ghost] for k in range(count)}
    heights = [
        sum(by_id[n].height for n in stacked[k]) + gap_y * max(len(stacked[k]) - 1, 0)
        for k in range(count)
    ]
    tallest = max(heights)
    for k in range(count):
        y = origin[1] + (tallest - heights[k]) / 2
        for n in layers.get(k, []):
            node = by_id[n]
            if node.ghost:
                if not node.pinned:
                    node.x, node.y, node.height = column_x[k], origin[1], max(tallest, 1.0)
                continue
            if not node.pinned:
                node.x = column_x[k] + (widths[k] - node.width) / 2
                node.y = y
            y += node.height + gap_y


#: The furthest :func:`_align_inlets` moves a node to line its inlet up with its source, mm.
ALIGN_SHIFT = 14.0


def _align_inlets(
    layers: dict[int, list[str]],
    count: int,
    by_id: dict[str, LNode],
    forward: list[LEdge],
    origin: tuple[float, float],
    gap_y: float,
) -> None:
    """Remove small jogs: column by column, left to right, move each unpinned node up or down
    (at most :data:`ALIGN_SHIFT`, keeping the gap to its neighbours and inside the columns'
    height) so the in port whose line would jog least runs straight from its source port."""
    real = [n for n in by_id.values() if not n.ghost]
    if not real:
        return
    top = origin[1]
    bottom = max(n.y + n.height for n in real)
    for k in range(count):
        column = [by_id[n] for n in layers.get(k, []) if not by_id[n].ghost]
        for i, node in enumerate(column):
            if node.pinned:
                continue
            low = column[i - 1].y + column[i - 1].height + gap_y if i else top
            high = (column[i + 1].y - gap_y if i + 1 < len(column) else bottom) - node.height
            shifts = []
            for e in forward:
                if e.dst != node.id or e.src == node.id or by_id[e.src].layer >= node.layer:
                    continue
                dy = by_id[e.src].port_point(e.src_port)[1] - node.port_point(e.dst_port)[1]
                if 1e-6 < abs(dy) <= ALIGN_SHIFT and low - 1e-6 <= node.y + dy <= high + 1e-6:
                    shifts.append(dy)
            if shifts:
                node.y = round(node.y + min(shifts, key=abs), 3)


def _order_ports(nodes: list[LNode], by_id: dict[str, LNode], edges: list[LEdge]) -> None:
    """Sort each node's in and out ports by the height of the other end of their lines, so lines
    leaving or entering one side do not cross each other. Pinned ghosts (a block boundary whose
    ports are already placed) and nodes with fixed ports keep their order."""
    heights: dict[tuple[str, str], list[float]] = {}
    for e in edges:
        src, dst = by_id[e.src], by_id[e.dst]
        heights.setdefault((e.src, e.src_port), []).append(dst.port_point(e.dst_port)[1])
        heights.setdefault((e.dst, e.dst_port), []).append(src.port_point(e.src_port)[1])
    for node in nodes:
        if node.fixed_ports or (node.ghost and node.pinned):
            continue
        for side in (node.ins, node.outs):
            here = {p: node.port_point(p)[1] for p in side}

            def key(
                p: str, here: dict[str, float] = here, side: list[str] = side, at: str = node.id
            ) -> tuple:
                ys = heights.get((at, p)) or [here[p]]
                return (sum(ys) / len(ys), side.index(p))

            side[:] = sorted(side, key=key)


def _route(
    by_id: dict[str, LNode],
    edges: list[LEdge],
    column_x: list[float],
    widths: list[float],
    gap_x: float,
    bounds: tuple[float, float, float, float],
    skip: str = "above",
) -> None:
    """Orthogonal routes in the column gaps and in channels above and below."""
    x0, y0, x1, y1 = bounds

    def gap_after(column: int) -> tuple[float, float]:
        if column < 0:
            return (x0 - gap_x, x0)
        if column >= len(column_x):
            return (x1, x1 + gap_x)
        start = column_x[column] + widths[column]
        return (start, start + gap_x)

    # requests for vertical slots, per gap: (gap index, edge id, purpose)
    slots: dict[int, list[str]] = {}
    plans: dict[str, tuple[str, int, int]] = {}
    above = below = 0
    for e in edges:
        src, dst = by_id[e.src], by_id[e.dst]
        if e.feedback:
            plans[e.id] = ("below", src.layer, dst.layer - 1)
        elif dst.layer == src.layer + 1:
            plans[e.id] = ("direct", src.layer, src.layer)
        else:
            plans[e.id] = (skip, src.layer, dst.layer - 1)
        kind, a, b = plans[e.id]
        slots.setdefault(a, []).append(f"{e.id}:a")
        if kind != "direct":
            slots.setdefault(b, []).append(f"{e.id}:b")
    # In a gap, a route leaving the column on the left runs from the left side to its slot and a
    # route entering the column on the right runs from its slot to the right side; at the same
    # port height they overlap unless leaving slots lie left of entering ones (direct in between).
    for keys in slots.values():
        keys.sort(key=lambda k: 1 if plans[k[:-2]][0] == "direct" else 0 if k[-1] == "a" else 2)

    def slot_x(gap: int, key: str) -> float:
        start, end = gap_after(gap)
        keys = slots[gap]
        return start + (end - start) * (keys.index(key) + 1) / (len(keys) + 1)

    for e in edges:
        src, dst = by_id[e.src], by_id[e.dst]
        sx, sy = src.port_point(e.src_port)
        tx, ty = dst.port_point(e.dst_port)
        kind, a, b = plans[e.id]
        ga = slot_x(a, f"{e.id}:a")
        if kind == "direct":
            e.points = [(sx, sy), (ga, sy), (ga, ty), (tx, ty)]
            continue
        gb = slot_x(b, f"{e.id}:b")
        if kind == "above":
            above += 1
            yc = y0 - CHANNEL * above
        else:
            below += 1
            yc = y1 + CHANNEL * below
        e.points = [(sx, sy), (ga, sy), (ga, yc), (gb, yc), (gb, ty), (tx, ty)]
    for e in edges:  # drop zero-length steps (straight runs)
        cleaned: list[tuple[float, float]] = []
        for p in e.points:
            p = (round(p[0], 3), round(p[1], 3))
            if cleaned and p == cleaned[-1]:
                continue
            if len(cleaned) >= 2 and _collinear(cleaned[-2], cleaned[-1], p):
                cleaned[-1] = p
                continue
            cleaned.append(p)
        e.points = cleaned


def _collinear(a: tuple[float, float], b: tuple[float, float], c: tuple[float, float]) -> bool:
    return (a[0] == b[0] == c[0]) or (a[1] == b[1] == c[1])


def _manhattan(by_id: dict[str, LNode], e: LEdge) -> float:
    (sx, sy), (tx, ty) = by_id[e.src].port_point(e.src_port), by_id[e.dst].port_point(e.dst_port)
    return abs(tx - sx) + abs(ty - sy)


Point = tuple[float, float]

#: Costs of the grid router, in drawing units of length.
BEND, CROSS, OVERLAP = 6.0, 40.0, 400.0
#: Lanes per free column gap; lanes in a node's vertical gap on each side.
LANES, SIDE_LANES = 5, 3


def _free(intervals: list[tuple[float, float]], lo: float, hi: float) -> list[tuple[float, float]]:
    """Parts of [lo, hi] that no interval covers."""
    free, at = [], lo
    for a, b in sorted(intervals):
        if a > at:
            free.append((at, min(a, hi)))
        at = max(at, b)
    if at < hi:
        free.append((at, hi))
    return [(a, b) for a, b in free if b - a > 1.0]


class GridRouter:
    """Shortest orthogonal routes on lanes in the free space between nodes (A* over a sparse
    grid): no route enters or runs along a node, running on another route is very expensive,
    crossing one and bending cost a little. Routes leave a port to the right and enter one from
    the left, as ports sit on the right (out) and left (in) sides."""

    def __init__(
        self,
        nodes: list[LNode],
        column_x: list[float],
        widths: list[float],
        gap_x: float,
        gap_y: float,
        area: Area | None,
    ) -> None:
        # rounded like the route points, so a port on a box side is outside it
        self.boxes = [
            (round(n.x, 3), round(n.y, 3), round(n.x + n.width, 3), round(n.y + n.height, 3))
            for n in nodes
        ]
        lo_x = min(b[0] for b in self.boxes) - gap_x
        hi_x = max(b[2] for b in self.boxes) + gap_x
        top, bottom = min(b[1] for b in self.boxes), max(b[3] for b in self.boxes)
        lo_y, hi_y = top - CHANNEL * (LANES + 1), bottom + CHANNEL * (LANES + 1)
        given = area or (None, None, None, None)
        lo_x, lo_y, hi_x, hi_y = (
            v if v is not None else d for v, d in zip(given, (lo_x, lo_y, hi_x, hi_y), strict=True)
        )
        xs: set[float] = set()
        for a, b in _free([(b[0], b[2]) for b in self.boxes], lo_x, hi_x):
            lanes = max(2, min(9, int((b - a) / 4.0)))
            xs.update(round(a + (b - a) * j / (lanes + 1), 3) for j in range(1, lanes + 1))
        ys: set[float] = set()
        for _, y0, _, y1 in self.boxes:
            for j in range(1, SIDE_LANES + 1):
                ys.add(round(y0 - gap_y * j / (SIDE_LANES + 1), 3))
                ys.add(round(y1 + gap_y * j / (SIDE_LANES + 1), 3))
        for j in range(1, LANES + 1):
            ys.add(round(top - CHANNEL * j, 3))
            ys.add(round(bottom + CHANNEL * j, 3))
        self.xs = {x for x in xs if lo_x <= x <= hi_x}
        self.ys = {y for y in ys if lo_y <= y <= hi_y}
        self.horizontal: dict[float, list[tuple[float, float]]] = {}
        self.vertical: dict[float, list[tuple[float, float]]] = {}
        self._hkeys: list[float] = []
        self._vkeys: list[float] = []
        self._blocked: dict[tuple[Point, Point], bool] = {}

    def add(self, points: list[Point]) -> None:
        """Make *points* an existing route the next ones avoid."""
        for a, b in zip(points, points[1:], strict=False):
            if a[1] == b[1] and a[0] != b[0]:
                self.horizontal.setdefault(a[1], []).append((min(a[0], b[0]), max(a[0], b[0])))
            elif a[0] == b[0] and a[1] != b[1]:
                self.vertical.setdefault(a[0], []).append((min(a[1], b[1]), max(a[1], b[1])))
        self._hkeys, self._vkeys = sorted(self.horizontal), sorted(self.vertical)

    def blocked(self, a: Point, b: Point) -> bool:
        key = (a, b)
        if key not in self._blocked:
            x0, x1 = min(a[0], b[0]), max(a[0], b[0])
            y0, y1 = min(a[1], b[1]), max(a[1], b[1])
            hit = False
            for bx0, by0, bx1, by1 in self.boxes:
                if y0 == y1:
                    hit = by0 <= y0 <= by1 and max(x0, bx0) < min(x1, bx1)
                else:
                    hit = bx0 <= x0 <= bx1 and max(y0, by0) < min(y1, by1)
                if hit:
                    break
            self._blocked[key] = hit
        return self._blocked[key]

    def penalty(self, a: Point, b: Point) -> float:
        """Running on an existing route, and crossing one at *b* or between *a* and *b*."""
        from bisect import bisect_left, bisect_right

        cost = 0.0
        if a[1] == b[1]:
            same, other, keys, at, lo, hi = (
                self.horizontal,
                self.vertical,
                self._vkeys,
                a[1],
                a[0],
                b[0],
            )
        else:
            same, other, keys, at, lo, hi = (
                self.vertical,
                self.horizontal,
                self._hkeys,
                a[0],
                a[1],
                b[1],
            )
        s0, s1 = min(lo, hi), max(lo, hi)
        for r0, r1 in same.get(at, ()):
            if max(s0, r0) < min(s1, r1):
                cost += OVERLAP
        # crossings strictly past a, up to and including b
        if hi > lo:
            found = keys[bisect_right(keys, lo) : bisect_right(keys, hi)]
        else:
            found = keys[bisect_left(keys, hi) : bisect_left(keys, lo)]
        for key in found:
            for r0, r1 in other[key]:
                if r0 < at < r1:
                    cost += CROSS
        return cost

    def route(self, start: Point, end: Point) -> list[Point] | None:
        import heapq

        start = (round(start[0], 3), round(start[1], 3))
        end = (round(end[0], 3), round(end[1], 3))
        xs = sorted(self.xs | {start[0], end[0]})
        ys = sorted(self.ys | {start[1], end[1]})
        xi, yi = {x: i for i, x in enumerate(xs)}, {y: i for i, y in enumerate(ys)}
        goal = (xi[end[0]], yi[end[1]])
        moves = ((1, 0), (-1, 0), (0, 1), (0, -1))

        def h(i: int, j: int) -> float:
            return abs(xs[i] - end[0]) + abs(ys[j] - end[1])

        s = (xi[start[0]], yi[start[1]], 0)  # direction index into moves: leave rightwards
        best = {s: 0.0}
        parent: dict[tuple[int, int, int], tuple[int, int, int]] = {}
        heap = [(h(s[0], s[1]), 0.0, 0, s)]
        counter = 0
        first = True
        while heap:
            _, cost, _, state = heapq.heappop(heap)
            if cost > best.get(state, float("inf")):
                continue
            i, j, d = state
            if (i, j) == goal:
                points = []
                at: tuple[int, int, int] | None = state
                while at is not None:
                    points.append((xs[at[0]], ys[at[1]]))
                    at = parent.get(at)
                points.reverse()
                return _straighten(points)
            for nd, (di, dj) in enumerate(moves):
                if first and nd != 0:
                    continue
                if not first and (di, dj) == (-moves[d][0], -moves[d][1]):
                    continue
                ni, nj = i + di, j + dj
                if not (0 <= ni < len(xs) and 0 <= nj < len(ys)):
                    continue
                if (ni, nj) == goal and nd != 0:
                    continue  # enter the port from the left
                a, b = (xs[i], ys[j]), (xs[ni], ys[nj])
                if self.blocked(a, b):
                    continue
                step = abs(b[0] - a[0]) + abs(b[1] - a[1])
                new = cost + step + self.penalty(a, b) + (BEND if nd != d and not first else 0)
                ns = (ni, nj, nd)
                if new < best.get(ns, float("inf")):
                    best[ns] = new
                    parent[ns] = state
                    counter += 1
                    heapq.heappush(heap, (new + h(ni, nj), new, counter, ns))
            first = False
        return None


def _straighten(points: list[Point]) -> list[Point]:
    out: list[Point] = []
    for p in points:
        if len(out) >= 2 and _collinear(out[-2], out[-1], p):
            out[-1] = p
        else:
            out.append(p)
    return out
