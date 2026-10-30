"""``control/cause-effect.yaml``: interlocks and trips as a cause-and-effect list;
``control/loops.yaml``: the regulatory control loops; ``control/sequences.yaml``: startup,
shutdown and abnormal-mode sequences with their permissives; the front matter of
``process/narrative.md`` and ``control/philosophy.md``;
``electrical/electrical-list.yaml``: substations, rooms, the motor list, junction boxes.

The conventions of the control records (docs/framework/control.md):

- a controller's ``action`` is ``direct`` when its output rises as the measurement rises,
  ``reverse`` when it falls; it says nothing about the valve;
- a final element's ``fail`` is the position it takes on loss of signal, power or motive air
  (``open``, ``closed``, ``last``; a drive ``stop``, a heater ``off``), independent of the
  controller's action;
- controller output 0 to 100 % moves a final element over ``travel`` (default 0 to 100 %: an
  increasing output opens a valve, speeds up a drive, raises a heater's duty); a split range
  gives each element the ``range`` of the output it acts on;
- a value left out (``action``, ``fail``, a target's ``value``) is not known yet, never a
  default: ``cheme validate`` reports it as ``cheme.control-incomplete`` (info) until it is
  given, and a stage gate decides when it must be.
"""

import re
from typing import Literal

from pydantic import Field, field_validator, model_validator

from chemeascode.foundation.schema_base import (
    Identifier,
    Origin,
    Provenance,
    Strict,
    optional_schema,
)
from chemeascode.foundation.schemas.reviews import Basis

Action = Literal["trip", "stop", "start", "close", "open", "depressurize", "alarm"]


# ---------------------------------------------------------------------------
# Conditions (interlock logic, permissives, sequence steps)
# ---------------------------------------------------------------------------


class Amount(Strict):
    """A value with its unit, e.g. a delay of 5 s or a dead band of 2 %."""

    value: float = Field(ge=0)
    unit: str = Field(min_length=1, description="e.g. s, min, %, K, bar.")


class Vote(Strict):
    """``k`` out of the conditions ``of`` (2oo3: ``{k: 2, of: [a, b, c]}``)."""

    k: int = Field(ge=1)
    of: list["Condition"] = Field(min_length=2)

    @model_validator(mode="after")
    def _check(self) -> "Vote":
        if self.k > len(self.of):
            raise ValueError(f"vote: k = {self.k} is more than the {len(self.of)} conditions")
        return self


class Condition(Strict):
    """A condition: one item in a state, or ``all``/``any``/``vote`` of conditions. Logic the
    format does not model is written as ``text`` (reported, never interpreted); a condition
    not known yet is ``unresolved``. Exactly one of item, ``all``, ``any``, ``vote``,
    ``text`` and ``unresolved``; an item is one of ``tag``, ``loop``, ``interlock``,
    ``sequence`` or ``step`` (a step of the same sequence) with its ``state``."""

    tag: Identifier | None = Field(
        default=None, description="An instrument or equipment tag, e.g. LT-101."
    )
    loop: Identifier | None = Field(default=None, description="A loop id of control/loops.yaml.")
    interlock: Identifier | None = Field(
        default=None, description="An interlock id of control/cause-effect.yaml."
    )
    sequence: Identifier | None = Field(
        default=None, description="A sequence id of control/sequences.yaml."
    )
    step: Identifier | None = Field(default=None, description="A step of the same sequence.")
    state: str = Field(
        default="",
        description="The state of the item, e.g. LAH, running, closed, 'in auto', '> 40 %', "
        "healthy, reset, complete.",
    )
    all_: list["Condition"] | None = Field(default=None, alias="all", min_length=1)
    any_: list["Condition"] | None = Field(default=None, alias="any", min_length=1)
    vote: Vote | None = None
    text: str | None = Field(
        default=None, description="Logic the format does not model, in words (not checked)."
    )
    unresolved: str | None = Field(
        default=None, description="Not known yet: what is missing (a draft finding)."
    )
    delay: Amount | None = Field(
        default=None, description="The condition must hold this long (on-delay)."
    )
    deadband: Amount | None = Field(
        default=None, description="Hysteresis: how far it must come back before it clears."
    )

    @model_validator(mode="after")
    def _one(self) -> "Condition":
        items = [n for n in ("tag", "loop", "interlock", "sequence", "step") if getattr(self, n)]
        forms = len(items) > 0, self.all_ is not None, self.any_ is not None
        forms += self.vote is not None, self.text is not None, self.unresolved is not None
        if len(items) > 1:
            raise ValueError(f"a condition names one item, not {' and '.join(items)}")
        if sum(forms) != 1:
            raise ValueError(
                "give exactly one of an item (tag, loop, interlock, sequence or step with its "
                "state), all, any, vote, text or unresolved"
            )
        return self


