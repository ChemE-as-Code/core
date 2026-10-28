/**
 * three.js side of the layout view. It turns the pure {@link SceneSpec} into a few merged meshes
 * (one per layer, material and opacity: equipment parts, pipes, steel, ... are batched with
 * vertex colours, so a large model is a handful of draw calls), line sets and CSS labels; it
 * renders on demand, except while walking or flying.
 *
 * Picking, selection and colour modes work on the merged meshes through vertex ranges: each
 * batch keeps the first vertex of every source mesh, so a ray hit's vertex maps back to its
 * item, and repainting an item rewrites only its vertex colours.
 *
 * Imported dynamically by LayoutView, so three.js loads on /layout only.
 */
import * as THREE from "three";
import { OrbitControls } from "three/examples/jsm/controls/OrbitControls.js";
import { CSS2DObject, CSS2DRenderer } from "three/examples/jsm/renderers/CSS2DRenderer.js";
import { mergeGeometries } from "three/examples/jsm/utils/BufferGeometryUtils.js";
import {
  cameraPose,
  CLASH_COLOR,
  fitDistance,
  planFrame,
  siteGrid,
  type LayerId,
  type MeshSpec,
  type Prim,
  type SceneSpec,
  type Vec3,
  type ViewName,
} from "./layoutScene";
import { declutter, distanceFade, labelRange, type ScreenLabel } from "./labelDeclutter";
import { EYE_HEIGHT, frustumCorners, measure, provenanceColor, REVIEW_COLOR, ringBasis, sectionPlanes, snapFloor, stepFloor, type Box3 } from "./layoutModel";
import { createRealism, GRATING_PITCH, gratingTexture, REAL_SURFACE, type Realism } from "./layoutRealism";

export interface Theme {
  background: string;
  ground: string;
  grid: string;
  /** Dark colour scheme: translucent area slabs are drawn more opaque to stay apart. */
  dark: boolean;
}

export type ColorMode = "normal" | "class" | "provenance";
/** How surfaces look: flat colours, or physically based materials with shadows and ambient occlusion. */
export type Look = "normal" | "realistic";
/** Which level of detail draws: by camera distance, all of it, or the envelopes only. */
export type Detail = "auto" | "full" | "envelope";
export type NavMode = "orbit" | "walk" | "fly";
export type Tool = "pick" | "measure";

export interface CameraState {
  position: Vec3;
  target: Vec3;
}

export interface MeasureResult {
  a: Vec3;
  b: Vec3;
  distance: number;
  dx: number;
  dy: number;
  dz: number;
}

declare global {
  interface Window {
    /** The layout page's renderer while it shows one, for the end-to-end tests (frame rate) and the console. */
    __layoutRenderer?: LayoutRenderer;
  }
}

export interface LayoutRenderer {
  setLayer(layer: LayerId | "labels" | "lines" | "names", visible: boolean): void;
  setView(view: ViewName): void;
  setSelected(item: string | null): void;
  /** Mark the items (and box) of a finding; an empty list clears it. */
  setHighlighted(items: string[], box?: Box3 | null): void;
  /** Draw polylines over the model (a cable's way), seen through what is in front; none clears it. */
  setRoute(paths: Vec3[][]): void;
  setTheme(theme: Theme): void;
  setColorMode(mode: ColorMode): void;
  setXray(on: boolean): void;
  setLook(look: Look): void;
  setDetail(detail: Detail): void;
  setSection(box: Box3 | null): void;
  setNavigation(mode: NavMode): void;
  setTool(tool: Tool): void;
  setFlySpeed(speed: number): void;
  /** Frame an item. */
  focus(item: string): void;
  getCamera(): CameraState;
  setCamera(state: CameraState): void;
  /** The visible scene as a binary glTF. */
  exportGlb(): Promise<ArrayBuffer>;
  /** Draw calls and triangles of the last frame (for the status line and tests). */
  stats(): RenderStats;
  /**
   * Frames per second while the camera turns about its target for `ms` milliseconds, rendering
   * every frame as the current look and detail would (the camera is put back after).
   */
  benchmark(ms?: number): Promise<{ fps: number; frames: number; calls: number; triangles: number }>;
  dispose(): void;
}

export interface RenderStats {
  /** Merged and instanced meshes. */
  batches: number;
  /** Source meshes (parts) in the scene. */
  meshes: number;
  /** Instanced meshes and the instances they draw. */
  instanced: number;
  instances: number;
  /** Detail (LOD 2) batches, and how many of them the last frame drew. */
  detail: number;
  detailShown: number;
  calls: number;
  triangles: number;
}

export interface RendererOptions {
  theme: Theme;
  onPick: (item: string | null) => void;
  onMeasure?: (result: MeasureResult | null) => void;
  /** Camera moved (orbit end, view change, focus); throttled by the caller if needed. */
  onCamera?: (state: CameraState) => void;
  /** Walk or fly mode ended by the user (Escape) or a lost pointer lock. */
  onNavigation?: (mode: NavMode) => void;
  onFlySpeed?: (speed: number) => void;
}

const FOV = 45;
const SELECT_COLOR = new THREE.Color("#3d8bfd");
const FINDING_COLOR = new THREE.Color("#ff8a00");
const CLASH = new THREE.Color(CLASH_COLOR);
const DARK_AREA_BOOST = 2;
/** The area slabs' opacity factor in the dark theme's realistic look (lit by the sun, tone mapped). */
export const DARK_REAL_AREA_DAMP = 0.15;

/**
 * A plain mesh with the instances of *mesh* baked in: each instance's geometry moved by its
 * matrix and painted with its colour as vertex colours, on a copy of its material. The mesh's
 * own transform and name carry over (`:instanced` becomes `:merged`).
 */
export function deinstance(mesh: THREE.InstancedMesh): THREE.Mesh {
  const matrix = new THREE.Matrix4();
  const color = new THREE.Color(1, 1, 1);
  const parts: THREE.BufferGeometry[] = [];
  for (let i = 0; i < mesh.count; i++) {
    mesh.getMatrixAt(i, matrix);
    if (mesh.instanceColor) mesh.getColorAt(i, color);
    const g = mesh.geometry.clone().applyMatrix4(matrix);
    const n = g.getAttribute("position").count;
    const colors = new Float32Array(n * 3);
    for (let v = 0; v < n; v++) colors.set([color.r, color.g, color.b], v * 3);
    g.setAttribute("color", new THREE.Float32BufferAttribute(colors, 3));
    parts.push(g);
  }
  const merged = (parts.length ? mergeGeometries(parts, false) : null) ?? new THREE.BufferGeometry();
  for (const g of parts) g.dispose();
  const source = Array.isArray(mesh.material) ? mesh.material[0]! : mesh.material;
  const material = source.clone() as THREE.MeshStandardMaterial;
  material.vertexColors = true;
  material.color.set(0xffffff);
  const plain = new THREE.Mesh(merged, material);
  plain.name = mesh.name.replace(":instanced", ":merged");
  plain.position.copy(mesh.position);
  plain.quaternion.copy(mesh.quaternion);
  plain.scale.copy(mesh.scale);
  plain.renderOrder = mesh.renderOrder;
  return plain;
}

const LOD_NAMES = ["", ":envelope", ":detail"];
/** Within this distance of the camera (m) the detail (LOD 2) parts draw in `auto` detail. */
export const DETAIL_DISTANCE = 90;
/** Detail parts are batched by plan cells of this size (m), so they switch per neighbourhood. */
export const DETAIL_CELL = 32;
/** Repeated parts are instanced once there are this many of one shape in a batch. */
export const INSTANCE_MIN = 8;

/** Roughness and metalness by material hint. */
const SURFACE: Record<string, [number, number]> = {
  shell: [0.55, 0.2],
  steel: [0.5, 0.45],
  casing: [0.5, 0.3],
  motor: [0.6, 0.2],
  plates: [0.5, 0.3],
  pipe: [0.4, 0.35],
  insulation: [0.9, 0],
  insulation_personnel: [0.9, 0],
  nozzle: [0.4, 0.4],
  grating: [0.7, 0.3],
  stair: [0.6, 0.2],
  wall: [0.8, 0.05],
  zone: [1, 0],
  envelope: [1, 0],
  inline: [0.45, 0.3],
  area: [1, 0],
  road: [0.95, 0],
  building: [0.85, 0.05],
  handrail: [0.5, 0.3],
  cage: [0.5, 0.3],
  cladding: [0.85, 0.05],
  fire_wall: [0.95, 0],
  concrete: [0.95, 0],
  painted: [0.55, 0.2],
  stainless: [0.3, 0.7],
  galvanised: [0.55, 0.5],
  insulation_jacket: [0.5, 0.5],
  guard: [0.5, 0.2],
  flange: [0.4, 0.45],
  sleeve: [0.5, 0.2],
  tray_power: [0.55, 0.5],
  tray_instrument: [0.55, 0.5],
  junction_box: [0.5, 0.3],
  ahu: [0.55, 0.35],
  duct_supply: [0.5, 0.5],
  duct_extract: [0.5, 0.5],
  duct_outdoor: [0.5, 0.5],
  duct_exhaust: [0.5, 0.5],
  grille_supply: [0.6, 0.3],
  grille_extract: [0.6, 0.3],
};
/** Colour of a selected item's route (a cable's way). */
const ROUTE_COLOR = new THREE.Color("#d946ef");

