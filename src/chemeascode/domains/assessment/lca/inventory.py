"""The plant's LCI: an unallocated dataset derived from the flowsheet, then per functional unit.

:func:`derive` builds the plant's unallocated LCI dataset (``kind: lci_dataset``, per hour of
operation) from its flowsheet, ``lca/lca.yaml`` and the construction inputs; :func:`inventory`
allocates it (:mod:`.allocation`) per functional unit of the study. Everything below describes
what the dataset holds.

:func:`inventory` reads the flowsheet's terminals in one case: every feed and product, each the
sum of the streams that reach it. A material terminal counts in kg/h (the mass flow,
``process.model.stream_flows``), an energy terminal in kWh/h (the stream duties in kW). A product
mapped ``emission: true`` is split into its components, ``emission:<component>`` in kg/h.

The burdens are then shared between the co-products (``allocation`` of ``lca/lca.yaml``):

- ``mass``: share of the functional unit's product = its mass flow / the co-products' total;
- ``economic``: the same with mass flow x price;
- ``none``: the functional unit's product carries everything.

Every flow that is not a co-product is scaled by ``share x FU / product flow``, so the inventory
reads "per functional unit". The co-products are listed with what is made alongside one
functional unit (unallocated), so a reader sees the multifunctionality.

Balances are not recomputed here: the flows are what the flowsheet holds, with the provenance
of each stream value. A feed's or product's exchange takes the ``uncertainty`` of its
``flows:`` entry, else the one its streams' flows (or duties) give in the flowsheet, else none
(the Monte Carlo then uses the study's default for its provenance).

The construction phase (``construction:``, :mod:`.construction`) adds the plant's materials:
take-off rows and equipment weights, in total, spread over the functional unit's product made in
the plant's life (``operation``: hours per year x life) and shared like the operation:
``share x FU / (product flow x hours x years)``.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from fnmatch import fnmatchcase

from chemeascode.domains.assessment.flows import Terminal as _Terminal
from chemeascode.domains.assessment.flows import common as _common
from chemeascode.domains.assessment.flows import terminals as _terminals
from chemeascode.domains.assessment.lca.allocation import (
    RELEASED,
    TAKEN,
    AllocatedRow,
    allocate,
    applicable,
)
from chemeascode.domains.assessment.lca.carbon import (
    CarbonTrace,
    Load,
    carbon_fractions,
    contents,
    split_emissions,
    trace,
)
from chemeascode.domains.assessment.lca.construction import construction
from chemeascode.domains.assessment.lca.documentation import document
from chemeascode.domains.assessment.lca.elementary import (
    WATER_CAS,
    crosswalk,
    identities,
    unverified,
)
from chemeascode.domains.assessment.lca.emissions import (
    ESTIMATED,
    RULE_ADDED,
    RULE_INCOMPLETE,
    RULE_SIMULATED,
)
from chemeascode.domains.assessment.lca.emissions import Context as EmissionContext
from chemeascode.domains.assessment.lca.emissions import estimate as estimate_emissions
from chemeascode.domains.assessment.lca.emissions import incomplete as emissions_incomplete
from chemeascode.domains.assessment.lca.emissions import sources as emission_sources
from chemeascode.domains.assessment.lca.methods import normalise_cas
from chemeascode.domains.assessment.lca.quality import score
from chemeascode.domains.assessment.lca.schemas import (
    CREDITING_MODELS,
    DATASET_SCHEMA,
    EXCHANGE_PROVENANCE,
    FACTOR_UNITS,
    INVENTORY_UNITS,
    NON_ROUTINE,
    Background,
    CarbonContent,
    Carrier,
    Composition,
    CutoffFlow,
    DatasetExchange,
    DatasetProvenance,
    Elementary,
    LcaFile,
    LciDataset,
    ProductProperties,
    ProductState,
    Treatment,
)
from chemeascode.domains.assessment.mto import MtoRow
from chemeascode.domains.equipment.schemas.equipment import EquipmentItem
from chemeascode.domains.process.model import Process
from chemeascode.foundation.findings import Finding

LCA_FILE = "lca/lca.yaml"
FLOWSHEET_FILE = "process/flowsheet.yaml"

#: Provenance of a row made of several values: the weakest of them.
_ORDER = EXCHANGE_PROVENANCE


#: One row of the inventory per functional unit (see :class:`.allocation.AllocatedRow`): key
#: (``feed:``, ``product:``, ``emission:``, ``construction:``, ``substitution:``), title,
#: direction, kind, the plant's amount and its unit, the quantity per functional unit, provenance,
#: streams (or take-off rows), mapping and phase.
InventoryRow = AllocatedRow


@dataclass
class Inventory:
    """The operation's foreground inventory per functional unit."""

    case: str
    #: e.g. ``1 t GOXP``.
    functional_unit: str
    #: Allocation method and the share of each co-product's burdens (sums to 1).
    method: str
    shares: dict[str, float] = field(default_factory=dict)
    rows: list[InventoryRow] = field(default_factory=list)
    findings: list[Finding] = field(default_factory=list)
    #: What the dataset's flows and carriers lack (info, warnings): reported after everything
    #: else, as they never stop the LCA.
    notes: list[Finding] = field(default_factory=list)
    #: The mapping of each row with a background, by key: what the backends characterise.
    backgrounds: dict[str, Background] = field(default_factory=dict)
    #: The plant's unallocated LCI dataset (None when the flowsheet does not give one).
    dataset: LciDataset | None = None
    #: Every allocation method: its shares, or why it does not apply.
    comparison: list[tuple[str, dict[str, float] | None, str]] = field(default_factory=list)
    #: Factor from the dataset's basis (1 h) to the plant's total, by phase (construction).
    totals: dict[str, float] = field(default_factory=dict)
    #: The functional unit in the reference product's inventory unit (kg, or kWh for an energy
    #: product): what allocation scales to.
    amount: float = 0.0
    #: What the construction leaves out without a quantity: (key, reason, detail), e.g. an
    #: item without a weight (``no-weight``) or a take-off row no entry counts
    #: (``unmatched``). Gaps of every category, never counted as 0.
    unknown: list[tuple[str, str, str]] = field(default_factory=list)
    #: What each material input is, by key: its state (phase, pressure, purity, main component)
    #: and that component's CAS number, from the flowsheet (not written into the dataset).
    inputs: dict[str, tuple[ProductState, str]] = field(default_factory=dict)
    #: The carbon traced through the dataset (:class:`.carbon.CarbonTrace`) when the study
    #: declares carbon_accounting; else None.
    carbon: CarbonTrace | None = None


def _line(text: str | None, needle: str) -> int | None:
    """The 1-based line of *text* holding *needle* first, if any."""
    if not text:
        return None
    for number, line in enumerate(text.splitlines(), 1):
        if needle in line:
            return number
    return None


def _weakest(values: list[str]) -> str:
    known = [v for v in values if v in _ORDER]
    return max(known, key=_ORDER.index) if known else "assumed"


