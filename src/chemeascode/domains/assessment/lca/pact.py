"""WBCSD PACT (Pathfinder) export of a product carbon footprint (pre-release issue 181).

:func:`footprint` gives the ``ProductFootprint`` of the study's functional unit product,
cradle-to-gate, in the PACT data model v2 (Technical Specifications for PCF Data Exchange,
version 2.3; the property names, enumerations and constraints below were read from the
specification's ``spec/v2/openapi.yaml`` 2.3.3, github.com/wbcsd/data-exchange-protocol). The
specification's licence does not allow redistributing it, so :class:`ProductFootprint` is our
own model of the properties and rules this export uses, and :func:`validate` checks a document
against it.

What the export takes from where:

- the values from the PCF breakdown (:class:`.carbon.Pcf`), per declared unit, by the product's
  unit (:data:`DECLARED_UNITS`: kg is ``kilogram``, kWh ``kilowatt hour``, m3 ``cubic meter``,
  m2 ``square meter``; any other is refused). A dataset counts its products in these base units
  only (``INVENTORY_UNITS``), and the functional unit is converted to the product's unit, so the
  amount is exported as it is (a functional unit of 1 t of a product in kg is 1000 kg);
- the data owner and the product's identifiers from ``carbon_accounting.pact``, the CPC code from
  there or from the dataset's ``classification.cpc``;
- the reference period from the study's ``year`` (a calendar year, the end excluded), the
  geography from its ``location``: an ISO 3166-1 alpha-2 code is ``geographyCountry``, an
  ISO 3166-2 subdivision (``DE-BY``) ``geographyCountrySubdivision``, a PACT region (``Western
  Europe``) ``geographyRegionOrSubregion``; no location is global, and any other location is
  refused (never exported as global);
- the IPCC report from ``carbon_accounting.ipcc`` (report and GWP horizon, which must be 100
  years) or from a packaged method category (``ipcc2021-gwp100``), never guessed from titles;
- the data quality from the dataset's rating (:mod:`.quality`): ``primaryDataShare`` in percent,
  and ``dqi`` with the TfS indicators (1 to 5) mapped linearly onto PACT's 1 to 3
  (``1 + (x - 1) / 2``, our mapping; the TfS values are repeated in ``comment``), and the
  coverage (100 % less the exempted share). A result with gaps is not exported: PACT needs the
  share of exempted emissions, and the size of a gap is unknown;
- the exempted emissions: only a cradle-to-gate study is exported (a PACT PCF is cradle-to-gate).
  What the boundary leaves out (:func:`.report._limitations`: construction, end of life of the
  plant, transport of supplies) and the flows cut off by the study's criteria are exempted
  emissions, and their share is unknown to cheme: the study states it
  (``carbon_accounting.pact.exempted_emissions_percent``, at most 5 %, with its description), or
  no document is made. A study that leaves out nothing exports 0 %.

The footprint ``id`` is a uuid5 of the dataset, version, product, case **and a hash of the ``pcf``
values and the reference period**, so a changed result never reuses an id with ``version`` 1.

Nothing here invents a value: what PACT requires and the study does not give is a problem, and
no document is made.
"""

from __future__ import annotations

import datetime as _dt
import hashlib
import json
import re
import uuid as _uuid
from decimal import Decimal
from typing import Any, Literal

from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    ValidationError,
    field_validator,
    model_validator,
)

from chemeascode.domains.assessment.lca.impacts import real_gaps
from chemeascode.domains.assessment.lca.schemas import pact_urn_ok

