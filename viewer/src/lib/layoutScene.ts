/**
 * Turn the `/api/layout` payload into a plain description of the 3D scene: solids, line sets
 * and labels with positions, sizes, rotations and colours. No three.js here, so the geometry
 * rules are unit tested without WebGL; `layoutThree.ts` turns the description into objects.
 *
 * The scene uses the site frame directly (metres, x east, y north, z up); the camera's `up` is +z.
 */
import type {
  EquipmentSize,
  Finding,
  Layout,
  LayoutBuilding,
  LineRoute,
  PlacedEquipment,
  Sheet,
  XY,
} from "@/api";
import {
  buildModelScene,
  classColors,
  type Box3,
  type Floor,
  type ItemRoute,
  type LayerId,
  type MeshSpec,
  type Prim,
  pipeService,
  serviceColor,
  serviceFamily,
  type Source,
  unionBox,
  primBounds,
  zoneColor,
  PROVENANCE_COLORS,
  REVIEW_COLOR,
  DUCT_COLORS,
  PENETRATION_COLOR,
  STEEL_COLOR,
  STRUCTURE_COLORS,
  TRAY_COLORS,
} from "./layoutModel";

export { LAYERS, LAYER_TITLES, LAYERS_OFF, type ItemRoute, type LayerId, type MeshSpec, type Prim, type Box3, type Floor } from "./layoutModel";

export type Vec3 = [number, number, number];

export type ItemKind =
  | "equipment"
  | "building"
  | "area"
  | "road"
  | "rack"
  | "nozzle"
  | "envelope"
  | "pipe"
  | "inline"
  | "structure"
  | "support"
  | "platform"
  | "zone"
  | "penetration"
  | "hatch"
  | "tray"
  | "junction_box"
  | "cable"
  | "instrument"
  | "duct"
  | "hvac_unit"
  | "hvac_room";

/** What the side panel shows for a picked item. */
export interface LayoutItem {
  kind: ItemKind;
  id: string;
  title: string | null;
  /** Equipment type, area kind or level kind. */
  type: string | null;
  sheet: string | null;
  /** Repo path of the sheet's P&ID, as cheme-as-code resolved it. */
  sheetFile: string | null;
  service: string | null;
  notes: string | null;
  building: string | null;
  level: string | null;
  details: [string, string][];
  clash: boolean;
  /** Where a model object comes from, null for objects the model does not have. */
  source?: Source | null;
  /** DEXPI id to highlight on the sheet. */
  highlight?: string | null;
  /** Related item keys (an item's nozzles, a nozzle's item, a pipe's ends). */
  related?: { key: string; label: string }[];
  /** Line number of a pipe or nozzle. */
  line?: string | null;
  /** A generated proposal or fallback route to review. */
  review?: boolean;
}

export interface SolidSpec {
  /** Unique within the scene, e.g. `equipment:P-101`, `building:B1:L1`. */
  key: string;
  layer: LayerId;
  /** `cylinder` has its axis along local `axis`; `size` is the full extent per local axis. */
  shape: "box" | "cylinder" | "sphere";
  axis: "x" | "z";
  /** Centre of the solid. */
  center: Vec3;
  size: Vec3;
  /** Rotation about +z (radians), around `center`. */
  rotationZ: number;
  color: string;
  opacity: number;
  clash: boolean;
  /** The item a click on this solid selects (its `kind:id`). */
  item: string;
}

export interface LinesSpec {
  key: string;
  layer: LayerId | "site";
  color: string;
  segments: [Vec3, Vec3][];
  clash: boolean;
  item: string | null;
  /** Draw each segment as a solid steel member of this section size (m) instead of a line. */
  members?: number;
}

/** Which toggle shows a label: equipment tags, line numbers, names of areas/buildings/racks, or always (north, scale). */
export type LabelToggle = "labels" | "lines" | "names" | null;

/**
 * Which label wins where labels overlap on screen (higher first): equipment tags over the names
 * of structures, racks and buildings, over area names, over line numbers. The selection and its
 * related objects always show; markers (north arrow, scale) are never hidden.
 */
export const LABEL_PRIORITY = { marker: 100, equipment: 40, structure: 30, area: 20, line: 10 } as const;

export interface LabelSpec {
  key: string;
  /** Labels belong to their item's layer and are hidden with it. */
  layer: LayerId | "site";
  toggle: LabelToggle;
  /** `tag` (equipment), `name` (area, building, rack) or `marker` (north arrow, scale bar). */
  style: "tag" | "name" | "marker";
  text: string;
  position: Vec3;
  clash: boolean;
  item: string | null;
  /** See {@link LABEL_PRIORITY}. */
  priority: number;
}

export interface LegendEntry {
  label: string;
  color: string;
  /** The types or services a grouped row stands for (more than one, or other than the label). */
  members?: string[];
}

export interface Bounds {
  min: Vec3;
  max: Vec3;
}

export interface SceneSpec {
  site: { width: number; depth: number; name: string | null } | null;
  /** Everything: site, areas, roads and the plant. */
  bounds: Bounds;
  /** The plant itself (equipment, structures, pipes, racks, buildings), what the views frame. */
  plantBounds: Bounds;
  solids: SolidSpec[];
  lines: LinesSpec[];
  labels: LabelSpec[];
  /** `kind:id` -> item, for the side panel. */
  items: Map<string, LayoutItem>;
  /** `kind:id` of every item a clash names. */
  clashKeys: Set<string>;
  legend: Legend;
  /** Everything to draw as meshes: the solids above, steel members and the generated model. */
  meshes: MeshSpec[];
  /** Wireframe edges of model objects (envelopes, structure outlines). */
  edges: { key: string; layer: LayerId; color: string; segments: [Vec3, Vec3][]; item: string }[];
  /** Bounds per item key, for camera focus. */
  itemBounds: Map<string, Box3>;
  /** Any id a link may name (tag, DEXPI id, segment, line, nozzle) -> item key. */
  ids: Map<string, string>;
  /** Floors to walk on (building levels, decks); the ground is always one. */
  floors: Floor[];
  /** True when the scene draws the generated model, not only the placement primitives. */
  hasModel: boolean;
  /** Model sections present: counts of meshes per layer. */
  counts: Record<string, number>;
  /** What a selection marks besides itself (cable routes, a unit's ducts), by item. */
  routes: Map<string, ItemRoute>;
  /** Generated proposals to review by what they are (`stair`, `ladder`, `penetration`, ...). */
  proposals: Map<string, string[]>;
}

export interface Legend {
  areas: LegendEntry[];
  equipment: LegendEntry[];
  pipes: LegendEntry[];
  pipeClasses: LegendEntry[];
  zones: LegendEntry[];
  /** Cable trays by system, junction boxes, ducts by air system (empty without them). */
  services: LegendEntry[];
  provenance: LegendEntry[];
}

