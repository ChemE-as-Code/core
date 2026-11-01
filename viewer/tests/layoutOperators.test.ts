/**
 * What the operator work added to the model and the studies beside it: declared operators (chain wheels,
 * extension spindles, remote operators, remote-mounted transmitters), the casing hatch, the
 * lifting study and the datasheets, against the real ASU fixtures (core's frozen `/api/layout`,
 * the ASU's committed `layout/lifting-study.csv` and its tree) and small hand-made cases.
 */
import { describe, expect, it } from "vitest";
import type { Layout, ModelInlineItem, Sheet, TreeEntry } from "@/api";
import { buildScene, findingTargets, resolveSelect } from "@/lib/layoutScene";
import {
  chainWheelGeometry,
  CHAIN_LOOP_M,
  hatchGeometry,
  nearestFloor,
  operatorTitle,
  operatorWheel,
  PEDESTAL_M,
  pedestalGeometry,
  planDistance,
  primBounds,
  STAND_M,
  standGeometry,
  type Floor,
} from "@/lib/layoutModel";
import { datasheetPaths, laneClear, LIFTING_COLUMNS, parseCsv, parseLiftingStudy } from "@/lib/studies";
import asuJson from "./fixtures/layout-asu.json";
import asuTreeJson from "./fixtures/api/tree-asu.json";
import liftingCsv from "./fixtures/api/lifting-study-asu.csv?raw";

const asu = asuJson as unknown as Layout;
const model = asu.model!;
const sheets: Sheet[] = ["P-01", "P-02", "P-03", "P-04"].map((id) => ({ id, file: `pid/${id}.xml`, title: "", kind: "pid" }));
const scene = buildScene(asu, { sheets });
const details = (key: string) => Object.fromEntries(scene.items.get(key)!.details);
const meshesOf = (key: string, part: string) => scene.meshes.filter((m) => m.item === key && m.key.includes(`:${part}:`));

