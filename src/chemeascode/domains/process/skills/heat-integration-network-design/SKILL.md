---
name: heat-integration-network-design
description: Design a heat exchanger network from the pinch outwards: matching criteria at the pinch, the grid diagram, stream splitting, the minimum number of units, and trading energy for simplicity through loops and paths. Use after targets are known.
---

# Heat exchanger network design

## Purpose and when to use

Once the targets are known the network is designed to meet them, then simplified until the energy
given up is worth the equipment saved (Ray and Das, *Process Equipment and Plant Design*, Elsevier
2020, §5.4.3-§5.6). Part of the family `heat-integration`.

## Required inputs and missing inputs

Stream table, dTmin, the pinch (`heat-integration-pinch-analysis`,
`heat-integration-minimum-utility-targets`), and the process and layout constraints on which
streams may meet. Ask for what is missing.

## Workflow and tools

Engineering guidance only; core has no network design or synthesis, and its pinch function returns
targets only.

Start at the pinch. It splits the problem in two; design each side separately, starting at the
pinch where driving forces are smallest, then work away from it (§5.4.3). Streams that cross the
pinch are cut there, each part ending or starting at the pinch temperatures (§5.10).

Grid diagram (§5.4.4): hot streams along the top, cold streams beneath, counter-current, the pinch a
vertical line; an exchanger is a pair of circles on the two matched streams joined by a line; a
heater sits on a cold stream and a cooler on a hot stream.

Matching at the pinch (matches with both streams touching it; §5.4.3, §5.4.5). Break the count rule
and some stream cannot reach pinch temperature by process exchange, so it needs utility on the
wrong side. Break the CP rule and that match's approach falls below dTmin away from the pinch.

| | Above the pinch | Below the pinch |
|---|---|---|
| Streams at the pinch | hot streams no more than cold | cold streams no more than hot |
| CP in each pinch match | hot CP no more than cold CP | cold CP no more than hot CP |

Generally: streams leaving the pinch must be at least as many as those entering, and in each pinch
match the leaving stream's CP must be at least the entering stream's. Source discrepancy: the
headline inequality of the stream-count rule in the book's Table 5.5 points the wrong way; the forms
derived beneath it, Table 5.6, the text and the worked problems all use the form above (§5.4.3,
§5.4.5, §5.10). Matches away from the pinch need not obey either condition; choose them on process
constraints, layout, controllability and judgement (§5.4.4).

Split a stream to satisfy whichever condition fails (§5.4.5): too few streams leaving the pinch,
split a leaving stream; CP rule broken with the count right, try other pairings first, then split an
entering stream (which lowers its CP). Splitting an entering stream adds one to the entering count
and can break the count rule; check both conditions after every split.

Completing the network:

- Tick off a stream with each exchanger: size it to bring one stream to target or use up a utility,
  then drop that stream (§5.4.4).
- Place utilities away from the pinch, then join the two sides.
- Minimum number of units is roughly streams minus one, counting utilities as streams (§5.3.1); for
  a design meeting the energy target count each side of the pinch separately, as the worked problems
  do (§5.10), so the total is usually higher.
- Ticking off keeps the count low but does not guarantee the target; too much driving force at the
  pinch can starve an exchanger further out. Try other pinch matches or give the pinch exchanger
  less duty and accept an extra unit (§5.4.4).

Safety overrides every match, including at the pinch (§5.4.4): a match of streams that must never
meet is not an option, whatever it saves.

Simplifying (§5.4.6): a heat-load loop is a closed path, typically two exchangers on the same pair
of streams either side of the pinch; shifting duty around it removes an exchanger without changing
any stream's duty, but internal temperatures move and may fall below dTmin. A heat-load path runs
from a heater to a cooler; shifting duty along it restores the approach after a loop is broken, at
the cost of more utility. Breaking loops and accepting some heat across the pinch is normal when the
exchanger saving outweighs the energy penalty; an exchanger far from the pinch may run below the
targeting dTmin if above the usual minimum for its type. The source treats this as a worked-example
judgement, not a rule (§5.10).

Recipe order (§5.6): consistent stream data; split at the pinch; start at the pinch with the largest
incoming stream; meet the matching conditions, splitting where needed; place and tick off the pinch
matches; fill in the rest; join the sides; simplify with loops and paths; look for cheaper utility
levels and process changes.

## Validation and failure handling

After design, check energy and exchanger balances against the stream table, every approach against
the chosen minimum, and every match against safety and contamination constraints. `cheme process
simulate` flags temperature crosses and approaches below a declared minimum for exchangers in a
solved case.

## Outputs and provenance

The grid diagram or match list with duties, the pinch matches and splits with the rule that
required them, the unit count against the minimum, and each deliberate rule-break with its reason.

## Required human judgment

Matches, splits, which loops to break and the energy-versus-equipment trade, and whether any match is
acceptable on safety grounds. Sources are silent on mathematical-programming synthesis, flexibility
across operating cases, spare area for a bypass-controlled exchanger, and retrofit methods beyond
correcting exchangers that cross the pinch; say so rather than improvising.

## References

- Ray and Das, *Process Equipment and Plant Design*, Elsevier 2020, §5.3.1, §5.4.3-§5.4.6, §5.6, §5.10.

Retained as general method (cited textbook): the matching rules, splitting, tick-off, loops and
paths. Needs review before operational use: the unit-count statements and the below-dTmin remark for
exchangers away from the pinch.
