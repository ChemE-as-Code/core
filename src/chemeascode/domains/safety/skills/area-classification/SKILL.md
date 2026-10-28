---
name: area-classification
description: Declare the zones of the 3D layout in layout/zones.yaml - hazardous areas around flammable releases, oxygen-enriched and oxygen-deficient zones around oxygen and inert vents of an air separation or similar plant, and keep-clear, laydown, maintenance and escape zones - from explicit volumes or release sources with release grade and substance, sized by cheme-as-code's ASSUMED radius table, then check separations and routes against them. Use when adding vents, relief outlets, seals or flanges handling oxygen, inerts or flammables, when a zone or separation finding appears, or before the layout review.
---

# Area classification for the layout

## Purpose and when to use

Put the zones that constrain the layout into `layout/zones.yaml`, so the 3D model shows them,
the router keeps pipes out of the forbidden ones and the separation rules measure against them.
This is a **screening** classification for layout work, not an area classification study: the
radii come from an indicative table marked ASSUMED, and no dispersion is modelled. Use it when
the P&IDs gain vents, relief valves, pump or compressor seals or flanged equipment handling
oxygen, inert gases or flammables; when `cheme validate` or `layout build` report
`layout-zone-crossing` or `layout-separation`; and before the layout review.

## Required inputs and missing inputs

- The placed items and the routed model (skill `layout-yaml`), the P&IDs (vents, relief
  valves, silencers, stacks; `piping/special-items.yaml` for safety valves and silencers), the
  line list (fluids), `DESIGN.md` (the substances, the vent philosophy, the site's wind).
- For each release point: what is released (substance), how often (release grade:
  `continuous`, `primary` - expected in normal operation from time to time, `secondary` - only
  in abnormal operation), and its kind (`vent`, `psv_outlet`, `pump_seal`, `compressor_seal`,
  `flange`, `valve`, `drain`). When the grade is not known, say so (`basis:`) and take the more
  frequent grade.
- The site's area classification standard and any study already done: a real classification
  replaces the table; ask for it.

## Workflow and tools

1. **Explicit zones** (`shape: box | cylinder | sphere`): `keep_clear` (truck loading bays,
   fire-fighting access), `laydown`, `maintenance` (crane and removal areas), `escape`
   (escape routes, kept clear up to `headroom_walkway_m`), and any zone a study gives you as a
   volume (`hazardous` with `zone: 0 | 1 | 2 | 20 | 21 | 22`, `oxygen_enriched`,
   `oxygen_deficient`). `box: [x0, y0, z0, x1, y1, z1]`; a cylinder's `centre` is the centre of
   its base, with `radius` and `height`. Give every zone a `title` and a `basis`.
2. **Zones from sources** (`sources: [{item, release_grade, substance, source_kind?,
   substance_class?}]`): `item` is a placed tag (a stack, silencer or vent: its top; a pump:
   its seal; a compressor or turbine: its seals; a safety valve: its outlet), a nozzle
   `TAG/N1` (a flange) or a line number (its open ends: vents and relief outlets). The
   substance maps to a class (`oxygen`, `inert`, `flammable_gas`, `flammable_liquid`; override
   with `substance_class`) and the table (`domains/safety/data/release-radii.yaml`) gives one
   volume per row of that source kind, grade and class whose kind is the zone's `kind` (and
   zone number, when given), so one zone holds one kind: e.g. a continuous oxygen vent an `oxygen_enriched` sphere of 5 m, an inert
   vent an `oxygen_deficient` sphere of 5 m, an LIN pump seal an `oxygen_deficient` cylinder of
   3 m from grade, a flammable relief outlet zone 1 within 3 m. Every generated volume carries
   `status: ASSUMED` and the row's `basis`.
3. **Air separation and other oxygen and inert plants**:
   - oxygen-enriched zones around GOX/LOX vents, oxygen relief outlets, oxygen compressor seals
     and LOX pump seals: no ignition sources, no oil or grease, no combustible materials
     (asphalt, wood) in them, and keep them away from air intakes, roads and buildings;
   - oxygen-deficient zones around nitrogen, argon and waste-gas vents, cold box casing
     breathers and LIN/LAR pump seals: cold inert vapour collects at grade and in pits and
     trenches; vents go above platforms and away from walkways and escape routes;
   - the main air intake upwind of every vent (the prevailing wind is a design assumption in
     `DESIGN.md`), with the distance measured (`cheme show <tag> --layout`) and declared as a
     `separation:` in the site plan (`from: <intake>, to: <zone id>, min_m: ...`);
   - liquid spills (LOX, LIN) spread at grade: keep drains, trenches and kerbs in mind.
