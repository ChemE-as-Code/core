"""Canonical form of a DEXPI XML P&ID, so hand edits and generated rewrites diff cleanly.

Formatting does two things and changes no meaning:

1. every ``<Object>`` without an id gets a readable, deterministic one, derived from the nearest
   identified ancestor and the property that composes it (``Tank1_Nozzles1``). pyDEXPI would
   otherwise mint a random id on every load, which makes every diff noisy;
2. the document is written back through pyDEXPI's serializer: DEXPI 2.0.1 imports, properties in
   their canonical order, two-space indentation. The ``<Model>`` keeps its ``name`` and ``uri``.

Formatting refuses a document whose load reports a loss: a loader error, or a warning that
content "will be ignored" (such as a ``Data`` property DEXPI does not define). Rewriting it would
drop that silently; ``cheme validate`` says what to fix first. What the loader does not report
(an unknown child element or attribute, say) is not detected. XML comments and processing
instructions are not part of the model and do not survive either; formatting drops them and
reports each one (:func:`dropped_markup`, :attr:`FormatResult.dropped`), since fragments and
snippets carry comments that are meant to go.

The exception is cheme-as-code's own provenance: a comment whose text starts with
:data:`PROVENANCE_PREFIX` (``<!-- cheme-process {...} -->``, say) is kept. Wherever it was, it
is written back at the top of the document (after an XML declaration, before pyDEXPI's banner
and the root element), one per line in document order, so formatting twice gives the same
bytes. Nothing else should start a comment with ``cheme-``; other comments are dropped and
reported as before.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from lxml import etree

_ID_UNSAFE = re.compile(r"[^A-Za-z0-9_]")


class FormatRefused(Exception):
    """The document cannot be formatted without losing content."""


@dataclass
class FormatResult:
    """What formatting did to one file."""

    path: Path
    changed: bool
    ids_assigned: int
    #: ``line N: <!-- ... -->`` for every comment or processing instruction the rewrite dropped.
    dropped: list[str] = field(default_factory=list)


def _parse(content: bytes) -> etree._Element:
    return etree.fromstring(content, etree.XMLParser(resolve_entities=False, no_network=True))


def _safe(text: str) -> str:
    text = _ID_UNSAFE.sub("_", text)
    return text if re.match(r"[A-Za-z_]", text) else f"_{text}"


def assign_ids(root: etree._Element) -> int:
    """Give every ``<Object>`` without an id a deterministic one. Returns how many were given.

    The id is ``<ancestor id>_<property><n>``: the nearest ancestor object with an id, the
    ``property`` of the ``<Components>`` holding the object (or its class when there is none),
    and the lowest number not yet taken. A ``RepresentationGroup`` is named after the object it
    represents instead (``Tank1_Drawing1``), so what it draws is readable from the id. Document
    order decides the numbers, so the same document always gets the same ids.
    """
    taken = {e.get("id") for e in root.iter() if isinstance(e.tag, str) and e.get("id")}
    assigned = 0
    for element in root.iter("Object"):
        if element.get("id"):
            continue
        anchor = "Model"
        for ancestor in element.iterancestors("Object"):
            if ancestor.get("id"):
                anchor = ancestor.get("id")
                break
        parent = element.getparent()
        represents = element.find("References[@property='Represents']")
        if represents is not None and represents.get("objects", "").split():
            # A drawing is named after what it draws: Tank1_Drawing1.
            anchor = represents.get("objects").split()[0].lstrip("#")
            part = "Drawing"
        elif parent is not None and parent.tag == "Components" and parent.get("property"):
            part = parent.get("property")
        else:
            part = element.get("type", "Object").rsplit(".", 1)[-1].rsplit("/", 1)[-1]
        stem = _safe(f"{anchor}_{part}")
        number = 1
        while f"{stem}{number}" in taken:
            number += 1
        new_id = f"{stem}{number}"
        element.set("id", new_id)
        taken.add(new_id)
        assigned += 1
    return assigned


#: The comment pyDEXPI's serializer writes on top of every document, whatever its version.
_BANNER = re.compile(r"<!--\s*Generated with pyDEXPI\b")


#: A comment whose text (leading whitespace aside) starts with this is cheme-as-code's own
#: provenance (``<!-- cheme-process {...} -->``): formatting keeps it (:func:`kept_comments`).
PROVENANCE_PREFIX = "cheme-"


def _markup(root: etree._Element) -> list[Any]:
    """Every comment and processing instruction of the document, in document order (also
    before and after the root element)."""
    nodes = [
        *reversed(list(root.itersiblings(preceding=True))),
        *root.iter(etree.Comment, etree.ProcessingInstruction),
        *root.itersiblings(),
    ]
    return [n for n in nodes if n.tag is etree.Comment or n.tag is etree.ProcessingInstruction]


def _is_provenance(node: Any) -> bool:
    return node.tag is etree.Comment and (node.text or "").lstrip().startswith(PROVENANCE_PREFIX)


def kept_comments(root: etree._Element | bytes) -> list[str]:
    """The text of every cheme-as-code provenance comment of the document (*root*, or its
    bytes), in document order: formatting writes them back (:data:`PROVENANCE_PREFIX`)."""
    if isinstance(root, bytes):
        root = _parse(root)
    return [node.text or "" for node in _markup(root) if _is_provenance(node)]


def dropped_markup(root: etree._Element | bytes) -> list[str]:
    """``line N: <!-- ... -->`` for every comment and processing instruction of the document
    (*root*, or its bytes; also before and after the root element): formatting drops them, the
    DEXPI model has no place for them. pyDEXPI's own ``Generated with pyDEXPI`` comment is left
    out: the serializer writes it again; so are cheme-as-code's provenance comments, which
    formatting keeps (:func:`kept_comments`).
    """
    if isinstance(root, bytes):
        root = _parse(root)
    found = []
    for node in _markup(root):
        if _is_provenance(node):
            continue
        text = " ".join(etree.tostring(node, encoding="unicode", with_tail=False).split())
        if _BANNER.match(text):
            continue
        text = text if len(text) <= 80 else text[:77] + "..."
        found.append(f"line {node.sourceline}: {text}" if node.sourceline else text)
    return found


def dropped_note(dropped: list[str], limit: int = 3) -> str:
    """``dropped 2 XML comment(s) / processing instruction(s): line 4: <!-- ... -->; ...``."""
    shown = "; ".join(dropped[:limit]) + ("; ..." if len(dropped) > limit else "")
    return f"dropped {len(dropped)} XML comment(s) / processing instruction(s): {shown}"


def format_bytes(content: bytes) -> tuple[bytes, int]:
    """The canonical form of *content*, and how many ids were assigned on the way (a writer
    that reports what it drops uses :func:`format_reporting`)."""
    formatted, assigned, _ = format_reporting(content)
    return formatted, assigned


def _lost(entry: Any) -> bool:
    """Whether a loader report entry means pyDEXPI's model lacks something the document has."""
    from pydexpi.loaders.error_registry import ErrorLevels

    if entry.level in (ErrorLevels.ERROR, ErrorLevels.CRITICAL):
        return True
    # pyDEXPI's tree loader (pydexpi/loaders/tree_ref_base/loader.py) reports an attribute its
    # class does not have as a WARNING "Field '...' is not a valid ... and will be ignored."; an
    # entry with ``content`` is something the load did not keep (error_registry.py).
    return entry.level == ErrorLevels.WARNING and (
        "will be ignored" in entry.message or entry.content is not None
    )