// ---------------------------------------------------------------------------------------------
// Geometry: shared unit primitives, cloned and transformed into the batches.

const unitCache = new Map<string, THREE.BufferGeometry>();

function unit(key: string, make: () => THREE.BufferGeometry): THREE.BufferGeometry {
  let g = unitCache.get(key);
  if (!g) {
    g = make();
    g.deleteAttribute("uv");
    unitCache.set(key, g);
  }
  return g;
}

function segmentsFor(radius: number): number {
  return radius > 1 ? 40 : radius > 0.3 ? 28 : radius > 0.08 ? 16 : 10;
}

const Y = new THREE.Vector3(0, 1, 0);
const tmpA = new THREE.Vector3();
const tmpB = new THREE.Vector3();
const tmpQ = new THREE.Quaternion();
const tmpM = new THREE.Matrix4();
const tmpS = new THREE.Vector3();

/** The coordinates of `v`, rounded to `1 / per` (`per` 100: centimetres). */
function rounded(v: THREE.Vector3, per: number): Vec3 {
  return [Math.round(v.x * per) / per, Math.round(v.y * per) / per, Math.round(v.z * per) / per];
}

/** A matrix that maps the unit +y axis onto `start -> end` with cross-section scale (sx, sz). */
function alongMatrix(start: Vec3, end: Vec3, sx: number, sz: number): THREE.Matrix4 | null {
  tmpA.set(...start);
  tmpB.set(...end).sub(tmpA);
  const len = tmpB.length();
  if (len < 1e-9) return null;
  tmpQ.setFromUnitVectors(Y, tmpB.clone().divideScalar(len));
  tmpS.set(sx, len, sz);
  const mid = tmpA.clone().addScaledVector(tmpB, 0.5);
  return tmpM.clone().compose(mid, tmpQ, tmpS);
}

/** The geometry of one primitive in the site frame, or null for a degenerate one. */
export function primGeometry(prim: Prim): THREE.BufferGeometry | null {
  switch (prim.kind) {
    case "box": {
      const g = unit("box", () => new THREE.BoxGeometry(1, 1, 1)).clone();
      g.applyMatrix4(
        new THREE.Matrix4().compose(
          new THREE.Vector3(...prim.centre),
          new THREE.Quaternion().setFromAxisAngle(new THREE.Vector3(0, 0, 1), prim.rotationZ),
          new THREE.Vector3(Math.max(prim.size[0], 1e-4), Math.max(prim.size[1], 1e-4), Math.max(prim.size[2], 1e-4)),
        ),
      );
      return g;
    }
    case "cylinder": {
      const r = Math.max(prim.radius, prim.radiusEnd, 1e-4);
      const n = segmentsFor(r);
      const ratio = Math.round((prim.radiusEnd / r) * 100) / 100;
      const bottom = Math.round((prim.radius / r) * 100) / 100;
      const g = unit(`cyl:${n}:${bottom}:${ratio}`, () => new THREE.CylinderGeometry(ratio, bottom, 1, n, 1, false)).clone();
      const m = alongMatrix(prim.start, prim.end, r, r);
      if (!m) return null;
      g.applyMatrix4(m);
      return g;
    }
    case "cap": {
      const n = segmentsFor(prim.radius);
      const g = unit(`cap:${n}`, () => new THREE.SphereGeometry(1, n, Math.max(4, n / 4), 0, Math.PI * 2, 0, Math.PI / 2)).clone();
      const axis = new THREE.Vector3(...prim.axis).normalize();
      g.applyMatrix4(
        new THREE.Matrix4().compose(new THREE.Vector3(...prim.centre), new THREE.Quaternion().setFromUnitVectors(Y, axis), new THREE.Vector3(prim.radius, Math.max(prim.depth, 1e-4), prim.radius)),
      );
      return g;
    }
    case "ellipsoid": {
      const n = segmentsFor(Math.max(...prim.radii));
      const g = unit(`sphere:${n}`, () => new THREE.SphereGeometry(1, n, Math.max(6, n / 2))).clone();
      g.applyMatrix4(
        new THREE.Matrix4().compose(
          new THREE.Vector3(...prim.centre),
          new THREE.Quaternion().setFromAxisAngle(new THREE.Vector3(0, 0, 1), prim.rotationZ),
          new THREE.Vector3(...prim.radii),
        ),
      );
      return g;
    }
    case "elbow": {
      const curve = new THREE.QuadraticBezierCurve3(new THREE.Vector3(...prim.start), new THREE.Vector3(...prim.corner), new THREE.Vector3(...prim.end));
      const g = new THREE.TubeGeometry(curve, 8, prim.radius, segmentsFor(prim.radius), false);
      g.deleteAttribute("uv");
      return g;
    }
    case "beam": {
      const g = unit("box", () => new THREE.BoxGeometry(1, 1, 1)).clone();
      const m = alongMatrix(prim.start, prim.end, prim.width, prim.depth);
      if (!m) return null;
      g.applyMatrix4(m);
      return g;
    }
    case "annulus": {
      if (!(prim.outer > prim.inner) || !(prim.depth > 0)) return null;
      const shape = new THREE.Shape();
      const full = !prim.arc || (((prim.arc[1] - prim.arc[0]) % 360) + 360) % 360 === 0;
      if (full) {
        shape.absarc(0, 0, prim.outer, 0, Math.PI * 2, false);
        if (prim.inner > 0) {
          const hole = new THREE.Path();
          hole.absarc(0, 0, prim.inner, 0, Math.PI * 2, true);
          shape.holes.push(hole);
        }
      } else {
        const a0 = (prim.arc![0] * Math.PI) / 180;
        let a1 = (prim.arc![1] * Math.PI) / 180;
        while (a1 <= a0) a1 += Math.PI * 2;
        shape.absarc(0, 0, prim.outer, a0, a1, false);
        shape.absarc(0, 0, prim.inner, a1, a0, true);
        shape.closePath();
      }
      const g = new THREE.ExtrudeGeometry(shape, { depth: prim.depth, bevelEnabled: false, curveSegments: 32 });
      g.deleteAttribute("uv");
      g.translate(prim.centre[0], prim.centre[1], prim.centre[2] - prim.depth);
      return g;
    }
    case "torus": {
      if (!(prim.radius > 0) || !(prim.tube > 0)) return null;
      let span = Math.PI * 2;
      let from = 0;
      if (prim.arc) {
        const deg = (((prim.arc[1] - prim.arc[0]) % 360) + 360) % 360;
        if (deg > 0) {
          span = (deg * Math.PI) / 180;
          from = (prim.arc[0] * Math.PI) / 180;
        }
      }
      const tubular = Math.max(6, Math.ceil((segmentsFor(prim.radius + prim.tube) * 1.5 * span) / (Math.PI * 2)));
      const g = new THREE.TorusGeometry(prim.radius, prim.tube, segmentsFor(prim.tube), tubular, span);
      g.deleteAttribute("uv");
      if (from) g.rotateZ(from);
      const [u, v] = ringBasis(prim.axis, prim.ref);
      const m = new THREE.Matrix4().makeBasis(new THREE.Vector3(...u), new THREE.Vector3(...v), new THREE.Vector3(...prim.axis).normalize());
      m.setPosition(...prim.centre);
      g.applyMatrix4(m);
      return g;
    }
    case "frustum": {
      const c = frustumCorners(prim);
      if (Math.hypot(prim.end[0] - prim.start[0], prim.end[1] - prim.start[1], prim.end[2] - prim.start[2]) < 1e-9) return null;
      const tris: number[] = [];
      const tri = (a: number, b: number, d: number) => tris.push(...c[a]!, ...c[b]!, ...c[d]!);
      // Start face (facing back along the axis), end face, then the four sides.
      tri(0, 2, 1);
      tri(0, 3, 2);
      tri(4, 5, 6);
      tri(4, 6, 7);
      for (let i = 0; i < 4; i++) {
        const j = (i + 1) % 4;
        tri(i, j, j + 4);
        tri(i, j + 4, i + 4);
      }
      const g = new THREE.BufferGeometry();
      g.setAttribute("position", new THREE.Float32BufferAttribute(tris, 3));
      g.computeVertexNormals();
      return g;
    }
  }
}

/**
 * A repeated primitive as a shared unit geometry and its transform, for instancing: boxes, beams,
 * cylinders and spheres (null for the rest, which are merged).
 */
