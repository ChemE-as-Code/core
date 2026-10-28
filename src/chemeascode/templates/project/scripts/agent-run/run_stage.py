#!/usr/bin/env python3
"""Run one stage of a staged agent design run, or the independent review after it.

    python3 scripts/agent-run/run_stage.py stage S1 --budget 3
    python3 scripts/agent-run/run_stage.py review S1 --budget 2
    python3 scripts/agent-run/run_stage.py stage S2 --budget 7 --dry-run   # print the prompt

Standard library only, Python 3.9 or later (macOS's ``/usr/bin/python3`` runs it); run it from
the plant repository root. It needs ``cheme`` and ``claude`` (Claude Code) on PATH, or
``CHEME`` / ``CLAUDE_BIN`` naming them.

The prompt is built from the repository, not from a plan written in advance:

- ``scripts/agent-run/spec.md``: the plant specification (one file, never repeated by hand);
- ``scripts/agent-run/stages.json``: per stage its ``target`` (a plant.yaml stage), ``task`` and
  ``budget_usd``;
- ``THIS STAGE``: the task, then what ``cheme status --json`` says is still to do for the
  target stage -- the sheets already drawn (not to be drawn again), the empty or planned sheets,
  the failing gates of every stage up to the target;
- ``FIX FIRST``: the open review findings (``cheme status``) and the previous review's
  ``carry_over`` list (``build/agent-run/<previous>/review.json``).

Everything a run produces goes to ``build/agent-run/<stage>/`` (``--out``): ``prompt.txt``,
``launch.json`` (command, versions, time, cost), ``result.json`` (Claude Code's JSON output),
``stderr.log`` and, last, ``done`` (``exit N``: wait for this file, not for a process).

Each session leaves a run record in ``runs/<run-id>/`` (``docs/agent-design-run.md`` in
cheme-as-code): the runner notes HEAD before the session, starts Claude Code with
``CHEME_RUN_RECORD=off`` (so the session's own hooks record nothing) and afterwards calls
``cheme runs record --kind agent --slug <stage> --task-file prompt.txt --cost <total_cost_usd>
--budget <cap> --start-commit <sha> --checks --commit --runner-name run_stage.py``, which
commits the run folder alone (the runner's commit is the plant repository's, the start commit).
A failed record is reported and does not change the exit code.

``--total-cap USD`` keeps a chain of sessions inside one total: the cap of this session shrinks
to what is left after the ``total_cost_usd`` of every earlier ``result.json`` under the output
directory, and the session is skipped when nothing is left. A stage that needs more tools
(``npm`` for a viewer) lists them as ``extra_tools`` in ``stages.json`` or gets
``--extra-tool``.
"""

from __future__ import annotations

import argparse
import datetime
import json
import os
import shutil
import string
import subprocess
import sys
import tempfile
from pathlib import Path

HERE = Path(__file__).resolve().parent


def run(command: list[str]) -> subprocess.CompletedProcess[str]:
    return subprocess.run(command, capture_output=True, text=True, check=False)


def tool(env: str, name: str, required: bool = True) -> str:
    found = os.environ.get(env) or shutil.which(name)
    if not found:
        if not required:  # a dry run only prints the command
            return name
        sys.exit(f"{name} not found: put it on PATH or set {env}")
    return found


def load_plan(path: Path) -> dict[str, dict]:
    stages = json.loads(path.read_text(encoding="utf-8"))["stages"]
    return {stage["id"]: stage for stage in stages}


def status(cheme: str) -> dict:
    result = run([cheme, "status", "--json"])
    if result.returncode != 0:
        sys.exit(f"cheme status failed: {result.stderr.strip()}")
    return json.loads(result.stdout)


def stages_up_to(data: dict, target: str) -> list[str]:
    stages = data["plant"]["stages"]
    return stages[: stages.index(target) + 1] if target in stages else stages


def this_stage(stage: dict, data: dict) -> str:
    """The stage task followed by what the repository says is left for its target stage."""
    lines = [stage["task"].strip(), ""]
    drawn = [s["id"] for s in data["sheets"] if s["state"] == "drawn"]
    todo = [f"{s['id']} ({s['state']})" for s in data["sheets"] if s["state"] != "drawn"]
    if drawn:
        lines.append(
            "Already drawn (edit them only to fix findings, never draw them again): "
            + ", ".join(drawn)
        )
    if todo:
        lines.append("Not drawn yet: " + ", ".join(todo))
    if data.get("next_sheet"):
        lines.append(f"Next sheet to draw: {data['next_sheet']}")
    failing = [
        f"[{name}] {gate['id']}: {gate['detail'] or gate['title']}"
        for name in stages_up_to(data, stage["target"])
        for gate in data["gates"].get(name, [])
        if gate["status"] == "fail"
    ]
    lines.append(
        f"Failing gates up to stage {stage['target']}: "
        + ("; ".join(failing) if failing else "none")
    )
    v = data["validation"]
    lines.append(
        f"cheme validate now: {v['errors']} error(s), {v['warnings']} warning(s)"
        + (
            " (not on a P&ID, by sheet: "
            + ", ".join(f"{k} {n}" for k, n in v["not_on_pid"].items())
            + ")"
            if v["not_on_pid"]
            else ""
        )
    )
    return "\n".join(lines)


