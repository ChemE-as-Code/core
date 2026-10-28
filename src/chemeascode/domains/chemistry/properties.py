"""Pure-component and binary-mixture properties from several sources, one call.

Each property has a source order (:data:`SOURCE_ORDER`): the first source that gives a value
wins, and the result names it. Sources are PubChem (identifiers), the NIST WebBook
(thermochemistry, Antoine parameters), OSHA (hazard data, by CAS number: a name is resolved
to its CAS number through the ``cas`` sources first), the ``thermo`` package (local
correlations, extra ``props``) and, only when the caller gives its endpoint, the GRAPPA
prediction service as the last resort. Binary properties: HANNA activity coefficients (endpoint
needed), relative volatility and boiling-point difference, derived from the pure-component values.

Network access happens only in the adapters of :mod:`chemeascode.integrations`; a test passes
``fetchers`` and never touches the network. Values keep the units of their source; the
derived properties convert through :mod:`chemeascode.foundation.units`.
"""

from __future__ import annotations

import math
from collections.abc import Callable
from dataclasses import dataclass, field
from enum import StrEnum
from typing import Any

from chemeascode.foundation.schema_base import CAS_RE
from chemeascode.foundation.units import UnitError, convert_units
from chemeascode.integrations.http import HttpClient, HttpError


class Source(StrEnum):
    PUBCHEM = "PubChem"
    NIST = "NIST"
    OSHA = "OSHA"
    THERMO = "Thermo"
    GRAPPA = "GRAPPA"
    HANNA = "HANNA"
    DERIVED = "Derived"


#: Every Antoine value this module returns is in this form, the NIST WebBook's.
ANTOINE_FORM = "log10(P/bar) = A - B/(T/K + C)"
GRAPPA_ANTOINE_FORM = "ln(p/kPa) = A - B/(T/K + C)"
#: GRAPPA is asked for the normal boiling point, like NIST (Tboil) and thermo (Tb).
NORMAL_BOILING_PRESSURE_KPA = 101.325

_IDENTITY = [Source.PUBCHEM, Source.THERMO, Source.NIST]
_NIST_THEN_THERMO = [Source.NIST, Source.THERMO]
_ANTOINE = ("antoine_parameters", "antoine_a", "antoine_b", "antoine_c")
_OSHA_FIELDS = (
    "nfpa_health_rating",
    "nfpa_fire_rating",
    "nfpa_reactivity_rating",
    "lower_explosive_limit",
    "upper_explosive_limit",
    "vapor_density",
    "specific_gravity",
    "osha_twa",
    "niosh_twa",
    "acgih_twa",
    "cal_osha_twa",
    "osha_stel",
    "niosh_stel",
    "acgih_stel",
    "cal_osha_stel",
    "idlh",
)
_NIST_ONLY = (
    "enthalpy_formation_gas",
    "enthalpy_combustion_gas",
    "entropy_gas",
    "heat_capacity_shomate_equation_gas",
    "enthalpy_formation_liquid",
    "enthalpy_combustion_liquid",
    "entropy_liquid",
    "heat_capacity_shomate_equation_liquid",
    "temperature_triple",
    "pressure_triple",
    "volume_critical",
    "density_critical",
    "enthalpy_vaporization_values",
)
_THERMO_ONLY = ("heat_of_vaporization", "heat_of_fusion", "viscosity", "flash_point")
_THERMO_ONLY += ("cp_ideal_gas", "cp_liquid", "cp_solid")

