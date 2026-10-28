/**
 * Label decluttering, view framing, legend and finding grouping, and in-line items that come
 * once per segment.
 */
import { describe, expect, it } from "vitest";
import type { Finding, Layout, LayoutModel, ModelInlineItem } from "@/api";
import { declutter, distanceFade, labelRange, overlaps, type ScreenLabel } from "@/lib/labelDeclutter";
import { buildScene, cameraPose, equipmentGroup, fitDistance, groupLegend, LABEL_PRIORITY, plantBox, VIEWS, viewDirection, type Bounds, type Vec3 } from "@/lib/layoutScene";
import { buildModelScene, serviceColor, serviceFamily } from "@/lib/layoutModel";
import { FINDINGS_OPEN_MAX, groupFindings } from "@/lib/findings";
import { DEFAULT_SHOWN, layoutQuery, parseLayoutQuery, TOGGLES } from "@/lib/layoutUrl";
import asuJson from "./fixtures/layout-asu.json";

const asu = asuJson as unknown as Layout;
const model = asu.model!;

const box = (id: number, x: number, y: number, priority: number, extra: Partial<ScreenLabel> = {}): ScreenLabel => ({ id, x0: x, y0: y, x1: x + 60, y1: y + 16, priority, ...extra });

describe("label decluttering", () => {
  it("keeps labels that do not overlap", () => {
    expect([...declutter([box(1, 0, 0, 10), box(2, 100, 0, 10), box(3, 0, 40, 10)])].sort()).toEqual([1, 2, 3]);
  });

  it("hides the lower priority label of an overlapping pair, whichever comes first", () => {
    const line = box(1, 0, 0, LABEL_PRIORITY.line);
    const tag = box(2, 20, 5, LABEL_PRIORITY.equipment);
    expect([...declutter([line, tag])]).toEqual([2]);
    expect([...declutter([tag, line])]).toEqual([2]);
    // Structures beat lines, equipment beats structures.
    const frame = box(3, 30, 8, LABEL_PRIORITY.structure);
    expect([...declutter([line, frame])]).toEqual([3]);
    expect([...declutter([frame, tag])]).toEqual([2]);
  });

  it("keeps pinned labels (the selection and its related objects) even under higher ones", () => {
    const selectedLine = box(1, 0, 0, LABEL_PRIORITY.line, { pinned: true });
    const tag = box(2, 20, 5, LABEL_PRIORITY.equipment);
    expect([...declutter([tag, selectedLine])]).toEqual([1]);
    // Two pinned labels both stay, even overlapping.
    expect([...declutter([selectedLine, { ...tag, pinned: true }])].sort()).toEqual([1, 2]);
  });

  it("prefers the nearer of two equal labels, then the first", () => {
    expect([...declutter([box(1, 0, 0, 40, { depth: 50 }), box(2, 10, 0, 40, { depth: 20 })])]).toEqual([2]);
    expect([...declutter([box(1, 0, 0, 40), box(2, 10, 0, 40)])]).toEqual([1]);
  });

  it("keeps a gap between labels, and a hidden label does not block a third one", () => {
    expect(overlaps(box(1, 0, 0, 1), box(2, 61, 0, 1), 2)).toBe(true);
    expect(overlaps(box(1, 0, 0, 1), box(2, 63, 0, 1), 2)).toBe(false);
    // 2 loses to 1; 3 overlaps only 2, so it stays.
    const kept = declutter([box(1, 0, 0, 40), box(2, 50, 0, 10), box(3, 100, 0, 10)]);
    expect([...kept].sort()).toEqual([1, 3]);
  });

  it("works across grid cells for many labels", () => {
    const many = Array.from({ length: 400 }, (_, i) => box(i, (i % 20) * 30, Math.floor(i / 20) * 10, i % 3));
    const kept = declutter(many);
    const list = many.filter((l) => kept.has(l.id));
    for (const a of list) for (const b of list) if (a !== b) expect(overlaps(a, b, 2)).toBe(false);
    expect(list.length).toBeGreaterThan(20);
  });

  it("fades labels with distance: line numbers close up, tags across the plant, markers never", () => {
    expect(distanceFade(10, 20, 30)).toBe(1);
    expect(distanceFade(25, 20, 30)).toBeCloseTo(0.5, 9);
    expect(distanceFade(40, 20, 30)).toBe(0);
    const lines = labelRange(LABEL_PRIORITY.line, 150);
    const tags = labelRange(LABEL_PRIORITY.equipment, 150);
    expect(lines.far).toBeLessThan(tags.near);
    expect(tags.near).toBeGreaterThanOrEqual(300);
    expect(labelRange(LABEL_PRIORITY.marker, 150).near).toBe(Infinity);
    // A small plant keeps a floor, so labels do not vanish a few metres away.
    expect(labelRange(LABEL_PRIORITY.line, 5).near).toBeGreaterThanOrEqual(30);
  });
});

