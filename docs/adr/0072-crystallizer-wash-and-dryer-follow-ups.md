# 0072. Crystallizer, wash and dryer follow-ups: a carried solubility point, the liquor checked, a displacement wash, a second liquid, the dryer's selectivity, sublimation, cooling and condenser

- **Status:** Proposed
- **Date:** 2026-11-13

## Context

ADRs 0056 and 0057 left gaps that the library's batch entries ran into (core#183):

- **One solubility point.** ADR 0025 interpolates solubility `points` and never extrapolates,
  so one sourced point away from the crystallizer's temperature is refused. The
  n-bromosuccinimide-1 and carbon-tetrabromide-1 entries (L-8, L-4) therefore entered their
  25 and 30 C values as a `value`, which the report then calls "given at the operating
  conditions". It is not.
- **Liquor composition.** A `measured_in: mother_liquor` solubility holds at its source's liquor
  composition, but nothing checks that the solved mother liquor is still there, for example
  after a recycle (sodium-azide-1 L-6).
- **Washes.** A wash is a mixer or a reslurry crystallizer. There is no dissolution into a wash
  of another solvent and no displacement-wash efficiency (sodium-azide-1 L-8).
- **Dryer.** It writes no outlet temperatures. Its vacuum condenser and the heat of cooling the
  vessel back for the next batch are worked out by hand (n-bromosuccinimide-1 L-7). It cannot
  lose a subliming product, and it keeps its volatiles in the inlet's ratio
  (carbon-tetrabromide-1 L-5).
- **A second liquid.** The o-TsCl oil of p-toluenesulfonyl-chloride-1 (L-4) is a spectator that
  divides with the aqueous liquor, so the cake's retention of the oil cannot be stated.

Options considered: an electrolyte or activity model for the liquor (ADR 0056 option 1, no
parameters at the concept stage); a dispersion model of cake washing (it needs cake porosity
and dispersion data that no entry has); a drying-curve model (ADR 0057 option 2). Each of these
needs data the entries do not have. The option taken is the same as ADRs 0056 and 0057:
closed forms with stated assumptions and specified inputs, each opt-in.

## Decision

Every new field is optional and is left out of a model dump when it is not given. A flowsheet
without the new fields solves, fingerprints and reports as before.

