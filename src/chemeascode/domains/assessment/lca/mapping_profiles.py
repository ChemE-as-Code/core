"""Provider profiles (``brightway.mapping_profiles``): the study's own
mappings first, then each selected profile's, by the flowsheet's terms.

The exchange contract is provider-independent: a feed or product is named by its key and, for
an energy terminal, by its utility kind in ``process/flowsheet.yaml``. A profile
(``kind: lca_mapping_profile``) says how one provider names the activity for each: changing the
provider of a study is selecting another profile, not rewriting ``flows:``. Only the feeds and
products that ``flows:`` leaves unmapped (no entry at all; ``missing:`` is an entry) take a
profile's mapping, and the first matching entry of the first profile wins: a key before a
utility kind.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import yaml
from pydantic import ValidationError

from chemeascode.domains.assessment.lca.schemas import FlowMap, MappingProfile
from chemeascode.foundation.findings import Finding


def load_profile(root: Path, path: str) -> MappingProfile | str:
    """The profile at *path* (from *root*, inside it), or why it does not load."""
    target = (root / path).resolve()
    if not target.is_relative_to(root.resolve()):
        return f"{path} is outside the repository"
    if not target.is_file():
        return f"no mapping profile {path}"
    try:
        data = yaml.safe_load(target.read_text(encoding="utf-8")) or {}
        return MappingProfile.model_validate(data)
    except (OSError, UnicodeDecodeError, ValidationError, yaml.YAMLError) as failure:
        return f"{path} does not load: {' '.join(str(failure).splitlines()[:3])}"


def _line(text: str | None, needle: str) -> int | None:
    for number, line in enumerate((text or "").splitlines(), 1):
        if needle in line:
            return number
    return None


def profile_flows(
    root: Path, scope: Any, process: Any, file: str, text: str | None = None
) -> tuple[list[FlowMap], list[str], list[Finding]]:
    """The flows: entries the selected profiles give (each marked with its profile), the
    profile files read, and the findings: a profile that does not load is an error; one of
    another system model or database identity than the study's, or an entry that matches no
    flow, a warning."""
    if not getattr(scope.brightway, "mapping_profiles", None):
        return [], [], []
    if scope.backend != "brightway":
        return (
            [],
            [],
            [
                Finding(
                    file,
                    "info",
                    "cheme.lca-mapping-profile-unused",
                    "brightway.mapping_profiles is not used: the study's backend is "
                    f"{scope.backend}",
                    line=_line(text, "mapping_profiles"),
                    hint="set backend: brightway to map flows by the profiles",
                )
            ],
        )
    findings: list[Finding] = []
    profiles: list[tuple[str, MappingProfile]] = []
    for path in scope.brightway.mapping_profiles:
        loaded = load_profile(root, path)
        if isinstance(loaded, str):
            inside = (root / path).is_file() and "does not load" in loaded
            findings.append(
                Finding(
                    path if inside else file,
                    "error",
                    "cheme.lca-mapping-profile",
                    loaded,
                    line=None if inside else _line(text, path),
                    ids=[path],
                    hint="give brightway.mapping_profiles the path of a kind lca_mapping_profile "
                    "file in the repository (cheme schema lca_mapping_profile)",
                )
            )
        else:
            profiles.append((path, loaded))
    if findings:
        return [], [], findings
    fs = process.flowsheet
    expect = scope.brightway.expect
    for path, profile in profiles:
        problems = []
        if profile.system_model and profile.system_model != scope.model:
            problems.append(f"system model {profile.system_model}, the study's {scope.model}")
        for database in sorted({e.activity.database for e in profile.entries}):
            known = expect.get(database)
            if known is None:
                continue
            for name in ("provider", "version", "system_model"):
                theirs, mine = getattr(profile, name), getattr(known, name)
                if theirs and mine and theirs != mine:
                    problems.append(f"{name} {theirs}, brightway.expect of {database}: {mine}")
        terminals = {f"feed:{n.id}" for n in fs.feeds} | {f"product:{n.id}" for n in fs.products}
        stray = sorted(
            e.match.key for e in profile.entries if e.match.key and e.match.key not in terminals
        )
        if stray:
            problems.append(f"entries for no flow of the flowsheet: {', '.join(stray)}")
        if problems:
            findings.append(
                Finding(
                    path,
                    "warning",
                    "cheme.lca-mapping-profile-fit",
                    f"mapping profile {profile.id} may not fit this study: {'; '.join(problems)}",
                    ids=[profile.id],
                    hint="select the profile of the study's provider, release and system model, "
                    "and give its entries the flowsheet's keys",
                )
            )
    mapped = {flow.key for flow in scope.flows}
    excluded = set(scope.allocation.coproducts) | {scope.functional_unit.product}
    # a gate-to-gate study maps its feeds free: profiles add no supply chain to it
    feeds = [] if scope.boundary == "gate-to-gate" else fs.feeds
    nodes = [("feed", n) for n in feeds] + [("product", n) for n in fs.products]
    added: list[FlowMap] = []
    for side, node in nodes:
        key = f"{side}:{node.id}"
        if key in mapped or (side == "product" and node.id in excluded):
            continue
        utility = getattr(getattr(node, "utility", None), "kind", None)
        for path, profile in profiles:
            entry = next((e for e in profile.entries if e.match.key == key), None)
            if entry is None and side == "feed" and utility:
                entry = next((e for e in profile.entries if e.match.utility == utility), None)
            if entry is None:
                continue
            added.append(
                FlowMap(
                    key=key,
                    activity=entry.activity,
                    source=f"mapping profile {profile.id} ({path}): {entry.source}",
                    proxy=entry.proxy,
                )
            )
            break
    if added:
        findings.append(
            Finding(
                file,
                "info",
                "cheme.lca-mapping-profile-used",
                f"{len(added)} flows are mapped by a provider profile: "
                + ", ".join(f"{f.key} ({f.source.split(' (', 1)[0].split()[-1]})" for f in added),
                line=_line(text, "mapping_profiles"),
                ids=[f.key for f in added],
                hint="map a flow in flows: to override its profile mapping; errors on its "
                "activity are corrected in the profile",
            )
        )
    return added, [path for path, _ in profiles], findings
