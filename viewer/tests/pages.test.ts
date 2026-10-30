import { describe, expect, it } from "vitest";
import type { Sheet } from "@/api";
import { isCurrent, navFiles, navGroups, type NavInput } from "@/lib/pages";

const sheets: Sheet[] = [
  { id: "P-01", file: "pid/P-01.xml", title: "Feed", kind: "pid" },
  { id: "PFD", file: "process/PFD.xml", title: "Process flow diagram", kind: "pfd" },
  { id: "BFD", file: "process/BFD.xml", title: "Block flow diagram", kind: "bfd" },
];

const bare: NavInput = {
  repo: {
    has_simulation: false,
    has_reactions: false,
    has_layout: false,
    has_equipment_estimate: false,
    has_lca: false,
    has_tea: false,
    has_control: false,
    has_issues: false,
  },
  sheets: [],
  paths: new Set(),
  hasDatasheets: false,
  hasInterlocks: false,
  hasReviews: false,
  snapshot: false,
};

const labels = (input: NavInput) => Object.fromEntries(navGroups(input).map((g) => [g.id, g.items.map((i) => i.label)]));

describe("navGroups", () => {
  it("always has the stream table, the quality pages and the project pages", () => {
    expect(labels(bare)).toEqual({
      process: ["Stream table"],
      quality: ["Checks", "Validation", "Maturity"],
      project: ["History", "Reaction library"],
    });
  });

  it("puts BFD before PFD in Process and the P&IDs in their own group", () => {
    const groups = navGroups({ ...bare, sheets });
    expect(groups.find((g) => g.id === "process")?.items.map((i) => [i.label, i.badge])).toEqual([
      ["BFD", "BFD"],
      ["PFD", "PFD"],
      ["Stream table", undefined],
    ]);
    expect(groups.find((g) => g.id === "pid")?.items.map((i) => i.file)).toEqual(["pid/P-01.xml"]);
  });

  it("lists a page only when the plant has something for it", () => {
    const all = labels({
      ...bare,
      repo: { has_simulation: true, has_reactions: true, has_layout: true, has_equipment_estimate: true, has_lca: true, has_tea: true, has_control: true, has_issues: true },
      hasDatasheets: true,
      hasInterlocks: true,
      hasReviews: true,
    });
    expect(all.process).toEqual(["Stream table", "Simulation", "Reactions"]);
    expect(all.equipment).toEqual(["Datasheets"]);
    expect(all.safety).toEqual(["Control", "Cause & effect"]);
    expect(all.layout).toEqual(["Layout 3D"]);
    expect(all.cost).toEqual(["MTO and estimate", "Techno-economics (TEA)", "Life cycle assessment"]);
    expect(all.quality).toEqual(["Checks", "Validation", "Maturity", "Reviews", "Issues"]);
  });

  it("lists the documents in the tree, the HAZOP studies by node", () => {
    const paths = new Set([
      "process/design-basis.yaml",
      "piping/line-list.yaml",
      "safety/risk-matrix.yaml",
      "safety/hazop/H-10/study.yaml",
      "safety/hazop/H-02/study.yaml",
      "safety/hazop/SESSION.md",
      "estimate/tea.md",
      "README.md",
      "process/flowsheet.yaml",
    ]);
    const groups = navGroups({ ...bare, paths });
    const byId = Object.fromEntries(groups.map((g) => [g.id, g.items]));
    expect(byId.process?.map((i) => i.label)).toEqual(["Stream table", "Design basis"]);
    expect(byId.equipment?.map((i) => i.label)).toEqual(["Line list"]);
    expect(byId.safety?.map((i) => i.label)).toEqual(["Risk matrix", "HAZOP H-02", "HAZOP H-10", "HAZOP session"]);
    expect(byId.cost?.map((i) => i.label)).toEqual(["Techno-economics (TEA)"]);
    expect(byId.project?.map((i) => i.label)).toEqual(["README", "History", "Reaction library"]);
    // YAML documents open in the table view, the others as files
    expect(byId.process?.[1]?.to).toEqual({ name: "yaml", params: { path: ["process", "design-basis.yaml"] } });
    expect(byId.cost?.[0]?.to).toEqual({ name: "file", params: { path: ["estimate", "tea.md"] } });
    expect(navFiles(groups)).toEqual(
      new Set(["process/design-basis.yaml", "piping/line-list.yaml", "safety/risk-matrix.yaml", "safety/hazop/H-02/study.yaml", "safety/hazop/H-10/study.yaml", "safety/hazop/SESSION.md", "estimate/tea.md", "README.md"]),
    );
  });

  it("lists the TEA page instead of its report when the plant has a TEA", () => {
    const paths = new Set(["estimate/tea.md", "estimate/estimate.md"]);
    const cost = (has_tea: boolean) => navGroups({ ...bare, repo: { ...bare.repo!, has_tea }, paths }).find((g) => g.id === "cost")!.items;
    expect(cost(false).map((i) => [i.label, i.to.name])).toEqual([["Cost estimate", "file"], ["Techno-economics (TEA)", "file"]]);
    expect(cost(true).map((i) => [i.label, i.to.name])).toEqual([["Techno-economics (TEA)", "tea"], ["Cost estimate", "file"]]);
  });

  it("has no documents before the tree is loaded and no history in a snapshot", () => {
    expect(labels({ ...bare, paths: null, snapshot: true }).project).toEqual(["Reaction library"]);
  });
});

describe("isCurrent", () => {
  const groups = navGroups({ ...bare, sheets, repo: { ...bare.repo!, has_simulation: true }, paths: new Set(["process/design-basis.yaml"]) });
  const item = (label: string) => groups.flatMap((g) => g.items).find((i) => i.label === label)!;

  it("tells the stream table from the simulation tab of the same page", () => {
    expect(isCurrent(item("Stream table"), { name: "streams", path: "", tab: null })).toBe(true);
    expect(isCurrent(item("Simulation"), { name: "streams", path: "", tab: null })).toBe(false);
    expect(isCurrent(item("Simulation"), { name: "streams", path: "", tab: "simulation" })).toBe(true);
  });

  it("matches a sheet or a document by its file", () => {
    expect(isCurrent(item("PFD"), { name: "pid", path: "process/PFD.xml", tab: null })).toBe(true);
    expect(isCurrent(item("PFD"), { name: "pid", path: "process/BFD.xml", tab: null })).toBe(false);
    expect(isCurrent(item("Design basis"), { name: "yaml", path: "process/design-basis.yaml", tab: null })).toBe(true);
    expect(isCurrent(item("Design basis"), { name: "file", path: "process/design-basis.yaml", tab: null })).toBe(false);
  });
});
