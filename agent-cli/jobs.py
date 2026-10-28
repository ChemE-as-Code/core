"""Run a file of agent jobs in parallel, supervised. Works on macOS, Linux and Windows.

    uv run jobs.py jobs/night.json --total 150 [--max-sessions 8] [--min-free-gb 8] [--dry-run]

Every job is one agent.py session (spending cap, guards, run record). The supervisor
- starts a queued job only while at least --min-free-gb RAM is free, fewer than --max-sessions
  run, and the batch's spend (runs.jsonl, crashed runs included) plus the caps of running jobs
  stays within --total;
- restarts a job whose session crashed or stopped without a final line, up to max_restarts, with a
  note about the partial work in its working directory;
- starts a job's `then` job (e.g. an independent review) when it ends with STATUS: DONE or a VERDICT;
- kills pytest runs older than an hour under the job folders (left behind by ended sessions), and
  the largest one when free RAM drops below --emergency-gb;
- keeps its state in logs/jobs/<file>.state.json: run the same command again to resume.

Job file (JSON; relative paths are relative to the job file):

    {"preamble_file": "preamble.md",
     "defaults": {"budget": 8, "approve": "auto", "effort": "high", "max_restarts": 3},
     "jobs": [
       {"name": "core-364", "cwd": "../../wt/core-364", "budget": 15, "task_file": "core-364.md",
        "then": {"name": "review-364", "budget": 8, "preamble_file": "review.md",
                 "task": "Review and merge the PR of this branch."}}]}
"""

import argparse
import json
import os
import subprocess
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

import procs

HERE = Path(__file__).resolve().parent
TERMINAL = {"done", "blocked", "failed", "budget", "skipped"}
CRASH_NOTE = (
    "NOTE: an earlier session on this task ended before finishing ({why}). Its partial work may be in this "
    "working directory (uncommitted files, commits, a pushed branch or an open PR): inspect git status, "
    "git log origin/main..HEAD and `gh pr list --head $(git branch --show-current)` first, reuse what is "
    "sound, and continue to the full deliverable.\n\n"
)


def now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


