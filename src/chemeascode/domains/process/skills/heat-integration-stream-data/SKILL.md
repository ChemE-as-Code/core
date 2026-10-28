---
name: heat-integration-stream-data
description: Extract the hot and cold streams a heat integration study needs from a flowsheet: supply and target temperatures, heat capacity flowrates, linearising, mixing points, and which heat sources count as utilities. Use before any pinch target or network design.
---

# Heat integration stream data

## Purpose and when to use

Every result of a heat integration study rests on its stream table, and most wrong results come
from extracting it badly. The table lists every stream that must be heated or cooled, not every
stream on the flowsheet (Ray and Das, *Process Equipment and Plant Design*, Elsevier 2020, §5.3,
§5.8). Part of the family `heat-integration`.

## Required inputs and missing inputs

For each stream: hot (needs cooling) or cold (needs heating); supply temperature (where it
starts); target temperature (where the process needs it to end); heat capacity flowrate CP (mass
flow times specific heat) or duty. A study also needs film coefficients if area is to be targeted,
the utilities available and their levels, present utility loads for a retrofit, utility costs
and exchanger cost against area, and the process and layout constraints on which streams may
meet (Ray and Das §5.3, §5.6). Say which operating case the table describes; one table cannot
stand for all cases (§5.8). Ask for what is missing; do not infer temperatures from equipment
design conditions.

## Workflow and tools

Engineering guidance only; core has no calculation for this. Stream temperatures, flows and
enthalpies of a solved case can be read with `cheme process streams`; deciding which become
pinch streams is yours.

Four rules (Ray and Das §5.8):

- Linearise on the safe side. Where enthalpy is not linear in temperature (a multicomponent vapour
  condensing), use segments, each with a constant CP, chosen so the linearised hot stream is never
  hotter than the real one and the linearised cold stream never colder (§5.8.1).
- Do not accept a mixing point as given. Two streams mixed at different temperatures are a
  direct-contact exchange the flowsheet happened to choose. Extract each from its own supply
  temperature to the mixed temperature and treat the mixing as isothermal there, so the heat the
  junction passed appears once in the data. Where a stream passed through exchangers before the
  mixing point, take its supply temperature from upstream of them (§5.8.2).
- Judge the driving force over what the stream actually does: a subcooled liquid that then boils
  is judged over its sensible and latent parts (§5.8.3).
- A utility is only something any other stream could replace. Steam, cooling water and
  refrigerant are utilities. Live stripping steam is not: it also lowers the partial pressure in
  the stripper, which no other heat source could do, so extract it as a process stream (§5.8.4).

Two things that change a stream's role:

- Raising steam is a cold utility, because it takes heat out of the process; a waste-heat boiler
  is a sink that may earn a credit (§5.1, §18.8).
- The target temperature is a process requirement. An intermediate temperature on the existing
  flowsheet may be a design choice only; extract from true supply to true target, not between the
  exchangers already drawn. Where a unit needs the stream at an intermediate temperature
  (separator, reactor inlet, column feed) that temperature is a target: end the stream there and
  start a new one after the unit.

## Validation and failure handling

- A hot stream whose target is above its supply (or the reverse) is a data error.
- Check that heat and material balances close for the case used before extracting from it.
- Core's `pinch_analysis` function rejects non-positive CP, supply equal to target and
  temperatures below 0 K; those checks do not make the stream choice right.

## Outputs and provenance

The stream table (name, hot or cold, supply and target in K or degC stated, CP in kW/K or duty in
kW, source of each value, operating case), the segments used for linearised streams, and the
utilities assumed. Record exclusions and their reasons.

## Required human judgment

Sources are silent on: which streams to leave out on safety or layout grounds, whether a target
temperature is fixed or flexible, and reconciling measured plant data before extraction. Ask the
user how their study handled each.

## References

- Ray and Das, *Process Equipment and Plant Design*, Elsevier 2020, §5.1, §5.3, §5.6, §5.8.1-§5.8.4, §18.8.

Retained as general method (stated by the cited textbook): the four extraction rules and the
raising-steam point. Needs review before operational use: the intermediate-target rule, which
generalises the textbook's mixing-point and upstream-exchanger cases.
