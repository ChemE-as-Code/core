"""Minimal Claude Agent SDK runner: one task, one working directory, a hard USD limit.

Usage:
    uv run agent.py "task text" --cwd /path/to/repo --budget 5
    uv run agent.py --task-file prompt.md --cwd /path/to/repo --budget 20 --unattended

Reads ANTHROPIC_API_KEY from the environment; the key is never printed or written.
Each run appends one JSON record (cost, time, tokens, session id) to runs.jsonl next to
this file, and writes the transcript to logs/<run-id>.log. In a process folder (process.yaml)
it also has `cheme runs record` write and commit runs/<run-id>/ (core ADR 0029).
"""

import argparse
import asyncio
import json
import os
import re
import sys
import subprocess
import time
from importlib import metadata
from datetime import datetime, timezone
from pathlib import Path

from claude_agent_sdk import (
    AssistantMessage,
    ClaudeAgentOptions,
    ClaudeSDKClient,
    HookMatcher,
    ResultMessage,
    SystemMessage,
    TextBlock,
    ToolUseBlock,
)

HERE = Path(__file__).resolve().parent

# Bash commands that need a human yes before they run.
DESTRUCTIVE = re.compile(
    r"(^|[;&|(]\s*|\bsudo\s+|\bxargs\s+(-\S+\s+)*)("
    r"rm|rmdir|unlink|shred|dd|mkfs\S*|truncate|chmod\s+-R|chown\s+-R|"
    r"git\s+(push|reset\s+--hard|clean|rebase|filter-repo|branch\s+-D|checkout\s+--|restore|stash\s+(drop|clear)|tag\s+-d|"
    r"worktree\s+(remove|prune))|"
    r"gh\s+(pr\s+(merge|close)|issue\s+(close|delete|edit|comment)|repo\s+delete|release)|"
    # gh api with a writing method reaches every endpoint above (e.g. PUT .../pulls/1/merge)
    r"gh\s+api\b[^;&|]*(-X|--method)\s*(PUT|POST|PATCH|DELETE)|"
    r"find\b.*\s-delete|"
    # PowerShell (the Windows tool set has a PowerShell tool next to Bash)
    r"Remove-Item|Move-Item|Clear-Content|Stop-Process|Format-Volume"
    r")\b",
    re.IGNORECASE,
)
# Refused even with --approve auto: irreversible or shared-state damage.
HARD_DENY = re.compile(
    r"\bgit\s+push\b[^\n;&|]*(\s--force(?!-with-lease)\b|\s-f\b|\s\+\S)"
    r"|\bgit\s+push\b[^\n;&|]*\s(origin\s+)?(HEAD:)?(main|master)\s*($|[;&|])"
    r"|\bgh\s+(repo\s+delete|release\s+delete)"
    r"|\bgh\s+api\b[^;&|]*(-X|--method)\s*DELETE"
    r"|\brm\s+-[a-z]*r[a-z]*\s+(/|~|\$HOME|[A-Za-z]:|\.\.)(\s|$|/|\\)"
    r"|Remove-Item\b[^;&|]*-Recurse[^;&|]*\s([A-Za-z]:\\?\s|\.\.|~|\$HOME|\$env:USERPROFILE)"
    r"|\bgit\s+branch\s+-D\s+(main|master)\b",
    re.IGNORECASE,
)
# Commands that could reveal the API key are refused outright.
SECRET = re.compile(
    r"ANTHROPIC_API_KEY|\bprintenv\b|(^|[;&|]\s*)(env|set|export)\s*($|[;&|])"
    r"|os\.environ|process\.env\b|/proc/\S*/environ|\bps\b[^;&|]*\be(ww)?\b"
    r"|\b(Get-ChildItem|gci|dir|ls)\s+env:|\[Environment\]::GetEnvironmentVariables",
    re.IGNORECASE,
)
# Tools that end the turn to wait for something; in a headless run that ends the session.
WAITING_TOOLS = ["ScheduleWakeup", "CronCreate", "CronDelete", "RemoteTrigger", "Monitor"]
STATUS_RULE = (
    "\n\n---\nYou run headless: when you end your turn the session is over and nobody replies. Do not "
    "end your turn to wait for background work (tests, CI, sub-agents); run it in the foreground. "
    "If the task above does not prescribe its own final line, end your final message with "
    "`STATUS: DONE` or `STATUS: BLOCKED: <reason>`."
)
DONE = re.compile(r"STATUS: (DONE|BLOCKED)|VERDICT: (merge|fix)")
NUDGE = (
    "You ended your turn without finishing (no final STATUS/VERDICT line). Results of background work "
    "you started will not arrive. Check the current state, continue in the foreground until the task is "
    "complete, then end with the final line the task asks for (or `STATUS: DONE` / `STATUS: BLOCKED: <reason>`)."
)
# USD per token, to estimate the cost of a session that crashed before its result message.
def _price(inp: float, out: float, cache_read: float) -> dict:  # USD per million tokens; cache writes 1.25x input
    return {"input_tokens": inp / 1e6, "output_tokens": out / 1e6,
            "cache_read_input_tokens": cache_read / 1e6, "cache_creation_input_tokens": 1.25 * inp / 1e6}


