# 0010. Accessibility and keyboard model

- **Status:** Accepted
- **Date:** 2026-10-25

## Context

Engineering review happens with the keyboard and, for some reviewers, with a screen reader. A
P&ID is a picture: objects can be clicked but not tabbed to. Single-page navigation does not
move focus or update the tab title by itself, and an async view could show the previous
revision's data under the new revision's label.

## Decision

- Every page sets the browser tab title (`<page> - <plant> - cheme-as-code viewer`); after
  navigation the focus moves to the page heading; the first `Tab` reaches a "Skip to content"
  link.
- Drawings have a keyboard picking model: `N`/`P` (or `Shift+N`) step through objects
  (centred, marked and announced to screen readers), `Enter`/`Space` show details,
  `Escape` clears; `+` `-` `0` and arrow keys pan and zoom. Table rows are selectable
  with `Enter`/`Space`.
- While another revision or case loads, a page shows its loading state, never the previous
  data (`useAsync` clears data when its source changes).
- In-page links scroll and focus without changing the route, so they also work in hash URLs.

## Consequences

- Keyboard and screen-reader users can review drawings and tables.
- New views must follow the same model; `e2e/keyboard.spec.ts` checks it.
- Clearing data on source change makes pages flash a loading state where they used to keep
  stale numbers; a plain reload keeps data to avoid flashing.

## Evidence

- "Fresh data on revision change, heading anchors, keyboard
  access and page titles".
- REFERENCE.md (formerly the README), "Pages" and the paragraph on page titles and focus.
