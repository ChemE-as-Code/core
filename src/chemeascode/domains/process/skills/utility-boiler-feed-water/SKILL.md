---
name: utility-boiler-feed-water
description: Water grades from clarified to demineralised, the deaerator and what protects it, feed pumps, chemical dosing points, condensate polishing, and boiler level protection and blowdown. Member of utility-systems.
---

# Boiler feed water

## Purpose and when to use

Boiler feed water is water a boiler can survive: free of hardness, low in oxygen, dosed to stay
slightly alkaline and, for higher-pressure boilers, low in dissolved solids. Each treatment step
removes something that would scale or pit tubes, so each has a place on the drawing. Hub: skill
`utility-systems`.

## Required inputs and missing inputs

Boiler pressure and type (drum or once-through), the boiler code the project follows, the water
treatment regime, and the project's fluid codes for each water grade. Ask for these before calling
anything missing.

## Workflow and tools

Engineering guidance only; core has no calculation for this.

**Grades.** Clarified water (suspended solids removed; utility stations, cooling-tower make-up,
cleaning; Karre, *P&ID: A Stepwise Approach*, De Gruyter 2023, §6.2.6). Soft water (sodium-cycle
cation exchange removes calcium and magnesium; regenerated with brine; §6.2.7). Demineralised
water (cation then anion beds; aggressively corrosive, so stored and pumped in stainless steel or
other resistant or lined material; Karre §6.2.8; Parkash, *Refining Processes Handbook*, Gulf
2003, Ch 9). Which grade feeds the deaerator depends on boiler pressure and the sources do not
settle it: one makes up with softened water (Karre §6.2.7), a refinery reference uses
demineralised water for low-pressure boilers and polished condensate for high-pressure ones
(Parkash Ch 9). Ask what the boilers are rated for.

**Deaerator.** Strips dissolved oxygen and carbon dioxide with steam; it also heats and stores the
water and, being elevated, gives the feed pumps suction head (Basu and Debnath, *Power Plant
Instrumentation and Control Handbook*, Academic Press 2019, Ch 2; Karre §6.2.7). It wants steam to
the deaerating and storage sections, a vent to atmosphere, an overflow, and the feed pumps below
it. As a pressure vessel on a steam supply it also needs overpressure protection for the steam
supply failing open, and vacuum protection unless designed for vacuum (uncited general guidance;
relief sizing is a question for the relief study). Its operating pressure is a design choice and
the sources' figures range from well under 1 kg/cm2 to the lowest steam header (Ray and Das,
*Process Equipment and Plant Design*, Elsevier 2020, Ch 18; Karre §6.2.7; Parkash Ch 10). Spray
deaerators are usual in process plants, tray types in power plants (Basu Ch 2). Mechanical
deaeration comes first, a chemical scavenger follows (Basu Ch 2). Small package boilers sometimes
run from a vented hot feed tank with a scavenger, so a missing deaerator there is a question.

**Feed pumps.** Minimum-flow recirculation to the deaerator taken between each pump and its check
valve; a standby pump starting on low discharge pressure (Basu Ch 3). They need far more suction
margin than ordinary pumps because they draw near-saturated water (Ray and Das Ch 16; Karre §6.2.7).

**Dosing** (drum boiler on phosphate treatment; Basu Ch 2, Ch 5): oxygen scavenger at feed pump
suction after the deaerator; pH control (amine or ammonia) on the condensate side, after any
polisher; phosphate into the drum. Other regimes dose differently (some add no phosphate; some
once-through boilers dose no scavenger), so read the project's treatment before calling a point
missing. Hydrazine is losing favour on health grounds, with lower-toxicity alternatives (Basu
Ch 5; Parkash Ch 10); where dosed, its closed transfer and exposure protection are in scope.

**Polishing.** Depends on boiler pressure: below roughly 40 kg/cm2 usually omitted, above that
usually needed, essential for once-through (Basu Ch 2); a refinery polishes condensate for its
high-pressure boilers (Parkash Ch 9). Some plants rely on monitoring and dumping, so ask before
reporting one missing. Resin is temperature sensitive, so hot condensate is cooled ahead of it.
Condensate sources and contamination: skill `utility-steam-and-condensate`.

**The boiler.** Relief and trip requirements are set by the boiler code the project follows; this
is where to start, not a pass mark. Safety valve count and location follow the code; a superheater
or economiser that can be isolated needs its own relief; discharge to a safe location (Karre
§8.10.16). Drum level protection: several independent level measurements, trips on very high
level (water carried into steam) and very low level (starved tubes) (Basu Ch 8). Blowdown:
continuous, controlled on flow or conductivity where size and treatment call for it, and
intermittent from the lowest point; blowdown flashes, so it goes to a blowdown vessel or flash
tank and is cooled before any drain (Karre §8.10.16; Basu Ch 2, Ch 5). Where fired, burner
management: see `utility-fuel-systems`. A kettle steam generator raising steam from process heat
is a boiler in miniature: level control, continuous blowdown, a relief valve to a safe location
(Karre §11.18).

## Validation and failure handling

Nothing here is checked by cheme. Treat missing items as questions about the regime, pressure or
code, not as defects. Whether level trips and relief are sufficient is for the hazard study and
the boiler code; the presence of several level measurements does not establish independence.

## Outputs and provenance

The grades used and how identified; the deaerator's steam, vent, overflow, overpressure and vacuum
protection and its height above the pumps; where each chemical is dosed and how hydrazine is
handled; the boiler's relief, level trips, blowdown route and burner management; the questions put
to the project.

## Required human judgment

Water-treatment regime, boiler code compliance, relief and trip integrity, and chemical handling.

## References

- Karre 2023, §6.2.6-6.2.8, §8.10.16, §11.18. Parkash 2003, Ch 9-10. Basu and Debnath 2019, Ch 1-3,
  5, 8 (power-plant handbook; turbine drain pots, regenerative heater trains and unit-size
  polishing thresholds were not carried because they do not transfer to a process plant). Ray and
  Das 2020, Ch 16, 18.
- Sources disagree on deaerator pressure and make-up grade. Needs review before operational use:
  the deaerator overpressure/vacuum statement (uncited) and the 40 kg/cm2 polishing threshold,
  which is a rule of thumb for drum boilers.
