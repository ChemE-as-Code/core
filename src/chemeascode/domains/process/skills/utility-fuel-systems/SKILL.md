---
name: utility-fuel-systems
description: Fuel gas conditioning, the mixing drum and liquids in the gas, the fuel train from header to each burner with its shutdown valves and pilot, and fuel oil circulation. Member of utility-systems.
---

# Fuel systems

## Purpose and when to use

A fuel system delivers gas or oil of steady quality at steady pressure and must never let fuel into
a firebox that is not lit. Most of what a drawing must show is the second half. Hub: skill
`utility-systems`.

## Required inputs and missing inputs

Fuel composition and whether it is sweetened, the project's fluid codes for fuel gas and fuel oil,
the burner type (pilot or direct igniter), and the integrity basis from the hazard study for the
shutdown valves. Ask for them.

## Workflow and tools

Engineering guidance only; core has no calculation for this.

**Fuel gas.** Refinery and gas-plant fuel gas is off-gas collected from process streams and
carries hydrogen sulfide, so it is sweetened before firing: suction knockout drum, compression and
cooling, discharge knockout drum, amine contactor, acid gas to sulfur recovery (Karre, *P&ID: A
Stepwise Approach*, De Gruyter 2023, §6.2.9). Gas plants typically run separate high- and
low-pressure fuel-gas systems (Mokhatab, Poe and Mak, *Handbook of Natural Gas Transmission and
Processing*, Elsevier 2015, §3.5.1). A mixing or balance drum evens out heating value and density,
since burners are designed for a particular gas; it carries mixing baffles, a heating coil to
vaporise carried-over liquid, a flare connection and a make-up route (Parkash, *Refining Processes
Handbook*, Gulf 2003, Ch 10).

**Liquid in fuel gas** is a hazard the sources agree on and treat three ways: knock it out in
drums and pots with drains (Karre §6.2.9, §8.10.14), vaporise it with a coil in the drum (Parkash
Ch 10), or for a gas turbine reheat the gas above its dew point after knocking out (Mokhatab
§15.5). A turbine supplier's margin is that supplier's figure, not a general rule. Where burners
are fed from gas that can carry liquid with none of these, ask. The sources frame hydrogen sulfide
as a sweetening problem and do not treat exposure at the burner; do not take silence as
clearance. On unsweetened gas, or during a sweetening upset, bleeds, vents and knockout-pot drains
release flammable and possibly toxic gas; ask where each discharges (flare, closed drain or a safe
elevated point), not at grade near the heater (general guidance, uncited).

**Fuel train to a fired heater**, in flow order (Toghraei, *P&ID Development*, Wiley 2019,
§11.12.3, §11.13): fuel preparation (pressure regulator, filter, often duplex); a shutdown valve
block (two in series with a vent between them is the common arrangement on gas; a single shutdown
valve on main or pilot fuel is a question to raise); a control valve station; a burner header with
a shutdown valve on each burner branch. Isolation valves sit after the fuel header, before the
burner header and upstream of each burner, with small valves for draining, venting and purging. A
pilot burns an easily lit fuel from a separate network or through its own regulator upstream of
the main shutdown valves; its line has its own shutdown valve and no control station. Fuel
shutdown valves fail closed. Some burners use a direct igniter.

Karre §8.10.14 adds for a heater: knockout pots with drains; double block and bleed where
required; proof-of-closure switches on shutdown valves; low and high fuel-pressure interlocks and
a low-fire start; manual shut-offs at a safe distance; bypasses round fuel control valves
car-sealed closed; and no bypass round a fuel shutdown valve at all, since it defeats the
flame-failure and fuel-pressure trips. A boiler's burner management is the same idea (Karre
§8.10.16). Two valves in series are a claim about integrity, not evidence of it; ask for the basis
before describing a fuel train as adequately protected.

**Fuel oil.** A furnace that must run without fuel gas (refinery start-up) needs oil firing too
(Parkash Ch 10). The oil circulates (Parkash Ch 10; Toghraei §11.13): a ring main under pressure
control with part returning to storage, a ring header across the burners at each heater; heated to
atomising viscosity with traced lines; two positive-displacement pumps that do not share a failure
(one source pairs a motor with a steam turbine; two motors on separate supplies serve the same
purpose); relief on pump discharge and heaters returning to the tank, and strainers at pump suction
and discharge; atomising steam or air where burners need it (Karre §8.10.14; Toghraei §11.12.3).
Storage days, pump margins and burner pressures are design basis, not drawn.

## Validation and failure handling

Nothing here is checked by cheme. Gaps are questions or findings for the hazard study. Whether the
shutdown valves and interlocks reach the integrity the project needs is the hazard study's
question, never settled by the drawing or this skill.

## Outputs and provenance

Where the fuel gas comes from and how liquids are kept out; for each heater the shutdown valves,
per-burner valves, pilot and interlocks; whether an oil supply exists where the heater must run
without gas; the integrity questions handed back.

## Required human judgment

Integrity of the burner management and shutdown valves, vent and drain destinations, and fuel
oil system design.

## References

- Karre 2023, §6.2.9, §8.10.14, §8.10.16. Toghraei 2019, §11.12.3, §11.13. Parkash 2003, Ch 10.
  Mokhatab, Poe and Mak 2015, §3.5.1, §15.5.
- Sources disagree on how liquids are kept out of fuel gas. Needs review before operational use:
  the Karre heater list is one book's list, not a code requirement, and every item on it, plus
  the shutdown-valve arrangement, is safety-critical; the vent-destination statement is uncited.
