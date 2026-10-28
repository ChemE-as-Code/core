/**
 * The datasheet parsing and counting (`src/lib/datasheets.ts`) against the ASU's real sheets
 * (`/api/yaml` of each `equipment/datasheets/<TAG>.yaml`, scripts/regen-fixtures.py) and small
 * hand-made cases.
 */
import { describe, expect, it } from "vitest";
import type { TreeEntry } from "@/api";
import { datasheetPaths } from "@/lib/studies";
import {
  countValues,
  filterEntries,
  inputsText,
  inputText,
  isQuantity,
  openKind,
  parseDatasheet,
  parseValue,
  sortEntries,
  valueText,
  type DatasheetEntry,
} from "@/lib/datasheets";
import datasheetsJson from "./fixtures/api/datasheets-asu.json";
import asuTreeJson from "./fixtures/api/tree-asu.json";

const docs = datasheetsJson as unknown as Record<string, { data: unknown; kind: string | null }>;
const sheet = (tag: string) => parseDatasheet(docs[`equipment/datasheets/${tag}.yaml`]!.data, tag);
const entries: DatasheetEntry[] = [...datasheetPaths(asuTreeJson as unknown as TreeEntry[])].map(([tag, path]) => {
  const s = parseDatasheet(docs[path]!.data, tag);
  return { tag, path, sheet: s, counts: countValues(s), error: null };
});

describe("values", () => {
  it("normalises numbers, texts and quantities", () => {
    expect(parseValue(5)).toEqual({ value: 5, unit: "", source: "", assumed: false, reason: "", open: null, origin: null, fingerprint: null, inputs: [] });
    expect(parseValue({ value: 5.01, unit: "bar(a)", source: "design basis", assumed: true })).toMatchObject({ value: 5.01, unit: "bar(a)", assumed: true, open: null });
    expect(parseValue("CS")).toMatchObject({ value: "CS", open: null });
  });

  it("marks TBD, missing, supplier and not applicable", () => {
    expect(openKind("TBD")).toBe("tbd");
    expect(openKind("tbd ")).toBe("tbd");
    expect(openKind(null)).toBe("tbd");
    expect(openKind(undefined)).toBe("tbd");
    expect(openKind("")).toBe("tbd");
    expect(openKind("supplier")).toBe("supplier");
    expect(openKind("not_applicable")).toBe("not_applicable");
    expect(openKind(0)).toBeNull();
    expect(parseValue({ value: null, unit: "m" })).toMatchObject({ value: null, unit: "m", open: "tbd" });
    expect(valueText(parseValue({ value: null }))).toBe("TBD (missing)");
    expect(valueText(parseValue("TBD"))).toBe("TBD");
    expect(valueText(parseValue({ value: "not_applicable", reason: "no reflux" }))).toBe("not applicable");
    expect(valueText(parseValue(83190))).toBe("83,190");
  });

  it("tells a quantity from a nested mapping", () => {
    expect(isQuantity({ value: 1, unit: "m" })).toBe(true);
    expect(isQuantity({ value: 1, stream: "S2" })).toBe(false);
    expect(isQuantity([{ value: 1 }])).toBe(false);
  });
});

