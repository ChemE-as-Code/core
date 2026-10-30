<script setup lang="ts">
import { computed, onBeforeUnmount, onMounted, reactive, ref, shallowRef, watch } from "vue";
import { useRoute, useRouter, type LocationQueryRaw } from "vue-router";
import { api, ApiError, type Finding, type Layout } from "@/api";
import LoadState from "@/components/LoadState.vue";
import SvgPane from "@/components/SvgPane.vue";
import { useAsync } from "@/lib/useAsync";
import { FINDINGS_OPEN_MAX, groupFindings } from "@/lib/findings";
import { useRev } from "@/lib/useRev";
import { pathSegments, shortRev } from "@/lib/format";
import { sanitizeSvg, type SanitizedSvg } from "@/lib/sanitize";
import { createView } from "@/lib/panzoom";
import {
  buildScene,
  findingTargets,
  LAYER_TITLES,
  lineRouteSummary,
  resolveSelect,
  sheetFile,
  VIEWS,
  type Box3,
  type ViewName,
} from "@/lib/layoutScene";
import { COLOR_MODES, DETAIL_MODES, layoutQuery, parseLayoutQuery, TOGGLES, type ColorMode, type DetailMode, type Toggle } from "@/lib/layoutUrl";
import type { LayoutRenderer, MeasureResult, NavMode, Theme } from "@/lib/layoutThree";
import { store } from "@/store";
import { isDarkScheme } from "@/lib/viewerOptions";
import {
  CABLE_SCHEDULE_CSV,
  CABLE_SCHEDULE_MD,
  cableMatches,
  cableTotals,
  datasheetPaths,
  laneClear,
  LIFTING_STUDY_CSV,
  LIFTING_STUDY_MD,
  parseCableSchedule,
  parseLiftingStudy,
  sortCables,
  type CableColumn,
  type CableRow,
  type LiftingRow,
} from "@/lib/studies";

const route = useRoute();
const router = useRouter();
const { rev, withRev } = useRev();

/** The layout at `rev`, or null when there are no layout files there (a 404). */
const layout = useAsync<Layout | null>(async (signal) => {
  try {
    return await api.layout(rev.value, signal);
  } catch (error) {
    if (error instanceof ApiError && error.status === 404) return null;
    throw error;
  }
}, [rev]);

const scene = computed(() => (layout.data.value ? buildScene(layout.data.value, { sheets: store.repo?.sheets }) : null));
const missing = computed(() => !layout.loading.value && !layout.error.value && layout.data.value === null);
const model = computed(() => layout.data.value?.model ?? null);

// ---------------------------------------------------------------------------------------------
// State, mirrored in the URL query.
const state = reactive(parseLayoutQuery(route.query));
const OWN_KEYS = ["select", "layers", "mode", "xray", "look", "detail", "view", "cam", "section", "tab", "drawing", "level", "z", "axis", "at"];
watch(
  state,
  () => {
    const query: LocationQueryRaw = {};
    for (const [k, v] of Object.entries(route.query)) if (!OWN_KEYS.includes(k)) query[k] = v;
    for (const [k, v] of Object.entries(layoutQuery(state))) if (v !== undefined) query[k] = v;
    const same = JSON.stringify(query) === JSON.stringify(route.query);
    if (!same) void router.replace({ query });
  },
  { deep: true },
);
// A link to this view with another selection (the P&ID's "show in 3D").
watch(
  () => route.query.select,
  (value) => {
    const id = Array.isArray(value) ? value[0] : value;
    if (id && id !== state.select) {
      state.select = id;
      resolveAndFocus();
    }
  },
);

const TOGGLE_LABELS: Record<Toggle, string> = {
  site: "Site",
  areas: "Areas",
  roads: "Roads",
  buildings: "Buildings",
  structures: "Structures",
  platforms: "Platforms & stairs",
  equipment: "Equipment",
  nozzles: "Nozzles",
  pipes: "Pipes",
  insulation: "Insulation",
  inline: "In-line items",
  trays: "Cable trays",
  ducts: "HVAC ducts",
  zones: "Zones",
  envelopes: "Envelopes",
  labels: "Equipment tags",
  lines: "Line numbers",
  names: "Names",
};
const TOGGLE_TITLES: Record<Toggle, string> = {
  ...LAYER_TITLES,
  labels: "Equipment tags",
  lines: "Line numbers on the pipes (the selected pipe's always shows)",
  names: "Names of areas, buildings, racks and steel frames",
};
const COLOR_TITLES: Record<ColorMode, string> = { normal: "type & service", class: "pipe class", provenance: "provenance" };
const DETAIL_TITLES: Record<DetailMode, string> = { auto: "near", full: "full", envelope: "envelopes" };
const VIEW_LABELS: Record<ViewName, [string, string]> = {
  iso: ["Iso", "Isometric view from the south-west"],
  top: ["Top", "Plan view from above"],
  north: ["N", "From the north"],
  east: ["E", "From the east"],
  south: ["S", "From the south"],
  west: ["W", "From the west"],
  site: ["Site", "The whole plot from the south-west"],
};
const shown = computed(() => new Set(state.shown));
/** Mesh counts per layer, to grey out layers with nothing in them. */
const layerCount = (t: Toggle): number | null => {
  if (t === "labels" || t === "lines" || t === "names" || !scene.value) return null;
  return scene.value.meshes.filter((m) => m.layer === t).length + scene.value.lines.filter((l) => l.layer === t && !l.members).length + scene.value.edges.filter((e) => e.layer === t).length;
};

const selectedItem = computed(() => (state.select ? (scene.value?.items.get(state.select) ?? null) : null));
// cheme-as-code resolves the sheet file; the repo's sheet list is the fallback for an older cheme-as-code.
const selectedSheet = computed(() => selectedItem.value?.sheetFile ?? sheetFile(selectedItem.value?.sheet, store.repo?.sheets));
const pidLink = computed(() => {
  const item = selectedItem.value;
  const file = selectedSheet.value;
  if (!item || !file) return null;
  const highlight = item.highlight ?? null;
  return { name: "pid", params: { path: pathSegments(file) }, query: withRev(highlight ? { select: highlight } : {}) };
});
const legendOpen = ref(false);
/** Legend sections for the colour mode: title and rows. */
const legendSections = computed(() => {
  const l = scene.value?.legend;
  if (!l) return [];
  if (state.mode === "provenance") return [{ title: "Provenance", area: false, pipe: false, rows: l.provenance }];
  return [
    { title: "Areas", area: true, pipe: false, rows: l.areas },
    { title: "Equipment", area: false, pipe: false, rows: l.equipment },
    { title: state.mode === "class" ? "Pipe classes" : "Services", area: false, pipe: true, rows: state.mode === "class" ? l.pipeClasses : l.pipes },
    { title: "Zones", area: true, pipe: false, rows: l.zones },
    { title: "Trays, ducts and walls", area: false, pipe: true, rows: l.services },
  ].filter((s) => s.rows.length);
});
/** The layout's findings and those of the rules on the generated model (with a 3D box). */
const findings = computed<Finding[]>(() => [...(layout.data.value?.findings ?? []), ...(layout.data.value?.model_findings ?? [])]);
const lines = computed(() => layout.data.value?.lines ?? []);
const counts = computed(() => {
  const out = { error: 0, warning: 0, info: 0 };
  for (const f of findings.value) if (f.level in out) out[f.level]++;
  return out;
});
const activeFinding = ref<number | null>(null);
const findingGroups = computed(() => groupFindings(findings.value));
/** Open finding groups: all of a short list, none of a longer one at first. */
const openRules = ref(new Set<string>());
watch(
  findings,
  (list) => (openRules.value = new Set(list.length <= FINDINGS_OPEN_MAX ? list.map((f) => f.rule) : [])),
  { immediate: true },
);
function onGroupToggle(rule: string, event: Event): void {
  const open = (event.target as HTMLDetailsElement).open;
  if (open === openRules.value.has(rule)) return;
  const next = new Set(openRules.value);
  if (open) next.add(rule);
  else next.delete(rule);
  openRules.value = next;
}

// ---------------------------------------------------------------------------------------------
// The 3D renderer.
const container = ref<HTMLElement | null>(null);
const renderer = shallowRef<LayoutRenderer | null>(null);
const renderError = ref<string | null>(null);
const nav = ref<NavMode>("orbit");
const tool = ref<"pick" | "measure">("pick");
const measured = ref<MeasureResult | null>(null);
// The finding is an index into this revision's list, the measure a distance in its model.
watch(rev, () => {
  activeFinding.value = null;
  measured.value = null;
});
const flySpeed = ref(8);
const exporting = ref(false);
let generation = 0;

function cssVar(name: string, fallback: string): string {
  const value = getComputedStyle(document.documentElement).getPropertyValue(name).trim();
  return value || fallback;
}
function theme(): Theme {
  return {
    background: cssVar("--bg-soft", "#f5f6f8"),
    ground: cssVar("--bg-sunk", "#eceef2"),
    grid: cssVar("--fg-faint", "#8a929c"),
    dark: isDarkScheme(),
  };
}

