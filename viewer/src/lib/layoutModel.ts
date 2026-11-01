/**
 * The generated 3D model (`/api/layout` `model`) as plain mesh descriptions: equipment parts,
 * nozzles, envelopes, pipes with elbows and insulation, in-line items, structures, platforms,
 * stairs, ladders and zones. Pure (no three.js), like `layoutScene.ts`, so the geometry rules
 * are unit tested; `layoutThree.ts` batches the descriptions into merged meshes.
 *
 * The model follows core's contract (`docs/framework/layout-model.md` of cheme-as-code); a repo
 * without a generated model is drawn from the placement data by `layoutScene.ts` instead.
 */
import type {
  LayoutModel,
  ModelCable,
  ModelDuct,
  BuildingOpening,
  ModelEquipment,
  ModelHvacRoom,
  ModelHvacUnit,
  ModelInlineItem,
  ModelJunctionBox,
  ModelLadder,
  ModelNozzle,
  ModelOperator,
  ModelPart,
  ModelPenetration,
  ModelPipe,
  ModelPlatform,
  ModelStair,
  ModelStepOver,
  ModelStructure,
  ModelSupportSteel,
  ModelSupport,
  ModelTray,
  ModelZone,
  Sheet,
  ZoneVolume,
  XYZ,
} from "@/api";

export type Vec3 = [number, number, number];

/** Our own layer set, in the order the toolbar lists it. */
export type LayerId =
  | "site"
  | "areas"
  | "roads"
  | "buildings"
  | "structures"
  | "platforms"
  | "equipment"
  | "nozzles"
  | "pipes"
  | "insulation"
  | "inline"
  | "trays"
  | "ducts"
  | "zones"
  | "envelopes";

export const LAYERS: LayerId[] = [
  "site",
  "areas",
  "roads",
  "buildings",
  "structures",
  "platforms",
  "equipment",
  "nozzles",
  "pipes",
  "insulation",
  "inline",
  "trays",
  "ducts",
  "zones",
  "envelopes",
];

export const LAYER_TITLES: Record<LayerId, string> = {
  site: "Site outline, north arrow and scale",
  areas: "Plot areas",
  roads: "Roads",
  buildings: "Buildings, their levels and column grids",
  structures: "Steel: pipe racks, frames, bracing, enclosure walls",
  platforms: "Decks, platforms (gratings), stairs and ladders",
  equipment: "Equipment",
  nozzles: "Nozzles",
  pipes: "Pipe routes",
  insulation: "Insulation sleeves",
  inline: "Valves, instruments and other in-line items",
  trays: "Cable trays, their tier steel, junction boxes and field instruments",
  ducts: "HVAC: air handling units, ducts and terminals",
  zones: "Hazardous, oxygen, keep-clear and maintenance zones",
  envelopes: "Maintenance envelopes (bundle pull, motor removal, access)",
};

/** Layers off when the view opens. */
export const LAYERS_OFF: LayerId[] = ["envelopes"];

/**
 * A primitive in the site frame:
 * - `box`: centre, full size along its own axes, turned `rotationZ` (radians) about z;
 * - `cylinder`: axis from `start` to `end`, a cone when `radiusEnd` differs from `radius`;
 * - `cap`: half an ellipsoid of revolution on its base `centre`, bulging along unit `axis` by `depth`;
 * - `ellipsoid`: `radii` along its own axes, turned `rotationZ` about z (a sphere when all equal);
 * - `elbow`: a bend of a pipe of `radius` from `start` to `end`, tangent to the corner's legs
 *   (a quadratic curve with `corner` as control point);
 * - `beam`: a member of `width` x `depth` section from `start` to `end`;
 * - `annulus`: a flat ring sector (a platform around a vessel) whose top is at `centre`,
 *   `depth` thick, from radius `inner` to `outer`, over `arc` (degrees ccw from +x; all round
 *   when null).
 * - `torus`: a ring of a round tube (a volute, a bend, a stiffening ring) about unit `axis`
 *   through `centre`, `radius` to the tube's centre line, `tube` thick, over `arc` (degrees ccw
 *   about the axis from `ref`, else from {@link ringBasis}'s first direction; all round when null);
 * - `frustum`: a rectangular frustum (a hopper, a plenum, a fan cowl) from `start` to `end`,
 *   `size` [a, b] at the start and `sizeEnd` at the end, along {@link frustumBasis}'s directions.
 */
export type Prim =
  | { kind: "box"; centre: Vec3; size: Vec3; rotationZ: number }
  | { kind: "cylinder"; start: Vec3; end: Vec3; radius: number; radiusEnd: number }
  | { kind: "cap"; centre: Vec3; axis: Vec3; radius: number; depth: number }
  | { kind: "ellipsoid"; centre: Vec3; radii: Vec3; rotationZ: number }
  | { kind: "elbow"; start: Vec3; corner: Vec3; end: Vec3; radius: number }
  | { kind: "beam"; start: Vec3; end: Vec3; width: number; depth: number }
  | { kind: "annulus"; centre: Vec3; inner: number; outer: number; depth: number; arc: [number, number] | null }
  | { kind: "torus"; centre: Vec3; axis: Vec3; radius: number; tube: number; arc: [number, number] | null; ref?: Vec3 | null }
  | { kind: "frustum"; start: Vec3; end: Vec3; size: [number, number]; sizeEnd: [number, number]; rotationZ: number };

export type Source = "generated" | "pinned" | "declared";

export interface MeshSpec {
  /** Unique within the scene. */
  key: string;
  layer: LayerId;
  /** The item a click on it selects (`kind:id`). */
  item: string;
  prim: Prim;
  /** Colour in the normal display mode. */
  color: string;
  /** Pipes: the colour by pipe class (the normal colour is by service). */
  classColor?: string;
  /** Rendering hint that also batches meshes: `shell`, `steel`, `casing`, `motor`, `pipe`, ... */
  material: string;
  opacity: number;
  source: Source | null;
  clash: boolean;
  /** Part of a generated object to review (a `direct` pipe route, a proposed platform). */
  review?: boolean;
  /**
   * Level of detail: absent at every distance; 1 the envelope, drawn from afar only; 2 the
   * detail, drawn close up only (an item's detail replaces its envelope near the camera).
   */
  lod?: number;
}

/** Colour of objects to review in the provenance mode. */
export const REVIEW_COLOR = "#e11d48";

export const PROVENANCE_COLORS: Record<Source | "unknown", string> = {
  generated: "#1c9fb0",
  pinned: "#8b5cf6",
  declared: "#8a939e",
  unknown: "#c3c8ce",
};

export function provenanceColor(source: string | null | undefined): string {
  return source === "generated" || source === "pinned" || source === "declared" ? PROVENANCE_COLORS[source] : PROVENANCE_COLORS.unknown;
}

const asSource = (s: string | null | undefined): Source | null =>
  s === "generated" || s === "pinned" || s === "declared" ? s : null;

/** Equipment part colours by `material` hint; the shell takes the item's type colour. */
export const MATERIAL_COLORS: Record<string, string> = {
  steel: "#6b7480",
  casing: "#4f6d8f",
  motor: "#3e7c59",
  plates: "#a07a3c",
  fan: "#8c96a3",
  opening: "#24282d",
  concrete: "#a8a59d",
  stainless: "#c4cad1",
  galvanised: "#a3abb3",
  insulation_jacket: "#d3d8de",
  grating: "#9aa3ad",
  handrail: "#e0a526",
  guard: "#e0a526",
  flange: "#8a929b",
  insulation: "#cfd6dd",
  instrument: "#0e7490",
  valve: "#c2410c",
  handwheel: "#b42318",
  actuator: "#4b6a8f",
};

/** Cable trays by system: power and instrument trays apart at a glance. */
export const TRAY_COLORS: Record<string, string> & { power: string; instrument: string } = { power: "#c2410c", instrument: "#0e7490" };
/** Ducts by air system (the usual HVAC colour code: supply blue, extract yellow, outdoor green, exhaust brown). */
export const DUCT_COLORS: Record<string, string> & { supply: string; extract: string; outdoor: string; exhaust: string } = { supply: "#3b82f6", extract: "#d4a017", outdoor: "#22a35a", exhaust: "#8b5a2b" };
/** Colour of a penetration's sleeve. */
export const PENETRATION_COLOR = "#e11d48";

/** Colours of steel, platform and wall parts by `material`. */
export const STRUCTURE_COLORS: Record<string, string> = {
  steel: "#5b6573",
  grating: "#9aa3ad",
  handrail: "#e0a526",
  cage: "#e0a526",
  casing: "#b7c3d0",
  cladding: "#a9b4c2",
  fire_wall: "#b9a58c",
  concrete: "#a8a59d",
  painted: "#5b6573",
  stainless: "#c4cad1",
  galvanised: "#a3abb3",
  insulation_jacket: "#d3d8de",
  guard: "#e0a526",
  flange: "#8a929b",
  roof: "#8f9aa6",
  door: "#6b7a8c",
  glass: "#9cc3dd",
  louvre: "#a9b4c2",
  crane: "#e0a526",
  tray_power: TRAY_COLORS.power,
  tray_instrument: TRAY_COLORS.instrument,
  junction_box: "#4b5563",
  ahu: "#8fa3b8",
  duct_supply: DUCT_COLORS.supply,
  duct_extract: DUCT_COLORS.extract,
  duct_outdoor: DUCT_COLORS.outdoor,
  duct_exhaust: DUCT_COLORS.exhaust,
  grille_supply: "#bfdbfe",
  grille_extract: "#fde68a",
};
/** Opacity of steel, platform and wall parts by `material` (solid otherwise). */
export const STRUCTURE_OPACITY: Record<string, number> = { grating: 0.55, cage: 0.5, casing: 0.6, cladding: 0.45, fire_wall: 0.7, roof: 0.45, door: 0.6, glass: 0.3, louvre: 0.6 };
/** Materials drawn on the platforms layer (the rest of the steel goes on the structures layer). */
const PLATFORM_MATERIALS = new Set(["grating", "handrail", "cage"]);

export const NOZZLE_COLOR = "#d9dde2";
export const ENVELOPE_COLOR = "#22a35a";
export const STEEL_COLOR = "#5b6573";
export const VALVE_COLOR = "#c2410c";
export const INSTRUMENT_COLOR = "#0e7490";

/**
 * Service families: a pipe's colour by its line-number prefix (`LOX`, `CW`) or a word of its
 * fluid (`Liquid oxygen`, `Cooling water`), so related services share a colour and a legend row.
 * Words are tried before prefixes (`Waste nitrogen` is nitrogen, not water).
 */
export const SERVICE_FAMILIES: { name: string; code: RegExp; words: RegExp; color: string }[] = [
  { name: "oxygen", code: /^(lox|gox|o2|oxy)/, words: /oxygen/, color: "#2563eb" },
  { name: "nitrogen", code: /^(lin|gan|n2|nit|wn2|wn)/, words: /nitrogen/, color: "#b8860b" },
  { name: "argon", code: /^(lar|gar|ar)/, words: /argon/, color: "#9333ea" },
  { name: "instrument air", code: /^(ia|instr)/, words: /instrument air/, color: "#38bdf8" },
  { name: "air", code: /^(air|pa|ma)/, words: /\bair\b/, color: "#60a5fa" },
  { name: "water", code: /^(cw|cwr|cws|chw|bfw|w|wat)/, words: /water/, color: "#16a34a" },
  { name: "steam", code: /^(st|lps|mps|hps|steam|cond)/, words: /steam|condensate/, color: "#94a3b8" },
  { name: "vent & flare", code: /^(vent|vnt|vg|fl|flare)/, words: /\bvent|flare/, color: "#78716c" },
];
/** @deprecated The prefix patterns of {@link SERVICE_FAMILIES}. */
export const SERVICE_COLORS: [RegExp, string][] = SERVICE_FAMILIES.map((f) => [f.code, f.color]);

/** The family of a service (`oxygen`, `water`, ...), or null for one of its own. */
export function serviceFamily(service: string): string | null {
  const lower = service.toLowerCase().trim();
  if (!lower) return null;
  for (const f of SERVICE_FAMILIES) if (f.words.test(lower)) return f.name;
  for (const f of SERVICE_FAMILIES) if (f.code.test(lower)) return f.name;
  return null;
}
const PALETTE = ["#0f766e", "#7c3aed", "#ca8a04", "#0369a1", "#be185d", "#4d7c0f", "#9a3412", "#475569"] as const;

function hashColor(key: string): string {
  let hash = 0;
  for (const ch of key) hash = (hash * 31 + ch.charCodeAt(0)) >>> 0;
  return PALETTE[hash % PALETTE.length] ?? PALETTE[0];
}

/** The service a pipe carries: its `fluid`, else the letters before the line number. */
export function pipeService(pipe: Pick<ModelPipe, "fluid" | "line" | "id">): string {
  if (pipe.fluid) return pipe.fluid;
  const match = /^([A-Za-z]+)/.exec(pipe.line || pipe.id);
  return match?.[1] ?? "";
}