Vote.model_rebuild()


class Cause(Strict):
    """What starts the interlock: an instrument and the condition, e.g. LIA-4108 at LALL."""

    tag: Identifier = Field(description="Printed instrument tag (or another tag), e.g. LIA-4108.")
    condition: str = Field(default="", description="e.g. LALL, HH, TSHH, 'loss of seal gas'.")


class Effect(Strict):
    """What the interlock does to one item."""

    tag: Identifier = Field(description="Equipment, valve or instrument tag, e.g. XV-4137.")
    action: Action


class Interlock(Strict):
    """One interlock (a candidate safety instrumented function)."""

    id: Identifier = Field(
        description="Interlock id, e.g. I-07; sheets refer to it ('see C&E I-07')."
    )
    title: str = ""
    cause: Cause
    effects: list[Effect] = Field(min_length=1)
    sheet: str | None = None
    sil: Literal[0, 1, 2, 3, 4, "a"] | None = Field(
        default=None,
        description="SIL from screening, if done (IEC 61511): 1 to 4; 0 or 'a' for a function "
        "screened without a SIL requirement. 'SIL 2' is read as 2, an empty string as none.",
    )
    logic: Condition | None = Field(
        default=None,
        description="The trip condition when it is more than the cause alone: all/any/vote of "
        "conditions (2oo3), with delays; the cause stays the row of the matrix.",
    )
    delay: Amount | None = Field(default=None, description="Trip delay (on-delay of the cause).")
    latching: bool | None = Field(
        default=None, description="True: the trip stays until reset; omitted: not stated yet."
    )
    reset: Literal["manual", "automatic"] | None = Field(
        default=None, description="How the trip is reset once the cause has cleared."
    )
    bypass: str | None = Field(
        default=None,
        description="Whether and how the trip may be bypassed or inhibited (e.g. a startup "
        "override with a timer and a permit); not a log of bypasses.",
    )
    notes: str = ""

    @field_validator("sil", mode="before")
    @classmethod
    def _sil(cls, value: object) -> object:
        """``SIL 2``, ``SIL-2``, ``sil2`` and ``"2"`` are 2; ``A`` is ``a``; an empty string is
        no SIL. Any other text is refused as written; a number is left to the type, which
        refuses one out of range (a bool too, never read as 0 or 1)."""
        if isinstance(value, bool):
            raise ValueError("a SIL: 0 to 4 or 'a'")
        if isinstance(value, str):
            text = re.sub(r"^sil\s*-?\s*", "", value.strip(), flags=re.IGNORECASE)
            if not value.strip():
                return None
            if text.lower() == "a":
                return "a"
            if text.isascii() and text.isdecimal() and int(text) <= 4:
                return int(text)
            raise ValueError(f"{value!r} is no SIL: 0 to 4 or 'a' ('SIL 2' is read as 2)")
        return value


class InterlockList(Strict, optional_schema("interlocks")):
    """The cause-and-effect list of the plant."""

    interlocks: list[Interlock] = Field(default_factory=list)


# ---------------------------------------------------------------------------
# control/loops.yaml (kind ``loops``)
# ---------------------------------------------------------------------------

#: What a loop controls.
Variable = Literal[
    "flow", "level", "temperature", "pressure", "composition", "speed", "ratio", "other"
]
#: The modes of a controller.
ControlMode = Literal["manual", "auto", "cascade"]
#: How a step or a mode change is made.
By = Literal["operator", "automatic"]


