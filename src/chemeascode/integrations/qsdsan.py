"""Run trusted project Python in a disposable directory using a user-selected interpreter."""

from __future__ import annotations

import contextlib
import json
import os
import shutil
import signal
import subprocess
import tempfile
from pathlib import Path

from chemeascode.foundation.project_paths import local_path
from chemeascode.foundation.schemas.run import AdapterResult


def _stop_group(child: subprocess.Popen) -> None:
    if os.name == "nt":
        subprocess.run(
            ["taskkill", "/PID", str(child.pid), "/T", "/F"], capture_output=True, check=False
        )
    else:
        with contextlib.suppress(ProcessLookupError):
            os.killpg(child.pid, signal.SIGKILL)
    child.kill()
    child.wait()


def execute(root: Path, config, case: str, evidence: Path) -> AdapterResult:
    """Stage only declared inputs. The worker receives request and response filenames."""
    setting = os.environ.get("CHEME_QSDSAN_PYTHON", "")
    python = Path(setting)
    if not python.is_absolute() or not python.is_file():
        raise ValueError(
            "Set CHEME_QSDSAN_PYTHON to the absolute path of your trusted Python executable"
        )
    module = config.worker.replace(".", "/")
    if not {module + ".py", module + "/__main__.py"}.intersection(config.inputs):
        raise ValueError("Worker module must be listed in qsdsan.files")
    with tempfile.TemporaryDirectory(prefix="cheme-qsdsan-") as temporary:
        temp = Path(temporary)
        stage = temp / "project"
        stage.mkdir()
        for name in config.inputs:
            path = local_path(root, name)
            if not path.is_file():
                raise ValueError(f"Missing worker input: {name}")
            target = stage / name
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(path, target)
        request, response = temp / "request.json", temp / "response.json"
        request.write_text(
            json.dumps(
                {
                    "case": case,
                    "input": config.input,
                    "files": config.inputs,
                    "timeout_s": config.timeout_s,
                    "evidence": str(evidence.resolve()),
                }
            ),
            encoding="utf-8",
        )
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
        env.update(OPENBLAS_NUM_THREADS="1", OMP_NUM_THREADS="1", MPLCONFIGDIR=str(temp / "mpl"))
        cmd = [
            str(python),
            "-E",
            "-s",
            "-B",
            "-X",
            "utf8",
            "-m",
            config.worker,
            str(request),
            str(response),
        ]
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
                code = child.wait(timeout=config.timeout_s)
            except subprocess.TimeoutExpired as exc:
                _stop_group(child)
                raise ValueError(
                    f"QSDsan worker timed out after {config.timeout_s:g} seconds"
                ) from exc
        if code:
            with (evidence / "worker.log").open("rb") as log:
                log.seek(max(0, log.seek(0, 2) - 1500))
                tail = log.read().decode("utf-8", errors="replace")
            raise ValueError(f"QSDsan worker exit code {code}: {tail}")
        if not response.is_file() or response.is_symlink() or response.stat().st_size > 16_000_000:
            raise ValueError("Worker response missing, linked or too large")
        try:
            payload = json.loads(response.read_bytes())
        except (ValueError, UnicodeError) as exc:
            raise ValueError("Invalid worker response JSON") from exc
        if not isinstance(payload, dict) or "evidence" in payload:
            raise ValueError("Expected AdapterResult; core owns the evidence location")
        if any(
            p.is_symlink() or p.is_junction() or not (p.is_file() or p.is_dir())
            for p in [evidence, *evidence.rglob("*")]
        ):
            raise ValueError("Worker evidence contains a link or special file")
        return AdapterResult.model_validate(payload)