export function primInstance(prim: Prim): { key: string; geometry: () => THREE.BufferGeometry; matrix: THREE.Matrix4 } | null {
  switch (prim.kind) {
    case "box":
      return {
        key: "box",
        geometry: () => unit("box", () => new THREE.BoxGeometry(1, 1, 1)),
        matrix: new THREE.Matrix4().compose(
          new THREE.Vector3(...prim.centre),
          new THREE.Quaternion().setFromAxisAngle(new THREE.Vector3(0, 0, 1), prim.rotationZ),
          new THREE.Vector3(Math.max(prim.size[0], 1e-4), Math.max(prim.size[1], 1e-4), Math.max(prim.size[2], 1e-4)),
        ),
      };
    case "beam": {
      const m = alongMatrix(prim.start, prim.end, prim.width, prim.depth);
      return m ? { key: "box", geometry: () => unit("box", () => new THREE.BoxGeometry(1, 1, 1)), matrix: m } : null;
    }
    case "cylinder": {
      const r = Math.max(prim.radius, prim.radiusEnd, 1e-4);
      const n = segmentsFor(r);
      const ratio = Math.round((prim.radiusEnd / r) * 100) / 100;
      const bottom = Math.round((prim.radius / r) * 100) / 100;
      const key = `cyl:${n}:${bottom}:${ratio}`;
      const m = alongMatrix(prim.start, prim.end, r, r);
      return m ? { key, geometry: () => unit(key, () => new THREE.CylinderGeometry(ratio, bottom, 1, n, 1, false)), matrix: m } : null;
    }
    case "ellipsoid": {
      const n = segmentsFor(Math.max(...prim.radii));
      const key = `sphere:${n}`;
      return {
        key,
        geometry: () => unit(key, () => new THREE.SphereGeometry(1, n, Math.max(6, n / 2))),
        matrix: new THREE.Matrix4().compose(new THREE.Vector3(...prim.centre), new THREE.Quaternion().setFromAxisAngle(new THREE.Vector3(0, 0, 1), prim.rotationZ), new THREE.Vector3(...prim.radii)),
      };
    }
    default:
      return null;
  }
}

/** Whether a mesh is drawn instanced when its shape repeats: detail parts and handrails. */
export function instanceable(m: Pick<MeshSpec, "lod" | "material" | "prim">): boolean {
  if (m.material === "grating") return false;
  return ((m.lod ?? 1) >= 2 || m.material === "handrail") && (m.prim.kind === "box" || m.prim.kind === "beam" || m.prim.kind === "cylinder" || m.prim.kind === "ellipsoid");
}

/** The plan cell of a detail mesh, by its item's centre (so an item's detail switches as one). */
export function detailCell(bounds: Box3 | undefined, cell = DETAIL_CELL): string {
  if (!bounds) return "0,0";
  return `${Math.floor((bounds.min[0] + bounds.max[0]) / 2 / cell)},${Math.floor((bounds.min[1] + bounds.max[1]) / 2 / cell)}`;
}

/**
 * Planar texture coordinates from the site x and y (gratings), `pitch` metres a repeat; the
 * edges (faces that do not face up or down) get a point on a bar, so they stay solid.
 */
function planarUv(g: THREE.BufferGeometry, pitch: number): void {
  const pos = g.getAttribute("position") as THREE.BufferAttribute;
  const normal = g.getAttribute("normal") as THREE.BufferAttribute | undefined;
  const uv = new Float32Array(pos.count * 2);
  for (let i = 0; i < pos.count; i++) {
    const edge = normal !== undefined && Math.abs(normal.getZ(i)) < 0.5;
    uv[i * 2] = edge ? 0.01 : pos.getX(i) / pitch;
    uv[i * 2 + 1] = edge ? 0.01 : pos.getY(i) / pitch;
  }
  g.setAttribute("uv", new THREE.BufferAttribute(uv, 2));
}

interface Range {
  /** First vertex of the source mesh in the batch (an instanced batch: its instance). */
  start: number;
  count: number;
  spec: MeshSpec;
}

interface Batch {
  mesh: THREE.Mesh<THREE.BufferGeometry, THREE.MeshStandardMaterial> | THREE.InstancedMesh<THREE.BufferGeometry, THREE.MeshStandardMaterial>;
  layer: LayerId;
  material: string;
  ranges: Range[];
  baseOpacity: number;
  instanced: boolean;
  /** Level of detail: 0 always drawn, 1 the envelope (from afar), 2 the detail (close up). */
  lod: number;
  /** Plan cell of an envelope or detail batch ({@link detailCell}). */
  cell: string;
  /** Outlines of a merged batch (equipment and buildings). */
  edges: THREE.LineSegments | null;
}

/** The range (source mesh) a vertex of a batch belongs to, by binary search. */
export function rangeOf(ranges: { start: number; count: number }[], vertex: number): number {
  let lo = 0;
  let hi = ranges.length - 1;
  while (lo <= hi) {
    const mid = (lo + hi) >> 1;
    const r = ranges[mid]!;
    if (vertex < r.start) hi = mid - 1;
    else if (vertex >= r.start + r.count) lo = mid + 1;
    else return mid;
  }
  return -1;
}

