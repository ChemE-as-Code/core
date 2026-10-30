# 0036. Several power trays per rack, by voltage class and fill

- **Status:** Accepted
- **Date:** 2026-10-30

## Context

`cheme layout build` ran one power tray along each rack, at `lane_fraction` of the rack width
left of its centreline, as wide as its cables needed up to the largest of `widths_mm`. In the
ammonia-1 run (process-library#86, cheme 1.0.1) the 10 kV cables of the compressors K-101,
K-501 and K-701 filled the main-rack power tray to 53-54 % against a 30 % limit. The trays on
PR-10, PR-7, the switchgear room leg and two links were also over the limit. The `tray-fill`
finding said to run a second tray, but `electrical/tray-rules.yaml` could not declare one: a
`tiers` rule only sets a rack's tray elevation. The only way out was to accept the finding, and
the detail gate `electrical` failed (core#71).

Options considered: a count of power trays per rack; one entry per tray with its voltage class;
stacking the trays on tiers of their own instead of side by side; a global rule that splits a
tray whenever it overflows. Side by side keeps the generated tray-tier steel (one beam across
the rack at each bent) as it is. A per-rack declaration keeps the project in control of what
stands on its racks. Voltage classes matter in practice: cables above and below about 1 kV are
commonly kept in separate trays. The US National Electrical Code (NFPA 70, 392.20(B)) allows
them in one tray only with a solid fixed barrier between them or with the higher-voltage
cables of type MC (see EC&M, "Mixing cables over and under 600V in cable tray",
https://www.ecmweb.com/national-electrical-code/article/20901257/mixing-cables-over-and-under-600v-in-cable-tray;
the 2016 article uses the 600 V limit of that edition).

## Decision

- The `trays` kind (`electrical/tray-rules.yaml`) gains `rules.power_trays: [{rack, trays}]`:
  `trays` is a count (1 .. 9, each tray takes any cable) or one voltage class per tray (`hv`,
  `lv`, `any`). `rules.lv_max_v` (default 1000 V, the low-voltage limit of IEC 60038) splits
  the classes: a cable rated above it is `hv`. A rack not listed has one power tray, as before.
- A rack's power trays stand side by side on its tray tier, centred on the power lane, the
  largest width plus `spacing_m` apart centre to centre.
- The build gives each power cable that runs on such a rack one of its trays for its whole way
  along that rack, deterministically. It takes the `hv` cables first, then the larger
  cross-section first, then the tag. Each cable goes to a tray of its class, else an `any`
  tray, else any other tray. Among those it takes the tray whose fullest piece along the
  cable's span stays under `fill_max_power` at the largest width, then the emptiest, then the
  first.
- Each tray's trunk is cut and sized on its own and is checked for fill and separation like
  every tray. Ids: `PT-<rack>-<letter>-<k>` (A, B, ... from the centreline out). Room legs and
  links split with the trays at their ends (`PT-<room>-<letter>`,
  `PT-<rack>-<rack>-<letters>`). A branch starts at its cable's tray. A rack's only tray keeps
  the old ids.
- Model trays of a classed tray record `voltage: hv|lv` (optional). `cabling.rules` records
  `power_trays` and `lv_max_v` only when power trays are declared. The cable schedule lists
  each cable's trays, as before.
- New model rule `cheme.layout-tray-voltage` (warning): a classed power tray carrying a cable
  of the other class. The gate requirement `trays` fails on it, as on `tray-fill` and
  `tray-separation`. `cheme.layout-tray-rack` also covers `power_trays`: an unknown or repeated
  rack is an error, and trays that do not fit on the power half of the rack at the largest
  width are a warning, on the entry's line. The `tray-fill` hint on a rack's power trunk names
  the number of power trays the rack needs and the `power_trays` entry to write.
- Without `power_trays` the build is byte-identical to before.

## Consequences

- Positive: a tray-fill finding on a rack can be fixed in the input, not only accepted. On the
  ammonia-1 copy, two power trays on PR-1, PR-10 and PR-7 remove all eight `tray-fill`
  findings, and gate `electrical` passes.
- Positive: HV and LV cables can be kept apart by declaring classed trays. A cable that ends up
  in a tray of the other class is a finding, not a silent mix.
- Negative: tray ids on a rack with several trays change (letters). Acceptances keyed by the
  old ids no longer match and need to be reviewed.
- Known limitations: the trays are side by side on one tier, not stacked. The pitch follows the
  largest width, not the actual one. The share-out balances cross-section, not the
  single-layer width rule that some codes apply to large cables. The share-out happens per
  rack, so a cable may change tray position where two racks meet (the link joins the two).
  HV-to-LV spacing beyond `spacing_m` is not checked.

## Evidence

- core#71; files: `src/chemeascode/domains/spatial/schemas.py` (`PowerTrays`,
  `TrayRuleSet.power_trays`, `lv_max_v`, `ModelTray.voltage`),
  `src/chemeascode/domains/spatial/trays.py` (`Cabling._assign`, `_plan`, `tray_findings`,
  `_fill_hint`), `src/chemeascode/domains/spatial/layout_validate.py` (`power_trays`),
  `src/chemeascode/domains/spatial/gates.py` (`TRAY_RULES`), `docs/framework/electrical.md`,
  skill `electrical-cabling`, `tests/test_electrical_trays.py`.