PRICES = {
    "claude-opus-5-5": _price(4, 20, 0.2),
    "claude-sonnet-5-5": _price(2, 10, 0.2),
    "claude-haiku-5-5": _price(0.1, 0.5, 0.01),
    "claude-fable-5-1": _price(10, 50, 0.25),
}


def make_bash_guard(approve: str, log, audit=lambda decision, cmd: None):
    """approve: 'ask' (y/N on the terminal), 'deny' (refuse every destructive command) or 'auto'
    (allow destructive commands except HARD_DENY, so agents can push branches and merge their PRs)."""
    async def guard(input_data, tool_use_id, context):
        cmd = input_data.get("tool_input", {}).get("command", "")
        if SECRET.search(cmd):
            audit("deny-secret", cmd)
            return _decide("deny", "Commands that print environment variables are not allowed.")
        if not DESTRUCTIVE.search(cmd):
            return {}
        if HARD_DENY.search(cmd):
            log(f"[guard] denied (hard): {cmd}")
            audit("deny-hard", cmd)
            return _decide("deny", "Refused by policy: force-push, pushing to main/master, deleting repositories or "
                                   "releases, or recursive deletes outside the working tree. Use a safe alternative "
                                   "(e.g. merge origin/main into your branch and push it normally).")
        if approve == "auto":
            audit("allow-auto", cmd)
            return {}
        if approve == "deny":
            log(f"[guard] denied (unattended): {cmd}")
            audit("deny-unattended", cmd)
            return _decide("deny", "Destructive command refused in unattended mode; find a non-destructive way or report it.")
        print(f"\n\033[33m[approve?]\033[0m {cmd}")
        try:
            answer = await asyncio.to_thread(input, "Run this command? [y/N] ")
        except EOFError:  # no terminal to answer on
            answer = ""
        ok = answer.strip().lower() in ("y", "yes")
        log(f"[guard] {'approved' if ok else 'denied'}: {cmd}")
        audit("allow-user" if ok else "deny-user", cmd)
        return _decide("allow" if ok else "deny", "Approved by the user." if ok else "The user declined this command.")

    return guard


def make_write_guard(cwd: Path, log):
    async def guard(input_data, tool_use_id, context):
        path = input_data.get("tool_input", {}).get("file_path") or input_data.get("tool_input", {}).get("notebook_path")
        if path and not (cwd / path).resolve().is_relative_to(cwd):  # relative paths are the agent's, not ours
            log(f"[guard] denied write outside cwd: {path}")
            return _decide("deny", f"Writes are limited to {cwd}.")
        return {}

    return guard


def _decide(decision, reason):
    return {"hookSpecificOutput": {"hookEventName": "PreToolUse",
                                   "permissionDecision": decision,
                                   "permissionDecisionReason": reason}}


