"""Clients for the GRAPPA and HANNA property-prediction services.

The services (FastAPI apps with their model weights) stay in LLM4ChemE (``services/grappa_service``
and ``services/hanna_service``) and run from there, e.g. ``docker compose up -d grappa-api
hanna-api`` in an LLM4ChemE checkout. ``cheme-as-code`` holds only these clients, and every call
takes the service's base URL explicitly: nothing defaults to localhost, nothing is read from the
environment.

GRAPPA predicts pure-component vapour pressure, Antoine parameters and boiling points from SMILES;
its Antoine form is ``ln(p/kPa) = A - B/(T/K + C)``. HANNA predicts activity coefficients of a
binary mixture.
"""

from __future__ import annotations

from typing import Any

from chemeascode.integrations.http import HttpClient

GRAPPA_ANTOINE_FORM = "ln(p/kPa) = A - B/(T/K + C)"


def _check_smiles(smiles: list[str]) -> None:
    if not smiles or not all(isinstance(s, str) and s.strip() for s in smiles):
        raise ValueError("smiles must be a non-empty list of non-empty SMILES strings")


def _check_positive(values: list[float], what: str) -> None:
    if not values or not all(isinstance(v, int | float) and v > 0 for v in values):
        raise ValueError(f"{what} must be a non-empty list of positive numbers")


def _predictions(response: Any) -> list[dict[str, Any]]:
    if not isinstance(response, list) or not all(isinstance(e, dict) for e in response):
        raise ValueError(f"unexpected GRAPPA response: {response!r}")
    return response


def grappa_vapor_pressure(
    endpoint: str,
    smiles: list[str],
    temperatures_K: list[float],
    *,
    client: HttpClient | None = None,
) -> list[dict[str, Any]]:
    """One entry per SMILES, e.g. ``{"smiles": "CCO", "temperature_K": 298.15,
    "vapor_pressure_kPa": 7.9}``."""
    _check_smiles(smiles)
    _check_positive(temperatures_K, "temperatures_K")
    if len(smiles) != len(temperatures_K):
        raise ValueError("give one temperature per SMILES")
    client = client or HttpClient()
    payload = {"smiles": smiles, "temperatures": temperatures_K}
    url = endpoint.rstrip("/") + "/predict/vapor-pressure"
    return _predictions(client.post_json(url, payload).json())


def grappa_antoine_parameters(
    endpoint: str, smiles: list[str], *, client: HttpClient | None = None
) -> list[dict[str, Any]]:
    """One entry per SMILES with ``antoine_A``, ``antoine_B``, ``antoine_C`` in
    :data:`GRAPPA_ANTOINE_FORM`."""
    _check_smiles(smiles)
    client = client or HttpClient()
    url = endpoint.rstrip("/") + "/predict/antoine-parameters"
    return _predictions(client.post_json(url, {"smiles": smiles}).json())


def grappa_boiling_point(
    endpoint: str,
    smiles: list[str],
    pressures_kPa: list[float] | None = None,
    *,
    client: HttpClient | None = None,
) -> list[dict[str, Any]]:
    """One entry per SMILES with ``boiling_point_K``; the service's default pressure is
    101.325 kPa."""
    _check_smiles(smiles)
    payload: dict[str, Any] = {"smiles": smiles}
    if pressures_kPa is not None:
        _check_positive(pressures_kPa, "pressures_kPa")
        if len(pressures_kPa) != len(smiles):
            raise ValueError("give one pressure per SMILES")
        payload["pressures"] = pressures_kPa
    client = client or HttpClient()
    url = endpoint.rstrip("/") + "/predict/boiling-point"
    return _predictions(client.post_json(url, payload).json())


def hanna_activity_coefficients(
    endpoint: str,
    smiles1: str,
    smiles2: str,
    temperature_K: float,
    x1: float | list[float],
    *,
    client: HttpClient | None = None,
) -> dict[str, Any]:
    """``{"activity_coefficients": [gamma_1, gamma_2] (or what the service returns for a list
    of x1), "raw_response": ...}`` for the binary mixture at *temperature_K* and mole fraction
    *x1* of component 1."""
    _check_smiles([smiles1, smiles2])
    if temperature_K <= 0:
        raise ValueError("temperature_K must be positive")
    fractions = x1 if isinstance(x1, list) else [x1]
    if not fractions or not all(0 <= x <= 1 for x in fractions):
        raise ValueError("x1 must lie between 0 and 1")
    client = client or HttpClient()
    payload = {"smiles1": smiles1, "smiles2": smiles2, "temperature": temperature_K, "x1": x1}
    raw = client.post_json(endpoint.rstrip("/") + "/activity_coeff", payload).json()
    if "gamma_1" in raw and "gamma_2" in raw:
        coefficients: Any = [raw["gamma_1"], raw["gamma_2"]]
    else:
        key = next(
            (
                k
                for k in ("activity_coefficients", "activity_coeffs", "results", "data")
                if k in raw
            ),
            None,
        )
        coefficients = raw[key] if key else None
    return {"activity_coefficients": coefficients, "raw_response": raw}
