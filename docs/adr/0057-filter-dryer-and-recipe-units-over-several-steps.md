# 0057. A filter-dryer step to a residual moisture, and recipe units over several steps

- **Status:** Proposed
- **Date:** 2026-11-05

## Context

A batch fine-chemical plant isolates its product in a filter-dryer or a vacuum dryer: filter,
wash, re-filter and dry in one vessel. Core had a specified filter (`solid_separation:`, ADR
0025) and nothing for the dryer, so the NBS pilot (process-library `n-bromosuccinimide-1`)
wrote the dryer's outlets and its steam duty from a balance script, as ASSUMED values. Its
recipe could name only one flowsheet step per unit procedure, so the filter-dryer F-101, which
spans four steps (F101, W101, F102, D101), was entered as D101 alone (lesson L-3). Its drying
time was a guess. Most batch candidates of the library need the same work-up (core#165: TsCl,
MePPh3Br, NaN3, CuCl, PVC, bioethanol).

Options considered:

1. **PharmaPy** (Casas-Orozco et al., Comput. Chem. Eng. 153 (2021) 107408) has filtration,
   deliquoring, displacement washing and a convective (gas-through) dryer of a discretised
   cake. Every dynamic unit integrates through SUNDIALS via Assimulo, which is not on PyPI for
   Python 3.12+ and cannot be installed with uv. PharmaPy also pins `numpy<2` and has no release
   of its own. It models no agitated contact or vacuum filter-dryer, and it needs cake
   permeability, porosity and particle-size data that a library entry does not have. It is not
   adopted, either as an extra or as a worker. Like ADR 0042, this is a heavy stack for a
   question it is not built for. Its papers are literature only; no code is copied.
2. **A drying-curve model** (constant-rate and falling-rate periods, a critical moisture, a
   sorption isotherm). This needs data no entry has at the concept stage.
3. **A specified dryer** (chosen): the residual moisture is the design input, as a filter's
   cake liquid is. The energy and the drying time follow from that specification and from
   declared or ASSUMED data, with closed forms that can be checked by hand.

## Decision

- A block or step may give **`dryer:`** (`domains/process/dryer.py`; exclusive with
  `crystallizer:` and `solid_separation:`). It has one wet-cake inlet and `outlets: {product,
  vapour}`. The `volatiles` (component ids) leave as vapour down to the `residual_moisture`
  (`mass_fraction` of the product, or `per_kg_solid`). The volatiles kept have the inlet's
  volatile composition. Every other component, including what the cake liquid held dissolved,
  stays in the product. `cheme process propagate` writes both outlets (behaviour `dryer`,
  fingerprinted on the volatiles, the moisture and the outlets). `cheme validate` balances the
  step on components. The model basis is `residual-moisture` (specified).
- **Energy** (`dryer.energy`), in kJ/h and divided by the `efficiency`: the wet cake from its
  inlet temperature to the drying `temperature` at a constant `heat_capacity`, plus the
  volatiles evaporated at their `latent_heat`, plus `vessel_heat_capacity` (kJ/K) heated once
  per batch. The vessel term needs `process/recipe.yaml` for the batch's hours of flows.
  - A latent heat that is not declared comes from the component's critical constants by
    Pitzer's corresponding-states correlation (Poling, Prausnitz and O'Connell 2001, eq.
    7-9.4). It is deterministic, pure Python, and reported with that basis. It is 3 to 4 % high
    for water, so a declared value is preferred.
  - Without either the duty is missing, and the report says why; no number is given.
- **`cheme process crystallizers`** reports dryers too: the evaporated flow, the moisture, the
  mass residual, the duty and its terms, each latent heat with its basis, and the amounts of
  one batch. A dryer's outlets are divided by its own split: the volatiles are the liquid and
  everything else the dry solid, so the product's moisture is the dryer's residual moisture.
  With `energy.port` it compares the heating stream's duty with the model's, beyond the
  flowsheet's relative tolerance (`cheme.process-dryer-duty`, apart from the outlets'
  `cheme.process-crystallizer-outlet`: propagate writes the outlets, never the energy stream).
  The schema and port rules are `cheme.process-dryer`; a `latent_heat` keyed by a component
  that is not a volatile is one of them.