export const CLASH_COLOR = "#e5243b";
export const ROAD_COLOR = "#8d939b";
export const RACK_COLOR = "#b06a2c";
export const BUILDING_COLOR = "#7c8a9c";
export const COLUMN_COLOR = "#56606d";
export const SITE_COLOR = "#3a7d44";

export const AREA_COLORS: Record<string, string> = {
  process: "#f2a33a",
  utilities: "#3b82f6",
  storage: "#22a35a",
  road: "#9aa1a9",
  reserved: "#a066d3",
  building: "#7c8a9c",
};
export const AREA_DEFAULT_COLOR = "#9aa1a9";

/** Equipment colours by keyword in the type (DEXPI class names or plain words), with the legend's name for each group. Never red. */
export const TYPE_COLORS: [RegExp, string, string][] = [
  [/pump/, "#2f7fd8", "pumps"],
  [/compressor|blower|fan/, "#7a52d1", "compressors & blowers"],
  [/column|tower/, "#e0861a", "columns"],
  [/exchanger|cooler|heater|condenser|reboiler|evaporator/, "#9c6b1c", "heat exchangers"],
  [/reactor/, "#c0458f", "reactors"],
  [/tank|silo/, "#2c9a5a", "tanks"],
  [/vessel|drum|separator|receiver/, "#1aa39a", "vessels"],
  [/filter|strainer/, "#0ea5c6", "filters"],
  [/mixer|agitator/, "#6b8e23", "mixers"],
];

/** The legend group of an equipment type (`pumps`, `heat exchangers`), or null for one of its own. */
export function equipmentGroup(type: string | null | undefined): string | null {
  const lower = (type ?? "").toLowerCase();
  for (const [pattern, , name] of TYPE_COLORS) if (pattern.test(lower)) return name;
  return null;
}
const OTHER_COLORS: [string, ...string[]] = ["#5f7486", "#4a90b8", "#8a7f5a", "#7d6b9e", "#5d8f7a"];

/** Colour of an equipment type; unknown types get a stable colour from a small palette. */
export function equipmentColor(type: string | null | undefined): string {
  const lower = (type ?? "").toLowerCase();
  for (const [pattern, color] of TYPE_COLORS) if (pattern.test(lower)) return color;
  if (!lower) return OTHER_COLORS[0];
  let hash = 0;
  for (const ch of lower) hash = (hash * 31 + ch.charCodeAt(0)) >>> 0;
  return OTHER_COLORS[hash % OTHER_COLORS.length] ?? OTHER_COLORS[0];
}

export const deg = (d: number | null | undefined): number => ((d ?? 0) * Math.PI) / 180;

const num = (v: unknown, fallback: number): number => (typeof v === "number" && Number.isFinite(v) ? v : fallback);
const positive = (v: unknown, fallback: number): number => {
  const n = num(v, fallback);
  return n > 0 ? n : fallback;
};

/** Rotate `[x, y]` by `angle` (radians, counter-clockwise) about `about`. */
export function rotateXY([x, y]: XY, angle: number, about: XY = [0, 0]): XY {
  if (!angle) return [x, y];
  const c = Math.cos(angle);
  const s = Math.sin(angle);
  const dx = x - about[0];
  const dy = y - about[1];
  // Round away float noise so 90 degree turns land on exact coordinates.
  const r = (v: number) => Math.round(v * 1e9) / 1e9;
  return [r(about[0] + dx * c - dy * s), r(about[1] + dx * s + dy * c)];
}

export interface EquipmentGeometry {
  shape: SolidSpec["shape"];
  axis: SolidSpec["axis"];
  /** Full extents of the drawn solid along local x, y, z. */
  size: Vec3;
  /**
   * Height of the solid's bottom above the item's position, m; absent for 0. Only a horizontal
   * cylinder raised on supports has one: its overall height (`base + size[2]`) is the placement's.
   */
  base?: number;
}

const DEFAULT_EXTENT = 1;

/**
 * Geometry of a placed item from its `shape` and `size` (`[dx, dy, dz]` or
 * `{diameter, height | length}`):
 * - box: `[dx, dy, dz]`;
 * - vertical_cylinder: diameter x diameter x height (axis z); from an array, `dx` is the diameter;
 * - horizontal_cylinder: length x diameter x diameter (axis along local x, turned by rotation_deg);
 *   from an array, `dz` is the overall height (cheme-as-code sends the axis height plus the
 *   radius), so a vessel on saddles is raised by `base = dz - diameter`;
 * - sphere: diameter in every direction.
 */
export function equipmentGeometry(shape: string, size: EquipmentSize | null | undefined): EquipmentGeometry {
  const arr = Array.isArray(size) ? size : null;
  const obj = !Array.isArray(size) && size && typeof size === "object" ? size : null;
  const a = (i: number) => positive(arr?.[i], DEFAULT_EXTENT);
  switch (shape) {
    case "vertical_cylinder": {
      const d = arr ? a(0) : positive(obj?.diameter, DEFAULT_EXTENT);
      const h = arr ? a(2) : positive(obj?.height ?? obj?.length, DEFAULT_EXTENT);
      return { shape: "cylinder", axis: "z", size: [d, d, h] };
    }
    case "horizontal_cylinder": {
      const length = arr ? a(0) : positive(obj?.length ?? obj?.height, DEFAULT_EXTENT);
      const d = arr ? a(1) : positive(obj?.diameter, DEFAULT_EXTENT);
      const base = arr ? a(2) - d : 0;
      return base > 0 ? { shape: "cylinder", axis: "x", size: [length, d, d], base } : { shape: "cylinder", axis: "x", size: [length, d, d] };
    }
    case "sphere": {
      const d = arr ? a(0) : positive(obj?.diameter, DEFAULT_EXTENT);
      return { shape: "sphere", axis: "z", size: [d, d, d] };
    }
    default: {
      if (arr) return { shape: "box", axis: "z", size: [a(0), a(1), a(2)] };
      const d = positive(obj?.diameter, DEFAULT_EXTENT);
      return { shape: "box", axis: "z", size: [d, d, positive(obj?.height ?? obj?.length, DEFAULT_EXTENT)] };
    }
  }
}

const isClash = (f: Finding) => /(^|\.)layout-clash$/.test(f.rule);

/**
 * `kind:id` of every item that clashes. cheme-as-code flags each item (`clash: true`); without a flag
 * (an older cheme-as-code) an item clashes when a `layout-clash` finding names its id. Each kind is
 * looked up by its own ids, so an area and a building that share an id do not clash together;
 * only `road` areas can clash at all.
 */
