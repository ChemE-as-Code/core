---
name: tech-refining-residue-upgrading
description: Reference for vacuum residue upgrading. Delayed coking, visbreaking and solvent deasphalting, with the coil and drum cycle, decoking and blowdown systems, the soaker coil and quench loop, and the extractor and solvent recovery train. Use when residue conversion units are being discussed or reviewed.
---

# Residue upgrading

## Purpose and when to use

These units reduce or destroy vacuum residue rather than selling it. Coking converts it to
distillates and solid coke, visbreaking only lowers viscosity and pour point so less cutter stock is
needed, and solvent deasphalting splits it into a clean oil and an asphalt without cracking.
Reached from `tech-refining`.

## Required inputs and missing inputs

Residue properties (gravity, carbon residue, sulfur, metals), the desired products (coke grade, tar
specification, deasphalted oil use), and what the refinery does with the heavy product. Ask for any that
is missing.

## Workflow and tools

Engineering guidance only; core has no calculation for this.

Delayed coker: fresh residue enters the fractionator bottom, where it mixes with condensed recycle, and
that combined stream goes to the heater; coil steam injection holds velocity; a switch valve
directs flow to one of at least two coke drums, one filling while the other is decoked; drum overhead
returns to the fractionator quenched and washed; the fractionator carries a heavy gas oil pumparound,
side stripper, sponge oil loop and overhead drum; a vapour recovery section; a blowdown system taking
every drum vent; and decoking water systems with cutting pump and coke settling. Decoking follows a
sequence (steam out, water fill and cool, drain, unhead, hydraulic cut, rehead and test, warm up) so no
step opens a hot drum to air.

Visbreaker: single-pass heater with soaking coils (a standby heater and permanent steam and air
decoking connections), effluent quenched with cracked gas oil, a main fractionator with stabiliser, and
a tar sump cooled to stop coke forming. Heater outlet temperature and coil profile are the severity
handle; running hotter than optimum makes unstable tar and shortens the run.

Solvent deasphalting: feed with predilution solvent into the middle of an extractor, solvent entering
at the bottom; deasphalted oil and asphalt each pass heaters, flash towers and steam strippers; solvent
receivers and compressor. The extractor temperature gradient is the main handle on oil yield, since
solubility falls as temperature rises; a heavier solvent gives more oil at lower selectivity.

Choosing: coking destroys residue and makes a solid product; visbreaking leaves a tar to blend; solvent
deasphalting suits a residue worth recovering as catalytic feed. Coke grade follows feed and drum
temperature (sponge, needle, fuel).

## Validation and failure handling

Questions for a flowsheet or P&ID:

- Two coke drums with a switch valve, and a recycle path from fractionator bottom to the heater charge?
- Steam injection connections on every coker coil, and a quench loop from the side stripper to the
  visbreaker heater outlet?
- A blowdown drum and settling drum with a flare connection collecting drum vents, and decoking
  water storage, cutting pump and coke settling?
- A separate condenser on asphalt flash vapour and predilution solvent ahead of the extractor in
  deasphalting?
- Do sour water streams go to stripping rather than drains?

During decoking the visbreaker tubes are designed for a metal temperature that is higher than the local
burn temperature the operators hold; the first is a rating, the second an operating limit. Ask which
the figure refers to. Sour water injection at the coker compressor addresses cyanide corrosion. This
skill does not certify any protection.

## Outputs and provenance

Unit choice with its basis and indicative conditions stated as from one worked case.

## Required human judgment

Conversion choice, drum cycle and decoking procedure, run length and severity, solvent choice.

## References

- Parkash, *Refining Processes Handbook*, Elsevier 2003, Ch 6 (worked cases: coker heater outlet about
  927 degF, drum pressure 15-35 psig; visbreaker soaking coil about 883 to 920 degF; deasphalting oil
  yields 65-85 LV%). Indicative only; needs review before operational use.
- `tech-refining`, `tech-refining-crude-and-vacuum-distillation`.
