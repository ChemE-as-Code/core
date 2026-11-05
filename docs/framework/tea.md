# TEA

`cheme assess tea` evaluates the economics of a plant. Its purpose is a decision, not a
precise number: it states the question the analysis supports and builds the capital cost from
the plant's own estimate. It prices what the plant buys and sells and computes the discounted
cash flow. It then shows where the money goes, which premises dominate the outcome and at which
value of each one the decision would turn. Its four principles:

- **comparable**: same product specification, boundary, scale, location and time basis;
- **traceable**: every input with source, year, unit and status;
- **uncertainty-aware**: ranges and drivers, not one number;
- **decision-led**: detail in proportion to the stage and its decision.

It covers a wide range of plants:

- continuous and batch, in one or several operating cases;
- material and energy main products (LCOP, cost of production, LCOE/LCOH);
- products, co-products, components of a flow, consumables the flowsheet does not carry,
  emissions with a carbon price and free allocation;
- replacements, turnarounds and grants as periodic events;
- prices that move over the plant's life.

Where the code and its companions live:

- Code: `domains/assessment/tea/`:
  - `schemas.py` (`estimate/tea.yaml`);
  - `build.py` (premises to lines, findings);
  - `model.py` (the cash flow);
  - `uncertainty.py` (Monte Carlo, tornado);
  - `report.py` (results, formats, comparison);
  - `gates.py`.

  The flowsheet's feed and product rates are in `domains/assessment/flows.py`, shared with the
  LCA.
- Template notes: `templates/project/estimate/README.md` and `STAGES.md`.
- Skill: `tea`. It has a complete example.

## Inputs

| file | kind | what |
|---|---|---|
| `estimate/tea.yaml` | `tea` | the premises, see below |
| `process/flowsheet.yaml` (`materials.yaml`, `reactions.yaml`, `catalysts.yaml`) | `process-flowsheet` | the feeds and products in each case. A material terminal counts in kg/h with its components, an energy terminal (`kind: energy` streams with `duty`) in kWh/h |
| `plant.yaml` | `plant` | the stage, which sets the estimate class expected |
| `estimate/cost-basis.yaml`, the equipment list and datasheets | `cost_basis`, ... | `isbl.source: equipment`: the bare module cost of `cheme assess equipment` |
| `estimate/rates.yaml`, `layout/plant-model.yaml` | `rates` | `isbl.source: mto`: the direct and indirect cost of `cheme assess estimate` (its contingency is left out, so it is not counted twice) |
| `lca/lca.yaml` | `lca` | `operation` when `tea.yaml` gives none (a finding says so; a different one is `tea-basis-mismatch`); the flows it maps as emissions; `allocation.prices` (and `allocation.properties.<p>.price`) checked against the products' prices here: the same plant at other price ratios gives the revenue and the economic allocation different premises (`tea-lca-price-mismatch`) |

## `estimate/tea.yaml`

`cheme schema tea` prints the JSON Schema; the skill `tea` has a complete example, marked
`example: true` (its figures show the shape only). `cheme init` writes no `tea.yaml`: the
project writes it when it prices its plant. Every value is a `Value`: `value`, `status`
(`ASSUMED` or `QUOTED`), `source`, `year`, and optionally `uncertainty` and `swing: {low, high}`.
The uncertainty is as in the LCA: lognormal `gsd2` or pedigree, normal `cv`, triangular or
uniform `low`/`high` multipliers.

### Decision and basis

- **`currency`, `cost_year`**: every cost is in one currency and year, in real terms.
  `example: true` marks example numbers.
- **`decision`**:
  - `question`;
  - `metric`: `npv` and `irr` must be at least the threshold, `lcop` and `cash_cost` at most;
  - `threshold`: npv in currency, default 0; irr a fraction, default the discount rate; lcop and
    cash_cost per the basis unit, required;
  - `confidence`: the probability of meeting the threshold the decision needs;
  - `alternatives`.
