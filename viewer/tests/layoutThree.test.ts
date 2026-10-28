/**
 * The three.js geometry of the scene primitives (no WebGL needed) and the vertex-range lookup
 * that maps a ray hit on a merged mesh back to its item.
 */
import { describe, expect, it } from "vitest";
import * as THREE from "three";
import { mergeGeometries } from "three/examples/jsm/utils/BufferGeometryUtils.js";
import type { Prim } from "@/lib/layoutModel";
import { primBounds } from "@/lib/layoutModel";
import { primGeometry, rangeOf } from "@/lib/layoutThree";

function box(prim: Prim): THREE.Box3 {
  const g = primGeometry(prim)!;
  g.computeBoundingBox();
  return g.boundingBox!;
}

const near = (v: THREE.Vector3, expected: number[], digits = 3) => {
  expect(v.x).toBeCloseTo(expected[0]!, digits);
  expect(v.y).toBeCloseTo(expected[1]!, digits);
  expect(v.z).toBeCloseTo(expected[2]!, digits);
};

describe("primitive geometry", () => {
  it("puts a cylinder along its axis with its radius", () => {
    const b = box({ kind: "cylinder", start: [10, 0, 0], end: [10, 0, 4], radius: 1, radiusEnd: 1 });
    near(b.min, [9, -1, 0]);
    near(b.max, [11, 1, 4]);
    const horizontal = box({ kind: "cylinder", start: [0, 0, 1], end: [6, 0, 1], radius: 0.5, radiusEnd: 0.5 });
    near(horizontal.min, [0, -0.5, 0.5]);
    near(horizontal.max, [6, 0.5, 1.5]);
  });

  it("narrows a cone towards its end", () => {
    const g = primGeometry({ kind: "cylinder", start: [0, 0, 0], end: [0, 0, 2], radius: 1, radiusEnd: 0 })!;
    const pos = g.getAttribute("position");
    let topRadius = 0;
    for (let i = 0; i < pos.count; i++) if (pos.getZ(i) > 1.99) topRadius = Math.max(topRadius, Math.hypot(pos.getX(i), pos.getY(i)));
    expect(topRadius).toBeLessThan(1e-6);
  });

  it("bulges a cap along its axis by its depth", () => {
    const b = box({ kind: "cap", centre: [0, 0, 5], axis: [0, 0, -1], radius: 2, depth: 0.5 });
    near(b.min, [-2, -2, 4.5]);
    near(b.max, [2, 2, 5]);
  });

  it("turns boxes about z and lays beams along their members", () => {
    const b = box({ kind: "box", centre: [0, 0, 0], size: [4, 2, 1], rotationZ: Math.PI / 2 });
    near(b.min, [-1, -2, -0.5]);
    const beam = box({ kind: "beam", start: [0, 0, 0], end: [0, 0, 6], width: 0.3, depth: 0.3 });
    near(beam.min, [-0.15, -0.15, 0]);
    near(beam.max, [0.15, 0.15, 6]);
  });

  it("bends elbows between their ends and stays inside the pure bounds", () => {
    const prim: Prim = { kind: "elbow", start: [9, 0, 0], corner: [10, 0, 0], end: [10, 1, 0], radius: 0.1 };
    const b = box(prim);
    const pure = primBounds(prim);
    expect(b.min.x).toBeGreaterThanOrEqual(pure.min[0] - 1e-6);
    expect(b.max.y).toBeLessThanOrEqual(pure.max[1] + 1e-6);
    near(b.max, [10.1, 1, 0.1], 2);
  });

  it("extrudes platform rings, all round or over an arc", () => {
    const full = box({ kind: "annulus", centre: [10, 0, 12], inner: 1.6, outer: 2.6, depth: 0.03, arc: null });
    near(full.min, [7.4, -2.6, 11.97]);
    near(full.max, [12.6, 2.6, 12]);
    // 300 to 60 degrees: the east side only.
    const arc = box({ kind: "annulus", centre: [0, 0, 0], inner: 1, outer: 2, depth: 0.1, arc: [300, 60] });
    expect(arc.min.x).toBeGreaterThan(0.49);
    near(arc.max, [2, Math.sqrt(3), 0], 2);
    expect(primGeometry({ kind: "annulus", centre: [0, 0, 0], inner: 2, outer: 1, depth: 0.1, arc: null })).toBeNull();
  });

  it("skips degenerate members and merges everything into one buffer", () => {
    expect(primGeometry({ kind: "beam", start: [1, 1, 1], end: [1, 1, 1], width: 1, depth: 1 })).toBeNull();
    const parts: Prim[] = [
      { kind: "box", centre: [0, 0, 0], size: [1, 1, 1], rotationZ: 0 },
      { kind: "cylinder", start: [0, 0, 0], end: [0, 0, 1], radius: 0.2, radiusEnd: 0.2 },
      { kind: "cap", centre: [0, 0, 1], axis: [0, 0, 1], radius: 0.2, depth: 0.1 },
      { kind: "ellipsoid", centre: [0, 0, 0], radii: [1, 1, 1], rotationZ: 0 },
      { kind: "elbow", start: [0, 0, 0], corner: [1, 0, 0], end: [1, 1, 0], radius: 0.1 },
      { kind: "annulus", centre: [0, 0, 0], inner: 1, outer: 2, depth: 0.1, arc: [0, 90] },
    ];
    const geometries = parts.map((p) => primGeometry(p)!);
    // Non-indexed ones (the extruded ring) get an index, as the batching does.
    for (const g of geometries) if (!g.index) g.setIndex([...Array(g.attributes.position!.count).keys()]);
    const merged = mergeGeometries(geometries);
    expect(merged).not.toBeNull();
    expect(Object.keys(merged!.attributes).sort()).toEqual(["normal", "position"]);
  });
});

