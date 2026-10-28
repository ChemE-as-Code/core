"""The liquid of a process's liquid-phase reactions (:class:`.chemistry.liquid.Liquid`): the
components' liquid molar volumes and the activity model ``process/reactions.yaml`` names."""

from __future__ import annotations

from typing import Any

from chemeascode.domains.chemistry.liquid import Liquid, ideal_model, unifac_model


def liquid_of(process: Any) -> Liquid:
    """The :class:`Liquid` of *process*: ``liquid_molar_volume`` of each component, and UNIFAC
    on the components' CAS numbers (``activity_model: ideal``: activity coefficients of 1)."""
    comps = process.components()
    model = getattr(process.reactions, "activity_model", "unifac")
    activity = (
        ideal_model if model == "ideal" else unifac_model({n: c.cas for n, c in comps.items()})
    )
    return Liquid({n: c.liquid_molar_volume for n, c in comps.items()}, activity)


def inputs_of(process: Any, names: list[str], bases: list[str]) -> dict[str, Any]:
    """What a liquid-phase result on *bases* depends on beyond the streams, for its
    fingerprint: the activity model and CAS numbers on an activity basis, the molar volumes on
    a concentration basis (nothing else, so an unused input marks nothing stale)."""
    comps = process.components()
    found: dict[str, Any] = {}
    if "activity" in bases:
        found["activity_model"] = getattr(process.reactions, "activity_model", "unifac")
        found["cas"] = {n: getattr(comps.get(n), "cas", "") for n in names}
    if "concentration" in bases:
        found["liquid_molar_volume"] = {
            n: getattr(comps.get(n), "liquid_molar_volume", None) for n in names
        }
    return found
