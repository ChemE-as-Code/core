"""IDAES, out of process: a simulator model (``domains/process/simulation/translate``) in, the
solved streams out, as JSON through ``idaes_worker.py`` (ADR 0039).

The worker runs in a separate Python that has idaes-pse, Pyomo and IPOPT (``idaes
get-extensions``); cheme-as-code never imports IDAES or Pyomo itself. Where it runs:

- ``CHEME_IDAES_COMMAND``: the command, as a shell would split it (a container, a remote host);
  it runs a copy of ``idaes_worker.py`` itself, the request goes to its stdin;
- ``CHEME_IDAES_PYTHON``: the Python with idaes-pse; the worker runs as ``<python> -I
  idaes_worker.py``.

Without either, :class:`IdaesUnavailable` is raised (the finding ``sim-unavailable``).
"""

from __future__ import annotations

import json
import os
import shlex
import subprocess
from pathlib import Path
from typing import Any

WORKER = Path(__file__).with_name("idaes_worker.py")
#: Seconds one solve may take (initialization of a recycle loop runs every unit several times).
TIMEOUT = 1800
HINT = (
    "set CHEME_IDAES_PYTHON to a Python with idaes-pse (pip install idaes-pse; idaes "
    "get-extensions for IPOPT), or use simulator: dwsim in process/simulation.yaml"
)


class IdaesUnavailable(RuntimeError):
    """No IDAES to run: neither ``CHEME_IDAES_PYTHON`` nor ``CHEME_IDAES_COMMAND``."""


class IdaesFailed(RuntimeError):
    """The worker ran and failed (model error, crash, timeout)."""


def _command() -> list[str]:
    if os.environ.get("CHEME_IDAES_COMMAND"):
        return shlex.split(os.environ["CHEME_IDAES_COMMAND"])
    python = os.environ.get("CHEME_IDAES_PYTHON")
    if not python:
        raise IdaesUnavailable(f"IDAES is not available: CHEME_IDAES_PYTHON is not set; {HINT}")
    if not Path(python).exists():
        raise IdaesUnavailable(
            f"IDAES is not available: CHEME_IDAES_PYTHON ({python}) does not exist; {HINT}"
        )
    return [python, "-I", str(WORKER)]


def solve(model: dict[str, Any], save: Path | None = None, details: bool = False) -> dict[str, Any]:
    """Solve *model* in IDAES. *save* is not supported (IDAES has no flowsheet file a user opens
    elsewhere): the result's ``save_error`` says so when it is given.

    Returns the worker's result in the shape of :func:`chemeascode.integrations.dwsim.solve`:
    ``version`` (idaes-pse), ``solver`` (IPOPT and its version), ``converged`` (IPOPT reached an
    optimal point of the square system and no unit reported a problem), ``iterations`` (IPOPT
    iterations of the final simultaneous solve), ``messages``, ``notes`` (initialization that
    did not finish; the simultaneous solve may still converge), ``streams``, ``units`` (id ->
    ``duty_kW``; a conversion reactor also ``extents_kmol_h``) and ``energies``. With *details*
    every stream also carries ``molar_mass_kg_kmol``, ``molar_enthalpy_kJ_kmol`` (IDAES's
    reference: formation enthalpies at 298.15 K included) and ``phases``.
    """
    command = _command()
    request = json.dumps({"model": model, "details": details})
    try:
        done = subprocess.run(
            command,
            input=request,
            check=False,
            capture_output=True,
            text=True,
            timeout=TIMEOUT,
        )
    except subprocess.TimeoutExpired as failure:
        raise IdaesFailed(f"IDAES did not finish within {TIMEOUT} s") from failure
    except OSError as failure:
        raise IdaesUnavailable(f"IDAES is not available: {failure}; {HINT}") from failure
    result = parse(done.stdout)
    if not result.get("ok"):
        tail = " | ".join((done.stderr or "").strip().splitlines()[-5:])
        reason = result.get("error") or tail or f"exit code {done.returncode}"
        raise IdaesFailed(f"IDAES failed: {reason}")
    if save is not None:
        result["save_error"] = "the IDAES backend writes no flowsheet file (--save is DWSIM's)"
    return result


def parse(stdout: str) -> dict[str, Any]:
    """The worker's result: the last line of its output (JSON); ``{}`` when there is none."""
    lines = (stdout or "").strip().splitlines()
    if not lines:
        return {}
    try:
        result = json.loads(lines[-1])
    except json.JSONDecodeError:
        return {}
    return result if isinstance(result, dict) else {}
