# Safety

**Scope.** HAZOP and related analyses: node selection, deviations and scenarios, causes and
consequences, safeguards, the evidence and assumptions behind them, review records, and links to
the exact revisions that were analysed.

**Artifact types.** A HAZOP study (nodes, deviations, safeguards, actions), a safeguard register.

**Code today.** `hazard_data.py`: OSHA hazard data (flash point, explosive limits, NFPA
ratings, exposure limits) in SI units with the source URL, as evidence for a study.
`area_classification.py` with `data/release-radii.yaml`: indicative zone radii around release
points (vents, relief outlets, seals, flanges) by release grade and substance class, every row
ASSUMED with its basis; the spatial domain places the volumes in the 3D model (no dispersion
modelling). `reaction_hazards.py`: thermal screening of reactors (adiabatic rise, MTSR,
Stoessel's criticality class from a given TD24 and MTT, a cooled bed's parametric sensitivity;
`cheme process reactor-hazards`), screening values a HAZOP study can cite. The bundled skill `skills/area-classification/` says how a plant repository declares
its zones with it, and what a competent person must still decide.

**HAZOP** (pre-release issue 136, [docs/framework/hazop.md](../../../../docs/framework/hazop.md)).
`schemas.py`: the study (`cheme/hazop-study/v1`, `safety/hazop/<study-id>/study.yaml`) and the
risk matrix (`cheme/risk-matrix/v1`). `risk_matrix.py`: the matrix rules and the one band
lookup. `hazop.py`: loading, the `cheme.hazop-*` rules against the study, the plant (tags of
the lists and sheets, interlocks of `control/cause-effect.yaml`) and the matrix, staleness of
bands and analysed inputs, the targeted band write, the study's state and review.
`hazop_report.py`: the report. `propagation.py` (ADR 0032, `cheme safety hazop propagate`):
the candidate scenarios of a node, each failure mode of its objects walked over the pyDEXPI
objects of the analysed P&IDs to a top event or study limit, with the safeguards on the path and
the open questions; the failure modes come from the project's `safety/failure-modes.yaml`
(`cheme/failure-modes/v1`, none shipped). `data/risk-matrix-example.yaml`: the illustrative matrix that
`cheme init` writes. Skills `hazop-study`, `hazop-node-breakdown`, `hazop-scenario-propagation`,
`hazop-risk-classification`, `hazop-assessment`, `hazop-review`. Review records
(`reviews/*.md`, `chemeascode.foundation.reviews`) tie the review to its scope and
`reviewed_commit`; interlocks and the cause-and-effect matrix belong to `control`, and a study
refers to them by id.

**Out of scope.** Deciding whether a plant is safe. The tools check structure and consistency;
the judgement belongs to the people who sign the review. No consequence modelling (dispersion,
fire, explosion) in this package; such tools are integrations.

May import: `chemistry`, `process`, `equipment`, `piping`, `control`. See
[the architecture](../../../../docs/framework/architecture.md).
