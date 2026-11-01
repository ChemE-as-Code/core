# 0009. three.js for the 3D layout, loaded on demand, with pure scene logic

- **Status:** Accepted
- **Date:** 2026-10-17

## Context

Core's layout milestone produces a 3D plant model (site, buildings, equipment, pipes, steel,
access). It needs an interactive 3D view in the browser. A 3D engine is a large download that
no other page needs, and WebGL code is hard to unit test.

## Decision

The layout view uses three.js, pinned to an exact version (`three 0.186.0`), loaded with a
dynamic `import()` on `/layout` only. The geometry rules live in plain, unit-tested modules
without three.js: `src/lib/layoutScene.ts` and `src/lib/layoutModel.ts` (core's layout-model
contract to mesh descriptions); `src/lib/layoutThree.ts` only renders them, merging meshes per
layer, material and opacity, with levels of detail per 32 m plan cell and instancing for
repeated details. A "realistic look" (`src/lib/layoutRealism.ts`, GTAO, multisampling) is
built on first use. The scene uses the site frame directly (x east, y north, z up).

## Consequences

- Other pages never download three.js; the scene logic is testable in jsdom.
- A three.js upgrade is a deliberate change (exact pin, `@types/three` to match).
- The view follows core's layout-model contract, so every contract change in core lands here
  too (many "Follow core's ... contract" commits).
- Performance is tested by an e2e frame-rate check (30 fps budget), enforced only locally
  because CI runners render in software.

## Evidence

- "three.js scene ... loaded only on /layout", exact pin.
- Merged meshes; levels of detail, realistic look, frame-rate budget.
- REFERENCE.md (formerly the README), "Design notes".