#: Property -> sources in the order they are asked.
SOURCE_ORDER: dict[str, list[Source]] = {
    "name": _IDENTITY,
    "formula": _IDENTITY,
    "molecular_weight": _IDENTITY,
    "cas": [Source.PUBCHEM, Source.NIST],
    "smiles": [Source.PUBCHEM],
    "inchi": [Source.PUBCHEM, Source.NIST],
    "inchikey": [Source.PUBCHEM, Source.NIST],
    "temperature_boil": [*_NIST_THEN_THERMO, Source.GRAPPA],
    "vapor_pressure": [*_NIST_THEN_THERMO, Source.GRAPPA],
    "temperature_critical": _NIST_THEN_THERMO,
    "pressure_critical": _NIST_THEN_THERMO,
    "temperature_fusion": _NIST_THEN_THERMO,
    "enthalpy_vaporization_average": [Source.NIST, Source.THERMO],
    **{name: [Source.NIST, Source.GRAPPA] for name in _ANTOINE},
    **{name: [Source.THERMO] for name in _THERMO_ONLY},
    **{name: [Source.OSHA] for name in _OSHA_FIELDS},
    **{name: [Source.NIST] for name in _NIST_ONLY},
}
#: Binary properties of :meth:`PropertyRetriever.mixture`.
MIXTURE_PROPERTIES = ("activity_coefficient", "relative_volatility", "boiling_point_difference")

_PUBCHEM_FIELDS = {
    "name": "iupac_name",
    "molecular_weight": "molecular_weight",
    "formula": "molecular_formula",
    "smiles": "canonical_smiles",
    "inchi": "inchi",
    "inchikey": "inchi_key",
    "cas": "cas_rn",
}
_NIST_FIELDS = {"inchi": "iupac_std_inchi", "inchikey": "iupac_std_inchikey"}
_THERMO_FIELDS = {
    "temperature_boil": "boiling_point",
    "temperature_critical": "critical_temperature",
    "pressure_critical": "critical_pressure",
    "temperature_fusion": "melting_point",
    "enthalpy_vaporization_average": "heat_of_vaporization",
    "viscosity": "liquid_viscosity",
    "molecular_weight": "molar_mass_g_mol",
}


@dataclass(frozen=True)
class PropertyResult:
    """One property of one component (or pair). ``value`` is None when no source gave it, and
    ``error`` says why. ``metadata`` carries the source URL, the method, or the inputs of a
    derived value."""

    component: str
    property: str
    value: Any = None
    units: str | None = None
    source: str | None = None
    error: str | None = None
    metadata: dict[str, Any] = field(default_factory=dict)

    @property
    def ok(self) -> bool:
        return self.value is not None

    def to_dict(self) -> dict[str, Any]:
        return {
            "component": self.component,
            "property": self.property,
            "value": self.value,
            "units": self.units,
            "source": self.source,
            "error": self.error,
            "metadata": self.metadata,
        }


# -- pure calculations ----------------------------------------------------------------------


def relative_volatility(
    vapor_pressure_1: float,
    vapor_pressure_2: float,
    gamma_1: float | None = None,
    gamma_2: float | None = None,
) -> float:
    """α12 = γ1·P1sat / (γ2·P2sat), or P1sat/P2sat without both activity coefficients."""
    if gamma_1 is not None and gamma_2 is not None:
        return (gamma_1 * vapor_pressure_1) / (gamma_2 * vapor_pressure_2)
    return vapor_pressure_1 / vapor_pressure_2


def grappa_antoine_to_canonical(a: float, b: float, c: float) -> tuple[float, float, float]:
    """GRAPPA's ``ln(p/kPa) = A - B/(T/K + C)`` as :data:`ANTOINE_FORM`:
    A' = A/ln 10 - 2, B' = B/ln 10, C' = C (``ln x = ln 10 · log10 x``, ``log10(p/kPa) =
    log10(P/bar) + 2``)."""
    ln10 = math.log(10.0)
    return a / ln10 - 2.0, b / ln10, c


def select_antoine_set(parameter_sets: list[Any], temperature_K: float | None) -> tuple[Any, bool]:
    """The first set whose range covers *temperature_K*, else the closest one, flagged as
    extrapolated. Each set has ``temperatures`` (K) and ``A``, ``B``, ``C``."""
    if temperature_K is None:
        return parameter_sets[0], False

    def distance(params: Any) -> float:
        low, high = min(params.temperatures), max(params.temperatures)
        return max(low - temperature_K, temperature_K - high, 0.0)

    best = min(parameter_sets, key=distance)  # the first set wins a tie
    return best, distance(best) > 0.0


