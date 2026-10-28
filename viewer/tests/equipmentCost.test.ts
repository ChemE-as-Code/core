/**
 * The equipment estimate's pure parts (`src/lib/equipmentCost.ts`) against the ASU's
 * `cheme assess equipment --json` (fixtures/README.md): statuses, sums per status, the AACE range.
 */
import { describe, expect, it } from "vitest";
import type { EquipmentCostLine, EquipmentEstimate } from "@/api";
import { accuracyBand, costLineMatches, costStatus, parseAccuracy, sizeAssumed, statusSums, wholeMoney } from "@/lib/equipmentCost";
import estimateJson from "./fixtures/api/equipment-estimate-asu.json";

const asu = estimateJson as unknown as EquipmentEstimate;
const line = (over: Partial<EquipmentCostLine>): EquipmentCostLine => ({
  tag: "P-1",
  type: "CentrifugalPump",
  correlation: "pump_centrifugal",
  size: 10,
  unit: "kW",
  size_source: "",
  cp0_base: 1000,
  fp: null,
  fm: null,
  fbm: null,
  cbm_base: null,
  index_ratio: 2,
  purchased: 2000,
  bare_module: null,
  status: "purchased only",
  notes: "",
  ...over,
});

describe("statuses", () => {
  it("reads core's status texts", () => {
    expect(costStatus({ status: "bare module" })).toBe("bare");
    expect(costStatus({ status: "purchased only" })).toBe("purchased");
    expect(costStatus({ status: "project cost" })).toBe("own");
    expect(costStatus({ status: "excluded: by the vendor package" })).toBe("excluded");
    expect(costStatus({ status: "not covered" })).toBe("uncovered");
  });

  it("sums per status as core's totals do (the ASU)", () => {
    const sums = statusSums(asu.lines);
    expect(sums.map((s) => [s.status, s.count])).toEqual([
      ["bare", asu.totals.bare_module_items],
      ["purchased", asu.totals.purchased_only],
      ["uncovered", asu.totals.not_covered],
    ]);
    expect(sums.reduce((a, s) => a + s.count, 0)).toBe(asu.totals.items);
    // Core rounds the sum of all lines; the per-status sums add up to it within rounding.
    expect(Math.abs(sums.reduce((a, s) => a + s.purchased, 0) - asu.totals.purchased)).toBeLessThanOrEqual(1);
    expect(sums.find((s) => s.status === "bare")!.bareModule).toBe(asu.totals.bare_module);
    expect(sums.find((s) => s.status === "uncovered")!.purchased).toBe(0);
  });

  it("filters by tag, class, correlation, status and notes", () => {
    const l = line({ notes: "no material factor for 'SS / bronze'" });
    expect(costLineMatches(l, "")).toBe(true);
    expect(costLineMatches(l, "p-1 centrifugal")).toBe(true);
    expect(costLineMatches(l, "purchased bronze")).toBe(true);
    expect(costLineMatches(l, "compressor")).toBe(false);
    expect(asu.lines.filter((x) => costLineMatches(x, "not covered")).length).toBe(asu.totals.not_covered);
  });

  it("marks assumed and draft sizes", () => {
    expect(sizeAssumed("datasheet type_specific.area_m2 (ASSUMED: from the duty)")).toBe(true);
    expect(sizeAssumed("draft datasheet type_specific.volume_m3")).toBe(true);
    expect(sizeAssumed("cost basis (vendor data sheet)")).toBe(false);
  });
});

describe("the AACE accuracy range", () => {
  it("reads core's range texts", () => {
    expect(parseAccuracy("-20 % to -50 %")).toEqual([-20, -50]);
    expect(parseAccuracy("+30 % to +100 %")).toEqual([30, 100]);
    expect(parseAccuracy("−5 % to −15 %")).toEqual([-5, -15]);
    expect(parseAccuracy("+10 %")).toEqual([10, 10]);
    expect(parseAccuracy("unknown")).toBeNull();
    expect(parseAccuracy(undefined)).toBeNull();
  });

  it("puts the class's range on a total", () => {
    expect(accuracyBand(1000, { low: "-20 % to -50 %", high: "+30 % to +100 %" })).toEqual({ low: [500, 800], high: [1300, 2000] });
    expect(accuracyBand(1000, { low: "?", high: "+30 %" })).toBeNull();
    expect(asu.estimate_class).toBe(5);
    const band = accuracyBand(asu.totals.bare_module, asu.accuracy)!;
    expect(band.low[0]).toBe(Math.round(asu.totals.bare_module * 0.5));
    expect(band.high[1]).toBe(Math.round(asu.totals.bare_module * 2));
  });

  it("writes whole money", () => {
    expect(wholeMoney(4002556.4, "USD")).toBe("4,002,556 USD");
    expect(wholeMoney(null)).toBe("");
  });
});
