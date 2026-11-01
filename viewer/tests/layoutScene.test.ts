import { describe, expect, it } from "vitest";
import type { Layout, LayoutBuilding } from "@/api";
import {
  AREA_COLORS,
  buildingCorners,
  buildingLevels,
  buildScene,
  cameraPose,
  CLASH_COLOR,
  clashKeys,
  equipmentColor,
  equipmentGeometry,
  findingItem,
  offsetPolyline,
  rotateXY,
  planFrame,
  scaleLength,
  sheetFile,
  siteGrid,
  stripSegments,
  type SolidSpec,
} from "@/lib/layoutScene";
// Hand-made, for shapes and cases the demo does not have; the contract with cheme-as-code is tested
// on real /api/layout responses in layoutContract.test.ts.
import fixture from "./fixtures/layout-shapes.json";

const layout = fixture as unknown as Layout;
const scene = buildScene(layout);
const solid = (key: string): SolidSpec => {
  const found = scene.solids.find((s) => s.key === key);
  if (!found) throw new Error(`no solid ${key}`);
  return found;
};
const close = (actual: number[], expected: number[]) =>
  expected.forEach((v, i) => expect(actual[i]).toBeCloseTo(v, 6));

describe("equipmentGeometry", () => {
  it("reads box sizes from [dx, dy, dz]", () => {
    expect(equipmentGeometry("box", [2, 1, 1.2])).toEqual({ shape: "box", axis: "z", size: [2, 1, 1.2] });
  });

  it("makes vertical cylinders diameter x diameter x height along z", () => {
    expect(equipmentGeometry("vertical_cylinder", { diameter: 3, height: 8 })).toEqual({
      shape: "cylinder",
      axis: "z",
      size: [3, 3, 8],
    });
    expect(equipmentGeometry("vertical_cylinder", [2, 2, 5]).size).toEqual([2, 2, 5]);
  });

  it("makes horizontal cylinders length x diameter x diameter along x", () => {
    expect(equipmentGeometry("horizontal_cylinder", { diameter: 1.2, length: 6 })).toEqual({
      shape: "cylinder",
      axis: "x",
      size: [6, 1.2, 1.2],
    });
    expect(equipmentGeometry("horizontal_cylinder", [6, 1.5, 1.5]).size).toEqual([6, 1.5, 1.5]);
  });

  it("raises a horizontal cylinder whose overall height exceeds its diameter", () => {
    // cheme-as-code's extent for a vessel on saddles: length, diameter, axis height + radius.
    const geometry = equipmentGeometry("horizontal_cylinder", [5, 1.5, 2.5]);
    expect(geometry).toEqual({ shape: "cylinder", axis: "x", size: [5, 1.5, 1.5], base: 1 });
    const scene = buildScene({ equipment: [{ tag: "V-1", shape: "horizontal_cylinder", size: [5, 1.5, 2.5], position: [10, 20, 0.5] }] } as unknown as Layout);
    const prim = scene.meshes.find((m) => m.key === "equipment:V-1")!.prim;
    expect(prim).toMatchObject({ kind: "cylinder", radius: 0.75 });
    if (prim.kind !== "cylinder") throw new Error("not a cylinder");
    // The axis at z + 1.75, the top at z + 2.5.
    close(prim.start, [7.5, 20, 2.25]);
    close(prim.end, [12.5, 20, 2.25]);
    const label = scene.labels.find((l) => l.key === "label:V-1")!;
    expect(label.position[2]).toBeCloseTo(0.5 + 2.5 + 0.4, 6);
    expect(scene.items.get("equipment:V-1")!.details).toContainEqual(["size", "5 x 1.5 x 2.5 m"]);
  });

  it("makes spheres from the diameter", () => {
    expect(equipmentGeometry("sphere", { diameter: 8 })).toEqual({ shape: "sphere", axis: "z", size: [8, 8, 8] });
  });

  it("falls back to 1 m for missing or bad sizes and to a box for unknown shapes", () => {
    expect(equipmentGeometry("vertical_cylinder", {}).size).toEqual([1, 1, 1]);
    expect(equipmentGeometry("box", [0, -2, Number.NaN] as [number, number, number]).size).toEqual([1, 1, 1]);
    expect(equipmentGeometry("pyramid", [2, 3, 4])).toEqual({ shape: "box", axis: "z", size: [2, 3, 4] });
  });
});

