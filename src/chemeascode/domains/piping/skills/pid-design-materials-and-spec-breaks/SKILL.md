---
name: pid-design-materials-and-spec-breaks
description: Where a piping class should change, whether a spec break sits in the right place, and which service changes should prompt a metallurgy question. Covers what a P&ID carries, where a break belongs by feature, the lower-rated-side protection question, and what a P&ID never settles. Use when asked about piping class changes, spec breaks or material choice.
---

# Piping classes, spec breaks and materials

## Purpose and when to use

A P&ID does not say what a pipe is made of. It gives a piping class, a short project code that
points into a material specification table holding material, wall thickness, corrosion allowance,
flange rating and branch table (Toghraei, *P&ID Development*, Wiley 2019, §6.3.3). The table is
not in the model. So: what can be checked, what can only be asked, what the drawing never settles.

## Required inputs and missing inputs

The class register (ask for it), line list with class and fluid code, design pressure and
temperature of each side of a suspected break, minimum design metal temperature, corrosion study
if any. A class code you cannot resolve is a code, not a material: never infer metallurgy from its
spelling. Line tags may encode class as a field (Karre, *P&ID: A Stepwise Approach*, De Gruyter
2023, §3.3) but field order is project-specific; confirm it.

## Workflow and tools

Engineering guidance only; core has no calculation for this. `cheme validate` and `cheme show`
find the classes and line numbers the sheet carries; `lists-sync` keeps them aligned with the
line list.

**Where a break belongs.** A break is realised as a flange, a block valve, or a block valve with a
check valve; the flange is the default, and the more robust spec covers the valve (Toghraei
§6.4.1). In a relief inlet or discharge path the break is a flange, since isolation there is a
relief question (`pid-design-pressure-relief`). A break mid-component is wrong; a break mid-run is
wrong for a flanged break, but an all-welded line changes spec at a welded transition spool, so
confirm the transition detail. Put the two class annotations on either side of the point (Toghraei
§18.8.5; Karre §6.3).

**What triggers one**: a change of fluid, temperature or pressure (control valve, orifice or
partly closed valve; pump or compressor; cooler, heater or injected stream; new fluid). Ordinary
friction loss does not, except possibly a long high-flow blowdown line (Toghraei §6.4.2). The
break can sit upstream of the change point: for fluid, to the first block valve on the
non-aggressive side; for temperature, a short distance in metal pipe; for pressure, not by default,
only where back-pressurisation is real, e.g. parallel pumps on a common header.

**Locations often considered** (each drawable once two sides are confirmed different):
- downstream of a relief device, and on its bypass; a bypass kept in the inlet spec to the header
  is conservative (a cost point, not a safety one; Karre §11.5); Toghraei's checklist names a
  missing break on a safety device outlet as a defect (§19.3.3);
- at a control valve station, past the downstream block valve so the bypass stays in the stronger
  spec (Karre §11.1; Toghraei §7.13.1); moving it inside leaves the bypass under-rated
  (`pid-design-control-valve-station`);
- at a letdown station, at each pressure step (Karre §11.2);
- on a pump minimum-circulation line downstream of its control valve (Karre §11.7);
- on pump vents and drains to a header, often with a blind and an insulation change as flags of
  the same break (Karre §11.8);
- on a sample take-off across a pump or filter (Karre §8.5);
- at an equipment nozzle, whose rating follows the container's design pressure (Toghraei §9.9.4).
  A nozzle states a pressure class; a chamber a design pressure; converting needs the standard's
  pressure-temperature table at design temperature. Quote both and put the comparison to the user.
  Carrying a machine's higher discharge rating back to the suction isolation valve is a judgment
  (Toghraei §10.6.8).

