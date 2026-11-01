"""Declared steel sections: their real sizes, and a name the model does not know."""

from __future__ import annotations

import pytest
import yaml
from pydantic import ValidationError

from chemeascode.domains.assessment.mto import section_masses
from chemeascode.domains.spatial.layout_validate import check_layout
from chemeascode.domains.spatial.schemas import PipeSupport, Rack, Structure
from chemeascode.domains.spatial.structures import (
    BEAM_LARGEST,
    BEAMS,
    COLUMNS,
    SECTION_SIZES,
    SUPPORT_POST,
    section,
    section_size,
)


@pytest.mark.parametrize(
    ("name", "size"),
    [
        ("HEB100", (0.1, 0.1)),
        ("HEB 300", (0.3, 0.3)),
        ("heb600", (0.3, 0.6)),
        ("HEB1000", (0.3, 1.0)),
        ("HEA100", (0.1, 0.096)),
        ("HEA400", (0.3, 0.39)),
        ("IPE300", (0.15, 0.3)),
        ("IPE600", (0.22, 0.6)),
        ("UPN200", (0.075, 0.2)),
        ("C200", (0.075, 0.2)),
        ("L100x10", (0.1, 0.1)),
        ("RHS 50x50", (0.05, 0.05)),
        ("FL100x5", (0.005, 0.1)),
    ],
)
def test_declared_sections_take_their_real_size(name, size):
    assert section_size(name) == size
    assert section([], (), SUPPORT_POST, name) == (name, *size)


def test_the_default_sections_are_in_the_table():
    for _, name, b, h in (*BEAMS, *COLUMNS, (None, *BEAM_LARGEST)):
        assert section_size(name) == (b, h)


def test_every_section_the_schema_accepts_has_a_mass_in_the_take_off_and_back():
    assert set(SECTION_SIZES) == set(section_masses())


def test_an_unknown_section_is_refused_not_drawn_300_by_300():
    assert section_size("W12x26") is None
    with pytest.raises(ValueError, match="unknown steel section 'W12x26'"):
        section([], (), SUPPORT_POST, "W12x26")
    structure = {"id": "S", "origin": [0, 0], "spans_x": [6], "spans_y": [6]}
    with pytest.raises(ValidationError, match="unknown steel section 'HEB310'"):
        Structure.model_validate({**structure, "beam_section": "HEB310"})
    with pytest.raises(ValidationError, match="unknown steel section"):
        Structure.model_validate({**structure, "column_section": "IPE 310"})
    Structure.model_validate({**structure, "column_section": "HEA 300"})
    rack = {"id": "PR", "points": [[0, 0], [20, 0]], "width": 4, "levels": [6]}
    with pytest.raises(ValidationError, match="unknown steel section"):
        Rack.model_validate({**rack, "intermediate_supports": {"section": "UB305"}})
    support = {"id": "PS-1", "at": [5, 5], "top": 3}
    with pytest.raises(ValidationError, match="unknown steel section"):
        PipeSupport.model_validate({**support, "section": "HEB100x"})
    assert PipeSupport.model_validate({**support, "section": "HEB100"}).section == "HEB100"


def test_an_unknown_section_is_a_schema_finding_at_its_line():
    site = (
        "site: {width: 50, depth: 50}\n"
        "racks:\n"
        "  - id: PR\n"
        "    points: [[0, 10], [40, 10]]\n"
        "    width: 4\n"
        "    levels: [6]\n"
        "    intermediate_supports: {section: W12x26}\n"
    )
    layout = check_layout({"site_plan": ("layout/site-plan.yaml", site)}, None, None)
    (error,) = [f for f in layout.findings if f.rule == "yaml.schema"]
    assert error.line == 7 and "unknown steel section 'W12x26'" in error.message
    assert yaml.safe_load(site)  # the text itself is valid YAML
