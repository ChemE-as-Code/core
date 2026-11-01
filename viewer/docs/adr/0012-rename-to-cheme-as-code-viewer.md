# 0012. Rename from plantcode-viewer to cheme-as-code-viewer

- **Status:** Accepted
- **Date:** 2026-10-22

## Context

The project started as plantcode (`plantcode-viewer`, command `plantcode`) and was renamed
with core 0.7.0 to ChemE-as-Code, command `cheme`. The viewer shows command names, finding
ids and schema ids, and reads an environment variable for the API address.

## Decision

Follow core's rename (core: `docs/framework/rename.md`): package `cheme-as-code-viewer`;
the command `cheme` in UI hints, titles and docs; finding ids `cheme.<rule>` (views strip the
prefix); schema ids `cheme/<kind>/v1`; `CHEME_API` / `VITE_CHEME_API` for the API base (was
`PLANTCODE_API`); header `X-Cheme-Token`. The repository is ChemE-as-Code/viewer.

## Consequences

- One name across core, viewer, library and website.
- Old environment variables and ids no longer work; the README names the old
  `PLANTCODE_API` to help people migrating.
- Some historical names remain in git history and in fixture provenance (e.g. local checkout
  paths such as `plantcode-demo`).

## Evidence

- "Rename plantcode to cheme-as-code: command cheme, ids
  cheme.<rule>".
- The first README, titled `plantcode-viewer`; README intro.
