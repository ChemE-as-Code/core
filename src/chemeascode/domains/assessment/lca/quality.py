"""Data quality of an LCI dataset (pre-release issue 178): a pedigree per exchange, its gsd2, and
the dataset's data quality rating.

**Per exchange.** The ecoinvent pedigree matrix (Weidema, B.P., Bauer, C., Hischier, R., Mutel,
C., Nemecek, T., Reinhard, J., Vadenbo, C.O., Wernet, G. (2013): Overview and methodology. Data
quality guideline for the ecoinvent database version 3. Ecoinvent Report 1 (v3), St. Gallen):
five scores, 1 (best) to 5, for reliability, completeness, temporal, geographical and further
technological correlation, each relative to the dataset's declared scope (its ``location`` and
``year``), not to the plant. They combine with a basic uncertainty by exchange type into a
lognormal gsd2 with the empirically based factors of Ciroth, A., Muller, S., Weidema, B.,
Lesage, P. (2016), Int J Life Cycle Assess 21:1338-1348 (``foundation.uncertainty.PEDIGREE``):
``gsd2 = exp(sqrt(ln(basic)^2 + sum ln(U_i)^2))``.

Nothing goes unscored: :func:`score` gives every exchange without a ``pedigree`` the default of
:data:`RULE`, from what core knows of the value (its provenance and origin), the dataset's
declared geography and year, and the design's maturity (``process.yaml``). The rule is cheme's
own convention (ASSUMED, docs/framework/lca.md lists it); a pedigree set by hand records its
reason. :data:`BASIC` gives the basic uncertainty by exchange type.

**Per dataset.** :func:`rating` gives the TfS data quality rating (Together for Sustainability,
PCF Guideline v3: technological, geographical and temporal representativeness TeR, GeR, TiR, 1 to
5, DQR their mean), averaged over the exchanges weighted by each one's absolute contribution to
a climate category where the contributions are known, else the unweighted unit-process value
(flagged). The pedigree's technological, geographical and temporal scores stand for TeR, GeR
and TiR (the scales run the same way). Beside it, the PEF-style indicators (adding precision P,
from the reliability score, and completeness C; DQR_PEF = (TeR + GeR + TiR + P) / 4 as in the
EF method) and the primary data share (PDS: the share of data measured at the plant, origin
``measured``).
"""

from __future__ import annotations

from dataclasses import asdict, dataclass
from typing import Any

from chemeascode.domains.assessment.lca.methods import normalise_cas
from chemeascode.domains.assessment.lca.schemas import DatasetExchange, LciDataset, Pedigree
from chemeascode.foundation.uncertainty import pedigree_gsd2
from chemeascode.foundation.units import LCI_UNITS

#: The default rule's name, recorded on every pedigree it gives.
RULE = "cheme default pedigree v1"
INDICATORS = ("reliability", "completeness", "temporal", "geographical", "technological")

#: Reliability by origin, then by provenance (ecoinvent: 1 verified measurement, 2 measurement
#: or verified partly assumed, 3 non-verified partly estimated, 4 qualified estimate, 5
#: non-qualified estimate). A verified measurement scores 1 only by hand.
RELIABILITY = {
    "measured": 2,
    "vendor": 2,
    "literature": 3,
    "simulated": 3,
    "correlation": 3,
    "design-rule": 4,
    "estimate": 4,
    "given": 3,
    "calculated": 3,
    # an emission-factor estimate (emission_estimates:, pre-release issue 176): activity data of the
    # design and average factors from a source, not measured at the plant (ASSUMED: cheme's choice)
    "estimated": 3,
    "assumed": 4,
}
#: Completeness: one plant (one site) represents the dataset (ecoinvent score 4).
COMPLETENESS = 4
#: Further technological correlation by origin, then provenance: data of the process itself 1,
#: an estimate for it 2, literature for a related process 3.
#: An emission-factor estimate takes average factors of related plants: 3 (ASSUMED: cheme's
#: choice, as for literature).
TECHNOLOGICAL = {"literature": 3, "given": 1, "calculated": 1, "estimated": 3, "assumed": 2}
#: Temporal score of secondary data by origin, when the dataset declares its year: a literature
#: value, a correlation or a design rule is not data of the reference year. ASSUMED 3 (ecoinvent:
#: less than 10 years of difference, the brief's freshness limit for secondary data); the data
#: of the design itself score 1.
TEMPORAL = {"literature": 3, "correlation": 3, "design-rule": 3}
#: The same by provenance, where the origin gives none: an emission-factor estimate's factors
#: are secondary data, not of the reference year (pre-release issue 176).
TEMPORAL_PROVENANCE = {"estimated": 3}
#: The least technological score a design of each maturity (process.yaml) supports: a concept
#: represents the technology only roughly.
MATURITY_FLOOR = {"concept": 3, "screening": 2}
#: Geography codes that name a region, not a country or a site: one design claimed for a region
#: scores geographical 3 (data from an area with similar production conditions).
REGIONS = frozenset(
    {"GLO", "RER", "RoW", "RNA", "RAS", "RLA", "RAF", "RME", "EU", "EU27", "EU28", "WEU", "OCE"}
)

