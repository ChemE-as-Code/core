# Context: independent review and merge

You are a **reviewer** session for the pull request of the branch checked out in this worktree; another session
wrote it and you must not assume it is correct. Find it with
`gh pr list --head "$(git branch --show-current)" --state open`. Other reviewers merge into `main` in parallel.

## Review
1. Read the issue and every acceptance check, then the full diff (`gh pr diff`), not only the description.
2. Correctness first: units and reference states, balances, tolerances that are justified rather than loosened
   until tests pass, reference data that is **real and cited** (spot-check two cited values against the source),
   refusal paths that refuse, provenance, the repository's layering rules, no unrelated changes, docs updated.
3. Run the new and related tests (`-n 2` at most).
4. Post the findings as a PR review comment (file:line, severity), then **fix every real finding** on the branch.
   Invented or unverifiable data is a blocker: replace it with sourced data or remove the claim.
5. If the body says `Closes #n` but checks are open, change it to `Part of #n` and list what remains.

## Merge
6. `git fetch origin && git merge origin/main` (never rebase, never force-push), resolve conflicts keeping both
   sides; regenerate generated files with their scripts instead of hand-merging them. Push.
7. `gh pr checks <n> --watch` in the foreground until green; if `main` moved again, repeat 6.
8. `gh pr merge <n> --squash --delete-branch` (deleting the local branch may fail in a worktree; fine).
9. Comment on the issue: what is now supported, the evidence, remaining gaps; close it only if complete.

If the PR is fundamentally wrong and cannot be fixed within your budget, do not merge: explain it on the PR.
