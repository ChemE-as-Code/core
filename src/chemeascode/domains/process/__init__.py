"""Process design: materials, flowsheet, block and process flow diagrams.

The source of truth is YAML (``process/materials.yaml`` and ``process/flowsheet.yaml``, schema
``cheme/process/v1``). ``cheme process build`` generates the BFD and PFD sheets from it as
DEXPI 2.0.1 ProcessModels with a drawing; ``cheme validate`` checks the YAML (ids, units,
bases, ports, balances, links) and that each generated sheet still matches what it was built from.
"""

#: The schema every process YAML file declares.
SCHEMA = "cheme/process/v1"
#: The version of the generator's output; a change makes every generated sheet outdated.
GENERATOR_VERSION = "5"

MATERIALS_FILE = "process/materials.yaml"
FLOWSHEET_FILE = "process/flowsheet.yaml"