def inventory(
    process: Process,
    scope: LcaFile,
    lca_text: str | None = None,
    takeoff: list[MtoRow] | None = None,
    equipment: list[EquipmentItem] | None = None,
    maturity: str | None = None,
    load: Load | None = None,
) -> Inventory:
    """The foreground inventory of *process* per functional unit of *scope*; the construction
    from the take-off rows *takeoff* and the *equipment* items (None: not available). Every
    exchange of the dataset gets the default pedigree where it has none (:mod:`.quality`), for
    a design of *maturity* (process.yaml, None: not capped). With ``carbon_accounting``, every
    material exchange gets its carbon content and the carbon is traced (:mod:`.carbon`), through
    the datasets *load* reads where inputs reference them."""
    fs = process.flowsheet
    case = scope.case or fs.default_case()
    fu = scope.functional_unit
    result = Inventory(case, f"{fu.amount:g} {fu.unit} {fu.product}", scope.allocation.method)

    def problem(level: str, rule: str, message: str, needle: str, hint: str, ids=()) -> None:
        result.findings.append(
            Finding(
                LCA_FILE,
                level,  # type: ignore[arg-type]
                rule,
                message,
                line=_line(lca_text, needle),
                ids=list(ids),
                hint=hint,
            )
        )

    # what the dataset's flows and carriers lack: reported after the inventory's own findings
    later: list[Finding] = []

    def note(level: str, rule: str, message: str, needle: str, hint: str, ids=()) -> None:
        before = len(result.findings)
        problem(level, rule, message, needle, hint, ids)
        later.append(result.findings.pop(before))

    if case not in {c.id for c in fs.cases}:
        problem(
            "error",
            "cheme.lca-case",
            f"case {case!r} is not a case of {FLOWSHEET_FILE}",
            "case:",
            f"use one of {', '.join(c.id for c in fs.cases)}",
        )
        return result
    terminals = {t.key: t for t in _terminals(process, case)}
    broken = False
    for terminal in terminals.values():
        if not terminal.streams:
            problem(
                "warning",
                "cheme.lca-flow-none",
                f"{terminal.key}: no stream reaches it in {FLOWSHEET_FILE}; it counts as 0",
                terminal.key,
                "connect it, or remove the feed or product",
                [terminal.key],
            )
        if len(terminal.kinds) > 1:
            broken = True
            problem(
                "error",
                "cheme.lca-flow-mixed",
                f"{terminal.key}: material and energy streams ({', '.join(terminal.streams)}) "
                "reach the same terminal; kg/h and kWh/h cannot be summed",
                terminal.key,
                "give utilities their own feed or product (e.g. POWER, CW)",
                [terminal.key],
            )
        if terminal.invalid:
            broken = True
            problem(
                "error",
                "cheme.lca-flow-invalid",
                f"{terminal.key}: cannot count {'; '.join(terminal.invalid)}",
                terminal.key,
                f"correct the stream state in {FLOWSHEET_FILE} (case {case})",
                [terminal.key],
            )
        if terminal.stale_exergy:
            problem(
                "warning",
                "cheme.lca-exergy-stale",
                f"{terminal.key}: the calculated exergy of {', '.join(terminal.stale_exergy)} is "
                "stale (its inputs changed); it is not used",
                terminal.key,
                "run cheme process props --fill",
                [terminal.key],
            )
        if terminal.missing:
            problem(
                "warning",
                "cheme.lca-flow-incomplete",
                f"{terminal.key}: the flowsheet lacks {', '.join(terminal.missing[:4])}; the "
                "inventory counts the rest",
                terminal.key,
                f"complete the stream state in {FLOWSHEET_FILE} (case {case})",
                [terminal.key],
            )
    product = terminals.get(f"product:{fu.product}")
    if product is None or product.per_hour <= 0:
        problem(
            "error",
            "cheme.lca-functional-unit",
            f"functional unit product {fu.product!r} is not a product with a flow (or duty) in "
            f"{FLOWSHEET_FILE} (case {case})",
            "product:",
            "name a product of the flowsheet whose streams carry a flow",
        )
        return result
    if broken:
        return result

    allocation = scope.allocation
    coproducts = list(dict.fromkeys([fu.product, *allocation.coproducts]))
    for name in coproducts:
        terminal = terminals.get(f"product:{name}")
        if terminal is None:
            problem(
                "error",
                "cheme.lca-coproduct",
                f"co-product {name!r} is not a product of {FLOWSHEET_FILE}",
                name,
                "list products of the flowsheet in allocation.coproducts",
                [name],
            )
            return result

    mapping = {flow.key: flow for flow in scope.flows}
    accounting = scope.carbon_accounting
    fractions = carbon_fractions(process.formulas()) if accounting is not None else {}

    def content(key: str, components: dict[str, float]) -> CarbonContent | None:
        """The carbon of a material flow: from its composition, with the study's override."""
        if accounting is None:
            return None
        given = accounting.content.get(key)
        total = given.total if given is not None else None
        mass = sum(components.values())
        if total is None and mass > 0 and all(fractions.get(c) is not None for c in components):
            total = sum(m * fractions[c] for c, m in components.items()) / mass
        if total is None and given is None:
            return None
        return CarbonContent(
            total=None if total is None else round(total, 9),
            biogenic_fraction=given.biogenic_fraction if given is not None else None,
            source=(given.source if given is not None and given.source else "")
            or ("composition and formulas" if total is not None else ""),
        )

    formulas = process.formulas()

    def composition(components: dict[str, float], streams: list[str]) -> Composition | None:
        """What a material flow is made of by mass, from the stream table (pre-release issue 174):
        every component with its formula ('' where materials.yaml gives none, so that the element
        balance names it rather than reading the id as a formula)."""
        mass = sum(components.values())
        if mass <= 0:
            return None
        fractions = {c: round(m / mass, 9) for c, m in components.items() if m > 0}
        return Composition(
            fractions=fractions,
            formulas={c: formulas.get(c) or "" for c in fractions},
            source="stream table" + (f" ({', '.join(streams)})" if streams else ""),
        )

    exchanges: list[DatasetExchange] = []
    emitted: dict[str, list[_Terminal]] = {}
    taken: dict[str, list[_Terminal]] = {}
    unmapped: list[str] = []
    nodes = {n.id: n for n in [*fs.feeds, *fs.products]}
    ambiguous: list[str] = []
    unlevelled: list[str] = []
    #: what each material input is (its state, and the CAS number of its main component)
    taken_as: dict[str, tuple[ProductState, str]] = {}
    for key, terminal in terminals.items():
        unit = "kWh" if terminal.kind == "energy" else "kg"
        carrier = None
        if terminal.kind == "energy":
            carrier = _carrier(process, nodes.get(key.split(":", 1)[1]))
            if carrier is None:
                ambiguous.append(key)
            elif _unlevelled(carrier):
                unlevelled.append(f"{key} ({_unlevelled(carrier)})")
        provenance = _weakest(terminal.provenance)
        name = key.split(":", 1)[1]
        common = {
            "key": key,
            "title": terminal.title,
            "amount": terminal.per_hour,
            "unit": unit,
            "provenance": provenance,
            "origin": terminal.origin,
            "streams": list(terminal.streams),
            # the study's own (flows:), else the flowsheet's (the flow's or duty's)
            "uncertainty": (mapping[key].uncertainty if key in mapping else None)
            or terminal.uncertainty,
            "carrier": carrier,
        }
        if terminal.kind == "material" and not terminal.unsplit:
            common["carbon"] = content(key, terminal.components)
            common["composition"] = composition(terminal.components, terminal.streams)
        elif terminal.kind == "material":
            common["carbon"] = content(key, {})
        if key in mapping and terminal.kind == "material":
            common["co2_source"] = mapping[key].co2_source
            common["storage"] = mapping[key].storage
        if name in coproducts:
            if key in mapping:
                problem(
                    "warning",
                    "cheme.lca-coproduct-mapped",
                    f"{key} is a co-product (allocation.coproducts); its flows: entry is not used",
                    key,
                    "remove the entry, or remove the product from allocation.coproducts to "
                    "count it by its mapping",
                    [key],
                )
            if terminal.kind == "energy":
                # an energy product's exergy from its carrier (electricity, Carnot factor)
                exergy, how = _carrier_exergy(carrier)
            else:
                exergy = (
                    terminal.exergy / terminal.per_hour
                    if not terminal.no_exergy and terminal.per_hour > 0
                    else None
                )
                how = f"exergy from {FLOWSHEET_FILE} (cheme process props --fill)"
            exchanges.append(
                DatasetExchange(
                    **common,
                    type="product",
                    properties=ProductProperties(exergy=exergy, source=how)
                    if exergy is not None
                    else None,
                    state=_state(process, case, terminal) if terminal.kind == "material" else None,
                )
            )
            continue
        kind = "input" if terminal.direction == "input" else "output"
        if kind == "input" and terminal.kind == "material":
            state = _state(process, case, terminal)
            if state is not None:
                main = process.components().get(state.component)
                taken_as[key] = (state, getattr(main, "cas", "") or "")
        flow = mapping.get(key)
        split = flow is not None and (flow.emission or flow.resource)
        if split:
            what = "emission" if flow.emission else "resource"
            if terminal.kind != "material":
                problem(
                    "error",
                    f"cheme.lca-{what}",
                    f"{key} is an energy terminal; only material terminals are split into {what}s",
                    key,
                    "map it to a factor or as free",
                    [key],
                )
                continue
            if terminal.unsplit:
                problem(
                    "error",
                    f"cheme.lca-{what}-components",
                    f"{key} is {'an emission' if flow.emission else 'a resource'}, but its "
                    f"components cannot be counted: {', '.join(dict.fromkeys(terminal.unsplit))}",
                    key,
                    f"give its streams a composition and every component a molar_mass "
                    f"({FLOWSHEET_FILE}, process/materials.yaml)",
                    [key],
                )
                continue
            for component in terminal.components:
                (emitted if flow.emission else taken).setdefault(component, []).append(terminal)
            marker = RELEASED if flow.emission else TAKEN
            exchanges.append(
                DatasetExchange(
                    **common, type=kind, source=f"{marker}: counted by its {what}:* exchanges"
                )
            )
            continue
        if flow is None:
            unmapped.append(key)
            exchanges.append(DatasetExchange(**common, type=kind))
        elif flow.free:
            made = DatasetExchange(**common, type=kind, free=True, source=flow.source)
            exchanges += _treated(made, flow.treatment, scope.model, problem)
        else:
            made = DatasetExchange(**common, type=kind, link=flow.background(), source=flow.source)
            exchanges += _treated(made, flow.treatment, scope.model, problem)
    unspecified: list[str] = []
    unidentified: list[tuple[str, str]] = []
    for what, components in (("emission", emitted), ("resource", taken)):
        for component, sources in sorted(components.items()):
            key = f"{what}:{component}"
            flow = mapping.get(key)
            cas = getattr(process.components().get(component), "cas", "") or None
            common = {
                "key": key,
                "cas": cas,
                "uncertainty": flow.uncertainty if flow is not None else None,
                "title": f"{component} to the environment"
                if what == "emission"
                else f"{component} from nature",
                "type": what,
                "amount": sum(t.components[component] for t in sources),
                "unit": "kg",
                "provenance": _weakest([p for t in sources for p in t.provenance]),
                "origin": _common([o for t in sources for o in t.origins]),
                "streams": [s for t in sources for s in t.streams],
            }
            common["composition"] = composition({component: 1.0}, common["streams"])
            if accounting is not None and fractions.get(component) is not None:
                common["carbon"] = CarbonContent(
                    total=round(fractions[component], 9), source="formula"
                )
            spec = flow.elementary if flow is not None else None
            if spec is None and what == "emission":
                # a free or unmapped emission states no receiving compartment (a drain is
                # water, a vent is air): its identity is never guessed, the finding names it
                unidentified.append((key, "no receiving compartment: give elementary.compartment"))
            elif spec is None and (flow is None or flow.free):
                # a free or unmapped resource is still an elementary flow: identified where the
                # crosswalk needs no origin (N2, O2, Ar, water), never guessed for carbon
                spec = Elementary(compartment="resource", subcompartment="unspecified")
                spec = spec if _origin_free(cas, spec) else None
            elif (
                spec is not None
                and "subcompartment" not in spec.model_fields_set
                and what == "emission"
            ):
                unspecified.append(key)
            identity: list = []
            if spec is not None:
                identity, why = identities(cas, spec)
                if not identity:
                    unidentified.append((key, why))
            common["flow"] = identity
            if flow is None:
                unmapped.append(key)
                exchanges.append(DatasetExchange(**common))
            elif flow.free:
                exchanges.append(DatasetExchange(**common, free=True, source=flow.source))
            else:
                exchanges.append(
                    DatasetExchange(**common, link=flow.background(), source=flow.source)
                )
    estimated_keys = _estimated(
        process,
        scope,
        case,
        terminals,
        exchanges,
        emitted,
        mapping,
        takeoff,
        equipment,
        accounting is not None and fractions,
        problem,
        unmapped,
        unspecified,
        unidentified,
    )
    if ambiguous:
        note(
            "info",
            "cheme.lca-carrier",
            f"energy terminals without a carrier (no utility kind, or other): "
            f"{', '.join(ambiguous)}",
            ambiguous[0],
            "give the terminal category utility and utility.kind (electricity, steam, "
            "hot_oil, fired_heat, fuel, cooling_water, air_cooling, refrigerant) in "
            f"{FLOWSHEET_FILE}",
            ambiguous,
        )
    if unlevelled:
        note(
            "info",
            "cheme.lca-carrier-level",
            f"energy carriers without their level: {'; '.join(unlevelled)}",
            unlevelled[0].split(" ", 1)[0],
            "give the utility its supply_temperature (heat, steam, cold) and, for steam, its "
            f"pressure and level (LP, MP, HP) in {FLOWSHEET_FILE}: the background to link and "
            "the exergy of an energy product depend on them",
            [u.split(" ", 1)[0] for u in unlevelled],
        )
    _flow_findings(note, exchanges, unspecified, unidentified)
    _completeness(process, scope, terminals, mapping, equipment, note)
    _water_findings(note, process, terminals, mapping, exchanges)
    if scope.construction:
        operation = scope.operation
        result.totals["construction"] = operation.hours_per_year * operation.life_years
        exchanges += _construction(
            scope, takeoff, equipment, result.totals["construction"], problem, result.unknown
        )
    if scope.operation is not None:
        life = scope.operation.hours_per_year * scope.operation.life_years
        for phase in ("maintenance", "end-of-life"):
            result.totals[phase] = life
    cutoff: list[CutoffFlow] = []
    if scope.construction:
        cutoff += _construction_cutoff(scope, takeoff, equipment, result.totals["construction"])
    exchanges += _supplies(scope, exchanges, problem, cutoff)
    cutoff += _study_cutoff(scope)
    cutoff += _excluded_emissions(scope)
    _system_model_findings(scope, problem)
    if any(f.level == "error" for f in result.findings):
        return result
    dataset = LciDataset(
        schema=DATASET_SCHEMA,
        kind="lci_dataset",
        id=_dataset_id(process),
        title=fs.title or "",
        description=f"Unallocated foreground LCI of {fs.title or 'the plant'}, case {case}, "
        "derived from the flowsheet by cheme assess lca.",
        scope="foreground",
        basis="1 h of operation",
        location=scope.location,
        year=scope.year,
        boundary="gate-to-gate foreground of the plant"
        + (" with its construction" if scope.construction else ""),
        technology=scope.technology,
        rights=scope.rights,
        exchanges=exchanges,
        cutoff=cutoff,
        allocation=scope.allocation,
        provenance=DatasetProvenance(generator="cheme assess lca", plant=fs.title or "", case=case),
        # recorded only when the study states it (the default build is cutoff all the same)
        system_model=scope.system_model or (scope.dataset and scope.dataset.system_model),
    )
    if accounting is not None:
        traced = trace(dataset, accounting, load)
        if accounting.trace_emissions:
            dataset = split_emissions(dataset, traced)
            traced = trace(dataset, accounting, load)
        dataset = contents(dataset, traced)
        result.carbon = traced
    dataset = score(dataset, maturity)
    result.dataset, _ = document(dataset, scope, fs.title or "plant", f"product:{fu.product}")
    result.inputs = taken_as
    reference = result.dataset.product(fu.product)
    amount, why = functional_amount(fu, reference, allocation, _molar_mass(process, product))
    if amount is None:
        problem(
            "error",
            "cheme.lca-functional-unit",
            f"functional unit {fu.amount:g} {fu.unit} {fu.product}: {why}",
            "functional_unit:",
            "give functional_unit.kg_per_unit with its source, or a unit of the product's kind",
        )
        return result
    result.amount = amount
    allocated = allocate(
        result.dataset, fu.product, amount, allocation.method, allocation, result.totals
    )
    if allocated.problem:
        problem(
            "error",
            "cheme.lca-allocation",
            f"{allocation.method} allocation: {allocated.problem}",
            "allocation:",
            "complete the products' data (prices, energy content, exergy: cheme process "
            "props --fill, or allocation.properties), the shares or the substitutes",
        )
        return result
    result.shares = {k: v for k, v in allocated.shares.items() if k in coproducts}
    result.rows = allocated.rows
    result.backgrounds = allocated.backgrounds
    methods = allocation.compare
    result.comparison = [
        entry
        for entry in applicable(result.dataset, fu.product, allocation)
        if methods is None or entry[0] in methods or entry[0] == allocation.method
    ]
    if unmapped:
        problem(
            "warning",
            "cheme.lca-unmapped",
            f"{len(unmapped)} flows have no background in {LCA_FILE}: {', '.join(unmapped)}; "
            "they carry no impact",
            "flows:",
            "add a flows: entry for each (factor: <id>, free: true, or emission: true for a "
            "product released to the environment), with its source",
            unmapped,
        )
    known = (
        set(terminals)
        | {f"emission:{c}" for c in emitted}
        | {f"resource:{c}" for c in taken}
        | estimated_keys
    )
    stray = [flow.key for flow in scope.flows if flow.key not in known]
    if stray:
        problem(
            "warning",
            "cheme.lca-flow-unknown",
            f"flows: entries that are no flow of case {case}: {', '.join(stray)}",
            stray[0],
            "remove them, or check the feed, product or component id",
            stray,
        )
    result.notes += later
    return result


