---
name: unit-ops-heat-transfer
description: One heat exchanger as a unit operation - naming its duty, which fluid goes on tube or shell side, temperature cross and shells in series, air and trim coolers, fouling, and process-side control. Use when an exchanger, condenser, reboiler or cooler is designed or reviewed; sizing is datasheets and heat integration is not computed by core.
---

# Heat exchangers in the process

## Purpose and when to use

What one exchanger does in the process. Hardware (nozzles, vents, isolation, relief) is a P&ID
matter. Sizing (duty, LMTD, area) is the `datasheets` skill. How several exchangers recover heat
together (pinch, targets, network design) is not computed by core; this skill gives no network
method.

## Required inputs and missing inputs

Fluids and states on both sides, duty or terminal temperatures, pressures, fouling tendency,
whether a stream changes phase, and climate for air coolers. Ask for what is missing.

## Workflow and tools

Engineering guidance only; core has no calculation for this beyond `cheme process energy` (duty
from stream enthalpies) and `cheme datasheets fill` (exchanger duty, LMTD and area). Sources:
Ludwig, *Applied Process Design for Chemical and Petrochemical Plants* v3, Elsevier 2001, Ch 10;
Ray and Das, *Process Equipment and Plant Design*, Elsevier 2020, §2.1 to §4.4.

Name the duty, by main purpose: heater/cooler (sensible heat), condenser (all vapour), partial
condenser, cooler-condenser, chiller (refrigerant, below what cooling water reaches), reboiler,
vaporiser, waste heat boiler, cross exchanger (process to process). The name says which stream
matters, which side can foul, and what happens on loss of the other stream.

Fluid allocation, shell-and-tube and double-pipe (Ray and Das §3.2.4), preliminary only:

- Tube side: the hotter fluid; the dirty or fouling fluid and slurries (tubes are easier to clean
  and run faster, so cooling water is normally in the tubes); the more hazardous or expensive
  fluid; the higher-pressure fluid; the corrosive fluid (only the tubes need the alloy).
- Shell side: the more viscous fluid; a condensing vapour; the fluid with the tighter pressure-drop
  limit or poorer heat-transfer properties.
- The source gives flow rate on both sides, so it is a weak criterion. On finned exchangers the
  fins go on the side with the poorer film coefficient. Where criteria conflict, ask which the
  design followed.

Temperature cross and shells: when the hot outlet is colder than the cold outlet there is a cross.
Counter-current takes the largest cross with least area; a single multipass shell takes a limited
one; co-current cannot cross and is chosen for a reason (capping a fluid's temperature, thinning a
viscous cold fluid). A multipass unit's mean temperature difference is the counter-current one
times a factor F. Keep F above roughly 0.75 to 0.8 (the sources differ slightly; higher at extreme
heat-capacity ratios); F is 1 when one side does not change temperature. Remedies: shells in
series, more shell passes, or a double-pipe unit. Shells in series on a flowsheet often mean a
cross or close approach, but can also come from shell size limits: ask. End temperatures can
mislead where a phase changes (desuperheating then condensing, heating then boiling): rate such
duties zone by zone.

Air coolers and trim coolers (Ludwig Ch 10): air cooling avoids water scaling and treatment but
cannot approach ambient closely, costs more capital, and is limited for gas (low tube-side
coefficient) and vacuum service (pressure drop). The economics favour roughly 30 to 40 F (17 to
22 K) between ambient air and fluid outlet. An air cooler followed by a water trim cooler is a
common train. Air coolers respond quickly to weather; outlet control by louvers, fan pitch or
speed. Outlet control does not prevent freezing; where it is possible the air is warmed (steam
coil, recirculation) (Toghraei, *P&ID Development*, Wiley 2019, §11.9.2). The sources give no
method to split duty between air and trim cooler; it is a project choice.

Fouling: the allowance is a margin chosen on cost, so a new clean exchanger over-performs; ask
what that does to the stream it overshoots. It costs a high-coefficient exchanger more. Fouling
raises pressure drop as well as cutting duty. Dirty fluids fast and in the tubes; cooling water
below about 1 m/s scales heavily. Widening the bundle for fouling area lowers velocity. For severe
fouling consider a spare. Deposits that crystallise on a cold wall are not treated by these sources.

Control from the process side (Toghraei §15.8.1): sensor on the target stream's outlet; valve
normally on the other stream. A utility exchanger is throttled on the utility (many cooling-water
coolers carry no temperature control; throttling lowers velocity and speeds scaling). A
process-to-process exchanger is normally controlled by bypass, with a utility trim exchanger if
the swing matters downstream; the equipment downstream must tolerate the unexchanged temperature.
A heat-recovery exchanger often has no control; a utility exchanger follows it. A steam heater is
controlled on the steam with a trap on the condensate (or a level-controlled condensate pot), and
partial flooding is a deliberate manufacturer-agreed alternative. A column condenser or reboiler
is controlled with the column (`unit-ops-distillation`). Running with part of a stream bypassed
lowers flow through the exchanger and speeds fouling; the sources do not resolve this (Ray and Das §4.1.2).

Feed/effluent interchanger (hydrotreating and similar): typically uncontrolled, closely matched,
limited by pressure drop at high pressure (Ray and Das §5.3.2; Toghraei §15.8.3). It couples feed
and effluent at shutdown and cooldown; the sources do not treat its feedback with an exothermic
reactor or the start-up heater it implies, so raise those as questions.

## Validation and failure handling

Check results from `cheme datasheets fill` against the reasoning above (F, cross, allocation).
Do not report an exchanger as wrong on allocation alone.

## Outputs and provenance

Name each exchanger's duty and kind (process or utility), side allocation and why, whether a cross
explains its shells, how it is controlled, and the fouling allowance. Separate what the design
shows from what needs the datasheet or heat balance.

## Required human judgment

Allocation, fouling margin, winterisation and control philosophy need a person.

## References

- Ludwig v3 Ch 10; Ray and Das §2.1, §2.3, §2.6.1, §3.1, §3.2.4, §3.2.5, §4.1.2, §4.4, §5.3.2;
  Toghraei §11.9.2, §15.8; Parkash, *Refining Processes Handbook*, Gulf 2003, Ch 1 to 3.
- `datasheets`, `unit-ops-distillation`.
- Retained as general method: duty naming, allocation reasoning, F-factor logic.
- Needs review before operational use: F floor, 17 to 22 K air approach, 1 m/s water velocity.
  Source citations to Karre (De Gruyter 2023) were dropped as unchecked.
