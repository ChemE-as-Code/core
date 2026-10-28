"""Import the ISO 10628-2 symbols listed in ``scripts/iso_shapes.yaml`` into the symbol library.

Usage: uv run python scripts/import_iso_shapes.py CATALOGUE PORTS ANNOTATIONS

- CATALOGUE: a pyDEXPI ``ShapeCatalogue`` as JSON whose shapes are drawn in a frame centred on
  the origin, Y down (the DEXPI drawing frame), each named as ``source`` in the selection;
- PORTS: the connection points of those shapes in the same frame (``{"shapes": {name:
  {"ports": [{"key", "x", "y", "side", "role"}]}}}``);
- ANNOTATIONS: an OWL ontology whose classes carry their ISO 10628-2 registration number in an
  ``rdfs:comment`` (``ISO 10628-2 REG#:2322``); a ``...Shape_N`` symbol takes its class's,
  unless the selection's ``iso`` overrides it.

Writes ``src/chemeascode/domains/process/data/iso_shapes.json``: per symbol its name, meaning,
registration number, default classes, size and the primitives (PolyLine, Polygon as a closed
PolyLine, Ellipse; texts are dropped) and ports, scaled so the longest side is ``size`` mm.
Rerun it rather than editing the JSON.
"""

from __future__ import annotations

import json
import re
import sys
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[1]
SELECTION = ROOT / "scripts/iso_shapes.yaml"
OUT = ROOT / "src/chemeascode/domains/process/data/iso_shapes.json"

_REG = re.compile(r"<IRI>#(\w+)</IRI>\s*<Literal>ISO[^<]*?REG#:\s*(\w+)[^<]*</Literal>")


def _round(value: float) -> float:
    rounded = round(value, 2)
    return 0.0 if rounded == 0 else rounded


def _points(data: dict) -> list[tuple[float, float]]:
    return [(p["data"]["x"], p["data"]["y"]) for p in data["points"]]


def _extent(primitives: list[dict]) -> tuple[float, float, float, float]:
    xs: list[float] = []
    ys: list[float] = []
    for p in primitives:
        data = p["data"]
        kind = p["uri"].rsplit("/", 1)[1]
        if kind in ("PolyLine", "Polygon"):
            for x, y in _points(data):
                xs.append(x)
                ys.append(y)
        elif kind == "Ellipse":
            c = data["center"]["data"]
            rx, ry = data["horizontalSemiAxis"], data["verticalSemiAxis"]
            xs += [c["x"] - rx, c["x"] + rx]
            ys += [c["y"] - ry, c["y"] + ry]
    return min(xs), min(ys), max(xs), max(ys)


def _dash(data: dict) -> str:
    name = data["stroke"]["data"]["dashStyle"]["name"]
    return {"SOLID": "Solid", "DASH": "Dash", "DOT": "Dot", "DASHDOT": "DashDot"}.get(name, "Solid")


def convert(shape: dict, size: float) -> tuple[list[dict], float, tuple[float, float]]:
    """The shape's primitives scaled so its longest side is *size* mm, centred on the origin."""
    primitives = shape["composition"]["primitives"]
    x0, y0, x1, y1 = _extent(primitives)
    factor = size / max(x1 - x0, y1 - y0)
    cx, cy = (x0 + x1) / 2, (y0 + y1) / 2

    def at(x: float, y: float) -> list[float]:
        return [_round((x - cx) * factor), _round((y - cy) * factor)]

    out: list[dict] = []
    for p in primitives:
        data = p["data"]
        kind = p["uri"].rsplit("/", 1)[1]
        width = round(data["stroke"]["data"]["width"], 2)
        if kind in ("PolyLine", "Polygon"):
            pts = [at(x, y) for x, y in _points(data)]
            if kind == "Polygon" and pts[0] != pts[-1]:
                pts.append(pts[0])
            out.append({"line": pts, "width": width, "dash": _dash(data)})
        elif kind == "Ellipse":
            c = data["center"]["data"]
            out.append(
                {
                    "ellipse": at(c["x"], c["y"]),
                    "rx": _round(data["horizontalSemiAxis"] * factor),
                    "ry": _round(data["verticalSemiAxis"] * factor),
                    "rotation": round(data.get("rotation") or 0.0, 2),
                    "width": width,
                    "dash": _dash(data),
                }
            )
    return out, factor, (cx, cy)


def main(catalogue: Path, ports_path: Path, annotations: Path) -> None:
    selection = yaml.safe_load(SELECTION.read_text(encoding="utf-8"))
    shapes = json.loads(catalogue.read_text(encoding="utf-8"))["composition"]["shapes"]
    by_name = {s["data"]["name"]: s for s in shapes}
    ports = json.loads(ports_path.read_text(encoding="utf-8"))["shapes"]
    numbers = dict(_REG.findall(annotations.read_text(encoding="utf-8")))

    out = []
    for entry in selection:
        source = entry["source"]
        shape = by_name.get(source)
        if shape is None:
            raise SystemExit(f"{source}: not in {catalogue}")
        # The selection's `iso` corrects a wrong annotation (its comment gives the evidence).
        number = (
            entry.get("iso")
            or numbers.get(source)
            or numbers.get(re.sub(r"Shape_\d+$", "", source))
        )
        if number is None:
            raise SystemExit(f"{source}: no ISO 10628-2 registration number in {annotations}")
        primitives, factor, (cx, cy) = convert(shape, float(entry["size"]))
        out.append(
            {
                "name": entry["name"],
                "meaning": entry["meaning"],
                "iso": number,
                "scale": entry["scale"],
                "inline": bool(entry.get("inline", False)),
                "template": bool(entry.get("template", False)),
                "classes": entry.get("classes", []),
                "primitives": primitives,
                "ports": [
                    {
                        "key": p["key"],
                        "x": _round((p["x"] - cx) * factor),
                        "y": _round((p["y"] - cy) * factor),
                        "side": p.get("side"),
                        "role": p.get("role"),
                    }
                    for p in ports.get(source, {}).get("ports", [])
                ],
            }
        )
    lines = ",\n".join(json.dumps(s, separators=(",", ":")) for s in out)
    OUT.write_text(
        '{"generated_by":"scripts/import_iso_shapes.py","shapes":[\n' + lines + "\n]}\n",
        encoding="utf-8",
    )
    print(f"{len(out)} symbols written to {OUT.relative_to(ROOT)}")


if __name__ == "__main__":
    if len(sys.argv) != 4:
        raise SystemExit(__doc__)
    main(Path(sys.argv[1]), Path(sys.argv[2]), Path(sys.argv[3]))