export function clashKeys(layout: Layout): Set<string> {
  const named = new Set<string>();
  for (const f of layout.findings ?? []) if (isClash(f)) for (const id of f.ids) named.add(id);
  const keys = new Set<string>();
  const check = (kind: ItemKind, id: string, flag: boolean | undefined) => {
    if (typeof flag === "boolean" ? flag : named.has(id)) keys.add(`${kind}:${id}`);
  };
  for (const e of layout.equipment ?? []) check("equipment", e.tag, e.clash);
  for (const b of layout.buildings ?? []) check("building", b.id, b.clash);
  for (const r of layout.roads ?? []) check("road", r.id, r.clash);
  for (const r of layout.racks ?? []) check("rack", r.id, r.clash);
  for (const a of layout.areas ?? []) if (a.kind === "road") check("area", a.id, a.clash);
  return keys;
}

const FINDING_KINDS: ItemKind[] = [
  "equipment",
  "pipe",
  "structure",
  "platform",
  "zone",
  "nozzle",
  "inline",
  "penetration",
  "hatch",
  "tray",
  "junction_box",
  "duct",
  "hvac_unit",
  "hvac_room",
  "cable",
  "instrument",
  "envelope",
  "building",
  "rack",
  "road",
  "area",
];

/** The item key a finding points at: the first of its ids that is in the scene. */
export function findingItem(finding: Finding, items: Map<string, LayoutItem>, ids?: Map<string, string>): string | null {
  for (const id of finding.ids) {
    for (const kind of FINDING_KINDS) if (items.has(`${kind}:${id}`)) return `${kind}:${id}`;
    const viaId = ids?.get(id);
    if (viaId && items.has(viaId)) return viaId;
  }
  return null;
}

/**
 * Item key for an id from a link (`?select=`): an item key itself, a tag, line number, DEXPI id,
 * segment or nozzle id of the scene, else null.
 */
export function resolveSelect(id: string | null | undefined, scene: Pick<SceneSpec, "items" | "ids">): string | null {
  if (!id) return null;
  if (scene.items.has(id)) return id;
  for (const kind of FINDING_KINDS) if (scene.items.has(`${kind}:${id}`)) return `${kind}:${id}`;
  const viaId = scene.ids.get(id);
  return viaId && scene.items.has(viaId) ? viaId : null;
}

/**
 * What a finding marks in 3D: every item its ids name, and its box when it is a 3D one
 * (`[x0, y0, z0, x1, y1, z1]`, a layout clash, headroom or access finding).
 */
export function findingTargets(finding: Finding, scene: Pick<SceneSpec, "items" | "ids">): { items: string[]; box: Box3 | null } {
  const out: string[] = [];
  // The finding's own subject first (a penetration, a tray), when it is an object of the scene.
  const subject = finding.key ? resolveSelect(finding.key, scene) : null;
  if (subject) out.push(subject);
  for (const id of finding.ids) {
    // A walking surface core names by its owner (`T-4101/stair`, an item's stair as a whole)
    // is no object of its own: its owner is.
    let key = resolveSelect(id, scene);
    for (let at = id.lastIndexOf("/"), owner = id; !key && at > 0; at = owner.lastIndexOf("/")) {
      owner = owner.slice(0, at);
      key = resolveSelect(owner, scene);
    }
    if (key && !out.includes(key)) out.push(key);
  }
  const b = finding.box;
  let box: Box3 | null = null;
  if (Array.isArray(b) && b.length === 6 && b.every((v) => typeof v === "number")) {
    const [x0, y0, z0, x1, y1, z1] = b;
    box = { min: [Math.min(x0, x1), Math.min(y0, y1), Math.min(z0, z1)], max: [Math.max(x0, x1), Math.max(y0, y1), Math.max(z0, z1)] };
  }
  return { items: out, box };
}

export { sheetFile } from "./format";

export interface BuildingLevelBox {
  id: string;
  title: string | null;
  kind: string;
  elevation: number;
  /** Clear height, as cheme-as-code checks it. */
  height: number;
  /** Thickness of the deck drawn at the elevation of a platform or roof, else null. */
  slab: number | null;
}

export const SLAB: Record<string, number> = { roof: 0.3, platform: 0.2 };

/**
 * Levels of a building with heights filled in, by the rule cheme-as-code uses (and sends as
 * `clear_height`): the declared height, else up to the next level, else 4 m for a floor and the
 * slab for a platform or roof. A building without levels has one 6 m floor.
 */
export function buildingLevels(building: LayoutBuilding): BuildingLevelBox[] {
  const levels = [...(building.levels ?? [])].sort((a, b) => num(a.elevation, 0) - num(b.elevation, 0));
  if (!levels.length) return [{ id: "", title: null, kind: "floor", elevation: 0, height: 6, slab: null }];
  return levels.map((level, i) => {
    const kind = level.kind ?? "floor";
    const elevation = num(level.elevation, 0);
    const next = levels[i + 1];
    const slab = SLAB[kind] ?? null;
    let height: number;
    if (typeof level.clear_height === "number" && level.clear_height > 0) height = level.clear_height;
    else if (level.height != null && level.height > 0) height = level.height;
    else if (next && num(next.elevation, 0) > elevation) height = num(next.elevation, 0) - elevation;
    else height = slab ?? 4;
    return { id: level.id, title: level.title ?? null, kind, elevation, height, slab };
  });
}

/** Footprint corners of a building (SW, SE, NE, NW in its local frame), rotated about `origin`. */
export function buildingCorners(b: LayoutBuilding): XY[] {
  const [ox, oy] = b.origin;
  const angle = deg(b.rotation_deg);
  const corners: XY[] = [
    [ox, oy],
    [ox + b.width, oy],
    [ox + b.width, oy + b.depth],
    [ox, oy + b.depth],
  ];
  return corners.map((p) => rotateXY(p, angle, b.origin));
}

/**
 * Strip segments of a polyline: centre, length and heading per segment. With `joint`, each
 * segment is lengthened by `joint` at the ends where it meets another one, so a strip of that
 * width has no gaps at its bends (the polyline's own ends stay where they are).
 */
export function stripSegments(points: XY[], joint = 0): { center: XY; length: number; angle: number }[] {
  const out: { center: XY; length: number; angle: number }[] = [];
  const last = points.length - 1;
  for (let i = 1; i < points.length; i++) {
    const [x0, y0] = points[i - 1]!;
    const [x1, y1] = points[i]!;
    const length = Math.hypot(x1 - x0, y1 - y0);
    if (length === 0) continue;
    const angle = Math.atan2(y1 - y0, x1 - x0);
    const e0 = i > 1 ? joint : 0;
    const e1 = i < last ? joint : 0;
    const shift = (e1 - e0) / 2;
    out.push({
      center: [(x0 + x1) / 2 + Math.cos(angle) * shift, (y0 + y1) / 2 + Math.sin(angle) * shift],
      length: length + e0 + e1,
      angle,
    });
  }
  return out;
}

/** Unit direction from `a` to `b`, or null for a zero-length step. */
function direction(a: XY, b: XY): XY | null {
  const len = Math.hypot(b[0] - a[0], b[1] - a[1]);
  return len > 1e-9 ? [(b[0] - a[0]) / len, (b[1] - a[1]) / len] : null;
}

