---
name: flowsheet-diagram-types
description: What belongs on a BFD, PFD, P&ID and the utility, flare and tie-in drawings, how they differ, and which conventions are universal and which are project-specific. Use when deciding what a drawing should contain or which drawing a question is about.
---

# Flowsheet diagram types

## Purpose and when to use

Much confusion about a drawing is confusion about which drawing it is. Use this to decide what is
in scope for a BFD, PFD or P&ID before adding or reviewing content. In core the BFD and PFD are
generated from YAML (skill `process-design`) and the P&ID is drafted from the PFD (skill
`pid-draft`).

## Required inputs and missing inputs

Which drawing the question is about, and the project's own drawing conventions (line-number
format, symbol set, whether lines may cross). If the project conventions are unknown, ask.

## Workflow and tools

Engineering guidance only; core has no calculation for this.

**Block flow diagram.** Named blocks joined by named streams. Each block states what is done at
that step, not how (Coker, *Petroleum Refining Design and Applications Handbook* v2, Wiley 2021,
§14.5.1). It fixes project scope and is often approved by the customer before the next phase
(Karre, *P&ID: A Stepwise Approach*, De Gruyter 2023, §1.5). Its standing varies: some traditions
gate a phase on one, others treat it as a simplification of the PFD, so treat it as a scoping and
communication device unless the project gates on it.

**Process flow diagram.** Adds equipment, connectivity and conditions: major equipment, main
piping, flow direction, operating pressures and temperatures, major controlling instruments
(Parisher and Rhea, *Pipe Drafting and Design* 4e, Elsevier 2022, Ch 7). Lines are labelled so
the mass and energy balance can be read off (Moran Ch 3). Instruments are usually not individually
numbered. It carries the heat and material balance, often confidential know-how, so its
readership is deliberately narrower than a P&ID's (Coker §14.5.2); some companies forbid a drawing
that combines the two.

**P&ID.** All equipment, all operating and isolating valves, all instrumentation including
transmitters, line numbers, sizes, piping specification, insulation and service codes, alarms,
interlock valves and relief protection. The order of equipment, valves, instruments and
connections along each line is information, not drafting taste. Pipe lengths and bends are
deliberately absent (Coker §14.5.3): they belong to isometrics, with coordinates and elevations.

The difference between PFD and P&ID is "major" and "main" against "all", so "what is missing
from this PFD?" is answerable: line numbers, size and specification per line, isolation valves,
transmitters, completeness of equipment and instrument sets. A missing isolation valve is a
defect on a P&ID and out of scope on a PFD.

The three drawings are not drafts of one another: PFD integrates the balance, P&ID integrates
control and the system, general arrangement integrates physical and hydraulic constraints, at
every stage (Moran Ch 6).

**Kinds of P&ID** (Karre §1.8): process P&IDs organised around a major item; utility P&IDs, split
into production and distribution; flare and disposal P&IDs; utility line diagrams carrying the
tie-in sequence (header sizes depend on the order units are served, which the plot plan fixes,
Coker §14.5.5); legend sheets; tie-in, demolition, battery-limit, vendor-scope and auxiliary
drawings. Vendor scope is a bounded box showing the crossing connections and is developed last.
Not every relief device discharges to a flare: thermal relief back into the line, a safe
atmospheric steam vent and tank breathing sit outside. The check is that each device has a named
destination.

**Conventions.** Broadly agreed: flow left to right; horizontal and vertical lines only; flow
arrows on every line; feeds labelled with where they come from and products by name; no scale, so
position and symbol size are not data. Project-specific, so check: whether lines may cross at
all, the line-number format, symbol shapes, equipment numbering, items per sheet.

## Validation and failure handling

Nothing here is checked by cheme. A report that something is "missing" should first state which
drawing was meant.

## Outputs and provenance

State the drawing type assumed and the conventions taken from the project rather than from a
textbook.

## Required human judgment

Whether the project gates on a BFD, which conventions apply and what each drawing must contain
are project decisions.

## References

- Coker, *Petroleum Refining Design and Applications Handbook* v2, Wiley 2021, §14.5.1-14.5.5.
- Karre, *P&ID: A Stepwise Approach*, De Gruyter 2023, §1.5, §1.8.
- Parisher and Rhea, *Pipe Drafting and Design* 4e, Elsevier 2022, Ch 7.
- Moran, *An Applied Guide to Process and Plant Design*, Elsevier 2015, Ch 3, Ch 6.
- The textbooks disagree on the standing of the BFD and on line-crossing and line-code
  conventions; the skill states this instead of choosing. Needs review before operational use:
  the confidentiality remark on PFDs is one author's view.
