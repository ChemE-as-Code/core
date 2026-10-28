"""``cheme chemistry``: pure-component and binary properties from PubChem, NIST, OSHA, thermo
and the prediction services (domains/chemistry/properties.py), ideal-gas formation data
(domains/chemistry/thermochemistry.py), reaction kinetics (domains/chemistry/kinetics/) and the
reaction evidence of a plant (domains/chemistry/evidence.py)."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Annotated

import typer

chemistry_app = typer.Typer(
    help="Chemistry: component properties from databases and correlations.",
    no_args_is_help=True,
)


@chemistry_app.command("props")
def props(
    component: Annotated[str, typer.Argument(help="Name or CAS number, e.g. ethanol, 64-17-5.")],
    prop: Annotated[
        list[str],
        typer.Option("--property", "-p", help="Property to look up (repeat for several)."),
    ],
    temperature: Annotated[float, typer.Option(help="Temperature.")] = 298.15,
    temperature_unit: Annotated[str, typer.Option(help="Unit of --temperature.")] = "K",
    pressure: Annotated[float, typer.Option(help="Pressure.")] = 101325.0,
    pressure_unit: Annotated[str, typer.Option(help="Unit of --pressure.")] = "Pa",
    source: Annotated[
        list[str] | None,
        typer.Option(help="Ask only these sources (PubChem, NIST, OSHA, Thermo, GRAPPA)."),
    ] = None,
    grappa_endpoint: Annotated[
        str | None, typer.Option(help="Base URL of a running GRAPPA service (last resort).")
    ] = None,
    as_json: Annotated[bool, typer.Option("--json", help="Results as JSON.")] = False,
) -> None:
    """Look up properties of one component; each line names the source of its value.

    Without --source the web databases are asked (network). Exits 1 when a property was not
    found.
    """
    from chemeascode.domains.chemistry.properties import (
        SOURCE_ORDER,
        PropertyRetriever,
        Source,
        retrieve_properties,
    )
    from chemeascode.foundation.units import UnitError

    try:
        sources = {Source(s) for s in source} if source else None
    except ValueError as failure:
        typer.echo(f"{failure}; sources: {', '.join(s.value for s in Source)}", err=True)
        raise typer.Exit(2) from failure
    unknown = [p for p in prop if p not in SOURCE_ORDER]
    if unknown:
        typer.echo(f"unknown property: {', '.join(unknown)}", err=True)
        typer.echo(f"known: {', '.join(sorted(SOURCE_ORDER))}", err=True)
        raise typer.Exit(2)
    retriever = PropertyRetriever(sources=sources, grappa_endpoint=grappa_endpoint)
    try:
        results = retrieve_properties(
            component,
            prop,
            temperature=temperature,
            temperature_unit=temperature_unit,
            pressure=pressure,
            pressure_unit=pressure_unit,
            retriever=retriever,
        )
    except UnitError as failure:
        typer.echo(str(failure), err=True)
        raise typer.Exit(2) from failure
    if as_json:
        typer.echo(json.dumps([r.to_dict() for r in results], indent=2, ensure_ascii=False))
    else:
        for r in results:
            if r.ok:
                units = f" {r.units}" if r.units else ""
                typer.echo(f"{r.property}: {r.value}{units} [{r.source}]")
            else:
                typer.echo(f"{r.property}: not found ({r.error})")
    for name, reason in retriever.unavailable.items():
        typer.echo(f"skipped {name}: {reason}", err=True)
    if not all(r.ok for r in results):
        raise typer.Exit(1)


@chemistry_app.command("thermo")
def thermo(
    components: Annotated[list[str], typer.Argument(help="Names or CAS numbers.")],
    fit: Annotated[
        str | None,
        typer.Option(
            help="LO,HI in K: fit the heat capacity to thermo over this range (beyond 1000 K)."
        ),
    ] = None,
    as_json: Annotated[bool, typer.Option("--json", help="Results as JSON.")] = False,
) -> None:
    """Ideal-gas formation data (dHf, S at 298.15 K, Cp/R polynomial) for process/materials.yaml.

    Prints one `ideal_gas:` entry per component to paste into its components: line (extra
    props, offline). Exits 1 when a component is not known.
    """
    from chemeascode.domains.chemistry.eos import lookup_critical
    from chemeascode.domains.chemistry.thermochemistry import lookup_ideal_gas

    window = None
    if fit is not None:
        try:
            lo, hi = (float(v) for v in fit.split(","))
        except ValueError as failure:
            typer.echo("--fit is LO,HI in K, e.g. 298.15,1500", err=True)
            raise typer.Exit(2) from failure
        window = (lo, hi)
    failed = False
    results = []
    for name in components:
        try:
            data, identity = lookup_ideal_gas(name, window)
        except ImportError as failure:
            typer.echo(
                f"{failure}; install the props extra: pip install 'cheme-as-code[props]'",
                err=True,
            )
            raise typer.Exit(2) from failure
        except ValueError as failure:
            typer.echo(f"{name}: {failure}", err=True)
            failed = True
            continue
        found = {**identity, "ideal_gas": data.model_dump(mode="json")}
        try:
            found["critical"] = lookup_critical(name).model_dump(mode="json")
        except ValueError:
            found["critical"] = None
        results.append(found)
        rng = data.temperature_range
        if not as_json and "fitted" in data.source and rng is not None and rng[1] < 1000.0:
            typer.echo(
                f"# note: {name}: its heat capacity holds from {rng[0]:g} to {rng[1]:g} K only",
                err=True,
            )
        if not as_json:
            entry = data.model_dump(mode="json", exclude_defaults=False)
            entry["cp_R"] = "[" + ", ".join(f"{c:.6g}" for c in data.cp_R) + "]"
            rng = data.temperature_range
            entry["temperature_range"] = f"[{rng[0]:g}, {rng[1]:g}]" if rng else "null"
            text = ", ".join(
                f"{k}: {v}" if k in ("cp_R", "temperature_range") else f"{k}: {json.dumps(v)}"
                for k, v in entry.items()
            )
            typer.echo(
                f"# {identity['name']} ({identity['cas']}, {identity['formula']}, "
                f"{identity['molar_mass']:.5g} kg/kmol)"
            )
            typer.echo(f"ideal_gas: {{{text}}}")
            values = found["critical"]
            if values is None:
                continue
            typer.echo(
                "critical: {"
                + ", ".join(
                    f"{k}: {json.dumps(v) if isinstance(v, str) else f'{v:.6g}'}"
                    for k, v in values.items()
                )
                + "}"
            )
    if as_json:
        typer.echo(json.dumps(results, indent=2))
    if failed:
        raise typer.Exit(1)


@chemistry_app.command("kinetics")
def kinetics(
    reactant: Annotated[
        list[str],
        typer.Option(
            "--reactant",
            "-r",
            help="ID=NAME or ID=SMILES, a reactant (repeat). A formula that is also a SMILES "
            "(CO, NO) is refused: give a name, [C-]#[O+], or smiles:CO.",
        ),
    ],
    product: Annotated[
        list[str] | None,
        typer.Option(
            "--product",
            "-p",
            help="ID=NAME or ID=SMILES, a product (repeat). A formula that is also a SMILES "
            "(CO, NO) is refused: give a name, [C-]#[O+], or smiles:CO.",
        ),
    ] = None,
    t_min: Annotated[
        float | None,
        typer.Option("--tmin", help="K; records must cover it (alone: the one temperature)."),
    ] = None,
    t_max: Annotated[
        float | None,
        typer.Option("--tmax", help="K; records must cover it (alone: the one temperature)."),
    ] = None,
    rmg_endpoint: Annotated[
        str | None, typer.Option(help="Base URL of a running RMG service (else NIST only).")
    ] = None,
    as_json: Annotated[bool, typer.Option("--json", help="The record and rate as JSON.")] = False,
) -> None:
    """Kinetics of an elementary gas-phase reaction from NIST (and RMG), reduced to one Arrhenius
    record, printed as a `rate:` entry for process/reactions.yaml (network).

    The rate is a power law per volume on concentrations (kmol/m3), its A converted from SI
    moles. Exits 1 when no record is found.
    """
    from chemeascode.domains.chemistry.kinetics.filter import filter_kinetics
    from chemeascode.domains.chemistry.kinetics.identification import (
        resolve_smiles,
        validate_smiles,
    )
    from chemeascode.domains.chemistry.kinetics.retrieval import retrieve_kinetics
    from chemeascode.domains.chemistry.rates import rate_law_from_record

    def split(entries: list[str]) -> tuple[list[str], list[str]]:
        ids, names = [], []
        for entry in entries:
            cid, eq, name = entry.partition("=")
            if not eq or not cid or not name:
                typer.echo(f"{entry!r}: give ID=NAME or ID=SMILES", err=True)
                raise typer.Exit(2)
            ids.append(cid)
            names.append(name)
        return ids, names

    reactant_ids, reactant_names = split(reactant)
    product_ids, product_names = split(product or [])
    try:
        reactant_smiles = resolve_smiles(reactant_names)
        product_smiles = resolve_smiles(product_names) if product_names else None
    except (ImportError, ValueError) as failure:
        typer.echo(f"cannot resolve the species: {failure}", err=True)
        raise typer.Exit(2) from failure
    found = retrieve_kinetics(
        reactant_smiles, product_smiles, t_min, t_max, rmg_endpoint=rmg_endpoint
    )
    for source, error in {**found.errors, **found.skipped}.items():
        typer.echo(f"{source}: {error}", err=True)
    try:
        record = filter_kinetics(
            found.rmg_records, found.nist_records, reactant_smiles, product_smiles
        )
        ids = dict(zip(reactant_smiles, reactant_ids, strict=True))
        law = rate_law_from_record(record, ids, canonical=validate_smiles)
    except ValueError as failure:
        typer.echo(f"no kinetics: {failure}", err=True)
        raise typer.Exit(1) from failure
    if as_json:
        typer.echo(
            json.dumps(
                {"record": record.model_dump(mode="json"), "rate": law.model_dump(mode="json")},
                indent=2,
            )
        )
        return
    typer.echo(f"# {record.reaction}: {record.confidence or 'no'} confidence, {record.data_type}")
    typer.echo("rate:")
    for key, value in law.model_dump(mode="json", exclude_defaults=True).items():
        typer.echo(f"  {key}: {json.dumps(value)}")


@chemistry_app.command("microkinetics")
def microkinetics(
    reaction: Annotated[str, typer.Argument(help="A reaction id of process/reactions.yaml.")],
    temperature: Annotated[float, typer.Option("--temperature", "-T", help="K")],
    pressure: Annotated[
        list[str],
        typer.Option("--pressure", "-p", help="ID=BAR, a partial pressure (repeat)."),
    ],
    product: Annotated[
        str | None,
        typer.Option(help="The component whose TOF is analysed (default: first product)."),
    ] = None,
    cantera: Annotated[
        bool, typer.Option("--cantera", help="Check the steady state with Cantera (extra cantera).")
    ] = False,
    export: Annotated[
        Path | None, typer.Option(help="Write the mechanism as a Cantera YAML input to this file.")
    ] = None,
    as_json: Annotated[bool, typer.Option("--json", help="As JSON.")] = False,
) -> None:
    """A reaction's elementary steps at steady state (mean field): coverages, TOF, degree of rate
    control of every step, apparent activation energy and reaction orders."""
    from chemeascode.domains.chemistry.microkinetics import cantera_yaml
    from chemeascode.domains.process.microkinetic_report import (
        NotAvailable,
        load_chemistry,
        microkinetic_report,
        report_text,
    )
    from chemeascode.interfaces.cli.process import _workspace

    pressures = {}
    for entry in pressure:
        cid, eq, value = entry.partition("=")
        try:
            pressures[cid] = float(value)
        except ValueError:
            eq = ""
        if not eq or not cid or pressures.get(cid, 0.0) < 0:
            typer.echo(f"{entry!r}: give ID=BAR, a pressure not below 0", err=True)
            raise typer.Exit(2)
    if temperature <= 0:
        typer.echo("--temperature is in K, above 0", err=True)
        raise typer.Exit(2)
    root = _workspace().root
    chemistry = load_chemistry(root)
    if export is not None:
        # written first: the input to debug a mechanism whose steady state is not found
        found = chemistry.reactions.by_id().get(reaction) if chemistry.reactions else None
        if found is None or found.mechanism is None:
            typer.echo(f"reaction {reaction} has no mechanism to export", err=True)
            raise typer.Exit(1)
        try:
            export.write_text(
                cantera_yaml(found.mechanism, chemistry.formulas(), name=reaction),
                encoding="utf-8",
            )
        except ValueError as failure:
            typer.echo(f"no Cantera input: {failure}", err=True)
            raise typer.Exit(1) from failure
    try:
        result = microkinetic_report(
            root, reaction, temperature, pressures, product, cantera, chemistry=chemistry
        )
    except (NotAvailable, ValueError) as failure:
        typer.echo(str(failure), err=True)
        raise typer.Exit(1) from failure
    except ImportError as failure:
        typer.echo(f"{failure}; install the extra: pip install 'cheme-as-code[cantera]'", err=True)
        raise typer.Exit(2) from failure
    typer.echo(json.dumps(result, indent=2) if as_json else report_text(result))


@chemistry_app.command("library")
def library(
    entry: Annotated[str | None, typer.Argument(help="An entry id (none: list them).")] = None,
    add: Annotated[
        bool, typer.Option("--add", help="Add the entry's components, reactions and catalysts.")
    ] = False,
    as_json: Annotated[bool, typer.Option("--json", help="As JSON.")] = False,
) -> None:
    """The reaction library: industrial processes with their components (ideal-gas data,
    critical constants), reactions and typical catalysts. Without an id, list them; with one,
    show it; with --add, add it to process/materials.yaml, reactions.yaml and catalysts.yaml."""
    from chemeascode.domains.process.reaction_library import Conflict, add_entry, entries

    found = entries()
    if entry is None:
        if as_json:
            typer.echo(json.dumps({k: v.title for k, v in found.items()}, indent=2))
            return
        for key, value in found.items():
            typer.echo(f"{key:22} {value.model_basis.kind:22} {value.title}")
        return
    if entry not in found:
        typer.echo(f"no library entry {entry!r}; `cheme chemistry library` lists them", err=True)
        raise typer.Exit(2)
    item = found[entry]
    if add:
        from chemeascode.interfaces.cli.process import _workspace

        try:
            result = add_entry(_workspace().root, entry)
        except Conflict as failure:
            typer.echo(str(failure), err=True)
            raise typer.Exit(1) from failure
        for path, ids in result.added.items():
            typer.echo(f"{path}: added {', '.join(ids)}")
        if result.present:
            typer.echo(f"already there: {', '.join(result.present)}")
        if not result.added:
            typer.echo("nothing to add")
        typer.echo(_basis_line(item))
        return
    if as_json:
        typer.echo(item.model_dump_json(indent=2, by_alias=True))
        return
    lo, hi = item.window.temperature
    plo, phi = item.window.pressure
    typer.echo(f"{item.id}: {item.title}")
    typer.echo(f"  window {lo:g}-{hi:g} K, {plo:g}-{phi:g} kPa(a)")
    typer.echo("  components: " + ", ".join(c.id for c in item.components))
    for reaction in item.reactions:
        typer.echo(
            f"  {reaction.id}: {reaction.equation or reaction.stoichiometry}"
            + (f" ({reaction.catalyst})" if reaction.catalyst else "")
        )
    for cat in item.catalysts:
        typer.echo(f"  catalyst {cat.id}: {cat.name or cat.active_phase}")
    typer.echo("  " + _basis_line(item))
    for source in item.sources:
        typer.echo(f"  source: {source}")


@chemistry_app.command("evidence")
def evidence(
    as_json: Annotated[bool, typer.Option("--json", help="As JSON.")] = False,
) -> None:
    """The route comparison of process/reaction-evidence.yaml: per route its sources and
    observations, the temperature, pressure, conversion, selectivity and yield reported (each
    kept apart), kinetics, conflicts, sources not read and gaps, then the model basis and the
    file's cheme.evidence-* findings. Exit 1 on an error finding."""
    from chemeascode.domains.chemistry.evidence import (
        EVIDENCE_FILE,
        comparison_text,
        route_comparison,
    )
    from chemeascode.foundation.schemas.run import finding_dict
    from chemeascode.interfaces.cli.process import _workspace
    from chemeascode.project.evidence import comparison

    root = _workspace().root
    if not (root / EVIDENCE_FILE).is_file():
        typer.echo(f"no {EVIDENCE_FILE}; skill reaction-evidence-search writes it", err=True)
        raise typer.Exit(2)
    found, findings = comparison(root)
    if as_json:
        document = {
            "file": EVIDENCE_FILE,
            "routes": [s.as_dict() for s in route_comparison(found)] if found else None,
            "model_basis": (
                found.model_basis.model_dump(mode="json")
                if found is not None and found.model_basis is not None
                else None
            ),
            "findings": [finding_dict(f) for f in findings],
        }
        typer.echo(json.dumps(document, indent=2))
    else:
        if found is not None:
            typer.echo(comparison_text(found))
        if findings:
            typer.echo("")
        for finding in findings:
            typer.echo(finding.format())
    if any(f.level == "error" for f in findings):
        raise typer.Exit(1)


def _basis_line(item) -> str:
    """``model basis: <kind> (<note>)``: which reactor model the entry's data supports."""
    basis = item.model_basis
    kind = basis.kind + (f", {basis.provenance}" if basis.provenance else "")
    return f"model basis: {kind}" + (f" ({basis.note})" if basis.note else "")