describe("declared operators on the ASU", () => {
  it("draws a chain wheel and its chain on each chain wheel valve, the chain down to hand height", () => {
    const valves = model.inline.filter((i) => i.operator?.kind === "chainwheel");
    expect(valves.length).toBe(5);
    for (const v of valves) {
      const key = `inline:${v.id}`;
      const parts = meshesOf(key, "operator");
      expect(parts.map((m) => m.prim.kind), v.id).toEqual(["torus", "cylinder", "cylinder", "cylinder"]);
      // Declared (routing.yaml), drawn close up like the valve's own detail.
      expect(new Set(parts.map((m) => m.source))).toEqual(new Set(["declared"]));
      expect(new Set(parts.map((m) => m.lod))).toEqual(new Set([2]));
      const d = details(key);
      expect(d.operator).toBe("chain wheel (infrequent use)");
      expect(d["operator basis"]).toBe(v.operator!.basis);
      expect(d["operator drawn"]).toMatch(/^chain wheel, chain to [\d.]+ m \(1 m above .+\); schematic, by the viewer$/);
    }
    // BV_P1101A_S: handwheel at 4.33 m, nothing under it but grade: the chain ends 1 m above grade.
    const chain = meshesOf("inline:P-01/BV_P1101A_S", "operator").filter((m) => m.key.includes("chain"));
    const bottom = Math.min(...chain.map((m) => primBounds(m.prim).min[2]));
    expect(bottom).toBeCloseTo(CHAIN_LOOP_M - 0.012, 6); // the chain's axis, less its radius
    expect(details("inline:P-01/BV_P1101A_S")["operator drawn"]).toContain("above grade at 0 m");
  });

  it("brings each extension spindle and remote operator to a pedestal 1 m above the nearest floor", () => {
    const valves = model.inline.filter((i) => i.operator?.kind === "extension_spindle" || i.operator?.kind === "remote_operator");
    expect(valves.length).toBe(26); // 21, and five remote operators since asu-1 D-060 (7)
    for (const v of valves) {
      const key = `inline:${v.id}`;
      const parts = meshesOf(key, "operator");
      const pedestal = parts.find((m) => m.key.endsWith(":pedestal"))!;
      expect(pedestal.prim.kind, v.id).toBe("box");
      const b = primBounds(pedestal.prim);
      expect(b.max[2] - b.min[2], v.id).toBeCloseTo(PEDESTAL_M, 3);
      expect(parts.some((m) => m.key.endsWith(":pedestal-wheel"))).toBe(true);
      expect(details(key)["operator drawn"]).toMatch(/^(extension spindle|remote operator), [\d.]+ m to a pedestal 1 m above /);
    }
    expect(details("inline:P-01/FV1108").operator).toBe("remote operator (regular use)");
  });

  it("moves each remote-mounted transmitter to a stand 1.2 m above its floor, with impulse lines or a capillary", () => {
    const tappings = model.equipment.flatMap((e) => e.nozzles).filter((n) => n.operator?.kind === "remote_mount");
    expect(tappings.length).toBe(11);
    for (const n of tappings) {
      const key = `nozzle:${n.id}`;
      const parts = meshesOf(key, "remote");
      const post = parts.find((m) => m.key.endsWith(":post"))!;
      const b = primBounds(post.prim);
      expect(b.max[2] - b.min[2], n.id).toBeCloseTo(STAND_M, 3);
      expect(parts.some((m) => m.key.endsWith(":transmitter"))).toBe(true);
      // Core's head on the tapping gives way to the stand.
      expect(scene.meshes.some((m) => m.key === `${n.id}/transmitter`)).toBe(false);
      const lines = parts.filter((m) => m.key.includes(":line-"));
      const pairs = new Set(lines.map((m) => m.key.split(":line-")[1]!.split("-")[0]));
      expect(pairs.size, n.id).toBe(n.operator!.via === "capillary" ? 1 : 2);
      expect(details(key)["operator drawn"]).toMatch(n.operator!.via === "capillary" ? /^capillary, / : /^impulse lines, /);
    }
    // The filter's top tapping goes out of the filter's plan first, then down to a stand at grade.
    const f1101 = model.equipment.find((e) => e.tag === "F-1101")!;
    const post = meshesOf("nozzle:F-1101/I1", "remote").find((m) => m.key.endsWith(":post"))!;
    const at = primBounds(post.prim);
    const [x0, y0, , x1, y1] = f1101.bbox;
    const outside = at.max[0] < x0 || at.min[0] > x1 || at.max[1] < y0 || at.min[1] > y1;
    expect(outside).toBe(true);
    expect(at.min[2]).toBe(0);
  });

  it("draws the cold box hatch H1 as an item of its own, on the casing's north face", () => {
    const key = "hatch:CB-1/H1";
    const hatch = scene.items.get(key)!;
    expect(hatch).toMatchObject({ kind: "hatch", id: "CB-1/H1", type: "hatch", source: "declared", related: [{ key: "structure:CB-1", label: "CB-1" }] });
    expect(details(key)).toMatchObject({ size: "1.2 x 1.2 m", sill: "20.3 m" });
    expect(resolveSelect("H1", scene)).toBe(key);
    expect(resolveSelect("CB-1/H1", scene)).toBe(key);
    // On the casing's north wall, outside the frame's north side, from 20.3 to 21.5 m.
    const cb = model.structures.find((s) => s.id === "CB-1")!;
    const box = scene.itemBounds.get(key)!;
    expect(box.min[2]).toBeCloseTo(20.3 - 0.08, 3);
    expect(box.max[2]).toBeCloseTo(21.5 + 0.08, 3);
    expect(box.min[1]).toBeGreaterThanOrEqual(cb.footprint[3] - 1e-6);
    expect(box.max[1]).toBeLessThan(cb.footprint[3] + 0.5);
    expect(scene.meshes.filter((m) => m.item === key)).toHaveLength(5);
  });
});

