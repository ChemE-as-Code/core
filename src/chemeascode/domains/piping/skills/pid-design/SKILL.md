---
name: pid-design
description: Index of the P&ID design-guidance skills (pumps, compressors, vessels and tanks, heat exchangers, control valve station and selection, instrumentation, isolation vents and drains, pressure relief, piping classes and spec breaks) and the review skills, with the questions common to all. Use when deciding what belongs around an equipment item or line on a P&ID, to pick the member skill.
---

# P&ID design guidance

## Purpose and when to use

What belongs around an item on a P&ID is a consequence of its service. This skill is the index
of the member skills and holds the questions common to all of them. The members are concise
engineering guidance with book citations: questions to put to a design, and conditional
recommendations, not calculations and not a compliance check. Drawing the result is `pid-draft`
and `pid-edit`.

| Skill | For |
|---|---|
| `pid-design-pumps` | Suction and discharge arrangement, minimum flow, positive-displacement relief |
| `pid-design-compressors` | Suction drum, anti-surge, check valve and relief on discharge, monitoring |
| `pid-design-vessels-and-tanks` | Nozzle set, level and pressure measurement, breathing and relief of tanks |
| `pid-design-heat-exchangers` | Configuration by service, vents and drains per side, condensers, reboilers, relief per enclosure |
| `pid-design-control-valve-station` | Block valves, drains, bypass, reducers, fail action, loop wiring |
| `pid-design-control-valve-selection` | Body, characteristic, rangeability, cavitation, noise, seat leakage |
| `pid-design-instrumentation` | Where a sensor may sit, what each equipment class measures, alarms, trips and control |
| `pid-design-isolation-vents-drains` | Isolation type, vent and drain branches, double block and bleed |
| `pid-design-pressure-relief` | Where a device is needed, inlet and outlet, back pressure, rupture discs |
| `pid-design-materials-and-spec-breaks` | Piping class, where a break belongs, service triggers for a metallurgy question |
| `pid-review-design-review` | Questions for reviewing a sheet before issue |
| `pid-review-commissioning-readiness` | Can the plant be cleaned, tested and started from this drawing |

Related skills: `relief-scenarios` and `safeguard-crediting` (safety), `area-classification`,
`control-loops`, `utility-systems`, `unit-operations`, `lists-sync`.

## Required inputs and missing inputs

The service of the item: fluid, phase, pressure and temperature range, hazard. Take it from
`process/flowsheet.yaml`, `cheme process streams` and the lists; ask for what is not there
rather than assuming it. A P&ID carries no elevation, no sizing basis and no pipe metallurgy.

## Workflow and tools

Engineering guidance only; core has no calculation for this. `cheme validate` checks that sheets
and lists agree with each other; it does not check the arrangements in these skills, so a clean
run says nothing about them. Ask, for any item:

1. How is it isolated, emptied and made safe for maintenance, and does anyone enter it?
2. What leaves it besides the product (vent, drain, purge, relief)? Where does that go?
3. What overpressure, underpressure or backflow can reach it, and what stops that?
4. What is measured and who acts on it (operator, controller, trip)?
5. What is the failure state of each actuated item on loss of air or power?

An item that looks missing may be absent for a reason the service explains. State the service
you assumed before calling anything a defect.

## Validation and failure handling

Several members give a pattern that is right in some services and wrong in others. Read the
pattern against the service; say when an arrangement is right as drawn. Where sources disagree
the member says so and does not pick one.

## Outputs and provenance

Guidance and questions, not files. Record decisions in `DESIGN.md` with the source of the
judgment.

## Required human judgment

Every safety-relevant choice: relief scenarios and set pressures, isolation for entry, trip
logic, fail actions, material selection. These skills prompt the questions; they never certify
that a design is safe or that protection layers are independent.

## References

Toghraei, *Piping and Instrumentation Diagram Development* (Wiley 2019); CCPS, *Guidelines for
Engineering Design for Process Safety* (AIChE); the individual members list their other books.
Citations were carried over from the source and not re-checked against the books in this port:
treat every numeric value and section reference as needing review before operational use.
