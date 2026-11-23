"""Review a snapshot of one continuous activated-sludge waterline."""

from __future__ import annotations

import math
from typing import Any


class Unavailable(ValueError):
    """A dependency is missing, invalid, or inconsistent."""


def _object(obj, key, path):
    value = obj.get(key, {})
    if not isinstance(value, dict):
        raise Unavailable(f"{path} must be an object")
    return value


def _number(obj, key, path, *, positive=False):
    value = obj.get(key)
    if value is None:
        raise Unavailable(f"Missing {path}")
    if (
        type(value) not in (int, float)
        or abs(value) > 1e308
        or not math.isfinite(value)
        or value < 0
        or (positive and value == 0)
    ):
        limit = "positive" if positive else "nonnegative"
        raise Unavailable(f"{path} must be finite and {limit}")
    return value


def _balance(inlet, *outlets):
    try:
        incoming, outgoing = inlet(), sum(outlet() for outlet in outlets)
        difference = incoming - outgoing
        if not math.isfinite(difference):
            raise Unavailable("Water balance exceeds the finite numeric range")
    except Unavailable as error:
        return {"status": "not-evaluable", "reason": str(error)}
    ok = math.isclose(incoming, outgoing, rel_tol=1e-8, abs_tol=1e-6)
    return {"status": "closed" if ok else "inconsistent", "residual_m3_d": difference}


def _tanks(case):
    tanks = case.get("tanks")
    if tanks is None or tanks == []:
        raise Unavailable("Missing biological tank list")
    if not isinstance(tanks, list) or not all(isinstance(tank, dict) for tank in tanks):
        raise Unavailable("tanks must be a list of tank objects")
    ids = [tank.get("id") for tank in tanks]
    if any(not isinstance(key, str) or not key.strip() for key in ids):
        raise Unavailable("Each biological tank needs a nonempty id")
    if len(set(ids)) != len(ids):
        raise Unavailable("Duplicate biological tank id")
    return tanks


