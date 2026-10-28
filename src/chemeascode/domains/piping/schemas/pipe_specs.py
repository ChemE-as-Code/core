"""``piping/pipe-specs.yaml``: pipe classes and insulation rules (optional; the outside diameters
by DN ship with cheme-as-code in ``domains/piping/data/pipe-od.yaml``)."""

from pydantic import ConfigDict, Field, model_validator

from chemeascode.foundation.schema_base import Strict, optional_schema


class PipeClass(Strict):
    """A pipe class: the line list's ``pressure_class`` (or a class code) and what it means."""

    code: str = Field(description="As the line list's pressure_class gives it, e.g. PN16.")
    material: str = ""
    rating: str | None = None
    colour: str | None = Field(default=None, description="Rendering colour, e.g. #4a7fb5.")
    notes: str = ""


class ThicknessRule(Strict):
    """Insulation thickness for lines up to (and including) ``dn_max``."""

    dn_max: float | None = Field(default=None, description="Up to this DN; none: any DN.")
    thickness_mm: float


class Insulation(Strict):
    """An insulation type, as the line list's ``insulation`` names it, and its thickness:
    ``thickness_mm`` for every DN, or ``rules`` by DN (the first that applies)."""

    model_config = ConfigDict(extra="forbid")

    type: str = Field(description="As the line list's insulation names it, any case.")
    thickness_mm: float | None = None
    rules: list[ThicknessRule] = Field(default_factory=list)
    notes: str = ""

    @model_validator(mode="after")
    def _check(self) -> "Insulation":
        if (self.thickness_mm is None) == (not self.rules):
            raise ValueError(f"insulation {self.type}: give thickness_mm or rules (one)")
        return self


class PipeSpecs(Strict, optional_schema("pipe_specs")):
    """Pipe classes and insulation thicknesses for the 3D pipe routes."""

    classes: list[PipeClass] = Field(default_factory=list)
    insulation: list[Insulation] = Field(default_factory=list)
    notes: str = ""
