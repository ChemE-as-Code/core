---
name: tech-petchem-aromatics
description: Process knowledge for a BTX aromatics complex - extraction and solvent loop, benzene/toluene fractionation, transalkylation, xylene splitter, paraxylene recovery by adsorption or crystallisation, xylene isomerisation - with recycles and purges. Use when drafting or reviewing an aromatics flowsheet.
---

# Aromatics extraction and the xylene loop

## Purpose and when to use

Reached from `tech-petrochemicals`. An aromatics complex takes reformate or hydrotreated pyrolysis gasoline and makes benzene, paraxylene and usually
orthoxylene, recycling toluene and heavy aromatics to extinction. Extraction involves no reaction; the reaction units (methyl transfer, xylene isomerisation
over zeolites) are adiabatic, while toluene hydrodealkylation is strongly exothermic and must be quenched.

## Required inputs and missing inputs

Feed (reformate or pyrolysis gasoline, ethylbenzene content), product slate, recovery targets. Energy figures from the source are on different bases and are not comparable.

## Workflow and tools

Engineering guidance only; core has no calculation for this (separation arrangement screening is in `separation-method-selection`; extraction and adsorption have
specified-split representations only). Units:

1. Feed preparation: naphtha hydrotreating and reforming; pyrolysis gasoline needs diolefin saturation; a reformate splitter cuts C7 minus for extraction.
2. Aromatics recovery by liquid-liquid extraction (extractor, raffinate wash, stripper, vacuum solvent recovery) or extractive distillation (solvent on top tray, vacuum stripper); solvent in a closed loop.
3. Benzene and toluene fractionation, with clay treating or catalytic olefin removal to hold bromine index.
4. Transalkylation or disproportionation over a zeolite with hydrogen present, separator and stabiliser.
5. Xylene splitter, orthoxylene column, heavy aromatics column.
6. Paraxylene recovery by adsorption (rotary valve stepping feed, extract, raffinate and desorbent along beds, two desorbent columns) or crystallisation (centrifuges, wash column).
7. Xylene isomerisation with hydrogen, separator with purge, deheptaniser.
8. Recycles: isomerised C8 to the splitter, toluene and C9+ to transalkylation, desorbent from both product columns, lean solvent to the extractor.

| Item | Source value |
|---|---|
| Aromatics recovery | above 99 to 99.5 % |
| Paraxylene, adsorption | 99.9 wt% at over 97 % per-pass recovery |
| Paraxylene, crystallisation | 99.8 wt%, up to 95 % recovery, feed enriched to 75 to 95 wt% |
| Hydrodealkylation | 500 to 600 degC, up to about 69 bar (1,000 psi) |

Control handles: solvent circulation rate (trades against reboiler duty); methyl-to-ring ratio in the feed; a purge on each hydrogen loop; in adsorption, valve step time and desorbent
circulation; multi-point hydrogen quench in hydrodealkylation. Extractive distillation tends to suit benzene/toluene-rich feeds; liquid-liquid wider C6 to C9 cuts.

## Validation and failure handling

Questions to put to the design:

- Do toluene and heavy aromatics have a return path rather than a product outlet? Does lean solvent return in a closed loop?
- Does every hydrogen recycle loop carry a purge, and does a deheptaniser or stripper sit between the isomerisation reactor and the xylene splitter (cracked light ends accumulate otherwise)?
- Do both product columns of an adsorptive separation return desorbent? Does the extract reach bromine-index treatment before fractionation?
- Is solvent recovery under vacuum to keep bottoms below solvent degradation, and are heat tracing and drain-down considered for a high-melting solvent?
- Does a hydrogen purge have a vent absorber so benzene stays out of the fuel header?

## Outputs and provenance

Record the extraction route, xylene loop configuration and sources in `DESIGN.md`.

## Required human judgment

Benzene exposure and hydrogen-system hazards, solvent selection, relief, route choice among extraction and paraxylene technologies. This skill certifies none of them.

## References

- Speight, *Handbook of Industrial Hydrocarbon Processes* (Elsevier 2011), Ch 11.
- Independently verifiable general method: closed solvent loop, recycle-to-extinction logic, purge on hydrogen loops.
- Needs review before operational use: purity and recovery figures, energy comparisons, loop feed tolerances (omitted), the safeguard statements.
