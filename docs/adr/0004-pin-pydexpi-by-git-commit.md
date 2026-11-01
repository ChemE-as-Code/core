# 0004. Pin pyDEXPI as a git dependency by commit

- **Status:** Accepted (a follow-up move to the public pyDEXPI repository is open)
- **Date:** 2026-10-22

## Context

cheme-as-code needs pyDEXPI 2.x (DEXPI 2.0.1 support, `id_diff`, SVG export). That version is
not on PyPI. It is developed in the private repository `pyDEXPI-dev`, which was re-initialised
in October 2026. Its behaviour (serializer output, ids) directly defines `cheme fmt`'s canonical
form and the generated-sheet fingerprints, so an unannounced upstream change would mark every
generated sheet as edited or outdated.

## Decision

`pyproject.toml` declares `pydexpi` as a base dependency and pins it in `[tool.uv.sources]` to a
fixed commit of `process-intelligence-research/pyDEXPI-dev` ("pinned by commit. Bump
deliberately."). CI reads it with a deploy key / token. A bump is its own change, with the
examples rebuilt.

## Consequences

- Positive: reproducible installs and stable canonical XML; upstream changes arrive only on a
  deliberate bump.
- Negative: installation needs access to a private repository, so cheme-as-code cannot be
  installed by the public until it depends on a public pyDEXPI.
- Negative: fixes upstream are not picked up automatically.
- Open: depend on the public pyDEXPI repository (#29).

## Evidence

- "Pin pyDEXPI to the re-initialised pyDEXPI-dev"; earlier, CI access through deploy keys
  (2026-10-17) and a fine-grained token.
- `pyproject.toml` (`[tool.uv.sources]`), `.github/workflows/ci.yml`.