#: The PACT Technical Specifications version the export follows.
SPEC_VERSION = "2.3.0"
NAMESPACE = _uuid.uuid5(_uuid.NAMESPACE_URL, "https://github.com/ChemE-as-Code/core/pact")
#: The TfS guideline (tfs-initiative.com/pcf-guideline: "The Product Carbon Footprint Guideline
#: for the Chemical Industry", Version 3.0, December 2024), as PACT's own example names a sector
#: rule it has no operator for. Stated only for a study that follows it (-1/+1 biogenic).
TFS_RULE = {
    "operator": "Other",
    "ruleNames": [
        "The Product Carbon Footprint Guideline for the Chemical Industry, Version 3.0 "
        "(Together for Sustainability, December 2024)"
    ],
    "otherOperatorName": "Together for Sustainability (TfS)",
}
#: Product unit (a base unit of the inventory) -> (PACT declaredUnit, declared units per it).
DECLARED_UNITS: dict[str, tuple[str, float]] = {
    "kg": ("kilogram", 1.0),
    "kWh": ("kilowatt hour", 1.0),
    "m3": ("cubic meter", 1.0),
    "m2": ("square meter", 1.0),
}
#: Climate categories whose IPCC report is known exactly (packaged methods, 100-year GWP).
KNOWN_IPCC = {"ipcc2021-gwp100": "AR6"}
#: The CarbonFootprint properties the specification marks O* (v2.3.3): optional, but they MUST
#: be defined when the reference period includes the start of 2025 or later.
O_STAR = (
    "pCfIncludingBiogenic",
    "dLucGhgEmissions",
    "landManagementGhgEmissions",
    "otherBiogenicGhgEmissions",
    "biogenicCarbonWithdrawal",
    "biogenicAccountingMethodology",
    "primaryDataShare",
    "dqi",
)
#: PACT's RegionOrSubregion enumeration.
REGIONS = (
    "Africa", "Americas", "Asia", "Europe", "Oceania", "Australia and New Zealand",
    "Central Asia", "Eastern Asia", "Eastern Europe", "Latin America and the Caribbean",
    "Melanesia", "Micronesia", "Northern Africa", "Northern America", "Northern Europe",
    "Polynesia", "South-eastern Asia", "Southern Asia", "Southern Europe", "Sub-Saharan Africa",
    "Western Asia", "Western Europe",
)  # fmt: skip
_DECIMAL = re.compile(r"^-?\d+(\.\d+)?$")
_URN = r"^([uU][rR][nN]):"
_COUNTRY = r"^[A-Z]{2}$"
_SUBDIVISION = r"^[A-Z]{2}-[A-Z0-9]{1,3}$"
_ISO_TIME = r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(\.\d+)?(Z|[+-]\d{2}:\d{2})$"

DeclaredUnit = Literal[
    "liter",
    "kilogram",
    "cubic meter",
    "kilowatt hour",
    "megajoule",
    "ton kilometer",
    "square meter",
]


class _Model(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)


def _check_decimal(value: str, sign: int = 0) -> str:
    if not _DECIMAL.match(value):
        raise ValueError(f"{value!r} is no decimal")
    if sign > 0 and Decimal(value) < 0:
        raise ValueError(f"{value} must be >= 0")
    if sign < 0 and Decimal(value) > 0:
        raise ValueError(f"{value} must be <= 0")
    return value


class DataQualityIndicators(_Model):
    coveragePercent: float = Field(ge=0, le=100)
    technologicalDQR: float = Field(ge=1, le=3)
    temporalDQR: float = Field(ge=1, le=3)
    geographicalDQR: float = Field(ge=1, le=3)
    completenessDQR: float = Field(ge=1, le=3)
    reliabilityDQR: float = Field(ge=1, le=3)


class EmissionFactorDatabase(_Model):
    name: str = Field(min_length=1)
    version: str = Field(min_length=1)


class ProductOrSectorSpecificRule(_Model):
    operator: Literal["PEF", "EPD International", "Other"]
    ruleNames: list[str] = Field(min_length=1)
    otherOperatorName: str | None = Field(default=None, min_length=1)