/**
 * Left and right edge points of a polyline offset by `half`, mitred at the inner points: the
 * edges meet where the offset segments would, so both sides stay `half` from every segment
 * (the mitre is capped at 4 x `half` for very sharp bends).
 */
export function offsetPolyline(points: XY[], half: number): { left: XY[]; right: XY[] } {
  const left: XY[] = [];
  const right: XY[] = [];
  for (let i = 0; i < points.length; i++) {
    const [x, y] = points[i]!;
    const before = i > 0 ? direction(points[i - 1]!, points[i]!) : null;
    const after = i < points.length - 1 ? direction(points[i]!, points[i + 1]!) : null;
    const d1 = before ?? after ?? [1, 0];
    const d2 = after ?? before ?? [1, 0];
    // Left normals of the two segments, and their bisector.
    const n1: XY = [-d1[1], d1[0]];
    const n2: XY = [-d2[1], d2[0]];
    let mx = n1[0] + n2[0];
    let my = n1[1] + n2[1];
    const mlen = Math.hypot(mx, my);
    if (mlen < 1e-9) [mx, my] = n1;
    else [mx, my] = [mx / mlen, my / mlen];
    const cos = mx * n1[0] + my * n1[1];
    const reach = Math.min(half / Math.max(cos, 1e-9), half * 4);
    const r = (v: number) => Math.round(v * 1e9) / 1e9;
    left.push([r(x + mx * reach), r(y + my * reach)]);
    right.push([r(x - mx * reach), r(y - my * reach)]);
  }
  return { left, right };
}

const ROAD_THICKNESS = 0.06;
const AREA_THICKNESS = 0.12;

function item(kind: ItemKind, id: string, fields: Partial<LayoutItem> = {}): LayoutItem {
  return {
    kind,
    id,
    title: null,
    type: null,
    sheet: null,
    sheetFile: null,
    service: null,
    notes: null,
    building: null,
    level: null,
    details: [],
    clash: false,
    ...fields,
  };
}

/** Grid lines every `step` m over the site, `[x0, y0] -> [x1, y1]` pairs. */
export function siteGrid(width: number, depth: number, step = width > 200 || depth > 200 ? 50 : 10): [XY, XY][] {
  const out: [XY, XY][] = [];
  for (let x = 0; x <= width + 1e-9; x += step) out.push([[x, 0], [x, depth]]);
  for (let y = 0; y <= depth + 1e-9; y += step) out.push([[0, y], [width, y]]);
  return out;
}

/** A round scale-bar length (1, 2 or 5 times a power of ten) about a fifth of `span`. */
export function scaleLength(span: number): number {
  const target = Math.max(span / 5, 1e-3);
  const power = 10 ** Math.floor(Math.log10(target));
  for (const m of [5, 2, 1]) if (m * power <= target) return m * power;
  return power;
}

const fmt = (n: number) => String(Math.round(n * 1000) / 1000);
const fmtVec = (v: number[]) => `[${v.map(fmt).join(", ")}]`;

function extend(bounds: Bounds, x: number, y: number, z: number): void {
  bounds.min = [Math.min(bounds.min[0], x), Math.min(bounds.min[1], y), Math.min(bounds.min[2], z)];
  bounds.max = [Math.max(bounds.max[0], x), Math.max(bounds.max[1], y), Math.max(bounds.max[2], z)];
}

