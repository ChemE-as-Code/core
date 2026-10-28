/**
 * Cable trays, junction boxes, cables, air handling units, rooms and ducts of the generated model
 * (`layout-mep.json`: core's small cabling and HVAC test plant), and the routes a selection marks.
 */
import { describe, expect, it } from "vitest";
import type { Layout, ModelTray } from "@/api";
import { buildScene } from "@/lib/layoutScene";
import { cablePath, DUCT_COLORS, joinRuns, segmentDirection, TRAY_COLORS, type Prim, type Vec3 } from "@/lib/layoutModel";
import mepJson from "./fixtures/layout-mep.json";

const mep = mepJson as unknown as Layout;
const model = mep.model!;
const scene = buildScene(mep);
const byKey = new Map(scene.meshes.map((m) => [m.key, m]));

describe("cable trays and cables", () => {
  it("draws every tray, the tray tier steel and the junction box on the trays layer", () => {
    for (const tray of model.trays!) {
      expect(scene.items.get(`tray:${tray.id}`)?.kind).toBe("tray");
      for (const part of tray.parts) expect(byKey.get(part.id)).toMatchObject({ layer: "trays", item: `tray:${tray.id}`, color: TRAY_COLORS[tray.system] });
    }
    // The tier's steel belongs to its rack.
    const tier = model.tray_tiers![0]!;
    expect(byKey.get(tier.parts[0]!.id)).toMatchObject({ layer: "trays", item: `rack:${tier.rack}`, material: "steel" });
    const jb = model.junction_boxes![0]!;
    expect(byKey.get(`${jb.tag}/box`)).toMatchObject({ layer: "trays", item: `junction_box:${jb.tag}`, review: true });
    expect(scene.proposals.get("junction box")).toEqual([`junction_box:${jb.tag}`]);
    expect(scene.counts.trays).toBeGreaterThan(model.trays!.length);
  });

  it("marks a motor's cable route: its trays in order from the room, and the cable's way", () => {
    const route = scene.routes.get("equipment:P-101")!;
    const cable = model.cables!.find((c) => c.kind === "motor")!;
    expect(route.items).toEqual(cable.trays.map((t) => `tray:${t}`));
    expect(route.paths).toHaveLength(1);
    const path = route.paths[0]!;
    expect(path[0]).toEqual(cable.from_point);
    expect(path[path.length - 1]).toEqual(cable.to_point);
    // The pump lists its cable; the cable is an item to select, framed by its way.
    const pump = scene.items.get("equipment:P-101")!;
    expect(pump.related).toContainEqual({ key: `cable:${cable.id}`, label: cable.tag });
    const info = scene.items.get(`cable:${cable.id}`)!;
    expect(Object.fromEntries(info.details)).toMatchObject({ trays: cable.trays.join(" > ") });
    expect(scene.itemBounds.get(`cable:${cable.id}`)).toBeTruthy();
    expect(scene.routes.get(`cable:${cable.id}`)?.items).toEqual(route.items);
    // A tray lists the cables it carries.
    expect(scene.items.get(`tray:${cable.trays[1]}`)?.related).toContainEqual({ key: `cable:${cable.id}`, label: cable.tag });
  });

  it("marks an instrument's way: its field cable to the junction box, and the box's multipair cable", () => {
    const multipair = model.cables!.find((c) => c.kind === "multipair")!;
    // PT-101 has nothing of its own in the model: a marker where its cable starts.
    const marker = scene.items.get("instrument:PT-101")!;
    expect(marker.kind).toBe("instrument");
    expect(byKey.get("instrument:PT-101")).toMatchObject({ layer: "trays", material: "instrument" });
    const route = scene.routes.get("instrument:PT-101")!;
    expect(route.items).toEqual([`junction_box:${multipair.to}`, ...multipair.trays.map((t) => `tray:${t}`)]);
    expect(route.paths).toHaveLength(2);
    // FV-104 is a control valve on the pipe: its in-line item carries the route.
    const valve = scene.ids.get("FV-104")!;
    expect(valve.startsWith("inline:")).toBe(true);
    expect(scene.routes.get(valve)?.items).toContain(`junction_box:${multipair.to}`);
    expect(scene.items.has("instrument:FV-104")).toBe(false);
    // The junction box marks its instruments' cables and its own.
    expect(scene.routes.get(`junction_box:${multipair.to}`)?.paths).toHaveLength(model.cables!.filter((c) => c.to === multipair.to).length);
  });

  it("follows the trays in order, turning each to continue the way", () => {
    const trays = new Map<string, Pick<ModelTray, "points" | "depth">>([
      ["A", { points: [[0, 0, 5], [10, 0, 5]], depth: 0.1 }],
      // drawn the other way round
      ["B", { points: [[10, 8, 5], [10, 0, 5]], depth: 0.1 }],
    ]);
    const path = cablePath({ from_point: [-1, 0, 4], to_point: [10, 9, 1], trays: ["A", "B"] }, trays);
    expect(path).toEqual([
      [-1, 0, 4],
      [0, 0, 5.05],
      [10, 0, 5.05],
      [10, 8, 5.05],
      [10, 9, 1],
    ]);
    expect(cablePath({ from_point: [0, 0, 0], to_point: [1, 1, 1], trays: [] }, trays)).toHaveLength(2);
  });
});