class Target(Strict):
    """A setpoint or a limit of a loop, a sequence or an alarm, with its unit and provenance.
    ``value`` omitted: not known yet (say why in ``unresolved``). ``stream`` and ``property``
    name the operating-case value it is: ``cheme validate`` compares the two."""

    kind: Literal["setpoint", "low", "high"] = "setpoint"
    value: float | None = None
    unit: str | None = Field(default=None, description="Required with a value (%, kg/h, °C).")
    provenance: Provenance | None = Field(default=None, description="Required with a value.")
    source: str = ""
    origin: Origin | None = None
    modes: list[str] = Field(
        default_factory=list,
        description="Operating modes it applies in (normal, startup, turndown, ...); empty: all.",
    )
    cases: list[Identifier] = Field(
        default_factory=list,
        description="Operating cases (process/flowsheet.yaml cases[].id) it applies to.",
    )
    stream: Identifier | None = Field(
        default=None, description="The flowsheet stream whose case value it is."
    )
    property: Literal["flow", "temperature", "pressure"] | None = Field(
        default=None, description="Which value of the stream (with stream)."
    )
    unresolved: str | None = Field(default=None, description="Why the value is not known yet.")

    @model_validator(mode="after")
    def _check(self) -> "Target":
        if (self.stream is None) != (self.property is None):
            raise ValueError("give stream and property together")
        return self


class Measurement(Strict):
    """A measurement of the controlled variable."""

    tag: Identifier = Field(description="Instrument tag, e.g. FT-101.")
    role: str = Field(default="", description="e.g. primary, compensation, redundant.")


class FinalElement(Strict):
    """What the controller output moves: a valve, a drive, a heater."""

    tag: Identifier = Field(description="Valve, drive or heater tag, e.g. FV-101, P-101A.")
    kind: Literal["valve", "drive", "heater", "damper", "other"] | None = None
    actuator: Literal["pneumatic", "electric", "hydraulic", "other"] | None = None
    fail: Literal["open", "closed", "last", "stop", "off"] | None = Field(
        default=None,
        description="Position on loss of signal, power or air; omitted: not known yet.",
    )
    range: tuple[float, float] | None = Field(
        default=None, description="Split range: the controller output, %, it acts on."
    )
    travel: tuple[float, float] | None = Field(
        default=None,
        description="Its travel, %, over the range (default [0, 100]; [100, 0]: it closes as "
        "the output rises).",
    )

    @field_validator("fail", mode="before")
    @classmethod
    def _off(cls, value: object) -> object:
        """YAML 1.1 reads a bare ``off`` as false: ``fail: off`` means ``off``."""
        return "off" if value is False else value

    @field_validator("range", "travel")
    @classmethod
    def _percent(cls, value: tuple[float, float] | None) -> tuple[float, float] | None:
        if value is not None and not all(0 <= v <= 100 for v in value):
            raise ValueError("a percentage from 0 to 100")
        if value is not None and value[0] == value[1]:
            raise ValueError("the two ends must differ")
        return value


class LoopLink(Strict):
    """How another loop or a measurement acts on this loop. ``cascade``: the output of
    ``loop`` (the master) is this loop's setpoint. ``ratio``: the setpoint is ``ratio`` times
    the flow of ``loop`` or ``tag``. ``feedforward``: the measured disturbance ``tag`` (or
    ``loop``'s measurement) adds to the output. ``override``: this loop and ``loop`` drive the
    same final element through a ``select`` (low or high) selector."""

    type: Literal["cascade", "ratio", "feedforward", "override"]
    loop: Identifier | None = None
    tag: Identifier | None = None
    select: Literal["low", "high"] | None = Field(default=None, description="Override only.")
    ratio: float | None = Field(default=None, gt=0, description="Ratio only.")
    notes: str = ""

    @model_validator(mode="after")
    def _check(self) -> "LoopLink":
        if (self.loop is None) == (self.tag is None):
            raise ValueError(f"{self.type}: give the loop or the tag it comes from, one of them")
        if self.type in ("cascade", "override") and self.loop is None:
            raise ValueError(f"{self.type}: give the loop")
        return self


class ModeTransition(Strict):
    """A change of controller mode and when it is made."""

    from_: ControlMode = Field(alias="from")
    to: ControlMode
    by: By | None = None
    condition: Condition | None = None
    notes: str = ""


class Alarm(Strict):
    """A process alarm of the loop and what the operator does on it. A trip belongs in the
    cause and effect list, not here."""

    tag: Identifier = Field(description="Instrument tag, e.g. LT-101 or LAH-101.")
    condition: str = Field(min_length=1, description="e.g. LAH, PAL, 'deviation'.")
    limit: Target | None = None
    priority: str | None = None
    response: str = Field(default="", description="What the operator does.")