/** The scene description of a layout. */
export function buildScene(layout: Layout, options: { sheets?: Sheet[] | undefined } = {}): SceneSpec {
  const clash = clashKeys(layout);
  const model = layout.model ? buildModelScene(layout.model, { sheets: options.sheets, clash, equipmentColor }) : null;
  const solids: SolidSpec[] = [];
  const lines: LinesSpec[] = [];
  const labels: LabelSpec[] = [];
  const items = new Map<string, LayoutItem>();
  const bounds: Bounds = { min: [Infinity, Infinity, 0], max: [-Infinity, -Infinity, 0] };

  const site = layout.site && layout.site.width > 0 && layout.site.depth > 0 ? layout.site : null;
  if (site) {
    extend(bounds, 0, 0, 0);
    extend(bounds, site.width, site.depth, 0);
    const c: Vec3[] = [
      [0, 0, 0],
      [site.width, 0, 0],
      [site.width, site.depth, 0],
      [0, site.depth, 0],
    ];
    lines.push({ key: "site:outline", layer: "site", color: SITE_COLOR, segments: c.map((p, i): [Vec3, Vec3] => [p, c[(i + 1) % 4]!]), clash: false, item: null });
    // North arrow beyond the north-east corner, scale bar below the south-west corner.
    const span = Math.max(site.width, site.depth);
    const arrow = Math.max(span * 0.06, 2);
    const ax = site.width + arrow;
    const ay = site.depth - arrow * 1.6;
    lines.push({
      key: "site:north",
      layer: "site",
      color: SITE_COLOR,
      segments: [
        [[ax, ay, 0.05], [ax, ay + arrow, 0.05]],
        [[ax, ay + arrow, 0.05], [ax - arrow * 0.3, ay + arrow * 0.6, 0.05]],
        [[ax, ay + arrow, 0.05], [ax + arrow * 0.3, ay + arrow * 0.6, 0.05]],
      ],
      clash: false,
      item: null,
    });
    labels.push({ key: "site:north", layer: "site", toggle: null, style: "marker", text: "N", position: [ax, ay + arrow * 1.15, 0.05], clash: false, item: null, priority: LABEL_PRIORITY.marker });
    const bar = scaleLength(site.width);
    const by = -Math.max(span * 0.04, 1.5);
    const tick = Math.max(span * 0.01, 0.4);
    lines.push({
      key: "site:scale",
      layer: "site",
      color: SITE_COLOR,
      segments: [
        [[0, by, 0.05], [bar, by, 0.05]],
        [[0, by - tick, 0.05], [0, by + tick, 0.05]],
        [[bar, by - tick, 0.05], [bar, by + tick, 0.05]],
      ],
      clash: false,
      item: null,
    });
    labels.push({ key: "site:scale", layer: "site", toggle: null, style: "marker", text: `${fmt(bar)} m`, position: [bar / 2, by - tick, 0.05], clash: false, item: null, priority: LABEL_PRIORITY.marker });
    extend(bounds, ax + arrow * 0.3, ay + arrow * 1.15, 0);
    extend(bounds, 0, by - tick, 0);
  }

  for (const area of layout.areas ?? []) {
    const [x0, y0, x1, y1] = area.box;
    const kind = area.kind ?? "";
    const key = `area:${area.id}`;
    const areaClash = clash.has(key);
    items.set(key, item("area", area.id, { title: area.title ?? null, type: kind || null, details: [["box", fmtVec(area.box)]], clash: areaClash }));
    extend(bounds, Math.min(x0, x1), Math.min(y0, y1), 0);
    extend(bounds, Math.max(x0, x1), Math.max(y0, y1), 0);
    solids.push({
      key,
      layer: "areas",
      shape: "box",
      axis: "z",
      center: [(x0 + x1) / 2, (y0 + y1) / 2, AREA_THICKNESS / 2],
      size: [Math.abs(x1 - x0), Math.abs(y1 - y0), AREA_THICKNESS],
      rotationZ: 0,
      color: AREA_COLORS[kind] ?? AREA_DEFAULT_COLOR,
      opacity: 0.22,
      clash: areaClash,
      item: key,
    });
    labels.push({ key: `name:${key}`, layer: "areas", toggle: "names", style: "name", text: area.id, position: [(x0 + x1) / 2, (y0 + y1) / 2, AREA_THICKNESS], clash: areaClash, item: key, priority: LABEL_PRIORITY.area });
  }

  for (const road of layout.roads ?? []) {
    const width = positive(road.width, 6);
    const key = `road:${road.id}`;
    const roadClash = clash.has(key);
    items.set(key, item("road", road.id, { title: road.title ?? null, details: [["width", `${fmt(width)} m`], ["points", String(road.points.length)]], clash: roadClash }));
    stripSegments(road.points, width / 2).forEach((seg, i) => {
      solids.push({
        key: `${key}:${i}`,
        layer: "roads",
        shape: "box",
        axis: "z",
        // On top of the area slabs, so a road through an area stays visible.
        center: [seg.center[0], seg.center[1], AREA_THICKNESS + ROAD_THICKNESS / 2],
        size: [seg.length, width, ROAD_THICKNESS],
        rotationZ: seg.angle,
        color: ROAD_COLOR,
        opacity: 1,
        clash: roadClash,
        item: key,
      });
    });
    const edges = offsetPolyline(road.points, width / 2);
    for (const [x, y] of [...edges.left, ...edges.right]) extend(bounds, x, y, 0);
  }

  for (const rack of layout.racks ?? []) {
    const width = positive(rack.width, 6);
    const levels = [...(rack.levels?.length ? rack.levels : [5])].sort((a, b) => a - b);
    const top = Math.max(...levels);
    const key = `rack:${rack.id}`;
    const rackClash = clash.has(key);
    items.set(
      key,
      item("rack", rack.id, {
        title: rack.title ?? null,
        details: [
          ["width", `${fmt(width)} m`],
          ["levels", levels.map((z) => `${fmt(z)} m`).join(", ")],
        ],
        clash: rackClash,
      }),
    );
    const { left, right } = offsetPolyline(rack.points, width / 2);
    const segments: [Vec3, Vec3][] = [];
    for (let i = 0; i < rack.points.length; i++) {
      const [lx, ly] = left[i]!;
      const [rx, ry] = right[i]!;
      // Bents: two posts and a cross beam per level at every point.
      segments.push([[lx, ly, 0], [lx, ly, top]], [[rx, ry, 0], [rx, ry, top]]);
      for (const z of levels) segments.push([[lx, ly, z], [rx, ry, z]]);
      if (i > 0) {
        const [plx, ply] = left[i - 1]!;
        const [prx, pry] = right[i - 1]!;
        // Longitudinal beams per level on both sides.
        for (const z of levels) segments.push([[plx, ply, z], [lx, ly, z]], [[prx, pry, z], [rx, ry, z]]);
      }
      extend(bounds, Math.min(lx, rx), Math.min(ly, ry), top);
      extend(bounds, Math.max(lx, rx), Math.max(ly, ry), top);
    }
    // The model's rack steel (bents) replaces the frame drawn from the centreline.
    if (!layout.model) lines.push({ key, layer: "structures", color: rackClash ? CLASH_COLOR : RACK_COLOR, segments, clash: rackClash, item: key, members: RACK_MEMBER });
    const [p0, p1] = [rack.points[0], rack.points[1]];
    if (p0 && p1)
      labels.push({ key: `name:${key}`, layer: "structures", toggle: "names", style: "name", text: rack.id, position: [(p0[0] + p1[0]) / 2, (p0[1] + p1[1]) / 2, top + 0.3], clash: rackClash, item: key, priority: LABEL_PRIORITY.structure });
    // A faint footprint solid so the rack can be clicked.
    stripSegments(rack.points).forEach((seg, i) => {
      solids.push({
        key: `${key}:${i}`,
        layer: "structures",
        shape: "box",
        axis: "z",
        center: [seg.center[0], seg.center[1], top / 2],
        size: [seg.length, width, top],
        rotationZ: seg.angle,
        color: rackClash ? CLASH_COLOR : RACK_COLOR,
        opacity: 0.06,
        clash: rackClash,
        item: key,
      });
    });
  }

  for (const b of layout.buildings ?? []) {
    const angle = deg(b.rotation_deg);
    const center = rotateXY([b.origin[0] + b.width / 2, b.origin[1] + b.depth / 2], angle, b.origin);
    const levels = buildingLevels(b);
    const key = `building:${b.id}`;
    const isClash = clash.has(key);
    items.set(
      key,
      item("building", b.id, {
        title: b.title ?? null,
        details: [
          ["origin", fmtVec(b.origin)],
          ["size", `${fmt(b.width)} x ${fmt(b.depth)} m`],
          ["rotation", `${fmt(b.rotation_deg ?? 0)} deg`],
          ["levels", levels.map((l) => `${l.id || l.kind} @ ${fmt(l.elevation)} m, ${fmt(l.height)} m high`).join("; ")],
        ],
        clash: isClash,
      }),
    );
    for (const level of levels) {
      const base = {
        layer: "buildings" as const,
        shape: "box" as const,
        axis: "z" as const,
        rotationZ: angle,
        color: isClash ? CLASH_COLOR : BUILDING_COLOR,
        clash: isClash,
        item: key,
      };
      const id = level.id || level.kind;
      if (level.slab == null) {
        solids.push({ ...base, key: `${key}:${id}`, center: [center[0], center[1], level.elevation + level.height / 2], size: [b.width, b.depth, level.height], opacity: 0.16 });
        continue;
      }
      // A platform or roof: its deck, and above it the clear height cheme-as-code checks, faintly.
      const slab = Math.min(level.slab, level.height);
      solids.push({ ...base, key: `${key}:${id}`, center: [center[0], center[1], level.elevation + slab / 2], size: [b.width, b.depth, slab], opacity: 0.32 });
      if (level.height > slab + 1e-6)
        solids.push({
          ...base,
          key: `${key}:${id}:clear`,
          center: [center[0], center[1], level.elevation + (slab + level.height) / 2],
          size: [b.width, b.depth, level.height - slab],
          opacity: 0.07,
        });
    }
    const top = Math.max(...levels.map((l) => l.elevation + l.height));
    const bottom = Math.min(...levels.map((l) => l.elevation));
    const gx = b.frame?.grid_x ?? [];
    const gy = b.frame?.grid_y ?? [];
    const segments: [Vec3, Vec3][] = [];
    const at = (lx: number, ly: number): XY => rotateXY([b.origin[0] + lx, b.origin[1] + ly], angle, b.origin);
    for (const x of gx)
      for (const y of gy) {
        const [px, py] = at(x, y);
        segments.push([[px, py, bottom], [px, py, top]]);
      }
    if (gx.length && gy.length) {
      const [y0, y1] = [Math.min(...gy), Math.max(...gy)];
      const [x0, x1] = [Math.min(...gx), Math.max(...gx)];
      for (const level of levels) {
        const z = level.elevation;
        for (const x of gx) {
          const p = at(x, y0);
          const q = at(x, y1);
          segments.push([[p[0], p[1], z], [q[0], q[1], z]]);
        }
        for (const y of gy) {
          const p = at(x0, y);
          const q = at(x1, y);
          segments.push([[p[0], p[1], z], [q[0], q[1], z]]);
        }
      }
    }
    if (segments.length) lines.push({ key: `${key}:grid`, layer: "buildings", color: COLUMN_COLOR, segments, clash: isClash, item: key, members: COLUMN_MEMBER });
    for (const [x, y] of buildingCorners(b)) extend(bounds, x, y, top);
    // At the north-west corner, so it does not cover the tags of the equipment inside.
    const corners = buildingCorners(b);
    const nw: XY = [Math.min(...corners.map((c) => c[0])), Math.max(...corners.map((c) => c[1]))];
    labels.push({ key: `name:${key}`, layer: "buildings", toggle: "names", style: "name", text: b.id, position: [nw[0], nw[1], top], clash: isClash, item: key, priority: LABEL_PRIORITY.structure });
  }

  for (const eq of layout.equipment ?? []) {
    const geometry = equipmentGeometry(eq.shape, eq.size);
    const [x, y, z] = eq.position;
    const key = `equipment:${eq.tag}`;
    const isClash = clash.has(key);
    const placed = equipmentItem(eq, geometry, isClash);
    const fromModel = model?.items.get(key);
    items.set(
      key,
      fromModel
        ? { ...placed, details: fromModel.details, source: fromModel.source, highlight: fromModel.highlight, related: fromModel.related, sheetFile: placed.sheetFile ?? fromModel.sheetFile }
        : placed,
    );
    const bottom = z + (geometry.base ?? 0);
    const top = model?.itemBounds.get(key)?.max[2] ?? bottom + geometry.size[2];
    labels.push({ key: `label:${eq.tag}`, layer: "equipment", toggle: "labels", style: "tag", text: eq.tag, position: [x, y, top + 0.4], clash: isClash, item: key, priority: LABEL_PRIORITY.equipment });
    const r = Math.hypot(geometry.size[0], geometry.size[1]) / 2;
    extend(bounds, x - r, y - r, z);
    extend(bounds, x + r, y + r, top);
    // The generated model draws this item from its parts.
    if (model?.tags.has(eq.tag)) continue;
    solids.push({
      key,
      layer: "equipment",
      shape: geometry.shape,
      axis: geometry.axis,
      center: [x, y, bottom + geometry.size[2] / 2],
      size: geometry.size,
      rotationZ: deg(eq.rotation_deg),
      color: isClash ? CLASH_COLOR : equipmentColor(eq.type),
      opacity: 1,
      clash: isClash,
      item: key,
    });
  }

  // Model objects the placement list does not have (pipes, structures, zones, nozzles, ...).
  const meshes: MeshSpec[] = solids.map(solidMesh);
  for (const set of lines)
    if (set.members && set.item)
      set.segments.forEach(([a, b], i) =>
        meshes.push({
          key: `${set.key}:m${i}`,
          layer: set.layer,
          item: set.item!,
          prim: { kind: "beam", start: a, end: b, width: set.members!, depth: set.members! },
          color: set.color,
          material: "steel",
          opacity: 1,
          source: "declared",
          clash: set.clash,
        }),
      );
  const itemBounds = new Map<string, Box3>();
  for (const m of meshes) itemBounds.set(m.item, unionBox(itemBounds.get(m.item), primBounds(m.prim)));
  if (model) {
    meshes.push(...model.meshes);
    for (const [key, box] of model.itemBounds) {
      itemBounds.set(key, unionBox(itemBounds.get(key), box));
      if (!items.has(key)) {
        const info = model.items.get(key)!;
        items.set(key, item(info.kind, info.id, { title: info.title, type: info.type, sheetFile: info.sheetFile, details: info.details, source: info.source, highlight: info.highlight, related: info.related, line: info.line, review: info.review, clash: clash.has(key) }));
      }
      extend(bounds, box.min[0], box.min[1], box.min[2]);
      extend(bounds, box.max[0], box.max[1], box.max[2]);
    }
    for (const label of model.labels)
      labels.push({ key: label.key, layer: label.layer, toggle: "lines", style: "tag", text: label.text, position: label.position, clash: false, item: label.item, priority: LABEL_PRIORITY.line });
    // Steel frames by name, above their top.
    for (const st of layout.model?.structures ?? []) {
      const box = itemBounds.get(`structure:${st.id}`);
      if (!box) continue;
      const key = `structure:${st.id}`;
      labels.push({ key: `name:${key}`, layer: "structures", toggle: "names", style: "name", text: st.id, position: [(box.min[0] + box.max[0]) / 2, (box.min[1] + box.max[1]) / 2, box.max[2] + 0.3], clash: clash.has(key), item: key, priority: LABEL_PRIORITY.structure });
    }
  }

  if (!Number.isFinite(bounds.min[0])) bounds.min = [0, 0, 0];
  if (!Number.isFinite(bounds.max[0])) bounds.max = [10, 10, 0];
  const pipePoints = (layout.model?.pipes ?? []).flatMap((p) => p.points);
  const plantBounds = plantBox(itemBounds, pipePoints) ?? { min: [...bounds.min], max: [...bounds.max] };

  return {
    site: site ? { width: site.width, depth: site.depth, name: site.name ?? null } : null,
    bounds,
    plantBounds,
    solids,
    lines,
    labels,
    items,
    clashKeys: clash,
    legend: legend(layout),
    meshes,
    edges: model?.edges ?? [],
    itemBounds,
    ids: model?.ids ?? new Map(),
    floors: model?.floors ?? buildingFloors(layout),
    hasModel: Boolean(model),
    counts: model?.counts ?? {},
    routes: model?.routes ?? new Map(),
    proposals: model?.proposals ?? new Map(),
  };
}

