"""Integration smoke test of the three parts of this repository, without an LLM provider:

1. the package: a plant repository made from examples/safety-hazop, `cheme check` on it;
2. the viewer: `cheme serve --ui viewer/dist` on that plant and the live Playwright test
   (viewer/playwright.live.config.ts), so viewer and API are the same commit;
3. the agent runner: `jobs.py --dry-run` on its example, then its run-record path
   (agent.py's write_run_record -> `cheme runs record`) on a synthetic transcript, and the
   revisions it recorded: `core_commit` and the runner commit each from its own source,
   `same_revision` true only for one clean commit, null without git.

    uv sync --all-extras && (cd viewer && npm ci && npm run build)
    uv run python scripts/integration_smoke.py [--skip-viewer]

Exits non-zero on the first failure. Writes nothing into this checkout (all in a temporary dir).
"""

from __future__ import annotations

import argparse
import json
import os
import shutil
import subprocess
import sys
import tempfile
import time
import urllib.request
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[1]
SESSION = "5e0c1a2b-0000-4000-8000-000000000001"
PORT = 8795


def run(cmd: list[str], cwd: Path, env: dict | None = None, ok=(0,)) -> subprocess.CompletedProcess:
    print("+", " ".join(cmd), flush=True)
    done = subprocess.run(cmd, cwd=cwd, env=env, text=True, capture_output=True, check=False)
    if done.returncode not in ok:
        sys.exit(f"failed ({done.returncode}): {' '.join(cmd)}\n{done.stdout}\n{done.stderr}")
    return done


def git(cwd: Path, *args: str) -> str:
    return run(["git", *args], cwd).stdout.strip()


def expected_revision() -> tuple[str | None, bool | None]:
    """This checkout's HEAD and whether it has changes; (None, None) outside git."""
    head = subprocess.run(
        ["git", "rev-parse", "--verify", "-q", "HEAD"],
        cwd=ROOT,
        capture_output=True,
        text=True,
        check=False,
    )
    if head.returncode != 0:
        return None, None
    status = subprocess.run(
        ["git", "status", "--porcelain"], cwd=ROOT, capture_output=True, text=True, check=False
    )
    return head.stdout.strip(), bool(status.stdout.strip())


def make_plant(tmp: Path) -> Path:
    plant = tmp / "safety-hazop"
    shutil.copytree(ROOT / "examples" / "safety-hazop", plant)
    git(plant, "init", "-q", "-b", "main")
    git(plant, "add", "-A")
    git(
        plant,
        "-c",
        "user.name=smoke",
        "-c",
        "user.email=smoke@example.invalid",
        "commit",
        "-qm",
        "plant",
    )
    return plant


def check_package(plant: Path) -> None:
    done = run(["cheme", "check"], plant, ok=(0, 1))  # 1: a gate is open, which is fine here
    print(done.stdout[-400:])


def check_viewer(plant: Path) -> None:
    dist = ROOT / "viewer" / "dist"
    if not (dist / "index.html").is_file():
        sys.exit("viewer/dist is missing: run `npm ci && npm run build` in viewer/ first")
    server = subprocess.Popen(
        ["cheme", "serve", "--repo", str(plant), "--port", str(PORT), "--ui", str(dist)], cwd=plant
    )
    try:
        url = f"http://127.0.0.1:{PORT}"
        for _ in range(60):
            try:
                with urllib.request.urlopen(f"{url}/api/repo", timeout=2) as r:
                    if r.status == 200:
                        break
            except OSError:
                time.sleep(1)
        else:
            sys.exit("cheme serve did not answer /api/repo within 60 s")
        npx = shutil.which("npx") or "npx"
        run(
            [npx, "playwright", "test", "-c", "playwright.live.config.ts"],
            ROOT / "viewer",
            env={**os.environ, "CHEME_LIVE_URL": url},
        )
    finally:
        server.terminate()
        server.wait(timeout=20)