- **`basis`**:
  - `product`: the flowsheet product whose levelised cost is computed;
  - `unit`: what its cost is per. The default is its price's unit, else t for a material and
    MWh for an energy product. Give `conversion` for a unit of another kind;
  - `specification`, `boundary`, `scale`, `location`.

### Operation

- `case`, or **`cases`**: `[{case, share, prices, source}]`. Each case's flows count by their
  share of the operating hours, and the shares sum to 1. A flow priced differently in a case
  becomes one line per case, `<key>~<case>`. These share one rate input and one price input, so
  the price driver stays one.
- **`operation`**:
  - `hours_per_year`, `life_years`;
  - `ramp_up`: capacity fractions of the first years;
  - `utilisation`: the load after the ramp-up;
  - `source`.
- **`operation.batch`**: `{cycle_time, basis_hours, trains, batches_per_year, success_rate,
  source}`. The flowsheet's rates are those of one batch over `basis_hours`. The operating hours
  are batches times `basis_hours`, with batches = `batches_per_year`, else hours x trains /
  cycle time. `success_rate` scales the products sold. `{recipe: true, source}` (with
  `success_rate` if wanted) takes the cycle time and the batches per year from
  `process/recipe.yaml` (`cheme process recipe`, ADR 0051); the flowsheet's rates are then the
  recipe's year averages, so `basis_hours` is hours / batches and `trains` 1 (the recipe's
  parallel units are in its cycle). A recipe on other hours than `hours_per_year`, or one that
  gives no cycle, is `cheme.tea-batch-recipe`.

### Capital

