"""Conversion reactors: the conversion DWSIM reached against the declared one
(pre-release issue 371).

DWSIM 9.0.5's conversion reactor applies a reaction's conversion to its key component in the
reaction's phase of the reactor inlet only: ``phase: liquid`` converts the key in the inlet's
liquid, ``vapor`` in its vapour, ``mixed`` (DWSIM's ``Mixture``) in the whole inlet. An inlet
the property package splits into two phases therefore reaches less than the declared
conversion, and DWSIM says nothing: Peng-Robinson and SRK split isobutene and methanol at 298 K
and 2000 kPa(a) into a "vapour" far above both vapour pressures, and the liquid-phase MTBE
reactor then converts 81.5 % (SRK) instead of the declared 100 %
(tests/test_process_simulate_energy_liquid.py). The worker gives every reaction of a reactor
one rank, so DWSIM converts each key's inlet flow in parallel, as ``cheme process propagate``
does (checked live, tests/test_process_simulate_reactors.py, parallel conversions).

After a converged run :func:`achieved` takes each conversion reactor's inlet and outlet
component flows from DWSIM's streams: the change of each key component against the change the
declared conversions give on the whole inlet, and the reactions' extents and conversions where
the stoichiometry makes them identifiable (the worker returns no extents for a conversion
reactor). :func:`findings` reports a key conversion off the declared one by more than
:data:`TOLERANCE` as ``cheme.process-sim-conversion-mismatch``, an error: the stream values
then follow a different reactor than the one declared.
"""

from __future__ import annotations

from typing import Any

from chemeascode.domains.process.simulation import SIMULATION_FILE
from chemeascode.foundation.findings import Finding
from chemeascode.foundation.yamlsource import _yaml_line

RULE = "cheme.process-sim-conversion-mismatch"
#: Achieved minus declared conversion of a key component (fraction of its inlet flow) beyond
#: which the reactor is reported. DWSIM applies a conversion directly, without iteration: on a
#: one-phase inlet the recorded MTBE run reproduces the declared conversion within 1e-8, so
#: 1e-3 (0.1 percentage point) is far above the numerical noise, below the smallest phase-split
#: shortfall observed (PR78: 0.15 %), and finer than a declared conversion is usually known.
TOLERANCE = 1e-3
#: A key whose inlet flow is below this fraction of the reactor's inlet is not compared: its
#: conversion is not defined by the flows (DWSIM converts nothing of nothing).
TRACE = 1e-12


def _flows(stream: dict[str, Any] | None) -> dict[str, float] | None:
    """kmol/h by component of a solved stream, None without its molar flow."""
    if not stream or stream.get("molar_flow_mol_s") is None:
        return None
    total = stream["molar_flow_mol_s"] * 3.6
    return {n: (y or 0.0) * total for n, y in (stream.get("mole_fractions") or {}).items()}


def _rank(rows: list[list[float]]) -> int:
    """The rank of a small matrix, Gaussian elimination with partial pivoting."""
    rows = [list(r) for r in rows]
    rank = 0
    for col in range(len(rows[0]) if rows else 0):
        best = max(range(rank, len(rows)), key=lambda r: abs(rows[r][col]), default=None)
        if best is None or abs(rows[best][col]) < 1e-12:
            continue
        rows[rank], rows[best] = rows[best], rows[rank]
        for r in range(rank + 1, len(rows)):
            f = rows[r][col] / rows[rank][col]
            rows[r] = [v - f * w for v, w in zip(rows[r], rows[rank], strict=True)]
        rank += 1
    return rank


def _extents(reactions: list[dict[str, Any]], change: dict[str, float]) -> dict[str, float]:
    """The extents (kmol/h) that explain *change* by least squares; the reactions are
    independent (:func:`_rank`)."""
    from types import SimpleNamespace

    from chemeascode.domains.chemistry.reactions import fit_extents

    fitted, _ = fit_extents(
        [SimpleNamespace(id=r["id"], stoichiometry=r["stoichiometry"]) for r in reactions],
        change,
    )
    return fitted


