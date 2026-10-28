/**
 * The material take-off page's pure parts: grouping, filtering and the CSV downloads, which must
 * be the files `cheme assess mto --csv` and `assess estimate --csv` write (from core, see
 * fixtures/README.md).
 */
import { describe, expect, it } from "vitest";
import type { MtoReport } from "@/api";
import { CATEGORIES, csvCell, dnText, estimateCsv, groupRows, money, mtoCsv, pyG, rowMatches } from "@/lib/mto";
import mtoAsuJson from "./fixtures/api/mto-asu.json";
import mtoAsuCsv from "./fixtures/api/mto-asu.csv?raw";
import estimateAsuCsv from "./fixtures/api/estimate-asu.csv?raw";

const asu = mtoAsuJson as unknown as MtoReport;

describe("CSV as core writes it", () => {
  it("formats numbers like Python's :g", () => {
    expect(pyG(4446.657)).toBe("4446.66");
    expect(pyG(15.159)).toBe("15.159");
    expect(pyG(2)).toBe("2");
    expect(pyG(100)).toBe("100");
    expect(pyG(0.5)).toBe("0.5");
    expect(pyG(0.0001)).toBe("0.0001");
    expect(pyG(0.00001)).toBe("1e-05");
    expect(pyG(1234567)).toBe("1.23457e+06");
    expect(pyG(999999.5)).toBe("1e+06");
    expect(pyG(-3.25)).toBe("-3.25");
    expect(pyG(0)).toBe("0");
  });

  it("quotes like Python's csv module", () => {
    expect(csvCell("plain")).toBe("plain");
    expect(csvCell("a, b")).toBe('"a, b"');
    expect(csvCell('say "x"')).toBe('"say ""x"""');
  });

  it("downloads the take-off and the estimate byte for byte as cheme-as-code writes them", () => {
    expect(mtoCsv(asu.rows)).toBe(mtoAsuCsv);
    expect(estimateCsv(asu.estimate!.lines)).toBe(estimateAsuCsv);
  });
});

describe("the take-off tables", () => {
  it("groups the rows by category in core's order, with totals per unit", () => {
    const groups = groupRows(asu.rows);
    const order = CATEGORIES.map(([c]) => c);
    expect(groups.map((g) => g.category)).toEqual(order.filter((c) => asu.rows.some((r) => r.category === c)));
    for (const g of groups) {
      expect(g.rows.every((r) => r.category === g.category)).toBe(true);
      for (const [unit, total] of Object.entries(g.totals)) expect(total).toBeCloseTo(asu.totals[g.category]![unit]!, 2);
    }
    expect(groups.find((g) => g.category === "steel")?.title).toBe("Structural steel");
    // An unknown category comes last, by its own name.
    const odd = groupRows([...asu.rows.slice(0, 2), { ...asu.rows[0]!, category: "cable", key: "x" }]);
    expect(odd.map((g) => g.category)).toEqual(["pipe", "cable"]);
  });

  it("filters rows by any of their words", () => {
    const pipe = asu.rows.find((r) => r.category === "pipe" && r.spec.includes("cold"))!;
    expect(rowMatches(pipe, "")).toBe(true);
    expect(rowMatches(pipe, `DN${pipe.dn} ${pipe.class}`)).toBe(true);
    expect(rowMatches(pipe, "cold")).toBe(true);
    expect(rowMatches(pipe, "HEB300")).toBe(false);
    const steel = asu.rows.find((r) => r.category === "steel")!;
    expect(rowMatches(steel, steel.item.toLowerCase())).toBe(true);
  });

  it("writes DNs and money for people", () => {
    expect(dnText({ dn: 100, dn2: null })).toBe("DN 100");
    expect(dnText({ dn: 100, dn2: 50 })).toBe("DN 100 x 50");
    expect(dnText({ dn: null, dn2: null })).toBe("");
    expect(money(34676.33, "EUR")).toBe("34,676.33 EUR");
    expect(money(2)).toBe("2.00");
    expect(money(null)).toBe("");
  });
});