describe("HVAC", () => {
  it("draws the unit, the ducts in their system's colour and the room's grilles", () => {
    const unit = model.hvac_units![0]!;
    expect(byKey.get(`${unit.id}/casing`)).toMatchObject({ layer: "ducts", item: `hvac_unit:${unit.id}`, material: "ahu" });
    for (const duct of model.ducts!) {
      const run = byKey.get(duct.parts[0]!.id)!;
      expect(run).toMatchObject({ layer: "ducts", item: `duct:${duct.id}` });
      expect(run.color).toBe(DUCT_COLORS[duct.system]);
    }
    const room = model.hvac_rooms![0]!;
    const grille = room.terminals[0]!.parts[0]!;
    expect(byKey.get(grille.id)).toMatchObject({ item: `hvac_room:${room.id}`, lod: 2 });
    expect(Object.fromEntries(scene.items.get(`hvac_room:${room.id}`)!.details)).toMatchObject({ "air changes": "6 per hour", supply: "5760 m3/h" });
    const duct = model.ducts![0]!;
    expect(Object.fromEntries(scene.items.get(`duct:${duct.id}`)!.details).size).toBe(`${duct.width * 1000} x ${duct.height * 1000} mm`);
  });

  it("marks a unit's ducts, and a room's: those that carry its air", () => {
    const unit = model.hvac_units![0]!;
    expect(new Set(scene.routes.get(`hvac_unit:${unit.id}`)!.items)).toEqual(new Set(model.ducts!.map((d) => `duct:${d.id}`)));
    const room = model.hvac_rooms![0]!;
    const serving = model.ducts!.filter((d) => d.serves?.includes(room.id)).map((d) => `duct:${d.id}`);
    expect(serving.length).toBeLessThan(model.ducts!.length);
    expect(scene.routes.get(`hvac_room:${room.id}`)!.items).toEqual(serving);
  });

  it("keys the legend by tray and air system", () => {
    const labels = scene.legend.services.map((e) => e.label);
    expect(labels).toEqual(expect.arrayContaining(["power tray", "instrument tray", "junction box", "air handling unit", "supply air duct", "extract air duct", "outdoor air duct", "exhaust air duct"]));
  });
});

describe("geometry helpers", () => {
  it("closes the corners of a duct: each run reaches into its neighbour", () => {
    // Up from a unit's port, then west, then north (core's boxes end at the corner points).
    const points: Vec3[] = [
      [21, 7.5, 2.2],
      [21, 7.5, 4.8],
      [20, 7.5, 4.8],
      [20, 9.5, 4.8],
    ];
    const runs: Prim[] = [
      { kind: "box", centre: [21, 7.5, 3.5], size: [0.5, 0.4, 2.6], rotationZ: 0 },
      { kind: "box", centre: [20.5, 7.5, 4.8], size: [1, 0.5, 0.4], rotationZ: Math.PI },
      { kind: "box", centre: [20, 8.5, 4.8], size: [2, 0.5, 0.4], rotationZ: Math.PI / 2 },
    ];
    const [up, west, north] = joinRuns(runs, points) as Extract<Prim, { kind: "box" }>[];
    // The riser reaches up half the level duct's height; the level runs half the other's width.
    expect(up!.size[2]).toBeCloseTo(2.8, 6);
    expect(up!.centre[2]).toBeCloseTo(3.6, 6);
    expect(west!.size[0]).toBeCloseTo(1 + 0.25 + 0.25, 6);
    expect(west!.centre[0]).toBeCloseTo(20.5, 6);
    expect(north!.size[0]).toBeCloseTo(2.25, 6);
    expect(north!.centre[1]).toBeCloseTo(8.375, 6);
    // Not runs of a polyline: as they are.
    expect(joinRuns(runs.slice(0, 2), points)).toEqual(runs.slice(0, 2));
  });

  it("finds the run of a polyline nearest a point", () => {
    const points: Vec3[] = [
      [0, 0, 0],
      [10, 0, 0],
      [10, 5, 0],
    ];
    expect(segmentDirection(points, [4, 0.1, 0])).toEqual([1, 0, 0]);
    expect(segmentDirection(points, [10, 3, 0])).toEqual([0, 1, 0]);
    expect(segmentDirection([], [0, 0, 0])).toEqual([1, 0, 0]);
  });
});