def review(case: dict[str, Any]) -> dict[str, Any]:
    """Return supported metrics and reasons for deferring the others.

    This boundary has one influent, an effluent, and wasting from the
    clarifier underflow. RAS and internal recycle stay inside the waterline.
    Clarifier inventory uses an equal-volume layer profile. Missing balance
    inputs are reported separately from missing metric dependencies.
    """
    if not isinstance(case, dict):
        raise ValueError("Expected one JSON object describing the waterline")

    values, deferred = {}, {}

    def emit(key, unit, compute):
        try:
            value = compute()
            if not math.isfinite(value):
                raise Unavailable("Calculation exceeds the finite numeric range")
        except Unavailable as error:
            deferred[key] = {"unit": unit, "reason": str(error)}
        else:
            values[key] = {"value": value, "unit": unit}

    def measure(stream, key, *, positive=False):
        streams = _object(case, "streams", "streams")
        return _number(
            _object(streams, stream, f"streams.{stream}"),
            key,
            f"streams.{stream}.{key}",
            positive=positive,
        )

    def influent():
        return measure("INFLUENT", "flow_m3_d", positive=True)

    def flow(stream):
        return measure(stream, "flow_m3_d")

    external = _balance(influent, lambda: flow("EFFLUENT"), lambda: flow("WAS"))
    settler = _balance(
        lambda: flow("TO_CLARIFIER"),
        lambda: flow("EFFLUENT"),
        lambda: flow("WAS"),
        lambda: flow("RAS"),
    )

    def require_consistent(check, boundary):
        if check["status"] == "inconsistent":
            raise Unavailable(
                f"{boundary} water balance does not close ({check['residual_m3_d']:g} m3/day)"
            )

    def volume(tank):
        return _number(tank, "volume_m3", f"tanks.{tank['id']}.volume_m3", positive=True)

    def tank_mass(tank):
        mlss = _number(tank, "mlss_mg_L", f"tanks.{tank['id']}.mlss_mg_L")
        return volume(tank) * mlss / 1000

    def biological_volume():
        return sum(volume(tank) for tank in _tanks(case))

    def biological_mass():
        return sum(tank_mass(tank) for tank in _tanks(case))

    def clarifier_value(key):
        return _number(
            _object(case, "clarifier", "clarifier"), key, f"clarifier.{key}", positive=True
        )

    def clarifier_mass():
        clarifier = _object(case, "clarifier", "clarifier")
        count = clarifier.get("n_layers")
        layers = clarifier.get("layer_tss_mg_L")
        if (
            not isinstance(layers, list)
            or type(count) is not int
            or count < 1
            or len(layers) != count
        ):
            raise Unavailable(
                "Need clarifier.n_layers and a complete equal-volume "
                "clarifier.layer_tss_mg_L profile"
            )
        tss = sum(
            _number({"value": x}, "value", f"clarifier.layer_tss_mg_L[{i}]")
            for i, x in enumerate(layers)
        )
        return clarifier_value("area_m2") * clarifier_value("height_m") * (tss / count) / 1000

    def solids_rate(stream):
        return flow(stream) * measure(stream, "tss_mg_L") / 1000

    def total_mass():
        return biological_mass() + clarifier_mass()

    def loss():
        return solids_rate("WAS") + solids_rate("EFFLUENT")

    def srt(mass):
        require_consistent(external, "External")
        outside = loss()
        if outside == 0:
            raise Unavailable("TSS SRT is undefined at zero external TSS loss")
        return mass() / outside

    def feed():
        require_consistent(settler, "Clarifier")
        return flow("TO_CLARIFIER")

    def feed_mass():
        return feed() * measure("TO_CLARIFIER", "tss_mg_L") / 1000

    emit("biological_volume_m3", "m3", biological_volume)
    emit("nominal_bio_hrt_h", "h", lambda: 24 * biological_volume() / influent())
    try:
        tanks = _tanks(case)
    except Unavailable as error:
        deferred["zone_nominal_hrt_h"] = {"unit": "h", "reason": str(error)}
    else:
        zones = {}
        for tank in tanks:
            emit(f"tank_inventory_kg_TSS.{tank['id']}", "kg TSS", lambda tank=tank: tank_mass(tank))
            zone = tank.get("zone")
            if isinstance(zone, str) and zone.strip():
                zones.setdefault(zone, []).append(tank)
        if sum(map(len, zones.values())) != len(tanks):
            deferred["zone_nominal_hrt_h"] = {
                "unit": "h",
                "reason": "Each biological tank needs an assigned zone for zone HRT",
            }
        for zone, group in zones.items():
            if "zone_nominal_hrt_h" not in deferred:
                emit(
                    f"zone_nominal_hrt_h.{zone}",
                    "h",
                    lambda group=group: 24 * sum(map(volume, group)) / influent(),
                )

    emit("bioreactor_inventory_kg_TSS", "kg TSS", biological_mass)
    emit("clarifier_inventory_kg_TSS", "kg TSS", clarifier_mass)
    emit("total_inventory_kg_TSS", "kg TSS", total_mass)
    emit("was_loss_kg_TSS_d", "kg TSS/day", lambda: solids_rate("WAS"))
    emit("effluent_loss_kg_TSS_d", "kg TSS/day", lambda: solids_rate("EFFLUENT"))
    emit("total_loss_kg_TSS_d", "kg TSS/day", loss)
    emit("reactor_only_tss_srt_d", "day", lambda: srt(biological_mass))
    emit("system_tss_srt_d", "day", lambda: srt(total_mass))
    emit(
        "effluent_overflow_m3_m2_d",
        "m3/(m2 day)",
        lambda: flow("EFFLUENT") / clarifier_value("area_m2"),
    )
    emit(
        "plant_influent_per_area_m3_m2_d",
        "m3/(m2 day)",
        lambda: influent() / clarifier_value("area_m2"),
    )
    emit(
        "clarifier_feed_per_area_m3_m2_d",
        "m3/(m2 day)",
        lambda: feed() / clarifier_value("area_m2"),
    )
    emit("clarifier_feed_kg_TSS_d", "kg TSS/day", feed_mass)
    emit(
        "clarifier_solids_loading_kg_TSS_m2_d",
        "kg TSS/(m2 day)",
        lambda: feed_mass() / clarifier_value("area_m2"),
    )

    return {
        "calculated": values,
        "deferred": deferred,
        "water_balances": {"external": external, "clarifier": settler},
    }
