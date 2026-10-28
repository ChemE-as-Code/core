"""Cut-off criteria and system-model consistency of an LCI dataset (pre-release issue 180).

A dataset records the flows it leaves out (``cutoff:``, :class:`~.schemas.CutoffFlow`) with their
amounts, so that the criteria can be checked where the dataset is made (``cheme assess lca``)
and where it is used (the process library's build reads the same fields). ISO 14044 4.2.3.3
names the types of cut-off criteria (mass, energy, environmental significance) but gives no
number. The numbers are the Atlas choice (process-library docs/system-model.md, #52):

- a cut flow is below :data:`SHARE` (1 %) of the process's input mass;
- all cut flows together are below :data:`SHARE` of it: the sum counts the cut outputs and the
  cut inputs alike against the input mass (ISO asks for similar criteria for outputs);
- never cut: a precious or critical metal named in the ``contains`` of any cut flow (a catalyst,
  an adsorbent or any other), or a flow with a high characterisation factor
  (:data:`HIGH_CF_CAS`, :data:`HEAVY_METALS`).

The input mass is every input and resource of the operation counted in kg, plus the cut inputs.
Cooling water is not part of it: the flowsheet counts it as a duty (kWh, carrier ``cold``), so it
is outside the mass basis by construction; a cut flow given in another unit than kg cannot be
checked against the mass rule and is reported as such.

:func:`findings` also checks the system model: a dataset of a non-crediting model (cutoff, apos,
unset) holds no avoided-burden credit (the schema refuses ``avoided:`` exchanges there; a
negative input elsewhere is reported).
"""

from __future__ import annotations

import re

from chemeascode.domains.assessment.lca.methods import normalise_cas
from chemeascode.domains.assessment.lca.schemas import CREDITING_MODELS, LciDataset
from chemeascode.foundation.findings import Finding

#: A cut flow's share of the input mass, and the cut flows' share in sum, must stay below it.
SHARE = 0.01

#: Metals that are never cut: the platinum-group metals and the other precious metals (Au, Ag are
#: listed as precious metals; they are not CRMA materials), and critical raw materials used in
#: catalysts and adsorbents (the EU Critical Raw Materials Act, Regulation (EU) 2024/1252, is the
#: reference for "critical"; not every metal below is named in its annexes). A curated list of
#: this project, not a copy of any annex.
NEVER_CUT_METALS = frozenset(
    {
        # platinum-group metals and the other precious metals
        "Pt", "Pd", "Rh", "Ru", "Ir", "Os", "Au", "Ag",
        # critical raw materials used in catalysts and adsorbents
        "Co", "Ni", "Cu", "V", "W", "Sb", "Bi", "Ga", "Ge", "Mn", "Nb", "Ta",
        # rare earths (cracking catalysts, autocatalysts)
        "La", "Ce", "Pr", "Nd", "Sm", "Eu", "Gd", "Tb", "Dy", "Ho", "Er", "Tm", "Yb", "Lu",
        "Y", "Sc",
    }
)  # fmt: skip
#: Heavy metals whose emissions are never cut (the heavy metals of the UNECE CLRTAP Aarhus
#: protocol, Cd, Hg, Pb, and those the EMEP/EEA air pollutant emission inventory guidebook
#: reports beside them): by element symbol.
HEAVY_METALS = frozenset({"Cd", "Hg", "Pb", "As", "Cr", "Cu", "Ni", "Se", "Zn"})
#: Their CAS numbers (the elements).
_HEAVY_METAL_CAS = {
    "7440-43-9": "Cd",
    "7439-97-6": "Hg",
    "7439-92-1": "Pb",
    "7440-38-2": "As",
    "7440-47-3": "Cr",
    "7440-50-8": "Cu",
    "7440-02-0": "Ni",
    "7782-49-2": "Se",
    "7440-66-6": "Zn",
}
#: Flows with a high characterisation factor, by CAS number: N2O, SF6, NF3, the
#: perfluorocarbons CF4 and C2F6, the common HFCs and the CFCs, HCFC-22, CCl4 and halons
#: (100-year GWPs of hundreds to tens of thousands, IPCC AR6 WG1 chapter 7, table 7.SM.7).
HIGH_CF_CAS = {
    "10024-97-2": "N2O",
    "2551-62-4": "SF6",
    "7783-54-2": "NF3",
    "75-73-0": "CF4 (PFC-14)",
    "76-16-4": "C2F6 (PFC-116)",
    "75-46-7": "HFC-23",
    "75-10-5": "HFC-32",
    "354-33-6": "HFC-125",
    "811-97-2": "HFC-134a",
    "420-46-2": "HFC-143a",
    "75-37-6": "HFC-152a",
    "431-89-0": "HFC-227ea",
    "690-39-1": "HFC-236fa",
    "460-73-1": "HFC-245fa",
    "406-58-6": "HFC-365mfc",
    # ozone-depleting gases that are also strong greenhouse gases (refrigerant and solvent losses)
    "75-69-4": "CFC-11",
    "75-71-8": "CFC-12",
    "76-13-1": "CFC-113",
    "75-45-6": "HCFC-22",
    "56-23-5": "CCl4",
    "353-59-3": "halon-1211",
    "75-63-8": "halon-1301",
}


_ENERGY = re.compile(
    r"incinerat|energy[- ]recovery|waste[- ]to[- ]energy|co[- ]?processing|cement[- ]kiln"
    r"|pyrolysis|gasification|(?:as|to)[- ]fuel|fuel[- ]blending|burn",
    re.IGNORECASE,
)