class CarbonFootprint(_Model):
    """``CarbonFootprint`` of the PACT data model v2 (the properties this export writes)."""

    declaredUnit: DeclaredUnit
    unitaryProductAmount: str
    pCfExcludingBiogenic: str
    pCfIncludingBiogenic: str | None = None
    fossilGhgEmissions: str
    fossilCarbonContent: str
    biogenicCarbonContent: str
    dLucGhgEmissions: str | None = None
    otherBiogenicGhgEmissions: str | None = None
    landManagementGhgEmissions: str | None = None
    biogenicCarbonWithdrawal: str | None = None
    characterizationFactors: Literal["AR6", "AR5"]
    ipccCharacterizationFactorsSources: list[str] = Field(min_length=1)
    crossSectoralStandardsUsed: list[
        Literal["GHG Protocol Product standard", "ISO Standard 14067", "ISO Standard 14044"]
    ] = Field(min_length=1)
    crossSectoralStandards: (
        list[
            Literal[
                "ISO14067",
                "ISO14083",
                "ISO14040-44",
                "GHGP-Product",
                "PEF",
                "PACT-1.0",
                "PACT-2.0",
                "PACT-3.0",
            ]
        ]
        | None
    ) = Field(default=None, min_length=1)
    productOrSectorSpecificRules: list[ProductOrSectorSpecificRule] | None = Field(
        default=None, min_length=1
    )
    biogenicAccountingMethodology: Literal["PEF", "ISO", "GHGP", "Quantis"] | None = None
    boundaryProcessesDescription: str
    referencePeriodStart: str = Field(pattern=_ISO_TIME)
    referencePeriodEnd: str = Field(pattern=_ISO_TIME)
    geographyRegionOrSubregion: Literal[
        "Africa", "Americas", "Asia", "Europe", "Oceania", "Australia and New Zealand",
        "Central Asia", "Eastern Asia", "Eastern Europe", "Latin America and the Caribbean",
        "Melanesia", "Micronesia", "Northern Africa", "Northern America", "Northern Europe",
        "Polynesia", "South-eastern Asia", "Southern Asia", "Southern Europe",
        "Sub-Saharan Africa", "Western Asia", "Western Europe",
    ] | None = None  # fmt: skip
    geographyCountry: str | None = Field(default=None, pattern=_COUNTRY)
    geographyCountrySubdivision: str | None = Field(default=None, pattern=_SUBDIVISION)
    secondaryEmissionFactorSources: list[EmissionFactorDatabase] | None = Field(
        default=None, min_length=1
    )
    exemptedEmissionsPercent: float = Field(ge=0, le=5)
    exemptedEmissionsDescription: str
    packagingEmissionsIncluded: bool
    allocationRulesDescription: str | None = None
    uncertaintyAssessmentDescription: str | None = None
    primaryDataShare: float | None = Field(default=None, ge=0, le=100)
    dqi: DataQualityIndicators | None = None

    @model_validator(mode="after")
    def _one_geography(self) -> CarbonFootprint:
        defined = [
            n
            for n in (
                "geographyRegionOrSubregion",
                "geographyCountry",
                "geographyCountrySubdivision",
            )
            if getattr(self, n) is not None
        ]
        if len(defined) > 1:
            raise ValueError(f"only one geography property may be defined, not {defined}")
        return self

    @field_validator("unitaryProductAmount")
    @classmethod
    def _positive(cls, value: str) -> str:
        _check_decimal(value, 1)
        if Decimal(value) <= 0:
            raise ValueError("unitaryProductAmount must be > 0")
        return value

    @field_validator(
        "pCfExcludingBiogenic",
        "fossilGhgEmissions",
        "fossilCarbonContent",
        "biogenicCarbonContent",
        "dLucGhgEmissions",
        "otherBiogenicGhgEmissions",
    )
    @classmethod
    def _non_negative(cls, value: str | None) -> str | None:
        return None if value is None else _check_decimal(value, 1)

    @field_validator("pCfIncludingBiogenic", "landManagementGhgEmissions")
    @classmethod
    def _any(cls, value: str | None) -> str | None:
        return None if value is None else _check_decimal(value)

    @field_validator("biogenicCarbonWithdrawal")
    @classmethod
    def _non_positive(cls, value: str | None) -> str | None:
        return None if value is None else _check_decimal(value, -1)

    @field_validator("ipccCharacterizationFactorsSources")
    @classmethod
    def _reports(cls, value: list[str]) -> list[str]:
        if not all(re.match(r"^AR\d+$", v) for v in value):
            raise ValueError("IPCC reports are AR<version>")
        return value


