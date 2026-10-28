# Your first plant

A plant is a git repository. `cheme init` writes the folders, the schemas' starting files, the
agent skills and a CI workflow from the [project template](project-template.md):

```sh
cheme init my-plant --name "Ethanol plant"   # folders, starting files, agent skills, CI
cd my-plant
git init
cheme git-setup                               # P&IDs as review text in git diffs, pre-commit hook
cheme status                                  # sheets, findings, gates, sign-offs
```

`cheme init [DIRECTORY] [--name NAME] [--force]` never overwrites an existing file without
`--force`. `cheme git-setup [--no-hook]` registers the P&ID diff driver and installs the
pre-commit hook that validates before each commit.

## Draw, check, render

```sh
cheme sheet new P-01 --title "Feed and reaction"   # a sheet with a real title block
cheme validate                                       # P&IDs and lists, lists against P&IDs
cheme fmt                                            # canonical XML, a readable id on every object
cheme render                                         # build/P-01.svg
cheme diff main                                      # build/diff.html, changes highlighted
```

Every finding is one line with `file:line`, level, rule and subject, so a person or an agent can
act on it. See [P&IDs and DEXPI](../guides/pids.md) for the rules.

## Process, layout and assessment

```sh
cheme process build      # BFD and PFD from process/materials.yaml and process/flowsheet.yaml
cheme process streams    # stream table with provenance, block balances
cheme layout build       # layout/plant-model.yaml from layout/*.yaml, the lists and the P&IDs
cheme assess mto         # material take-off of the 3D model
cheme check              # the engineering-step gates of checks/checks.yaml
```

Each step has a guide: [process BFD/PFD](../guides/process.md), [3D layout](../guides/layout.md),
[MTO and estimate](../guides/mto-estimate.md), [stages and gates](../concepts/stages-and-gates.md).

## Working with an agent

The template installs Claude Code skills in `.claude/skills/` and an allowlist in
`.claude/settings.json`. Claude Code applies that allowlist only once the folder is trusted:
open it interactively once and accept the trust dialog, or run headless with
`--settings .claude/settings.json`. See [Agents and skills](../guides/agents.md).