def input_mass(dataset: LciDataset) -> float:
    """The process's input mass per its basis: inputs and resources of the operation in kg
    (avoided production and duties excluded), plus the cut inputs in kg."""
    counted = sum(
        e.amount
        for e in dataset.exchanges
        if e.type in ("input", "resource")
        and e.unit == "kg"
        and e.phase == "operation"
        and e.amount > 0
        and not (e.carrier is not None and e.carrier.kind == "cold")
    )
    cut = sum(
        c.amount
        for c in dataset.cutoff
        if c.direction == "input" and c.unit == "kg" and c.amount is not None
    )
    return counted + cut


def never_cut(flow) -> str:
    """Why *flow* (a :class:`~.schemas.CutoffFlow`) may never be cut, or ``""``."""
    cas = normalise_cas(flow.cas or "") if flow.cas else ""
    if cas in HIGH_CF_CAS:
        return f"a high characterisation factor ({HIGH_CF_CAS[cas]})"
    if cas in _HEAVY_METAL_CAS:
        return f"a heavy metal ({_HEAVY_METAL_CAS[cas]})"
    elements = {e.strip() for e in flow.contains}
    if elements & NEVER_CUT_METALS:
        kind = "a catalyst" if flow.catalyst else "a flow"
        return f"{kind} with {', '.join(sorted(elements & NEVER_CUT_METALS))}"
    if elements & HEAVY_METALS:
        # an emission, or an input such as a Cr-based catalyst
        what = "a release of" if flow.direction == "output" else "an input with"
        return f"{what} heavy metals ({', '.join(sorted(elements & HEAVY_METALS))})"
    return ""


def findings(dataset: LciDataset, path: str, background: bool = False) -> list[Finding]:
    """What breaks the cut-off criteria or the system model in *dataset* (read from *path*).

    Rules: ``cheme.lca-cutoff-share`` (a flow at or above 1 % of the input mass),
    ``cheme.lca-cutoff-sum`` (the cut flows together), ``cheme.lca-cutoff-never`` (a never-cut
    flow), ``cheme.lca-cutoff-unchecked`` (no amount, or not a mass: info) and
    ``cheme.lca-cutoff-credit`` (a negative input in a non-crediting system model: a warning for
    the plant's own dataset; for a loaded *background* dataset that states no system model an
    info only), and ``cheme.lca-recyclable-energy`` (a recyclable whose route is incineration or
    energy recovery: that is a waste, its burden stays with the producer)."""
    found: list[Finding] = []

    def add(level: str, rule: str, message: str, ids: list[str], hint: str) -> None:
        found.append(Finding(path, level, rule, message, ids=ids, hint=hint))  # type: ignore[arg-type]

    if dataset.system_model not in CREDITING_MODELS:
        negative = [e.key for e in dataset.exchanges if e.type == "input" and e.amount < 0]
        if negative:
            add(
                "info" if background and dataset.system_model is None else "warning",
                "cheme.lca-cutoff-credit",
                f"negative inputs in a dataset of system model "
                f"{dataset.system_model or 'unset (cutoff)'}: {', '.join(negative)}: a cut-off "
                "dataset holds no avoided-burden credits",
                negative,
                "classify the output (treatment: kind recyclable) and leave credits to a "
                "substitution build (system_model: substitution)",
            )
    for e in dataset.exchanges:
        if (
            e.treatment is not None
            and e.treatment.kind == "recyclable"
            and _ENERGY.search(e.treatment.route)
        ):
            add(
                "warning",
                "cheme.lca-recyclable-energy",
                f"{e.key} is a recyclable, but its route is {e.treatment.route!r}: incineration "
                "and energy recovery are not recycling; in the cut-off model the burden of the "
                "incineration stays with the waste producer",
                [e.key],
                "classify it as kind: waste linked to its incineration; only the recovered "
                "energy leaves burden-free (credit it in a substitution variant)",
            )
    if not dataset.cutoff:
        return found
    basis = input_mass(dataset)
    unchecked, total = [], 0.0
    for flow in dataset.cutoff:
        why = never_cut(flow)
        if why:
            add(
                "warning",
                "cheme.lca-cutoff-never",
                f"cut flow {flow.key} is {why}: never cut",
                [flow.key],
                "count it (an exchange with its background, or missing: when none is available)",
            )
        if flow.catalyst and not flow.contains:
            add(
                "info",
                "cheme.lca-cutoff-catalyst-metals",
                f"cut catalyst {flow.key} states no metals (contains): the never-cut rule for "
                "precious and critical metals cannot be checked",
                [flow.key],
                "list its element symbols in contains (Pt, Ni, ...), or state that it holds none",
            )
        if flow.amount is None or flow.unit != "kg" or basis <= 0:
            unchecked.append(flow.key)
            continue
        total += flow.amount
        share = flow.amount / basis
        if share >= SHARE:
            add(
                "warning",
                "cheme.lca-cutoff-share",
                f"cut flow {flow.key} is {share:.2%} of the input mass ({basis:.6g} kg per "
                f"{dataset.basis}): the criterion is below {SHARE:.0%}",
                [flow.key],
                "count it, or check its amount",
            )
    if basis > 0 and total / basis >= SHARE:
        add(
            "warning",
            "cheme.lca-cutoff-sum",
            f"the cut flows together are {total / basis:.2%} of the input mass: the criterion "
            f"is below {SHARE:.0%}",
            [f.key for f in dataset.cutoff],
            "count the largest of them",
        )
    if unchecked:
        add(
            "info",
            "cheme.lca-cutoff-unchecked",
            f"cut flows the mass criterion cannot check (no amount, or not in kg): "
            f"{', '.join(unchecked)}",
            unchecked,
            "give each its amount in kg (cutoff: per_year, unit kg) so that the 1 % rule can "
            "be checked",
        )
    return found