async def run(args) -> int:
    task = Path(args.task_file).read_text(encoding="utf-8") if args.task_file else args.task
    cwd = Path(args.cwd).resolve()
    started_at = datetime.now(timezone.utc)
    run_id = started_at.strftime("%Y%m%d-%H%M%S") + (f"-{args.slug}" if args.slug else "")
    plant = (cwd / "plant.yaml").exists()  # a plant repository / process folder: write a run record
    start_commit = _git(cwd, "rev-parse", "HEAD")
    (HERE / "logs").mkdir(exist_ok=True)
    log_file = (HERE / "logs" / f"{run_id}.log").open("w", encoding="utf-8")

    def log(line: str):
        log_file.write(line + "\n")
        log_file.flush()

    log(f"# task\n{task}\n# cwd {cwd}\n# model {args.model} budget ${args.budget}\n")

    def audit(decision: str, cmd: str):  # every destructive-command decision, for a later look
        with (HERE / "logs" / "audit.jsonl").open("a", encoding="utf-8") as f:
            f.write(json.dumps({"run_id": run_id, "job": os.environ.get("AGENT_CLI_JOB"),
                                "decision": decision, "command": cmd}) + "\n")
    options = ClaudeAgentOptions(
        cwd=str(cwd),
        model=args.model,
        effort=args.effort,
        max_budget_usd=args.budget,
        max_turns=args.max_turns,
        system_prompt={"type": "preset", "preset": "claude_code"},
        setting_sources=["project", "local"],  # CLAUDE.md, project skills and settings; not ~/.claude
        # Tools run without per-call prompts; the PreToolUse hooks below still run first and
        # ask before destructive Bash, refuse key-revealing commands and writes outside cwd.
        permission_mode="bypassPermissions",
        hooks={"PreToolUse": [
            HookMatcher(matcher="Bash|PowerShell", hooks=[make_bash_guard(args.approve, log, audit)], timeout=3600),
            HookMatcher(matcher="Write|Edit|MultiEdit|NotebookEdit", hooks=[make_write_guard(cwd, log)]),
        ]},
        disallowed_tools=WAITING_TOOLS,
        max_buffer_size=64 * 1024 * 1024,  # one large tool output (a PDF, a test log) exceeds the 1 MB default
    )

    started = time.monotonic()
    result: ResultMessage | None = None
    session_id, crash, last_text = None, None, ""
    prompt = task + STATUS_RULE
    try:
        async with ClaudeSDKClient(options=options) as client:
            for attempt in range(args.nudges + 1):
                await client.query(prompt)
                last_text = ""
                async for msg in client.receive_response():
                    if isinstance(msg, SystemMessage) and msg.subtype == "init":
                        session_id = msg.data.get("session_id", session_id)
                    elif isinstance(msg, AssistantMessage):
                        for block in msg.content:
                            if isinstance(block, TextBlock) and block.text.strip():
                                last_text = block.text
                                print(block.text)
                                log(block.text)
                            elif isinstance(block, ToolUseBlock):
                                detail = block.input.get("command") or block.input.get("file_path") or block.input.get("skill") or ""
                                print(f"\033[2m  · {block.name} {str(detail)[:140]}\033[0m")
                                log(f"  · {block.name} {json.dumps(block.input)[:2000]}")
                    elif isinstance(msg, ResultMessage):
                        result = msg
                        session_id = msg.session_id
                # Stop on a final line, an error result (e.g. budget reached) or when the budget is nearly used.
                if (result is None or result.is_error or DONE.search(last_text)
                        or (result.total_cost_usd or 0) >= 0.9 * args.budget):
                    break
                log(f"[runner] no final line; nudging to continue ({attempt + 1}/{args.nudges})")
                prompt = NUDGE
    except Exception as e:  # Claude Code crashed (out of memory, native crash, ...): still record the run
        crash = f"{type(e).__name__}: {e}"[:500]
        log(f"[runner] session crashed: {crash}")
        print(f"\n[runner] session crashed: {crash}")

    wall = time.monotonic() - started
    finished_at = datetime.now(timezone.utc)
    cost, estimated = (result.total_cost_usd, False) if result else (estimate_cost(session_id, args.model), True)
    summary = {
        "run_id": run_id,
        "finished": finished_at.isoformat(timespec="seconds"),
        "cwd": str(cwd),
        "model": args.model,
        "effort": args.effort,
        "budget_usd": args.budget,
        "task": task[:500],
        "wall_s": round(wall),
        # night.py's ledger sums cost_usd: a crashed run counts with its transcript estimate, never as zero
        "cost_usd": cost,
        "cost_estimated": estimated,
        "subtype": result.subtype if result else ("crashed" if crash else "no-result"),
        # DONE | BLOCKED | VERDICT-merge | VERDICT-fix, or null when the agent stopped without a final line
        "final_status": _final_status(last_text),
        "job": os.environ.get("AGENT_CLI_JOB"),  # set by jobs.py
        "batch": os.environ.get("AGENT_CLI_BATCH"),
        "error": crash,
        "num_turns": result.num_turns if result else None,
        "usage": result.usage if result else None,
        "session_id": session_id,
    }
    with (HERE / "runs.jsonl").open("a", encoding="utf-8") as f:
        f.write(json.dumps(summary) + "\n")
    log(f"\n# result\n{json.dumps(summary, indent=2)}\n{result.result if result and result.result else ''}")
    log_file.close()

    cost = f"${summary['cost_usd']:.2f}" if summary["cost_usd"] is not None else "unknown"
    print(f"\n── {summary['subtype']} · cost {cost} of ${args.budget} · {wall / 60:.1f} min · "
          f"{summary['num_turns']} turns · log logs/{run_id}.log")
    if plant:
        print(write_run_record(cwd, args, task, result, start_commit))
    return 0 if result and not result.is_error else 1