class ProductFootprint(_Model):
    """``ProductFootprint`` of the PACT data model v2 (the properties this export writes)."""

    id: str = Field(pattern=r"^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$")
    specVersion: str = Field(pattern=r"^\d+\.\d+\.\d+(-\d{8})?$")
    version: int = Field(ge=0)
    created: str = Field(pattern=_ISO_TIME)
    status: Literal["Active", "Deprecated"]
    companyName: str = Field(min_length=1)
    companyIds: list[str] = Field(min_length=1)
    productDescription: str
    productIds: list[str] = Field(min_length=1)
    productCategoryCpc: str = Field(min_length=1)
    productNameCompany: str = Field(min_length=1)
    comment: str
    pcf: CarbonFootprint

    @field_validator("companyIds", "productIds")
    @classmethod
    def _urns(cls, value: list[str]) -> list[str]:
        if not all(re.match(_URN, v) for v in value):
            raise ValueError("identifiers are URNs (urn:...)")
        if not all(pact_urn_ok(v) for v in value):
            raise ValueError("urn:pact: identifiers are urn:pact:<domain>:<type>:<id>")
        return value


def validate(document: dict[str, Any]) -> list[str]:
    """What makes *document* no valid PACT v2 ``ProductFootprint`` under :class:`ProductFootprint`
    (empty: valid), plus the rules across properties: for reference periods from 2025 on, the
    properties the specification marks O* (``MUST`` be defined from then on: ``O_STAR``)."""
    try:
        footprint_ = ProductFootprint.model_validate(document)
    except ValidationError as failure:
        return [
            f"{'.'.join(str(p) for p in error['loc'])}: {error['msg']}"
            for error in failure.errors()
        ]
    problems = []
    pcf = footprint_.pcf
    end = _dt.datetime.fromisoformat(pcf.referencePeriodEnd)
    if end.tzinfo is None:
        end = end.replace(tzinfo=_dt.UTC)
    # the end is excluded: a period ending at the beginning of 2025 lies before it
    if end > _dt.datetime(2025, 1, 1, tzinfo=_dt.UTC):
        missing = [n for n in O_STAR if getattr(pcf, n) is None]
        if missing:
            problems.append(
                f"pcf: {', '.join(missing)} required when the reference period includes the "
                "beginning of 2025 or later"
            )
    elif pcf.dqi is None and pcf.primaryDataShare is None:
        problems.append("pcf: primaryDataShare or dqi is required")
    return problems


def _decimal(value: float) -> str:
    """*value* as a PACT decimal string (no exponent, nine decimals at most)."""
    text = format(Decimal(repr(round(value, 9))).normalize(), "f")
    if "." in text:
        text = text.rstrip("0").rstrip(".")
    return "0" if text in ("-0", "") else text


def _dqr(value: float) -> float:
    """A TfS indicator (1 to 5) on PACT's scale (1 to 3): linear, our mapping."""
    return round(1 + (min(5.0, max(1.0, value)) - 1) / 2, 4)


def _ipcc(category: Any, declared: Any) -> tuple[str | None, str | None]:
    """The IPCC report (AR5 or AR6) of the climate category's 100-year GWP factors, or None and
    why not: the study's declaration (``carbon_accounting.ipcc``) or an exact packaged method
    (``category.elementary``); the titles are never read."""
    known = KNOWN_IPCC.get(category.elementary or "")
    if declared is None:
        if known is not None:
            return known, None
        return None, (
            f"{category.id}: the IPCC report and GWP horizon of its factors are not declared "
            "(carbon_accounting.ipcc: {report: AR6, gwp_horizon: 100}); cheme does not guess "
            "them from titles"
        )
    if declared.gwp_horizon != 100:
        return None, f"carbon_accounting.ipcc: GWP{declared.gwp_horizon} (PACT needs GWP100)"
    if known is not None and known != declared.report:
        return None, (
            f"carbon_accounting.ipcc says {declared.report}, but {category.elementary} is {known}"
        )
    return declared.report, None


