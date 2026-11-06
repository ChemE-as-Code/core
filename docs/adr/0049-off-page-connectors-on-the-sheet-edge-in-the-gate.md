# 0049. Off-page connectors off the sheet's edge are a drawing finding the gate fails on

- **Status:** Proposed
- **Date:** 2026-11-05

## Context

The plant owner decided that off-page connectors go on the sheet's edges, incoming on the left
and outgoing on the right (a utility header's connectors may share the top or bottom edge), even
where moving one there costs a line crossing; such a crossing is accepted in the plant's gate
with a reason. Until now only the drafting agents and the `pid-drafting-standards` skill knew
this, so a connector left mid-sheet passed `cheme validate` and the `drawing-clean` gate.

DEXPI 2.0.1 draws two different things with the same classes
(`FlowIn`/`FlowOutPipeOffPageConnector`): a connection to another sheet or the battery limit,
and an open end drawn where it is (a relief valve's tail pipe to atmosphere, a vent, an open
drain, a tanker hose connection). The process library's sheets carry no reference from a
connector to its partner on the other sheet, so only the connector's id and its own note tell
the two apart. On the library's asu-1, hda-1 and ammonia-1 P&IDs (26 sheets, 348 connectors),
41 connectors are such open ends, 30 of them on asu-1 P-04 and P-03 beside their valves.

Real sheets put an edge connector 3 to 8 mm inside the border (the library), or set a row of
them in from the edge under their notes: up to 24 mm on the CW and flare header sheets
(ammonia-1 P-111 and P-114, hda-1 P-07 and P-08), 27 and 31 mm on the DEXPI reference P&ID.
The notes band beside the title block lies below the drawing, so the library's bottom-edge
connectors sit just above the title block's top, not at the border.

## Decision

- The drawing lint reports `cheme.offpage-not-on-edge` (warning, one finding per connector,
  id `<sheet>#offpage-not-on-edge:<connector id>`) for an off-page connector on a P&ID whose
  symbol is not on an edge of the drawing area. The drawing area is the inside of the border
  down to the top of the title block. A connector is on an edge within 10 mm of it
  (`EDGE_TOLERANCE`), or within 35 mm (`EDGE_REACH`) when nothing but its own line and texts is
  drawn between it and that edge.
- A connector is an open end, and not checked, when its own text (lower case, punctuation read
  as spaces) contains an open-end word (atm, atmosphere, sky, safe location, breather, hose,
  funnel, sewer, vent, drain: `OPEN_END`) and nowhere names a system it goes into (header,
  flare, oxidiser, thermal, blowdown, recovery, closed, drum, KO, knock-out, scrubber,
  collection, system, station, tank, sump, line, main, network, vessel, B/L, battery limit:
  `DESTINATION`) or a sheet (`P-nn`/`P-nnn` after from, to, on, see, sheet or a comma:
  `SHEET_REF`; a pump tag such as P-101A is no sheet). A destination word anywhere wins:
  "vent to flare", "to vent/flare header", "drain to the closed drain drum" are checked. The
  id counts only for a connector with no text, and then only atm, atmosphere or sky
  (`OPEN_ID`): an id saying vent or drain never overrides a text naming a closed system. The
  message names the criterion.
- The hint gives the `cheme move ID --offset=DX,DY` onto the nearest edge and, when that is not
  the edge the connector's direction calls for, the offset onto the left (incoming) or right
  (outgoing) edge.
- The rule does not check which edge (an incoming connector on the right edge passes): the
  owner allows header rows on the top and bottom edges, and the library has no connector on the
  wrong side edge today.
- BFD and PFD sheets are not checked (no P&ID drawing lint runs on them; generated process
  diagrams draw no off-page connectors).
- The template's `drawing-clean` gate lists the rule; its example generator draws its two
  connectors on the right edge.

## Consequences

- Positive: a connector left mid-sheet fails the basic stage, with the move that fixes it. On
  the library sheets it finds the five connectors still off the edges (asu-1 P-04: the LOX-3001
  inlet and the E-4102/E-4103 CW and CWR stubs) and nothing else.
- Negative: the exemption errs towards reporting: an open end whose note says nothing about
  where it goes, or names a system word ("vent near KO drum"), is reported; the plant accepts
  it in the gate or writes "to atm." on it. A plant repository made with an earlier template keeps its own
  `checks.yaml` and gets the rule in its gate only when it adds it.
- Known limitation: a utility stub drawn at its user by convention (CW/CWR at an exchanger) is
  reported and accepted one by one; a wrong-edge rule can follow if the owner wants one.

## Evidence

- `src/chemeascode/domains/piping/drawing.py` (`offpage_placements`, `_offpage_not_on_edge`),
  `templates/project/checks/checks.yaml`, `templates/project/scripts/example_draft.py`.
- `tests/test_drawing.py`, `tests/test_drawing_gates.py`, `tests/test_scripts.py`.
