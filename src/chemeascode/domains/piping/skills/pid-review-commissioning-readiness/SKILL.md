---
name: pid-review-commissioning-readiness
description: Review a P&ID for whether the plant can be cleaned, tested and brought into service from it - cleaning and test routes, commissioning-only items, maintenance isolation against relief, handover status. Use when asked what commissioning will find missing.
---

# Reviewing a P&ID for commissioning

## Purpose and when to use

A design review asks whether the drawing is finished (`pid-review-design-review`). This asks
whether the plant can be brought into service from it. Sources: Killcross, *Chemical and Process
Plant Commissioning Handbook* 2e (Elsevier 2021), cited by chapter, and Moran, *An Applied Guide
to Process and Plant Design* (Butterworth-Heinemann 2015).

## Required inputs and missing inputs

The commissioning intent, which a drawing does not carry: which system is cleaned and how, the
designated receiver, boundaries, test scope, which systems are dried or evacuated, whether the
drawing is as-built. Ask first. Without it, the checks below are unchecked, not passed or failed.
A P&ID has no elevation and no flange detail, so whether a route falls or a blind fits is an
isometric or field question.

## Workflow and tools

Engineering guidance only; core has no calculation for this. Killcross asks for drawing content
in two places for commissioning items: intersystem cleaning isolations marked with position and
type (§16), and boundary and boundary-isolation points on an as-built drawing (§21). He also
requires test scope on system drawings (§41), boundaries at isolation valves (§6) and relief
equipment documented (§7). Otherwise commissioning items live in a bill of materials, register,
isometric or marked-up copy; offer the rest as what the drawing must support. Each check applies
only to the operation confirmed.

- **A cleaning route is continuous.** A water flush runs high to low (§31); a blow only where
  practicable (§16). Circulated chemical cleaning, pigging and manual cleaning of large-bore line
  differ (§31). The route's topology is drawn; that it is the cleaning route is intent.
- **Never flush or blow into a process vessel that is not the designated receiver** (§31). A blow
  ends at an open end or receiver. The end anchored against whiplash, a safe discharge location and
  a screen or catch pot (§31, §16) are field and test-package scope: ask, do not report them
  missing from a P&ID.
- **Intersystem cleaning isolations** are identified with position and type: blind or spool (§16).
  Which systems meet is intent. A mark on a copy is not a modelled object, so finding none confirms
  nothing: ask for the marked-up copy. Killcross elsewhere treats blinds and spools as consumables
  on the isometric or test copy (§8, §31, §41); the specific drawing requirement is taken as
  stronger.
- **Items that cannot survive the cleaning medium come out** (instruments, control valves, check
  valves, filters, orifices), replaced by temporary spools (§31), with a reinstatement schedule
  (§16; a check valve went back without internals, §32). A pulled restriction orifice may be a
  registered protective device. Removability needs flange detail: unchecked.
- **A test needs somewhere to admit the medium, read pressure and depressurise safely** (§41). A
  hydrostatic test needs a safe vent and a safe drain together, since draining a filled system
  without a vent pulls vacuum; a pneumatic test has nothing to drain. The test rig carries its own
  certified relief (§41): test-package scope.
- **Instrument air is blown clean before pneumatic instruments are connected** (§31). The source
  does not say how: ask.
- **Drying and purging**, if confirmed, need a purge source and a dew-point sample point (§31).
  **Vacuum**, if confirmed, needs a connection and readable gauge; everything inside, instruments
  and relief streams included, is confirmed for full vacuum (§31, §41); take the rating from
  datasheets. An inert purge outlet needs a named destination; whether gas can collect there is
  layout.

**Commissioning-only items**: temporary strainers where the service warrants one (see
`pid-design-pumps`; absence is not a defect), temporary spools (isometric, not P&ID), boundary
isolation valves positioned so a blind or spool fits (§6, §21), tagged tie-ins and package battery
limits (§7, §22; not model data: ask for the register), sample points with isolation (§44).
Vents and drains for filling and draining are permanent plant; hydrotest ones depend on project
convention (`pid-design-isolation-vents-drains`). Disagreement to surface: Moran says avoid
permanent pump suction strainers because they get removed (Ch 2); Killcross lists strainers
installed among pre-commissioning checks (§32) while describing his own as removed after start-up
(§31).

**Maintenance isolation.** Isolating a vessel for maintenance must not orphan it from its relief
system while it holds pressure or inventory (Moran Ch 17), and that route is also a connection back
to the process that must be assessed. Where it is opened or entered, entry isolation governs and
the relief connection is blinded or spooled (`pid-design-isolation-vents-drains`). An isolation made
by breaking the line leaves a joint to re-make and recheck before start-up (§41); closing a valve
does not. Trace relief path and isolation valves together.

**Handover.** As-built is a status conferred at handover, not correct, complete or installed
(Killcross's handover certificate carries reservations and a known wrong valve, §21, §45).
As-built status and boundaries come from the user. The boundary-point requirement can be checked
only with both. Moran gives the surrounding vocabulary (Ch 16).

**Not settled by these sources**: turndown, emergency against planned shutdown, first fill, batch
plant (Killcross §7, §42; Moran Ch 7); treat them as questions. For fired heaters Moran's upset
table has a low-flow alarm and fuel cutout, a metal temperature alarm and a high stack temperature
alarm on fired equipment only (see `relief-scenarios`).

## Validation and failure handling

Cover every sheet: cleaning routes, boundaries and relief paths cross sheets, and a route that
does not close is unchecked, not a break. `cheme show` and `cheme render` read single objects and
regions; a missing connection is a finding only when the whole neighbourhood was read.

## Outputs and provenance

Sheets read; what the drawing supports for cleaning, testing and isolation; what commissioning
must add or cut into; the two direct drawing requirements kept separate from as-built status; the
questions that needed intent not given.

## Required human judgment

Commissioning intent, receivers, boundaries, test scope, entry isolation, handover acceptance.

## References

Killcross §6, §7, §8, §16, §21, §22, §31, §32, §41, §42, §44, §45; Moran Ch 2, 7, 16, 17. Needs
review before operational use: all section references (inherited, not re-read), statements on
cleaning-route direction, vacuum, and test-rig relief (safety-relevant).