/** Turn a link's id (tag, line, DEXPI id) into an item key and frame it. */
let focusPending = Boolean(state.select);
function resolveAndFocus(): void {
  const spec = scene.value;
  if (!spec || !state.select) return;
  const key = resolveSelect(state.select, spec);
  if (!key) return;
  state.select = key;
  if (focusPending || renderer.value) {
    renderer.value?.setSelected(key);
    renderer.value?.focus(key);
    focusPending = false;
  }
}

let cameraTimer = 0;
async function mount(): Promise<void> {
  const current = ++generation;
  disposeRenderer();
  renderError.value = null;
  nav.value = "orbit";
  const spec = scene.value;
  if (!spec || !container.value || state.tab !== "3d") return;
  try {
    // three.js is only loaded here, on the layout route.
    const { createLayoutRenderer } = await import("@/lib/layoutThree");
    if (current !== generation || !container.value) return;
    const r = createLayoutRenderer(container.value, spec, {
      theme: theme(),
      onPick: (item) => {
        // A pick in the model leaves the finding it was looking at.
        if (activeFinding.value !== null) activeFinding.value = null;
        state.select = item;
        applyMarks();
      },
      onMeasure: (result) => (measured.value = result),
      onCamera: (pose) => {
        window.clearTimeout(cameraTimer);
        cameraTimer = window.setTimeout(() => {
          state.cam = pose;
        }, 250);
      },
      onNavigation: (mode) => (nav.value = mode),
      onFlySpeed: (speed) => (flySpeed.value = speed),
    });
    renderer.value = r;
    for (const t of TOGGLES) if (!shown.value.has(t)) r.setLayer(t, false);
    r.setColorMode(state.mode);
    r.setXray(state.xray);
    r.setLook(state.realistic ? "realistic" : "normal");
    r.setDetail(state.detail);
    // For the end-to-end tests (frame rate) and the console; cleared with the renderer.
    window.__layoutRenderer = r;
    r.setSection(state.section);
    if (state.cam) r.setCamera(state.cam);
    else if (state.view) r.setView(state.view);
    const key = resolveSelect(state.select, spec);
    if (key) {
      state.select = key;
      r.setSelected(key);
      if (focusPending && !state.cam) r.focus(key);
    } else if (state.select && spec.items.size) state.select = null;
    focusPending = false;
    // Only the user's own camera moves go to the URL, not the initial framing.
    window.clearTimeout(cameraTimer);
    applyMarks();
  } catch (error) {
    renderError.value = `Cannot draw the 3D view: ${error instanceof Error ? error.message : String(error)}`;
  }
}

watch(scene, () => void mount(), { flush: "post" });
watch(
  () => state.tab,
  () => void mount(),
  { flush: "post" },
);
watch(
  () => state.select,
  (item) => {
    renderer.value?.setSelected(item && scene.value?.items.has(item) ? item : null);
    applyMarks();
  },
);
watch(
  () => state.mode,
  (mode) => renderer.value?.setColorMode(mode),
);
watch(
  () => state.xray,
  (on) => renderer.value?.setXray(on),
);
watch(
  () => state.realistic,
  (on) => renderer.value?.setLook(on ? "realistic" : "normal"),
);
watch(
  () => state.detail,
  (detail) => renderer.value?.setDetail(detail),
);
watch(
  () => state.section,
  (box) => renderer.value?.setSection(box ? { min: [...box.min], max: [...box.max] } : null),
  { deep: true },
);

function toggle(t: Toggle): void {
  const on = !shown.value.has(t);
  state.shown = on ? [...state.shown, t] : state.shown.filter((x) => x !== t);
  renderer.value?.setLayer(t, on);
}
function setView(view: ViewName): void {
  state.view = view;
  renderer.value?.setView(view);
  window.clearTimeout(cameraTimer);
  state.cam = null;
}
function setNav(mode: NavMode): void {
  nav.value = mode;
  renderer.value?.setNavigation(mode);
}
function setTool(next: "pick" | "measure"): void {
  tool.value = tool.value === next ? "pick" : next;
  renderer.value?.setTool(tool.value);
}
function focusSelected(): void {
  if (state.select) renderer.value?.focus(state.select);
}
function select(key: string): void {
  const resolved = scene.value ? resolveSelect(key, scene.value) : null;
  if (resolved) state.select = resolved;
}
/**
 * What the model marks: the active finding's objects and box, else the selection's route (a
 * motor's or instrument's cable, a unit's ducts).
 */
function applyMarks(): void {
  const r = renderer.value;
  const spec = scene.value;
  if (!r || !spec) return;
  const f = activeFinding.value !== null ? (findings.value[activeFinding.value] ?? null) : null;
  if (f) {
    const targets = findingTargets(f, spec);
    r.setHighlighted(targets.items, targets.box);
    r.setRoute([]);
    return;
  }
  const route = state.select ? spec.routes.get(state.select) : undefined;
  r.setHighlighted(route?.items ?? [], null);
  r.setRoute(route?.paths ?? []);
}
/** The selection's route, for the side panel. */
const selectedRoute = computed(() => (state.select ? (scene.value?.routes.get(state.select) ?? null) : null));
function selectFinding(f: Finding, index: number): void {
  if (!scene.value) return;
  if (activeFinding.value === index) {
    activeFinding.value = null;
    applyMarks();
    return;
  }
  activeFinding.value = index;
  applyMarks();
  const targets = findingTargets(f, scene.value);
  if (targets.items[0]) {
    state.select = targets.items[0];
    renderer.value?.focus(targets.items[0]);
  }
}
const lineItem = (number: string): string | null => (scene.value ? resolveSelect(number, scene.value) : null);

// Section box: on with the scene bounds, then narrowed with the sliders.
const sectionBounds = computed<Box3 | null>(() => {
  const b = scene.value?.bounds;
  if (!b) return null;
  const pad = (lo: number, hi: number): [number, number] => [Math.floor(lo), Math.ceil(Math.max(hi, lo + 1))];
  const [x0, x1] = pad(b.min[0], b.max[0]);
  const [y0, y1] = pad(b.min[1], b.max[1]);
  const [z0, z1] = pad(Math.min(b.min[2], 0), b.max[2] + 1);
  return { min: [x0, y0, z0], max: [x1, y1, z1] };
});
function toggleSection(): void {
  const b = sectionBounds.value;
  state.section = state.section || !b ? null : { min: [...b.min], max: [...b.max] };
}
const AXES = [
  ["x", 0],
  ["y", 1],
  ["z", 2],
] as const;
function setBound(side: "min" | "max", axis: 0 | 1 | 2, value: number): void {
  if (!state.section || !Number.isFinite(value)) return;
  const box = state.section;
  if (side === "min") box.min[axis] = Math.min(value, box.max[axis]);
  else box.max[axis] = Math.max(value, box.min[axis]);
}
function sectionAroundSelection(): void {
  const box = state.select ? scene.value?.itemBounds.get(state.select) : null;
  if (!box) return;
  const m = 2;
  state.section = { min: [box.min[0] - m, box.min[1] - m, Math.max(box.min[2] - m, sectionBounds.value?.min[2] ?? 0)], max: [box.max[0] + m, box.max[1] + m, box.max[2] + m] };
}

/** Print scales offered for the STL export (1:n; millimetres on the print). */
const STL_SCALES = [100, 200, 500, 1000];
const stlScale = ref(1000);
const stlBase = ref(true);

function exportGlb(): Promise<void> {
  return exportFile((r) => r.exportGlb(), "model/gltf-binary", "glb");
}
function exportStl(): Promise<void> {
  return exportFile((r) => r.exportStl({ scale: stlScale.value, base: stlBase.value }), "model/stl", `1-${stlScale.value}.stl`);
}

async function exportFile(write: (r: LayoutRenderer) => Promise<ArrayBuffer>, type: string, ext: string): Promise<void> {
  if (!renderer.value) return;
  exporting.value = true;
  try {
    const data = await write(renderer.value);
    const url = URL.createObjectURL(new Blob([data], { type }));
    const a = document.createElement("a");
    a.href = url;
    a.download = `layout-${rev.value ? shortRev(rev.value) : "working-tree"}.${ext}`;
    document.body.appendChild(a);
    a.click();
    a.remove();
    setTimeout(() => URL.revokeObjectURL(url), 1000);
  } catch (error) {
    renderError.value = `Cannot export: ${error instanceof Error ? error.message : String(error)}`;
  } finally {
    exporting.value = false;
  }
}

/** Dispose the renderer and drop the test hook to it, so nothing keeps its scene alive. */
function disposeRenderer(): void {
  if (window.__layoutRenderer && window.__layoutRenderer === renderer.value) delete window.__layoutRenderer;
  renderer.value?.dispose();
  renderer.value = null;
}
const dark = typeof window !== "undefined" && window.matchMedia ? window.matchMedia("(prefers-color-scheme: dark)") : null;
const onScheme = () => renderer.value?.setTheme(theme());
onMounted(() => {
  dark?.addEventListener("change", onScheme);
  if (scene.value) void mount();
});
onBeforeUnmount(() => {
  generation++;
  window.clearTimeout(cameraTimer);
  dark?.removeEventListener("change", onScheme);
  disposeRenderer();
});

