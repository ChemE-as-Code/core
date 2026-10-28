# Renamed from plantcode (0.7.0)

Version 0.7.0 renames the package. Before it, package, import name and command were all
`plantcode`; the package now covers chemistry, sizing, cost, LCA, safety and layout as well as
the P&IDs, and is named after the GitHub organisation. Pre-1.0 there are no aliases: the old
names do not work any more, and a plant repository has to be migrated once.

| | before 0.7.0 | from 0.7.0 |
|---|---|---|
| distribution (pip, uv) | `plantcode` | `cheme-as-code` |
| Python import | `import plantcode`, `plantcode.domains...` | `import chemeascode`, `chemeascode.domains...` |
| command | `plantcode validate` | `cheme validate` |
| `python -m` | `python -m plantcode` | `python -m chemeascode` |
| finding / rule ids | `plantcode.layout-clash` | `cheme.layout-clash` |
| schema ids in YAML | `plantcode/process/v1` | `cheme/process/v1` |
| `plant.yaml` | `requires: plantcode>=0.6` | `requires: cheme-as-code>=0.7` |
| generated BFD/PFD marker | `<!-- plantcode-process {...} -->`, note `plantcode_provenance` | `<!-- cheme-process {...} -->`, note `cheme_provenance` |
| generated layout model | `generator: plantcode layout build`, `schema: plantcode/layout_model/v1` | `generator: cheme layout build`, `schema: cheme/layout_model/v1` |
| template sheet | `<Model name="plantcode-template" uri="urn:plantcode:template">` | `<Model name="cheme-template" uri="urn:cheme:template">` |
| environment variables | `PLANTCODE`, `PLANTCODE_UI`, `PLANTCODE_DWSIM_*` | `CHEME`, `CHEME_UI`, `CHEME_DWSIM_*` |
| `cheme serve` token header | `X-Plantcode-Token` | `X-Cheme-Token` (announced by `GET /api/session`) |
| DWSIM image | `plantcode-dwsim:9.0.5` | `cheme-dwsim:9.0.5` |
| agent permission | `Bash(plantcode:*)` | `Bash(cheme:*)` |

Unchanged: the GitHub repositories (`ChemE-as-Code/core`, `viewer`, the plant and template
repositories), the CI secret `PLANTCODE_READ_TOKEN` (set by the owner), the git diff driver
`dexpi`, pyDEXPI and every command, option and endpoint apart from its name.

## What an old repository gets

- `requires: plantcode>=X` in `plant.yaml`: every command stops with `cheme.version-required`,
  naming `requires: cheme-as-code>=0.7`.
- `schema: plantcode/<kind>/v1` in a process, simulation or LCA file: a schema error naming
  `cheme/<kind>/v1`.
- A BFD/PFD with the `plantcode-process` marker: `cheme.generated-edited`, saying it carries
  the old provenance record; `cheme process build --force` regenerates it.
- `layout/plant-model.yaml` with the old schema or generator: `cheme.layout-model-version`;
  `cheme layout build` rebuilds it.
- Generator scripts that `import plantcode...` fail under `cheme run` / `cheme regen` with
  `ModuleNotFoundError`.
- `--ignore`/`--only` and `accept:` entries that name `plantcode.<rule>` match nothing.

## Migrating a plant repository

1. Install the new package and remove the old one:
   `uv tool uninstall plantcode && uv tool install git+https://github.com/ChemE-as-Code/core.git`.
2. `plant.yaml`: `requires: cheme-as-code>=0.7`; comments mentioning `plantcode schema ...`
   become `cheme schema ...`.
3. Schema ids in every YAML file: `plantcode/` -> `cheme/` (`process/materials.yaml`,
   `process/flowsheet.yaml`, `process/simulation.yaml`, `lca/*.yaml`, `estimate/rates.yaml`,
   `estimate/cost-basis.yaml`).
4. Rule ids wherever the repository names them: `plantcode.` -> `cheme.` (`checks/checks.yaml`
   `rules:`/`ignore:` lists, accepted findings, `--ignore` in scripts and CI, review records'
   current findings).
5. Generator scripts: `from plantcode.` -> `from chemeascode.`.
6. Commands in `AGENTS.md`, `README.md`, `.claude/settings.json` (`Bash(cheme:*)`),
   `scripts/agent-run/` (`CHEME` for the command) and `.github/workflows/*.yml`:
   `plantcode <cmd>` -> `cheme <cmd>`. The CI installs the same git URL; keep the secret name
   `PLANTCODE_READ_TOKEN`.
7. Skills: `cheme skills update` (or `--force` for skills not changed locally) installs the
   renamed bundled skills; the manifest knows the earlier versions, so unchanged old copies show
   as outdated, not modified.
8. Rebuild what is generated: `cheme process build --force`, `cheme layout build`, `cheme regen`
   for generated P&IDs, and the `--write` outputs (`cheme assess mto|estimate|lca --write`,
   `cheme layout cables --write`) where the repository keeps them.
9. Hooks and diffs: rerun `cheme git-setup` in every clone (the pre-commit hook and the textconv
   driver call the command by its absolute path, which was the old `plantcode`).
10. `cheme validate` and `cheme check` should give the findings they gave before, under the new
    ids.

A mechanical first pass over YAML and scripts (review the result; the XML stays to be
regenerated):

```sh
grep -rlE 'plantcode' --include='*.yaml' --include='*.yml' --include='*.py' --include='*.md' \
  --include='*.json' --include='*.txt' . | grep -v '^./.git/' | xargs perl -pi -e '
  s/\bplantcode(\s*)>=\s*[\d.]+/cheme-as-code>=0.7/g;
  s/\bplantcode\/([a-z_-]+\/v\d)/cheme\/$1/g;
  s/\b(from|import) plantcode\b/$1 chemeascode/g;
  s/\bplantcode\.(?=[a-z*])/cheme./g;
  s/Bash\(plantcode:\*\)/Bash(cheme:*)/g;
  s/\bplantcode (?=[a-z-]+)/cheme /g'
```

Historical texts (decision records, review records, `PROGRESS.md` entries) describe the past and
keep the old names; add a note where it helps instead of rewriting them.