def check_runner(plant: Path, tmp: Path) -> None:
    runner = ROOT / "agent-cli"
    env = {**os.environ, "ANTHROPIC_API_KEY": "not-used-by-a-dry-run"}
    env.pop("VIRTUAL_ENV", None)
    run(
        [
            "uv",
            "run",
            "--project",
            str(runner),
            "jobs.py",
            "jobs/examples/issues.json",
            "--total",
            "20",
            "--dry-run",
        ],
        runner,
        env=env,
    )

    # The transcript where `cheme runs record --session-id` looks for it (CLAUDE_CONFIG_DIR).
    home = tmp / "claude-home"
    from chemeascode.integrations.claude_code import project_dir

    transcript = project_dir(plant, home) / f"{SESSION}.jsonl"
    transcript.parent.mkdir(parents=True)
    entries = [
        {
            "type": "user",
            "sessionId": SESSION,
            "timestamp": "2026-10-28T09:00:00.000Z",
            "message": {"role": "user", "content": [{"type": "text", "text": "smoke"}]},
        },
        {
            "type": "assistant",
            "sessionId": SESSION,
            "version": "2.1.3",
            "timestamp": "2026-10-28T09:00:05.000Z",
            "message": {
                "id": "msg_1",
                "model": "claude-opus-5-5",
                "role": "assistant",
                "content": [{"type": "text", "text": "STATUS: DONE"}],
                "usage": {"input_tokens": 1, "output_tokens": 2},
            },
        },
    ]
    transcript.write_text("\n".join(json.dumps(e) for e in entries) + "\n", encoding="utf-8")

    # agent.py's own recording code, with a result object as the SDK would return it. The
    # package's cheme (this checkout's environment) goes first on PATH.
    bin_dir = Path(sys.executable).parent
    env = {**env, "CLAUDE_CONFIG_DIR": str(home), "PATH": f"{bin_dir}{os.pathsep}{env['PATH']}"}
    start = git(plant, "rev-parse", "HEAD")
    code = (
        "import sys, types, agent\n"
        "from pathlib import Path\n"
        "args = types.SimpleNamespace(budget=1.0, effort='high', slug='smoke')\n"
        f"result = types.SimpleNamespace(session_id={SESSION!r}, result='STATUS: DONE', "
        "total_cost_usd=0.01, subtype='success')\n"
        f"print(agent.write_run_record(Path(sys.argv[1]), args, 'smoke', result, {start!r}))\n"
    )
    cmd = ["uv", "run", "--project", str(runner), "python", "-c", code, str(plant)]
    done = run(cmd, runner, env=env)
    print(done.stdout)
    records = sorted((plant / "runs").glob("*/run.yaml"))
    if not records:
        sys.exit("no run record written")
    tools = yaml.safe_load(records[-1].read_text(encoding="utf-8"))["tools"]
    print("tools:", json.dumps(tools, indent=1))

    head, dirty = expected_revision()
    problems = []
    if (tools.get("runner") or {}).get("name") != "agent-cli":
        problems.append("runner name is not agent-cli")
    if head is None:  # an exported snapshot: nothing may be invented
        if tools.get("same_revision") is not None or (tools.get("runner") or {}).get("commit"):
            problems.append("a revision was recorded although this checkout is not in git")
    else:
        if tools.get("core_commit") != head or (tools.get("runner") or {}).get("commit") != head:
            problems.append(f"core_commit / runner commit differ from HEAD {head}")
        if tools.get("same_revision") is not (not dirty):
            problems.append(f"same_revision {tools.get('same_revision')} with dirty={dirty}")
    if problems:
        sys.exit("run record: " + "; ".join(problems))
    where = f" (HEAD {head}, dirty {dirty})" if head else " (no git)"
    print("run record revisions as expected" + where)


def main() -> None:
    p = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    p.add_argument("--skip-viewer", action="store_true", help="Leave out the live viewer test.")
    a = p.parse_args()
    with tempfile.TemporaryDirectory() as name:
        tmp = Path(name)
        plant = make_plant(tmp)
        check_package(plant)
        if not a.skip_viewer:
            check_viewer(plant)
        check_runner(plant, tmp)
    print("integration smoke test passed")


if __name__ == "__main__":
    main()