describe("equipment in the scene", () => {
  it("puts the solid's centre half its height above the bottom elevation", () => {
    const pump = solid("equipment:P-101");
    expect(pump.center).toEqual([25, 20, 0.6]);
    expect(pump.size).toEqual([2, 1, 1.2]);
    const exchanger = solid("equipment:E-101");
    expect(exchanger.center).toEqual([48, 20, 0.5 + 0.6]);
    expect(exchanger.axis).toBe("x");
    const sphere = solid("equipment:S-301");
    expect(sphere.center).toEqual([100, 20, 6]);
  });

  it("turns rotation_deg into radians about z", () => {
    expect(solid("equipment:P-101").rotationZ).toBeCloseTo(Math.PI / 2, 9);
    expect(solid("equipment:V-101").rotationZ).toBe(0);
  });

  it("colours equipment by type and keeps red for clashes", () => {
    expect(solid("equipment:P-101").color).toBe(equipmentColor("CentrifugalPump"));
    expect(solid("equipment:K-101").color).toBe(equipmentColor("compressor"));
    expect(equipmentColor("CentrifugalPump")).not.toBe(equipmentColor("Tank"));
    expect(equipmentColor("Something odd")).toBe(equipmentColor("something odd"));
    for (const t of ["pump", "vessel", "tank", "column", "reactor", "unknown thing", null])
      expect(equipmentColor(t)).not.toBe(CLASH_COLOR);
  });

  it("highlights items named by layout-clash findings", () => {
    expect([...scene.clashKeys].sort()).toEqual(["equipment:E-101", "equipment:E-102"]);
    for (const tag of ["E-101", "E-102"]) {
      expect(solid(`equipment:${tag}`).clash).toBe(true);
      expect(solid(`equipment:${tag}`).color).toBe(CLASH_COLOR);
      expect(scene.labels.find((l) => l.text === tag)?.clash).toBe(true);
    }
    expect(solid("equipment:P-101").clash).toBe(false);
    // Area overlap is a warning, not a clash.
    expect(solid("area:A-PROC").clash).toBe(false);
  });

  it("labels each tag above its solid", () => {
    const label = scene.labels.find((l) => l.text === "V-101");
    expect(label?.position).toEqual([40, 20, 8.4]);
    expect(label?.item).toBe("equipment:V-101");
  });

  it("exposes tag, type, sheet, building and level for the side panel", () => {
    const item = scene.items.get("equipment:K-101");
    expect(item).toMatchObject({ kind: "equipment", id: "K-101", type: "Compressor", sheet: "pid/P-02.xml", building: "B-100", level: "L0" });
  });
});

