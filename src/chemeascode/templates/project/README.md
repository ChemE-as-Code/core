# {{plant_name}}

A plant design kept as plain files in git: DEXPI 2.0.1 P&IDs in `pid/`, engineering lists as
YAML, decisions and progress as Markdown. Edited by people and by coding agents (Claude Code),
checked by [`cheme-as-code`](https://github.com/ChemE-as-Code/core).

| path | what |
|---|---|
| `plant.yaml` | name, stage, sheets |
| `pid/` | P&ID sheets (DEXPI 2.0.1 XML) |
| `process/design-basis.yaml` | capacity, feeds, products, utilities, site |
| `process/materials.yaml`, `process/flowsheet.yaml` | components, blocks, steps and streams: the source of the generated BFD and PFD (`process/*.xml`, `cheme process build`) |
| `equipment/equipment-list.yaml`, `piping/line-list.yaml`, `control/instrument-list.yaml` | lists, consistent with the P&IDs |
| `control/cause-effect.yaml` | interlocks and trips (cause and effect) |
| `piping/special-items.yaml` (optional) | tagged piping components: safety valves, silencers, rupture discs (skill `lists-sync`) |
| `safety/` | HAZOP studies (`safety/hazop/<id>/study.yaml`) and the risk matrix they rate against; `safety/README.md` says how |
| `checks/checks.yaml` | engineering-step gates; `checks/status.json` their result at the last stage sign-off |
| `reviews/` | review records |
| `runs/` | one record per design session, written by `cheme runs record` (`runs/README.md`); never edited |
| `DESIGN.md`, `PROGRESS.md`, `STAGES.md` | decisions, change log, stage definitions |
| `scripts/` | generator scripts: the source of generated sheets (`generator:` in `plant.yaml`), provenance for the others |
| `.claude/skills/` | how an agent works here |

## How this repository works

- **This repository holds your plant**: drawings, lists, decisions. It does not hold the tools.
- **The tools come from [`cheme-as-code`](https://github.com/ChemE-as-Code/core)**, installed once on
  your computer (`uv tool install git+https://github.com/ChemE-as-Code/core.git`). Every check,
  drawing and generated file is made by the `cheme` command, so you need it to work here. The CI
  in `.github/workflows/` installs it too.
- **Licences.** The ChemE-as-Code tools are licensed under AGPL-3.0-or-later; the content of this
  repository (your plant data and models) is yours and can be licensed however you choose.
- **The skills in `.claude/skills/` are copies** of the ones in cheme-as-code, so that Claude Code
  finds them here. After upgrading (`uv tool upgrade cheme-as-code`), run `cheme skills update` to
  refresh them; `cheme skills status` shows which are out of date. A skill you changed here is
  kept.
- **While cheme-as-code is private**, you need read access to it, and the CI needs the secrets
  named in `.github/workflows/validate.yml`.

## Working here

```sh
uv tool install cheme-as-code           # once (see the cheme-as-code README while it is private)
cheme git-setup                 # once per clone: readable P&ID diffs + pre-commit hook
cheme status                    # where the plant stands: sheets, findings, gates, sign-offs
cheme validate                  # after every change
cheme fmt                       # canonical XML, stable ids
cheme render [--png] [--crop]   # build/<sheet>[_crop-X0-Y0-X1-Y1].svg (or .png)
cheme render --png --tiles auto # build/<sheet>_tile-A1.png ... to read the whole sheet
cheme show <id or tag>          # where an object and its drawing are in the file
cheme diff main [--list]        # build/diff.html, or one line per changed plant item
cheme check                     # engineering-step gates (--write only at sign-off)
cheme runs list                 # the record of each design session in runs/
cheme process build             # BFD and PFD from process/*.yaml
cheme process streams           # stream table with provenance, block balances
```
