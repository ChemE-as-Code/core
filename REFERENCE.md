# ChemE-as-Code reference

The full reference of the `cheme` toolkit: every command, file and endpoint. The short
introduction is the [README](README.md); the documentation site is
https://docs.cheme-as-code.org. The documentation pages include sections of this file, so
renaming a heading here fails `mkdocs build --strict` (`docs/hooks/includes.py`).

**Plant design as code.** A process plant kept as plain files in a git repository -- DEXPI 2.0.1
P&IDs, engineering lists in YAML, decisions in Markdown -- edited by engineers and by coding
agents such as Claude Code, and checked by this tool.

Coding agents are very good with text files and git, and getting better. cheme-as-code gives them
(and people) what they need to work on engineering files the same way they work on code: a
validator with `file:line` findings, a formatter that keeps diffs small, a renderer, a visual
diff, and engineering-step gates.

> Status: research prototype of the Process Intelligence Research group.

> **Renamed from plantcode.** Since 0.7.0 the package is `cheme-as-code`, the import name
> `chemeascode` and the command `cheme`; finding ids start with `cheme.` and schema ids with
> `cheme/`. The old names are gone, without aliases. Plant repositories migrate once:
> [docs/framework/rename.md](docs/framework/rename.md).

## How the pieces fit together

This repository is the toolkit of **ChemE-as-Code**, the open project of the `cheme` toolkit,
viewer, process library and Process Atlas. The project's terms (calculation maturity, design
maturity, project stage, review status) are defined once, in the
[glossary](docs/concepts/glossary.md).

Three kinds of repository, like a toolbox and notebooks:

