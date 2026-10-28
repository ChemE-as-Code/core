"""Loading and saving DEXPI models: where piping and project code turn sheet content into a
pyDEXPI model and back.

The only serialization today is DEXPI XML, through pyDEXPI's public loader and serializer.
Every model load and export in ``domains/piping`` and ``project`` goes through :func:`load` and
:func:`dump`, so a further serialization pyDEXPI might offer is selected here and not at each
call site (see "Possible DEXPI YAML serialization" in docs/framework/architecture.md).

Not covered, by design: code that works on the XML text itself (the canonical form in ``fmt``,
``show``, the git projection, the authoring API, source line numbers in findings) parses it with
lxml. ``domains/process/sheets.py`` writes and loads BFD/PFD sheets with pyDEXPI directly,
because ``process`` may not import ``piping``.
"""

from __future__ import annotations

from typing import Any


def load(content: bytes, *, strict: bool = True) -> Any:
    """pyDEXPI's load of a DEXPI XML document, with its report (``.model``, ``.report``).

    Raises what pyDEXPI raises for a document it cannot load: ``ValueError``, or
    ``pydexpi.loaders.compat.ConversionRefusedError`` for an older version it will not convert.
    """
    from pydexpi.loaders.public import load_xml_with_report

    return load_xml_with_report(content, strict=strict)


def dump(model: Any, metadata: Any = None) -> bytes:
    """*model* as DEXPI XML bytes; *metadata* (``DexpiXmlModelMetadata``) sets the exported
    model name and URI."""
    from pydexpi.loaders.xml_serializer import DexpiXmlSerializer

    return DexpiXmlSerializer(export_metadata=metadata).export_to_bytes(model)
