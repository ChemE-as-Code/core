"""The catalogue of the schemas of the YAML files in a plant repository.

Each file a plant repository holds besides its P&IDs follows one of these models. They are the
contract between people, agents and ``cheme validate``; ``cheme schema`` exports them as
JSON Schema for editors.

Each schema lives with its owner: ``foundation.schemas`` (``plant.yaml``, checks, status,
review records, adapter results, run records), ``domains.requirements.schemas`` (design basis),
``domains.equipment.schemas``,
``domains.piping.schemas`` (line, instrument and special-item lists), ``domains.control.schemas``
(cause and effect, loops, sequences, narrative and control philosophy, electrical
list), ``domains.spatial.schemas`` (layout, cable tray rules, HVAC,
and the generated layout model),
``domains.process.schema``, ``domains.safety.schemas`` (risk matrix, HAZOP study),
``domains.assessment.schemas`` (unit rates),
``domains.assessment.tea.schemas`` (TEA premises) and ``domains.assessment.lca.schemas`` (LCA
scope and factors). This module only
re-exports them (the same objects).
"""

from chemeascode.domains.assessment.lca.schemas import (
    FactorFile,
    LcaFile,
    LciDataset,
    LciEstimate,
    MappingProfile,
)
from chemeascode.domains.assessment.schemas import CostBasis, RateFile
from chemeascode.domains.assessment.tea.schemas import TeaFile
from chemeascode.domains.chemistry.catalysts import Catalysts
from chemeascode.domains.chemistry.evidence import ReactionEvidence
from chemeascode.domains.chemistry.reactions import Reactions
from chemeascode.domains.control.schemas import (
    ElectricalList,
    Interlock,
    InterlockList,
    LoopList,
    Narrative,
    Philosophy,
    SequenceList,
)
from chemeascode.domains.equipment.schemas.datasheet import Datasheet
from chemeascode.domains.equipment.schemas.equipment import EquipmentItem, EquipmentList
from chemeascode.domains.experiments.kinetic_fit import KineticData
from chemeascode.domains.piping.schemas.lines import (
    Instrument,
    InstrumentList,
    Line,
    LineList,
    LineSegment,
)
from chemeascode.domains.piping.schemas.pipe_specs import PipeSpecs
from chemeascode.domains.piping.schemas.piping_items import PipingItem, PipingItemList
from chemeascode.domains.process.electrochemical_cell import Cells
from chemeascode.domains.process.furnace import FurnacesFile
from chemeascode.domains.process.schema import Flowsheet, Materials
from chemeascode.domains.process.separations.extraction import ExtractionFile
from chemeascode.domains.process.separations.schema import Adsorption
from chemeascode.domains.process.simulation.schema import Simulation
from chemeascode.domains.process.thermodynamics.assay import Assays
from chemeascode.domains.requirements.schemas import DesignBasis
from chemeascode.domains.safety.schemas import (
    DeviationMatrix,
    FailureModeLibrary,
    FrequencyLibrary,
    HazopCoverage,
    HazopStudy,
    RiskMatrix,
)
from chemeascode.domains.spatial.schemas import (
    LAYOUT_SCHEMAS,
    BuildingList,
    CraneCharts,
    Hvac,
    LayoutModelFile,
    Placement,
    PlacementList,
    Routing,
    SitePlan,
    StructureList,
    TrayRules,
    ZoneList,
)
from chemeascode.foundation.schemas.checks import Accept, Check, CheckList
from chemeascode.foundation.schemas.plant import Generator, PlantConfig, Project, Sheet, Stage
from chemeascode.foundation.schemas.reviews import ReviewRecord
from chemeascode.foundation.schemas.run import AdapterResult
from chemeascode.foundation.schemas.run_record import RunRecord
from chemeascode.foundation.schemas.status import StatusFile

#: Schema of each engineering list, by the key ``workspace.LIST_FILES`` files it under.
LIST_SCHEMAS = {
    "design_basis": DesignBasis,
    "equipment": EquipmentList,
    "lines": LineList,
    "instruments": InstrumentList,
    "piping_items": PipingItemList,
    "interlocks": InterlockList,
    "loops": LoopList,
    "sequences": SequenceList,
    "checks": CheckList,
    "rates": RateFile,
    "cost_basis": CostBasis,
    "tea": TeaFile,
    "electrical": ElectricalList,
    "crane_chart": CraneCharts,
    "lca": LcaFile,
    "lca_factors": FactorFile,
}

