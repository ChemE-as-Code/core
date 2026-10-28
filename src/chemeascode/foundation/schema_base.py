"""Shared base for the YAML schemas."""

import re
from typing import Annotated, Any, ClassVar, Literal

from pydantic import BaseModel, BeforeValidator, ConfigDict, Field, field_validator

#: Where a value comes from (docs/framework/contract.md): the user's figure, an engineering
#: guess, or a tool's result (the producing tool is named at the start of ``source``).
Provenance = Literal["given", "assumed", "calculated"]

#: What kind of figure a value is, refining its :data:`Provenance` (optional; the class stays
#: what tools and the LCA read): ``given`` a ``measured``, ``vendor`` or ``literature`` figure;
#: ``assumed`` a ``design-rule``, an ``estimate`` or a ``literature`` figure taken as a guess;
#: ``calculated`` a ``simulated`` result (``cheme process simulate``) or a ``correlation``
#: (``cheme process props``, ``cheme datasheets fill``).
Origin = Literal[
    "measured", "vendor", "literature", "design-rule", "estimate", "simulated", "correlation"
]

#: The provenance classes each :data:`Origin` refines; another class is
#: ``cheme.provenance-origin``.
ORIGIN_CLASSES: dict[str, tuple[str, ...]] = {
    "measured": ("given",),
    "vendor": ("given",),
    "literature": ("given", "assumed"),
    "design-rule": ("assumed",),
    "estimate": ("assumed",),
    "simulated": ("calculated",),
    "correlation": ("calculated",),
}

#: A stable identifier: letters, digits, _ and -, starting with a letter.
ID_PATTERN = re.compile(r"^[A-Za-z][A-Za-z0-9_\-]*$")
#: CAS Registry Number: digits-digits-digit, e.g. 74-82-8.
CAS_RE = re.compile(r"^\d{2,7}-\d{2}-\d$")
#: Standard InChIKey: 14 letters, 10 letters, 1 letter, e.g. VNWKTOKETHGBQD-UHFFFAOYSA-N.
INCHIKEY_RE = re.compile(r"^[A-Z]{14}-[A-Z]{10}-[A-Z]$")


def cas_check_digit_ok(cas: str) -> bool:
    """Whether the last digit of the CAS number *cas* (of :data:`CAS_RE`'s shape) is its check
    digit: the other digits, from the right, weighted 1, 2, 3, ..., summed modulo 10."""
    digits = cas.replace("-", "")
    body = digits[:-1][::-1]
    return sum(i * int(d) for i, d in enumerate(body, start=1)) % 10 == int(digits[-1])


class Strict(BaseModel):
    """Unknown keys are refused, so a typo is reported rather than silently ignored."""

    model_config = ConfigDict(extra="forbid")


def _identifier(value: Any) -> Any:
    """A tag, number or DN as text: YAML reads ``number: 47121`` or ``nominal_diameter: 80`` as a
    number, which means the same as the quoted string. Surrounding blanks are dropped."""
    if isinstance(value, int | float) and not isinstance(value, bool):
        value = f"{value:g}" if isinstance(value, float) else str(value)
    return value.strip() if isinstance(value, str) else value


#: A tag, line or segment number, or DN, compared with what a P&ID holds.
Identifier = Annotated[str, BeforeValidator(_identifier)]


def unsupported_schema(found: object, expected: str) -> str:
    """The error for a ``schema:`` other than *expected* (``cheme/<kind>/vN``). The id under the
    package's name before 0.7.0 (``plantcode/<kind>/vN``) gets the new spelling."""
    if found == "plantcode/" + expected.removeprefix("cheme/"):
        return (
            f"schema {found!r} is the id from before the rename of plantcode to cheme-as-code "
            f"(0.7.0): write `schema: {expected}`"
        )
    return f"schema {found!r} is not supported: this cheme-as-code reads {expected}"


def optional_schema(kind: str) -> type[BaseModel]:
    """A base that gives a file kind its optional ``schema: cheme/<kind>/v1`` (first in the
    exported schema). A file without the field reads as v1; any other id is refused with the
    shared message. ``cheme migrate`` writes the field into the files that lack it."""
    expected = f"cheme/{kind}/v1"

    class OptionalSchema(BaseModel):
        #: The id this cheme-as-code reads for the kind.
        schema_id: ClassVar[str] = expected

        schema_: str | None = Field(
            default=None,
            alias="schema",
            description=f"{expected}; optional (a file without it reads as {expected}).",
        )

        @field_validator("schema_")
        @classmethod
        def _version(cls, value: str | None) -> str | None:
            if value is not None and value != expected:
                raise ValueError(unsupported_schema(value, expected))
            return value

    return OptionalSchema
