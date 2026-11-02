# 0004. Pin pyDEXPI as a git dependency by commit

- **Status:** Accepted; amended 2026-11-02 (pyDEXPI 2.1.0 is public, pinned exactly from PyPI)
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
- Done: depend on the public pyDEXPI (#111); see the amendment.

## Amendment (2026-11-02)

pyDEXPI 2.1.0 is released in the public repository and on PyPI. The pinned `pyDEXPI-dev` commit
`be793a0` was the same version, 2.1.0. `pyproject.toml` now pins `pydexpi==2.1.0` from PyPI,
and `[tool.uv.sources]` is gone. The rule stays: one exact version, bumped deliberately, with the
examples rebuilt. CI and the plant template no longer need the `DEPLOY_KEY_PYDEXPI` secret.

## Evidence

- "Pin pyDEXPI to the re-initialised pyDEXPI-dev"; earlier, CI access through deploy keys
  (2026-10-17) and a fine-grained token.
- `pyproject.toml` (`[tool.uv.sources]`, from the amendment on the `pydexpi` dependency),
  `.github/workflows/ci.yml`.
- https://pypi.org/project/pydexpi/2.1.0/ and the `v2.1.0` tag of
  https://github.com/process-intelligence-research/pyDEXPI (2026-11-01).