def fix_first(stage_id: str, plan: dict[str, dict], data: dict, out_root: Path) -> str:
    ids = list(plan)
    previous = ids[ids.index(stage_id) - 1] if ids.index(stage_id) > 0 else None
    lines = []
    if previous:
        review = out_root / previous / "review.json"
        if review.is_file():
            carry = json.loads(review.read_text(encoding="utf-8")).get("carry_over") or []
            lines += [f"{i}) {item}" for i, item in enumerate(carry, 1)]
    for row in data["reviews"]["open"]:
        lines.append(f"- open review finding {row['id']} ({row['severity']}): {row['finding']}")
    return "\n".join(lines) or "nothing"


def spent(out_root: Path, skip: Path) -> float:
    """USD of every ``result.json`` under *out_root* except *skip*: ``total_cost_usd`` is the
    cumulative cost of a session (``num_turns`` counts only its last segment)."""
    total = 0.0
    for result in sorted(out_root.rglob("result.json")) if out_root.is_dir() else []:
        if result.resolve() == skip.resolve():
            continue
        try:
            total += float(json.loads(result.read_text(encoding="utf-8")).get("total_cost_usd", 0))
        except (OSError, ValueError, TypeError, AttributeError):
            continue
    return total


def summary(result: Path) -> dict:
    """Cost, turns and permission denials of a finished session, for launch.json."""
    try:
        data = json.loads(result.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}
    if not isinstance(data, dict):
        return {}
    return {
        "total_cost_usd": data.get("total_cost_usd"),
        "num_turns_last_segment": data.get("num_turns"),
        "permission_denials": len(data.get("permission_denials") or []),
        "is_error": data.get("is_error"),
    }


def record_run(args: argparse.Namespace, out: Path, budget: float, start_commit: str) -> str | None:
    """``cheme runs record`` for the finished session: the run folder, or None (reported)."""
    try:
        data = json.loads((out / "result.json").read_text(encoding="utf-8"))
    except (OSError, ValueError):
        data = None
    if not isinstance(data, dict) or not data.get("session_id"):
        print(f"{args.stage} {args.mode}: no session_id in result.json, no run record written")
        return None
    slug = args.stage if args.mode == "stage" else f"review-{args.stage}"
    command = [
        tool("CHEME", "cheme"),
        "runs",
        "record",
        "--session-id",
        str(data["session_id"]),
        "--kind",
        "agent",
        "--slug",
        slug,
        "--task-file",
        str(out / "prompt.txt"),
        "--budget",
        f"{budget:g}",
        "--checks",
        "--commit",
        "--runner-name",
        "run_stage.py",
    ]
    if data.get("total_cost_usd") is not None:
        command += ["--cost", str(data["total_cost_usd"])]
    if start_commit:
        command += ["--start-commit", start_commit]
    if isinstance(data.get("subtype"), str):
        command += ["--result", data["subtype"]]
    report = None
    if isinstance(data.get("result"), str) and data["result"].strip():
        with tempfile.NamedTemporaryFile(
            "w", suffix=".md", delete=False, encoding="utf-8"
        ) as handle:
            handle.write(data["result"].strip() + "\n")
            report = handle.name
        command += ["--report-file", report]
    try:
        done = run(command)
    finally:
        if report:
            os.unlink(report)
    if done.returncode != 0:
        print(f"{args.stage} {args.mode}: run record failed: {done.stderr.strip()}")
        return None
    folder = (done.stdout.strip().splitlines() or [""])[0]
    print(f"{args.stage} {args.mode}: run record {folder}")
    return folder


def fill(template: Path, values: dict[str, str]) -> str:
    return string.Template(template.read_text(encoding="utf-8")).safe_substitute(values)


