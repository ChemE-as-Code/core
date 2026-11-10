"""Read-only wastewater columns, separate from molecular stream states and balances."""

from copy import deepcopy
from math import isfinite

from chemeascode.domains.process.simulation.record import RUN_FILE

COLUMNS = (
    ("flow", "Flow", "m3/day", "Liquid volumetric flow"),
    ("COD", "COD", "mg COD/L", "Chemical oxygen demand"),
    ("TN", "TN", "mg N/L", "Total nitrogen, expressed as N"),
    ("TP", "TP", "mg P/L", "Total phosphorus, expressed as P"),
    ("TSS", "TSS", "mg TSS/L", "Total suspended solids"),
    ("NH4", "NH4-N", "mg N/L", "Ammonium nitrogen, expressed as N"),
    ("PO4", "PO4-P", "mg P/L", "Orthophosphate phosphorus, expressed as P"),
)


def stream_table(table: dict, simulation: dict) -> dict:
    """Join a saved QSDsan case by stream id without changing any molecular value.

    The caller supplies the same snapshot's simulation view (including input staleness).
    Invalid or absent cells stay absent, never zero. Units are checked, never converted.
    This is a final-time result projection, not a steady-state or conservation check.
    """
    if simulation.get("spec", {}).get("simulator") != "qsdsan":
        return table
    result = deepcopy(table)
    meta = result["wastewater"] = {
        "status": "missing",
        "case": table["case"],
        "run_file": RUN_FILE,
        "run_at": None,
        "evidence": None,
        "stale": simulation.get("stale"),
        "changed_files": simulation.get("staleness", {}).get("changed_files", []),
        "columns": [
            {"key": key, "label": label, "unit": unit, "basis": basis}
            for key, label, unit, basis in COLUMNS
        ],
        "findings": [],
    }
    for row in result["streams"]:
        row["wastewater"] = {}

    def finding(message: str) -> None:
        meta["findings"].append(
            {
                "file": RUN_FILE,
                "line": None,
                "level": "warning",
                "rule": "cheme.process-wastewater-record",
                "message": message,
                "hint": "Inspect the saved run; missing cells are not zero. "
                "Record a new run with cheme process simulate --fill when appropriate.",
            }
        )

    if simulation.get("problem"):
        meta["status"] = "invalid"
        finding(simulation["problem"])
        return result
    run = simulation.get("run")
    if run is None:
        finding(f"No saved wastewater run for case {table['case']}.")
        return result
    solver = run.get("simulator") or run.get("solver") or {}
    if (
        simulation.get("case") != table["case"]
        or run.get("case") != table["case"]
        or str(solver.get("name", "")).lower() != "qsdsan"
    ):
        meta["status"] = "invalid"
        finding("The saved run does not match the selected case and QSDsan simulator.")
        return result
    meta.update(run_at=run.get("run_at"), evidence=run.get("evidence"))
    if run.get("status") != "converged" or run.get("integration_completed") is False:
        meta["status"] = "failed"
        finding("The saved run did not complete successfully; no values are displayed.")
        return result
    records = run.get("streams")
    if not isinstance(records, list):
        meta["status"] = "invalid"
        finding("The saved run has no stream list.")
        return result
    indexed = {}
    for stream in records:
        if not isinstance(stream, dict) or not isinstance(stream.get("id"), str):
            meta["status"] = "invalid"
            finding("The saved run contains an invalid stream id.")
            return result
        if stream["id"] in indexed:
            meta["status"] = "invalid"
            finding(f"Duplicate saved stream id: {stream['id']}.")
            return result
        indexed[stream["id"]] = stream
    meta["status"] = "available"
    for row in result["streams"]:
        if row["kind"] != "material":
            continue
        saved = indexed.get(row["id"], {})
        values = saved.get("values")
        if not isinstance(values, dict):
            finding(f"No wastewater values for stream {row['id']}.")
            continue
        missing = []
        for key, _, unit, basis in COLUMNS:
            cell = values.get(key)
            number = cell.get("value") if isinstance(cell, dict) else None
            if type(number) not in (float, int) or not isfinite(number) or cell.get("unit") != unit:
                missing.append(f"{key} (expected {unit})")
                continue
            row["wastewater"][key] = {
                "value": number,
                "unit": unit,
                "basis": basis,
                "provenance": "calculated",
                "source": f"{RUN_FILE}: case {table['case']}, stream {row['id']}, {key}",
                "stale": meta["stale"] is True,
            }
        if missing:
            finding(f"Missing or invalid {row['id']} values: {', '.join(missing)}.")
        if row["wastewater"] and meta["stale"] is True:
            row["stale"] = list(dict.fromkeys([*row["stale"], "wastewater"]))
    unknown = sorted(set(indexed) - {row["id"] for row in result["streams"]})
    if unknown:
        finding(f"Saved streams absent from the current flowsheet: {', '.join(unknown)}.")
    if meta["findings"]:
        meta["status"] = "partial"
    return result
