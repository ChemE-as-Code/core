"""The external identifiers of the components (``process/materials.yaml``): CAS number,
InChIKey and SMILES (docs/framework/contract.md, Identity).

Rules, warnings, each finding naming the file, line, component and a hint:

- ``component-cas``: a CAS number whose last digit is not its check digit (one that is not
  digits-digits-digit at all is reported too);
- ``component-identity``: a SMILES that does not parse, or whose InChIKey or molecular formula
  differs from the component's ``inchikey`` or ``formula``. Needs RDKit (extra ``chemistry``);
  without it the SMILES is not checked and nothing is reported.

The pattern of an InChIKey is the schema's. The functions take the components as parsed, so
that they need nothing else from the process domain.
"""

from __future__ import annotations

from collections.abc import Sequence
from typing import Any

from chemeascode.domains.chemistry.formulas import parse_formula
from chemeascode.foundation.findings import Finding
from chemeascode.foundation.schema_base import CAS_RE, cas_check_digit_ok
from chemeascode.foundation.yamlsource import _yaml_line


def _cas_findings(file: str, doc: Any, i: int, component: Any) -> list[Finding]:
    cas = component.cas
    if not cas or (CAS_RE.match(cas) and cas_check_digit_ok(cas)):
        return []
    what = "is not digits-digits-digit" if not CAS_RE.match(cas) else "has a wrong check digit"
    return [
        Finding(
            file,
            "warning",
            "cheme.component-cas",
            f"components[{i}] {component.id}: CAS number {cas!r} {what}",
            line=_yaml_line(doc, ["components", i, "cas"]),
            ids=[component.id],
            hint="copy the CAS number again from its source (PubChem, NIST WebBook); the last "
            "digit is the check digit of the others",
        )
    ]


def _identity_findings(file: str, doc: Any, i: int, component: Any) -> list[Finding]:
    from chemeascode.integrations.rdkit import smiles_identity

    def finding(message: str, field: str, hint: str) -> Finding:
        return Finding(
            file,
            "warning",
            "cheme.component-identity",
            f"components[{i}] {component.id}: {message}",
            line=_yaml_line(doc, ["components", i, field]),
            ids=[component.id],
            hint=hint,
        )

    try:
        inchikey, formula = smiles_identity(component.smiles)
    except ValueError:
        return [
            finding(
                f"SMILES {component.smiles!r} does not parse",
                "smiles",
                "write a valid SMILES (e.g. from PubChem), or leave smiles out",
            )
        ]
    found = []
    if component.inchikey and component.inchikey != inchikey:
        found.append(
            finding(
                f"InChIKey {component.inchikey} differs from {inchikey}, the InChIKey of SMILES "
                f"{component.smiles!r}",
                "inchikey",
                "one of smiles and inchikey names another compound: correct the wrong one",
            )
        )
    given = parse_formula(component.formula) if component.formula else None
    derived = parse_formula(formula)
    if given is not None and derived is not None and given != derived:
        found.append(
            finding(
                f"formula {component.formula} differs from {formula}, the formula of SMILES "
                f"{component.smiles!r}",
                "formula",
                "one of smiles and formula names another compound: correct the wrong one",
            )
        )
    return found


def identifier_findings(file: str, doc: Any, components: Sequence[Any]) -> list[Finding]:
    """``cheme.component-cas`` and ``cheme.component-identity`` of *components* (the
    ``components`` of *file*, parsed from *doc*); see the module docstring."""
    try:
        import rdkit  # noqa: F401

        checks_smiles = True
    except ImportError:
        checks_smiles = False
    findings = []
    for i, component in enumerate(components):
        findings += _cas_findings(file, doc, i, component)
        if component.smiles and checks_smiles:
            findings += _identity_findings(file, doc, i, component)
    return findings
