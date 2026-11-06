# 0056. Precipitation from a mixed liquor in the crystallizer; phase changes are not screened as reactions

- **Status:** Proposed
- **Date:** 2026-11-05

## Context

The crystallizer of ADR 0025 (`domains/process/crystallization.py`) takes one solute in one
solvent and one material inlet, and refuses an inlet with any other component. A batch
precipitation from a reaction liquor always carries other solutes. In the N-bromosuccinimide
pilot (process-library `processes/n-bromosuccinimide-1`, DESIGN.md lessons L-2 and L-5; core
#165), the mother liquor holds NaBr, NaOH and unreacted succinimide. The pilot therefore wrote
the precipitation (CR101) and the dissolution loss of its reslurry wash (W101) as conversion
"reactions", `NBS -> NBS_S` and `NBS_S -> NBS`, with conversions worked out by a script. That
had two costs:

- the solubility, the real basis of both steps, lived in a script, not in the flowsheet;
- `cheme process reactor-hazards` screened both steps as reactors and reported missing data
  for them (L-5).

The library candidates scouted for #165 have the same gap: NaN3 crystallizes from a liquor
that holds NaOH and hydrazine, CuCl precipitates by diluting a chloride brine, TsCl solidifies
from an H2SO4/HCl liquor, and MePPh3Br precipitates from toluene that still holds PPh3.

Options considered:

1. **An electrolyte thermodynamic model** (Pitzer, eNRTL) for the solubility in the liquor.
   It needs parameters that a concept-stage entry does not have, and a new property-package
   path.
2. **PharmaPy** (Casas-Orozco et al., Comput. Chem. Eng. 153 (2021) 107408). Its
   crystallizers solve population balances with nucleation and growth kinetics, which the
   entries do not have, and it brings no electrolyte thermodynamics. Every dynamic unit
   integrates through Assimulo, which cannot be installed with uv on Python 3.12 or later. It
   was reviewed (2026-11-05) and not adopted.
3. **Spectator solutes in the existing equilibrium crystallizer.** The solubility comes from
   data measured in that liquor, or from the pure solvent's corrected by a Setschenow
   coefficient. Without either, the case is refused. Deterministic and pure Python (ADR 0010),
   and a closed form for each case.

## Decision

cheme-as-code takes option 3. It is implemented natively; no PharmaPy code is used or copied.

- **Schema** (`domains/process/schema.py`):
  - `Crystallizer.spectators: [component ids]`: dissolved components carried unchanged.
  - `Solubility.measured_in: pure_solvent | mother_liquor`.
  - A new solubility unit `kg/kg_liquor`: per kg of solute-free liquor, which is solvent plus
    spectators. It is allowed only with `measured_in: mother_liquor`.
  - `Solubility.salting_out: {coefficients: {spectator: k}, log: log10 | ln, provenance,
    source}`. It needs one coefficient per spectator (0 stated where a spectator has no
    effect) and is refused with liquor-measured data, which already include the spectators.
  - Every new field is left out of the dump at its default, so a single-solute crystallizer's
    outlet fingerprints do not change (tested against the 1.7.0 values).
- **Model**:
  - Spectators pass with the liquor. They are never crystallized or evaporated, and they
    divide between cake and filtrate with the liquid.
  - Solubility per kg of solute-free liquor: `C = (S - s (W + P)) / (a - s (1 - a))`. A mass
    fraction `x` in the saturated liquor is `x / (1 - x)` on that basis. Per kg of solvent the
    ADR 0025 form holds.
  - Setschenow correction: `log10(s0 / s) = sum_i k_i m_i`, with `m_i` the spectator's
    molality in the mother liquor (mol per kg of free solvent). For a hydrate this is solved by
    successive substitution on the free solvent that the hydrate leaves.
  - Evaporation to a concentration counts the spectators in the liquid.
  - The balances add a per-spectator triple and the spectators' atoms.
  - The report's `solubility_kg_per_kg_solvent` is then the mother liquor's at the solution,
    per kg of free solvent (salting out applied, a per-liquor value converted). The declared
    value stays under `mother_liquor.declared_solubility` with its basis. Without spectators
    the key holds the declared value, as in 1.7.0.
  - A block's reactive balance (`validate`, `cheme.process-balance`) fits one reversible
    phase change `<step>:crystallization` (solute, and the hydrate's solvent, into crystal)
    per crystallizer inside it next to the block's reactions. A precipitation in the reactor
    vessel (a reacting step and a crystallizer in one block) therefore balances. These
    extents are not reported as reaction extents.
- **No silent pure-water value.** A crystallizer that declares spectators and gives only a
  pure-solvent solubility is `cheme.process-crystallizer` (error, with file, line and hint).
  `propagate` refuses it as unsupported, and its model basis is not sourced. An inlet
  component that is not declared is still refused, as before.
- **Several inlets.** A crystallizer takes its material inlets together. The energy balance
  uses their mass-weighted mean temperature, which is exact for its one heat capacity. A
  reslurry wash is therefore a crystallizer fed by the cake and the wash water: its crystals
  dissolve until the liquid is saturated, and its own `separation:` (or a following
  `solid_separation:`) is the re-filtration. There is no new `wash:` block.
- **Phase changes in the screening** (`chemistry/reactions.py`, `safety/reaction_hazards.py`):
  - A reaction may say `kind: phase-change`. This field is left out of the dump at
    `reaction` and of the reactor input fingerprint.
  - One component into one other with the same formula, coefficient for coefficient, one of
    them `phase: solid`, is recognized as a phase change without the field, unless it
    declares a `heat_of_reaction`. An isomerization has no solid side, so it stays a reaction.
    A recognized one with a heat of reaction (dissolving caustic or diluting acid can boil a
    batch) stays screened as a reaction, its heat in dT_ad, with a note: a heuristic the
    author never opted into must not drop an MTSR warning.
  - `cheme process reactor-hazards` does not screen a step whose reactions are all phase
    changes. Instead it reports `cheme.reactor-hazard-phase-change` (info, stable id
    `process/flowsheet.yaml#reactor-hazard-phase-change:<step>`) and lists the step under
    `phase_changes` in the JSON.
  - A step with both kinds takes its `dT_ad` and MTT from its chemical reactions alone, with a
    note. A semi-batch's MTSR is the cooling-failure temperature of its model, which integrates
    every reaction of the step: the phase changes' kinetics and heat count in it, and a second
    note says so.

## Consequences

- Positive: the NBS precipitation and its reslurry wash can be written with their solubility
  in the flowsheet and no conversion "reactions". The thermal screening no longer reports
  them as reactors with missing data. NaN3, CuCl, TsCl and MePPh3Br become expressible in the
  same way.
- Positive: closed forms throughout, so the tests check hand calculations: the
  per-kg-of-liquor balance, the Setschenow factor at a stated molality, and the dissolution
  of a reslurry wash.
- Negative: liquor-measured data hold at the liquor composition their source states. The
  model does not check that the solved mother liquor (after a recycle, say) is still at that
  composition. The Setschenow form is only the empirical linear molal correction: there is no
  electrolyte activity model, no common-ion solubility product, and no check of a
  spectator's own solubility limit.
- Limitations: one crystallizing solute. Displacement washing and filtration, centrifuge or
  drying rates are not modelled. A hydrate's formation from solute and water written as a
  reaction is detected only when declared `kind: phase-change`.
- Follow-ups: the library re-expresses NBS CR101 and W101 (process-library#370). A
  two-dimensional table (temperature and spectator content) when an entry has such data.
  PharmaPy could be revisited through a worker, never a base dependency, once it is released
  for Python 3.12+ and an entry has measured kinetics (the scout note of 2026-11-05).

## Evidence

- core#165 (lessons L-2, L-5), this ADR's PR.
- `src/chemeascode/domains/process/crystallization.py` (`Liquor`, `_equilibrium`,
  `liquor_of`, `pure_solvent_only`, `node_feed`), `schema.py` (`Solubility`, `SaltingOut`,
  `Crystallizer.spectators`), `propagate.py` (several crystallizer inlets), `model_basis.py`,
  `domains/chemistry/reactions.py` (`Reaction.kind`, `phase_change`),
  `domains/safety/reaction_hazards.py` (`phase_changes`, `PhaseChangeStep`).
- `tests/test_precipitation.py`.
- Setschenow, J. (1889) Über die Konstitution der Salzlösungen auf Grund ihres Verhaltens zu
  Kohlensäure, Z. Phys. Chem. 4, 117-125; Mullin, J. W. (2001) Crystallization, 4th ed.,
  Butterworth-Heinemann, chapter 3 (solubility in mixed solvents and salting out).
- Literature only, no code used: Casas-Orozco, D. et al. (2021) PharmaPy: an object-oriented
  tool for the development of hybrid pharmaceutical flowsheets, Comput. Chem. Eng. 153,
  107408.