describe("values cheme datasheets fill calculated (pre-release PR 282)", () => {
  // A vessel's volume after a fill: origin, the fingerprint of its inputs and the inputs besides the streams.
  const filled = {
    value: 12.4,
    unit: "m3",
    source: "cheme datasheets fill: residence time x liquid flow (stream S7)",
    assumed: true,
    origin: "correlation",
    fingerprint: "3f9a0c1d2e4b5a69",
    inputs: ["catalyst:CAT-1", "pipe:L-12", "nozzle:R-101/N1", "residence_time:R-101", "datasheet:design.pressure_barg"],
  };
  const sheetWith = (v: unknown) =>
    parseDatasheet({
      tag: "R-101",
      operating: { flow_kg_h: v, pressure_barg: { value: 5, unit: "barg" } },
      design: { pressure_barg: { value: 7, unit: "barg", source: "equipment/equipment-list.yaml" } },
      materials: { shell: v },
      type_specific: { volume_m3: v, stages: 12 },
      dimensions: { inside_diameter: v },
      weights: { empty: v },
      sizing_basis: [{ parameter: "volume", value: v }],
    });

  it("is a quantity, read with its origin, fingerprint and inputs", () => {
    expect(isQuantity(filled)).toBe(true);
    expect(isQuantity({ value: 1, fingerprint: null, inputs: null, origin: null })).toBe(true);
    expect(parseValue(filled)).toEqual({
      value: 12.4,
      unit: "m3",
      source: filled.source,
      assumed: true,
      reason: "",
      open: null,
      origin: "correlation",
      fingerprint: "3f9a0c1d2e4b5a69",
      inputs: filled.inputs,
    });
    expect(parseValue({ value: 1, fingerprint: null, inputs: null, origin: null })).toMatchObject({ value: 1, open: null, origin: null, fingerprint: null, inputs: [] });
  });

  it("stays a row of every section, not a nested mapping", () => {
    const s = sheetWith(filled);
    const row = { value: 12.4, unit: "m3", assumed: true, open: null, origin: "correlation", inputs: filled.inputs };
    expect(s.operating.find((r) => r.key === "flow_kg_h")).toMatchObject(row);
    expect(s.materials[0]).toMatchObject({ key: "shell", ...row, material_class: null });
    expect(s.type_specific.map((r) => r.key)).toEqual(["volume_m3", "stages"]);
    expect(s.type_specific[0]).toMatchObject(row);
    expect(s.type_other).toEqual({});
    expect(s.dimensions!.groups[0]!.rows[0]).toMatchObject({ key: "inside_diameter", ...row });
    expect(s.weights![0]).toMatchObject({ key: "empty", ...row });
    expect(s.sizing_basis[0]).toMatchObject({ parameter: "volume", ...row });
    expect(countValues(s)).toEqual({ values: 9, assumed: 6, tbd: 0, supplier: 0, not_applicable: 0 });
  });

  it("leaves the other rows as they were", () => {
    const s = sheetWith(3);
    expect(s.operating[1]).toEqual({ key: "pressure_barg", value: 5, unit: "barg", source: "", assumed: false, reason: "", open: null, origin: null, fingerprint: null, inputs: [] });
    expect(s.design[0]).toMatchObject({ key: "pressure_barg", value: 7, source: "equipment/equipment-list.yaml", origin: null, inputs: [] });
    expect(inputsText(s.design[0]!)).toBe("");
  });

  it("reads a list value (a compressor's intercooler duties) and writes it out", () => {
    const duties = parseValue({ value: [1234.5, 678.9], unit: "kW", assumed: true, origin: "correlation", fingerprint: "ab12" });
    expect(duties).toMatchObject({ value: [1234.5, 678.9], unit: "kW", open: null, origin: "correlation" });
    expect(valueText(duties)).toBe("1,234.5; 678.9");
    expect(valueText(parseValue({ value: [1500, 1450], unit: "kW" }))).toBe("1,500; 1,450");
    expect(parseDatasheet({ type_specific: { intercooler_duties_kw: { value: [1234.5, 678.9], unit: "kW", fingerprint: "ab12" } } }).type_specific).toHaveLength(1);
    // A nested mapping in a list is no value.
    expect(parseValue({ value: [{ a: 1 }] })).toMatchObject({ value: null });
  });

  it("names the inputs, compactly and one by one", () => {
    const v = parseValue(filled);
    expect(inputText("catalyst:CAT-1")).toBe("catalyst CAT-1");
    expect(inputText("residence_time:R-101")).toBe("residence time R-101");
    expect(inputText("datasheet:design.pressure_barg")).toBe("datasheet design.pressure_barg");
    expect(inputText("other")).toBe("other");
    expect(parseValue({ value: 1, inputs: ["pipe:L-12", 3, "", null] }).inputs).toEqual(["pipe:L-12"]);
    expect(inputsText(v)).toBe("catalyst CAT-1, pipe L-12, nozzle R-101/N1, +2 more");
    expect(inputsText(parseValue({ ...filled, inputs: ["pipe:L-12"] }))).toBe("pipe L-12");
    expect(v.inputs.map(inputText)).toEqual(["catalyst CAT-1", "pipe L-12", "nozzle R-101/N1", "residence time R-101", "datasheet design.pressure_barg"]);
  });
});