#: Basic uncertainty (gsd2) by exchange type: the default basic uncertainties of the ecoinvent
#: v3 data quality guideline (Weidema et al. 2013; the factors of ecoinvent v2, Frischknecht et
#: al. 2007): energy, materials, waste and resources 1.05; transport 2.0; infrastructure 3.0;
#: land occupation 1.5, transformation 2.0; emissions to air by substance (combustion and
#: process values, not the agricultural ones).
#:
#: TODO(pre-release issue 313): UNVERIFIED. The values of BASIC, BASIC_AIR and BASIC_AIR_FLOW were
#: entered from memory, not read from the guideline. Check each against the table of default basic
#: uncertainties in Weidema et al. (2013), Data quality guideline for the ecoinvent database
#: version 3, Ecoinvent Report 1 (v3), section on basic uncertainty, and cite the table (with
#: its number and page) here and in docs/framework/lca.md; in particular NH3 (1.5 combustion,
#: 1.2 agricultural), CH4, PM2.5 (3.0), NMVOC (1.5), CO (5.0) and the emission default 1.5
#: (used for emissions to water and soil). Until then they are cheme's working defaults.
BASIC = {
    "default": 1.05,
    "transport": 2.0,
    "infrastructure": 3.0,
    "land-occupation": 1.5,
    "land-transformation": 2.0,
    # ASSUMED: an emission the table does not list takes the value of most air pollutants
    "emission": 1.5,
}
#: Basic uncertainty of emissions to air by CAS number (CO2, SO2, CH4, NOx as NO2 and NO, N2O,
#: NH3, CO). CH4 and NH3 take the combustion value 1.5; the table gives 1.2 for agricultural
#: emissions of both.
BASIC_AIR = {
    "124-38-9": 1.05,
    "7446-09-5": 1.05,
    "74-82-8": 1.5,
    "10102-44-0": 1.5,
    "10102-43-9": 1.5,
    "10024-97-2": 1.5,
    "7664-41-7": 1.5,
    "630-08-0": 5.0,
}
#: Basic uncertainty of emissions to air without a CAS number, by crosswalk id
#: (data/elementary-flows.yaml): PM2.5 3.0 and NMVOC 1.5, from the same table.
BASIC_AIR_FLOW = {"particulate-matter-pm2.5": 3.0, "nmvoc": 1.5}


def basic_uncertainty(exchange: DatasetExchange) -> tuple[float, str]:
    """The basic gsd2 of *exchange* by its type, and the type's name."""
    kind = LCI_UNITS.get(exchange.unit, ("", 1.0))[0]
    if exchange.phase in ("construction", "maintenance"):
        return BASIC["infrastructure"], "infrastructure"
    if kind == "transport":
        return BASIC["transport"], "transport"
    if kind == "land-occupation":
        return BASIC["land-occupation"], "land occupation"
    if exchange.type == "resource" and kind == "area":
        return BASIC["land-transformation"], "land transformation"
    if exchange.type == "emission":
        cas = normalise_cas(exchange.cas or "")
        compartment = (
            exchange.link.elementary.compartment
            if (exchange.link is not None and exchange.link.elementary is not None)
            else "air"
        )
        if compartment == "air" and cas in BASIC_AIR:
            return BASIC_AIR[cas], f"emission to air, CAS {cas}"
        flow = _crosswalk_id(exchange)
        if compartment == "air" and flow in BASIC_AIR_FLOW:
            return BASIC_AIR_FLOW[flow], f"emission to air, {flow}"
        return BASIC["emission"], "emission (ASSUMED)"
    return BASIC["default"], "energy, material, waste or resource"


def _crosswalk_id(exchange: DatasetExchange) -> str | None:
    """The crosswalk id of an emission: as mapped (``elementary.flow``), else by its
    biosphere3 identity's name."""
    elementary = exchange.link.elementary if exchange.link is not None else None
    if elementary is not None and elementary.flow is not None:
        return elementary.flow
    names = {f.name for f in exchange.flow if f.list == "biosphere3" and f.name}
    if not names:
        return None
    from chemeascode.domains.assessment.lca.elementary import crosswalk

    return next(
        (i for i, f in crosswalk()["flows"].items() if f["biosphere3"]["name"] in names), None
    )


def geographical(location: str) -> int:
    """The geographical score of data from one plant design for a dataset declared at
    *location*: 1 for a country or site, 3 for a region, 5 when undeclared."""
    if not location:
        return 5
    return 3 if location in REGIONS or len(location.split("-")[0]) > 2 else 1


