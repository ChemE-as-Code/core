import sys

import pytest
from lxml import etree

from chemeascode.domains.piping.render import (
    Crop,
    PngUnavailable,
    TooLarge,
    crop_svg,
    load_model,
    render_svg,
    svg_to_png,
)

from .conftest import REFERENCE


def test_crop_parse_orders_corners():
    assert Crop.parse("30, 40,10,20") == Crop(10, 20, 30, 40)
    for bad in ("1,2,3", "a,b,c,d", "1,1,1,5", "nan,0,10,10", "0,0,inf,10"):
        with pytest.raises(ValueError):
            Crop.parse(bad)


def test_crop_svg_sets_viewbox():
    svg = etree.fromstring(b'<svg width="420" height="297" viewBox="0 0 420 297"/>')
    crop_svg(svg, Crop(10, 20, 110.5, 70))
    assert svg.get("viewBox") == "10 20 100.5 50"
    assert (svg.get("width"), svg.get("height")) == ("100.5", "50")


def test_png_scale_is_pixels_per_unit():
    png = svg_to_png('<svg xmlns="http://www.w3.org/2000/svg" width="10" height="5"/>', 3)
    assert png.startswith(b"\x89PNG")
    assert int.from_bytes(png[16:20]) == 30 and int.from_bytes(png[20:24]) == 15


def test_png_without_resvg(monkeypatch):
    monkeypatch.setitem(sys.modules, "resvg_py", None)
    with pytest.raises(PngUnavailable, match=r"cheme-as-code\[png\]"):
        svg_to_png("<svg/>")


def test_png_size_is_capped():
    with pytest.raises(TooLarge, match="Mpx"):
        svg_to_png('<svg xmlns="http://www.w3.org/2000/svg" width="1e5" height="1e5"/>', 1)


def _sheet_groups(svg: str) -> list[tuple[str | None, str | None]]:
    root = etree.fromstring(svg.encode())
    content = next(g for g in root.iter("{*}g") if g.get("class") == "diagram")
    return [(g.get("class"), g.get("id")) for g in content]


def test_title_block_and_border_get_their_xml_ids():
    from chemeascode.domains.piping.fmt import format_bytes

    formatted, _ = format_bytes(REFERENCE.read_bytes())
    groups = _sheet_groups(render_svg(load_model(formatted)))
    labels = [(c, i) for c, i in groups if c in ("label", "border")]
    assert [c for c, _ in labels] == ["border", "label"]
    for _, object_id in labels:
        assert object_id and f'id="{object_id}"'.encode() in formatted
    # Represented objects keep the id of what they represent.
    assert all(i for c, i in groups if c == "representation-group")


def test_made_up_ids_are_not_written():
    # The reference P&ID has no XML ids: pyDEXPI invents new ones on every load.
    groups = _sheet_groups(render_svg(load_model(REFERENCE)))
    assert [i for c, i in groups if c in ("label", "border")] == [None, None]