class Loop(Strict):
    """One regulatory control loop. It is not a safeguard: protective functions are the
    interlocks of the cause and effect list, which ``interlocks`` refers to."""

    id: Identifier = Field(description="Stable loop id, usually the loop tag (FIC-101).")
    title: str = ""
    purpose: str = ""
    section: Identifier | None = Field(
        default=None, description="Process section id of process/narrative.md."
    )
    cases: list[Identifier] = Field(
        default_factory=list, description="Operating cases it is designed for."
    )
    variable: Variable | None = Field(default=None, description="What it controls.")
    measurement: list[Measurement] = Field(default_factory=list)
    controller: Identifier | None = Field(
        default=None, description="Controller tag where the P&ID shows one (FIC-101)."
    )
    action: Literal["direct", "reverse"] | None = Field(
        default=None, description="Controller action; omitted: not known yet."
    )
    final_elements: list[FinalElement] = Field(default_factory=list)
    targets: list[Target] = Field(default_factory=list)
    modes: list[ControlMode] = Field(
        default_factory=list, description="The modes it has (manual, auto, cascade)."
    )
    normal_mode: ControlMode | None = None
    transitions: list[ModeTransition] = Field(default_factory=list)
    links: list[LoopLink] = Field(default_factory=list)
    alarms: list[Alarm] = Field(default_factory=list)
    interlocks: list[Identifier] = Field(
        default_factory=list, description="Related interlocks of control/cause-effect.yaml."
    )
    rationale: str = Field(default="", description="Why this loop, this pairing, these modes.")
    operator: str = Field(default="", description="Judgement the operator has to make.")
    unresolved: list[str] = Field(
        default_factory=list, description="What is still open (a draft finding each)."
    )
    notes: str = ""


class LoopList(Strict, optional_schema("loops")):
    """The control loop register: regulatory loops.

    Each with its measurements, final elements, targets, modes and links."""

    loops: list[Loop] = Field(default_factory=list)
    basis: list[Basis] = Field(
        default_factory=list,
        description="Engineering inputs the register rests on, each at the revision used; a "
        "changed one is cheme.control-stale.",
    )
    notes: str = ""


# ---------------------------------------------------------------------------
# control/sequences.yaml (kind ``sequences``)
# ---------------------------------------------------------------------------


class SequenceAction(Strict):
    """One action of a step: a tag started, stopped, opened or closed; a loop put in a mode
    or given a setpoint; another sequence run; or ``text`` (not modelled)."""

    tag: Identifier | None = None
    loop: Identifier | None = None
    sequence: Identifier | None = None
    text: str | None = None
    action: (
        Literal["start", "stop", "open", "close", "manual", "auto", "cascade", "setpoint", "run"]
        | None
    ) = None
    setpoint: Target | None = Field(default=None, description="action: setpoint.")
    by: By | None = None

    @model_validator(mode="after")
    def _check(self) -> "SequenceAction":
        given = [n for n in ("tag", "loop", "sequence", "text") if getattr(self, n) is not None]
        if len(given) != 1:
            raise ValueError("give one of tag, loop, sequence or text")
        allowed = {
            "tag": {"start", "stop", "open", "close"},
            "loop": {"manual", "auto", "cascade", "setpoint"},
            "sequence": {"run"},
            "text": {None},
        }[given[0]]
        if self.action not in allowed:
            shown = ", ".join(sorted(a for a in allowed if a)) or "no action"
            raise ValueError(f"{given[0]}: action {self.action!r} is not one of {shown}")
        if (self.action == "setpoint") != (self.setpoint is not None):
            raise ValueError("action setpoint takes a setpoint, and only it does")
        return self


class Step(Strict):
    """One step of a sequence: entered when ``entry`` holds (and the step before is
    complete), its actions made, done when ``complete`` holds."""

    id: Identifier
    title: str = ""
    entry: Condition | None = None
    actions: list[SequenceAction] = Field(default_factory=list)
    complete: Condition | None = None
    timeout: Amount | None = None
    on_timeout: Identifier | None = Field(
        default=None, description="A step id, or abort, when the step times out."
    )
    next: Identifier | None = Field(
        default=None, description="The next step (default: the one below; end: the last)."
    )
    operator: str = Field(default="", description="Instructions and judgement for the operator.")
    notes: str = ""


