"""``checks/checks.yaml``: the engineering-step gates of the plant."""

from typing import Literal

from pydantic import Field, model_validator

from chemeascode.foundation.schema_base import Identifier, Strict, optional_schema
from chemeascode.foundation.schemas.reviews import ReviewerKind


class Accept(Strict):
    """A validate finding accepted on purpose (e.g. a crossing that cannot be avoided)."""

    id: str = Field(
        description="The finding's id as `cheme validate --json` prints it, e.g. "
        "pid/P-03.xml#line-crossing:Line_A_S1_P1+Line_B_S1_P1; * and ? match any text."
    )
    reason: str = Field(min_length=3, description="Why it is accepted, and by whom.")


class Check(Strict):
    """One gate. Exactly one of its kinds is evaluated.

    ``validate``: no finding of the selected ``rules`` (default: all) at ``fail_on`` or above
    (default: error) that is not accepted, and a built sheet of each ``generated`` kind (bfd,
    pfd). ``files``: every glob matches a file. ``command``: a
    shell command, run at the repository root, exits with 0. ``on-sheet``: the tags (and
    classes) are drawn on the sheet(s), found by their printed tags in the loaded model, not by
    text. ``review``: a review record with front
    matter covers the current drawings and was written by an allowed kind of reviewer.
    ``datasheets``: every equipment-list item has a valid ``equipment/datasheets/<TAG>.yaml``.
    ``process-links``: every link of the process flowsheet (blocks, steps, streams, feeds,
    products) resolves against the equipment, line and instrument lists and the sheets; at
    ``level: warning`` unresolved links are reported and the gate passes, at ``error`` it fails.
    ``layout-model``: the 3D layout and its generated model meet each of ``require`` (site,
    areas, roads, racks, placed, separations, model-current, nozzles, mounted, routed, clashes,
    zones, drawings, cables, trays, hvac, lifting, lifting-current; see
    ``chemeascode.domains.spatial.gates``). ``mto``: the material take-off and the estimates meet
    each of ``require`` (mto-current, rates, estimate-current, equipment-current,
    equipment-covered; see ``chemeascode.domains.assessment.gates``). ``lca`` and ``tea``: the
    LCA and the techno-economic analysis meet each of ``require`` (see
    ``chemeascode.domains.assessment.lca.gates`` and ``.tea.gates``). ``datasheets``: a datasheet
    still marked ``draft: true`` does not count; with ``require`` (dimensions, weights, nozzles,
    drawing-current; see ``chemeascode.domains.equipment.datasheets.datasheet_gate``) each valid
    datasheet must also meet those. ``hazop``: every HAZOP study (or those ``files`` names)
    meets each of ``require`` (see ``chemeascode.project.hazop``). ``maturity``: the calculation
    maturity level ``cheme maturity`` computes reaches the one level in ``require`` (sourced,
    balanced, predictive, engineering), and with ``max_claim`` the process.yaml design maturity
    claim does not exceed the evidence (see ``chemeascode.project.maturity.maturity_gate``).
    ``issues``: no issue of the plant (``plant.yaml`` ``issues:``) with a ``gate:`` at or before
    this stage is open (of ``types``, default all; see ``chemeascode.project.issues``); n/a
    without ``issues:``.
    """

    id: str
    title: str
    stage: str = Field(description="Stage id from plant.yaml this check gates.")
    kind: Literal[
        "validate",
        "files",
        "command",
        "on-sheet",
        "review",
        "datasheets",
        "process-links",
        "layout-model",
        "mto",
        "lca",
        "tea",
        "hazop",
        "maturity",
        "issues",
    ]
    level: Literal["warning", "error"] = Field(
        default="error",
        description="kind=process-links: warning reports unresolved links and passes; error "
        "fails (typically warning at concept, error at basic).",
    )
    files: list[str] = Field(
        default_factory=list,
        description="Globs, for kind=files (kind=review: the records to consider).",
    )
    command: str | None = Field(default=None, description="Shell command, for kind=command.")
    applies: bool = Field(default=True, description="False marks the check not applicable.")
    fail_on: Literal["error", "warning", "info"] = Field(
        default="error", description="kind=validate: the lowest finding level that fails the gate."
    )
    rules: list[str] = Field(
        default_factory=list,
        description="kind=validate: only these rule ids count (* and ? match); empty: all. One "
        "that matches cheme.generated-sheet-drift also matches cheme.generator-failed.",
    )
    accept: list[Accept] = Field(
        default_factory=list,
        description="kind=validate: findings this gate accepts, each with a reason.",
    )
    generated: list[Literal["bfd", "pfd"]] = Field(
        default_factory=list,
        description="kind=validate: generated sheet kinds the gate also requires: plant.yaml "
        "declares a sheet of each kind and its file has been built (`cheme process build`).",
    )
    # -- kind: on-sheet
    sheet: str | None = Field(
        default=None, description="kind=on-sheet: sheet id (P-03) or file; omitted: any sheet."
    )
    sheets: list[str] = Field(
        default_factory=list, description="kind=on-sheet: several sheets, each must hold them."
    )
    tags: list[Identifier] = Field(
        default_factory=list,
        description="kind=on-sheet: printed tags that must be drawn (equipment, instrument, "
        "piping component or line number).",
    )
    classes: list[str] = Field(
        default_factory=list,
        description="kind=on-sheet: DEXPI classes of which at least min_count must be drawn "
        "(a class also matches its subclasses and classes ending with its name).",
    )
    min_count: int = Field(default=1, ge=1, description="kind=on-sheet: per class.")
    connected: bool = Field(
        default=False,
        description="kind=on-sheet: the items must be connected (a nozzle piped, an instrument "
        "with a measuring/signal line, a valve on a segment).",
    )

    # -- kind: layout-model
    require: list[
        Literal[
            "site",
            "areas",
            "roads",
            "racks",
            "placed",
            "separations",
            "model-current",
            "nozzles",
            "mounted",
            "routed",
            "clashes",
            "zones",
            "drawings",
            "cables",
            "trays",
            "hvac",
            "lifting",
            "lifting-current",
            "mto-current",
            "rates",
            "estimate-current",
            "equipment-current",
            "equipment-covered",
            "mapped",
            "factors",
            "no-gaps",
            "factors-published",
            "publishable",
            "lci-documented",
            "cutoff-criteria",
            "lci-emissions-complete",
            "lci-mass-balance",
            "lci-element-balance",
            "lci-carbon-origin",
            "lca-current",
            "prices",
            "no-example",
            "class-stage",
            "decision",
            "tea-current",
            "dimensions",
            "weights",
            "nozzle-schedule",
            "drawing-current",
            "assessed",
            "reviewed",
            "inputs-current",
            "actions-closed",
            "sourced",
            "balanced",
            "predictive",
            "engineering",
        ]
    ] = Field(
        default_factory=list,
        description="kind=layout-model: what the layout must meet (rules and accept: the model "
        "findings `clashes` fails on, default cheme.layout-clash-* and -headroom; topic: "
        "the review record `drawings` reads, default layout; cables: a cable to every motor "
        "and instrument, routed in trays; trays: tray fill and separation; hvac: ducts for "
        "the clad buildings within their velocity limits; lifting: a crane, a clear lane, a "
        "laydown and, with crane charts, the capacity for every heavy item; lifting-current: "
        "layout/lifting-study.csv, and .md when written, current). kind=mto: mto-current, "
        "rates, estimate-current, equipment-current (estimate/equipment-cost.csv current), "
        "equipment-covered (every "
        "listed item costed by a correlation or the project's own cost). kind=lca: mapped, "
        "factors, no-gaps (no exchange without a burden: lca/gaps.csv empty), factors-published "
        "(every exchange's factor status PUBLISHED, EPD, a background database's or none: no "
        "example, ASSUMED, PROXY, ESTIMATE or gap), publishable (every "
        "source public, or restricted with a reviewed decision), lci-documented (lca/dataset.yaml "
        "gives the publication minimum of its documentation), cutoff-criteria (the dataset's cut "
        "flows meet the 1 % rules and the never-cut list, no credit in a cut-off model, every "
        "replaced consumable disposed), lci-emissions-complete (every combustion unit, fuel "
        "feed, flare, storage tank and untreated wastewater outlet has an emission estimate or "
        "a declared exclusion), lci-mass-balance, lci-element-balance and "
        "lci-carbon-origin (the dataset closes in mass, in each element and in carbon by origin "
        "within 1 % for a simulated, 5 % for a sourced screening dataset), lca-current. "
        "kind=tea: prices (every flow priced or listed free), no-example, "
        "class-stage (the estimate class the stage expects), decision (stated and met), "
        "tea-current. kind=datasheets (optional): dimensions (the main dimensions of "
        "each item's family), weights (empty, operating, and test for a pressure-containing "
        "item), nozzle-schedule (every nozzle with a DN and a location), drawing-current (each "
        "outline drawing equipment/datasheets/<TAG>.svg what cheme datasheets drawing writes). "
        "kind=hazop (files: the study files it covers, default all): assessed (nothing "
        "unresolved), reviewed (a current human review record), inputs-current, actions-closed "
        "(every action closed or rejected), no-example (neither study nor matrix example data). "
        "kind=maturity: one level the computed calculation maturity must reach: sourced, "
        "balanced, predictive or engineering (engineering runs the whole-repository validation).",
    )
    max_claim: bool = Field(
        default=False,
        description="kind=maturity: also fail when process.yaml claims a design maturity above "
        "what the checked evidence supports (cheme.maturity-claim-exceeds).",
    )
    min_dn: float = Field(
        default=25.0,
        ge=0,
        description="kind=layout-model, routed: lines below this DN need no route.",
    )
    exclude_lines: list[str] = Field(
        default_factory=list,
        description="kind=layout-model, routed: line number patterns (CW-*, or a prefix) that "
        "need no route at this stage (utilities at basic engineering).",
    )
    exclude_fluids: list[str] = Field(
        default_factory=list,
        description="kind=layout-model, routed: line-list fluids that need no route yet.",
    )
    sections: int = Field(
        default=2,
        ge=0,
        description="kind=layout-model, drawings: sections the layout review must cite.",
    )

    # -- kind: issues
    types: list[Literal["action", "hold", "tq", "change"]] = Field(
        default_factory=list,
        description="kind=issues: the issue types that block (action, hold, tq, change); empty: "
        "all. The gate fails while an issue of the plant (plant.yaml issues:) labelled gate:<this "
        "stage or an earlier one> is open; without a GitHub token it fails as not evaluated.",
    )

    # -- kind: review
    topic: str | None = Field(
        default=None, description="kind=review: the records' front matter topic."
    )
    require_kind: list[ReviewerKind] = Field(
        default_factory=lambda: ["human", "agent"],
        description="kind=review: reviewer kinds that pass (default human and agent: a self "
        "review does not).",
    )
    current: bool = Field(
        default=True,
        description="kind=review: fail when a file in the record's scope changed after its "
        "reviewed_commit (a change of nothing but full sha256 or commit digests, such as a "
        "regenerated output's source fingerprint, does not count).",
    )

    @model_validator(mode="after")
    def _check(self) -> "Check":
        if self.kind == "on-sheet":
            if not self.tags and not self.classes:
                raise ValueError("an on-sheet check needs tags or classes")
            if self.sheet and self.sheets:
                raise ValueError("give sheet or sheets, not both")
        if self.kind in ("layout-model", "mto", "lca", "tea", "hazop") and not self.require:
            raise ValueError(f"a {self.kind} check needs require: [...]")
        mto = {
            "mto-current",
            "rates",
            "estimate-current",
            "equipment-current",
            "equipment-covered",
        }
        if self.kind == "mto" and not set(self.require) <= mto:
            raise ValueError(f"a mto check requires only {', '.join(sorted(mto))}")
        if self.kind == "layout-model" and set(self.require) & mto:
            raise ValueError(
                "mto-current, rates, estimate-current, equipment-current and equipment-covered "
                "belong to a kind: mto check"
            )
        lca = {
            "mapped",
            "factors",
            "no-gaps",
            "factors-published",
            "publishable",
            "lci-documented",
            "cutoff-criteria",
            "lci-emissions-complete",
            "lci-mass-balance",
            "lci-element-balance",
            "lci-carbon-origin",
            "lca-current",
        }
        if self.kind == "lca" and not set(self.require) <= lca:
            raise ValueError(f"a lca check requires only {', '.join(sorted(lca))}")
        if self.kind in ("layout-model", "mto") and set(self.require) & lca:
            raise ValueError(
                "mapped, factors, no-gaps, factors-published, publishable, lci-documented, "
                "cutoff-criteria, "
                "lci-emissions-complete, lci-mass-balance, lci-element-balance, lci-carbon-origin "
                "and lca-current belong to a kind: lca check"
            )
        tea = {"prices", "no-example", "class-stage", "decision", "tea-current"}
        if self.kind == "tea" and not set(self.require) <= tea:
            raise ValueError(f"a tea check requires only {', '.join(sorted(tea))}")
        hazop = {"assessed", "reviewed", "inputs-current", "actions-closed", "no-example"}
        if self.kind == "hazop" and not set(self.require) <= hazop:
            raise ValueError(f"a hazop check requires only {', '.join(sorted(hazop))}")
        if self.kind not in ("tea", "hazop") and set(self.require) & tea:
            raise ValueError(f"{', '.join(sorted(tea))} belong to a kind: tea check")
        if self.kind != "hazop" and set(self.require) & (hazop - tea):
            raise ValueError(f"{', '.join(sorted(hazop - tea))} belong to a kind: hazop check")
        sheets = {"dimensions", "weights", "nozzle-schedule", "drawing-current"}
        if self.kind == "datasheets" and not set(self.require) <= sheets:
            raise ValueError(f"a datasheets check requires only {', '.join(sorted(sheets))}")
        if self.kind != "datasheets" and set(self.require) & sheets:
            raise ValueError(
                "dimensions, weights, nozzle-schedule and drawing-current belong to a kind: "
                "datasheets check"
            )
        levels = {"sourced", "balanced", "predictive", "engineering"}
        named = "sourced, balanced, predictive, engineering"
        if self.kind == "maturity":
            if not set(self.require) <= levels or len(self.require) > 1:
                raise ValueError(f"a maturity check requires one level of {named}")
            if not self.require and not self.max_claim:
                raise ValueError("a maturity check needs require: [<level>] or max_claim: true")
        elif set(self.require) & levels:
            raise ValueError(f"{named} belong to a kind: maturity check")
        elif self.max_claim:
            raise ValueError("max_claim belongs to a kind: maturity check")
        if self.kind == "review" and not self.topic and not self.files:
            raise ValueError("a review check needs a topic or files (globs of review records)")
        return self


class CheckList(Strict, optional_schema("checks")):
    """Every gate of the plant."""

    checks: list[Check] = Field(default_factory=list)
    accept: list[Accept] = Field(
        default_factory=list,
        description="Warnings and infos accepted everywhere: `cheme validate` reports them "
        "as info with the reason, and no gate fails on them. Errors are never accepted.",
    )
