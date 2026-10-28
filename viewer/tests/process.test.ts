import { describe, expect, it } from "vitest";
import type { ProcessStream, Sheet, StreamTable, YamlDoc } from "@/api";
import {
  balanceDetail,
  bfdConnectionOf,
  filterStreams,
  formatComposition,
  formatValue,
  groupSheets,
  pickInfo,
  streamStatus,
} from "@/lib/process";
import { processSections } from "@/lib/yamlTable";

function stream(id: string, over: Partial<ProcessStream> = {}): ProcessStream {
  return {
    id,
    title: `Stream ${id}`,
    kind: "material",
    from: "A.out",
    to: "B.in",
    from_block: "A",
    to_block: "B",
    on_bfd: true,
    template: null,
    has_state: true,
    properties: {
      pressure: null,
      temperature: null,
      flow: { value: 1000, unit: "kg/h", provenance: "given", stale: false },
      duty: null,
    },
    composition: null,
    phase: null,
    calculated: {},
    stale: [],
    imbalance: [],
    links: [],
    ...over,
  };
}

const table: StreamTable = {
  rev: null,
  case: "design",
  cases: [{ id: "design", description: "", default: true }],
  default_case: "design",
  units: { flow: "kg/h" },
  streams: [
    stream("S1", { from: "FEED.out", to: "M1.feed", from_block: "FEED", to_block: "MIX" }),
    stream("S2", { from: "M1.out", to: "C1.in", from_block: "MIX", to_block: "SEP" }),
    stream("S6", { from: "C1.vapour", to: "E1.in", from_block: "SEP", to_block: "SEP", on_bfd: false }),
  ],
  balances: [
    {
      node: "MIX",
      kind: "block",
      title: "Mixing",
      status: "ok",
      in_kg_h: 1500,
      out_kg_h: 1500,
      missing: [],
      failing: [],
      streams_in: ["S1"],
      streams_out: ["S2"],
    },
  ],
  nodes: [
    { id: "MIX", kind: "block", title: "Mixing", block: null, links: [] },
    { id: "C1", kind: "step", title: "Column", block: "SEP", links: [] },
  ],
  bfd_connections: { S1: ["S1"], S2: ["S2"] },
};

describe("groupSheets", () => {
  it("puts BFD then PFD under Process, then the P&IDs", () => {
    const sheets: Sheet[] = [
      { id: "P-01", file: "pid/P-01.xml", title: "", kind: "pid" },
      { id: "PFD", file: "process/PFD.xml", title: "", kind: "pfd" },
      { id: "BFD", file: "process/BFD.xml", title: "", kind: "bfd" },
      { id: "P-02", file: "pid/P-02.xml", title: "" },
    ];
    const groups = groupSheets(sheets);
    expect(groups.map((g) => [g.title, g.sheets.map((s) => s.id)])).toEqual([
      ["Process", ["BFD", "PFD"]],
      ["P&IDs", ["P-01", "P-02"]],
    ]);
  });

  it("leaves out empty groups", () => {
    expect(groupSheets([{ id: "P-01", file: "pid/P-01.xml", title: "" }]).map((g) => g.id)).toEqual(["pid"]);
    expect(groupSheets([])).toEqual([]);
  });
});

describe("stream table helpers", () => {
  it("formats values and compositions", () => {
    expect(formatValue({ value: 98000.0000001, unit: "kg/h", provenance: "given", stale: false })).toBe("98000 kg/h");
    expect(formatValue(null)).toBe("");
    const s = stream("S", {
      composition: { basis: "mole_fraction", values: { N2: 0.7812, O2: 0.2096 }, provenance: "assumed" },
    });
    expect(formatComposition(s)).toBe("mol: N2 0.7812, O2 0.2096");
  });

  it("marks balance errors before stale values", () => {
    expect(streamStatus(stream("S"))).toBe("ok");
    expect(streamStatus(stream("S", { stale: ["density"] }))).toBe("stale");
    expect(streamStatus(stream("S", { stale: ["density"], imbalance: ["SEP"] }))).toBe("error");
  });

  it("filters by text, BFD visibility and problems", () => {
    expect(filterStreams(table.streams, "mix").map((s) => s.id)).toEqual(["S1", "S2"]);
    expect(filterStreams(table.streams, "", "bfd").map((s) => s.id)).toEqual(["S1", "S2"]);
    const withProblem = [...table.streams, stream("S9", { imbalance: ["X"] })];
    expect(filterStreams(withProblem, "", "problems").map((s) => s.id)).toEqual(["S9"]);
  });

  it("explains balances", () => {
    expect(balanceDetail(table.balances[0]!)).toBe("in 1500 kg/h, out 1500 kg/h");
    expect(balanceDetail({ ...table.balances[0]!, status: "not-evaluable", missing: ["S13 flow"] })).toBe(
      "missing S13 flow",
    );
  });
});

