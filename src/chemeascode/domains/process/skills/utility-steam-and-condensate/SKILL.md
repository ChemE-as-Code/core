---
name: utility-steam-and-condensate
description: Steam header levels and letdown, desuperheating and low-side relief, trap stations and drip legs, condensate return and contamination, and steam users with their own arrangement. Member of utility-systems.
---

# Steam and condensate

## Purpose and when to use

A steam system is a cascade: raised at the top level, let down through lower ones, condensed at the
users and returned. Most drawing problems are at the joins: a letdown with nothing protecting the
header below it, a control valve fed wet steam, condensate that should not have been returned.
Hub: skill `utility-systems`.

## Required inputs and missing inputs

The project's steam levels and how its fluid codes and line numbers mark them, and the users on
each header. Ask when missing; one project's steam code is another's condensate.

## Workflow and tools

Engineering guidance only; core has no calculation for this.

**Levels are site-specific.** One reference gives 600, 250 and 50 psig (Karre, *P&ID: A Stepwise
Approach*, De Gruyter 2023, §6.2.1); a refinery reference gives 900, 475, 150 and 50 psig, higher
with in-house power (Parkash, *Refining Processes Handbook*, Gulf 2003, Ch 10). Neither is a
standard.

**Header cascade.** Each header is fed from above: boilers and waste-heat boilers at the top,
turbine exhaust and letdown below. A letdown is usually paired with desuperheating. Surplus at
the lowest level is normally condensed and returned, though a pressure-controlled vent through a
silencer is also common; that vent is a control, not the header's relief device. The deaerator sits
on the lowest header (Parkash Ch 10; Ray and Das, *Process Equipment and Plant Design*, Elsevier
2020, Ch 18). A header carries some superheat so transit losses do not condense it (Ray and Das
Ch 18). A back-pressure or extraction turbine between two levels recovers as work what a letdown
throws away; where both exist the letdown makes up the rest (Karre §2.11; Parkash Ch 10).

**Letdown station** (Karre §11.2; Basu and Debnath, *Power Plant Instrumentation and Control
Handbook*, Academic Press 2019, Ch 1, 3): a pressure-reducing valve on the lower header's pressure
in a block and bypass arrangement, the bypass also warming the line. An open bypass is a second
path onto the lower header, so low-side relief must cover it wide open, or the bypass is
restricted or car-sealed closed. A desuperheater downstream spraying boiler feed water or
condensate on temperature control, with a check valve on the spray water. A relief valve on the
low-pressure side, because a letdown valve failing open puts upstream pressure onto the whole
lower network; it need not sit at the station, so check the lower header's rating and any relief
elsewhere on it before reporting one missing. A control vent is not one. Discharge to a safe
location, away from people (Karre §11.2, §8.2). Where demand swings widely, two letdown stations
of different capacity may run in parallel (Basu Ch 3). A letdown without a desuperheater is not
automatically a defect: one reference exports the first step down as it is (Karre §11.2) and no
source gives a rule for omitting it, so ask whether the lower-header users can take the superheat.

**Trap stations.** A trap passes condensate and holds steam back: on a main it stops two-phase flow
and hammer, at an exchanger outlet it keeps steam in the exchanger (Ray and Das Ch 16). One trap
per collection point (a line or an item of equipment); steam tracing is the stated exception. One
trap draining two parallel exchangers is a finding, since the faster condenser starves the other;
shells in series on the steam side are one collection point. Station: bleeder, block valve,
strainer, trap, block valve, bleeder, so the trap can be removed and tested (Ray and Das Ch 16); a
trap with a built-in strainer needs no separate one; the trap carries no instrumentation (Basu
Ch 1). A bypass round the trap is contested: one reference draws one (Ray and Das Ch 16), another
shows none (Karre §11.3), and many companies forbid one because an open bypass passes live steam
into the condensate system (Toghraei, *P&ID Development*, Wiley 2019, §6.9.1). Follow the project;
do not report its absence. Ahead of a control valve on saturated steam a trap is wanted, since
condensate cuts capacity and upsets control; on superheated steam it may be unnecessary (Karre
§11.3). Drip legs on a main collect condensate at low points and intervals, each ending in a trap;
the interval is layout and heat loss, and the sources differ widely (Ray and Das Ch 16, 18; Karre
§11.3). Take branches from the top of the header (a note only, Karre §8.2). Trap and relief
discharges go to a safe location, since both can scald (Karre §8.2). One reference puts the trap
in a higher piping class with a spec break downstream (Karre §11.3); the other does not mention it.

**Condensate return.** Cascaded: high-pressure condensate flashes in a medium-pressure drum whose
flash steam joins that header, again at low pressure, then an atmospheric flash drum, then pumped
to the deaerator (Karre §6.2.1). Returned condensate is feed water in waiting, so what it might
carry matters. A refinery reference treats two returns differently (Parkash Ch 9): surface-condenser
condensate is clean unless a cooling-water tube leaks, so its header has conductivity monitoring
with two set points (divert to a utility-water tank, then dump to sewer); process-equipment
condensate may carry oil, so it passes activated carbon and a polisher, cooled first because resin
is temperature sensitive. Contaminated condensate must not reach a boiler, where it foams and fails
tubes; process condensate returned to feed water with no detection and no means of diverting it is
a finding. Where the process side runs above the steam pressure (a reboiler on a pressurised
column, a heater on light hydrocarbon), a tube leak puts hydrocarbon into the condensate and it
flashes out of the next flash drum or deaerator vent: ask where that release goes. Heating steam
in remote areas may be dumped rather than returned (Parkash Ch 10).

**Users with their own arrangement.** A steam turbine takes an inlet strainer and a trap ahead of
it and a safety valve downstream against exhaust-piping overpressure (Karre §2.11, §8.10.9). An
ejector's motive steam passes a strainer or knockout drum with a trap upstream; a spare ejector is
recommended (Karre §11.20). A utility station's steam comes from the low-pressure header through a
block valve and a check valve to a hose connection (Karre §11.21). An atmospheric steam vent may
carry a silencer; no source gives a rule for when it is required, so a missing one is a question.

## Validation and failure handling

Nothing here is checked by cheme. Present gaps as questions or findings; check the lower header's
rating and other relief before reporting a missing letdown relief.

## Outputs and provenance

The levels the project uses and how identified; each letdown with its low-side relief and
desuperheating; traps found, including any serving more than one collection point; how returned
condensate is protected against contamination; items asked about rather than checked.

## Required human judgment

Header relief sizing, desuperheater need, trap bypass policy, condensate contamination
monitoring and release destinations.

## References

- Karre 2023, §2.11, §6.2.1, §8.2, §8.10.9, §11.2, §11.3, §11.20, §11.21. Parkash 2003, Ch 9-10.
  Ray and Das 2020, Ch 16, 18. Basu and Debnath 2019, Ch 1, 3. Toghraei 2019, §6.9.1.
- Sources disagree on steam levels and on a trap bypass; sources are silent on when a letdown may
  omit its desuperheater and when a vent needs a silencer. Needs review before operational use:
  the low-side relief and process-leak contamination statements are protective guidance.
