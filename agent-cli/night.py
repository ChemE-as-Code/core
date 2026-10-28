"""Overnight orchestrator: process-library case studies, design -> PR -> independent review -> fix -> CI -> merge.

    uv run night.py [--cases cases.json] [--total 100] [--lanes 3]

Each case gets its own worktree and branch (case/<pid>); every agent session goes through
agent.py (spending cap, guards, run record committed in processes/<pid>/runs/). This script
does the outward steps itself (push, PR, merge), never the agents. The ledger counts every
runs.jsonl entry since --since (default: the start) plus the caps of sessions still running.

The cases are a JSON list (see jobs/examples/cases.json); the process-library checkout and the
worktree folder default to siblings of this repository (CHEME_LIBRARY, CHEME_WORKTREES).
"""

import argparse
import json
import os
import shutil
import subprocess
import sys
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from datetime import date, datetime, timezone
from pathlib import Path

import procs

HERE = Path(__file__).resolve().parent
WORKSPACE = HERE.parent.parent  # the folder holding this repository and process-library
LIB = Path(os.environ.get("CHEME_LIBRARY") or WORKSPACE / "process-library")
WT = Path(os.environ.get("CHEME_WORKTREES") or WORKSPACE / "wt")
LEDGER_SINCE = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M")  # --since; default: this start
CAPS = {"design": 14.0, "review": 3.0, "fix": 5.0, "ci-fix": 3.0}
MIN = {"design": 8.0, "review": 1.5, "fix": 2.0, "ci-fix": 1.5}

lock = threading.Lock()
reserved = {}
_log_file = None  # opened on first use, so `import night` creates no log file


def log(msg):
    global _log_file
    line = f"{datetime.now():%H:%M:%S} {msg}"
    with lock:
        if _log_file is None:
            (HERE / "logs").mkdir(exist_ok=True)
            _log_file = (HERE / "logs" / f"night-{datetime.now():%Y%m%d-%H%M}.log").open("a", encoding="utf-8")
        print(line, flush=True)
        _log_file.write(line + "\n")
        _log_file.flush()


def spent():
    total = 0.0
    if (HERE / "runs.jsonl").exists():
        for line in (HERE / "runs.jsonl").read_text(encoding="utf-8").splitlines():
            r = json.loads(line)
            if r.get("finished", "") < LEDGER_SINCE:
                continue
            # a crashed run without a cost estimate counts with its full cap, never as free
            total += r["cost_usd"] if r.get("cost_usd") is not None else (r.get("budget_usd") or 0.0)
    return total


def sh(cmd, cwd=None, check=True, timeout=None):
    r = subprocess.run(cmd, cwd=cwd, capture_output=True, text=True, timeout=timeout)
    if check and r.returncode:
        raise RuntimeError(f"{' '.join(map(str, cmd))}: {r.stderr.strip()[:500]}")
    return r


running_agents = procs.running_agents  # {cwd: budget} of every agent.py session on this machine


def report_of(cwd, slug):
    runs = sorted((cwd / "runs").glob(f"*-{slug}")) if (cwd / "runs").exists() else []
    return (runs[-1] / "report.md").read_text(encoding="utf-8") if runs and (runs[-1] / "report.md").exists() else None