def _geography(location: str) -> tuple[dict[str, str], str | None]:
    """The PACT geography property of a study ``location``, or why it has none: empty is global
    (no property); a region of PACT's enumeration, an ISO 3166-1 alpha-2 country or an ISO
    3166-2 subdivision each go to their property; anything else is refused."""
    text = location.strip()
    if not text:
        return {}, None
    for region in REGIONS:
        if text.casefold() == region.casefold():
            return {"geographyRegionOrSubregion": region}, None
    code = text.upper()
    head, sep, rest = code.partition("-")
    if head == "UK":
        code = "GB" + sep + rest
    if re.fullmatch(_COUNTRY, code):
        return {"geographyCountry": code}, None
    if re.fullmatch(_SUBDIVISION, code):
        return {"geographyCountrySubdivision": code}, None
    return {}, (
        f"location {location!r} is no ISO 3166-1 country, ISO 3166-2 subdivision or PACT region "
        "(leave location empty for a global study); it is not exported as global"
    )


def _iso(moment: _dt.datetime) -> str:
    if moment.tzinfo is None:
        moment = moment.replace(tzinfo=_dt.UTC)
    return moment.astimezone(_dt.UTC).strftime("%Y-%m-%dT%H:%M:%SZ")


def _exempted(
    report: Any, scope: Any, identity: Any, dataset: Any
) -> tuple[tuple[float, str], str | None]:
    """The exempted emissions of the footprint as ``(percent, description)``, or why they
    cannot be stated. Only a cradle-to-gate study is a PACT PCF. What the boundary leaves out
    and what the cut-off criteria cut are exempted emissions whose share cheme cannot know:
    the study states it, or nothing is exported (never a claimed 0 %)."""
    from chemeascode.domains.assessment.lca.report import _limitations

    if scope.boundary != "cradle-to-gate":
        return (0.0, ""), (
            f"boundary {scope.boundary}: a PACT product footprint is cradle-to-gate "
            "(lca.yaml boundary: cradle-to-gate)"
        )
    left_out = [
        *_limitations(scope),
        *(f"cut off: {c.id}" for c in scope.cutoff),
        *(f"cut off: {c.key}" for c in dataset.cutoff),
    ]
    declared = identity.exempted_emissions_percent if identity is not None else None
    if declared is None:
        if left_out:
            return (0.0, ""), (
                "the study leaves out " + "; ".join(dict.fromkeys(left_out)) + ": PACT needs "
                "the share of exempted emissions, which cheme cannot know "
                "(carbon_accounting.pact.exempted_emissions_percent, at most 5, with "
                "exempted_emissions_description; mark an estimate ASSUMED)"
            )
        return (0.0, "Nothing left out by the study's boundary or cut-off criteria."), None
    return (declared, identity.exempted_emissions_description), None


