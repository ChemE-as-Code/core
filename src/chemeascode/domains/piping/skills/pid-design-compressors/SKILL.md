---
name: pid-design-compressors
description: What to consider around a compressor or blower on a P&ID - suction drum and liquid protection, suction throttling, anti-surge flow element and recycle, discharge check valve and relief, monitoring. Use when adding, completing or reviewing a gas mover.
---

# Compressor installation

## Purpose and when to use

Adding, completing or reviewing a compressor, blower or fan. Drawing it is `pid-draft` / `pid-edit`.

## Required inputs and missing inputs

Machine type (centrifugal, axial, reciprocating, rotary), gas and whether it is flammable or
toxic, whether liquid can reach the suction, the surge line and relief set pressure (not on the
P&ID; ask). Without the surge line the anti-surge loop can be shown but not specified.

## Workflow and tools

Engineering guidance only; core has no calculation for this. From the machine outward:

**Suction**
1. Isolation for maintenance: ask how the machine is isolated (`pid-design-isolation-vents-drains`).
2. A suction drum as the last vessel before the machine, with a high-level trip so liquid cannot
   reach the compression chamber (CCPS, *Guidelines for Engineering Design for Process Safety*,
   §4.4.11.2, §4.4.8), and its own level control and drain.
3. Ask what a control valve on the suction is for. Throttling the inlet costs capacity and moves a
   centrifugal machine toward surge, so capacity is normally set on the discharge, by recycle, or
   by speed; but the valve is legitimate where holding an upstream pressure is the duty (flare gas
   recovery, a refrigeration suction-pressure controller) or where the maker offers inlet
   throttling or guide vanes.
4. For anti-surge, the flow element belongs on the suction, which correlates with the surge line
   better than discharge flow (CCPS §4.4.11.2); a low-loss element.

**Discharge**
1. Anti-surge take-off first, so the recycle branches before the check valve: a fast control valve
   back to upstream of the suction drum, through a cooler where the gas heats significantly,
   controlled from suction flow and pressure rise (CCPS §4.4.11.2). Do not recycle into the
   suction pipe downstream of the drum.
2. A check valve after the take-off against backflow into a stopped machine. The reverse-flow
   transient picks the type; a non-slam axial valve is the usual choice after a machine, a
   dual-plate only where its duty and installation meet the maker's limits, and every type needs
   straight run (Sotoodeh, *A Practical Guide to Piping and Valves for the Oil and Gas Industry*,
   Elsevier 2021, Ch 8 to 10). Ask what the transient is.
3. Relief on the discharge upstream of the discharge block valve. A reciprocating machine keeps
   raising pressure until something fails (CCPS §4.4.11.2). Destination: `pid-design-pressure-relief`.
4. Where the vapour destination is flammable, ask whether flame protection is required there
   (project code).

**Monitoring**: vibration, discharge temperature and pressure, suction pressure, lube-oil
pressure, speed where the driver varies; vibration and high discharge temperature carry alarm and
shutdown functions (CCPS §4.4.11.2, §9.2.5). See `pid-design-instrumentation`.

## Validation and failure handling

Do not put a strainer that can plug on the suction. Do not share one sensor between the
anti-surge controller and the surge trip (CCPS §9.3). The surge line, cooler duty and relief
set pressure are open data: list them. Anti-surge valve selection is not covered by the sources.

## Outputs and provenance

Items added or questioned, with the service assumed and what data is still needed.

## Required human judgment

Suction-valve purpose, relief scenario and destination, anti-surge philosophy, trips.

## References

CCPS §4.4.8, §4.4.11.2, §9.2.5, §9.3; Sotoodeh Ch 8 to 10. Needs review before operational
use: section numbers (inherited) and all safety statements.
