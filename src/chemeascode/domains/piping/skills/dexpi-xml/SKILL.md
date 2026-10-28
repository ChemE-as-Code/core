---
name: dexpi-xml
description: How to read and write DEXPI 2.0.1 XML P&IDs by hand in this repository - document structure, ids and references, equipment with nozzles, piping systems/segments/pipes, valves, instruments, and how each is drawn (RepresentationGroup, ShapeUsage, node positions, ConnectorLine). Use before editing any pid/*.xml file.
---

# Writing DEXPI 2.0.1 XML

## Purpose and when to use

P&IDs in `pid/` are DEXPI 2.0.1 XML, edited directly as text. A sheet holds two parallel
trees: **what the plant is** (the conceptual model) and **how it is drawn** (the diagram). Every
plant item is in the first, and a `RepresentationGroup` in the second draws it.

```
Model
  Import Core / Plant (models/2.0.1)
  Object Core/EngineeringModel
    Components ConceptualModel -> Object Plant/PlantModel
        Components TaggedPlantItems           equipment (Tank, CentrifugalPump, ...)
        Components PipingNetworkSystems       lines -> segments -> items + pipes
        Components ProcessInstrumentationFunctions   instruments
        Components ActuatingSystems / InstrumentationLoopFunctions
        Components MetaData                   title block data
    Components Diagram -> Object Core/Diagram.Diagram
        Components Groups                     Border, title block Label, one RepresentationGroup per drawn object
    Components ShapeCatalogues                the symbols (Shape objects) ShapeUsages point at
```

Use it before editing any `pid/*.xml` file.

## Required inputs and missing inputs

The sheet to change (`pid/<sheet>.xml`) and the change asked for. `cheme show <id or tag>`
gives the line ranges to read; a symbol not in the catalogue is handled under "Symbols" below.

## Workflow and tools

### The five element kinds

| XML | meaning |
|---|---|
| `<Object id="X" type="Plant/Piping.GlobeValve">` | an object of a DEXPI class |
| `<Components property="Nodes">` children | objects this one **owns** (composition) |
| `<References objects="#A #B" property="SourceItem"/>` | objects it **points at**, by `#id`, space-separated |
| `<Data property="TagName"><String>T4750</String></Data>` | a value: `String`, `Double`, `Integer`, `Boolean`, `DateTime` |
| `<DataReference data="Core/Diagram.DashStyle.Solid"/>` inside `Data` | an enumeration value |
| `<AggregatedDataValue type="Core/Diagram.Point">` inside `Data` | a structured value (Point, Color, Stroke, PhysicalQuantity) with its own `Data` children |

A physical quantity:

```xml
<Data property="NominalCapacityVolume">
  <AggregatedDataValue type="Core/PhysicalQuantities.PhysicalQuantity">
    <Data property="Unit"><DataReference data="Core/PhysicalQuantities.VolumeUnit.MetreCubed"/></Data>
    <Data property="Value"><Double>26.0</Double></Data>
  </AggregatedDataValue>
</Data>
```

Pressures are gauge or absolute: `PressureGaugeUnit.Bar` (barg) vs `PressureAbsoluteUnit.Bar`.

### Drawing an object

A drawing is a `Core/Diagram.RepresentationGroup` that `Represents` the object and holds:

- a `Core/Diagram.Static` group with one `Core/Diagram.ShapeUsage`: `Shape` reference to a symbol
  in the catalogue (see `shapes.md`), `Position`, `Rotation` (degrees), `ScaleX`/`ScaleY`
  (valves use 0.4), `IsMirrored`;
- for each piping node of the object, a nested `RepresentationGroup` representing the node with
  one `Plant/Diagram.PipingNodePosition` (`Node` reference + `Position`): where pipes attach;
- optionally a label group (`Plant/Diagram.*Label`) with `Core/Diagram.Text` elements whose
  `Template` fragments show attributes (`AttributeRepresentation` -> `Object` + `AttributeName`).

A pipe is drawn by a group representing the `Pipe` with a `Static` holding one
`Core/Diagram.ConnectorLine`: `Source` and `Target` reference the two **PipingNodePosition**
objects (not the nodes), `InnerPoints` lists the bends, `Stroke` the line style.

### Writing the verbose parts: `cheme copy` and `cheme fragment`

Most of a sheet's XML is drawing: a valve is ~60 lines of nodes, node positions and symbol.
Do not type it, and do not write a templating script for it (a generator script uses the
`chemeascode.domains.piping.authoring` API with the same builders, run by `cheme run`; skill `pid-draft`):

- `cheme copy ID --prefix NEWID [--tag T] [--offset DX,DY] [--into PARENT] [--print]`
  duplicates an object with its parts and **everything that draws it** (symbol, nozzles, node
  positions, labels, data table), renames every id (`CentrifugalPump1` -> `NEWID`,
  `CentrifugalPump1_Drawing1` -> `NEWID_Drawing1`, `Nozzle1` -> `NEWID_Nozzle1`), sets the tag
  (and `TagNamePrefix`/`SequenceNumber`/`Suffix`; for an instrument `--tag PICSA-4713.02` sets
  category, letters and number, and the number in its sensor and actuator functions) and the
  label texts that showed it, and moves
  the drawing by the offset (sheet mm, Y down). An `EquipmentBarLabel` data table goes to a free
  slot of the table band instead. It inserts the copy next to the original and prints the new
  ids, the line ranges written and what was **not copied**: the pipes and segments at the
  original's nozzles, an actuating system's valve reference. Connect those by hand.
  `--print` shows the XML without writing. `--into` puts a copy into another parent (a valve
  into another segment's `Items`, its drawing into that segment's drawing). An instrument copied
  with another measured variable (`--tag FI-148` from `AI-104`) gets the sensor `FT148` (and
  actuator `FV...`), not `AT148`. Options that adapt the copy in the same command (repeat each
  as needed):

  | option | does |
  |---|---|
  | `--rename HV-146=HV-147` | an inner tag: in the copied data, the label texts and the ids that spell it (`Line_L105_HV147`) |
  | `--renumber 144:145` | a number in the inner tags, label texts and ids (`TSV-144` -> `TSV-145`) |
  | `--set 'FluidCode=Liquid nitrogen'` | a data value on every copied object that has it (line and segments), and the labels showing it |
  | `--connect PIPE=ITEM:NODE` (`PIPE.target=...`) | a copied pipe's open end (old or new id), with its segment's end and the ConnectorLine's `Source`/`Target` |
  | `--sense-at ID[:X,Y]` | an instrument's `SensingLocation`; with X,Y a new `InstrumentationNodePosition` there in ID's drawing, where the measuring line starts |

  Its report ends with `duplicate tags:` -- inner tags the copy shares with objects on the
  P&IDs. `cheme validate` fails on them (`cheme.duplicate-tag`).
- `cheme fragment KIND --id ID [--sheet pid/<sheet>.xml] ...` prints a fragment with a
  `CONCEPTUAL` and a `DRAWING` part, each after a comment saying where to paste it (and a
  `SHAPE` part when the symbol is not in the catalogue yet). Pass `--sheet`: shape ids are then
  looked up in the sheet's catalogue, pipe ends in its node positions, label texts in its data.

  | kind | options | ids it writes |
  |---|---|---|
  | `valve` | `--class GlobeValve\|BallValve\|GateValve\|SwingCheckValve\|ButterflyValve --dn 80 --at X,Y [--rotation R] [--tag C3]` | `ID`, nodes `ID_N1` (inlet) `ID_N2` (outlet), positions `ID_N1_Position`, `ID_N2_Position` 2 mm either side |
  | `tee` | `--dn 80 [--branch-dn 50] --at X,Y [--rotation R] [--branch up\|down\|left\|right]` | `ID`, `ID_N1` run in, `ID_N2` run out, `ID_N3` branch, positions 0.001 mm apart |
  | `pipe` | `--from ITEM:NODE --to ITEM:NODE [--points x,y;x,y]` (the bends) | `ID`, its ConnectorLine between the two nodes' positions |
  | `segment` | `--from ITEM:NODE --to ITEM:NODE [--like SEGMENT] [--number S2] [--dn 80]` | `ID` with empty `Connections`/`Items` to fill, `ID_Drawing` |
  | `node` | `--dn 80 [--standard Din2448\|Iso6708\|none] [--at X,Y]` | `ID`, with `--at` `ID_Position` |
  | `label` | `--for ID --attribute TagName [--at X,Y]` | `ID` (label class from the object: `ValveLabel`, `EquipmentTagNameLabel`, ...) |
  | `equipment` | `--class CentrifugalCompressor --tag K-101 --at X,Y [--shape NAME] [--rotation R] [--scale S\|SX,SY] [--label-at X,Y] [--marker NAME:dy[:SY][:m] ...] --nozzle N1:dx,dy[:DN] ...` | `ID` with nozzles `ID_N1` (node `ID_N1_Node`), symbol, tag label; pipes attach at `ID_N1_Node_Position` |
  | `nozzle` | `--on EQUIP --at dx,dy [--dn 50] [--tag N7]` (needs the sheet) | `ID` with node `ID_Node`, into the equipment and its drawing |
  | `instrument` | `--tag PIC-101 --at X,Y --sense ITEM[:x,y] [--field]` | `ID` with sensor `ID_Sensor`, measuring line `ID_MeasuringLine`, bubble nodes `ID_Top`/`_Bottom`/`_Left`/`_Right` |
  | `signal` | `--from INST --to VALVE\|INST[,VALVE...] [--fail-action FC\|FO\|FL] [--number PV-111] [--points x,y;...]` (needs the sheet) | `ID` (SignalLineFunction, dashed line); to a valve also `ID_Actuating` and, if the valve has none, `<valve>_ActuatingSystem` |
  | `offpage` | `--in\|--out --at X,Y [--rotation R] [--dn 80] [--note TEXT] [--note-at X,Y]` | `ID` (Flow In/Out PipeOffPageConnector) with node `ID_N`, position `ID_N_Position` |
  | `line` | `--number L-101 --dn 100 [--fluid Water] [--at X,Y]` (the label) | `ID` (PipingNetworkSystem) with empty `Segments`, `ID_Drawing` |
  | `note` | `--text TEXT --at X,Y` | `ID`, a Static text at the top of the diagram, owned by no object |
  | `shape` | `NAME` (e.g. `COLUMN_SHAPE`, `compressor`) | the catalogue Shape to paste, or "already as #ShapeN" |

  `--rotation` is the flow direction: 0 left to right, 90 downwards, 180 right to left, 270
  upwards (Y down). A tee's `--branch` is absolute (up, down, left, right on the sheet); it must
  leave the run sideways, and without it the branch leaves on the left of the flow. Node
  positions a fragment draws are named `<node id>_Position`; nodes already on the sheet have
  other position ids (`PipingNodePosition8`), which only `--sheet` finds. Without `--sheet`,
  `fragment` uses the one sheet holding the ids it refers to, and says so; still pass `--sheet`
  in commands you write down.

  Drafting a sheet takes no generator script: `equipment` (with its nozzles), `line` + `segment`
  + `valve`/`tee` + `pipe`, `offpage` at the sheet edges, `instrument` on a nozzle or segment,
  `signal` from a controller or switch to its valves, `note` for free text. With `--sheet`, the
  comments name the holder's id and line (`into <Components property="Nozzles"> of T101
  (pid/P-04.xml:9229)`); paste each part there.

  - `equipment`/`nozzle` offsets are from the symbol's centre along the sheet axes and name a
    point on its outline; a nozzle with a DN gets a 4 mm stub outwards (along the axis the
    offset points) and its pipe attaches at the stub's end. A nozzle without a DN is an
    instrument connection: its `InstrumentationNodePosition` is where an `instrument --sense`
    measuring line starts. A pipe's `--from`/`--to` ITEM is the **nozzle** (`T101_N1`), not the
    equipment.
  - `--class` is the DEXPI class; the symbol defaults by class (`shapes.md`, "default for").
    Beds and trays inside a column or adsorber are `--marker` symbols in the same drawing:
    `--marker COLUMN_PACKED_BED_SHAPE:-20:1.5` (a 30 mm bed centred 20 mm above the symbol
    centre; ScaleX is the column's), `--marker COLUMN_TRAY_SHAPE:10:1:m` (a tray, mirrored for
    the downcomer on the left). Repeat it, one per bed or tray shown.
  - `signal` to a valve models what a dashed line only shows: an `ActuatingFunction` in the
    instrument referencing the valve's `ActuatingSystem` (made with its `ControlledActuator`
    and `OperatedValveReference` when the valve has none) and a `SignalLineFunction` from the
    instrument to it. A trip is one `signal` with several targets (`--to XV136,PV111`); a
    second signal to the same valve joins its actuating system. When several parts go into a
    block the holder lacks, only the first says "create it"; the others say "the ... part above
    creates": paste them into that one block (two blocks of one property lose objects). Signal
    and measuring lines are routed orthogonally out of the node (one bend, or two round what
    lies between), clear of the bubbles, equipment and texts drawn on the sheet and crossing as
    few pipes as they can; check `cheme validate`'s drawing findings and pass `--points` where
    a line still crosses something. A signal that repeats an existing instrument-to-valve relation gets a WARNING. `cheme show <valve>` then
    lists the instruments acting on it. If the valve's drawing has an actuator symbol already,
    only the attach point is added; remove a dashed PolyLine that drew the signal before.
  - Trip and interlock text goes in a `note` (or a signal line), not into an instrument's or
    valve's drawing: there `cheme.label-literal` reads it as a label of that object.

### Changing what is on a sheet: `cheme move`, `rename` and `set`

Use these before a hand edit: they find every coordinate, reference and label text for you, run
`cheme fmt` afterwards, and `--print` shows the change as a diff without writing.

- `cheme move ID --offset DX,DY`: moves everything that draws ID (symbol, node positions,
  labels, bends of lines inside its group) and prints each coordinate it changed. Lines attached
  to its node positions follow by reference; their bends stay put and are listed as
  `stretched`, a straight line that is no longer horizontal or vertical as `now slanted`. An
  equipment data table stays in its band (move it by its own id). ID may also be a drawing
  element (a label `Text`, to nudge only it).
- `cheme rename OLD NEW [--children]`: an id and every `#OLD`; `--children` also renames
  `OLD_*`. Given a tag (`cheme rename HV-146 HV-147 [--ids]`): the tag data
  (`TagNamePrefix`/`SequenceNumber`/`Suffix` too; for an instrument category, letters, number
  and its sensor/actuator numbers) and the labels showing it; `--ids` also the ids that spell
  it. A tag (`PipingComponentNumber`, a safety valve's `PositionNumber`, ...) addresses the
  object like its id. When two objects share the tag, give the one to retag by its id with
  `--tag`: `cheme rename Inst_Y FI-150 --tag` (the sensor becomes `FT150`). A valve and its
  own actuation chain (actuating system, actuating function, an instrument function tagged
  alike) sharing `XV-104` are retagged together by `cheme rename XV-104 XV-105`. Unknown ids,
  taken names and tags another valve or instrument already has exit 2.
- `cheme set ID PROP=VALUE...`: data values by their DEXPI name, in the type DEXPI gives
  them: `FluidCode=Nitrogen`, `OnHold=OnHold` (enumeration member),
  `InsulationThickness='50 mm'` and `UpperLimitDesignPressure='16 barg'` (value and unit),
  `Stroke.Width=0.5` (a value inside an aggregate, on a drawing element),
  `Text='to flare'` on a note's `Text`. `PROP=` removes the value. Every label whose template
  shows the attribute gets its cached text updated, so `cheme.label-stale` stays clean.

Hand edits remain for what is short: re-pointing a `References` (a pipe's `TargetNode`, a
segment's ends, a ConnectorLine's `Target`), moving an existing `<Object>` block into another
segment, deleting blocks. After pasting: `cheme fmt` re-indents everything.

### Symbols: scales and missing shapes

The catalogue (`shapes.md`) holds the reference's shapes and the ones cheme-as-code adds:
compressors (centrifugal, axial), turbine/expander, blower, column body with packed-bed and tray
markers (`fragment equipment --marker`), gas filter, silencer (inline: `fragment valve --class Silencer`), air cooler, general
and shell-and-tube exchangers, electric heater, ambient vaporizer, flat-bottom tank, plate-fin
exchanger and gate valve. `empty-sheet.xml` has them all; for an older sheet,
`cheme fragment shape NAME --sheet pid/<sheet>.xml` prints the one to paste (or says it is
there), and `fragment equipment` adds a SHAPE part by itself.

Scales that stay legible on A3: equipment 1.0 (pumps 15 mm, vessels 20 x 25 mm; columns ScaleX
1.0, ScaleY for the height), valves 0.4 (`--scale 0.5` for check valves and crowded areas, never
below 0.4), actuators 0.4-0.45, nozzles 0.8 x 0.4, instrument bubbles 1.0, off-page arrows 0.7,
tees 0.0001 (invisible). `shapes.md` gives each added shape's scale, its ISO 10628-2
registration number and its ports (where nozzles and pipe ends go, at scale 1). Most added
shapes are not in `empty-sheet.xml`: `cheme fragment shape NAME --sheet ...` (or the SHAPE part
of an equipment/valve fragment) adds one to the sheet's catalogue on first use.

When a symbol is truly missing: use the nearest catalogue shape that means the same thing
(ISO 10628-2 meaning, not looks: a cooler is an exchanger shape, not a pump), and say what it
stands for in a `note` or the review. Only if none fits, add a Shape named after its ISO
meaning (`VORTEX_BREAKER_SHAPE`), with the name as its `SymbolRegistrationNumber` as the
reference does: never invent a registration number, and never use one shape for things of
different meaning.

### Recipes

Start every recipe with `cheme show <id or tag>`: it prints the `file:start-end` of the
object's `<Object>` block and of its drawing(s), its owner chain, and the ids it references and
that reference it, each with a line number. Read those line ranges instead of the whole file.
After every recipe: fmt, validate, `cheme render --png --crop ...` around the change, and
`cheme diff HEAD --list` to check the change list is what you meant (see Loop).

#### Insert a valve into an existing pipe

`cheme fragment valve --id ... --class ... --dn ... --at X,Y --rotation R --sheet ...` gives
the valve and its drawing; `cheme fragment pipe` the new pipe.

1. conceptual: add the valve with two `PipingNode`s to the segment's `Items`; split the pipe into
   two (old pipe now ends at valve node 1, a new pipe starts at valve node 2). If the old pipe was
   the segment's last one, the segment's `TargetItem`/`TargetNode` stay as they were (the new
   pipe ends there).
2. drawing: add the valve's group (ShapeUsage on the line, two PipingNodePositions 2 mm either
   side along the line), shorten the old ConnectorLine to end at the first node position, add a
   ConnectorLine for the new pipe from the second node position to the old end.

#### Insert a tee and a branch (split a segment)

`cheme fragment tee`, `segment` and `pipe` write the new objects and their drawings;
`snippets/tee-branch.xml` and `tee-branch-drawing.xml` show the same in the reference.

1. `cheme show <segment id>` and pick the pipe to split and the point on its line.
2. Split the segment at that pipe into **A** (from the old source to the tee) and **B** (from the
   tee to the old target):
   - A keeps the pipes before the split; the split pipe now ends at tee node 1 (run in). The tee
     with its three `PipingNode`s goes into **A's `Items`** (A ends at it). A's
     `TargetItem`/`TargetNode` = the tee / node 1.
   - B is a new `PipingNetworkSegment` in the same system, holding a new pipe from tee node 2
     (run out) to where the split pipe used to end, the remaining pipes and the items after the
     split (move their `<Object>` blocks from A to B). B's `SourceItem`/`SourceNode` = the tee /
     node 2; B's `TargetItem`/`TargetNode` = A's old target.
   - Give B the segment data A has (fluid, piping class, the three DN properties).
3. The branch: a new segment (in this system or in the branch's own `PipingNetworkSystem`, with
   its own `LineNumber`) whose first pipe starts at tee node 3.
4. Drawing: the tee group (Shape12, three node positions, see Conventions) goes in A's drawing
   group; a group for B with its pipes' ConnectorLines (move the moved items' groups into it);
   a group for the branch segment. The split ConnectorLine ends at the run-in node position; the
   new one starts at the run-out position.
5. `cheme validate`: `cheme.segment-ends` catches ends that disagree with their pipes.

#### Parallel / spare equipment (a standby pump)

Example: a spare P4711B beside P4711 (suction line 47121, discharge 47122, both DN 80, flowing
left to right at y 154).

1. `cheme render pid/P-01.xml --png --crop ...` and pick free space: here 30 mm below.
   `cheme copy P4711 --prefix Pump_P4711B --tag P4711B --offset 0,30`. Note what it says is
   not copied: `Pipe1`/`PipingNetworkSegment1` at `Nozzle1` (suction) and `Pipe2`/
   `PipingNetworkSegment2` at `Nozzle2` (discharge). The copy's nozzle nodes are
   `Pump_P4711B_PipingNode2` (N1) and `Pump_P4711B_PipingNode3` (N2).
2. **Suction tee** on the duty pump's suction pipe (the tee recipe below, with fragments):
   `cheme fragment tee --id Tee_47121_P4711B --dn 80 --at 66,154 --branch down --sheet pid/P-01.xml`.
   CONCEPTUAL into `PipingNetworkSegment1`'s `Items` (it now ends at the tee); point `Pipe1`'s
   and the segment's `TargetItem`/`TargetNode` at `Tee_47121_P4711B`/`Tee_47121_P4711B_N1`, and
   `Pipe1`'s ConnectorLine `Target` at `#Tee_47121_P4711B_N1_Position`. DRAWING into
   `PipingNetworkSegment1`'s drawing group.
3. **Run on to the duty pump**: `fragment segment --id Seg_47121_S2 --from Tee_47121_P4711B:Tee_47121_P4711B_N2 --to Nozzle1:PipingNode2 --like PipingNetworkSegment1 --number S2 --sheet pid/P-01.xml`
   into the system's `Segments` (drawing into the system's drawing group), and
   `fragment pipe --id Pipe_47121_S2 --from Tee_47121_P4711B:Tee_47121_P4711B_N2 --to Nozzle1:PipingNode2 --sheet pid/P-01.xml`
   into its `Connections` (drawing into its drawing group).
4. **Branch to the spare**: `fragment segment` from the tee's `_N3` to
   `Pump_P4711B_Nozzle1:Pump_P4711B_PipingNode2`, an isolation valve
   `fragment valve --id Valve_P4711B_in --class GateValve --dn 80 --at 70,184 --sheet pid/P-01.xml` in its `Items`,
   and two pipes: tee `_N3` -> valve `_N1` with `--points 66,184` (the bend), valve `_N2` ->
   the nozzle node. Pass `--sheet pid/P-01.xml` to each: after pasting step 3, the tee and the
   copied pump are on the sheet and their node positions are looked up there.
5. **Discharge tee** on the duty pump's discharge pipe the same way (`--at 100,154 --branch down`
   on `PipingNetworkSegment2`, a run segment on to the old target). The spare's branch flows
   **into** the tee: a segment from `Pump_P4711B_Nozzle2:Pump_P4711B_PipingNode3` to the tee's
   `_N3`, with a check valve (`--class SwingCheckValve`) and an isolation valve. It ends at the
   tee's branch node and does not own the tee: only the segment that ends at its run-in node
   does.
6. Labels: `fragment label --id Label_C9 --for Valve_P4711B_check --attribute PipingComponentNumber --sheet pid/P-01.xml`.
7. **A copy of a line with its valves** (a second fill line beside L-104) is one command:
   `cheme copy Line_L104 --prefix Line_L105 --tag L-105 --offset 0,40 --rename HV-146=HV-147 --renumber 144:145 --set 'FluidCode=Water' --connect Line_L104_S2_P2=T102_N7:T102_N7_Node`
   (`T102_N7` a free nozzle added for the new line: `--connect` refuses a node another pipe
   already ends at).
   An instrument beside another: `cheme copy Inst_AI104 --prefix Inst_FI148 --tag FI-148 --offset 14,0 --sense-at Line_L102_S1:318,45`
   (the sensor becomes `FT148`, its measuring line starts at a new node on the segment). Check
   the `duplicate tags:` line of the report is `none`; nudge the result with
   `cheme move Inst_FI148 --offset DX,DY` after the render.
8. Remove an `Items` left empty, then the Loop. Expected: `cheme.equipment-not-listed` for
   P4711B until `lists-sync` adds it; the new segments go into the line list's `segments` if
   their DN differs.

#### Bypass around a valve

Two tees, four segments. Example: control valve C1 (`GlobeValve2`) on line 47123, which runs
upwards at x 160 (`Pipe3` from `Nozzle4` to C1's inlet at y 121, `Pipe4` from C1's outlet at
y 117 up to `Nozzle5`), all in `PipingNetworkSegment3`.

1. `fragment tee --id Tee_C1_in --dn 80 --at 160,127 --rotation 270 --branch right --sheet pid/P-01.xml`
   (upstream) and `--id Tee_C1_out ... --at 160,111` (downstream).
2. The four segments, each tee owned by the segment that **ends** at its run-in node:

   | segment | from | through | to | owns |
   |---|---|---|---|---|
   | S1 (`PipingNetworkSegment3`, kept) | old source | `Pipe3` | `Tee_C1_in_N1` | `Tee_C1_in` |
   | S2 (`fragment segment --number S2 --like PipingNetworkSegment3 --sheet pid/P-01.xml`) | `Tee_C1_in_N2` | new pipe, C1, `Pipe4` | `Tee_C1_out_N1` | `Tee_C1_out`, C1 |
   | S3 (new) | `Tee_C1_out_N2` | new pipe with `Pipe4`'s old bends | old target `Nozzle5` | |
   | S4, the bypass (new) | `Tee_C1_in_N3` | pipe, bypass valve (`fragment valve --class GlobeValve --at 170,119 --rotation 270 --tag C3 --sheet pid/P-01.xml`), pipe | `Tee_C1_out_N3` | the bypass valve |

3. Move C1's `<Object>` block and `Pipe4` into S2 (and C1's and `Pipe4`'s drawing groups into
   S2's drawing); re-point `Pipe3`'s and S1's targets and `Pipe4`'s target at the tees, and their
   ConnectorLines' `Target` at the tees' `_N1_Position`s; drop `Pipe4`'s `InnerPoints` (S3's
   pipe takes the bends:
   `fragment pipe --id Pipe_47123_S3 --from Tee_C1_out:Tee_C1_out_N2 --to Nozzle5:PipingNode8 --points '160,61;181,61' --sheet pid/P-01.xml`,
   which takes `Nozzle5`'s real node position from the sheet). The bypass pipes bend at the
   tees' height: `--points 170,127` and `--points 170,111`.
4. Keep the ids of what you move: a moved object shows as `moved`/`modified` in
   `cheme diff --list`, a renamed one as removed plus added.
5. The Loop. Isolation valves either side of C1 and an `NC` note on the bypass valve are
   engineering decisions: add them or record why not in `DESIGN.md`.

#### Remove an item cleanly

1. `cheme show <id or tag>`: note its block, its drawing(s) and **every incoming reference**.
   For equipment it also prints `connections:` (the segment and line at each nozzle, and what is
   at the other end) and `only for <tag>:` -- the segments, whole lines and branch tees that
   exist only for it and dangle once it is gone, with the instrument chains of their items. For
   a valve or instrument, `instrumentation:` follows the chain: loop, sensing location,
   measuring line, signal line, actuating function, actuating system, actuator and valve, each
   with its block and drawing.
2. Conceptual: delete the item's `<Object>` block (with its nodes). Reconnect or delete the pipes
   that referenced its nodes: for an inline valve, delete one of its two pipes and point the
   other at the far node (`SourceItem`/`SourceNode` or `TargetItem`/`TargetNode`); for
   equipment, delete the pipes and segments (or whole systems) that only served it. Fix the ends
   of every segment whose first or last pipe changed.
3. Drawing: delete the item's `RepresentationGroup` (symbol, node positions, labels -- valve,
   nozzle and equipment labels, an `EquipmentBarLabel` data table on the equipment band), the
   groups of every deleted pipe and segment, and stretch the remaining `ConnectorLine` to the
   node position of the new end (`Source`/`Target`, and `InnerPoints` if it bent).
4. Instrumentation: `ActuatingSystem`s whose `OperatedValveReference` names the valve (with
   their actuator drawing and `ActuatingSystemNumberLabel`/`FailActionLabel`),
   `ProcessSignalGeneratingFunction`s whose `SensingLocation` is the item, and the measuring and
   signal lines drawn to it. Delete them or re-point them, as the change asks.
5. `grep -n '#<id>\b' pid/<sheet>.xml` for each deleted id (item, nodes, pipes, node positions)
   must print nothing. Then remove the tag from the lists (`lists-sync`).

#### Add an instrument with an instrument nozzle

The measured point is an item on the line (here a blind flange on a short branch with an
isolation valve) that carries both a `PipingNodePosition` (the pipe attaches) and an
`InstrumentationNodePosition` (the measuring line attaches). Copy from
`snippets/instrument-nozzle.xml`, `instrument-nozzle-drawing.xml`, `instrument-function.xml`
and `instrument-function-drawing.xml`.

1. Conceptual: a tee on the line (recipe above), a branch segment: pipe from tee node 3 to the
   isolation valve, `DirectPipingConnection` from the valve's node 2 to the `BlindFlange`'s one
   node; segment ends = tee node 3 and the blind flange node.
2. A `ProcessInstrumentationFunction` under `ProcessInstrumentationFunctions` with
   `ProcessInstrumentationFunctionCategory` (`P`), `ProcessInstrumentationFunctions` (`I`),
   `ProcessInstrumentationFunctionNumber`; inside it a `ProcessSignalGeneratingFunction` whose
   `SensingLocation` references the blind flange, and a `MeasuringLineFunction` from the signal
   generating function to the instrument function.
3. Drawing: the blind flange group holds its symbol (`Shape13`, scale 0.4, rotated to face the
   valve), a `PipingNodePosition` for its node, and an `InstrumentationNodePosition` in its
   `NodePositions` 0.8 mm off the node position, at the flange face. The bubble group (see
   Conventions) holds the label texts, the four bubble `InstrumentationNodePosition`s and the
   `MeasuringLineFunction` group with a `ConnectorLine` from the flange's
   `InstrumentationNodePosition` to the bubble's lower one.
4. Add the printed tag (e.g. `PI-4712.01`) to `control/instrument-list.yaml` (`lists-sync`).

#### Change a line's DN everywhere

1. `cheme show <LineNumber>` lists the system, its segments, items, pipes and nodes with
   their DN and line numbers.
2. Decide which segments change size, by `SegmentNumber`. A line often has branches of its own,
   smaller DN (line 47126 is DN 50 with DN 25 segments S2 drain, S5 and S9 instrument
   connections). **Leave those branch segments, their nodes and the tee's branch node as they
   are** unless the branch is resized too; a tee whose branch keeps its size is then a reducing
   tee (run nodes new DN, branch node old DN), as in the reference.
3. Set the three DN properties (Conventions) on the `PipingNetworkSystem` (if its main run
   changes), on each segment that changes, and on each `PipingNode` those segments' pipes connect
   -- the run in/run out nodes of the tees and the nodes of the nozzles at the run's ends. If the
   equipment nozzle keeps its size, put a reducer in the segment instead of changing that node.
   `cheme.dn-mismatch` does not notice a branch resized together with the run: check the
   `cheme show <LineNumber>` output again afterwards, segment by segment.
4. Update the cached `Text` of every label that shows the DN: the system label
   (`PipingNetworkSystemLabel`, e.g. `MNc 47126 75HB13 50`), segment labels, nozzle labels.
   `grep -n '<String>[^<]*\b50\b' pid/<sheet>.xml` inside the line's drawing groups finds them;
   `cheme.label-literal` (validate) warns about a literal label such as `DN = 25/50` that no
   longer matches its object's nodes.
5. Change `nominal_diameter` in `piping/line-list.yaml`, and list every segment whose DN differs
   from it under `segments` (all of them, so `cheme.line-dn-mismatch` compares each).
6. `cheme validate` must not report `cheme.dn-mismatch`, `cheme.label-stale`,
   `cheme.label-literal` warnings or `cheme.line-dn-mismatch`.

## Validation and failure handling

### Rules that keep a sheet valid

1. **Every `<Object>` has an id, unique in the document**, matching `[A-Za-z_][A-Za-z0-9_]*`
   (no hyphens, no dots). Use readable ids: `Pump_P101B`, `Pipe_P101B_suction`.
   `cheme fmt` names any object you leave without one.
2. **References point at ids that exist.** Rename an id with
   `cheme rename OLD NEW [--children]`: it renames every `#OLD` too (`--children` also the
   ids derived from it, `OLD_Drawing`, `OLD_Pos`, ...) and refuses a name that is taken.
3. **A pipe connects two nodes.** Each `Plant/Piping.Pipe` has `SourceItem` + `SourceNode` and
   `TargetItem` + `TargetNode`. Nodes belong to items: a nozzle owns one `PipingNode`, an inline
   valve owns two. Convention: **node 1 (first) is the inlet, node 2 (second) the outlet**; flow
   runs source -> target.
4. **A segment is one run in flow order.** `PipingNetworkSegment` owns `Items` (valves, reducers,
   ...) and `Connections` (pipes), and references its own ends: `SourceItem`/`SourceNode` = where
   the first pipe starts, `TargetItem`/`TargetNode` = where the last one ends (see Conventions).
   One node is connected by at most one pipe.
5. **Tags** are `Data property="TagName"` on equipment (with `TagNamePrefix`,
   `TagNameSequenceNumber`), `PipingComponentNumber` on valves, `LineNumber` on a piping system,
   category + functions + number on an instrument function (printed `PI-4712.01`). Keep the
   equipment, line and instrument lists in step (`lists-sync`).
6. **Every plant item is drawn**: a `RepresentationGroup` under `Diagram/Groups` (or nested in
   its owner's group) with `<References objects="#TheItem" property="Represents"/>`.
7. Coordinates are millimetres on the sheet, **Y down** (like SVG). The reference sheet is
   420 x 297 (A3; `MinX`/`MaxX`/`MinY`/`MaxY` on the Diagram). Keep new symbols inside the
   border and off existing ones.

### Conventions

`cheme validate` checks the ones that name a rule id. The snippets are unmodified excerpts
of the reference P&ID and follow them.

- **Coordinates**: millimetres, origin top left, **Y grows downwards**. `--crop X0,Y0,X1,Y1` of
  `cheme render` takes the same numbers. Rotation is in degrees.
- **Segment ends** (`cheme.segment-ends`): `SourceItem`/`SourceNode` of a segment are the
  first pipe's `SourceItem`/`SourceNode`; `TargetItem`/`TargetNode` are the last pipe's
  `TargetItem`/`TargetNode`. Prefer the node the last pipe ends at. Validate also accepts the
  reference convention: when the segment **owns** its end item (it is in the segment's `Items`,
  e.g. the tee or check valve it ends at), the node may be that item's other node -- the one the
  next segment starts at, so consecutive segments share a node (`snippets/tee-branch.xml`: S3
  ends at `PipeTee1`/`PipingNode30`, where S4 starts). Do not "fix" existing segments that use
  it. For a segment that ends in a `DirectPipingConnection` (valve bolted to a blind flange),
  that connection is the last one.
- **Tees and property breaks only at segment ends.** A `PipeTee` (or `PropertyBreak`) is where
  segments meet. It is an `Item` of exactly one segment: the one that **ends** at it. The
  segments leaving it start at its other nodes and do not own it. A tee owns three
  `PipingNode`s: run in, run out, branch.
- **Drawing a tee**: one `ShapeUsage` of `Shape12` at the tee point, `ScaleX`/`ScaleY` 0.0001
  (a dot), and the three `PipingNodePosition`s 0.001 mm from it towards their pipes: run in at
  (x - 0.001, y), run out at (x + 0.001, y), branch at (x, y - 0.001) for a branch going up
  (`snippets/tee-branch-drawing.xml`). The lines then appear to meet in one point.
- **Instrument bubble** (`Shape16` field, `Shape17` central/DCS with a middle bar; scale 1):
  `Position` is the centre (x, y). The bubble is a stadium **13.5 mm wide, 7.5 mm high**: straight
  top and bottom from x - 3 to x + 3, ends of radius 3.75 -- keep 6.75 mm clear left and right.
  Its group has four `InstrumentationNodePosition`s where lines attach: top (x, y - 3.75),
  bottom (x, y + 3.75), left (x - 6.75, y), right (x + 6.75, y). In the reference measuring lines
  end at the bottom one; signal lines leave from the top one (going up) or a side one (going
  sideways). The label (`ProcessInstrumentationFunctionLabel`)
  has two `Text`s, size 3, `CenterCenter`: the letters (category + functions, e.g. `PI`) at
  (x, y - 2.25), the number at (x, y + 1.2). The measuring line is a `ConnectorLine` (green,
  0.2 mm) from an `InstrumentationNodePosition` on the sensing location to the bubble.
- **Nominal diameter is stated three times** on every `PipingNode`, segment and system:
  `NominalDiameterRepresentation` (`DN 50`), `NominalDiameterNumericalValueRepresentation`
  (`50`) and `NominalDiameterTypeRepresentation` (`DN`). Change all three together. Two nodes
  joined by a pipe have the same DN unless one item is a reducer (`cheme.dn-mismatch`).
- **Labels cache their text.** A `Core/Diagram.Text` holds a `TextTemplate` (fragments that name
  attributes) and the rendered `Text` string. When you change an attribute a label shows, update
  the cached `Text` too (`cheme.label-stale` finds the ones you missed). A label made of
  literal text only (`DN = 25/50` on the reference's safety valve, the nozzle DN labels) follows
  nothing: `cheme.label-literal` reports it as info while it repeats the object's DN, a
  physical quantity or a string, and warns once it contradicts them.

### Loop

After every change:

```sh
cheme fmt pid/<sheet>.xml
cheme validate
cheme render pid/<sheet>.xml --png --crop 240,120,320,180   # build/<sheet>_crop-240-120-320-180.png
cheme diff HEAD --list                                       # one line per changed plant item
```

Fix `error`s before anything else; each finding gives `file:line`, the rule and a hint. Look at
the PNG (crop with a margin of 20 mm around what you changed; `--scale` sets the pixels per mm).
A crop is written next to the full sheet under its own name, so `render --png` and
`render --png --crop ...` (or `--rev HEAD --crop ...`, `build/<sheet>@HEAD_crop-...png`, for the
before picture) never overwrite each other.
`cheme diff --list` prints a `<sheet>:` line, then one line per plant item a change belongs
to: `<kind> <class> <id> [tag]: N added, M removed, K modified`, where `<kind>` is what happened
to the item itself (`added`, `removed`, `modified`, or `changed` when only its parts or drawing
did). Nozzles, nodes, labels and drawing elements count under their item, pipes and segments
under their line. `--list --verbose` adds each change under its item, `--list --flat` prints one
line per object instead (`<kind> <class> <id> [tag] (<domain>) <attrs> -> drawn as <owner>`):
every line should be a change you meant, and every changed plant item should be drawn.
`cheme diff --json` gives the same as data (each change's `item`, and `items`).

| finding | usual cause | fix |
|---|---|---|
| `xml.syntax` | unclosed tag, stray `&` | fix the XML at that line |
| `dexpi.load` "Reference 'X' ... not found" | `#X` names no object | fix the id or add the object |
| `dexpi.load` unknown class / property | misspelt `type` or `property` | copy the spelling from a snippet |
| `cheme.duplicate-id` | copied snippet without renaming | `cheme rename OLD NEW` (renames its references) |
| `cheme.duplicate-tag` | two piping components (`PipingComponentNumber`/`PositionNumber` such as `HV-146`) or two instruments share a tag, e.g. after a copy | `cheme rename ID HV-147 --tag` (an instrument: `rename ID FI-150 --tag`, its sensor and actuator follow), or copy again with `--rename`/`--renumber` |
| `cheme.not-drawn` | conceptual object without a drawing | add a RepresentationGroup |
| `cheme.segment-ends` | segment Source/Target Item/Node is not where its pipes start/end (pyDEXPI's `pydexpi_segment_connectivity`, `..._reference_nodes_and_items_match`) | point the segment's SourceItem/SourceNode at where its pipes start, TargetItem/TargetNode at where they end (or, for an end item the segment owns, its other node; see Conventions) |
| `cheme.dn-mismatch` | a pipe joins nodes of different DN (also at a reducer port) | give both nodes the DN of the pipe; a reducer's own two nodes carry the two DNs |
| `cheme.label-stale` | label text no longer what its template shows, or AttributeName misspelt | update the cached `Text`, or fix the AttributeName |
| `cheme.label-literal` warning | a literal-only label (`DN = 25/50`) contradicts its object's DN, a quantity or a string | correct the text, or show the attribute with an `AttributeRepresentation`; as info it only says the label repeats the data and must be changed with it |
| `pydexpi_piping_node_single_connection` | two pipes on one node | give the item another node, or reroute |
| `cheme.dn-mismatch` | DN changed on one side of a pipe only | change all three DN properties on both nodes, or add a reducer |
| `cheme.label-stale` | data changed, cached label `Text` not | change data with `cheme set` (it updates the labels), or set the `Text` to what the template renders |
| `cheme.line-*`, `cheme.instrument-*` | sheet and list disagree | `lists-sync` skill |

## Outputs and provenance

The edited `pid/<sheet>.xml`, formatted by `cheme fmt`, and the lists kept in step
(`lists-sync`). `cheme diff HEAD --list` shows which plant items the change touched.

## Required human judgment

Isolation valves, an `NC` note on a bypass valve and similar engineering decisions: add them or
record why not in `DESIGN.md`. A substitute for a missing symbol is said in a `note` or the review.

## References

### Snippets (copy, then rename every id)

To read how the reference does something. To write, prefer `cheme copy` and
`cheme fragment` (above): they name every id for you.


| file | what |
|---|---|
| `snippets/empty-sheet.xml` | the frame `cheme sheet new` starts from: metadata (empty, status "for review"), border, title block, full shape catalogue; use `sheet new` rather than copying it |
| `snippets/equipment-tank.xml`, `...-drawing.xml` | Tank with chambers and nozzles, and its drawing |
| `snippets/equipment-pump.xml`, `...-drawing.xml` | centrifugal pump with two nozzles, and its drawing |
| `snippets/piping-system-with-valve.xml`, `...-drawing.xml` | a line: nozzle -> globe valve -> nozzle, and its drawing |
| `snippets/tee-branch.xml`, `...-drawing.xml` | a run segment ending at a tee, the run continuing, and a branch segment |
| `snippets/instrument-function.xml`, `...-drawing.xml` | a field instrument, and its bubble and measuring line |
| `snippets/instrument-nozzle.xml`, `...-drawing.xml` | the measured point: branch, isolation valve, blind flange with the `InstrumentationNodePosition` the measuring line starts at |
| `snippets/actuating-system.xml`, `...-drawing.xml` | an actuating system: controlled actuator (fail close) and the valve it operates, and its drawing |
| `snippets/signal-line.xml`, `...-drawing.xml` | a controller with its actuating function and the signal line to the actuating system, and the dashed line |
| `snippets/offpage-connector.xml`, `...-drawing.xml` | a segment starting at a flow-in off-page connector, and the arrow |
| `shapes.md` | every shape in the catalogue and which object uses it |

The snippets are long because drawings are verbose. Read them with `grep -n` and line ranges
rather than in full. Snippets with several fragments say above each where it goes.
