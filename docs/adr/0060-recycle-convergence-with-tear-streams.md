# 0060. Propagate converges recycles at declared tear streams

- **Status:** Proposed
- **Date:** 2026-11-05

## Context

`cheme process propagate` derives stream values node by node from the given and assumed ones.
It repeats its sweeps until nothing more can be derived, but a recycle loop never starts: the
mixer that takes the recycle waits for it, and the recycle waits for the mixer. Before this
change a plant broke the loop by hand. It typed the recycle as an ASSUMED tear stream, ran
propagate, copied what the loop gave back into the tear, and repeated. The sodium azide entry
of the process library (`sodium-azide-1`, DESIGN.md D-006, lesson L-1) converged its
mother-liquor and methanol recycles that way, with a scratch driver outside the plant. Every
upstream change made the loop unbalanced until someone re-converged it, and the tear values
were ASSUMED although they are calculated. core#181 asks for declared tear streams solved by
successive substitution or Wegstein to the flowsheet tolerance, with a finding when they do not
converge.

`cheme process simulate` already converges recycles, but in DWSIM or IDAES (`tear_streams` in
`process/simulation.yaml`). Neither runs propagate's own models (semi-batches, stills,
crystallizers, filters, dryers), and both are optional installs. ADR 0010 asks for the domain
models to stay deterministic, pure Python.

Options considered:

1. **Simultaneous (equation-oriented) solve.** Newton on every stream of the loop. This needs
   derivatives of every node model, and most of propagate's models (Rayleigh stills, the
   semi-batch integrator, solubility-limited crystallizers) are procedures, not equations.
2. **Automatic tear selection.** `simulation/translate.py` chooses tears by a depth-first
   walk. In propagate, a plant whose recycle is already given by hand would then change
   behaviour, and a poor choice (a stream whose zero guess stalls a still or a splitter
   remainder) fails in ways the user cannot see. It is left for later.
3. **Declared tears, sequential-modular iteration (chosen).** The tears are named in the
   flowsheet. Each iteration is one ordinary propagate run with the tears at their guess. This
   is the same method as the sequential-modular simulators (Westerberg et al. 1979), and it
   reuses every node model unchanged.

## Decision

- **Schema** (`process/flowsheet.yaml`, `schema.py`): `tears: [{stream, initial?}]` names one
  stream per loop. `initial: {flow, unit, basis, composition}` is the first guess; without it
  the guess is an empty stream. `convergence: {method, max_iterations, damping, tolerance}` is
  optional, with defaults `wegstein`, 100, 1 and the flowsheet's tolerance. Both fields are left
  out of a model dump when they are not given, so a flowsheet without them dumps, solves and
  fingerprints as in 1.8.0.
- **Iteration** (`domains/process/recycle.py`). Each tear stream holds its guess for the node
  it enters. The node it leaves writes into a copy of the stream, so one sweep
  (`propagate._sweep`) is one evaluation `g(x)` of every loop. The variables are the component
  mass flows (kg/h) of the tears. Successive substitution is `x + d (g - x)` with the damping d.
  Wegstein (1958) works per component with `q = s/(s - 1)` bounded to [-5, 0] (acceleration
  only, as in Aspen Plus's defaults), and its first step is a substitution. Flows are clipped
  at 0. The iterates are not rounded; the written values are rounded to six digits, as every
  propagated value.
- **Convergence**: every component and the total of every tear must satisfy
  `|g - x| <= abs + rel * max(g, x)`. The values written are those of the last sweep, with the
  tears at the guess that sweep started from, so the flowsheet as written is one consistent
  evaluation. The tear's source node balances within the tolerance; the rest balance exactly.
- **Provenance** (ADR 0011): a tear value is `calculated`, with source `cheme process
  propagate: recycle <node> from <inlets> (tear, <method>)`. Its fingerprint is
  `recycle.loop_inputs`: the given and assumed values of every stream upstream of the tear's
  source (the loop and what feeds it), those nodes as declared, their reactions, the components,
  the catalysts, the tears and the convergence settings. It is not the iterate. The iterations
  always start from the declared guess and never from values written earlier, so a converged
  plant derives the same values again and `--check` finds nothing stale. Changing a feed makes
  the loop stale.
- **Fixed parts of a tear**: a given or assumed flow or composition of a tear stays fixed, as a
  design specification, and only the other is iterated. Sodium azide's methanol recycle S3 is
  an example: its flow is set by a charge ratio and its composition is the still cut's.
- **Findings** (ADR 0006): `cheme.process-recycle` (propagate) is info for a converged loop,
  with the iterations and the worst residual against its tolerance. It is a warning for a loop
  that does not converge in `max_iterations` (with the residual) and for a loop that does not
  close (a guess from which the tear's source derives nothing). After a warning, nothing that
  depends on the loop is written: the values are those of a sweep without the tears, as before.
  `cheme.process-tear` (validate) is an error for a tear that cannot be iterated (an unknown or
  energy stream, a feed or product stream, a stream named twice, a guess in undeclared
  components or flow units). It is a warning for a tear whose flow and composition are both
  given or assumed. The adapter result (`--json`) is `not-converged` when a loop is, and its
  `iterations` count the loop's iterations.

## Consequences

- Positive: recycles are solved by the same models as the rest of the plant, deterministically.
  They become `calculated`, and they go stale when an input changes. The NaN3 entry converges
  both loops in 20 Wegstein iterations (68 by substitution) to within 0.02 % of its
  hand-converged streams. The scratch driver is no longer needed.
- Negative: each iteration is a full propagate run, so a plant with semi-batches and stills
  takes seconds (NaN3: about 10 s for propagate, and the same again in `validate`'s staleness
  check). The tolerance applies to the residual, not to the error: a slowly contracting loop
  (gain near 1) stops further from its fixed point than its tolerance. A tight
  `convergence.tolerance` is the remedy.
- Limitations: tears are declared, never chosen. Feeds sized for a product rate (a design
  spec, core#181 part 2) and component separators solved from recoveries (part 3) are not part
  of this ADR: NaN3's hydrazine top-up and the other fresh feeds that follow charge ratios stay
  ASSUMED at their converged values. A guess too far off can leave the loop open (a splitter
  remainder below zero, a still with nothing to distil); `initial:` fixes that. Wegstein is per
  component (diagonal), so strongly coupled loops gain less.
- Follow-ups: automatic tear selection (reuse `simulation/translate._tears`) as a hint when a
  loop is left unsolved; Broyden's method for coupled loops; design specs on feeds (core#181
  part 2).

## Evidence

- core#181 part 1; process-library `sodium-azide-1` DESIGN.md D-006 (lesson L-1); this ADR's
  PR.
- `src/chemeascode/domains/process/recycle.py`, `propagate.py` (`_sweep`, `recycle_findings`),
  `schema.py` (`Tear`, `TearGuess`, `Convergence`), `model.py` (`_tear_rules`).
- `tests/test_recycle.py`: the loop reactor with a recycle split of `examples/process-purge-loop`
  against its closed form (reactor feed `F/(1 - r)`, n-butane `F_A/(1 - r(1 - X))`), Wegstein's
  step on a linear map (the fixed point in its second step), substitution and damping, a loop
  that does not converge, a fixed recycle flow, the declaration findings, staleness after a
  changed feed, and model dumps without the new fields.
- Wegstein, J. H. (1958), Accelerating convergence of iterative processes, Commun. ACM 1(6),
  9-13. Westerberg, A. W., Hutchison, H. P., Motard, R. L., Winter, P. (1979), *Process
  Flowsheeting*, Cambridge University Press.
