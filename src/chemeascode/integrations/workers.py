"""Local Python transport; no simulator or publication semantics (ADR 0072)."""

from __future__ import annotations

import contextlib
import hashlib
import json
import os
import shutil
import signal
import subprocess
import tempfile
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Protocol

from chemeascode.foundation.project_paths import local_path
from chemeascode.foundation.schemas.run import AdapterResult
from chemeascode.foundation.schemas.worker import ExecutionOutcome, WorkerRequest


@dataclass
class ExecutionResult:
    execution: ExecutionOutcome
    result: AdapterResult | None = None


class WorkerTransport(Protocol):
    """Deployment owns staging, invocation and cleanup, not numerical success.

    Future session/remote transports need not launch Python. Their configuration and
    credentials stay outside engineering YAML. This interface implements no such transport.
    """

    def execute(self, root: Path, request: WorkerRequest) -> ExecutionResult: ...


def interpreter(adapter_variable: str) -> Path:
    """Adapter-specific settings override the fallback, including invalid settings."""
    variable = adapter_variable if adapter_variable in os.environ else "CHEME_WORKER_PYTHON"
    python = Path(os.environ.get(variable, ""))
    if not python.is_absolute() or not python.is_file():
        raise ValueError(
            f"Set {adapter_variable} (or CHEME_WORKER_PYTHON) to an absolute Python executable; "
            f"{variable} is missing or invalid"
        )
    return python


def _stop_group(child: subprocess.Popen) -> None:
    if os.name == "nt":
        subprocess.run(
            ["taskkill", "/PID", str(child.pid), "/T", "/F"], capture_output=True, check=False
        )
    else:
        with contextlib.suppress(ProcessLookupError):
            os.killpg(child.pid, signal.SIGKILL)
    with contextlib.suppress(ProcessLookupError):
        child.kill()
    child.wait()


def evidence_files(evidence: Path) -> None:
    if any(
        p.is_symlink() or p.is_junction() or not (p.is_file() or p.is_dir())
        for p in [evidence, *evidence.rglob("*")]
    ):
        raise ValueError("Worker evidence contains a link or special file")


@dataclass(frozen=True)
class LocalPythonTransport:
    python: Path
    module: str

    def execute(self, root: Path, request: WorkerRequest) -> ExecutionResult:
        start = time.monotonic()
        state, code = "refused", None
        try:
            if not self.python.is_absolute() or not self.python.is_file():
                raise ValueError("Worker Python executable must be an existing absolute path")
            module = self.module.replace(".", "/")
            if not {module + ".py", module + "/__main__.py"}.intersection(request.files):
                raise ValueError("Worker module must be listed in the declared files")
            evidence = Path(request.evidence)
            if not evidence.is_absolute() or not evidence.is_dir():
                raise ValueError("Core must assign an existing absolute evidence directory")
            with tempfile.TemporaryDirectory(prefix="cheme-worker-") as temporary:
                temp = Path(temporary)
                stage = temp / "project"
                stage.mkdir()
                for name in request.files:
                    source = local_path(root, name)
                    if not source.is_file():
                        raise ValueError(f"Missing worker input: {name}")
                    target = stage / name
                    target.parent.mkdir(parents=True, exist_ok=True)
                    shutil.copyfile(source, target)
                    expected = request.fingerprints.get(name)
                    if (
                        expected
                        and expected != "sha256:" + hashlib.sha256(target.read_bytes()).hexdigest()
                    ):
                        raise ValueError(f"Model input changed while staging: {name}")
                req, response = temp / "request.json", temp / "response.json"
                req.write_text(request.model_dump_json(by_alias=True), encoding="utf-8")
                # Record exact inputs before the worker can edit its disposable staging copy.
                shutil.copytree(stage, evidence / "cheme-inputs")
                allowed = (
                    "PATH",
                    "SYSTEMROOT",
                    "WINDIR",
                    "TEMP",
                    "TMP",
                    "TMPDIR",
                    "HOME",
                    "USERPROFILE",
                    "LOCALAPPDATA",
                    "APPDATA",
                    "LANG",
                    "LC_ALL",
                )
                env = {key: os.environ[key] for key in allowed if key in os.environ}
                env.update(
                    OPENBLAS_NUM_THREADS="1", OMP_NUM_THREADS="1", MPLCONFIGDIR=str(temp / "mpl")
                )
                cmd = [
                    str(self.python),
                    "-E",
                    "-s",
                    "-B",
                    "-X",
                    "utf8",
                    "-m",
                    self.module,
                    str(req),
                    str(response),
                ]
                state = "failed"
                with (evidence / "worker.log").open("wb") as log:
                    child = subprocess.Popen(
                        cmd,
                        cwd=stage,
                        env=env,
                        stdin=subprocess.DEVNULL,
                        stdout=log,
                        stderr=subprocess.STDOUT,
                        start_new_session=os.name != "nt",
                        creationflags=subprocess.CREATE_NEW_PROCESS_GROUP if os.name == "nt" else 0,
                    )
                    try:
                        code = child.wait(timeout=request.timeout_s)
                    except subprocess.TimeoutExpired:
                        state = "timed-out"
                        _stop_group(child)
                        raise ValueError(
                            f"Worker timed out after {request.timeout_s:g} seconds"
                        ) from None
                    except BaseException:
                        _stop_group(child)
                        raise
                if code:
                    with (evidence / "worker.log").open("rb") as log:
                        log.seek(max(0, log.seek(0, 2) - 1500))
                        tail = log.read().decode("utf-8", errors="replace")
                    raise ValueError(f"Worker exit code {code}: {tail}")
                if (
                    not response.is_file()
                    or response.is_symlink()
                    or response.stat().st_size > 16_000_000
                ):
                    raise ValueError("Worker response missing, linked or too large")
                evidence_files(evidence)
                for name, expected in request.fingerprints.items():
                    original = local_path(evidence / "cheme-inputs", name)
                    if (
                        not original.is_file()
                        or "sha256:" + hashlib.sha256(original.read_bytes()).hexdigest() != expected
                    ):
                        raise ValueError(f"Worker altered archived input evidence: {name}")
                response_bytes = response.read_bytes()
                (evidence / "cheme-worker-response.json").write_bytes(response_bytes)
                try:
                    payload = json.loads(response_bytes)
                except (ValueError, UnicodeError) as exc:
                    raise ValueError("Invalid worker response JSON") from exc
                if not isinstance(payload, dict) or "evidence" in payload:
                    raise ValueError("Expected AdapterResult; core owns the evidence location")
                result = AdapterResult.model_validate(payload)
                outcome = ExecutionOutcome(
                    state="completed",
                    transport="local-python",
                    exit_code=code,
                    elapsed_s=time.monotonic() - start,
                )
                result.execution = outcome
                return ExecutionResult(outcome, result)
        except (OSError, ValueError) as exc:
            return ExecutionResult(
                ExecutionOutcome(
                    state=state,
                    transport="local-python",
                    exit_code=code,
                    elapsed_s=time.monotonic() - start,
                    message=str(exc),
                )
            )