describe("pickInfo", () => {
  it("lists the streams a BFD connection represents", () => {
    const info = pickInfo(table, "bfd", "S1");
    expect(info.kind).toBe("connection");
    expect(info.streams.map((s) => s.id)).toEqual(["S1"]);
  });

  it("gives a PFD stream's values, also internal ones", () => {
    const info = pickInfo(table, "pfd", "S6");
    expect(info.kind).toBe("stream");
    expect(info.streams[0]?.properties.flow?.value).toBe(1000);
  });

  it("gives a block's balance and its boundary streams", () => {
    const info = pickInfo(table, "bfd", "MIX");
    expect(info.kind).toBe("node");
    expect(info.balance?.status).toBe("ok");
    expect(info.streams.map((s) => s.id)).toEqual(["S1", "S2"]);
  });

  it("lists every stream an aggregated BFD connection represents, not just its own id", () => {
    const aggregated: StreamTable = {
      ...table,
      streams: [...table.streams, stream("S3", { from: "M1.side", to: "C1.feed2", from_block: "MIX", to_block: "SEP" })],
      bfd_connections: { S1: ["S1"], S2: ["S2", "S3"] },
      bfd_connections_from: "sheet",
    };
    const info = pickInfo(aggregated, "bfd", "S2");
    expect(info.kind).toBe("connection");
    expect(info.streams.map((s) => s.id)).toEqual(["S2", "S3"]);
    expect(bfdConnectionOf(aggregated, "S3")).toBe("S2");
    expect(bfdConnectionOf(aggregated, "S2")).toBe("S2");
    expect(bfdConnectionOf(aggregated, "S6")).toBeUndefined();
  });

  it("treats a boundary stream as its own connection without a connection map", () => {
    const old: StreamTable = { ...table, bfd_connections: {} };
    expect(pickInfo(old, "bfd", "S2").kind).toBe("connection");
    expect(pickInfo(old, "bfd", "S6").kind).toBe("unknown");
  });

  it("knows a step without a balance by its stream ends", () => {
    expect(pickInfo(table, "pfd", "C1").streams.map((s) => s.id)).toEqual(["S2", "S6"]);
    expect(pickInfo(table, "bfd", "Drawing_title").kind).toBe("unknown");
  });
});

describe("processSections", () => {
  it("makes one table per flowsheet section with nested values shortened", () => {
    const doc: YamlDoc = {
      kind: "flowsheet",
      schema: null,
      data: {
        schema: "cheme/process/v1",
        kind: "flowsheet",
        blocks: [{ id: "MIX", ports: [{ id: "in", direction: "in" }], links: [{ target: "equipment", ref: "M-101" }] }],
        streams: [{ id: "S1", from: "FEED.out", to: "MIX.in", state: { design: { flow: { value: 1 } } } }],
      },
    };
    const tables = processSections(doc)!;
    expect(tables.map((t) => t.key)).toEqual(["streams", "blocks"]);
    expect(tables[0]!.rows[0]!.state).toBe("design");
    expect(tables[1]!.rows[0]!.ports).toBe("in (in)");
    expect(tables[1]!.rows[0]!.links).toBe("equipment M-101");
  });

  it("is null for other kinds", () => {
    expect(processSections({ kind: "equipment", schema: null, data: { equipment: [] } })).toBeNull();
  });
});
