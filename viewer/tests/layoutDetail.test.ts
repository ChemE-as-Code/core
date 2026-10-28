/**
 * Level of detail and the new part kinds: torus and frustum primitives (model and geometry),
 * the `lod` of parts through the scene, instancing of repeated detail, the grating texture and
 * the URL state of the realistic look and the detail mode.
 */
import { describe, expect, it } from "vitest";
import * as THREE from "three";
import type { LayoutModel, ModelEquipment, ModelPart } from "@/api";
import { buildModelScene, frustumCorners, lodOf, partPrim, primBounds, ringBasis, type MeshSpec, type Prim } from "@/lib/layoutModel";
import { detailCell, instanceable, primGeometry, primInstance } from "@/lib/layoutThree";
import { gratingTexture, REAL_SURFACE } from "@/lib/layoutRealism";
import { layoutQuery, parseLayoutQuery } from "@/lib/layoutUrl";

const base = { refs: {}, source: "generated" as const };

function bbox(prim: Prim): THREE.Box3 {
  const g = primGeometry(prim)!;
  g.computeBoundingBox();
  return g.boundingBox!;
}

const close = (a: ArrayLike<number>, b: ArrayLike<number>, digits = 3) => {
  for (let i = 0; i < b.length; i++) expect(a[i]).toBeCloseTo(b[i]!, digits);
};

describe("torus and frustum parts", () => {
  it("reads a torus with its tube, arc and start direction", () => {
    const prim = partPrim({ ...base, id: "P/volute", kind: "torus", material: "casing", centre: [1, 2, 3], axis: [2, 0, 0], radius: 0.4, tube: 0.1, ref: [0, 0, 1], arc_deg: [0, 270] });
    expect(prim).toEqual({ kind: "torus", centre: [1, 2, 3], axis: [1, 0, 0], radius: 0.4, tube: 0.1, arc: [0, 270], ref: [0, 0, 1] });
    expect(partPrim({ ...base, id: "x", kind: "torus", material: "steel", centre: [0, 0, 0], radius: 1 })).toBeNull();
  });

  it("reads core's upright frustum: bottom centre, [dx, dy, height] and the top's size", () => {
    const prim = partPrim({ ...base, id: "AC/plenum", kind: "frustum", material: "casing", centre: [5, 5, 2], size: [4, 2, 1.5], size_end: [1, 1], rotation_deg: 90 });
    expect(prim).toMatchObject({ kind: "frustum", start: [5, 5, 2], end: [5, 5, 3.5], size: [4, 2], sizeEnd: [1, 1] });
    expect((prim as Extract<Prim, { kind: "frustum" }>).rotationZ).toBeCloseTo(Math.PI / 2);
    // Turned 90 degrees: the 4 m side runs north.
    const b = primBounds(prim!);
    close(b.min, [4, 3, 2]);
    close(b.max, [6, 7, 3.5]);
    expect(partPrim({ ...base, id: "x", kind: "frustum", material: "casing", centre: [0, 0, 0], size: [1, 1, 0] })).toBeNull();
    // A round one is a cone.
    expect(partPrim({ ...base, id: "x", kind: "frustum", material: "casing", start: [0, 0, 0], end: [0, 0, 1], radius: 1, radius_end: 0.5 })).toEqual({ kind: "cylinder", start: [0, 0, 0], end: [0, 0, 1], radius: 1, radiusEnd: 0.5 });
  });

  it("starts a ring at east about a vertical axis, else at the top, or at the given direction", () => {
    close(ringBasis([0, 0, 1])[0], [1, 0, 0]);
    close(ringBasis([0, 0, 1])[1], [0, 1, 0]);
    close(ringBasis([1, 0, 0])[0], [0, 0, 1]);
    close(ringBasis([1, 0, 0], [0, 1, 0.2])[0], [0, 1 / Math.hypot(1, 0.2), 0.2 / Math.hypot(1, 0.2)]);
  });

  it("draws a full torus within its bounds and a quarter one where its arc says", () => {
    const full: Prim = { kind: "torus", centre: [0, 0, 1], axis: [0, 0, 1], radius: 1, tube: 0.2, arc: null };
    const b = bbox(full);
    close(b.min.toArray(), [-1.2, -1.2, 0.8], 2);
    close(b.max.toArray(), [1.2, 1.2, 1.2], 2);
    const bounds = primBounds(full);
    close(bounds.min, [-1.2, -1.2, 0.8]);
    // East to north only: nothing west or south of the tube.
    const quarter = bbox({ ...full, arc: [0, 90] });
    expect(quarter.min.x).toBeGreaterThan(-0.21);
    expect(quarter.min.y).toBeGreaterThan(-0.21);
    expect(quarter.max.x).toBeCloseTo(1.2, 2);
    // About +x from straight down, half a turn ccw sweeps through +y (axis x down = y).
    const half = bbox({ kind: "torus", centre: [0, 0, 5], axis: [1, 0, 0], radius: 1, tube: 0.1, arc: [0, 180], ref: [0, 0, -1] });
    expect(half.min.y).toBeGreaterThan(-0.11);
    expect(half.max.y).toBeCloseTo(1.1, 2);
    expect(half.min.z).toBeCloseTo(3.9, 2);
    expect(half.max.z).toBeCloseTo(6.1, 2);
  });

  it("draws a frustum as a closed solid with outward faces", () => {
    const prim: Extract<Prim, { kind: "frustum" }> = { kind: "frustum", start: [0, 0, 0], end: [0, 0, 2], size: [2, 2], sizeEnd: [1, 1], rotationZ: 0 };
    const g = primGeometry(prim)!;
    const pos = g.getAttribute("position");
    const normal = g.getAttribute("normal");
    expect(pos.count).toBe(36);
    // Every face's normal points away from the axis' middle.
    for (let i = 0; i < pos.count; i += 3) {
      const c = new THREE.Vector3();
      for (let k = 0; k < 3; k++) c.add(new THREE.Vector3(pos.getX(i + k), pos.getY(i + k), pos.getZ(i + k)));
      c.divideScalar(3).sub(new THREE.Vector3(0, 0, 1));
      expect(c.dot(new THREE.Vector3(normal.getX(i), normal.getY(i), normal.getZ(i)))).toBeGreaterThan(0);
    }
    expect(frustumCorners(prim)).toHaveLength(8);
    const b = bbox(prim);
    close(b.min.toArray(), [-1, -1, 0]);
    close(b.max.toArray(), [1, 1, 2]);
    // Lying along x: the first size runs across (y), the second up.
    const lying = bbox({ kind: "frustum", start: [0, 0, 1], end: [3, 0, 1], size: [2, 1], sizeEnd: [2, 1], rotationZ: 0 });
    close(lying.min.toArray(), [0, -1, 0.5]);
    close(lying.max.toArray(), [3, 1, 1.5]);
  });
});