// ---------------------------------------------------------------------------------------------
// 2D drawings from core: a plan per level or z range, a section at x= or y=.
const view2d = createView();
const drawing = useAsync<SanitizedSvg | null>(
  async (signal) => {
    if (!layout.data.value?.model) return null;
    try {
      const p = state.plan;
      const text =
        p.kind === "section"
          ? await api.layoutSectionSvg({ rev: rev.value, [p.axis]: p.at ?? sectionMiddle(p.axis) }, signal)
          : await api.layoutPlanSvg({ rev: rev.value, level: p.level, z: p.z }, signal);
      return sanitizeSvg(text);
    } catch (error) {
      if (error instanceof ApiError && (error.status === 404 || error.status === 501)) return null;
      throw error;
    }
  },
  [rev, () => layout.data.value?.model, () => ({ ...state.plan })],
);
/**
 * The drawing is still to come: it loads, or the layout it is drawn from does (another revision:
 * the loader has no model yet and answers null at once, which is not "no plans").
 */
const drawingPending = computed(() => drawing.loading.value || layout.loading.value);
/** The 2D tab shows only when the server draws plans (a 404 hides it). */
const has2d = computed(() => Boolean(drawing.data.value) || (state.tab === "2d" && (drawingPending.value || Boolean(drawing.error.value))));
function sectionMiddle(axis: "x" | "y"): number {
  const b = scene.value?.bounds;
  if (!b) return 0;
  const i = axis === "x" ? 0 : 1;
  return Math.round((b.min[i] + b.max[i]) / 2);
}
const levelOptions = computed(() => {
  const out: { id: string; label: string }[] = [];
  for (const b of layout.data.value?.buildings ?? []) for (const l of b.levels ?? []) out.push({ id: l.id, label: `${b.id} ${l.id} @ ${l.elevation} m` });
  for (const s of model.value?.structures ?? []) for (const l of s.levels) out.push({ id: l.id, label: `${s.id} ${l.id} @ ${l.elevation} m` });
  return out;
});
const drawingLayers = computed(() => [{ id: "layout-2d", svg: drawing.data.value ?? null }]);
watch(
  () => [drawingPending.value, drawing.data.value] as const,
  ([pending, data]) => {
    if (!pending && !data && !drawing.error.value && state.tab === "2d") state.tab = "3d";
  },
);
function setTab(tab: "3d" | "2d"): void {
  if (tab === "3d" && nav.value !== "orbit") nav.value = "orbit";
  state.tab = tab;
}
const unrouted = computed(() => model.value?.unrouted ?? []);
const routing = computed(() => model.value?.routing ?? null);
/** Routes by method, most first. */
const byCount = (counts: Record<string, number> | null | undefined) => Object.entries(counts ?? {}).sort((a, b) => b[1] - a[1] || a[0].localeCompare(b[0]));
const routingMethods = computed(() => byCount(routing.value?.methods));
/** Why the router took each route, most first. */
const routingReasons = computed(() => byCount(routing.value?.reasons));
/** Segments ending at a battery limit, by how. */
const batteryLimits = computed(() => byCount(routing.value?.battery_limits));
/** Objects to review: `direct` pipe routes and proposed platforms. */
const toReview = computed(() => {
  const m = model.value;
  return { pipes: (m?.pipes ?? []).filter((p) => p.review_needed).length, platforms: (m?.platforms ?? []).filter((p) => p.review_needed).length };
});
const PROPOSAL_TITLES: Record<string, string> = {
  stair: "Stairs",
  ladder: "Ladders",
  "step-over": "Step-overs",
  platform: "Platforms",
  penetration: "Wall and roof openings",
  "valve platform": "Valve access platforms",
  "support steel": "Support steel",
  "junction box": "Junction boxes",
};
/** Generated proposals to review, by what they are, with the items to pick. */
const proposals = computed(() =>
  [...(scene.value?.proposals ?? new Map<string, string[]>())].map(([what, keys]) => ({
    what,
    title: PROPOSAL_TITLES[what] ?? what,
    items: keys.map((key) => ({ key, label: scene.value?.items.get(key)?.id ?? key })),
  })),
);
const cabling = computed(() => model.value?.cabling ?? null);
const hvac = computed(() => model.value?.hvac ?? null);
const fmt1 = (v: number) => (Math.round(v * 10) / 10).toLocaleString("en");
function unroutedLink(u: { sheet: string; segment: string }) {
  const file = sheetFile(u.sheet, store.repo?.sheets) ?? u.sheet;
  return { name: "pid", params: { path: pathSegments(file) }, query: withRev({ select: u.segment }) };
}
const provenance = computed(() => model.value?.provenance ?? null);

// ---------------------------------------------------------------------------------------------
// Committed studies beside the model. cheme serve has no endpoint for the lifting study or
// the datasheets: the files core writes are read through the tree and file endpoints.
const repoTree = useAsync((signal) => api.tree(rev.value, signal), [rev]);
const treePaths = computed(() => new Set((repoTree.data.value ?? []).map((e) => e.path)));
const datasheets = computed(() => datasheetPaths(repoTree.data.value ?? []));
const lifting = useAsync<LiftingRow[] | null>(
  async (signal) => (treePaths.value.has(LIFTING_STUDY_CSV) ? parseLiftingStudy(await api.file(LIFTING_STUDY_CSV, rev.value, signal)) : null),
  [treePaths],
);
const liftingRows = computed(() => lifting.data.value ?? []);
const liftingReport = computed(() => (treePaths.value.has(LIFTING_STUDY_MD) ? LIFTING_STUDY_MD : null));
/** The lifting findings of the rules on the model, by the item lifted (its first id). */
const liftingFindings = computed(() => {
  const out = new Map<string, number>();
  for (const f of layout.data.value?.model_findings ?? []) if (/layout-(lifting|laydown|lifting-capacity)$/.test(f.rule) && f.ids[0]) out.set(f.ids[0], (out.get(f.ids[0]) ?? 0) + 1);
  return out;
});
const selectedTag = computed(() => (selectedItem.value?.kind === "equipment" ? selectedItem.value.id : null));
const selectedDatasheet = computed(() => (selectedTag.value ? (datasheets.value.get(selectedTag.value) ?? null) : null));
const selectedLift = computed(() => (selectedTag.value ? (liftingRows.value.find((r) => r.tag === selectedTag.value) ?? null) : null));
// The cable schedule (`cheme layout cables --write`), committed beside the model: a row selects
// its cable, whose way the model marks (the trays in order, the junction box, the cable drawn).
const cableSchedule = useAsync<CableRow[] | null>(
  async (signal) => (treePaths.value.has(CABLE_SCHEDULE_CSV) ? parseCableSchedule(await api.file(CABLE_SCHEDULE_CSV, rev.value, signal)) : null),
  [treePaths],
);
const cableRows = computed(() => cableSchedule.data.value ?? []);
const cableReport = computed(() => (treePaths.value.has(CABLE_SCHEDULE_MD) ? CABLE_SCHEDULE_MD : null));
const cableSummary = computed(() => cableTotals(cableRows.value));
const cableQuery = ref("");
const cableSort = ref<{ column: CableColumn; descending: boolean }>({ column: "tag", descending: false });
const shownCables = computed(() => sortCables(cableRows.value.filter((r) => cableMatches(r, cableQuery.value)), cableSort.value.column, cableSort.value.descending));
const CABLE_HEADS: { column: CableColumn; label: string; title: string; num?: boolean }[] = [
  { column: "tag", label: "cable", title: "Cable tag" },
  { column: "kind", label: "kind", title: "motor, feeder, field (instrument to junction box) or multipair (junction box to the control room)" },
  { column: "to", label: "from > to", title: "From its room or junction box to the load or instrument" },
  { column: "power_kw", label: "kW", title: "Load, kW", num: true },
  { column: "length_m", label: "m", title: "Length with terminations and slack, m", num: true },
];
function sortCablesBy(column: CableColumn): void {
  const current = cableSort.value;
  cableSort.value = { column, descending: current.column === column ? !current.descending : column === "power_kw" || column === "length_m" };
}
const cableKey = (tag: string) => (scene.value?.items.has(`cable:${tag}`) ? `cable:${tag}` : tag);
const selectedCable = computed(() => (selectedItem.value?.kind === "cable" ? selectedItem.value.id : null));
const num = (v: number | null, digits = 1) => (v === null ? "–" : v.toLocaleString("en", { maximumFractionDigits: digits }));

const LAYOUT_FILES = ["layout/site-plan.yaml", "layout/building.yaml", "layout/equipment-placement.yaml", "layout/plant-model.yaml (cheme layout build)"];
</script>