#: The carrier of each utility kind of a terminal (process/flowsheet.yaml ``utility.kind``):
#: cooling water, air cooling and refrigerants deliver cold (heat rejected at their level).
UTILITY_CARRIERS = {
    "electricity": "electricity",
    "steam": "steam",
    "hot_oil": "heat",
    "fired_heat": "heat",
    "fuel": "fuel",
    "cooling_water": "cold",
    "air_cooling": "cold",
    "refrigerant": "cold",
}
#: Dead-state temperature of the exergy (K), as in cheme process props.
T0 = 298.15
#: Ambient pressure a gauge pressure is read against, kPa (the standard atmosphere).
AMBIENT_KPA = 101.325


def _celsius(quantity, default_unit: str) -> float | None:
    from chemeascode.foundation.units import UnitError, convert_units

    if quantity is None:
        return None
    try:
        return convert_units(quantity.value, quantity.unit or default_unit, "°C")
    except UnitError:
        return None


def _bar_abs(quantity, default_unit: str) -> float | None:
    from chemeascode.foundation.units import UnitError, convert_units

    if quantity is None:
        return None
    try:
        unit = quantity.unit or default_unit
        return convert_units(quantity.value, unit, "bar(a)", ambient_kpa=AMBIENT_KPA)
    except UnitError:
        return None


