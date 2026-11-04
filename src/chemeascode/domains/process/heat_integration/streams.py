"""The thermal streams of a solved simulation case: every thermal duty of the run, once.

:func:`thermal_streams` turns the simulator model of one case (``translate``'s ``model``) and the
simulator's result (``out``: ``units`` and ``streams`` as :mod:`..simulation.run` reports them, or
as rebuilt from ``process/simulation-run.json`` by :func:`out_from_record`) into one
:class:`ThermalStream` per duty and side, each with its source unit, role, case, class, quality
and pinch :class:`~.pinch.Segment` s, plus a :class:`Reconciliation` against the duties of the
run.

**Class** (each duty in exactly one):

- ``utility``: a process stream heated or cooled by a utility (heater, cooler, flash, column
  condenser or reboiler, the process side of an exchanger whose other side is a utility
  terminal's stream: a waste-heat boiler raising steam, a steam heater). The utility side is not
  a stream: a waste-heat boiler's process side is a hot process stream and its steam is the
  utility, not a second source.
- ``recovery``: existing process/process exchange. Both sides of a two-stream exchanger whose
  sides are process streams, every side of a multi-stream exchanger, a reboiler heated by another
  column's condenser (``heat_integration.condenser_of``) and that condenser. Both sides enter the
  targets as process streams; the exchanger's duty counts once (the reconciliation counts one
  side, ``counted_kW``), never as utility.
- ``constrained``: a duty whose temperature is set by something other than the heat it gives or
  takes: by default every reactor (:data:`REACTORS`; the reason is given). Left out of the
  targets by default, included as a sensitivity on request.
- ``excluded``: left out of the targets, with the reason: no usable temperatures
  (quality ``insufficient``), a multi-stream exchanger's net imbalance, a compressor train's
  intercooling (no temperatures reported), a specified split's stated imbalance (ADR 0038).

**Quality.** The simulator returns, per unit, its duty (or condenser and reboiler duties) and, per
stream, the inlet and outlet temperature, vapour fraction and enthalpy: two points of each
heated or cooled stream, never an enthalpy-temperature profile across the duty (DWSIM's worker,
``integrations/dwsim_worker.py``; IDAES's likewise). So this module gives only two qualities:

- ``linearised``: total duty and the end temperatures: one constant-CP segment from inlet to
  outlet, or one isothermal (latent) segment where they are equal (a column's condenser at its
  top temperature and reboiler at its bottom temperature; a shortcut column, which reports no
  stage temperatures, at the distillate and bottoms temperatures). A stream that changes phase
  is *not* split at a dew or bubble point: it stays one line and says so (``notes``);
- ``insufficient``: a temperature or the duty is missing, or the temperatures run against the
  duty (heat added while the stream cools, e.g. a flash with a pressure drop): class
  ``excluded``, its duty listed.

``profile`` (several H-T points across the duty) and ``segmented`` (sensible and latent parts
separately) are part of the vocabulary (:data:`QUALITIES`) for sources that have them; no
simulation output gives them today.

**Reconciliation.** :func:`run_duties` lists every thermal duty of the run from the units'
results alone (not from the extraction): heat duties of heated units, exchanger duties,
condenser and reboiler duties, intercooling, stated imbalances, and any heat result of a unit
kind this module does not know. Each extracted stream accounts for part of one of them
(``counted_kW``); the per-class sums plus what is left over give back the run's total. A duty
not accounted for within :func:`duty_tolerance` is left over: a finding, and ``cheme process
pinch --write`` refuses.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Literal

from chemeascode.domains.process.energy import ENERGY_TOLERANCE
from chemeascode.domains.process.heat_integration.pinch import PinchStream, Segment

#: Reacting units (a kinetic_pfr is solved by cheme-as-code and seen by DWSIM as a conversion
#: reactor: it reacts all the same).
REACTORS = ("conversion_reactor", "equilibrium_reactor", "gibbs_reactor", "kinetic_pfr")
#: Units whose single duty heats or cools one process stream (inlet 0 to outlet 0).
HEATED = ("heater", "cooler", "flash", *REACTORS)
#: Units with a condenser and a reboiler.
COLUMNS = ("distillation_column", "shortcut_column")
#: Units whose ``duty_kW`` is shaft power, not heat.
MACHINES = ("compressor", "pump", "expander")
#: Temperature differences below this are taken as no change (K); vapour fractions below
#: this as no phase change.
SMALL_DT = 1e-6
SMALL_VF = 1e-4
#: A duty at or below this (kW) is none.
SMALL_KW = 1e-9
#: Result keys that are heat (kW) for a unit kind not otherwise known.
HEAT_KEYS = ("duty_kW", "condenser_kW", "reboiler_kW", "cooling_kW")

Category = Literal["utility", "recovery", "constrained", "excluded"]
Quality = Literal["profile", "segmented", "linearised", "insufficient"]
CATEGORIES: tuple[Category, ...] = ("utility", "recovery", "constrained", "excluded")
QUALITIES: tuple[Quality, ...] = ("profile", "segmented", "linearised", "insufficient")
#: Why a reactor is constrained by default.
REACTOR_REASON = (
    "reactor duty: its temperature is set by the reaction and the reactor's operation, not "
    "free for heat recovery; excluded from the targets by default (--include-constrained "
    "includes it as a sensitivity)"
)
#: What a target resting on linearised streams is (``basis`` of the extraction).
LINEARISED_BASIS = (
    "each stream linearised between its inlet and outlet temperature (one constant-CP or "
    "isothermal segment): the simulation reports no enthalpy-temperature profile"
)


def duty_tolerance(kw: float) -> float:
    """The reconciliation tolerance of one duty of *kw* kW: 0.1 kW plus 1 % (the energy
    closure's ``abs_kW`` and ``rel_duty``, :data:`chemeascode.domains.process.energy.
    ENERGY_TOLERANCE`)."""
    return ENERGY_TOLERANCE["abs_kW"] + ENERGY_TOLERANCE["rel_duty"] * abs(kw)


def side(t_in: float, t_out: float, duty: float, name: str, side: str | None = None):
    """A pinch stream for one exchanger side: constant heat capacity flow, or an isothermal
    load (temperatures equal) on *side*."""
    if abs(t_in - t_out) <= SMALL_DT:
        return PinchStream.piecewise([Segment.latent(t_in, duty)], name, side=side)  # type: ignore[arg-type]
    return PinchStream(t_in, t_out, duty / abs(t_in - t_out), name)


def _flow(out: dict[str, Any], sid: str) -> dict[str, Any]:
    return (out.get("streams") or {}).get(sid) or {}


def _temperature(out: dict[str, Any], sid: str | None) -> float | None:
    return _flow(out, sid).get("temperature_K") if sid else None


def _enthalpy_flow(out: dict[str, Any], sid: str) -> float | None:
    s = _flow(out, sid)
    m, h = s.get("mass_flow_kg_s"), s.get("mass_enthalpy_kJ_kg")
    return None if m is None or h is None else m * h


def _phase_changes(out: dict[str, Any], a: str, b: str) -> bool | None:
    """Whether stream *a* changes phase into *b*; None when the vapour fractions are unknown."""
    va, vb = _flow(out, a).get("vapor_fraction"), _flow(out, b).get("vapor_fraction")
    if va is None or vb is None:
        return None
    two_phase = any(SMALL_VF < v < 1 - SMALL_VF for v in (va, vb))
    return two_phase or abs(va - vb) > SMALL_VF


@dataclass(frozen=True)
class ProcessDuty:
    """One duty of a heated unit or a column on its process side: *role* (``energy``,
    ``condenser``, ``reboiler``), the side as a pinch stream, and whether heat is added."""

    role: str
    stream: PinchStream
    heated: bool
    #: How the temperatures were taken: ``inlet-outlet``, ``stage`` (a rigorous column's top or
    #: bottom stage) or ``product`` (a shortcut column's distillate or bottoms).
    basis: str = "inlet-outlet"


def process_duties(
    u: dict[str, Any], got: dict[str, Any], out: dict[str, Any], *, shortcut: bool = True
) -> list[ProcessDuty]:
    """The process-side duties of unit *u* (model unit) with results *got*: a heated unit's one
    duty (inlet 0 to outlet 0, constant CP or isothermal) and a column's condenser (isothermal
    at its top) and reboiler (at its bottom). A rigorous column uses its top and bottom stage
    temperatures; with *shortcut* a shortcut column, which reports none, uses its distillate's
    and bottoms' temperatures. Duties without the temperatures are left out (see
    :func:`thermal_streams` for those)."""
    uid, kind = u["id"], u["type"]
    found: list[ProcessDuty] = []
    if kind in HEATED and u["inlets"] and u["outlets"]:
        q = got.get("duty_kW")
        t_in = _temperature(out, u["inlets"][0])
        t_out = _temperature(out, u["outlets"][0])
        if q and t_in is not None and t_out is not None:
            heated = q > 0
            stream = side(t_in, t_out, abs(q), uid, "cold" if heated else "hot")
            found.append(ProcessDuty("energy", stream, heated))
    elif kind in COLUMNS:
        top, bottom, basis = got.get("top_temperature_K"), got.get("bottom_temperature_K"), "stage"
        if kind == "shortcut_column":
            if not shortcut:
                return found
            outlets = u["outlets"]
            top = _temperature(out, outlets[0]) if outlets else None
            bottom = _temperature(out, outlets[1]) if len(outlets) > 1 else None
            basis = "product"
        if got.get("condenser_kW") and top is not None:
            found.append(
                ProcessDuty(
                    "condenser", side(top, top, got["condenser_kW"], uid, "hot"), False, basis
                )
            )
        if got.get("reboiler_kW") and bottom is not None:
            found.append(
                ProcessDuty(
                    "reboiler", side(bottom, bottom, got["reboiler_kW"], uid, "cold"), True, basis
                )
            )
    return found


@dataclass(frozen=True)
class ThermalStream:
    """One side of one thermal duty of a solved case."""

    id: str  # unit, unit:role or unit:inlet stream
    unit: str
    unit_type: str
    role: str  # energy, condenser, reboiler, exchange, net, intercooling, stated, ...
    case: str
    category: Category
    quality: Quality
    side: Literal["hot", "cold"] | None  # None where not known
    duty_kW: float
    supply_K: float | None = None
    target_K: float | None = None
    segments: tuple[Segment, ...] = ()
    #: The run duty this stream accounts for (``(unit, role)`` of :func:`run_duties`) and how
    #: much of it: the counted side of an exchanger carries its duty, the other side 0.
    duty_key: tuple[str, str] = ("", "")
    counted_kW: float = 0.0
    #: The utility terminal serving it (class utility), where known.
    utility: str | None = None
    #: The process stream ids (inlet, outlet) where there are some.
    streams: tuple[str, ...] = ()
    reason: str = ""
    notes: tuple[str, ...] = ()

    @property
    def usable(self) -> bool:
        """Whether it has segments to enter the targets."""
        return bool(self.segments) and self.quality != "insufficient"

    def pinch_stream(self) -> PinchStream:
        """The stream for :func:`~.pinch.pinch_analysis` (``usable`` streams only)."""
        if not self.usable:
            raise ValueError(f"{self.id}: no thermal data for the targets ({self.reason})")
        return PinchStream.piecewise(list(self.segments), self.id, side=self.side)

    def entry(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "unit": self.unit,
            "unit_type": self.unit_type,
            "role": self.role,
            "case": self.case,
            "class": self.category,
            "quality": self.quality,
            "side": self.side,
            "duty_kW": self.duty_kW,
            "supply_K": self.supply_K,
            "target_K": self.target_K,
            "segments": [
                {
                    "supply_K": s.supply_temperature,
                    "target_K": s.target_temperature,
                    "duty_kW": s.duty,
                }
                for s in self.segments
            ],
            "counts_for": {"unit": self.duty_key[0], "role": self.duty_key[1]},
            "counted_kW": self.counted_kW,
            "utility": self.utility,
            "streams": list(self.streams),
            "reason": self.reason or None,
            "notes": list(self.notes),
        }


@dataclass
class Reconciliation:
    """The extracted streams against the run's thermal duties (:func:`run_duties`)."""

    #: One row per run duty: unit, unit_type, role, kW, class, counted_kW, residual_kW,
    #: tolerance_kW, closed.
    duties: list[dict[str, Any]]
    #: kW of the run's duties accounted for, by class.
    by_class: dict[str, float]
    total_kW: float
    accounted_kW: float
    residual_kW: float
    #: The duties left over (not accounted for within their tolerance).
    leftover: list[dict[str, Any]] = field(default_factory=list)

    @property
    def closed(self) -> bool:
        return not self.leftover

    def entry(self) -> dict[str, Any]:
        return {
            "closed": self.closed,
            "total_kW": self.total_kW,
            "accounted_kW": self.accounted_kW,
            "residual_kW": self.residual_kW,
            "by_class_kW": dict(self.by_class),
            "duties": self.duties,
            "leftover": self.leftover,
        }


@dataclass
class Extraction:
    """The thermal streams of one case and their reconciliation."""

    case: str
    streams: list[ThermalStream]
    reconciliation: Reconciliation
    basis: str = LINEARISED_BASIS

    def targeted(self, include_constrained: bool = False) -> list[ThermalStream]:
        """The streams that enter the targets: usable utility and recovery streams, and the
        constrained ones with *include_constrained*."""
        wanted = {"utility", "recovery"} | ({"constrained"} if include_constrained else set())
        return [s for s in self.streams if s.usable and s.category in wanted]

    def shares(self) -> dict[str, dict[str, float]]:
        """The share of the run's thermal duty (each duty once, as the reconciliation counts
        it) by class and by quality."""
        total = sum(s.counted_kW for s in self.streams) or 1.0
        return {
            "class": {
                c: sum(s.counted_kW for s in self.streams if s.category == c) / total
                for c in CATEGORIES
            },
            "quality": {
                q: sum(s.counted_kW for s in self.streams if s.quality == q) / total
                for q in QUALITIES
            },
        }


# -- the run's duties --------------------------------------------------------------------------


def _msx_groups(got: dict[str, Any]) -> tuple[float, float]:
    """(heat given by the hot sides, heat taken by the cold sides) of a multi-stream
    exchanger, kW."""
    duties = got.get("side_duties_kW") or []
    if duties:
        return sum(-d for d in duties if d < 0), sum(d for d in duties if d > 0)
    total = got.get("duty_kW") or 0.0  # the cold sides
    return total - (got.get("imbalance_kW") or 0.0), total


def run_duties(model: dict[str, Any], out: dict[str, Any]) -> list[dict[str, Any]]:
    """Every thermal duty of the run, from the units' results alone: ``{unit, unit_type, role,
    kW}`` (kW positive). Power is not heat: a machine's ``duty_kW`` is left out, its
    intercooling is not. A reboiler heated by another column's condenser is one exchange: the
    reboiler's duty, and of the condenser only what it gives beyond it (``condenser-excess``)."""
    units = out.get("units") or {}
    linked = {
        u["spec"]["heat_integration"]["condenser_of"]: u["id"]
        for u in model["units"]
        if (u.get("spec") or {}).get("heat_integration")
    }
    rows: list[dict[str, Any]] = []

    def add(u: dict[str, Any], role: str, kw: float | None) -> None:
        if kw is not None and abs(kw) > SMALL_KW:
            rows.append({"unit": u["id"], "unit_type": u["type"], "role": role, "kW": abs(kw)})

    for u in model["units"]:
        if u.get("internal"):
            continue
        uid, kind = u["id"], u["type"]
        got = units.get(uid) or {}
        if kind in MACHINES:
            add(u, "intercooling", got.get("cooling_kW"))
        elif kind in HEATED:
            add(u, "energy", got.get("duty_kW"))
        elif kind == "heat_exchanger":
            add(u, "exchange", got.get("duty_kW"))
        elif kind == "multi_stream_exchanger":
            hot, cold = _msx_groups(got)
            add(u, "exchange", min(hot, cold))
            add(u, "net", cold - hot)
        elif kind in COLUMNS:
            condenser = got.get("condenser_kW") or 0.0
            if uid in linked:
                other = (units.get(linked[uid]) or {}).get("reboiler_kW") or 0.0
                add(u, "condenser-excess", condenser - other)
            else:
                add(u, "condenser", condenser)
            add(u, "reboiler", got.get("reboiler_kW"))
        elif kind == "component_separator":
            add(u, "stated", got.get("duty_kW"))
        else:
            for key in HEAT_KEYS:
                add(u, key.removesuffix("_kW"), got.get(key))
    return rows


# -- extraction --------------------------------------------------------------------------------


def _segments(stream: PinchStream) -> tuple[Segment, ...]:
    return tuple(stream.profile)


def _notes_for(out: dict[str, Any], a: str | None, b: str | None) -> tuple[str, ...]:
    if not a or not b:
        return ()
    changes = _phase_changes(out, a, b)
    if changes:
        va, vb = _flow(out, a)["vapor_fraction"], _flow(out, b)["vapor_fraction"]
        return (
            f"{a} changes phase or is two-phase (vapour fraction {va:.3g} -> {vb:.3g}): "
            "linearised across it, not split at a dew or bubble point",
        )
    if changes is None:
        return ("vapour fractions not recorded: a phase change is not known",)
    return ()


def thermal_streams(
    model: dict[str, Any],
    out: dict[str, Any],
    case: str,
    *,
    process: Any = None,
    constrained: dict[str, str] | None = None,
) -> Extraction:
    """The thermal streams of *case*: *model* is the simulator model (``translate(...).model``),
    *out* the simulator's result (``units``, ``streams``), *process* the loaded flowsheet (for
    the utility terminals; without it no material stream is known as a utility and no terminal
    is named). *constrained* maps unit ids to the reason they are constrained; by default every
    reactor (:data:`REACTORS`, :data:`REACTOR_REASON`). See the module docstring."""
    ends, terminals = _ends(process), _terminals(process)
    units = out.get("units") or {}
    if constrained is None:
        constrained = {u["id"]: REACTOR_REASON for u in model["units"] if u["type"] in REACTORS}
    linked = {
        u["spec"]["heat_integration"]["condenser_of"]: u["id"]
        for u in model["units"]
        if (u.get("spec") or {}).get("heat_integration")
    }
    found: list[ThermalStream] = []

    def utility_of(u: dict[str, Any], role: str) -> str | None:
        stream = (u.get("energies") or {}).get(role)
        return ends.get(stream or "") or None

    for u in model["units"]:
        if u.get("internal"):
            continue
        uid, kind = u["id"], u["type"]
        got = units.get(uid) or {}
        base = {"unit": uid, "unit_type": kind, "case": case}
        if kind in MACHINES:
            cooling = abs(got.get("cooling_kW") or 0.0)
            if cooling > SMALL_KW:
                found.append(
                    ThermalStream(
                        id=f"{uid}:intercooling",
                        role="intercooling",
                        category="excluded",
                        quality="insufficient",
                        side="hot",
                        duty_kW=cooling,
                        duty_key=(uid, "intercooling"),
                        counted_kW=cooling,
                        reason="a compressor train's intercooling: the simulator reports no "
                        "intercooler temperatures",
                        **base,
                    )
                )
        elif kind in HEATED:
            found += _heated(u, got, out, base, constrained, utility_of(u, "energy"))
        elif kind == "heat_exchanger":
            found += _exchanger(u, got, out, base, ends, terminals)
        elif kind == "multi_stream_exchanger":
            found += _multi_stream(u, got, out, base)
        elif kind in COLUMNS:
            found += _column(u, got, out, base, linked, utility_of)
        elif kind == "component_separator":
            q = abs(got.get("duty_kW") or 0.0)
            if q > SMALL_KW:
                found.append(
                    ThermalStream(
                        id=f"{uid}:stated",
                        role="stated",
                        category="excluded",
                        quality="insufficient",
                        side=None,
                        duty_kW=q,
                        duty_key=(uid, "stated"),
                        counted_kW=q,
                        reason="a specified split's stated energy imbalance (ADR 0038), not a "
                        "heat duty",
                        **base,
                    )
                )
    return Extraction(case, found, reconcile(run_duties(model, out), found))


def _heated(u, got, out, base, constrained, utility) -> list[ThermalStream]:
    uid = u["id"]
    q = got.get("duty_kW")
    if q is None or abs(q) <= SMALL_KW:
        return []
    heated = q > 0
    a = u["inlets"][0] if u["inlets"] else None
    b = u["outlets"][0] if u["outlets"] else None
    t_in, t_out = _temperature(out, a), _temperature(out, b)
    category: Category = "constrained" if uid in constrained else "utility"
    reason = constrained.get(uid, "")
    common = {
        "id": uid,
        "role": "energy",
        "side": "cold" if heated else "hot",
        "duty_kW": abs(q),
        "supply_K": t_in,
        "target_K": t_out,
        "duty_key": (uid, "energy"),
        "counted_kW": abs(q),
        "utility": utility if category == "utility" else None,
        "streams": tuple(s for s in (a, b) if s),
        **base,
    }
    if t_in is None or t_out is None:
        missing = [s for s, t in ((a, t_in), (b, t_out)) if t is None]
        return [
            ThermalStream(
                category="excluded",
                quality="insufficient",
                reason=f"no temperature of {', '.join(str(m) for m in missing)}"
                + (f"; {reason}" if reason else ""),
                **common,
            )
        ]
    if abs(t_in - t_out) > SMALL_DT and (t_out > t_in) != heated:
        return [
            ThermalStream(
                category="excluded",
                quality="insufficient",
                reason=f"the temperature runs against the duty ({t_in:.2f} -> {t_out:.2f} K while "
                f"heat is {'added' if heated else 'removed'}: a flash or pressure change); not "
                "one heated or cooled stream" + (f"; {reason}" if reason else ""),
                **common,
            )
        ]
    stream = side(t_in, t_out, abs(q), uid, "cold" if heated else "hot")
    return [
        ThermalStream(
            category=category,
            quality="linearised",
            segments=_segments(stream),
            reason=reason,
            notes=_notes_for(out, a, b),
            **common,
        )
    ]


def _is_utility(stream: str, ends: dict[str, str], terminals: dict[str, Any]) -> bool:
    terminal = terminals.get(ends.get(stream, ""))
    return getattr(terminal, "category", None) == "utility"


def _exchanger(u, got, out, base, ends, terminals) -> list[ThermalStream]:
    """A two-stream exchanger: both sides as recovery streams (the hot side counts the duty), or
    the process side against a utility stream (a waste-heat boiler, a steam heater) as one
    utility stream; the utility side is not a stream."""
    uid = u["id"]
    q = abs(got.get("duty_kW") or 0.0)
    if q <= SMALL_KW:
        return []
    pairs = list(zip(u["inlets"], u["outlets"], strict=False))
    sides = []
    for a, b in pairs:
        ha, hb = _enthalpy_flow(out, a), _enthalpy_flow(out, b)
        duty = abs(hb - ha) if ha is not None and hb is not None else q
        sides.append((a, b, _temperature(out, a), _temperature(out, b), duty))
    utility_sides = [s for s in sides if _is_utility(s[0], ends, terminals)]
    process_sides = [s for s in sides if s not in utility_sides]
    if not process_sides:
        return [
            ThermalStream(
                id=uid,
                role="exchange",
                category="excluded",
                quality="insufficient",
                side=None,
                duty_kW=q,
                duty_key=(uid, "exchange"),
                counted_kW=q,
                reason="both sides are utility streams: no process stream",
                **base,
            )
        ]
    temps_known = all(s[2] is not None and s[3] is not None for s in sides)
    # which process side is hot: the one whose temperature falls, else the hotter inlet
    out_sides: list[ThermalStream] = []
    hot_inlet = None
    if temps_known:
        falling = [s for s in sides if s[2] - s[3] > SMALL_DT]
        rising = [s for s in sides if s[3] - s[2] > SMALL_DT]
        if falling:
            hot_inlet = falling[0][0]
        elif rising:
            hot_inlet = next(s[0] for s in sides if s not in rising)
        else:
            hot_inlet = max(sides, key=lambda s: s[2])[0]
    if utility_sides:
        a, b, t_in, t_out, duty = process_sides[0]
        terminal = ends.get(utility_sides[0][0])
        # the process side's own temperatures say which it is; isothermal: the utility's
        hot_inlet = None
        if t_in is not None and t_out is not None:
            ua, _, ut_in, ut_out, _ = utility_sides[0]
            if t_in - t_out > SMALL_DT:
                hot_inlet = a
            elif t_out - t_in > SMALL_DT:
                hot_inlet = ua
            elif ut_in is not None and ut_out is not None and abs(ut_in - ut_out) > SMALL_DT:
                hot_inlet = ua if ut_in > ut_out else a
        temps_known = hot_inlet is not None
        common = {
            "id": f"{uid}:{a}",
            "role": "exchange",
            "duty_kW": duty,
            "supply_K": t_in,
            "target_K": t_out,
            "duty_key": (uid, "exchange"),
            "counted_kW": duty,
            "streams": (a, b),
            "utility": terminal,
            **base,
        }
        if not temps_known or hot_inlet is None:
            return [
                ThermalStream(
                    category="excluded",
                    quality="insufficient",
                    side=None,
                    reason="the process side's temperatures are missing, or neither side's "
                    "temperature changes",
                    **common,
                )
            ]
        hot = a == hot_inlet
        stream = side(t_in, t_out, duty, common["id"], "hot" if hot else "cold")
        return [
            ThermalStream(
                category="utility",
                quality="linearised",
                side="hot" if hot else "cold",
                segments=_segments(stream),
                notes=(
                    f"the other side ({utility_sides[0][0]}) is utility {terminal}: not a "
                    "second stream",
                    *_notes_for(out, a, b),
                ),
                **common,
            )
        ]
    for a, b, t_in, t_out, duty in sides:
        hot = a == hot_inlet
        common = {
            "id": f"{uid}:{a}",
            "role": "exchange",
            "duty_kW": duty,
            "supply_K": t_in,
            "target_K": t_out,
            "duty_key": (uid, "exchange"),
            "streams": (a, b),
            **base,
        }
        if not temps_known or hot_inlet is None:
            out_sides.append(
                ThermalStream(
                    category="excluded",
                    quality="insufficient",
                    side=None,
                    counted_kW=duty if a == sides[0][0] else 0.0,
                    reason="a side's inlet or outlet temperature is missing: the exchanger is "
                    "left out (one side alone would look like a utility demand)",
                    **common,
                )
            )
            continue
        stream = side(t_in, t_out, duty, common["id"], "hot" if hot else "cold")
        out_sides.append(
            ThermalStream(
                category="recovery",
                quality="linearised",
                side="hot" if hot else "cold",
                segments=_segments(stream),
                counted_kW=duty if hot else 0.0,
                notes=(
                    ("counts the exchanger's duty" if hot else "the same heat as the hot side"),
                    *_notes_for(out, a, b),
                ),
                **common,
            )
        )
    return out_sides


def _multi_stream(u, got, out, base) -> list[ThermalStream]:
    """Every side of a multi-stream exchanger as a recovery stream; the smaller of the hot and
    the cold group counts the exchanged duty, the net imbalance is excluded."""
    uid = u["id"]
    duties = got.get("side_duties_kW") or []
    found: list[ThermalStream] = []
    hot, cold = _msx_groups(got)
    hot_counts = hot <= cold
    pairs = list(zip(u["inlets"], u["outlets"], strict=False))
    if len(duties) != len(pairs):
        duties = []
        for a, b in pairs:
            ha, hb = _enthalpy_flow(out, a), _enthalpy_flow(out, b)
            duties.append(None if ha is None or hb is None else hb - ha)
    for (a, b), d in zip(pairs, duties, strict=False):
        t_in, t_out = _temperature(out, a), _temperature(out, b)
        if d is None or abs(d) <= SMALL_KW:
            continue
        is_hot = d < 0
        counts = is_hot == hot_counts
        common = {
            "id": f"{uid}:{a}",
            "role": "exchange",
            "duty_kW": abs(d),
            "supply_K": t_in,
            "target_K": t_out,
            "side": "hot" if is_hot else "cold",
            "duty_key": (uid, "exchange"),
            "counted_kW": abs(d) if counts else 0.0,
            "streams": (a, b),
            **base,
        }
        if t_in is None or t_out is None:
            found.append(
                ThermalStream(
                    category="excluded",
                    quality="insufficient",
                    reason="a side's inlet or outlet temperature is missing",
                    **common,
                )
            )
            continue
        stream = side(t_in, t_out, abs(d), common["id"], "hot" if is_hot else "cold")
        found.append(
            ThermalStream(
                category="recovery",
                quality="linearised",
                segments=_segments(stream),
                notes=_notes_for(out, a, b),
                **common,
            )
        )
    net = cold - hot
    if abs(net) > SMALL_KW:
        found.append(
            ThermalStream(
                id=f"{uid}:net",
                role="net",
                category="excluded",
                quality="insufficient",
                side=None,
                duty_kW=abs(net),
                duty_key=(uid, "net"),
                counted_kW=abs(net),
                reason="the multi-stream exchanger's net imbalance (heat its sides do not "
                "balance): no stream carries it",
                **base,
            )
        )
    return found


def _column(u, got, out, base, linked, utility_of) -> list[ThermalStream]:
    """A column's condenser (hot) and reboiler (cold), isothermal. A reboiler heated by another
    column's condenser and that condenser are recovery; the reboiler counts the exchange."""
    uid = u["id"]
    found: list[ThermalStream] = []
    by_role = {d.role: d for d in process_duties(u, got, out)}
    link = (u.get("spec") or {}).get("heat_integration")
    units = out.get("units") or {}
    for role, key, hot in (("condenser", "condenser_kW", True), ("reboiler", "reboiler_kW", False)):
        kw = abs(got.get(key) or 0.0)
        if kw <= SMALL_KW:
            continue
        recovery = (role == "reboiler" and bool(link)) or (role == "condenser" and uid in linked)
        duty_key = (uid, role)
        counted = kw
        notes: list[str] = []
        if role == "condenser" and uid in linked:
            other = (units.get(linked[uid]) or {}).get("reboiler_kW") or 0.0
            duty_key = (uid, "condenser-excess")
            counted = max(kw - other, 0.0)
            notes.append(f"heats {linked[uid]}'s reboiler: the same heat as that reboiler")
        if role == "reboiler" and link:
            notes.append(f"heated by {link['condenser_of']}'s condenser")
        found_duty = by_role.get(role)
        basis_note = {
            "stage": f"isothermal at the column's {'top' if hot else 'bottom'} stage temperature",
            "product": (
                f"isothermal at the {'distillate' if hot else 'bottoms'} temperature (a shortcut "
                "column reports no stage temperatures)"
            ),
        }
        common = {
            "id": f"{uid}:{role}",
            "role": role,
            "side": "hot" if hot else "cold",
            "duty_kW": kw,
            "duty_key": duty_key,
            "counted_kW": counted,
            "utility": None if recovery else utility_of(u, role),
            **base,
        }
        if found_duty is None:
            found.append(
                ThermalStream(
                    category="excluded",
                    quality="insufficient",
                    reason=f"no {'top' if hot else 'bottom'} temperature reported",
                    notes=tuple(notes),
                    **common,
                )
            )
            continue
        t = found_duty.stream.supply_temperature
        found.append(
            ThermalStream(
                category="recovery" if recovery else "utility",
                quality="linearised",
                supply_K=t,
                target_K=t,
                segments=_segments(found_duty.stream),
                notes=(basis_note[found_duty.basis], *notes),
                **common,
            )
        )
    return found


def reconcile(duties: list[dict[str, Any]], streams: list[ThermalStream]) -> Reconciliation:
    """The streams' counted duties against the run's (:func:`run_duties`): per duty the class
    it was put in, what the streams account for and the residual; per class the sums. A duty
    whose residual exceeds :func:`duty_tolerance`, or that no stream accounts for, is left
    over."""
    rows: list[dict[str, Any]] = []
    by_class = dict.fromkeys(CATEGORIES, 0.0)
    leftover = []
    for d in duties:
        key = (d["unit"], d["role"])
        mine = [s for s in streams if s.duty_key == key]
        counted = sum(s.counted_kW for s in mine)
        classes = sorted({s.category for s in mine})
        tol = duty_tolerance(d["kW"])
        residual = d["kW"] - counted
        row = {
            **d,
            "class": classes[0] if len(classes) == 1 else (classes or None),
            "streams": [s.id for s in mine],
            "counted_kW": counted,
            "residual_kW": residual,
            "tolerance_kW": tol,
            "closed": bool(mine) and abs(residual) <= tol,
        }
        rows.append(row)
        if len(classes) == 1:
            by_class[classes[0]] += counted
        elif mine:
            for s in mine:
                by_class[s.category] += s.counted_kW
        if not row["closed"]:
            leftover.append(
                {
                    "unit": d["unit"],
                    "role": d["role"],
                    "kW": d["kW"],
                    "residual_kW": residual,
                    "reason": "no stream accounts for it"
                    if not mine
                    else f"the streams account for {counted:.6g} of {d['kW']:.6g} kW",
                }
            )
    # a stream counting for a duty the run does not have
    known = {(d["unit"], d["role"]) for d in duties}
    for s in streams:
        if s.counted_kW > SMALL_KW and s.duty_key not in known:
            leftover.append(
                {
                    "unit": s.unit,
                    "role": s.duty_key[1],
                    "kW": 0.0,
                    "residual_kW": -s.counted_kW,
                    "reason": f"{s.id} counts {s.counted_kW:.6g} kW for a duty the run does not "
                    "have",
                }
            )
    total = sum(d["kW"] for d in duties)
    accounted = sum(by_class.values())
    return Reconciliation(rows, by_class, total, accounted, total - accounted, leftover)


# -- the flowsheet's terminals ------------------------------------------------------------------


def _ends(process: Any) -> dict[str, str]:
    """Stream id -> the terminal at its other end (feed or product id); empty without a
    process."""
    if process is None:
        return {}
    fs = process.flowsheet
    feeds = {t.id for t in fs.feeds}
    products = {t.id for t in fs.products}
    found = {}
    for s in fs.streams:
        a, b = s.from_.split(".")[0], s.to.split(".")[0]
        if a in feeds:
            found[s.id] = a
        elif b in products:
            found[s.id] = b
    return found


def _terminals(process: Any) -> dict[str, Any]:
    if process is None:
        return {}
    fs = process.flowsheet
    return {t.id: t for t in [*fs.feeds, *fs.products]}


# -- a recorded run ----------------------------------------------------------------------------


def out_from_record(entry: dict[str, Any], model: dict[str, Any]) -> dict[str, Any]:
    """The simulator result (``units``, ``streams`` with ``temperature_K``) rebuilt from a run
    record entry (``process/simulation-run.json``): the units' recorded results and the
    streams' recorded temperatures, the feeds' from the model. The record keeps no stream
    enthalpies or vapour fractions: an exchanger's sides then take its duty, and a phase change
    is not known (``notes``)."""
    from chemeascode.foundation.units import to_kelvin

    units = {
        row["id"]: dict(row.get("results") or {})
        for row in entry.get("units") or []
        if row.get("status") == "simulated"
    }
    streams: dict[str, dict[str, Any]] = {}
    for s in model.get("streams") or []:
        feed = s.get("feed") or {}
        if feed.get("temperature_K") is not None:
            streams[s["id"]] = {"temperature_K": feed["temperature_K"]}
    for row in entry.get("streams") or []:
        t = (row.get("values") or {}).get("temperature")
        if not t or t.get("value") is None:
            continue
        kelvin = to_kelvin(t["value"], t.get("unit") or "K")
        if kelvin is not None:
            streams.setdefault(row["id"], {})["temperature_K"] = kelvin
    return {"converged": entry.get("converged", False), "units": units, "streams": streams}