describe("levels of detail through the scene", () => {
  const part = (id: string, extra: Partial<ModelPart>): ModelPart => ({ ...base, id, kind: "box", material: "casing", centre: [0, 0, 0.5], size: [1, 1, 1], ...extra });
  const pump: ModelEquipment = {
    id: "P-1",
    refs: { tag: "P-1" },
    source: "declared",
    tag: "P-1",
    type: "CentrifugalPump",
    family: "pump",
    shape: "box",
    size_from: "default",
    dimensions: {},
    position: [0, 0, 0],
    rotation_deg: 0,
    bbox: [-1, -1, 0, 1, 1, 1],
    parts: [
      part("P-1/plinth", { material: "concrete" }),
      part("P-1/envelope", { lod: 1 }),
      part("P-1/volute", { kind: "torus", centre: [0, 0, 0.5], axis: [1, 0, 0], radius: 0.2, tube: 0.08, lod: 2 }),
      part("P-1/guard", { material: "guard", lod: 2 }),
    ],
    nozzles: [],
    envelopes: [],
  } as unknown as ModelEquipment;
  const model = { equipment: [pump], pipes: [], inline: [], structures: [], platforms: [], racks: [], zones: [], buildings: [] } as unknown as LayoutModel;

  it("keeps each part's level: none, the envelope or the detail", () => {
    expect(lodOf({ lod: null })).toEqual({});
    expect(lodOf({ lod: 1 })).toEqual({ lod: 1 });
    expect(lodOf({ lod: 2 })).toEqual({ lod: 2 });
    const scene = buildModelScene(model);
    const byKey = new Map(scene.meshes.map((m) => [m.key, m]));
    expect(byKey.get("P-1/plinth")!.lod).toBeUndefined();
    expect(byKey.get("P-1/plinth")!.color).toBe("#a8a59d");
    expect(byKey.get("P-1/envelope")!.lod).toBe(1);
    expect(byKey.get("P-1/volute")!.lod).toBe(2);
    expect(byKey.get("P-1/volute")!.prim.kind).toBe("torus");
    expect(byKey.get("P-1/guard")!.color).toBe("#e0a526");
  });

  it("gives a nozzle its own detail and draws its stand-in from the shell to the flange face, from afar", () => {
    const withNozzle = {
      ...model,
      equipment: [
        {
          ...pump,
          parts: [
            ...pump.parts,
            { ...base, id: "P-1/N1/neck", kind: "cylinder", material: "steel", start: [0, 0, 1], end: [0, 0, 1.3], radius: 0.05, lod: 2 },
            { ...base, id: "P-1/N1/flange", kind: "cylinder", material: "flange", start: [0, 0, 1.27], end: [0, 0, 1.3], radius: 0.09, lod: 2 },
          ],
          nozzles: [{ ...base, id: "P-1/N1", name: "N1", dn: 100, point: [0, 0, 1.3], base: [0, 0, 1], direction: [0, 0, 1], basis: "pid", source: "generated" }],
        },
      ],
    } as unknown as LayoutModel;
    const scene = buildModelScene(withNozzle);
    const nozzle = scene.meshes.filter((m) => m.item === "nozzle:P-1/N1");
    expect(nozzle.map((m) => [m.key, m.lod])).toEqual([
      ["nozzle:P-1/N1", 1],
      ["nozzle:P-1/N1:flange", 1],
      ["P-1/N1/neck", 2],
      ["P-1/N1/flange", 2],
    ]);
    expect(nozzle[0]!.prim).toMatchObject({ start: [0, 0, 1], end: [0, 0, 1.3] });
    expect(scene.meshes.some((m) => m.item === "equipment:P-1" && m.key.startsWith("P-1/N1/"))).toBe(false);
    expect(scene.ids.get("P-1/N1/flange")).toBe("nozzle:P-1/N1");
  });

  it("draws core's in-line parts instead of its own valve shape, and pipe parts on the pipe", () => {
    const withValve = {
      ...model,
      equipment: [],
      pipes: [
        {
          id: "L1/S1",
          refs: {},
          source: "generated",
          line: "L1",
          segment: "S1",
          points: [
            [0, 0, 1],
            [10, 0, 1],
          ],
          dn: 100,
          od: 0.114,
          insulation_mm: 0,
          length: 10,
          method: "astar",
          parts: [{ ...base, id: "L1/S1/flange-1", kind: "cylinder", material: "flange", start: [2, 0, 1], end: [2.03, 0, 1], radius: 0.11, lod: 2 }],
        },
      ],
      inline: [
        {
          id: "V1",
          refs: {},
          source: "generated",
          kind: "valve",
          dexpi_class: "GateValve",
          point: [5, 0, 1],
          direction: [1, 0, 0],
          line: "L1",
          segment: "S1",
          pipe: "L1/S1",
          parts: [
            { ...base, id: "V1/body", kind: "cylinder", material: "casing", start: [4.8, 0, 1], end: [5.2, 0, 1], radius: 0.1 },
            { ...base, id: "V1/handwheel", kind: "torus", material: "steel", centre: [5, 0, 1.5], axis: [0, 0, 1], radius: 0.15, tube: 0.01, lod: 2 },
          ],
        },
      ],
    } as unknown as LayoutModel;
    const scene = buildModelScene(withValve);
    const valve = scene.meshes.filter((m) => m.item === "inline:V1");
    expect(valve.map((m) => m.prim.kind)).toEqual(["cylinder", "torus"]);
    expect(valve[1]!.lod).toBe(2);
    expect(scene.ids.get("V1/handwheel")).toBe("inline:V1");
    const flange = scene.meshes.find((m) => m.key === "L1/S1/flange-1")!;
    expect(flange).toMatchObject({ layer: "pipes", item: "pipe:L1/S1", material: "flange", lod: 2 });
  });
});