def _carrier(process: Process, node) -> Carrier | None:
    """The carrier of an energy terminal from its utility kind, level, supply temperature and
    (steam) pressure (the migration of v1's bare kWh, pre-release issue 177; levels
    pre-release issue 313); None where the flowsheet does not say."""
    utility = getattr(node, "utility", None)
    kind = UTILITY_CARRIERS.get(getattr(utility, "kind", None) or "")
    if kind is None:
        return None
    units = process.flowsheet.units
    temperature = pressure = None
    if kind in ("heat", "steam", "cold"):
        temperature = _celsius(utility.supply_temperature, units.temperature)
    if kind == "steam":
        pressure = _bar_abs(utility.pressure, units.pressure)
    return Carrier(
        kind=kind,
        temperature=None if temperature is None else round(temperature, 6),
        pressure=None if pressure is None or pressure <= 0 else round(pressure, 6),
        level=utility.level if kind != "electricity" else "",
        source=f"utility of {node.id} in {FLOWSHEET_FILE}",
    )


def _unlevelled(carrier: Carrier) -> str:
    """What a heat, steam or cold carrier lacks of its level ("" when nothing)."""
    if carrier.kind not in ("heat", "steam", "cold"):
        return ""
    lacking = [] if carrier.temperature is not None else ["temperature"]
    if carrier.kind == "steam" and carrier.pressure is None:
        lacking.append("pressure")
    return ", ".join(lacking)


def _carrier_exergy(carrier: Carrier | None) -> tuple[float | None, str]:
    """Exergy per kWh (kJ) of an energy product: 3600 for electricity; heat or steam at T,
    3600 (1 - T0/T); cold at T < T0, 3600 (T0/T - 1) (the Carnot factor, T0 = 298.15 K)."""
    if carrier is None:
        return None, ""
    if carrier.kind == "electricity":
        return 3600.0, "exergy of electricity: 3600 kJ/kWh"
    if carrier.temperature is None or carrier.kind == "fuel":
        return None, ""
    t = carrier.temperature + 273.15
    factor = 1 - T0 / t if carrier.kind != "cold" else T0 / t - 1
    if factor <= 0:
        return None, ""
    how = f"Carnot factor at {carrier.temperature:g} °C, T0 = {T0} K"
    return round(3600.0 * factor, 6), how


def _state(process: Process, case: str, terminal) -> ProductState | None:
    """A material product's state from its streams in *case*: what every stream agrees on."""
    fs = process.flowsheet
    streams = {s.id: s for s in fs.streams}
    states = [streams[i].state.get(case) for i in terminal.streams if i in streams]
    states = [s for s in states if s is not None]
    if not states:
        return None
    phases = {"vapor": "gas", "liquid": "liquid", "two-phase": "two-phase"}
    phase = _common([phases.get(s.phase.value) if s.phase else None for s in states])
    pressure = _common([_bar_abs(s.pressure, fs.units.pressure) for s in states])
    temperature = _common([_celsius(s.temperature, fs.units.temperature) for s in states])
    purity = component = basis = None
    compositions = [s.composition for s in states]
    if all(c is not None for c in compositions):
        main = _common([max(c.values, key=c.values.get) for c in compositions])
        fraction = _common([c.values.get(main) for c in compositions]) if main else None
        kind = _common([c.basis for c in compositions])
        if main and fraction and kind:
            purity, component = fraction, main
            basis = "mole" if kind == "mole_fraction" else "mass"
    if all(v is None for v in (phase, pressure, temperature, purity)):
        return None
    return ProductState(
        phase=phase,
        pressure=None if pressure is None else round(pressure, 6),
        temperature=None if temperature is None else round(temperature, 6),
        purity=purity,
        basis=basis,
        component=component or "",
    )


def _molar_mass(process: Process, terminal) -> float | None:
    """The mean molar mass (kg/kmol) of a material terminal from its components' flows."""
    if terminal is None or not terminal.components:
        return None
    components = process.components()
    moles = 0.0
    for name, kg in terminal.components.items():
        molar_mass = getattr(components.get(name), "molar_mass", None)
        if not molar_mass:
            return None
        moles += kg / molar_mass
    total = sum(terminal.components.values())
    return total / moles if moles > 0 else None


def functional_amount(
    fu, product: DatasetExchange | None, allocation, molar_mass: float | None
) -> tuple[float | None, str]:
    """The functional unit *fu* in *product*'s inventory unit (pre-release issue 177), or ``(None,
    why)``: the same kind directly; a material product per gas volume through *molar_mass* (ideal
    gas at the unit's reference state), per energy through its energy content (kJ/kg, e.g. LHV), or
    per item through ``kg_per_unit``."""
    from chemeascode.domains.assessment.lca.allocation import properties
    from chemeascode.foundation.units import LCI_UNITS, gas_volume_to_kg

    if product is None:
        return None, "not a product of the dataset"
    kind, factor = LCI_UNITS[fu.unit]
    own = LCI_UNITS[product.unit][0]
    if fu.kg_per_unit is not None and own == "mass":
        return fu.amount * fu.kg_per_unit, ""
    if kind == own:
        return fu.amount * factor, ""
    if own != "mass":
        return None, f"{product.key} is counted in {product.unit}, not convertible from {fu.unit}"
    if kind == "normal-volume":
        if molar_mass is None:
            return None, "no molar mass of the product (composition and molar masses)"
        return gas_volume_to_kg(fu.amount, fu.unit, molar_mass), ""
    if kind == "energy":
        energy = properties(product, allocation).energy
        if not energy:
            return None, "no energy content of the product (allocation.properties.<id>.energy)"
        return fu.amount * factor * 3600.0 / energy, ""
    return None, f"a {kind} functional unit needs kg_per_unit"


def _origin_free(cas: str | None, spec: Elementary) -> bool:
    """Whether the crosswalk identifies *cas* in *spec*'s compartment without an origin (the
    flow of a free or unmapped exchange is identified only then)."""
    if cas is None:
        return False
    found = [
        f
        for f in crosswalk()["flows"].values()
        if f.get("cas") == normalise_cas(cas)
        and f["compartment"] == spec.compartment
        and f.get("default", True)
    ]
    return len(found) == 1 and "origin" not in found[0]


