---
schema: cheme/control_philosophy/v1
objectives:
  - {id: OBJ-1, title: Feed the column at the rate of the operating case, loops: [FIC-101]}
  - {id: OBJ-2, title: Steady column feed temperature, loops: [TIC-103, FIC-105]}
  - {id: OBJ-3, title: No gas blow-by from D-101 into the preheater, loops: [LIC-102]}
failures:
  - id: F-AIR
    title: Loss of instrument air
    response: FV-101, LV-102, FV-105 and XV-107 fail closed; the feed stops, D-101 holds its
      liquid. PV-104 is open (see the open points).
    loops: [FIC-101, LIC-102, FIC-105, PIC-104]
  - id: F-HOTOIL
    title: Loss of hot pentane
    response: TIC-103 saturates; the operator reduces the feed (FIC-101) and starts SEQ-STOP.
    loops: [TIC-103, FIC-105]
    sequences: [SEQ-STOP]
  - id: F-LEVEL
    title: Loss of level in D-101
    response: Low-low level trip I-01 closes XV-107 and FV-105.
    interlocks: [I-01]
unresolved:
  - fail position of PV-104
---

# Control philosophy: depropanizer

> PROPOSED. Not approved for implementation; the review status comes from `reviews/`. Loops,
> sequences and trips are defined in `control/loops.yaml`, `control/sequences.yaml` and
> `control/cause-effect.yaml`; this text explains them and does not repeat their values.

## Operating objectives

1. OBJ-1: feed the column at the rate of the operating case.
2. OBJ-2: a steady column feed temperature.
3. OBJ-3: no gas blow-by from D-101 into the preheater.

## Control hierarchy

Regulatory control (the loops) keeps the plant at its operating point. Sequences take it
between modes. Protective functions are the interlocks of the cause and effect list; a
regulatory loop is never counted as a safeguard. The trip I-01 has its own transmitter
(LT-106); it shares the valve FV-105 with the loop FIC-105, which the HAZOP has to judge.

## Normal operation and disturbances

The feed rate is set by the operator on FIC-101. A change of the feed composition reaches the
flash and the preheater; LIC-102 averages the level, TIC-103 corrects the temperature through
the hot pentane flow. A change of the hot oil header pressure is rejected by FIC-105 before it
reaches the temperature.

## Operator and automatic actions

Automatic: the loops in their normal modes, the trip I-01. Operator: the feed rate, the mode
changes during startup and shutdown (SEQ-START, SEQ-STOP), the reset of I-01 once the level
has recovered, the reduction of the feed when the column is unstable.

## Equipment and utility failures

See `failures` in the front matter: loss of instrument air (F-AIR), loss of hot pentane
(F-HOTOIL), loss of level in D-101 (F-LEVEL).

## Assumptions and open points

- The level setpoint and limits are assumptions (`provenance: assumed`).
- The fail position of PV-104 and the flash pressure are open.
- The column's control is not described yet.