def _antoine_dict(params: Any, extrapolated_to: float | None) -> dict[str, Any]:
    found = {
        "A": params.A,
        "B": params.B,
        "C": params.C,
        "temp_min_K": min(params.temperatures),
        "temp_max_K": max(params.temperatures),
        "equation": ANTOINE_FORM,
    }
    if extrapolated_to is not None:
        found["note"] = (
            f"Requested T = {extrapolated_to:.2f} K is outside the fitted range; this is the "
            "closest NIST parameter set and is extrapolated."
        )
    return found


def _magnitude(value: Any, units: str | None, target: str) -> float:
    if units and units != target:
        return float(convert_units(float(value), units, target))
    return float(value)


# -- retrieval ------------------------------------------------------------------------------

Fetcher = Callable[[str, float, float], Any]
"""``(identifier, temperature_K, pressure_Pa) -> raw record or None``."""


def default_fetchers(client: HttpClient | None = None) -> dict[Source, Fetcher]:
    """The adapters of :mod:`chemeascode.integrations`, imported when first called."""

    def pubchem(identifier: str, _t: float, _p: float):
        from chemeascode.integrations.pubchem import search_compounds

        found = search_compounds(identifier, "name", max_records=1, client=client)
        return found[0] if found else None

    def nist(identifier: str, _t: float, _p: float):
        from chemeascode.integrations.nist_webbook import retrieve

        return retrieve(identifier, client=client)

    def osha(identifier: str, _t: float, _p: float):
        from chemeascode.integrations.osha import retrieve

        return retrieve(identifier, client=client)

    def thermo(identifier: str, t: float, p: float):
        from chemeascode.integrations.thermo import chemical_properties

        return chemical_properties(identifier, t, p)

    return {Source.PUBCHEM: pubchem, Source.NIST: nist, Source.OSHA: osha, Source.THERMO: thermo}