- `capex.isbl`:
  - `source`: `equipment`, `mto`, or `given` with `value`;
  - `scaling`: `{reference, unit, exponent}`. For a given value at another capacity: ISBL x
    (capacity / reference) ** exponent, where the capacity is the design capacity: the main
    product per year in its largest case, at full load;
  - conversions to the file's basis: `exchange_rate`, `escalation`, `location_factor`. The
    project's own costs already stated in the TEA's currency and year (quotations for this
    plant) are neither converted nor moved by the location factor;
  - `purchased_installation`: installed / purchased, for items with a purchased cost only;
  - `uncovered_allowance`: a fraction of the costed ISBL for what the estimate leaves uncosted
    (equipment or mto): items no correlation covers, take-off rows without a rate;
  - a catalyst's first fill is a line of its own, of its price's year: `escalation` (from the
    cost index's year) applies to it only when that is the index's year, and a fill of a third
    year is reported (`tea-cost-year`). A fill priced in another currency than the estimate's
    counts as it is when that is the TEA's currency and cost year, else it is left out
    (`tea-capex-own-cost`);
  - optionally `uncertainty`, `swing` and `estimate_class`.
- `osbl` (x ISBL), `owners_cost` (x (ISBL + OSBL)), `contingency` (x (ISBL + OSBL + owner's
  cost)). Their sum with the ISBL is the **fixed capital**.

### Lines: what the plant buys and sells

- **`prices`**: `{key: feed:<id> | product:<id>, component?, value, unit, conversion?,
  category?, profile? | escalation?, status, source, year, uncertainty, swing}`.
  - `unit` is one of kg, t, lb, st, kWh, MWh, MJ, GJ, MMBtu, therm, Nm3, m3, L, gal, bbl,
    kmol, ea.
  - A unit of the flow's kind converts by itself. Any other unit needs `conversion`: units per
    kg or kWh of the flow, with its source, e.g. 0.0455 MMBtu/kg (LHV) for a gas, or Nm3/kg.
  - `component` prices only that component's mass, `<key>@<component>`, for example H2 in an
    off-gas.
  - A product with a disposal cost has a negative price.
- **`free`**: `{key, reason}` for flows that carry no price (never the main product).
- A product with a negative price is carried as a cost line: a material one in category
  disposal, an energy one (rejected heat) in category utility.
- **`variable_opex`**: `[{id, per, component?, amount, unit, value, category, profile? |
  escalation?, ...}]`. These are consumables, utilities, fees and incentives the flowsheet does
  not carry, each a line `variable:<id>`:
  - `per` is a flow (`amount` per kg or kWh of it, or of its `component`), `hour`, or `batch`;
  - `value` is the price per `unit`;
  - a negative price is a credit (category `incentive` counts as a subsidy).
- **`emissions`**: `{price, profile? | escalation?, sources, allocation?}`.
  - Each source `{id, key, component?, factor, unit, conversion?, captured?}` charges t CO2-eq
    per `unit` of the flow or component, less what is captured (`emission:<id>`).
  - `allocation: {benchmark, per, unit, fraction, profile?}` credits the free allowances
    (`allowance:carbon`).
  - Every emission line takes `price:carbon`.
- **Categories**: feed, utility, chemical, catalyst, disposal, emission, incentive, byproduct,
  other. The default follows the flow: a material feed is a feed, an energy feed a utility, a
  product a co-product credit, or disposal when its price is negative. They group the cost of
  production.
- **Price paths**: `profile` gives multipliers by operating year, the last holding after.
  `escalation` gives a real change per year, compounding.

### Fixed cost and events

- **`fixed_opex`**:
  - `maintenance` and `insurance_tax`: x fixed capital;
  - `labour`: `operators` x `cost_per_operator`, plus `supervision`;
  - `overheads`: x (labour + maintenance);
  - `items`: own annual costs, each with an id and an optional price path.
- **`events`**: `[{id, kind, cost | fraction_of_isbl, every_years | every_hours, first_year,
  downtime_days, treatment, skip_last, source}]`. These are replacements (catalyst, membrane,
  stack), turnarounds, sustaining capital, and one-off costs or grants (a negative cost).
  - `every_hours` counts the plant's operating hours at its load, so a stack lasts longer at a
    lower capacity factor. In batch operation these are batches x cycle time / trains.
  - `first_year` defaults to `every_years`, else 1. 0 and below are the last construction
    years. A one-off after the last operating year is not charged. With `every_hours`, a given
    `first_year` is the year of the first occurrence and the next ones follow every
    `every_hours` of running after it; without one, the running hours count from start-up.
  - `downtime_days` lowers the load of the year it occurs in, once per occurrence (days of the
    plant's operating hours).
  - `skip_last` (default true) leaves a recurring event out of the last operating year; a
    one-off is never skipped.
  - `treatment: capital` depreciates the cost from start-up until the next occurrence (or over
    the rest of the life).

### Finance and uncertainty

- **`finance`**:
  - `discount_rate` (real) and `tax_rate`;
  - `losses`: `credit`, offset against the owner's other income, or `carry_forward`;
  - `depreciation_years` (straight line, default the life), or `depreciation`, a list of
    fractions per operating year;
  - `construction`: fractions per year, summing to 1;
  - `working_capital` (x fixed capital), or `working_capital_days`: days of feed inventory,
    product inventory, receivables and payables;
  - `salvage` (x fixed capital).
- **`class_by_stage`**: the AACE 18R-97 class each stage is expected to reach (default concept
  5, basic 4, detail 3).
- **`uncertainty`**:
  - `iterations`, `seed`;
  - `defaults` by status (`ASSUMED`, `QUOTED`);
  - `rates` by the provenance of the flowsheet values, with `rate_mode: independent`;
  - with `rate_mode: throughput`, every rate moves together through `throughput`, so the mass
    balance holds in every sample.

  `sensitivity.swing` is the default tornado swing.
- **`scenarios`**: `{id, prices: {line or carbon: price}, scale: {input id: multiplier},
  source}`. A scenario price replaces the line's price, in the baseline price's unit.

### Input ids

Input ids name what a scenario scales, what the Monte Carlo samples and what the tornado and the
break-even move:

- `price:<line>`, `rate:<line>` (a line is `feed:X`, `product:Y`, `product:Y@C` or
  `variable:<id>`; a flow's lines per case, `feed:X~<case>`, share its inputs), `rate:<line>`
  only for `emission:<id>` and `allowance:carbon` (their price is `price:carbon`),
  `price:carbon`, `conversion:<line>`;
- `capex:isbl`, `capex:osbl`, `capex:owners_cost`, `capex:contingency`;
- `opex:maintenance`, `opex:labour`, `opex:insurance_tax`, `opex:overheads`, `opex:<item>`,
  `event:<id>`;
- `operation:hours_per_year`. In batch operation: `operation:cycle_time` or
  `operation:batches_per_year`, and `operation:success_rate` (with a derived batch count the
  hours stay an input too);
- `operation:utilisation`, and `operation:throughput` with `rate_mode: throughput`;
- `finance:discount_rate`, `finance:wc:<days>`.

## Calculation

The cash flow by year `t` (0 is the first construction year):

- **Construction years:** the fixed capital times each year's fraction, plus events in those
  years.
- **Working capital and salvage:** working capital is spent in the last construction year. It is
  recovered, and the salvage value received, in the last operating year.
- **Operating years**, at the year's load (ramp-up, then utilisation, less the downtime of
  events):
  - revenue (product lines) minus the cost lines, each at its price path;
  - minus the fixed operating cost and the events expensed that year;
  - minus income tax on that result less depreciation.
- **Tax losses:** a loss is credited, or carried forward to later profits.
- **Last year:** the book value left is written off and a salvage above it is taxed.
- **Discounting:** by `(1 + i) ** t`.

The results:

- **NPV:** the sum of the discounted cash flows.
- **IRR:** found by bisection; none when the cash flow does not change sign.
- **Discounted payback:** years from start-up.
- **LCOP:** the main product's price that makes the NPV zero, every other product a credit.
  With losses credited the NPV is linear in that price and two evaluations give the LCOP; with
  losses carried forward it is found by a bracketed search. With a price path on the main
  product, the LCOP is the base price the path multiplies: with `escalation` the price of the
  first operating year, with a `profile` the price its multiplier 1 stands for (the first
  year's price is the LCOP x its first multiplier).
- **Cash cost:** (variable cost + fixed cost - co-product revenue) per unit of the main product,
  first full year.
- **Cost of production:** per unit of the main product, by category, plus the fixed cost, the
  events as an annuity at the discount rate, and capital and tax (the rest of the LCOP). It
  sums to the LCOP. With `incentive` lines, the LCOP without them is reported too.

### Boundary

The operating cost and revenue count only the flowsheet's terminals. What the flowsheet implies
but does not declare is not in them: a heater, cooler, compressor, pump, column or reactor with
no energy stream (its steam, cooling, refrigeration or power is priced nowhere), or a product
without `category` (its disposal or treatment as wastewater, off-gas, solid waste or emission
is not stated). The TEA runs `assessment.flows.boundary_gaps` on the flowsheet and reports
these as findings `cheme.boundary-*`, the same check as `cheme process energy` and the LCA's
`boundary_check` (the rules are
in the docstring of `domains/assessment/flows.py`); it does not add or price anything for them.

The check is narrow, and the report says so. It covers steps of the unit kinds compressor, pump,
heater, cooler, shortcut column and the reactors (a step counts as connected when any energy
stream is at its port), terminal categories and utility levels. It does not cover steps of
other kinds (component separators, flash drums, mixers, splitters, unknown classes), whether an
energy stream reaches a utility terminal (a step-to-step stream counts), or whether duties are
given or balance (`cheme process energy`). A step is exempt only when declared adiabatic:
`mode: adiabatic` in `process/simulation.yaml` (a reactor) or `heat: adiabatic` on its bed, tank
or batch. A `simulation.yaml` that does not load is `cheme.boundary-adiabatic-unread`: a
warning naming the unassigned reactors it could have exempted, info when there are none.

The report's `boundary` (`--json`, `/api/tea`) has:

- `complete`: no warning *from these rules*; not a claim that the inventory is complete;
- `checked` (the rules that warn), `noted` (info only: feed categories, energy terminals'
  category, utility levels), `not_checked`: the coverage above, as text;
- `categories`, `unassigned_duties`, `gaps` (rule, level, ids, message, file, line);
- `excluded_products`: products without a category that have no price, are not listed free, have
  no `variable_opex` item of category disposal per them and no emission source on them, and are
  not the main product, so the operating cost counts them at no cost. A product without a
  category that is costed in one of these ways is a classification gap only.

`estimate/tea.md` states gaps under its title and has a section Boundary: what was and was not
checked, what the variable operating cost excludes, and the gaps by rule.

### Uncertainty and sensitivity

- **Break-even:** for every input, the value at which the decision's metric meets its
  threshold. This is the value that would change the decision. It is searched between x0.001
  and x1000, nearest to the baseline.
- **Tornado:** one input at a time, each moved to its `swing`, else to the P10 and P90 of its
  distribution, else to the default swing. The largest effect comes first.
- **Monte Carlo:** one multiplier per input id. It reports the P10, P50, P90 and mean of the
  fixed capital, LCOP, cash cost, NPV and IRR, the probability of meeting the decision, and
  Spearman rank correlations naming the drivers. Results are reproducible from the seed.
  - NPV and IRR are reported only when the main product is priced.
  - A metric that fewer than half the samples have (an IRR) gets no statistics.
- **ISBL uncertainty:** without its own, the ISBL is spread over the claimed class's AACE range
  as a triangle, for example class 5 from x0.5 to x2.0 with its mode at 1. A capital range
  narrower than the class can claim is `cheme.tea-capex-range`.
- **Composite inputs:** an uncertainty given on a part of one (exchange rate, escalation,
  location factor, labour headcount) is reported as unused (`tea-uncertainty-unused`); give it
  on the composite. The discount rate has only its own uncertainty, never a default.

### Estimate class against the stage

The claimed class comes from `isbl.estimate_class`, else from the equipment estimate's
`estimate_class` in `cost-basis.yaml`, else 5. `cheme.tea-class-stage` warns in two cases:

- the class is finer than the stage supports, for example class 3 at concept, when the scope is
  not defined that far;
- the class is coarser than the stage expects before its decision.

## Findings

| rule | level | finds |
|---|---|---|
| `cheme.tea-no-premises`, `-premises` | error | no `estimate/tea.yaml`, or it does not load |
| `cheme.tea-no-operation`, `-case`, `-product`, `-no-flowsheet` | error | what the evaluation cannot do without (the flowsheet's own errors stop it too) |
| `cheme.tea-flow-invalid` | error | a terminal's streams cannot be counted (mixed kinds, unknown unit, negative duty) |
| `cheme.tea-price-unknown`, `-price-unit`, `-price-component`, `-product-unit` | error | a price for a key that is not a terminal; a unit that needs a conversion; a component the streams do not carry; a main product unit that cannot be converted |
| `cheme.tea-variable-per`, `-emission-source`, `-emission-components`, `-case-price` | error / warning | a variable item or emission source on an unknown flow or component; a case price for the main product (error) or for a flow without a baseline price (warning); a case price for a key that is no flow is `tea-price-unknown` |
| `cheme.tea-currency`, `-capex-source` | error | an estimate in another currency without `exchange_rate`; the estimate it builds on does not compute |
| `cheme.tea-flow-incomplete` | warning | a stream state is missing; the rest is counted |
| `cheme.tea-price-missing` | warning | flows without a price and not free (a product costed by a disposal item or an emission source is not missing); a decision on npv or irr without a price of the main product |
| `cheme.tea-capex-uncovered` | warning / info | items not costed, or costed by purchase only, or take-off rows without a rate, without an allowance (info with one) |
| `cheme.tea-capex-own-cost` | warning | an own cost, or a catalyst fill in another currency than the estimate's, in neither the TEA's nor the estimate's currency and year: left out |
| `cheme.tea-cost-year` | warning / info | an estimate (or a given ISBL: info) of another year, not escalated; a catalyst fill priced in neither the index's nor the TEA's year |
| `cheme.tea-class-stage` | warning / info | the class against the stage |
| `cheme.tea-capex-range` | warning | a capital range narrower than the class supports |
| `cheme.tea-basis-mismatch` | warning | operation different from `lca/lca.yaml` |
| `cheme.tea-lca-price-mismatch` | warning / info | the products' relative prices differ by more than 5 % from the allocation prices of `lca/lca.yaml` (warning for `method: economic`, info when economic is only compared), or a product priced there is free or unpriced here |
| `cheme.tea-batch-overbooked` | warning | more batch hours than the trains have |
| `cheme.tea-emission-unpriced` | warning / info | `lca/lca.yaml` maps emissions no source prices (info without `emissions`) |
| `cheme.tea-conversion-unused` | warning | a conversion or escalation that is not needed, so not used |
| `cheme.tea-no-decision`, `-no-fixed-opex`, `-example`, `-example-rates`, `-scenario` | warning | what makes the result weaker than it looks |
| `cheme.tea-price-year`, `-no-year`, `-operation-from-lca`, `-capex-missing`, `-confidence`, `-case-terminal`, `-batch-basis`, `-event-beyond-life`, `-turnaround-hours`, `-depreciation`, `-uncertainty-unused` | info | worth knowing |
| `cheme.tea-not-comparable` | warning | `--compare`: the two analyses differ in a premise of their basis |
| `cheme.boundary-utility-unassigned` | warning | a step of a checked kind with no energy stream: the operating cost excludes its utility (see Boundary) |
| `cheme.boundary-unclassified` | warning / info | a product (warning) or feed (info) without a category; excluded from the cost only when it is also unpriced and not free |
| `cheme.boundary-adiabatic-unread` | warning / info | `process/simulation.yaml` does not load, so `mode: adiabatic` is not read: warning when an unassigned reactor depends on it (named), info otherwise |
| `cheme.boundary-energy-terminal`, `-utility-level` | info | an energy terminal not classified utility; a heat utility without its level |

## Commands

```sh
cheme assess tea                 # estimate/tea.md (Markdown)
cheme assess tea --json          # premises, results, findings, provenance
cheme assess tea --csv           # the cash flow by year
cheme assess tea --sensitivity   # tornado and break-even per input
cheme assess tea --write         # estimate/tea.md, tea-cashflow.csv, tea-sensitivity.csv,
                                 # tea-uncertainty.csv (with a Monte Carlo)
cheme assess tea --check         # exit 1 when one of them is not current
cheme assess tea --compare main  # what the two do not share, then the results
```

## Gate `kind: tea`

`require` takes any of these:

- `prices`: every flow with a rate, other than the main product, is priced or free.
- `no-example`
- `class-stage`: the class equals the class the stage expects.
- `decision`: stated and met, with the confidence when there is a Monte Carlo.
- `tea-current`

## Viewer API

`GET /api/tea?rev=` returns the document of `cheme assess tea --json` without the source, with
`rev`. Its keys are:

- `currency`, `cost_year`, `example`, `stage`, `estimate_class`, `expected_class`
- `decision`, `metric`, `threshold`, `basis`, `operation`
- `capex` (each line in its estimate's `currency`, with `tea_value`), `capex_range`
- `flows` (`per_year`: the net income of the flow's lines, revenue positive and cost
  negative; `prices`: every price of the flow), `lines`, `variable`, `emissions`, `opex`,
  `events`
- `results`, `cost_of_production`, `cashflow`
- `scenarios`, `inputs`, `break_even`, `tornado`, `uncertainty`, `boundary`, `findings`

A number that does not exist, such as an IRR, is null. The endpoint answers 404 without
`estimate/tea.yaml`, and 422 when the TEA does not compute. `/api/repo` has `has_tea`, and
`cheme export-static` exports `tea`. The viewer shows the analysis on its TEA page.
