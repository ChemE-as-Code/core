/**
 * The viewer's navigation: the plant's pages and documents in engineering groups (process,
 * P&IDs, equipment, control and safety, layout, cost and impact, quality, project), shared by the
 * sidebar and the overview. Pure: the flags come from `/api/repo`, the paths from `/api/tree`.
 *
 * A page is listed when the plant has something for it to show; a document (a committed file
 * the viewer renders as a table or as text) when the file is in the tree. Everything else stays
 * under "Files", the raw repository tree, which the sidebar folds away by default.
 */
import type { RepoInfo, Sheet } from "@/api";
import { kindFromPath, pathSegments, viewFor } from "@/lib/format";
import { KIND_BADGE, groupSheets } from "@/lib/process";

export interface NavItem {
  /** Unique within the navigation (the route name, or the file path of a document or sheet). */
  key: string;
  label: string;
  /** Shown after the label, muted (a sheet's title). */
  detail?: string;
  /** Tooltip: what the page shows or which file it is. */
  title?: string | undefined;
  /** Route name, path param (repo files) and extra query (e.g. `tab`); the rev is added by the caller. */
  to: { name: string; params?: { path: string[] }; query?: Record<string, string> };
  /** A short badge after the label (the sheet kind). */
  badge?: string | undefined;
  /** The repo file the item shows, if it is one (a sheet or a document). */
  file?: string;
}

export interface NavGroup {
  id: string;
  title: string;
  items: NavItem[];
}

/** What the navigation needs to know about the plant. */
export interface NavInput {
  repo: Pick<
    RepoInfo,
    | "has_simulation"
    | "has_reactions"
    | "has_layout"
    | "has_equipment_estimate"
    | "has_lca"
    | "has_control"
    | "has_issues"
  > | null;
  /** The drawn sheets (not the planned ones), in plant.yaml order. */
  sheets: readonly Sheet[];
  /** File paths of the tree (null until loaded: no documents yet). */
  paths: ReadonlySet<string> | null;
  hasDatasheets: boolean;
  hasInterlocks: boolean;
  hasReviews: boolean;
  /** A static snapshot: no git history to browse. */
  snapshot: boolean;
}

/** A committed document by its conventional path (the plant template's), with its title. */
const DOCUMENTS: Record<string, { label: string; path: string }[]> = {
  process: [
    { label: "Design basis", path: "process/design-basis.yaml" },
    { label: "Process narrative", path: "process/narrative.md" },
    { label: "Materials", path: "process/materials.yaml" },
  ],
  equipment: [
    { label: "Equipment list", path: "equipment/equipment-list.yaml" },
    { label: "Line list", path: "piping/line-list.yaml" },
    { label: "Instrument list", path: "control/instrument-list.yaml" },
    { label: "Electrical list", path: "electrical/electrical-list.yaml" },
    { label: "Cable schedule", path: "electrical/cable-schedule.md" },
  ],
  safety: [
    { label: "Risk matrix", path: "safety/risk-matrix.yaml" },
    { label: "HAZOP session", path: "safety/hazop/SESSION.md" },
    { label: "Relief study", path: "safety/relief/relief-study.md" },
  ],
  layout: [{ label: "Lifting study", path: "layout/lifting-study.md" }],
  cost: [
    { label: "Cost estimate", path: "estimate/estimate.md" },
    { label: "Equipment cost", path: "estimate/equipment-cost.md" },
    { label: "Techno-economics (TEA)", path: "estimate/tea.md" },
  ],
  project: [
    { label: "README", path: "README.md" },
    { label: "Design notes", path: "DESIGN.md" },
    { label: "Stages", path: "STAGES.md" },
    { label: "Progress", path: "PROGRESS.md" },
  ],
};

/** The HAZOP studies (`safety/hazop/<node>/study.yaml`), by node. */
const HAZOP_STUDY = /^safety\/hazop\/([^/]+)\/study\.ya?ml$/;

function document(path: string, label: string): NavItem {
  return { key: path, label, title: path, file: path, to: { name: viewFor(kindFromPath(path)), params: { path: pathSegments(path) } } };
}

function documents(group: string, paths: ReadonlySet<string> | null): NavItem[] {
  if (!paths) return [];
  const items = (DOCUMENTS[group] ?? []).filter((d) => paths.has(d.path)).map((d) => document(d.path, d.label));
  if (group === "safety") {
    const studies = [...paths]
      .map((path) => ({ path, node: HAZOP_STUDY.exec(path)?.[1] }))
      .filter((s): s is { path: string; node: string } => Boolean(s.node))
      .sort((a, b) => a.node.localeCompare(b.node, undefined, { numeric: true }));
    items.splice(1, 0, ...studies.map((s) => document(s.path, `HAZOP ${s.node}`)));
  }
  return items;
}