/** Section of the rack and building steel drawn as solid members, m. */
export const RACK_MEMBER = 0.3;
export const COLUMN_MEMBER = 0.35;

const SOLID_MATERIAL: Record<string, string> = { areas: "area", roads: "road", structures: "steel", buildings: "building", equipment: "shell" };

/** A placement solid as a mesh primitive. */
export function solidPrim(s: SolidSpec): Prim {
  if (s.shape === "sphere") return { kind: "ellipsoid", centre: s.center, radii: [s.size[0] / 2, s.size[1] / 2, s.size[2] / 2], rotationZ: s.rotationZ };
  if (s.shape === "cylinder") {
    const [cx, cy, cz] = s.center;
    if (s.axis === "z") return { kind: "cylinder", start: [cx, cy, cz - s.size[2] / 2], end: [cx, cy, cz + s.size[2] / 2], radius: s.size[0] / 2, radiusEnd: s.size[0] / 2 };
    const hx = (Math.cos(s.rotationZ) * s.size[0]) / 2;
    const hy = (Math.sin(s.rotationZ) * s.size[0]) / 2;
    return { kind: "cylinder", start: [cx - hx, cy - hy, cz], end: [cx + hx, cy + hy, cz], radius: s.size[1] / 2, radiusEnd: s.size[1] / 2 };
  }
  return { kind: "box", centre: s.center, size: s.size, rotationZ: s.rotationZ };
}