/** Every corner of `b` is inside the frustum of a camera at `position` looking at `target`. */
function seesAll(b: Bounds, position: Vec3, target: Vec3, fov: number, aspect: number): boolean {
  const f = norm(sub(target, position));
  let r = cross(f, [0, 0, 1]);
  r = Math.hypot(...r) < 1e-6 ? [1, 0, 0] : norm(r);
  const u = cross(r, f);
  const tanV = Math.tan((fov / 2) * (Math.PI / 180));
  for (const x of [b.min[0], b.max[0]])
    for (const y of [b.min[1], b.max[1]])
      for (const z of [b.min[2], b.max[2]]) {
        const rel = sub([x, y, z], position);
        const depth = dot(rel, f);
        if (depth <= 0) return false;
        if (Math.abs(dot(rel, u)) / depth > tanV + 1e-9) return false;
        if (Math.abs(dot(rel, r)) / depth > tanV * aspect + 1e-9) return false;
      }
  return true;
}
const sub = (a: Vec3, b: Vec3): Vec3 => [a[0] - b[0], a[1] - b[1], a[2] - b[2]];
const dot = (a: Vec3, b: Vec3) => a[0] * b[0] + a[1] * b[1] + a[2] * b[2];
const cross = (a: Vec3, b: Vec3): Vec3 => [a[1] * b[2] - a[2] * b[1], a[2] * b[0] - a[0] * b[2], a[0] * b[1] - a[1] * b[0]];
const norm = (v: Vec3): Vec3 => {
  const l = Math.hypot(...v);
  return [v[0] / l, v[1] / l, v[2] / l];
};

describe("framing", () => {
  const plant: Bounds = { min: [40, 30, 0], max: [130, 90, 45] };

  it("backs off until every corner of the box is in view, for each view and viewport shape", () => {
    for (const view of VIEWS)
      for (const aspect of [0.5, 1, 2.2]) {
        const pose = cameraPose(view, plant, 45, aspect);
        expect(seesAll(plant, pose.position, pose.target, 45, aspect), `${view} at ${aspect}`).toBe(true);
        // ... and not much further: with no margin, a corner touches the frustum.
        const tight = fitDistance(plant, viewDirection(view), 45, aspect, 1);
        const d = viewDirection(view);
        const nearer: Vec3 = [pose.target[0] + d[0] * tight * 0.97, pose.target[1] + d[1] * tight * 0.97, pose.target[2] + d[2] * tight * 0.97];
        expect(seesAll(plant, nearer, pose.target, 45, aspect), `${view} closer`).toBe(false);
      }
  });

  it("aims at the box centre from the named side", () => {
    const iso = cameraPose("iso", plant);
    expect(iso.target).toEqual([85, 60, 22.5]);
    expect(iso.position[0]).toBeLessThan(40);
    expect(iso.position[1]).toBeLessThan(30);
    expect(cameraPose("east", plant).position[0]).toBeGreaterThan(130);
    expect(cameraPose("top", plant).position[2]).toBeGreaterThan(45);
  });

  it("frames the plant, not the site: equipment, structures, pipes, racks and buildings", () => {
    const scene = buildScene(asu);
    const p = scene.plantBounds;
    const b = scene.bounds;
    // The site is 200 x 150 m; the plant is a part of it, although cooling water and product
    // lines run out to the battery limits at its edges.
    expect(b.max[0] - b.min[0]).toBeGreaterThan(200);
    expect(p.min[0]).toBeGreaterThan(10);
    expect(p.min[1]).toBeGreaterThan(10);
    expect((p.max[0] - p.min[0]) * (p.max[1] - p.min[1])).toBeLessThan(0.7 * (b.max[0] - b.min[0]) * (b.max[1] - b.min[1]));
    for (const key of ["equipment:K-1101", "structure:CB-1", "rack:PR1"]) {
      const box = scene.itemBounds.get(key)!;
      for (const i of [0, 1, 2] as const) {
        expect(box.min[i]).toBeGreaterThanOrEqual(p.min[i] - 1e-9);
        expect(box.max[i]).toBeLessThanOrEqual(p.max[i] + 1e-9);
      }
    }
    // Site-wide things (areas, roads) do not count.
    expect(plantBox(new Map([["area:A", { min: [0, 0, 0], max: [500, 500, 0] }]]))).toBeNull();
    expect(plantBox(new Map([["pipe:X", { min: [1, 2, 3], max: [4, 5, 6] }], ["road:R", { min: [0, 0, 0], max: [500, 500, 0] }]]))).toEqual({ min: [1, 2, 3], max: [4, 5, 6] });
    // Pipe points near the plant widen it; a run out to the battery limit does not.
    const items = new Map([["equipment:E", { min: [50, 50, 0], max: [60, 60, 10] } as Bounds]]);
    expect(plantBox(items, [[63, 55, 5], [0, 55, 5], [55, 55, 14]])).toEqual({ min: [50, 50, 0], max: [63, 60, 14] });
  });

  it("falls back to the whole scene when there is no plant", () => {
    const scene = buildScene({ site: { width: 50, depth: 40 }, areas: [], roads: [], racks: [], buildings: [], equipment: [], findings: [] } as unknown as Layout);
    expect(scene.plantBounds).toEqual(scene.bounds);
  });

  it("keeps the site view in the URL", () => {
    const state = parseLayoutQuery({ view: "site" });
    expect(state.view).toBe("site");
    expect(layoutQuery(state).view).toBe("site");
  });
});