def format_reporting(content: bytes) -> tuple[bytes, int, list[str]]:
    """:func:`format_bytes`, and the comments and processing instructions it dropped
    (:func:`dropped_markup`)."""
    from pydexpi.loaders.xml_serializer import DexpiXmlModelMetadata

    from chemeascode.domains.piping import dexpi_io

    try:
        root = _parse(content)
    except etree.XMLSyntaxError as failure:
        raise FormatRefused(f"not well-formed XML: {failure.msg}") from failure
    dropped = dropped_markup(root)
    kept = kept_comments(root)
    assigned = assign_ids(root)
    with_ids = etree.tostring(root, xml_declaration=True, encoding="UTF-8")

    try:
        loaded = dexpi_io.load(with_ids, strict=True)
    except ValueError as failure:
        raise FormatRefused(f"pyDEXPI could not load it: {failure}") from failure
    lost = [e for e in loaded.errors if _lost(e)]
    if lost:
        first = lost[0]
        where = f" (line {first.line})" if first.line else ""
        raise FormatRefused(
            f"pyDEXPI would drop content ({len(lost)} loader finding(s), first{where}: "
            f"{first.message}); fix what `cheme validate` reports first"
        )
    # The serializer would otherwise write pyDEXPI's defaults (name="example") back.
    defaults = DexpiXmlModelMetadata()
    metadata = DexpiXmlModelMetadata(
        name=root.get("name") or defaults.name, uri=root.get("uri") or defaults.uri
    )
    return _reinsert(dexpi_io.dump(loaded.model, metadata), kept), assigned, dropped


def _reinsert(content: bytes, comments: list[str]) -> bytes:
    """*content* with *comments* (their text) at its top, after an XML declaration, one per
    line."""
    if not comments:
        return content
    block = b"".join(b"<!--" + text.encode("utf-8") + b"-->\n" for text in comments)
    if content.startswith(b"<?xml"):
        end = content.index(b"?>") + 2
        return content[:end] + b"\n" + block + content[end:].lstrip(b"\r\n")
    return block + content


def format_file(path: Path, *, check: bool = False) -> FormatResult:
    """Format *path* in place, or with *check* only report whether it would change."""
    content = path.read_bytes()
    formatted, assigned, dropped = format_reporting(content)
    changed = formatted != content
    if changed and not check:
        path.write_bytes(formatted)
    return FormatResult(path, changed, assigned, dropped)
