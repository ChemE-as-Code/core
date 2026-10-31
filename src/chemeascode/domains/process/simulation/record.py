"""The run record of ``cheme process simulate --fill``: ``process/simulation-run.json``.

The CLI prints the convergence and the unit results of a simulation; the record keeps them, so
that the viewer (``GET /api/simulation``) and a reviewer see what the last run gave without
running the simulator (DWSIM or IDAES, ADR 0038) again. It is generated: ``--fill`` rewrites
the entry of its case after every run the simulator finished (converged or not); ``--check``
writes nothing and reports an entry made from other inputs (``cheme.process-sim-run-stale``)
or a case without one (``cheme.process-sim-run-missing``, info). Never edit it by hand.

Format (schema ``cheme/simulation-run/v1``), one entry per case::

    {"schema": "cheme/simulation-run/v1", "kind": "simulation-run",
     "cases": {"design": {
        "case": "design", "run_at": "2026-10-23T12:00:00Z", "tool": "cheme-as-code 0.9.0",
        "simulator": {"name": "dwsim", "version": "9.0.5.0", "method": "Peng-Robinson (PR)"},
        "property_package": "Peng-Robinson (PR)",
        "model_fingerprint": "<the fingerprint of the simulator model>",
        "inputs": {"commit": "<HEAD>", "dirty": [...], "fingerprints": {"<path>": "sha256:..."}},
        "converged": true, "status": "converged", "iterations": 4, "messages": [],
        "units": [{"id", "unit", "status": "simulated", "basis", "converged", "results",
                   "warnings", "coupling": "native" | "external-unit", "outer_loop"},
                  {"id", "status": "excluded", "reason"}],
        "streams": [{"id", "values", "filled", "kept"}],
        "energy": {"reference", "tolerance", "closure": {"units", "plant"}, "exchangers",
                   "utility_levels", "utilities"},
        "findings": [...]}}}

``basis`` is how the unit's outlet follows from its inlets (``predictive``, ``shortcut``,
``specified``; :data:`~.translate.UNIT_BASIS`). A component separator's row is ``specified``
and carries ``basis_source`` and ``operating_basis`` where given and a ``note`` that its
convergence closes the balances around a given split and predicts nothing: a reader never
takes a converged specified split for a predicted one. Entries written before it lack it.
``energy`` (converged runs, :func:`.energy.audit`) is absent from older entries.

``model_fingerprint`` is the fingerprint every simulated stream value carries: the feeds, the
specs, the property package and the simulator model, not the values the run filled. The record
is current while the inputs translate to the same fingerprint (:func:`staleness`); ``inputs``
fingerprints the files as they were after the run (the flowsheet with its filled values), so a
reader also sees which files changed since.

Each entry is an adapter result (``cheme/adapter-result/v1``,
:mod:`chemeascode.foundation.schemas.run`) in this file's keys: ``simulator`` is its
``solver`` (``method`` the property package), ``status`` follows ``converged``. Entries written
before both were added lack them and read the same. ``iterations`` is the number of flowsheet
passes DWSIM made (:func:`chemeascode.integrations.dwsim.solve`), with ``simulator: idaes``
the IPOPT iterations of the final simultaneous solve
(:func:`chemeascode.integrations.idaes.solve`; ``simulator.solver`` then names IPOPT and its
version, ``notes`` an initialization that did not finish); null where the worker does not report it.
"""

from __future__ import annotations

import datetime as _dt
import json
from pathlib import Path
from typing import Any

from chemeascode.domains.chemistry.catalysts import CATALYSTS_FILE
from chemeascode.domains.chemistry.reactions import REACTIONS_FILE
from chemeascode.domains.process import FLOWSHEET_FILE, MATERIALS_FILE
from chemeascode.domains.process.simulation import SIMULATION_FILE
from chemeascode.foundation.findings import Finding
from chemeascode.foundation.schemas.run import AdapterResult, finding_dict

RUN_FILE = "process/simulation-run.json"
RUN_SCHEMA = "cheme/simulation-run/v1"
#: The files a simulation reads; the record fingerprints those that exist (the catalysts: the
#: fixed beds coupled as external units).
RUN_INPUTS = (MATERIALS_FILE, FLOWSHEET_FILE, REACTIONS_FILE, CATALYSTS_FILE, SIMULATION_FILE)