describe("access and support detail", () => {
  it("draws supports on their pipe, step-overs to review, rack ladders and bund walls", () => {
    const grating = { ...base, kind: "box", material: "grating", centre: [5, 0, 0.6], size: [1, 1, 0.03] };
    const model = {
      equipment: [],
      inline: [],
      structures: [],
      platforms: [],
      zones: [],
      buildings: [],
      pipes: [{ id: "L1/S1", refs: {}, source: "generated", line: "L1", segment: "S1", points: [[0, 0, 0.3], [10, 0, 0.3]], dn: 50, od: 0.06, insulation_mm: 50, jacket: "personnel", length: 10, method: "astar" }],
      supports: [{ ...base, id: "L1/S1/support-1", kind: "shoe", pipe: "L1/S1", on: "R1/beam", point: [2, 0, 0.2], parts: [{ ...base, id: "L1/S1/support-1/shoe", kind: "box", material: "steel", centre: [2, 0, 0.25], size: [0.2, 0.1, 0.1], lod: 2 }] }],
      step_overs: [{ ...base, id: "step-over-1", pipe: "L1/S1", walkway: "Z-escape", point: [5, 0, 0], height: 0.6, box: [4.5, -0.5, 0, 5.5, 0.5, 0.6], review_needed: true, parts: [{ ...grating, id: "step-over-1/deck" }] }],
      racks: [{ id: "R1", refs: {}, source: "generated", points: [[0, 0], [10, 0]], width: 6, levels: [5], parts: [], ladders: [{ ...base, id: "R1/ladder-start", base: [0, 0, 0], top: [0, 0, 5], cage: true, review_needed: true, parts: [{ ...base, id: "R1/ladder-start/rail-1", kind: "member", material: "steel", start: [0, 0, 0], end: [0, 0, 6] }] }] }],
      areas: [{ id: "BUND-1", refs: {}, source: "declared", box: [0, 0, 10, 10], kind: "bund", wall_height: 1, parts: [{ ...base, id: "BUND-1/wall-north", kind: "box", material: "concrete", centre: [5, 9.85, 0.5], size: [10, 0.3, 1] }] }],
    } as unknown as LayoutModel;
    const scene = buildModelScene(model);
    const byKey = new Map(scene.meshes.map((m) => [m.key, m]));
    expect(byKey.get("L1/S1/support-1/shoe")).toMatchObject({ item: "pipe:L1/S1", layer: "pipes", lod: 2 });
    expect(scene.ids.get("L1/S1/support-1")).toBe("pipe:L1/S1");
    expect(byKey.get("step-over-1/deck")).toMatchObject({ item: "platform:step-over-1", layer: "platforms", review: true });
    expect(scene.items.get("platform:step-over-1")).toMatchObject({ type: "step-over", review: true });
    expect(scene.floors.map((f) => f.id)).toContain("step-over-1/deck");
    // A proposed rack ladder is an item of its own, related to its rack.
    expect(byKey.get("R1/ladder-start/rail-1")).toMatchObject({ item: "platform:R1/ladder-start", layer: "platforms", review: true });
    expect(scene.items.get("platform:R1/ladder-start")).toMatchObject({ type: "ladder", review: true, related: [{ key: "rack:R1", label: "R1" }] });
    expect(scene.proposals.get("ladder")).toEqual(["platform:R1/ladder-start"]);
    expect(byKey.get("BUND-1/wall-north")).toMatchObject({ item: "area:BUND-1", layer: "structures", opacity: 1, color: "#a8a59d" });
    expect(byKey.get("pipe:L1/S1:i0")!.material).toBe("insulation_personnel");
  });
});