4. **Separations against zones**: a site-plan separation may name a zone id (`from: Z-O2-VENT,
   to: R-1, min_m: 15, basis: ...`); `cheme layout build` measures it
   (`layout-separation`). Routes through `keep_clear`, `laydown`, `maintenance` and `escape`
   zones are avoided by the router; `layout-zone-crossing` reports what crosses a zone. Cable
   trays inside an oxygen-enriched or hazardous zone are `layout-tray-zone` (the zone kinds in
   `avoid_zones` of `electrical/tray-rules.yaml`): an ignition source and a combustible cable
   sheath in an oxygen zone, or equipment not rated for a hazardous area. A vent or relief
   zone that reaches a walking level is `layout-vent-outlet`; the walking levels include the
   generated ones (a tank's spiral stair, its landing and roof platform, stair landings,
   step-overs), and an outlet directly under a walking surface is a finding even without a
   zone. Platforms and ladders inside a casing are no walking levels: a casing breather's
   zone covers the roof walkway, not the platforms inside.
5. **Look at the zones**: `cheme layout render --plan --png` (zones are drawn with their
   ids), a section through a vent area (`--section x=.. --png`), and `cheme serve`
   (Layout 3D: zones as transparent volumes). Check that every vent and relief outlet of the
   P&IDs has a zone or a reason why not.

### Reading the P&IDs for release sources (engineering guidance only; core has no calculation for this)

Use this before choosing `release_grade` and `source_kind` for the sources in step 2. A zone follows
from how often a source releases and how well the release is diluted (Bottrill, Cheyne and
Vijayaraghavan, *Practical Electrical Equipment and Installations in Hazardous Areas*, Newnes 2005,
3.5, 3.8). That book describes a method since superseded: only its principles are used here, no
extents; extents come from the site's adopted standard.

- Grade: continuous (present always or for long periods, e.g. the vapour space of a vented
  fixed-roof tank), primary (expected in normal operation, e.g. a seal expected to weep, a routinely
  opened sample point), secondary (only on failure, e.g. a gasketed joint). The same item can be
  primary or secondary; that is a property of design and service, not of the symbol. As a starting
  point only, continuous tends toward zone 0, primary toward 1, secondary toward 2 (dusts 20, 21,
  22), then ventilation and release character move it (3.6, 3.8.2). The zone decision is the
  classification's. Non-routine maintenance under permit is not a source; anything opened routinely
  (filters, strainers, pig traps) is (3.2, 3.8.1).
- Ventilation dilutes a release and, if good and reliable enough, changes the zone type. Reliability
  shows on drawings as standby fans starting automatically, ventilation-failure detection or a
  process trip on loss of ventilation (3.8.10).
- Design to have fewer and smaller releases: prefer equipment whose releases are only secondary, keep
  unavoidable primary releases small (3.10).
- Walk items in flammable or combustible service only (gas or vapour, liquid at or above flash point or
  as mist, combustible dust); joints on cooling water, plant air or steam are not sources (3.4.1,
  3.8.1). An all-welded line is not counted as a source; flanges and screwed joints, instrument
  connections, pump and compressor seals (with seal-oil pots, breathers, distance-piece vents), valve
  stems, sample points, drains (water draw-offs from hydrocarbon vessels), vents, breathers, relief
  outlets and anything opened in normal operation are (3.13, 3.14).
- Things that make a release smaller or rarer: discharge of vents and reliefs to flare or recovery
  rather than atmosphere (a light gas may be released high enough to disperse; a heavy gas needs
  enough release velocity to self-dilute at low flow too, else flare; 3.14.3); closed or cooled
  sampling, with liquefied flammable gas sampled only into a closed system vented to a safe place; a
  tundish to a sealed drain keeps liquid off the ground but still gives off vapour; closed drains with
  double block valves in liquefied-gas service; restricted bore on sample points and drains; mechanical
  seals rather than packing on hot flammable liquids and liquefied gases; excess-flow valves and
  self-sealing couplings on loading connections; vacuum operation of dust systems. Ask why each
  atmospheric discharge goes to atmosphere and where (Toghraei, *P&ID Development*, Wiley 2019,
  12.16.2, 16.11; Karre, *P&ID: A Stepwise Approach*, De Gruyter 2023, 11.4).