def default_pedigree(
    exchange: DatasetExchange, dataset: LciDataset, maturity: str | None = None
) -> Pedigree:
    """The default pedigree of *exchange* under :data:`RULE`."""
    origin, provenance = exchange.origin, exchange.provenance
    reliability = RELIABILITY.get(origin or "", RELIABILITY[provenance])
    technological = TECHNOLOGICAL.get(origin or "", TECHNOLOGICAL[provenance])
    technological = max(technological, MATURITY_FLOOR.get(maturity or "", 1))
    temporal = (
        TEMPORAL.get(origin or "", TEMPORAL_PROVENANCE.get(provenance, 1))
        if dataset.year is not None
        else 5
    )
    scores = [
        reliability,
        COMPLETENESS,
        temporal,
        geographical(dataset.location),
        technological,
    ]
    basis = f"{origin or provenance}"
    if maturity:
        basis += f", design maturity {maturity}"
    floor = dataset.generation.pedigree_floor if dataset.generation else None
    if floor:
        # a generated dataset's tier caps its quality (pre-release issue 182): no score better than
        # its floor
        scores = [max(s, f) for s, f in zip(scores, floor, strict=True)]
        basis += f", Tier {dataset.generation.tier} floor"
    return Pedigree(scores=scores, rule=f"{RULE} ({basis})")


def score(dataset: LciDataset, maturity: str | None = None) -> LciDataset:
    """*dataset* with a pedigree and a basic uncertainty on every exchange that has none."""
    exchanges = []
    for exchange in dataset.exchanges:
        update: dict[str, Any] = {}
        if exchange.pedigree is None:
            update["pedigree"] = default_pedigree(exchange, dataset, maturity)
        if exchange.basic_uncertainty is None:
            update["basic_uncertainty"] = basic_uncertainty(exchange)[0]
        exchanges.append(exchange.model_copy(update=update) if update else exchange)
    return dataset.model_copy(update={"exchanges": exchanges})


def gsd2(exchange: DatasetExchange) -> float | None:
    """The lognormal gsd2 of *exchange*'s pedigree on its basic uncertainty (None without a
    pedigree)."""
    if exchange.pedigree is None:
        return None
    basic = exchange.basic_uncertainty or basic_uncertainty(exchange)[0]
    return pedigree_gsd2(list(exchange.pedigree.scores), basic)


@dataclass
class Rating:
    """The data quality of a dataset (see the module docstring)."""

    TeR: float
    GeR: float
    TiR: float
    #: The TfS DQR: (TeR + GeR + TiR) / 3.
    dqr: float
    #: PEF-style: precision (from reliability), completeness, and their DQR.
    P: float
    C: float
    dqr_pef: float
    #: The primary data share (0 to 1).
    primary_share: float
    #: Weighted by the exchanges' absolute contributions to ``basis``, or the unweighted
    #: unit-process value (a simplification).
    weighted: bool
    basis: str
    #: The worst of TeR, GeR and TiR (the TfS DQR's indicators).
    weakest: str
    exchanges: int

    def as_dict(self) -> dict[str, Any]:
        return {k: (round(v, 4) if isinstance(v, float) else v) for k, v in asdict(self).items()}


def _counted(exchange: DatasetExchange) -> bool:
    """Exchanges the rating reads: not the products, not what carries no burden or only
    stands for its components (a vent counted by its emissions)."""
    from chemeascode.domains.assessment.lca.allocation import _released

    return exchange.type != "product" and not exchange.free and not _released(exchange)


def rating(
    dataset: LciDataset, contributions: dict[str, float] | None = None, basis: str = ""
) -> Rating | None:
    """The data quality rating of *dataset* (scored, :func:`score`), weighted by
    *contributions* (exchange key -> its contribution in the category *basis*) where they are
    given and not all 0; None without an exchange to rate."""
    rated = [e for e in dataset.exchanges if _counted(e) and e.pedigree is not None]
    if not rated:
        return None
    weights = {e.key: abs((contributions or {}).get(e.key, 0.0)) for e in rated}
    weighted = sum(weights.values()) > 0
    if not weighted:
        weights = {e.key: 1.0 for e in rated}
    total = sum(weights.values())

    def mean(index: int) -> float:
        return sum(weights[e.key] * e.pedigree.scores[index] for e in rated) / total

    reliability, completeness, temporal, geo, tech = (mean(i) for i in range(5))
    # the weakest of the DQR's own indicators (P and C are reported beside it)
    indicators = {"TeR": tech, "GeR": geo, "TiR": temporal}
    primary = sum(weights[e.key] for e in rated if e.origin == "measured") / total
    return Rating(
        TeR=tech,
        GeR=geo,
        TiR=temporal,
        dqr=(tech + geo + temporal) / 3,
        P=reliability,
        C=completeness,
        dqr_pef=(tech + geo + temporal + reliability) / 4,
        primary_share=primary,
        weighted=weighted,
        basis=basis if weighted else "unit process (unweighted)",
        weakest=max(indicators, key=lambda k: (indicators[k], -list(indicators).index(k))),
        exchanges=len(rated),
    )
