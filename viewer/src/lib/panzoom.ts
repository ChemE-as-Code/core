import { reactive } from "vue";

export interface View {
  x: number;
  y: number;
  k: number;
}

export const MIN_SCALE = 0.05;
export const MAX_SCALE = 40;

const clamp = (value: number, lo: number, hi: number) => Math.min(hi, Math.max(lo, value));

/** A pan/zoom transform; share one object between panes to keep them in sync. */
export function createView(): View {
  return reactive({ x: 0, y: 0, k: 1 });
}

/** Zoom by `factor` keeping the point (`px`, `py`) (in container pixels) fixed. */
export function zoomAt(view: View, factor: number, px: number, py: number): void {
  const k = clamp(view.k * factor, MIN_SCALE, MAX_SCALE);
  const ratio = k / view.k;
  view.x = px - (px - view.x) * ratio;
  view.y = py - (py - view.y) * ratio;
  view.k = k;
}

/** Scale and centre a `width` x `height` drawing in a `cw` x `ch` container. */
export function fitView(view: View, cw: number, ch: number, width: number, height: number, margin = 12): void {
  if (!width || !height || !cw || !ch) return;
  const k = clamp(Math.min((cw - 2 * margin) / width, (ch - 2 * margin) / height), MIN_SCALE, MAX_SCALE);
  view.k = k;
  view.x = (cw - width * k) / 2;
  view.y = (ch - height * k) / 2;
}

export function transformOf(view: View): string {
  return `translate(${view.x}px, ${view.y}px) scale(${view.k})`;
}