describe("instancing and cells", () => {
  const mesh = (prim: Prim, extra: Partial<MeshSpec> = {}): MeshSpec => ({ key: "k", layer: "equipment", item: "equipment:P-1", prim, color: "#fff", material: "steel", opacity: 1, source: null, clash: false, ...extra });

  it("instances detail and handrails of simple shapes, never gratings", () => {
    const post: Prim = { kind: "beam", start: [0, 0, 0], end: [0, 0, 1.1], width: 0.05, depth: 0.05 };
    expect(instanceable(mesh(post, { material: "handrail" }))).toBe(true);
    expect(instanceable(mesh(post, { lod: 2 }))).toBe(true);
    expect(instanceable(mesh(post))).toBe(false);
    expect(instanceable(mesh(post, { lod: 2, material: "grating" }))).toBe(false);
    expect(instanceable(mesh({ kind: "torus", centre: [0, 0, 0], axis: [0, 0, 1], radius: 1, tube: 0.1, arc: null }, { lod: 2 }))).toBe(false);
  });

  it("puts an instance where the merged geometry would be", () => {
    const prims: Prim[] = [
      { kind: "box", centre: [3, 4, 5], size: [1, 2, 3], rotationZ: 0.3 },
      { kind: "beam", start: [0, 0, 0], end: [2, 1, 1], width: 0.1, depth: 0.2 },
      { kind: "cylinder", start: [1, 1, 1], end: [1, 3, 1], radius: 0.1, radiusEnd: 0.05 },
      { kind: "ellipsoid", centre: [0, 0, 2], radii: [0.3, 0.3, 0.3], rotationZ: 0 },
    ];
    for (const prim of prims) {
      const inst = primInstance(prim)!;
      const g = inst.geometry().clone().applyMatrix4(inst.matrix);
      g.computeBoundingBox();
      const merged = bbox(prim);
      close(g.boundingBox!.min.toArray(), merged.min.toArray());
      close(g.boundingBox!.max.toArray(), merged.max.toArray());
    }
    expect(primInstance({ kind: "elbow", start: [0, 0, 0], corner: [1, 0, 0], end: [1, 1, 0], radius: 0.1 })).toBeNull();
  });

  it("groups detail by the plan cell of its item's centre", () => {
    expect(detailCell({ min: [0, 0, 0], max: [10, 10, 5] }, 32)).toBe("0,0");
    expect(detailCell({ min: [60, -10, 0], max: [70, -2, 5] }, 32)).toBe("2,-1");
    expect(detailCell(undefined)).toBe("0,0");
  });
});

