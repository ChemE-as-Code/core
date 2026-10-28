"""Process and memory helpers shared by jobs.py and night.py (macOS, Linux and Windows, via psutil)."""

import time
from pathlib import Path

import psutil


def free_gb() -> float:
    return psutil.virtual_memory().available / 2**30


def running_agents() -> dict[str, float]:
    """{cwd: budget} of every agent.py session running on this machine (any orchestrator)."""
    found = {}
    for p in psutil.process_iter(["cmdline"]):
        args = p.info["cmdline"] or []
        if any(a.endswith("agent.py") for a in args) and "--cwd" in args and "--budget" in args:
            try:
                found[str(Path(args[args.index("--cwd") + 1]).resolve())] = float(args[args.index("--budget") + 1])
            except (ValueError, IndexError):
                pass
    return found


def kill_tree(p: psutil.Process) -> int:
    procs = []
    try:
        procs = p.children(recursive=True) + [p]
    except psutil.Error:
        return 0
    for q in procs:
        try:
            q.kill()
        except psutil.Error:
            pass
    return len(procs)


def _pytest_roots(roots: list[Path]):
    """Top-level pytest processes (not xdist workers) whose working directory is under one of roots."""
    roots = [r.resolve() for r in roots]
    for p in psutil.process_iter(["name", "cmdline", "create_time"]):
        cmd = " ".join(p.info["cmdline"] or [])
        if "pytest" not in cmd or "exec(eval(" in cmd:  # xdist workers die with their controller
            continue
        try:
            parent = p.parent()
            if parent and "pytest" in " ".join(parent.cmdline()):
                continue  # a launcher's child (uv run pytest -> pytest -> python): take the outermost
            cwd = Path(p.cwd()).resolve()
        except psutil.Error:
            continue
        if any(cwd.is_relative_to(r) for r in roots):
            yield p


def sweep_stale_pytest(roots: list[Path], max_age_s: float = 3600) -> list[str]:
    """Kill pytest runs older than max_age_s under roots: a test suite that runs this long has hung or
    belongs to a session that ended (agents leave background test runs behind). Returns what was killed."""
    killed, now = [], time.time()
    for p in _pytest_roots(roots):
        age = now - (p.info["create_time"] or now)
        if age > max_age_s:
            killed.append(f"pytest {p.pid} ({int(age / 60)} min, {kill_tree(p)} processes)")
    return killed


def emergency_relief(roots: list[Path]) -> str | None:
    """Kill the pytest tree under roots that uses the most memory; the agent sees a failed test run and reruns it."""
    best, best_mem = None, 0
    for p in _pytest_roots(roots):
        try:
            mem = sum(c.memory_info().rss for c in p.children(recursive=True)) + p.memory_info().rss
        except psutil.Error:
            continue
        if mem > best_mem:
            best, best_mem = p, mem
    if best is None:
        return None
    n = kill_tree(best)
    return f"pytest {best.pid} ({best_mem / 2**30:.1f} GB, {n} processes)"
