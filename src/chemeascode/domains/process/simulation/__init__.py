"""Process simulation: the flowsheet solved by an external simulator (DWSIM), its results
written back as ``calculated`` stream values (``cheme process simulate``)."""

SIMULATION_FILE = "process/simulation.yaml"
SCHEMA = "cheme/simulation/v1"
#: The source prefix of every value ``cheme process simulate`` writes.
SOURCE = "cheme process simulate"