def parse(text: str | bytes | None) -> dict[str, Any] | None:
    """The run file's content, or None when it is absent, not JSON, or another schema."""
    if text is None:
        return None
    try:
        data = json.loads(text)
    except ValueError:
        return None
    if not isinstance(data, dict) or data.get("schema") != RUN_SCHEMA:
        return None
    if not isinstance(data.get("cases"), dict):
        return None
    return data


def read(root: Path) -> dict[str, Any] | None:
    path = root / RUN_FILE
    return parse(path.read_bytes()) if path.is_file() else None


def entry_of(data: dict[str, Any] | None, case: str) -> dict[str, Any] | None:
    found = (data or {}).get("cases", {}).get(case)
    return found if isinstance(found, dict) else None


def write(root: Path, entry: dict[str, Any]) -> None:
    """Store *entry* as its case's, keeping the other cases."""
    data = read(root) or {"schema": RUN_SCHEMA, "kind": "simulation-run", "cases": {}}
    data["cases"][entry["case"]] = entry
    data["cases"] = dict(sorted(data["cases"].items()))
    path = root / RUN_FILE
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")


def excluded(process: Any, sim: Any) -> dict[str, str]:
    """Step or block id -> why the simulation leaves it out (``exclude:`` names it, or a block
    around it)."""
    left_out = list(sim.exclude)
    found: dict[str, str] = {}
    for name in left_out:
        found[name] = f"exclude: in {SIMULATION_FILE}"
    for node in [*process.flowsheet.steps, *process.flowsheet.blocks]:
        if node.id in found:
            continue
        around = next((x for x in left_out if x != node.id and process.within(node.id, x)), None)
        if around is not None:
            found[node.id] = f"inside {around}, excluded in {SIMULATION_FILE}"
    return found


def _quantity(value: Any, default_unit: str) -> dict[str, Any]:
    return {"value": value.value, "unit": value.unit or default_unit}


def stream_values(process: Any, new: dict[tuple[str, str], Any]) -> dict[str, dict[str, Any]]:
    """Stream id -> field -> the simulated value (with its unit; composition by basis)."""
    units = process.flowsheet.units
    defaults = {
        "temperature": units.temperature,
        "pressure": units.pressure,
        "flow": units.flow,
        "duty": units.duty,
    }
    out: dict[str, dict[str, Any]] = {}
    for (sid, name), value in new.items():
        if name == "composition":
            shown = {"basis": value.basis, "values": dict(value.values)}
        else:
            shown = _quantity(value, defaults.get(name, ""))
        out.setdefault(sid, {})[name] = shown
    return out


#: The note a specified split's row carries: its convergence is not a prediction.
SPECIFIED_NOTE = (
    "specified split: the simulator closed the balances around the given recoveries; "
    "convergence does not predict or validate the split"
)


def _basis_fields(unit: str | None, basis: dict[str, Any]) -> dict[str, Any]:
    """The ``basis`` keys of a unit row (none without a basis)."""
    if not basis.get("basis"):
        return {}
    fields: dict[str, Any] = {"basis": basis["basis"]}
    if basis.get("source"):
        fields["basis_source"] = basis["source"]
    if basis.get("operating_basis"):
        fields["operating_basis"] = basis["operating_basis"]
    if basis["basis"] == "specified" and unit == "component_separator":
        fields["note"] = SPECIFIED_NOTE
    return fields


