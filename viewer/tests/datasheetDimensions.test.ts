/**
 * The datasheet fields (main dimensions, weights, structured materials, the nozzle
 * schedule) and the `/api/datasheets` path with its fallback, against the ASU's real answers
 * (scripts/regen-fixtures.py --asu-datasheets) and small hand-made cases.
 */
import { afterEach, describe, expect, it } from "vitest";
import { api, setFetch, useSnapshot, type DatasheetDetail, type DatasheetIndex } from "@/api";
import { snapshotKey, SnapshotSource, type SnapshotManifest } from "@/dataSource";
import {
  countValues,
  drawingState,
  loadDatasheetIndex,
  loadDatasheetPage,
  parseDatasheet,
  parseDimensions,
  parseMaterial,
  parseWeights,
  serverHasDatasheets,
  sortEntries,
  summaryEntry,
  totalsOf,
} from "@/lib/datasheets";
import indexJson from "./fixtures/api/datasheets-index-asu.json";
import detailsJson from "./fixtures/api/datasheet-details-asu.json";
import drawingsJson from "./fixtures/api/datasheet-drawings-asu.json";
import snapshotKeysJson from "./fixtures/api/datasheets-snapshot-keys.json";
import yamlJson from "./fixtures/api/datasheets-asu.json";

const index = indexJson as unknown as DatasheetIndex;
const details = detailsJson as unknown as Record<string, DatasheetDetail>;
const sheet = (tag: string) => parseDatasheet(details[tag]!.data, tag);

describe("main dimensions", () => {
  it("groups a horizontal vessel's dimensions by family, with units and assumed markers", () => {
    const dims = sheet("V-2101A").dimensions!;
    expect(dims.orientation).toBe("horizontal");
    expect(dims.groups.map((g) => g.key)).toEqual(["shell", "support", "overall"]);
    const shell = dims.groups[0]!.rows;
    expect(shell.map((r) => r.key)).toEqual(["outside_diameter", "tangent_length", "head", "axis_deg"]);
    expect(shell[1]).toMatchObject({ label: "tangent length (T-T)", value: 15.75, unit: "m", assumed: true });
    expect(shell[2]).toMatchObject({ value: "ellipsoidal_2_1", unit: "" });
    expect(dims.groups[1]!.rows.map((r) => [r.key, r.value])).toEqual([
      ["support.type", "saddles"],
      ["support.height", 2],
    ]);
    expect(dims.sections).toEqual([]);
  });

  it("states a plain number in the field's unit, and nothing for a count", () => {
    const dims = parseDimensions({
      inside_diameter: 2.4,
      shell_passes: 1,
      axis_deg: 90,
      tubes: { count: 412, outside_diameter: { value: 19.05, unit: "mm" }, length: 6, passes: 2 },
      plates: { height: 1.2, count: "TBD" },
      baseplate: { length: 2.6, width: 1 },
      shaft_height: 0.6,
      overall_width: { value: "supplier", reason: "skid drawing" },
    })!;
    const row = (group: string, key: string) => dims.groups.find((g) => g.key === group)!.rows.find((r) => r.key === key)!;
    expect(row("shell", "inside_diameter").unit).toBe("m");
    expect(row("shell", "shell_passes").unit).toBe("");
    expect(row("shell", "axis_deg").unit).toBe("deg");
    expect(row("tubes", "tubes.count")).toMatchObject({ value: 412, unit: "" });
    expect(row("tubes", "tubes.outside_diameter")).toMatchObject({ value: 19.05, unit: "mm" });
    expect(row("tubes", "tubes.length").unit).toBe("m");
    expect(row("plates", "plates.count").open).toBe("tbd");
    expect(row("machine", "baseplate.length")).toMatchObject({ label: "baseplate length", unit: "m" });
    expect(row("machine", "shaft_height").value).toBe(0.6);
    expect(row("overall", "overall_width")).toMatchObject({ open: "supplier", reason: "skid drawing" });
    expect(parseDimensions(null)).toBeNull();
    expect(parseDimensions({})).toEqual({ orientation: null, groups: [], sections: [] });
  });

  it("reads a column's sections", () => {
    const dims = parseDimensions({
      orientation: "vertical",
      sections: [
        { id: "stripping", internals: "sieve trays", bottom: 1.5, height: { value: 12, unit: "m", assumed: true }, count: 30, spacing: 0.4 },
        { id: "rectifying", internals: { value: "structured packing Mellapak 250Y", source: "D-061" }, notes: "two beds" },
      ],
    })!;
    expect(dims.sections).toHaveLength(2);
    expect(dims.sections[0]).toMatchObject({ id: "stripping", bottom: { value: 1.5, unit: "m" }, height: { assumed: true }, count: { value: 30, unit: "" }, spacing: { unit: "m" } });
    expect(dims.sections[1]).toMatchObject({ bottom: null, height: null, notes: "two beds", internals: { source: "D-061" } });
  });

  it("reads weights in t, with supplier values and their reason", () => {
    const w = sheet("V-2101A").weights!;
    expect(w.map((r) => [r.key, r.value, r.unit, r.assumed])).toEqual([
      ["empty", 62, "t", true],
      ["operating", 158, "t", true],
      ["test", "supplier", "t", false],
    ]);
    expect(w[2]).toMatchObject({ open: "supplier", reason: "full of water, from the vessel supplier" });
    expect(parseWeights({ empty: 3 })).toEqual([expect.objectContaining({ key: "empty", value: 3, unit: "t" })]);
    expect(sheet("C-1101").weights).toBeNull();
  });

  it("counts dimension and weight values with the others", () => {
    const c = countValues(sheet("V-2101A"));
    expect(c.supplier).toBe(1);
    expect(c.assumed).toBeGreaterThanOrEqual(details["V-2101A"]!.summary.counts.assumed - 1);
  });
});