describe("operator geometry", () => {
  const floors: Floor[] = [
    { id: "P1", elevation: 5, polygon: [[0, 0], [4, 0], [4, 2], [0, 2]] },
    { id: "P2", elevation: 12, polygon: [[0, 0], [4, 0], [4, 2], [0, 2]] },
  ];

  it("measures plan distances to floors", () => {
    expect(planDistance(floors[0]!.polygon, 2, 1)).toBe(0);
    expect(planDistance(floors[0]!.polygon, 2, 3)).toBeCloseTo(1, 9);
    expect(planDistance(floors[0]!.polygon, 6, 4)).toBeCloseTo(Math.hypot(2, 2), 9);
  });

  it("takes core's nearest floor: the shortest run to the lift height, the plan beyond reach counted", () => {
    // Over P1 at 7 m: P1 (|7 - 6| = 1) beats grade (6) and P2 is above.
    expect(nearestFloor(floors, [2, 1, 7], PEDESTAL_M)).toEqual({ id: "P1", elevation: 5, at: [2, 1] });
    // 3 m off P1 in plan at 6 m: P1 costs 2.4 + 0 = 2.4, grade 5: P1, at its edge pulled 0.15 m in.
    const off = nearestFloor(floors, [2, 5, 6], PEDESTAL_M);
    expect(off.id).toBe("P1");
    expect(off.at[0]).toBeCloseTo(2, 6);
    expect(off.at[1]).toBeCloseTo(1.85, 6);
    // Far off everything: grade, under the point.
    expect(nearestFloor(floors, [50, 50, 3], PEDESTAL_M)).toEqual({ id: "grade", elevation: 0, at: [50, 50] });
  });

  it("hangs a chain from both ends of the wheel's level diameter", () => {
    const g = chainWheelGeometry({ centre: [2, 1, 9], axis: [1, 0, 0], radius: 0.25 }, floors);
    expect(g.floor).toEqual({ id: "P1", elevation: 5 });
    expect(g.bottom).toBe(5 + CHAIN_LOOP_M);
    expect(g.centre).toEqual([2.06, 1, 9]);
    const [a, b, foot] = g.chain;
    expect(a![0][1]).toBeCloseTo(1 - 0.25, 9);
    expect(b![0][1]).toBeCloseTo(1 + 0.25, 9);
    expect(a![1][2]).toBe(6);
    expect(foot![0][2]).toBe(6);
    // Close over its floor, the loop stays 0.3 m under the wheel (and above the floor).
    expect(chainWheelGeometry({ centre: [2, 1, 5.6], axis: [0, 1, 0], radius: 0.2 }, floors).bottom).toBeCloseTo(5.1, 9);
  });

  it("runs a spindle down to its pedestal, then across to the floor", () => {
    const g = pedestalGeometry([2, 5, 9], floors, PEDESTAL_M);
    expect(g.floor.id).toBe("P1");
    expect(g.top).toBe(6);
    expect(g.path).toEqual([[2, 5, 9], [2, 5, 6], [2, 1.85, 6]]);
    expect(g.length).toBeCloseTo(3 + 3.15, 6);
  });

  it("leaves an item's plan before a transmitter's lines go down", () => {
    const g = standGeometry([1, 1, 8], [0, 0, 0, 4, 2, 7], []);
    expect(g.path[0]).toEqual([1, 1, 8]);
    expect(g.path[1]).toEqual([-0.3, 1, 8]);
    expect(g.path[g.path.length - 1]).toEqual([-0.3, 1, STAND_M]);
    expect(g.top).toBe(STAND_M);
    expect(g.across).toEqual([1, 0, 0]);
  });

  it("finds the handwheel, else the lever, gearbox or actuator", () => {
    const base = { point: [0, 0, 1], direction: [1, 0, 0] } as Pick<ModelInlineItem, "point" | "direction">;
    const part = (id: string, extra: object) => ({ id: `V/${id}`, refs: {}, source: "generated", material: "valve", ...extra }) as NonNullable<ModelInlineItem["parts"]>[number];
    expect(operatorWheel({ ...base, parts: [part("handwheel", { kind: "torus", centre: [0, 0, 1.5], axis: [0, 0, 2], radius: 0.2 })] })).toEqual({ centre: [0, 0, 1.5], axis: [0, 0, 1], radius: 0.2 });
    expect(operatorWheel({ ...base, parts: [part("lever", { kind: "cylinder", start: [0, 0, 1.2], end: [0.4, 0, 1.2], radius: 0.01 })] }).centre).toEqual([0.4, 0, 1.2]);
    expect(operatorWheel({ ...base, parts: [part("actuator", { kind: "box", centre: [0, 0, 1.6], size: [0.3, 0.3, 0.3] })] }).centre).toEqual([0, 0, 1.6]);
    expect(operatorWheel({ ...base, parts: null }).centre).toEqual([0, 0, 1.3]);
  });

  it("names the operator kinds", () => {
    expect(operatorTitle({ kind: "chainwheel", use: "infrequent" })).toBe("chain wheel (infrequent use)");
    expect(operatorTitle({ kind: "remote_mount", via: "capillary", use: "regular" })).toBe("remote mount (capillary, regular use)");
    expect(operatorTitle({ kind: "extension_spindle" })).toBe("extension spindle");
  });

  it("puts a hatch on the outer face of the side it is declared on, turned with its owner", () => {
    const owner = { id: "S", origin: [10, 20] as [number, number], rotation: 90, width: 6, depth: 4, walls: [] };
    const g = hatchGeometry({ id: "H", side: "south", offset: 1, width: 1, height: 1, sill: 2, kind: "hatch" }, owner)!;
    // Turned 90 degrees: the frame's south side runs along +y at x = 10, outward to -x... the
    // south face's normal (0, -1) turns to (+1, 0): the wall stands at x = 10 + t (0.1).
    expect(g.centre[0]).toBeCloseTo(10.1, 6);
    expect(g.centre[1]).toBeCloseTo(21.5, 6);
    expect(g.centre[2]).toBeCloseTo(2.5, 6);
    expect(g.frame).toHaveLength(4);
    expect(hatchGeometry({ side: "up", offset: 0, width: 1, height: 1, kind: "hatch" }, owner)).toBeNull();
  });
});

