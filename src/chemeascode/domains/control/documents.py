"""``process/narrative.md`` and ``control/philosophy.md``: Markdown with YAML front matter.

The text explains; the front matter names, by id, what the text is about (the process sections
of the narrative, the objectives and failures of the philosophy) and the loops, sequences,
interlocks, tags and cases they rest on, so ``cheme validate`` can check those references.
The prose itself is not checked beyond its headings: each narrative section needs a heading
``## <id> <title>``, the philosophy the headings of :data:`PHILOSOPHY_HEADINGS`.

A document that is still the template ``cheme init`` wrote, unchanged, is not started: it is
neither checked nor reported, so a plant that does not document its control gets no findings
and no empty pages. Any edit starts it.

Whether a document is drafted, reviewed or accepted comes from the review records
(``foundation.reviews.coverage``), never from the document itself.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import yaml
from pydantic import BaseModel, ValidationError

from chemeascode.foundation.findings import Finding
from chemeascode.foundation.workspace import Workspace
from chemeascode.foundation.yamlsource import _yaml_line

NARRATIVE_FILE = "process/narrative.md"
PHILOSOPHY_FILE = "control/philosophy.md"

#: The topics a control philosophy covers, each a heading of its body (matched ignoring case,
#: as the start of the heading text).
PHILOSOPHY_HEADINGS = (
    "Operating objectives",
    "Control hierarchy",
    "Normal operation and disturbances",
    "Operator and automatic actions",
    "Equipment and utility failures",
    "Assumptions and open points",
)

#: The fingerprints of the files ``cheme init`` writes (templates/project/); a test keeps them
#: in step with the templates.
TEMPLATE_FINGERPRINTS = {
    NARRATIVE_FILE: "sha256:510bf08b24e7e8fe7c1245a1283a06d21476ba72d11d936abbc7227a282d83c8",
    PHILOSOPHY_FILE: "sha256:f08c020dad3de417d10371f036d4b66e77e246ae24dc11522cf15304a6927270",
}

_HEADING = re.compile(r"^#{1,6}\s+(.+?)\s*#*\s*$")
_HIDDEN = re.compile(r"<!--.*?-->|^```.*?^```", re.DOTALL | re.MULTILINE)


@dataclass
class Document:
    """One control document: its front matter (parsed, or the errors) and its headings."""

    name: str
    kind: str
    front: Any = None
    #: The YAML node of the front matter, for line numbers (:meth:`line`).
    node: Any = None
    has_front: bool = False
    errors: list[Finding] = field(default_factory=list)
    #: Heading texts of the body, outside comments and code blocks.
    headings: list[str] = field(default_factory=list)

    def line(self, loc: tuple[Any, ...]) -> int | None:
        """The file line of the front matter entry at *loc*."""
        found = _yaml_line(self.node, loc) if self.node is not None else None
        return found + 1 if found else None  # the block starts on line 2

    #: :func:`content_fingerprint` of the file's text.
    fingerprint: str = ""

    @property
    def started(self) -> bool:
        """False while the file is still the template ``cheme init`` wrote, byte for byte
        (:data:`TEMPLATE_FINGERPRINTS`); any edit starts it. A document not started is neither
        checked nor shown."""
        return self.fingerprint != TEMPLATE_FINGERPRINTS.get(self.name)

    def has_heading(self, start: str) -> bool:
        start = start.lower()
        return any(h.lower().startswith(start) for h in self.headings)


def read_document(path: Path, name: str, kind: str, model: type[BaseModel]) -> Document:
    """*path* (a Markdown file) with its front matter validated against *model*."""
    from chemeascode.foundation.provenance import file_fingerprint

    document = Document(name, kind, fingerprint=file_fingerprint(path))
    try:
        text = path.read_text(encoding="utf-8-sig")  # a BOM is not part of the text
    except (OSError, UnicodeDecodeError) as failure:
        document.errors.append(_error(name, f"cannot be read as UTF-8 text: {failure}", 1))
        return document
    lines = text.splitlines()
    body = text
    if lines and lines[0].strip() == "---":
        end = next((i for i in range(1, len(lines)) if lines[i].strip() in ("---", "...")), None)
        document.has_front = True
        if end is None:
            document.errors.append(_error(name, "front matter has no closing '---' line", 1))
            return document
        block = "\n".join(lines[1:end])
        body = "\n".join(lines[end + 1 :])
        try:
            data = yaml.safe_load(block)
            document.node = yaml.compose(block)
        except yaml.YAMLError as failure:
            mark = getattr(failure, "problem_mark", None)
            message = f"front matter is not YAML: {failure}".splitlines()[0]
            document.errors.append(_error(name, message, mark.line + 2 if mark else 1))
            return document
        if data is None:
            data = {}
        if not isinstance(data, dict):
            document.errors.append(_error(name, "front matter must be a mapping", 2))
            return document
        try:
            document.front = model.model_validate(data)
        except ValidationError as failure:
            for error in failure.errors():
                where = ".".join(str(p) for p in error["loc"])
                document.errors.append(
                    _error(name, f"{where}: {error['msg']}", document.line(error["loc"]) or 1)
                )
    else:
        document.front = model.model_validate({})
    for line in _HIDDEN.sub("", body).splitlines():
        match = _HEADING.match(line)
        if match:
            document.headings.append(match.group(1))
    return document


def _error(name: str, message: str, line: int) -> Finding:
    kind = "narrative" if name == NARRATIVE_FILE else "control_philosophy"
    return Finding(
        name,
        "error",
        "cheme.control-document",
        message,
        line=line,
        hint=f"see `cheme schema {kind}`",
    )


def load_documents(workspace: Workspace) -> dict[str, Document]:
    """The narrative and the control philosophy the repository has, by kind."""
    from chemeascode.domains.control.schemas import Narrative, Philosophy

    found = {}
    for kind, name, model in (
        ("narrative", NARRATIVE_FILE, Narrative),
        ("philosophy", PHILOSOPHY_FILE, Philosophy),
    ):
        path = workspace.root / name
        if path.is_file():
            found[kind] = read_document(path, name, kind, model)
    return found
