import {
  createRouter,
  createWebHashHistory,
  createWebHistory,
  type LocationQuery,
  type RouteLocationNormalizedLoaded,
  type RouteRecordRaw,
} from "vue-router";
import { paramPath } from "./lib/format";

// Page options (`src/lib/viewerOptions.ts`) that in-app links must not drop in web history mode,
// where they are part of the route query rather than sitting before the hash.
const STICKY_QUERY = ["embed", "theme"] as const;

/** `to` with the sticky page options of `from` added where `to` lacks them; null if none missing. */
export function keepStickyQuery(to: LocationQuery, from: LocationQuery): LocationQuery | null {
  const missing = STICKY_QUERY.filter((key) => from[key] != null && to[key] == null);
  if (!missing.length) return null;
  const query = { ...to };
  for (const key of missing) query[key] = from[key] ?? null;
  return query;
}

// Repo paths use repeatable params (`:path(.*)*`) so their slashes stay readable in the URL.
const routes: RouteRecordRaw[] = [
  { path: "/", name: "home", component: () => import("./views/HomeView.vue") },
  { path: "/pid/:path(.*)*", name: "pid", component: () => import("./views/PidView.vue") },
  { path: "/diff/:path(.*)*", name: "diff", component: () => import("./views/DiffView.vue") },
  { path: "/yaml/:path(.*)*", name: "yaml", component: () => import("./views/YamlView.vue") },
  { path: "/file/:path(.*)*", name: "file", component: () => import("./views/FileView.vue") },
  { path: "/streams", name: "streams", component: () => import("./views/StreamsView.vue") },
  { path: "/reactions", name: "reactions", component: () => import("./views/ReactionsView.vue") },
  { path: "/library", name: "library", component: () => import("./views/LibraryView.vue") },
  { path: "/checks", name: "checks", component: () => import("./views/ChecksView.vue") },
  { path: "/reviews", name: "reviews", component: () => import("./views/ReviewsView.vue") },
  { path: "/validate", name: "validate", component: () => import("./views/ValidateView.vue") },
  { path: "/maturity", name: "maturity", component: () => import("./views/MaturityView.vue") },
  { path: "/layout", name: "layout", component: () => import("./views/LayoutView.vue") },
  { path: "/mto", name: "mto", component: () => import("./views/MtoView.vue") },
  { path: "/datasheets", name: "datasheets", component: () => import("./views/DatasheetsView.vue") },
  { path: "/datasheets/:tag", name: "datasheet", component: () => import("./views/DatasheetView.vue") },
  { path: "/lca", name: "lca", component: () => import("./views/LcaView.vue") },
  { path: "/tea", name: "tea", component: () => import("./views/TeaView.vue") },
  { path: "/cause-effect", name: "cause-effect", component: () => import("./views/CauseEffectView.vue") },
  { path: "/control", name: "control", component: () => import("./views/ControlView.vue") },
  { path: "/issues", name: "issues", component: () => import("./views/IssuesView.vue") },
  { path: "/history", name: "history", component: () => import("./views/HistoryView.vue") },
  { path: "/about", name: "about", component: () => import("./views/AboutView.vue") },
  { path: "/:rest(.*)*", name: "not-found", component: () => import("./views/NotFoundView.vue") },
];

const PAGE_TITLES: Record<string, string> = {
  home: "Overview",
  streams: "Stream table",
  reactions: "Reactions",
  library: "Reaction library",
  checks: "Checks",
  reviews: "Reviews",
  validate: "Validation",
  maturity: "Maturity",
  layout: "Layout",
  mto: "Material take-off",
  datasheets: "Datasheets",
  lca: "Life cycle assessment",
  tea: "Techno-economics",
  "cause-effect": "Cause and effect",
  control: "Control",
  history: "History",
  about: "About",
  "not-found": "Not found",
};

/** The page's name in the document title: the static title, or the file, sheet or tag shown. */
function pageName(route: Pick<RouteLocationNormalizedLoaded, "name" | "params">): string {
  const name = String(route.name ?? "");
  const path = paramPath(route.params.path);
  switch (name) {
    case "pid":
      return `P&ID ${path}`;
    case "diff":
      return `Diff ${path}`;
    case "yaml":
    case "file":
      return path;
    case "datasheet":
      return `Datasheet ${String(route.params.tag ?? "")}`;
    default:
      return PAGE_TITLES[name] ?? "";
  }
}

/** The document title of a page: `<page> – <plant> – cheme-as-code viewer`. */
export function pageTitle(route: Pick<RouteLocationNormalizedLoaded, "name" | "params">, plant?: string | null): string {
  return [pageName(route), plant, "cheme-as-code viewer"].filter(Boolean).join(" – ");
}

/** Web history against a server; hash history for a static snapshot (any static host, no rewrites). */
export function createAppRouter(mode: "web" | "hash" = "web") {
  const history = mode === "hash" ? createWebHashHistory() : createWebHistory(import.meta.env.BASE_URL);
  const router = createRouter({ history, routes });
  if (mode === "web") {
    router.beforeEach((to, from) => {
      const query = keepStickyQuery(to.query, from.query);
      return query ? { ...to, query } : true;
    });
  }
  return router;
}
