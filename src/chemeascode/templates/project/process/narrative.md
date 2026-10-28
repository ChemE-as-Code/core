---
# Process narrative. Schema of this front matter: `cheme schema narrative`. Skill
# control-narrative. Each section gets a heading "## <id> <title>" below.
schema: cheme/narrative/v1
sections: []
#  - id: FEED
#    title: Feed and flash
#    equipment: [D-101]
#    blocks: [FL]                # blocks and steps of process/flowsheet.yaml
#    cases: [design]
#    modes: [normal, startup, shutdown]
#    loops: [FIC-101]
#    sequences: [SEQ-START]
#    interlocks: [I-01]
unresolved: []
---

# Process narrative

> PROPOSED. This narrative describes the intended operation. It is not approved for
> implementation; its review status comes from the records in `reviews/`.

Do not repeat values here: refer to the operating case in `process/flowsheet.yaml`, the
setpoints in `control/loops.yaml` and the trips in `control/cause-effect.yaml`.

<!--
One section per process section, in flow order:

## FEED Feed and flash

**Purpose.** What the section does.
**Boundaries.** From where to where (streams, tie-ins).
**Normal operation.** The operating conditions (by case), how material and energy flow, which
loops hold what.
**Modes.** Startup, shutdown, turndown, regeneration, ... and the sequences for them.
**Assumptions and open points.** What is assumed or not known yet.
-->
