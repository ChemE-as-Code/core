---
name: tech-refining-treating-and-blending
description: Reference for refinery finishing. Caustic and catalytic mercaptan sweetening, jet fuel treating train, sour water stripping, and blending, tankage and shipping. Use when product treating or blending is being discussed or reviewed.
---

# Treating and blending

## Purpose and when to use

Treating removes what conversion left in a finished cut (mercaptans, residual acids, water,
surfactants); blending assembles finished grades from component streams. They are where a product
specification is actually met. Reached from `tech-refining`.

## Required inputs and missing inputs

Stream to be treated and its mercaptan, total sulfur and acid content, product specification (jet fuel
water separation, copper strip, colour), shipping pattern and storage constraints. Ask for any that is
missing.

## Workflow and tools

Engineering guidance only; core has no calculation for this. Blending quality properties are not
computed by core.

Light gasoline sweetening: dilute caustic and metered air mixed into the feed, a packed bed carrying the
oxidation catalyst, caustic and reaction water drained on level, an air eliminator releasing dissolved air
to a vent incinerator, inhibitor injection. Jet fuel needs a longer train: heater, caustic prewash
neutralising H2S and naphthenic acids, air and reactors, settler, air eliminator and vent tank, water
wash and settler, salt drier, clay filter for surfactants and copper bodies. Kerosene should come from the
crude unit without intermediate storage, because storage ages acids and admits oxygen.

Sour water stripping: foul water cooled and degassed, a fuel-gas blanketed tank with detention for oil to
separate, a stripper with reboiler, acid gas to the sulfur plant, stripped water to reuse.

Blending: batch (flexible, little instrumentation, many tanks), partial in-line (about 5% accuracy
suffices, an orifice meter will do) and continuous in-line (needs 0.25% or better and positive
displacement, venturi or velocity meters; least product storage and quality give-away, but one blender
per product loaded at once and no way to correct an error) (Parkash, *Refining Processes Handbook*,
Elsevier 2003, Ch 10). In-line blending principle: failure to readjust must stop the blend, by stopping
flow or recycling, rather than letting it drift off specification.

Sweetening converts mercaptans to disulfides and leaves total sulfur unchanged, so it is no substitute for
hydrotreating where total sulfur must fall.

## Validation and failure handling

Questions for a flowsheet or P&ID:

- Does a sweetening reactor have separate caustic and air injection each with a mixer, a level-controlled
  drain, and an air eliminator venting to an incinerator behind a flame arrestor?
- Does a jet fuel train show prewash, settler, water wash, salt drier and clay filter in that order, with
  named destinations for spent caustic and wash water in the foul water system?
- On an in-line blender, does each component have its own meter and control valve into a common header?
- Does every product tank show pressure and vacuum relief, and does a fixed-roof tank over a volatile stock
  also show blanketing and vapour recovery?

Caustic carryover into jet fuel is addressed in stages (settler, wash, salt drier, clay filter), none
redundant. Butane is blended into a component through a line before the tank rather than into the tank,
because in-tank butane blending can generate static in a flammable atmosphere. Sour water is degassed
before storage and its tank blanketed. Spent caustic and wash water go to the foul water system, never
open drainage. This skill does not certify any protection.

## Outputs and provenance

The treating route per stream with its basis, the blending mode with its metering accuracy basis, and the
open points.

## Required human judgment

Treating route versus hydrotreating, blending mode, tank roof and vapour handling, specification margins.

## References

- Parkash, *Refining Processes Handbook*, Elsevier 2003, Ch 7 (treating), Ch 9 (sour water), Ch 10
  (blending accuracy and tankage). Retained: blending accuracy figures. Needs review before operational
  use: all treating conditions and tankage day counts were dropped.
- The butane line-blending and static statement is a protective statement not tied to a cited section.
- `tech-refining`, `tech-refining-catalytic-cracking`.