describe("materials and nozzles", () => {
  it("reads a structured material with its class and standard, and a plain one", () => {
    const m = sheet("V-2101A").materials;
    expect(m.map((r) => [r.key, r.value, r.material_class, r.standard])).toEqual([
      ["shell", "SA-516-70N", "low_temperature_carbon_steel", "ASME II A"],
      ["heads", "SA-516-70N", "low_temperature_carbon_steel", "ASME II A"],
      ["internals", "SS 304 support grid", null, ""],
    ]);
    expect(m[1]!.assumed).toBe(true);
    expect(parseMaterial("casing", { value: "TBD", source: "vendor" })).toMatchObject({ open: "tbd", material_class: null });
    expect(parseMaterial("casing", { value: "CS", unit: "", source: "list" })).toMatchObject({ value: "CS", source: "list" });
  });

  it("reads the extended nozzle schedule (mark, facing, standard, projection, assumed)", () => {
    const nozzles = sheet("V-2101A").nozzles;
    expect(nozzles.find((n) => n.name === "N1")).toMatchObject({ mark: "N1", service: "Feed air inlet", rating: "PN16", facing: "RF", standard: "EN 1092-1", projection_m: 0.6, assumed: false });
    expect(nozzles.find((n) => n.name === "M1")).toMatchObject({ mark: "M1", face: "side", axial_m: 0, assumed: true });
    // Without a mark, the P&ID name stands in.
    expect(sheet("V-2101B").nozzles[0]).toMatchObject({ name: "N1", mark: "N1", facing: "", projection_m: null });
  });

  it("knows every field the ASU's sheets use (core's Datasheet, DatasheetDimensions, Weights, Material, DatasheetNozzle)", () => {
    const SHEET = ["tag", "type", "service", "operating", "design", "materials", "dimensions", "weights", "nozzles", "sizing_basis", "type_specific", "draft", "notes"];
    const DIMENSIONS = ["orientation", "inside_diameter", "outside_diameter", "tangent_length", "head", "support", "sections", "shell_passes", "tubes", "plates", "baseplate", "shaft_height", "axis_deg", "overall_height", "overall_length", "overall_width"];
    const NOZZLE = ["name", "dn", "lines", "service", "rating", "source", "orientation_deg", "offset_m", "face", "elevation_m", "location_source", "mark", "facing", "standard", "projection_m", "axial_m", "assumed"];
    const unknown = new Set<string>();
    for (const detail of Object.values(details)) {
      const d = detail.data as Record<string, unknown>;
      for (const k of Object.keys(d)) if (!SHEET.includes(k)) unknown.add(k);
      for (const k of Object.keys((d.dimensions ?? {}) as object)) if (!DIMENSIONS.includes(k)) unknown.add(`dimensions.${k}`);
      for (const k of Object.keys((d.weights ?? {}) as object)) if (!["empty", "operating", "test"].includes(k)) unknown.add(`weights.${k}`);
      for (const n of (d.nozzles ?? []) as Record<string, unknown>[]) for (const k of Object.keys(n)) if (!NOZZLE.includes(k)) unknown.add(`nozzle.${k}`);
    }
    expect([...unknown]).toEqual([]);
  });
});