| repository | what it is | what you do with it |
|---|---|---|
| [`core`](https://github.com/ChemE-as-Code/core) (this one) | **the toolbox**: the `cheme` command and the skills (instructions for agents) | install it once on your computer |
| [`project-template`](https://github.com/ChemE-as-Code/project-template) | **an empty notebook**: a new plant with no content yet | press **Use this template** on GitHub to start a plant |
| [`process-library`](https://github.com/ChemE-as-Code/process-library) | **filled notebooks**: real plants, one folder each (`processes/asu-1`) | read them, copy from them, add a new process |

This repository also holds the **viewer** ([`viewer/`](viewer/README.md), the web app that
`cheme serve` serves) and the **agent runner** ([`agent-cli/`](agent-cli/README.md), Claude agents
with a spending cap and run records), each with its own package files and CI. The `cheme`
package needs neither of them, nor an LLM provider.

Starting a plant takes two steps:

1. **Make the plant repository.** Either press **Use this template** on GitHub (no tools needed),
   or run `cheme init my-plant` on your computer. Both give the same files.
2. **Install the toolbox.** `uv tool install git+https://github.com/ChemE-as-Code/core.git`
   (see [Install](#install)). The plant repository holds your data, not the tools: checking,
   drawing and generating (`cheme validate`, `cheme render`, `cheme process build`, ...) always
   run the installed `cheme`. The plant's CI installs it too.

The skills in a plant's `.claude/skills/` are **copies** of the skills in this repository, because
Claude Code reads skills only from the repository it works in. They do not update themselves:
after upgrading `cheme` (`uv tool upgrade cheme-as-code`), run `cheme skills update` in each plant,
and `cheme skills status` to see which are out of date. `project-template` is never edited by hand
either: after every merge to `main` here, the `project-template` workflow regenerates it with
`cheme init` and pushes it (secret `PROJECT_TEMPLATE_TOKEN`). If that workflow cannot run, for
example while GitHub Actions is unavailable, the template falls behind until the next run.

## Install

```sh
uv tool install git+https://github.com/ChemE-as-Code/core.git
```

Needs Python 3.12+. pyDEXPI comes from PyPI, pinned to one version in `pyproject.toml`.
`cheme --version` prints the pyDEXPI that was installed. For PNG output
(`cheme render --png`) install the `png` extra, which adds resvg:
`uv tool install 'cheme-as-code[png] @ git+https://github.com/ChemE-as-Code/core.git'`.
Stream properties (`cheme process props`) and the phase calculations of
`chemeascode.domains.process.thermodynamics` need the `props` extra (thermo and chemicals,
pinned), and a PC-SAFT property package the `saft` extra (feos, pinned); the viewer API (`cheme serve`) the `serve` extra; unit conversion beyond K, °C and
the pressure units of the process YAML (`chemeascode.foundation.units`) the `units` extra (Pint);
SMILES checks in `chemeascode.domains.chemistry` the `chemistry` extra (RDKit). Extras combine:
`cheme-as-code[png,props,serve]`.

The ChemSep SRK interaction parameters (`kij`) of the Redlich-Kwong-Soave phase calculation are
not shipped, as their licence is not yet confirmed. `cheme data fetch chemsep-srk`
downloads ChemSep-LITE (http://www.chemsep.org, plain HTTP; the archive's sha256 is checked), or
reads a downloaded copy with `--zip lite.zip`, and installs the converted `srk.json` in the user
data directory (`$CHEME_DATA_DIR` if set; `cheme data status` shows where). Without it every
SRK `kij` is zero, and the result's `notes` say so.

Component properties (`cheme chemistry props NAME -p PROPERTY`) come from PubChem, the
NIST WebBook, OSHA and thermo; `--source Thermo` stays offline. SMILES checks in the kinetics
tools need the `chemistry` extra (RDKit).

## Use

```sh
cheme init my-plant --name "Ethanol plant"   # folders, schemas, agent skills, CI
cd my-plant && git init && cheme git-setup    # readable P&ID diffs, pre-commit hook
cheme validate                                # P&IDs + lists, and lists vs P&IDs
cheme validate --ignore cheme.label-literal  # leave a rule out (--only: just these)
cheme sheet new P-01 --title "Feed and reaction"  # a sheet with a real title block
cheme sheet meta P-01 Revision=B Status=issued   # title-block values, texts updated too
cheme fmt                                     # canonical XML, a readable id on every object
cheme render                                  # build/<sheet>.svg
cheme render --png --crop 150,50,300,180      # build/<sheet>_crop-150-50-300-180.png
cheme render --png --tiles 4x3 --findings     # build/<sheet>_tile-A1.png ... C4, findings marked
cheme diff main                               # build/diff.html, changes highlighted
cheme diff main --list                        # one line per changed plant item
cheme show T4750                              # where an object is, and what it connects to
cheme show K-4101 --layout                    # measured plot-plan distances around it
cheme --version                               # cheme-as-code, pyDEXPI, the interpreter path
cheme run scripts/draft_P-02.py pid/P-02.xml  # a generator, with pyDEXPI importable
cheme regen P-02                              # rebuild a generated sheet (plant.yaml generator:)
cheme copy P4711 --prefix Pump_P4711B --tag P4711B --offset 0,30   # a spare, with its drawing
cheme fragment valve --id V1 --class GateValve --dn 80 --at 70,184 # XML to paste
cheme move Inst_FI101 --offset -8,12          # nudge a symbol with its nodes and labels
cheme rename T4101_I1 T4101_N6 --children     # an id, every #reference, the ids under it
cheme set Line_101 FluidCode=Nitrogen         # a data value and the labels that show it
cheme status [--json]                         # sheets, findings by sheet, gates, sign-offs
cheme check                                   # engineering-step gates (checks/checks.yaml)
cheme cause-effect                            # build/cause-effect.html + .csv
cheme process build                           # BFD and PFD from process/materials.yaml + flowsheet.yaml
cheme process streams [--md]                  # stream table with provenance, block balances
cheme process propagate --fill                # compositions/flows through mixers, splitters, reactors, separators (recovery:); recycles at tears:, feeds for specs:
cheme process reactors                        # per reactor: extents, heats of reaction, ln(Q/K), duty
cheme process crystallizers                   # per crystallizer/filter/dryer: basis, crystals, recovery, dry solid, moisture, duty
cheme process stills                          # per batch still/solvent swap/column: cuts, residue, purity, recovery, reflux, boil-up time, duty per batch
cheme process energy                          # energy balances, simulation energy audit, boundary gaps
cheme process pinch --dt-min 10               # pinch targets of the recorded simulation run
cheme process furnace [K-101]                 # lime kiln: elements, off-gas, furnace energy closure (extra cantera)
cheme chemistry thermo ammonia                # ideal-gas formation data for materials.yaml (extra props)
cheme process props --fill                    # phase, density, enthalpy (extra props), in range only
cheme process methods                         # which thermodynamic models phase/simulate run, substitutes
cheme process phase A B --model Peng-Robinson # kij coverage per pair; with -T/-P a flash (extra props)
cheme process extract [UNIT] [--systems]      # LLE extraction stages, process/extraction.yaml (extra props)
cheme process layout --view pfd --pin         # keep the generated positions in flowsheet.yaml
cheme layout build [--check]                  # layout/plant-model.yaml: 3D parts, nozzles, envelopes
cheme layout cables [--write]                 # cable schedule: from, to, size, trays, length
cheme layout lifting [--write]                # lifting study: radius, load moment, capacity per heavy lift
cheme assess mto | estimate [--write]         # material take-off of the model, factor estimate
cheme assess equipment [--write]              # equipment costs from published correlations (Turton)
cheme assess tea [--write] [--compare REV]    # TEA: capex build-up, cash flow, NPV/IRR/LCOP, drivers
cheme assess lca [--write | --check]          # LCA per functional unit; lca/dataset.yaml, results
cheme assess lca --write --case B             # case B's own LCI dataset: lca/datasets/<id>-b.yaml
cheme datasheets draft [--tag T]              # draft datasheets for items without one (sources, TBD)
cheme datasheets fill [--tag T] [--param k=v] # calculated sizes with their basis into the drafts
cheme schema [equipment]                      # JSON Schema of a YAML file kind (none: list them)
cheme migrate [--check | --write]             # add `schema: cheme/<kind>/v1` where a YAML input lacks it
cheme serve                                   # read-only JSON API on 127.0.0.1:8765
```

### validate

A P&ID is checked in layers: well-formed XML, a lossless DEXPI 2.0.1 load by pyDEXPI, pyDEXPI's
validation rules, then cheme-as-code's document rules (unique ids, an id on every object, every plant
item drawn) and model rules:

| rule | level | finds |
|---|---|---|
| `cheme.segment-ends` | error | a segment's Source/Target Item/Node that is not where its pipes and items start / end, or a node that is not its item's |
| `cheme.dn-mismatch` | warning | a pipe joining two nodes of different numerical DN (reducers too: a reducer changes DN between its own nodes, which no pipe joins) |
| `cheme.label-stale` | warning | a `Text` whose `TextTemplate` (with an `AttributeRepresentation`) renders other than its cached text, or cannot be rendered (an attribute the object does not have) |
| `cheme.duplicate-tag` | error | two piping components (`PipingComponentNumber` or `PositionNumber` with a plant-wide tag such as `HV-4146`; the segment-local `C1` of the DEXPI reference does not count) or two instruments (printed tag) with the same tag, on one sheet or across the sheets |
| `cheme.label-literal` | warning / info | a drawn `Text` of literal text only (no template, or only `LiteralText` fragments) whose text contradicts (warning) or repeats (info) the data of the object its drawing represents: its DN or its nodes' DNs (`DN = 25/50`, a nozzle's `80`, a reducer's `80/50`), a physical quantity with its unit (`6 barg` against `SetPressureHigh`), or a string attribute |
| `cheme.template-metadata` | warning | a MetaData value, the `<Model name/uri>` or the diagram `Name` that is still template data: pyDEXPI's sample title block (`A. P. Prover`, `Oil & Gas, Inc.`, `Dexpi City`, `P3.1415`, 2016 dates, `name="example"`, `DEXPI Example C01`, ...) or the placeholders of the template sheet (`cheme-template`, `TEMPLATE`) |
| `cheme.titleblock-approval` | warning | `ApproverName`, `ApprovalDateRepresentation` or status (`ApprovalDescription`) "approved" while `checks/status.json` records no sign-off of the current stage (every recorded gate of the stage passing, or a per-stage entry); `CheckerName` while `reviews/` holds no review record |
| `cheme.titleblock-sheet` | warning | `SheetNumber` (the sheet id, or its number: `1` for `P-01`) or `DrawingName` (neither containing the other) disagreeing with the sheet's entry in `plant.yaml` |
| `cheme.line-through-label` | warning | a pipe or signal line running through a text box, its own line number or DN label included (it must reach 0.3 mm into the box) |
| `cheme.line-crossing` | warning | two pipes, or a pipe and a signal line, crossing more than 0.5 mm from either line's ends (a branch ending on a line, a tee or a measuring line's tap is no crossing); one finding per pair of lines, with the points |
| `cheme.label-overlap` | warning | two text boxes overlapping by more than 0.25 mm both ways, or a text box that a symbol outline of an object it does not belong to reaches 0.4 mm into, or an equipment text (its tag) that the outline of the item's own symbol reaches 0.4 mm into (a tag inside its vessel is fine, also over the internals drawn inside a column; its nozzles do not count) |
| `cheme.label-far-from-owner` | warning | a label more than 15 mm from the object it represents (a literal note starting with an instrument's tag, e.g. `LALL-4108 / TSLL-4114 trip ...`, belongs next to that instrument; `LALL-4108` is a function of loop `LIA-4108`); or a label 4 mm or more from its own object and less than half as far from another of the same kind (equipment, valve, instrument, line), so that it reads as the other's |
| `cheme.text-outside-frame` | warning | a drawn text running more than 0.5 mm outside the inside of the sheet's border |
| `cheme.title-text-overflow` | warning | a title block text more than 2 mm wider than its cell (e.g. a long sheet title from `plant.yaml`) |
| `cheme.line-through-symbol` | warning | a pipe or signal line running through an instrument bubble, or the body of an equipment item, it does not end on (a line ending at a nozzle, or with an end inside the body at an internal or a tap, does not count) |
| `cheme.line-through-valve` | warning | a signal or measuring line running through the body of a valve, a pipe of another segment running through a valve, or any line running through an actuator's head (a control valve's signal drawn up through the valve to an actuator on top, an actuator drawn up the pipe on a vertical valve); one finding per line and valve, the actuator's valve named (from its `ActuatingSystem`). The pipes of the segment the valve sits on, the actuator's stem, a line with an end inside the outline (a signal line into the actuator's centre) and a line meeting the outline within 1 mm of its end (a signal line ending on the actuator's top) do not count; the line must run 0.3 mm into the outline's box |
| `cheme.line-on-pipe` | warning | a signal or measuring line drawn on top of a pipe: a horizontal or vertical stretch within 0.3 mm of a pipe's stretch, along it for more than 1 mm (a signal line run down the pipe to an actuator drawn on it); one finding per line and piping line |
| `cheme.line-not-orthogonal` | info | a signal or measuring line with a slanted stretch, 2 mm or longer and more than 1 degree off horizontal and vertical (a measuring line drawn straight from its tap to the bubble); the short legs of a hop over another line do not count |
| `cheme.offpage-not-on-edge` | warning | an off-page connector to another sheet or the battery limit that does not sit on an edge of the drawing area (the inside of the border; the bottom edge is the top of the title block, the notes band beside it counting as the edge): its symbol more than 10 mm from every edge, and more than 35 mm or with anything but its own line and texts drawn between it and the nearest edge (a header sheet's row of connectors set in under their texts is on the edge); one finding per connector, its hint a `cheme move ID --offset=DX,DY` onto the nearest edge (and onto the left edge for an incoming, the right for an outgoing connector). An open end drawn with the same DEXPI classes may sit anywhere: its own text (lower case, punctuation read as spaces) says `atm`, atmosphere, sky, safe location, breather, hose, funnel, sewer, vent or drain and names no system it goes into anywhere (header, flare, oxidiser, thermal, blowdown, recovery, closed, drum, KO, knock-out, scrubber, collection, system, station, tank, sump, line, main, network, vessel, `B/L`, battery limit) and no sheet (`P-nn` or `P-nnn` after from, to, on, see, sheet or a comma: `from P-03 E-3101`, `to C-202, P-05`; a pump tag `P-101A` is no sheet); a connector without text when its id says atm, atmosphere or sky. So `to atm.`, `open drain` and `tanker hose` may stay by their valve, `vent to flare`, `to vent header` and `drain to the closed drain drum` may not. BFD and PFD sheets are not checked |
| `cheme.drawing-not-checked` | info | the SVG export failed, so the drawing rules did not run |

`cheme.segment-ends` reports what pyDEXPI's Mandatory rules `pydexpi_segment_connectivity`
and `pydexpi_segment_reference_nodes_and_items_match` find, once per segment, on the line of the
segment's `References`; the pyDEXPI rule ids are named in the message, and are not reported
separately. The ends are read from how the pipes connect, not from their order in the file
(DEXPI 2.0.1 does not order a segment's `Connections`; pipes listed out of flow order are only
pyDEXPI's Recommended `pydexpi_segment_linear_order`). A segment may end at another node of its
end item when that item is one of the segment's own `Items`: the DEXPI reference P&ID ends a
segment at the outlet of its last valve or at the branch of its tee, where the next segment
starts. A template that stops short of its text (the reference labels valves `66KL21-80` from
`PipingComponentName` and `-`) is not stale while the text starts with what the template
renders. Labels made of literal text only (e.g. a hand-written `DN = 25/50`) show no attribute,
so `label-stale` cannot check them; `cheme.label-literal` compares the values they spell out
with the object's data instead. DNs are compared as a set (`DN = 25/50` matches nodes DN 25 and
DN 50 in either order); a text that is only numbers (`80`, `80/50`) is read as DNs when the object
has any. The info findings say which labels must be changed by hand with the data (`-q` hides
them).

#### Drawing geometry

The drawing rules check the sheet as `cheme render` draws it: pyDEXPI's SVG export,
with every shape's transform applied, so they see what a reader of the rendered sheet sees.
Text boxes are estimated from the font size and the characters (Arial widths, the export's
fallback font), placed by `text-anchor` and `dominant-baseline` (a `text-bottom` label stands
above its y, a `middle` one is centred on it) and turned with the text. The sheet's border (zone
numbers) and title block are not checked. Each finding has the sheet, the ids, a `box` in sheet
mm and a `crop` (the box plus 10 mm, on the sheet) ready for `cheme render --crop`; the text
output adds `[crop X0,Y0,X1,Y1] [id ...]`. Before the totals, `cheme validate` prints one
line per sheet with the counts, which a review record quotes:

```
pid/P-04.xml:1952: warning cheme.line-crossing [Line_GOX4003_S1_P2, Inst_UIC4103_ML]: pipe GOX-4003 (Line_GOX4003_S1_P2) crosses signal line Inst_UIC4103_ML at (121.4,80.0), away from any node -- route one line around the other; ... [crop 110.3,69,132.4,91] [id pid/P-04.xml#line-crossing:Line_GOX4003_S1_P2+Inst_UIC4103_ML]
drawing pid/P-04.xml: 1 line-through-label, 1 line-crossing, 3 label-overlap, 11 label-far-from-owner
```

They take well under a second per sheet. On the DEXPI reference P&ID they find its three line
crossings and two labels its own lines touch.

#### Tags named in texts

Literal texts (no template) often name other objects: off-page texts (`from P-03 LIN-3001`) and
trip notes (`LALL-4108 / TSLL-4114 trip P-4102A/B, XV-4137`). With every sheet validated, a
cross-check reads their tag-like tokens -- letters, `-`, digits, e.g. `P-4102A`, with `A/B`
expanded -- that have the shape (letters and number of digits) of a tag in the lists or sheets,
or of an instrument loop:

| rule | level | finds |
|---|---|---|
| `cheme.label-tag-unknown` | warning | a token that no list entry, drawn tag (TagName, LineNumber, valve number, printed instrument tag) or instrument loop has (`LALL-4108` is known when `LIA-4108` is), or a sheet number plant.yaml does not declare |
| `cheme.offpage-mismatch` | warning | an off-page connector whose text names a line other than its own that differs only in its code (`LN-3001` on `LIN-3001`), is not on the named sheet, or does not join the connector's line there (a branch's `from P-04 GAN-4002` is fine); or names a sheet that does not carry the connector's line |
| `cheme.label-tag` | info | what each such text names and what it is (`K-4101 (equipment)`, `LALL-4108 (instrument loop)`), as no template follows these names |

A note that names an external tag on purpose is accepted like any other finding.

#### Accepting a finding

Each finding has an id, `<file>#<rule without cheme.>:<subject>` (`--json` gives it as
`id`; the drawing rules also print it), e.g.
`pid/P-03.xml#line-crossing:Line_GOX3001_S1_P1+Line_LOX3001_S1_P1`. `checks/checks.yaml` can
accept findings, each with a reason; `*` and `?` match any text:

```yaml
accept:
  - id: "pid/P-03.xml#line-crossing:Line_GOX3001_S1_P1+Line_LOX3001_S1_P1"
    reason: "D-023: no route around the GOX riser (J. Smith, design review 2026-10-20)"
```

`cheme validate` then reports the finding as info, `(accepted: <reason>)`, the `drawing`
line counts it as `(+1 accepted)`, and no gate fails on it. Only warnings and infos can be
accepted: an entry (top-level or a gate's) that matches an error leaves it an error, so validate,
the pre-commit hook, CI and the gates still fail, and is reported as `cheme.accept-error`
(warning). An entry, top-level or a gate's, that names no finding is `cheme.accept-unused`
(info), so stale entries get removed. The text output prints `[id ...]` on every finding that
can be accepted.

YAML lists are checked against their schemas, then compared with the P&IDs: equipment tags and
classes (`cheme.equipment-*`), the optional `dimensions` of an equipment item (overall
`diameter`, `height` or `length`, `width`, `head`, `support`, `weight`; `source`, `assumed`
and `fingerprint` of sizes a tool calculated, such as `cheme process stack`, of which the
datasheets carry `source` and `assumed`) against the sizes its
P&ID states where it states them (`NominalCapacityVolume`, `CylinderLength`, `TubeLength`, a
chamber's `InsideDiameter` or `NominalDiameter`, `PlateHeight`/`PlateWidth`:
`cheme.equipment-dimension-mismatch`, warning), line numbers against `PipingNetworkSystem` LineNumbers and
their DN, per segment when the line lists `segments` (`cheme.line-not-listed`,
`line-not-on-pid`, `line-dn-mismatch`), their `from`/`to` against the ends of the drawn
segments (`cheme.line-endpoint-mismatch`, warning: a listed tag drawn on a loaded sheet that the
line does not reach while it ends at a nozzle of equipment the list does not name; `BL`, `ATM`,
line numbers and areas are not compared, and nor is an end beyond a tee or an off-page
connector), and instrument tags as printed, e.g. `PICSA-4712.02`
(`cheme.instrument-not-listed`, `instrument-not-on-pid`), and, when the optional
`piping/special-items.yaml` (kind `piping_items`: tag, type, line, sheet, `set_pressure_barg`,
`relief_case`) exists, tagged piping components by their printed tag (the first of
`PipingComponentNumber`, `PositionNumber`, `PipingComponentName` that is not a segment-local
number such as the DEXPI reference's `C1`; a component with only `C1` has no tag):
`cheme.piping-item-not-on-pid`, `piping-item-not-listed` (only safety
valves and fittings -- `SafetyValveOrFitting` subclasses -- and silencers must be listed),
`piping-item-type-mismatch` (the DEXPI class or a superclass), `piping-item-line-mismatch`. An
item of that list may be placed in the layout like equipment. Interlocks in
`control/cause-effect.yaml` (kind `interlocks`: `id`, `cause: {tag, condition}`, `effects:
[{tag, action}]` with action trip, stop, start, close, open, depressurize or alarm, `sheet`,
`sil`: 1 to 4, or 0 / `a`) are checked against the lists and sheets:
`cheme.interlock-unknown-tag` (warning, a cause or effect tag no list holds and no sheet
draws), `cheme.interlock-duplicate`, `cheme.interlock-duplicate-effect` (warning, two effects
of one interlock on one tag; the matrix shows both actions), and
`cheme.instrument-no-interlock` for a trip instrument -- function letters with `HH` or `LL`
(`TSLL-4114`), or instrument-list notes saying it trips -- that is in no interlock, as its
cause or in its `logic` (info up to the concept stage, a warning from `basic` on).
`cheme cause-effect [-o FILE]` writes the matrix, causes by effect tags, to
`build/cause-effect.html` and `.csv`. An entry listed twice is
`cheme.line-duplicate` / `instrument-duplicate` / `equipment-duplicate`, and each entry is
checked on its own line. Numbers, tags and DNs need no quotes (`number: 47121` is read as
`'47121'`) and surrounding blanks are ignored.

Sheets in `plant.yaml` may be `status: planned` (the default is `drafted`): declared, not drawn
yet. A planned sheet without its file is `cheme.sheet-planned` (info) instead of
`cheme.missing-sheet` (error); once the file exists it is validated like any other.
Missing from the P&IDs is judged per sheet: a listed item whose `sheet:` names a planned sheet,
or one that is missing or did not load, is held back, and so is an item without `sheet:` while
any sheet is missing or did not load, or while `plant.yaml` `stage` is the first stage (after
the first stage a planned sheet does not hold back items without `sheet:`). Held items give one
info line per list, rule and reason (all their ids in `ids`); an item assigned to a drafted,
loaded sheet stays a warning. The `compared:` line names planned and not loaded sheets.
`--ignore RULE[,RULE]` drops rules from the report and `--only RULE[,RULE]` keeps only those
(ids or globs such as `cheme.*-not-on-pid`, repeatable); both apply to `--json`, `--quiet`
and `--fail-on`. A pattern that matches `cheme.generated-sheet-drift` (`cheme.generated-*`
included) also matches `cheme.generator-failed`, as a gate's `rules` do. The text output
ends with a `compared:` line naming the sheets, lists and cross-checks run (and those skipped, with the
reason); `--json` has the same under `compared`. Each finding is one line an agent can act on:

```
pid/P-01.xml:1043: error dexpi.load [Pipe_7]: Reference 'Nozzle_9' for attribute 'targetNode' not found ...
equipment/equipment-list.yaml:14: warning cheme.equipment-not-on-pid [P-102B]: P-102B is in the equipment list and on no P&ID -- draw it, or remove it from the list
```

Equipment datasheets, `equipment/datasheets/<TAG>.yaml` (kind `datasheet`: service, operating
and design conditions, materials, sizing basis, values marked `assumed`), are checked against
their schema and the equipment list: `cheme.datasheet-not-listed` (warning, a tag not in the
list), `cheme.datasheet-mismatch` (warning, design pressure, temperature or type differ from
the list entry) and `cheme.datasheet-name` (warning, a file not named after its tag).
`cheme datasheets draft [--tag T]` drafts the missing ones from the equipment list, the
P&ID nozzles and the flowsheet streams linked to each item: every value with its source,
unknowns `TBD`, `draft: true` (the `datasheets` gate, a detail gate, does not count drafts).
`cheme datasheets fill [--tag T] [--param name=value] [--dry-run]` calculates the sizes a
draft leaves `TBD` and writes each with its basis (calculation, stream ids, nozzles, pipes,
cited tables; `assumed: true` when an input is an assumption), never over a value it did not
write: exchanger duty (property adapter), LMTD with F and area from a given or typical U
(Sinnott, C&R Vol. 6, Table 12.1); pump head from the stream pressures, the nozzle elevations
and the Darcy-Weisbach losses along the routed lines, NPSH available and power; compressor
stages, power and intercooler duties; Fenske-Underwood-Gilliland stages; vessel volume and
residence time. A value calculated from the streams carries their fingerprint, and validate
reports it as `cheme.datasheet-stale` once they change; the sheet's `operating` names the
`case` and the `streams` it was filled from, which validate resolves (`cheme.contract-ref`). See [docs/framework/sizing.md](docs/framework/sizing.md) and the skill
`datasheets`.

#### 3D layout

The optional files `layout/site-plan.yaml` (kind `site_plan`: site box, plot areas, roads, pipe
racks), `layout/building.yaml` (kind `building`: buildings, levels, column grid) and
`layout/equipment-placement.yaml` (kind `placement`: position, rotation, `mount: {building |
structure, level}`, nozzle overrides and declared access platforms of each equipment-list tag) describe the plant in 3D, in
metres, x east, y north, z up, origin at the site's south-west corner (see the template's
`layout/README.md`). An item's shape and size come from the equipment list: its DEXPI `type`
picks a parametric family (`domains/spatial/shapes.py`: vessel, column, tank, shell-and-tube or
plate exchanger, air cooler, pump, compressor, turbine, filter, silencer, stack, generic) and its
`dimensions` the overall size; the placement's `shape` overrides the shape and its `size` is only
a fallback for an item without dimensions. Each file is checked against its schema, then:

| rule | level | finds |
|---|---|---|
| `cheme.layout-outside-site` | error | an area, road, rack, building or equipment item extending outside the site box |
| `cheme.layout-clash` | error | two equipment items intersecting (plan outlines, and the parts standing out of them such as a tank's stair); equipment intersecting a building it is not placed in; equipment on a road (or `road` area); equipment reaching into a rack's height band (lowest tier - 0.5 m to top tier + 0.5 m) under its footprint; a building on a road, a rack running through a building below its top + 0.5 m, or two buildings overlapping |
| `cheme.layout-unknown-tag` | error | a placed tag that is not in the equipment list (or `piping/special-items.yaml`) |
| `cheme.layout-not-placed` | info | an equipment-list item without a placement (only when a placement file exists) |
| `cheme.layout-level` | error | an unknown building or level, `z` more than 0.05 m from its level's elevation, or an item outside its building's footprint; as a warning, an item taller than its level's clear height, or placed in a building with levels but without a `level` |
| `cheme.layout-area-overlap` | warning | two plot areas overlapping (roads excepted) |
| `cheme.layout-duplicate` | warning | an id or tag listed twice |
| `cheme.layout-line-route` | warning | a line of `piping/line-list.yaml` whose ends lie in different areas, or further apart than `max_unsupported_length` (site plan, default 30 m), and that no rack carries: an end further than `rack_reach` (default: `max_unsupported_length`, as the run from an end to the rack is unsupported) from every rack centreline, or the racks at its two ends not connected; names the ends, their areas, the distance and the nearest rack |
| `cheme.layout-line-length` | info | such a line that racks do carry, with its length estimated along the rack centrelines |
| `cheme.layout-line-unrouted` | info | a line one of whose ends is a tag of the equipment or piping-items list, or a tag drawn on a sheet, that is not placed, so its route cannot be checked |
| `cheme.layout-separation` | warning | a declared separation (site plan `separations`) not kept, e.g. `K-4101 to CB-1: 32.3 m < 50.0 m (1 x height 50 m; D-026; toppling)`; or one naming an id that is not on the plot plan |
| `cheme.layout-size-from-placement` | info | items sized by the placement's `size` instead of `dimensions` in the equipment list (one finding listing them) |
| `cheme.layout-size-ignored` | warning | a placement `size` for an item that has `dimensions` |
| `cheme.layout-size-missing` | warning | an item with neither, drawn at its family's assumed size |
| `cheme.layout-nozzle-unknown` | error | a nozzle override naming a nozzle the item's P&ID does not draw |
| `cheme.layout-unreadable` | error | (`cheme serve` only) a layout file that exists but cannot be read, e.g. a symlink out of the repository |

A line's end is a placed tag (`K-4101/N2` counts as `K-4101`; a piping item of
`piping/special-items.yaml` may be placed too), an area id, the line's `from_area` / `to_area`
(an end that is no placed item, e.g. a vent area), or another line's number, then the point of
that line (the straight run between its own ends) nearest the other end. Racks are connected
where their strips touch or cross. A separation is `{from, to, min_m | min_factor_of_height,
height_of: max|from|to, measure: footprint|centre, reason, basis}` between placed tags, areas,
buildings, roads, racks or `site-boundary`; the height is the top of the item (a building's
highest level), and distances are horizontal, between footprints unless `measure: centre`.
`cheme show <tag> --layout` prints the measured distances from an item (or building, area,
road, rack) to the nearest items, buildings, roads, racks and areas and to the site boundary, so
`DESIGN.md` can quote measured values. `GET /api/layout` returns each line's route as `lines:
[{number, from, to, from_point, to_point, distance, length_est, racks, finding}]`.

**The generated model.** `cheme layout build [--check] [--force]` derives
`layout/plant-model.yaml` (kind `layout_model`) from the layout files, the equipment list
(`type`, `dimensions`), the line list and the P&IDs: every placed item's parts (cylinders, heads,
cones, boxes with a material hint), its nozzles from the P&ID (point, outward direction, DN,
lines and segments; placed from the side of the symbol they are drawn on, or overridden in the
placement) and its maintenance envelopes (bundle pull, motor removal, pump access), plus the site
geometry. Commit it with its inputs. `cheme validate` reports
`cheme.layout-model-edited` (error), `-version`, `-outdated` (warnings) and `-missing`
(info); `cheme impact` lists an outdated model. The format and the `/api/layout` contract:
[docs/framework/layout-model.md](docs/framework/layout-model.md).

**Cable trays.** With `electrical/electrical-list.yaml` (rooms in buildings, the motor list's
powers, junction boxes) the build cables the plant: a motor for every driven item, instruments
where the P&IDs measure, junction boxes, power and instrument trays from the rooms along the
racks' own tray tier to the loads, sized by their cables, and the cable schedule
(`cheme layout cables`). Rules, rooms and the schedule:
[docs/framework/electrical.md](docs/framework/electrical.md).

**HVAC ducts.** With `layout/hvac.yaml` (air handling units, rooms with their air changes) the
build ventilates the buildings: terminals in each room, supply and extract ducts from the unit
routed inside the building, the intake and exhaust to their louvres, each duct sized within
its velocity limit (findings `layout-hvac-capacity`, `-duct-unrouted`, `-clash-duct`; skill
`hvac-ducts`). The sections and rules:
[docs/framework/layout-model.md](docs/framework/layout-model.md).

**Access and lifting.** The rules on the model check headroom over every walking surface
(stairs, landings, platforms, structure floors), a free standing space in front of valves,
transmitters and casing hatches (a stair flight is no operating position), the walk beside a
stacked stair's next flight, ways off a roof inside a vent zone, and the operators
`piping/routing.yaml` declares for what stays out of reach (`operators:` chain wheel, extension
spindle, remote operator, remote-mounted transmitter, each within an ASSUMED limit).
`cheme layout lifting` gives the lifting study of the heavy items: working radius, gross
load, load moment, capacity needed, lift and hook height, lane and laydown, checked against
crane load charts in `layout/crane-chart.yaml` when the project has chosen a crane (gate
`lifting-study`). Details: [docs/framework/layout-model.md](docs/framework/layout-model.md).

**Material take-off and estimate.** `cheme assess mto` counts the model's bulk materials
(pipe by DN, class and insulation; elbows, tees, reducers, flanges, gaskets; valves by type and
DN; steel tonnage by section; grating, insulation and concrete); `cheme assess estimate`
prices them with the project's `estimate/rates.yaml` (every rate with status, source and year;
cheme-as-code ships no prices, the template's file is an example) by the factor method. `--write`
puts them into `estimate/`; the gate `kind: mto` checks they are current.
`cheme assess equipment` costs the equipment list from the published purchased and bare
module cost correlations of Turton et al. (CAPCOST, 5th ed. 2018, Appendix A; package data with
the table of every row), escalated by the CEPCI value the project gives with its year and
source in `estimate/cost-basis.yaml`; an item outside a correlation's range or without its size
or factors is a finding, never extrapolated, and the report states its AACE 18R-97 class.
Rows, rules and `GET /api/mto`: [docs/framework/mto.md](docs/framework/mto.md).

**A design case's LCI dataset.** `cheme assess lca --dataset|--write|--check --case <id>`
derives the unallocated LCI dataset of another computed flowsheet case. It uses the study's
scope, reference product and functional unit, and an id (`<dataset id>-<case>`), title
(`<title>, case <case>`) and uuid (`uuid5(<base uuid>, "case:<case>")`) that name the case.
`--write` writes it to `lca/datasets/<dataset id>-<case>.yaml` (generated: a header comment
and `provenance`; never over a file it did not generate, `cheme.lca-dataset-not-generated`).
`--check` exits 1 with `cheme.lca-dataset-stale` when that file is missing or differs. An
undeclared case exits 2 and lists the declared ones. The study's own case is
`lca/dataset.yaml`, unchanged. Details:
[docs/framework/lci-scenarios.md](docs/framework/lci-scenarios.md), ADR 0045.

**Techno-economic analysis.** `cheme assess tea` evaluates the economics against the decision
`estimate/tea.yaml` states (npv, irr, lcop or cash cost and a threshold). It works for continuous
and batch plants, in one or several operating cases, for material and energy main products.

- **Capital:** built up from the equipment or take-off estimate, or from a reference cost scaled
  to the plant's capacity (ISBL, then OSBL, owner's cost and contingency). Its AACE class is
  checked against the stage.
- **What the plant buys and sells:** the flowsheet's feeds and products, their components,
  consumables it does not carry, and emissions with a carbon price and free allocation. Each is
  priced with the project's prices (status, source and year on each; cheme ships none), with
  price paths over the life.
- **Fixed cost and periodic events:** replacements, turnarounds and grants.

The result is the discounted cash flow (NPV, IRR, LCOP and cash cost of the main product,
payback; tax losses credited or carried forward), plus:

- the cost of production per unit;
- scenarios;
- a tornado and the break-even value of every input, i.e. what would change the decision;
- with `uncertainty:`, a seeded Monte Carlo (P10/P50/P90, P(meets), Spearman drivers).

`--compare REV` lists the premises two analyses do not share (product, specification,
boundary, scale, location, currency and cost year, case, operation, discount and tax rate)
before their results. Gate `kind: tea`, `GET /api/tea` and the viewer's TEA page:
[docs/framework/tea.md](docs/framework/tea.md).

The model also holds steel (`layout/structures.yaml` frames and generated rack bents), access
platforms (declared in the placement's `access:`, or proposed with `review_needed`), zones
(`layout/zones.yaml`) and a pipe route for every P&ID segment. The router is deterministic: a
line goes over the racks when its ends lie in different areas, its straight run would cross a
road or another area, or it is longer than `local_max_m` (15 m); it rises near the equipment,
enters the rack at the point nearest each end and takes a lane of its own. Local lines run at
the pipe-way elevation (`local_elevation_m`, 3.5 m), pump suction and discharge runs at grade.
Battery-limit ends (`BL`, `CW`, `CWR`) go to a `battery_limits:` point or rack end of
`piping/routing.yaml`, else the nearest rack end; a line with battery limits at both ends (a
header) runs along a rack from end to end, or between the points of two matching rules. Each
pipe records how (`method`) and why (`reason`) it was routed. `cheme layout report` lists every line routed, skipped or
unrouted with the reasons and the counts per method and reason; `layout route --line L`
reroutes some lines, `layout pin` keeps a route or platform, `layout render --plan | --section
x=.. [--png]` draws plans and sections. Gates of kind `layout-model` (template:
`layout-plot-plan`, `layout-3d`, `layout-detail`) turn this into stage requirements, and the
skills `layout-yaml`, `pipe-routing`, `structures-access`, `area-classification` and `review`
say how to work with it. What the layout does not do (pipe stress, supports, isometrics,
structural design, HVAC and cable trays, dispersion, CAD export beyond glTF and STL) is listed in
[`domains/spatial/README.md`](src/chemeascode/domains/spatial/README.md).

Equipment is compared by its outline in plan over the height of its box: a circle for a vertical
cylinder or sphere, else its rectangle turned with it; against other equipment also by the solid
parts standing out of that outline (a tank's stair, a base plate, a plinth); buildings turn in steps of 90 degrees; roads and
racks are strips of their width along their centrelines, closed at the bends. A level is as high
as its `height`, else up to the next level, else 4 m (a floor) or a 0.2 / 0.3 m slab (platform /
roof); a building without levels is 6 m high. Touching is not a clash. Numbers must be finite
(no `.inf` / `.nan`), ids not empty, and a round shape takes `size: {diameter, ...}` (a list is
for `box` only). The layout rules run only when every layout file present passes its schema.

### sheet

`cheme sheet new <ID> [--title T] [--file F] [--revision R] [--force]` writes
`pid/<ID>.xml` from the template frame (`.claude/skills/dexpi-xml/snippets/empty-sheet.xml`,
generated without pyDEXPI's sample data) and fills its title block from `plant.yaml`: Model
name (plant name) and uri, diagram Name (the sheet id), DrawingNumber (`<project.number>-<ID>`),
DrawingName (title), SheetNumber, project number and name, client (EnterpriseName), site,
revision (`project.revision`, default A), creation and modification dates, status "for review";
approver, approval date and checker stay empty. It adds the sheet to `plant.yaml` `sheets:`
(keeping comments; with an empty list the sheets already in `pid/` are listed too) or turns a
planned entry drafted. The optional `project:` block of `plant.yaml` is
`{number, name, client, site, revision}` (`cheme schema plant`).

`cheme sheet meta <ID> Key=Value ...` sets title-block values: a MetaData property
(`RevisionNumber`, `ApproverName`, ...), a short name (`Revision`, `Status`, `Title`,
`Approver`, `Checker`, `Creator`, `Client`, `Site`, `Project`, `Number`, `Sheet`, `Date`, ...),
or `ModelName`, `ModelUri`, `DiagramName`. Each title-block text showing a changed attribute is
re-rendered with pyDEXPI's label toolkit (what `cheme.label-stale` checks), and the file is
written in `fmt` form. Without pairs it prints the title block.

### fmt

Gives every `<Object>` without an id a deterministic, readable one (`Tank1_Nozzles2`,
`Pipe3_Drawing1`) -- pyDEXPI would otherwise mint a random id on every load -- and writes the
document back through pyDEXPI's serializer in canonical order, keeping the `<Model>`'s `name`
and `uri`. It refuses a document whose load reports a loss -- a loader error, or a warning that
content "will be ignored", such as a `Data` property DEXPI does not define -- and names it; the
edit commands then write their change unformatted and say so. XML comments and processing
instructions have no place in the DEXPI model and are dropped, each one reported with its line
(by `cheme fmt`, `cheme run --fmt`, the edit commands, `cheme sheet meta` and the Python API's
`Sheet.save()`, as a warning).

### render

`cheme render [PATHS] [--png] [--scale 4] [--crop X0,Y0,X1,Y1] [--rev REV] [-o OUT]` draws
each sheet with pyDEXPI's SVG export to `build/<sheet>.svg` (`build/<sheet>@<rev>.svg` with
`--rev`, which renders the sheet as committed at that revision). With `--crop` the name ends
in the crop, `build/<sheet>[@<rev>]_crop-X0-Y0-X1-Y1.svg|png` (corners ordered), so a crop never
overwrites the full sheet or another crop. `--png` writes a PNG instead,
`--scale` pixels per sheet millimetre (default 4); it needs the `png` extra and says so when it is
missing. `--crop` limits the output, SVG or PNG, to a region of the sheet given in millimetres
from the top-left corner, Y down. These are the sheet's own XML coordinates (the export does not
flip Y), so a `Position` read from the XML can be used directly. Each drawn object's `<g>` carries
the id of the object it represents. A PNG larger than 100 Mpx is refused (exit 2). A sheet that
does not load or draw is reported as `<path>: cannot render: <reason>`; the other sheets are still
rendered and the exit code is 1.

`--findings` draws the drawing-geometry findings (see validate) on the output as numbered red
frames with the rule's name; those checks/checks.yaml's `accept:` accepts are grey and captioned
`(accepted)`. `--tiles CxR` (e.g. `4x3`) renders the whole viewBox, which can include content
left of or above the frame, as C columns by R rows of tiles that overlap by 10 %, `build/<sheet>[@<rev>]_tile-<row letter><column>.svg|png`
(`_tile-B3` is the second row, third column), at `--scale 8` unless given, and writes the index
`build/<sheet>[@<rev>]_tiles.json` (each tile's `crop`, its file and, with `--findings`, the
findings it shows: number, rule, `id` and, when accepted, the reason); it prints one line per
tile with `--crop X0,Y0,X1,Y1 --scale S`, which reproduces the tile.
`--tiles auto` picks the grid so a tile is at most 1600 x 1200 px (2 mm text is 16 px at scale
8): 3x3 for an A3 sheet. `--tiles` with `--crop` or `-o`, or a malformed grid, exits 2. Tiles
make a visual review cover the whole sheet; they do not replace the drawing rules.

`--emphasise-inline` draws the valves, inline fittings (reducers, silencers, ...) and the
actuators 1.5 times larger about their insertion points, with lines twice as wide, so they can be
read on a full-sheet render (a valve at the usual scale 0.4 is 4 x 2 mm). It is a review aid: the
XML, the pipes and the labels are unchanged, and the output is named `..._inline.svg|png`
(`build/<sheet>_inline_tile-A1.png` with `--tiles`) so it never stands in for the drawing.

### diff

`cheme diff [OLD=HEAD] [NEW=working tree] [--path P] [--html OUT] [--json] [--list [--verbose|--flat]]` loads two
revisions, compares them with pyDEXPI's semantic diff, and writes an HTML page with both sheets
side by side: added items green, removed red, modified orange, plus the change list and the
review-text diff. It prints the counts per sheet and the report's path. Without `--path` it
compares every `pid/*.xml` on either side, so a deleted or added sheet is reported too. An
unknown revision exits 2 with `unknown revision` (as does `render --rev`). A sheet that does not
load or draw on either side is named on stderr with a one-line reason
(`<sheet>: cannot compare: <rev> does not load: <reason>`, or `cannot draw <rev>: <reason>`);
the other sheets are still compared, the output (counts, list, JSON, HTML) is still written, and
the exit code is 1.

- `--list` prints, per changed sheet, a `<sheet>:` line (with `(sheet added)` or
  `(sheet removed)` for a sheet on one side only) and one line per plant item a change belongs
  to: `<kind> <class> <id> [tag]: N added, M removed, K modified` (`, L moved` when any moved),
  e.g. `removed TubularHeatExchanger TubularHeatExchanger1 [H1008]: 0 added, 132 removed, 0
  modified`. `<kind>` is what happened to the item itself, or `changed` when only its parts or
  its drawing did. A part (nozzle, node, chamber) belongs to its item, a pipe or segment to its
  line (piping network system), a valve or tee is an item of its own, an instrument function's
  parts belong to it, and a drawing element to the item of the object it draws (the title block
  and frame to the plant model); changes that belong to none are counted under
  `changed (no plant item)`. Removed items come first, then added, modified and changed.
- `--list --verbose` adds, under each item, its changes one per line, indented, as `--flat`
  prints them.
- `--list --flat` prints one line per changed object, as 0.2 did:
  `<kind> <class> <id> [tag] (<domain>) <attrs> -> drawn as <owner|not drawn>`, e.g.
  `modified GlobeValve GlobeValve2 [C1A] (conceptual) pipingComponentNumber -> drawn as GlobeValve2`.
  The owner is the drawn object (a `<g id>` of the SVG) the change shows on. `--flat` or
  `--verbose` without `--list` exits 2.
- `--json` prints a JSON array with one object per changed sheet, the shape of `GET /api/diff`
  without `old_svg`/`new_svg`: `path`, `old_rev`, `new_rev`, `status`, `changes`
  (`kind`, `object_type`, `object_id`, `tag`, `domain`, `detail`, `item`), `old_highlight`,
  `new_highlight`, `old_owner`, `new_owner`, `items` (each plant item a change names: `class`,
  `tag`), `projection_diff`, `error` (why the sheet could not be compared or a side not drawn;
`""` when all went well). No change prints `[]`.

With `--json` or `--list` the HTML report is written only when `--html` names a file.

### show

`cheme show ID_OR_TAG [--sheet FILE]` finds an object in every sheet (or in one) by its XML id
or a tag -- `TagName`, the printed instrument tag (`PICSA-4712.02`; also without the hyphen or
with a space), `LineNumber`, `PipingComponentNumber`/`PipingComponentName`, a function or
segment number -- and prints where it is: `file:start-end` of its `<Object>` block, its class and
tag, its owner chain, the `file:start-end` of the RepresentationGroup(s) that draw it with the
region their points span (`at X0,Y0,X1,Y1 mm`, sheet mm, Y down: symbol insertion points, line
and label positions; add a margin for `render --crop`) or the drawn object it is part of, the ids it references and the references to it, each with a line number.
An object's parts (nozzles, chambers, instrument functions) are listed with what connects to
them. For a piping network system (a line number) or segment it also lists the segments, their end
items and nodes, the pipes with both ends, and every item's nodes with their DN.

For equipment (or a nozzle), `connections:` lists each nozzle with the segment and line attached
to it and what is at the segment's other end (another equipment's nozzle, a tee on another
segment, its own end item, or open), or the instrument sensing at it, or `nothing`. `only for
<tag>:` lists what exists only for that equipment and dangles without it: the segments reached
from its nozzles through items that are not tees, when they reach no other equipment, no
off-page connector and no tee branching off them; lines all of whose segments are among them;
and the branch tee on another segment they start from. Items on those segments that are part of
an instrument chain are named with the `cheme show` call that prints it.

`instrumentation:` follows the instrument chains an object is part of, from any member: an
instrument function (`ProcessInstrumentationFunction`) or its parts, an
`InstrumentationLoopFunction`, an `ActuatingSystem` (or its actuator), a valve its
`OperatedValveReference` names, or an object (or part, such as a nozzle) a
`ProcessSignalGeneratingFunction` senses at. Per function it prints the loop(s) that list it
(or `none`), what it senses and where, its measuring and signal lines (`Source -> Target`, with
their drawings), and each `ActuatingFunction` with its `ActuatingSystem`, `ControlledActuator`
and operated valve, each with its block and drawing. Functions joined by a signal line (a
cascade) are listed together.

It reads the XML only, so it works on a sheet pyDEXPI cannot load. Nothing found: exit 1 and
close ids and tags.

```
$ cheme show T4750
pid/P-01.xml:3412-3718 Tank Tank1 [T4750]
  owner: PlantModel1 (PlantModel) pid/P-01.xml:8 < Model_EngineeringModel1 (EngineeringModel) pid/P-01.xml:6
  drawn by: Tank1_Drawing1 (RepresentationGroup) pid/P-01.xml:25152-28120 at 171,69.3138,280,291 mm
  references (0):
  referenced by (4):
    pid/P-01.xml:25233 Tank1_Drawing1_Groups2_Elements1_Template1_Fragments1 (AttributeRepresentation) Object
    ...
  parts (9):
    Nozzles: Nozzle5 (ProcessNozzle N1) pid/P-01.xml:3414-3434 <- Pipe4 TargetItem, PipingNetworkSegment3 TargetItem
    ...
  connections:
    Nozzle5 (ProcessNozzle N1): segment PipingNetworkSegment3 (PipingNetworkSegment S1) of line 47123 pid/P-01.xml:449-535; other end: PlateHeatExchanger1 (PlateHeatExchanger H1007) nozzle Nozzle4 (ProcessNozzle N2)
    Nozzle18 (ProcessNozzle N3): nothing
    ...
  only for T4750 (these dangle without it):
    segment PipingNetworkSegment8 (PipingNetworkSegment S2) of line 47125 pid/P-01.xml:979-1016
    ...
    line PipingNetworkSystem5 (PipingNetworkSystem 47125) pid/P-01.xml:889-1039: all its segments
    branch tee PipeTee1 (PipeTee C3) pid/P-01.xml:1231-1285 on PipingNetworkSegment11 (PipingNetworkSegment S3) of line 47126 pid/P-01.xml:1221-1315: its branch serves only this
  instrumentation (1 function(s)):
    ProcessInstrumentationFunction4 (ProcessInstrumentationFunction TICSA-4750.03) pid/P-01.xml:2577-2616 drawn by ProcessInstrumentationFunction4_Drawing1 pid/P-01.xml:16160-16448 at 197.25,57.25,340.5,64.75 mm
      loop: PlantModel1_InstrumentationLoopFunctions4 (InstrumentationLoopFunction 4750.03) pid/P-01.xml:306-311
      actuates: ActuatingFunction3 (ActuatingFunction TV4750.03) pid/P-01.xml:2579-2584
        system: ActuatingSystem3 (ActuatingSystem TV4750.03) pid/P-01.xml:257-285 drawn by ActuatingSystem3_Drawing1 pid/P-01.xml:9941-10111 at 337.5,104.9,340.5,115.5 mm
        ...
        valve: GlobeValve3 (GlobeValve C1) pid/P-01.xml:2348-2401 (OperatedValveReference pid/P-01.xml:275)
      senses: ProcessSignalGeneratingFunction3 (ProcessSignalGeneratingFunction TT4750.03) pid/P-01.xml:2587-2592 at Nozzle17 (InstrumentNozzle N7) pid/P-01.xml:3519
      ...
```

### copy

`cheme copy ID --prefix NEWID [--tag TAG] [--offset DX,DY] [--sheet FILE] [--into PARENT_ID]
[--print]` duplicates an object (an id or a unique tag) with its parts and every
`RepresentationGroup` that draws it or a part: symbol, nozzles and their nodes, node positions,
labels, the equipment data table. Every id inside the copies is renamed deterministically: the
object's id becomes `NEWID`, an id starting with it keeps its suffix
(`CentrifugalPump1_Drawing1` -> `Pump_P4711B_Drawing1`), any other id gets the prefix
(`Nozzle1` -> `Pump_P4711B_Nozzle1`). References inside the copy follow; references out of it are
kept (shapes, a sensing location), except connections (`SourceItem`, `TargetNode`, a
ConnectorLine's `Source`, ...), which would join a node twice and are dropped. `--tag` sets the
tag property (`TagName`, or `PipingComponentNumber`, ...; with `TagNamePrefix`,
`TagNameSequenceNumber`, `TagNameSuffix` when the object has them) and every label text of the
copy that showed the old tag. Drawing coordinates move by `--offset` (sheet mm, Y down); an
`EquipmentBarLabel` data table goes to the nearest free slot of the table band instead (moved
with the offset only when there is none, and said so). The copies are inserted as text next to
the originals (with `--into`, at the end of that object's matching `Components` and its drawing),
so the rest of the file stays byte for byte. It prints the new ids, the `file:start-end` written,
and what was **not copied** -- the pipes and segments at the original's nozzles, an actuating
system's valve reference -- with their lines. `--print` prints the XML and changes no file. Run
`cheme fmt` and `cheme validate` afterwards.

An instrument copied with another measured variable follows it in its functions: `copy
Inst_AI3104 --tag FI-4199` gives the sensor `FT4199` (and an actuator `AV...` `FV...`). Options
that adapt the copy in the same command (each repeatable):

| option | does |
|---|---|
| `--rename OLD=NEW` | an inner tag (`HV-4146=HV-4147`): every copied data value equal to it, the label texts that show it, and the ids that spell it (`..._HV4146` -> `..._HV4147`) |
| `--renumber OLD:NEW` | a number (`4144:4145`) in the copied tags, label texts and ids |
| `--set PROP=VALUE` | a data value on every copied object that has PROP (`FluidCode=Liquid nitrogen` on a line and its segments), typed as `cheme set` types it, and the labels showing it |
| `--connect PIPE[.source\|.target]=ITEM:NODE` | close a copied pipe's open end (its old or new id): the pipe's Item/Node references, the segment end that pointed at the same place, and the ConnectorLine's `Source`/`Target` at the node's position |
| `--sense-at ID[:X,Y]` | an instrument's `SensingLocation`; with X,Y a new `InstrumentationNodePosition` in ID's drawing, where the copied measuring line now starts |

Ids inside the copy that spell the original's tag follow `--tag` too (`CV_LOX4004` of line
`LOX-4004` -> `CV_LIN4004`). The report ends with `duplicate tags:`: each tag of the copy that an
object on this sheet or another sheet already has, with its line. `--connect` refuses a node
another pipe already ends at.

### move, rename, set

Edit commands for objects already on a sheet. Each works on the XML tree (never pyDEXPI's
editor), leaves the file as it was except for the change, runs `cheme fmt` afterwards
(`--no-fmt` not), and with `--print` prints the change as a unified diff and writes nothing.
Without `--sheet` they use the one sheet holding the id or tag. An unknown id, a taken name or
a value of the wrong type exits 2 and changes nothing.

- `cheme move ID --offset DX,DY` moves every coordinate that draws ID (the drawings of the
  object and its parts: symbol, node positions, labels, the bends of lines drawn inside its
  group whose ends both move) and prints each one, old -> new. ConnectorLines attached to a moved
  node position follow by reference; their bends stay and are listed as `stretched`, and a
  straight one that is no longer horizontal or vertical as `now slanted`. A PolyLine ending on a
  moved point gets that end moved. An `EquipmentBarLabel` data table stays in its band. ID may
  be a drawing element too, to move only it (a label `Text`).
- `cheme rename OLD NEW [--children]` renames the id OLD and every `#OLD` reference;
  `--children` also every id `OLD_*` (`T4101_I1_Drawing`, `T4101_I1_Pos`). A name already taken
  is refused. A note says when the object keeps data that spelled the old id (its `SubTagName`).
  Given a tag instead of an id (`cheme rename HV-4146 HV-4147`) it sets the tag data
  (`TagNamePrefix`/`SequenceNumber`/`Suffix` with a `TagName`; an instrument's category,
  letters and number, and the numbers of its sensor and actuator) and the labels showing it;
  `--ids` also renames the ids that spell the whole tag (`V101`, not inside `FV101`) within the
  retagged objects, their parts and drawings. A tag already held by another piping
  component or instrument (this sheet or another) is refused. When two objects share a tag
  (after a copy), `cheme rename ID NEWTAG --tag` retags the one with the id ID
  (`rename Inst_Y FI-4150 --tag`: category, number, sensor `FT4150`). A valve that shares its
  tag with its own actuation chain (`XV-104`: the valve, the actuating system that operates it,
  the actuating function driving that system and, when tagged alike, the instrument function)
  is retagged together with it by `cheme rename XV-104 XV-105`; any other object with the tag
  still makes it ambiguous. Tags in
  `PositionNumber` (safety valves) address objects like the other tag properties.
- `cheme set ID PROP=VALUE...` sets data values by their DEXPI name, in the type the
  attribute has: the type of the value already there, else pyDEXPI's class -- `String`,
  `Double`, `Integer`, `Boolean`, an enumeration member (`OnHold=OnHold`), a physical quantity
  with its unit (`InsulationThickness='50 mm'`, `'16 barg'`, `'26 MetreCubed'`). A dotted name
  reaches into an aggregate (`Stroke.Width=0.5` on a ConnectorLine). `PROP=` removes the value.
  Every label whose template shows an attribute of the object gets the cached text pyDEXPI's
  label renderer gives, so `cheme.label-stale` stays clean (also on a sheet whose Texts have
  no ids yet); the lines changed are printed. Setting an instrument's
  `ProcessInstrumentationFunctionCategory` or `...Number` renumbers its sensor and actuator too,
  and a tag another object already has is noted.

### fragment

`cheme fragment KIND --id ID [--sheet FILE] ...` prints ready-to-paste XML in two parts,
`CONCEPTUAL` and `DRAWING`, each after an XML comment saying where it goes (plus a `SHAPE` part
when the symbol is not in the catalogue, e.g. `GATE_VALVE_SHAPE`). Ids derive from `--id`:

| kind | options | writes |
|---|---|---|
| `node` | `--dn 80 [--standard Din2448\|Iso6708\|none] [--at X,Y]` | a `PipingNode` with all DN properties; with `--at`, its `PipingNodePosition` group |
| `pipe` | `--from ITEM:NODE --to ITEM:NODE [--points x,y;x,y]` | a `Pipe` and its `ConnectorLine` between the two node positions, `--points` the bends |
| `valve` | `--class GlobeValve\|BallValve\|GateValve\|SwingCheckValve\|ButterflyValve --dn --at X,Y [--rotation R] [--tag]` | the valve with nodes `ID_N1` (in), `ID_N2` (out), its symbol (scale 0.4) and node positions 2 mm either side |
| `tee` | `--dn [--branch-dn] --at X,Y [--rotation R] [--branch up\|down\|left\|right]` | a `PipeTee` with `ID_N1` run in, `ID_N2` run out, `ID_N3` branch, drawn as in the reference (Shape12 dot, positions 0.001 mm apart) |
| `segment` | `--from ITEM:NODE --to ITEM:NODE [--like SEGMENT] [--number S2] [--dn]` | a `PipingNetworkSegment` with its ends, data copied from `--like`, empty `Connections`/`Items`, and its drawing group |
| `label` | `--for ID --attribute A [--at X,Y]` | a label (`ValveLabel`, `EquipmentTagNameLabel`, ... by the object's class) showing the attribute |
| `equipment` | `--class C --tag T --at X,Y [--shape S] [--rotation R] [--scale S\|SX,SY] [--label-at X,Y] [--marker NAME:dy[:SY][:m]] --nozzle N1:dx,dy[:DN] ...` | equipment of DEXPI class `C` with tag parts, nozzles (`ID_N1`, node `ID_N1_Node`; no DN: an instrument connection), symbol (default by class) with marker symbols such as packed beds and trays, nozzle stubs and node positions, tag label |
| `nozzle` | `--on EQUIP --at dx,dy [--dn] [--tag]` (needs `--sheet`) | a nozzle for existing equipment, placed from its symbol, pasted into its `Nozzles` and its drawing |
| `instrument` | `--tag PIC-4101 --at X,Y --sense ITEM[:x,y] [--field]` | a `ProcessInstrumentationFunction` (category, letters, number) with its `ProcessSignalGeneratingFunction` (sensing location ITEM) and `MeasuringLineFunction`, bubble, labels, node positions and the drawn measuring line |
| `signal` | `--from INST --to VALVE\|INST[,...] [--fail-action FC\|FO\|FL] [--number] [--points]` (needs `--sheet`) | a `SignalLineFunction` drawn dashed; to a valve also an `ActuatingFunction` and, when the valve has none, an `ActuatingSystem` with `ControlledActuator` and `OperatedValveReference` (and actuator symbol) |
| `offpage` | `--in\|--out --at X,Y [--rotation R] [--dn] [--note TEXT] [--note-at X,Y]` | a `FlowIn`/`FlowOutPipeOffPageConnector` with node, arrow and note |
| `line` | `--number N --dn [--fluid F] [--at X,Y]` | a `PipingNetworkSystem` with empty `Segments`, its drawing and number label |
| `note` | `--text TEXT --at X,Y` | a `Static` text at the top of the diagram, owned by no object (no `label-literal`) |
| `shape` | `NAME [--id]` | the catalogue `Shape` to paste into a sheet that lacks it, or which id it has there |

`--rotation` is the flow direction in degrees (0 left to right, 90 down, 270 up; Y down). With
`--sheet` the shape ids come from the sheet's `ShapeCatalogue` (looked up by shape name, else the
reference ids), a pipe's ends from the sheet's node positions (else `<node>_Position`, the name a
fragment gives them), and a label's cached text from the value it shows. Notes (a node that
already has a pipe, a DN without a standard enumeration value) go to stderr. Nothing is written.
With `--sheet`, the comments of the drafting kinds name the holder's id and line.

The template catalogue (`empty-sheet.xml`, `shapes.md`) has, besides the reference's shapes,
compressors, turbine/expander, blower, column with packed-bed and tray markers, gas filter,
silencer, air cooler, general and shell-and-tube exchangers, electric heater, ambient vaporizer,
flat-bottom tank, plate-fin exchanger and gate valve (`chemeascode.domains.piping.authoring.shapes`; their
`SymbolRegistrationNumber` is the shape's name until an ISO 10628-2 number is checked against
the standard; none is borrowed from a symbol of another name).

### run

`cheme run [--fmt SHEET] SCRIPT [ARGS...]` runs a Python file in cheme-as-code's own
interpreter, where `pydexpi` and `chemeascode` (with the authoring API) import. A plant repository
has no Python project, so neither `python3` nor `uv run python` can import pyDEXPI there, and the
template's `Bash(cheme:*)` permission already covers `cheme run`. Arguments after SCRIPT
go to the script as `sys.argv[1:]`, its exit code is cheme-as-code's (an uncaught exception prints
its traceback and exits 1), and the working directory is the repository root, so relative paths
mean the same wherever it is started. `--fmt SHEET` (before SCRIPT, repeatable) formats a sheet
after a successful run (after SCRIPT it goes to the script, and cheme-as-code warns).
`cheme --version` prints the interpreter's path on its second line.

### Authoring API (`chemeascode.domains.piping.authoring`)

Generator scripts build sheets with the documented module `chemeascode.domains.piping.authoring` instead of
their own XML helpers:

```python
import sys
from chemeascode.domains.piping.authoring import (
    Sheet,
    Marker,
    Nozzle,
    equipment,
    line,
    valve,
    tee,
    instrument,
    offpage,
    note,
)

sheet = Sheet.load(sys.argv[1])  # reads the shape catalogue, ids, node positions
pump = equipment(
    sheet,
    "CentrifugalPump",
    "P-101",
    shape="CENTRIFUGAL_PUMP_SHAPE",
    at=(160, 150),
    nozzles=[Nozzle("N1", (-7.5, 0), 80), Nozzle("N2", (0, -7.5), 50)],
)
column = equipment(
    sheet,
    "ProcessColumn",
    "C-101",
    shape="COLUMN_SHAPE",
    at=(260, 120),
    scale=(1.0, 1.6),
    markers=[Marker("COLUMN_PACKED_BED_SHAPE", -20, 1.5), Marker("COLUMN_TRAY_SHAPE", 20)],
)
t = tee("T1")
line(
    sheet,
    "80-W-101",
    dn=80,
    fluid="Water",
    route=[
        offpage("in", at=(20, 150), note="from P-01"),
        valve("HV101", "GateValve"),
        t,
        valve("FV101", tag="FV-101"),
        pump["N1"],
    ],
)
line(
    sheet, "25-W-103", dn=25, route=[t.branch, (t.branch.xy[0], 180), offpage("out", at=(405, 180))]
)
instrument(
    sheet,
    "FIC-101",
    at=(130, 130),
    sensing="Line_80W101_S2",
    sensing_at=(135, 150),
    signal_to="FV101",
)
note(sheet, "Trip: LALL-101 stops P-101", at=(60, 210))
sheet.save()  # writes, then cheme fmt
```

| builder | builds |
|---|---|
| `Sheet.load(path)`, `sheet.save([path])` | load a sheet (refusing ids that clash when adding), write and format it |
| `equipment(sheet, cls, tag, shape=, at=, nozzles=[Nozzle(name, (dx, dy), dn)], scale=, markers=)` | equipment of a DEXPI class with nozzles, symbol, node positions and tag label; `eq["N1"]` is a nozzle's port. `scale=1.2` or `scale=(1.0, 1.6)` (ScaleX, ScaleY: a tall column); `markers=[Marker("COLUMN_PACKED_BED_SHAPE", -20, 1.5), ("COLUMN_TRAY_SHAPE", 10), "COLUMN_TRAY_SHAPE:20:1:m"]` draws packed beds and trays on the symbol at `dy` from its centre, as `fragment equipment --marker NAME:dy[:SY][:m]` does. A shape missing from an older sheet's catalogue is copied from the template's |
| `line(sheet, number, dn=, fluid=, route=[start, (x, y)..., valve(...), tee(...), end])` | the piping network system, its segments (split at tees), pipes with bends, inline items and the number and DN labels, placed beside the route and never on it, clear of symbols, other lines and texts where there is room |
| `valve(id, cls, at=, tag=)`, `tee(id, at=, branch=)` | inline items for a route (mid-leg without `at`); `t.branch` is the tee's branch port |
| `offpage("in"\|"out", at=, note=)` | an off-page connector starting or ending a route |
| `instrument(sheet, tag, at=, sensing=, sensing_at=, signal_to=, location=)` | an instrument function with sensor, measuring line and bubble; `signal_to` a valve adds the actuating system, actuator and signal line |
| `note(sheet, text, at=)`, `label(sheet, for_id, attribute, at=)` | free text owned by no object; a label as `fragment label` makes it |

Valves, tees, pipes, segments and labels are built by the same functions as `cheme
fragment`, so the XML is identical. Each builder is atomic: one that raises (an id that
exists, a valve off its leg) leaves the sheet as it was, so a corrected retry with the same ids
works. `cheme init` puts a runnable example in `scripts/example_draft.py`.

### regen: generated and hand-maintained sheets

A sheet in `plant.yaml` may name its generator:

```yaml
sheets:
  - {id: P-04, file: pid/P-04.xml, generator: {script: scripts/draft_P-04.py, frame: 9aa9b38}}
```

`frame` is a file in the repository or a git revision whose copy of the sheet file is the start
(the commit with the empty sheet). A sheet with a generator is **generated**: the script is the
source and the XML is not edited by hand. Without one it is **hand-maintained**: the XML is the
source and any script is provenance only.

- `cheme regen [SHEET...]` copies the frame to a scratch file, runs `cheme run SCRIPT
  FILE` (the script edits FILE in place) and `fmt`, and writes the sheet. It refuses when the
  sheet differs from what the generator *as committed at HEAD* makes (someone edited the XML by
  hand) and names the plant items that differ; `--force` overwrites anyway. `--detach SHEET`
  removes the `generator:` (keeping the rest of `plant.yaml` as written): the sheet becomes
  hand-maintained. `--list` prints each sheet's state.
- `cheme validate` runs each declared generator in a scratch copy of the repository (so
  whatever else the script writes never reaches the working tree) and warns
  `cheme.generated-sheet-drift` when it no longer reproduces the sheet (`generator-failed`
  when it cannot run). This executes the scripts `plant.yaml` declares, also in the pre-commit
  hook and CI: on a clone you do not trust, run `cheme validate --skip-generators`, which
  leaves this out. `validate` also gives an info
  `cheme.generator-undeclared` for each `scripts/draft_<sheet>.py` of a sheet without
  `generator:`.

### process: BFD, PFD, stream table and properties

The block flow diagram (BFD) and process flow diagram (PFD) are generated, never drawn by hand.
Their source is two YAML files, schema `cheme/process/v1`:

- `process/materials.yaml` (kind `process-materials`): components (id, name, formula, CAS, molar
  mass, optional InChIKey and SMILES, checked by `cheme validate`), templates (ordered component lists) and the property method;
- `process/flowsheet.yaml` (kind `process-flowsheet`): units (every value without its own unit
  is in these; pressure absolute, gauge only as an explicit unit, `Nm3/h` only with
  `normal_conditions`), cases, the balance tolerance, `feeds` and `products` (DEXPI `Source` and
  `Sink`), `blocks` and `steps` with explicit `ports` (in/out, material/energy/information),
  `streams` from port to port with a per-case `state` (pressure, temperature, flow, duty,
  composition, phase), `links` to the lists and sheets, `layout.bfd` / `layout.pfd` pins, and
  optionally `tears` and `convergence` (the recycle loops `process propagate` converges, ADR
  0060) and `specs` (design specifications: feeds or splits it solves for a stream target, ADR
  0070); a block or step may give `recovery` (a component separator's specified split, ADR
  0070). Each value carries `provenance: given | assumed | calculated` and, when given, a `source`.
  A value or composition may give an `uncertainty` (the LCA's shape, e.g. `{gsd2: 1.2}` or
  `{distribution: triangular, low: 0.9, high: 1.1}`); `cheme assess lca` samples a feed's or
  product's flow with it, and no calculated value's fingerprint includes it. An optional
  `origin` says what kind of figure it is: given `measured`, `vendor` or `literature`; assumed
  `design-rule`, `estimate` or `literature`; calculated `simulated` (`cheme process simulate
  --fill` writes it) or `correlation` (`cheme process props --fill`, `cheme datasheets fill`).
  Another pairing is `cheme.provenance-origin` (warning). A DEXPI sheet maps `measured` to
  OBSERVED, and `lca.yaml`'s `uncertainty.defaults` may be keyed by an origin
  (`measured: {gsd2: 1.02}`), which wins over the provenance's.

`plant.yaml` declares the sheets by kind: `{id: BFD, kind: bfd, file: process/BFD.xml}` and
`{id: PFD, kind: pfd, file: process/PFD.xml}`. A `kind: validate` gate with `generated: [pfd]`
(the template's `process-basic`) fails until the PFD is declared and built.

`plant.yaml`'s `requires: cheme-as-code>=X.Y` (written by `cheme init`) names the oldest
cheme-as-code the repository works with; an older one stops every command, the pre-commit hook
included, with `cheme.version-required` and an upgrade hint before any schema error.

- **`cheme process build [SHEET...] [--force]`** writes DEXPI 2.0.1 `ProcessModel`s with a
  drawing. The BFD shows blocks, feeds and products and every stream that crosses a block
  boundary; the PFD nests the steps in their blocks, with block ports delegating to step ports
  (`superReference`), and adds the internal streams. Values become `QualifiedValue`s with their
  provenance and case. The layout is layered left to right with recycles routed back, labels
  placed clear of lines and nodes, and the `layout.<view>` pins applied. A rebuild is
  byte-identical; a title rename moves nothing.
- **The PFD drawing** (ADR 0046). The sheet is the smallest that holds the drawing and the stream
  table: ISO 216 A3 to A0 or an ISO 5457 elongated one (A3x3 to A0x3), landscape, with the
  frame, zone markers and a title block (title, project, drawing number, case, sheet). A layout
  wider than an A0 wraps into rows, read like text. Steps are drawn with the ISO symbol of
  their class (a step's optional `symbol:` overrides it: a symbol name, `junction` or `box`;
  an unknown name is `cheme.process-symbol`, warning); mixing and splitting steps are junction
  tees. A utility terminal (`category: utility`, a `utility:` given, or only energy ports) is
  not a box with a line to every user: each of its streams is a short stub on top of the step
  it serves, with the utility's id. Process lines are drawn heavier than equipment, with flow
  arrowheads; blocks holding steps are light dash-dot process areas. Below the drawing the
  stream table lists each material stream's phase, temperature (°C), pressure (bar), mass flow
  and the flows of the largest components, and each energy stream's duty, for the default case
  (assumed values marked `*`, stale ones blank). The BFD gets the same frame and title block.
- **Calculated values and phase in the sheets.** Each material stream's `MaterialState` (its
  `MaterialStateType`) carries the `state.calculated` values DEXPI 2.0.1 has a property for:
  `density` (kg/m3) and `specificEnthalpy`, one `QualifiedValue` per case with the YAML
  provenance (`calculated`: CALCULATED) and source. DEXPI binds `specificEnthalpy` to mass
  units, so kJ/kmol is divided by the case's molar mass (kJ/kg; the display text keeps the
  kJ/kmol value, the description names the molar mass and the enthalpy reference); without a
  molar mass the enthalpy is not a `QualifiedValue`. The phase is the material state's `phases`:
  one `MaterialStateType` per phase present (identifier `vapor` or `liquid`, two-phase gives
  both), its description `<case>: <phase>, vapour fraction <x>; <provenance>; source: ...`.
  DEXPI has no property for the molar mass (or any other calculated value): those are lines
  `calculated molar_mass (<case>) = 28.96 kg/kmol; source: ...` in the state type's
  description; no class or attribute is invented. **Stale values are not exported**: a value
  or phase reported by `cheme.process-calculated-stale` is left out of the sheet, and the
  description says `stale, not exported (<case>): density, phase`, so a DEXPI consumer never
  reads a value its inputs no longer give. Because staleness follows from the YAML, the sheet is
  `generated-outdated` until rebuilt; recalculate (`props --fill`) and rebuild to export again.
- **BFD aggregation.** `bfd: {aggregate: true}` in the flowsheet draws parallel boundary
  streams between the same two BFD nodes (same kind, same direction) as one connection;
  `aggregate: [[A, B], ...]` limits it to those pairs (`cheme.process-aggregate` if one is
  not on the BFD). The connection keeps its first stream's id and ports, its label and
  description list every stream (`represents: S2 S3`), and it carries no values; the PFD,
  stream table and balances are unchanged (`examples/process-aggregate/`).
- **Refinement keeps stream ids.** When a block gets steps, a boundary stream keeps its id and
  moves its end from `BLOCK.port` to `STEP.port`, whose port `delegates` the block port. Balances
  count it once; the BFD and its balances are unchanged by a refinement
  (`examples/process-blocks/` before, `examples/process-recycle/` after).
- **Nested blocks.** A block with `parent: P` is drawn inside P on the PFD (with its own steps
  and nested blocks) and is a sub process step of P; the BFD shows top-level blocks. Its ports
  `delegate` P's ports where a stream crosses P's boundary, just like step ports
  (`examples/process-nested/`). Inside a block, ports are ordered by where their lines go and
  the step order with the fewest crossings wins.
- **Generated-sheet provenance.** Each sheet records a fingerprint of its YAML source and of its
  own XML. `validate` reports `cheme.generated-outdated` (warning: the YAML changed, rebuild),
  `cheme.generated-edited` (error: the XML was edited by hand; `build` refuses it unless
  `--force`) and `cheme.generated-version` (warning: cheme-as-code's generator version, generator
  code (`generator_sha256`, a hash of the `chemeascode.domains.process` sources) or schema version
  changed). A YAML edit never reports `generated-edited`.
- **Balances.** Steady-state, non-reactive mass and component balances per block and per step,
  on its boundary streams (internal streams cancel), with `|in - out| <= abs + rel * max(in,
  out)`, in the default case and every other case that streams give a state for.
  `cheme.process-balance` (error) names the block, the case and both sums;
  `process-balance-not-evaluable` (info, default case only: in another case a balance with
  missing values is not reported) names the missing values;
  `process-component-balance-not-evaluable` (info) a mass balance that closes while the
  component balance lacks compositions (accepted by the concept gate, not by `process-basic`).
- **Reactions** live in `process/reactions.yaml` (schema `cheme/reactions/v1`,
  `cheme schema process-reactions`): stoichiometry over the component ids (reactants
  negative), an optional conversion of a key component, heat of reaction, catalyst and sources.
  `validate` checks each reaction's element balance from the components' `formula`
  (`cheme.reaction-*`). A step or block naming `reactions: [ID, ...]` (optionally
  `conversion: {ID: fraction}`), or a block with `balance_scope: reactive`, balances mass and
  elements instead of components, and the component changes must be explained by extents of its
  reactions (least squares; `process streams` prints the extents). A block holding a reactor
  step is reactive too. `reactor: equilibrium` takes the named reactions to equilibrium at the
  outlet's temperature (plus `approach`) and pressure, `reactor: gibbs` minimises the Gibbs
  energy over every component of the streams (both ideal gas, in `process propagate`), with
  ln K from each component's `ideal_gas` data (formation enthalpy, entropy, Cp/R polynomial) or
  a reaction's `equilibrium_constant`. With `fugacity: peng_robinson` the equilibrium is that of a
  real gas (Peng-Robinson fugacity coefficients from the components' `critical:` constants;
  `domains/chemistry/eos.py`). `examples/process-ammonia` is an ammonia synthesis loop with a
  real-gas equilibrium converter, purge and recycle.
- **Fixed beds** (`reactor: pfr` with `catalyst:` and `bed:`): `process propagate`
  integrates the reactions' rate laws along the catalyst mass (1D plug flow, adiabatic,
  isothermal or cooled, Ergun pressure drop; `domains/process/fixed_bed.py`) and writes the
  outlet's composition, flow, temperature and pressure; `process reactors` adds the bed
  (catalyst mass and volume, pressure drop, hot spot, profile). `datasheets fill` sizes a
  reactor's datasheet from its bed (or the catalyst's space velocity) and `assess equipment`
  adds its first catalyst fill at the catalyst's price. `examples/process-shift` is an
  adiabatic high-temperature shift bed.
- **`cheme process reactors [--case C] [--json]`** reports per reactor its model, the extents,
  each reaction's heat and ln K at the outlet, `ln(Q/K)` (0 at equilibrium) and the duty
  H(out) - H(in) on the elements basis, ideal gas.
- **Catalysts** live in `process/catalysts.yaml` (schema `cheme/catalysts/v1`): active phase,
  promoters, support, particle and bed data, the temperature and pressure window, space
  velocity, poisons, deactivation and price, each with provenance. A reactor names its
  `catalyst:`; `validate` warns when its streams leave the window or a feed carries a poison.
  Reactions take a `rate:` (power law or LHHW, per kg of catalyst or per m3, optional
  `(1 - Q/K)`), which `process reactors` evaluates at the outlet. A reaction's `catalyst:`, its
  `rate.catalyst` and its `mechanism.catalyst` name a catalyst by id; `validate` warns on one
  the file does not declare (`cheme.catalyst-unknown`).
- **Reactive hazard screening**: **`cheme process reactor-hazards [--json]`** gives each
  reactor's adiabatic rise, MTSR, MTT and, with a TD24 from calorimetry (`hazard:` on the
  reactor), Stoessel's criticality class; a cooled bed's hot-spot sensitivity
  (`domains/safety/reaction_hazards.py`, findings `cheme.reactor-hazard-*`). A semi-batch's
  accumulation `X_ac` is the dosed reactant's largest over the run and its MTSR the
  cooling-failure temperature at the worst moment (ADR 0050); a batch keeps `X_ac = 1`. A
  reaction with `kind: phase-change` (or one component into one other of the same formula, one
  of them `phase: solid`, declaring no `heat_of_reaction`) is a phase change: a step whose
  reactions are all phase changes is not screened (`cheme.reactor-hazard-phase-change`, info;
  JSON `phase_changes`), a step with both takes dT_ad and the MTT from its reactions alone, a
  semi-batch's MTSR from its whole model, the phase changes included, with a note (ADR 0056).
  The default MTT is the lowest boiling point of what boils in the liquid at the reactor's
  pressure (ADR 0058): a batch's vent components, a dosed gas (a dose with `absorbed`) and
  dissolved gases (under 5 % of the liquid, boiling below `T_p`) are left out with a note
  (JSON `mtt_left_out`; with nothing else left the MTT needs `hazard.mtt`; a larger share
  boiling below `T_p`, a solvent at reflux, sets the MTT at or below `T_p`, with a note); from 90 to 110 kPa(a) the normal boiling point,
  else Clausius-Clapeyron with the component's `heat_of_vaporization` (without it a note, and
  above atmospheric no MTT where that component could set it). `hazard.reactions: [ids]` names
  the reactions whose heat sets dT_ad and the MTSR (default: every reaction, the largest); with
  more than one reaction the output gives each one's dT_ad and MTSR (an endothermic one's MTSR
  is `T_p`; JSON `per_reaction`,
  `counted_reactions`, `counted_basis`; `cheme.reactor-hazard-reactions`, warning: a name the
  step does not hold). A semi-batch gives its MTSR profile, time, `X_ac`, temperature and
  MTSR at about 21 moments and the worst (JSON `mtsr_profile`, a text line). A vented batch or
  semi-batch gives its gas release at the MTSR (JSON `gas_release`): the vent components forming
  at the rate laws at the MTSR, the larger with the worst moment's content and with the content
  once the reaction setting the MTSR ran to completion (gas from its products; `rate_from`; a
  longer chain is not covered), in kmol/s and m3/h at the MTSR and the vessel's pressure, per
  batch of `process/recipe.yaml` (else per hour of flows), and the most gas one reaction forms
  run to completion (`formed_by`, `formed_from`: of the counted reactions from the worst
  moment's content, or of a reaction consuming a product of the one setting the MTSR);
  `cheme.reactor-hazard-vent`
  warns without `hazard.vent_capacity` (m3/h) or above it, and is info within it. The pressure
  of a blocked vent is not screened. ADR 0069 (`domains/safety/reaction_network.py`):
  `hazard.potential: network` takes dT_ad and the MTSR from the counted reactions as a network,
  the largest heat forward extents of them together release from the content (a linear
  programme: a consecutive reaction on a product adds its heat, of competing ones the more
  exothermic takes the reactant); a batch or semi-batch with a consecutive pair reports it
  without the choice (JSON `network`, a text line, a note where it is above the largest single
  reaction's MTSR). A semi-batch gives each dosed reactant's largest accumulation and the share
  of it the reactions can still consume (`accumulations`: `max`, `reactive_max`; a deliberate
  excess is not reactive; with more than one dosed reactant or an excess). A vented
  semi-batch's `gas_release.largest_over_batch` is the largest release over the batch, each
  step's content at its MTSR with the liquid's vapour (at most what the reactions' heat there
  evaporates, `heat_limited`), by component, and the `-vent` check
  takes the larger of it and the release at the MTSR. A content boiling at the MTSR gets
  `gas_release.boil_up`: its bubble point, the reactions' heat there and the vapour it boils
  off (kmol/s, m3/h). `dissolved_release` gives the dosed and dissolved gases (and vent
  components boiling below the MTSR) held in the liquid at their largest over the batch, kg per
  batch, their boiling point against the MTSR and what the gas release strips of them
  (`cheme.reactor-hazard-dissolved`, info). The default MTT counts a product a counted reaction
  forms in the liquid (at least 5 % of it once formed, boiling at or above `T_p`);
  `hazard.mtt_from: bubble-point` takes the MTT from the content's bubble point at the vessel's
  pressure instead (Raoult's law over `vapour_pressure`, else `normal_boiling_point` and
  `heat_of_vaporization`; the lower of the worst moment's content and that after the cooling
  failure; dissolved gases left out; JSON `bubble_point`).
- **Reactor choice**: **`cheme process reactor-choice NODE --product P [--key K] [--tanks N]
  [--svg FILE] [--json | --csv]`** compares an ideal PFR, one CSTR and N CSTRs in series for a
  step's reactions: yield and selectivity of P against the key's conversion over a range of
  space times, the largest yield of each, and the PFR's instantaneous selectivity
  (`domains/process/reactor_choice.py`; the SVG in light and dark); `--region-svg FILE` adds
  the candidate attainable region (`domains/process/attainable_region.py`).
- **Reactor uncertainty**: **`cheme process reactor-uncertainty NODE [--samples 200] [--seed 1]
  [--case C] [--json]`** samples the `uncertainty` of a step's reaction data (`rate.uncertainty`
  of A and Ea, and that of `heat_of_reaction`, `equilibrium_constant` and `conversion`) by Monte
  Carlo through the step's own reactor model (a fixed bed, a stirred tank or batch, a conversion
  reactor; equilibrium and Gibbs reactors are not sampled) and prints the conversion of the key
  (the first fed reactant), the outlet and the highest temperature as declared, with their mean
  and 5th, 50th and 95th percentile; draws that do not solve are counted and named
  (`domains/process/reactor_uncertainty.py`). Nothing is written. Exit 2 when the step cannot
  be sampled (not one inlet, no reaction with an uncertainty, not solvable as declared).
- **Selectivity as a design input**: a conversion reactor step may give `selectivity: {key,
  conversion, products: {id: S}}` (kmol formed per kmol of the key converted); `process
  propagate` solves the extents of its parallel and series reactions
  (`chemistry.reactions.selectivity_extents`), refusing selectivities the reactions cannot give.
- **Batch recipe**: **`cheme process recipe [--case C] [--svg FILE] [--json]`** reads
  `process/recipe.yaml` (`cheme/recipe/v1`, ADR 0051): the `batch_size` (kg, t or m3 of one
  stream per batch), the `hours_per_year`, and the `unit_procedures` (ISA-88 names: a unit, its
  `parallel` units, its ordered operations charge, heat, dose, react, cool, transfer, distil,
  filter, dry, clean, hold or other, each with a `duration` or, for dose and react, `from:` a
  batch or semi-batch step's model; for distil, `from:` a still step's boil-up time (ADR 0055);
  for dry and filter, `from:` a dryer or a filter with `filtration:` (ADR 0057); for transfer,
  `from:` the semi-batch whose dose takes what the unit makes, that dose's time (ADR 0073); a
  unit procedure gives `unit:` or `units:`, several steps in one vessel). It gives each unit's
  occupancy, the cycle time (the bottleneck), the batches per year, one batch's timeline (a unit starts at the previous one's `transfer`, or at
  its `start`) and the batch-size stream's year-average rate; `--svg` draws one batch as a
  Gantt chart (light and dark). `validate` reports `cheme.recipe-*`: `-schema`, `-reference`,
  `-duration` and `-basis` (warning: the flowsheet's rate of that stream differs from batch size
  x batches / hours by more than 1 %). `estimate/tea.yaml` `operation.batch: {recipe: true}`
  takes the cycle time and batches per year from it (`domains/process/recipe.py`). A unit
  procedure on a batch or semi-batch step may size its `vessel` (fill fraction, R10 preferred
  sizes) and check its `jacket` (U, area or wetted shell, coolant and heating temperatures)
  against the model's peak duty (`cheme.recipe-jacket`, `-vessel`); a `heat` or `cool`
  operation with `temperatures: [start, end]` gets its time from the jacket; `datasheets fill`
  writes a batch reactor's volume and peak duty from it (ADR 0052). A `unit:` that is a block,
  or `units:`, holding one batch or semi-batch step sizes the vessel from that step (ADR 0057;
  1.7.0 gave `cheme.recipe-reference` for a block). Several such steps one after the other in
  one vessel (a one-pot sequence, ADR 0073; 1.12.0 gave `cheme.recipe-reference`) size it from
  the largest content of any of them, check the jacket against each step's peak duty at that
  step's own charge (`vessels[].steps`, the vessel's own fields the step with the least
  margin; `cheme.recipe-jacket` names the step), time a `heat` or `cool` with `temperatures` on
  the content of the batch step its next `from:` operation names (that step's charge when none
  of its operations came before, else its end; after the last, the last step's end), report
  each vented step's vent, and give `datasheets fill` each step's own peak duty. Another step
  of the vessel that takes in more for one batch than the batch steps' content (a conversion
  step adding a second portion) is `cheme.recipe-vessel` (warning); `vessel.size_from: steps`
  sizes the vessel from it too. `vessel.jacket.shortest_dosing: true` reports, for each
  semi-batch step of the vessel, the shortest dosing whose peak duty the jacket removes at the
  charge (`dosing`: the declared and the shortest h, the peak and the removable kW, or why
  there is none): the dosing schedule stretched in time (every dose's start and segments, the
  shares and the post-reaction kept), its factor bracketed from the declared schedule and
  bisected to 1e-4 between 1e-3 and 1e3 times; the model keeps its declared dosing.
  `cheme.recipe-coupling` (warning): a dose fed by another batch step's vent whose operation
  does not start in one batch when the generator's dose (or reaction) operation does. A filter
  or dryer in the same vessel takes
  its plate and heated area (`vessel.heated_area`, else the jacket's area, else the shell and
  bottom the dryer's wet cake wets) from it. `vessel.metal_heat_capacity` (kJ/K, ADR 0063)
  counts the vessel's steel in the `heat` and `cool` times (`C + C_m`) and adds the term `vessel
  metal`, `C_m (T_1 - T_0)` per batch, to the duty of each model in the vessel that changes the
  content's temperature: the metal follows the content (a batch with `heat_up` from its
  charge's temperature, none without it; a still from its bubble point to its end temperature,
  from its charge's with `heat_up`, or from its bubble point when the charge enters at or above
  it; a crystallizer from its feed's; a still at constant volatility models no temperature and
  gets none, its basis saying so). `process recipe` reports
  the heat of each heat-up or cool-down with `temperatures` in a vessel with metal (`heats`:
  content and metal kJ per batch, mean and year-average kW; a recipe without metal reports as in
  1.9.0). A unit
  procedure holding a still may give a `vessel` (sized from what its steps take in, or its
  `volume`; no jacket check).
- **Stirred tanks and batches**: `reactor: cstr` (a `tank:` of a volume or residence time,
  `count` tanks in series, isothermal or adiabatic) and `reactor: batch` (a `batch:` time or
  target conversion) solve the reactions' rate laws (`domains/process/stirred_tank.py`), gas or
  liquid; `process propagate --fill` writes the outlet and `process reactors` reports the tanks'
  conversions and duty, or the batch's profile and heat release. `reactor: semibatch` (liquid)
  is a batch with `batch.dosing: [{stream, time | profile, start}]` dosed into its charge: the
  dosed streams are inlets of the step, the other inlet the charge, `time`/`target` the
  post-reaction. `process reactors` adds the accumulation of the dosed reactant over time and
  its maximum, the worst cooling-failure temperature and the peak cooling duty per m3
  (`stirred_tank.solve_batch` with doses; ADR 0050). `process simulate` does not couple it.
  A liquid batch or semi-batch that gives off gas takes `batch.vent: {stream, components,
  fraction}` (ADR 0054): the listed components leave the liquid as they form (a `fraction` of
  what each reaction forms, default 1; a reaction consuming one takes it from the liquid), by
  the vent `stream`, the step's second outlet; they count in neither the liquid's volume,
  concentrations nor heat capacity, and their `heat_of_reaction` forms them as gas at the
  vessel's temperature. A dose may give `absorbed: share`: that share dissolves, the rest passes
  through to the vent. A dissolving dose adds no heat of absorption or condensation: write the
  `heat_of_reaction` of its reactions with the dosed gas as a gas, or give the dose's
  `heat_of_solution` and its reactions' heats on the dissolved basis (below).
  A dose's `heat_of_solution: {values: {component: kJ/kmol}, provenance}` (ADR 0063) is the
  integral heat of solution, dilution or mixing (J/mol of the component dosed, negative:
  released) of a liquid or of a gas's absorbed share: released at the dose's rate, it counts in
  the adiabatic balance, the peak cooling duty and the recipe's jacket check, the duty's term
  `solution`, and in `reactor-hazards`' dT_ad (`heat_of_solution`), not in the MTSR (released on
  mixing, nothing of it is accumulated when the cooling fails and the dosing stops). A dosed
  component the vent's vapour takes off the liquid again takes its heat of solution back (what
  passes the condenser when its condensate returns, else all the gas carries): `solution` is
  then the heat of what stays dissolved or reacts.
  `batch.heat_up: true` adds the charge heated from its inlet temperature to the batch's to the
  duty (`charge heat-up`), and the vessel's metal with it; without it the model holds the batch
  at its temperature from the start and leaves both to the recipe's heat operation. `heat_up`
  and an isothermal batch's `heat_of_solution` change only the duty: the outlets and a recycle's
  tears do not go stale on them, nor on a vent condenser's `energy_port`. `process propagate` writes both outlets and the balance
  closes over them; `process reactors` adds the vent's kmol/h and peak rate per m3 of the final
  content, `process recipe` its peak kmol/s and m3/h per batch and what a batch gives off, and
  `process reactor-hazards` leaves the vented gas out of the MTSR and the MTT (the vent's
  components, a dosed gas and dissolved gases do not set it, ADR 0058; a note gives the vent's
  peak rate) and reports the gas release at the MTSR against `hazard.vent_capacity`. `cheme.process-reactor`: the vent stream no outlet of the step or its only one,
  more than two outlets, an undeclared vent component, a vented batch on gas-phase reactions,
  a vent stream whose template lacks a vent component or a passing dose's component, (warning)
  one formed by no reaction, a dose with `absorbed` below 1 and no vent, (warning, ADR 0073) a
  dose's gas that passes through (a dose with `absorbed` below 1, a vent's inerts) without
  `ideal_gas` data, whose warming to the vessel's temperature is then left out.
  `cheme.process-coupled-dosing` (ADR 0073): a semi-batch dose fed by another batch or
  semi-batch step's vent (directly or through steps with one material inlet each) on another
  schedule than the generator's dosing (its one dose's segments, its doses' window, or a
  batch's 0 to `time`) is a warning; where the generator solves, an info gives the largest
  difference between the share of its vent gas that has left and the share the dose has fed,
  over the batch (both clocks from the charge). `process simulate` does not couple a vented
  batch.
  The vent may say more (ADR 0062; a vent without these keys solves as in 1.9.0):
  `vapour: {components, activity, source}` saturates the gas with the liquid's volatile
  components at the vessel's temperature and pressure (Raoult, each component's Antoine
  `vapour_pressure`; an ideal liquid unless `activity` gives sourced constants; default every
  component with a `vapour_pressure`, never a vent component): each kmol of gas carries
  `Y / (1 - Y)` kmol of vapour, `Y = sum gamma_i x_i P_i^sat / P`, taken off the liquid as it
  leaves, its latent heat (`heat_of_vaporization`) the vessel's evaporative cooling (a `vent
  vapour` term of the isothermal duty; in an adiabatic batch it cools the content); a content
  that boils (`Y >= 1`) is refused. `condenser: {temperature, returns: vessel | stream,
  energy_port, provenance, source}` is a partial vent condenser: one flash at its outlet
  temperature over an ideal condensate (the vent's gases are inerts), the gas past it saturated
  there (one condensable over an inert: `G K / (1 - K)`), the condensate back to the vessel
  (warmed back, a `condensate return` term) or out by a third outlet stream; its duty
  (condensation at the vessel's temperature, the vapour cooled as liquid, the gases cooled as
  ideal gases, left out with a note without their `ideal_gas`) is written on the energy stream
  at its `energy_port` (`calculated`, ADR 0059; never the step's own `energy_port`), and the
  vent and condensate streams carry its temperature. `henry: {gas: {points: [[K, kPa]],
  provenance, source}}` keeps a vent gas dissolved up to its solubility instead of a
  `fraction` (`p = H x`, ln H linear in 1/T): the liquid at the end holds `x = y P / H`, `y` the
  gas's share over the liquid, by successive substitution over whole runs (what was charged or
  dosed stays, with a note). `process reactors` adds the vapour carried off, the condensate,
  the vent's temperature, the condenser's duty on its stream and each gas's solubility;
  `process recipe` gives the vent's m3/h at the condenser's temperature; `reactor-hazards`
  takes the gas release at the MTSR vapour-laden (`vapour_share`, `noncondensable_m3_h`, the
  volume over `1 - Y` at the MTSR; no condenser credited; `formed_kmol` and `formed_m3` stay
  the non-condensables formed, `formed_m3_with_vapour` their volume with the vapour), and a
  content that boils at the MTSR is `boils`, a `cheme.reactor-hazard-vent` warning.
  `cheme.process-reactor` adds: a vapour component undeclared or without a `vapour_pressure`,
  a vent or condensate template lacking the vapour's components, a condensate stream that is
  no outlet, a condenser `energy_port` that is no energy port (or the step's own), a Henry gas
  missing from the liquid's template, a condenser `temperature` at or above the batch's
  temperature (an isothermal batch: its liquid outlet's given temperature, which the model
  holds it at, else the charge's; a warning for an adiabatic one, at its charge's); (warning) a
  `vapour` with no volatile
  component.
  A gas-liquid batch may say more still (ADR 0071; a vent without these keys, a component
  without `melting_point`, solves as in 1.11.0): `inerts: [N2]` are gases that never dissolve:
  a dose's share of them passes straight through to the vent (a nitrogen sweep or purge dosed
  with `start` and `time`, the nitrogen of a dosed air), each carrying the liquid's vapour like
  a formed gas; `components` may then be empty (a vent of a sweep alone), and an inert in the
  charge is refused. `head_space: {stream, provenance, source}` (needs `inerts`) pads the
  vessel's head space by `stream`, an inlet of the step that carries only inerts (its kmol/h:
  the head space's inert at the start); the vessel is the charge's volume plus that head space
  at the start, saturated; the head space holds `(1 - Y) P (V_vessel - V) / (R T)` and expels,
  vapour-laden, what a dose displaces, a rising vapour pressure or a warming pushes out, with
  what forms and passes through; what it holds at the end leaves by the vent too (with the
  next charge), and a liquid that fills the vessel is refused. A batch with a head space takes
  one charge stream besides the pad. `vapour.henry: {gas: {points: [[K, kPa]], provenance}}`
  degasses a dissolved gas with no Antoine `vapour_pressure` in `materials.yaml` (a dilute
  solute such as HCl, or a gas above its critical point) at `y = H x / P`; it never condenses
  (a vent condenser passes it as a gas). Any vapour component, by Raoult's law or Henry's, is stripped by whatever gas leaves, so a charged or dosed excess
  degasses under a sweep. `heat_of_absorption: {values: {gas: kJ/kmol}, provenance}` (negative:
  released) is released as a formed gas's dissolved share forms (`1 - fraction`, or its Henry
  share: the duty's term `absorption`, the adiabatic balance, the peak cooling duty; not the
  MTSR) and taken back by a degassing gas as it leaves (in its `vent vapour` term). `process
  reactors` adds the head space (`vent.head_space`: `vessel_m3`, `start_m3`, `end_m3`,
  `start_kmol`, `end_kmol`, `expelled_kmol`, per hour of charge), `reactor-hazards` leaves the
  inerts and the pad out of the content and the MTT, and a vent of inerts only has no formed-gas
  release at the MTSR (with `vapour`, a content boiling at the MTSR still reports its boil-up,
  `gas_release.boils` and `boil_up`, and the `-vent` warning); it takes a `vapour.henry` gas at
  `H x / P` in the gas release and leaves it out of the default MTT and the bubble point as a
  dissolved gas (dosed or not) whatever its share or boiling point (`mtt_left_out`,
  `dissolved_release`, with or without a `normal_boiling_point`); a boil-up at the MTSR that
  carries it asks for its `heat_of_absorption` (its heat of desorption), not its
  `heat_of_vaporization`; a vapour whose latent heat is not positive (an endothermic
  absorption, a positive `heat_of_absorption`, outweighing the liquids') leaves the boil-up
  unsized, with `missing` saying why.
  `cheme.process-reactor` adds: an inert or degassing gas undeclared, an
  inert in a reaction, a pad that is no material inlet of the step or carries more than the
  inerts, a vent template lacking an inert. `cheme.process-condenser-freezing` (warning): a
  vent condenser's outlet temperature, or the `supply_temperature` of the utility its
  `energy_port` stream runs to, below a condensed component's `melting_point` (K, on the
  component in `materials.yaml`; the pure component's, no freezing-point depression): keep both
  above it (a tempered coolant) or say in DESIGN.md why the mixture cannot freeze. The rule
  also checks a batch still's condenser: the `supply_temperature` of the utility its
  `condenser_port` stream (by default a column's one heat stream out) runs to, below the
  `melting_point` of a component its distillate's cuts carry at 1 mol% or more. Not
  modelled: a pressure balance (the vessel stays at its stream pressure), mass-transfer limits,
  a content at its boiling point.
- **Liquid-phase reactions**: a reaction with `phase: liquid` takes its `equilibrium_constant`
  on `basis: mole_fraction`, `activity` (UNIFAC from the components' CAS numbers, extra
  `props`; `activity_model: ideal` in `reactions.yaml` for activity coefficients of 1) or
  `concentration` (with each component's `liquid_molar_volume`), and its rate law on
  `driving: mole_fraction`, `activity` or `concentration`
  (`domains/chemistry/liquid.py`). `reactor: equilibrium` solves a liquid equilibrium and
  `process reactors` reports ln(Q/K) and the rate on that basis; `validate` warns when a basis
  does not fit the phase (`cheme.reaction-phase-basis`).
- **Solids, crystallizers and filters**: a component with `phase: solid` in
  `process/materials.yaml` is a solid (a crystal, or a hydrate with its water in the formula,
  `Na2CO3(H2O)10`), a separate component from the same substance dissolved; every stream then
  divides into dry solid and liquid (mother liquor or moisture) with their compositions
  (`domains/process/solids.py`; no particle size or population balance). A block or step with
  `crystallizer:` (one solute, one solvent, its material inlets taken together) is a cooling
  and/or evaporative crystallizer with an optional specified filter or centrifuge (`separation:` solid recovery
  and cake liquid) and mother-liquor `recycle:`; `basis: solubility` predicts the crystals from
  sourced solubility data (the mother liquor leaves saturated; points interpolated in
  temperature, never extrapolated), `basis: yield` imposes them (specified, compared with the
  solubility when given). `solid_separation:` is a filter or centrifuge on its own. `process
  propagate --fill` writes the outlets, `validate` balances the node on mass and elements, the
  model basis is `solubility-equilibrium` (predictive, not simulated), `imposed-yield` or
  `solid-split` (specified). **`cheme process crystallizers [--case C] [--json]`** reports the
  crystals formed (and at equilibrium), recovery, loop iterations, mass, solute and element
  residuals, the lumped duty (with `energy:`), the outlets as dry solid, liquid and moisture,
  and refuses undeclared impurities, several crystallizing solutes or a temperature outside the
  data (`cheme.process-crystallizer-unsupported`). Qualified against Felder & Rousseau Example
  4.5-2 and Geankoplis Examples 12.11-1 and 12.11-2 (`tests/test_crystallization.py`;
  `docs/adr/0025-solid-components-and-a-bounded-crystallizer-adapter.md`).
- **Precipitation from a mixed liquor** (ADR 0056): `crystallizer.spectators: [ids]` names the
  other dissolved components of the liquor (a salt, a base, unreacted reagent); they pass with
  the liquor unchanged, never crystallize or evaporate, and appear in the balances and the
  report, text and `--json` (`mother_liquor`: solubility basis, declared value and value at
  the solution, salting-out factor, molalities; `solubility_kg_per_kg_solvent` is then the
  mother liquor's per kg of free solvent). A block holding a crystallizer and a reacting step
  balances with the crystallization as a phase change next to its reactions. The
  solubility then holds in that liquor: `measured_in: mother_liquor` (unit `kg/kg_solvent`,
  `kg/kg_liquor` per kg of solute-free liquor, or `mass_fraction` in the saturated liquor:
  `C = (S - s (W + P)) / (a - s (1 - a))`), or the pure solvent's with `salting_out:
  {coefficients: {id: k}, log: log10 | ln, provenance, source}` (Setschenow, `log10(s0/s) =
  sum k_i m_i`, molal scale, every spectator once). A pure-solvent value alone is
  `cheme.process-crystallizer` (error) and refused by propagate. A crystallizer takes several
  inlets together (their mass-weighted mean temperature for the energy balance), so a reslurry
  wash is a crystallizer fed by the cake and the wash, its crystals dissolving to saturation
  (`tests/test_precipitation.py`).

- **Filter-dryers and dryers**: a block or step with `dryer:` (one wet-cake inlet, `outlets:
  {product, vapour}`) dries its `volatiles` to a `residual_moisture` (`mass_fraction` of the
  product or `per_kg_solid`). The volatiles kept have the inlet's ratio, and everything else
  (the solid and what the cake liquid held dissolved) stays in the product. `process propagate
  --fill` writes both outlets, and the model basis is `residual-moisture` (specified).
  - With `energy: {heat_capacity, latent_heat: {id: kJ/kg}, inlet_temperature,
    vessel_heat_capacity, efficiency, port}`, `process crystallizers` reports the duty `(m cp
    (T - T_in) + sum W lambda + C_v (T - T_in) / h_batch) / eta`. A latent heat that is not
    declared comes from the component's `critical` constants (Pitzer, Poling et al. 2001, eq.
    7-9.4). The vessel's heat is per batch of `process/recipe.yaml`. The duty is compared with
    the energy stream at `port` (`cheme.process-dryer-duty`). The product's dry solid is
    everything but the volatiles, so its moisture is the residual moisture.
  - A recipe `dry` operation with `from:` the dryer takes one batch's vapour over
    `drying_rate` (kg/(m2 h)) times the heated area of the unit procedure's vessel
    (`vessel.heated_area`, the jacket's area, or the shell and bottom the cake wets), or the
    dryer's `drying_time`. The vessel is sized, when it gives no `volume`, from the largest
    content of one batch: the wet cake over `cake_density`, or what a step of the unit
    procedure takes in (the slurry, a reslurry wash) from the liquid molar volumes. A given
    `volume` is checked against the same content (`cheme.recipe-vessel`).
  - A `solid_separation:` with `filtration: {specific_cake_resistance, medium_resistance,
    pressure_difference, viscosity, filtrate_density, area}` gives a `filter` `from:` its
    Ruth time `mu (alpha M V / (2 A^2) + R_m V / A) / dP`, with the area defaulting to the
    vessel's bottom.
  - A unit procedure may name `units: [F101, W101, F102, D101]` instead of `unit:`: the steps of
    one vessel, whose occupancy is counted once. A step in two vessels is
    `cheme.recipe-reference`. Rules: `cheme.process-dryer` (also a `latent_heat` keyed by a
    component that is not a volatile), `cheme.process-dryer-duty`.
  - The module is `domains/process/dryer.py`, the tests `tests/test_dryer.py`, the decision
    `docs/adr/0057-filter-dryer-and-recipe-units-over-several-steps.md`.

- **Batch still and solvent swap**: a block or step with `still:` (ADR 0055,
  `domains/process/batch_still.py`) is a batch (Rayleigh) still: one equilibrium stage, total
  condenser, no reflux, `dN_i/ds = -y_i` over the moles boiled up. The vapour comes from
  Raoult's law at the still's bubble point (`volatility: {model: raoult}`, each volatile
  component's Antoine `vapour_pressure: {a, b, c, form: log10 | ln, pressure_unit: bar | kPa |
  Pa | mmHg, temperature_unit: K | degC, temperature_range}` in `materials.yaml`, by default
  the NIST form `log10(P/bar) = a - b/(T/K + c)`), or from a constant relative volatility
  (`{model: constant, alpha: {component: value}}`). `nonvolatile:` components (and solid
  components) stay in the still, counted in the liquid as dissolved solutes.
  `separate_phase: [ids]` (ADR 0068) lists components in a phase of their own (a suspended
  solid, an immiscible non-volatile liquid, a salt): they stay in the still and are left out of
  the liquid's mole fractions (the bubble point, the vapour, a residue end's and the profile's
  key fraction, a column's still liquid). A residue end on a still with it is the key's share
  of the liquid, not of the pot.
  - `boilup: {value, unit}` is constant: kmol/h, kmol/s or kg/h of vapour, kW of heat (`V = Q
    / lambda(y)`, the components' `heat_of_vaporization` in kJ/kmol), 1/h (kmol of vapour
    per hour per kmol of charge) or m3/h (raoult, ADR 0068: the vapour's volume at the still's
    temperature and pressure as an ideal gas, `V = Vdot P / (R T)`, a vacuum pump's capacity).
  - `cuts: [{outlet, end, pressure, boilup}]` (ADR 0068): a cut is collected at its own
    `pressure` kPa(a) (raoult) and `boilup`, else the still's; a vacuum ramp is a sequence of
    cuts. At a change of pressure the still steps to the new bubble point (a note; the flash or
    the heating between is not in the time or the duty). Without a feed the first cut's
    pressure is the still's from the start. `process stills` gives `pressure_kPa` and `boilup`
    for a cut with its own.
  - The still stops at `end:` (one of `distilled` with `basis: mole | mass`, `residue: {key,
    mole_fraction}`, `time` s of boil-up, `temperature` K, `purity: {key, fraction}` with
    `basis: mole | mass`: the cut's mean share of the key falls to the fraction, a product cut
    collected to its specification), or `cuts: [{outlet, end}]` collect
    the distillate in turn. `outlets: {distillate, residue}` (with cuts: `residue` only) maps
    the roles to the step's ports.
  - `feed: {stream, mode: constant_level | portions, portions, down_to}` makes it a solvent
    swap. The feed is an inlet stream (its flow per hour of charge, as a semi-batch's dose).
    At constant level it is fed as fast as the still boils up, after distilling down to
    `down_to` of the charge. With portions (put and take) the still distils down to the level
    and adds a portion, in turn. The ends apply once the feed is in.
  - One batch is the hours of flows the recipe's batch size makes (else one hour). The boil-up
    time and the energy per batch scale with it; a 1/h boil-up does not.
  - `process propagate --fill` writes the cuts and the residue. A recipe `distil` operation
    takes the boil-up time `from:` the still.
  - **`cheme process stills [--case C] [--json]`** reports the basis (`rayleigh`, predictive;
    sourced when the relative volatilities, or for Raoult's law the volatility itself and every
    volatile component's vapour pressure, are `given` with a source: an ideal liquid declared
    `assumed`, as for a pair with an azeotrope, is not sourced), the charge, feed, cuts and
    residue (per batch and per hour, mole fractions), the boil-up time, the mean and peak duty,
    the energy per batch and the still's temperatures
    (`cheme.process-still-unsolved`, `-outlet`, `-note`).
  - `validate` reports `cheme.process-still`: ports, charge and feed, unknown components, and
    missing vapour pressures, relative volatilities or (for kW) heats of vaporization; without
    those otherwise it is info, no duty. The components it checks are those its inlets'
    compositions carry at a non-zero amount (an inlet's template, while it has none, only as an
    info: needed only if the charge holds them). A `heat_of_vaporization`
    below 2000 kJ/kmol is a warning: NIST gives kJ/mol, times 1000.
  - A residue end's direction is the target's: the key falls to a target below its share, or
    rises to one above it; a target it never reaches is an error, not an empty cut. Each cut's
    energy is its own. An end at a time with the recipe's batch-size stream downstream of the
    still is circular and refused, unless every boil-up up to that end is specific (1/h); only
    the boil-ups the still runs at count (a still's own `boilup` that every cut replaces, with
    no feed, is not used: no unit or heat_of_vaporization check, no hours in a fingerprint).
    An end at a share distilled, a time or a purity that the still cannot reach before it
    boils dry is an error at the first step that shows it, without waiting for the pace
    check below ("boils dry before its end"): at most the volatile content left is still
    distilled (by mole, or its mass), in at most its kmol times the most s per kmol of any
    vapour of it (the largest heat of vaporization for kW, the heaviest molar mass for kg/h,
    2000 K for m3/h) times R + 1 at the highest reflux (`ratio`, or `maximum_ratio`), and a
    cut's mean share of its purity key falls no lower than its key over the cut and all the
    other volatile content left (by mole, or by mass). That floor rises from 0 as the cut
    fills, so a purity end below it is refused only once the floor passes it, not at the
    cut's first step (a 50/50 binary's cut without a column at 0.4 of its light component with
    45 % of the volatile content left, at 0.499 with 3 %). A still
    whose boil-up crawls near empty (a column on a trace it enriches, before an end next to
    its dry point) is checked after 500 small steps in a row: if at that pace its end is not
    reached within 10^6 steps in all, it stalls (`cheme.process-still-unsolved`: the volatile
    kmol left, and to end the cut earlier): an error, not a hang, though it can take minutes.
    A volatile component falling 1000-fold in that run is progress, and an amount below 1e-100
    of the charge and feed is taken as gone.
  - `still.heat_up: true` (raoult, ADR 0063) adds the charge heated from its inlet
    temperature to its bubble point to the duty (`charge heat-up`), and a swap's feed warmed
    from its inlet temperature to the still's as it mixes in (`feed heat-up`, the still's
    temperature averaged by the kmol fed); `process stills` then gives the duty's terms, the
    whole energy per batch on the duty's basis (`total_energy_kWh_per_batch`, beside the year
    average; `energy_kWh_per_batch` stays the latent heat) and assumptions that say what the
    duty holds.
  - `still.heat_up_time: true` (raoult, ADR 0068): the duty's terms besides the boil-up (the
    charge's and a swap's feed's heat-up, a recipe vessel's metal) take time at the still's own
    boil-up's heat input, `t = (Q_whole - Q_boil-up) / (Q_boil-up / t_boil)` over the cuts
    collected at it (a boil-up in kW: its value; a cut's own boil-up, a forerun the vacuum pump
    limits, limits the vapour, not the heating; every cut with its own: the mean over the whole
    boil-up); `process stills` gives `heat_up_time_h` and `time_h` (the boil-up's and the
    heat-up's), and a recipe `distil` `from:` the still takes both. A term that gives heat back
    takes no time; the metal is timed from its start to the still's first bubble point `T_0`
    and on to its end only above `T_0` (`C_m [(T_0 - T_start) + max(T_end - T_0, 0)]`), so a
    vacuum ramp that ends below the charge still times the metal's heat-up.
  - An end at a temperature (or any end) stops where the integrator found it (core#198: a
    re-evaluation of the bubble point there could fall short and report a dry still). Only a
    component the charge or the feed holds at a non-zero amount needs volatility data
    (core#214); a component only an inlet's template lists (before propagate) is an info.
  - Not modelled: activity coefficients (azeotropes), the content's sensible rise while it
    boils (and the heat-up without `heat_up`), losses, constant level by volume. `process
    simulate` does not couple it.
    Qualified against Rayleigh's binary closed form, the Rayleigh integral for benzene-toluene
    and the constant-level swap's closed form (`tests/test_batch_still.py`).
  - **Batch rectification** (ADR 0061): `column: {stages: N, reflux: constant, ratio: R}` puts
    a column of N theoretical stages (the still included) with a total condenser on the still,
    on Diwekar's batch shortcut: at each point of the path the distillate follows from
    Hengstebeck-Geddes at the Fenske index, Underwood's minimum reflux (the still's liquid as a
    saturated-liquid feed, the root between `heavy_key`, by default the next less volatile
    component of the charge after the distillate's key, and the next lighter one; without a
    key, the keys at each point: the most volatile component above 1 % of the still's vapour
    and the next less volatile one, so a main cut after a forerun separates the next pair; a
    lighter trace takes at most `(R + 1)` times its share of the still's vapour) and
    Gilliland's correlation (Molokanov); no holdup, constant molar overflow, the relative
    volatilities at the still's bubble point. `reflux: constant_distillate, distillate: {key, mole_fraction},
    maximum_ratio` raises the reflux to hold the distillate, then stays at the maximum (a note
    with where; another note when the key is not the charge's most volatile component).
    `minimum_reflux_factor: f` with a `distillate` designs the column at the start instead of
    `stages` (R = f Rmin, the stages from Gilliland). `(R + 1)` moles boil up per mole distilled:
    the boil-up time and the reboiler's energy are `(R + 1)` times a one-stage still's for the
    same distillate. N = 1 is Rayleigh's still; R -> infinity the Fenske limit. The basis is
    `batch-shortcut` (predictive); `process stills` adds the column's reflux (start, end, along
    the profile), each cut's mass fractions and recovery, and the condenser's duty. Rules: a
    column's `distillate` or `heavy_key` that is no or a non-volatile component, a purity key
    that is no component (errors). Qualified against Rayleigh (N = 1), the Fenske limit,
    Underwood's binary closed form, the constant-distillate balance and rigorous
    plate-to-plate binary and ternary columns (a forerun and a main cut) as a bound
    (`tests/test_batch_rectification.py`; Diwekar's published examples and DWSIM: core#195); worked
    example `examples/process-batch-rectification`. One reflux policy for all cuts; the column
    and its condenser are not sized.
- **Model duties on energy streams** (ADR 0059, `domains/process/duties.py`): an isothermal
  `reactor: batch` or `semibatch`, a `still:`, a `crystallizer:` with `energy:` and a
  conversion step (`reactions:` with conversions or a `selectivity:`) give the heat they
  exchange per hour of the flowsheet's flows (the year average), and `process propagate
  --fill` writes it as the `duty` of their energy stream, `calculated` with a fingerprint.
  - The heat: a batch's is minus the heat its reactions release over the batch plus each dose
    warmed to the batch's temperature (and a dosed gas passing to the vent; the doses' heat of
    solution, less what the vent's vapour takes back, the charge's heat-up with `heat_up` and
    the vessel's metal, ADR 0063; the latent
    heat of the vent's vapour and a returned condensate warmed back, ADR 0062), and its vent
    condenser's heat out on that condenser's own stream (`batch.vent.condenser.energy_port`,
    never the jacket's); a still's the latent heat of its distillate, `sum dHvap_i D_i` (with
    a column the reboiler's `(R + 1) D lambda`, and its condenser the same latent heat out on
    its own stream: `still.condenser_port`, else, with a column, the still's one heat stream
    out, the reboiler's then its one heat stream in; ADR 0061; the condenser takes no heat-up
    or metal).
    The two condensers differ: a still's (total, the boil-up's latent heat) and a batch's
    vent condenser (partial, on the vent gas); each writes its own stream;
    a crystallizer's its lumped duty; a conversion step's (batch or continuous)
    `sum xi dHr` at the heats' own `heat_of_reaction.temperature` with every inlet brought to
    it and every outlet from it (`liquid_heat_capacity`, or the ideal-gas enthalpy for a stream
    said to be vapour), or `H(out) - H(in)` of ideal gases for a gas-phase step (no stream said
    to be liquid or two-phase, no liquid or mixed reaction) whose components all have
    `ideal_gas` data; less the work `W` its other energy streams bring in (their duties, signed
    by direction: an electrolyser's DC power, a pump's work; one without a duty leaves it
    unknown). Heats at different temperatures, or a component vapour on one side of the step
    and liquid on the other, leave it unknown; without the data nothing.
  - The stream: the one at the node's `energy_port: PORT`, else its one heat stream (an energy
    stream to or from a steam, hot-oil, fired-heat, cooling-water, air-cooling or refrigerant
    utility; electricity, fuel and terminals without `utility:` are not heat, and a stream to or
    from another block or step is heat only where `energy_port` names it). A duty is positive in its stream's direction: a stream out of the step carries
    the heat removed. A model whose heat flows against the stream is a warning, never a
    negative duty. A flow-style stream (`{id: Q1, ...}` on one line) is written in place.
  - A given or assumed duty is never overwritten: it is compared, and one beyond the
    flowsheet's relative tolerance is `cheme.process-duty` (warning, naming both values) in
    `process propagate --fill` and `--check` and in `validate`; two models giving one stream
    different duties are a warning naming both (neither written); several heat streams,
    missing data or an adiabatic batch are `cheme.process-duty` (info, propagate only). `validate` reports
    `cheme.process-energy-port`: a port that is no energy port of the node (error), or one on
    a node no model gives a duty (warning). `process reactors` shows a batch's or conversion
    step's duty, its terms and its stream where the ideal-gas duty is `?`, `process stills`
    the year-average duty. A dryer keeps its own `energy.port` check
    (`cheme.process-dryer-duty`).
- **Reaction evidence**: `process/reaction-evidence.yaml` (schema `cheme/reaction-evidence/v1`,
  `cheme schema reaction-evidence`, skills `reaction-evidence-search` and `route-selection`)
  records the searches, sources, observations, candidate routes, conflicts and the model basis
  behind the reactions, before any flowsheet. `cheme validate` checks it (`cheme.evidence-*`:
  references, DOIs and patent numbers, a location for every reported value, no numbers from a
  source only seen as a snippet, units, the yield basis, duplicate evidence, kinetics validity,
  an explicit model basis whose reactions `reactions.yaml` declares). **`cheme chemistry
  evidence [--json]`** prints the route comparison. Worked example:
  `examples/reaction-evidence-ethyl-acetate` (three routes to ethyl acetate from papers and
  patents).
- **The reaction library**: **`cheme chemistry library [ID] [--add]`** lists, shows and adds 23
  industrial processes (ammonia, methanol, reforming, shift, methanation, ethylene oxide,
  sulfuric and nitric acid, Claus, Fischer-Tropsch, hydrotreating, styrene, acrylonitrile,
  propylene oxide, cracking, vinyl chloride, formaldehyde, maleic anhydride, cumene,
  ethylbenzene, MTBE, HCN): components with chemicals' ideal-gas data and critical constants,
  main and side reactions, typical catalysts and windows, with sources
  (`domains/process/data/library/`, built by `scripts/build_reaction_library.py` from
  `scripts/reaction_library.yaml`). `--add` appends to the plant's process files, keeping their
  comments. Each entry's `model_basis` says which reactor model its own data support, checked
  against the data: `equilibrium` (8 entries: every reaction reversible, gas phase, ideal-gas
  data over the window; an equilibrium limit, not a kinetic model) or `stoichiometry_only` (15
  entries: no conversion, selectivity, equilibrium basis or rate law); `conversion_selectivity`
  and `kinetic` need sourced conversions or rate laws no entry has yet. The listing, `--add`
  and `GET /api/library` show it: an entry brings chemistry, the reactor model is chosen
  separately.
- **Microkinetics**: a reaction's `mechanism:` lists its elementary surface steps (adsorbates
  `X*`, free sites `*`, per-site rate constants or sticking coefficients). **`cheme chemistry
  microkinetics ID -T K -p ID=BAR ... [--cantera] [--export FILE]`** solves the mean-field steady
  state (coverages, TOF, degree of rate control per step, apparent activation energy, orders;
  `domains/chemistry/microkinetics.py`), checks it against Cantera (extra `cantera`) and writes
  Cantera's YAML input.
- **Rate laws from data**: `experiments/kinetics/*.yaml` (schema `cheme/kinetic-data/v1`)
  holds rates of a reaction; **`cheme experiments fit-rate FILE [--form lhhw] [--reverse]`**
  fits a power law (linear least squares on ln r) or an LHHW law (Levenberg-Marquardt), each
  parameter with its 95 % interval; **`cheme experiments sample-mechanism`** makes such data
  from a mechanism, to lump it into a rate law for a fixed bed. Mechanism steps may give DFT
  `energies:` (transition state theory) instead of rate constants.
- **Electrochemical cells and measurements**: **`cheme process cell [--json]`** evaluates the
  cells of `process/cells.yaml` (schema `cheme/electrochemical-cells/v1`): the Faraday
  balance, power, heat duty and kWh per kg, from specified values or, with
  `performance: measured`, from a measured series looked up at the cell's current density
  (refused outside its range, never extrapolated), and an optional membrane block (water
  dissociation efficiency, co-ion fluxes, anolyte hydroxide deficit;
  `docs/framework/electrochemical-cells.md`). `experiments/electrochemistry/*.yaml` (schema
  `cheme/electrochemical-measurements/v1`) holds a measured series with replicates;
  **`cheme experiments electrochem FILE [--json] [--plot DIR]`** computes per replicate and
  point (mean, sd, n) the Faradaic efficiency of each product from the outlet flow and mole
  fractions (standard conditions required), partial current densities, the water dissociation
  efficiency from the anolyte titration, power, heat and the charge and carbon balances, and
  writes polarisation, efficiency, partial-current and water-dissociation plots only for the
  inputs that support them (`docs/framework/electrochemical-measurements.md`).
- **Electrolysis duties**: `process/duties.yaml` (schema `cheme/electrolysis-duties/v1`)
  states dynamic duties of a cell of `process/cells.yaml` against its anolyte reservoir: a
  current, power or on/off schedule, the reservoir (volume, composition, anolyte model by id,
  optional CO2 degassing), dosing on a pH trigger or continuous, bleed, make-up water, the
  stated pH threshold (a design criterion) and the horizon.
  **`cheme process duty [IDS] [--json] [--plot DIR] [--compare ID,ID --co KG]`** integrates
  them (Dormand-Prince 5(4) with events): the voltage, Faradaic efficiency and water
  dissociation efficiency at each instant from the measured series (never extrapolated: the
  transient stops at the first exit from the measured range and the time outside is summed)
  or the specified cell; pH, inventory, product, charge, energy, dosing and bleed over time;
  the time to the specified pH threshold; `--compare` compares duties at equal delivered
  product; `--plot` writes aligned time plots and an operating map (WDE x reservoir volume)
  with the measured WDE points apart from the simulated values. The first anolyte model is
  `well-mixed-carbonate` v1 (equilibrium carbonate speciation on a concentration basis;
  `docs/framework/electrolysis-duties.md`). A duty a stack of `process/cells.yaml` names runs
  at the arrangement that stack is sized at (`cheme.duty-arrangement`), as in
  `cheme process stack`, and so does a duty that names the stack itself (`stack: STK-1`, a
  comparison duty on the skid's hardware; another `cells_in_series` or `stacks` on it is an
  error). The totals are split by route (the cation and carbon dosed, bled and through the
  membrane, the initial inventories), so both balances close on their own.
  `reservoir.size: to_horizon` (optional `time_margin`) reports the exact volume that reaches
  the horizon, `V0 Q(target) / Q*`, for a duty without dosing, bleed, make-up or degassing at
  one operating point, raised to keep a stated minimum inventory and the anolyte model's
  validity to the target (`required_volume`, `limited_by`; otherwise `cheme.duty-size`,
  error).
- **Electrolyser stacks**: the optional `stacks:` section of `process/cells.yaml` (same schema,
  optional fields only) names per stack design a cell, the product duty, the electrical
  limits, the assumed envelope per cell, clearances, the replacement interval and the skid
  equipment a duty sizes. **`cheme process stack [IDS] [--json] [--write]`** sizes it at the
  cell's operating point (refused outside its measured or declared range, never
  extrapolated): `A = n F Ndot / (nu FE j)`, `ceil(A / A_cell)` cells, at most
  `floor(U_max / U)` in series per stack, the stacks, the reconciled voltage, current, DC
  power, output and margin, kWh per kg, the envelope and footprint; and the reservoir, dosing
  and bleed tanks and the recirculation and dosing pumps' inputs from the named duty, run at
  that arrangement (a duty at another current density or of another cell, or not feasible,
  gives none: `cheme.stack-duty`); a dosing tank's `refill_interval` and a bleed tank's
  `empty_interval` size it for the most dosed or bled in any such interval, with the fills or
  emptyings per campaign; `product.recovery` (default 1) sizes the stacks for the product
  formed, rate / recovery, and reports formed and delivered output; a duty with
  `reservoir.size: to_horizon` gets its reservoir volume written into `process/duties.yaml` by
  `--write`. Without `--write` it writes nothing and reports what
  differs (`cheme.stack-outdated`); `--write` edits the equipment-list `dimensions` in place and
  the pumps' datasheet `type_specific` (the recirculation pump's with its end points
  `suction_from` and `discharge_to`), never over a value written by hand
  (`cheme.stack-kept`), from which `cheme layout build` and `cheme datasheets draft`/`fill`
  take them; a value it wrote that is no longer given is cleared, a tag two stacks name is
  written by neither, and `--write --json` adds `written` (file -> tags). The LCA does not read
  the stacks: their power and dosing go into the flowsheet streams by hand. Exit 1 on an error finding (a `process/cells.yaml` that does not follow its
  schema among them, its findings printed), 2 without the file or stacks or for an unknown id
  (`docs/framework/electrolyser-stacks.md`, ADR 0044, skill `skid-design`).
- **`cheme chemistry kinetics -r ID=NAME ... [-p ID=NAME ...] [--rmg-endpoint URL]`** reduces
  the NIST (and RMG) records of an elementary gas-phase reaction to one Arrhenius record and
  prints it as a `rate:` entry (network). An entry that is a formula and also another
  compound's SMILES (`CO`, `NO`, `O`, `C`) is refused as ambiguous: give a name (`carbon
  monoxide`), an explicit SMILES (`[C-]#[O+]`) or `smiles:CO` for the SMILES reading.
- **`cheme chemistry thermo NAME... [--fit LO,HI]`** (extra `props`) prints a component's
  `ideal_gas` entry from chemicals: ATcT formation enthalpy, entropy and Poling's Cp/R (to
  1000 K), or Cp/R fitted to thermo's ideal-gas heat capacity over LO to HI K.
- **`cheme process streams [--case C] [--md | --csv | --json]`** prints the stream table
  (value, unit and provenance per property, calculated values, stale ones marked) and the
  balances.
- **`cheme process propagate --fill | --check`** derives missing compositions and flows
  through steps whose streams determine them: pass-through classes (compressing, pumping,
  cooling, heating, filtering, transporting, flow control; heat exchanging with one stream in
  and one out) keep composition and flow, mixers combine, splitters keep the composition and
  split by `split: {outlet port: fraction}` (else the one missing outlet flow is the mass
  balance remainder), and a conversion reactor (a step naming `reactions:`, each with a
  conversion) converts its fraction of each key component's inlet flow; a crystallizer or a
  filter (`crystallizer:`, `solid_separation:`, below) fills its outlets; a batch,
  semi-batch, still, crystallizer or conversion step writes its duty on its energy stream
  (`energy_port:`, ADR 0059, below) and a given duty is compared (`cheme.process-duty`); a
  component separator (`recovery:`, below) splits each component of its inlets by its given
  fractions. Other separators, and reactors without conversions, are only checked, never
  solved. Values are
  `calculated` with source and input fingerprint, never overwrite given or assumed ones, and
  are reported stale when an upstream value changes. Run it before `props --fill`. `--json`
  prints the run as an adapter result (`cheme/adapter-result/v1`, `cheme schema
  adapter-result`): `converged` when every node is solved (and every torn loop converged), else
  `not-converged` with the unsolved nodes in `messages` and `units`; `iterations` the sweeps
  through the flowsheet (with tears: the loop's iterations); per stream the derived values and
  those written (`filled`). It writes no file of its own.
  - **Recycles** (ADR 0060). A loop is torn at a stream named in the flowsheet's `tears:`, one
    per loop, with an optional first guess (default an empty stream):

    ```yaml
    tears:
      - stream: S11
        initial: {flow: 140, unit: kg/h, basis: mass_fraction, composition: {H2O: 0.6, NAOH: 0.4}}
    convergence: {method: wegstein, max_iterations: 100, tolerance: {abs: 0.001, rel: 1.0e-5}}
    ```

    Propagate sets each tear to its guess, sweeps the flowsheet, and compares what the loop
    gives back with the guess, per component in kg/h. It repeats by successive substitution
    (`method: substitution`, optional `damping` below 1) or Wegstein's method (the default; q
    per component bounded to [-5, 0]) until every component and the total are within
    `convergence.tolerance` (default: the flowsheet's), at most `max_iterations` times (default
    100). The iterations round nothing; the values written come from one more sweep from the
    converged guess, rounded to six digits as every propagated value. A tear
    value is `calculated`, with source `recycle <node> from <inlets> (tear, <method>)`, and is
    fingerprinted on the loop's inputs, not on the iterate. The iterations always start from
    `initial`, so a converged plant derives the same values again and is not stale. A given or
    assumed flow or composition of a tear stays fixed (a design specification), and only the
    other is iterated. `cheme.process-recycle` is info for a converged loop (iterations, worst
    residual against its tolerance). It is a warning for a loop that does not converge (with
    its residual), or that does not close because the guess leaves the tear's source without
    values: an empty guess can leave a splitter remainder negative, or a still, reactor or
    filter with nothing to work on (give a closer `initial`). An open tear never moves, so the
    iterations stop as soon as the other tears converge. Nothing that depends on an unconverged
    loop is written, and `--json` is then `not-converged`; a tear left out of the iterations
    (below) does not change the status. `cheme validate` reports a tear that cannot be iterated
    as `cheme.process-tear`: an unknown, energy, feed or product stream, one named twice, or a
    guess in undeclared components or flow units or whose fractions do not sum to 1 (within
    0.001) are errors; a tear whose flow and composition are both given is a warning. The
    tolerance applies to the residual: a loop whose gain is near 1 stops up to
    tolerance / (1 - gain) from its fixed point, so tighten it there. Tear each loop once: two
    tears in one loop converge, but only as fast as plain substitution (each tear's slope is 0
    for Wegstein). Tears are declared, never chosen.
    `examples/process-purge-loop` is a loop reactor with a recycle split whose steady state is
    analytic (`tests/test_recycle.py`).
  - **Component separators** (ADR 0070). A block or step without another model (reactions,
    still, crystallizer, filter, dryer) and of a separating or generic class may give its split:

    ```yaml
    recovery:
      outlets: {dry: {TBA: 0.99, H2O: 0.0074358}}   # outlet port -> component -> share of its inlet flow
      provenance: assumed
      source: "scripts/makeup_drying.py (D-004)"
    ```

    Each listed port takes its share of each component's inlet flow (all material inlets
    together; a component it does not name: none); one material outlet may be left out and
    takes the rest. Propagate writes the outlets' flows and compositions (`separator <node> from
    <inlets>`); temperatures and pressures stay as given. The split is specified, not
    predicted. `cheme validate` reports a `recovery:` that does not fit as `cheme.process-recovery`
    (error): beside another model, on a mixer, splitter, pass-through or reactor class or on a
    block with steps inside, a port that is no material outlet, two outlets left out, an
    undeclared component, a fraction outside [0, 1], or a component's fractions summing beyond 1
    (with every outlet listed: to other than 1).
  - **Design specifications** (ADR 0070). `specs:` adjusts one variable per spec until a stream
    target is met, solved together with the tears:

    ```yaml
    specs:
      - id: rate
        vary: {stream: S4, initial: 70, with: {S1: 1.89688, S3: 0.26124}}  # a feed; followers at fixed ratios
        target: {stream: S24, quantity: annual, value: 1000, unit: t}         # hours: the recipe's
        provenance: given
        source: "design basis: 1000 t/a (D-002)"
      - id: purge
        vary: {node: X1, port: purge, initial: 0.1}                           # a splitter outlet
        target: {stream: S2, component: C3, quantity: fraction, basis: mass, value: 0.1}
        provenance: assumed
    ```

    `vary` is a feed stream's flow (`unit`, default `units.flow`; `low`, `high`; `with:` the
    feeds that follow it, stream -> ratio, so charge ratios are kept) or the fraction of a
    splitter's inlet to an outlet its `split:` leaves out (`low`/`high` within [0, 1]). The
    varied flows must not be given or assumed: they are written `calculated`, source `spec <id>
    (<target>)`. `target` is a stream's (or one `component`'s) `flow` (a flow unit), `annual`
    amount (`t` or `kg` per year: the flow times `hours`, default the recipe's
    `hours_per_year`), `ratio` to `per: {stream, component}` or `fraction` of the stream (`basis:
    mole`, the default, or `mass`); `tolerance` is relative (default 1e-6), `cases` the cases it
    holds in (default all). Propagate solves the tears' component flows and the variables
    together by Newton's method with a finite-difference Jacobian kept current by Broyden's
    update (the recycle's method then reads `broyden`); without tears, one sweep per step. The
    values written come from one more sweep at six digits, so a target reads within the six
    digits written. `cheme.process-design-spec` is info per spec met (the variable, a split's
    fraction, the target reached, the sweeps), and a warning for one that cannot be met (the
    target does not depend on the variable, has no value, lies beyond the bounds (a variable
    held at a bound, or at a bound where the target no longer moves, such as a purge of 1 that
    empties the loop torn after it), or is not met
    in `convergence.max_iterations`): nothing that depends on the specs or the tears is then
    written, and `--json` is `not-converged`. `cheme validate` reports a spec that cannot be
    solved as declared as `cheme.process-spec` (error): an id or variable named twice, an
    unknown case, stream, component or unit, a varied stream that is no feed, is a tear or has
    a given or assumed flow, a split of no splitter or of a port its `split:` fixes, splits that
    leave a splitter no outlet for the remainder (its `split:` and the specs of a case fix every
    outlet), a split's `low`, `high` or `initial` above 1, an initial value outside the bounds, an annual target without hours, a flow target on its own
    variable. In a batch plant the flowsheet holds year averages: a spec on the annual product
    sets the flowsheet's rate, and the recipe's batch size must make it, `batch = rate x
    cycle(batch)`, where the cycle depends on the batch (jacket and dosing times, a still, a
    filter or a dryer). `cheme.recipe-basis` names the batch size that closes it and its cycle,
    or, when the cycle grows about as fast as the batch, the most the batches tried made (the
    train's capacity); set it in `process/recipe.yaml` and run `--fill` again.
    `examples/process-design-spec` is a loop reactor with a component separator whose fresh
    feed and purge are solved for a product rate and an inert level, against their closed form
    (`tests/test_design_spec.py`).
- **`cheme process props --fill | --check | --coverage`** (extra `props`) calculates phase,
  vapour fraction, molar mass, density and enthalpy, only inside the validated range of the
  process's property package (`property_method.package` in `materials.yaml`, else the package
  covering the most streams; `--coverage` lists it and, per stream, whether it is covered or
  why not, writing nothing). Package `air-pr-chemsep`: N2, O2 and Ar; 77 to 315 K; vapour 100
  to 3200 kPa(a); liquid and two-phase 100 to 600 kPa(a). Peng-Robinson (thermo, ChemSep kij)
  for equilibrium and vapour density, COSTALD for liquid density, enthalpy on ideal gas at
  298.15 K and 101.325 kPa. The references (NIST WebBook equations,
  `tests/data/process_props_references.yaml`) pass within 0.5 % (gas density at ambient
  pressure), 1 % (gas density up to 31 bar), 1.5 % (liquid density) and 0.3 K (saturation
  temperatures). Package `syngas-pr-vapor`: H2, N2, Ar, CH4, CO, CO2 and their mixtures, NH3
  pure and in mixtures with H2, N2, Ar and CH4 up to mole fraction 0.25 (ammonia synthesis loop
  gas), vapour only, in per-component temperature-pressure boxes within 250 to 1000 K and 100 to
  30000 kPa(a), benchmarked by `tests/test_property_packages.py` against CoolProp's reference
  equations of state, GERG-2008 mixtures and the Neumann et al. (2020) ammonia mixture models,
  and against measured densities (density 2 % pure, 3 % mixtures; enthalpy differences 300
  kJ/kmol). Package `water-methanol-pcsaft-liquid` (extra `saft`: feos, PC-SAFT with the Esper
  et al. 2023 parameters and the Rehner et al. 2023 `k_ij`, ADR 0064): water and methanol,
  liquid density only, within 1 % of the reference equations (pure) and of measured densities
  (Coquelet et al. 2005, Safarov et al. 2004; `tests/test_property_packages_pcsaft.py`):
  methanol 240 to 420 K, pure water 360 to 550 K, mixtures to 420 K with water up to mole
  fraction 0.75 (0.64 below 323.15 K), to 60 MPa(a). A state is liquid at 1.2 times PC-SAFT's
  bubble pressure or above (its bubble pressures miss measured ones by up to 19 %); nearer it,
  only with the stream's phase given or assumed `liquid`. It writes no enthalpy or exergy and
  refuses vapour, two-phase, VLE and viscosity. A state outside the range, another component, a pressure that is
  not absolute and positive, solids, or a phase the flash contradicts is refused with a finding,
  and nothing is written. `--fill` never overwrites given or assumed values, records the method,
  its package versions and range in `materials.yaml`, and stores an input fingerprint with each
  calculated value; when an input changes, `validate` reports `cheme.process-calculated-stale`
  until it is recalculated (a refused recalculation keeps the old values, marked stale).
  `--check` recalculates and reports only (exit 1 on a warning); `--fill` exits 3 when it
  refused a stream and names the refused streams on its summary line. `--json` prints the run
  as an adapter result (solver `thermo` with its version and EOS; `not-converged` with the
  refused or uncalculable streams in `messages`; `iterations` null, one flash per stream).
- **`cheme process simulate --fill | --check [--save x.dwxmz]`** solves the flowsheet in
  DWSIM. `process/simulation.yaml` gives the property package and what each step needs beyond
  its streams (every value with its provenance):

  ```yaml
  schema: cheme/simulation/v1
  kind: simulation
  property_package: Peng-Robinson (PR)
  specs:
    K1: {outlet_pressure: {value: 800, provenance: given}, efficiency: {value: 0.78, provenance: assumed}}
    E1: {outlet_temperature: {value: 308.15, provenance: given}}
  ```

  DWSIM runs in Docker: build the image once with `docker build --platform linux/amd64 -t
  cheme-dwsim:9.0.5 -f docker/dwsim/Dockerfile .` in this repository. Simulated streams get
  temperature, pressure, flow and composition (energy streams their duty) as `calculated`;
  given and assumed values are never overwritten, and a deviation from them is a warning. A
  duty is written only where its sign agrees with its energy stream's direction (heat added or
  power into the unit, heat removed or power produced out of it); otherwise, and for a
  component separator's energy imbalance, `cheme.process-sim-energy-direction` warns. Run
  `props --fill` afterwards for phase, density and enthalpy. Units: compressor, expander, pump,
  heater, cooler, valve, mixer, splitter, flash drum, heat exchanger, shortcut and rigorous
  column, and conversion, equilibrium and Gibbs reactors from the flowsheet's reactions (the
  specs each needs: `cheme schema process-simulation`); recycle loops are torn
  and solved iteratively. Rigorous columns take side draws, a partial or no condenser, no
  reboiler and a condenser-reboiler check (`examples/process-double-column`, an air separation
  double column). See `examples/process-simulation`
  and `examples/process-separation`.

  `simulator: idaes` in `simulation.yaml` (default `dwsim`; ADR 0039) solves the flowsheet in
  the optional IDAES backend instead: the worker runs in the Python `CHEME_IDAES_PYTHON` names
  (with idaes-pse and IPOPT; cheme-as-code never imports IDAES or Pyomo). Its scope is heater,
  cooler, valve, pump, mixer, splitter, flash, conversion reactor and recycles (compressor and
  expander with Peng-Robinson), property packages `IDAES ideal VLE` and `IDAES Peng-Robinson`
  for benzene, toluene, hydrogen and methane; anything else is
  `cheme.process-sim-backend-unsupported` (error) at translation, and neither package is
  benchmarked (`-sim-method-unbenchmarked`, info). Values carry the source `cheme process
  simulate: IDAES <version>, <property package>`; the run record also names the solver
  (IPOPT). See [docs/framework/idaes.md](docs/framework/idaes.md) and
  `examples/process-hda-idaes`.

  `--fill` also records the run in `process/simulation-run.json` (generated, committed with the
  flowsheet; schema `cheme/simulation-run/v1`, one entry per case): simulator and version,
  property package, when, the model fingerprint and the input files' commit and fingerprints,
  convergence and `status`, iterations (the flowsheet passes DWSIM made: one per solve without
  a recycle, else the iterations of the slowest recycle), messages, per unit its
  status (simulated, or excluded with the reason), convergence, results and warnings, per stream
  the simulated values and which of them it holds. A run that does not converge is recorded too
  (no stream value is written). `--check` and `cheme validate` report a record from other
  inputs (`cheme.process-sim-run-stale`, warning; translating needs no simulator), `--check`
  also a case without one (`-sim-run-missing`, info).
  `GET /api/simulation` serves it. Each entry is an adapter result (`cheme/adapter-result/v1`)
  in the file's keys: `simulator` (with `method`, the property package) is its solver.

  The property package must be one the worker runs (`cheme process methods`; another is
  `cheme.process-sim-property-package`, error). `method_selection: {facts: {...}}` records the
  facts of the thermodynamic model selection; the translation re-evaluates them and flags a
  package they do not recommend (`cheme.process-sim-method-not-recommended`, warning) unless
  `method_selection.substitution` records why it is accepted (`-sim-method-substituted`,
  info); incomplete facts are `-sim-method-selection`.
- **`cheme process methods [--json]`** prints the supported-method contract
  (`domains/process/thermodynamics/methods.yml`): for each model the selection tree can
  recommend, whether `cheme process phase` (thermo) and `cheme process simulate` (DWSIM) run
  it, else the nearest model they run as an explicit substitution with what it loses, or none.
  Coverage decisions: electrolytes, solid equilibrium and petroleum pseudocomponents are
  unsupported on both routes (ions, unidentified components and, with water, the salts, acids
  and bases `electrolytes.yml` lists, and any compound of an alkali or alkaline-earth metal,
  are refused by the phase route and by the simulation
  translation, `cheme.process-sim-electrolyte`; the phase route has no solid phase).
  Electrolytes are `limited`: the electrolyte route runs Pitzer's liquid model for aqueous NaCl
  only (`cheme process electrolyte`, below). The phase route claims no application range; the simulation
  route claims one only where a test benchmarks it (today Peng-Robinson (PR) for N2/O2/Ar and their
  mixtures, Soave-Redlich-Kwong (SRK) for each of them alone, NRTL for the ethanol + water
  bubble points at 101.3 kPa(a) against measured VLE data, on DWSIM 9.0.5,
  `methods[].simulation.application_range`, checked by `cheme maturity`).
- **`cheme process phase COMPONENT... (--model EOS | --liquid M --vapor V) [--z x,y]
  [--temperature T --pressure P] [--accept-zero A:B] [--check] [--json]`** (extra `props`)
  reports per binary pair whether the model's interaction parameter is `sourced` (with its
  source: thermo's ChemSep PR, NRTL and Wilson tables, the fetched ChemSep SRK file, thermo's
  UNIFAC group parameters), `missing` (the calculation uses zero) or `accepted_zero`
  (`--accept-zero`); with a temperature and pressure it also runs the flash. `--check` exits 1
  when a pair is missing. Python: `thermodynamics.coverage.interaction_parameter_coverage`.
- **`cheme process electrolyte --temperature T --pressure P (--molality M | --mass-fraction W |
  --species Na+=M,Cl-=M) [--system NaCl-H2O] [--json]`** (extras `cantera` and `props`) runs a
  qualified aqueous electrolyte system of the versioned contract
  `domains/process/thermodynamics/electrolytes.yml` (ADR 0027): today NaCl-H2O, through Pitzer's
  equations in Cantera's `HMW-electrolyte` phase with the Silvester and Pitzer (1977) parameters,
  complete dissociation into Na+ and Cl-. It prints the mean ionic activity coefficient
  (molality scale), the osmotic coefficient, the water activity and the water vapour pressure
  over the solution (a_w times the IAPWS-95 saturation pressure), the relative apparent molar
  enthalpy phi_L of NaCl (heats of dilution), the species, element and charge closure, and the
  provenance (solver version, parameter source, tolerances, benchmark). The claim:
  273.15-373.15 K, up to 1000 kPa(a) and 6 mol/kg, phi_L from 313.15 K, one liquid phase;
  `tests/test_electrolytes.py` checks it against Hamer and Wu (1972) and Pitzer, Peiper and
  Busey (1984) within 2 % in gamma+-, 0.01 in phi and 0.03 RT in phi_L. Anything else is refused
  with exit code 3 and a rule id (`cheme.process-electrolyte-range`, `-unsupported` for another
  ion, `-charge-balance`, `-phase` for a boiling solution, `-system`), never computed with a
  neutral-fluid model. A brine in a mass balance with specified splits (an inventory) needs no
  property model; its properties come from this route or stay unclaimed. Python:
  `thermodynamics.electrolytes.electrolyte_state`.
  A converged run is also checked for energy, independently of the duty balance DWSIM closes
  itself; the record keeps the audit under `energy`. Exchangers: the hot and cold composite
  curves from the solved temperatures and duties (counter-current, constant heat capacity flow
  per stream) give the least approach; a crossing is `sim-temperature-cross`, an approach below
  `min_approach` (in `simulation.yaml`, or per exchanger spec) `sim-exchanger-approach`; a
  stream that changes phase is `sim-exchanger-zones` (info: no zone temperatures, so the
  internal approach is not checked). Utility levels: a duty whose energy stream comes from (or
  goes to) a terminal with `category: utility` and `utility: {kind, supply_temperature,
  return_temperature, min_approach}` is checked against those temperatures
  (`sim-utility-level`). Enthalpy closure: per unit and for the simulated plant (boundary
  streams, heat, shaft work) from DWSIM's stream enthalpies, within an explicit tolerance
  (`sim-energy-unbalanced`). Reactors (conversion, equilibrium, Gibbs, kinetic_pfr) close on a
  heat-of-formation basis: DWSIM's enthalpy flows plus `sum (n_out - n_in) dHf_298` of the
  reacting components, on DWSIM's own formation enthalpies (its database, which its reactor
  duty takes), so the closure tests the simulation's energy conservation. Verified live
  (DWSIM 9.0.5): the reference state (each component's ideal gas at 298.15 K = 0, no
  formation enthalpies) for Peng-Robinson, PR78 and SRK, not for NRTL; the duty reproduced
  within 1e-3 kW for vapour ammonia synthesis at 10 bar (conversion, equilibrium and Gibbs
  reactors under Peng-Robinson; the conversion reactor under PR78 and SRK). The project's
  formation enthalpies are compared with DWSIM's separately (`sim-formation-data`): a warning
  where values declared in materials make a reaction heat that differs by more than 1 % of it
  (`predictive.formation-data` then fails); a smaller nonzero difference, chemicals' fallback
  values and missing values are info and recorded limitations, with each component's
  difference in kJ/kmol (ammonia: -45558 kJ/kmol in ATcT, -45898 in DWSIM, 0.74 % of the
  synthesis heat). Another package and units
  with an unestablished duty sign (a column top without condenser) are
  `sim-energy-unsupported`, never a number. With `simulator: idaes` the record's
  `energy.reference` states IDAES's basis (formation enthalpies included,
  `formation_enthalpy_included: true`) and a reactor's closure is `sim-energy-unsupported`
  ([idaes.md](docs/framework/idaes.md)). A component separator (a specified split) conserves
  no energy: its imbalance is stated, not judged (`status: stated`, `imbalance_kW` = enthalpy
  out minus in from the solved streams, positive: heat the unit would have to take in; DWSIM's
  `EnergyImb` is recorded with its observed sign, `simulator_convention`, and not relied on),
  and the plant closes with it as a stated residual (`stated_kW`; `sim-energy-stated`, info,
  beyond the tolerance; not a utility; ADR 0038). Every duty
  is classified once as hot or cold utility, power, or heat recovered between process streams
  (process-to-process exchangers, condenser-reboilers), which is never also counted as utility.
- **`cheme process extract [UNIT] [--systems] [--json]`** (extra `props`) solves each extractor
  of `process/extraction.yaml` (schema `cheme/extraction/v1`, `cheme schema process-extraction`):
  a feed and a solvent feed through `stages` countercurrent equilibrium stages at one
  temperature, NRTL from thermo with a bundled LLE system (`system:`, listed by `--systems`) or
  sourced parameters for every pair (`model:`). It prints the raffinate and extract, solute
  recovery, solvent loss, distribution coefficient and selectivity, the component closure and
  `qualification` (`qualified` only for a bundled system inside its benchmarked range; the
  bundled water + 1-propanol + n-butyl acetate system is benchmarked against Costa et al. 2009
  at 323.15 K). Refused (exit 1, a finding with its line): no two-phase region, a missing pair
  (never taken as zero), a temperature outside the parameters' range. Isothermal, no energy
  balance; solvent regeneration is a separate unit; the flowsheet keeps a component separator
  citing the result. Writes nothing. Python: `separations.extraction`.
- **`cheme process energy [--case C] [--json]`** prints the energy balances of blocks and steps
  (stream `calculated.enthalpy` times molar flow against the energy streams crossing them,
  `cheme.process-energy-balance`, checked by `validate` in every case with stream states; a
  `calculated` enthalpy must be in kJ/kmol and a molar mass in kg/kmol, another unit is
  `cheme.process-unit` and leaves the balance not evaluable, never converted; a block holding
  a step without an energy stream whose duty is unknown is not evaluable; a reacting node
  needs `units.enthalpy_reference.state: elements` and values on that basis, else it is
  unsupported), the energy audit of the recorded
  simulation run, and the boundary gaps that leave TEA and LCA inventories incomplete:
  steps that exchange heat or work without an energy stream (`cheme.boundary-utility-unassigned`),
  terminals without `category` (`raw_material`, `product`, `by_product`, `utility`,
  `wastewater`, `off_gas`, `solid_waste`, `emission`; `cheme.boundary-unclassified`) and utility
  terminals without levels. Exit 1 on a warning.
- **`cheme process pinch --dt-min X [--dt-min-source S] [--case C] [--include-constrained]
  [--json|--md] [--write]`** takes whole-plant pinch targets (problem table,
  `heat_integration/pinch.py`) from the case's recorded simulation run
  (`process/simulation-run.json`; it never runs the simulator: a missing, stale or unconverged
  run is an error, `cheme.process-pinch-run-missing`, `-run-stale`, `-run-not-converged`).
  dTmin is required, its source recorded (default `ASSUMED`). `heat_integration/streams.py`
  extracts one stream per thermal duty and side, each in one class: `utility` (heaters, coolers,
  flashes, condensers, reboilers, the process side of an exchanger against a utility terminal's
  stream such as a waste-heat boiler, whose steam is the utility and no second stream),
  `recovery` (both sides of a process/process exchanger, counted once; every side of a
  multi-stream exchanger; a condenser heating another column's reboiler), `constrained`
  (reactors, with the reason; out of the targets unless `--include-constrained`) or `excluded`
  (with the reason). Quality: the simulators report end temperatures only, so a stream is
  `linearised` (one constant-CP or isothermal segment; a phase change is not split at dew or
  bubble points, `cheme.process-pinch-stream-linearised`) or `insufficient` (excluded,
  `cheme.process-pinch-stream-excluded`). The reconciliation lists every thermal duty of the
  run from the units' results and checks the streams give each back within 0.1 kW + 1 %;
  heat left over is `cheme.process-pinch-reconciliation` (warning). It prints the **current
  utility demand** (of the targeted streams; recovered heat is not utility), the **theoretical
  minimum utility demand at dTmin** and the **theoretical energy-saving potential** (their
  difference; it ignores pressure, distance, fouling, control, safety and cost and is not a
  saving), the hot-side, cold-side and shifted pinch or a threshold problem, utility-use pinch
  violations (a utility heater below, a cooler above the pinch) apart from cross-pinch
  process-to-process transfer of the existing exchangers whose sides are all known (with their
  least approach), the stream table and the reconciliation. `--write` records settings, core
  version, the simulation run (model and content fingerprints), the inputs and the results in
  `process/pinch-run.json` (schema `cheme/pinch-run/v1`, one entry per case, generated) and
  refuses with exit 3 while the reconciliation has a finding. Exit 1 on an error or a warning,
  2 on invalid input (no or a negative `--dt-min`, an unknown case, `--json` with `--md`).
  Python: `heat_integration.report`; ADR 0040.
- **`cheme process furnace [ID] [--json]`** gives the energy basis of a solid-reaction furnace
  declared in `process/furnaces.yaml` (schema `cheme/furnaces/v1`; today limestone calcination
  only): the element balance, the product and off-gas composition (calcination and fuel CO2
  apart), the reaction enthalpy and the furnace energy closure (fuel LHV or electric power,
  sensible heat of feed, product and off-gas, moisture, losses) from the NASA condensed and gas
  data Cantera ships (extra `cantera`), never from a fluid flash. A measured fuel flow or power
  is checked (`cheme.furnace-closure`), an absent one solved; the degree of calcination is
  given, never predicted. Temperatures outside a species' data, other reactions (carbothermal
  reduction, dolomite) and missing losses are refused with a finding. `method: specific-energy`
  is a labelled conceptual fallback (a sourced GJ/t or the lime BREF's range by kiln type).
  Reference case, data and tolerances: [docs/framework/furnace.md](docs/framework/furnace.md).
  Exit 1 on a warning or error.
- **Links.** Blocks, steps, streams, feeds and products link to `equipment`, `line`,
  `instrument` or `sheet` (several per object, an optional `sheet:` scope). They resolve against
  the lists and `plant.yaml`; unresolved ones are `cheme.process-link-unresolved` (info), and
  the gate `kind: process-links` with `level: warning` or `error` reports or requires them.
- **`cheme process layout [IDS] --view bfd|pfd [--pin]`** prints the generated positions, and
  `--pin` writes them into `layout.<view>` so later builds keep them.

`validate`, `status`, `diff`, `show` and `render` take BFD and PFD sheets like P&IDs; the
loader's warning about port reference cycles is demoted to one info line per sheet. The
template's skill `process-design` walks through it, and `pid-draft` starts the P&IDs from the PFD.

### safety: HAZOP studies

A HAZOP study is one YAML file, `safety/hazop/<study-id>/study.yaml` (`cheme schema
hazop-study`): scope, operating modes, the analysed P&IDs and control files at the revision
analysed, nodes with their plant members and design intent, deviations (guide word and
parameter), scenarios (cause and consequence) with their initial and residual ratings, and the
study's safeguards and actions, each with a stable id. It rates against a risk matrix
(`safety/risk-matrix.yaml`, `cheme schema risk-matrix`): bands in their order, likelihood and
severity codes, categories, and the band of every cell. The matrix `cheme init` writes is
example data.

```sh
cheme safety hazop init H-01 --title "Feed section" --input pid/P-01.xml --input control/cause-effect.yaml
cheme safety hazop check H-01            # findings and state: invalid, draft, assessed, reviewed
cheme safety hazop rate H-01 [--target S3] [--write]   # bands from the matrix; --write records them
cheme safety hazop report H-01           # build/hazop/H-01.md and .html
cheme safety hazop stamp H-01 --write    # record the analysed inputs' current revisions
cheme safety hazop review H-01 [--write] # a review record (reviews/) for the reviewer to complete
```

- Judgements are `status: proposed` until the team accepts them; agents only propose.
- Severity and likelihood are the team's inputs, each with its basis. The tool looks up the
  configured cell: it never multiplies codes, estimates frequencies, credits safeguards or
  derives a residual risk. A missing or unknown code stays unresolved.
- A band is written as `band: {value, provenance: calculated, source, fingerprint}`. A changed
  rating or matrix makes it stale (`cheme.hazop-band-stale`), and so does a changed analysed
  input (`cheme.hazop-input-changed`). Other changes to the repository do not.
- `cheme validate` checks every study: ids, internal references, tags against the lists and
  P&IDs, interlocks against `control/cause-effect.yaml`, matrix codes and cells, actions.
  `kind: hazop` gates (`require: [assessed, reviewed, inputs-current, actions-closed,
  no-example]`) and `kind: review, topic: hazop` gates ask for completion and review per stage.
- `examples/safety-hazop/` is a small plant with an illustrative study; the skills
  `hazop-study`, `hazop-assessment` and `hazop-review` describe the workflow.

### check

`cheme check [--stage S [--only-stage]] [--write [--review RECORD] [--by NAME]]` evaluates
the gates of `checks/checks.yaml` and exits 1 when one fails. `--stage S` runs the gates of every
stage up to S in `plant.yaml` order (concept and basic for `basic`); `--only-stage` only S's. A
gate whose `stage:` is not a stage of `plant.yaml` (a typo such as `Concept`) is never left out:
it fails in every run, and `cheme validate` reports it (`cheme.check-stage-unknown`, error), as
it does a check id listed twice (`cheme.check-duplicate-id`, error). It only prints, except
with `--write`, which signs off stage S (default: `plant.yaml`'s `stage`) in
`checks/status.json`:

```json
{
  "stages": {
    "basic": {
      "stage": "basic", "commit": "<sha of the checked tree>", "date": "2026-10-18T14:02:11Z",
      "signed_by": "A. Engineer", "branch": "stage/basic-closeout", "default_branch": "main",
      "review": "reviews/2026-10-18-basic.md", "review_commit": "<sha>",
      "reviewer": "...", "reviewer_kind": "human", "stages": ["concept", "basic"],
      "checks": [{"id": "pids-valid", "title": "...", "stage": "basic", "status": "pass", "detail": ""}]
    }
  },
  "checks": ["... the gates of the latest sign-off, as 0.3 wrote them"]
}
```

Each stage has its own entry; signing off `basic` keeps the `concept` entry. `--write` writes
nothing and exits 1 when the working tree has changes other than `checks/status.json`, when any
gate fails, when no signer is known (`--by`, else `git config user.name`), when the `--review`
record has no valid front matter or is the signer's own (`reviewer_kind: self`, or the reviewer
is the signer) without an `approved_by` naming someone else, or when a critical or high finding
of any review record is open or is `closed` by a commit that does not exist or is not an
ancestor of HEAD, or when the `--review` record has `cheme.review-*` warnings. A finding is as
severe as the most severe rating any record gives it: a later record that carries it forward
without a severity, or with a lower one, does not lower it (close, accept or supersede it
instead); an open critical or high row whose id is not `<record>#<n>` blocks on its own.
`cheme status` and `GET /api/status` show the same severity. Signed off on a branch other than
the default, it says to merge: a stage counts as signed off only once the sign-off is on the
default branch. Commit
`checks/status.json` as the last commit of the stage. `cheme schema status` prints the
file's schema.

| kind | passes when |
|---|---|
| `validate` | no `cheme validate` finding at `fail_on` (`error`, the default; `warning`; `info`) or above, among the `rules` (ids, `*` matches; default all), that neither the gate's `accept: [{id, reason}]` nor the repository-wide `accept:` list names (errors are never accepted); a gate that `cheme.generated-sheet-drift` could fail runs the P&ID generators, as `cheme validate` does, and fails on `cheme.generator-failed` (a generator that cannot run) as on drift: a rule that matches the drift (`cheme.generated-*` included) matches it too |
| `files` | every glob of `files` matches a file inside the repository |
| `command` | the shell `command`, run at the repository root, exits 0 |
| `on-sheet` | the `tags` are drawn on the `sheet` (or each of `sheets`; neither: any sheet), and at least `min_count` (1) items of each of `classes` |
| `datasheets` | every equipment-list item has a valid `equipment/datasheets/<TAG>.yaml` (`cheme schema datasheet`; an empty list fails) |
| `layout-model` | the 3D layout meets each item of `require`: `site`, `areas`, `roads`, `racks`, `placed` (every equipment-list item), `separations` (declared in the site plan), `model-current` (`layout/plant-model.yaml` built from the current inputs), `nozzles` (no unknown override, no piped nozzle placed by default), `mounted` (every item above grade on a building or structure level, or on another item), `routed` (every line of DN `min_dn` (25) and above, not matched by `exclude_lines` / `exclude_fluids`, routed or skipped with a reason), `clashes` (no model finding of `rules`, default `cheme.layout-clash-*`, `-headroom` and `-buried-cover`, unaccepted), `zones` (declared), `drawings` (a review record of `topic`, default `layout`, cites the plot plan and `sections` (2) sections) |
| `review` | a review record for the `topic` (or among the `files` globs) has valid front matter, a reviewer kind in `require_kind` (default `[human, agent]`: a self review does not pass), a `reviewed_commit` that is an ancestor of HEAD, and (`current: true`, the default) no file of its `scope` changed since that commit, committed or not (when git cannot tell, the record is not current) |

The template's `drawing-clean` gate (stage basic) fails while a drawing finding is neither fixed
nor accepted; the detail of a failing validate gate counts what failed per rule and names the
first finding's id:

```yaml
- id: drawing-clean
  title: No line through a label or valve, along a pipe or slanted, no crossing, overlapping or
    misplaced label, no off-page connector off the sheet's edge left unaccepted
  stage: basic
  kind: validate
  fail_on: info          # cheme.line-not-orthogonal is an info finding
  rules: [cheme.line-through-label, cheme.line-crossing, cheme.label-overlap,
          cheme.label-far-from-owner, cheme.line-through-valve, cheme.line-on-pipe,
          cheme.line-not-orthogonal, cheme.offpage-not-on-edge]
```

Off-page connectors go on the sheet's edges even where that costs a line crossing: accept the
crossing in this gate with a reason, not the connector (a utility stub the plant keeps at its
user, such as a CW/CWR arrow at an exchanger, is accepted by its `offpage-not-on-edge` id).

`on-sheet` asks the loaded model, not the XML text: a tag is the one the P&ID prints
(`TagName`, the instrument tag `AIA-3103` built from category, letters and number, a piping
component's first `PipingComponentNumber` / `PositionNumber` / `PipingComponentName` that is not
a segment-local `C1`, a `LineNumber`), so renaming ids changes
nothing and an id or substring that merely looks like the tag does not pass. A class matches
itself, its DEXPI superclasses and classes whose name ends with it (`SafetyValve` matches
`SpringLoadedGlobeSafetyValve`). With `connected: true` each item must also be connected:
equipment with a pipe at a nozzle, an instrument function with a measuring or signal line (or a
sensing location), a piping component on a segment with a pipe or the segment's end at it. A
failing gate names what is missing, e.g. `P-03: AIA-9999 not drawn; FV-3111 drawn but not
connected`.

A review record is `reviews/<YYYY-MM-DD>-<topic>.md` starting with YAML front matter
(`cheme schema review`):

```markdown
---
topic: o2-safety
reviewed_commit: 521473c0d3...      # the commit whose files were reviewed
scope: [pid/P-03.xml, pid/P-04.xml, DESIGN.md]
reviewer: A. Engineer
reviewer_kind: human                # human | agent | self (the author's own review)
---
```

A passing review gate names the record and its commit, `(agent-reviewed only)` when the reviewer
is not a human, and its `evidence` (path, `reviewed_commit`, `reviewer`, `reviewer_kind`) goes
into `checks/status.json`. A failing one names the record and why: no front matter, a field
missing, the reviewer kind, `not an ancestor of HEAD`, or `changed since <commit>: pid/P-04.xml`.
`cheme validate` checks every `reviews/*.md` (but `README.md`):

| rule | level | finds |
|---|---|---|
| `cheme.review-front-matter` | warning / info | front matter that is not YAML or misses a field (warning); a record without front matter (info: no review gate accepts it) |
| `cheme.review-unknown-commit` | warning | a `reviewed_commit` that is not a commit of the repository |
| `cheme.review-scope-missing` | warning / info | a `scope` path that does not exist (warning); one written with a leading `/` (warning) or `./` (info), which is read from the repository root (`/pid/P-01.xml` as `pid/P-01.xml`, `/` and `./` as `.`, the whole repository) |
| `cheme.review-finding-id` | warning | a finding id that is not `<record file stem>#<n>` (an earlier record's id under Previous findings), or names no record |
| `cheme.review-finding-status` | warning / info | a status other than `open`, `closed <commit>` (an existing commit), `accepted: <reason>`, `superseded by <id>`; a severity other than critical, high, medium, low (info); an open finding without a severity (info); an open finding carried forward with no or a lower severity than the critical or high an earlier record gave it (warning: it still counts as that) |
| `cheme.review-previous-missing` | warning | the newest (or an uncommitted) record does not list, under `## Previous findings`, a finding of an earlier record of overlapping scope that is still open |

A findings table is any Markdown table with an `id` and a `status` column. A finding's status
is the one in the latest record listing it (by date, then the commit that added the record);
records are snapshots, and the next record carries open findings forward with their new status.

```yaml
- id: hydrocarbon-on-pid
  title: Sump hydrocarbon analyzer and LOX purge drawn
  stage: basic
  kind: on-sheet
  sheet: P-03
  tags: [AIA-3103, FIC-3111, FV-3111]
  classes: [SafetyValve]
  connected: true
```

### status

`cheme status [--json] [--rev REV] [--no-gates]` summarizes where the repository stands,
read-only: the stage; per sheet whether it is `drawn`, `empty` (an empty frame), `missing`
(declared in `plant.yaml`, no file yet) or `not-loaded`, what it draws and which items the lists
assign to it (`sheet:`) that it does not draw; the next sheet to draw; validation totals by level
and rule, and the not-on-pid findings by the sheet their list entry names (`unassigned` without
`sheet:`); every stage's gates (evaluated, not written; `--no-gates` skips them, as they may run
commands); the sign-offs of `checks/status.json`, flagged when the signed commit is not on the
default branch; the open review findings; and git branch, head, uncommitted paths (`null` in
`--json` when git cannot tell) and how far the branch is ahead of / behind the default branch.
`--rev` summarizes a revision, checked out in a temporary worktree that is removed afterwards. `--json` has the keys `plant`, `sheets`
(`id`, `file`, `state`, `drawn`, `assigned`, `missing`), `next_sheet`, `validation`, `gates`,
`signoffs`, `legacy_status` (a 0.3 `status.json`), `reviews` and `git`, documented in
`chemeascode.project.status`; a script can take the next sheet to draw from `next_sheet`. `GET
/api/status` returns it (without the gates).

### impact

`cheme impact [--json]` lists, read-only, the artifacts whose recorded source revision or
fingerprint no longer matches the current source, as `cheme.review-needed` findings at level
info: a review record whose `scope` changed since its `reviewed_commit` (or git cannot tell),
except files a later record of the same topic covers (that record supersedes it for them);
entries of a record's optional `basis:` list (`{path, revision, relation}`, revision a commit or
`sha256:<hex>`) whose path changed; generated BFD/PFD sheets whose `process/*.yaml` changed; and
stale calculated stream values. It exits 0, regenerates nothing and declares nothing invalid;
`validate`, `check` and `status` are unchanged. `--json` prints `{commit, findings}` (each
finding with its `id`); `GET /api/impact` returns the same. In Python:
`chemeascode.project.impact.review_needed` (or `impact_report` for the JSON form).

### maturity

`cheme maturity [--json] [--write] [--require LEVEL]` says which calculation maturity level the
evidence in the repository supports: `sourced` (a sourced process description), `balanced` (a
balanced conceptual PFD), `predictive` (a converged predictive simulation) or `engineering` (a
preliminary/basic engineering package), with every requirement `pass`, `fail`, `missing` or
`unsupported` and its evidence (fingerprints, balance residuals and tolerances, the run record's
simulator and version). Schema-valid files and drawings never satisfy a calculation level;
specified splits and conversions count as specified and cap the level at `balanced`. Artifact
completeness and review status are reported beside the levels and never raise one; nothing sets
the review status. `--write` writes `checks/maturity.json` (schema `cheme/maturity-report/v1`),
the only file it writes; `--require` exits 1 below that level. The text ends with the level and
the manifest's claim (`calculation maturity: balanced (design maturity claimed: screening)`).
The requirements and the mapping onto the design maturity of the process-library manifest:
[docs/framework/maturity.md](docs/framework/maturity.md); calculation maturity, design maturity,
project stage and review status side by side: [docs/concepts/glossary.md](docs/concepts/glossary.md).
In Python: `chemeascode.project.maturity.maturity_report`.

### skills

`cheme skills status [NAME...] [--json]` compares the skills installed in `.claude/skills/`
with the bundled ones: each file is `current`, `outdated` (an earlier bundled version, known from
the package's `templates/skills-manifest.json`), `modified` (changed in this repository) or
`missing`. `cheme skills update [NAME...]` installs missing and outdated files and keeps a
modified one, reporting `cheme.skill-modified` (exit 1); `--force` replaces it and still
reports it. `cheme init` reports a modified skill it kept, or replaced under `--force`. The licence
notice `.claude/skills/NOTICE.md` is tracked the same way; an update naming skills leaves it alone.

### git diff

`cheme git-setup` registers a textconv driver for `pid/*.xml`, so `git diff`, `git log -p`
and `git show` print P&IDs as pyDEXPI's review text (one block per object, attributes sorted)
instead of XML. Objects are written `Class@<id>` with the id as written in the file
(`PipeTee@PipeTee_47123_BypassIn`); an object without an id in the file (before `cheme fmt`)
keeps pyDEXPI's stable hash token. The driver and the pre-commit hook call cheme by the
absolute path it had when `git-setup` ran, so they work from clients without cheme on PATH
(rerun `git-setup` after moving the installation). The driver never fails a git command: a file it
cannot load is shown as its XML under a `(cheme textconv could not load ...)` line.

### serve

`cheme serve [--repo DIR] [--library] [--host 127.0.0.1] [--port 8765] [--ui DIST_DIR]` serves the plant
repository as JSON over HTTP, for the viewer. Every `GET` only reads. It needs the `serve` extra
(`uv tool install 'cheme-as-code[serve] @ git+...'`). Every endpoint takes an optional `rev` (a
branch, tag or sha; absent: the working tree) and repo-relative POSIX `path`s:

| endpoint | returns |
|---|---|
| `GET /api/repo` | name, root_name, branch, head, stage, stages, sheets (each with `kind` `pid`, `bfd` or `pfd`), dirty, has_layout, has_lca, has_tea (`estimate/tea.yaml`), has_equipment_estimate (the equipment list lists items), has_simulation (`process/simulation.yaml`), has_reactions (`process/reactions.yaml`), has_kinetic_data (`experiments/kinetics/*.yaml`) |
| `GET /api/streams?case=&rev=` | the stream table of `process/flowsheet.yaml`: streams (values with unit, provenance, source and stale flag, composition, calculated values, links with `resolved`/`problem`, `imbalance`, `on_bfd`), `balances`, `nodes`, `bfd_connections` (BFD connection id to the streams it represents, read from the built BFD sheet's `represents:` descriptions, else from the flowsheet; `bfd_connections_from` says which: `sheet` or `flowsheet`), cases, units, tolerance; 404 without a flowsheet, 422 for one that does not load or an unknown case |
| `GET /api/simulation?case=&rev=` | `{rev, file, run_file, case, cases, spec, run, stale, staleness, units, problem, findings}`: `spec` is `process/simulation.yaml` parsed (simulator, property_package, components, tolerance, tear_streams, exclude, guesses, specs per step as written, with provenance); `run` the case's entry of `process/simulation-run.json` (null without one); `stale` whether that run was simulated from other inputs (model fingerprint; null without a run or when the flowsheet does not load), `staleness` `{model_fingerprint, current_fingerprint, changed_files}`; `units` one row per step `{id, unit, status (simulated, excluded, refused, not-simulated), reason, spec, run}`; `findings` the translation's; 404 without `process/simulation.yaml`, 422 when it does not load or for an unknown case |
| `GET /api/reactions?case=&rev=` | `{rev, file, case, cases, reactions, reactors, balance, kinetics}`: each reaction as declared (stoichiometry, equation, phase, reversible, conversion, heat_of_reaction, equilibrium_constant with provenance, catalyst, sources) plus `key_component`, `reaction_smiles` (the reaction's external identifier, `reactants>>products` from the stoichiometry and the components' SMILES; null unless every component has one and every coefficient is whole), `type` (the reactor model it runs in: conversion, equilibrium, gibbs, mixed or null), `units` (`{unit, kind, model, approach_K, conversion}` per block or step naming it) and `element_balance`; `reactors` the `cheme process reactors --json` rows; `balance` `{balances, findings}` (the reactive balances and the reaction, reactor and balance findings of `validate`); per reaction its `rate` as declared (form, basis, driving, `k` {A, Ea, n, T_ref}, orders, adsorption, catalyst, temperature_range, provenance, source) and `rate_law` (null without a rate: `{expression, k_expression, rate_unit, driving_unit, k_unit, catalyst, k_profile: [{temperature_K, k}], k_profile_from}`, k(T) over the rate's temperature range, else its catalyst's window); `kinetics` `{file, catalysts, findings}`: each catalyst of `process/catalysts.yaml` as declared plus `reactions` (ids it catalyses) and `units` (`{unit, kind, reactor, reactions, bed}` per block or step holding it), the `cheme.catalyst-*` and `cheme.process-catalyst` findings (`file` null and `catalysts` empty without the file); a solved fixed bed is the `bed` of its `reactors` row, and each `reactors` row says its gas model (`fugacity`: ideal or peng_robinson); a reaction with a `mechanism` has `microkinetics` (null without one): `{conditions: {unit, stream, temperature_K, pressures_bar}, missing, ...}`, the `cheme chemistry microkinetics --json` analysis (coverages, TOF, degree of rate control, apparent Ea, orders) at the outlet of its first reactor, or `missing` naming why there is none; 404 without `process/reactions.yaml` or a flowsheet, 422 when either does not load or for an unknown case |
| `GET /api/kinetics?rev=` | `{rev, directory, files: [{file, data, fit, problem}]}`: each kinetic data file of `experiments/kinetics/` as declared and its default fit (`cheme experiments fit-rate --json`: a power law in the reaction's reactants, over 1 − Q/K when the reaction is reversible and K is known; `fit.reverse` says which), or the problem with either (where 1 − Q/K fails at a point, a forward-only fit with a note); a flowsheet that does not load is not needed; `cheme export-static --exclude` leaves out excluded files; 404 without data files or process files |
| `GET /api/library?rev=` | `{rev, entries}`: the reaction library (`cheme chemistry library`), every entry (window, components, reactions, catalysts, model basis, sources), each item's `in_plant` saying what the plant has (a component: the plant's id with its CAS number, else null; a reaction: the same stoichiometry under its id; a catalyst: its id, with `differs` when the plant's has other data, so `--add` refuses it); without process files nothing is marked, and a flowsheet that does not load leaves the marks from the materials, reactions and catalysts |
| `GET /api/branches` | `[{name, head, current}]` |
| `GET /api/log?limit=50&path=&rev=` | `[{sha, short, author, date, subject}]` |
| `GET /api/tree?rev=` | `[{path, type, kind}]`, kind `pid`, `yaml`, `markdown`, `json` or `other` |
| `GET /api/file?path=&rev=` | the file as text (400 for binary or over 5 MB) |
| `GET /api/pid.svg?path=&rev=` | the sheet rendered, as `cheme render` draws it |
| `GET /api/diff?path=&old=HEAD&new=` | changes, both SVGs, highlight maps, `old_owner`/`new_owner` (changed id to drawn id), `status` (`added`/`removed` for a sheet on one side), review-text diff |
| `GET /api/interlocks?rev=` | `{rev, file, interlocks, columns (effect tags), rows: [{id, title, cause, condition, sheet, sil, cells}]}`: the cause-and-effect list and matrix; 404 without `control/cause-effect.yaml` |
| `GET /api/control` | the `cheme control report --json` report of the working tree: loops, sequences, the narrative and the control philosophy with their review status and findings; see docs/framework/control.md; 404 without control records, 422 when they do not load |
| `GET /api/issues` | the `cheme issues --json` report: the plant's GitHub issues as engineering items (type, gate, discipline, source, status), `open_by_gate`, `blocking` per stage and `new` links to the issue forms; see docs/framework/issues.md; cached two minutes; 404 when plant.yaml declares no issues, 503 when they cannot be read (no token, no network) |
| `GET /api/status` | the `cheme status --json` summary of the working tree, without evaluating the gates |
| `GET /api/impact` | the `cheme impact --json` report of the working tree: `{commit, findings}`, every finding `cheme.review-needed` at level info, with its `id` |
| `GET /api/validate` | the `cheme validate --json` report of the working tree |
| `GET /api/maturity?through=` | the `cheme maturity --json` report of the working tree, evaluated on every request (one at a time) and never written; without `through` the engineering level runs the whole validation (some 30 s on ASU-1), `through=predictive` or lower skips it; see docs/framework/maturity.md; 400 for an unknown level |
| `GET /api/checks?rev=` | `checks/status.json` (`{checks: []}` when absent) |
| `GET /api/session` | `{token, header}`: the per-launch token for `POST /api/checks/run` |
| `POST /api/checks/run` | the gates evaluated now on the working tree (not written); needs the token header |
| `GET /api/yaml?path=&rev=` | `{data, kind, schema}` for a `.yaml`/`.yml` mapping or list; kind is a list or layout kind, `plant`, `materials`, `flowsheet` or null |
| `GET /api/layout?rev=` | `{site, areas, roads, racks, buildings (with footprint), equipment: [{tag, type, service, position, shape, family, size [dx, dy, dz], size_from (list, placement, default), rotation_deg, on, building, level, sheet, sheet_file, bbox, clash, notes}], lines: [{number, from, to, from_point, to_point, distance, length_est, racks, finding}], separations, model, notes, files, rev, findings}` with the layout findings; `separations` as written in the site plan, `model` the generated `layout/plant-model.yaml` (null without one; see docs/framework/layout-model.md); 404 without layout files |
| `GET /api/layout/plan.svg?rev=&level=&z=` | the plot plan of the committed `layout/plant-model.yaml`, or a level plan (`level=` a structure or building level id, or `z=a,b` an elevation range); see docs/framework/layout-model.md; 404 without a model or for an unknown level, 400 for a bad `z` |
| `GET /api/layout/section.svg?rev=&x=&y=&depth=6` | a section of the committed model at `x=` or `y=` (one of them), `depth` m thick (0 to 1000); 404 without a model, 400 for bad arguments |
| `GET /api/mto?rev=` | the material take-off of the committed `layout/plant-model.yaml`: `{rev, model, model_sha256, columns, rows, totals, findings, estimate}`, `estimate` priced with `estimate/rates.yaml` (null without one); see docs/framework/mto.md; 404 without a model |
| `GET /api/estimate/equipment?rev=` | the equipment estimate (`cheme assess equipment --json`): `{rev, currency, base, index, estimate_class, accuracy, totals, lines, own_costs, findings, source}`; see docs/framework/mto.md; 404 without an equipment list or with no items, 422 for a list that does not load |
| `GET /api/datasheets?rev=` | the equipment datasheets (`equipment/datasheets/`): `{rev, directory, datasheets: [{tag, file, valid, type, service, draft, counts, drawing, drawing_current, findings, ...}], missing, source}`; see docs/framework/datasheet-drawings.md; 404 without datasheets |
| `GET /api/datasheets/{tag}?rev=` | one datasheet: `{rev, tag, file, summary, datasheet (parsed, null when it does not validate), data, drawing: {file, state, current}, findings, source}`; 404 without it |
| `GET /api/datasheets/{tag}.svg?rev=&generated=` | its outline drawing: the committed SVG, or the generated one when none is committed or with `generated=true`; headers `X-Cheme-Drawing` (`committed` or `generated`) and `X-Cheme-Drawing-Current`; 422 for a datasheet that does not validate |
| `GET /api/lca?rev=` | the LCA (`cheme assess lca --json` without the source): inventory, impacts by scenario, category, phase and contributor, findings; see docs/framework/lca.md; 404 without `lca/lca.yaml` or `plant.yaml`, 422 when it does not compute |
| `GET /api/tea?rev=` | the techno-economic analysis (`cheme assess tea --json` without the source): premises, capex build-up, flows, cash flow, results, scenarios, tornado, break-even values, Monte Carlo, findings; see docs/framework/tea.md; 404 without `estimate/tea.yaml`, 422 when it does not compute |

Errors are `{"error": "..."}` with 400 (bad path or revision, file over 5 MB), 403 (cross-site
request, missing token), 404 (absent), 405, 409 (checks already running), 422 (cannot load) or
500 (`internal error`, no details). `POST /api/checks/run` runs the `kind: command` checks of
`checks/checks.yaml`, which are shell commands: one run at a time, each command stopped after
120 s. `/api/*` refuses requests another web site makes (`Sec-Fetch-Site` cross-site or
same-site, or a foreign `Origin`). YAML is returned with aliases expanded up to 200,000 values;
self-referencing aliases and `!!binary` are 422. Sheets that `plant.yaml` lists outside the
repository are never read; `validate` reports them as `cheme.sheet-outside-repo`.
Paths must stay inside the repository (no `..`, absolute paths, `.git`, or symlinks out);
revisions are resolved with `git rev-parse --verify --end-of-options` and may not start with `-`.
The server binds 127.0.0.1 and accepts only local `Host` headers. With `--ui` (or `CHEME_UI`)
it also serves a built single-page app at `/`, falling back to its `index.html`. Rendered sheets
and diffs are cached in memory by git blob id.

**A folder of plants (library mode, ADR 0034).** `cheme serve` in a folder that has no
`plant.yaml` above it but plants below it (at most 3 levels down: process-library's root, or a
folder of plant repositories), or with `--library`, serves every plant under `/p/<id>/` (the id
is the plant's folder name; when two share it, their relative paths, `a-same`). Each plant's
endpoints are the ones above, unchanged (`/p/asu-1/api/repo`); a plant in a subfolder of a git
repository reads its history from that repository, a plant repository its own. The library adds:

| endpoint | returns |
|---|---|
| `GET /api/plants` | `{root_name, plants: [{id, path, name, stage, sheets, maturity, maturity_checked, title, summary, families, error}]}`: `name`, `stage` and the number of `sheets` from `plant.yaml` (`error` when it does not validate), the recorded maturity level of `checks/maturity.json` (never evaluated live), and the optional `title`, `summary` and `families` of a `process.yaml` beside it |

`/p/<id>` redirects to `/p/<id>/`; an unknown id is a 404. With `--ui` the viewer is served at
`/` (its index of the plants) and at every `/p/<id>/` page. The same guards apply to the library
and to each plant (the `Host` check, the cross-site refusal, a session token per plant).

## The plant repository

`cheme init` creates the layout from `src/chemeascode/templates/project/` and the bundled skills
(`src/chemeascode/domains/<domain>/skills/`, `src/chemeascode/project/skills/`) (also published as the
[`project-template`](https://github.com/ChemE-as-Code/project-template) repository): `plant.yaml`, `pid/`, `process/`, `equipment/`, `piping/`,
`control/`, `checks/`, `reviews/`, `layout/` (3D layout, see its `README.md`), `DESIGN.md`, `PROGRESS.md`, `AGENTS.md`, and Claude Code
skills in `.claude/skills/`:

| skill | for |
|---|---|
| `dexpi-xml` | reading and writing DEXPI 2.0.1 XML by hand: conventions (coordinates, segment ends, tees, instrument bubbles), recipes (tee and branch, remove an item, instrument on a nozzle, change a line's DN) and verbatim snippets from the DEXPI reference P&ID (pump, tank, piping system with valve, tee with branch, instrument function, instrument nozzle) |
| `process-design` | materials and flowsheet YAML, `process build`, balances, refinement into the PFD, `process props`, links, layout pins, DESIGN.md holding decisions rather than numbers |
| `reaction-evidence-search` | the evidence behind a reaction model in `process/reaction-evidence.yaml`: searches with the agent's own tools (logged with dates), sources with DOI or patent number, access reached and reuse terms, one observation per experiment or patent example at its exact location (conversion, selectivity and yield kept apart; kinetics with units, basis and range), conflicts and gaps, never a value a source does not give |
| `route-selection` | comparing the routes (`cheme chemistry evidence`), selecting one with its rationale, the `model_basis` (reactions, evidence, assumptions, validation plan) and the handoff to `reactions.yaml` with each value citing its observation |
| `reactions` | `process/reactions.yaml` (stoichiometry, conversion, heat of reaction, catalyst, sources), reactions on reactor steps, element and extent balances, conversion reactors in `process propagate` |
| `electrochemical-cell-modelling` | `process/cells.yaml`: reactions and electrons, half-reactions, specified or measured performance (`performance: measured`, never extrapolated), the membrane block with FE and WDE kept apart, `cheme process cell` and the flowsheet link |
| `electrolysis-duty-assessment` | `process/duties.yaml`: current, power or on/off schedules against the anolyte reservoir, the stated pH threshold, dosing, bleed, `cheme process duty`, comparison at equal delivered product, the measured range never left unflagged, measured points kept apart from simulated transients |
| `skid-design` | an electrolyser skid from one design basis: the cell, the `stacks:` section of `process/cells.yaml` and a duty, `cheme process cell`, `duty` and `stack --write`, the control P&ID and `control report`, `datasheets draft/fill`, `layout build/render`, `assess lca`; the vendor envelope, clearances, hazardous area and H2/CO handling left to a human |
| `experiment-reproduction` | reproducing a published measured series: the data set pinned by DOI and checksum, tolerances frozen before comparing, reproduction kept apart from validation and design use, no third-party content copied, `cheme experiments electrochem` |
| `process-simulation` | `process/simulation.yaml` (property package, step specs), `process simulate --check` and `--fill` with DWSIM, deviations from assumed values, shortcut before rigorous columns, recycles |
| `pid-edit` | changing a sheet: edit, fmt, validate, render, diff, commit |
| `pid-draft` | a new sheet (`cheme sheet new`) started from the PFD, drafted with fragments or with a generator script on `chemeascode.domains.piping.authoring` (`cheme run`), and whether it stays generated |
| `lists-sync` | equipment, line and instrument lists consistent with the P&IDs and the flowsheet links |
| `review` | validation, checks, drawing review backed by the drawing counts and a tile sweep, engineering review, layout review backed by the plot plan and section PNGs and `layout report`, a review record with Drawing and Layout sections |
| `layout-yaml` | site plan, buildings, structures, zones and equipment placement (mount, nozzles, access): placing equipment, avoiding clashes, tags consistent with the equipment list, the `layout build` loop |
| `pipe-routing` | routing intent in `piping/routing.yaml` (tiers per service, battery limits, pipe-way elevation, vias, pins, skips with a reason, buried lines), iterating with `layout route`, `report` and plan/section renders, fixing clashes; what the router cannot decide |
| `structures-access` | what goes on a steel structure, frames, cold boxes and enclosures, platforms, ladders and stairs for manways and valves above 2.5 m, escape routes, maintenance envelopes |
| `tea` | techno-economic analysis: `estimate/tea.yaml` (decision, basis, capex build-up from the estimate, prices with sources, fixed opex, finance, uncertainty, scenarios), `cheme assess tea`, the dominating premises and break-even values, `--compare` on a shared basis |
| `area-classification` | `layout/zones.yaml`: hazardous, oxygen-enriched and oxygen-deficient zones from release sources (release grade, substance) and the ASSUMED radius table, keep-clear and escape zones; review by a competent person |

Agents edit the XML files directly. There is deliberately no MCP server and no edit-operation
API: the experiment is how far direct file editing with validation goes. `copy` and `fragment`
are text helpers in that spirit: they write XML for the agent to place, and the file stays the
only state. The builder library `chemeascode.domains.piping.authoring` for generator scripts fits the same
principle (decided in 0.4): it loads a file, inserts XML built by the same functions as
`fragment`, writes the file and formats it; it holds no state between runs, and its output is
validated like any hand edit.

## Agent design runs

[`docs/agent-design-run.md`](docs/agent-design-run.md) describes a repeatable staged agent design
run: the runner `scripts/agent-run/run_stage.py` (in every plant repository), stage and reviewer
prompts built from the repository (`cheme status --json`), budgets per stage type and the
record layout.

## Run records

Every design session leaves a record in the plant repository, one folder per run:
`runs/<run-id>/` (run id: the start in UTC, `YYYYMMDD-HHMMSS`, then optionally `-<slug>`) with
`run.yaml` (schema `process-run/v1`, `cheme schema process-run`), `task.md`, an optional
`report.md` and `session.jsonl.gz`, the gzipped Claude Code transcript. `run.yaml` holds the
start and end commits, times, the cost as the API reported it (never estimated), budget, model,
turns, tokens (each API message counted once), the distinct `cheme` commands the session ran and,
with `--checks`, the exit and a summary of `cheme check` and `cheme maturity` afterwards. A value
nobody knows is null; `complete: false` and `incomplete_notes` say what is missing and why. A
record is never edited: a revision is a new run.

- `cheme runs start [--hook | --session-id ID]` remembers the start (HEAD, branch, time, the
  working tree) in `build/run-records/<session id>.start.json`.
- `cheme runs record [--hook] [--session-id ID | --transcript F] [--kind K] [--slug S]
  [--task-file F] [--report-file F] [--cost USD] [--budget USD] [--effort E] [--result R]
  [--start-commit SHA] [--checks] [--commit]` writes the folder and prints it; `--commit` commits
  it alone (`<process>: run record <run-id>`).
- `cheme runs list [--json]`: run id, kind, cost, wall time, complete, turns.

The project template's `.claude/settings.json` runs `cheme runs start --hook` on `SessionStart`
and `cheme runs record --hook` on `SessionEnd`, so an interactive session records itself (kind
`interactive`, uncommitted, skipped when HEAD and the working tree did not change); a hook never
fails the session. A runner that records its sessions itself (`scripts/agent-run/run_stage.py`)
starts them with `CHEME_RUN_RECORD=off`. The transcript stays out of the run folder when it holds
`sk-ant-` or the value of `ANTHROPIC_API_KEY` (not exported at all), or when the session used
WebFetch, WebSearch, `curl` or `wget` (kept in the ignored `build/run-records/`, since it may
hold third-party text). In Python: `chemeascode.project.run_records.record_run`; the transcript
reader is `chemeascode.integrations.claude_code`. ADR 0029.

## Running agents headless

Claude Code reads a repository's `.claude/settings.json` (the template's allowlist: `cheme`,
read-only `git`, `grep`, `ls`, `wc`, `head`, `tail`, `cat`, `cmp`, `sed -n`, Edit and Write) only
once the folder is **trusted**. In a folder that was never opened interactively, a headless run
(`claude -p ...`) prints `Ignoring N permissions.allow entries from .claude/settings.json: this
workspace has not been trusted` and every command outside the defaults is denied. Either open
the folder in Claude Code once and accept the trust dialog (or set
`projects["<path>"].hasTrustDialogAccepted: true` in `~/.claude.json`), or
pass the allowlist explicitly:

```sh
claude -p "$(cat build/prompt.txt)" --settings .claude/settings.json --output-format json
# or: --allowedTools "Bash(cheme:*)" "Bash(git log:*)" ... Edit Write
```

With `--settings` the `Ignoring N permissions.allow entries` line is still printed, because the
project copy of the file stays untrusted, but the same entries apply from the flag. Check the
`permission_denials` of the JSON result, not that line: in an untrusted folder freshly made by
`cheme init` (Claude Code 2.1.311), the same short task (`cheme validate`, `git log`, `wc`, an
Edit of `DESIGN.md`, `git commit`) had `cheme validate` and the Edit denied without the flag,
and no denials with `--settings .claude/settings.json`.

The allowlist deliberately leaves out `sed -i`, `awk`, `cp` and heredocs: allowing them would
approve shell rewrites of 50,000-line sheets. The template's `AGENTS.md` and the `pid-edit` /
`pid-draft` skills tell agents to change files with Edit/Write only, to run one command per
Bash call (no loops, `&&` chains or `VAR=...;` prefixes, which prefix rules do not match) and to
keep scratch files in `build/`. `cheme init` prints a reminder. `docs/agent-design-run.md`
packages a staged design run with these flags.

## Development

```sh
uv sync --all-extras
uv run pytest -n auto   # in parallel (pytest-xdist); plain `uv run pytest` runs serially
uv run ruff format && uv run ruff check
uv run python scripts/build_snippets.py tests/data/reference_pid.xml   # regenerate skill snippets
uv run python scripts/build_skill_manifest.py                          # after changing a skill
```

The package is organised as a framework of `foundation`, ten engineering `domains`, a `project`
layer, `interfaces`, `integrations` and `templates`; see
[docs/framework/architecture.md](docs/framework/architecture.md) for the modules and their import
rules, and [docs/framework/contributing.md](docs/framework/contributing.md) for where new
functions, skills, schemas, integrations and tests go. Every capability has a Python function
that the CLI wraps, for example `chemeascode.domains.process.streams.stream_report(root, case)`
behind `cheme process streams`.

## License

This work is licensed under the GNU Affero General Public License v3.0 or later (AGPL-3.0-or-later) - see LICENSE.

Technische Universiteit Delft hereby disclaims all copyright interest in the program "Cheme-as-Code" written by Artur M. Schweidtmann. Paulien Herder, Dean of Applied Science.

Copyright (C) 2026 Artur Schweidtmann

The same text is in `NOTICE`. Which licence applies where:

- **The code** (the `chemeascode` package, its CLI, scripts, tests and docs): AGPL-3.0-or-later.
- **Bundled third-party data keeps its own terms**, recorded next to it: the DEXPI excerpts in
  the `dexpi-xml` skill (`snippets/`, `shapes.md`) are CC BY 4.0 (DEXPI e.V.), see its
  `NOTICE.md`; the packaged LCA background profiles in
  `domains/assessment/lca/data/backgrounds/` each state theirs in `sources:` (Ember: CC BY 4.0;
  EEA: CC BY; DESNZ: Open Government Licence v3.0; UBA: UBA data terms; US EPA eGRID: public
  domain in the US). The ChemSep SRK data is not shipped (`data/chemsep/SOURCE.md`).
- **The tools stay AGPL; your plant data is yours.** The skills `cheme init` writes into a plant
  repository (`.claude/skills/`) and the scripts it writes there (`scripts/`) are
  AGPL-3.0-or-later, like the rest of the tools. Plant data and models you create (P&IDs, YAML,
  reports, generated drawings and results) are yours, under terms you choose; running the tools
  does not put AGPL on what they produce. `.claude/skills/NOTICE.md` and the plant README say so
  in the repository. `cheme init` adds no `LICENSE` file for the plant content, and neither does
  the ChemE-as-Code/project-template repository generated from it.
- pyDEXPI and the other dependencies keep their own licenses.