<template>
  <div class="layout">
    <div class="bar">
      <h1>
        Layout
        <span v-if="scene?.site?.name" class="muted">{{ scene.site.name }}</span>
        <small>{{ shortRev(rev) }}</small>
      </h1>
      <div v-if="scene" class="tabs" role="tablist" aria-label="Drawing">
        <button type="button" role="tab" class="tab" :class="{ active: state.tab === '3d' }" :aria-selected="state.tab === '3d'" @click="setTab('3d')">3D</button>
        <button v-if="has2d" type="button" role="tab" class="tab" :class="{ active: state.tab === '2d' }" :aria-selected="state.tab === '2d'" @click="setTab('2d')">2D</button>
      </div>
    </div>

    <div v-if="scene && state.tab === '3d'" class="toolbar" role="toolbar" aria-label="3D view">
      <details class="menu">
        <summary class="btn">Layers</summary>
        <div class="menu-body" role="group" aria-label="Layers">
          <label v-for="t in TOGGLES" :key="t" :title="TOGGLE_TITLES[t]" :class="{ empty: layerCount(t) === 0 }">
            <input type="checkbox" :checked="shown.has(t)" :data-layer="t" @change="toggle(t)" />
            {{ TOGGLE_LABELS[t] }}
            <span v-if="layerCount(t)" class="count">{{ layerCount(t) }}</span>
          </label>
        </div>
      </details>
      <label class="field" title="What the colours show">
        Colour by
        <select v-model="state.mode" aria-label="Colour by">
          <option v-for="m in COLOR_MODES" :key="m" :value="m">{{ COLOR_TITLES[m] }}</option>
        </select>
      </label>
      <label class="field" title="Level of detail: near the camera, everywhere, or the envelopes only">
        Detail
        <select v-model="state.detail" aria-label="Detail">
          <option v-for="d in DETAIL_MODES" :key="d" :value="d">{{ DETAIL_TITLES[d] }}</option>
        </select>
      </label>
      <button type="button" class="btn" :class="{ active: state.realistic }" :aria-pressed="state.realistic" title="Materials, shadows and ambient occlusion" @click="state.realistic = !state.realistic">Realistic</button>
      <button type="button" class="btn" :class="{ active: state.xray }" :aria-pressed="state.xray" title="See through solids" @click="state.xray = !state.xray">X-ray</button>
      <button type="button" class="btn" :class="{ active: !!state.section }" :aria-pressed="!!state.section" title="Cut the model with a box" @click="toggleSection">Section box</button>
      <span class="sep" />
      <div class="seg" role="group" aria-label="Navigation">
        <button type="button" class="btn" :class="{ active: nav === 'orbit' }" :aria-pressed="nav === 'orbit'" title="Drag to orbit, scroll to zoom, right-drag to pan" @click="setNav('orbit')">Orbit</button>
        <button type="button" class="btn" :class="{ active: nav === 'walk' }" :aria-pressed="nav === 'walk'" title="Walk at eye height on floors and decks" @click="setNav('walk')">Walk</button>
        <button type="button" class="btn" :class="{ active: nav === 'fly' }" :aria-pressed="nav === 'fly'" title="Fly freely" @click="setNav('fly')">Fly</button>
      </div>
      <div class="seg" role="group" aria-label="View">
        <button v-for="v in VIEWS" :key="v" type="button" class="btn" :title="VIEW_LABELS[v][1]" @click="setView(v)">{{ VIEW_LABELS[v][0] }}</button>
      </div>
      <span class="sep" />
      <button type="button" class="btn" :class="{ active: tool === 'measure' }" :aria-pressed="tool === 'measure'" title="Click two points to measure their distance" @click="setTool('measure')">Measure</button>
      <button type="button" class="btn" :disabled="!state.select" title="Frame the selection" @click="focusSelected">Focus</button>
      <button type="button" class="btn" :disabled="exporting || !renderer" title="Download the visible model as binary glTF (.glb)" @click="exportGlb">Export .glb</button>
      <label class="field" title="Print scale of the STL (millimetres on the print)">
        STL
        <select v-model.number="stlScale" aria-label="STL scale">
          <option v-for="s in STL_SCALES" :key="s" :value="s">1:{{ s }}</option>
        </select>
      </label>
      <label class="field" title="A slab under the model, its top at ground level, so the print is one piece">
        <input v-model="stlBase" type="checkbox" aria-label="STL base" />
        base
      </label>
      <button type="button" class="btn" :disabled="exporting || !renderer" title="Download the visible model as binary STL for 3D printing" @click="exportStl">Export .stl</button>
    </div>

    <div v-if="scene && state.tab === '3d' && state.section && sectionBounds" class="section-bar" aria-label="Section box">
      <div v-for="[name, i] in AXES" :key="name" class="axis">
        <span class="axis-name">{{ name }}</span>
        <input
          type="range"
          :aria-label="`${name} from`"
          :min="sectionBounds.min[i]"
          :max="sectionBounds.max[i]"
          step="0.5"
          :value="state.section.min[i]"
          @input="setBound('min', i, Number(($event.target as HTMLInputElement).value))"
        />
        <input
          type="range"
          :aria-label="`${name} to`"
          :min="sectionBounds.min[i]"
          :max="sectionBounds.max[i]"
          step="0.5"
          :value="state.section.max[i]"
          @input="setBound('max', i, Number(($event.target as HTMLInputElement).value))"
        />
        <input class="num" type="number" step="0.5" :aria-label="`${name} min, m`" :value="state.section.min[i]" @change="setBound('min', i, Number(($event.target as HTMLInputElement).value))" />
        <span class="muted">to</span>
        <input class="num" type="number" step="0.5" :aria-label="`${name} max, m`" :value="state.section.max[i]" @change="setBound('max', i, Number(($event.target as HTMLInputElement).value))" />
        <span class="muted">m</span>
      </div>
      <button type="button" class="btn" :disabled="!state.select" title="A box 2 m around the selection" @click="sectionAroundSelection">Around selection</button>
    </div>

    <div v-if="scene && state.tab === '2d'" class="toolbar" role="toolbar" aria-label="2D drawing">
      <div class="seg" role="group" aria-label="Drawing kind">
        <button type="button" class="btn" :class="{ active: state.plan.kind === 'plan' }" @click="state.plan.kind = 'plan'">Plan</button>
        <button type="button" class="btn" :class="{ active: state.plan.kind === 'section' }" @click="state.plan.kind = 'section'">Section</button>
      </div>
      <template v-if="state.plan.kind === 'plan'">
        <label class="field">
          Level
          <select v-model="state.plan.level" aria-label="Level">
            <option :value="null">plot plan</option>
            <option v-for="l in levelOptions" :key="l.id + l.label" :value="l.id">{{ l.label }}</option>
          </select>
        </label>
        <label v-if="!state.plan.level" class="field" title="Cut range in m, e.g. 0,6">
          z
          <input class="num wide" type="text" placeholder="a,b" :value="state.plan.z ?? ''" aria-label="z range" @change="state.plan.z = ($event.target as HTMLInputElement).value.trim() || null" />
        </label>
      </template>
      <template v-else>
        <label class="field">
          at
          <select v-model="state.plan.axis" aria-label="Section axis">
            <option value="x">x =</option>
            <option value="y">y =</option>
          </select>
          <input
            class="num"
            type="number"
            step="1"
            :value="state.plan.at ?? sectionMiddle(state.plan.axis)"
            aria-label="Section position, m"
            @change="state.plan.at = Number(($event.target as HTMLInputElement).value)"
          />
          m
        </label>
      </template>
    </div>

    <div class="body">
      <LoadState
        class="state"
        :loading="layout.loading.value && !layout.data.value"
        :error="layout.error.value ?? renderError"
        @retry="layout.reload"
      />
      <div v-if="missing" class="notice empty">
        <p><strong>No layout files at {{ shortRev(rev) }}.</strong></p>
        <p class="muted">The layout view reads these files (all optional):</p>
        <ul>
          <li v-for="f in LAYOUT_FILES" :key="f"><code>{{ f }}</code></li>
        </ul>
        <p class="muted">See <code>layout/README.md</code> of a new <code>cheme init</code> repo for their format.</p>
      </div>
      <div v-show="scene && state.tab === '3d'" class="stage-wrap">
        <div ref="container" class="stage" :class="{ measuring: tool === 'measure', moving: nav !== 'orbit' }" aria-label="3D layout. Drag to orbit, scroll to zoom, right-drag to pan." />
        <p v-if="nav !== 'orbit'" class="nav-help">
          <template v-if="nav === 'walk'">Walking at 1.7 m eye height.</template>
          <template v-else>Flying at {{ flySpeed }} m/s (+/- or wheel).</template>
          WASD or arrows move, Shift runs, drag (or double-click for pointer lock) to look,
          <template v-if="nav === 'walk'">PageUp/PageDown or E/Q change level,</template>
          <template v-else>E/Q up and down,</template>
          Esc goes back to orbit.
        </p>
        <p v-if="tool === 'measure'" class="measure-help" aria-live="polite">
          <template v-if="measured">
            <strong>{{ measured.distance.toFixed(2) }} m</strong>
            (dx {{ measured.dx.toFixed(2) }}, dy {{ measured.dy.toFixed(2) }}, dz {{ measured.dz.toFixed(2) }}). Click again to start over.
          </template>
          <template v-else>Click two points on the model.</template>
        </p>
        <div v-if="scene" class="legend" :class="{ open: legendOpen }" role="region" aria-label="Legend">
          <button type="button" class="legend-toggle" :aria-expanded="legendOpen" title="Colour key" @click="legendOpen = !legendOpen">
            <span class="legend-dots" aria-hidden="true">
              <span v-for="e in legendSections.flatMap((s) => s.rows).slice(0, 4)" :key="e.label" :style="{ background: e.color }" />
            </span>
            Legend
          </button>
          <div v-if="legendOpen" class="legend-body">
            <section v-for="sec in legendSections" :key="sec.title" :aria-label="sec.title">
              <h3>{{ sec.title }}</h3>
              <ul>
                <li v-for="e in sec.rows" :key="e.label" :title="e.members ? e.members.join(', ') : undefined">
                  <span class="swatch" :class="{ area: sec.area, pipe: sec.pipe }" :style="{ background: e.color }" />
                  <span class="legend-label">{{ e.label }}</span>
                  <span v-if="e.members && e.members.length > 1" class="legend-count">({{ e.members.length }})</span>
                </li>
              </ul>
            </section>
          </div>
        </div>
      </div>
      <div v-if="scene && state.tab === '2d'" class="stage-wrap drawing">
        <LoadState class="state" :loading="drawing.loading.value && !drawing.data.value" :error="drawing.error.value" @retry="drawing.reload" />
        <SvgPane class="canvas" :layers="drawingLayers" :view="view2d" label="2D layout drawing" :empty-text="drawing.loading.value ? 'Rendering…' : 'Nothing to draw.'" />
      </div>

      <aside v-if="scene" class="side" aria-label="Details">
        <section v-if="selectedItem" class="panel" aria-label="Selection">
          <header>
            <span class="badge info">{{ selectedItem.kind }}</span>
            <strong class="tag">{{ selectedItem.id }}</strong>
            <span v-if="selectedItem.source" class="badge source" :class="selectedItem.source" :title="`This object is ${selectedItem.source}`">{{ selectedItem.source }}</span>
            <span v-if="selectedItem.review" class="badge review" title="A generated proposal or fallback route: review it, then pin or declare it">review needed</span>
            <button class="btn close" type="button" aria-label="Clear selection" @click="state.select = null">&times;</button>
          </header>
          <p v-if="selectedItem.title" class="muted">{{ selectedItem.title }}</p>
          <p v-if="selectedItem.service" class="service">{{ selectedItem.service }}</p>
          <dl>
            <template v-if="selectedItem.type">
              <dt>{{ selectedItem.kind === "equipment" ? "type" : selectedItem.kind === "pipe" ? "service" : "kind" }}</dt>
              <dd>{{ selectedItem.type }}</dd>
            </template>
            <template v-if="selectedItem.kind === 'equipment'">
              <dt>sheet</dt>
              <dd>
                <RouterLink v-if="selectedSheet" :to="{ name: 'pid', params: { path: pathSegments(selectedSheet) }, query: withRev() }">
                  {{ selectedItem.sheet ?? selectedSheet }}
                </RouterLink>
                <span v-else class="muted">{{ selectedItem.sheet ?? "not on a P&ID" }}</span>
              </dd>
              <dt>datasheet</dt>
              <dd data-datasheet>
                <RouterLink v-if="selectedDatasheet && selectedTag" :to="{ name: 'datasheet', params: { tag: selectedTag }, query: withRev() }">{{ selectedDatasheet }}</RouterLink>
                <span v-else class="muted">none in equipment/datasheets/</span>
              </dd>
            </template>
            <template v-if="selectedLift">
              <dt>lift</dt>
              <dd data-lift>
                {{ selectedLift.crane }}<template v-if="selectedLift.pad"> from <button type="button" class="link" @click="select(selectedLift.pad)">{{ selectedLift.pad }}</button></template>,
                <template v-if="selectedLift.radius_m !== null">{{ num(selectedLift.radius_m) }} m radius, {{ num(selectedLift.moment_tm, 0) }} t m, </template>{{ num(selectedLift.required_t) }} t chart capacity needed; lane
                <span class="badge" :class="laneClear(selectedLift) ? 'pass' : 'warning'">{{ selectedLift.lane }}</span>
              </dd>
            </template>
            <template v-if="selectedItem.building">
              <dt>building</dt>
              <dd>{{ selectedItem.building }}<template v-if="selectedItem.level"> / {{ selectedItem.level }}</template></dd>
            </template>
            <template v-for="[k, v] in selectedItem.details" :key="k">
              <dt>{{ k }}</dt>
              <dd>{{ v }}</dd>
            </template>
          </dl>
          <div class="actions">
            <RouterLink v-if="pidLink" class="btn" :to="pidLink" data-action="open-pid">Open in P&amp;ID</RouterLink>
            <button type="button" class="btn" @click="focusSelected">Focus</button>
          </div>
          <div v-if="selectedItem.related?.length" class="related">
            <span class="muted">Related</span>
            <button v-for="r in selectedItem.related" :key="r.key" type="button" class="chip" :disabled="!scene.items.has(r.key)" @click="select(r.key)">{{ r.label }}</button>
          </div>
          <p v-if="selectedRoute && (selectedRoute.items.length || selectedRoute.paths.length)" class="muted route-note" data-route>
            <template v-if="selectedRoute.paths.length">
              Cable route marked: {{ selectedRoute.paths.length }} cable{{ selectedRoute.paths.length === 1 ? "" : "s" }} over {{ selectedRoute.items.filter((k) => k.startsWith("tray:")).length }} trays.
            </template>
            <template v-else>{{ selectedRoute.items.length }} ducts marked.</template>
          </p>
          <p v-if="selectedItem.notes" class="notes">{{ selectedItem.notes }}</p>
          <p v-if="selectedItem.clash" class="clash-note">Clashes with another item (see findings).</p>
        </section>
        <p v-else class="muted hint">Click an item, a tag or a line to see its details.</p>

        <section class="panel">
          <header>
            <strong>Findings</strong>
            <span class="badge error">{{ counts.error }}</span>
            <span class="badge warning">{{ counts.warning }}</span>
            <span class="badge info">{{ counts.info }}</span>
          </header>
          <p v-if="!findings.length" class="muted">The layout validates.</p>
          <div v-else class="finding-groups">
            <details v-for="g in findingGroups" :key="g.rule" class="finding-group" :data-rule="g.rule" :open="openRules.has(g.rule)" @toggle="onGroupToggle(g.rule, $event)">
              <summary>
                <span class="badge" :class="g.level">{{ g.level }}</span>
                <code class="rule">{{ g.rule.replace(/^cheme\./, "") }}</code>
                <span class="group-count">{{ g.count }}</span>
              </summary>
              <ul class="findings">
                <li v-for="{ finding: f, index: i } in g.items" :key="i">
                  <button type="button" class="finding" :class="{ active: activeFinding === i }" :aria-pressed="activeFinding === i" :title="f.hint || f.message" @click="selectFinding(f, i)">
                    <span v-if="f.level !== g.level" class="badge" :class="f.level">{{ f.level }}</span>
                    <span class="msg">{{ f.message }}</span>
                  </button>
                  <RouterLink
                    class="file"
                    :to="{ name: 'file', params: { path: pathSegments(f.file) }, query: withRev(f.line ? { line: String(f.line) } : {}) }"
                  >
                    {{ f.file }}<template v-if="f.line">:{{ f.line }}</template>
                  </RouterLink>
                </li>
              </ul>
            </details>
          </div>
        </section>

        <section v-if="lines.length" class="panel" aria-label="Line routes">
          <header>
            <strong>Lines</strong>
            <span class="muted">{{ lines.length }}</span>
          </header>
          <ul class="lines">
            <li v-for="l in lines" :key="l.number" :data-line="l.number">
              <button v-if="lineItem(l.number)" type="button" class="link tag" @click="select(l.number)">{{ l.number }}</button>
              <code v-else class="tag">{{ l.number }}</code>
              <span class="ends">{{ l.from }} &rarr; {{ l.to }}</span>
              <span class="muted route">{{ lineRouteSummary(l) }}</span>
              <code v-if="l.finding" class="rule">{{ l.finding.replace(/^cheme\./, "") }}</code>
            </li>
          </ul>
        </section>

        <section v-if="unrouted.length" class="panel" aria-label="Unrouted">
          <header>
            <strong>Not routed</strong>
            <span class="muted">{{ unrouted.length }}</span>
          </header>
          <ul class="lines">
            <li v-for="(u, i) in unrouted" :key="i" :data-segment="u.segment">
              <RouterLink class="tag" :to="unroutedLink(u)" :title="`Show ${u.segment} on ${u.sheet}`">{{ u.segment_number ? `${u.line} ${u.segment_number}` : u.line }}</RouterLink>
              <span class="ends">{{ u.sheet }}</span>
              <span class="muted route">{{ u.reason }}</span>
            </li>
          </ul>
        </section>

        <section v-if="routing" class="panel" aria-label="Routing">
          <header>
            <strong>Routing</strong>
            <span class="muted">{{ routing.routed }} of {{ routing.segments }} segments</span>
          </header>
          <dl class="methods">
            <template v-for="[method, n] in routingMethods" :key="method">
              <dt><code>{{ method }}</code></dt>
              <dd>{{ n }}</dd>
            </template>
          </dl>
          <details v-if="routingReasons.length" class="reasons" aria-label="Routing reasons">
            <summary class="muted">Why: {{ routingReasons.length }} reasons</summary>
            <dl class="methods">
              <template v-for="[reason, n] in routingReasons" :key="reason">
                <dt :data-reason="reason">{{ reason }}</dt>
                <dd>{{ n }}</dd>
              </template>
            </dl>
          </details>
          <p v-if="batteryLimits.length" class="muted battery" aria-label="Battery limits">
            Battery limits: <span v-for="([how, n], i) in batteryLimits" :key="how">{{ i ? ", " : "" }}{{ n }} by {{ how }}</span>
          </p>
          <p v-if="toReview.pipes || toReview.platforms" class="muted review-note">
            To review: {{ toReview.pipes }} fallback pipe routes, {{ toReview.platforms }} proposed platforms (colour by provenance).
          </p>
          <table v-if="routing.rack_fill.length" class="fill" aria-label="Rack fill">
            <thead>
              <tr><th>rack</th><th>tier</th><th>used</th><th>fill</th></tr>
            </thead>
            <tbody>
              <tr v-for="r in routing.rack_fill" :key="r.rack + r.tier" :data-rack="r.rack">
                <td><button type="button" class="link" @click="select(r.rack)">{{ r.rack }}</button></td>
                <td>{{ r.tier }} m</td>
                <td>{{ r.used_m.toFixed(2) }} / {{ r.width_m }} m</td>
                <td>
                  <span class="bar-track"><span class="bar-fill" :style="{ width: `${Math.min(r.fill, 1) * 100}%` }" /></span>
                  {{ Math.round(r.fill * 100) }} %
                </td>
              </tr>
            </tbody>
          </table>
        </section>

        <section v-if="proposals.length" class="panel" aria-label="To review">
          <header>
            <strong>Proposals to review</strong>
            <span class="muted">{{ proposals.reduce((n, p) => n + p.items.length, 0) }}</span>
          </header>
          <p class="muted">Generated, not declared: review each, then keep it with <code>cheme layout pin ID</code> or declare your own (a roof penetration cannot be pinned: route its line through a wall).</p>
          <details v-for="p in proposals" :key="p.what" class="proposal-group" :data-proposal="p.what">
            <summary>{{ p.title }} <span class="group-count">{{ p.items.length }}</span></summary>
            <div class="chips">
              <button v-for="i in p.items" :key="i.key" type="button" class="chip" :class="{ active: state.select === i.key }" :data-item="i.key" @click="select(i.key)">{{ i.label }}</button>
            </div>
          </details>
        </section>

        <section v-if="cabling" class="panel" aria-label="Cabling">
          <header>
            <strong>Cabling</strong>
            <span class="muted">{{ cabling.cables }} cables</span>
          </header>
          <dl>
            <dt>power, instrument</dt>
            <dd>{{ cabling.power }}, {{ cabling.instrument }}</dd>
            <dt>motors</dt>
            <dd>{{ cabling.motors }}<template v-if="cabling.motors_skipped"> ({{ cabling.motors_skipped }} skipped)</template></dd>
            <dt>trays</dt>
            <dd>{{ cabling.trays }}, {{ fmt1(cabling.tray_length_m) }} m</dd>
            <dt>cable length</dt>
            <dd>{{ fmt1(cabling.cable_length_m) }} m</dd>
            <dt>junction boxes</dt>
            <dd>{{ cabling.junction_boxes }}</dd>
          </dl>
          <p class="muted">Click a motor's item or an instrument to see its cable's way.</p>
          <ul v-if="cabling.missing.length" class="lines">
            <li v-for="m in cabling.missing" :key="m.tag"><code class="tag">{{ m.tag }}</code> <span class="muted route">{{ m.kind }}: {{ m.reason }}</span></li>
          </ul>
        </section>

        <section v-if="cableRows.length" class="panel" aria-label="Cable schedule">
          <header>
            <strong>Cable schedule</strong>
            <span class="muted">{{ cableSummary.count }} cables, {{ fmt1(cableSummary.length_m) }} m</span>
            <span v-if="cableSummary.review" class="badge review" title="Cables on a fallback route or a proposal: review them">{{ cableSummary.review }} to review</span>
          </header>
          <p class="muted">
            As committed in
            <RouterLink :to="{ name: 'file', params: { path: pathSegments(cableReport ?? CABLE_SCHEDULE_CSV) }, query: withRev() }">{{ cableReport ?? CABLE_SCHEDULE_CSV }}</RouterLink>
            (<code>cheme layout cables --write</code>). Click a cable to mark its way.
          </p>
          <input v-model="cableQuery" class="cable-filter" type="search" placeholder="Filter: power, JB-A1-1, PT-PR1-2, review…" aria-label="Filter the cables" />
          <div class="table-scroll cable-scroll">
            <table class="fill cables" aria-label="Cables">
              <thead>
                <tr>
                  <th v-for="h in CABLE_HEADS" :key="h.column" :class="{ num: h.num }" :aria-sort="cableSort.column === h.column ? (cableSort.descending ? 'descending' : 'ascending') : 'none'">
                    <button type="button" class="sort" :title="h.title" :data-sort="h.column" @click="sortCablesBy(h.column)">
                      {{ h.label }}<span v-if="cableSort.column === h.column" aria-hidden="true">{{ cableSort.descending ? " \u25BE" : " \u25B4" }}</span>
                    </button>
                  </th>
                </tr>
              </thead>
              <tbody>
                <tr
                  v-for="r in shownCables"
                  :key="r.tag"
                  :data-cable="r.tag"
                  :class="{ active: selectedCable === r.tag, review: r.review_needed }"
                  :title="`${r.size}${r.voltage_v !== null ? `, ${r.voltage_v} V` : ''}; ${r.trays.length ? r.trays.join(' > ') : 'no trays (direct to its junction box)'}`"
                  @click="select(cableKey(r.tag))"
                >
                  <td>
                    <button type="button" class="link tag" @click.stop="select(cableKey(r.tag))">{{ r.tag }}</button>
                    <span v-if="r.review_needed" class="badge review" title="Review needed">review</span>
                  </td>
                  <td>{{ r.kind }}</td>
                  <td class="ends">{{ r.from }} &gt; {{ r.to }}</td>
                  <td class="num">{{ num(r.power_kw) }}</td>
                  <td class="num">{{ num(r.length_m, 0) }}</td>
                </tr>
              </tbody>
            </table>
          </div>
          <p v-if="!shownCables.length" class="muted">No cable matches "{{ cableQuery }}".</p>
        </section>
        <p v-else-if="cableSchedule.error.value" class="muted">Cable schedule: {{ cableSchedule.error.value }}</p>

        <section v-if="hvac" class="panel" aria-label="HVAC">
          <header>
            <strong>HVAC</strong>
            <span class="muted">{{ hvac.units }} units, {{ hvac.rooms }} rooms</span>
          </header>
          <dl>
            <dt>supply, extract</dt>
            <dd>{{ fmt1(hvac.supply_m3h) }}, {{ fmt1(hvac.extract_m3h) }} m3/h</dd>
            <dt>ducts</dt>
            <dd>{{ hvac.ducts }}, {{ fmt1(hvac.duct_length_m) }} m, {{ fmt1(hvac.duct_area_m2) }} m2 sheet</dd>
            <dt>terminals</dt>
            <dd>{{ hvac.terminals }}</dd>
            <template v-for="l in hvac.louvres" :key="l.building + l.opening">
              <dt>{{ l.kind }} {{ l.building }}/{{ l.opening }}</dt>
              <dd :class="{ over: l.velocity_m_s > l.velocity_max_m_s }">{{ fmt1(l.flow_m3h) }} m3/h at {{ l.velocity_m_s.toFixed(2) }} m/s (max {{ l.velocity_max_m_s }})</dd>
            </template>
          </dl>
        </section>

        <section v-if="liftingRows.length" class="panel" aria-label="Lifting study">
          <header>
            <strong>Lifting study</strong>
            <span class="muted">{{ liftingRows.length }} lifts, {{ liftingRows.filter((r) => !laneClear(r)).length }} lanes blocked</span>
          </header>
          <p class="muted">
            As committed in
            <RouterLink :to="{ name: 'file', params: { path: pathSegments(liftingReport ?? LIFTING_STUDY_CSV) }, query: withRev() }">{{ liftingReport ?? LIFTING_STUDY_CSV }}</RouterLink>
            (<code>cheme layout lifting --write</code>): radius from the pad's centre, load moment and chart capacity needed with core's ASSUMED factors.
          </p>
          <div class="table-scroll">
            <table class="fill lifting" aria-label="Lifts">
              <thead>
                <tr><th>item</th><th>crane pad</th><th class="num" title="Working radius from the pad's centre, m">R m</th><th class="num" title="Load moment: gross load x radius, t m">t m</th><th class="num" title="Chart capacity needed, t">need t</th><th>lane</th></tr>
              </thead>
              <tbody>
                <tr v-for="r in liftingRows" :key="r.tag" :data-lift="r.tag" :class="{ active: selectedTag === r.tag }" :title="r.status">
                  <td>
                    <button type="button" class="link tag" @click="select(`equipment:${r.tag}`)">{{ r.tag }}</button>
                    <span v-if="liftingFindings.get(r.tag)" class="badge warning" title="Lifting findings on the model">{{ liftingFindings.get(r.tag) }}</span>
                  </td>
                  <td>
                    <button v-if="r.pad" type="button" class="link" @click="select(r.pad)">{{ r.pad }}</button>
                    <span v-else>{{ r.crane }}</span>
                  </td>
                  <td class="num">{{ num(r.radius_m) }}</td>
                  <td class="num">{{ num(r.moment_tm, 0) }}</td>
                  <td class="num">{{ num(r.required_t) }}</td>
                  <td><span class="badge" :class="laneClear(r) ? 'pass' : 'warning'">{{ r.lane }}</span></td>
                </tr>
              </tbody>
            </table>
          </div>
          <p v-if="liftingRows.some((r) => r.chart)" class="muted">Checked against the load charts of <code>layout/crane-chart.yaml</code>.</p>
          <p v-else class="muted">No crane load chart (<code>layout/crane-chart.yaml</code>): the crane is chosen against the capacity needed.</p>
        </section>
        <p v-else-if="lifting.error.value" class="muted">Lifting study: {{ lifting.error.value }}</p>

        <section v-if="scene" class="panel" aria-label="Equipment">
          <header>
            <strong>Equipment</strong>
            <span class="muted">{{ layout.data.value?.equipment.length ?? 0 }}</span>
          </header>
          <div class="chips">
            <button
              v-for="e in layout.data.value?.equipment ?? []"
              :key="e.tag"
              type="button"
              class="chip"
              :class="{ active: state.select === `equipment:${e.tag}` }"
              :data-item="`equipment:${e.tag}`"
              @click="select(`equipment:${e.tag}`)"
            >
              {{ e.tag }}
            </button>
          </div>
        </section>

        <section v-if="provenance" class="panel" aria-label="Model">
          <header><strong>Generated model</strong></header>
          <dl>
            <dt>by</dt>
            <dd>{{ provenance.generator }} v{{ provenance.generator_version }}</dd>
            <dt>inputs</dt>
            <dd>{{ Object.keys(provenance.sources).length }} files</dd>
            <dt>content</dt>
            <dd><code>{{ provenance.output_sha256.slice(0, 12) }}</code></dd>
          </dl>
          <div class="actions">
            <RouterLink class="btn" :to="{ name: 'mto', query: withRev() }" data-action="open-mto">Material take-off</RouterLink>
          </div>
        </section>
      </aside>
    </div>
  </div>
