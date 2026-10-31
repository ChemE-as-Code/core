"""The simulators ``cheme process simulate`` runs, and what each one takes (ADR 0038).

``process/simulation.yaml`` names its simulator (``simulator:``): ``dwsim`` (the default,
:mod:`chemeascode.integrations.dwsim`) or ``idaes`` (:mod:`chemeascode.integrations.idaes`, an
optional backend). Both take the same simulator model (:mod:`.translate`) and return results in
the same shape, so the fill, the check, the run record and the provenance are one path.

The IDAES backend is bounded: the units, property packages and compounds below, which its worker
(``integrations/idaes_worker.py``, ``UNITS`` and ``PACKAGES``) builds; a test keeps the two in
step. Everything else is refused at translation, with a finding, before any solver runs.
"""

from __future__ import annotations

from typing import Any

from chemeascode.domains.process.simulation import SIMULATION_FILE
from chemeascode.foundation.findings import Finding
from chemeascode.foundation.yamlsource import _yaml_line

DWSIM = "dwsim"
IDAES = "idaes"
#: The name a simulator has in the source of every value it simulates.
TITLES = {DWSIM: "DWSIM", IDAES: "IDAES"}

#: IDAES property package (simulation.yaml ``property_package``) -> the methods.yml method it
#: implements, its phases' equation of state, and the compounds it holds (CAS -> name). The
#: component data are those IDAES ships with its example packages (BT_ideal, BT_PR, HC_PR);
#: none of it is benchmarked by cheme-as-code, so no application range is claimed.
IDAES_PACKAGES: dict[str, dict[str, Any]] = {
    "IDAES ideal VLE": {
        "method": "IDEAL",
        "eos": "ideal",
        "compounds": {
            "71-43-2": "benzene",
            "108-88-3": "toluene",
            "1333-74-0": "hydrogen (vapour only)",
            "74-82-8": "methane (vapour only)",
        },
        "note": "Raoult's law and ideal gas; benzene and toluene from IDAES's BT_ideal data, "
        "hydrogen and methane (non-condensable) from its HC_PR data",
    },
    "IDAES Peng-Robinson": {
        "method": "PR",
        "eos": "PR",
        "compounds": {
            "71-43-2": "benzene",
            "108-88-3": "toluene",
            "1333-74-0": "hydrogen (vapour only)",
            "74-82-8": "methane (vapour only)",
        },
        "note": "Peng-Robinson with every kij 0 (IDAES's example data hold no other value); "
        "benzene and toluene from IDAES's BT_PR data, hydrogen and methane (non-condensable) "
        "from its HC_PR data",
    },
}
#: Unit kinds the IDAES worker builds, by the package's equation of state (an isentropic
#: compressor or expander needs entropies the ideal package's aromatics lack).
IDAES_UNITS = {
    "ideal": (
        "heater",
        "cooler",
        "valve",
        "pump",
        "mixer",
        "splitter",
        "flash",
        "conversion_reactor",
    ),
    "PR": (
        "heater",
        "cooler",
        "valve",
        "pump",
        "compressor",
        "expander",
        "mixer",
        "splitter",
        "flash",
        "conversion_reactor",
    ),
}
#: Reaction phases the IDAES reactor takes (one phase per reaction).
IDAES_REACTION_PHASES = ("vapor", "liquid")


def model_findings(model: dict[str, Any], sim: Any, sim_doc: Any) -> list[Finding]:
    """What the IDAES backend cannot run in the translated *model* (errors: the case is then
    refused): a unit kind it does not build, a reactor with two outlets, a reaction that is not a
    one-phase conversion, a compound the package does not hold, a saturation feed, interaction
    parameters."""
    found: list[Finding] = []
    package = IDAES_PACKAGES.get(sim.property_package)
    if package is None:
        return found  # property_package_findings refuses it already

    def add(message: str, loc: list[Any], ids: list[str], hint: str) -> None:
        found.append(
            Finding(
                SIMULATION_FILE,
                "error",
                "cheme.process-sim-backend-unsupported",
                message,
                line=_yaml_line(sim_doc, loc) if sim_doc is not None else None,
                ids=ids,
                hint=hint,
            )
        )

    units = IDAES_UNITS[package["eos"]]
    for u in model.get("units", []):
        uid, kind = u["id"], u["type"]
        where = ["specs", uid] if uid in sim.specs else ["simulator"]
        if kind not in units:
            add(
                f"{uid} ({kind}): the IDAES backend has no {kind} with {sim.property_package}",
                where,
                [uid],
                "simulate this flowsheet with simulator: dwsim, or exclude the step; the IDAES "
                f"backend builds {', '.join(units)}",
            )
            continue
        if kind == "conversion_reactor":
            if len(u["outlets"]) != 1:
                add(
                    f"{uid}: the IDAES reactor has one outlet (both phases); the step has "
                    f"{len(u['outlets'])}",
                    where,
                    [uid],
                    "give the reactor one outlet and a flash after it",
                )
            for r in u["spec"].get("reactions", []):
                if r.get("type") != "conversion" or r.get("phase") not in IDAES_REACTION_PHASES:
                    add(
                        f"{uid}: reaction {r['id']} ({r.get('type')}, phase {r.get('phase')}): "
                        "the IDAES backend takes conversion reactions in the vapour or the "
                        "liquid phase only",
                        where,
                        [uid, r["id"]],
                        "give the reaction phase: vapor or liquid",
                    )
        if kind in ("heater", "cooler") and len(u["outlets"]) != 1:
            add(
                f"{uid} ({kind}): the IDAES backend has no condensate outlet",
                where,
                [uid],
                "put a flash after the unit instead of its second outlet",
            )
        if kind == "flash" and len(u["inlets"]) != 1:
            add(
                f"{uid} (flash): the IDAES flash takes one inlet; the step has {len(u['inlets'])}",
                where,
                [uid],
                "mix the inlets in a mixer step before the flash",
            )
        if kind == "compressor" and "stages" in u["spec"]:
            add(
                f"{uid} (compressor): the IDAES backend has no intercooled compressor",
                where,
                [uid],
                "model the stages as compressors and coolers, or simulate with dwsim",
            )
    for c in model.get("compounds", []):
        if c["cas"] not in package["compounds"]:
            add(
                f"compound {c['id']} (CAS {c['cas']}) is not in {sim.property_package}, which "
                "holds " + ", ".join(package["compounds"].values()),
                ["property_package"],
                [c["id"]],
                "simulate with simulator: dwsim, or leave the compound out",
            )
    for s in model.get("streams", []):
        feed = s.get("feed") or {}
        if feed.get("vapor_fraction") is not None:
            add(
                f"feed {s['id']}: a saturation state (vapour fraction); the IDAES backend takes "
                "temperature and pressure",
                ["simulator"],
                [s["id"]],
                "give the feed's temperature",
            )
    if model.get("interaction_parameters"):
        add(
            "interaction_parameters: the IDAES backend does not take them",
            ["interaction_parameters"],
            [],
            "remove them, or simulate with simulator: dwsim",
        )
    return found
