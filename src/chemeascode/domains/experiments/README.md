# Experiments and uncertainty

**Scope.** Experimental records and datasets, measurement provenance, parameter estimation, model
calibration, descriptions of uncertainty, and the assumptions made when scaling up.

**Artifact types.** An experiment record (conditions, measured values with units, instrument,
date, operator), a dataset, a fitted parameter set that names the data and the model it came from.

**Related code today.** `kinetic_fit.py`: kinetic data files (`experiments/kinetics/*.yaml`),
power-law and LHHW fits with their uncertainty, and data sampled from a microkinetic mechanism
(`cheme experiments fit-rate`, `sample-mechanism`). `electrochemistry.py`: measured
electrochemical series (`experiments/electrochemistry/*.yaml`): Faradaic efficiency, partial
current densities, water dissociation efficiency from the anolyte titration, power, heat,
charge and carbon balances, the measured performance interpolated between points and never
extrapolated, and SVG plots (`cheme experiments electrochem`). Provenance follows the convention in
[the architecture](../../../../docs/framework/architecture.md): a record names its source files
and revisions, so a fit can be flagged for review when its data change.

**What will live here.** Schemas for records and datasets, unit and range checks on them, and
fitting routines that take explicit data and return parameters with their uncertainty.

**Out of scope.** Laboratory information management, instrument control, and the results of
individual research projects: papers and their data stay in their own repositories and depend
on this package.

May import: `requirements`, `chemistry`.
