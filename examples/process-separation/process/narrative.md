---
schema: cheme/narrative/v1
sections:
  - id: FEED
    title: Feed let-down and flash
    equipment: [D-101]
    blocks: [FL, V1, D1]
    cases: [design]
    modes: [normal, startup, shutdown]
    loops: [FIC-101, LIC-102, PIC-104]
    sequences: [SEQ-START, SEQ-STOP]
    interlocks: [I-01]
  - id: PREHEAT
    title: Feed preheat
    equipment: [E-101]
    blocks: [PH, E1]
    cases: [design]
    modes: [normal, startup, shutdown]
    loops: [TIC-103, FIC-105]
  - id: COLUMN
    title: Depropanizer
    equipment: [C-101]
    blocks: [DC3, C1]
    cases: [design]
unresolved:
  - the column's own control (reflux, reboil, pressure) is not described yet
---

# Process narrative: depropanizer

> PROPOSED. This narrative describes the intended operation. It is not approved for
> implementation; its review status comes from the records in `reviews/`.

Values are not repeated here: the operating case is `design` in `process/flowsheet.yaml`, the
setpoints are in `control/loops.yaml`, the trips in `control/cause-effect.yaml`.

## FEED Feed let-down and flash

**Purpose.** The C3 to C5 cut arrives at the battery limit (stream S1) and is let down across
FV-101 (step V1) into the flash drum D-101 (D1). The flash gas leaves overhead (S3); the liquid
(S4) goes on to the preheater.

**Boundaries.** From the battery limit to the outlet of D-101 (S3 and S4).

**Normal operation.** FIC-101 holds the feed rate of the operating case. LIC-102 holds the drum
level by the liquid outlet LV-102, averaging the level so that the preheater sees a steady
flow. PIC-104 holds the flash pressure by the gas valve PV-104; its setpoint is open until the
flash is simulated.

**Modes.** Startup (SEQ-START), normal operation, normal shutdown (SEQ-STOP). The low-low level
trip I-01 protects the preheater against gas blow-by in every mode.

## PREHEAT Feed preheat

**Purpose.** E-101 (E1) heats the flash liquid against hot pentane from the hot oil system
(H1 in, H2 out).

**Normal operation.** TIC-103 holds the column feed temperature by setting the hot pentane flow
FIC-105 (cascade). I-01 closes FV-105 on low-low level in D-101.

## COLUMN Depropanizer

**Purpose.** C-101 (C1) takes propane overhead (S6) and butane and pentane at the bottom (S7).
Its control is not described yet (see the open points).