class Batch:
    def __init__(self, job_file: Path, args):
        self.file, self.args = job_file.resolve(), args
        self.dir = HERE / "logs" / "jobs"
        self.dir.mkdir(parents=True, exist_ok=True)
        self.state_file = self.dir / f"{self.file.stem}.state.json"
        self.jobs = self._load()
        self.state = self._load_state()
        self.popen: dict[str, subprocess.Popen] = {}
        self.log_file = (self.dir / f"{self.file.stem}.log").open("a", encoding="utf-8")

    # ---- loading -------------------------------------------------------------------------------
    def _load(self) -> dict[str, dict]:
        raw = json.loads(self.file.read_text(encoding="utf-8"))
        defaults = {"budget": 8.0, "approve": "auto", "effort": "high", "model": "claude-opus-5-5",
                    "max_restarts": 3, **raw.get("defaults", {})}
        jobs: dict[str, dict] = {}

        def add(spec: dict, parent: str | None, preamble_file: str | None):
            job = {**defaults, **{k: v for k, v in spec.items() if k != "then"}}
            if job["name"] in jobs:
                sys.exit(f"duplicate job name {job['name']}")
            job["cwd"] = str((self.file.parent / spec.get("cwd", parent and jobs[parent]["cwd"] or ".")).resolve())
            pre = spec.get("preamble_file", preamble_file)
            text = (self.file.parent / pre).read_text(encoding="utf-8") + "\n\n" if pre else ""
            if spec.get("task_file"):
                text += (self.file.parent / spec["task_file"]).read_text(encoding="utf-8")
            else:
                text += spec["task"]
            job.update(task=text, after=parent, budget=float(job["budget"]))
            if not Path(job["cwd"]).is_dir():
                sys.exit(f"{job['name']}: working directory does not exist: {job['cwd']}")
            jobs[job["name"]] = job
            if spec.get("then"):
                add(spec["then"], job["name"], spec["then"].get("preamble_file", preamble_file))

        for spec in raw["jobs"]:
            add(spec, None, raw.get("preamble_file"))
        return jobs

    def _load_state(self) -> dict:
        if self.state_file.exists():
            st = json.loads(self.state_file.read_text(encoding="utf-8"))
        else:
            st = {"batch": f"{self.file.stem}-{datetime.now():%Y%m%d-%H%M%S}", "started": now(), "jobs": {}}
        for name, job in self.jobs.items():
            st["jobs"].setdefault(name, {"status": "waiting" if job["after"] else "queued", "attempts": 0})
        return st

    def save(self):
        self.state_file.write_text(json.dumps(self.state, indent=1), encoding="utf-8")

    def log(self, msg: str):
        line = f"{datetime.now():%H:%M:%S} {msg}"
        print(line, flush=True)
        self.log_file.write(line + "\n")
        self.log_file.flush()

    # ---- ledger ------------------------------------------------------------------------------------
    def records(self, name: str | None = None, since: str = "") -> list[dict]:
        out = []
        if (HERE / "runs.jsonl").exists():
            for line in (HERE / "runs.jsonl").read_text(encoding="utf-8").splitlines():
                try:
                    r = json.loads(line)
                except ValueError:
                    continue
                if r.get("batch") == self.state["batch"] and (name is None or r.get("job") == name) \
                        and r.get("finished", "") >= since:
                    out.append(r)
        return out

    def spent(self) -> float:
        # a run without a cost (crashed, no transcript) counts with its cap, never as free
        return sum(r["cost_usd"] if r.get("cost_usd") is not None else (r.get("budget_usd") or 0.0)
                   for r in self.records())

    def running(self) -> list[str]:
        return [n for n, s in self.state["jobs"].items() if s["status"] == "running"]

    # ---- lifecycle ---------------------------------------------------------------------------------
    def start(self, name: str, why: str | None):
        job, st = self.jobs[name], self.state["jobs"][name]
        st["attempts"] += 1
        task = (CRASH_NOTE.format(why=why) if why else "") + job["task"]
        task_file = self.dir / f"{name}-{st['attempts']}.md"
        task_file.write_text(task, encoding="utf-8")
        out = (self.dir / f"{name}-{st['attempts']}.out").open("w", encoding="utf-8")
        env = {**os.environ, "AGENT_CLI_JOB": name, "AGENT_CLI_BATCH": self.state["batch"], "PYTHONIOENCODING": "utf-8"}
        detach = ({"creationflags": subprocess.CREATE_NEW_PROCESS_GROUP} if os.name == "nt"
                  else {"start_new_session": True})  # sessions survive a restart of this supervisor
        p = subprocess.Popen(
            [sys.executable, str(HERE / "agent.py"), "--task-file", str(task_file), "--cwd", job["cwd"],
             "--budget", f"{job['budget']:.2f}", "--approve", job["approve"], "--effort", job["effort"],
             "--model", job["model"], "--slug", name],
            cwd=HERE, env=env, stdin=subprocess.DEVNULL, stdout=out, stderr=subprocess.STDOUT, **detach)
        self.popen[name] = p
        st.update(status="running", pid=p.pid, run_started=now())
        self.log(f"{name}: started (attempt {st['attempts']}, cap ${job['budget']:.2f}, free {procs.free_gb():.1f} GB)")

    def alive(self, name: str) -> bool:
        if name in self.popen:
            return self.popen[name].poll() is None
        pid = self.state["jobs"][name].get("pid")  # started by an earlier run of this supervisor
        return bool(pid) and procs.psutil.pid_exists(pid)

    def finish(self, name: str):
        job, st = self.jobs[name], self.state["jobs"][name]
        self.popen.pop(name, None)
        recs = self.records(name, since=st.get("run_started", ""))
        r = recs[-1] if recs else None
        final, subtype = (r or {}).get("final_status"), (r or {}).get("subtype", "no-record")
        cost = (r or {}).get("cost_usd")
        st["last"] = {"subtype": subtype, "final_status": final, "cost_usd": cost}
        if final in ("DONE", "VERDICT-merge", "VERDICT-fix"):
            st["status"] = "done"
            for child, cj in self.jobs.items():
                if cj["after"] == name and self.state["jobs"][child]["status"] == "waiting":
                    self.state["jobs"][child]["status"] = "queued"
                    self.log(f"{child}: queued after {name}")
        elif final == "BLOCKED":
            st["status"] = "blocked"
        elif subtype == "error_max_budget_usd":
            st["status"] = "budget"
        elif st["attempts"] <= job["max_restarts"]:
            st["status"] = "queued"
            st["why"] = "the session crashed" if subtype in ("crashed", "no-result", "no-record") \
                else "it stopped without a final STATUS line"
        else:
            st["status"] = "failed"
        if st["status"] in TERMINAL:  # a parent that will never finish releases nothing
            self._skip_children(name)
        self.log(f"{name}: {st['status']} ({subtype}, final {final}, ${cost if cost is not None else '?'})")

    def _skip_children(self, name: str):
        if self.state["jobs"][name]["status"] == "done":
            return
        for child, cj in self.jobs.items():
            if cj["after"] == name and self.state["jobs"][child]["status"] == "waiting":
                self.state["jobs"][child]["status"] = "skipped"
                self._skip_children(child)

    def tick(self) -> bool:
        a = self.args
        for name in self.running():
            if not self.alive(name):
                self.finish(name)
        roots = [Path(j["cwd"]) for j in self.jobs.values()]
        for k in procs.sweep_stale_pytest(roots, a.stale_pytest_min * 60):
            self.log(f"killed stale {k}")
        free = procs.free_gb()
        if free < a.emergency_gb and (k := procs.emergency_relief(roots)):
            self.log(f"EMERGENCY: {free:.1f} GB free, killed {k}")
        queued = [n for n, s in self.state["jobs"].items() if s["status"] == "queued"]
        reserved = sum(self.jobs[n]["budget"] for n in self.running())
        spent = self.spent()
        for name in queued:
            if len(self.running()) >= a.max_sessions or procs.free_gb() < a.min_free_gb:
                break
            if spent + reserved + self.jobs[name]["budget"] > a.total:
                continue  # a cheaper job may still fit
            self.start(name, self.state["jobs"][name].pop("why", None))
            reserved += self.jobs[name]["budget"]
            time.sleep(5)  # stagger start-up (Claude Code, uv sync)
        self.save()
        return any(s["status"] in ("queued", "running") for s in self.state["jobs"].values())

    def run(self):
        self.log(f"batch {self.state['batch']}: {len(self.jobs)} jobs, ${self.spent():.2f} of ${self.args.total} spent")
        last_note = 0.0
        while self.tick():
            if time.time() - last_note > 600:
                self.log(f"spent ${self.spent():.2f} of ${self.args.total}, running {len(self.running())}, "
                         f"free {procs.free_gb():.1f} GB")
                last_note = time.time()
            time.sleep(15)
        waiting = [n for n, s in self.state["jobs"].items() if s["status"] == "waiting"]
        for n in waiting:  # queued jobs that never fit the budget leave their children waiting
            self.state["jobs"][n]["status"] = "skipped"
        self.save()
        self.log(f"end: ${self.spent():.2f} spent")
        for n, s in self.state["jobs"].items():
            self.log(f"  {n:<28} {s['status']:<8} attempts {s['attempts']}  {s.get('last', {})}")