</template>

<style scoped>
.layout {
  display: flex;
  flex-direction: column;
  height: 100%;
}
.bar {
  display: flex;
  flex-wrap: wrap;
  align-items: center;
  gap: var(--space-2) var(--space-4);
  padding: var(--space-2) var(--space-4);
  border-bottom: 1px solid var(--border);
}
h1 {
  font-size: var(--text-lg);
  margin: 0;
  display: flex;
  gap: var(--space-2);
  align-items: baseline;
}
h1 small {
  color: var(--fg-muted);
  font-weight: normal;
  font-size: var(--text-sm);
}
.controls {
  display: flex;
  flex-wrap: wrap;
  gap: var(--space-2) var(--space-3);
  margin-left: auto;
}
.group {
  display: flex;
  flex-wrap: wrap;
  gap: var(--space-1);
}
.body {
  position: relative;
  flex: 1;
  min-height: 0;
  display: flex;
}
.state {
  position: absolute;
  top: 8px;
  left: 8px;
  right: 8px;
  z-index: 4;
}
.empty {
  margin: var(--space-4);
  align-self: flex-start;
}
.empty p {
  margin: 0 0 var(--space-2);
}
.stage-wrap {
  position: relative;
  flex: 1;
  min-width: 0;
  display: flex;
}
.stage {
  position: relative;
  flex: 1;
  min-width: 0;
  overflow: hidden;
  background: var(--bg-soft);
}
.legend {
  position: absolute;
  right: 8px;
  bottom: 8px;
  z-index: 3;
  max-width: min(240px, calc(100% - 16px));
  max-height: min(60%, calc(100% - 16px));
  display: flex;
  flex-direction: column;
  background: var(--surface);
  color: var(--fg);
  border: 1px solid var(--border);
  border-radius: var(--radius);
  font-size: 12px;
  box-shadow: 0 2px 8px rgb(0 0 0 / 0.08);
}
.legend-toggle {
  display: inline-flex;
  align-items: center;
  gap: 6px;
  background: none;
  border: none;
  padding: 4px 8px;
  font: inherit;
  font-weight: 600;
  color: inherit;
  cursor: pointer;
}
.legend-toggle::after {
  content: "\25B4";
  color: var(--fg-muted);
  font-size: 10px;
}
.legend.open .legend-toggle::after {
  content: "\25BE";
}
.legend-dots {
  display: inline-flex;
}
.legend-dots span {
  width: 8px;
  height: 8px;
  border-radius: 50%;
  margin-left: -2px;
  border: 1px solid var(--surface);
}
.legend-body {
  overflow: auto;
  padding: 0 var(--space-2) var(--space-2);
  border-top: 1px solid var(--border);
}
.legend h3 {
  margin: 6px 0 2px;
  font-size: 10.5px;
  font-weight: 600;
  text-transform: uppercase;
  letter-spacing: 0.04em;
  color: var(--fg-muted);
}
.legend ul {
  list-style: none;
  margin: 0;
  padding: 0;
  display: grid;
  gap: 2px;
}
.legend li {
  display: flex;
  align-items: center;
  gap: 6px;
  min-width: 0;
}
.legend-label {
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}
.legend-count {
  flex: none;
  color: var(--fg-muted);
  font-size: 10.5px;
  font-variant-numeric: tabular-nums;
}
.swatch {
  width: 12px;
  height: 12px;
  border-radius: 3px;
  flex: none;
  border: 1px solid var(--border);
}
.swatch.area {
  opacity: 0.75;
}
.service {
  font-size: var(--text-sm);
}
.notes {
  font-size: var(--text-sm);
  color: var(--fg-muted);
  border-left: 3px solid var(--border);
  padding-left: var(--space-2);
  margin-top: var(--space-2) !important;
  white-space: pre-wrap;
}
.stage :deep(.layout-canvas),
.stage :deep(.layout-labels) {
  position: absolute;
  inset: 0;
}
.stage :deep(.layout-labels) {
  touch-action: none;
}
.stage :deep(.layout-label) {
  font: 600 11px/1.2 var(--mono);
  padding: 1px 5px;
  border-radius: 4px;
  background: var(--surface);
  color: var(--fg);
  border: 1px solid var(--border);
  white-space: nowrap;
  cursor: pointer;
  user-select: none;
}
.stage :deep(.layout-label.name) {
  font: 600 11px/1.2 var(--font);
  background: none;
  border-color: transparent;
  color: var(--fg-muted);
  text-shadow: 0 0 3px var(--bg-soft), 0 0 3px var(--bg-soft);
}
.stage :deep(.layout-label.marker) {
  font: 700 12px/1.2 var(--font);
  background: none;
  border: none;
  color: var(--fg-muted);
  cursor: default;
}
.stage :deep(.layout-label.clash) {
  background: var(--bad-soft);
  color: var(--bad);
  border-color: var(--bad);
}
.stage :deep(.layout-label.selected) {
  border-color: var(--accent);
  box-shadow: 0 0 0 2px var(--accent);
}
.side {
  width: 320px;
  flex: none;
  overflow: auto;
  border-left: 1px solid var(--border);
  background: var(--surface);
  padding: var(--space-3);
  display: flex;
  flex-direction: column;
  gap: var(--space-3);
}
.panel header {
  display: flex;
  flex-wrap: wrap;
  align-items: center;
  gap: var(--space-1) var(--space-2);
  margin-bottom: var(--space-2);
}
.panel p {
  margin: 0 0 var(--space-2);
}
.tag {
  font-family: var(--mono);
  word-break: break-all;
}
/* A long id (a pipe's sheet/segment) takes its own line above the badges rather than a sliver. */
header .tag {
  flex: 1 1 12ch;
  min-width: 12ch;
}
.close {
  margin-left: auto;
  min-height: 24px;
  padding: 0 8px;
}
.hint {
  margin: 0;
}
dl {
  display: grid;
  grid-template-columns: max-content minmax(0, 1fr);
  gap: 2px var(--space-3);
  margin: 0;
  font-size: var(--text-sm);
}
dt {
  color: var(--fg-muted);
}
dd {
  margin: 0;
  word-break: break-word;
}
.clash-note {
  color: var(--bad);
  font-size: var(--text-sm);
  margin-top: var(--space-2) !important;
}
.findings {
  list-style: none;
  margin: 0;
  padding: 0;
  display: flex;
  flex-direction: column;
  gap: var(--space-2);
}
.finding-groups {
  display: flex;
  flex-direction: column;
  gap: var(--space-1);
}
.finding-group > summary {
  display: flex;
  align-items: center;
  gap: var(--space-1);
  cursor: pointer;
  list-style: none;
  padding: 2px 0;
  font-size: var(--text-sm);
}
.finding-group > summary::-webkit-details-marker {
  display: none;
}
.finding-group > summary::before {
  content: "\25B8";
  color: var(--fg-muted);
  width: 10px;
}
.finding-group[open] > summary::before {
  content: "\25BE";
}
.finding-group > summary .rule {
  flex: 1;
  min-width: 0;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}
