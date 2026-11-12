# 0070. Propagate solves feeds for design specifications, and component separators from their split

- **Status:** Proposed
- **Date:** 2026-11-12

## Context

`cheme process propagate` derives every stream from the feeds forward, and since ADR 0060 it
converges the recycles torn at `tears:`. Two gaps of core#181 remained.

**Part 2: feeds solved for a target.** A plant is designed for a product rate (1000 t/a), a
charge ratio (8.60 kmol of alcohol per kmol of metal in the reactor's charge) or a purity (an
inert's share in a loop). Propagate cannot run backwards from such a target, so every batch
entry of the process library scaled its feeds by hand or by script and iterated them to a
fixed point: methyltriphenylphosphonium-bromide-1 L-6, benzyl-bromide-1 L-7, acetyl-chloride-1
L-7, carbon-tetrabromide-1 L-7, p-toluenesulfonyl-chloride-1 L-6, benzoyl-chloride-1 L-6. In a
batch plant the target is an annual amount, the batch product times the batches per year, and
the cycle depends on the batch (jacket heat-up and cool-down times, a filtration's time): the
batch size and the cycle were iterated by hand as well. potassium-tert-butoxide-1 L-8 is the
hardest case: the make-up of an alcohol loop with a 0.5 % purge holds a charge ratio. With a
loop gain of 0.995 the recycle is 199 times as sensitive to the make-up, which was tuned by
hand, and Wegstein took 156 iterations at the tear S19.

**Part 3: component separators.** A separator without one of propagate's models (a
molecular-sieve dryer, a decanter, a scrubber with a known split) was only checked. Its
outlets had to be typed as ASSUMED values from a balance script (potassium-tert-butoxide-1
L-4, A001). When a feed upstream changed, they did not follow it, and a spec on a feed could not
reach anything downstream of such a separator.

Options considered:

1. **Nested loops (a spec around the tear iterations).** Each change of a feed reconverges the
   recycle. This is simple, but every spec iteration costs a full recycle convergence, and with
   a gain near 1 each of them is slow.
2. **Spec feeds as tears.** The flows would be treated as further iterates of Wegstein. But a
   target is not a fixed point `g(x) = x`, and Wegstein's diagonal step has no handle on it.
3. **Simultaneous Newton-Broyden on tears and specs together (chosen).** The unknowns are the
   tears' component flows and the specs' variables. The residuals are `g(x) - x` of the tears
   and the specs' relative deviations. Each evaluation is one ordinary sweep, as in ADR 0060.
   This is what the sequential-modular simulators do with "simultaneous" design-spec
   convergence (Aspen Plus's Broyden option). It reuses every node model unchanged.

For the batch size, the flowsheet holds year averages (ADR 0051), so a spec on the annual amount
sets the flowsheet's rate. The cycle, and with it the batch size that gives this rate, belongs
to the recipe, which propagate does not write.

## Decision

- **Schema** (`process/flowsheet.yaml`, `schema.py`): `specs: [{id, vary, target, tolerance,
  cases, provenance, source}]`.
  - `vary` is either `{stream, initial, unit?, low?, high?, with?}`, the flow of a feed stream
    (a stream from a feed terminal), or `{node, port, initial, low?, high?}`, the fraction of a
    splitter's inlet (class SplittingMaterial) that leaves by an outlet not fixed in its
    `split:`. `with: {stream: ratio}` lists feeds whose flow follows the varied one at a fixed
    ratio (in its unit): charge ratios are kept.
  - `target` is `{stream, component?, quantity, value, ...}` with quantity `flow` (a flow unit,
    default `units.flow`), `annual` (t or kg per year: the flow times `hours`, default the
    recipe's `hours_per_year`), `ratio` (to `per: {stream, component?}`, on moles or masses)
    or `fraction` (a component's share of the stream).
  - `tolerance` is relative (default 1e-6).
  - Blocks and steps take `recovery: {outlets: {port: {component: fraction}}, provenance,
    source}`: the share of each component's inlet flow (all material inlets together) that
    leaves by each listed port. One material outlet may be left out and takes the rest.
  - Both fields are excluded from a dump when empty or absent, so a flowsheet without them
    dumps, solves and fingerprints as in 1.11.0.
- **Component separators** (`separator.py`): a block or step with `recovery:`, no other model
  (reactions, still, crystallizer, filter, dryer) and a separating or generic class is solved
  in the sweep. Its outlets' flows and compositions are `calculated`, with source `cheme process
  propagate: separator <node> from <inlets>`. The temperatures and pressures stay as given. The
  split is specified, not predicted: `provenance` and `source` say where it comes from.
- **Solving** (`design_spec.py`): with `specs:`, `propagate.derive` calls `design_spec.solve`.
  - The unknowns are the iterated tear component flows (kg/h, as in ADR 0060) and the specs'
    variables.
  - The residuals are `g - x` per tear component and `(value - target) / target` per spec.
  - The Newton step uses a Jacobian from forward differences (one sweep per unknown), kept up to
    date by Broyden's good update. It is refreshed when a step does not reduce the merit
    function (the squared residuals relative to each tear's flow) or a loop starts to carry a
    new component.
  - A fresh Jacobian's step is halved up to 8 times. A singular Jacobian (a tear whose flow or
    composition is fixed has a direction its residual does not see) takes the least-squares
    step with a vanishing Levenberg-Marquardt term.
  - One step moves a split by 0.25 at most and a flow by a factor of 10. The variables stay
    within `[low, high]` (default `[0, inf)`, a split `[0, 1]`).
  - The loop is converged by ADR 0060's test (`|g - x| <= abs + rel max(g, x)` per component
    and per total). Each spec is met within its tolerance.
  - Nothing is rounded while iterating. The values written come from one more sweep, rounded to
    six digits, from the variables and the tear values rounded to six digits.
  - Without tears, only the variables are iterated, one sweep per step.
- **Provenance** (ADR 0011): an adjusted flow and the flows that follow it are `calculated`,
  with source `cheme process propagate: spec <id> (<target>)` (a follower: `spec <id> (<ratio>
  x <stream>)`). Their fingerprint is `design_spec.spec_inputs`: the specs, the given and
  assumed values upstream of the targets (`recycle.upstream`, ADR 0060's loop inputs) and of the
  target streams, and the recipe's batch size and hours. The tear values keep ADR 0060's
  fingerprint, now extended by the specs (`recycle.loop_inputs`). A split fraction has no place
  in the file: the outlets it sets are written, and the finding reports the fraction. The
  iterations always start from `initial`, so a solved plant derives the same values again and
  `--check` finds nothing stale. A changed target makes the adjusted feeds stale.
- **Batch size and cycle** (`recipe.batch_for_rate`): `batch = rate x cycle(batch)` is solved by
  a substitution and then secant steps on the recipe's evaluation. Every batch model's hours of
  flows are taken from the batch size tried. When the flowsheet's rate differs from the
  recipe's, `cheme.recipe-basis` names the batch size that closes it and its cycle. When no
  batch size does, because the cycle grows about as fast as the batch, the finding gives the
  most the batches tried made, the train's capacity. Propagate does not write the recipe: the
  batch size stays a design input (given or assumed) in `process/recipe.yaml`.
- **Findings** (ADR 0006):
  - `cheme.process-design-spec` (propagate) is info for each spec met, with its variable and
    the target reached. It is a warning for a spec whose target does not depend on its
    variables, has no value (the target stream is not derived: the node problems of that point
    are reported), lies beyond the variable's bounds (the variable held at a bound twice
    running), or is not met within `convergence.max_iterations`. After a warning, nothing that
    depends on the specs or the tears is written (the sweep without them, as ADR 0060), and the
    adapter result is `not-converged`.
  - `cheme.process-spec` (validate) is an error for a spec that cannot be solved as declared:
    an id or variable named twice; an unknown case, stream, component or unit; a varied stream
    that is no feed, is a tear, or whose flow (or a follower's) is given or assumed; a split of
    no splitter or of a port its `split:` fixes; an initial value outside the bounds; an annual
    target without hours; a flow target on its own variable.
  - `cheme.process-recovery` (validate) is an error for a `recovery:` beside another model, on
    a mixing, splitting, pass-through or reacting class or on a block with steps inside; a
    listed port that is no material outlet; two outlets left out; an undeclared component; a
    fraction outside [0, 1]; fractions of a component summing beyond 1, or, with every outlet
    listed, to other than 1.
  - Propagate reports a separator it cannot split as `cheme.process-recovery` (warning).

## Consequences

- Positive:
  - Feeds sized for a rate, a charge ratio or a purity are `calculated`, deterministic and go
    stale with their inputs. The hand and script iterations of the batch entries are no longer
    needed.
  - On a scratch copy of potassium-tert-butoxide-1, with A001 as a `recovery:` and two specs
    (1000 t/a of S15; 8.60 kmol TBA in S9 per kmol K in S2, S4 following S3 at the azeotrope's
    ratio), the loop and both specs converge in 3 Broyden iterations (8 sweeps, about 10 s).
    Before, Wegstein took 156 iterations (about 60 s) for the loop alone, with the make-up tuned
    by hand. The solve finds the hand values: S1 43.9613 kg/h (hand: 43.9613), S3 92.7044 kg/h
    (hand: 92.7064, the sieve's split rounded).
  - On p-toluenesulfonyl-chloride-1, a spec on toluene S4 with chlorosulfonic acid and
    ammonium chloride following it gives S4 77.2603 kg/h for 1000 t/a (hand: 77.2601) in 5
    sweeps. At 1150 t/a, `cheme.recipe-basis` names the 3118.75 kg batch (21.48 h cycle) that
    closes the recipe. At 1500 t/a it reports that the train makes about 151 kg/h at most: the
    jacket-limited cycle grows by about 6.5 h per tonne of batch.
- Negative:
  - Each Jacobian costs one sweep per unknown (tear components plus specs). For a plant with
    many components in its loops, that is more sweeps than a Wegstein iteration, but far fewer
    iterations near a gain of 1.
  - The target holds to the six digits propagate writes, not to the spec's tolerance: an
    annual target reads 8000.02 for 8000 when the feed is written as 1321.13.
  - Feeds that follow other streams than the varied one (a scrubber's caustic per kmol of
    vented HCl) need their own spec. Otherwise they stay at their hand values and the balance
    finds them.
- Limitations:
  - One variable per spec, and the specs are solved together. A spec that its variable cannot
    move, or two specs that fix the same degree of freedom, is a singular Jacobian and a warning.
  - The batch size is reported, not written. Propagate's batch models take their hours of flows
    from the recipe's batch size, so after changing it, run `--fill` again.
  - A `recovery:` is a constant split, not a separation model (no temperature or pressure, no
    duty).
- Follow-ups:
  - Automatic tear selection (core#181).
  - A spec on a duty or a temperature.
  - `batch_size: {from: rate}` in the recipe, so that the batch closes on its own.

## Evidence

- core#181 parts 2 and 3. Process library DESIGN.md lines: potassium-tert-butoxide-1 L-4, L-7,
  L-8; p-toluenesulfonyl-chloride-1 L-6; methyltriphenylphosphonium-bromide-1 L-6;
  benzyl-bromide-1 L-7; acetyl-chloride-1 L-7; carbon-tetrabromide-1 L-7; benzoyl-chloride-1
  L-6. This ADR's PR.
- Code: `src/chemeascode/domains/process/design_spec.py`, `separator.py`, `propagate.py`
  (`Settings`, the `component-separator` behaviour), `recycle.py` (`converge`, `upstream`),
  `recipe.py` (`batch_for_rate`), `schema.py` (`DesignSpec`, `Recovery`), `model.py` (rules).
- `examples/process-design-spec`: an isomerisation loop with a component separator, its fresh
  feed solved for 8000 t/a of isobutane and its purge for 10 wt% propane in the reactor feed.
- `tests/test_design_spec.py` covers:
  - the example against its closed form (both variables within six digits, from far initial
    values too);
  - a two-feed mixer with a separator, solved without tears for flow, annual and ratio targets
    against closed forms (a ratio its variable cannot move is a warning);
  - the bound and declaration findings, the adapter status, and staleness after a changed
    target;
  - separator outlets and rules, and dumps without the new fields;
  - `batch_for_rate` against `b = r c0 / (1 - r k)` for a jacket-timed cool-down whose cycle
    is linear in the batch, and above the cap `1/k`.
- Broyden, C. G. (1965), A class of methods for solving nonlinear simultaneous equations, Math.
  Comp. 19, 577-593. Westerberg, A. W., Hutchison, H. P., Motard, R. L., Winter, P. (1979),
  *Process Flowsheeting*, Cambridge University Press (simultaneous convergence of design specs
  and tears).