class PropertyRetriever:
    """Retrieves properties and caches every source record for the instance's lifetime.

    *sources* restricts the sources asked (e.g. ``{Source.THERMO}`` for an offline lookup).
    GRAPPA and HANNA are asked only when their endpoint is given. *fetchers* replaces the
    adapters (tests, or a caller with its own access to the services).
    """

    def __init__(
        self,
        *,
        sources: set[Source] | None = None,
        client: HttpClient | None = None,
        grappa_endpoint: str | None = None,
        hanna_endpoint: str | None = None,
        fetchers: dict[Source, Fetcher] | None = None,
    ) -> None:
        self.client = client
        self.grappa_endpoint = grappa_endpoint
        self.hanna_endpoint = hanna_endpoint
        self.fetchers = fetchers if fetchers is not None else default_fetchers(client)
        self.sources = set(Source) if sources is None else set(sources)
        self._records: dict[tuple, Any] = {}
        self._failures: dict[tuple, Exception] = {}
        """Fetch errors per record key, raised again instead of asking the source again."""
        self.unavailable: dict[Source, str] = {}
        """Sources skipped because an optional dependency is missing, with the reason."""

    # ---- pure components

    def get(
        self,
        identifier: str,
        property_name: str,
        temperature_K: float = 298.15,
        pressure_Pa: float = 101325.0,
    ) -> PropertyResult:
        if property_name not in SOURCE_ORDER:
            return PropertyResult(
                identifier, property_name, error=f"{property_name!r} is not a known property"
            )
        tried = []
        for source in SOURCE_ORDER[property_name]:
            if source not in self.sources:
                continue
            tried.append(source.value)
            try:
                found = self._from_source(
                    source, identifier, property_name, temperature_K, pressure_Pa
                )
            except (HttpError, ValueError, UnitError) as failure:
                found = None
                tried[-1] += f" ({failure})"
            if found is not None:
                value, units, metadata = found
                return PropertyResult(
                    identifier, property_name, value, units, source, None, metadata
                )
        reason = f"tried {', '.join(tried)}" if tried else "no enabled source gives it"
        return PropertyResult(
            identifier, property_name, error=f"{property_name} not found for {identifier}: {reason}"
        )

    def get_many(
        self,
        identifier: str,
        property_names: list[str],
        temperature_K: float = 298.15,
        pressure_Pa: float = 101325.0,
    ) -> list[PropertyResult]:
        return [self.get(identifier, n, temperature_K, pressure_Pa) for n in property_names]

    def _record(self, source: Source, identifier: str, temperature_K: float, pressure_Pa: float):
        key = (
            (source, identifier, temperature_K, pressure_Pa)
            if source == Source.THERMO
            else (
                source,
                identifier,
            )
        )
        if key in self._failures:
            raise self._failures[key]
        if key not in self._records:
            fetcher = self.fetchers.get(source)
            try:
                self._records[key] = (
                    fetcher(identifier, temperature_K, pressure_Pa) if fetcher else None
                )
            except ImportError as failure:
                self.unavailable[source] = str(failure)
                self._records[key] = None
            except (HttpError, ValueError, UnitError) as failure:
                self._failures[key] = failure  # one refused request, not one per property
                raise
        return self._records[key]

    def _from_source(
        self, source: Source, identifier: str, name: str, temperature_K: float, pressure_Pa: float
    ):
        if source == Source.GRAPPA:
            return self._grappa(identifier, name, temperature_K)
        if source == Source.OSHA:
            identifier = self._cas_number(identifier)
        record = self._record(source, identifier, temperature_K, pressure_Pa)
        if record is None:
            return None
        if source == Source.PUBCHEM:
            value = getattr(record, _PUBCHEM_FIELDS.get(name, ""), None)
            units = "g/mol" if name == "molecular_weight" else None
            return None if value is None else (value, units, {"cid": record.cid})
        if source == Source.NIST:
            return self._nist(record, name, temperature_K)
        if source == Source.OSHA:
            return _from_mapping(record, name, {"source_url": record.get("source_url")})
        if source == Source.THERMO:
            mapped = {**record, **{k: record.get(v) for k, v in _THERMO_FIELDS.items()}}
            if name == "molecular_weight" and mapped.get(name) is not None:
                mapped[name] = {"value": mapped[name], "units": "g/mol"}
            metadata = {"method": "thermo", "temperature_K": record.get("temperature_K")}
            return _from_mapping(mapped, name, metadata)
        return None

    def _cas_number(self, identifier: str) -> str:
        """*identifier* if it is a CAS number, else its ``cas`` from the enabled sources (OSHA
        is searched by CAS number only); ``ValueError`` when there is none."""
        if CAS_RE.match(identifier.strip()):
            return identifier.strip()
        found = self.get(identifier, "cas")
        if not found.ok:
            raise ValueError(f"OSHA needs the CAS number: {found.error}")
        return str(found.value)

    def _nist(self, record: Any, name: str, temperature_K: float):
        metadata = {"source_url": record.source_url}
        if name in _ANTOINE:
            if not record.antoine_equation:
                return None
            params, extrapolated = select_antoine_set(record.antoine_equation, temperature_K)
            if name == "antoine_parameters":
                value = _antoine_dict(params, temperature_K if extrapolated else None)
                return value, None, metadata
            return getattr(params, name[-1].upper()), None, {**metadata, "equation": ANTOINE_FORM}
        if name == "vapor_pressure":
            # The WebBook gives no vapour pressure, only Antoine sets; one is used inside its
            # fitted range only, otherwise the next source is asked.
            if not record.antoine_equation:
                return None
            params, extrapolated = select_antoine_set(record.antoine_equation, temperature_K)
            if extrapolated:
                return None
            bar = 10 ** (params.A - params.B / (temperature_K + params.C))
            return bar * 1e5, "Pa", {**metadata, "from": ANTOINE_FORM}
        value = getattr(record, _NIST_FIELDS.get(name, name), None)
        if value is None:
            return None
        if hasattr(value, "value") and hasattr(value, "units"):
            return value.value, value.units, metadata
        if isinstance(value, list) and value and hasattr(value[0], "model_dump"):
            return [v.model_dump() for v in value], None, metadata
        units = None
        if name == "enthalpy_vaporization_values" and record.enthalpy_vaporization_units:
            units = "/".join(record.enthalpy_vaporization_units)
        return value, units, metadata

    def _grappa(self, identifier: str, name: str, temperature_K: float):
        if self.grappa_endpoint is None or name not in (
            "vapor_pressure",
            "temperature_boil",
            *_ANTOINE,
        ):
            return None
        smiles = self.get(identifier, "smiles").value
        if not smiles:
            return None
        from chemeascode.integrations import prediction_services as services

        metadata = {"endpoint": self.grappa_endpoint, "smiles": smiles, "predicted": True}
        endpoint, client = self.grappa_endpoint, self.client
        if name == "vapor_pressure":
            entry = services.grappa_vapor_pressure(
                endpoint, [smiles], [temperature_K], client=client
            )
            return float(entry[0]["vapor_pressure_kPa"]) * 1000.0, "Pa", metadata
        if name == "temperature_boil":
            entry = services.grappa_boiling_point(
                endpoint, [smiles], [NORMAL_BOILING_PRESSURE_KPA], client=client
            )
            meta = {**metadata, "pressure_kPa": NORMAL_BOILING_PRESSURE_KPA}
            return float(entry[0]["boiling_point_K"]), "K", meta
        entry = services.grappa_antoine_parameters(endpoint, [smiles], client=client)[0]
        a, b, c = grappa_antoine_to_canonical(
            float(entry["antoine_A"]), float(entry["antoine_B"]), float(entry["antoine_C"])
        )
        if name != "antoine_parameters":
            return {"antoine_a": a, "antoine_b": b, "antoine_c": c}[name], None, metadata
        value = {"A": a, "B": b, "C": c, "equation": ANTOINE_FORM}
        return value, None, {**metadata, "converted_from": GRAPPA_ANTOINE_FORM}

    # ---- binary mixtures

    def mixture(
        self,
        component_1: str,
        component_2: str,
        property_name: str,
        *,
        x1: float | list[float] | None = None,
        temperature_K: float = 298.15,
        pressure_Pa: float = 101325.0,
        smiles_1: str | None = None,
        smiles_2: str | None = None,
    ) -> PropertyResult:
        """A binary property (:data:`MIXTURE_PROPERTIES`) of component 1 relative to 2.

        ``activity_coefficient`` needs the HANNA endpoint and SMILES (given, or from PubChem).
        ``relative_volatility`` uses activity coefficients when *x1* is given and HANNA answers,
        and the ideal ratio otherwise (``metadata["ideal"]`` says which).
        """
        pair = f"{component_1} / {component_2}"

        def failed(error: str, **metadata: Any) -> PropertyResult:
            return PropertyResult(pair, property_name, error=error, metadata=metadata)

        if property_name == "activity_coefficient":
            if self.hanna_endpoint is None:
                return failed("activity coefficients need the HANNA endpoint (hanna_endpoint)")
            if x1 is None:
                return failed("activity coefficients need the mole fraction x1")
            smiles_1 = smiles_1 or self.get(component_1, "smiles").value
            smiles_2 = smiles_2 or self.get(component_2, "smiles").value
            if not smiles_1 or not smiles_2:
                return failed("SMILES of both components are needed (give smiles_1/smiles_2)")
            from chemeascode.integrations.prediction_services import hanna_activity_coefficients

            try:
                found = hanna_activity_coefficients(
                    self.hanna_endpoint, smiles_1, smiles_2, temperature_K, x1, client=self.client
                )
            except (HttpError, ValueError) as failure:
                return failed(f"HANNA prediction failed: {failure}")
            if found["activity_coefficients"] is None:
                return failed("HANNA returned no activity coefficients")
            metadata = {"endpoint": self.hanna_endpoint, "x1": x1, "temperature_K": temperature_K}
            return PropertyResult(
                pair,
                property_name,
                found["activity_coefficients"],
                None,
                Source.HANNA,
                None,
                metadata,
            )
        if property_name == "boiling_point_difference":
            return self._difference(pair, component_1, component_2, temperature_K, pressure_Pa)
        if property_name == "relative_volatility":
            return self._relative_volatility(
                pair, component_1, component_2, x1, temperature_K, pressure_Pa, smiles_1, smiles_2
            )
        return failed(
            f"{property_name!r} is not a binary property ({', '.join(MIXTURE_PROPERTIES)})"
        )

    def _both(self, c1: str, c2: str, name: str, target: str, t: float, p: float):
        results = [self.get(c, name, t, p) for c in (c1, c2)]
        missing = [f"{name} of {r.component}" for r in results if not r.ok]
        if missing:
            return None, results, f"failed to retrieve {', '.join(missing)}"
        try:
            values = [_magnitude(r.value, r.units, target) for r in results]
        except (UnitError, TypeError, ValueError) as failure:
            return None, results, f"{name} not convertible to {target} ({failure})"
        return values, results, None

    def _difference(self, pair: str, c1: str, c2: str, t: float, p: float) -> PropertyResult:
        name = "boiling_point_difference"
        values, results, error = self._both(c1, c2, "temperature_boil", "K", t, p)
        if values is None:
            return PropertyResult(pair, name, error=f"Cannot compute {name}: {error}")
        metadata = {
            f"boiling_point_{i}": {"value": v, "units": "K", "source": r.source}
            for i, (v, r) in enumerate(zip(values, results, strict=True), start=1)
        }
        return PropertyResult(
            pair, name, abs(values[0] - values[1]), "K", Source.DERIVED, None, metadata
        )

    def _relative_volatility(self, pair, c1, c2, x1, t, p, smiles_1, smiles_2) -> PropertyResult:
        name = "relative_volatility"
        values, results, error = self._both(c1, c2, "vapor_pressure", "Pa", t, p)
        if values is None:
            return PropertyResult(pair, name, error=f"Cannot compute {name}: {error}")
        if values[1] == 0:
            return PropertyResult(pair, name, error=f"Cannot compute {name}: P_sat of {c2} is 0")
        gamma_1 = gamma_2 = None
        if x1 is not None and self.hanna_endpoint is not None:
            found = self.mixture(
                c1,
                c2,
                "activity_coefficient",
                x1=x1,
                temperature_K=t,
                smiles_1=smiles_1,
                smiles_2=smiles_2,
            )
            coefficients = found.value
            if (
                isinstance(coefficients, list)
                and len(coefficients) >= 2
                and all(isinstance(g, int | float) for g in coefficients[:2])
            ):
                gamma_1, gamma_2 = float(coefficients[0]), float(coefficients[1])
        if gamma_2 is not None and abs(gamma_2 * values[1]) < 1e-12:
            return PropertyResult(pair, name, error=f"Cannot compute {name}: γ2·P2sat is 0")
        metadata: dict[str, Any] = {
            f"vapor_pressure_{i}": {"value": v, "units": "Pa", "source": r.source}
            for i, (v, r) in enumerate(zip(values, results, strict=True), start=1)
        }
        metadata["ideal"] = gamma_1 is None
        if gamma_1 is not None:
            metadata.update(activity_coefficient_1=gamma_1, activity_coefficient_2=gamma_2)
        alpha = relative_volatility(values[0], values[1], gamma_1, gamma_2)
        return PropertyResult(pair, name, alpha, None, Source.DERIVED, None, metadata)


def _from_mapping(record: dict[str, Any], name: str, metadata: dict[str, Any]):
    value = record.get(name)
    if value is None:
        return None
    if isinstance(value, dict) and "value" in value:
        if value["value"] is None:
            return None
        extra = {k: v for k, v in value.items() if k not in ("value", "units")}
        return value["value"], value.get("units"), {**metadata, **extra}
    return value, None, metadata


def retrieve_properties(
    identifier: str,
    properties: list[str],
    *,
    temperature: float = 298.15,
    temperature_unit: str = "K",
    pressure: float = 101325.0,
    pressure_unit: str = "Pa",
    retriever: PropertyRetriever | None = None,
) -> list[PropertyResult]:
    """*properties* of *identifier* (name, CAS number) at the given conditions, one result per
    property in the order asked; a failed one carries ``error``."""
    temperature_K = convert_units(temperature, temperature_unit, "K")
    pressure_Pa = convert_units(pressure, pressure_unit, "Pa")
    retriever = retriever or PropertyRetriever()
    return retriever.get_many(identifier, properties, temperature_K, pressure_Pa)