def unit_rows(
    model: dict[str, Any],
    solved: dict[str, Any],
    converged: bool,
    messages: list[str],
    findings: list[Finding],
    left_out: dict[str, str],
    bases: dict[str, dict[str, Any]] | None = None,
    coupled: dict[str, Any] | None = None,
) -> list[dict[str, Any]]:
    """One row per unit of *model* (simulated) and per step or block left out (excluded).
    *bases* (:attr:`~.translate.Translation.bases`) add each unit's ``basis`` (with its
    ``basis_source`` and ``operating_basis`` where given); a specified split also gets a
    ``note`` that its convergence closes the balances around a given split and predicts
    nothing. ``coupling`` says how a unit took part in the DWSIM solve: ``native`` (a DWSIM
    unit) or ``external-unit`` (a kinetic reactor solved by cheme-as-code, :mod:`.coupling`;
    its ``outer_loop`` keeps the iterations, the residuals and the bed at the last inlet)."""
    coupled = coupled or {}
    rows: list[dict[str, Any]] = []
    for u in model.get("units", []):
        uid = u["id"]
        if u.get("internal"):
            continue
        named = [m for m in messages if m.startswith(f"{uid}:") or f" {uid}:" in m]
        basis = (bases or {}).get(uid) or {}
        rows.append(
            {
                "id": uid,
                "unit": u.get("type"),
                "status": "simulated",
                **_basis_fields(u.get("type"), basis),
                "converged": True if converged else (False if named else None),
                "results": {k: v for k, v in (solved.get(uid) or {}).items() if v is not None},
                "messages": named,
                "warnings": [
                    f.message for f in findings if uid in f.ids and f.level in ("warning", "error")
                ],
                "coupling": coupled[uid]["coupling"] if uid in coupled else "native",
                **({"outer_loop": coupled[uid]} if uid in coupled else {}),
            }
        )
    rows += [
        {"id": node, "status": "excluded", "reason": reason}
        for node, reason in sorted(left_out.items())
    ]
    return rows