def write_run_record(cwd, args, task, result, start_commit) -> str:
    """`cheme runs record` writes runs/<run-id>/ (core ADR 0029) and commits it as the run's last commit."""
    if not result:
        return "run record: no result message, nothing recorded"
    files = {}
    for name, text in (("task", task), ("report", result.result or "")):
        files[name] = HERE / "logs" / f"{result.session_id}.{name}.md"
        files[name].write_text(text, encoding="utf-8")
    runner_commit = _git(HERE, "rev-parse", "HEAD")
    cmd = ["cheme", "runs", "record", "--session-id", result.session_id, "--kind", "agent",
           "--task-file", str(files["task"]), "--report-file", str(files["report"]),
           "--cost", str(result.total_cost_usd), "--budget", str(args.budget), "--effort", args.effort,
           "--result", result.subtype, "--start-commit", start_commit, "--checks", "--commit",
           "--runner-name", "agent-cli", "--sdk-version", metadata.version("claude-agent-sdk")]
    if args.slug:
        cmd += ["--slug", args.slug]
    if runner_commit:
        cmd += ["--runner-commit", runner_commit, "--runner-dirty" if _git(HERE, "status", "--porcelain") else "--runner-clean"]
    r = subprocess.run(cmd, cwd=cwd, capture_output=True, text=True)
    return f"run record: {(r.stdout + r.stderr).strip()[-500:]}"


def estimate_cost(session_id: str | None, model: str) -> float | None:
    """Cost of a session from its Claude Code transcript (token usage x list prices), for runs that
    crashed before the SDK reported total_cost_usd. Messages are counted once by id."""
    prices = PRICES.get(model)
    if not session_id or not prices:
        return None
    seen, total = set(), 0.0
    for f in (Path.home() / ".claude" / "projects").glob(f"*/{session_id}.jsonl"):
        for line in f.open(encoding="utf-8", errors="replace"):
            if '"usage"' not in line:
                continue
            try:
                msg = json.loads(line).get("message") or {}
            except ValueError:
                continue
            usage, mid = msg.get("usage"), msg.get("id")
            if usage and mid and mid not in seen:
                seen.add(mid)
                total += sum(usage.get(k, 0) * p for k, p in prices.items())
    return round(total, 4) if seen else None


def _final_status(text: str) -> str | None:
    m = DONE.search(text or "")
    return None if not m else (m.group(1) or f"VERDICT-{m.group(2)}")


def _git(cwd: Path, *a: str) -> str | None:
    r = subprocess.run(["git", *a], cwd=cwd, capture_output=True, text=True)
    return r.stdout.strip() if r.returncode == 0 else None


def main():
    p = argparse.ArgumentParser(description="Run one Claude agent task in a repository with a spending limit.")
    p.add_argument("task", nargs="?", help="Task text (or use --task-file).")
    p.add_argument("--task-file", help="Read the task from a file.")
    p.add_argument("--cwd", default=".", help="Working directory for the agent (default: current).")
    p.add_argument("--budget", type=float, required=True, help="Hard spending limit in USD for this run.")
    p.add_argument("--model", default="claude-opus-5-5")
    p.add_argument("--effort", default="high", choices=["low", "medium", "high", "xhigh", "max"])
    p.add_argument("--max-turns", type=int, default=None)
    p.add_argument("--nudges", type=int, default=2,
                   help="Follow-up 'continue' prompts when the agent stops without a final line (default 2).")
    p.add_argument("--slug", help="Short name appended to the run id, e.g. concept-to-pfd.")
    p.add_argument("--unattended", action="store_true",
                   help="Never prompt: destructive commands are refused instead of asked (= --approve deny).")
    p.add_argument("--approve", choices=["ask", "deny", "auto"], default=None,
                   help="Destructive commands: ask y/N (default), deny all, or auto = allow all except the hard-deny "
                        "list (force-push, push to main, repo/release deletion, recursive deletes outside the tree).")
    args = p.parse_args()
    args.approve = args.approve or ("deny" if args.unattended else "ask")
    for stream in (sys.stdout, sys.stderr):  # agent text and the summary line are UTF-8 (Windows consoles are not)
        stream.reconfigure(encoding="utf-8", errors="replace")
    if not (args.task or args.task_file):
        p.error("give a task or --task-file")
    # This runner writes the run record itself: turn off the plant template's session hooks
    # (cheme runs start/record) in the agent's Claude Code child process.
    os.environ["CHEME_RUN_RECORD"] = "off"
    if not os.environ.get("ANTHROPIC_API_KEY"):
        sys.exit("ANTHROPIC_API_KEY is not set in this shell (export it, or add it to your shell profile).")
    sys.exit(asyncio.run(run(args)))


if __name__ == "__main__":
    main()
