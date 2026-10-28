# 0013. AGPL-3.0-or-later licence

- **Status:** Accepted
- **Date:** 2026-10-25

## Context

The viewer is part of cheme-as-code and is built and served with it (`cheme serve --ui`); the
Process Atlas and other tools embed it.

## Decision

The viewer is licensed under AGPL-3.0-or-later (`LICENSE`), like core; `NOTICE` carries the
copyright and TU Delft's disclaimer of copyright interest.

## Consequences

- Reuse and embedding in other products are allowed under the AGPL's terms.
- Copyleft, also over a network: a modified viewer offered to users over a network must offer
  them its source, so improvements made elsewhere flow back.

## Evidence

- Pre-release viewer pre-release viewer commit 76e15e3: the first `LICENSE.md`, "AGPL-3.0-or-later".
- `LICENSE` and `NOTICE` of this folder.
