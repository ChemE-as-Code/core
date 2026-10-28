"""Authoring: write the verbose parts of a sheet, for agents and generator scripts.

``copy`` duplicates an object with its drawing, ``fragment`` prints ready-to-paste XML. Both work
on the XML text and tree (lxml) only; the agent runs ``cheme fmt`` and ``validate`` after.

This module is also the documented **Python API for generator scripts** (run them with
``cheme run``, which has pyDEXPI and chemeascode importable). Scripts import it by its
public name ``chemeascode.domains.piping.authoring``::

    import sys
    from chemeascode.domains.piping.authoring import Sheet, Nozzle, equipment, line, valve, tee
    from chemeascode.domains.piping.authoring import instrument, offpage, note

    sheet = Sheet.load(sys.argv[1])                     # the frame: e.g. the empty sheet
    tank = equipment(sheet, "Tank", "T-101", shape="VESSEL_WITH_DISHED_HEADS_SHAPE",
                     at=(80, 120), nozzles=[Nozzle("N1", (10, 8), 80)])
    pump = equipment(sheet, "CentrifugalPump", "P-101", shape="CENTRIFUGAL_PUMP_SHAPE",
                     at=(160, 150), nozzles=[Nozzle("N1", (-7.5, 0), 80),
                                             Nozzle("N2", (0, -7.5), 50)])
    line(sheet, "80-W-101", dn=80, fluid="Water",
         route=[tank["N1"], (90, 150), valve("V101", "GateValve"), pump["N1"]])
    line(sheet, "50-W-102", dn=50, fluid="Water",
         route=[pump["N2"], (160, 100), offpage("out", at=(240, 100), note="to P-02")])
    instrument(sheet, "PI-101", at=(175, 125), sensing=pump["N2"])
    note(sheet, "Trip: LALL-101 stops P-101", at=(60, 180))
    sheet.save()                                        # writes and runs cheme fmt

Builders insert into the loaded sheet and refuse ids that exist already. Valves, tees, pipes,
segments and labels come from the same functions as ``cheme fragment``, so the XML is the
same. The file stays the only state: there is still no edit-operation server; a generator
writes a file that is then formatted and validated like a hand edit.
"""

from chemeascode.domains.piping.authoring.sheet import (
    AuthoringError,
    Equipment,
    Line,
    Marker,
    Nozzle,
    OffPage,
    Port,
    Sheet,
    Tee,
    Valve,
    equipment,
    instrument,
    label,
    line,
    note,
    offpage,
    place_line_labels,
    tee,
    valve,
)

__all__ = [
    "AuthoringError",
    "Equipment",
    "Line",
    "Marker",
    "Nozzle",
    "OffPage",
    "Port",
    "Sheet",
    "Tee",
    "Valve",
    "equipment",
    "instrument",
    "label",
    "line",
    "note",
    "offpage",
    "place_line_labels",
    "tee",
    "valve",
]