def main():
    p = argparse.ArgumentParser(description="Run a job file of agent sessions in parallel, supervised.")
    p.add_argument("job_file")
    p.add_argument("--total", type=float, required=True, help="Spending limit in USD for the whole batch.")
    p.add_argument("--max-sessions", type=int, default=8)
    p.add_argument("--min-free-gb", type=float, default=8.0, help="Start a session only with this much RAM free.")
    p.add_argument("--emergency-gb", type=float, default=3.0, help="Below this, kill the largest pytest run.")
    p.add_argument("--stale-pytest-min", type=float, default=60.0, help="Kill pytest runs older than this.")
    p.add_argument("--dry-run", action="store_true", help="Show the jobs and exit.")
    a = p.parse_args()
    for stream in (sys.stdout, sys.stderr):
        stream.reconfigure(encoding="utf-8", errors="replace")
    if not os.environ.get("ANTHROPIC_API_KEY"):
        sys.exit("ANTHROPIC_API_KEY is not set in this shell.")
    b = Batch(Path(a.job_file), a)
    if a.dry_run:
        caps = sum(j["budget"] for j in b.jobs.values())
        for n, j in b.jobs.items():
            print(f"{n:<28} ${j['budget']:>6.2f} {j['approve']:<5} after={j['after'] or '-':<20} {j['cwd']}")
        print(f"{len(b.jobs)} jobs, caps add up to ${caps:.2f} (limit ${a.total:.2f})")
        return
    b.run()


if __name__ == "__main__":
    main()