function sheetItem(sheet: Sheet): NavItem {
  return {
    key: sheet.file,
    label: sheet.id,
    detail: sheet.title,
    title: `${sheet.title} (${sheet.file})`,
    badge: KIND_BADGE[sheet.kind ?? "pid"],
    file: sheet.file,
    to: { name: "pid", params: { path: pathSegments(sheet.file) } },
  };
}

const page = (name: string, label: string, title?: string, query?: Record<string, string>): NavItem => ({
  key: query ? `${name}?${new URLSearchParams(query)}` : name,
  label,
  title,
  to: query ? { name, query } : { name },
});

/** The navigation groups; empty groups are left out. */
export function navGroups(input: NavInput): NavGroup[] {
  const { repo, paths } = input;
  const sheets = groupSheets([...input.sheets]);
  const process = sheets.find((g) => g.id === "process")?.sheets ?? [];
  const pids = sheets.find((g) => g.id === "pid")?.sheets ?? [];
  const groups: NavGroup[] = [
    {
      id: "process",
      title: "Process",
      items: [
        ...process.map(sheetItem),
        page("streams", "Stream table", "Stream values, provenance and balances (process/flowsheet.yaml)"),
        ...(repo?.has_simulation ? [page("streams", "Simulation", "The recorded simulation run (process/simulation.yaml)", { tab: "simulation" })] : []),
        ...(repo?.has_reactions ? [page("reactions", "Reactions", "Reactions and reactors (process/reactions.yaml)")] : []),
        ...documents("process", paths),
      ],
    },
    { id: "pid", title: "P&IDs", items: pids.map(sheetItem) },
    {
      id: "equipment",
      title: "Equipment and lists",
      items: [
        ...(input.hasDatasheets ? [page("datasheets", "Datasheets", "Equipment datasheets (equipment/datasheets/)")] : []),
        ...documents("equipment", paths),
      ],
    },
    {
      id: "safety",
      title: "Control and safety",
      items: [
        ...(repo?.has_control ? [page("control", "Control", "Control loops, sequences, narrative and control philosophy (cheme control report)")] : []),
        ...(input.hasInterlocks ? [page("cause-effect", "Cause & effect", "Cause and effect matrix of the interlocks (control/cause-effect.yaml)")] : []),
        ...documents("safety", paths),
      ],
    },
    {
      id: "layout",
      title: "Layout",
      items: [...(repo?.has_layout ? [page("layout", "Layout 3D", "The 3D plant model (layout/)")] : []), ...documents("layout", paths)],
    },
    {
      id: "cost",
      title: "Cost and impact",
      items: [
        ...(repo?.has_layout || repo?.has_equipment_estimate
          ? [page("mto", "MTO and estimate", repo?.has_layout ? "Material take-off and estimate of the 3D model, equipment estimate" : "Equipment estimate (cheme assess equipment)")]
          : []),
        ...documents("cost", paths),
        ...(repo?.has_lca ? [page("lca", "Life cycle assessment", "Life cycle assessment (cheme assess lca)")] : []),
      ],
    },
    {
      id: "quality",
      title: "Quality",
      items: [
        page("checks", "Checks", "Engineering-step checks of the current stage (checks/checks.yaml)"),
        page("validate", "Validation", "Schema and consistency findings of the working tree (cheme validate)"),
        page("maturity", "Maturity", "Evidence-based calculation maturity (cheme maturity): the four levels and their requirements"),
        ...(input.hasReviews ? [page("reviews", "Reviews", "Open review findings and stage sign-offs")] : []),
        ...(repo?.has_issues ? [page("issues", "Issues", "Action items, engineering holds, technical queries and design changes (GitHub issues, cheme issues)")] : []),
      ],
    },
    {
      id: "project",
      title: "Project",
      items: [
        ...documents("project", paths),
        ...(input.snapshot ? [] : [page("history", "History", "Commits of the plant")]),
        page("library", "Reaction library", "Industrial processes to start from"),
      ],
    },
  ];
  return groups.filter((g) => g.items.length);
}

/** The files the navigation shows (sheets and documents): the sidebar keeps "Files" folded for them. */
export function navFiles(groups: readonly NavGroup[]): Set<string> {
  return new Set(groups.flatMap((g) => g.items.flatMap((i) => (i.file ? [i.file] : []))));
}

/** Whether `item` is the page shown: same route, same file, same tab. */
export function isCurrent(item: NavItem, route: { name: string; path: string; tab: string | null }): boolean {
  if (item.to.name !== route.name) return false;
  if (item.file !== undefined) return item.file === route.path;
  return (item.to.query?.tab ?? null) === route.tab;
}
