import { describe, expect, it } from "vitest";
import type { TreeEntry } from "@/api";
import { hazopPaths, parseStudy, refLabel, studyTotals, worksheetRows, type HazopStudy } from "@/lib/hazop";

const study: HazopStudy = {
  id: "H-01",
  nodes: [
    {
      id: "N1",
      status: "accepted",
      deviations: [
        { id: "N1-LL", guide_word: "less", parameter: "level", scenarios: [{ id: "S1", status: "accepted" }, { id: "S2" }] },
        { id: "N1-HP", guide_word: "more", parameter: "pressure", notes: "no credible cause" },
      ],
    },
  ],
  safeguards: [{ id: "SG1", status: "proposed" }],
  actions: [{ id: "A1", status: "open" }, { id: "A2", status: "closed" }],
};

describe("hazopPaths", () => {
  it("finds the study files core reads, sorted by id", () => {
    const tree: TreeEntry[] = [
      { path: "safety/hazop/H-02/study.yaml", type: "file", kind: "yaml" },
      { path: "safety/hazop/H-01/study.yaml", type: "file", kind: "yaml" },
      { path: "safety/hazop/H-01", type: "dir", kind: "other" },
      { path: "safety/risk-matrix.yaml", type: "file", kind: "yaml" },
      { path: "safety/hazop/H-01/notes/study.yaml", type: "file", kind: "yaml" },
    ];
    expect([...hazopPaths(tree)]).toEqual([
      ["H-01", "safety/hazop/H-01/study.yaml"],
      ["H-02", "safety/hazop/H-02/study.yaml"],
    ]);
  });
});

describe("parseStudy", () => {
  it("keeps the file's id, falls back to the folder's, and refuses a non-mapping", () => {
    expect(parseStudy({ title: "t" }, "H-03").id).toBe("H-03");
    expect(parseStudy({ id: "X" }, "H-03").id).toBe("X");
    expect(() => parseStudy([1], "H-03")).toThrow(/not a HAZOP study/);
  });
});

describe("worksheetRows", () => {
  it("spans a deviation over its scenarios and keeps one without scenarios", () => {
    const rows = worksheetRows(study.nodes![0]!);
    expect(rows.map((r) => [r.deviation.id, r.scenario?.id ?? null, r.first, r.span])).toEqual([
      ["N1-LL", "S1", true, 2],
      ["N1-LL", "S2", false, 2],
      ["N1-HP", null, true, 1],
    ]);
  });
});

describe("studyTotals", () => {
  it("counts a missing status as proposed and closed actions as done", () => {
    expect(studyTotals(study)).toEqual({ nodes: 1, scenarios: 2, proposed: 2, openActions: 1 });
  });
});

describe("refLabel", () => {
  it("reads tags, sheet tags and untagged objects", () => {
    expect(refLabel("V-101")).toBe("V-101");
    expect(refLabel({ tag: "P-101", sheet: "P-02" })).toBe("P-101");
    expect(refLabel({ sheet: "P-01", object: "Nozzle-7" })).toBe("P-01:Nozzle-7");
  });
});