describe("realistic look", () => {
  it("makes a grating texture with a full mip chain that closes up with distance", () => {
    const t = gratingTexture(64);
    expect(t.mipmaps).toHaveLength(7);
    expect(t.generateMipmaps).toBe(false);
    expect(t.wrapS).toBe(THREE.RepeatWrapping);
    const levels = t.mipmaps as unknown as { data?: Uint8Array; width: number }[];
    // jsdom has no 2D canvas: the levels are raw data.
    const open = (level: { data?: Uint8Array }) => {
      const d = level.data!;
      let n = 0;
      for (let i = 0; i < d.length; i += 4) if (d[i] === 0) n++;
      return n / (d.length / 4);
    };
    expect(open(levels[0]!)).toBeGreaterThan(0.4);
    expect(open(levels[4]!)).toBe(0);
  });

  it("knows the new materials", () => {
    for (const m of ["concrete", "painted", "stainless", "galvanised", "insulation_jacket", "grating"]) expect(REAL_SURFACE[m]).toBeDefined();
    expect(REAL_SURFACE.stainless!.metalness).toBeGreaterThan(REAL_SURFACE.concrete!.metalness);
  });

  it("keeps the look and the detail mode in the URL", () => {
    const state = parseLayoutQuery({ look: "realistic", detail: "full" });
    expect(state.realistic).toBe(true);
    expect(state.detail).toBe("full");
    expect(layoutQuery(state)).toMatchObject({ look: "realistic", detail: "full" });
    const plain = parseLayoutQuery({ detail: "bogus" });
    expect(plain.realistic).toBe(false);
    expect(plain.detail).toBe("auto");
    expect(layoutQuery(plain)).toMatchObject({ look: undefined, detail: undefined });
  });
});