def _flow_findings(problem, exchanges, unspecified, unidentified) -> None:
    """The elementary flows' identities: a sub-compartment left unspecified, a flow the
    crosswalk does not hold, and identities without their EF 3.1 UUID (pre-release issue 175)."""
    if unspecified:
        problem(
            "info",
            "cheme.lca-subcompartment",
            f"{len(unspecified)} elementary emissions give no subcompartment and count as "
            f"unspecified: {', '.join(unspecified)}",
            "elementary:",
            "give elementary.subcompartment (air: urban-close-to-ground, non-urban-high-stack, "
            "lower-stratosphere; water: fresh-surface, ground, sea; soil: agricultural, "
            "industrial) where the release point is known: methods characterise them apart",
            unspecified,
        )
    if unidentified:
        problem(
            "info",
            "cheme.lca-flow-identity",
            "elementary flows without an identity in a reference list: "
            + "; ".join(f"{k} ({why})" for k, why in unidentified),
            "elementary:",
            "name a crosswalk flow (elementary.flow), or extend the curated crosswalk "
            "(domains/assessment/lca/data/elementary-flows.yaml) with a verified identifier",
            [k for k, _ in unidentified],
        )
    pending = [e.key for e in exchanges if e.flow and unverified(e.flow)]
    if pending:
        problem(
            "info",
            "cheme.lca-flow-uuid",
            f"{len(pending)} elementary flows have no verified EF 3.1 UUID yet (uuid: null; "
            f"biosphere3 given): {', '.join(pending)}",
            "elementary:",
            "a TODO of the packaged crosswalk: its EF 3.1 UUIDs are added from the reference "
            "package, never guessed",
            pending,
        )


def _water_findings(problem, process, terminals, mapping, exchanges) -> None:
    """A water feed (water its main component by mass) taken free or unmapped, or a
    cooling-water duty mapped free or unmapped, without a water resource flow: the withdrawal
    is invisible (pre-release issue 175). The moisture of an air intake is not a withdrawal."""
    if any(e.type == "resource" and normalise_cas(e.cas or "") == WATER_CAS for e in exchanges):
        return
    nodes = {n.id: n for n in [*process.flowsheet.feeds, *process.flowsheet.products]}
    components = process.components()
    hidden = []
    for key, terminal in terminals.items():
        flow = mapping.get(key)
        if flow is not None and not flow.free:
            continue  # linked: its background holds the water (or it is split)
        node = nodes.get(key.split(":", 1)[1])
        utility = getattr(getattr(node, "utility", None), "kind", None)
        total = sum(terminal.components.values())
        h2o = sum(
            kg
            for c, kg in terminal.components.items()
            if normalise_cas(getattr(components.get(c), "cas", "") or "") == WATER_CAS
        )
        water = terminal.direction == "input" and total > 0 and h2o > total / 2
        if water or utility == "cooling_water":
            hidden.append(key)
    if hidden:
        problem(
            "warning",
            "cheme.lca-water-resource",
            f"no water resource flow, but {', '.join(hidden)} take or reject water free or "
            "unmapped: the water withdrawal and consumption are not counted",
            hidden[0],
            "map a water feed resource: true (each component a resource:<component> flow, "
            "water by its source, e.g. elementary: {compartment: resource, flow: water-river}), "
            "or link the feed or the cooling duty to a background that holds the water",
            hidden,
        )


def _estimated(
    process: Process,
    scope: LcaFile,
    case: str,
    terminals: dict[str, _Terminal],
    exchanges: list[DatasetExchange],
    emitted: dict[str, list[_Terminal]],
    mapping: dict,
    takeoff: list[MtoRow] | None,
    equipment: list[EquipmentItem] | None,
    fractions: dict | bool,
    problem,
    unmapped: list[str],
    unspecified: list[str],
    unidentified: list[tuple[str, str]],
) -> set[str]:
    """Add the emissions of ``emission_estimates:`` (pre-release issue 176) to *exchanges*: one
    ``emission:<substance>`` exchange per substance (``.non-routine`` apart), of provenance
    ``estimated``, the methods in its ``source``. A substance the flowsheet emits too is never
    overwritten: an estimate is left out with a warning, or added to it (``add: true``) with an
    info. The keys estimated, for the check of the flows: entries."""
    if not scope.emission_estimates:
        return set()
    simulated = {f"emission:{c}": sum(t.components[c] for t in ts) for c, ts in emitted.items()}
    ctx = EmissionContext(
        process,
        case,
        {e.key: (e.amount, e.unit) for e in exchanges},
        {
            key: (dict(t.components) if t.kind == "material" and not t.unsplit else None)
            for key, t in terminals.items()
        },
        takeoff,
        equipment,
        scope.operation.hours_per_year if scope.operation is not None else None,
        simulated,
    )
    found = estimate_emissions(scope, ctx, problem)
    groups: dict[str, list] = {}
    for item in found:
        groups.setdefault(item.key, []).append(item)
    by_key = {e.key: i for i, e in enumerate(exchanges)}
    components = process.components()
    for key, items in groups.items():
        substance = items[0].substance
        if key in simulated:
            added = [i for i in items if i.entry.add]
            for item in items:
                if item.entry.add:
                    continue
                problem(
                    "warning",
                    RULE_SIMULATED,
                    f"emission estimate {item.entry.id}: {key} is emitted by the flowsheet "
                    f"({simulated[key]:.6g} kg/h); the estimate ({item.amount:.6g} kg/h) is not "
                    "added and the simulated amount stays",
                    f"id: {item.entry.id}",
                    "set add: true when the estimate is a path the flowsheet does not carry "
                    "(leaks beside a vent), or leave the component out (components:)",
                    [item.entry.id, key],
                )
            if not added:
                continue
            old = exchanges[by_key[key]]
            exchanges[by_key[key]] = old.model_copy(
                update={
                    "amount": old.amount + sum(i.amount for i in added),
                    "provenance": _weakest([old.provenance, ESTIMATED]),
                    "streams": [*old.streams, *[s for i in added for s in i.streams]],
                    "source": "; ".join(filter(None, [old.source, *[i.source for i in added]])),
                }
            )
            problem(
                "info",
                RULE_ADDED,
                f"{key}: {sum(i.amount for i in added):.6g} kg/h of emission estimates "
                f"{', '.join(i.entry.id for i in added)} added to the flowsheet's "
                f"{simulated[key]:.6g} kg/h",
                f"id: {added[0].entry.id}",
                "check that the estimate is a path the flowsheet does not carry",
                [key, *[i.entry.id for i in added]],
            )
            continue
        base = key.removesuffix(NON_ROUTINE)
        flow = mapping.get(key) or mapping.get(base)
        entries = [i.entry for i in items]
        cas = next((e.cas[substance] for e in entries if substance in e.cas), None) or (
            getattr(components.get(substance), "cas", "") or None
        )
        declared = next((e.elementary for e in entries if e.elementary is not None), None)
        routine = next((e for e in exchanges if e.key == base), None) if base != key else None
        if flow is None and declared is None and routine is not None:
            # a non-routine emission takes the identity and background of its routine one
            exchanges.append(
                DatasetExchange(
                    key=key,
                    title=f"{substance} to the environment (estimated, non-routine)",
                    type="emission",
                    phase="non-routine",
                    amount=sum(i.amount for i in items),
                    unit="kg",
                    provenance=ESTIMATED,
                    cas=routine.cas,
                    flow=routine.flow,
                    link=routine.link,
                    free=routine.free,
                    carbon=routine.carbon,
                    uncertainty=items[0].entry.uncertainty,
                    streams=[s for i in items for s in i.streams],
                    source="; ".join(i.source for i in items),
                    balance_exclusion="estimated (non-routine): outside the flowsheet's "
                    "steady-state mass balance",
                )
            )
            if routine.link is None and not routine.free:
                unmapped.append(key)
            continue
        if flow is None and declared is not None and not cas:
            # characterised by CAS: without one there is no identity, the finding names it
            unidentified.append((key, "no CAS number: give cas: of the estimate, or map it"))
            declared = None
        spec = flow.elementary if flow is not None else declared
        if spec is None:
            if not any(u[0] == key for u in unidentified):
                unidentified.append(
                    (key, "no receiving compartment: give elementary (flows: or the estimate's)")
                )
        elif "subcompartment" not in spec.model_fields_set:
            unspecified.append(key)
        identity: list = []
        if spec is not None:
            identity, why = identities(cas, spec)
            if not identity:
                unidentified.append((key, why))
        uncertainties = [i.uncertainty for i in items]
        estimates = ", ".join(dict.fromkeys(e.id for e in entries))
        common = {
            "key": key,
            "title": f"{substance} to the environment (estimated"
            + (", non-routine)" if key.endswith(NON_ROUTINE) else ")"),
            "type": "emission",
            "phase": items[0].phase,
            "amount": sum(i.amount for i in items),
            "unit": "kg",
            "provenance": ESTIMATED,
            "cas": cas,
            "flow": identity,
            "uncertainty": (flow.uncertainty if flow is not None else None)
            or (uncertainties[0] if all(u == uncertainties[0] for u in uncertainties) else None),
            "streams": [s for i in items for s in i.streams],
            "source": "; ".join(i.source for i in items),
            # an emission-factor estimate: the flowsheet's balance does not carry it
            "balance_exclusion": f"estimated (emission_estimates {estimates}): an "
            "emission-factor estimate, outside the flowsheet's mass balance",
        }
        if fractions and fractions.get(substance) is not None:
            common["carbon"] = CarbonContent(total=round(fractions[substance], 9), source="formula")
        if flow is None:
            link = None
            if declared is not None:
                link = Background(
                    elementary=declared,
                    source="emission_estimates " + ", ".join(e.id for e in entries),
                )
            else:
                unmapped.append(key)
            exchanges.append(DatasetExchange(**common, link=link))
        elif flow.free:
            exchanges.append(DatasetExchange(**common, free=True))
        else:
            exchanges.append(DatasetExchange(**common, link=flow.background()))
    return set(groups)