- Things that protect equipment or report a release but shrink nothing: flame arresters (the vent is
  still a source), explosion vents (ask where they point) and fast isolation on dust equipment, and
  fixed gas detection (ask what each alarm does and whether that action is credited; detector
  positions are on the plot plan, so a missing detector is not a P&ID defect).
- An open liquefied-gas sample point or drain is worth raising whatever the classification says: the
  operator stands in a flashing vapour cloud with cold burns as well as fire. A combustible vent
  or relief to atmosphere (other than tank breathing), or an open sample of a volatile
  hydrocarbon with no cooler or closed connection, is a question about the classification it implies.

Pressurised and purged enclosures (analyser house, control room) are kept safe by pressurisation
above the surroundings or by a purge flow that dilutes an internal release (Bottrill 9.1, 9.2).
Check them as a drawn system (9.4 to 9.7): supply from a safe area, uncontaminated and reliable,
with standby where needed (air for rooms, since inert gas asphyxiates; inert for small enclosures
with an internal release); proof the inside is gas-free before energising (usually several volume
changes, flow-proven and timed; some designs use a gas test; an enclosure with zone-rated contents
needs neither; the certificate says which); monitoring that proves the protection (differential
pressure or outlet flow; fan-rotation and supply-pressure signals can read healthy after the
protection has failed, so they suit alarm duty only); the action on loss (alarm or disconnection)
depends on the zone and on whether contents spark in normal operation, and disconnection that
creates a dangerous process condition needs a specific answer; an outlet that cannot recirculate to
the inlet and whose discharge does not change the classification where it lands; for an analyser,
the sample containment inside (a limited leak can be diluted if air flow is sized for that leak,
a restriction alone proves nothing; an unlimited leak usually needs inert gas, only where the sample
has no oxidant of its own, the release is gas and the exhaust leaves occupied space). The monitoring
devices, controller and purge valve sit in the hazardous area until the purge completes, so their own
protection is a datasheet matter. Equipment gas group and temperature class are unrelated (hydrogen is
hardest for sparks yet has a high ignition temperature; Bottrill 4.5, 4.6): take them from the current
standard's tables and the hazardous-materials schedule. First rule: keep electrical equipment out of
the hazardous area where practical (4.1). All of this guides questions; zones, gas groups, Ex ratings
and the purge design belong to the classification and datasheets.

## Validation and failure handling

- `cheme validate` checks the file against `cheme schema zones` (a zone needs a shape or
  sources, a hazardous shape a zone number); `cheme layout build` reports
  `cheme.layout-zone-source` for a source it cannot find (an unplaced tag, a nozzle the P&ID
  lacks, a line without open ends), a substance not in the table, or a source the table has no
  row of the zone's kind for: place the item, fix the name, set `source_kind` /
  `substance_class`, or give an explicit volume with its basis.
- Gate `layout-3d` requires `layout/zones.yaml` with at least one zone; it does not judge the
  extents.

## Outputs and provenance

`layout/zones.yaml` (`source: declared` zones; volumes from sources are `generated` with
`status: ASSUMED` and the table row's basis), the separations naming zones in
`layout/site-plan.yaml`, and the zone basis in `DESIGN.md` (substances, grades, wind, the
standard to be applied). Never present a table radius as a classification result.

## Required human judgment

The radius table is indicative and ASSUMED: it ignores release rates, pressure, ventilation,
obstructions, wind and the site's standard. An area classification (IEC 60079-10-1 / -10-2, EI
15 or the site's code for flammables; EIGA guidance and a vent study for oxygen and inert gases)
must be made or reviewed by a **competent person**, who replaces or confirms each zone and signs
the record. Until then every zone stays ASSUMED, the layout review lists it under "Not checked"
or as a finding, and no equipment selection (Ex ratings) may rest on it. Dispersion and
consequence modelling are out of scope here; their results come in as explicit volumes.

## References

- `cheme schema zones`, `layout/README.md`, `docs/framework/layout-model.md` (zones)
- the radius table `domains/safety/data/release-radii.yaml` (bundled with cheme-as-code),
  `domains/safety/area_classification.py`
- Bottrill, Cheyne and Vijayaraghavan 2005, chapters 3, 4, 9; Toghraei 2019, 12.16.2 and 16.11;
  Karre 2023, 11.4. The principles in "Reading the P&IDs for release sources" are re-expressed general
  method; the superseded zone-extent figures were not carried over; operational use needs review by a
  competent person.
- skills `layout-yaml`, `structures-access`, `review`, `process-safety`, `relief-scenarios`
