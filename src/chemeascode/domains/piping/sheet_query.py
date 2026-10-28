"""What a P&ID draws, by printed tag: for gates and list cross-checks that ask the model, not grep.

A sheet is loaded with pyDEXPI and every tagged object is listed with the tag a P&ID prints for
it: equipment (``TagName``), instrument functions (``PICSA-4712.02``), piping components
(:func:`component_tag`) and lines (``LineNumber``). Ids play no part, so renaming ids does not
change what a query finds.

Each object also says whether it is *connected*:

- equipment: a pipe or segment ends at one of its nozzles (or at the item itself);
- an instrument function: it has a measuring or signal line, or senses at a location;
- a piping component: it is an item of a segment and a pipe or the segment's end references it;
- a line: one of its segments has a pipe.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from chemeascode.foundation.workspace import Workspace


@dataclass(frozen=True)
class DrawnItem:
    """One tagged object of a sheet."""

    tag: str
    #: DEXPI class name, e.g. ``SpringLoadedGlobeSafetyValve``.
    cls: str
    #: The class and its DEXPI superclasses, most specific first.
    classes: tuple[str, ...]
    id: str
    kind: str  # equipment, instrument, piping, line
    connected: bool
    sheet: str
    #: Line number of the PipingNetworkSystem a piping component sits in.
    line: str | None = None


def class_matches(item: DrawnItem, wanted: str) -> bool:
    """Whether *item* is of class *wanted*: the class itself, a DEXPI superclass, or a class whose
    name ends with *wanted* (``SafetyValve`` matches ``SpringLoadedGlobeSafetyValve``)."""
    return any(name == wanted or name.endswith(wanted) for name in item.classes)


_STOP = {"ConceptualObject", "PyDexpiBaseModel", "BaseModel", "ABC", "object"}


def _classes(obj: Any) -> tuple[str, ...]:
    found = []
    for klass in type(obj).__mro__:
        if klass.__name__ in _STOP:
            break
        found.append(klass.__name__)
    return tuple(found)


def _text(value: Any) -> str | None:
    return value.strip() if isinstance(value, str) and value.strip() else None


#: How the DEXPI reference numbers the components within one segment (``C1``, ``C12``). These
#: repeat from segment to segment and are no tag; its label prints ``PipingComponentName``.
SEGMENT_LOCAL = re.compile(r"C\d+")


def component_tag(number: Any, position: Any, name: Any) -> str | None:
    """The tag a P&ID prints for a piping component, from its ``PipingComponentNumber``,
    ``PositionNumber`` and ``PipingComponentName``.

    The first value in that order that is not a segment-local number (``C1``):
    ``PipingComponentNumber`` ``FV-104`` (or ``V12``) is the tag whatever the name says;
    ``PipingComponentNumber`` ``C1`` with ``PipingComponentName`` ``66KL21`` (the DEXPI
    reference) is ``66KL21``; a component with only ``C1`` has no tag.
    """
    for value in map(_text, (number, position, name)):
        if value and not SEGMENT_LOCAL.fullmatch(value):
            return value
    return None


def piping_tag(component: Any) -> str | None:
    """The tag a P&ID prints for a piping component (:func:`component_tag`)."""
    return component_tag(
        *(
            getattr(component, n, None)
            for n in ("pipingComponentNumber", "positionNumber", "pipingComponentName")
        )
    )


def sheet_items(model: Any, sheet: str) -> list[DrawnItem]:
    """Every tagged object of a loaded *model*, in model order."""
    from pydexpi.pydexpi_classes.pydexpi_classes import (
        PipingComponent,
        ProcessInstrumentationFunction,
        TaggedPlantItem,
    )
    from pydexpi.toolkits.display_name import get_tag, instrument_tag
    from pydexpi.toolkits.model_toolkit import get_all_instances_in_model

    conceptual = model.conceptualModel
    ends: set[int] = set()  # id() of every item a pipe or segment starts or ends at
    piped_lines: set[int] = set()
    line_of: dict[int, str] = {}
    in_segment: set[int] = set()
    systems = list(getattr(conceptual, "pipingNetworkSystems", None) or ())
    for system in systems:
        number = _text(getattr(system, "lineNumber", None))
        for segment in system.segments or ():
            pipes = list(segment.connections or ())
            if pipes:
                piped_lines.add(id(system))
            for holder in (segment, *pipes):
                for side in ("sourceItem", "targetItem"):
                    item = getattr(holder, side, None)
                    if item is not None:
                        ends.add(id(item))
            for item in segment.items or ():
                in_segment.add(id(item))
                if number:
                    line_of.setdefault(id(item), number)

    found: list[DrawnItem] = []
    for obj in get_all_instances_in_model(model):
        if isinstance(obj, TaggedPlantItem):
            tag = get_tag(obj)
            nozzles = list(getattr(obj, "nozzles", None) or ())
            connected = id(obj) in ends or any(id(n) in ends for n in nozzles)
            kind = "equipment"
        elif isinstance(obj, ProcessInstrumentationFunction):
            tag = instrument_tag(obj)
            sensing = any(
                getattr(f, "sensingLocation", None) is not None
                for f in obj.processSignalGeneratingFunctions or ()
            )
            connected = bool(obj.signalConveyingFunctions) or sensing
            kind = "instrument"
        elif isinstance(obj, PipingComponent):
            tag = piping_tag(obj)
            connected = id(obj) in in_segment and id(obj) in ends
            kind = "piping"
        else:
            continue
        if not tag:
            continue
        found.append(
            DrawnItem(
                tag=tag.strip(),
                cls=type(obj).__name__,
                classes=_classes(obj),
                id=getattr(obj, "id", "") or "",
                kind=kind,
                connected=connected,
                sheet=sheet,
                line=line_of.get(id(obj)),
            )
        )
    for system in systems:
        number = _text(getattr(system, "lineNumber", None))
        if number:
            found.append(
                DrawnItem(
                    tag=number,
                    cls=type(system).__name__,
                    classes=_classes(system),
                    id=system.id or "",
                    kind="line",
                    connected=id(system) in piped_lines,
                    sheet=sheet,
                )
            )
    return found


@dataclass
class LoadedSheet:
    """A sheet of the repository: its path, id from ``plant.yaml`` and model (None: not loaded)."""

    name: str
    sheet_id: str
    model: Any
    error: str = ""


def sheet_id_of(workspace: Workspace, name: str) -> str:
    """The sheet id ``plant.yaml`` gives the file *name*, else its stem (``pid/P-03.xml``: P-03)."""
    for sheet in workspace.config().sheets:
        if sheet.file.replace("\\", "/").lstrip("./") == name:
            return sheet.id
    return Path(name).stem


def load_sheets(workspace: Workspace) -> list[LoadedSheet]:
    """Every sheet of *workspace*, loaded with pyDEXPI (an unreadable one with its error)."""
    from chemeascode.domains.piping import dexpi_io

    loaded = []
    for path in workspace.pid_files():
        name = workspace.relative(path)
        sheet_id = sheet_id_of(workspace, name)
        if not path.is_file():
            loaded.append(LoadedSheet(name, sheet_id, None, "the file does not exist"))
            continue
        try:
            model = dexpi_io.load(path.read_bytes(), strict=True).model
        except Exception as failure:  # noqa: BLE001 - any load failure is reported, not raised
            loaded.append(LoadedSheet(name, sheet_id, None, str(failure).splitlines()[0][:200]))
            continue
        loaded.append(LoadedSheet(name, sheet_id, model))
    return loaded


def matches_sheet(sheet: LoadedSheet, wanted: str) -> bool:
    """Whether *wanted* names *sheet*: its id (``P-03``), file (``pid/P-03.xml``) or stem."""
    wanted = wanted.strip()
    return wanted in (sheet.sheet_id, sheet.name, Path(sheet.name).stem)
