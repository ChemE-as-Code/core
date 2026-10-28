---
name: heat-integration-flowsheet-review
description: What a heat-integrated plant looks like on a flowsheet, what integration costs in start-up, cleaning and control, and what can and cannot be checked without stream data. Use when reviewing an integrated flowsheet for operability or looking for possible energy waste.
---

# Reviewing an integrated flowsheet

## Purpose and when to use

A heat-integrated plant looks different on a drawing and behaves differently when it starts, fouls or
is upset. This covers both, and what a drawing can and cannot tell you. Part of the family
`heat-integration`.

## Required inputs and missing inputs

The flowsheet, and for any judgment about the pinch the operating duties, temperatures and stream
data from the heat and material balance. Equipment design conditions are mechanical limits, not
stream data.

## Workflow and tools

Engineering guidance only; core has no calculation for this review. `cheme process energy` and
`cheme process simulate` report energy balances and exchanger audits of a solved case.

Recognising integration: process-to-process exchangers sit between units (feed against effluent,
feed against bottoms) and utility exchangers usually appear at the ends of a train (Ray and Das,
*Process Equipment and Plant Design*, Elsevier 2020, §5.1, §18.8); an intermediate utility level can
legitimately sit between process exchangers (`heat-integration-multiple-utilities`). A single
feed-against-bottoms exchanger on a column recovers heat the bottoms cooler used to throw away and
can remove that cooler; an integrated flowsheet often has fewer utility exchangers. Which utility
duty falls depends on the plant (one case in the source cuts a feed heater, another the reboiler;
§5.1, §18.8), so do not assume feed preheat reduces the reboiler one-for-one. A recurring refining
train cools a hot product or effluent against the unit's own feed, then in an air cooler, then in a
water trim cooler (Parkash, *Refining Processes Handbook*, Gulf 2003, Ch 1, Ch 2).

What integration costs (see `heat-integration` for the dispute over new design):

- Start-up: the streams that heat and cool each other do not exist at start. Moran (*An Applied Guide
  to Process and Plant Design*, 2015, Ch 18) holds that if the designer did not provide heating and
  cooling able to carry the full loads without integration, the commissioning engineer will have to
  add them. Ask how each integrated exchanger's duty is met at start-up.
- Commissioning and maintenance: an integrated network is one interdependent system; the added
  equipment has to be maintained (Moran Ch 5, Ch 18).
- Control: tighter integration is harder to control. A classical nitrogen-rejection column driven by a
  heat pump uses a lot of power and its internal reflux exchanger cannot follow changes in feed
  composition (Mokhatab, Poe and Mak, 2015, §10.4).
- Shutdown: feed and effluent are coupled, so cutting feed can briefly unbalance an exchanger past its
  design temperature; feed is reduced gradually for that reason (Parkash Ch 3).

Cleaning an integrated exchanger on line: the sources disagree. Ray and Das (§4.1.2) say large
continuous plants fit isolation and bypass valves on both sides so an exchanger can be cleaned while
the plant runs. Toghraei (*P&ID Development*, Wiley 2019, §11.7.2) says most companies fit neither,
because the plant cannot run with the exchanger out, and justifies them only with a spare or with
cleaning in place plus enough downstream inventory to ride out the gap. Ray and Das add that running
with part of a stream bypassed lowers flow through the exchanger and speeds fouling. Ask how each
integrated exchanger is cleaned and what covers its duty while out.

Whole-plant accounting: compare alternatives and vendor packages on total utility use; a saving in
one place can be spent elsewhere (a dry vacuum column saves stripping steam but its deeper vacuum
can use as much in ejector motive steam; Ray and Das §18.8).

Patterns worth a question: a heater and cooler in the same temperature range with no exchanger
between; a stream heated then cooled again or the reverse; refrigeration where cooling water would
reach the temperature; a cooler above the pinch or a heater below it
(`heat-integration-pinch-analysis`). Each is a question, not a finding: the streams may be kept apart
for safety, contamination or layout; may not run at the same time; a unit in between may need the
intermediate temperature; a coolant may have been chosen for what a tube leak would do.

## Validation and failure handling

From a drawing alone you can say which exchangers are process-to-process and which are utility, how
they are arranged and controlled, and what exists for start-up and cleaning. You cannot say whether
any of it crosses the pinch. This review does not establish that the plant is safe to start, clean or
operate.

## Outputs and provenance

A list of questions and observations, each marked as drawing-based or needing stream data, with the
source behind each operational concern.

## Required human judgment

Operating, commissioning and maintenance practice (start-up utilities, on-line cleaning, controllability) is
a project decision. Sources are silent on controllability of a whole network, spare area for
bypass-controlled exchangers and sizing of start-up utilities; treat those as project questions.

## References

- Ray and Das, *Process Equipment and Plant Design*, Elsevier 2020, §4.1.2, §5.1, §18.8.
- Moran, *An Applied Guide to Process and Plant Design*, Butterworth-Heinemann 2015, Ch 5, Ch 18.
- Mokhatab, Poe and Mak, *Handbook of Natural Gas Transmission and Processing*, Elsevier 2015, §10.4.
- Parkash, *Refining Processes Handbook*, Gulf 2003, Ch 1-3.
- Toghraei, *Piping and Instrumentation Diagram Development*, Wiley 2019, §11.7.2.

Retained as general engineering fact (cited book): recognition of integration, the start-up and
fouling concerns. Needs review before operational use: all start-up, cleaning, shutdown and control
statements, which are single-source or disputed.