describe("rangeOf", () => {
  const ranges = [
    { start: 0, count: 24 },
    { start: 24, count: 100 },
    { start: 124, count: 8 },
  ];
  it("finds the source mesh of a vertex", () => {
    expect(rangeOf(ranges, 0)).toBe(0);
    expect(rangeOf(ranges, 23)).toBe(0);
    expect(rangeOf(ranges, 24)).toBe(1);
    expect(rangeOf(ranges, 131)).toBe(2);
    expect(rangeOf(ranges, 132)).toBe(-1);
    expect(rangeOf([], 0)).toBe(-1);
  });
});

describe("glTF export of instanced detail", () => {
  it("bakes each instance's matrix and colour into a plain mesh with vertex colours", async () => {
    const { deinstance } = await import("@/lib/layoutThree");
    const material = new THREE.MeshStandardMaterial({ vertexColors: false });
    const mesh = new THREE.InstancedMesh(new THREE.BoxGeometry(1, 1, 1), material, 2);
    mesh.name = "structures:handrail:instanced:detail";
    mesh.setMatrixAt(0, new THREE.Matrix4().makeTranslation(10, 0, 0));
    mesh.setMatrixAt(1, new THREE.Matrix4().makeTranslation(0, 20, 0));
    mesh.setColorAt(0, new THREE.Color(1, 0, 0));
    mesh.setColorAt(1, new THREE.Color(0, 0, 1));
    const plain = deinstance(mesh);
    expect(plain).not.toBeInstanceOf(THREE.InstancedMesh);
    expect(plain.name).toBe("structures:handrail:merged:detail");
    const m = plain.material as THREE.MeshStandardMaterial;
    expect(m.vertexColors).toBe(true);
    expect(m).not.toBe(material);
    expect(material.vertexColors).toBe(false); // the live material is untouched
    const position = plain.geometry.getAttribute("position");
    const color = plain.geometry.getAttribute("color");
    expect(position.count).toBe(2 * mesh.geometry.getAttribute("position").count);
    const half = position.count / 2;
    expect(position.getX(0)).toBeCloseTo(10.5, 3); // the first box moved by its matrix
    expect([color.getX(0), color.getY(0), color.getZ(0)]).toEqual([1, 0, 0]);
    expect(position.getY(half)).toBeGreaterThan(19);
    expect([color.getX(half), color.getY(half), color.getZ(half)]).toEqual([0, 0, 1]);
  });
});