def _completeness(process, scope, terminals, mapping, equipment, note) -> None:
    """``cheme.lci-emissions-incomplete``: combustion units and fuel feeds, flares, storage
    tanks and wastewater outlets with neither an estimate nor a declared exclusion."""
    found = emission_sources(
        process, equipment, mapping, {k: list(t.streams) for k, t in terminals.items()}
    )
    missing = emissions_incomplete(scope, found)
    if not missing:
        return
    note(
        "warning",
        RULE_INCOMPLETE,
        "emission sources the flowsheet does not carry, with neither an estimate nor a "
        "declared exclusion: " + ", ".join(f"{s.name} ({s.why}: {s.method})" for s in missing),
        "emission_estimates:",
        "add emission_estimates: entries (method, scope, sourced factors), or "
        "emission_exclusions: {id, method, equipment or exchange, reason} for what is "
        "negligible",
        [s.name for s in missing],
    )


def _excluded_emissions(scope) -> list[CutoffFlow]:
    """The declared emission exclusions, recorded as cut-off flows (no amount)."""
    return [
        CutoffFlow(
            key=f"emission-excluded:{x.id}",
            title=f"{x.method} emissions of "
            + (", ".join(x.equipment) or x.exchange or "the plant"),
            direction="output",
            reason=x.reason,
            source=x.source,
        )
        for x in scope.emission_exclusions
    ]


def _dataset_id(process: Process) -> str:
    """An id for the plant's dataset: its flowsheet title, made an identifier."""
    import re

    title = process.flowsheet.title or "plant"
    return re.sub(r"[^A-Za-z0-9_.\-]+", "-", title).strip("-").lower() or "plant"


def _construction(
    scope, takeoff, equipment, hours, problem, unknown: list[tuple[str, str, str]]
) -> list[DatasetExchange]:
    """The construction exchanges of *scope*, per hour of operation (the totals over *hours*,
    the plant's operating hours in its life); what has no amount into *unknown*."""
    exchanges: list[DatasetExchange] = []
    kinds = {entry.takeoff for entry in scope.construction}
    for entry in scope.construction:
        absent = (entry.takeoff == "mto" and takeoff is None) or (
            entry.takeoff == "equipment" and equipment is None
        )
        if absent and not entry.cutoff:
            source = "estimate/mto.csv" if entry.takeoff == "mto" else "a valid equipment list"
            unknown.append((f"no-takeoff:{entry.id}", "no-takeoff", f"no {source}"))
    if "mto" in kinds and takeoff is None:
        problem(
            "warning",
            "cheme.lca-construction-input",
            "no estimate/mto.csv: the take-off entries count nothing (gaps)",
            "takeoff: mto",
            "cheme assess mto --write (after cheme layout build)",
        )
    if "equipment" in kinds and equipment is None:
        problem(
            "warning",
            "cheme.lca-construction-input",
            "no valid equipment/equipment-list.yaml: the equipment entries count nothing (gaps)",
            "takeoff: equipment",
            "cheme validate names the problem",
        )
    count = construction(scope.construction, takeoff, equipment)
    weightless = {entry_id for entry_id, _ in count.no_weight_entries}
    for counted in count.counted:
        entry = counted.entry
        key = f"construction:{entry.id}"
        if entry.cutoff:
            continue  # declared out by the cut-off criteria: a limitation, no exchange
        if not counted.items and entry.id in weightless:
            continue  # its items have no weight: gaps below
        if not counted.items and (takeoff if entry.takeoff == "mto" else equipment) is None:
            continue  # its input is absent: a gap above
        if not counted.items:
            problem(
                "warning",
                "cheme.lca-construction-empty",
                f"{key} counts no take-off row or equipment item",
                f"id: {entry.id}",
                "check its category and where:, or the equipment globs",
                [key],
            )
            continue
        exchanges.append(
            DatasetExchange(
                key=key,
                title=entry.title or entry.id,
                type="input",
                phase="construction",
                amount=counted.quantity / hours,
                unit=counted.unit,
                provenance="calculated" if entry.takeoff == "mto" else "assumed",
                uncertainty=entry.uncertainty,
                link=entry.background(),
                streams=list(counted.items),
                source=entry.source,
            )
        )
    for what, left, needle in (
        ("take-off rows", count.rows_left if "mto" in kinds else [], "takeoff: mto"),
        ("equipment items", count.items_left if "equipment" in kinds else [], "takeoff: equipment"),
    ):
        if left:
            shown = ", ".join(left[:6]) + (f" and {len(left) - 6} more" if len(left) > 6 else "")
            problem(
                "warning",
                "cheme.lca-construction-unmapped",
                f"{len(left)} {what} no construction entry counts (gaps): {shown}",
                needle,
                "add an entry whose filters match them (entries count in order, the first "
                "match wins), with missing: when no background is available, or cutoff: when "
                "the study's cut-off criteria leave them out",
                left[:20],
            )
    cut = {e.id for e in scope.construction if e.cutoff}
    unknown += [
        (f"no-weight:{entry_id}/{tag}", "no-weight", f"{tag} has no dimensions.weight")
        for entry_id, tag in count.no_weight_entries
        if entry_id not in cut
    ]
    if "mto" in kinds:
        unknown += [
            (f"unmatched:{row}", "unmatched", "a take-off row, its amount in the plant")
            for row in count.rows_left
        ]
    if "equipment" in kinds:
        unknown += [
            (f"unmatched:{tag}", "unmatched", "an equipment item") for tag in count.items_left
        ]
    if count.no_weight:
        problem(
            "warning",
            "cheme.lca-equipment-weight",
            f"{len(count.no_weight)} equipment items have no dimensions.weight: gaps of their "
            f"construction entry, not counted as 0: {', '.join(count.no_weight)}",
            "takeoff: equipment",
            "give each its empty weight (t) in equipment/equipment-list.yaml, from the "
            "datasheet or a vendor (ASSUMED until then)",
            count.no_weight,
        )
    if count.unit_problems:
        problem(
            "error",
            "cheme.lca-construction-unit",
            "construction entries mix units: " + "; ".join(count.unit_problems[:5]),
            "construction:",
            "give rows of different units their own entries (e.g. one per category)",
        )
    return exchanges


def _matches(key: str, patterns: list[str]) -> bool:
    return any(fnmatchcase(key, pattern) for pattern in patterns)