export function createLayoutRenderer(container: HTMLElement, spec: SceneSpec, options: RendererOptions): LayoutRenderer {
  const width = () => Math.max(container.clientWidth, 1);
  const height = () => Math.max(container.clientHeight, 1);

  const renderer = new THREE.WebGLRenderer({ antialias: true, preserveDrawingBuffer: false });
  renderer.setPixelRatio(Math.min(window.devicePixelRatio || 1, 2));
  // Counted per frame in draw(): the realistic look renders several passes.
  renderer.info.autoReset = false;
  renderer.setSize(width(), height());
  renderer.domElement.className = "layout-canvas";
  container.appendChild(renderer.domElement);

  const labelRenderer = new CSS2DRenderer();
  labelRenderer.setSize(width(), height());
  labelRenderer.domElement.className = "layout-labels";
  container.appendChild(labelRenderer.domElement);

  const scene = new THREE.Scene();
  const span = Math.max(spec.bounds.max[0] - spec.bounds.min[0], spec.bounds.max[1] - spec.bounds.min[1], 10);
  const perspective = new THREE.PerspectiveCamera(FOV, width() / height(), 0.1, span * 12);
  perspective.up.set(0, 0, 1);
  // The plan (Top) view is orthographic, so tall items do not lean away from the centre.
  const ortho = new THREE.OrthographicCamera(-1, 1, 1, -1, 0.1, span * 12);
  ortho.up.set(0, 0, 1);
  let camera: THREE.PerspectiveCamera | THREE.OrthographicCamera = perspective;
  // What the named views frame: the plant, or the whole site for the `site` view.
  let frameBounds = spec.plantBounds;
  const fitOrtho = () => {
    const { halfWidth, halfHeight } = planFrame(frameBounds, width() / height());
    ortho.left = -halfWidth;
    ortho.right = halfWidth;
    ortho.top = halfHeight;
    ortho.bottom = -halfHeight;
    ortho.updateProjectionMatrix();
  };

  const hemi = new THREE.HemisphereLight(0xffffff, 0x667788, 1.6);
  scene.add(hemi);
  const sun = new THREE.DirectionalLight(0xffffff, 1.4);
  const SUN_DIRECTION = new THREE.Vector3(-0.6, -0.9, 1.4).normalize();
  sun.position.copy(SUN_DIRECTION).multiplyScalar(span);
  scene.add(sun);
  scene.add(sun.target);
  sun.shadow.mapSize.set(4096, 4096);
  sun.shadow.radius = 3;

  const disposables: { dispose(): void }[] = [];
  const track = <T extends { dispose(): void }>(thing: T): T => {
    disposables.push(thing);
    return thing;
  };

  // Ground and site grid (not exported, not part of any layer).
  const groundWidth = spec.site?.width ?? span;
  const groundDepth = spec.site?.depth ?? span;
  const groundMaterial = track(new THREE.MeshLambertMaterial({ color: options.theme.ground }));
  
  const ground = new THREE.Mesh(track(new THREE.PlaneGeometry(groundWidth, groundDepth)), groundMaterial);
  ground.position.set(
    spec.site ? groundWidth / 2 : (spec.bounds.min[0] + spec.bounds.max[0]) / 2,
    spec.site ? groundDepth / 2 : (spec.bounds.min[1] + spec.bounds.max[1]) / 2,
    -0.01,
  );
  ground.name = "ground";
  ground.receiveShadow = true;
  scene.add(ground);
  let gridHelper: THREE.LineSegments | null = null;
  const gridOrigin: [number, number] = [ground.position.x - groundWidth / 2, ground.position.y - groundDepth / 2];
  function addGrid(color: string): void {
    if (gridHelper) {
      scene.remove(gridHelper);
      gridHelper.geometry.dispose();
      (gridHelper.material as THREE.Material).dispose();
    }
    const points: number[] = [];
    for (const [a, b] of siteGrid(groundWidth, groundDepth))
      points.push(gridOrigin[0] + a[0], gridOrigin[1] + a[1], -0.005, gridOrigin[0] + b[0], gridOrigin[1] + b[1], -0.005);
    const geometry = new THREE.BufferGeometry();
    geometry.setAttribute("position", new THREE.Float32BufferAttribute(points, 3));
    gridHelper = new THREE.LineSegments(geometry, new THREE.LineBasicMaterial({ color, transparent: true, opacity: 0.35 }));
    gridHelper.name = "grid";
    scene.add(gridHelper);
  }
  addGrid(options.theme.grid);

  const world = new THREE.Group();
  world.name = "plant";
  scene.add(world);
  const groups = new Map<string, THREE.Group>();
  const group = (layer: string): THREE.Group => {
    let g = groups.get(layer);
    if (!g) {
      g = new THREE.Group();
      g.name = layer;
      groups.set(layer, g);
      world.add(g);
    }
    return g;
  };

  // Batches: one merged mesh per layer, material and opacity (detail: also per plan cell), and
  // one instanced mesh per repeated shape among the detail parts and handrails.
  const batches: Batch[] = [];
  const cellSpheres = new Map<string, THREE.Sphere>();
  const rangesByItem = new Map<string, { batch: Batch; range: Range }[]>();
  const grating = gratingTexture();
  track(grating);
  function makeMaterial(material: string, opacity: number, vertexColors: boolean): THREE.MeshStandardMaterial {
    const [roughness, metalness] = SURFACE[material] ?? [0.6, 0.15];
    const transparent = opacity < 1;
    return track(
      new THREE.MeshStandardMaterial({
        vertexColors,
        roughness,
        metalness,
        transparent,
        opacity,
        depthWrite: !transparent,
        side: transparent ? THREE.DoubleSide : THREE.FrontSide,
      }),
    );
  }
  function addBatch(batch: Batch): void {
    const { mesh, layer } = batch;
    mesh.userData = { batch: batches.length };
    if (batch.baseOpacity < 1) mesh.renderOrder = layer === "zones" ? 3 : 2;
    batches.push(batch);
    group(layer).add(mesh);
    for (const range of batch.ranges) {
      const list = rangesByItem.get(range.spec.item) ?? [];
      list.push({ batch, range });
      rangesByItem.set(range.spec.item, list);
    }
  }
  {
    const buckets = new Map<string, MeshSpec[]>();
    const cellBoxes = new Map<string, THREE.Box3>();
    const instancedBuckets = new Map<string, { spec: MeshSpec; matrix: THREE.Matrix4; geometry: () => THREE.BufferGeometry }[]>();
    for (const m of spec.meshes) {
      const lod = m.lod === 2 ? 2 : m.lod === 1 ? 1 : 0;
      const cell = lod ? detailCell(spec.itemBounds.get(m.item)) : "";
      if (lod) {
        const box = spec.itemBounds.get(m.item);
        if (box) cellBoxes.set(cell, (cellBoxes.get(cell) ?? new THREE.Box3()).union(new THREE.Box3(new THREE.Vector3(...box.min), new THREE.Vector3(...box.max))));
      }
      const base = `${m.layer}|${m.material}|${m.opacity}|${lod}|${cell}`;
      const inst = instanceable(m) ? primInstance(m.prim) : null;
      if (inst) {
        const key = `${base}|${inst.key}`;
        const list = instancedBuckets.get(key) ?? [];
        list.push({ spec: m, matrix: inst.matrix, geometry: inst.geometry });
        instancedBuckets.set(key, list);
        continue;
      }
      const list = buckets.get(base) ?? [];
      list.push(m);
      buckets.set(base, list);
    }
    // Too few of a shape to instance: merged with the rest of their bucket.
    for (const [key, list] of instancedBuckets) {
      if (list.length >= INSTANCE_MIN) continue;
      const base = key.split("|").slice(0, 5).join("|");
      buckets.set(base, [...(buckets.get(base) ?? []), ...list.map((x) => x.spec)]);
      instancedBuckets.delete(key);
    }
    // Merge in chunks so no single buffer gets huge (and index stays well inside 32 bits).
    const CHUNK = 4000;
    for (const [key, list] of buckets) {
      const [layer, material, opacityText, lodText, cell] = key.split("|") as [LayerId, string, string, string, string];
      const opacity = Number(opacityText);
      const lod = Number(lodText);
      for (let c = 0; c < list.length; c += CHUNK) {
        const geometries: THREE.BufferGeometry[] = [];
        const ranges: Range[] = [];
        let vertex = 0;
        for (const m of list.slice(c, c + CHUNK)) {
          const g = primGeometry(m.prim);
          if (!g) continue;
          if (!g.index) g.setIndex([...Array(g.attributes.position!.count).keys()]);
          const count = g.attributes.position!.count;
          ranges.push({ start: vertex, count, spec: m });
          vertex += count;
          geometries.push(g);
        }
        if (!geometries.length) continue;
        const merged = mergeGeometries(geometries, false);
        for (const g of geometries) g.dispose();
        if (!merged) continue;
        merged.setAttribute("color", new THREE.Float32BufferAttribute(new Float32Array(vertex * 3), 3));
        if (material === "grating") planarUv(merged, GRATING_PITCH);
        merged.computeBoundingSphere();
        const mesh = new THREE.Mesh(track(merged), makeMaterial(material, opacity, true));
        mesh.name = `${layer}:${material}${LOD_NAMES[lod]}`;
        // Outlines on equipment and buildings, as before the model (not on the detail).
        let edges: THREE.LineSegments | null = null;
        if ((layer === "equipment" || layer === "buildings") && opacity >= 0.15 && lod < 2) {
          edges = new THREE.LineSegments(track(new THREE.EdgesGeometry(merged, 30)), track(new THREE.LineBasicMaterial({ color: 0x1d2127, transparent: true, opacity: 0.25 })));
          edges.name = `${layer}:${material}:edges`;
          group(layer).add(edges);
        }
        addBatch({ mesh, layer, material, ranges, baseOpacity: opacity, instanced: false, lod, cell, edges });
      }
    }
    for (const [key, list] of instancedBuckets) {
      const [layer, material, opacityText, lodText, cell] = key.split("|") as [LayerId, string, string, string, string];
      const opacity = Number(opacityText);
      const lod = Number(lodText);
      const mesh = new THREE.InstancedMesh(list[0]!.geometry(), makeMaterial(material, opacity, false), list.length);
      const ranges: Range[] = [];
      list.forEach((x, i) => {
        mesh.setMatrixAt(i, x.matrix);
        mesh.setColorAt(i, new THREE.Color(x.spec.color));
        ranges.push({ start: i, count: 1, spec: x.spec });
      });
      mesh.instanceMatrix.needsUpdate = true;
      mesh.computeBoundingSphere();
      mesh.computeBoundingBox();
      mesh.name = `${layer}:${material}:instanced${LOD_NAMES[lod]}`;
      track({ dispose: () => mesh.dispose() });
      addBatch({ mesh, layer, material, ranges, baseOpacity: opacity, instanced: true, lod, cell, edges: null });
    }
    for (const [cell, box] of cellBoxes) cellSpheres.set(cell, box.getBoundingSphere(new THREE.Sphere()));
  }
  /** Envelope and detail batches, switched by their cell's distance from the camera. */
  const lodBatches = batches.filter((b) => b.lod > 0);
  const detailCount = batches.filter((b) => b.lod === 2).length;

  // Line sets that are not drawn as members (site outline, north arrow, scale bar) and model edges.
  for (const set of [...spec.lines.filter((l) => !l.members), ...spec.edges.map((e) => ({ ...e, clash: false }))]) {
    const points: number[] = [];
    for (const [a, b] of set.segments) points.push(...a, ...b);
    const geometry = track(new THREE.BufferGeometry());
    geometry.setAttribute("position", new THREE.Float32BufferAttribute(points, 3));
    const lines = new THREE.LineSegments(geometry, track(new THREE.LineBasicMaterial({ color: set.color })));
    lines.name = set.key;
    group(set.layer).add(lines);
  }

  // Labels, children of their item's group so a hidden layer hides them too.
  interface Label {
    obj: CSS2DObject;
    item: string | null;
    toggle: string | null;
    position: Vec3;
    priority: number;
    marker: boolean;
    /** Shown by its toggle and the section box (before decluttering). */
    base: boolean;
    /** Measured size in px, once it has been on screen. */
    size: [number, number] | null;
    estimate: [number, number];
  }
  const labels: Label[] = [];
  for (const label of spec.labels) {
    const el = document.createElement("div");
    el.className = `layout-label ${label.style}${label.clash ? " clash" : ""}`;
    el.textContent = label.text;
    if (label.item) el.dataset.item = label.item;
    const pick = label.item;
    if (pick) {
      el.addEventListener("pointerdown", (event) => event.stopPropagation());
      el.addEventListener("click", (event) => {
        event.stopPropagation();
        options.onPick(pick);
      });
    }
    const obj = new CSS2DObject(el);
    obj.position.set(...label.position);
    obj.center.set(0.5, label.style === "marker" ? 0 : 1);
    group(label.layer).add(obj);
    labels.push({
      obj,
      item: label.item,
      toggle: label.toggle,
      position: label.position,
      priority: label.priority ?? 0,
      marker: label.style === "marker",
      base: true,
      size: null,
      // 11 px type: about 6.7 px a character, plus padding and border.
      estimate: [label.text.length * 6.7 + 12, 17],
    });
  }
  const labelToggles: Record<string, boolean> = { labels: true, lines: true, names: true };
  /** Items whose labels always show: the selection, its related objects and a finding's items. */
  let pinned = new Set<string>();
  let section: Box3 | null = null;
  const plantSpan = Math.max(spec.plantBounds.max[0] - spec.plantBounds.min[0], spec.plantBounds.max[1] - spec.plantBounds.min[1], spec.plantBounds.max[2] - spec.plantBounds.min[2], 10);
  function updateLabels(): void {
    for (const l of labels) {
      const inSection =
        !section ||
        (l.position[0] >= section.min[0] && l.position[0] <= section.max[0] && l.position[1] >= section.min[1] && l.position[1] <= section.max[1] && l.position[2] >= section.min[2] - 1 && l.position[2] <= section.max[2] + 1);
      const on = l.toggle ? labelToggles[l.toggle] !== false : true;
      l.base = (on || (l.item !== null && pinned.has(l.item))) && inSection;
    }
  }
  function layerVisible(obj: THREE.Object3D): boolean {
    for (let o: THREE.Object3D | null = obj.parent; o; o = o.parent) if (!o.visible) return false;
    return true;
  }
  const projected = new THREE.Vector3();
  const worldPos = new THREE.Vector3();
  /** Hide labels that are off screen, too far or under a label that matters more. */
  function placeLabels(): void {
    const w = width();
    const h = height();
    const candidates: ScreenLabel[] = [];
    const fades = new Map<number, number>();
    // An orthographic view has no distance: use the one a perspective view of the same scale would.
    const orthoDistance = camera === ortho ? (ortho.top - ortho.bottom) / ortho.zoom / 2 / Math.tan(((FOV / 2) * Math.PI) / 180) : 0;
    labels.forEach((l, id) => {
      if (!l.base || !layerVisible(l.obj)) {
        l.obj.visible = false;
        return;
      }
      worldPos.set(...l.position);
      projected.copy(worldPos).project(camera);
      if (projected.z < -1 || projected.z > 1 || Math.abs(projected.x) > 1.1 || Math.abs(projected.y) > 1.1) {
        l.obj.visible = false;
        return;
      }
      const isPinned = l.item !== null && pinned.has(l.item);
      const distance = camera === ortho ? orthoDistance : camera.position.distanceTo(worldPos);
      const range = labelRange(l.marker ? 100 : l.priority, plantSpan);
      const fade = isPinned ? 1 : distanceFade(distance, range.near, range.far);
      if (fade <= 0.05) {
        l.obj.visible = false;
        return;
      }
      fades.set(id, fade);
      const [lw, lh] = l.size ?? l.estimate;
      const sx = ((projected.x + 1) / 2) * w;
      const sy = ((1 - projected.y) / 2) * h;
      const y0 = l.marker ? sy : sy - lh;
      candidates.push({ id, x0: sx - lw / 2, x1: sx + lw / 2, y0, y1: y0 + lh, priority: l.marker ? 100 : l.priority, pinned: isPinned, depth: distance });
    });
    const kept = declutter(candidates);
    for (const c of candidates) {
      const l = labels[c.id]!;
      l.obj.visible = kept.has(c.id);
      const fade = fades.get(c.id) ?? 1;
      l.obj.element.style.opacity = fade < 1 ? fade.toFixed(2) : "";
    }
  }
  function measureLabels(): void {
    for (const l of labels)
      if (!l.size && l.obj.visible && l.obj.element.isConnected) {
        const el = l.obj.element;
        if (el.offsetWidth > 0) l.size = [el.offsetWidth, el.offsetHeight];
      }
  }

  // Measure markers and the finding box live outside the layers.
  const overlay = new THREE.Group();
  overlay.name = "overlay";
  scene.add(overlay);

  const controls = new OrbitControls<THREE.PerspectiveCamera | THREE.OrthographicCamera>(perspective, labelRenderer.domElement);
  controls.maxPolarAngle = Math.PI / 2 - 0.02;
  controls.screenSpacePanning = true;

  let frame = 0;
  let benchFrame = 0;
  let stats = { calls: 0, triangles: 0 };
  const requestRender = () => {
    if (!frame) frame = requestAnimationFrame(loop);
  };
  controls.addEventListener("change", requestRender);
  controls.addEventListener("end", () => options.onCamera?.(getCamera()));

  // -------------------------------------------------------------------------------------------
  // Colours.
  let colorMode: ColorMode = "normal";
  let surfaceLook: Look = "normal";
  let detail: Detail = "auto";
  let selected: string | null = null;
  let highlighted = new Set<string>();
  const color = new THREE.Color();
  function baseColor(m: MeshSpec): THREE.Color {
    if (colorMode === "provenance") return color.set(m.review ? REVIEW_COLOR : provenanceColor(m.source));
    if (m.clash) return color.copy(CLASH);
    if (colorMode === "class" && m.classColor) return color.set(m.classColor);
    const real = surfaceLook === "realistic" ? REAL_SURFACE[m.material]?.color : undefined;
    return color.set(real ?? m.color);
  }
  function paintRange(batch: Batch, range: Range): void {
    const c = baseColor(range.spec);
    if (range.spec.item === selected) c.lerp(SELECT_COLOR, 0.75);
    else if (highlighted.has(range.spec.item)) c.lerp(FINDING_COLOR, 0.8);
    if (batch.mesh instanceof THREE.InstancedMesh) {
      batch.mesh.setColorAt(range.start, c);
      batch.mesh.instanceColor!.needsUpdate = true;
      return;
    }
    const attr = batch.mesh.geometry.getAttribute("color") as THREE.BufferAttribute;
    const array = attr.array as Float32Array;
    for (let v = range.start; v < range.start + range.count; v++) {
      array[v * 3] = c.r;
      array[v * 3 + 1] = c.g;
      array[v * 3 + 2] = c.b;
    }
    attr.addUpdateRange(range.start * 3, range.count * 3);
    attr.needsUpdate = true;
  }
  function paintItem(item: string | null): void {
    for (const { batch, range } of rangesByItem.get(item ?? "") ?? []) paintRange(batch, range);
  }
  function paintAll(): void {
    for (const batch of batches) {
      if (batch.instanced) {
        for (const range of batch.ranges) paintRange(batch, range);
        continue;
      }
      const attr = batch.mesh.geometry.getAttribute("color") as THREE.BufferAttribute;
      attr.clearUpdateRanges();
      for (const range of batch.ranges) paintRange(batch, range);
      attr.clearUpdateRanges();
      attr.needsUpdate = true;
    }
  }
  paintAll();

  let xray = false;
  let dark = options.theme.dark;
  /** Materials, opacity and shadows of every batch for the look, x-ray and theme. */
  function applyOpacity(): void {
    const real = surfaceLook === "realistic";
    for (const batch of batches) {
      const mat = batch.mesh.material;
      const surface = real ? REAL_SURFACE[batch.material] : undefined;
      let opacity = batch.baseOpacity;
      // Realistic: jacketed insulation and gratings (cut by their alpha pattern) are solid.
      if (surface?.solid) opacity = 1;
      // Dark theme: in the normal look the area slabs are boosted to stay visible on the dark
      // ground; the realistic look's sun and tone mapping light them up, so there they are
      // damped to a tint, and the ground still reads as a dark-theme ground.
      if (batch.layer === "areas" && dark) opacity = real ? opacity * DARK_REAL_AREA_DAMP : Math.min(opacity * DARK_AREA_BOOST, 0.6);
      if (xray && opacity >= 1) opacity = 0.22;
      const transparent = opacity < 1;
      const patterned = real && batch.material === "grating" && !transparent;
      const [roughness, metalness] = surface ? [surface.roughness, surface.metalness] : (SURFACE[batch.material] ?? [0.6, 0.15]);
      mat.roughness = roughness;
      mat.metalness = metalness;
      if (mat.transparent !== transparent || (mat.alphaMap !== null) !== patterned) mat.needsUpdate = true;
      mat.opacity = opacity;
      mat.transparent = transparent;
      mat.depthWrite = !transparent;
      mat.alphaMap = patterned ? grating : null;
      mat.alphaTest = patterned ? 0.5 : 0;
      mat.side = transparent || patterned ? THREE.DoubleSide : THREE.FrontSide;
      // Solids cast shadows; they and the ground-level slabs (areas, roads) receive them.
      const ghost = batch.layer === "zones" || batch.layer === "envelopes";
      batch.mesh.castShadow = real && !transparent && !ghost && batch.layer !== "areas" && batch.layer !== "roads" && batch.layer !== "site";
      batch.mesh.receiveShadow = real && !ghost && (!transparent || batch.layer === "areas" || batch.layer === "roads");
    }
  }

  // -------------------------------------------------------------------------------------------
  // Views and camera.
  function getCamera(): CameraState {
    return {
      position: rounded(camera.position, 100),
      target: rounded(controls.target, 100),
    };
  }
  function setCamera(state: CameraState): void {
    if (nav !== "orbit") setNavigation("orbit");
    camera = perspective;
    controls.object = camera;
    camera.position.set(...state.position);
    controls.target.set(...state.target);
    controls.update();
    requestRender();
  }
  function setView(view: ViewName): void {
    if (nav !== "orbit") setNavigation("orbit");
    frameBounds = view === "site" ? spec.bounds : spec.plantBounds;
    const pose = cameraPose(view, frameBounds, FOV, width() / height());
    camera = view === "top" ? ortho : perspective;
    controls.object = camera;
    controls.maxPolarAngle = Math.PI / 2 - 0.02;
    if (view === "top") {
      fitOrtho();
      ortho.zoom = 1;
      ortho.updateProjectionMatrix();
    }
    camera.position.set(...pose.position);
    controls.target.set(...pose.target);
    controls.update();
    requestRender();
    options.onCamera?.(getCamera());
  }

  function focus(item: string): void {
    const box = spec.itemBounds.get(item);
    if (!box) return;
    if (nav !== "orbit") setNavigation("orbit");
    const centre = new THREE.Vector3((box.min[0] + box.max[0]) / 2, (box.min[1] + box.max[1]) / 2, (box.min[2] + box.max[2]) / 2);
    if (camera === ortho) {
      const aspect = width() / height();
      const { halfHeight } = planFrame(frameBounds, aspect);
      const item = planFrame(box, aspect);
      ortho.zoom = Math.min(Math.max(halfHeight / (item.halfHeight * 1.6), 0.05), 200);
      ortho.updateProjectionMatrix();
      const offset = camera.position.clone().sub(controls.target);
      controls.target.copy(centre);
      camera.position.copy(centre).add(offset);
    } else {
      const direction = camera.position.clone().sub(controls.target).normalize();
      // The whole item in view with room around it, and never closer than a few metres.
      const distance = fitDistance(box, [direction.x, direction.y, direction.z], FOV, width() / height(), 1.8);
      controls.target.copy(centre);
      camera.position.copy(centre).addScaledVector(direction, Math.max(distance, 4));
    }
    controls.update();
    requestRender();
    options.onCamera?.(getCamera());
  }

  // -------------------------------------------------------------------------------------------
  // Walk and fly.
  // Our own look controls: three's PointerLockControls assume a y-up camera, ours is z-up. The
  // pointer lock (double click) turns the view with the mouse; without it, dragging does.
  let nav: NavMode = "orbit";
  const look = {
    get isLocked() {
      return document.pointerLockElement === labelRenderer.domElement;
    },
    lock() {
      void labelRenderer.domElement.requestPointerLock?.();
    },
    unlock() {
      document.exitPointerLock?.();
    },
  };
  const keys = new Set<string>();
  let flySpeed = 8;
  let feet = 0;
  let last = 0;
  const euler = new THREE.Euler(0, 0, 0, "ZXY");

  function loop(time: number): void {
    frame = 0;
    if (nav !== "orbit") {
      const dt = last ? Math.min((time - last) / 1000, 0.1) : 0;
      last = time;
      move(dt);
      frame = requestAnimationFrame(loop);
    }
    draw();
    placeLabels();
    labelRenderer.render(scene, camera);
    measureLabels();
    stats = { calls: renderer.info.render.calls, triangles: renderer.info.render.triangles };
  }

  // -------------------------------------------------------------------------------------------
  // Drawing: detail by distance, the sun's shadow frustum, the realistic composer.
  let realism: Realism | null = null;
  let detailShown = 0;
  /** The distance a view looks from: the camera's, or for the plan view a perspective one of the same scale. */
  function viewDistance(point: THREE.Vector3): number {
    if (camera === ortho) return (ortho.top - ortho.bottom) / ortho.zoom / 2 / Math.tan(((FOV / 2) * Math.PI) / 180);
    return camera.position.distanceTo(point);
  }
  /** Detail near the camera and envelopes elsewhere (or all of one, by the detail mode); outlines with what they outline. */
  function updateDetail(): void {
    detailShown = 0;
    const near = new Map<string, boolean>();
    if (detail === "auto") for (const [cell, s] of cellSpheres) near.set(cell, viewDistance(s.center) - s.radius < DETAIL_DISTANCE);
    for (const batch of lodBatches) {
      const close = detail === "full" || (detail === "auto" && near.get(batch.cell) === true);
      batch.mesh.visible = batch.lod === 2 ? close : !close;
      if (batch.lod === 2 && close && batch.mesh.parent?.visible) detailShown++;
    }
    const real = surfaceLook === "realistic";
    for (const batch of batches) if (batch.edges) batch.edges.visible = batch.mesh.visible && !real;
  }
  const plantCentre = new THREE.Vector3(
    (spec.plantBounds.min[0] + spec.plantBounds.max[0]) / 2,
    (spec.plantBounds.min[1] + spec.plantBounds.max[1]) / 2,
    (spec.plantBounds.min[2] + spec.plantBounds.max[2]) / 2,
  );
  const plantRadius = Math.max(
    Math.hypot(spec.plantBounds.max[0] - spec.plantBounds.min[0], spec.plantBounds.max[1] - spec.plantBounds.min[1], spec.plantBounds.max[2] - spec.plantBounds.min[2]) / 2,
    10,
  );
  /** Fit the sun's shadow camera around what is looked at: the plant, or a closer neighbourhood. */
  function fitShadow(): void {
    const near = camera === perspective ? Math.min(Math.max(camera.position.distanceTo(controls.target) * 1.3, 25), plantRadius) : plantRadius;
    const centre = near < plantRadius ? controls.target : plantCentre;
    const shadowCamera = sun.shadow.camera;
    shadowCamera.left = -near;
    shadowCamera.right = near;
    shadowCamera.top = near;
    shadowCamera.bottom = -near;
    shadowCamera.near = 0.5;
    shadowCamera.far = plantRadius * 4 + near * 2;
    shadowCamera.updateProjectionMatrix();
    sun.target.position.copy(centre);
    sun.position.copy(centre).addScaledVector(SUN_DIRECTION, plantRadius * 2 + near);
    sun.target.updateMatrixWorld();
    sun.updateMatrixWorld();
    // About 1.5 texels of normal offset against acne.
    sun.shadow.normalBias = ((2 * near) / sun.shadow.mapSize.x) * 1.5;
    sun.shadow.bias = -0.0002;
  }
  function draw(): void {
    renderer.info.reset();
    updateDetail();
    if (surfaceLook === "realistic") {
      fitShadow();
      realism ??= createRealism(renderer, scene, camera, width(), height());
      scene.environment = realism.environment;
      realism.render(camera);
    } else {
      renderer.render(scene, camera);
    }
  }
  function setLook(next: Look): void {
    if (next === surfaceLook) return;
    surfaceLook = next;
    const real = surfaceLook === "realistic";
    renderer.shadowMap.enabled = real;
    renderer.shadowMap.type = THREE.PCFShadowMap;
    renderer.toneMapping = real ? THREE.NeutralToneMapping : THREE.NoToneMapping;
    sun.castShadow = real;
    sun.intensity = real ? 2.2 : 1.4;
    hemi.intensity = real ? 0.25 : 1.6;
    scene.environmentIntensity = 0.35;
    renderer.toneMappingExposure = 1;
    if (!real) scene.environment = null;
    groundMaterial.needsUpdate = true;
    applyOpacity();
    paintAll();
    requestRender();
  }

  const forward = new THREE.Vector3();
  const right = new THREE.Vector3();
  function move(dt: number): void {
    const run = keys.has("ShiftLeft") || keys.has("ShiftRight") ? 3 : 1;
    const ahead = (keys.has("KeyW") || keys.has("ArrowUp") ? 1 : 0) - (keys.has("KeyS") || keys.has("ArrowDown") ? 1 : 0);
    const side = (keys.has("KeyD") || keys.has("ArrowRight") ? 1 : 0) - (keys.has("KeyA") || keys.has("ArrowLeft") ? 1 : 0);
    perspective.getWorldDirection(forward);
    if (nav === "walk") {
      forward.z = 0;
      forward.normalize();
      right.crossVectors(forward, perspective.up).normalize();
      const step = 1.4 * run * dt;
      perspective.position.addScaledVector(forward, ahead * step).addScaledVector(right, side * step);
      feet = snapFloor(spec.floors, perspective.position.x, perspective.position.y, feet);
      perspective.position.z = feet + EYE_HEIGHT;
    } else {
      right.crossVectors(forward, perspective.up).normalize();
      const up = (keys.has("KeyE") || keys.has("Space") ? 1 : 0) - (keys.has("KeyQ") || keys.has("KeyC") ? 1 : 0);
      const step = flySpeed * run * dt;
      perspective.position.addScaledVector(forward, ahead * step).addScaledVector(right, side * step);
      perspective.position.z += up * step;
    }
  }

  const onKeyDown = (event: KeyboardEvent) => {
    if (nav === "orbit") return;
    const target = event.target;
    if (target instanceof Element && /^(INPUT|SELECT|TEXTAREA)$/.test(target.tagName)) return;
    if (event.code === "Escape") {
      setNavigation("orbit");
      options.onNavigation?.("orbit");
      return;
    }
    if (nav === "walk" && (event.code === "PageUp" || event.code === "PageDown" || event.code === "KeyE" || event.code === "KeyQ")) {
      feet = stepFloor(spec.floors, perspective.position.x, perspective.position.y, feet, event.code === "PageUp" || event.code === "KeyE" ? 1 : -1);
      perspective.position.z = feet + EYE_HEIGHT;
      event.preventDefault();
      return;
    }
    if (nav === "fly" && (event.code === "Equal" || event.code === "NumpadAdd" || event.code === "Minus" || event.code === "NumpadSubtract")) {
      setFlySpeed(flySpeed * (event.code === "Equal" || event.code === "NumpadAdd" ? 1.5 : 1 / 1.5));
      return;
    }
    keys.add(event.code);
    if (/^Arrow|^Space$|^Page/.test(event.code)) event.preventDefault();
  };
  const onKeyUp = (event: KeyboardEvent) => keys.delete(event.code);
  window.addEventListener("keydown", onKeyDown);
  window.addEventListener("keyup", onKeyUp);
  const onBlur = () => keys.clear();
  window.addEventListener("blur", onBlur);
  const onLockChange = () => {
    if (!look.isLocked) keys.clear();
  };
  document.addEventListener("pointerlockchange", onLockChange);
  function turn(dx: number, dy: number): void {
    euler.setFromQuaternion(perspective.quaternion);
    euler.z -= dx * 0.003;
    euler.x = Math.min(Math.max(euler.x - dy * 0.003, 0.05), Math.PI - 0.05);
    euler.y = 0;
    perspective.quaternion.setFromEuler(euler);
  }
  const onLockedMove = (event: MouseEvent) => {
    if (nav !== "orbit" && look.isLocked) turn(event.movementX, event.movementY);
  };
  document.addEventListener("mousemove", onLockedMove);

  // Without pointer lock (or before it), dragging looks around.
  let drag: { x: number; y: number } | null = null;
  const onLookDown = (event: PointerEvent) => {
    if (nav === "orbit" || tool === "measure") return;
    drag = { x: event.clientX, y: event.clientY };
  };
  const onLookMove = (event: PointerEvent) => {
    if (nav === "orbit" || !drag || look.isLocked) return;
    const dx = event.clientX - drag.x;
    const dy = event.clientY - drag.y;
    drag = { x: event.clientX, y: event.clientY };
    turn(dx * 1.3, dy * 1.3);
  };
  const onLookUp = () => (drag = null);
  const onWheel = (event: WheelEvent) => {
    if (nav !== "fly") return;
    event.preventDefault();
    setFlySpeed(flySpeed * (event.deltaY < 0 ? 1.25 : 0.8));
  };
  labelRenderer.domElement.addEventListener("pointerdown", onLookDown);
  window.addEventListener("pointermove", onLookMove);
  window.addEventListener("pointerup", onLookUp);
  labelRenderer.domElement.addEventListener("wheel", onWheel, { passive: false });
  const onDblClick = () => {
    if (nav !== "orbit" && !look.isLocked) {
      try {
        look.lock();
      } catch {
        // Pointer lock is optional: dragging looks around too.
      }
    }
  };
  labelRenderer.domElement.addEventListener("dblclick", onDblClick);

  function setFlySpeed(speed: number): void {
    flySpeed = Math.min(Math.max(speed, 0.5), 200);
    options.onFlySpeed?.(Math.round(flySpeed * 10) / 10);
  }

  function setNavigation(mode: NavMode): void {
    if (mode === nav) return;
    const previous = nav;
    nav = mode;
    keys.clear();
    if (mode === "orbit") {
      if (look.isLocked) look.unlock();
      controls.enabled = true;
      // Orbit about a point ahead of where the walker or flyer looks.
      perspective.getWorldDirection(forward);
      controls.target.copy(perspective.position).addScaledVector(forward, 20);
      if (controls.target.z < 0) controls.target.z = 0;
      controls.update();
      requestRender();
      options.onCamera?.(getCamera());
      return;
    }
    controls.enabled = false;
    if (camera !== perspective) {
      // From the plan view: stand where its centre was, looking north.
      perspective.position.set(controls.target.x, controls.target.y - 5, EYE_HEIGHT);
      camera = perspective;
    }
    if (mode === "walk") {
      // Down to the floor under the camera, looking level along the view direction.
      perspective.getWorldDirection(forward);
      if (previous === "orbit") {
        const t = controls.target;
        perspective.position.set(t.x - forward.x * 8, t.y - forward.y * 8, 0);
      }
      feet = snapFloor(spec.floors, perspective.position.x, perspective.position.y, previous === "fly" ? perspective.position.z - EYE_HEIGHT : 0);
      perspective.position.z = feet + EYE_HEIGHT;
      perspective.lookAt(perspective.position.x + forward.x, perspective.position.y + forward.y, perspective.position.z);
    }
    last = 0;
    if (!frame) frame = requestAnimationFrame(loop);
  }

  // -------------------------------------------------------------------------------------------
  // Picking and measuring: a click that is not the end of a drag.
  let tool: Tool = "pick";
  const raycaster = new THREE.Raycaster();
  const pointer = new THREE.Vector2();
  let down: { x: number; y: number } | null = null;
  let measureA: Vec3 | null = null;
  function clearOverlay(name: string): void {
    for (const child of [...overlay.children])
      if (child.name === name) {
        overlay.remove(child);
        child.traverse((o) => {
          const any = o as THREE.Mesh;
          any.geometry?.dispose();
          (any.material as THREE.Material | undefined)?.dispose?.();
          if (o instanceof CSS2DObject) o.element.remove();
        });
      }
  }
  function hitAt(event: PointerEvent): { item: string; point: Vec3 } | null {
    const rect = labelRenderer.domElement.getBoundingClientRect();
    if (nav !== "orbit" && look.isLocked) pointer.set(0, 0);
    else pointer.set(((event.clientX - rect.left) / rect.width) * 2 - 1, -((event.clientY - rect.top) / rect.height) * 2 + 1);
    raycaster.setFromCamera(pointer, camera);
    const visible = batches.filter((b) => b.mesh.visible && b.mesh.parent?.visible).map((b) => b.mesh);
    const hits = raycaster.intersectObjects(visible, false).filter((h) => !section || insideBox(section, h.point));
    // Prefer solid things over the translucent shells, zones and envelopes around them.
    const solid = hits.find((h) => batches[h.object.userData.batch as number]!.baseOpacity >= 1);
    const hit = solid ?? hits[0];
    if (!hit || !hit.face) return null;
    const batch = batches[hit.object.userData.batch as number]!;
    const index = batch.instanced ? (hit.instanceId ?? -1) : rangeOf(batch.ranges, hit.face.a);
    const range = batch.ranges[index];
    if (!range) return null;
    return { item: range.spec.item, point: rounded(hit.point, 1000) };
  }
  const onDown = (event: PointerEvent) => (down = { x: event.clientX, y: event.clientY });
  const onUp = (event: PointerEvent) => {
    if (!down || Math.hypot(event.clientX - down.x, event.clientY - down.y) > 4) return;
    down = null;
    const hit = hitAt(event);
    if (tool === "measure") {
      if (!hit) return;
      if (!measureA || overlay.children.some((c) => c.name === "measure-line")) {
        clearOverlay("measure");
        clearOverlay("measure-line");
        measureA = hit.point;
        overlay.add(marker(hit.point, "measure"));
        options.onMeasure?.(null);
      } else {
        const b = hit.point;
        overlay.add(marker(b, "measure"));
        const result = measure(measureA, b);
        const line = new THREE.Line(
          new THREE.BufferGeometry().setFromPoints([new THREE.Vector3(...measureA), new THREE.Vector3(...b)]),
          new THREE.LineBasicMaterial({ color: 0xff8a00, depthTest: false }),
        );
        line.name = "measure-line";
        line.renderOrder = 10;
        const el = document.createElement("div");
        el.className = "layout-label measure";
        el.textContent = `${result.distance.toFixed(2)} m`;
        const tag = new CSS2DObject(el);
        tag.position.set((measureA[0] + b[0]) / 2, (measureA[1] + b[1]) / 2, (measureA[2] + b[2]) / 2);
        line.add(tag);
        overlay.add(line);
        options.onMeasure?.({ a: measureA, b, ...result });
      }
      requestRender();
      return;
    }
    options.onPick(hit ? hit.item : null);
  };
  labelRenderer.domElement.addEventListener("pointerdown", onDown);
  labelRenderer.domElement.addEventListener("pointerup", onUp);

  function marker(p: Vec3, name: string): THREE.Mesh {
    const m = new THREE.Mesh(new THREE.SphereGeometry(Math.max(span / 600, 0.08), 12, 8), new THREE.MeshBasicMaterial({ color: 0xff8a00, depthTest: false }));
    m.position.set(...p);
    m.name = name;
    m.renderOrder = 10;
    return m;
  }

  function setTool(next: Tool): void {
    tool = next;
    if (next !== "measure") {
      clearOverlay("measure");
      clearOverlay("measure-line");
      measureA = null;
      options.onMeasure?.(null);
    }
    requestRender();
  }

  // -------------------------------------------------------------------------------------------
  function insideBox(box: Box3, p: THREE.Vector3): boolean {
    const e = 1e-6;
    return p.x >= box.min[0] - e && p.x <= box.max[0] + e && p.y >= box.min[1] - e && p.y <= box.max[1] + e && p.z >= box.min[2] - e && p.z <= box.max[2] + e;
  }

  function setSection(box: Box3 | null): void {
    section = box;
    renderer.clippingPlanes = box ? sectionPlanes(box).map((p) => new THREE.Plane(new THREE.Vector3(...p.normal), p.constant)) : [];
    updateLabels();
    requestRender();
  }

  const resize = new ResizeObserver(() => {
    perspective.aspect = width() / height();
    perspective.updateProjectionMatrix();
    fitOrtho();
    renderer.setSize(width(), height());
    labelRenderer.setSize(width(), height());
    realism?.setSize(width(), height());
    requestRender();
  });
  resize.observe(container);

  const background = new THREE.Color();
  function setTheme(theme: Theme): void {
    background.set(theme.background);
    scene.background = background;
    groundMaterial.color.set(theme.ground);
    addGrid(theme.grid);
    dark = theme.dark;
    applyOpacity();
    requestRender();
  }
  setTheme(options.theme);
  setView("iso");

  function setSelected(item: string | null): void {
    const previous = selected;
    selected = item;
    paintItem(previous);
    paintItem(item);
    for (const label of labels) label.obj.element.classList.toggle("selected", label.item === item);
    updatePinned();
    requestRender();
  }

  function setHighlighted(items: string[], box: Box3 | null = null): void {
    const previous = highlighted;
    highlighted = new Set(items);
    for (const item of previous) paintItem(item);
    for (const item of highlighted) paintItem(item);
    updatePinned();
    clearOverlay("finding-box");
    if (box) {
      const size: Vec3 = [box.max[0] - box.min[0], box.max[1] - box.min[1], box.max[2] - box.min[2]];
      const geometry = new THREE.EdgesGeometry(new THREE.BoxGeometry(Math.max(size[0], 0.05), Math.max(size[1], 0.05), Math.max(size[2], 0.05)));
      const lines = new THREE.LineSegments(geometry, new THREE.LineBasicMaterial({ color: FINDING_COLOR, depthTest: false }));
      lines.position.set((box.min[0] + box.max[0]) / 2, (box.min[1] + box.max[1]) / 2, (box.min[2] + box.max[2]) / 2);
      lines.name = "finding-box";
      lines.renderOrder = 10;
      overlay.add(lines);
    }
    requestRender();
  }

  function setRoute(paths: Vec3[][]): void {
    clearOverlay("route");
    const group = new THREE.Group();
    group.name = "route";
    // Thin tubes rather than lines (a line is one pixel whatever the zoom), drawn over the model.
    const material = new THREE.MeshBasicMaterial({ color: ROUTE_COLOR, depthTest: false, transparent: true, opacity: 0.9 });
    const geometry = new THREE.CylinderGeometry(1, 1, 1, 8, 1, false);
    const radius = Math.max(span / 1500, 0.04);
    for (const path of paths)
      for (let i = 1; i < path.length; i++) {
        const m = alongMatrix(path[i - 1]!, path[i]!, radius, radius);
        if (!m) continue;
        const tube = new THREE.Mesh(geometry, material);
        tube.applyMatrix4(m);
        tube.renderOrder = 11;
        group.add(tube);
      }
    // One geometry and material for all the tubes (clearOverlay disposes them).
    if (group.children.length) overlay.add(group);
    else {
      geometry.dispose();
      material.dispose();
    }
    requestRender();
  }

  function updatePinned(): void {
    pinned = new Set(highlighted);
    if (selected) {
      pinned.add(selected);
      for (const r of spec.items.get(selected)?.related ?? []) pinned.add(r.key);
    }
    updateLabels();
  }

  function setLayer(layer: LayerId | "labels" | "lines" | "names", visible: boolean): void {
    if (layer === "labels" || layer === "lines" || layer === "names") {
      labelToggles[layer] = visible;
      updateLabels();
    } else {
      group(layer).visible = visible;
    }
    requestRender();
  }

  async function exportGlb(): Promise<ArrayBuffer> {
    const { GLTFExporter } = await import("three/examples/jsm/exporters/GLTFExporter.js");
    const exporter = new GLTFExporter();
    // Labels are HTML, not geometry: leave them out of the file.
    const hidden: THREE.Object3D[] = [];
    world.traverse((o) => {
      if (o instanceof CSS2DObject && o.visible) {
        o.visible = false;
        hidden.push(o);
      }
    });
    // Instanced detail goes out as plain meshes with vertex colours, so the file needs no
    // extension (EXT_mesh_gpu_instancing) and keeps every part's colour.
    const swapped: { instanced: THREE.InstancedMesh; parent: THREE.Object3D; plain: THREE.Mesh }[] = [];
    world.traverseVisible((o) => {
      if (o instanceof THREE.InstancedMesh && o.parent) swapped.push({ instanced: o, parent: o.parent, plain: deinstance(o) });
    });
    for (const { instanced, parent, plain } of swapped) {
      parent.add(plain);
      instanced.visible = false;
    }
    try {
      const result = await exporter.parseAsync(world, { binary: true, onlyVisible: true });
      return result as ArrayBuffer;
    } finally {
      for (const o of hidden) o.visible = true;
      for (const { instanced, plain } of swapped) {
        instanced.visible = true;
        plain.removeFromParent();
        plain.geometry.dispose();
        (plain.material as THREE.Material).dispose();
      }
    }
  }

  return {
    setLayer,
    setView,
    setSelected,
    setHighlighted,
    setRoute,
    setTheme,
    setColorMode(mode) {
      colorMode = mode;
      paintAll();
      requestRender();
    },
    setXray(on) {
      xray = on;
      applyOpacity();
      requestRender();
    },
    setSection,
    setNavigation,
    setTool,
    setFlySpeed,
    focus,
    getCamera,
    setCamera,
    exportGlb,
    setLook,
    setDetail(next) {
      detail = next;
      requestRender();
    },
    stats: () => ({
      batches: batches.length,
      meshes: spec.meshes.length,
      instanced: batches.filter((b) => b.instanced).length,
      instances: batches.reduce((n, b) => n + (b.instanced ? b.ranges.length : 0), 0),
      detail: detailCount,
      detailShown,
      ...stats,
    }),
    benchmark(ms = 2000) {
      const saved = { position: perspective.position.clone(), target: controls.target.clone() };
      const offset = camera.position.clone().sub(controls.target);
      const axis = new THREE.Vector3(0, 0, 1);
      return new Promise((resolve) => {
        let frames = 0;
        let t0 = 0;
        let calls = 0;
        let triangles = 0;
        const step = (time: number) => {
          if (!t0) t0 = time;
          const elapsed = time - t0;
          // A full turn over the run, so every side of the plant is drawn.
          const turned = offset.clone().applyAxisAngle(axis, (elapsed / ms) * Math.PI * 2);
          camera.position.copy(controls.target).add(turned);
          camera.lookAt(controls.target);
          draw();
          calls = Math.max(calls, renderer.info.render.calls);
          triangles = Math.max(triangles, renderer.info.render.triangles);
          frames++;
          if (elapsed < ms) {
            benchFrame = requestAnimationFrame(step);
            return;
          }
          benchFrame = 0;
          if (camera === perspective) {
            perspective.position.copy(saved.position);
            controls.target.copy(saved.target);
            controls.update();
          }
          requestRender();
          resolve({ fps: Math.round(((frames - 1) / Math.max(elapsed, 1)) * 1000 * 10) / 10, frames, calls, triangles });
        };
        benchFrame = requestAnimationFrame(step);
      });
    },
    dispose() {
      if (benchFrame) cancelAnimationFrame(benchFrame);
      realism?.dispose();
      if (frame) cancelAnimationFrame(frame);
      nav = "orbit";
      resize.disconnect();
      controls.dispose();
      if (look.isLocked) look.unlock();
      document.removeEventListener("pointerlockchange", onLockChange);
      document.removeEventListener("mousemove", onLockedMove);
      window.removeEventListener("keydown", onKeyDown);
      window.removeEventListener("keyup", onKeyUp);
      window.removeEventListener("blur", onBlur);
      window.removeEventListener("pointermove", onLookMove);
      window.removeEventListener("pointerup", onLookUp);
      labelRenderer.domElement.removeEventListener("pointerdown", onLookDown);
      labelRenderer.domElement.removeEventListener("wheel", onWheel);
      labelRenderer.domElement.removeEventListener("dblclick", onDblClick);
      labelRenderer.domElement.removeEventListener("pointerdown", onDown);
      labelRenderer.domElement.removeEventListener("pointerup", onUp);
      clearOverlay("measure");
      clearOverlay("measure-line");
      clearOverlay("finding-box");
      clearOverlay("route");
      for (const thing of disposables) thing.dispose();
      if (gridHelper) {
        gridHelper.geometry.dispose();
        (gridHelper.material as THREE.Material).dispose();
      }
      renderer.dispose();
      renderer.domElement.remove();
      labelRenderer.domElement.remove();
    },
  };
}
