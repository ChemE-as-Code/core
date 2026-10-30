/**
 * A folder of plants served by `cheme serve` (library mode, core's ADR 0034): every plant under
 * `/p/<id>/`, the list at `/api/plants`. The viewer reads its plant from the page's path (the API
 * base and the router base), shows an index of the plants at `/` of a library, and switches plant
 * with a page load, so no state of one plant reaches the next.
 */
import type { PlantEntry } from "@/api";

/** `/p/<id>/...` of a library server: the plant's id and its base (`/p/<id>/`). */
export function plantFromPath(pathname: string): { id: string; base: string } | null {
  const match = /^\/p\/([^/]+)\//.exec(pathname);
  if (!match) return null;
  let id: string;
  try {
    id = decodeURIComponent(match[1]!);
  } catch {
    return null;
  }
  return { id, base: `/p/${match[1]}/` };
}

/** Pages that show one plant-wide view (no file, sheet or tag): kept when switching plant. */
const KEPT_PAGES = new Set([
  "streams",
  "reactions",
  "checks",
  "reviews",
  "validate",
  "maturity",
  "layout",
  "mto",
  "datasheets",
  "lca",
  "tea",
  "cause-effect",
  "control",
  "issues",
  "history",
  "library",
  "about",
]);

/** The page options that survive a switch (src/lib/viewerOptions.ts). */
const KEPT_QUERY = ["embed", "theme"];

/**
 * The URL of plant `id` showing the same page as `route` when it is a plant-wide one (the stream
 * table, the LCA, ...), else its overview; the page options are kept, the revision and the
 * page's own query are not (another plant may not have them).
 */
export function switchUrl(id: string, route: { name: string; path: string }, search: string): string {
  const params = new URLSearchParams(search);
  const kept = new URLSearchParams();
  for (const key of KEPT_QUERY) {
    const value = params.get(key);
    if (value !== null) kept.set(key, value);
  }
  const page = KEPT_PAGES.has(route.name) ? route.path.replace(/^\/+/, "") : "";
  const query = kept.toString();
  return `/p/${encodeURIComponent(id)}/${page}${query ? `?${query}` : ""}`;
}

/** The library index (`/`), with the page options kept. */
export function indexUrl(search: string): string {
  const params = new URLSearchParams(search);
  const kept = new URLSearchParams();
  for (const key of KEPT_QUERY) {
    const value = params.get(key);
    if (value !== null) kept.set(key, value);
  }
  const query = kept.toString();
  return `/${query ? `?${query}` : ""}`;
}

/** What a plant is called on the index and in the switcher. */
export function plantName(plant: Pick<PlantEntry, "id" | "name" | "title">): string {
  return plant.name || plant.title || plant.id;
}

/** The plants matching a text (id, path, name, title, summary, families) and the filters. */
export function filterPlants(
  plants: readonly PlantEntry[],
  filters: { text?: string; family?: string; stage?: string },
): PlantEntry[] {
  const words = (filters.text ?? "").toLowerCase().split(/\s+/).filter(Boolean);
  return plants.filter((p) => {
    if (filters.family && !p.families.includes(filters.family)) return false;
    if (filters.stage && p.stage !== filters.stage) return false;
    const hay = [p.id, p.path, p.name, p.title, p.summary, ...p.families].filter(Boolean).join(" ").toLowerCase();
    return words.every((w) => hay.includes(w));
  });
}

/**
 * `?back=` of a snapshot (the Process Atlas page it was opened from): a link back, only to this
 * site (a relative URL or the same origin, http or https), never elsewhere; null otherwise.
 */
export function safeBackUrl(back: string | null, here: string): string | null {
  if (!back) return null;
  let url: URL;
  try {
    url = new URL(back, here);
  } catch {
    return null;
  }
  const origin = new URL(here).origin;
  if (url.origin !== origin || (url.protocol !== "http:" && url.protocol !== "https:")) return null;
  return url.pathname + url.search + url.hash;
}