describe("the /api/datasheets index", () => {
  const entries = index.datasheets.map(summaryEntry);

  it("reads the drawing state of each summary", () => {
    const state = (tag: string) => drawingState(index.datasheets.find((s) => s.tag === tag));
    expect(state("V-2101A")).toBe("current");
    expect(state("V-2101B")).toBe("stale");
    expect(state("T-4102")).toBe("missing");
    expect(drawingState({ valid: false, has_drawing: false, drawing_current: false })).toBe("none");
    expect(drawingState(undefined)).toBeNull();
    expect(index.missing).toEqual(["P-4102B"]);
  });

  it("totals the plant", () => {
    expect(totalsOf(entries)).toMatchObject({
      sheets: 38,
      drafts: 4,
      assumed: 301,
      tbd: 13,
      dimensions: 37,
      weights: 30,
      drawings: { current: 35, stale: 2, missing: 1, none: 0 },
      findings: { error: 0, warning: 6, info: 0 },
    });
  });

  it("sorts by drawing state and findings, worst first", () => {
    expect(sortEntries(entries, "drawing", -1).slice(0, 3).map((e) => e.tag)).toEqual(["T-4102", "V-2101B", "V-3101"]);
    expect(sortEntries(entries, "findings", -1).slice(0, 3).map((e) => e.tag)).toEqual(["V-3101", "V-2101A", "V-2101B"]);
    expect(sortEntries(entries, "weights", 1)[0]!.tag).toBe("C-1101");
  });

  it("each sheet's answer matches its summary", () => {
    for (const s of index.datasheets) {
      const d = details[s.tag]!;
      expect(d.summary).toEqual(s);
      expect(d.drawing.state).toBe(drawingState(s));
      expect(d.findings.length).toBe(s.findings.error + s.findings.warning + s.findings.info);
    }
  });
});

