---
name: pid-design-pumps
description: What to consider around a pump on a P&ID - suction and discharge arrangement, strainer, reducer, check valve, gauges, minimum-flow line for centrifugal pumps and discharge relief for positive-displacement pumps. Use when adding, completing or reviewing a pump.
---

# Pump installation

## Purpose and when to use

Adding, completing or reviewing a pump on a sheet. Drawing it is `pid-draft` / `pid-edit`.

## Required inputs and missing inputs

Pump type (centrifugal, reciprocating, rotary), fluid and its volatility, solids content, whether
the suction is from storage, an open system or a closed loop, whether the pump can run blocked in.
The pump curve is needed for a minimum-flow line; if absent, say the line is still needed and
what data it waits for.

## Workflow and tools

Engineering guidance only; core has no calculation for this. In flow order:

**Suction**
1. Isolation and a way to empty the casing before opening it: see `pid-design-isolation-vents-drains`
   (Toghraei, *P&ID Development*, Wiley 2019, §8.7). Ask how the pump is isolated.
2. A strainer where the suction can carry debris (line from storage or an open system,
   commissioning scale, close-clearance seals). A T-type body can be cleaned online (CCPS
   *Guidelines for Engineering Design for Process Safety* §4.4.11.1); pressure indication each side
   shows plugging (Toghraei §14.9.2). On clean closed-loop service a temporary start-up strainer
   later removed is the usual alternative, because a permanent one costs suction head. An absent
   strainer is not by itself a defect: state the service assumed. See also
   `pid-review-commissioning-readiness` for the disagreement on permanent strainers.
3. A reducer where the line is larger than the pump nozzle. On a centrifugal suction it reduces
   (an enlarger there is a sizing error, Toghraei §10.6.1). Eccentric orientation is a note for
   the user; it is not drawn.
4. The pump, and its driver as a separate item.

**Discharge**
1. Enlarger back to line size where needed.
2. A check valve against reverse flow to a stopped pump. Reciprocating pumps do not need one
   (their own valves act, Toghraei §10.7.1.1); in hazardous service it is not the only backflow
   protection (CCPS §6.3.1). The reverse-flow transient picks the type, not the line size: ask
   what it is. Check valves need straight run each side, so one bolted directly to a reduced-bore
   valve is worth a question (Sotoodeh, *A Practical Guide to Piping and Valves for the Oil and
   Gas Industry*, Elsevier 2021, Ch 8 to 10).
3. A discharge pressure gauge or transmitter with its root valve (Toghraei §14.9.2). A suction
   gauge for hot or volatile liquids where cavitation is a concern.
4. A drain between pump and discharge valve, and isolation (Toghraei §8.7).

**Protection by type**
- Centrifugal: a minimum-flow line from the discharge upstream of the check valve back to the
  suction vessel, not into the suction pipe, because recirculated liquid heats up (CCPS §4.4.11.1).
  Sized from the pump curve with a flow control valve or restriction orifice.
- Positive displacement: it has no maximum pressure when blocked in, so a relief device on the
  discharge upstream of the discharge block valve, relieving to the suction vessel or another
  destination with enough inventory to absorb the heat, never into the suction pipe. Where no such
  destination exists, ask about a low-flow or high-temperature trip as well (Toghraei §10.7.1.1,
  §12.3.3; CCPS §4.4.11.1). See `pid-design-pressure-relief`.
- A vent or drain on the casing so the case can be emptied.

## Validation and failure handling

Do not report a missing strainer, check valve or minimum-flow line before the service is stated.
Do not add a bypass around the check valve. Take-off for minimum flow is between the pump and the
check valve.

## Outputs and provenance

A list of items added or questioned with the service assumed and the data still needed.

## Required human judgment

Check-valve type and backflow protection in hazardous service, relief destination, whether a
trip is needed, strainer policy.

## References

Toghraei §8.7, §10.6.1, §10.7.1.1, §12.3.3, §14.9.2; CCPS §4.4.11.1, §6.3.1; Sotoodeh Ch 8 to 10.
Needs review before operational use: all section numbers (inherited), and each safety statement.
