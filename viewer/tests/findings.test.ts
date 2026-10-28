import { describe, expect, it } from "vitest";
import type { Finding, ImpactReport, LineRoute } from "@/api";
import { countLevels, matchesQuery } from "@/lib/findings";
import { lineRouteSummary } from "@/lib/layoutScene";
import impactJson from "./fixtures/api/impact.json";

const impact = impactJson as unknown as ImpactReport;

function finding(over: Partial<Finding> = {}): Finding {
  return { file: "pid/P-01.xml", level: "warning", rule: "cheme.x", message: "m", line: null, ids: [], hint: "", ...over };
}

describe("matchesQuery", () => {
  it("matches file, rule, message, hint and ids, ignoring case and surrounding blanks", () => {
    const [bfd] = impact.findings;
    expect(matchesQuery(bfd!, "  ")).toBe(true);
    expect(matchesQuery(bfd!, "BFD.XML")).toBe(true);
    expect(matchesQuery(bfd!, "review-needed")).toBe(true);
    expect(matchesQuery(bfd!, "rebuild with")).toBe(true);
    expect(matchesQuery(finding({ ids: ["P-101"] }), "p-101")).toBe(true);
    expect(matchesQuery(bfd!, "P-101")).toBe(false);
  });
});

describe("countLevels", () => {
  it("counts each level and ignores unknown ones", () => {
    const findings = [finding({ level: "error" }), finding(), finding(), finding({ level: "fatal" as Finding["level"] })];
    expect(countLevels(findings)).toEqual({ error: 1, warning: 2, info: 0 });
    expect(countLevels(impact.findings)).toEqual({ error: 0, warning: 0, info: 2 });
  });
});

describe("lineRouteSummary", () => {
  const route: LineRoute = {
    number: "47123",
    from: "H1007/N2",
    to: "T4750/N1",
    from_point: [29, 30],
    to_point: [52.5, 24],
    distance: 20.4,
    length_est: 32.1,
    racks: ["PR-1"],
    finding: "cheme.layout-line-length",
  };

  it("gives the distance and the estimate along the racks", () => {
    expect(lineRouteSummary(route)).toBe("20.4 m apart, about 32.1 m along PR-1");
    expect(lineRouteSummary({ ...route, length_est: null, racks: [], finding: null })).toBe("20.4 m apart");
  });

  it("says why there is no route", () => {
    const unplaced = { ...route, from_point: null, distance: null, length_est: null, racks: [] };
    expect(lineRouteSummary({ ...unplaced, finding: null })).toBe("ends not placed");
    expect(lineRouteSummary({ ...unplaced, finding: "cheme.layout-line-unrouted" })).toBe("route not checked");
  });
});