def make_entry(
    *,
    root: Path,
    case: str,
    sim: Any,
    model: dict[str, Any],
    fingerprint: str,
    out: dict[str, Any],
    units: list[dict[str, Any]],
    streams: list[dict[str, Any]],
    findings: list[Finding],
    energy: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """The record entry of one finished run (see the module docstring), an adapter result
    (:class:`~chemeascode.foundation.schemas.run.AdapterResult`) in the file's own keys."""
    from chemeascode.foundation.provenance import source_revision
    from chemeascode.foundation.workspace import installed_version

    now = _dt.datetime.now(_dt.UTC).replace(microsecond=0)
    converged = bool(out.get("converged", False))
    entry = {
        "case": case,
        "run_at": now.isoformat().replace("+00:00", "Z"),
        "tool": "cheme-as-code " + ".".join(str(n) for n in installed_version()),
        "simulator": {
            "name": sim.simulator,
            "version": out.get("version"),
            "method": sim.property_package,
        },
        "property_package": sim.property_package,
        "model_fingerprint": fingerprint,
        "inputs": source_revision(root, RUN_INPUTS).as_dict(),
        "converged": converged,
        "status": "converged" if converged else "not-converged",
        "iterations": out.get("iterations"),
        "messages": list(out.get("messages") or []),
        "units": units,
        "streams": streams,
        "findings": [finding_dict(f) for f in findings],
    }
    if out.get("solver"):  # the IDAES backend: its numerical solver (IPOPT and version)
        entry["simulator"]["solver"] = out["solver"]
    if out.get("notes"):  # the IDAES backend: an initialization that did not finish
        entry["notes"] = list(out["notes"])
    if energy is not None:
        entry["energy"] = energy
    AdapterResult.model_validate(entry)  # the shared shape; the file keeps its own keys
    return entry


def staleness(
    entry: dict[str, Any] | None, current: str | None, fingerprints: dict[str, str]
) -> dict[str, Any]:
    """Whether *entry* still describes the inputs: *current* is the model fingerprint they
    translate to now (None: they do not translate), *fingerprints* the files as they are.
    ``stale`` is None without an entry, else True when the model fingerprints differ."""
    if entry is None:
        return {
            "stale": None,
            "model_fingerprint": None,
            "current_fingerprint": current,
            "changed_files": [],
        }
    recorded = (entry.get("inputs") or {}).get("fingerprints") or {}
    paths = sorted(set(recorded) | set(fingerprints))
    changed = [p for p in paths if recorded.get(p) != fingerprints.get(p)]
    return {
        "stale": entry.get("model_fingerprint") != current,
        "model_fingerprint": entry.get("model_fingerprint"),
        "current_fingerprint": current,
        "changed_files": changed,
    }


def view(
    process: Any,
    sim: Any,
    sim_doc: Any,
    data: dict[str, Any] | None,
    case: str | None,
    fingerprints: dict[str, str],
    problem: str = "",
) -> dict[str, Any]:
    """``GET /api/simulation`` without ``rev``: the parsed ``process/simulation.yaml``
    (``spec``), the record of *case* (``run``, None without one), whether it is stale, and one
    merged row per step or block (``units``). *process* is None when the flowsheet does not
    load (*problem* says why): the spec and the record are then shown, the staleness is None."""
    from chemeascode.domains.process.simulation.translate import translate

    findings: list[Finding] = []
    cases: list[str] = []
    current = None
    model_units: dict[str, dict[str, Any]] = {}
    bases: dict[str, dict[str, Any]] = {}
    left_out: dict[str, str] = {}
    if process is not None:
        cases = [c.id for c in process.flowsheet.cases]
        case = case or process.flowsheet.default_case()
        found = translate(process, sim, sim_doc, case)
        findings = found.findings
        bases = found.bases
        if found.model is not None:
            current = found.fingerprint
            model_units = {u["id"]: u for u in found.model["units"] if not u.get("internal")}
        left_out = excluded(process, sim)
    elif case is None:
        recorded = sorted((data or {}).get("cases", {}))
        case = recorded[0] if len(recorded) == 1 else None
    entry = entry_of(data, case) if case else None
    stale = staleness(entry, current, fingerprints)
    if process is None and entry is not None:
        stale["stale"] = None  # cannot tell: the inputs do not load
    ran = {u["id"]: u for u in (entry or {}).get("units", [])}
    specs = {
        k: v.model_dump(mode="json", by_alias=True, exclude_unset=True)
        for k, v in sim.specs.items()
    }
    # the flowsheet's order: every step, the blocks excluded or simulated as one unit, then
    # what only the spec or the record names
    ids: list[str] = []
    if process is not None:
        fs = process.flowsheet
        units_of = [*fs.steps, *(b for b in fs.blocks if not process.inside(b.id))]
        ids = [n.id for n in [*units_of, *fs.blocks] if n.id in model_units or n.id in left_out]
        ids += [n.id for n in units_of if n.id not in ids]
    ids += [i for i in [*specs, *ran] if i not in ids]
    units = []
    for uid in ids:
        if uid in left_out:
            status, reason = "excluded", left_out[uid]
        elif uid in model_units:
            status, reason = "simulated", ""
        elif process is None:
            status, reason = ran.get(uid, {}).get("status", "unknown"), ""
        else:
            refused = [f.message for f in findings if uid in f.ids and f.level == "error"]
            status = "refused" if refused else "not-simulated"
            if refused:
                reason = "; ".join(refused)
            elif uid not in process.nodes:
                reason = "not in the flowsheet"
            else:
                reason = "the simulator model was not made" if current is None else ""
        row = ran.get(uid) or {}
        units.append(
            {
                "id": uid,
                "unit": (model_units.get(uid) or {}).get("type") or row.get("unit"),
                "status": status,
                **_basis_fields(
                    (model_units.get(uid) or {}).get("type") or row.get("unit"),
                    bases.get(uid) or {"basis": row.get("basis")},
                ),
                "reason": reason,
                "spec": specs.get(uid),
                "run": row or None,
            }
        )
    return {
        "file": SIMULATION_FILE,
        "run_file": RUN_FILE,
        "case": case,
        "cases": cases,
        "spec": {
            "simulator": sim.simulator,
            "property_package": sim.property_package,
            "components": dict(sim.components),
            "tolerance": sim.tolerance.model_dump(mode="json"),
            "tear_streams": list(sim.tear_streams),
            "exclude": list(sim.exclude),
            "guesses": {
                k: v.model_dump(mode="json", by_alias=True, exclude_none=True)
                for k, v in sim.guesses.items()
            },
            "specs": specs,
        },
        "run": entry,
        "stale": stale.pop("stale"),
        "staleness": stale,
        "units": units,
        "problem": problem or None,
        "findings": [finding_dict(f) for f in findings],
    }