class Abort(Strict):
    """What happens when the sequence is aborted: on ``condition``, on a trip of one of the
    sequence's interlocks, or by the operator."""

    condition: Condition | None = None
    actions: list[SequenceAction] = Field(default_factory=list)
    then: Identifier | None = Field(default=None, description="A sequence to run next.")
    notes: str = ""


class Reset(Strict):
    """Reset and restart after an abort or a trip."""

    latching: bool | None = Field(
        default=None, description="True: the abort stays until reset; omitted: not stated."
    )
    manual: bool | None = Field(default=None, description="True: the operator resets it.")
    condition: Condition | None = Field(default=None, description="What must hold to reset.")
    restart: Condition | None = Field(default=None, description="What must hold to restart.")


class Sequence(Strict):
    """A startup, shutdown or abnormal-mode sequence. Start ``permissives`` are separate from
    trips: the trips are the C&E interlocks named in ``interlocks``, not repeated here."""

    id: Identifier
    title: str = ""
    mode: Literal["startup", "shutdown", "abnormal", "normal", "other"]
    section: Identifier | None = Field(default=None, description="Section of the narrative.")
    cases: list[Identifier] = Field(default_factory=list)
    equipment: list[Identifier] = Field(default_factory=list, description="Tags it operates.")
    permissives: list[Condition] = Field(
        default_factory=list, description="What must hold before it may start."
    )
    interlocks: list[Identifier] = Field(
        default_factory=list, description="C&E interlocks that protect it (by id)."
    )
    steps: list[Step] = Field(default_factory=list)
    abort: Abort | None = None
    reset: Reset | None = None
    unresolved: list[str] = Field(default_factory=list)
    notes: str = ""


class SequenceList(Strict, optional_schema("sequences")):
    """Operating sequences: startup, shutdown, abnormal modes.

    Each with its permissives, steps, abort and reset behaviour."""

    sequences: list[Sequence] = Field(default_factory=list)
    basis: list[Basis] = Field(default_factory=list, description="As in control/loops.yaml.")
    notes: str = ""


# ---------------------------------------------------------------------------
# process/narrative.md and control/philosophy.md (front matter)
# ---------------------------------------------------------------------------


class Section(Strict):
    """A process section of the narrative: a heading ``## <id> <title>`` in its body."""

    id: Identifier
    title: str = ""
    equipment: list[Identifier] = Field(default_factory=list, description="Its tags.")
    blocks: list[Identifier] = Field(
        default_factory=list, description="Its blocks or steps of process/flowsheet.yaml."
    )
    cases: list[Identifier] = Field(default_factory=list)
    modes: list[str] = Field(default_factory=list, description="normal, startup, shutdown, ...")
    loops: list[Identifier] = Field(default_factory=list)
    sequences: list[Identifier] = Field(default_factory=list)
    interlocks: list[Identifier] = Field(default_factory=list)


class Narrative(Strict, optional_schema("narrative")):
    """Process narrative: the sections the text describes."""

    sections: list[Section] = Field(default_factory=list)
    basis: list[Basis] = Field(default_factory=list)
    unresolved: list[str] = Field(default_factory=list)


class Failure(Strict):
    """An equipment or utility failure and the designed response."""

    id: Identifier
    title: str = Field(min_length=1, description="e.g. loss of instrument air.")
    response: str = ""
    loops: list[Identifier] = Field(default_factory=list)
    sequences: list[Identifier] = Field(default_factory=list)
    interlocks: list[Identifier] = Field(default_factory=list)


class Objective(Strict):
    id: Identifier
    title: str = Field(min_length=1)
    loops: list[Identifier] = Field(default_factory=list)


class Philosophy(Strict, optional_schema("control_philosophy")):
    """Control philosophy: objectives and failures the text describes.

    By id, with the loops, sequences and interlocks they rest on."""

    objectives: list[Objective] = Field(default_factory=list)
    failures: list[Failure] = Field(default_factory=list)
    basis: list[Basis] = Field(default_factory=list)
    unresolved: list[str] = Field(default_factory=list)


# ---------------------------------------------------------------------------
# electrical/electrical-list.yaml (kind ``electrical``)
# ---------------------------------------------------------------------------

