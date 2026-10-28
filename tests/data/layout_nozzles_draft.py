import sys
from pathlib import Path

from chemeascode.domains.piping.authoring import Nozzle, Sheet, equipment, line

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
        Nozzle("N3", (-10, 0), 150),  # left, middle: feed
        Nozzle("N4", (-10, 0.5), 50),  # left, same spot: a second inlet
        Nozzle("N5", (10, -12), 25),  # right, high
        Nozzle("N6", (10, 12), 25),  # right, low
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
sheet.save()
