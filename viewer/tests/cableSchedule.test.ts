/**
 * The cable schedule beside the layout (`src/lib/studies.ts`): the ASU's committed
 * `electrical/cable-schedule.csv` (`cheme layout cables --write`) and small hand-made cases.
 */
import { describe, expect, it } from "vitest";
import { cableMatches, cableTotals, CABLE_COLUMNS, parseCableSchedule, sortCables } from "@/lib/studies";
import scheduleCsv from "./fixtures/api/cable-schedule-asu.csv?raw";
import layoutJson from "./fixtures/layout-asu.json";

const rows = parseCableSchedule(scheduleCsv);

describe("parsing", () => {
  it("reads every cable of the ASU, one per model cable", () => {
    expect(rows).toHaveLength(130);
    const tags = new Set((layoutJson as unknown as { model: { cables: { tag: string }[] } }).model.cables.map((c) => c.tag));
    expect(rows.every((r) => tags.has(r.tag))).toBe(true);
    const e2101 = rows.find((r) => r.tag === "C-E-2101")!;
    expect(e2101).toMatchObject({
      system: "power",
      kind: "feeder",
      from: "MCC-1",
      to: "E-2101",
      size: "3 x 4C x 300 mm2",
      od_mm: 71,
      voltage_v: 690,
      power_kw: 1000,
      current_a: 1070,
      pairs: null,
      route_length_m: 103.5,
      length_m: 112,
      review_needed: false,
    });
    expect(e2101.trays).toEqual(["PT-MCC-1", "PT-PR1-1", "PT-PR1-2", "PT-PR1-3", "PT-E-2101"]);
    // a field cable has no trays (direct to its junction box) and no load
    const field = rows.find((r) => r.kind === "field")!;
    expect(field.trays).toEqual([]);
    expect(field.voltage_v).toBeNull();
  });

  it("reads by header, quoted cells, review flags and CRLF", () => {
    const text = 'kind,tag,review_needed,size,length_m\r\nmotor,C-1,yes,"4C x 2.5 mm2, armoured",12.5\r\nfield,IC-2,,1 pr x 1.5 mm2,\r\n';
    const [a, b] = parseCableSchedule(text);
    expect(a).toMatchObject({ tag: "C-1", kind: "motor", review_needed: true, size: "4C x 2.5 mm2, armoured", length_m: 12.5, trays: [], system: "" });
    expect(b).toMatchObject({ tag: "IC-2", review_needed: false, length_m: null });
    expect(() => parseCableSchedule("a,b\n1,2\n")).toThrow(/no tag column/);
    expect(CABLE_COLUMNS[0]).toBe("tag");
  });
});

describe("filter, sort, totals", () => {
  it("filters by any word", () => {
    expect(rows.filter((r) => cableMatches(r, "power")).length).toBe(11);
    expect(rows.filter((r) => cableMatches(r, "PT-PR2-1")).every((r) => r.trays.includes("PT-PR2-1"))).toBe(true);
    expect(rows.filter((r) => cableMatches(r, "multipair")).length).toBe(9);
    expect(cableMatches({ ...rows[0]!, review_needed: true }, "review")).toBe(true);
    expect(cableMatches(rows[0]!, "review")).toBe(false);
  });

  it("sorts numbers with empty cells last, text naturally", () => {
    const byLength = sortCables(rows, "length_m", true);
    expect(byLength[0]!.length_m).toBe(Math.max(...rows.map((r) => r.length_m ?? 0)));
    const byPower = sortCables(rows, "power_kw");
    expect(byPower[0]!.power_kw).toBe(Math.min(...rows.filter((r) => r.power_kw !== null).map((r) => r.power_kw!)));
    expect(byPower.at(-1)!.power_kw).toBeNull();
    expect(sortCables(rows, "power_kw", true).at(-1)!.power_kw).toBeNull();
    const t = (tag: string) => ({ ...rows[0]!, tag });
    expect(sortCables([t("C-10"), t("C-2")], "tag").map((r) => r.tag)).toEqual(["C-2", "C-10"]);
    const flagged = sortCables([rows[0]!, { ...rows[1]!, review_needed: true }], "review_needed");
    expect(flagged[0]!.review_needed).toBe(true);
  });

  it("totals the lengths per system", () => {
    const totals = cableTotals(rows);
    expect(totals.count).toBe(130);
    expect(totals.review).toBe(0);
    expect(totals.systems.power!.count + totals.systems.instrument!.count).toBe(130);
    const sum = rows.reduce((a, r) => a + (r.length_m ?? 0), 0);
    expect(totals.length_m).toBeCloseTo(sum, 1);
  });
});