describe("labels in the scene", () => {
  const scene = buildScene(asu);

  it("starts with equipment tags on and line numbers off, on a toggle of their own", () => {
    expect(TOGGLES).toContain("lines");
    expect(DEFAULT_SHOWN).toContain("labels");
    expect(DEFAULT_SHOWN).not.toContain("lines");
    expect(parseLayoutQuery({ layers: "equipment,pipes,labels,lines" }).shown).toContain("lines");
    const tag = scene.labels.find((l) => l.item === "equipment:K-1101")!;
    expect(tag.toggle).toBe("labels");
    const lines = scene.labels.filter((l) => l.item?.startsWith("pipe:"));
    expect(lines.length).toBeGreaterThan(50);
    expect(lines.every((l) => l.toggle === "lines" && l.priority === LABEL_PRIORITY.line)).toBe(true);
  });

  it("names the steel frames, between tags and line numbers", () => {
    const frame = scene.labels.find((l) => l.item === "structure:CB-1")!;
    expect(frame.toggle).toBe("names");
    expect(frame.priority).toBe(LABEL_PRIORITY.structure);
    expect(LABEL_PRIORITY.equipment).toBeGreaterThan(LABEL_PRIORITY.structure);
    expect(LABEL_PRIORITY.structure).toBeGreaterThan(LABEL_PRIORITY.line);
  });
});

describe("legend grouping", () => {
  it("groups rows by group, in order of first appearance, and drops repeats", () => {
    const rows = groupLegend([
      { label: "CentrifugalPump", color: "#1", group: "pumps" },
      { label: "Odd", color: "#2", group: null },
      { label: "ReciprocatingPump", color: "#1", group: "pumps" },
      { label: "CentrifugalPump", color: "#1", group: "pumps" },
      { label: "Odd", color: "#2", group: null },
    ]);
    expect(rows).toEqual([
      { label: "pumps", color: "#1", members: ["CentrifugalPump", "ReciprocatingPump"] },
      { label: "Odd", color: "#2" },
    ]);
  });

  it("names equipment groups from the type and service families from code or words", () => {
    expect(equipmentGroup("CentrifugalPump")).toBe("pumps");
    expect(equipmentGroup("PlateHeatExchanger")).toBe("heat exchangers");
    expect(equipmentGroup("Turbine")).toBeNull();
    expect(serviceFamily("Liquid oxygen")).toBe("oxygen");
    expect(serviceFamily("GOX")).toBe("oxygen");
    expect(serviceFamily("Waste nitrogen")).toBe("nitrogen");
    expect(serviceFamily("Cooling water return")).toBe("water");
    expect(serviceFamily("Dry air")).toBe("air");
    expect(serviceFamily("Rich liquid")).toBeNull();
    // A family shares its colour.
    expect(serviceColor("Liquid oxygen")).toBe(serviceColor("LOX"));
  });

  it("keeps the ASU legend short", () => {
    const scene = buildScene(asu);
    const types = new Set(asu.equipment.map((e) => e.type));
    expect(scene.legend.equipment.length).toBeLessThan(types.size);
    const exchangers = scene.legend.equipment.find((e) => e.label === "heat exchangers")!;
    expect(exchangers.members).toEqual(expect.arrayContaining(["TubularHeatExchanger", "PlateHeatExchanger"]));
    const services = new Set(model.pipes.map((p) => p.fluid || p.line));
    expect(scene.legend.pipes.length).toBeLessThan(services.size);
  });
});