Point3 = tuple[float, float, float]
#: What an electrical room holds: low-voltage motor control centre, medium-voltage switchgear,
#: the control room (the DCS marshalling the instrument cables end at) or a rack room.
RoomKind = Literal["mcc", "switchgear", "control", "rack_room"]


class Substation(Strict):
    """A substation: where the plant's supply is transformed, in a building of the layout."""

    id: Identifier
    title: str = ""
    building: str | None = Field(default=None, description="Its building in layout/building.yaml.")
    incoming_kv: float | None = Field(default=None, gt=0, description="Supply voltage, kV.")
    notes: str = ""


class Transformer(Strict):
    """A power transformer of a substation."""

    tag: Identifier
    substation: str | None = Field(default=None, description="Substation id it stands in.")
    rating_kva: float | None = Field(default=None, gt=0)
    primary_kv: float | None = Field(default=None, gt=0)
    secondary_v: float | None = Field(default=None, gt=0)
    feeds: list[str] = Field(default_factory=list, description="Room ids it supplies.")
    notes: str = ""


class Room(Strict):
    """An electrical room, a part of a building of the layout: the cables of its kind start
    there. ``point``: where they leave it (default: the middle of the building's side that
    faces the nearest rack, 0.5 m outside, at the cable entry height)."""

    id: Identifier
    kind: RoomKind
    title: str = ""
    building: str | None = Field(default=None, description="Building in layout/building.yaml.")
    substation: str | None = Field(default=None, description="Substation id it belongs to.")
    voltage_v: float | None = Field(default=None, gt=0, description="Bus voltage, V.")
    point: Point3 | None = Field(default=None, description="Cable exit [x, y, z], site m.")
    notes: str = ""

    @model_validator(mode="after")
    def _check(self) -> "Room":
        if self.building is None and self.point is None:
            raise ValueError(f"room {self.id}: give its building or its point")
        return self


#: A side of the driven item's plan footprint in site axes: north +y, south -y, east +x, west -x.
EntrySide = Literal["north", "south", "east", "west"]


class CableEntry(Strict):
    """Where a motor's cable leaves its tray for the terminal box: beside the driven item, so
    the tray does not run over the machine (a crane lane over it stays clear). The tray ends
    there; the cable drops from there to the terminal box as cable, not tray.

    Either ``side`` (of the item's footprint in plan, the axis-aligned box of the placed item
    in site axes) with ``offset_m`` along it and ``clearance_m`` out from it, or ``point``
    [x, y] in site m. ``elevation_m``: the height of the tray's end (default: 0.6 m above the
    terminal box, as without an entry)."""

    side: EntrySide | None = Field(default=None, description="Side of the driven item.")
    offset_m: float | None = Field(
        default=None,
        description="Along the side from its middle, m: toward +x on north and south, toward +y "
        "on east and west (default 0); at most half the side's length.",
    )
    clearance_m: float | None = Field(
        default=None,
        ge=0,
        description="From the side out to the tray's centreline, m (default: the layout "
        "criteria's lane_margin_m plus half the tray's width plus the tray rules' spacing_m, "
        "so a crane lane square to that side stays clear).",
    )
    point: tuple[float, float] | None = Field(
        default=None, description="The tray's end [x, y], site m, outside the item's footprint."
    )
    elevation_m: float | None = Field(
        default=None, ge=0, description="The tray's end above grade, m."
    )

    @model_validator(mode="after")
    def _check(self) -> "CableEntry":
        if self.side is None and self.point is None:
            raise ValueError("cable_entry: give its side (of the driven item) or its point")
        if self.side is not None and self.point is not None:
            raise ValueError("cable_entry: give its side or its point, not both")
        if self.point is not None and (self.offset_m is not None or self.clearance_m is not None):
            raise ValueError("cable_entry: offset_m and clearance_m go with side, not point")
        return self


class Motor(Strict):
    """A motor of the motor list. A motor driving an equipment-list item is derived from that
    item (``driven``); an entry here gives or overrides its power, voltage and room, or says
    why it has no cable of the plant's own (``skip``: a vendor package, a steam turbine), and
    where its cable leaves the tray (``cable_entry``)."""

    driven: Identifier = Field(description="The equipment-list tag it drives.")
    tag: Identifier | None = Field(default=None, description="Motor tag (default M-<driven>).")
    power_kw: float | None = Field(default=None, gt=0, description="Rated output, kW.")
    voltage_v: float | None = Field(default=None, gt=0)
    room: str | None = Field(default=None, description="The room id it is fed from.")
    assumed: bool = Field(default=False, description="True: the power is an assumption.")
    source: str = Field(default="", description="Where the power comes from.")
    skip: str | None = Field(default=None, description="No cable of its own, for this reason.")
    cable_entry: CableEntry | None = Field(
        default=None,
        description="Where its cable leaves the tray beside the item (default: the tray runs "
        "to above the terminal box and drops onto it).",
    )
    notes: str = ""


