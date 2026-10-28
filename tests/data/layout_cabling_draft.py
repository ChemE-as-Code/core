import sys
from pathlib import Path

from chemeascode.domains.piping.authoring import (
    Nozzle,
    Sheet,
    equipment,
    instrument,
    line,
    offpage,
    valve,
)

sheet = Sheet.load(Path(sys.argv[1]))
vessel = equipment(
    sheet,
    "PressureVessel",
    "V-101",
    shape="VESSEL_WITH_DISHED_HEADS_SHAPE",
    at=(100, 120),
    nozzles=[
        Nozzle("N1", (0, -20), 100),  # top: vapour out
        Nozzle("N2", (0, 20), 80),  # bottom: liquid out
        Nozzle("N5", (10, -12), 25),  # right, high: level tapping
        Nozzle("N6", (10, 12), 25),  # right, low: local gauge
    ],
)
pump = equipment(
    sheet,
    "CentrifugalPump",
    "P-101",
    shape="CENTRIFUGAL_PUMP_SHAPE",
    at=(160, 170),
    nozzles=[Nozzle("N1", (-7.5, 0), 80), Nozzle("N2", (0, -7.5), 50)],
)
line(sheet, "80-P-101", dn=80, fluid="Water", route=[vessel["N2"], (100, 170), pump["N1"]])
line(
    sheet,
    "50-P-102",
    dn=50,
    fluid="Water",
    route=[
        pump["N2"],
        (160, 100),
        valve("FV104", "GlobeValve", tag="FV-104"),
        offpage("out", at=(240, 100), note="to B/L"),
    ],
)
instrument(sheet, "PT-101", at=(185, 150), sensing=pump["N2"])
instrument(sheet, "LT-102", at=(130, 100), sensing=vessel["N5"])
instrument(sheet, "PI-103", at=(130, 140), sensing=vessel["N6"], location="field")
instrument(
    sheet,
    "FIC-104",
    at=(200, 80),
    sensing="Line_50P102_S1",
    sensing_at=(180, 100),
    signal_to="FV104",
)
sheet.save()