- **Drying time.** A recipe `dry` operation may take `from:` a dryer step. The time is one
  batch's vapour over `drying_rate` (kg/(m2 h), a constant mean rate, given or ASSUMED) times
  the heated area of the unit procedure's vessel, or the dryer's given `drying_time`.
  - The heated area is `vessel.heated_area`, else `vessel.jacket.area`, else the shell and
    bottom the wet cake wets.
  - The wet cake's volume is the dryer's inlet for one batch over its `cake_density`. The
    vessel's working volume is the largest of that and what each step of the unit procedure
    takes in for one batch (the slurry, a reslurry wash), from the components' liquid molar
    volumes where they are known. That volume over the fill fraction, rounded up to R10 (ADR
    0052), sizes the vessel when no `volume` is given, and a given volume is checked against
    it (`cheme.recipe-vessel`). The heated area stays the cake's.
- **Filtration time.** A `filter` operation may take `from:` a `solid_separation:` that gives
  `filtration:` (specific cake resistance, medium resistance, pressure difference, viscosity,
  optional filtrate density and area). Its time is Ruth's constant-pressure equation, `t = mu
  (alpha M V / (2 A^2) + R_m V / A) / dP`, with M the dry solid of one batch's cake, V its
  filtrate, and A the given area or the vessel's bottom (a Nutsche's plate). There is no
  filtration time without a specific cake resistance. The split itself stays the specified one.
- **Recipe units.** A unit procedure gives `unit:` (a flowsheet block or step, as before) or
  **`units: [steps]`**, the steps that run in one vessel (a filter-dryer's filter, wash,
  re-filter and dry). Its occupancy is the sum of its operations, counted once for the vessel.
  - A step listed in one vessel's `units` and named by another unit procedure is
    `cheme.recipe-reference`.
  - A unit (or units) that is a block, or holds a batch or semi-batch step, sizes the vessel
    from that step, as in ADR 0052.
  - The results name such a unit `F101+W101+F102+D101`.
- **Unchanged behaviour.** `dryer`, `filtration`, `units` and `heated_area` are left out of a
  model dump when they are not given. Fingerprints of flowsheets and recipes that do not use
  them (propagate's outlets, datasheets fill's `recipe:` input) and the behaviour of plain
  batches, semi-batches, crystallizers, filters and recipes stay as they were.

## Consequences

- Positive: a filter-dryer's outlets, its duty and its drying and filtration times are
  calculated from stated inputs, and a changed moisture, rate or batch size changes the cycle.
  The NBS pilot can drop its dryer script and name F-101 as one vessel.
- Negative: the residual moisture and the drying rate are specified, not predicted. There is
  no falling-rate period, critical moisture or sorption equilibrium. Several volatiles leave in
  their inlet ratio (no selective drying), and the vacuum's boiling point is not checked. The
  wash is still a step of the user's choosing (a mixer and a filter); there is no washing
  efficiency or displacement model.
- Limitations: an incompressible cake (constant alpha); constant heat capacity; the vessel
  cooled back to the cake's inlet temperature each batch; heat losses only through the
  efficiency; no agitator or vacuum-pump power; no condenser. The same step in two unit
  procedures that are not lists (ADR 0051) still does not add their occupancies.
- Follow-ups: a drying curve when a library entry has measured data; washing efficiency; a
  revisit of PharmaPy only if it is released on PyPI with an Assimulo that runs on Python 3.12+
  and an entry has cake data, and then through a worker ADR.

## Evidence

- core#165 (filter-dryer, lesson L-3); this ADR's PR.
- `src/chemeascode/domains/process/dryer.py`, `schema.py` (`Dryer`, `DryerEnergy`,
  `ResidualMoisture`, `Filtration`), `recipe.py` (`UnitProcedure.units`, `Vessel.heated_area`,
  `_cake_vessel`, `_solids_time`, `batch_hours`), `propagate.py`, `crystallization.py` (the
  report), `model_basis.py`.
- `tests/test_dryer.py`: the mass and energy balance and the drying and filtration times
  against hand calculations, Pitzer's latent heat against measured heats of vaporization, a
  recipe unit over several steps, and model dumps without the new fields.
- Poling, B. E., Prausnitz, J. M., O'Connell, J. P. (2001), *The Properties of Gases and
  Liquids*, 5th ed., McGraw-Hill, eq. 7-9.4 and Appendix A. Ruth, B. F. (1935), Studies in
  filtration, Ind. Eng. Chem. 27, 708-723. Casas-Orozco, D. et al. (2021), PharmaPy, Comput.
  Chem. Eng. 153, 107408 (reviewed, not adopted).
