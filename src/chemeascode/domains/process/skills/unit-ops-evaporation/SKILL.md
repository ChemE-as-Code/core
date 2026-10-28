---
name: unit-ops-evaporation
description: Evaporators and their auxiliaries - separator, condenser and vacuum system, circulation types, the elevation rule of forced circulation, multiple effect and vapour recompression. Use when an evaporator is designed or reviewed.
---

# Evaporation

## Purpose and when to use

An evaporator boils solvent out of a solution to concentrate it. It is not a reboiler (a
reboiler's vapour returns to a column) and not a drier (which drives liquid off a solid) (Ray and
Das, *Process Equipment and Plant Design*, Elsevier 2020, Ch 6).

## Required inputs and missing inputs

Solution, concentration range, boiling-point rise, heat-sensitivity, fouling or crystallising
tendency, available steam pressure and cooling temperature. Ask for what is missing.

## Workflow and tools

Engineering guidance only; core has no calculation for this. An evaporation step can be modelled
as a `heater` and `flash` (`separation-method-selection`, downstream representation: predictive,
tested; evaporator rating left out). `cheme process energy` balances the duty.

The body comes with auxiliaries: a vapour-liquid separator (entrainment contaminates condensate
and fouls the condensing surface); a condenser, surface or direct contact; a vacuum system where
it runs below atmospheric, taking non-condensables off the condenser; condensate removal; a feed
preheater (a sub-cooled feed creates cold zones); for forced circulation a circulating pump and
large-bore pipework; for a crystallising duty a salt trap or filter.

Circulation types:

- Natural circulation through a calandria: in a short-tube unit heat transfer is best with the
  liquid about half way up the tubes; lower leaves the wall unwetted and fouling accelerates.
- Forced circulation: widest application and the practical choice where a definite crystal size
  is wanted. The heating element sits well below the liquid level and below the return to the
  flash chamber, so hydrostatic head suppresses boiling in the tubes and flashing happens in the
  separator, which keeps salt and scale off the surface. Circulation is roughly 100 to 150 kg
  liquor per kg water evaporated, so the temperature rise across the bundle is small.
- Film types (rising, falling, wiped) keep holdup and residence time low and suit heat-sensitive
  products; a falling film depends on its liquid distributor and usually recycles concentrate.

Multiple effect uses each effect's vapour as the next effect's heat. The number of effects is
limited by the total temperature spread divided by the driving force per effect (about 14 C for a
rising-film unit, under 10 C for a falling film, as the source reads). Mechanical or thermal vapour
recompression is the alternative to more effects.

## Validation and failure handling

Questions for a design: no separator; a vacuum unit with no vacuum system or non-condensable path;
no feed preheater; a forced-circulation heater above the liquid level; crystallising service with
no salt removal; effect vapour not going to the next effect's heating side.

## Outputs and provenance

State the circulation type, effect count and the basis. Record in `DESIGN.md`.

## Required human judgment

Evaporator type, fouling allowance and vacuum level need a person.

## References

- Ray and Das, *Process Equipment and Plant Design*, Elsevier 2020, Ch 6.
- `separation-method-selection`, `unit-ops-heat-transfer`.
- Retained as general method: auxiliary set, forced-circulation elevation rule, effect-count logic.
- Needs review before operational use: 100 to 150 kg/kg circulation, 14 C and 10 C per effect.