.proposal-group > summary {
  cursor: pointer;
  font-size: var(--text-sm);
  padding: 2px 0;
}
.proposal-group .chips {
  margin: var(--space-1) 0 var(--space-2) 14px;
}
.route-note {
  margin: var(--space-2) 0 0;
  font-size: var(--text-sm);
}
dd.over {
  color: var(--bad);
}
.group-count {
  color: var(--fg-muted);
  font-variant-numeric: tabular-nums;
}
.finding-group .findings {
  margin: var(--space-1) 0 var(--space-2) 14px;
}
.finding {
  display: block;
  width: 100%;
  text-align: left;
  background: none;
  border: 1px solid var(--border);
  border-radius: var(--radius);
  padding: var(--space-1) var(--space-2);
  cursor: pointer;
  font-size: var(--text-sm);
}
.finding:hover {
  border-color: var(--accent);
}
.lines {
  list-style: none;
  margin: 0;
  padding: 0;
  display: flex;
  flex-direction: column;
  gap: var(--space-1);
  font-size: var(--text-sm);
}
.lines li {
  display: flex;
  flex-wrap: wrap;
  gap: 2px var(--space-2);
  align-items: baseline;
}
.lines .route {
  flex-basis: 100%;
}
.rule {
  margin: 0 var(--space-1);
}
.msg {
  display: block;
  margin-top: 2px;
}
.file {
  display: inline-block;
  font-family: var(--mono);
  font-size: 11.5px;
  margin: 2px 0 0 var(--space-2);
  word-break: break-all;
}