describe("choosing the source", () => {
  const calls: string[] = [];
  const serve = (routes: Record<string, unknown>) =>
    setFetch(async (input) => {
      const url = String(input);
      calls.push(url);
      const path = url.replace(/^\/api\//, "").split("?")[0]!;
      if (!(path in routes)) return new Response('{"error":"not found"}', { status: 404 });
      const body = routes[path];
      return new Response(typeof body === "string" ? body : JSON.stringify(body), { status: 200, headers: path.endsWith(".svg") ? { "x-cheme-drawing": "committed", "x-cheme-drawing-current": "false" } : {} });
    });
  const yamlDocs = yamlJson as unknown as Record<string, unknown>;

  afterEach(() => {
    calls.length = 0;
    useSnapshot(null);
  });

  it("asks /api/datasheets only when /api/repo has has_datasheets", () => {
    expect(serverHasDatasheets({ has_datasheets: true } as never)).toBe(true);
    expect(serverHasDatasheets({ has_datasheets: false } as never)).toBe(true);
    expect(serverHasDatasheets({} as never)).toBe(false);
    expect(serverHasDatasheets(null)).toBe(false);
  });

  it("uses the server's index, and falls back to the tree on a 404", async () => {
    serve({ datasheets: index });
    const fromServer = await loadDatasheetIndex(null, true);
    expect(fromServer).toMatchObject({ source: "server", missing: ["P-4102B"] });
    expect(fromServer.entries).toHaveLength(38);
    expect(calls).toEqual(["/api/datasheets"]);

    calls.length = 0;
    serve({ tree: [] });
    const fallback = await loadDatasheetIndex("main", true);
    expect(fallback).toEqual({ source: "tree", entries: [], missing: [], index: null });
    expect(calls).toEqual(["/api/datasheets?rev=main", "/api/tree?rev=main"]);

    calls.length = 0;
    await loadDatasheetIndex(null, false);
    expect(calls).toEqual(["/api/tree"]);
  });

  it("reads one sheet from the server, else from the tree with its committed drawing", async () => {
    serve({ "datasheets/V-2101B": details["V-2101B"] });
    const page = await loadDatasheetPage("V-2101B", null, true);
    expect(page).toMatchObject({ source: "server", path: "equipment/datasheets/V-2101B.yaml", treeDrawing: null });
    expect(page.sheet!.dimensions!.groups[0]!.rows.find((r) => r.key === "tangent_length")!.value).toBe(16);
    expect(page.findings.map((f) => f.rule)).toEqual(["cheme.datasheet-drawing-stale"]);

    calls.length = 0;
    const path = "equipment/datasheets/P-1101A.yaml";
    serve({ tree: [{ path, type: "file", kind: "yaml" }, { path: "equipment/datasheets/P-1101A.svg", type: "file", kind: "other" }], yaml: yamlDocs[path] });
    const old = await loadDatasheetPage("P-1101A", null, true);
    expect(old).toMatchObject({ source: "tree", path, detail: null, findings: [], treeDrawing: "equipment/datasheets/P-1101A.svg" });
    expect(calls).toEqual(["/api/datasheets/P-1101A", "/api/tree", `/api/yaml?path=${encodeURIComponent(path)}`]);
  });

  it("reads the drawing and what the headers say it is", async () => {
    serve({ "datasheets/V-2101B.svg": (drawingsJson as Record<string, { svg: string }>)["V-2101B.svg"]!.svg });
    const drawing = await api.datasheetDrawing("V-2101B", { generated: true, rev: "main" });
    expect(calls).toEqual(["/api/datasheets/V-2101B.svg?generated=true&rev=main"]);
    expect(drawing).toMatchObject({ kind: "committed", current: false });
    expect(drawing.svg).toContain("<svg");
    expect(api.datasheetDrawingUrl("V-2101B")).toBe("/api/datasheets/V-2101B.svg");
    expect(api.datasheetDrawingUrl("V-2101B", { generated: true })).toBe("/api/datasheets/V-2101B.svg?generated=true");
  });

  it("names the requests as cheme export-static does", () => {
    const keys = Object.keys(snapshotKeysJson);
    expect(keys).toContain(snapshotKey("datasheets"));
    expect(keys).toContain(snapshotKey(`datasheets/${encodeURIComponent("V-2101A")}`, { rev: undefined }));
    expect(keys).toContain(snapshotKey("datasheets/V-2101A.svg", { rev: undefined, generated: undefined }));
    expect(keys.filter((k) => k.endsWith(".svg"))).toHaveLength(38);
    expect(keys.some((k) => k.includes("generated"))).toBe(false);
  });

  it("opens a datasheet and its drawing from a snapshot when the tag has a space", async () => {
    // The keys cheme export-static writes for the tag "E 101": the raw tag, not URL-encoded.
    const manifest = {
      schema: "cheme/viewer-snapshot/v1",
      source: { name: null, commit: "abc", rev: null, dirty: false, tool: "test" },
      limits: { max_file_bytes: 1, log_limit: 50 },
      skipped: [],
      entries: {
        "datasheets/E 101": { file: "d.json", status: 200, type: "application/json" },
        "datasheets/E 101.svg": { file: "d.svg", status: 200, type: "image/svg+xml" },
      },
    } as SnapshotManifest;
    const files: Record<string, string> = { "http://host/snap/data/d.json": JSON.stringify({ ...details["V-2101A"], tag: "E 101" }), "http://host/snap/data/d.svg": "<svg/>" };
    const fetched: string[] = [];
    const host = (async (input: RequestInfo | URL) => {
      fetched.push(String(input));
      return String(input) in files ? new Response(files[String(input)]) : new Response("nope", { status: 404 });
    }) as typeof fetch;
    useSnapshot(new SnapshotSource("http://host/snap/", manifest, host));
    expect((await api.datasheet("E 101")).tag).toBe("E 101");
    expect((await api.datasheetDrawing("E 101")).svg).toBe("<svg/>");
    expect(api.datasheetDrawingUrl("E 101")).toBe("http://host/snap/data/d.svg");
    expect(fetched).toEqual(["http://host/snap/data/d.json", "http://host/snap/data/d.svg"]);

    // Against a server the tag stays URL-encoded.
    useSnapshot(null);
    serve({ "datasheets/E%20101": { ...details["V-2101A"], tag: "E 101" }, "datasheets/E%20101.svg": "<svg/>" });
    await api.datasheet("E 101");
    await api.datasheetDrawing("E 101");
    expect(calls).toEqual(["/api/datasheets/E%20101", "/api/datasheets/E%20101.svg"]);
    expect(api.datasheetDrawingUrl("E 101")).toBe("/api/datasheets/E%20101.svg");
  });

  it("serves the drawing URL from a snapshot when it holds it", () => {
    const manifest = {
      schema: "cheme/viewer-snapshot/v1",
      source: { name: null, commit: "abc", rev: null, dirty: false, tool: "test" },
      limits: { max_file_bytes: 1, log_limit: 50 },
      skipped: [],
      entries: { "datasheets/V-2101A.svg": { file: "x.svg", status: 200, type: "image/svg+xml" } },
    } as SnapshotManifest;
    useSnapshot(new SnapshotSource("http://host/snap/", manifest));
    expect(api.datasheetDrawingUrl("V-2101A")).toBe("http://host/snap/data/x.svg");
    expect(api.datasheetDrawingUrl("V-2101A", { generated: true })).toBeNull();
  });
});