#: Schemas of the other files cheme reads, by kind, with where those files are.
OTHER_SCHEMAS = {
    "datasheet": (Datasheet, "equipment/datasheets/<TAG>.yaml"),
    "review": (ReviewRecord, "reviews/*.md (front matter)"),
    "status": (StatusFile, "checks/status.json"),
    "process-materials": (Materials, "process/materials.yaml"),
    "process-flowsheet": (Flowsheet, "process/flowsheet.yaml"),
    "process-simulation": (Simulation, "process/simulation.yaml"),
    "process-reactions": (Reactions, "process/reactions.yaml"),
    "process-catalysts": (Catalysts, "process/catalysts.yaml"),
    "process-assays": (Assays, "process/assays.yaml"),
    "process-cells": (Cells, "process/cells.yaml"),
    "process-adsorption": (Adsorption, "process/adsorption.yaml"),
    "reaction-evidence": (ReactionEvidence, "process/reaction-evidence.yaml"),
    "process-extraction": (ExtractionFile, "process/extraction.yaml"),
    "furnaces": (FurnacesFile, "process/furnaces.yaml"),
    "kinetic-data": (KineticData, "experiments/kinetics/*.yaml"),
    "layout_model": (LayoutModelFile, "layout/plant-model.yaml (generated)"),
    "lci_dataset": (LciDataset, "lca/dataset.yaml (generated), lca/datasets/*.yaml"),
    "lci_estimate": (LciEstimate, "lca/estimate.yaml"),
    "lca_mapping_profile": (MappingProfile, "lca/mapping-profiles/*.yaml"),
    "adapter-result": (AdapterResult, "process/simulation-run.json cases; --json"),
    "risk-matrix": (RiskMatrix, "safety/risk-matrix.yaml"),
    "hazop-study": (HazopStudy, "safety/hazop/<id>/study.yaml"),
    "failure-modes": (FailureModeLibrary, "safety/failure-modes.yaml"),
    "hazop-coverage": (HazopCoverage, "safety/hazop/<id>/coverage.yaml"),
    "hazop-deviation-matrix": (DeviationMatrix, "safety/deviation-matrix.yaml"),
    "frequencies": (FrequencyLibrary, "safety/frequencies.yaml"),
    "narrative": (Narrative, "process/narrative.md (front matter)"),
    "control_philosophy": (Philosophy, "control/philosophy.md (front matter)"),
    "process-run": (RunRecord, "runs/<run-id>/run.yaml"),
}

__all__ = [
    "LAYOUT_SCHEMAS",
    "AdapterResult",
    "LIST_SCHEMAS",
    "OTHER_SCHEMAS",
    "BuildingList",
    "CraneCharts",
    "Accept",
    "Adsorption",
    "Check",
    "CostBasis",
    "CheckList",
    "Datasheet",
    "ElectricalList",
    "FactorFile",
    "FailureModeLibrary",
    "FrequencyLibrary",
    "HazopCoverage",
    "HazopStudy",
    "DesignBasis",
    "DeviationMatrix",
    "EquipmentItem",
    "EquipmentList",
    "Generator",
    "Hvac",
    "Instrument",
    "InstrumentList",
    "Interlock",
    "LayoutModelFile",
    "LcaFile",
    "LciDataset",
    "LciEstimate",
    "MappingProfile",
    "PipeSpecs",
    "Routing",
    "StructureList",
    "TrayRules",
    "ZoneList",
    "InterlockList",
    "LoopList",
    "Narrative",
    "Philosophy",
    "SequenceList",
    "Line",
    "LineList",
    "LineSegment",
    "PipingItem",
    "PipingItemList",
    "Placement",
    "PlacementList",
    "PlantConfig",
    "RateFile",
    "TeaFile",
    "Project",
    "Reactions",
    "Assays",
    "Catalysts",
    "Cells",
    "ReactionEvidence",
    "ExtractionFile",
    "FurnacesFile",
    "KineticData",
    "ReviewRecord",
    "RiskMatrix",
    "RunRecord",
    "Sheet",
    "SitePlan",
    "Stage",
    "StatusFile",
]
