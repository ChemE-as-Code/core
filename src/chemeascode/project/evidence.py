"""The reaction evidence of a plant repository (``process/reaction-evidence.yaml``,
:mod:`chemeascode.domains.chemistry.evidence`) against its materials, reactions and catalysts.

The evidence is gathered before there is a flowsheet, so this reads the three files on its own
rather than through the process model. A file that does not follow its schema contributes no
ids here; its schema findings are the process checks' to report.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import yaml
from pydantic import BaseModel

from chemeascode.domains.chemistry import evidence as ev
from chemeascode.domains.chemistry.catalysts import CATALYSTS_FILE, Catalysts
from chemeascode.domains.chemistry.reactions import REACTIONS_FILE, Reactions
from chemeascode.domains.process import MATERIALS_FILE
from chemeascode.domains.process.schema import Materials
from chemeascode.foundation.findings import Finding
from chemeascode.foundation.yamlsource import _compose


class _Unreadable:
    """A file that exists but does not load."""


def _parsed[T: BaseModel](root: Path, name: str, model: type[T]) -> T | None | _Unreadable:
    path = root / name
    if not path.is_file():
        return None
    try:
        return model.model_validate(yaml.safe_load(path.read_text(encoding="utf-8")) or {})
    except (OSError, ValueError, yaml.YAMLError):  # ValidationError, UnicodeDecodeError
        return _Unreadable()


def declared(root: Path) -> tuple[ev.Declared, Any]:
    """The component, reaction and catalyst ids of the plant at *root* (None for a file that is
    missing or does not load), and the YAML nodes of its reactions file."""
    root = Path(root)
    files = {
        MATERIALS_FILE: _parsed(root, MATERIALS_FILE, Materials),
        REACTIONS_FILE: _parsed(root, REACTIONS_FILE, Reactions),
        CATALYSTS_FILE: _parsed(root, CATALYSTS_FILE, Catalysts),
    }
    loaded = {k: v for k, v in files.items() if v is not None and not isinstance(v, _Unreadable)}
    materials, reactions, catalysts = (loaded.get(k) for k in files)
    found = ev.Declared(
        components={c.id for c in materials.components} if materials is not None else None,
        catalysts={c.id for c in catalysts.catalysts} if catalysts is not None else None,
        unreadable=frozenset(k for k, v in files.items() if isinstance(v, _Unreadable)),
    )
    if reactions is not None:
        found.reactions = {}
        for i, reaction in enumerate(reactions.reactions):
            if reaction.id not in found.reactions:
                found.reactions[reaction.id] = reaction
                found.reaction_index[reaction.id] = i
    doc = _compose(root / REACTIONS_FILE) if reactions is not None else None
    return found, doc


def evidence_findings(root: Path, targets: set[Path] | None = None) -> tuple[list[Finding], bool]:
    """Every ``cheme.evidence-*`` finding of the plant at *root*, and whether it has an evidence
    file. With *targets*, only when one of them is the evidence file or a file it refers to."""
    root = Path(root)
    path = root / ev.EVIDENCE_FILE
    if not path.is_file():
        return [], False
    related = [ev.EVIDENCE_FILE, MATERIALS_FILE, REACTIONS_FILE, CATALYSTS_FILE]
    if targets is not None and not any((root / p).resolve() in targets for p in related):
        return [], True
    return _checked(root)[1], True


def _checked(root: Path) -> tuple[ev.ReactionEvidence | None, list[Finding]]:
    evidence, doc, findings = ev.load(root)
    if evidence is not None:
        known, reactions_doc = declared(root)
        findings += ev.rules(evidence, doc, known, reactions_doc)
    findings.sort(key=lambda f: (f.file, f.line or 0))
    return evidence, findings


def checked(root: Path) -> tuple[ev.ReactionEvidence | None, list[Finding]]:
    """The evidence of the plant at *root* (None when the file is missing or does not load) and
    every ``cheme.evidence-*`` finding on it, unaccepted (``cheme maturity`` reads the errors)."""
    return _checked(Path(root))


def comparison(root: Path) -> tuple[ev.ReactionEvidence | None, list[Finding]]:
    """The evidence of the plant at *root* for ``cheme chemistry evidence`` (None when the file
    is missing or does not load), with its findings as ``cheme validate`` reports them: the
    warnings ``checks/checks.yaml`` accepts are accepted infos."""
    from chemeascode.foundation.workspace import Workspace
    from chemeascode.project.validate import Report, _accept

    evidence, findings = _checked(Path(root))
    report = Report()
    report.findings = findings
    _accept(Workspace(Path(root)), report, full=False)
    return evidence, report.findings
