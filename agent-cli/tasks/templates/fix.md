You are revising the process-library case study {title} (`processes/{pid}/`, branch
`case/{pid}`, issue #{issue}) after an independent review. Read the newest record in
`reviews/` and close every **critical and high** finding (medium/low only where quick).
{extra}
Follow this folder's AGENTS.md and the library rules in `../../CLAUDE.md`. Do not edit anything
outside `processes/{pid}/`; never edit an existing review record or run record. For each
finding you close, append a short "Response" entry to PROGRESS.md (finding id, what changed,
commit). Re-run `cheme check`, `cheme maturity`, `cheme process streams` and
`cheme assess lca --coverage` afterwards. Commit everything; do not push.
End with a short report: findings closed (ids), findings left open and why.
