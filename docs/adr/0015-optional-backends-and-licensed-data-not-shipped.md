# 0015. Brightway as an optional LCA backend; licensed third-party data is linked or fetched, never shipped

- **Status:** Accepted
- **Date:** 2026-10-22 (Brightway backend); ChemSep data unshipped on 2026-10-23

## Context

LCA backgrounds (ecoinvent and similar) and some thermodynamic parameter sets carry licences that
forbid or do not clearly allow redistribution. cheme-as-code is AGPL-3.0-or-later licensed and meant to become
public; a plant study must be usable and publishable without a licensed database.

## Decision

- LCA has two backends: `factors` (the project's own characterised factors in
  `lca/factors.yaml`, plus packaged open profiles with recorded licences) and `brightway`
  (extra `lca`, adapter `integrations/brightway.py`). The Brightway project is the user's own
  and is only read; background activities are referenced by database, name, reference product and
  location; cheme writes no foreground database into it. Foreground, background links and results
  stay separate layers, and a source registry records each source's terms and publication policy.
- Data whose licence does not clearly allow redistribution is not shipped. The ChemSep SRK
  interaction parameters were removed from the package; `cheme data fetch chemsep-srk` downloads
  them per user into the user data directory (`foundation/userdata.py`), with a recorded checksum.

## Consequences

- Positive: the package and the example plants stay redistributable; results record which
  licensed sources they used.
- Negative: users must obtain licensed databases themselves; results with a licensed background
  cannot be reproduced by someone without the licence.
- Negative: features relying on fetched data need an explicit setup step; the code names the
  fetch command (`FETCH_COMMAND` in `thermodynamics/chemsep_srk.py`) when the data is absent.
- Open: the ChemSep IPD licence is still unconfirmed.

## Evidence

- Brightway backend: `pyproject.toml` extra `lca`.
- ChemSep: CHANGELOG "ChemSep SRK data no
  longer shipped", `src/chemeascode/domains/process/thermodynamics/data/chemsep/SOURCE.md`.
- [lca.md](../framework/lca.md) ("Open data, sources and coverage").
