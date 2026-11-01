# Repository baseline

The first commit of this repository is a baseline: three formerly separate, private repositories
assembled into one, with no earlier history. Later changes are ordinary commits on top of it; the
baseline itself is never rewritten.

## Sources

| folder | from (earlier repository, kept private) | commit |
|---|---|---|
| `/` (the `cheme-as-code` package, docs, examples) | core | `ed538265ee4a950d32d757190eb1c8556708eb10` |
| `viewer/` | viewer | `c1d7663eff89ddc6d7b8f3efc734e153fe87d4c1` |
| `agent-cli/` | agent-cli | `0f052d49fb6973ca78baf9d59fda3abee9de8ddc` |

The baseline commit names the same three commits in its `Source-core`, `Source-viewer` and
`Source-agent-cli` trailers. Their full histories, issues and pull requests stay in the private
archives of those repositories.

Left out of the baseline: the agent runner's generated prompts (`tasks/gen/`), its job prompts
for specific issues, its case list and one-off scripts for specific nights, and everything the
runner writes at run time (logs, `runs.jsonl`, transcripts). They are project-specific and stay
outside this repository; `agent-cli/jobs/examples/` and `agent-cli/tasks/templates/` are the
reusable parts.

## Run records

Run records written before the baseline (`runs/<run-id>/run.yaml` in plant repositories) are
unchanged: their `core_commit` and runner commit name commits of the earlier core and
agent-cli repositories.
Records written from the baseline on name commits of this repository. The toolkit and the runner
are recorded independently, each from the source that was installed or run; `same_revision:
true` means both were the same clean commit of this repository ([run records](../agent-design-run.md)).