describe("the lifting study and the datasheets", () => {
  const rows = parseLiftingStudy(liftingCsv);

  it("reads core's lifting study CSV, its columns in core's order", () => {
    expect(parseCsv(liftingCsv)[0]).toEqual([...LIFTING_COLUMNS]);
    expect(rows).toHaveLength(15);
    // the MAC motor (K-1101's heaviest maintenance lift, 30 t) under the 40 t B1 crane
    // an overhead crane is checked on the gross load: needed = gross, its rating as the capacity
    expect(rows.find((r) => r.tag === "K-1101")).toMatchObject({ weight_t: 30, crane: "building B1", gross_t: 34.65, required_t: 34.65, chart_capacity_t: 40, status: "building crane 40 t carries it" });
    const k4101 = rows.find((r) => r.tag === "K-4101")!;
    expect(k4101).toMatchObject({ weight_t: 45, crane: "mobile", pad: "Z-PAD-A4", radius_m: 12.5, gross_t: 51.975, moment_tm: 649.688, required_t: 69.3, lane: "clear", laydown: "Z-LAYDOWN-A4", chart: "", chart_capacity_t: null, status: "lane clear" });
    // A building crane has no pad, radius or moment.
    expect(rows.find((r) => r.tag === "E-1101")).toMatchObject({ crane: "building B1", pad: "", radius_m: null, moment_tm: null, status: "building crane 40 t carries it" });
    expect(rows.every(laneClear)).toBe(true);
    // Every lifted item, pad and laydown is an object of the model.
    for (const r of rows) {
      expect(resolveSelect(r.tag, scene), r.tag).toBe(`equipment:${r.tag}`);
      if (r.pad) expect(resolveSelect(r.pad, scene), r.pad).toBe(`zone:${r.pad}`);
      expect(resolveSelect(r.laydown, scene), r.laydown).toBe(`zone:${r.laydown}`);
    }
  });

  it("reads quoted cells, other line ends, a blocked lane, and refuses a file that is no study", () => {
    const text = 'tag,lane,radius_m,status\r\nX-1,"P-1, P-2",7.5,"lane blocked by ""P-1"""\r\n';
    const [row] = parseLiftingStudy(text);
    expect(row).toMatchObject({ tag: "X-1", lane: "P-1, P-2", radius_m: 7.5, status: 'lane blocked by "P-1"', weight_t: null, pad: "" });
    expect(laneClear(row!)).toBe(false);
    expect(() => parseLiftingStudy("a,b\n1,2\n")).toThrow(/no tag column/);
  });

  it("finds a datasheet for every equipment-list item the ASU places (not its silencers and relief valves, piping items)", () => {
    const tree = asuTreeJson as unknown as TreeEntry[];
    const paths = datasheetPaths(tree);
    expect(paths.get("K-4101")).toBe("equipment/datasheets/K-4101.yaml");
    expect(paths.has("README")).toBe(false);
    expect(asu.equipment.filter((e) => !paths.has(e.tag)).map((e) => e.type)).toEqual(["Silencer", "Silencer", "Silencer", "Silencer", "SpringLoadedGlobeSafetyValve", "SpringLoadedGlobeSafetyValve", "Silencer"]);
    expect(paths.size).toBe(39);
    expect(datasheetPaths([{ path: "equipment/datasheets/sub/X.yaml", type: "file", kind: "yaml" }, { path: "equipment/datasheets/P-1.yml", type: "file", kind: "yaml" }])).toEqual(new Map([["P-1", "equipment/datasheets/P-1.yml"]]));
  });

  it("marks a lifting finding on the item, its pad and what blocks its lane", () => {
    const f = { rule: "cheme.layout-lifting", level: "warning", file: "layout/plant-model.yaml", line: null, message: "", hint: "", ids: ["K-4101", "Z-PAD-A4"], key: "K-4101" } as unknown as Parameters<typeof findingTargets>[0];
    expect(findingTargets(f, scene).items).toEqual(["equipment:K-4101", "zone:Z-PAD-A4"]);
  });
});