describe("site, areas, roads and racks", () => {
  it("outlines the site and bounds the scene by it", () => {
    expect(scene.site).toEqual({ width: 120, depth: 80, name: "Demo site" });
    const outline = scene.lines.find((l) => l.key === "site:outline");
    expect(outline?.segments).toHaveLength(4);
    expect(scene.bounds.min[0]).toBe(0);
    expect(scene.bounds.max[0]).toBeGreaterThanOrEqual(120);
    expect(scene.bounds.max[2]).toBe(12); // the tank top
  });

  it("draws areas as translucent slabs coloured by kind", () => {
    const area = solid("area:A-PROC");
    expect(area.center[0]).toBe(35);
    expect(area.center[1]).toBe(30);
    expect(area.size.slice(0, 2)).toEqual([50, 40]);
    expect(area.color).toBe(AREA_COLORS.process);
    expect(area.opacity).toBeLessThan(0.5);
    expect(solid("area:A-TANK").color).toBe(AREA_COLORS.storage);
  });

  it("draws roads as strips along their segments, joined at bends", () => {
    const straight = solid("road:R-1:0");
    expect(straight.center.slice(0, 2)).toEqual([60, 60]);
    expect(straight.size.slice(0, 2)).toEqual([120, 8]);
    expect(straight.rotationZ).toBe(0);
    const first = solid("road:R-2:0");
    // 55 m south, lengthened by half the width at the bend only.
    expect(first.size[0]).toBe(58);
    expect(first.rotationZ).toBeCloseTo(-Math.PI / 2, 9);
    close(first.center, [65, 31, first.center[2]]);
    // Roads lie on top of the area slabs.
    expect(first.center[2]).toBeGreaterThan(solid("area:A-ROAD").size[2]);
  });

  it("frames pipe racks with posts, cross beams and longitudinal beams per level", () => {
    const rack = scene.lines.find((l) => l.key === "rack:PR-1");
    // 2 points x (2 posts + 2 cross beams) + 1 span x 2 levels x 2 sides.
    expect(rack?.segments).toHaveLength(2 * 4 + 4);
    expect(rack?.segments).toContainEqual([
      [15, 33, 0],
      [15, 33, 7.5],
    ]);
    expect(rack?.segments).toContainEqual([
      [15, 27, 5],
      [55, 27, 5],
    ]);
    // Drawn as solid steel members on the structures layer, each picking the rack.
    expect(rack?.layer).toBe("structures");
    const members = scene.meshes.filter((m) => m.key.startsWith("rack:PR-1:m"));
    expect(members).toHaveLength(rack!.segments.length);
    expect(members.every((m) => m.prim.kind === "beam" && m.item === "rack:PR-1" && m.material === "steel")).toBe(true);
  });

  it("turns every placement solid into a mesh with the same placement", () => {
    expect(scene.hasModel).toBe(false);
    for (const s of scene.solids) expect(scene.meshes.find((m) => m.key === s.key)?.item).toBe(s.item);
    const cylinder = scene.meshes.find((m) => m.prim.kind === "cylinder" && m.layer === "equipment")!;
    const source = scene.solids.find((s) => s.key === cylinder.key)!;
    if (cylinder.prim.kind === "cylinder") {
      const mid = cylinder.prim.start.map((v, i) => (v + (cylinder.prim as { end: number[] }).end[i]!) / 2);
      close(mid, source.center);
    }
  });
});

describe("buildings", () => {
  const b100 = layout.buildings.find((b) => b.id === "B-100") as LayoutBuilding;

  it("fills in level heights and slabs", () => {
    expect(buildingLevels(b100)).toEqual([
      { id: "L0", title: "Ground floor", kind: "floor", elevation: 0, height: 6, slab: null },
      // A platform without a height reaches up to the next level, drawn as a deck plus that room.
      { id: "L1", title: "Platform", kind: "platform", elevation: 6, height: 3, slab: 0.2 },
      { id: "RF", title: "Roof", kind: "roof", elevation: 9, height: 0.3, slab: 0.3 },
    ]);
    // A declared platform height is respected (the review: the viewer drew 0.2 m, cheme-as-code 4 m).
    const declared = buildingLevels({ ...b100, levels: [{ id: "PF", elevation: 5, height: 4, kind: "platform" }] });
    expect(declared[0]).toMatchObject({ height: 4, slab: 0.2 });
    // cheme-as-code's clear_height wins.
    expect(buildingLevels({ ...b100, levels: [{ id: "GF", elevation: 0, clear_height: 7 }] })[0]!.height).toBe(7);
    expect(buildingLevels({ ...b100, levels: [{ id: "a", elevation: 0 }, { id: "b", elevation: 5 }] }).map((l) => l.height)).toEqual([5, 4]);
    expect(buildingLevels({ ...b100, levels: [] })).toHaveLength(1);
  });

  it("draws a translucent box per level at the footprint centre", () => {
    const floor = solid("building:B-100:L0");
    expect(floor.center).toEqual([29, 43, 3]);
    expect(floor.size).toEqual([18, 10, 6]);
    expect(floor.opacity).toBeLessThan(1);
    expect(solid("building:B-100:RF").center[2]).toBeCloseTo(9.15, 9);
    expect(solid("building:B-100:L1").size[2]).toBeCloseTo(0.2, 9);
    const clear = solid("building:B-100:L1:clear");
    expect(clear.center[2]).toBeCloseTo(6 + (0.2 + 3) / 2, 9);
    expect(clear.opacity).toBeLessThan(0.15);
  });

  it("rotates buildings about their origin", () => {
    const rotated = solid("building:B-200:L0");
    // 12 x 8 turned 90 degrees about (100, 70): centre (100 - 4, 70 + 6).
    close(rotated.center, [96, 76, 2]);
    expect(rotated.rotationZ).toBeCloseTo(Math.PI / 2, 9);
    const b200 = layout.buildings.find((b) => b.id === "B-200") as LayoutBuilding;
    expect(buildingCorners(b200)).toEqual([
      [100, 70],
      [100, 82],
      [92, 82],
      [92, 70],
    ]);
  });

  it("draws columns at every grid intersection and grid lines per level", () => {
    const grid = scene.lines.find((l) => l.key === "building:B-100:grid");
    const columns = (grid?.segments ?? []).filter(([a, b]) => a[0] === b[0] && a[1] === b[1]);
    expect(columns).toHaveLength(4 * 2);
    expect(columns).toContainEqual([
      [26, 38, 0],
      [26, 38, 9.3],
    ]);
    // 3 levels x (4 lines along y + 2 along x).
    expect((grid?.segments.length ?? 0) - columns.length).toBe(3 * 6);
    expect(scene.lines.find((l) => l.key === "building:B-200:grid")).toBeUndefined();
  });
});