def achieved(
    model: dict[str, Any], out: dict[str, Any], skip: set[str] | None = None
) -> dict[str, dict[str, Any]]:
    """By conversion reactor of *model* solved in *out*: ``keys`` (key component ->
    ``declared``, ``achieved`` conversion, the reactions converting it and their phases),
    ``inlet`` and ``inlet_vapor_fraction``, and where the reactions are independent their
    ``extents_kmol_h`` and achieved ``conversions``. Reactors in *skip*, or whose streams are
    not all in *out*, are left out."""
    streams = out.get("streams") or {}
    result: dict[str, dict[str, Any]] = {}
    for u in model.get("units", []):
        reactions = u.get("spec", {}).get("reactions") or []
        if u["type"] != "conversion_reactor" or u["id"] in (skip or set()) or not reactions:
            continue
        if any(r.get("type") != "conversion" for r in reactions) or len(u["inlets"]) != 1:
            continue
        inlet = _flows(streams.get(u["inlets"][0]))
        outlets = [_flows(streams.get(s)) for s in u["outlets"]]
        if inlet is None or any(o is None for o in outlets):
            continue
        names = sorted({*inlet, *(n for o in outlets for n in o or {})})
        outlet = {n: sum((o or {}).get(n, 0.0) for o in outlets) for n in names}
        total = sum(inlet.values())
        if total <= 0:
            continue
        # the declared extents: each conversion of its key's whole inlet flow, in parallel
        declared = {
            r["id"]: r["conversion"]
            * inlet.get(r["base"], 0.0)
            / abs(r["stoichiometry"][r["base"]])
            for r in reactions
        }
        keys: dict[str, dict[str, Any]] = {}
        for r in reactions:
            key = r["base"]
            fed = inlet.get(key, 0.0)
            if fed <= TRACE * total:
                continue
            entry = keys.setdefault(key, {"reactions": [], "phases": []})
            entry["reactions"].append(r["id"])
            if r["phase"] not in entry["phases"]:
                entry["phases"].append(r["phase"])
        for key, entry in keys.items():
            fed = inlet[key]
            used = -sum(r["stoichiometry"].get(key, 0.0) * declared[r["id"]] for r in reactions)
            entry["declared"] = used / fed
            entry["achieved"] = (fed - outlet.get(key, 0.0)) / fed
        info: dict[str, Any] = {
            "inlet": u["inlets"][0],
            "inlet_vapor_fraction": streams[u["inlets"][0]].get("vapor_fraction"),
            "keys": keys,
        }
        matrix = [[r["stoichiometry"].get(n, 0.0) for n in names] for r in reactions]
        if _rank(matrix) == len(reactions):
            change = {n: outlet[n] - inlet.get(n, 0.0) for n in names}
            extents = _extents(reactions, change)
            info["extents_kmol_h"] = extents
            info["conversions"] = {
                r["id"]: extents[r["id"]] * abs(r["stoichiometry"][r["base"]]) / inlet[r["base"]]
                for r in reactions
                if inlet.get(r["base"], 0.0) > TRACE * total
            }
        result[u["id"]] = info
    return result


def findings(checked: dict[str, dict[str, Any]], sim_doc: Any) -> list[Finding]:
    """A reactor whose key conversion is off the declared one beyond :data:`TOLERANCE`."""
    found = []
    for uid, info in checked.items():
        for key, entry in info["keys"].items():
            off = entry["achieved"] - entry["declared"]
            if abs(off) <= TOLERANCE:
                continue
            ids = ", ".join(entry["reactions"])
            split = info["inlet_vapor_fraction"]
            two_phase = split is not None and 0.0 < split < 1.0
            state = (
                f"; its inlet {info['inlet']} is {split:.4g} vapour (mole fraction)"
                if split is not None
                else ""
            )
            phased = "/".join(p for p in entry["phases"] if p in ("liquid", "vapor"))
            if phased:
                hint = (
                    f"DWSIM converts a {phased}-phase reaction's key in the inlet's {phased} "
                    + (
                        f"only: bring the inlet of {uid} to one phase (its temperature or "
                        "pressure ahead of the reactor)"
                        if two_phase
                        else f"only: check that the inlet of {uid} is in that phase"
                    )
                    + f", or declare reaction {ids} phase: mixed in process/reactions.yaml "
                    "(converted on the whole inlet); a co-reactant running out before the key "
                    "also falls short"
                )
            else:
                hint = (
                    "check that the declared conversions are feasible together: a co-reactant "
                    "may run out before the key"
                )
            found.append(
                Finding(
                    SIMULATION_FILE,
                    "error",
                    RULE,
                    f"{uid}: DWSIM converted {entry['achieved']:.6g} of {key} (reaction {ids}), "
                    f"{entry['declared']:.6g} declared ({off:+.3g}, tolerance {TOLERANCE:g})"
                    + state
                    + ": the simulated streams do not follow the declared conversion",
                    line=_yaml_line(sim_doc, ["specs", uid]),
                    ids=[uid],
                    hint=hint,
                )
            )
    return found