describe("finding groups", () => {
  const f = (rule: string, level: Finding["level"], message = rule): Finding => ({ rule, level, message, hint: "", file: "x.yaml", line: null, ids: [] }) as unknown as Finding;

  it("groups by rule with counts and indexes, most severe first, then the largest", () => {
    const list = [f("a", "info"), f("b", "warning"), f("a", "info"), f("c", "info"), f("b", "error"), f("a", "info")];
    const groups = groupFindings(list);
    expect(groups.map((g) => [g.rule, g.level, g.count])).toEqual([
      ["b", "error", 2],
      ["a", "info", 3],
      ["c", "info", 1],
    ]);
    expect(groups[0]!.items.map((x) => x.index)).toEqual([1, 4]);
    expect(groups[0]!.counts).toEqual({ error: 1, warning: 1, info: 0 });
    expect(groupFindings([])).toEqual([]);
    expect(FINDINGS_OPEN_MAX).toBe(10);
  });

  it("groups the ASU findings to a handful of rules", () => {
    const all = [...(asu.findings ?? []), ...((asu as unknown as { model_findings?: Finding[] }).model_findings ?? [])];
    const groups = groupFindings(all);
    expect(all.length).toBeGreaterThan(FINDINGS_OPEN_MAX);
    expect(groups.length).toBeLessThan(all.length / 3);
    expect(groups.reduce((n, g) => n + g.count, 0)).toBe(all.length);
  });
});

describe("in-line items shared by two segments", () => {
  // The final contract: once, with both segments in its refs.
  const final = model.inline.find((i) => i.id === "P-03/PSV3114")!;
  const others = model.inline.filter((i) => i.id !== "P-03/PSV3114");
  // Older shapes: once per segment, each on its own pipe.
  const perSegment = ["S1", "S2"].map((n) => ({ ...final, segment: `Line_VNT3002_${n}`, pipe: `P-03/Line_VNT3002_${n}`, refs: { ...final.refs, segments: [`Line_VNT3002_${n}`] } }));

  const check = (inline: ModelInlineItem[]) => {
    const s = buildModelScene({ ...model, inline } as LayoutModel);
    const keys = [...s.items.keys()].filter((k) => k.startsWith("inline:") && s.items.get(k)!.highlight === "PSV3114");
    expect(keys).toHaveLength(1);
    const item = s.items.get(keys[0]!)!;
    expect(item.related.map((r) => r.key).sort()).toEqual(["pipe:P-03/Line_VNT3002_S1", "pipe:P-03/Line_VNT3002_S2"]);
    expect(item.details).toContainEqual(["segments", "Line_VNT3002_S1, Line_VNT3002_S2"]);
    expect(item.details.filter(([k]) => k === "line" || k === "lines")).toEqual([["line", "VNT-3002"]]);
    // Drawn once.
    expect(new Set(s.meshes.filter((m) => m.item === keys[0]).map((m) => m.key)).size).toBe(s.meshes.filter((m) => m.item === keys[0]).length);
    return s;
  };

  it("is one item when it comes once with both segments in its refs (the final contract)", () => {
    expect(final.refs.segments).toEqual(["Line_VNT3002_S1", "Line_VNT3002_S2"]);
    expect(model.inline.filter((i) => i.id === final.id)).toHaveLength(1);
    check(model.inline);
  });

  it("is one item when it comes twice with the same id (older core)", () => {
    check([...others, ...perSegment]);
  });

  it("is one item when the ids are unique per segment", () => {
    const s = check([...others, { ...perSegment[0]!, id: "P-03/PSV3114@S1" }, { ...perSegment[1]!, id: "P-03/PSV3114@S2" }]);
    // Both ids still lead to it.
    expect(s.ids.get("P-03/PSV3114@S2")).toBe(s.ids.get("P-03/PSV3114@S1"));
  });
});
