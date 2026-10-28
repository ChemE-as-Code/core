/**
 * The layout view's state in the URL query, so a view can be shared and reloaded: selection,
 * visible layers, colour mode, x-ray, realistic look, level of detail, camera view or pose,
 * section box, tab and 2D settings.
 * Defaults are left out of the query.
 */
import { LAYERS, LAYERS_OFF, type Box3, type LayerId } from "./layoutModel";
import type { ViewName } from "./layoutScene";

export type Toggle = LayerId | "labels" | "lines" | "names";
export const TOGGLES: Toggle[] = [...LAYERS, "labels", "lines", "names"];
/** Off at first: the layers in `LAYERS_OFF`, and line numbers (equipment tags are on). */
export const TOGGLES_OFF: Toggle[] = [...LAYERS_OFF, "lines"];
export const DEFAULT_SHOWN: Toggle[] = TOGGLES.filter((t) => !TOGGLES_OFF.includes(t));

export type ColorMode = "normal" | "class" | "provenance";
export const COLOR_MODES: ColorMode[] = ["normal", "class", "provenance"];
/** Level of detail: by camera distance, all of it, or the envelopes only. */
export type DetailMode = "auto" | "full" | "envelope";
export const DETAIL_MODES: DetailMode[] = ["auto", "full", "envelope"];
const VIEW_NAMES: ViewName[] = ["iso", "top", "north", "east", "south", "west", "site"];

export interface LayoutUrlState {
  select: string | null;
  shown: Toggle[];
  mode: ColorMode;
  xray: boolean;
  /** Physically based materials, shadows and ambient occlusion. */
  realistic: boolean;
  detail: DetailMode;
  view: ViewName | null;
  /** Camera position and target, when the user moved it after the last named view. */
  cam: { position: [number, number, number]; target: [number, number, number] } | null;
  section: Box3 | null;
  tab: "3d" | "2d";
  /** 2D: `plan` or `section`, level id or `z` range, section axis and position. */
  plan: { kind: "plan" | "section"; level: string | null; z: string | null; axis: "x" | "y"; at: number | null };
}

type Raw = Record<string, unknown>;

function first(value: unknown): string | null {
  const v = Array.isArray(value) ? value[0] : value;
  return typeof v === "string" && v !== "" ? v : null;
}

/** `value` if it is one of `values`, else null. */
function oneOf<T extends string>(values: readonly T[], value: string | null): T | null {
  return values.find((v) => v === value) ?? null;
}

type Six = [number, number, number, number, number, number];

const isSix = (parts: number[]): parts is Six => parts.length === 6;

function sixNumbers(text: string | null): Six | null {
  if (!text) return null;
  const parts = text.split(",").map(Number);
  return isSix(parts) && parts.every(Number.isFinite) ? parts : null;
}

export function parseLayoutQuery(query: Raw): LayoutUrlState {
  const layers = first(query.layers);
  const shown = layers === null ? [...DEFAULT_SHOWN] : layers === "none" ? [] : layers.split(",").flatMap((t) => oneOf(TOGGLES, t) ?? []);
  const cam = sixNumbers(first(query.cam));
  const section = sixNumbers(first(query.section));
  const at = first(query.at);
  return {
    select: first(query.select),
    shown,
    mode: oneOf(COLOR_MODES, first(query.mode)) ?? "normal",
    xray: first(query.xray) === "1",
    realistic: first(query.look) === "realistic",
    detail: oneOf(DETAIL_MODES, first(query.detail)) ?? "auto",
    view: oneOf(VIEW_NAMES, first(query.view)),
    cam: cam ? { position: [cam[0], cam[1], cam[2]], target: [cam[3], cam[4], cam[5]] } : null,
    section: section
      ? {
          min: [Math.min(section[0], section[3]), Math.min(section[1], section[4]), Math.min(section[2], section[5])],
          max: [Math.max(section[0], section[3]), Math.max(section[1], section[4]), Math.max(section[2], section[5])],
        }
      : null,
    tab: first(query.tab) === "2d" ? "2d" : "3d",
    plan: {
      kind: first(query.drawing) === "section" ? "section" : "plan",
      level: first(query.level),
      z: first(query.z),
      axis: first(query.axis) === "y" ? "y" : "x",
      at: at !== null && Number.isFinite(Number(at)) ? Number(at) : null,
    },
  };
}

const r2 = (v: number) => String(Math.round(v * 100) / 100);

/** The query for a state: only what differs from the defaults (`undefined` removes a key). */
export function layoutQuery(state: LayoutUrlState): Record<string, string | undefined> {
  const shown = TOGGLES.filter((t) => state.shown.includes(t));
  const isDefault = shown.length === DEFAULT_SHOWN.length && DEFAULT_SHOWN.every((t) => shown.includes(t));
  return {
    select: state.select ?? undefined,
    layers: isDefault ? undefined : shown.length ? shown.join(",") : "none",
    mode: state.mode === "normal" ? undefined : state.mode,
    xray: state.xray ? "1" : undefined,
    look: state.realistic ? "realistic" : undefined,
    detail: state.detail === "auto" ? undefined : state.detail,
    view: state.cam ? undefined : (state.view ?? undefined),
    cam: state.cam ? [...state.cam.position, ...state.cam.target].map(r2).join(",") : undefined,
    section: state.section ? [...state.section.min, ...state.section.max].map(r2).join(",") : undefined,
    tab: state.tab === "2d" ? "2d" : undefined,
    drawing: state.tab === "2d" && state.plan.kind === "section" ? "section" : undefined,
    level: state.tab === "2d" && state.plan.kind === "plan" ? (state.plan.level ?? undefined) : undefined,
    z: state.tab === "2d" && state.plan.kind === "plan" && !state.plan.level ? (state.plan.z ?? undefined) : undefined,
    axis: state.tab === "2d" && state.plan.kind === "section" ? state.plan.axis : undefined,
    at: state.tab === "2d" && state.plan.kind === "section" && state.plan.at !== null ? r2(state.plan.at) : undefined,
  };
}