function solidMesh(s: SolidSpec): MeshSpec {
  return { key: s.key, layer: s.layer, item: s.item, prim: solidPrim(s), color: s.color, material: SOLID_MATERIAL[s.layer] ?? "shell", opacity: s.opacity, source: "declared", clash: s.clash };
}

/** Walkable building levels from the placement data (when there is no model). */
function buildingFloors(layout: Layout): Floor[] {
  const out: Floor[] = [];
  for (const b of layout.buildings ?? []) {
    const polygon = buildingCorners(b);
    for (const level of buildingLevels(b)) out.push({ id: `${b.id}/${level.id}`, elevation: level.elevation + (level.slab ?? 0), polygon });
  }
  return out;
}

/** Colour keys for the area kinds, equipment types, pipe services and zones present, in the order they first appear. */
export function legend(layout: Layout): Legend {
  const areas = new Map<string, string>();
  for (const a of layout.areas ?? []) {
    const kind = a.kind ?? "";
    if (kind && !areas.has(kind)) areas.set(kind, AREA_COLORS[kind] ?? AREA_DEFAULT_COLOR);
  }
  if ((layout.roads ?? []).length && !areas.has("road")) areas.set("road", ROAD_COLOR);
  if ((layout.racks ?? []).length) areas.set("pipe rack", RACK_COLOR);
  if ((layout.buildings ?? []).length && !areas.has("building")) areas.set("building", BUILDING_COLOR);
  const equipmentTypes: GroupInput[] = (layout.equipment ?? []).map((e) => ({ label: e.type ?? "unknown type", color: equipmentColor(e.type), group: equipmentGroup(e.type) }));
  const equipment = groupLegend(equipmentTypes);
  if (clashKeys(layout).size) equipment.push({ label: "clash", color: CLASH_COLOR });
  const services: GroupInput[] = (layout.model?.pipes ?? []).map((p) => {
    const service = pipeService(p);
    return { label: service || "other", color: serviceColor(service), group: service ? serviceFamily(service) : null };
  });
  const classes = new Map([...classColors(layout.model?.pipes ?? [])].map(([cls, color]) => [cls || "no class", color]));
  const zones = new Map<string, string>();
  for (const z of layout.model?.zones ?? []) if (!zones.has(z.kind)) zones.set(z.kind.replace(/_/g, " "), zoneColor(z.kind));
  const entries = (m: Map<string, string>) => [...m].map(([label, color]) => ({ label, color }));
  const provenance: LegendEntry[] = (["generated", "pinned", "declared"] as const).map((label) => ({ label, color: PROVENANCE_COLORS[label] }));
  const m = layout.model;
  const toReview =
    (m?.pipes ?? []).some((p) => p.review_needed) ||
    (m?.platforms ?? []).some((p) => p.review_needed) ||
    (m?.structures ?? []).some((s) => [...s.stairs, ...s.ladders].some((x) => x.review_needed)) ||
    (m?.racks ?? []).some((r) => (r.ladders ?? []).some((l) => l.review_needed)) ||
    (m?.step_overs ?? []).some((s) => s.review_needed) ||
    (m?.penetrations ?? []).some((p) => p.review_needed !== false) ||
    (m?.junction_boxes ?? []).some((j) => j.review_needed);
  if (toReview) provenance.push({ label: "review needed", color: REVIEW_COLOR });
  const mep: LegendEntry[] = [];
  for (const system of new Set((m?.trays ?? []).map((t) => t.system))) mep.push({ label: `${system} tray`, color: TRAY_COLORS[system] ?? STEEL_COLOR });
  if ((m?.junction_boxes ?? []).length) mep.push({ label: "junction box", color: STRUCTURE_COLORS.junction_box! });
  if ((m?.hvac_units ?? []).length) mep.push({ label: "air handling unit", color: STRUCTURE_COLORS.ahu! });
  for (const system of new Set((m?.ducts ?? []).map((d) => d.system))) mep.push({ label: `${system} air duct`, color: DUCT_COLORS[system] ?? STEEL_COLOR });
  if ((m?.penetrations ?? []).length) mep.push({ label: "wall penetration", color: PENETRATION_COLOR });
  return { areas: entries(areas), equipment, pipes: groupLegend(services), pipeClasses: entries(classes), zones: entries(zones), services: mep, provenance };
}

export interface GroupInput {
  label: string;
  color: string;
  /** Rows with the same group share one legend row named by the group; null keeps a row of its own. */
  group: string | null;
}

/**
 * Legend rows from types or services in order of first appearance: one row per group (named by
 * the group, its members listed), one per ungrouped label; repeats are dropped.
 */
export function groupLegend(inputs: readonly GroupInput[]): LegendEntry[] {
  const rows = new Map<string, LegendEntry & { members: string[] }>();
  for (const input of inputs) {
    const id = input.group !== null ? `g:${input.group}` : `l:${input.label}`;
    let row = rows.get(id);
    if (!row) {
      row = { label: input.group ?? input.label, color: input.color, members: [] };
      rows.set(id, row);
    }
    if (!row.members.includes(input.label)) row.members.push(input.label);
  }
  return [...rows.values()].map((r) => (r.members.length === 1 && r.members[0] === r.label ? { label: r.label, color: r.color } : r));
}

const PLANT_KINDS = new Set(["equipment", "structure", "rack", "building", "platform", "nozzle"]);
/** How far pipe runs may stretch the plant's frame beyond its equipment and steel, m. */
export const PIPE_REACH = 5;

/**
 * Bounds of the plant: its equipment, steel, racks and buildings (not the site, areas, roads,
 * zones or envelopes), widened by the pipe points and in-line items within {@link PIPE_REACH}
 * of them. Pipe runs out to the battery limits at the site edge do not stretch it. Null when there
 * is no plant item.
 */