describe("helpers", () => {
  it("rotates points about a centre", () => {
    expect(rotateXY([1, 0], Math.PI / 2)).toEqual([0, 1]);
    expect(rotateXY([12, 0], Math.PI, [10, 0])).toEqual([8, 0]);
  });

  it("splits polylines into segments", () => {
    expect(stripSegments([[0, 0], [10, 0], [10, 0]])).toEqual([{ center: [5, 0], length: 10, angle: 0 }]);
  });

  it("offsets polylines to both sides", () => {
    expect(offsetPolyline([[0, 0], [10, 0]], 2)).toEqual({ left: [[0, 2], [10, 2]], right: [[0, -2], [10, -2]] });
  });

  it("mitres the offset edges at a bend so the rack frame keeps its width", () => {
    // An L: east, then north. The outer (right) corner is at (12, -2), the inner (left) at (8, 2).
    const { left, right } = offsetPolyline([[0, 0], [10, 0], [10, 10]], 2);
    expect(left).toEqual([[0, 2], [8, 2], [8, 10]]);
    expect(right).toEqual([[0, -2], [12, -2], [12, 10]]);
  });

  it("collects clashes from findings with or without the cheme. prefix when items carry no flag", () => {
    const f = { file: "x", level: "error" as const, line: null, hint: "", message: "" };
    const eq = (tag: string) => ({ tag, position: [0, 0, 0] as [number, number, number], shape: "box", size: [1, 1, 1] as [number, number, number] });
    const keys = clashKeys({
      site: null,
      areas: [],
      roads: [],
      racks: [],
      buildings: [],
      equipment: [eq("A"), eq("B")],
      findings: [{ ...f, rule: "layout-clash", ids: ["A"] }, { ...f, rule: "cheme.layout-level", ids: ["B"] }],
    });
    expect([...keys]).toEqual(["equipment:A"]);
  });

  it("keeps clashes apart by kind: an area or road sharing an id with a building or tag does not turn red", () => {
    const f = { file: "x", level: "error" as const, line: null, hint: "", message: "", rule: "cheme.layout-clash" };
    const base = { site: { width: 100, depth: 100 }, racks: [], equipment: [] };
    const building = { id: "B-1", origin: [10, 10] as [number, number], width: 10, depth: 10 };
    // Without flags (an older cheme-as-code): looked up per kind; plain areas never clash.
    const unflagged: Layout = {
      ...base,
      areas: [{ id: "B-1", box: [10, 10, 20, 20], kind: "building" }],
      roads: [{ id: "X", points: [[0, 50], [100, 50]], width: 6 }],
      buildings: [building],
      equipment: [{ tag: "X", position: [15, 15, 0], shape: "box", size: [1, 1, 1] }],
      findings: [{ ...f, ids: ["X", "B-1"] }],
    };
    const s1 = buildScene(unflagged);
    expect(s1.solids.find((x) => x.key === "area:B-1")?.clash).toBe(false);
    expect(s1.solids.find((x) => x.key === "building:B-1:floor")?.clash).toBe(true);
    expect(s1.items.get("area:B-1")?.clash).toBe(false);
    // With cheme-as-code's flags: road X is not the clashing X.
    const flagged: Layout = {
      ...unflagged,
      roads: [{ ...unflagged.roads[0]!, clash: false }],
      buildings: [{ ...building, clash: true }],
      equipment: [{ ...unflagged.equipment[0]!, clash: true }],
    };
    const s2 = buildScene(flagged);
    expect(s2.solids.find((x) => x.key === "road:X:0")?.clash).toBe(false);
    expect(s2.items.get("road:X")?.clash).toBe(false);
    expect(s2.items.get("equipment:X")?.clash).toBe(true);
    expect([...s2.clashKeys].sort()).toEqual(["building:B-1", "equipment:X"]);
  });

  it("maps findings to the first item they name", () => {
    expect(findingItem(layout.findings[0]!, scene.items)).toBe("equipment:E-101");
    expect(findingItem(layout.findings[1]!, scene.items)).toBe("area:A-PROC");
    expect(findingItem(layout.findings[2]!, scene.items)).toBeNull();
  });

  it("resolves sheets by id or file path", () => {
    const sheets = [{ id: "P-01", file: "pid/P-01.xml", title: "Feed" }];
    expect(sheetFile("P-01", sheets)).toBe("pid/P-01.xml");
    expect(sheetFile("pid/P-01.xml", sheets)).toBe("pid/P-01.xml");
    expect(sheetFile("pid/P-09.xml", sheets)).toBe("pid/P-09.xml");
    expect(sheetFile("P-09", sheets)).toBeNull();
    expect(sheetFile(null, sheets)).toBeNull();
  });

  it("frames the bounds from above and from the south-west", () => {
    const bounds = { min: [0, 0, 0] as [number, number, number], max: [100, 50, 10] as [number, number, number] };
    const top = cameraPose("top", bounds);
    expect(top.target).toEqual([50, 25, 5]);
    expect(top.position[0]).toBe(50);
    expect(top.position[2]).toBeGreaterThan(100);
    const iso = cameraPose("iso", bounds);
    // The plan frame keeps a margin around the bounds and follows the viewport's shape.
    const wide = planFrame(bounds, 2);
    expect(wide.halfWidth * 2).toBeGreaterThanOrEqual(100 * 1.15 - 1e-9);
    expect(wide.halfHeight * 2).toBeGreaterThanOrEqual(50 * 1.15 - 1e-9);
    expect(wide.halfWidth / wide.halfHeight).toBeCloseTo(2, 9);
    const tall = planFrame(bounds, 0.5);
    expect(tall.halfWidth * 2).toBeCloseTo(115, 6);
    expect(iso.position[0]).toBeLessThan(50);
    expect(iso.position[1]).toBeLessThan(25);
    expect(iso.position[2]).toBeGreaterThan(0);
    // A portrait viewport moves the camera further away (the box is wider than high).
    expect(cameraPose("top", bounds, 45, 0.5).position[2]).toBeGreaterThan(top.position[2] * 1.5);
  });

  it("grids the site only, and picks round scale-bar lengths", () => {
    const grid = siteGrid(60, 40);
    expect(grid).toHaveLength(7 + 5);
    expect(grid).toContainEqual([[60, 0], [60, 40]]);
    expect(grid.every(([a, b]) => Math.max(a[0], b[0]) <= 60 && Math.max(a[1], b[1]) <= 40)).toBe(true);
    expect(scaleLength(60)).toBe(10);
    expect(scaleLength(120)).toBe(20);
    expect(scaleLength(300)).toBe(50);
  });

  it("copes with an empty layout", () => {
    const empty = buildScene({ site: null, areas: [], roads: [], racks: [], buildings: [], equipment: [], findings: [] });
    expect(empty.solids).toEqual([]);
    expect(empty.bounds).toEqual({ min: [0, 0, 0], max: [10, 10, 0] });
  });
});