class Feeder(Strict):
    """Another consumer that needs a power cable: an electric heater, a package, a socket
    outlet. It is at a placed ``item`` (its tag) or at ``point``."""

    tag: Identifier
    item: str | None = Field(default=None, description="The placed tag it is at.")
    point: Point3 | None = None
    power_kw: float = Field(gt=0)
    voltage_v: float | None = Field(default=None, gt=0)
    power_factor: float | None = Field(
        default=None,
        gt=0,
        le=1,
        description="Of the load, for its cable current P / (sqrt(3) U pf); omitted: 1.0 (a "
        "resistive heater), marked ASSUMED in the cable's basis; give it for a package with "
        "motors. No motor efficiency applies. The current is three-phase: a single-phase load "
        "(a 230 V socket outlet) draws more for its power and is undersized.",
    )
    room: str | None = None
    assumed: bool = False
    source: str = ""
    notes: str = ""

    @model_validator(mode="after")
    def _check(self) -> "Feeder":
        if self.item is None and self.point is None:
            raise ValueError(f"feeder {self.tag}: give its item or its point")
        return self


class JunctionBox(Strict):
    """A field junction box: the instrument cables of the instruments it takes end there, and
    one multipair cable runs from it to the control room. Placed at ``point``, or proposed in
    ``area`` near its instruments."""

    tag: Identifier
    point: Point3 | None = None
    area: str | None = Field(default=None, description="Site plan area it stands in.")
    instruments: list[str] = Field(
        default_factory=list, description="Instrument tags or patterns (TT-1*) it takes."
    )
    capacity: int | None = Field(default=None, gt=0, description="Instrument cables at most.")
    room: str | None = Field(default=None, description="The room its multipair cable goes to.")
    notes: str = ""


class InstrumentCable(Strict):
    """Cabling of one instrument or actuated valve: its junction box, where it stands when the
    P&ID does not place it, or why it needs no cable (``skip``: wireless, local gauge)."""

    tag: Identifier
    jb: str | None = Field(default=None, description="Its junction box tag.")
    point: Point3 | None = None
    skip: str | None = None
    notes: str = ""


class ElectricalDefaults(Strict):
    """Which room feeds what, and the voltages, when an entry does not say (ASSUMED)."""

    lv_room: str | None = Field(default=None, description="Room of LV motors (an mcc).")
    mv_room: str | None = Field(default=None, description="Room of MV motors (switchgear).")
    control_room: str | None = Field(default=None, description="Where instrument cables go.")
    lv_voltage_v: float = Field(default=400.0, gt=0)
    mv_voltage_v: float = Field(default=6600.0, gt=0)
    mv_above_kw: float = Field(
        default=200.0, gt=0, description="Motors above this rating are fed at MV, kW."
    )
    jb_capacity: int = Field(default=24, gt=0, description="Instrument cables per JB.")
    spare_pairs: float = Field(
        default=0.2, ge=0, description="Spare pairs of a multipair cable, fraction."
    )


class ElectricalList(Strict, optional_schema("electrical")):
    """``electrical/electrical-list.yaml``: substations, transformers, electrical rooms, the
    motor list (derived from the driven equipment, given or overridden here), other feeders,
    junction boxes and the cabling of single instruments."""

    substations: list[Substation] = Field(default_factory=list)
    transformers: list[Transformer] = Field(default_factory=list)
    rooms: list[Room] = Field(default_factory=list)
    defaults: ElectricalDefaults = Field(default_factory=ElectricalDefaults)
    motors: list[Motor] = Field(default_factory=list)
    feeders: list[Feeder] = Field(default_factory=list)
    junction_boxes: list[JunctionBox] = Field(default_factory=list)
    instruments: list[InstrumentCable] = Field(default_factory=list)
    notes: str = ""