**Where the sources part company** (state as one source's practice, not a rule): a break at a
utility tie-in upstream of the isolation valve (Karre §6.3) against backflow prevention and
contamination control only (Toghraei §17.2.5); a break downstream of a steam trap built to a higher
class (Karre §11.3) while Toghraei's trap coverage mentions no spec change.

**The safety point.** Where a pressure-reducing device creates a lower-rated system downstream, the
low side needs protecting (Karre §11.2; Toghraei §18.8.5). A break marks where the rating drops; it
protects nothing. A check valve limits reverse flow, not reverse pressure (Toghraei §18.8.5).
Typical answers: relief on the low side, raising the low side's rating, or an instrumented
function, the last only where its integrity level and scenario can be named
(`safeguard-crediting`). Ask at a utility tie-in whether the utility side is the lower-rated one;
and at a steam trap how the low-pressure side survives blow-through. An instrument tapping may
deliberately be under-rated (Toghraei §18.8.5): not a missing break.

**Metallurgy questions** (never assert a material change from them):
- Where water first condenses: dry carbon dioxide and hydrogen sulfide are not corrosive to steel;
  both need a free water phase (Sotoodeh, *A Practical Guide to Piping and Valves for the Oil and
  Gas Industry*, Elsevier 2021, Ch 13). Ask whether start-up, upset or depressuring wets the line
  earlier; hydrogen sulfide also drives toxicity and cracking requirements when dry.
- Where a phase separates: outlets of one drum may be different classes (Sotoodeh Ch 13).
- Where acid gas flashes from rich solution, or velocity strips a film: erosion-corrosion points in
  an amine circuit, often answered with stainless internals on the let-down valve (Kohl and
  Nielsen, *Gas Purification*, Gulf 1997, Ch 2).
- Where an ammonium salt can deposit: alloy and heat tracing together; wash water must not
  vaporise completely (Mokhatab, Poe and Mak, *Handbook of Natural Gas Transmission and
  Processing*, Elsevier 2015, §5.4.2; Parkash, *Refining Processes Handbook*, Gulf 2003, Ch 3).
- Hot hydrogen: screen on temperature and hydrogen partial pressure together, not total pressure;
  carbon steel becomes susceptible somewhere above about 450 F at a hydrogen partial pressure of
  order 100 psia (Coker, *Petroleum Refining Design and Applications Handbook* v2, Wiley 2021,
  §15.38). Hydrogen damage in wet sour service is a separate question.
- Low temperature: carbon steel to about -29 C, with the exemption lost above about 12.7 mm wall
  (Sotoodeh Ch 15). Ask for the minimum design metal temperature: depressuring through a letdown,
  blowdown or relief device can autorefrigerate far below normal service.
- Chloride and caustic: desalter with caustic downstream; seawater kept out of the process by a
  fresh-water circuit (Parkash Ch 1, Ch 9).
- A chemical injection for corrosion control: ask what happens if it stops; it may equally be
  process chemistry.
- A break between dissimilar metals needs an insulating gasket, drawn as a specialty item
  (Toghraei §6.14.2.1; Sotoodeh Ch 16); a welded dissimilar joint sits in a transition spool
  (Sotoodeh Ch 11).

A corrosion threshold means nothing without its conditions (water phase, pH, temperature, partial
pressure); material selection is the output of a corrosion study (Sotoodeh Ch 13).

**Legitimate breaks and absences.** A break may exist because the spec does not stock the size or
valve (Toghraei §6.3.3). Small-bore piping and small valves carry a rating floor (§18.8.5). Nozzle
ratings and sizes are drawn only when they differ from the pipe, so silence is sameness (§9.9.4).
A change of pressure, temperature or fluid does not always warrant a new line tag; the test is
whether the class changes (§6.2.2.2).

## Validation and failure handling

Break position is judged across sheets: a class boundary, utility tie-in and relief tailpipe often
cross drawings. Say which sheets were read; report what could not be closed as unchecked, not as
a break. Keep a difference that is only inferred a question; it becomes a finding when the
differing classes or conditions are on the drawing or supplied.

## Outputs and provenance

Sheets read; classes resolved and absent; breaks found with their feature; places where conditions
differ and no break is drawn; lower-rated systems exposed to higher pressure; metallurgy questions
raised, separate from anything checked.

## Required human judgment

Class register, break placement, protection of lower-rated systems, material selection: piping
and materials engineers.

## References

Toghraei §6.2.2.2, §6.3.3, §6.4.1, §6.4.2, §6.14.2.1, §7.13.1, §9.9.4, §10.6.8, §17.2.5, §18.8.5,
§19.3.3; Karre §3.3, §6.3, §8.5, §11.1 to §11.8; Sotoodeh Ch 11, 13, 15, 16; Kohl and Nielsen Ch 2;
Mokhatab, Poe and Mak §5.4.2; Parkash Ch 1, 3, 9; Coker §15.38. Needs review before operational
use: all temperature, pressure and wall-thickness figures, and every section number (inherited).