def _treated(
    exchange: DatasetExchange, treatment: Treatment | None, model: str, problem=None
) -> list[DatasetExchange]:
    """*exchange* (an output) as the system model *model* links it, with its *treatment*, and
    the production it avoids (pre-release issue 180). A waste keeps its treatment's background. A
    recyclable or a by-product is free under a non-crediting model (cut-off: the recycler carries
    the treatment). Under substitution and consequential the ``credit`` of any kind (a recycled
    material, or the heat of an incineration) becomes an ``avoided:`` input of negative amount;
    under cut-off and apos it is recorded in the treatment and not applied. A hazardous
    recyclable keeps its background under every model (the producer pays for its treatment);
    with no background of its own it is a finding (*problem*)."""
    if treatment is None:
        return [exchange]
    credits = model in CREDITING_MODELS
    if (
        problem is not None
        and treatment.kind == "recyclable"
        and treatment.hazardous
        and exchange.link is None
    ):
        problem(
            "warning",
            "cheme.lca-hazardous-recyclable",
            f"{exchange.key} is a hazardous recyclable with no background: it is counted "
            "burden-free, but a hazardous waste rarely has a buyer",
            "lca.yaml",
            "link the treatment of the recycler or the hazardous waste treatment "
            "(factor, activity or dataset), or classify it as kind: waste",
            [exchange.key],
        )
    if problem is not None and treatment.kind == "byproduct" and not credits:
        problem(
            "warning",
            "cheme.lca-byproduct-free",
            f"{exchange.key} is a by-product left burden-free under system model {model}: "
            "ecoinvent cut-off cuts off only the by-products of waste treatment and recyclables; "
            "an ordinary by-product (steam, a fuel, a valuable material) shares the burdens by "
            "allocation",
            "lca.yaml",
            "list it in allocation.coproducts, or classify it as kind: recyclable or waste; "
            "keep kind: byproduct only for a flow below 1 % of the output mass (ASSUMED "
            "negligible, state why)",
            [exchange.key],
        )
    update: dict = {"treatment": treatment}
    # a hazardous recyclable linked to its treatment carries it, as a waste does
    hazardous = treatment.kind == "recyclable" and treatment.hazardous and exchange.link is not None
    if treatment.kind != "waste" and not credits and not hazardous:
        update |= {"link": None, "free": True}
    found = [exchange.model_copy(update=update)]
    if credits and treatment.credit is not None:
        credit = treatment.credit
        found.append(
            DatasetExchange(
                key="avoided:" + exchange.key.replace(":", ".", 1),
                title=f"Avoided by: {exchange.title or exchange.key}",
                type="input",
                phase=exchange.phase,
                amount=-exchange.amount * treatment.ratio,
                unit=exchange.unit,
                provenance=exchange.provenance,
                link=credit.background(),
                streams=[exchange.key],
                source=credit.source,
            )
        )
    return found


def _per_hour(scope, unit: str, per_year: float) -> tuple[float, str]:
    """An amount per year in *unit*, per hour of operation in the inventory unit."""
    kind, per = FACTOR_UNITS[unit]
    return per_year * per / scope.operation.hours_per_year, INVENTORY_UNITS[kind]


def _study_cutoff(scope) -> list[CutoffFlow]:
    """The study's own cut flows (``cutoff:`` of lca.yaml), per hour of operation."""
    found = []
    for entry in scope.cutoff:
        amount, unit = (
            _per_hour(scope, entry.unit, entry.per_year)
            if entry.per_year is not None and scope.operation is not None
            else (None, INVENTORY_UNITS[FACTOR_UNITS[entry.unit][0]])
        )
        found.append(
            CutoffFlow(
                key=f"cutoff:{entry.id}",
                title=entry.title or entry.id,
                direction=entry.direction,
                amount=amount,
                unit=unit,
                reason=entry.reason,
                cas=entry.cas,
                catalyst=entry.catalyst,
                contains=list(entry.contains),
                source=entry.source,
            )
        )
    return found


def _construction_cutoff(scope, takeoff, equipment, hours: float) -> list[CutoffFlow]:
    """The construction entries cut off by the study's criteria, with what they match."""
    cut = [e for e in scope.construction if e.cutoff]
    if not cut:
        return []
    count = construction(scope.construction, takeoff, equipment)
    found = []
    for counted in count.counted:
        entry = counted.entry
        if not entry.cutoff:
            continue
        found.append(
            CutoffFlow(
                key=f"construction:{entry.id}",
                title=entry.title or entry.id,
                amount=counted.quantity / hours if counted.items else None,
                unit=counted.unit or "kg",
                reason=entry.cutoff,
                source=entry.source,
            )
        )
    return found


def _disposed(
    source: DatasetExchange,
    disposal,
    key: str,
    phase: str,
    cutoff: list[CutoffFlow],
    model: str,
    problem,
    catalyst: bool = False,
) -> list[DatasetExchange]:
    """The output of *disposal* for the input *source* (kg), or its record in *cutoff*. A
    flow with ``metals`` is a catalyst unless told otherwise (the never-cut rule)."""
    amount = source.amount * disposal.fraction
    catalyst = catalyst or bool(source.metals)
    if disposal.fraction < 1:
        problem(
            "info",
            "cheme.lca-disposal-fraction",
            f"disposal of {source.key} takes {disposal.fraction:g} of its mass: the remainder "
            f"({source.amount * (1 - disposal.fraction):.6g} {source.unit}) is assumed retained "
            "or used up, and leaves nowhere",
            "disposal:",
            "give the full mass to a disposal (fraction: 1) when all of it leaves the plant",
            [key],
        )
    if disposal.cutoff:
        cutoff.append(
            CutoffFlow(
                key=key,
                title=f"Disposal: {source.title}",
                direction="output",
                amount=amount,
                unit=source.unit,
                reason=disposal.cutoff,
                contains=sorted(source.metals),
                catalyst=catalyst,
                source=disposal.source,
            )
        )
        return []
    backed = any(
        v is not None
        for v in (disposal.factor, disposal.activity, disposal.dataset, disposal.missing or None)
    )
    exchange = DatasetExchange(
        key=key,
        title=f"Disposal: {source.title} ({disposal.route})",
        type="output",
        phase=phase,
        amount=amount,
        unit=source.unit,
        provenance=source.provenance,
        free=not backed,
        link=disposal.background() if backed else None,
        streams=[source.key],
        source=disposal.source,
        metals=dict(source.metals),
    )
    return _treated(exchange, disposal.treatment(), model, problem)