/** Code, colour and material of a pipe's class (`{code, material?, colour?}`). */
export function pipeClassOf(pipe: Pick<ModelPipe, "class">): { code: string; colour: string | null; material: string | null } {
  const c = pipe.class;
  if (!c) return { code: "", colour: null, material: null };
  return { code: c.code ?? "", colour: c.colour && /^#[0-9a-f]{6}$/i.test(c.colour) ? c.colour : null, material: c.material ?? null };
}

export function serviceColor(service: string): string {
  const lower = service.toLowerCase();
  const family = serviceFamily(lower);
  if (family) return SERVICE_FAMILIES.find((f) => f.name === family)!.color;
  return lower ? hashColor(lower) : PALETTE[7];
}

/**
 * Colours of the pipe classes: the class's own colour (from `piping/pipe-specs.yaml`) when the
 * model gives one, else the palette in order of first appearance, so classes stay apart.
 */
export function classColors(pipes: readonly Pick<ModelPipe, "class">[]): Map<string, string> {
  const out = new Map<string, string>();
  let next = 0;
  for (const p of pipes) {
    const { code: cls, colour } = pipeClassOf(p);
    if (out.has(cls)) continue;
    if (colour) out.set(cls, colour);
    else if (!cls) out.set(cls, PALETTE[7]);
    else out.set(cls, PALETTE[next++ % 7]!);
  }
  return out;
}

export const ZONE_COLORS: Record<string, string> = {
  hazardous: "#eab308",
  oxygen_enriched: "#3b82f6",
  oxygen_deficient: "#a855f7",
  keep_clear: "#f97316",
  laydown: "#84cc16",
  maintenance: "#06b6d4",
  escape: "#22c55e",
  crane_pad: "#a16207",
};

export function zoneColor(kind: string): string {
  return ZONE_COLORS[kind] ?? "#94a3b8";
}

/** A lighter tint of `#rrggbb` (`amount` 0..1 towards white). */
export function lighten(color: string, amount = 0.5): string {
  const m = /^#([0-9a-f]{6})$/i.exec(color);
  if (!m) return color;
  const n = parseInt(m[1]!, 16);
  const ch = (shift: number) => {
    const c = (n >> shift) & 255;
    return Math.round(c + (255 - c) * amount)
      .toString(16)
      .padStart(2, "0");
  };
  return `#${ch(16)}${ch(8)}${ch(0)}`;
}

/** Outside diameters (m) by DN (ISO 6708 / EN 10220 series), for nozzles (the model gives pipes their OD). */
export const DN_OD: Record<number, number> = {
  15: 0.0213, 20: 0.0269, 25: 0.0337, 32: 0.0424, 40: 0.0483, 50: 0.0603, 65: 0.0761, 80: 0.0889,
  100: 0.1143, 125: 0.1397, 150: 0.1683, 200: 0.2191, 250: 0.273, 300: 0.3239, 350: 0.3556,
  400: 0.4064, 450: 0.457, 500: 0.508, 600: 0.61, 700: 0.711, 800: 0.813, 900: 0.914, 1000: 1.016,
  1200: 1.219, 1400: 1.422, 1600: 1.626, 1800: 1.829, 2000: 2.032,
};

/** OD in m for a DN: the table, else DN / 1000 plus 2 %. */
export function odOf(dn: number | null | undefined): number {
  if (!dn || dn <= 0) return 0.1;
  return DN_OD[dn] ?? Math.round(dn * 1.02) / 1000;
}

const sub = (a: Vec3, b: Vec3): Vec3 => [a[0] - b[0], a[1] - b[1], a[2] - b[2]];
const add = (a: Vec3, b: Vec3): Vec3 => [a[0] + b[0], a[1] + b[1], a[2] + b[2]];
const scale = (a: Vec3, k: number): Vec3 => [a[0] * k, a[1] * k, a[2] * k];
const dot = (a: Vec3, b: Vec3) => a[0] * b[0] + a[1] * b[1] + a[2] * b[2];
export const length3 = (a: Vec3) => Math.hypot(a[0], a[1], a[2]);
const norm = (a: Vec3): Vec3 => {
  const l = length3(a);
  return l > 1e-12 ? scale(a, 1 / l) : [0, 0, 1];
};
const r6 = (v: number) => Math.round(v * 1e6) / 1e6;
const round3 = (v: Vec3): Vec3 => [r6(v[0]), r6(v[1]), r6(v[2])];

const cross = (a: Vec3, b: Vec3): Vec3 => [a[1] * b[2] - a[2] * b[1], a[2] * b[0] - a[0] * b[2], a[0] * b[1] - a[1] * b[0]];

const isVec3 = (v: unknown): v is Vec3 => Array.isArray(v) && v.length === 3 && v.every((n) => typeof n === "number" && Number.isFinite(n));
const isPair = (v: unknown): v is [number, number] => Array.isArray(v) && v.length === 2 && v.every((n) => typeof n === "number" && Number.isFinite(n));
const pos = (v: unknown, fallback: number) => (typeof v === "number" && Number.isFinite(v) && v > 0 ? v : fallback);

/** Length of a polyline. */
export function polylineLength(points: readonly XYZ[]): number {
  let total = 0;
  for (let i = 1; i < points.length; i++) total += length3(sub(points[i]!, points[i - 1]!));
  return total;
}

/**
 * A pipe route as straight runs and elbows: each inner corner is rounded with a bend of
 * `bendRadius` (shortened where the legs are too short for it), straight legs are trimmed to
 * meet the bends, and points that repeat or lie on a straight line make no elbow.
 */
export function pipeRun(points: readonly XYZ[], bendRadius: number): { straights: [Vec3, Vec3][]; elbows: { start: Vec3; corner: Vec3; end: Vec3 }[] } {
  const pts: Vec3[] = [];
  for (const p of points) if (isVec3(p) && (!pts.length || length3(sub(p, pts[pts.length - 1]!)) > 1e-9)) pts.push([...p]);
  const straights: [Vec3, Vec3][] = [];
  const elbows: { start: Vec3; corner: Vec3; end: Vec3 }[] = [];
  if (pts.length < 2) return { straights, elbows };
  // Trim at each inner point: how far the bend reaches back and forward along the legs.
  const trim: number[] = pts.map(() => 0);
  for (let i = 1; i < pts.length - 1; i++) {
    const a = norm(sub(pts[i]!, pts[i - 1]!));
    const b = norm(sub(pts[i + 1]!, pts[i]!));
    const cos = Math.min(Math.max(dot(a, b), -1), 1);
    const angle = Math.acos(cos);
    if (angle < 1e-3) continue;
    const reach = bendRadius * Math.tan(angle / 2);
    const legIn = length3(sub(pts[i]!, pts[i - 1]!));
    const legOut = length3(sub(pts[i + 1]!, pts[i]!));
    trim[i] = Math.min(reach, legIn / 2, legOut / 2);
  }
  let from: Vec3 = pts[0]!;
  for (let i = 1; i < pts.length; i++) {
    const corner = pts[i]!;
    const dirIn = norm(sub(corner, pts[i - 1]!));
    const t = trim[i] ?? 0;
    const to = t > 0 ? add(corner, scale(dirIn, -t)) : corner;
    if (length3(sub(to, from)) > 1e-9) straights.push([round3(from), round3(to)]);
    if (t > 0) {
      const dirOut = norm(sub(pts[i + 1]!, corner));
      const end = add(corner, scale(dirOut, t));
      elbows.push({ start: round3(to), corner: round3(corner), end: round3(end) });
      from = end;
    } else from = corner;
  }
  return { straights, elbows };
}

/** Eight corners of a box turned `rotationZ` about its centre. */
export function boxCorners(centre: Vec3, size: Vec3, rotationZ = 0): Vec3[] {
  const c = Math.cos(rotationZ);
  const s = Math.sin(rotationZ);
  const out: Vec3[] = [];
  for (const dz of [-1, 1])
    for (const [dx, dy] of [
      [-1, -1],
      [1, -1],
      [1, 1],
      [-1, 1],
    ] as const) {
      const x = (dx * size[0]) / 2;
      const y = (dy * size[1]) / 2;
      out.push(round3([centre[0] + x * c - y * s, centre[1] + x * s + y * c, centre[2] + (dz * size[2]) / 2]));
    }
  return out;
}

/** The twelve edges of a box, for wireframes. */
export function boxEdges(centre: Vec3, size: Vec3, rotationZ = 0): [Vec3, Vec3][] {
  const k = boxCorners(centre, size, rotationZ);
  const e: [number, number][] = [
    [0, 1], [1, 2], [2, 3], [3, 0],
    [4, 5], [5, 6], [6, 7], [7, 4],
    [0, 4], [1, 5], [2, 6], [3, 7],
  ];
  return e.map(([a, b]) => [k[a]!, k[b]!]);
}

export interface Box3 {
  min: Vec3;
  max: Vec3;
}

/** Axis-aligned bounds of a primitive (conservative for rotated or curved ones). */
export function primBounds(prim: Prim): Box3 {
  const pts: Vec3[] = [];
  let pad: number | Vec3 = 0;
  // A disc of radius r normal to unit axis a reaches r * sqrt(1 - a_i^2) along axis i.
  const disc = (a: Vec3, r: number): Vec3 => [r * Math.sqrt(Math.max(1 - a[0] ** 2, 0)), r * Math.sqrt(Math.max(1 - a[1] ** 2, 0)), r * Math.sqrt(Math.max(1 - a[2] ** 2, 0))];
  switch (prim.kind) {
    case "box":
      pts.push(...boxCorners(prim.centre, prim.size, prim.rotationZ));
      break;
    case "cylinder":
      pts.push(prim.start, prim.end);
      pad = disc(norm(sub(prim.end, prim.start)), Math.max(prim.radius, prim.radiusEnd));
      break;
    case "cap":
      pts.push(prim.centre, add(prim.centre, scale(norm(prim.axis), prim.depth)));
      pad = disc(norm(prim.axis), prim.radius);
      break;
    case "ellipsoid":
      pts.push(prim.centre);
      pad = Math.max(...prim.radii);
      break;
    case "elbow":
      pts.push(prim.start, prim.corner, prim.end);
      pad = prim.radius;
      break;
    case "beam":
      pts.push(prim.start, prim.end);
      pad = Math.max(prim.width, prim.depth) / 2;
      break;
    case "annulus":
      pts.push([prim.centre[0], prim.centre[1], prim.centre[2] - prim.depth], prim.centre);
      pad = [prim.outer, prim.outer, 0];
      break;
    case "torus": {
      const a = norm(prim.axis);
      pts.push(add(prim.centre, scale(a, prim.tube)), add(prim.centre, scale(a, -prim.tube)));
      pad = disc(a, prim.radius + prim.tube);
      break;
    }
    case "frustum":
      pts.push(...frustumCorners(prim));
      break;
  }
  const min: Vec3 = [Infinity, Infinity, Infinity];
  const max: Vec3 = [-Infinity, -Infinity, -Infinity];
  const padding: Vec3 = typeof pad === "number" ? [pad, pad, pad] : pad;
  for (const p of pts)
    for (let i = 0; i < 3; i++) {
      min[i] = r6(Math.min(min[i]!, p[i]! - padding[i]!));
      max[i] = r6(Math.max(max[i]!, p[i]! + padding[i]!));
    }
  return { min, max };
}

/**
 * The plane of a torus: two unit directions normal to `axis`, the first one where its arc starts.
 * About a near-vertical axis the first is east (+x), as for an annulus; about any other axis it
 * is the upward direction in the ring's plane.
 */
export function ringBasis(axis: Vec3, ref?: Vec3 | null): [Vec3, Vec3] {
  const a = norm(axis);
  if (ref && isVec3(ref)) {
    // The given start direction, made normal to the axis.
    const r = sub(ref, scale(a, dot(ref, a)));
    if (length3(r) > 1e-9) {
      const u = norm(r);
      return [u, cross(a, u)];
    }
  }
  const u: Vec3 = Math.abs(a[2]) > 0.9 ? norm(sub([1, 0, 0], scale(a, a[0]))) : norm(sub([0, 0, 1], scale(a, a[2])));
  return [u, cross(a, u)];
}

/**
 * The cross-section directions of a frustum from `start` to `end`: `size[0]` runs along the first,
 * `size[1]` along the second. Vertical: east and north turned `rotationZ` about z; otherwise the
 * horizontal normal to the axis and the one above it.
 */
export function frustumBasis(start: Vec3, end: Vec3, rotationZ: number): [Vec3, Vec3] {
  const a = norm(sub(end, start));
  if (Math.abs(a[2]) > 0.9) {
    const u: Vec3 = [Math.cos(rotationZ), Math.sin(rotationZ), 0];
    return [u, norm(cross(a, u))];
  }
  const u = norm(cross([0, 0, 1], a));
  return [u, norm(cross(a, u))];
}

/** The 8 corners of a frustum: the start face, then the end face (each ccw about the axis). */
export function frustumCorners(prim: Extract<Prim, { kind: "frustum" }>): Vec3[] {
  const [u, v] = frustumBasis(prim.start, prim.end, prim.rotationZ);
  const face = (c: Vec3, [a, b]: [number, number]): Vec3[] =>
    [
      [-1, -1],
      [1, -1],
      [1, 1],
      [-1, 1],
    ].map(([i, j]) => add(add(c, scale(u, (i! * a) / 2)), scale(v, (j! * b) / 2)));
  return [...face(prim.start, prim.size), ...face(prim.end, prim.sizeEnd)];
}

export function unionBox(a: Box3 | undefined, b: Box3): Box3 {
  if (!a) return { min: [...b.min], max: [...b.max] };
  return {
    min: [Math.min(a.min[0], b.min[0]), Math.min(a.min[1], b.min[1]), Math.min(a.min[2], b.min[2])],
    max: [Math.max(a.max[0], b.max[0]), Math.max(a.max[1], b.max[1]), Math.max(a.max[2], b.max[2])],
  };
}

/** What the side panel shows for a picked model object. */
export type ModelItemKind =
  | "equipment"
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

export interface ModelItemInfo {
  kind: ModelItemKind;
  id: string;
  title: string | null;
  type: string | null;
  source: Source | null;
  details: [string, string][];
  /** Repo path of the P&ID sheet, and the DEXPI id to highlight on it. */
  sheetFile: string | null;
  highlight: string | null;
  /** Item keys of related objects: an item's nozzles, a pipe's ends, a nozzle's item. */
  related: { key: string; label: string }[];
  line: string | null;
  /** A generated proposal or fallback to review. */
  review: boolean;
}

export interface ModelLabel {
  key: string;
  layer: LayerId;
  text: string;
  position: Vec3;
  item: string;
}

export interface ModelScene {
  meshes: MeshSpec[];
  /** Wireframe edges (envelopes, structure outlines), per item. */
  edges: { key: string; layer: LayerId; color: string; segments: [Vec3, Vec3][]; item: string }[];
  labels: ModelLabel[];
  items: Map<string, ModelItemInfo>;
  /** Bounds per item key, for camera focus and finding boxes. */
  itemBounds: Map<string, Box3>;
  /** Any id a link may name (tag, DEXPI id, segment, line, nozzle id) -> item key. */
  ids: Map<string, string>;
  /** Equipment tags the model draws (the fallback primitive is left out for them). */
  tags: Set<string>;
  /** Floors to walk on: building levels and decks (the ground is always one). */
  floors: Floor[];
  counts: Record<string, number>;
  /**
   * What a selection marks besides itself: a motor's or instrument's cable route (its trays,
   * junction box and the cable's path), a unit's or room's ducts. Keyed by item.
   */
  routes: Map<string, ItemRoute>;
  /** Generated proposals to review, by what they are (`stair`, `ladder`, `step-over`, ...): item keys. */
  proposals: Map<string, string[]>;
}

/** Items to mark with a selection, and polylines to draw (a cable's way). */
export interface ItemRoute {
  items: string[];
  paths: Vec3[][];
}

/** A walkable floor: `elevation` over a plan polygon. */
export interface Floor {
  id: string;
  elevation: number;
  polygon: [number, number][];
}

const fmt = (n: number) => String(Math.round(n * 1000) / 1000);
const fmtVec = (v: readonly number[]) => `[${v.map(fmt).join(", ")}]`;

/** A roof opening, in the owner's plan frame: `offset` and `width` along its own x
 * from its origin corner, `sill` and `height` along its own y. */
const roofOpening = (o: BuildingOpening, owner: string): string => {
  const y0 = o.sill ?? 0;
  return `${fmt(o.width)} x ${fmt(o.height)} m in the roof, x ${fmt(o.offset)} to ${fmt(o.offset + o.width)} m and y ${fmt(y0)} to ${fmt(y0 + o.height)} m from ${owner}'s origin corner`;
};

/**
 * Repo path of the sheet a model ref names (core writes it repo-relative, `pid/P-01.xml`): the
 * repo's sheet with that file or id, else the ref as it is.
 */
export function repoSheet(sheet: string | null | undefined, sheets: Sheet[] = []): string | null {
  if (!sheet) return null;
  return sheets.find((s) => s.file === sheet || s.id === sheet)?.file ?? sheet;
}

export interface ModelOptions {
  sheets?: Sheet[] | undefined;
  /** `kind:id` keys that clash. */
  clash?: Set<string>;
  /** Equipment colour by type (the scene's palette). */
  equipmentColor?: (type: string | null | undefined) => string;
}

/** What makes two in-line entries the same component: its sheet, DEXPI id and point (to the mm). */
export function inlineIdentity(inline: Pick<ModelInlineItem, "id" | "point" | "refs">): string {
  const dexpi = inline.refs?.dexpi;
  if (!dexpi) return `id:${inline.id}`;
  const p = isVec3(inline.point) ? inline.point.map((v) => Math.round(v * 1000)).join(",") : "";
  return `${inline.refs?.sheet ?? ""}|${dexpi}|${p}`;
}

/** The mesh description of a generated model. */
export function buildModelScene(model: LayoutModel, options: ModelOptions = {}): ModelScene {
  const meshes: MeshSpec[] = [];
  const edges: ModelScene["edges"] = [];
  const labels: ModelLabel[] = [];
  const items = new Map<string, ModelItemInfo>();
  const itemBounds = new Map<string, Box3>();
  const ids = new Map<string, string>();
  const tags = new Set<string>();
  const floors: Floor[] = [];
  const routes = new Map<string, ItemRoute>();
  const proposals = new Map<string, string[]>();
  const propose = (what: string, key: string) => {
    const list = proposals.get(what) ?? [];
    if (!list.includes(key)) list.push(key);
    proposals.set(what, list);
  };
  const clash = options.clash ?? new Set<string>();
  const colorOf = options.equipmentColor ?? (() => "#5f7486");
  const sheets = options.sheets ?? [];

  // Detail (lod 2) may reach past an item's envelope (foundations, treads): its bounds count only
  // for an item that has nothing else.
  const detailBounds = new Map<string, Box3>();
  const push = (spec: Omit<MeshSpec, "clash"> & { clash?: boolean }) => {
    const mesh: MeshSpec = { clash: false, ...spec };
    meshes.push(mesh);
    const bounds = mesh.lod === 2 ? detailBounds : itemBounds;
    bounds.set(mesh.item, unionBox(bounds.get(mesh.item), primBounds(mesh.prim)));
  };
  const index = (id: string | null | undefined, key: string) => {
    if (id && !ids.has(id)) ids.set(id, key);
  };

  const byClass = classColors(model.pipes);
  /** Core's model with levels of detail (nozzle points on the flange face). */
  const detailed = model.equipment.some((e) => e.parts.some((p) => typeof p.lod === "number"));
  const nozzleRefs = new Map<string, { segments: string[] }>();
  const remoteMounts: { eq: ModelEquipment; nozzle: ModelNozzle; key: string; from: Vec3; detail: boolean }[] = [];
  for (const eq of model.equipment) equipment(eq);
  const pipeOd = new Map<string, number>();
  const inlineSeen = new Map<string, string>();
  for (const pipe of model.pipes) pipeMeshes(pipe);
  for (const inline of model.inline) inlineMeshes(inline);
  for (const structure of model.structures) structureMeshes(structure);
  for (const platform of model.platforms) platformMeshes(platform);
  for (const rack of model.racks) {
    steelParts(rack.parts, `rack:${rack.id}`, "structures", asSource(rack.source));
    for (const ladder of rack.ladders ?? []) {
      if (ladder.review_needed) {
        accessProposal(ladder, "ladder", rack.id, `rack:${rack.id}`);
        continue;
      }
      index(ladder.id, `rack:${rack.id}`);
      steelParts(ladder.parts, `rack:${rack.id}`, "platforms", asSource(ladder.source) ?? asSource(rack.source));
    }
  }
  // Bund walls: concrete, solid, with the steel.
  for (const area of model.areas ?? []) if (area.parts?.length) steelParts(area.parts, `area:${area.id}`, "structures", asSource(area.source));
  for (const support of model.supports ?? []) supportMeshes(support);
  // How a pipe is carried: its shoes and guides.
  const carried = new Map<string, Record<string, number>>();
  for (const support of model.supports ?? []) {
    const byKind = carried.get(support.pipe) ?? {};
    byKind[support.kind] = (byKind[support.kind] ?? 0) + 1;
    carried.set(support.pipe, byKind);
  }
  for (const [pipe, byKind] of carried)
    items.get(`pipe:${pipe}`)?.details.push(["supports", Object.entries(byKind).map(([kind, n]) => `${n} ${kind}${n === 1 ? "" : "s"}`).join(", ")]);
  for (const steel of model.support_steel ?? []) supportSteelMeshes(steel);
  for (const stepOver of model.step_overs ?? []) stepOverMeshes(stepOver);
  for (const penetration of model.penetrations ?? []) penetrationMeshes(penetration);
  // Cabling: tray tiers (with their rack), trays, junction boxes, the cables' routes.
  for (const tier of model.tray_tiers ?? []) steelParts(tier.parts, `rack:${tier.rack}`, "trays", asSource(tier.source));
  const trays = new Map((model.trays ?? []).map((t) => [t.id, t]));
  for (const tray of model.trays ?? []) trayMeshes(tray);
  for (const jb of model.junction_boxes ?? []) junctionBoxMeshes(jb);
  cableItems(model.cables ?? []);
  // HVAC: units, ducts, rooms with their terminals.
  for (const unit of model.hvac_units ?? []) hvacUnitMeshes(unit);
  for (const duct of model.ducts ?? []) ductMeshes(duct);
  for (const room of model.hvac_rooms ?? []) hvacRoomMeshes(room);
  for (const zone of model.zones) zoneMeshes(zone);
  for (const b of model.buildings) steelParts(b.parts, `building:${b.id}`, "buildings", asSource(b.source));
  for (const b of model.buildings)
    for (const level of b.levels) {
      const top = level.kind === "roof" || level.kind === "platform" ? level.elevation + (level.kind === "roof" ? 0.3 : 0.2) : level.elevation;
      const [x0, y0, x1, y1] = b.footprint;
      floors.push({ id: `${b.id}/${level.id}`, elevation: top, polygon: [[x0, y0], [x1, y0], [x1, y1], [x0, y1]] });
    }
  // Declared operators and casing hatches: the model declares them but has no geometry for them,
  // so the viewer draws them (schematic) once every floor is known.
  const standing = floors.filter((f) => !STAIR_FLIGHT.test(f.id));
  for (const inline of model.inline) if (inline.operator) operatorMeshes(inline, inline.operator);
  for (const mount of remoteMounts) remoteMountMeshes(mount);
  for (const st of model.structures)
    for (const opening of st.openings ?? []) if (opening.kind === "hatch") hatchMeshes(opening, { id: st.id, key: `structure:${st.id}`, origin: st.origin, rotation: st.rotation_deg, width: st.width, depth: st.depth, walls: st.walls, layer: "structures" });
  for (const b of model.buildings)
    for (const opening of b.openings ?? []) if (opening.kind === "hatch") hatchMeshes(opening, { id: b.id, key: `building:${b.id}`, origin: b.origin, rotation: b.rotation_deg, width: b.width, depth: b.depth, walls: b.parts, layer: "buildings" });

  for (const [item, box] of detailBounds) if (!itemBounds.has(item)) itemBounds.set(item, box);

  const counts: Record<string, number> = {};
  for (const m of meshes) counts[m.layer] = (counts[m.layer] ?? 0) + 1;
  return { meshes, edges, labels, items, itemBounds, ids, tags, floors, counts, routes, proposals };

  function equipment(eq: ModelEquipment): void {
    const key = `equipment:${eq.tag}`;
    tags.add(eq.tag);
    index(eq.tag, key);
    index(eq.refs?.dexpi, key);
    const isClash = clash.has(key);
    const shellColor = colorOf(eq.type);
    const source = asSource(eq.source);
    // A nozzle's own detail (`<tag>/<nozzle>/neck|flange|transmitter|...`) belongs to the nozzle.
    const nozzleIds = new Set((eq.nozzles ?? []).map((n) => n.id));
    const nozzleParts = new Map<string, ModelPart[]>();
    for (const part of eq.parts) {
      const cut = part.id.lastIndexOf("/");
      const owner = cut > 0 ? part.id.slice(0, cut) : "";
      if (nozzleIds.has(owner)) {
        nozzleParts.set(owner, [...(nozzleParts.get(owner) ?? []), part]);
        continue;
      }
      const prim = partPrim(part);
      if (!prim) continue;
      index(part.id, key);
      const color = (part.material === "shell" ? undefined : MATERIAL_COLORS[part.material]) || shellColor;
      push({ key: part.id, layer: "equipment", item: key, prim, color, material: part.material || "shell", opacity: 1, source: asSource(part.source) ?? source, clash: isClash, ...lodOf(part) });
    }
    const [x0, y0, z0, x1, y1, z1] = eq.bbox;
    itemBounds.set(key, unionBox(itemBounds.get(key), { min: [x0, y0, z0], max: [x1, y1, z1] }));
    const sheetFile = repoSheet(eq.refs.sheet, sheets);
    const dims = Object.entries(eq.dimensions ?? {}).map(([k, v]) => `${k} ${typeof v === "number" ? `${fmt(v)} m` : v}`);
    const related: { key: string; label: string }[] = [];
    for (const nozzle of eq.nozzles ?? []) {
      const nkey = `nozzle:${nozzle.id}`;
      related.push({ key: nkey, label: `${nozzle.name}${nozzle.dn ? ` DN ${nozzle.dn}` : ""}` });
      index(nozzle.id, nkey);
      index(nozzle.refs?.dexpi, nkey);
      const d = norm(nozzle.direction);
      const od = odOf(nozzle.dn ?? null);
      const stub = Math.max(0.15, Math.min(od * 1.5, 0.6));
      const r = Math.max(od / 2, 0.03);
      // A transmitter declared remote-mounted (`operators:`) sits on its stand, not on the tapping:
      // core's head and bracket give way to the viewer's stand (drawn after the floors are known).
      const remote = nozzle.operator?.kind === "remote_mount";
      const all = nozzleParts.get(nozzle.id) ?? [];
      const own = remote ? all.filter((part) => !REMOTE_HEAD_PARTS.test(part.id)) : all;
      if (remote) remoteMounts.push({ eq, nozzle, key: nkey, from: remoteStart(nozzle, all), detail: all.length > 0 });
      // Core's model with levels of detail puts `point` on the flange face (the neck from `base`);
      // an older one on the shell, the viewer drawing the stub outward.
      const start: Vec3 = detailed ? (isVec3(nozzle.base) ? [...nozzle.base] : round3(add(nozzle.point, scale(d, -Math.min(stub, 0.15))))) : [...nozzle.point];
      const end: Vec3 = detailed ? [...nozzle.point] : round3(add(nozzle.point, scale(d, stub)));
      // With core's own neck and flange, the viewer's stand-in only from afar.
      const far = own.length ? { lod: 1 } : {};
      push({ key: nkey, layer: "nozzles", item: nkey, prim: { kind: "cylinder", start, end, radius: r, radiusEnd: r }, color: NOZZLE_COLOR, material: "nozzle", opacity: 1, source: asSource(nozzle.source), ...far });
      // A flange ring at the end of the stub.
      const flange = add(end, scale(d, -0.03));
      push({ key: `${nkey}:flange`, layer: "nozzles", item: nkey, prim: { kind: "cylinder", start: round3(flange), end: [...end], radius: r * 1.6, radiusEnd: r * 1.6 }, color: NOZZLE_COLOR, material: "nozzle", opacity: 1, source: asSource(nozzle.source), ...far });
      for (const part of own) {
        const prim = partPrim(part);
        if (!prim) continue;
        index(part.id, nkey);
        const color = part.material === "instrument" ? INSTRUMENT_COLOR : (MATERIAL_COLORS[part.material] ?? NOZZLE_COLOR);
        push({ key: part.id, layer: "nozzles", item: nkey, prim, color, material: part.material || "nozzle", opacity: 1, source: asSource(part.source) ?? asSource(nozzle.source), ...lodOf(part) });
      }
      const lines = nozzle.refs?.lines ?? [];
      const segments = nozzle.refs?.segments ?? [];
      nozzleRefs.set(nkey, { segments });
      items.set(nkey, {
        kind: "nozzle",
        id: nozzle.id,
        title: `${eq.tag} nozzle ${nozzle.name}`,
        type: nozzle.dn ? `DN ${nozzle.dn}` : null,
        source: asSource(nozzle.source),
        details: [
          ["point", fmtVec(nozzle.point)],
          ["direction", fmtVec(nozzle.direction)],
          ["placed by", nozzle.basis + (nozzle.side ? ` (${nozzle.side} side on the P&ID)` : "")],
          ...(lines.length ? [["lines", lines.join(", ")] as [string, string]] : []),
          ...(segments.length ? [["segments", segments.join(", ")] as [string, string]] : []),
        ],
        sheetFile: repoSheet(nozzle.refs.sheet, sheets) ?? sheetFile,
        highlight: nozzle.refs?.dexpi ?? null,
        related: [{ key, label: eq.tag }],
        line: lines[0] ?? null,
        review: false,
      });
    }
    for (const env of eq.envelopes ?? []) {
      const ekey = `envelope:${env.id}`;
      const rot = (env.rotation_deg * Math.PI) / 180;
      push({ key: ekey, layer: "envelopes", item: ekey, prim: { kind: "box", centre: [...env.centre], size: [...env.size], rotationZ: rot }, color: ENVELOPE_COLOR, material: "envelope", opacity: 0.08, source: asSource(env.source) });
      edges.push({ key: ekey, layer: "envelopes", color: ENVELOPE_COLOR, segments: boxEdges(env.centre, env.size, rot), item: ekey });
      items.set(ekey, {
        kind: "envelope",
        id: env.id,
        title: `${env.kind.replace(/_/g, " ")} space of ${eq.tag}`,
        type: env.kind,
        source: asSource(env.source),
        details: [
          ["centre", fmtVec(env.centre)],
          ["size", `${env.size.map(fmt).join(" x ")} m`],
        ],
        sheetFile: null,
        highlight: null,
        related: [{ key, label: eq.tag }],
        line: null,
        review: false,
      });
      related.push({ key: ekey, label: env.kind.replace(/_/g, " ") });
    }
    items.set(key, {
      kind: "equipment",
      id: eq.tag,
      title: null,
      type: eq.type ?? null,
      source,
      details: [
        ["family", eq.family],
        ["shape", eq.shape],
        ...(dims.length ? [["dimensions", dims.join(", ")] as [string, string]] : []),
        ["size from", eq.size_from],
        ["position", fmtVec(eq.position)],
        ...(eq.rotation_deg ? [["rotation", `${fmt(eq.rotation_deg)} deg`] as [string, string]] : []),
        ...(eq.mount ? [["mounted on", Object.entries(eq.mount).map(([k, v]) => `${k} ${v}`).join(", ")] as [string, string]] : []),
        ...(eq.plinth ? [["on a plinth", `${fmt(eq.plinth)} m`] as [string, string]] : []),
        ["bbox", fmtVec(eq.bbox)],
        ["parts", String((eq.parts ?? []).length)],
        ["nozzles", String((eq.nozzles ?? []).length)],
      ],
      sheetFile,
      highlight: eq.refs?.dexpi ?? null,
      related,
      line: null,
      review: false,
    });
  }

  function pipeMeshes(pipe: ModelPipe): void {
    const points = pipe.points.filter(isVec3);
    if (points.length < 2) return;
    const key = `pipe:${pipe.id}`;
    const od = pipe.od;
    pipeOd.set(pipe.id, od);
    const r = od / 2;
    const service = pipeService(pipe);
    const color = serviceColor(service);
    const cls = pipeClassOf(pipe);
    const pipeClass = byClass.get(cls.code) ?? PALETTE[7];
    const source = asSource(pipe.source);
    const review = Boolean(pipe.review_needed);
    // Long-radius elbows: 1.5 x OD.
    const run = pipeRun(points, 1.5 * od);
    const insulation = Math.max(pipe.insulation_mm, 0) / 1000;
    // Personnel protection is a guard, not a vapour-tight jacket: it looks different when realistic.
    const jacketMaterial = pipe.jacket === "personnel" ? "insulation_personnel" : "insulation";
    const add3 = (suffix: string, prim: Prim, layer: LayerId, c: string, cc: string, opacity: number) =>
      push({ key: `${key}:${suffix}`, layer, item: key, prim, color: c, classColor: cc, material: layer === "pipes" ? "pipe" : jacketMaterial, opacity, source, review });
    run.straights.forEach(([a, b], i) => {
      add3(`s${i}`, { kind: "cylinder", start: a, end: b, radius: r, radiusEnd: r }, "pipes", color, pipeClass, 1);
      if (insulation) add3(`i${i}`, { kind: "cylinder", start: a, end: b, radius: r + insulation, radiusEnd: r + insulation }, "insulation", lighten(color, 0.6), lighten(pipeClass, 0.6), 0.35);
    });
    run.elbows.forEach((e, i) => {
      add3(`e${i}`, { kind: "elbow", ...e, radius: r }, "pipes", color, pipeClass, 1);
      if (insulation) add3(`ie${i}`, { kind: "elbow", ...e, radius: r + insulation }, "insulation", lighten(color, 0.6), lighten(pipeClass, 0.6), 0.35);
    });
    // Core's detail along the pipe: flanges in the pipe's colours, supports in their material's.
    for (const part of pipe.parts ?? []) {
      const prim = partPrim(part);
      if (!prim) continue;
      index(part.id, key);
      const own = MATERIAL_COLORS[part.material] ?? STRUCTURE_COLORS[part.material];
      const jacket = part.material === "insulation_jacket";
      push({
        key: part.id,
        layer: jacket ? "insulation" : "pipes",
        item: key,
        prim,
        color: own && part.material !== "pipe" ? own : color,
        classColor: own && part.material !== "pipe" ? own : pipeClass,
        material: part.material || "pipe",
        opacity: 1,
        source: asSource(part.source) ?? source,
        review,
        ...lodOf(part),
      });
    }
    const { line, segment, length } = pipe;
    index(pipe.id, key);
    index(segment, key);
    index(line, key);
    const details: [string, string][] = [];
    details.push(["line", line]);
    details.push(["segment", segment + (pipe.segment_number ? ` (${pipe.segment_number})` : "")]);
    details.push(["DN", String(pipe.dn)]);
    details.push(["OD", `${fmt(od * 1000)} mm`]);
    if (cls.code) details.push(["class", cls.code + (cls.material ? `, ${cls.material}` : "")]);
    details.push(["insulation", insulation ? `${fmt(insulation * 1000)} mm` : "none"]);
    if (pipe.fluid) details.push(["fluid", pipe.fluid]);
    details.push(["length", `${fmt(length)} m`]);
    details.push(["bends", String(run.elbows.length)]);
    details.push(["routed", pipe.method + (pipe.racks?.length ? ` over ${pipe.racks.join(", ")}` : "") + (pipe.tier != null ? ` at ${fmt(pipe.tier)} m` : "")]);
    if (pipe.reason) details.push(["reason", pipe.reason]);
    if (pipe.open_ends?.length) details.push(["open end", pipe.open_ends.join(", ")]);
    if (pipe.review_needed) details.push(["status", "review needed (fallback route)"]);
    const related: { key: string; label: string }[] = [];
    // The nozzles the segment ends at.
    for (const [nozzleKey, refs] of nozzleRefs) if (refs.segments.includes(segment)) related.push({ key: nozzleKey, label: nozzleKey.slice("nozzle:".length) });
    items.set(key, {
      kind: "pipe",
      id: pipe.id,
      title: `Line ${line}`,
      type: service || null,
      source,
      details,
      sheetFile: repoSheet(pipe.refs.sheet, sheets),
      highlight: segment,
      related,
      line,
      review,
    });
    // The line number at the middle of the longest straight.
    const longest = run.straights.reduce<[Vec3, Vec3] | null>((best, s) => (!best || length3(sub(s[1], s[0])) > length3(sub(best[1], best[0])) ? s : best), null);
    if (longest)
      labels.push({ key: `label:${key}`, layer: "pipes", text: line, position: round3(add(scale(add(longest[0], longest[1]), 0.5), [0, 0, r + 0.15])), item: key });
  }

  function inlineMeshes(inline: ModelInlineItem): void {
    if (!isVec3(inline.point)) return;
    // A component two segments share may come once per segment: with the same id (older core)
    // or with ids of their own but the same DEXPI object at the same point. Either way it is one
    // item between both pipes.
    const same = inlineSeen.get(inlineIdentity(inline));
    const key = items.has(`inline:${inline.id}`) ? `inline:${inline.id}` : (same ?? `inline:${inline.id}`);
    const known = items.get(key);
    if (known) {
      mergeInline(known, inline);
      index(inline.id, key);
      return;
    }
    inlineSeen.set(inlineIdentity(inline), key);
    const od = pipeOd.get(inline.pipe) ?? odOf(null);
    const d = norm(inline.direction);
    const kind = inline.kind.toLowerCase();
    const source = asSource(inline.source);
    const p = inline.point;
    const own = (inline.parts ?? []).map((part) => [part, partPrim(part)] as const).filter((x): x is readonly [ModelPart, Prim] => x[1] !== null);
    const ownColor = /instrument|tapping|gauge|transmitter|element|item/.test(kind) ? INSTRUMENT_COLOR : VALVE_COLOR;
    if (own.length) {
      // Core's own body, operator and flanges.
      own.forEach(([part, prim], i) => {
        index(part.id, key);
        const color = (part.material === "shell" || part.material === "inline" ? undefined : MATERIAL_COLORS[part.material]) || ownColor;
        push({ key: i ? part.id : key, layer: "inline", item: key, prim, color, material: part.material || "inline", opacity: 1, source: asSource(part.source) ?? source, ...lodOf(part) });
      });
    } else if (/instrument|tapping|gauge|transmitter|element/.test(kind)) {
      const radius = Math.max(od * 0.6, 0.08);
      // A stem up from the pipe and a bulb on it.
      const top = add(p, [0, 0, od / 2 + radius * 1.5]);
      push({ key: `${key}:stem`, layer: "inline", item: key, prim: { kind: "cylinder", start: [...p], end: round3(top), radius: radius * 0.25, radiusEnd: radius * 0.25 }, color: INSTRUMENT_COLOR, material: "inline", opacity: 1, source });
      push({ key, layer: "inline", item: key, prim: { kind: "ellipsoid", centre: round3(top), radii: [radius, radius, radius], rotationZ: 0 }, color: INSTRUMENT_COLOR, material: "inline", opacity: 1, source });
    } else if (/reducer|expander/.test(kind)) {
      const half = (od * 1.5) / 2;
      push({ key, layer: "inline", item: key, prim: { kind: "cylinder", start: round3(add(p, scale(d, -half))), end: round3(add(p, scale(d, half))), radius: od * 0.6, radiusEnd: od * 0.4 }, color: VALVE_COLOR, material: "inline", opacity: 1, source });
    } else if (/silencer|filter|strainer|item/.test(kind)) {
      // A drum on the pipe: silencers big, strainers and other items small.
      const big = kind === "silencer";
      const half = big ? Math.max(od * 2, 0.5) : Math.max(od, 0.15);
      const radius = big ? Math.max(od * 1.2, 0.2) : Math.max(od * 0.8, 0.06);
      push({ key, layer: "inline", item: key, prim: { kind: "cylinder", start: round3(add(p, scale(d, -half))), end: round3(add(p, scale(d, half))), radius, radiusEnd: radius }, color: kind === "item" ? INSTRUMENT_COLOR : VALVE_COLOR, material: "inline", opacity: 1, source });
    } else {
      // A valve: two cones tip to tip along the pipe, and a stem with a handwheel (a safety
      // valve: a bonnet instead).
      const half = Math.max(od * 2, 0.25) / 2;
      const radius = Math.max(od * 0.75, 0.06);
      const a = round3(add(p, scale(d, -half)));
      const b = round3(add(p, scale(d, half)));
      push({ key, layer: "inline", item: key, prim: { kind: "cylinder", start: a, end: [...p], radius, radiusEnd: radius * 0.15 }, color: VALVE_COLOR, material: "inline", opacity: 1, source });
      push({ key: `${key}:b`, layer: "inline", item: key, prim: { kind: "cylinder", start: b, end: [...p], radius, radiusEnd: radius * 0.15 }, color: VALVE_COLOR, material: "inline", opacity: 1, source });
      const up: Vec3 = Math.abs(d[2]) > 0.9 ? [1, 0, 0] : [0, 0, 1];
      const stemTop = round3(add(p, scale(up, radius * 2.2)));
      if (kind === "safety_valve")
        push({ key: `${key}:bonnet`, layer: "inline", item: key, prim: { kind: "cylinder", start: [...p], end: stemTop, radius: radius * 0.5, radiusEnd: radius * 0.3 }, color: VALVE_COLOR, material: "inline", opacity: 1, source });
      else if (kind === "check_valve")
        push({ key: `${key}:cover`, layer: "inline", item: key, prim: { kind: "cylinder", start: [...p], end: round3(add(p, scale(up, radius * 1.1))), radius: radius * 0.6, radiusEnd: radius * 0.6 }, color: VALVE_COLOR, material: "inline", opacity: 1, source });
      else {
        push({ key: `${key}:stem`, layer: "inline", item: key, prim: { kind: "cylinder", start: [...p], end: stemTop, radius: radius * 0.12, radiusEnd: radius * 0.12 }, color: VALVE_COLOR, material: "inline", opacity: 1, source });
        push({ key: `${key}:wheel`, layer: "inline", item: key, prim: { kind: "cylinder", start: stemTop, end: round3(add(stemTop, scale(up, radius * 0.15))), radius: radius * 0.9, radiusEnd: radius * 0.9 }, color: VALVE_COLOR, material: "inline", opacity: 1, source });
      }
    }
    index(inline.id, key);
    index(inline.tag, key);
    index(inline.refs.dexpi, key);
    const line = inline.line;
    items.set(key, {
      kind: "inline",
      id: inline.tag || inline.id,
      title: inline.dexpi_class,
      type: inline.kind.replace(/_/g, " "),
      source,
      details: [
        ["point", fmtVec(inline.point)],
        ["line", line],
        ["segment", inline.segment],
      ],
      sheetFile: repoSheet(inline.refs.sheet, sheets),
      highlight: inline.refs.dexpi ?? null,
      related: [{ key: `pipe:${inline.pipe}`, label: line }],
      line,
      review: false,
    });
    // The other segments core's refs name (one entry for a component two segments share).
    mergeInline(items.get(key)!, inline);
  }

  /** Add another occurrence's pipe, line and segment to an in-line item, without repeats. */
  function mergeInline(known: ModelItemInfo, inline: ModelInlineItem): void {
    const relate = (pipeKey: string, label: string) => {
      if (!known.related.some((r) => r.key === pipeKey)) known.related.push({ key: pipeKey, label });
    };
    relate(`pipe:${inline.pipe}`, `${inline.line} ${inline.segment}`);
    const add = (name: string, plural: string, value: string) => {
      const row = known.details.find(([k]) => k === name || k === plural);
      if (!row) return void known.details.push([name, value]);
      const values = row[1].split(", ");
      if (values.includes(value)) return;
      row[0] = plural;
      row[1] = [...values, value].join(", ");
    };
    add("line", "lines", inline.line);
    add("segment", "segments", inline.segment);
    const refs = inline.refs;
    for (const l of Array.isArray(refs?.lines) ? refs.lines : []) if (typeof l === "string" && l) add("line", "lines", l);
    for (const seg of Array.isArray(refs?.segments) ? refs.segments : []) {
      if (typeof seg !== "string" || !seg) continue;
      add("segment", "segments", seg);
      const pipeKey = ids.get(`${inline.pipe.split("/")[0]}/${seg}`) ?? ids.get(seg);
      if (pipeKey?.startsWith("pipe:")) relate(pipeKey, `${items.get(pipeKey)?.line ?? ""} ${seg}`.trim());
    }
  }

  /** A pipe's shoe or guide: detail on the pipe it carries. */
  function supportMeshes(support: ModelSupport): void {
    const key = `pipe:${support.pipe}`;
    if (!items.has(key)) return;
    index(support.id, key);
    for (const part of support.parts ?? []) {
      const prim = partPrim(part);
      if (!prim) continue;
      index(part.id, key);
      const color = STRUCTURE_COLORS[part.material] ?? STEEL_COLOR;
      push({ key: part.id, layer: "pipes", item: key, prim, color, classColor: color, material: part.material || "steel", opacity: 1, source: asSource(part.source) ?? asSource(support.source), ...lodOf(part) });
    }
  }

  /** A proposed step-over: a deck over the pipe with treads and handrails, to review. */
  function stepOverMeshes(stepOver: ModelStepOver): void {
    const key = `platform:${stepOver.id}`;
    const source = asSource(stepOver.source);
    index(stepOver.id, key);
    steelParts(stepOver.parts ?? [], key, "platforms", source, stepOver.review_needed !== false);
    if (stepOver.review_needed !== false) propose("step-over", key);
    const pipeKey = ids.get(stepOver.pipe) ?? `pipe:${stepOver.pipe}`;
    items.set(key, {
      kind: "platform",
      id: stepOver.id,
      title: `Step-over at ${items.get(pipeKey)?.line ?? stepOver.pipe}`,
      type: "step-over",
      source,
      details: [
        ["point", fmtVec(stepOver.point)],
        ["deck height", `${fmt(stepOver.height)} m above the walkway`],
        ["walkway", stepOver.walkway],
        ...(stepOver.review_needed !== false ? [["status", "proposed, review needed"] as [string, string]] : []),
      ],
      sheetFile: null,
      highlight: null,
      related: items.has(pipeKey) ? [{ key: pipeKey, label: items.get(pipeKey)?.line ?? stepOver.pipe }] : [],
      line: null,
      review: stepOver.review_needed !== false,
    });
  }

  function structureMeshes(st: ModelStructure): void {
    const key = `structure:${st.id}`;
    const source = asSource(st.source);
    // A proposed structure (a valve access platform) is reviewed and pinned as a whole, its ways with it.
    const proposed = Boolean(st.review_needed);
    index(st.id, key);
    // A finding names a floor by its level ids (`CB-1/E20`, `E20`).
    for (const level of st.levels) {
      index(`${st.id}/${level.id}`, key);
      index(level.id, key);
    }
    steelParts(st.parts, key, "structures", source, proposed);
    if (proposed) {
      propose("valve platform", key);
      for (const way of [...st.stairs, ...st.ladders]) {
        index(way.id, key);
        steelParts(way.parts, key, "platforms", asSource(way.source) ?? source, true);
      }
    }
    // Declared stairs and ladders are part of the frame; proposals are items of their own to review.
    for (const stair of proposed ? [] : st.stairs) {
      if (stair.review_needed) accessProposal(stair, "stair", st.id, key);
      else {
        index(stair.id, key);
        steelParts(stair.parts, key, "platforms", asSource(stair.source) ?? source);
      }
    }
    for (const ladder of proposed ? [] : st.ladders) {
      if (ladder.review_needed) accessProposal(ladder, "ladder", st.id, key);
      else {
        index(ladder.id, key);
        steelParts(ladder.parts, key, "platforms", asSource(ladder.source) ?? source);
      }
    }
    steelParts(st.walls, key, "structures", source);
    const box = itemBounds.get(key);
    const sections = Object.entries(st.sections).filter(([k]) => k !== "assumed");
    items.set(key, {
      kind: "structure",
      id: st.id,
      title: st.title || null,
      type: proposed ? "valve access platform" : "steel frame",
      source,
      details: [
        ...(st.serves?.length ? [["serves", st.serves.join(", ")] as [string, string]] : []),
        ...(st.reason ? [["why", st.reason] as [string, string]] : []),
        ...(proposed ? [["status", "proposed, review needed"], ["to keep it", `cheme layout pin ${st.id}`]] as [string, string][] : []),
        ["size", `${fmt(st.width)} x ${fmt(st.depth)} x ${fmt(st.height)} m`],
        ["parts", String(st.parts.length)],
        ...(st.stairs.length ? [["stairs", st.stairs.map((s) => `${s.from} to ${s.to} (${s.flights} flights, ${s.side})`).join("; ")] as [string, string]] : []),
        ...(st.ladders.length ? [["ladders", String(st.ladders.length) + (st.ladders.some((l) => l.cage) ? " (caged)" : "")] as [string, string]] : []),
        ...(st.walls.length ? [["walls", String(st.walls.length)] as [string, string]] : []),
        ...(st.levels.length ? [["levels", st.levels.map((l) => `${l.id} @ ${fmt(l.elevation)} m`).join(", ")] as [string, string]] : []),
        ...(sections.length ? [["sections", sections.map(([k, v]) => `${k} ${v}`).join(", ") + (st.sections.assumed ? " (ASSUMED)" : "")] as [string, string]] : []),
        ...(box ? [["extent", `${fmtVec(box.min)} - ${fmtVec(box.max)}`] as [string, string]] : []),
      ],
      sheetFile: null,
      highlight: null,
      related: [],
      line: null,
      review: proposed,
    });
  }

  /**
   * Generated steel and wall parts (members, boxes, cylinders, ring sectors) of an object:
   * gratings, handrails and cages on the platforms layer, the rest on `layer`; every grating's
   * top is a floor to walk on. Each part's id links to the object (a finding names part ids).
   */
  function steelParts(parts: readonly ModelPart[], item: string, layer: LayerId, source: Source | null, review = false): void {
    for (const part of parts) {
      const prim = partPrim(part);
      if (!prim) continue;
      index(part.id, item);
      const material = part.material || "steel";
      push({
        key: part.id,
        layer: PLATFORM_MATERIALS.has(material) ? "platforms" : layer,
        item,
        prim,
        color: STRUCTURE_COLORS[material] ?? STEEL_COLOR,
        material,
        opacity: STRUCTURE_OPACITY[material] ?? 1,
        source: asSource(part.source) ?? source,
        review,
        ...lodOf(part),
      });
      if (material !== "grating") continue;
      if (prim.kind === "box") {
        const corners = boxCorners(prim.centre, prim.size, prim.rotationZ).slice(4);
        floors.push({ id: part.id, elevation: r6(prim.centre[2] + prim.size[2] / 2), polygon: corners.map((c) => [c[0], c[1]] as [number, number]) });
      } else if (prim.kind === "annulus") {
        const polygon: [number, number][] = [];
        for (let i = 0; i < 24; i++) {
          const a = (i / 24) * 2 * Math.PI;
          polygon.push([prim.centre[0] + prim.outer * Math.cos(a), prim.centre[1] + prim.outer * Math.sin(a)]);
        }
        floors.push({ id: part.id, elevation: prim.centre[2], polygon });
      }
    }
  }

  function platformMeshes(platform: ModelPlatform): void {
    const key = `platform:${platform.id}`;
    const source = asSource(platform.source);
    const review = Boolean(platform.review_needed);
    if (review) propose("platform", key);
    index(platform.id, key);
    index(platform.ladder.id, key);
    steelParts(platform.parts, key, "platforms", source, review);
    steelParts(platform.ladder.parts, key, "platforms", asSource(platform.ladder.source) ?? source, review);
    const owner = platform.tag;
    const serves = platform.serves ?? [];
    items.set(key, {
      kind: "platform",
      id: platform.id,
      title: `Platform at ${owner}`,
      type: platform.kind,
      source,
      details: [
        ["floor", `${fmt(platform.elevation)} m`],
        ["above the item's bottom", `${fmt(platform.item_elevation)} m`],
        ["width", `${fmt(platform.width)} m`],
        ...(platform.arc_deg ? [["arc", `${fmt(platform.arc_deg[0])} to ${fmt(platform.arc_deg[1])} deg`] as [string, string]] : []),
        ["ladder", platform.ladder.cage ? "caged" : "yes"],
        ...(serves.length ? [["serves", serves.join(", ")] as [string, string]] : []),
        ...(review ? [["status", "proposed, review needed"] as [string, string]] : []),
      ],
      sheetFile: null,
      highlight: null,
      related: [{ key: `equipment:${owner}`, label: owner }, ...serves.map((id) => ({ key: ids.get(id) ?? id, label: id }))],
      line: null,
      review,
    });
  }

  /**
   * A valve's declared operator: a chain wheel on its handwheel with the chain hanging
   * to {@link CHAIN_LOOP_M} above the floor under it, or an extension spindle or remote operator
   * as a rod from the handwheel to a pedestal {@link PEDESTAL_M} above the nearest floor (core's
   * measure). Schematic: core checks the operator but draws no chain, spindle or pedestal.
   */
  function operatorMeshes(inline: ModelInlineItem, op: ModelOperator): void {
    const key = ids.get(inline.id) ?? `inline:${inline.id}`;
    const info = items.get(key);
    if (!info || !isVec3(inline.point)) return;
    const source: Source = "declared";
    const lod = inline.parts?.length ? { lod: 2 } : {};
    const wheel = operatorWheel(inline);
    const rows: [string, string][] = [["operator", operatorTitle(op)]];
    if (op.basis) rows.push(["operator basis", op.basis]);
    const mesh = (suffix: string, prim: Prim, color = OPERATOR_COLOR, material = "steel") =>
      push({ key: `${key}:operator:${suffix}`, layer: "inline", item: key, prim, color, material, opacity: 1, source, ...lod });
    if (op.kind === "chainwheel") {
      const g = chainWheelGeometry(wheel, standing);
      mesh("wheel", { kind: "torus", centre: g.centre, axis: wheel.axis, radius: g.radius, tube: 0.02, arc: null }, CHAIN_COLOR, "handwheel");
      g.chain.forEach(([a, b], i) => mesh(`chain-${i}`, { kind: "cylinder", start: a, end: b, radius: 0.012, radiusEnd: 0.012 }, CHAIN_COLOR));
      rows.push(["operator drawn", `chain wheel, chain to ${fmt(g.bottom)} m (${fmt(CHAIN_LOOP_M)} m above ${g.floor.id} at ${fmt(g.floor.elevation)} m); schematic, by the viewer`]);
    } else if (op.kind === "extension_spindle" || op.kind === "remote_operator") {
      const g = pedestalGeometry(wheel.centre, standing, PEDESTAL_M);
      g.path.slice(1).forEach((b, i) => mesh(`rod-${i}`, { kind: "cylinder", start: g.path[i]!, end: b, radius: 0.02, radiusEnd: 0.02 }));
      g.path.slice(1, -1).forEach((p, i) => mesh(`joint-${i}`, { kind: "ellipsoid", centre: p, radii: [0.04, 0.04, 0.04], rotationZ: 0 }));
      mesh("pedestal", { kind: "box", centre: round3([g.at[0], g.at[1], (g.floor.elevation + g.top) / 2]), size: [0.14, 0.14, r6(g.top - g.floor.elevation)], rotationZ: 0 }, STEEL_COLOR);
      mesh("pedestal-wheel", { kind: "torus", centre: round3([g.at[0], g.at[1], g.top + 0.06]), axis: [0, 0, 1], radius: 0.16, tube: 0.015, arc: null }, MATERIAL_COLORS.handwheel!, "handwheel");
      const what = op.kind === "remote_operator" ? "remote operator" : "extension spindle";
      rows.push(["operator drawn", `${what}, ${fmt(g.length)} m to a pedestal ${fmt(PEDESTAL_M)} m above ${g.floor.id} at ${fmt(g.floor.elevation)} m${op.length_m ? ` (declared ${fmt(op.length_m)} m)` : ""}; schematic, by the viewer`]);
    } else rows.push(["operator drawn", "not drawn (no shape for this kind)"]);
    info.details.push(...rows);
  }

  /**
   * A transmitter declared remote-mounted on a tapping: its impulse lines (two) or capillary (one)
   * from core's tapping out of the item's plan, down to a stand {@link STAND_M} above the nearest
   * floor (core's measure), the transmitter on the stand. Schematic, like the operators.
   */
  function remoteMountMeshes(mount: { eq: ModelEquipment; nozzle: ModelNozzle; key: string; from: Vec3; detail: boolean }): void {
    const { nozzle, key } = mount;
    const op = nozzle.operator!;
    const info = items.get(key);
    if (!info) return;
    const source: Source = "declared";
    const lod = mount.detail ? { lod: 2 } : {};
    const g = standGeometry(mount.from, mount.eq.bbox, standing);
    const mesh = (suffix: string, prim: Prim, color: string, material: string) =>
      push({ key: `${key}:remote:${suffix}`, layer: "nozzles", item: key, prim, color, material, opacity: 1, source, ...lod });
    const capillary = op.via === "capillary";
    const offsets = capillary ? [0] : [-0.03, 0.03];
    for (const [j, o] of offsets.entries()) {
      const shift: Vec3 = [o * g.across[0], o * g.across[1], 0];
      g.path.slice(1).forEach((b, i) => mesh(`line-${j}-${i}`, { kind: "cylinder", start: round3(add(g.path[i]!, shift)), end: round3(add(b, shift)), radius: 0.01, radiusEnd: 0.01 }, capillary ? INSTRUMENT_COLOR : STEEL_COLOR, "steel"));
    }
    mesh("post", { kind: "cylinder", start: [g.at[0], g.at[1], g.floor.elevation], end: [g.at[0], g.at[1], r6(g.top)], radius: 0.03, radiusEnd: 0.03 }, STEEL_COLOR, "steel");
    mesh("base", { kind: "box", centre: [g.at[0], g.at[1], r6(g.floor.elevation + 0.01)], size: [0.25, 0.25, 0.02], rotationZ: 0 }, STEEL_COLOR, "steel");
    mesh("transmitter", { kind: "box", centre: [g.at[0], g.at[1], r6(g.top + 0.08)], size: [0.12, 0.12, 0.16], rotationZ: 0 }, INSTRUMENT_COLOR, "instrument");
    mesh("transmitter-cap", { kind: "cylinder", start: [g.at[0], g.at[1], r6(g.top + 0.16)], end: [g.at[0], g.at[1], r6(g.top + 0.22)], radius: 0.055, radiusEnd: 0.055 }, INSTRUMENT_COLOR, "instrument");
    info.details.push(["operator", operatorTitle(op)]);
    if (op.basis) info.details.push(["operator basis", op.basis]);
    info.details.push(["operator drawn", `${capillary ? "capillary" : "impulse lines"}, ${fmt(g.length)} m to a stand ${fmt(STAND_M)} m above ${g.floor.id} at ${fmt(g.floor.elevation)} m${op.length_m ? ` (declared ${fmt(op.length_m)} m)` : ""}; schematic, by the viewer`]);
  }

  /**
   * A casing's or building's declared `hatch` opening: core cuts the wall around it but draws no
   * hatch, so the viewer draws its frame and a closed cover on the wall's outer face.
   */
  function hatchMeshes(opening: BuildingOpening, owner: { id: string; key: string; origin: [number, number]; rotation: number; width: number; depth: number; walls: readonly ModelPart[]; layer: LayerId }): void {
    const g = hatchGeometry(opening, owner);
    if (!g) return;
    const name = opening.id || `hatch-${opening.side}-${fmt(opening.offset)}`;
    const key = `hatch:${owner.id}/${name}`;
    const source: Source = "declared";
    g.frame.forEach((prim, i) => push({ key: `${key}:frame-${i}`, layer: owner.layer, item: key, prim, color: HATCH_COLOR, material: "steel", opacity: 1, source }));
    push({ key, layer: owner.layer, item: key, prim: g.cover, color: STRUCTURE_COLORS.door!, material: "door", opacity: 0.85, source });
    index(`${owner.id}/${name}`, key);
    index(name, key);
    items.set(key, {
      kind: "hatch",
      id: `${owner.id}/${name}`,
      title: `Hatch ${name} in the ${opening.side} wall of ${owner.id}`,
      type: "hatch",
      source,
      details: [
        ["size", `${fmt(opening.width)} x ${fmt(opening.height)} m`],
        ["side", `${opening.side}, ${fmt(opening.offset)} m from its left end seen from outside`],
        ["sill", `${fmt(opening.sill ?? 0)} m`],
        ["centre", fmtVec(g.centre)],
        ["drawn", "frame and closed cover, by the viewer (the model declares the opening)"],
      ],
      sheetFile: null,
      highlight: null,
      related: [{ key: owner.key, label: owner.id }],
      line: null,
      review: false,
    });
  }

  /** A proposed stair or ladder (of a frame or a rack): an item of its own, with why and how to keep it. */
  function accessProposal(access: ModelStair | ModelLadder, what: "stair" | "ladder", owner: string, ownerKey: string): void {
    const key = `platform:${access.id}`;
    const source = asSource(access.source);
    index(access.id, key);
    steelParts(access.parts, key, "platforms", source, true);
    propose(what, key);
    const stair = "flights" in access ? access : null;
    const ladder = "cage" in access ? access : null;
    const details: [string, string][] = [];
    if (access.from || access.to) details.push(["from, to", `${access.from ?? "grade"} to ${access.to ?? "top"}`]);
    if (stair) details.push(["flights", `${stair.flights} (${fmt(stair.width)} m wide, ${stair.side} side)`]);
    if (ladder) {
      details.push(["rise", `${fmt(ladder.top[2] - ladder.base[2])} m${ladder.cage ? ", caged" : ""}`]);
      if (ladder.end) details.push(["at the rack's", ladder.end]);
    }
    if (access.reason) details.push(["why", access.reason]);
    details.push(["status", "proposed, review needed"]);
    details.push(["to keep it", `cheme layout pin ${access.id}`]);
    items.set(key, {
      kind: "platform",
      id: access.id,
      title: `Proposed ${what} of ${owner}`,
      type: what,
      source,
      details,
      sheetFile: null,
      highlight: null,
      related: [{ key: ownerKey, label: owner }],
      line: null,
      review: true,
    });
  }

  /** A post or T-post under a pipe: steel of its own; a proposal to review and pin. */
  function supportSteelMeshes(steel: ModelSupportSteel): void {
    const key = `support:${steel.id}`;
    const source = asSource(steel.source);
    const proposed = Boolean(steel.review_needed);
    index(steel.id, key);
    steelParts(steel.parts, key, "structures", source, proposed);
    if (proposed) propose("support steel", key);
    const details: [string, string][] = [
      ["kind", steel.kind.replace("_", "-")],
      ["top of steel", `${fmt(steel.top)} m${steel.base > 0 ? ` (on steel at ${fmt(steel.base)} m)` : " (from grade)"}`],
    ];
    if (steel.serves?.length) details.push(["carries", steel.serves.join(", ")]);
    if (steel.reason) details.push(["why", steel.reason]);
    if (proposed) {
      details.push(["status", "proposed, review needed"]);
      details.push(["to keep it", `cheme layout pin ${steel.id}`]);
    }
    items.set(key, {
      kind: "support",
      id: steel.id,
      title: proposed ? `Proposed support steel` : null,
      type: "support steel",
      source,
      details,
      sheetFile: null,
      highlight: null,
      related: (steel.serves ?? []).map((pipe) => ({ key: `pipe:${pipe}`, label: pipe })),
      line: null,
      review: proposed,
    });
  }

  /** A pipe through a wall or a building's roof outside the declared openings: a sleeve where it meets it. */
  function penetrationMeshes(pen: ModelPenetration): void {
    if (!isVec3(pen.point)) return;
    const key = `penetration:${pen.id}`;
    const pipeKey = `pipe:${pen.pipe}`;
    const pipe = model.pipes.find((p) => p.id === pen.pipe);
    const d = pipe ? segmentDirection(pipe.points.filter(isVec3), pen.point) : ([1, 0, 0] as Vec3);
    // A collar a little wider than the pipe with its insulation (core sizes the opening 0.05 m all round).
    const outer = (pipeOd.get(pen.pipe) ?? 0.1) / 2 + Math.max(pipe?.insulation_mm ?? 0, 0) / 1000;
    const r = Math.max(outer + 0.08, outer * 1.15);
    const half = 0.3;
    push({
      key,
      layer: "pipes",
      item: key,
      prim: { kind: "cylinder", start: round3(add(pen.point, scale(d, -half))), end: round3(add(pen.point, scale(d, half))), radius: r, radiusEnd: r },
      color: PENETRATION_COLOR,
      classColor: PENETRATION_COLOR,
      material: "sleeve",
      opacity: 0.85,
      source: asSource(pen.source),
      review: pen.review_needed !== false,
    });
    index(pen.id, key);
    if (pen.review_needed !== false) propose("penetration", key);
    const o = pen.opening;
    const roof = o?.side === "roof";
    const ownerKey = model.buildings.some((b) => b.id === pen.owner) ? `building:${pen.owner}` : `structure:${pen.owner}`;
    items.set(key, {
      kind: "penetration",
      id: pen.id,
      title: `${pipe?.line ?? pen.pipe} through ${pen.owner}`,
      type: pen.material.replace(/_/g, " "),
      source: asSource(pen.source),
      details: [
        ["point", fmtVec(pen.point)],
        [roof ? "roof" : "wall", pen.wall],
        ["pipe", pen.end_inside ? "ends inside" : "passes through"],
        ...(pen.length > 0.05 ? [[roof ? "in the roof slab" : "in the wall's plane", `${fmt(pen.length)} m`] as [string, string]] : []),
        ...(o ? [["opening needed", roof ? roofOpening(o, pen.owner) : `${fmt(o.width)} x ${fmt(o.height)} m, ${o.side} side, ${fmt(o.offset)} m along, sill ${fmt(o.sill ?? 0)} m`] as [string, string]] : []),
        ["why", pen.reason],
        // core's `cheme layout pin` refuses a roof penetration: its message, not the command.
        roof
          ? ["cannot be pinned", `${pen.id} is a roof penetration: a roof opening cannot be declared; route the line into ${pen.owner} through a wall (via points) and pin that opening`]
          : ["to keep it", `cheme layout pin ${pen.id}`],
      ],
      sheetFile: null,
      highlight: null,
      related: [
        ...(items.has(pipeKey) ? [{ key: pipeKey, label: pipe?.line ?? pen.pipe }] : []),
        { key: ownerKey, label: pen.owner },
      ],
      line: pipe?.line ?? null,
      review: pen.review_needed !== false,
    });
  }

  /** A duct's or tray's run parts with their primitives, the runs joined at the corners. */
  function runParts(parts: readonly ModelPart[], points: readonly XYZ[]): [ModelPart, Prim][] {
    const pairs = parts.map((part) => [part, partPrim(part)] as const).filter((x): x is readonly [ModelPart, Prim] => x[1] !== null);
    const runs = pairs.filter(([part]) => /\/run-\d+$/.test(part.id));
    const joined = joinRuns(
      runs.map(([, prim]) => prim),
      points.filter(isVec3),
    );
    const byPart = new Map(runs.map(([part], i) => [part, joined[i]!]));
    return pairs.map(([part, prim]) => [part, byPart.get(part) ?? prim]);
  }

  function trayMeshes(tray: ModelTray): void {
    const key = `tray:${tray.id}`;
    const source = asSource(tray.source);
    const color = TRAY_COLORS[tray.system] ?? STEEL_COLOR;
    for (const [part, prim] of runParts(tray.parts ?? [], tray.points)) {
      index(part.id, key);
      push({ key: part.id, layer: "trays", item: key, prim, color: STRUCTURE_COLORS[part.material] ?? color, material: part.material || "tray_power", opacity: 1, source: asSource(part.source) ?? source, review: Boolean(tray.review_needed), ...lodOf(part) });
    }
    index(tray.id, key);
    const loaded = tray.refs?.tag ?? null;
    items.set(key, {
      kind: "tray",
      id: tray.id,
      title: `${tray.system} tray, ${tray.kind}`,
      type: `${tray.system} ${tray.kind}`,
      source,
      details: [
        ["size", `${fmt(tray.width * 1000)} x ${fmt(tray.depth * 1000)} mm`],
        ["length", `${fmt(tray.length)} m`],
        ["fill", `${Math.round(tray.fill * 100)} % (at most ${Math.round(tray.fill_max * 100)} %)`],
        ["cables", String(tray.cables.length)],
        ...(tray.rack ? [["rack", tray.rack] as [string, string]] : []),
        ...(loaded ? [["feeds", loaded] as [string, string]] : []),
        ...(tray.method ? [["routed", tray.method] as [string, string]] : []),
        ...(tray.review_needed ? [["status", "review needed"] as [string, string]] : []),
      ],
      sheetFile: null,
      highlight: null,
      related: [],
      line: null,
      review: Boolean(tray.review_needed),
    });
  }

  function junctionBoxMeshes(jb: ModelJunctionBox): void {
    const key = `junction_box:${jb.tag}`;
    const source = asSource(jb.source);
    for (const part of jb.parts ?? []) {
      const prim = partPrim(part);
      if (!prim) continue;
      index(part.id, key);
      push({ key: part.id, layer: "trays", item: key, prim, color: STRUCTURE_COLORS[part.material] ?? STEEL_COLOR, material: part.material || "junction_box", opacity: 1, source: asSource(part.source) ?? source, review: Boolean(jb.review_needed), ...lodOf(part) });
    }
    index(jb.tag, key);
    index(jb.id, key);
    if (jb.review_needed) propose("junction box", key);
    items.set(key, {
      kind: "junction_box",
      id: jb.tag,
      title: "Junction box",
      type: jb.area ? `field junction box, area ${jb.area}` : "field junction box",
      source,
      details: [
        ["point", fmtVec(jb.point)],
        ["instruments", jb.instruments.join(", ")],
        ...(jb.room ? [["to", jb.room] as [string, string]] : []),
        ...(jb.review_needed ? [["status", "proposed, review needed"] as [string, string]] : []),
      ],
      sheetFile: null,
      highlight: null,
      related: [],
      line: null,
      review: Boolean(jb.review_needed),
    });
  }

  /**
   * Cables as items (no geometry of their own: their route is drawn when selected) and the routes
   * of what they feed: a motor's cable to its item, an instrument's field cable and its junction
   * box's multipair cable to the instrument (a marker where the model has nothing else for it).
   */
  function cableItems(cables: ModelCable[]): void {
    const byJb = new Map<string, ModelCable[]>();
    for (const c of cables) if (c.kind === "multipair") byJb.set(c.to, [...(byJb.get(c.to) ?? []), c]);
    const routeOf = new Map<string, ItemRoute>();
    for (const c of cables) {
      const key = `cable:${c.id}`;
      const path = cablePath(c, trays);
      const trayKeys = c.trays.filter((t) => trays.has(t)).map((t) => `tray:${t}`);
      const ends = [c.from, c.to].map((tag) => ids.get(tag)).filter((k): k is string => !!k && k.startsWith("junction_box:"));
      routeOf.set(c.id, { items: [...trayKeys, ...ends], paths: path.length > 1 ? [path] : [] });
      index(c.id, key);
      index(c.tag, key);
      let box: Box3 | undefined;
      for (const p of path) box = unionBox(box, { min: p, max: p });
      if (box) itemBounds.set(key, box);
      for (const t of trayKeys) items.get(t)?.related.push({ key, label: c.tag });
      const power = c.power_kw != null ? `${fmt(c.power_kw)} kW` : null;
      const volts = c.voltage_v != null ? `${fmt(c.voltage_v)} V` : null;
      items.set(key, {
        kind: "cable",
        id: c.tag,
        title: `${c.from} to ${c.to}`,
        type: `${c.system} ${c.kind}`,
        source: asSource(c.source),
        details: [
          ["size", `${c.size}${c.count > 1 ? ` (${c.count} in parallel)` : ""}, ${fmt(c.od_mm)} mm OD`],
          ...(power || volts ? [["load", [power, volts, c.current_a != null ? `${fmt(c.current_a)} A` : null].filter(Boolean).join(", ")] as [string, string]] : []),
          ...(c.pairs ? [["pairs", String(c.pairs)] as [string, string]] : []),
          ["trays", c.trays.length ? c.trays.join(" > ") : "none (direct to its junction box)"],
          ["length", `${fmt(c.length)} m (route ${fmt(c.route_length)} m)`],
          ...(c.basis ? [["basis", c.basis] as [string, string]] : []),
          ...(c.reason ? [["why", c.reason] as [string, string]] : []),
        ],
        sheetFile: null,
        highlight: null,
        related: c.trays.filter((t) => trays.has(t)).map((t) => ({ key: `tray:${t}`, label: t })),
        line: null,
        review: Boolean(c.review_needed),
      });
    }
    const attach = (itemKey: string, cableIds: string[]) => {
      const route: ItemRoute = routes.get(itemKey) ?? { items: [], paths: [] };
      for (const id of cableIds) {
        const r = routeOf.get(id);
        if (!r) continue;
        for (const k of r.items) if (!route.items.includes(k) && k !== itemKey) route.items.push(k);
        route.paths.push(...r.paths);
        const info = items.get(itemKey);
        if (info && !info.related.some((x) => x.key === `cable:${id}`)) info.related.push({ key: `cable:${id}`, label: cables.find((c) => c.id === id)?.tag ?? id });
      }
      routes.set(itemKey, route);
    };
    for (const c of cables) {
      routes.set(`cable:${c.id}`, routeOf.get(c.id)!);
      if (c.kind === "motor" || c.kind === "feeder") {
        // The driven item: the branch tray's load, else the tag the motor is named after.
        const branch = c.trays.map((t) => trays.get(t)).find((t) => t?.kind === "branch" && t.refs?.tag);
        const candidates = [branch?.refs?.tag, c.to, c.to.replace(/^M-/, ""), c.refs?.tag];
        const owner = candidates.map((t) => (t ? ids.get(t) : undefined)).find((k) => k && !k.startsWith("cable:"));
        if (owner) attach(owner, [c.id]);
        continue;
      }
      if (c.kind === "field") {
        let owner = ids.get(c.from);
        if (!owner || owner.startsWith("cable:")) owner = instrumentMarker(c);
        attach(owner, [c.id, ...(byJb.get(c.to) ?? []).map((m) => m.id)]);
        const jb = ids.get(c.to);
        if (jb?.startsWith("junction_box:")) attach(jb, [c.id]);
        continue;
      }
      const jb = ids.get(c.to);
      if (jb?.startsWith("junction_box:")) attach(jb, [c.id]);
    }
  }

  /** A field instrument the model draws nothing for: a small marker where its cable starts. */
  function instrumentMarker(c: ModelCable): string {
    const key = `instrument:${c.from}`;
    if (items.has(key)) return key;
    const s = 0.16;
    push({ key, layer: "trays", item: key, prim: { kind: "box", centre: [...c.from_point], size: [s, s, s], rotationZ: 0 }, color: INSTRUMENT_COLOR, material: "instrument", opacity: 1, source: asSource(c.source) });
    index(c.from, key);
    items.set(key, {
      kind: "instrument",
      id: c.from,
      title: "Field instrument (where its cable starts)",
      type: "instrument",
      source: asSource(c.source),
      details: [["point", fmtVec(c.from_point)], ["junction box", c.to]],
      sheetFile: null,
      highlight: null,
      related: [],
      line: null,
      review: false,
    });
    return key;
  }

  function hvacUnitMeshes(unit: ModelHvacUnit): void {
    const key = `hvac_unit:${unit.id}`;
    const source = asSource(unit.source);
    for (const part of unit.parts ?? []) {
      const prim = partPrim(part);
      if (!prim) continue;
      index(part.id, key);
      push({ key: part.id, layer: "ducts", item: key, prim, color: STRUCTURE_COLORS[part.material] ?? STEEL_COLOR, material: part.material || "ahu", opacity: 1, source: asSource(part.source) ?? source, ...lodOf(part) });
    }
    index(unit.id, key);
    items.set(key, {
      kind: "hvac_unit",
      id: unit.id,
      title: unit.title || "Air handling unit",
      type: "air handling unit",
      source,
      details: [
        ["building", `${unit.building}${unit.level ? ` / ${unit.level}` : ""}`],
        ["size", `${unit.size.map(fmt).join(" x ")} m`],
        ...(unit.capacity_m3h != null ? [["capacity", `${fmt(unit.capacity_m3h)} m3/h`] as [string, string]] : []),
        ["supply", `${fmt(unit.supply_m3h)} m3/h`],
        ["extract", `${fmt(unit.extract_m3h)} m3/h`],
        ...(unit.intake ? [["intake", unit.intake] as [string, string]] : []),
        ...(unit.exhaust ? [["exhaust", unit.exhaust] as [string, string]] : []),
      ],
      sheetFile: null,
      highlight: null,
      related: [{ key: `building:${unit.building}`, label: unit.building }],
      line: null,
      review: false,
    });
  }

  function ductMeshes(duct: ModelDuct): void {
    const key = `duct:${duct.id}`;
    const source = asSource(duct.source);
    const review = Boolean(duct.review_needed);
    for (const [part, prim] of runParts(duct.parts ?? [], duct.points)) {
      index(part.id, key);
      push({ key: part.id, layer: "ducts", item: key, prim, color: STRUCTURE_COLORS[part.material] ?? DUCT_COLORS[duct.system] ?? STEEL_COLOR, material: part.material || "duct_supply", opacity: 1, source: asSource(part.source) ?? source, review, ...lodOf(part) });
    }
    index(duct.id, key);
    const unitKey = `hvac_unit:${duct.unit}`;
    const over = duct.velocity_m_s > duct.velocity_max_m_s + 1e-6;
    items.set(key, {
      kind: "duct",
      id: duct.id,
      title: `${duct.system} ${duct.kind}`,
      type: `${duct.system} ${duct.kind}`,
      source,
      details: [
        ["size", `${fmt(duct.width * 1000)} x ${fmt(duct.height * 1000)} mm`],
        ["air", `${fmt(duct.flow_m3h)} m3/h`],
        ["velocity", `${fmt(duct.velocity_m_s)} m/s (at most ${fmt(duct.velocity_max_m_s)})${over ? ": too fast" : ""}`],
        ["length", `${fmt(duct.length)} m`],
        ...(duct.serves?.length ? [["serves", duct.serves.join(", ")] as [string, string]] : []),
        ...(duct.method ? [["routed", duct.method] as [string, string]] : []),
        ...(duct.reason ? [["why", duct.reason] as [string, string]] : []),
      ],
      sheetFile: null,
      highlight: null,
      related: [{ key: unitKey, label: duct.unit }, ...(duct.serves ?? []).map((r) => ({ key: `hvac_room:${r}`, label: r }))],
      line: null,
      review,
    });
    // A unit marks every duct it feeds; a room the ducts that carry its air.
    for (const owner of [unitKey, ...(duct.serves ?? []).map((r) => `hvac_room:${r}`)]) {
      const route = routes.get(owner) ?? { items: [], paths: [] };
      route.items.push(key);
      routes.set(owner, route);
    }
  }

  function hvacRoomMeshes(room: ModelHvacRoom): void {
    const key = `hvac_room:${room.id}`;
    const source = asSource(room.source);
    for (const t of room.terminals ?? [])
      for (const part of t.parts ?? []) {
        const prim = partPrim(part);
        if (!prim) continue;
        index(part.id, key);
        push({ key: part.id, layer: "ducts", item: key, prim, color: STRUCTURE_COLORS[part.material] ?? STEEL_COLOR, material: part.material || "grille_supply", opacity: 1, source: asSource(part.source) ?? source, ...lodOf(part) });
      }
    const [x0, y0, x1, y1] = room.extent;
    itemBounds.set(key, unionBox(itemBounds.get(key), { min: [x0, y0, room.floor], max: [x1, y1, room.floor + room.height] }));
    index(room.id, key);
    const supply = room.terminals.filter((t) => t.system === "supply").length;
    items.set(key, {
      kind: "hvac_room",
      id: room.id,
      title: room.title || "Ventilated room",
      type: "ventilated room",
      source,
      details: [
        ["building", `${room.building}${room.level ? ` / ${room.level}` : ""}`],
        ["volume", `${fmt(room.volume_m3)} m3`],
        ["air changes", `${fmt(room.air_changes_per_h)} per hour`],
        ["supply", `${fmt(room.supply_m3h)} m3/h`],
        ["extract", `${fmt(room.extract_m3h)} m3/h`],
        ["terminals", `${supply} supply, ${room.terminals.length - supply} extract`],
        ...(room.basis ? [["basis", room.basis] as [string, string]] : []),
      ],
      sheetFile: null,
      highlight: null,
      related: [{ key: `hvac_unit:${room.unit}`, label: room.unit }],
      line: null,
      review: false,
    });
    if (items.has(`hvac_unit:${room.unit}`)) items.get(`hvac_unit:${room.unit}`)!.related.push({ key, label: room.id });
  }

  function zoneMeshes(zone: ModelZone): void {
    const key = `zone:${zone.id}`;
    const color = zoneColor(zone.kind);
    const source = asSource(zone.source);
    const volumes: ZoneVolume[] = zone.volumes;
    let box: Box3 | undefined;
    const shapes = new Set<string>();
    const sources: string[] = [];
    volumes.forEach((v, i) => {
      const prim = volumePrim(v);
      if (!prim) return;
      shapes.add(v.shape);
      if (v.item && !sources.includes(v.item)) sources.push(v.item);
      push({ key: i ? `${key}:v${i}` : key, layer: "zones", item: key, prim, color, material: "zone", opacity: 0.16, source: asSource(v.source) ?? source });
      box = unionBox(box, primBounds(prim));
    });
    if (!box) return;
    index(zone.id, key);
    const basis = zone.basis || volumes.find((v) => v.basis)?.basis || null;
    items.set(key, {
      kind: "zone",
      id: zone.id,
      title: zone.title ?? null,
      type: zone.kind.replace(/_/g, " ") + (zone.zone != null ? ` (zone ${zone.zone})` : ""),
      source,
      details: [
        ["shape", [...shapes].join(", ")],
        ...(volumes.length > 1 ? [["volumes", String(volumes.length)] as [string, string]] : []),
        ...(sources.length ? [["sources", sources.join(", ")] as [string, string]] : []),
        ["extent", `${fmtVec(box.min)} - ${fmtVec(box.max)}`],
        ...(basis ? [["basis", basis] as [string, string]] : []),
      ],
      sheetFile: null,
      highlight: null,
      related: [],
      line: null,
      review: false,
    });
  }
}

/** The unit direction of the run of a polyline nearest to `p` (+x without one). */
export function segmentDirection(points: readonly Vec3[], p: Vec3): Vec3 {
  let best: Vec3 = [1, 0, 0];
  let bestDistance = Infinity;
  for (let i = 1; i < points.length; i++) {
    const a = points[i - 1]!;
    const b = points[i]!;
    const ab = sub(b, a);
    const len2 = dot(ab, ab);
    if (len2 < 1e-12) continue;
    const t = Math.min(Math.max(dot(sub(p, a), ab) / len2, 0), 1);
    const distance = length3(sub(p, add(a, scale(ab, t))));
    if (distance < bestDistance) {
      bestDistance = distance;
      best = norm(ab);
    }
  }
  return best;
}

/** How far a box reaches along a unit direction (its full extent). */
function boxExtent(prim: Extract<Prim, { kind: "box" }>, d: Vec3): number {
  const c = Math.cos(prim.rotationZ);
  const sn = Math.sin(prim.rotationZ);
  return Math.abs(d[0] * c + d[1] * sn) * prim.size[0] + Math.abs(-d[0] * sn + d[1] * c) * prim.size[1] + Math.abs(d[2]) * prim.size[2];
}

/**
 * The straight runs of a duct or tray (one box per run, ending at the corner points) lengthened
 * into their neighbours at each corner, so a bend is closed instead of notched: each run end
 * reaches half the neighbour's extent along the run. Other part lists come back as they are.
 */
export function joinRuns(prims: readonly Prim[], points: readonly Vec3[]): Prim[] {
  if (prims.length < 2 || prims.length !== points.length - 1 || !prims.every((p): p is Extract<Prim, { kind: "box" }> => p.kind === "box")) return [...prims];
  const boxes = prims;
  return boxes.map((box, i) => {
    const a = points[i]!;
    const b = points[i + 1]!;
    const run = sub(b, a);
    const len = length3(run);
    if (len < 1e-9) return box;
    const d = scale(run, 1 / len);
    const before = i > 0 ? boxExtent(boxes[i - 1]!, d) / 2 : 0;
    const after = i < boxes.length - 1 ? boxExtent(boxes[i + 1]!, d) / 2 : 0;
    if (!before && !after) return box;
    const vertical = Math.abs(d[2]) > 0.9;
    const size: Vec3 = [...box.size];
    size[vertical ? 2 : 0] += before + after;
    return { ...box, centre: round3(add(box.centre, scale(d, (after - before) / 2))), size };
  });
}

/**
 * The way a cable takes, as one polyline: from its start, along its trays in order (each turned
 * to continue from where the last one ended), to its end; a cable without trays runs straight.
 */
export function cablePath(cable: Pick<ModelCable, "from_point" | "to_point" | "trays">, trays: ReadonlyMap<string, Pick<ModelTray, "points" | "depth">>): Vec3[] {
  const out: Vec3[] = [];
  const add1 = (p: Vec3) => {
    const last = out[out.length - 1];
    if (!last || length3(sub(p, last)) > 1e-6) out.push(round3(p));
  };
  if (isVec3(cable.from_point)) add1(cable.from_point);
  for (const id of cable.trays) {
    const tray = trays.get(id);
    const points = (tray?.points ?? []).filter(isVec3).map((p): Vec3 => [p[0], p[1], p[2] + (tray?.depth ?? 0) / 2]);
    if (!points.length) continue;
    const last = out[out.length - 1];
    if (last && length3(sub(points[points.length - 1]!, last)) < length3(sub(points[0]!, last))) points.reverse();
    for (const p of points) add1(p);
  }
  if (isVec3(cable.to_point)) add1(cable.to_point);
  return out;
}

/** The primitive of one zone volume, or null when its fields are incomplete. */
export function volumePrim(v: ZoneVolume): Prim | null {
  if (v.shape === "box" && Array.isArray(v.box) && v.box.length === 6) {
    const [x0, y0, z0, x1, y1, z1] = v.box;
    return { kind: "box", centre: [(x0 + x1) / 2, (y0 + y1) / 2, (z0 + z1) / 2], size: [Math.abs(x1 - x0), Math.abs(y1 - y0), Math.abs(z1 - z0)], rotationZ: 0 };
  }
  if (!isVec3(v.centre) || !pos(v.radius, 0)) return null;
  const r = v.radius!;
  if (v.shape === "sphere") return { kind: "ellipsoid", centre: [...v.centre], radii: [r, r, r], rotationZ: 0 };
  const h = pos(v.height, r);
  return { kind: "cylinder", start: [...v.centre], end: [v.centre[0], v.centre[1], v.centre[2] + h], radius: r, radiusEnd: r };
}

/** A part as a primitive, or null when its fields are incomplete. */
/** A part's level of detail as a mesh field: `{lod: 1}` (envelope only), `{lod: 2}` (detail only), else nothing. */
export function lodOf(part: Pick<ModelPart, "lod">): { lod?: number } {
  if (typeof part.lod !== "number" || !Number.isFinite(part.lod)) return {};
  return { lod: part.lod >= 2 ? 2 : 1 };
}

export function partPrim(part: ModelPart): Prim | null {
  switch (part.kind) {
    case "cylinder":
    case "cone":
      if (!isVec3(part.start) || !isVec3(part.end) || !pos(part.radius, 0)) return null;
      return { kind: "cylinder", start: [...part.start], end: [...part.end], radius: part.radius!, radiusEnd: part.kind === "cone" ? Math.max(part.radius_end ?? 0, 0) : part.radius! };
    case "cap":
      if (!isVec3(part.centre) || !isVec3(part.axis) || !pos(part.radius, 0)) return null;
      return { kind: "cap", centre: [...part.centre], axis: norm(part.axis), radius: part.radius!, depth: pos(part.depth, part.radius!) };
    case "box":
      if (!isVec3(part.centre) || !isVec3(part.size)) return null;
      return { kind: "box", centre: [...part.centre], size: [...part.size], rotationZ: ((part.rotation_deg ?? 0) * Math.PI) / 180 };
    case "sphere":
      if (!isVec3(part.centre) || !pos(part.radius, 0)) return null;
      return { kind: "ellipsoid", centre: [...part.centre], radii: [part.radius!, part.radius!, part.radius!], rotationZ: 0 };
    case "member": {
      if (!isVec3(part.start) || !isVec3(part.end)) return null;
      const [b, h] = Array.isArray(part.profile) && part.profile.length === 2 ? part.profile : [0.2, 0.2];
      return { kind: "beam", start: [...part.start], end: [...part.end], width: pos(b, 0.2), depth: pos(h, 0.2) };
    }
    case "annulus": {
      if (!isVec3(part.centre) || !pos(part.radius_end, 0)) return null;
      const arc = Array.isArray(part.arc_deg) && part.arc_deg.length === 2 ? part.arc_deg : null;
      return { kind: "annulus", centre: [...part.centre], inner: Math.max(part.radius ?? 0, 0), outer: part.radius_end!, depth: pos(part.depth, 0.03), arc: arc ? [arc[0], arc[1]] : null };
    }
    case "torus": {
      const tube = pos(part.tube, 0);
      if (!isVec3(part.centre) || !pos(part.radius, 0) || !tube) return null;
      const arc = Array.isArray(part.arc_deg) && part.arc_deg.length === 2 ? part.arc_deg : null;
      const axis = isVec3(part.axis) && length3(part.axis) > 1e-9 ? norm(part.axis) : ([0, 0, 1] as Vec3);
      const ref = isVec3(part.ref) ? ringBasis(axis, part.ref)[0] : null;
      return { kind: "torus", centre: [...part.centre], axis, radius: part.radius!, tube, arc: arc ? [arc[0], arc[1]] : null, ...(ref ? { ref } : {}) };
    }
    case "frustum": {
      // Upright, as core draws it: `centre` of the bottom face, `size` [dx, dy, height], `size_end` [dx, dy] of the top.
      if (isVec3(part.centre) && Array.isArray(part.size) && part.size.length === 3 && part.size.every((v) => Number.isFinite(v))) {
        const [dx, dy, h] = part.size as [number, number, number];
        if (!(h > 0)) return null;
        const top = isPair(part.size_end) ? part.size_end : [dx, dy];
        return {
          kind: "frustum",
          start: [...part.centre],
          end: [part.centre[0], part.centre[1], part.centre[2] + h],
          size: [Math.max(dx, 0), Math.max(dy, 0)],
          sizeEnd: [Math.max(top[0]!, 0), Math.max(top[1]!, 0)],
          rotationZ: ((part.rotation_deg ?? 0) * Math.PI) / 180,
        };
      }
      if (!isVec3(part.start) || !isVec3(part.end) || length3(sub(part.end, part.start)) < 1e-9) return null;
      // A round frustum is a cone.
      if (!isPair(part.size) && pos(part.radius, 0)) return { kind: "cylinder", start: [...part.start], end: [...part.end], radius: part.radius!, radiusEnd: Math.max(part.radius_end ?? part.radius!, 0) };
      if (!isPair(part.size)) return null;
      const size: [number, number] = [Math.max(part.size[0]!, 0), Math.max(part.size[1]!, 0)];
      const sizeEnd: [number, number] = isPair(part.size_end) ? [Math.max(part.size_end[0]!, 0), Math.max(part.size_end[1]!, 0)] : size;
      if (Math.max(...size, ...sizeEnd) <= 0) return null;
      return { kind: "frustum", start: [...part.start], end: [...part.end], size, sizeEnd, rotationZ: ((part.rotation_deg ?? 0) * Math.PI) / 180 };
    }
    default:
      return null;
  }
}

// ---------------------------------------------------------------------------------------------
// View helpers: section box, walking, measuring.

/**
 * Clipping planes of a section box as `{normal, constant}` (three.js `Plane`: a point p is kept
 * where `normal . p + constant >= 0`), in the order -x, +x, -y, +y, -z, +z faces.
 */
export function sectionPlanes(box: Box3): { normal: Vec3; constant: number }[] {
  return [
    { normal: [1, 0, 0], constant: -box.min[0] },
    { normal: [-1, 0, 0], constant: box.max[0] },
    { normal: [0, 1, 0], constant: -box.min[1] },
    { normal: [0, -1, 0], constant: box.max[1] },
    { normal: [0, 0, 1], constant: -box.min[2] },
    { normal: [0, 0, -1], constant: box.max[2] },
  ];
}

/** Whether a point is kept by a section box. */
export function insideSection(box: Box3, p: Vec3): boolean {
  return sectionPlanes(box).every((plane) => dot(plane.normal, p) + plane.constant >= -1e-9);
}

/** A section box from slider fractions (0..1 per bound) of the scene bounds, min never above max. */
export function sectionFromFractions(bounds: Box3, f: { min: Vec3; max: Vec3 }): Box3 {
  const min: Vec3 = [0, 0, 0];
  const max: Vec3 = [0, 0, 0];
  for (let i = 0; i < 3; i++) {
    const lo = bounds.min[i]!;
    const span = bounds.max[i]! - lo;
    const a = Math.min(Math.max(f.min[i]!, 0), 1);
    const b = Math.min(Math.max(f.max[i]!, 0), 1);
    min[i] = r6(lo + span * Math.min(a, b));
    max[i] = r6(lo + span * Math.max(a, b));
  }
  return { min, max };
}

/** Whether `[x, y]` is inside a plan polygon (even-odd rule). */
export function inPolygon([x, y]: [number, number], polygon: [number, number][]): boolean {
  let inside = false;
  for (let i = 0, j = polygon.length - 1; i < polygon.length; j = i++) {
    const [xi, yi] = polygon[i]!;
    const [xj, yj] = polygon[j]!;
    if (yi > y !== yj > y && x < ((xj - xi) * (y - yi)) / (yj - yi) + xi) inside = !inside;
  }
  return inside;
}

/** Eye height above the floor in walk mode, m. */
export const EYE_HEIGHT = 1.7;
/** How far a walker steps up onto a floor without a level change, m. */
export const STEP_UP = 0.5;

/** Elevations of the floors under `[x, y]` (the ground at 0 always), lowest first. */
export function floorsAt(floors: Floor[], x: number, y: number): number[] {
  const out = new Set<number>([0]);
  for (const f of floors) if (inPolygon([x, y], f.polygon)) out.add(f.elevation);
  return [...out].sort((a, b) => a - b);
}

/** The floor a walker with feet at `feetZ` stands on: the highest one at most {@link STEP_UP} above the feet. */
export function snapFloor(floors: Floor[], x: number, y: number, feetZ: number): number {
  const levels = floorsAt(floors, x, y);
  let best = levels[0]!;
  for (const z of levels) if (z <= feetZ + STEP_UP) best = z;
  return best;
}

/** The next floor up (`+1`) or down (`-1`) from `feetZ` under `[x, y]`; the same floor at the top or bottom. */
export function stepFloor(floors: Floor[], x: number, y: number, feetZ: number, dir: 1 | -1): number {
  const levels = floorsAt(floors, x, y);
  const current = snapFloor(floors, x, y, feetZ);
  const i = levels.indexOf(current);
  return levels[Math.min(Math.max(i + dir, 0), levels.length - 1)]!;
}

/** Distance between two picked points, with its components. */
export function measure(a: Vec3, b: Vec3): { distance: number; dx: number; dy: number; dz: number; horizontal: number } {
  const d = sub(b, a);
  const [dx, dy, dz] = [r6(Math.abs(d[0])), r6(Math.abs(d[1])), r6(Math.abs(d[2]))];
  return { distance: r6(length3(sub(b, a))), dx, dy, dz, horizontal: r6(Math.hypot(dx, dy)) };
}

// ---------------------------------------------------------------------------------------------
// Declared operators, remote transmitters and hatches: the model declares them, the
// viewer draws them. Heights follow core's rules (`domains/spatial/access_rules.py`).

/** Height of a remote operator's or spindle's pedestal handwheel above its floor, m (core's PEDESTAL_M, ASSUMED there). */
export const PEDESTAL_M = 1.0;
/** Height of a remote-mounted transmitter on its stand above its floor, m (core's STAND_M). */
export const STAND_M = 1.2;
/** In plan, how far from a floor an operator reaches, m (core's `operator_reach_m` default). */
export const OPERATOR_REACH_M = 0.6;
/** Where a chain wheel's chain loop ends above the floor, m. ASSUMED: about hand height; drawing only, no rule uses it. */
export const CHAIN_LOOP_M = 1.0;
export const OPERATOR_COLOR = "#6b7480";
export const CHAIN_COLOR = "#d97706";
export const HATCH_COLOR = "#e0a526";
/** Walking levels that are stair flights (no operating position, as in core's rules): treads, not landings. */
const STAIR_FLIGHT = /\/flight-|\/tread-|stair-tread/;
/** Core's parts of a transmitter on its tapping that a remote mount replaces. */
const REMOTE_HEAD_PARTS = /\/(transmitter|transmitter-cap|bracket)$/;

/** How a declared operator reads in the side panel. */
export function operatorTitle(op: ModelOperator): string {
  const kind = op.kind.replace(/_/g, " ").replace("chainwheel", "chain wheel");
  const extra = [op.via, op.use ? `${op.use} use` : null].filter(Boolean);
  return extra.length ? `${kind} (${extra.join(", ")})` : kind;
}

/** Plan distance from `[x, y]` to a floor polygon (0 inside). */
export function planDistance(polygon: [number, number][], x: number, y: number): number {
  if (inPolygon([x, y], polygon)) return 0;
  const [px, py] = nearestOnEdges(polygon, x, y);
  return Math.hypot(px - x, py - y);
}

function nearestOnEdges(polygon: [number, number][], x: number, y: number): [number, number] {
  let best: [number, number] = polygon[0] ?? [x, y];
  let bestD = Infinity;
  for (let i = 0, j = polygon.length - 1; i < polygon.length; j = i++) {
    const [ax, ay] = polygon[j]!;
    const [bx, by] = polygon[i]!;
    const dx = bx - ax;
    const dy = by - ay;
    const l2 = dx * dx + dy * dy;
    const t = l2 > 0 ? Math.max(0, Math.min(1, ((x - ax) * dx + (y - ay) * dy) / l2)) : 0;
    const p: [number, number] = [ax + t * dx, ay + t * dy];
    const d = Math.hypot(p[0] - x, p[1] - y);
    if (d < bestD) {
      bestD = d;
      best = p;
    }
  }
  return best;
}

/** A floor an operator or stand is brought to, and where on it in plan. */
export interface FloorTarget {
  id: string;
  elevation: number;
  /** Plan point on the floor: `p` itself over the floor, else the floor's nearest point, a little inside. */
  at: [number, number];
}

/**
 * The floor core brings a remote operator or transmitter to: the shortest orthogonal run from
 * `p` to `lift` above a floor no higher than `p` (+0.05 m), counting the plan distance beyond
 * {@link OPERATOR_REACH_M} (core's `nearest_floor`). Grade is always one.
 */
export function nearestFloor(floors: readonly Floor[], p: Vec3, lift: number): FloorTarget {
  let best: FloorTarget = { id: "grade", elevation: 0, at: [p[0], p[1]] };
  let bestRun = Math.abs(p[2] - lift);
  for (const f of floors) {
    if (f.elevation > p[2] + 0.05) continue;
    const d = planDistance(f.polygon, p[0], p[1]);
    const run = Math.max(d - OPERATOR_REACH_M, 0) + Math.abs(p[2] - (f.elevation + lift));
    if (run < bestRun - 1e-9) {
      bestRun = run;
      best = { id: f.id, elevation: f.elevation, at: d === 0 ? [p[0], p[1]] : inside(f.polygon, p[0], p[1]) };
    }
  }
  return best;
}

/** The polygon's nearest point to `[x, y]`, moved 0.15 m towards its centre (to stand on, not on the edge). */
function inside(polygon: [number, number][], x: number, y: number): [number, number] {
  const [px, py] = nearestOnEdges(polygon, x, y);
  const cx = polygon.reduce((s, q) => s + q[0], 0) / polygon.length;
  const cy = polygon.reduce((s, q) => s + q[1], 0) / polygon.length;
  const l = Math.hypot(cx - px, cy - py);
  const k = l > 0.15 ? 0.15 / l : 0;
  return [r6(px + (cx - px) * k), r6(py + (cy - py) * k)];
}

/** Where a valve is operated from: core's handwheel (or lever, gearbox, actuator), else above the body. */
export function operatorWheel(inline: Pick<ModelInlineItem, "point" | "direction" | "parts">): { centre: Vec3; axis: Vec3; radius: number } {
  const parts = inline.parts ?? [];
  const named = (name: string) => parts.find((part) => part.id.endsWith(`/${name}`));
  const wheel = named("handwheel");
  if (wheel && wheel.kind === "torus" && isVec3(wheel.centre) && isVec3(wheel.axis)) return { centre: [...wheel.centre], axis: norm(wheel.axis), radius: pos(wheel.radius, 0.2) };
  const lever = named("lever");
  if (lever && isVec3(lever.end)) return { centre: [...lever.end], axis: [0, 0, 1], radius: 0.15 };
  for (const name of ["gearbox", "actuator"]) {
    const part = named(name);
    if (part && isVec3(part.centre)) return { centre: [...part.centre], axis: [0, 0, 1], radius: 0.15 };
  }
  return { centre: round3(add(inline.point, [0, 0, 0.3])), axis: [0, 0, 1], radius: 0.15 };
}

/**
 * A chain wheel beside the handwheel and its chain: two falls from either side of the wheel in
 * its plane, joined at the bottom, {@link CHAIN_LOOP_M} above the highest floor under the wheel
 * within reach (but at least 0.3 m below the wheel).
 */
export function chainWheelGeometry(wheel: { centre: Vec3; axis: Vec3; radius: number }, floors: readonly Floor[]): { centre: Vec3; radius: number; chain: [Vec3, Vec3][]; bottom: number; floor: { id: string; elevation: number } } {
  const centre = round3(add(wheel.centre, scale(wheel.axis, 0.06)));
  const radius = Math.max(wheel.radius, 0.15);
  let floor = { id: "grade", elevation: 0 };
  for (const f of floors)
    if (f.elevation <= wheel.centre[2] + 0.05 && f.elevation > floor.elevation && planDistance(f.polygon, wheel.centre[0], wheel.centre[1]) <= OPERATOR_REACH_M) floor = { id: f.id, elevation: f.elevation };
  const bottom = r6(Math.max(Math.min(floor.elevation + CHAIN_LOOP_M, centre[2] - radius - 0.3), floor.elevation + 0.1));
  // Across the wheel, level: the chain falls from the two ends of the wheel's horizontal diameter.
  const flat = cross(wheel.axis, [0, 0, 1]);
  const h: Vec3 = length3(flat) > 1e-6 ? norm(flat) : [1, 0, 0];
  const top = (k: number) => round3(add(centre, scale(h, k * radius)));
  const foot = (k: number): Vec3 => { const t = top(k); return [t[0], t[1], bottom]; };
  return { centre, radius, chain: [[top(1), foot(1)], [top(-1), foot(-1)], [foot(1), foot(-1)]], bottom, floor };
}

/** A rod from `from` to a pedestal `lift` above the nearest floor: down (or up), then across. */
export function pedestalGeometry(from: Vec3, floors: readonly Floor[], lift: number): { path: Vec3[]; at: [number, number]; top: number; floor: FloorTarget; length: number } {
  const floor = nearestFloor(floors, from, lift);
  const top = r6(floor.elevation + lift);
  const path: Vec3[] = [[...from], [from[0], from[1], top]];
  if (Math.hypot(floor.at[0] - from[0], floor.at[1] - from[1]) > 1e-6) path.push([floor.at[0], floor.at[1], top]);
  return { path, at: floor.at, top, floor, length: r6(polylineLength(path)) };
}

/**
 * Impulse lines or a capillary from a tapping to a stand: first level out of the item's plan
 * (bbox `[x0, y0, z0, x1, y1, z1]`) by 0.3 m on its nearest side when the tapping is over it,
 * then as {@link pedestalGeometry} to {@link STAND_M} above the nearest floor (the transmitter's
 * bottom at that height). `across` is the plan direction the paired lines are spread along.
 */
export function standGeometry(from: Vec3, bbox: readonly number[], floors: readonly Floor[]): { path: Vec3[]; at: [number, number]; top: number; floor: FloorTarget; length: number; across: Vec3 } {
  const [x0, y0, , x1, y1] = bbox as [number, number, number, number, number, number];
  let start: Vec3 = [...from];
  const lead: Vec3[] = [];
  if (bbox.length === 6 && from[0] > x0 && from[0] < x1 && from[1] > y0 && from[1] < y1) {
    const sides: [number, Vec3][] = [
      [from[0] - x0, [x0 - 0.3, from[1], from[2]]],
      [x1 - from[0], [x1 + 0.3, from[1], from[2]]],
      [from[1] - y0, [from[0], y0 - 0.3, from[2]]],
      [y1 - from[1], [from[0], y1 + 0.3, from[2]]],
    ];
    sides.sort((a, b) => a[0] - b[0]);
    lead.push([...from]);
    start = round3(sides[0]![1]);
  }
  const g = pedestalGeometry(start, floors, STAND_M);
  const path = [...lead, ...g.path];
  const last = path.length > 1 ? sub(path[path.length - 1]!, path[path.length - 2]!) : ([1, 0, 0] as Vec3);
  const flat: Vec3 = [last[0], last[1], 0];
  const across: Vec3 = length3(flat) > 1e-6 ? norm([-flat[1], flat[0], 0]) : [1, 0, 0];
  return { ...g, path, length: r6(polylineLength(path)), across };
}

/** Where core's tapping ends (its impulse line's far end), else 0.3 m out of the nozzle. */
function remoteStart(nozzle: ModelNozzle, parts: readonly ModelPart[]): Vec3 {
  const lines = parts.filter((part) => /\/impulse-\d+$/.test(part.id) && isVec3(part.end)).sort((a, b) => a.id.localeCompare(b.id));
  const last = lines[lines.length - 1];
  if (last && isVec3(last.end)) return [...last.end];
  return round3(add(nozzle.point, scale(norm(nozzle.direction), 0.3)));
}

/**
 * A hatch in a wall of a frame or building (own frame `origin`, `rotation` about z): a frame of
 * four bars round the opening and a closed cover, on the wall's outer face. The wall stands
 * outside the side, `t` thick (core's walls; t from the side's wall panels, else 0.1 m).
 */
export function hatchGeometry(
  opening: BuildingOpening,
  owner: { id: string; origin: [number, number]; rotation: number; width: number; depth: number; walls: readonly ModelPart[] },
): { frame: Prim[]; cover: Prim; centre: Vec3 } | null {
  const sides: Record<string, [[number, number], [number, number], [number, number]]> = {
    south: [[0, 0], [owner.width, 0], [0, -1]],
    east: [[owner.width, 0], [owner.width, owner.depth], [1, 0]],
    north: [[owner.width, owner.depth], [0, owner.depth], [0, 1]],
    west: [[0, owner.depth], [0, 0], [-1, 0]],
  };
  const side = sides[opening.side];
  if (!side) return null;
  const [left, right, normal] = side;
  const length = Math.hypot(right[0] - left[0], right[1] - left[1]);
  const u: [number, number] = [(right[0] - left[0]) / length, (right[1] - left[1]) / length];
  const panels = owner.walls.filter((w) => w.kind === "box" && w.id.startsWith(`${owner.id}/wall-${opening.side}`) && Array.isArray(w.size));
  // Panels are boxes in the owner's frame: the wall's thickness is their extent along the normal.
  const across = panels.map((w) => w.size![normal[0] !== 0 ? 0 : 1]!).filter((v) => v > 0).sort((p, q) => p - q);
  const t = across.length ? across[Math.floor(across.length / 2)]! : 0.1;
  const rot = (owner.rotation * Math.PI) / 180;
  const c = Math.round(Math.cos(rot) * 1e12) / 1e12;
  const s = Math.round(Math.sin(rot) * 1e12) / 1e12;
  const site = (sAlong: number, d: number, z: number): Vec3 => {
    const fx = left[0] + u[0] * sAlong + normal[0] * d;
    const fy = left[1] + u[1] * sAlong + normal[1] * d;
    return round3([owner.origin[0] + fx * c - fy * s, owner.origin[1] + fx * s + fy * c, z]);
  };
  const s0 = opening.offset;
  const s1 = opening.offset + opening.width;
  const z0 = opening.sill ?? 0;
  const z1 = z0 + opening.height;
  const bar = 0.08;
  const d = t + 0.04;
  const zRot = Math.atan2(u[1] * c + u[0] * s, u[0] * c - u[1] * s);
  const boxAt = (sa: number, sb: number, za: number, zb: number, d0: number, d1: number): Prim => {
    const centre = site((sa + sb) / 2, (d0 + d1) / 2, (za + zb) / 2);
    return { kind: "box", centre, size: [r6(Math.abs(sb - sa)), r6(Math.abs(d1 - d0)), r6(Math.abs(zb - za))], rotationZ: r6(zRot) };
  };
  const frame = [
    boxAt(s0 - bar, s1 + bar, z0 - bar, z0, t - 0.02, d),
    boxAt(s0 - bar, s1 + bar, z1, z1 + bar, t - 0.02, d),
    boxAt(s0 - bar, s0, z0, z1, t - 0.02, d),
    boxAt(s1, s1 + bar, z0, z1, t - 0.02, d),
  ];
  const cover = boxAt(s0, s1, z0, z1, t, t + 0.03);
  return { frame, cover, centre: site((s0 + s1) / 2, t, (z0 + z1) / 2) };
}