def footprint(
    report: Any, created: _dt.datetime, version: int = 1
) -> tuple[dict[str, Any] | None, list[str]]:
    """The PACT ``ProductFootprint`` of *report*'s functional unit product, or None and what
    is missing for one. *created* is when it is made (PACT asks for it; it is no input of the
    LCA, so ``--write`` does not write this file)."""
    problems: list[str] = []
    scope, found, inv = report.scope, report.pcf, report.inventory
    if scope is None or scope.carbon_accounting is None or found is None or inv is None:
        return None, ["no PCF: the study declares no carbon_accounting, or the LCA did not run"]
    identity = scope.carbon_accounting.pact
    if identity is None:
        problems.append("carbon_accounting.pact (data owner and product identifiers) is missing")
    problems += found.problems
    if scope.year is None:
        problems.append("the study has no year: PACT needs the reference period")
    category = next((c for c in report.categories if c.id == found.category), None)
    ipcc, why = (
        _ipcc(category, scope.carbon_accounting.ipcc)
        if category is not None
        else (None, f"{found.category}: no such category")
    )
    if why is not None:
        problems.append(why)
    geography, why = _geography(scope.location)
    if why is not None:
        problems.append(why)
    gaps = real_gaps(
        [g for g in report.gaps if g.scenario == "baseline" and g.category == found.category]
    )
    if gaps:
        problems.append(
            f"{len(gaps)} gaps in {found.category} ({', '.join(sorted({g.key for g in gaps}))}): "
            "PACT needs the share of exempted emissions, and theirs is unknown"
        )
    dataset = inv.dataset
    cpc = (identity.cpc if identity is not None else "") or (
        dataset.classification.cpc if dataset.classification is not None else ""
    )
    if not cpc:
        problems.append("no CPC code: carbon_accounting.pact.cpc or dataset.classification.cpc")
    exempted, why = _exempted(report, scope, identity, dataset)
    if why is not None:
        problems.append(why)
    reference = dataset.product(scope.functional_unit.product)
    declared = DECLARED_UNITS.get(reference.unit)
    if declared is None:
        problems.append(
            f"{reference.key}: unit {reference.unit} has no PACT declaredUnit "
            f"({', '.join(DECLARED_UNITS)})"
        )
    quality = report.data_quality
    if quality is None:
        problems.append("no data quality rating of the dataset (primaryDataShare, dqi)")
    if problems:
        return None, problems
    unit, per_product_unit = declared
    # the inventory amount is in the product's unit (a base unit), not in the functional unit's
    amount = inv.amount * per_product_unit  # in declared units
    percent, description = exempted

    def per(value: float) -> str:
        return _decimal(value / amount)

    from chemeascode.domains.assessment.lca.report import _limitations

    follows_tfs = found.biogenic_method == "minus-one-plus-one"
    allocation = scope.allocation
    pcf: dict[str, Any] = {
        "declaredUnit": unit,
        "unitaryProductAmount": _decimal(amount),
        "pCfExcludingBiogenic": per(found.excluding),
        # PACT v2 has no field for a technological removal: biogenic CO2 to storage stays out
        "pCfIncludingBiogenic": per(found.including - found.stored_biogenic),
        "fossilGhgEmissions": per(found.fossil),
        "fossilCarbonContent": per(found.fossil_carbon),
        "biogenicCarbonContent": per(found.biogenic_carbon),
        "dLucGhgEmissions": per(found.dluc),
        "otherBiogenicGhgEmissions": per(found.other_biogenic),
        # required from 2025 on; cheme does not model land management (ASSUMED 0, see comment)
        "landManagementGhgEmissions": "0",
        "biogenicCarbonWithdrawal": per(found.withdrawal),
        "characterizationFactors": ipcc,
        "ipccCharacterizationFactorsSources": [ipcc],
        "crossSectoralStandardsUsed": ["ISO Standard 14067"],
        "crossSectoralStandards": ["ISO14067"],
        "boundaryProcessesDescription": "; ".join(
            [
                f"{scope.boundary} of {dataset.title or dataset.id}",
                *(_limitations(scope)),
            ]
        ),
        "referencePeriodStart": f"{scope.year}-01-01T00:00:00Z",
        "referencePeriodEnd": f"{scope.year + 1}-01-01T00:00:00Z",
        "exemptedEmissionsPercent": percent,
        "exemptedEmissionsDescription": description,
        "packagingEmissionsIncluded": False,
        "allocationRulesDescription": f"{inv.method} allocation"
        + (f" ({allocation.source})" if allocation.source else "")
        + (f"; deviation: {allocation.deviation}" if allocation.deviation else "")
        + "; biogenic carbon removals follow the product's own biogenic carbon content",
        "primaryDataShare": round(100 * quality.primary_share, 4),
        "dqi": {
            "coveragePercent": round(100.0 - percent, 4),
            "technologicalDQR": _dqr(quality.TeR),
            "temporalDQR": _dqr(quality.TiR),
            "geographicalDQR": _dqr(quality.GeR),
            "completenessDQR": _dqr(quality.C),
            "reliabilityDQR": _dqr(quality.P),
        },
    }
    if follows_tfs:
        # the TfS guideline asks for -1/+1; a zero-zero study does not follow it
        pcf["productOrSectorSpecificRules"] = [TFS_RULE]
    # required from 2025 on: -1/+1 is the ISO 14067 treatment; 0/0 (biogenic CO2 neither
    # emitted nor removed, the carbon content declared) is the PEF one (our mapping, in comment)
    pcf["biogenicAccountingMethodology"] = "ISO" if follows_tfs else "PEF"
    pcf.update(geography)
    databases = [
        {"name": s.title or s.provider, "version": s.version}
        for s in report.sources
        if s.version and (s.title or s.provider)
    ]
    if databases:
        pcf["secondaryEmissionFactorSources"] = databases
    if report.uncertainty is not None:
        mc = report.uncertainty
        pcf["uncertaintyAssessmentDescription"] = (
            f"Monte Carlo, {mc.iterations} iterations (seed {mc.seed}), lognormal exchanges "
            "from the pedigree matrix"
        )
    # the id follows the content: a changed result (or period) is another footprint
    content = hashlib.sha256(json.dumps(pcf, sort_keys=True).encode()).hexdigest()
    stored = (
        f" Biogenic CO2 sent to permanent storage (CCS): {per(found.stored_biogenic)} kg CO2e "
        "per declared unit, NOT in pCfIncludingBiogenic (PACT v2 has no field for a "
        "technological removal; the permanence is to be shown separately). With it the PCF "
        f"including biogenic CO2 would be {per(found.including)} kg CO2e per declared unit."
        if found.stored_biogenic
        else ""
    )
    other = (
        f" pCfIncludingBiogenic also credits {per(found.withdrawal_other)} kg CO2e per declared "
        "unit for biogenic carbon leaving as CH4, CO or in a non-product output (beyond "
        "biogenicCarbonWithdrawal, which is the product's biogenic carbon)."
        if found.withdrawal_other
        else ""
    )
    ccu = (
        f" Carbon content from captured CO2 (CCU): {per(found.ccu_carbon)} kg C per declared "
        f"unit, of which from a biogenic point source or the air (DAC): "
        f"{per(found.ccu_non_fossil_carbon)} kg C; DAC carbon is booked with the biogenic "
        "carbon content."
        if found.ccu_carbon
        else ""
    )
    notes = (
        " The carbon contents are on a physical basis (the carbon traced through the process, "
        "no mass-balance attribution). fossilGhgEmissions contains every background "
        "contribution: biogenic CH4 or land-use change inside background factors is not "
        "separated from it. landManagementGhgEmissions 0: land management emissions are not "
        "modelled (ASSUMED). biogenicAccountingMethodology is cheme's mapping: ISO for -1/+1, "
        "PEF for 0/0."
    )
    key = (
        f"{dataset.uuid or dataset.id}/{dataset.version or ''}/{reference.key}/{inv.case}/{content}"
    )
    document = {
        "id": str(_uuid.uuid5(NAMESPACE, key)),
        "specVersion": SPEC_VERSION,
        "version": version,
        "created": _iso(created),
        "status": "Active",
        "companyName": identity.company_name,
        "companyIds": list(identity.company_ids),
        "productDescription": identity.product_description or dataset.title or "",
        "productIds": list(identity.product_ids),
        "productCategoryCpc": cpc,
        "productNameCompany": identity.product_name,
        "comment": (
            f"{report.label}; generated by cheme assess lca from {dataset.id}. TfS DQR "
            f"{quality.dqr:.2f} (TeR {quality.TeR:.2f}, GeR {quality.GeR:.2f}, TiR "
            f"{quality.TiR:.2f}, 1 to 5); PACT dqi mapped linearly to 1 to 3. Biogenic "
            f"carbon: {found.biogenic_method}; CCU {found.ccu_rule}; CCS {found.ccs}."
            + stored
            + other
            + ccu
            + notes
        ),
        "pcf": pcf,
    }
    invalid = validate(document)
    if invalid:
        return None, [f"not a valid PACT footprint: {p}" for p in invalid]
    return document, []


def footprint_json(document: dict[str, Any]) -> str:
    return json.dumps(document, indent=2) + "\n"