export function plantBox(itemBounds: ReadonlyMap<string, Box3>, pipePoints: readonly (readonly number[])[] = []): Bounds | null {
  let out: Box3 | undefined;
  for (const [key, box] of itemBounds) if (PLANT_KINDS.has(key.slice(0, key.indexOf(":")))) out = unionBox(out, box);
  if (!out) {
    // Pipes only: all of them.
    for (const [key, box] of itemBounds) if (key.startsWith("pipe:")) out = unionBox(out, box);
    return out ? { min: [...out.min], max: [...out.max] } : null;
  }
  const core = out;
  const near = (p: readonly number[]) => [0, 1, 2].every((i) => p[i]! >= core.min[i]! - PIPE_REACH && p[i]! <= core.max[i]! + PIPE_REACH);
  for (const p of pipePoints) if (p.length === 3 && near(p)) out = unionBox(out, { min: [p[0]!, p[1]!, p[2]!], max: [p[0]!, p[1]!, p[2]!] });
  for (const [key, box] of itemBounds) if (key.startsWith("inline:") && near(box.min) && near(box.max)) out = unionBox(out, box);
  return { min: [...out.min], max: [...out.max] };
}

function equipmentItem(eq: PlacedEquipment, geometry: EquipmentGeometry, clash: boolean): LayoutItem {
  const details: [string, string][] = [
    ["position", fmtVec(eq.position)],
    ["shape", eq.shape],
    ["size", `${[geometry.size[0], geometry.size[1], (geometry.base ?? 0) + geometry.size[2]].map(fmt).join(" x ")} m`],
  ];
  if (eq.rotation_deg) details.push(["rotation", `${fmt(eq.rotation_deg)} deg`]);
  return item("equipment", eq.tag, {
    type: eq.type ?? null,
    sheet: eq.sheet ?? null,
    sheetFile: eq.sheet_file ?? null,
    service: eq.service || null,
    notes: eq.notes || null,
    clash,
    building: eq.building ?? null,
    level: eq.level ?? null,
    details,
  });
}

export type ViewName = "top" | "iso" | "north" | "east" | "south" | "west" | "site";
/** Views of the plant, and `site`: the whole plot from the south-west. */
export const VIEWS: ViewName[] = ["iso", "top", "north", "east", "south", "west", "site"];

/** Room left around the bounds when a view frames them. */
export const FRAME_MARGIN = 1.15;

/**
 * Half width and half height of an orthographic (plan) view of `bounds` in a viewport of
 * `aspect` (width / height), with {@link FRAME_MARGIN}.
 */
export function planFrame(bounds: Bounds, aspect = 1): { halfWidth: number; halfHeight: number } {
  const sx = Math.max(bounds.max[0] - bounds.min[0], 1) * FRAME_MARGIN;
  const sy = Math.max(bounds.max[1] - bounds.min[1], 1) * FRAME_MARGIN;
  const a = Math.max(aspect, 0.1);
  const halfHeight = Math.max(sy, sx / a) / 2;
  return { halfWidth: halfHeight * a, halfHeight };
}

const normalize = (v: Vec3): Vec3 => {
  const l = Math.hypot(v[0], v[1], v[2]) || 1;
  return [v[0] / l, v[1] / l, v[2] / l];
};
const cross = (a: Vec3, b: Vec3): Vec3 => [a[1] * b[2] - a[2] * b[1], a[2] * b[0] - a[0] * b[2], a[0] * b[1] - a[1] * b[0]];
const dot = (a: Vec3, b: Vec3) => a[0] * b[0] + a[1] * b[1] + a[2] * b[2];

/** Unit vector from the target towards the camera for a view (z up). */
export function viewDirection(view: ViewName): Vec3 {
  switch (view) {
    case "top":
      return normalize([0, -1e-3, 1]);
    case "north":
      return normalize([0, 1, 0.12]);
    case "south":
      return normalize([0, -1, 0.12]);
    case "east":
      return normalize([1, 0, 0.12]);
    case "west":
      return normalize([-1, 0, 0.12]);
    default:
      return normalize([-1, -1.2, 1.1]);
  }
}

/**
 * Distance from the centre of `bounds` along `direction` (target to camera) at which a
 * perspective camera with vertical field of view `fovDeg` in a viewport of `aspect` sees all
 * eight corners of the box, with `margin` room around them.
 */
export function fitDistance(bounds: Bounds, direction: Vec3, fovDeg = 45, aspect = 1, margin = FRAME_MARGIN): number {
  const back = normalize(direction);
  const forward: Vec3 = [-back[0], -back[1], -back[2]];
  // Camera right and up; looking straight down, right is east.
  let right = cross(forward, [0, 0, 1]);
  right = Math.hypot(...right) < 1e-6 ? [1, 0, 0] : normalize(right);
  const up = cross(right, forward);
  const tanV = Math.tan(deg(fovDeg) / 2) / margin;
  const tanH = tanV * Math.max(aspect, 0.05);
  const centre: Vec3 = [(bounds.min[0] + bounds.max[0]) / 2, (bounds.min[1] + bounds.max[1]) / 2, (bounds.min[2] + bounds.max[2]) / 2];
  let distance = 0;
  for (const x of [bounds.min[0], bounds.max[0]])
    for (const y of [bounds.min[1], bounds.max[1]])
      for (const z of [bounds.min[2], bounds.max[2]]) {
        const rel: Vec3 = [x - centre[0], y - centre[1], z - centre[2]];
        // A corner `toward` the camera is nearer, so needs more room: distance - toward.
        const toward = dot(rel, back);
        distance = Math.max(distance, toward + Math.abs(dot(rel, right)) / tanH, toward + Math.abs(dot(rel, up)) / tanV);
      }
  return distance;
}

/**
 * Camera position and orbit target that frame `bounds` for a view in a viewport of `aspect`
 * (width / height): the target is the box centre, the camera backs off until the whole box fits.
 * `site` is the south-west view of whatever bounds it is given (the whole plot).
 */
export function cameraPose(view: ViewName, bounds: Bounds, fovDeg = 45, aspect = 1, minDistance = 4): { position: Vec3; target: Vec3 } {
  const target: Vec3 = [(bounds.min[0] + bounds.max[0]) / 2, (bounds.min[1] + bounds.max[1]) / 2, (bounds.min[2] + bounds.max[2]) / 2];
  const dir = viewDirection(view);
  const distance = Math.max(fitDistance(bounds, dir, fovDeg, aspect), minDistance);
  return { position: [target[0] + dir[0] * distance, target[1] + dir[1] * distance, target[2] + dir[2] * distance], target };
}

/** `12.4 m apart, about 32 m along PR-1`, or why the route is not known. */
export function lineRouteSummary(route: LineRoute): string {
  const parts: string[] = [];
  if (route.distance !== null) parts.push(`${route.distance} m apart`);
  if (route.length_est !== null)
    parts.push(`about ${route.length_est} m${route.racks.length ? ` along ${route.racks.join(", ")}` : ""}`);
  if (!parts.length) return route.finding ? "route not checked" : "ends not placed";
  return parts.join(", ");
}