describe("the ASU's datasheets", () => {
  it("reads every sheet of the tree", () => {
    expect(entries).toHaveLength(39);
    expect(entries.every((e) => e.sheet!.tag === e.tag)).toBe(true);
    expect(entries.filter((e) => e.sheet!.draft).map((e) => e.tag)).toEqual(["C-3101", "C-3102", "E-3102", "E-3103"]);
  });

  it("uses only the fields the viewer reads (core's Datasheet, DatasheetNozzle, Quantity, SizingItem)", () => {
    const SHEET = ["tag", "type", "service", "operating", "design", "materials", "nozzles", "sizing_basis", "type_specific", "draft", "notes"];
    const NOZZLE = ["name", "dn", "lines", "service", "rating", "source", "orientation_deg", "offset_m", "face", "elevation_m", "location_source"];
    const unknown = new Set<string>();
    for (const doc of Object.values(docs)) {
      const d = doc.data as Record<string, unknown>;
      for (const k of Object.keys(d)) if (!SHEET.includes(k)) unknown.add(k);
      for (const n of (d.nozzles ?? []) as Record<string, unknown>[]) for (const k of Object.keys(n)) if (!NOZZLE.includes(k)) unknown.add(`nozzle.${k}`);
      for (const section of ["operating", "design", "materials"])
        for (const [k, v] of Object.entries((d[section] ?? {}) as Record<string, unknown>)) if (typeof v === "object" && v !== null && !isQuantity(v)) unknown.add(`${section}.${k}`);
      for (const item of (d.sizing_basis ?? []) as Record<string, unknown>[]) for (const k of Object.keys(item)) if (!["parameter", "value", "reference"].includes(k)) unknown.add(`sizing_basis.${k}`);
    }
    expect([...unknown]).toEqual([]);
  });

  it("parses a pump: header, sections, nozzles, type-specific values", () => {
    const p = sheet("P-1101A");
    expect(p).toMatchObject({ tag: "P-1101A", type: "CentrifugalPump", service: "DCAC cooling water pump", draft: false });
    expect(p.operating.map((r) => r.key)).toEqual(["fluid", "source_pressure", "destination_pressure", "density"]);
    expect(p.design.find((r) => r.key === "pressure_barg")).toMatchObject({ value: 10, unit: "barg", source: "equipment/equipment-list.yaml", assumed: false });
    expect(p.nozzles).toEqual([
      expect.objectContaining({ name: "N1", dn: 200, lines: ["CW-1001"], source: "pid/P-01.xml", face: "", orientation_deg: null }),
      expect.objectContaining({ name: "N2", dn: 200, lines: ["CW-1001"] }),
    ]);
    expect(p.type_specific.find((r) => r.key === "shaft_power_kw")).toMatchObject({ value: 28.13, unit: "kW", assumed: true });
    expect(p.sizing_basis).toEqual([]);
    expect(countValues(p)).toEqual({ values: 15, assumed: 6, tbd: 0, supplier: 0, not_applicable: 0 });
  });

  it("counts a draft column's TBD values and keeps its process streams apart", () => {
    const c = sheet("C-3101");
    expect(c.draft).toBe(true);
    expect(c.type_specific.filter((r) => r.open === "tbd").map((r) => r.key)).toEqual(["number_of_stages", "theoretical_stages"]);
    expect(Object.keys(c.type_other)).toEqual(["process_streams"]);
    expect(c.nozzles[0]).toMatchObject({ name: "N1", face: "side", orientation_deg: 0, elevation_m: 5.8 });
    expect(countValues(c)).toEqual({ values: 14, assumed: 6, tbd: 2, supplier: 0, not_applicable: 0 });
  });

  it("counts values awaiting the supplier and not applicable with their reasons", () => {
    const c = sheet("C-1101");
    expect(countValues(c)).toEqual({ values: 23, assumed: 11, tbd: 0, supplier: 3, not_applicable: 4 });
    expect(c.type_specific.find((r) => r.key === "minimum_reflux_ratio")).toMatchObject({ open: "not_applicable", reason: "no reflux in a direct contact cooler" });
  });

  it("counts the sizing basis", () => {
    const e = sheet("E-3101");
    expect(e.sizing_basis).toEqual([
      expect.objectContaining({ parameter: "cold outlet temperatures", value: "13 C (2 K warm-end approach to the 15 C main air, ASSUMED)", reference: "DESIGN.md D-060 (4), (6)", open: null }),
    ]);
  });

  it("totals over the plant", () => {
    const sum = (k: "assumed" | "tbd") => entries.reduce((n, e) => n + e.counts![k], 0);
    expect(sum("assumed")).toBe(276);
    expect(sum("tbd")).toBe(13);
  });
});

describe("index filter and sort", () => {
  it("filters by tag, type or service, and by type", () => {
    expect(filterEntries(entries, "p-110").map((e) => e.tag)).toEqual(["P-1101A", "P-1101B", "P-1102A", "P-1102B"]);
    expect(filterEntries(entries, "vaporizer").map((e) => e.tag)).toContain("E-4105A");
    expect(filterEntries(entries, "", "ProcessColumn").every((e) => e.sheet!.type === "ProcessColumn")).toBe(true);
    expect(filterEntries(entries, "C-1101", "CentrifugalPump")).toEqual([]);
  });

  it("sorts by tag (numeric), by counts and drafts first", () => {
    expect(sortEntries(entries, "tag", -1)[0]!.tag).toBe("V-3101");
    const byTbd = sortEntries(entries, "tbd", -1);
    expect(byTbd[0]!.counts!.tbd).toBeGreaterThanOrEqual(byTbd[1]!.counts!.tbd);
    expect(sortEntries(entries, "draft", -1).slice(0, 4).map((e) => e.tag)).toEqual(["C-3101", "C-3102", "E-3102", "E-3103"]);
    const a = { tag: "P-2", path: "", sheet: null, counts: null, error: "x" };
    const b = { tag: "P-10", path: "", sheet: null, counts: null, error: "x" };
    expect(sortEntries([b, a], "tag").map((e) => e.tag)).toEqual(["P-2", "P-10"]);
  });

  it("parses a sheet with nothing in it", () => {
    expect(parseDatasheet(null, "X-1")).toMatchObject({ tag: "X-1", type: null, draft: false, operating: [], nozzles: [], sizing_basis: [] });
    expect(countValues(parseDatasheet({}, "X-1")).values).toBe(0);
  });
});
