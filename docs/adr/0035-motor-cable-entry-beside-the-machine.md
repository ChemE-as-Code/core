# 0035. A motor's cable entry ends its tray beside the machine

- **Status:** Accepted
- **Date:** 2026-10-30

## Context

`cheme layout build` ran each motor's branch tray to 0.6 m above the terminal box and dropped
it onto the machine, so the branch's last horizontal run lay over the machine's footprint. The
lifting study's crane lane covers that footprint (the item's width across the direction of
travel plus `lane_margin_m` each side, above its top plus `lift_clearance_m`). It left out
only the branch's last vertical run, so the horizontal run blocked the lane. In the ammonia-1
run (process-library#304, cheme 1.0.1) this blocked the lanes of the compressors K-101, K-102,
K-103 and K-701, and gate `lifting-study` failed (core#73). A project had no way to say where a
motor's cable comes in, so the route could not be steered off the machine.

Options considered: a field on the motor entry of the electrical list; a field on the
equipment placement (where the terminal box sits); leaving the tray as it was and not counting
a motor's own tray in the lane. The electrical list is where a motor's cabling is declared, and
an exemption would hide fixed steel over the machine from the lifting study.

## Decision

- The `electrical` kind (`electrical/electrical-list.yaml`) gives a motor an optional
  `cable_entry`: either `side` (`north`, `south`, `east`, `west` of the driven item's plan
  footprint, the placed item's axis-aligned box in site axes) with `offset_m` along it from its
  middle and `clearance_m` out from it, or `point` [x, y]. `elevation_m` is optional. The
  schema refuses neither or both of `side` and `point`, and `offset_m` or `clearance_m` with a
  `point`.
- With it, the build ends the motor's branch at that point, at `elevation_m` (default 0.6 m
  above the terminal box, as without it). The branch keeps `branch_elevation_m` to above the
  point and drops to it as tray. The rest of the way to the terminal box is a cable drop, not
  tray. The cable's `route_length` includes it as the orthogonal distance. The default
  `clearance_m` is the layout criteria's `lane_margin_m`, plus half the tray's width, plus the
  tray rules' `spacing_m`.
- The model's tray entry records the terminal box as `drop_to` (optional; only on such a
  branch). For a tray with `drop_to`, the lifting lane and `clash-tray` count every run. The
  exemption for the last drop onto the item applies only to a branch without one.
- An entry the placed item makes impossible (a point inside the footprint, an offset beyond
  half the side) is `cheme.electrical-cable-entry`, an error on the entry's line in the
  electrical list (build, validate, layout report). The build gives that motor no cable
  (`cable-missing`) and does not end its tray over the machine.
- Without `cable_entry` the build is byte-identical to before.

## Consequences

- Positive: a project can keep a crane lane over a machine clear of its own motor tray. The
  lifting study still names any tray that stands in the lane, including one beside the machine.
- Positive: the cable schedule counts the drop, so its lengths do not shrink.
- Negative: two new optional fields (`motors[].cable_entry` in the electrical list,
  `trays[].drop_to` in the model). Older readers that forbid unknown keys see `drop_to` only in
  models built with an entry.
- Known limitations: the default clearance keeps the tray end outside a lane that runs along
  the chosen side or ends at it. A lane that runs diagonally to the footprint is wider, and an entry between the
  pad and the machine is inside the lane. The router chooses the branch's way from the rack to
  the entry, and that way can still cross the lane higher up. `cheme layout lifting` reports
  both cases. The cable drop has no geometry in the model.

## Evidence

- core#73; this PR.
- `src/chemeascode/domains/control/schemas.py` (`CableEntry`), `domains/spatial/trays.py`
  (`entry_problem`, `entry_point`, `cable_entry_findings`), `domains/spatial/engineering_rules.py`
  (`_lane`), `domains/spatial/schemas.py` (`ModelTray.drop_to`).
- `tests/test_electrical_trays.py` (`test_a_cable_entry_ends_the_motor_tray_beside_the_machine`,
  `test_an_impossible_cable_entry_is_an_error_on_its_line`).
- `docs/framework/electrical.md` (Motor cable entry), skills `electrical-cabling` and
  `structures-access`.