def agent(case, stage, prompt, total):
    """One agent session; returns its report, or None when the budget does not allow it.

    Resumable: a stage with a record already is not run again; a session of this case still
    running (from an earlier orchestrator) is waited for.
    """
    cwd = WT / case["pid"] / "processes" / case["pid"]
    slug = stage.replace("#", "")
    while str(cwd) in running_agents():
        time.sleep(30)
    if (done := report_of(cwd, slug)) is not None:
        log(f"{case['pid']}: {stage} already recorded, reusing its report")
        return done
    key = f"{case['pid']}:{stage}"
    with lock:
        others = {c: b for c, b in running_agents().items() if c not in {k.split("|")[0] for k in reserved}}
        left = total - spent() - sum(reserved.values()) - sum(others.values())
        cap = min(CAPS[stage.split("#")[0]], left)
        if cap < MIN[stage.split("#")[0]]:
            return None
        reserved[f"{cwd}|{key}"] = cap
        key = f"{cwd}|{key}"
    task = HERE / "tasks" / "gen" / f"{case['pid']}-{stage.replace('#', '')}.md"
    task.parent.mkdir(parents=True, exist_ok=True)
    task.write_text(prompt, encoding="utf-8")
    log(f"{case['pid']}: {stage} started, cap ${cap:.2f}")
    t0 = time.time()
    out = HERE / "logs" / f"night-{case['pid']}-{stage.replace('#', '')}.out"
    with out.open("w", encoding="utf-8") as f:
        # run.sh loads the key from ~/.zshrc on macOS; on Windows the key comes from the environment
        runner = [sys.executable, str(HERE / "agent.py")] if os.name == "nt" else [str(HERE / "run.sh")]
        subprocess.run([*runner, "--task-file", str(task), "--cwd", str(cwd), "--budget", f"{cap:.2f}",
                        "--unattended", "--slug", stage.replace("#", "")], stdout=f, stderr=subprocess.STDOUT)
    with lock:
        reserved.pop(key, None)
    report = report_of(cwd, slug) or out.read_text(encoding="utf-8")[-4000:]
    tail = out.read_text(encoding="utf-8").strip().splitlines()[-1] if out.exists() else ""
    log(f"{case['pid']}: {stage} done ({(time.time() - t0) / 60:.0f} min) {tail}")
    return report


def fill(template, case, **extra):
    return (HERE / "tasks" / "templates" / template).read_text(encoding="utf-8").format(
        title=case["title"], pid=case["pid"], issue=case["issue"], date=date.today().isoformat(),
        skill_hint=f" (`{case['skill']}`)" if case.get("skill") else "",
        case_notes=f"\n## Case notes\n{case['notes']}\n" if case.get("notes") else "", **extra)


def push(case):
    sh(["git", "push", "-q", "-u", "origin", f"case/{case['pid']}"], cwd=WT / case["pid"])


def ci(case, pr):
    """Wait for the PR's checks: 'pass', 'fail' or 'none'."""
    time.sleep(30)
    try:
        r = sh(["gh", "pr", "checks", str(pr), "--watch", "--interval", "30"], cwd=LIB, check=False, timeout=3600)
    except subprocess.TimeoutExpired:  # CI still running after an hour: report it as failed, keep the case alive
        log(f"{case['pid']}: CI of PR {pr} still running after 60 min")
        return "fail"
    if "no checks reported" in (r.stdout + r.stderr):
        return "none"
    return "pass" if r.returncode == 0 else "fail"