- **A solubility point carried to the crystallizer's temperature.** `Solubility.transfer:
  {heat_of_solution, unit: kJ/kmol, provenance, source}` takes exactly one `points` entry of a
  pure-solvent solubility. It applies the temperature dependence of an ideal solution's
  solubility at a constant heat of solution (at infinite dilution: the dissolved solute's
  partial molar enthalpy less the crystal's), `ln(x / x0) = -(dH_sol / R) (1 / T - 1 / T0)`, to
  the solute's mole fraction in its solvent. `mass_fraction` data are converted to kg per kg of
  solvent first, and a mole fraction of 1 or more is refused. A heat of solution of 0 states no
  temperature dependence, which is the n-bromosuccinimide workaround made explicit.
  - The report gives `solubility_transfer` (from, to, the value there, the heat, provenance and
    basis). An info finding, `cheme.process-crystallizer-transfer`, says the value is not one at
    the operating conditions.
  - The model basis says the same. It is not sourced while the transfer is assumed.
  - The rule "outside the solubility data" no longer applies to a point with a transfer. Its
    hint names `transfer:`.
- **The liquor a solubility was measured in.** `Solubility.liquor: {mass_fraction: {spectator:
  w}, tolerance, provenance, source}` is allowed only with `measured_in: mother_liquor`.
  - `cheme process crystallizers` compares the solved mother liquor with it. The mother liquor
    here is the solute, the solvent and the dissolved spectators. The comparison is in
    `mother_liquor.composition`.
  - Each spectator beyond the relative tolerance is a warning,
    `cheme.process-crystallizer-liquor`. Its hint is to bring the liquor back (the still's end,
    the purge) or to give data at this composition.
- **A displacement wash on a filter.** `SolidSeparation.wash: {port, efficiency, cake_liquid,
  dissolution, provenance, source}`.
  - The wash enters by its own material inlet `port`, so the filter takes two inlets. The
    slurry is separated as before.
  - The unwashed cake's liquor `L` stays in the washed cake by `R = (1 - E)^n`, where `E` is the
    wash efficiency and `n` the mass wash ratio, the wash fed over `L`. This is the wash-ratio
    form of the SysCAD filter-press model, which cites Merritt.
  - The washed cake holds its `cake_liquid` (default: the separation's): at most `R L` of its
    liquor, the rest wash. Everything else leaves as the wash filtrate, which goes to
    `outlets.wash_filtrate` or joins the filtrate.
  - `dissolution: {crystal, solute, solubility, temperature, saturation}`: before it displaces
    the liquor, the wash dissolves crystals up to `saturation` times its solubility. The
    solubility is per kg of the wash fed, net of the solute the wash brings. A `saturation` of
    1 gives a saturated wash, the upper bound of the loss. Only an anhydrous crystal is taken
    (crystal and solute with the same formula). `validate` balances the dissolution as a
    reversible phase change `<step>:dissolution`, as ADR 0056 does a crystallization.
  - A recipe `filter` `from:` a washed filter takes Ruth's time for the slurry's own filtrate,
    plus the wash at the final filtration rate: `t_w = mu V_w (alpha M / A^2 + R_m / A) / dP`,
    from `dV/dt = A dP / (mu (alpha M / A + R_m))` at the end of Ruth's filtration.
  - A crystallizer's own `separation:` takes no wash.
- **A second liquid.**
  - `SolidSeparation.second_liquid: {components, cake_liquid}`: the cake holds that oil at its
    own cake liquid, and the rest of the liquid at the separation's.
  - `Crystallizer.second_liquid: {components}`: spectators in a phase of their own. They are
    left out of a per-liquor solubility basis, the salting-out molality and the liquor's
    composition, and they take no Setschenow coefficient.
  - A filter that holds a second liquid takes no wash. That combination is refused.
- **The dryer.** New fields: `pressure` (kPa(a)), `selectivity`, `sublimation`, `cooling`,
  `condenser`, and a `condensate` outlet role.
  - `selectivity: raoult` replaces the inlet-ratio rule. The cake liquid evaporates as an open
    (Rayleigh) evaporation of an ideal liquid at the drying temperature, so `n_i = n_i0 f^(P_i
    / P_max)`. `f` is found by bisection so that the volatiles kept are the residual moisture.
    A volatile without a vapour pressure at that temperature stays; if what stays is more than
    the moisture, the case is refused.
  - `sublimation: {components: {solid: vapour component}, heat: {solid: kJ/kg}}` needs the
    `pressure`. The vapour leaves saturated with each solid, `n_j = n_vap P_j / (P - sum P_j)`,
    with the solid's `vapour_pressure` as its sublimation pressure. This is an upper bound of
    the loss.
    - Because the loss lowers the product of which the moisture is a share, it is solved by
      successive substitution.
    - The sublimate leaves with the vapour as the component it maps to (the same formula). Its
      heat counts in the duty, which is missing without it. `validate` balances it as a phase
      change.
  - `cooling: {product_temperature, heat_capacity, vessel_temperature, port}` gives the heat
    removed after drying: `m_p cp_p (T - T_p) + C_v (T - T_v) / h_batch`.
    - The next batch heats the vessel from `T_v`, which defaults to the cake's inlet
      temperature, the ADR 0057 assumption.
  - `condenser: {temperature, heat_capacity, port}` needs the `pressure`. The vapour is flashed
    over an ideal condensate at the condenser's temperature, with `K_i = P_i(T_c) / P` and no
    inert. The Rachford-Rice solution condenses everything below the bubble point and nothing
    above the dew point.
    - Its duty is the latent heat (the dryer's) of what condenses plus all of the vapour cooled
      as liquid, the same path as the vent condenser of ADR 0062.
    - With `outlets.condensate`, the condensate leaves there and the vapour outlet takes what
      passes to the pump.
  - With `cooling:` or `condenser:`, `cheme process propagate` writes the outlets'
    temperatures: the product at its discharge temperature, the vapour at the drying
    temperature (past a condenser with a condensate outlet, the condenser's), and the
    condensate at the condenser's.
  - The cooling's and the condenser's duties are compared with the energy streams at their
    outlet ports (`cheme.process-dryer-duty`), as the heating's is.
  - Their fingerprints include the new fields and the vapour pressures they use, only when they
    are given.

## Consequences

- Positive: the library's workarounds get honest forms: a `value` entered at another
  temperature becomes a carried point that the report says is not at the operating
  conditions; the vacuum condenser, cool-back heat and outlet temperatures come from the model
  instead of hand sums; the NaN3 methanol wash can dissolve NaN3 at a stated approach; CBr4's
  sublimation loss and its selective drying can be estimated; the TsCl oil's retention in the
  cake can be stated.
- Positive: every new form is closed and checked against hand calculations in
  `tests/test_solids_followups.py`.
- Negative: each is no better than its inputs. The heat of solution, the wash efficiency, the
  wash's approach to saturation, a second liquid's cake liquid and the condenser's ideal
  condensate are specified or ASSUMED, not predicted.
- Left open, with the reason:
  - **The solute's share in a second liquid**: the solute dissolved in an oil and in the
    aqueous liquor is one component of one stream composition, so a following filter could not
    divide it by phase. It needs a pseudo-component or phase-resolved streams, which the
    flowsheet's streams do not carry.
  - **A second crystallizing solute** (TsCl's ortho isomer): this is solid-liquid equilibrium
    of a ternary system (eutectic or solid solution). It needs phase-diagram data that no entry
    has, and the crystallizer stays one solute.
  - **The wash efficiency itself**: a dispersion or channel model of the cake needs porosity,
    dispersion and particle data that no entry has.
  - **Leaked air in the vacuum condenser and the sublimate's deposit there**: no leak rate or
    deposition data are declared anywhere. The sublimate passes the condenser and its duty
    uncounted, and the report says so.
  - **A drying curve**: as ADR 0057, there are no measured data.
- The library entries do not change until they adopt these fields. Their `crystallizers`,
  `recipe`, `propagate --check` and `validate` results stay as they were (the library bar of
  this ADR's PR).

## Evidence

- core#183 (its comment adds carbon-tetrabromide-1 L-4, L-5 and p-toluenesulfonyl-chloride-1
  L-4), this ADR's PR.
- `src/chemeascode/domains/process/crystallization.py` (`transferred`, `solubility_at`,
  `liquor_check`, `separate_solids`, `wash_cake`, `filter_node`), `dryer.py` (`kept_by`,
  `flash`, `_sublime`, `cooling_duty`, `condense_vapour`, `outlet_temperatures`, `wash_hours`),
  `schema.py` (`SolubilityTransfer`, `LiquorComposition`, `CakeWash`, `WashDissolution`,
  `SecondLiquid`, `DryerCooling`, `DryerCondenser`, `Sublimation`), `propagate.py`,
  `model.py` (`_solid_phase_changes`), `model_basis.py`, `recipe.py`.
- `tests/test_solids_followups.py`.
- The temperature dependence of an ideal solution's solubility, `(d ln x_i / dT)_P = (H_i,aq -
  H_i,cr) / (R T^2)`: Wikipedia, "Solubility equilibrium", section "Effects of conditions",
  "Temperature effect" (read 2026-11-13).
- The wash ratio form `R = (1 - E)^n`, `n` the mass of wash over the mass of liquor in the
  unwashed cake: SysCAD documentation, "Filter Press", section "Model Theory", "Wash
  Efficiency", "Based on Wash Ratio (Mass Ratio)", help.syscad.net/FiltPrss (read 2026-11-13).
  That page cites Merritt, R. C., *The Extractive Metallurgy of Uranium*. Only the form is used;
  no value is taken from it.
- Ruth, B. F. (1935), Studies in filtration, Ind. Eng. Chem. 27, 708-723 (the filtration time
  of ADR 0057, here differentiated for the final rate). The Rachford-Rice flash and the
  condenser duty's path are the vent condenser's of ADR 0062.
