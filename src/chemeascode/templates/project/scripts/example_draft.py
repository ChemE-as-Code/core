"""Example generator: a tank, a pump, three lines, two instruments and a note.

Run it with cheme-as-code's interpreter (python3 and `uv run python` have no pyDEXPI here):

    cheme sheet new P-99 --title 'Example'
    cheme run scripts/example_draft.py pid/P-99.xml

It edits the sheet file given as its argument in place (start it with `cheme sheet new`, so
its title block is real) and formats it (`Sheet.save`). Copy it to `scripts/draft_<sheet>.py`
for a real sheet. The builders are documented in the `pid-draft` skill and in the docstrings of
`chemeascode.domains.piping.authoring`.
"""

import sys
from pathlib import Path

from chemeascode.domains.piping.authoring import (
    Nozzle,
    Sheet,
    equipment,
    instrument,
    line,
    note,
    offpage,
    tee,
    valve,
)

target = Path(sys.argv[1] if len(sys.argv) > 1 else "pid/P-99.xml")
if not target.exists():
    sys.exit(f"{target} does not exist: start it with `cheme sheet new {target.stem}`")

sheet = Sheet.load(target)

# Equipment: class, tag, catalogue shape, position (sheet mm, Y down), nozzles (dx, dy from it).
tank = equipment(
    sheet,
    "Tank",
    "T-101",
    shape="VESSEL_WITH_DISHED_HEADS_SHAPE",
    at=(80, 120),
    nozzles=[Nozzle("N1", (10, 8), 80)],
)
pump = equipment(
    sheet,
    "CentrifugalPump",
    "P-101",
    shape="CENTRIFUGAL_PUMP_SHAPE",
    at=(160, 150),
    nozzles=[Nozzle("N1", (-7.5, 0), 80), Nozzle("N2", (0, -7.5), 50)],
)

# Lines: start port, bends (x, y), inline valves and tees in flow order, end port. Valves
# without `at` sit mid-leg; a tee ends a segment. Number and DN labels go beside the route.
branch = tee("T101_Tee1")
line(
    sheet,
    "80-W-101",
    dn=80,
    fluid="Water",
    route=[
        tank["N1"],
        (90, 150),
        valve("HV101", "GateValve", tag="HV-101"),
        branch,
        valve("FV101", tag="FV-101"),
        pump["N1"],
    ],
)
line(
    sheet,
    "50-W-102",
    dn=50,
    fluid="Water",
    route=[pump["N2"], (160, 100), offpage("out", at=(405, 100), note="to P-02")],
)
line(
    sheet,
    "25-W-103",
    dn=25,
    fluid="Water",
    route=[branch.branch, (branch.branch.xy[0], 180), offpage("out", at=(405, 180))],
)

# Off-page connectors go on the sheet's edges (incoming left, outgoing right):
# cheme.offpage-not-on-edge reports one left mid-sheet.

# Instruments: tag, bubble position, what they sense, and the valve they act on.
instrument(sheet, "PI-101", at=(175, 142.5), sensing=pump["N2"])
instrument(
    sheet,
    "FIC-101",
    at=(128, 128),
    sensing="Line_80W101_S2",
    sensing_at=(128, 150),
    signal_to="FV101",
)
note(sheet, "Trip: LALL-101 stops P-101", at=(60, 180))

sheet.save()
for message in sheet.notes:
    print(f"note: {message}", file=sys.stderr)
print(f"wrote {target}")
