/**
 * The contract with cheme-as-code: real `/api/layout` responses of the example-dexpi-plant layout
 * (`layout-demo.json`) and of a copy with a clash (`layout-demo-clash.json`: P4711 moved into
 * building B-1, plus an area that shares the id B-1). See fixtures/README.md to regenerate them.
 */
import { describe, expect, it } from "vitest";
import type { Layout } from "@/api";
import { buildScene, buildingLevels, CLASH_COLOR, equipmentGeometry, findingItem } from "@/lib/layoutScene";
import demoJson from "./fixtures/layout-demo.json";
import clashJson from "./fixtures/layout-demo-clash.json";
import asuJson from "./fixtures/layout-asu.json";

const demo = demoJson as unknown as Layout;
const clash = clashJson as unknown as Layout;
const asu = asuJson as unknown as Layout;

describe("the /api/layout response", () => {
  it("has the fields the viewer reads", () => {
    for (const layout of [demo, clash]) {
      expect(Object.keys(layout)).toEqual(
        expect.arrayContaining(["site", "areas", "roads", "racks", "buildings", "equipment", "findings"]),
      );
      for (const e of layout.equipment) {
        expect(e).toEqual(
          expect.objectContaining({ tag: expect.any(String), shape: expect.any(String), clash: expect.any(Boolean) }),
        );
        // cheme-as-code always sends the size as [dx, dy, dz] and resolves the sheet file.
        expect(Array.isArray(e.size) && e.size.length === 3).toBe(true);
        expect(e.position).toHaveLength(3);
        expect(e.bbox).toHaveLength(6);
        expect(typeof e.notes).toBe("string");
        if (e.sheet) expect(e.sheet_file).toMatch(/\.xml$/);
      }
      for (const b of layout.buildings) {
        expect(typeof b.clash).toBe("boolean");
        for (const level of b.levels ?? []) expect(level.clear_height).toBeGreaterThan(0);
      }
      for (const r of [...layout.roads, ...layout.racks]) expect(typeof r.clash).toBe("boolean");
    }
  });

  it("draws every equipment item at the size cheme-as-code checks", () => {
    for (const e of demo.equipment) {
      const geometry = equipmentGeometry(e.shape, e.size);
      const [x0, y0, z0, x1, y1, z1] = e.bbox!;
      expect(z1 - z0).toBeCloseTo((geometry.base ?? 0) + geometry.size[2], 6);
      if (!e.rotation_deg) {
        expect(x1 - x0).toBeCloseTo(geometry.size[0], 6);
        expect(y1 - y0).toBeCloseTo(geometry.size[1], 6);
      }
    }
  });

  it("draws raised horizontal equipment at its height without a model (pre-release viewer issue 45)", () => {
    // The ASU's exchangers and the V-2101 vessels sit on saddles: size[2] (the axis height plus
    // the radius) is more than the diameter. Without layout/plant-model.yaml the placement draws them.
    const { model: _model, ...placement } = asu;
    const scene = buildScene(placement as Layout);
    const raised = asu.equipment.filter((e) => e.shape === "horizontal_cylinder");
    expect(raised.length).toBeGreaterThan(0);
    for (const e of raised) {
      const [, , z0, , , z1] = e.bbox!;
      const [length, diameter, height] = e.size as [number, number, number];
      expect(height).toBeGreaterThan(diameter);
      const prim = scene.meshes.find((m) => m.key === `equipment:${e.tag}`)!.prim;
      if (prim.kind !== "cylinder") throw new Error(`${e.tag} is not a cylinder`);
      // The shell's axis one radius below the top of core's box, the shell as long as the item.
      expect(prim.start[2]).toBeCloseTo(z1 - diameter / 2, 6);
      expect(prim.end[2]).toBeCloseTo(z1 - diameter / 2, 6);
      expect(prim.radius).toBeCloseTo(diameter / 2, 6);
      expect(Math.hypot(prim.end[0] - prim.start[0], prim.end[1] - prim.start[1])).toBeCloseTo(length, 6);
      const label = scene.labels.find((l) => l.key === `label:${e.tag}`)!;
      expect(label.position[2]).toBeCloseTo(z0 + height + 0.4, 6);
    }
  });

  it("uses cheme-as-code's level heights", () => {
    const b1 = demo.buildings.find((b) => b.id === "B-1")!;
    const top = Math.max(...buildingLevels(b1).map((l) => l.elevation + l.height));
    expect(top).toBeCloseTo(b1.heights![1], 6);
  });

  it("sends the line routes, with length estimates along the racks", () => {
    const lines = demo.lines ?? [];
    expect(lines.length).toBeGreaterThan(0);
    const routed = lines.find((l) => l.number === "47123")!;
    expect(routed.racks).toEqual(["PR-1"]);
    expect(routed.length_est).toBeGreaterThan(routed.distance!);
    expect(routed.finding).toBe("cheme.layout-line-length");
    // a length finding per routed line, at level info
    const lengths = demo.findings.filter((f) => f.rule === "cheme.layout-line-length");
    expect(lengths.map((f) => f.ids[0]).sort()).toEqual(lines.filter((l) => l.finding === "cheme.layout-line-length").map((l) => l.number).sort());
  });

  it("shows the demo layout without clashes, with names, legend and P&ID links", () => {
    const scene = buildScene(demo);
    // only information (line lengths, lines whose ends are not placed), no warnings or errors
    expect(demo.findings.filter((f) => f.level !== "info")).toEqual([]);
    expect(scene.clashKeys.size).toBe(0);
    expect(scene.solids.some((s) => s.clash)).toBe(false);
    const names = scene.labels.filter((l) => l.toggle === "names").map((l) => l.text);
    expect(names).toEqual(expect.arrayContaining(["A-100", "A-310", "PR-1", "B-1"]));
    expect(scene.labels.map((l) => l.text)).toEqual(expect.arrayContaining(["N", "10 m"]));
    expect(scene.legend.areas.map((e) => e.label)).toEqual(expect.arrayContaining(["process", "storage", "pipe rack"]));
    // Equipment types grouped by what they are, with the types behind each row.
    expect(scene.legend.equipment.map((e) => e.label)).toEqual(expect.arrayContaining(["tanks"]));
    expect(scene.legend.equipment.find((e) => e.label === "tanks")?.members).toEqual(["Tank"]);
    const tank = scene.items.get("equipment:T4750")!;
    expect(tank.sheetFile).toBe("pid/P-01.xml");
    expect(tank.notes).toMatch(/^ASSUMED - vertical tank about 190 m3/);
  });

  it("paints only the clashing equipment and building red, not the area sharing the building's id", () => {
    const scene = buildScene(clash);
    expect([...scene.clashKeys].sort()).toEqual(["building:B-1", "equipment:P4711"]);
    expect(scene.solids.find((s) => s.key === "equipment:P4711")?.color).toBe(CLASH_COLOR);
    expect(scene.solids.find((s) => s.key === "area:B-1")?.clash).toBe(false);
    expect(scene.items.get("area:B-1")?.clash).toBe(false);
    const finding = clash.findings.find((f) => f.rule === "cheme.layout-clash")!;
    expect(findingItem(finding, scene.items)).toBe("equipment:P4711");
  });
});
