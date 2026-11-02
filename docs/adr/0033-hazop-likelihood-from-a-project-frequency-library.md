# 0033. HAZOP likelihood derived from a project frequency library, never estimated

- **Status:** Proposed
- **Date:** 2026-10-30

## Context

A HAZOP rating needs a likelihood code for its cause. The skill `hazop-risk-classification`
lets an agent take a code only from evidence the project holds, and leaves it `null` otherwise.
In practice the evidence is usually a table of generic initiating-event frequencies (LOPA
screening values, QRA loss-of-containment frequencies), read by hand and mapped onto the
matrix's likelihood grades: by every reader again, with no record of which value was used.

Forces:

- **No licensed content in core.** Frequency tables come from licensed books or secondary
  sources; cheme-as-code ships none of their numbers (as for the failure modes, ADR 0032).
- **No LLM in a domain function** (ADR 0010): picking the event type a cause is an instance of
  is judgement; turning a value into a code is not.
- **Bands are calculated, never typed**, with fingerprints that make them stale (ADR 0011). A
  likelihood from a table should be as reproducible.

The hazops-copilot-dev project does this with a frequency library (event types, records with
source and locator, a screening rule) and a matrix whose grades carry an upper frequency bound;
a classifier fills in only where the library has no record.

## Decision

- **A frequency library is project data**: `cheme/frequencies/v1` (`kind: frequencies`,
  `safety/frequencies.yaml` by convention), with its `sources` (citation, the secondary source
  it was read in, `basis: lopa_ief | qra_loc`), `event_types`, `records` (id, event type, value
  per year, optional `per` a length or a joint, conditions, source, locator, `verified`) and an
  optional failure mode -> event type map. The study names it (`frequencies:`); cheme-as-code
  ships none.
- **The matrix may carry `max_frequency`** per likelihood grade (per year, increasing; the most
  likely grade open). It is not part of the matrix fingerprint: bands follow the codes.
- **A rating links instead of typing**: `frequency: {event_type: ...}` or `{record: ...}`. An
  event type gives its screening value: its records per item, LOPA initiating-event records
  only when there are any, the highest (conservative, never an average).
- **`cheme safety hazop rate --write` derives the likelihood** of a linked rating (the first
  grade whose bound is above the value) and writes it in place before the bands, which are then
  looked up as before. A typed likelihood that differs is `hazop-likelihood-derived` (warning);
  a link that gives nothing is `hazop-frequency`: an error for a broken link or a matrix without
  bounds, info where the library has no value per item, which leaves the likelihood to the team.
- Choosing the event type or record stays a judgement written by an agent or the team
  (`status: proposed`); the skill names the record and its verification state in the basis.

## Consequences

- Positive: a likelihood names its record; changing a record, a bound or the link shows up at
  the next check; no number is typed twice; the library is the project's to cite and license.
- Positive: the rate writers now take their YAML positions from the text on disk, so a file
  with CRLF line endings is edited in place correctly (it was shifted before: the four
  `test_hazop.py` write tests failed on Windows).
- Negative: one more file kind and a schema field each on the matrix, the study and the rating.
- Negative: a screening value is conservative by design; a better value needs its own record.
- Known limitations: records per a length or a joint give no likelihood (the length is not
  modelled); no residual frequency from safeguard PFDs (credit stays the team's residual rating);
  conditional modifiers (ignition, occupancy) are not applied.

## Evidence

- `src/chemeascode/domains/safety/frequencies.py`, `schemas.py` (`FrequencyLibrary`,
  `FrequencyRef`, `Likelihood.max_frequency`), `hazop.py` (`likelihood_rows`, `rate`,
  `write_keys`), `risk_matrix.py` (`matrix_fingerprint`).
- `tests/test_hazop_frequencies.py`; skills `hazop-risk-classification`, `hazop-assessment`.
