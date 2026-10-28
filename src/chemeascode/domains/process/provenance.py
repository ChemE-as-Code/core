"""What a generated process sheet was built from, and whether it still is.

Every generated sheet starts with one XML comment::

    <!-- cheme-process {"generator_version": "1", "generator_sha256": "...",
         "schema": "cheme/process/v1", "view": "bfd", "case": "design",
         "source_sha256": "...", "output_sha256": "..."} -->

``source_sha256`` fingerprints the canonical input (both YAML files as parsed, the view's layout
overrides, the title-block data); ``output_sha256`` the canonical XML (C14N, comments left out)
as generated; ``generator_sha256`` the generator code (the sources of
:mod:`chemeascode.domains.process`). ``cheme validate`` compares them:

- XML changed since generation: ``cheme.generated-edited`` (error);
- generator version, generator code or schema version changed: ``cheme.generated-version``
  (warning; a sheet without ``generator_sha256``, written before 0.6, is compared by version);
- YAML changed since generation: ``cheme.generated-outdated`` (warning).

A YAML edit changes only the source fingerprint, so it never reports ``generated-edited``.
"""

from __future__ import annotations

import hashlib
import json
import re
from functools import cache
from pathlib import Path
from typing import Any

from lxml import etree

from chemeascode.domains.process import GENERATOR_VERSION, SCHEMA

_COMMENT = re.compile(rb"<!-- cheme-process (\{.*?\}) -->\n?")


# The modules that turn process/*.yaml into BFD/PFD sheets. Reports, checks and YAML-writing
# commands (streams, summary, sheets, fill, propagate) are left out: editing them changes no sheet.
GENERATOR_MODULES = (
    "__init__.py",
    "build.py",
    "layout.py",
    "model.py",
    "props.py",
    "provenance.py",
    "schema.py",
)


@cache
def generator_fingerprint() -> str:
    """SHA-256 of the generator code: the :data:`GENERATOR_MODULES` of
    :mod:`chemeascode.domains.process` by name and content (line endings normalised), so a code
    change without a version bump is noticed."""
    digest = hashlib.sha256()
    here = Path(__file__).parent
    for path in (here / name for name in GENERATOR_MODULES):
        digest.update(path.name.encode() + b"\0")
        digest.update(path.read_bytes().replace(b"\r\n", b"\n") + b"\0")
    return digest.hexdigest()


def source_fingerprint(process: Any, view: str, meta: dict[str, str]) -> str:
    """SHA-256 of the canonical input of *view*: the parsed YAML, not its formatting. Unset
    optional values are left out, so a new optional schema field changes no fingerprint."""
    flowsheet = process.flowsheet.model_dump(mode="json", by_alias=True, exclude_none=True)
    flowsheet["layout"] = flowsheet.get("layout", {}).get(view, {})
    if view != "bfd":
        flowsheet.pop("bfd", None)
    materials = (
        process.materials.model_dump(mode="json", by_alias=True, exclude_none=True)
        if process.materials
        else None
    )
    payload = {"view": view, "flowsheet": flowsheet, "materials": materials, "meta": meta}
    canonical = json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def output_fingerprint(content: bytes) -> str:
    """SHA-256 of *content*'s canonical XML (C14N without comments)."""
    root = etree.fromstring(content, etree.XMLParser(resolve_entities=False, no_network=True))
    canonical = etree.tostring(root, method="c14n", with_comments=False)
    return hashlib.sha256(canonical).hexdigest()


def stamp(content: bytes, view: str, case: str, source: str) -> bytes:
    """*content* with its provenance comment after the XML declaration."""
    record = {
        "generator_version": GENERATOR_VERSION,
        "generator_sha256": generator_fingerprint(),
        "schema": SCHEMA,
        "view": view,
        "case": case,
        "source_sha256": source,
        "output_sha256": output_fingerprint(content),
    }
    comment = b"<!-- cheme-process " + json.dumps(record).encode() + b" -->\n"
    if content.startswith(b"<?xml"):
        end = content.index(b"?>") + 2
        return content[:end] + b"\n" + comment + content[end:].lstrip(b"\r\n")
    return comment + content


def read(content: bytes) -> dict[str, Any] | None:
    """The provenance record of a generated sheet, None when it has none."""
    found = _COMMENT.search(content[:4096])
    if found is None:
        return None
    try:
        return json.loads(found.group(1))
    except ValueError:
        return None