.tabs {
  display: flex;
  gap: 2px;
  margin-left: auto;
  border: 1px solid var(--border);
  border-radius: var(--radius);
  padding: 2px;
}
.tab {
  background: none;
  border: none;
  border-radius: calc(var(--radius) - 2px);
  padding: 2px 14px;
  font: inherit;
  font-weight: 600;
  color: var(--fg-muted);
  cursor: pointer;
}
.tab.active {
  background: var(--accent-soft);
  color: var(--accent);
}
.toolbar,
.section-bar {
  display: flex;
  flex-wrap: wrap;
  align-items: center;
  gap: var(--space-1) var(--space-2);
  padding: var(--space-1) var(--space-4);
  border-bottom: 1px solid var(--border);
  font-size: var(--text-sm);
}
.sep {
  width: 1px;
  align-self: stretch;
  background: var(--border);
}
.seg {
  display: flex;
  gap: 2px;
}
.field {
  display: inline-flex;
  align-items: center;
  gap: var(--space-1);
  color: var(--fg-muted);
}
.field select,
.num {
  font: inherit;
  color: var(--fg);
  background: var(--surface);
  border: 1px solid var(--border);
  border-radius: var(--radius);
  padding: 2px 4px;
}
.num {
  width: 5.5em;
}
.num.wide {
  width: 7em;
}
.menu {
  position: relative;
}
.menu summary {
  list-style: none;
  cursor: pointer;
}
.menu summary::-webkit-details-marker {
  display: none;
}
.menu summary::after {
  content: " \25BE";
}
.menu-body {
  position: absolute;
  z-index: 10;
  top: calc(100% + 4px);
  left: 0;
  min-width: 220px;
  background: var(--surface);
  border: 1px solid var(--border);
  border-radius: var(--radius);
  padding: var(--space-2);
  display: grid;
  gap: 2px;
  box-shadow: 0 6px 20px rgb(0 0 0 / 0.15);
}
.menu-body label {
  display: flex;
  align-items: center;
  gap: 6px;
  white-space: nowrap;
  cursor: pointer;
}
.menu-body label.empty {
  color: var(--fg-muted);
}
.menu-body .count {
  margin-left: auto;
  color: var(--fg-muted);
  font-size: 11px;
}
.section-bar .axis {
  display: inline-flex;
  align-items: center;
  gap: 4px;
}
.axis-name {
  font-weight: 700;
  font-family: var(--mono);
}
.section-bar input[type="range"] {
  width: 90px;
}
.stage.measuring :deep(.layout-labels) {
  cursor: crosshair;
}
.stage.moving :deep(.layout-labels) {
  cursor: move;
}
.nav-help,
.measure-help {
  position: absolute;
  left: 8px;
  top: 8px;
  z-index: 3;
  margin: 0;
  max-width: min(520px, calc(100% - 16px));
  background: var(--surface);
  color: var(--fg);
  border: 1px solid var(--border);
  border-radius: var(--radius);
  padding: var(--space-1) var(--space-2);
  font-size: 12px;
}
.measure-help {
  top: auto;
  bottom: 8px;
}
.stage :deep(.layout-label.measure) {
  background: #ff8a00;
  color: #111;
  border-color: #ff8a00;
}
.drawing {
  flex-direction: column;
}
.drawing .canvas {
  flex: 1;
  min-height: 0;
}
.swatch.pipe {
  height: 5px;
  border-radius: 2px;
}
.badge.source {
  text-transform: none;
}
.badge.source.generated {
  background: #d7f1f4;
  color: #116470;
}
.badge.source.pinned {
  background: #ece4fe;
  color: #5b30b8;
}
.badge.source.declared {
  background: var(--bg-sunk);
  color: var(--fg-muted);
}
.badge.review {
  background: var(--bad-soft);
  color: var(--bad);
}
.review-note {
  font-size: var(--text-sm);
  margin: var(--space-2) 0 !important;
}
.methods {
  grid-template-columns: max-content max-content;
}
.reasons {
  font-size: var(--text-sm);
  margin: var(--space-2) 0;
}
.reasons summary {
  cursor: pointer;
}
.reasons .methods {
  grid-template-columns: minmax(0, 1fr) max-content;
}
.reasons dt {
  overflow-wrap: anywhere;
}
.battery {
  font-size: var(--text-sm);
  margin: var(--space-2) 0 !important;
}
.fill {
  width: 100%;
  border-collapse: collapse;
  font-size: var(--text-sm);
  font-variant-numeric: tabular-nums;
}
.fill th {
  text-align: left;
  font-weight: 500;
  color: var(--fg-muted);
}
.fill td,
.fill th {
  padding: 1px var(--space-1) 1px 0;
}
.table-scroll {
  overflow-x: auto;
}
.cable-filter {
  width: 100%;
  margin: 0 0 var(--space-1);
  padding: 3px 6px;
  border: 1px solid var(--border);
  border-radius: var(--radius);
  background: var(--surface);
  color: var(--fg);
  font: inherit;
  font-size: var(--text-sm);
}
.cable-scroll {
  max-height: 320px;
  overflow-y: auto;
}
.cables th {
  position: sticky;
  top: 0;
  background: var(--surface);
}
.cables .sort {
  background: none;
  border: none;
  padding: 0;
  font: inherit;
  color: inherit;
  cursor: pointer;
  white-space: nowrap;
}
.cables td {
  white-space: nowrap;
  vertical-align: baseline;
  cursor: pointer;
}
.cables .num {
  text-align: right;
  padding-right: var(--space-2);
}
.cables .ends {
  max-width: 170px;
  overflow: hidden;
  text-overflow: ellipsis;
}
.cables tr.review td {
  background: var(--warn-soft);
}
.cables tr.active td {
  background: var(--accent-soft);
}
.cables .badge {
  margin-left: 2px;
}
.lifting td {
  white-space: nowrap;
  vertical-align: baseline;
}
.lifting .num {
  text-align: right;
  padding-right: var(--space-2);
}
.lifting tr.active td {
  background: var(--bg-soft);
}
.lifting .badge {
  margin-left: 2px;
}
.bar-track {
  display: inline-block;
  width: 40px;
  height: 6px;
  border-radius: 3px;
  background: var(--bg-sunk);
  vertical-align: middle;
  overflow: hidden;
}
.bar-fill {
  display: block;
  height: 100%;
  background: var(--accent);
}
.actions {
  display: flex;
  flex-wrap: wrap;
  gap: var(--space-1);
  margin-top: var(--space-2);
}
.actions .btn:hover {
  text-decoration: none;
}
.related,
.chips {
  display: flex;
  flex-wrap: wrap;
  gap: 4px;
  align-items: center;
  margin-top: var(--space-2);
  font-size: var(--text-sm);
}
.chips {
  margin-top: 0;
}
.chip {
  font: 11.5px/1.4 var(--mono);
  background: var(--bg-soft);
  border: 1px solid var(--border);
  border-radius: 999px;
  padding: 0 8px;
  color: var(--fg);
  cursor: pointer;
}
.chip:hover:not(:disabled),
.chip.active {
  border-color: var(--accent);
  color: var(--accent);
}
.chip:disabled {
  cursor: default;
  opacity: 0.6;
}
.link {
  background: none;
  border: none;
  padding: 0;
  color: var(--accent);
  cursor: pointer;
  font: inherit;
}
.finding.active {
  border-color: #ff8a00;
  box-shadow: 0 0 0 1px #ff8a00;
}

@media (max-width: 860px) {
  .body {
    flex-direction: column;
  }
  .stage-wrap {
    flex: none;
    height: 60vh;
  }
  /* The open legend goes below the scene instead of over it. */
  .stage-wrap:has(.legend.open) {
    flex-direction: column;
    height: auto;
  }
  .stage-wrap:has(.legend.open) .stage {
    flex: none;
    height: 60vh;
  }
  .legend.open {
    position: static;
    max-width: none;
    max-height: none;
    margin: var(--space-2);
    box-shadow: none;
  }
  .legend.open ul {
    grid-template-columns: repeat(auto-fill, minmax(150px, 1fr));
  }
  .side {
    width: auto;
    border-left: none;
    border-top: 1px solid var(--border);
    overflow: visible;
  }
  .layout {
    height: auto;
    min-height: 100%;
  }
}
</style>