def _supplies(
    scope, exchanges: list[DatasetExchange], problem, cutoff: list[CutoffFlow]
) -> list[DatasetExchange]:
    """Consumables, maintenance, transport and end of life: exchanges per hour of operation,
    the last three derived from *exchanges* (construction and the flows already counted), and
    the disposal outputs of consumables and construction materials (pre-release issue 180);
    disposals cut off by the study's criteria go to *cutoff*."""
    found: list[DatasetExchange] = []
    operation = scope.operation
    model = scope.model
    for item in scope.consumables:
        kind, per = FACTOR_UNITS[item.unit]
        per_year = (
            item.per_year
            if item.per_year is not None
            else item.per_replacement / item.every_years  # type: ignore[operator]
            if item.per_replacement is not None
            else 0.0
        )
        if item.initial_charge:
            per_year += item.initial_charge / operation.life_years
        consumed = DatasetExchange(
            key=f"consumable:{item.id}",
            title=item.title or item.id,
            type="input",
            amount=per_year * per / operation.hours_per_year,
            unit=INVENTORY_UNITS[kind],
            uncertainty=item.uncertainty,
            link=item.background(),
            source=item.source,
            metals=dict(item.metals),
        )
        found.append(consumed)
        if item.disposal is not None:
            found += _disposed(
                consumed,
                item.disposal,
                f"disposal:consumable.{item.id}",
                "operation",
                cutoff,
                model,
                problem,
                item.catalyst,
            )
        elif kind == "mass":
            _undisposed(item, problem)
        elif item.finite:
            problem(
                "warning",
                "cheme.lca-disposal",
                f"consumable {item.id} is replaced or charged in {item.unit}, but a disposal is "
                "given for a mass only: what goes in does not come out",
                f"id: {item.id}",
                "give the consumable in kg (bed mass = volume x bulk density) with a disposal:",
                [f"consumable:{item.id}"],
            )
    if scope.maintenance is not None:
        rule = scope.maintenance
        built = [e for e in exchanges if e.phase == "construction"]
        matched = [e for e in built if _matches(e.key.split(":", 1)[1], rule.applies_to)]
        if not matched:
            problem(
                "warning",
                "cheme.lca-supply-unmatched",
                "maintenance applies to no construction entry",
                "maintenance:",
                "check applies_to (globs on construction ids)",
            )
        for exchange in matched:
            found.append(
                exchange.model_copy(
                    update={
                        "key": f"maintenance:{exchange.key.split(':', 1)[1]}",
                        "title": f"Maintenance: {exchange.title}",
                        "phase": "maintenance",
                        # a fraction of the plant's material per year, over its life: the
                        # construction's per-hour amount (total / life hours) x fraction x years
                        "amount": exchange.amount * rule.fraction_per_year * operation.life_years,
                        "source": rule.source,
                        # varies with its construction entry (uncertainty.monte_carlo)
                        "uncertainty": None,
                    }
                )
            )
    found += _construction_disposals(scope, exchanges + found, problem, cutoff, model)
    counted = exchanges + found
    for item in scope.transport:
        # what is brought to the plant: inputs, in kg (products and emissions leave)
        inputs = [
            e
            for e in counted
            if e.type == "input"
            and not e.key.startswith("avoided:")
            and _matches(e.key, item.applies_to)
        ]
        matched = [e for e in inputs if e.unit == "kg"]
        skipped = [e.key for e in inputs if e.unit != "kg"]
        if skipped:
            problem(
                "warning",
                "cheme.lca-supply-unit",
                f"transport {item.id}: only masses are transported; left out: {', '.join(skipped)}",
                f"id: {item.id}",
                "narrow applies_to to material exchanges (kg)",
                skipped,
            )
        if not matched:
            problem(
                "warning",
                "cheme.lca-supply-unmatched",
                f"transport {item.id} applies to no material exchange",
                f"id: {item.id}",
                "check applies_to (globs on keys such as construction:*)",
            )
            continue
        phases = {e.phase for e in matched}
        found.append(
            DatasetExchange(
                key=f"transport:{item.id}",
                title=item.title or f"Transport ({item.distance_km:g} km)",
                type="input",
                phase=phases.pop() if len(phases) == 1 else "transport",
                amount=sum(e.amount for e in matched) / 1000.0 * item.distance_km,
                unit="tkm",
                uncertainty=item.uncertainty,
                link=item.background(),
                streams=[e.key for e in matched],
                source=item.source,
            )
        )
    # sources that already leave through a disposal: an end_of_life entry must not count them twice
    disposed = {f"consumable:{c.id}" for c in scope.consumables if c.disposal is not None}
    for entry in scope.construction:
        if entry.disposal is not None:
            disposed |= {f"construction:{entry.id}", f"maintenance:{entry.id}"}
    for item in scope.end_of_life:
        matched = [
            e
            for e in counted
            if _matches(e.key, item.applies_to)
            and e.unit == "kg"
            and (e.phase in ("construction", "maintenance") or e.key.startswith("consumable:"))
        ]
        twice = [e.key for e in matched if e.key in disposed]
        if twice:
            problem(
                "warning",
                "cheme.lca-eol-double",
                f"end of life {item.id} matches {', '.join(twice)}, which already have a "
                "disposal: output; "
                "the end_of_life match is skipped, so that the mass is not disposed (or "
                "credited) twice",
                f"id: {item.id}",
                "keep the disposal: of the construction or consumable entry, or narrow "
                "applies_to of the end_of_life entry to what has none",
                [f"end-of-life:{item.id}", *twice],
            )
            matched = [e for e in matched if e.key not in disposed]
            if not matched:
                continue
        if not matched:
            problem(
                "warning",
                "cheme.lca-supply-unmatched",
                f"end of life {item.id} applies to no construction, maintenance or consumable mass",
                f"id: {item.id}",
                "check applies_to (globs on keys such as construction:*)",
            )
            continue
        treatment = item.treatment()
        if treatment is None:
            problem(
                "info",
                "cheme.lca-eol-kind",
                f"end of life {item.id} gives no kind: its output is linked to its background "
                f"as given, under system model {model}",
                f"id: {item.id}",
                "give kind: waste (with its treatment) or kind: recyclable (route, and credit: "
                "for a substitution build); a recycling credit hidden in a background with a "
                "negative impact is not allowed in a cut-off study",
                [f"end-of-life:{item.id}"],
            )
        backed = any(
            v is not None
            for v in (item.factor, item.activity, item.biosphere, item.dataset, item.elementary)
        )
        exchange = DatasetExchange(
            key=f"end-of-life:{item.id}",
            title=item.title or f"End of life: {item.id}",
            type="output",
            phase="end-of-life",
            amount=sum(e.amount for e in matched) * item.fraction,
            unit="kg",
            uncertainty=item.uncertainty,
            free=not backed and not item.missing,
            link=item.background() if backed or item.missing else None,
            streams=[e.key for e in matched],
            source=item.source,
        )
        found += _treated(exchange, treatment, model, problem)
    return found


def _undisposed(item, problem) -> None:
    """A consumable whose mass leaves the plant again without a disposal: a finding
    (pre-release issue 180). Replaced or charged material (spent adsorbent or catalyst) always comes
    out again; what is bought per year may be used up (a warning only for the first)."""
    if item.finite:
        problem(
            "warning",
            "cheme.lca-disposal",
            f"consumable {item.id} is replaced or charged, but has no disposal: what goes in "
            "does not come out",
            f"id: {item.id}",
            "give disposal: {kind: waste|recyclable, route, <treatment background>} (spent "
            "adsorbent to landfill, spent catalyst to metal recovery), or disposal: {route, "
            "cutoff: <why>} to record it as cut off",
            [f"consumable:{item.id}"],
        )
    else:
        problem(
            "info",
            "cheme.lca-disposal",
            f"consumable {item.id} gives no disposal: counted as used up (not leaving the "
            "plant as waste)",
            f"id: {item.id}",
            "give disposal: when it leaves as waste (waste oil to incineration or re-refining)",
            [f"consumable:{item.id}"],
        )


def _construction_disposals(
    scope, counted: list[DatasetExchange], problem, cutoff: list[CutoffFlow], model: str
) -> list[DatasetExchange]:
    """The disposal outputs of the construction materials and their maintenance replacements."""
    found: list[DatasetExchange] = []
    entries = {e.id: e for e in scope.construction if e.disposal is not None}
    for exchange in counted:
        what, _, name = exchange.key.partition(":")
        entry = entries.get(name)
        if entry is None or what not in ("construction", "maintenance"):
            continue
        if exchange.unit != "kg":
            problem(
                "warning",
                "cheme.lca-supply-unit",
                f"disposal of {exchange.key}: only masses are disposed; it counts {exchange.unit}",
                f"id: {name}",
                "give the disposal to an entry counted in kg (steel, equipment)",
                [exchange.key],
            )
            continue
        phase = "end-of-life" if what == "construction" else "maintenance"
        found += _disposed(
            exchange, entry.disposal, f"disposal:{what}.{name}", phase, cutoff, model, problem
        )
    return found


def _system_model_findings(scope, problem) -> None:
    """A credit the study's system model does not allow (pre-release issue 180)."""
    model = scope.model
    if scope.allocation.method == "substitution" and model not in CREDITING_MODELS:
        problem(
            "warning",
            "cheme.lca-system-model",
            f"allocation substitution credits the co-products, but the system model is {model}: "
            "avoided-burden credits belong to a substitution or consequential build",
            "allocation:",
            "set system_model: substitution, or allocate (exergy, energy, economic, mass)",
        )
    if model == "apos":
        problem(
            "info",
            "cheme.lca-system-model",
            "system model apos: recyclable and by-product outputs leave burden-free as in "
            "cutoff; the share of upstream burdens APOS gives them is not modelled",
            "system_model:",
            "list a valuable by-product in allocation.coproducts to share the burdens with it",
        )
