"""DWSIM, out of process: a simulator model (``domains/process/simulation/translate``) in, the
solved streams out, as JSON through ``dwsim_worker.py``.

The worker runs where DWSIM is installed; cheme-as-code never loads .NET itself. Where it runs:

- ``CHEME_DWSIM_COMMAND``: the command, as a shell would split it (e.g. a remote host);
- ``CHEME_DWSIM_PATH``: a local DWSIM install (``/usr/local/lib/dwsim``); the worker runs
  with this Python, which needs pythonnet;
- else the Docker image :data:`IMAGE` (docker/dwsim/Dockerfile).
"""

from __future__ import annotations

import json
import os
import shlex
import shutil
import subprocess
import sys
import uuid
from pathlib import Path
from typing import Any

#: The Docker image with DWSIM and the worker (docker/dwsim/Dockerfile).
IMAGE = "cheme-dwsim:9.0.5"
WORKER = Path(__file__).with_name("dwsim_worker.py")
#: Seconds one solve may take (the image runs emulated on Apple silicon).
TIMEOUT = 900
HINT = (
    "build the DWSIM image (docker build --platform linux/amd64 -t cheme-dwsim:9.0.5 -f "
    "docker/dwsim/Dockerfile . in the cheme-as-code repository), or set "
    "CHEME_DWSIM_PATH to a DWSIM install (with pythonnet in this Python)"
)


class DwsimUnavailable(RuntimeError):
    """No DWSIM to run: no image, no install, no command."""


class DwsimFailed(RuntimeError):
    """The worker ran and failed (DWSIM error, crash, timeout)."""


def _docker(docker: str, *args: str) -> subprocess.CompletedProcess:
    try:
        return subprocess.run(
            [docker, *args], check=False, capture_output=True, text=True, timeout=60
        )
    except (subprocess.TimeoutExpired, OSError) as failure:
        raise DwsimUnavailable(f"DWSIM is not available: docker does not answer ({failure})") from (
            failure
        )


def _command(save: Path | None) -> tuple[list[str], str | None, dict[str, str], str | None]:
    """The worker command, the path the worker saves the flowsheet to (as it sees it), its
    environment, and the container name (Docker only)."""
    env = dict(os.environ)
    if os.environ.get("CHEME_DWSIM_COMMAND"):
        target = str(save.resolve()) if save else None
        return shlex.split(os.environ["CHEME_DWSIM_COMMAND"]), target, env, None
    if os.environ.get("CHEME_DWSIM_PATH"):
        path = os.environ["CHEME_DWSIM_PATH"]
        # read by the loader at start only: set before the worker starts
        libraries = [path, os.path.join(path, "ThermoCS"), env.get("LD_LIBRARY_PATH", "")]
        env["LD_LIBRARY_PATH"] = ":".join(p for p in libraries if p)
        if save is not None:
            save.parent.mkdir(parents=True, exist_ok=True)
        return [sys.executable, "-I", str(WORKER)], str(save.resolve()) if save else None, env, None
    docker = shutil.which("docker")
    if docker is None:
        raise DwsimUnavailable(f"DWSIM is not available: docker is not installed; {HINT}")
    found = _docker(docker, "image", "inspect", IMAGE)
    if found.returncode != 0:
        if "daemon" in (found.stderr or "").lower():
            raise DwsimUnavailable(
                "DWSIM is not available: the Docker daemon is not running (start Docker)"
            )
        raise DwsimUnavailable(f"DWSIM is not available: no Docker image {IMAGE}; {HINT}")
    name = f"cheme-dwsim-{os.getpid()}-{uuid.uuid4().hex[:8]}"
    command = [docker, "run", "-i", "--rm", "--name", name, "--platform", "linux/amd64"]
    # the worker of this cheme-as-code, not the one copied into the image when it was built
    command += ["-v", f"{WORKER.resolve()}:/opt/cheme/dwsim_worker.py:ro"]
    target = None
    if save is not None:
        save.parent.mkdir(parents=True, exist_ok=True)
        command += ["-v", f"{save.parent.resolve()}:/out"]
        target = f"/out/{save.name}"
    return [*command, IMAGE], target, env, name


def solve(model: dict[str, Any], save: Path | None = None, details: bool = False) -> dict[str, Any]:
    """Solve *model* in DWSIM; with *save*, also write the flowsheet there (``.dwxmz``).

    Returns the worker's result: ``version``, ``converged``, ``iterations`` (the flowsheet
    passes DWSIM made over every solve: one per solve without a recycle, else the passes of the
    worker's tear iteration and of DWSIM's recycle test after it), ``messages`` (a tear that
    does not converge is named with how far its copy is off), ``streams`` (id ->
    ``temperature_K``, ``pressure_Pa``, ``mass_flow_kg_s``, ``mole_fractions`` by compound id,
    ``vapor_fraction``), ``units`` (id -> ``duty_kW``), ``energies`` (id -> ``duty_kW``) and
    ``save_error`` when the flowsheet could not be saved.

    A feed with ``vapor_fraction`` (instead of ``temperature_K``) is a saturation state: DWSIM
    finds its temperature at the pressure. With *details* every stream also carries
    ``density_kg_m3``, ``molar_mass_kg_kmol``, ``molar_enthalpy_kJ_kmol`` (DWSIM's reference) and
    ``phases`` (``vapor``, ``liquid``, ``liquid2`` present -> ``fraction``, ``density_kg_m3``,
    ``molar_enthalpy_kJ_kmol``, ``mole_fractions``), a saturation feed at vapour fraction 0 or 1
    ``incipient`` (the phase in equilibrium that is not present, vapour at the bubble point and
    liquid at the dew point: ``phase``, ``mole_fractions``), and the result
    ``interaction_parameters`` (``[{"components": [id, id], "kij"}]``, the package's own values
    for the model's compound pairs; ``kij`` None where it holds none; NRTL and UNIQUAC also
    ``activity``, the pair's entry with ``components`` in DWSIM's order, or None) and
    ``package_settings`` (its liquid-density settings; NRTL and UNIQUAC also their vapour,
    Poynting and missing-parameter settings), which the property-package benchmarks
    (tests/test_process_simulate_property_package*.py) read.
    """
    command, target, env, container = _command(save)
    request = json.dumps({"model": model, "save": target, "details": details})
    try:
        done = subprocess.run(
            command,
            input=request,
            check=False,
            capture_output=True,
            text=True,
            timeout=TIMEOUT,
            env=env,
        )
    except subprocess.TimeoutExpired as failure:
        if container is not None:
            _docker(command[0], "kill", container)
        raise DwsimFailed(f"DWSIM did not finish within {TIMEOUT} s") from failure
    except OSError as failure:
        raise DwsimUnavailable(f"DWSIM is not available: {failure}; {HINT}") from failure
    try:
        result = json.loads(done.stdout.strip().splitlines()[-1]) if done.stdout.strip() else {}
    except json.JSONDecodeError:
        result = {}
    if not result.get("ok"):
        tail = " | ".join((done.stderr or "").strip().splitlines()[-5:])
        reason = result.get("error") or tail or f"exit code {done.returncode}"
        raise DwsimFailed(f"DWSIM failed: {reason}")
    return result
