# 0079. Review activated-sludge snapshots with partial inputs

- **Status:** Proposed
- **Date:** 2026-11-19

`cheme process activated-sludge-review <snapshot.json>` invokes a read-only
process-domain calculation used by the installed retention and clarifier skill.
The snapshot represents one continuous suspended-growth waterline with
clarifier-underflow wasting and an equal-volume layer profile where available.
The skill documents the required fields, units, sources and engineering
judgments. Preparing the snapshot from the flowsheet and operating evidence
is an explicit step. No simulator or plant files are required by the command.

The JSON report contains `calculated` and `deferred` maps keyed by metric, with
units and either a value or a reason. Tank and zone metrics append their
identifier after a dot. `water_balances` reports the external and clarifier
checks separately. A missing input affects dependent metrics; a known
inconsistent external balance blocks SRT, and a known inconsistent
clarifier balance blocks feed-based loading. A partially computable snapshot
is a valid report. Malformed JSON or a non-object input exits 2.

HRT uses external influent and biological volume. SRT uses TSS inventory and
effluent plus WAS solids loss. Active area and the actual flows distinguish
influent loading, effluent overflow and clarifier feed loading. The report
does not establish peak capacity, steady state or treatment performance.
