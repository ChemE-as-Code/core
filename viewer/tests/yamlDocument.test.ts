import { describe, expect, it } from "vitest";
import { docText, documentBlocks, keyTitle } from "@/lib/yamlDocument";

describe("documentBlocks", () => {
  it("groups scalars, lists values, tabulates lists of objects and nests mappings", () => {
    const blocks = documentBlocks({
      title: "ASU",
      year: 2026,
      assumptions: ["ASSUMED 30 C", "ASSUMED 1.013 bara"],
      products: [
        { name: "GOX", purity: 0.995 },
        { name: "LIN", rate: 2 },
      ],
      site: { location: "coast", elevation_m: 5, limits: { min_c: -5 } },
      empty: [],
    });
    expect(blocks).toEqual([
      { kind: "fields", fields: [{ key: "title", text: "ASU" }, { key: "year", text: "2026" }] },
      { kind: "list", key: "assumptions", items: ["ASSUMED 30 C", "ASSUMED 1.013 bara"] },
      { kind: "table", key: "products", columns: ["name", "purity", "rate"], rows: [["GOX", "0.995", ""], ["LIN", "", "2"]] },
      {
        kind: "section",
        key: "site",
        title: "Site",
        blocks: [
          { kind: "fields", fields: [{ key: "location", text: "coast" }, { key: "elevation_m", text: "5" }] },
          { kind: "section", key: "limits", title: "Limits", blocks: [{ kind: "fields", fields: [{ key: "min_c", text: "-5" }] }] },
        ],
      },
      { kind: "fields", fields: [{ key: "empty", text: "none" }] },
    ]);
  });

  it("keeps deep or mixed structure as a tree", () => {
    const deep = { a: { b: { c: { d: 1 } } }, mixed: [1, { x: 2 }] };
    const blocks = documentBlocks(deep);
    expect(blocks[1]).toEqual({ kind: "tree", key: "mixed", value: [1, { x: 2 }] });
    const a = blocks[0];
    expect(a?.kind === "section" && a.blocks[0]?.kind === "section" && a.blocks[0].blocks[0]).toEqual({ kind: "tree", key: "c", value: { d: 1 } });
  });
});

describe("docText", () => {
  it("writes nested values as text, not JSON", () => {
    expect(docText({ pressure_barg: 30, limit: "pipeline", tags: ["a", "b"] })).toBe("pressure_barg: 30; limit: pipeline; tags: a, b");
    expect(docText([{ a: 1 }, { a: 2 }])).toBe("a: 1, a: 2");
    expect(docText(null)).toBe("");
  });
});

describe("keyTitle", () => {
  it("turns a YAML key into a heading", () => {
    expect(keyTitle("design_basis")).toBe("Design basis");
    expect(keyTitle("risk-matrix")).toBe("Risk matrix");
  });
});
