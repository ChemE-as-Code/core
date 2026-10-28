You are developing a new case study in the ChemE-as-Code process library: {title}, issue
ChemE-as-Code/process-library#{issue}. Your working directory is the new process folder
`processes/{pid}/` on git branch `case/{pid}` (a git worktree of the library). The orchestrator
created it just before this run with `cheme init` and copied `templates/process/process.yaml`;
nothing is committed yet: your first commit adds the scaffold. Follow this folder's
CLAUDE.md/AGENTS.md and the library rules in `../../CLAUDE.md` (sources and licences: never copy
third-party tables/figures/text, facts with sources, estimates marked ASSUMED).

## Read first
- `gh issue view {issue} --repo ChemE-as-Code/process-library --comments` (scope notes,
  literature, handoffs). Read-only: never comment on, edit or close issues or PRs.
  Held-out benchmark answers are not in the issue; do not search for published "answers" to
  copy, design independently.
- `../methanol-1/` (DESIGN.md, process/, lca/ if present, runs/) and `../asu-1/lca/` as worked
  examples of the conventions. Never modify other process folders.
- Skills: `route-selection`, `flowsheet-development`, `process-design`, `process-simulation`,
  `thermodynamic-model-selection`, `reactions`, `lca`, `lci-estimate`, and the matching `tech-*`
  skill{skill_hint}.
{case_notes}
## Scope of this run: design basis -> balanced BFD/PFD -> preliminary gate-to-gate LCI
1. Route/boundary memo, design basis (`process/design-basis.yaml`), `process.yaml`
   (`publication.status: internal`, honest maturity/validation, references).
2. BFD and PFD in `process/flowsheet.yaml` with the main units, recycles/purges and a stream
   table; `cheme process build`; mass/element balances closed with cheme (energy where core
   supports it; otherwise state the gated step precisely, e.g. pre-release issue 315).
3. Reaction/model evidence in DESIGN.md (sourced conversion/equilibrium models are acceptable,
   labelled as such; no invented kinetics or vendor data).
4. **Preliminary gate-to-gate LCI** in `lca/` (skills `lca`, `lci-estimate`; follow asu-1's
   files): functional unit 1 kg of main product at the gate, every foreground exchange from the
   balanced flowsheet: raw materials, utilities (electricity, steam by level, cooling water,
   fuel), co-products, emissions to air/water and wastes, each with amount per functional unit,
   unit and provenance (flowsheet stream id or ASSUMED with reason). Leave background datasets
   **unmapped** (gaps, never 0 and never values from licensed databases); give for each a short
   description of the background activity it should connect to later. Write the inventory
   (`cheme assess lca --inventory --write` and `--coverage`) and check its mass balance against
   the flowsheet.
5. DESIGN.md, PROGRESS.md and the equipment/line lists as far as the PFD requires.

Out of scope: P&IDs (leave the template's DEXPI reference sheet alone or remove it), layout,
HAZOP, TEA, datasheets. Do not edit anything outside `processes/{pid}/` (shared files such as
`chemicals/chemicals.yaml` are changed later in one consolidated PR: list what is missing there).

## Working rules
- Run `cheme status`, `cheme check`, `cheme maturity`, `cheme process streams` and fix what you
  can. Never sign off a stage (`--write` on check).
- Commit in sensible steps (`git add .` from this folder). Do not push, do not switch branches.
- Destructive shell commands are refused; work around them.
- Budget is fixed: a complete, honest, balanced PFD plus the LCI beat polish. Commit everything
  before you finish (uncommitted work is lost to the record).

## Final answer
Short report: files produced, balance/check/LCI results (with numbers), sources used, ASSUMED
key values, missing registry entries, open inputs and gated steps, recommended next stage.
