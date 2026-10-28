/**
 * Label decluttering for the 3D layout, on screen-space boxes: no three.js and no DOM, so the
 * rules are unit tested. The renderer projects each label, calls {@link declutter} and
 * {@link distanceFade} and shows what they keep.
 */

/** A label's box on screen (pixels, y down) and what decides whether it stays. */
export interface ScreenLabel {
  id: number;
  x0: number;
  y0: number;
  x1: number;
  y1: number;
  /** Higher wins an overlap (see `LABEL_PRIORITY`). */
  priority: number;
  /** The selection, its related objects and a finding's items: always kept, never hidden by others. */
  pinned?: boolean;
  /** Distance from the camera; of two equal priorities the nearer label wins. */
  depth?: number;
}

const CELL = 64;

export function overlaps(a: ScreenLabel, b: ScreenLabel, gap = 0): boolean {
  return a.x0 < b.x1 + gap && b.x0 < a.x1 + gap && a.y0 < b.y1 + gap && b.y0 < a.y1 + gap;
}

/** The labels to show: pinned first, then by priority, then nearest first; a label that overlaps one already kept is dropped. */
export function declutter(labels: readonly ScreenLabel[], gap = 2): Set<number> {
  const order = labels
    .map((l, i) => ({ l, i }))
    .sort(
      (a, b) =>
        Number(Boolean(b.l.pinned)) - Number(Boolean(a.l.pinned)) ||
        b.l.priority - a.l.priority ||
        (a.l.depth ?? 0) - (b.l.depth ?? 0) ||
        a.i - b.i,
    );
  const kept = new Set<number>();
  // A uniform grid of the kept boxes, so each test looks at its neighbours only.
  const grid = new Map<string, ScreenLabel[]>();
  const cells = (l: ScreenLabel): string[] => {
    const out: string[] = [];
    for (let cx = Math.floor((l.x0 - gap) / CELL); cx <= Math.floor((l.x1 + gap) / CELL); cx++)
      for (let cy = Math.floor((l.y0 - gap) / CELL); cy <= Math.floor((l.y1 + gap) / CELL); cy++) out.push(`${cx},${cy}`);
    return out;
  };
  for (const { l } of order) {
    const mine = cells(l);
    if (!l.pinned && mine.some((c) => grid.get(c)?.some((k) => overlaps(l, k, gap)))) continue;
    kept.add(l.id);
    for (const c of mine) {
      const list = grid.get(c);
      if (list) list.push(l);
      else grid.set(c, [l]);
    }
  }
  return kept;
}

/** Opacity of a label at `distance` from the camera: 1 up to `near`, fading to 0 at `far`. */
export function distanceFade(distance: number, near: number, far: number): number {
  if (!(distance > near)) return 1;
  if (distance >= far) return 0;
  return 1 - (distance - near) / (far - near);
}

/**
 * How far a label of `priority` stays readable in a plant of `span` m: line numbers only up
 * close, equipment tags and names across the plant. Returns where the fade starts and ends.
 */
export function labelRange(priority: number, span: number): { near: number; far: number } {
  const s = Math.max(span, 10);
  if (priority >= 100) return { near: Infinity, far: Infinity };
  const near = priority >= 40 ? Math.max(2 * s, 80) : priority >= 20 ? Math.max(1.5 * s, 60) : Math.max(s, 30);
  return { near, far: near * 1.5 };
}