def launch(
    args: argparse.Namespace,
    prompt: str,
    out: Path,
    budget: float,
    max_turns: int,
    extra_tools: list[str],
) -> int:
    out.mkdir(parents=True, exist_ok=True)
    done = out / "done"
    if done.exists():
        done.unlink()
    (out / "prompt.txt").write_text(prompt, encoding="utf-8")
    tools = [
        line.strip()
        for line in (HERE / "allowed-tools.txt").read_text(encoding="utf-8").splitlines()
        if line.strip() and not line.startswith("#")
    ]
    tools += [t for t in extra_tools if t not in tools]
    command = [
        tool("CLAUDE_BIN", "claude", required=not args.dry_run),
        "-p",
        prompt,
        "--output-format",
        "json",
        "--max-turns",
        str(max_turns),
        "--max-budget-usd",
        f"{budget:g}",
        "--settings",
        ".claude/settings.json",
        "--allowedTools",
        *tools,
    ]
    shown = [c if c != prompt else "<prompt.txt>" for c in command]
    meta = {
        "stage": args.stage,
        "mode": args.mode,
        "command": shown,
        "budget_usd": budget,
        "max_turns": max_turns,
        "started": datetime.datetime.now(datetime.timezone.utc).isoformat(timespec="seconds"),
        "cheme": run([tool("CHEME", "cheme"), "--version"]).stdout.strip(),
        "head": run(["git", "rev-parse", "HEAD"]).stdout.strip(),
    }
    if args.dry_run:
        print(prompt)
        print(f"\n(dry run: would run {' '.join(shown)}; prompt in {out / 'prompt.txt'})")
        return 0
    result, log = out / "result.json", out / "stderr.log"
    # the session's own SessionStart/SessionEnd hooks record nothing: the runner records it
    env = dict(os.environ, CHEME_RUN_RECORD="off")
    with result.open("w", encoding="utf-8") as stdout, log.open("w", encoding="utf-8") as stderr:
        code = subprocess.run(
            command, stdout=stdout, stderr=stderr, env=env, check=False
        ).returncode
    meta["finished"] = datetime.datetime.now(datetime.timezone.utc).isoformat(timespec="seconds")
    meta["exit_code"] = code
    meta.update(summary(result))
    meta["run_record"] = record_run(args, out, budget, meta["head"])
    (out / "launch.json").write_text(json.dumps(meta, indent=2) + "\n", encoding="utf-8")
    done.write_text(f"exit {code}\n", encoding="utf-8")
    cost = meta.get("total_cost_usd")
    print(
        f"{args.stage} {args.mode}: exit {code} in {out}"
        + (f"; cost USD {cost}" if cost is not None else "")
        + "; check the work yourself (tests, cheme validate), do not trust the summary"
    )
    return code


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n", 1)[0])
    parser.add_argument("mode", choices=["stage", "review"])
    parser.add_argument("stage", help="Stage id of stages.json, e.g. S1.")
    parser.add_argument("--budget", type=float, help="USD cap (default: stages.json).")
    parser.add_argument("--max-turns", type=int, default=200)
    parser.add_argument("--plan", type=Path, default=HERE / "stages.json")
    parser.add_argument("--spec", type=Path, default=HERE / "spec.md")
    parser.add_argument("--out", type=Path, help="Output directory (default build/agent-run).")
    parser.add_argument("--dry-run", action="store_true", help="Print the prompt, run nothing.")
    parser.add_argument(
        "--total-cap",
        type=float,
        help="USD for the whole chain: cap this session at what earlier result.json files left.",
    )
    parser.add_argument(
        "--extra-tool",
        action="append",
        default=[],
        help="Another allowed tool for this session (e.g. 'Bash(npm:*)'); repeatable.",
    )
    args = parser.parse_args(argv)
    if not Path("plant.yaml").is_file():
        sys.exit("run it from the plant repository root (no plant.yaml here)")
    plan = load_plan(args.plan)
    if args.stage not in plan:
        sys.exit(f"unknown stage {args.stage}; {args.plan} has {', '.join(plan)}")
    stage = plan[args.stage]
    spec = args.spec.read_text(encoding="utf-8").strip()
    out_root = args.out or Path("build") / "agent-run"
    data = status(tool("CHEME", "cheme"))
    if args.mode == "stage":
        budget = args.budget or float(stage.get("budget_usd", 5))
    else:
        budget = args.budget or float(stage.get("review_budget_usd", 2))
    out = out_root / args.stage / ("review" if args.mode == "review" else "")
    if args.total_cap is not None:
        left = args.total_cap - spent(out_root, out / "result.json")
        if left <= 0.01:
            print(
                f"{args.stage} {args.mode}: skipped, the total cap USD {args.total_cap:g} is spent"
            )
            return 3
        if left < budget:
            print(f"{args.stage} {args.mode}: cap lowered to USD {left:.2f} (total cap)")
            budget = round(left, 2)
    values = {
        "STAGE": args.stage,
        "TARGET": stage["target"],
        "SPEC": spec,
        "TASK": stage["task"].strip(),
        "THIS_STAGE": this_stage(stage, data),
        "FIX_FIRST": fix_first(args.stage, plan, data, out_root),
        "BUDGET": f"{budget:g}",
        "OUT": str(out_root / args.stage),
    }
    if args.mode == "stage":
        prompt = fill(HERE / "stage-prompt.md", values)
    else:
        result = out_root / args.stage / "result.json"
        values["RESULT"] = result.read_text(encoding="utf-8")[-4000:] if result.is_file() else "{}"
        prompt = fill(HERE / "reviewer-prompt.md", values)
    extra = list(stage.get("extra_tools") or []) + args.extra_tool
    return launch(args, prompt, out, budget, args.max_turns, extra)


if __name__ == "__main__":
    sys.exit(main())
