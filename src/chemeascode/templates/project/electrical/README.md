# Electrical

Electrical rooms, the motor list, junction boxes and the cable trays of the 3D model (skill
`electrical-cabling`).

| file | what | written by |
|---|---|---|
| `electrical-list.yaml` | substations, transformers, rooms (`kind: mcc \| switchgear \| control \| rack_room`, in a building of `layout/building.yaml`), `defaults`, `motors` (power, voltage and room of the motors derived from the driven equipment; `cable_entry` where a motor's cable leaves the tray beside the machine), `feeders`, `junction_boxes`, `instruments` (`cheme schema electrical`) | people |
| `tray-rules.yaml` (optional) | tray widths, depth, fill, power/instrument separation, rack tray tiers (`cheme schema trays`); every default is ASSUMED | people |
| `cable-schedule.csv`, `cable-schedule.md` | every cable: from, to, size, trays, length | `cheme layout cables --write` |

Example `electrical-list.yaml`:

```yaml
rooms:
  - {id: MCC-1, kind: mcc, building: SUB-1}
  - {id: CR-1, kind: control, building: SUB-1}
motors:                       # derived from pumps, compressors, fans, ...; give what the
  - {driven: P-101A, power_kw: 15, source: vendor data sheet}   # datasheet does not
junction_boxes:               # optional: without them one is proposed per area
  - {tag: JB-101, point: [24.0, 12.5, 1.2], instruments: ["*-1*"]}
```

`cheme layout build` places the trays and cables in `layout/plant-model.yaml`; never edit
the schedule by hand.