def run_case(case, total):
    pid = case["pid"]
    try:
        wt = WT / pid
        if not wt.exists():
            sh(["git", "fetch", "-q", "origin"], cwd=LIB)
            sh(["git", "worktree", "add", "-q", "-b", f"case/{pid}", str(wt), "origin/main"], cwd=LIB)
            folder = wt / "processes" / pid
            folder.mkdir(parents=True)
            shutil.copy(wt / "templates" / "process" / "process.yaml", folder)
            sh(["cheme", "init", str(folder), "--name", case["title"]])
            shutil.rmtree(folder / ".github", ignore_errors=True)
        if agent(case, "design", fill("design.md", case), total) is None:
            log(f"{pid}: skipped, budget exhausted")
            return
        push(case)
        existing = json.loads(sh(["gh", "pr", "list", "--head", f"case/{pid}", "--state", "all", "--json", "number,state"],
                                 cwd=LIB).stdout)
        if existing and existing[0]["state"] == "MERGED":
            log(f"{pid}: already merged")
            return
        if existing:
            pr = str(existing[0]["number"])
        else:
            report = report_of(wt / "processes" / pid, "design")
            body = HERE / "tasks" / "gen" / f"{pid}-pr.md"
            body.write_text(
                f"New process folder `processes/{pid}/` for #{case['issue']}: design basis, balanced BFD/PFD and a "
                f"preliminary gate-to-gate LCI with unmapped background, produced by an agent run "
                f"(record in `processes/{pid}/runs/`). An independent agent review follows on this PR.\n\n"
                f"## Agent report\n\n{report or '(no report)'}\n\n"
                f"🤖 Generated with [Claude Code](https://claude.com/claude-code)\n", encoding="utf-8")
            pr_url = sh(["gh", "pr", "create", "--base", "main", "--head", f"case/{pid}",
                         "--title", f"{pid}: {case['title']}, design basis to balanced PFD and preliminary LCI (#{case['issue']})",
                         "--body-file", str(body)], cwd=LIB).stdout.strip()
            pr = pr_url.rsplit("/", 1)[-1]
            log(f"{pid}: PR {pr_url}")

        review = agent(case, "review", fill("review.md", case), total)
        if review is None:
            log(f"{pid}: review skipped, budget exhausted; PR left open")
            return
        push(case)
        verdict = "fix" if "VERDICT: fix" in review else "merge" if "VERDICT: merge" in review else "unknown"
        sh(["gh", "pr", "comment", pr, "--body", f"Independent agent review ({verdict}): see `processes/{pid}/reviews/` "
            f"and the review run in `processes/{pid}/runs/`.\n\n{review[-3000:]}"], cwd=LIB, check=False)
        if verdict != "merge":
            if agent(case, "fix", fill("fix.md", case, extra=""), total) is None:
                log(f"{pid}: fix skipped, budget exhausted; PR left open")
                return
            push(case)

        state = ci(case, pr)
        if state == "fail":
            extra = (f"\nFirst, the pull request's CI failed: run `gh pr checks {pr}` and "
                     f"`gh run view <run id> --log-failed` (read-only) and fix the causes inside this folder.\n")
            if agent(case, "ci-fix", fill("fix.md", case, extra=extra), total) is None:
                log(f"{pid}: CI failed, no budget to fix; PR left open")
                return
            push(case)
            state = ci(case, pr)
        if state == "fail":
            sh(["gh", "pr", "comment", pr, "--body", "CI still fails after one fix run; left open for a human."], cwd=LIB, check=False)
            log(f"{pid}: CI still failing, PR {pr} left open")
            return
        sh(["gh", "pr", "merge", pr, "--merge"], cwd=LIB)
        log(f"{pid}: merged PR {pr} (CI {state})")
    except Exception as e:  # one case failing must not stop the night
        log(f"{pid}: ERROR {e}")


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--cases", default=str(HERE / "cases.json"),
                   help="JSON list of cases: pid, title, issue, skill, notes (default: cases.json, not in git).")
    p.add_argument("--total", type=float, default=100.0)
    p.add_argument("--lanes", type=int, default=3)
    p.add_argument("--only", nargs="*")
    p.add_argument("--since", help="Ledger start (UTC, YYYY-MM-DDTHH:MM): count runs.jsonl from here; default: now.")
    a = p.parse_args()
    all_cases = json.loads(Path(a.cases).read_text(encoding="utf-8"))
    cases = [c for c in all_cases if not a.only or c["pid"] in a.only]
    global LEDGER_SINCE
    LEDGER_SINCE = a.since or LEDGER_SINCE
    log(f"start: {len(cases)} cases, {a.lanes} lanes, ${a.total} total, ${spent():.2f} already spent")
    with ThreadPoolExecutor(a.lanes) as pool:
        for c in cases:
            pool.submit(run_case, c, a.total)
            time.sleep(20)  # stagger git worktree/cheme init
    log(f"end: ${spent():.2f} spent")


if __name__ == "__main__":
    main()
