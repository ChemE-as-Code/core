---
name: tech-gas-inlet-and-separation
description: Reference for the gas plant front end. Slug catching, three-phase inlet separation, condensate stabilisation, sour water stripping, glycol recovery and condensate storage. Use when the inlet facilities of a gas plant are being discussed or reviewed.
---

# Inlet and separation

## Purpose and when to use

The front end absorbs what the pipeline delivers, makes a steady gas stream and a steady liquid
stream, and lowers the liquid's vapour pressure far enough for an atmospheric tank. Reached from
`tech-gas-processing`.

## Required inputs and missing inputs

Largest slug or pigging volume the line can deliver, inlet pressure and temperature, liquid and
water content, whether glycol is injected upstream, sulfur species in the condensate, and the
condensate vapour pressure specification. Ask for any that is missing.

## Workflow and tools

Engineering guidance only; core has no calculation for this. Stabiliser cut points and flash
splits need a simulation with an adequate property method (`thermodynamic-model-selection`,
`process-simulation`).

Units in flow order: slug catcher (vessel type for small volumes, finger type for large; gas
leaves on pressure control, liquid to the separator); three-phase inlet separator (gas to acid gas
removal, hydrocarbon liquid to stabilisation, water to stripping and glycol recovery); medium
pressure flash drum and a feed/bottoms exchanger; condensate stabiliser (refluxed column or simple
non-refluxed stripper) with light ends and H2S overhead; overhead recompression returning vapour to
the feed gas ahead of acid gas removal, so that recycle sizes the treating unit; sour water stripper
sending acid gas to the sulfur plant; glycol regeneration and reclaiming where glycol is injected
(formation salts concentrate in lean glycol); condensate storage with blanketing and vapour
recovery.

Variants: an LPG-producing plant puts a feed liquid stripper ahead of the stabiliser so its overhead
becomes a product. Cascade flash stages replace the column, saving weight (offshore) at lower yield
and a higher achievable vapour pressure. A non-refluxed stripper is cheaper but loses C5+ overhead.
Where sulfur species survive, a condensate hydrotreater follows.

Control reported: level and pressure on the slug catcher; an interface loop on the three-phase
separator; stabiliser reboiler on a (pressure-compensated) bottom temperature, verified by laboratory
samples; smoothing of feed flow to the column; tank pressure in split range between blanket gas and
vapour recovery.

## Validation and failure handling

Questions for a flowsheet or P&ID:

- Does every flash and stabiliser overhead have a destination (recompressed into feed gas, or to
  product)?
- Does the three-phase separator show an interface loop rather than two identical level loops?
- On a refluxed stabiliser, is there a water draw? (A stripper or cascade flash has no reflux drum.)
- Do sour water and recovered glycol have named destinations?
- Does the condensate tank have overpressure and vacuum relief, flame arrestors on vents, and
  blanketing and vapour recovery?

The slug catcher is normally the largest high-pressure inventory on site, so emergency
depressuring is a case to be argued for it. The rate is bounded by metal temperature and
brittle-fracture limits, hydrate behaviour, valve capacity, flare back pressure and other header
loads; ask for the documented depressuring basis rather than assuming a rate. Slug predictions
need a margin, since more liquid than the catcher holds shuts the plant down. Ammonium bisulfide
can foul the sour water stripper overhead at low temperature. This skill does not certify any
protection.

## Outputs and provenance

The front-end line-up with its recycle topology, the vapour pressure target stated as project data
(two sources give different ranges), and open questions.

## Required human judgment

Slug and depressuring basis, stabilisation route, vapour pressure specification, relief and
storage design.

## References

- Mokhatab, Poe and Mak, *Handbook of Natural Gas Transmission and Processing*, 3rd ed.,
  Elsevier 2015, Ch 5 (stabilisation and vapour pressure specifications). Sources disagree on the
  vapour pressure target; no value is recommended here.
- Needs review before operational use: all unit line-up and variant statements, and
  the control description; stabiliser, stripper and slug catcher size figures were not carried over.
- `tech-gas-processing`, `tech-gas-sulfur-recovery`.
