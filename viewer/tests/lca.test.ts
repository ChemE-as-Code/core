import { describe, expect, it } from "vitest";
import type { LcaReport } from "@/api";
import {
  allocationRows,
  compareContributions,
  compareTotals,
  impactsOf,
  intervalGeometry,
  sensitivityLabel,
  sourceHref,
  statisticsOf,
  statusClass,
  BASELINE,
  OTHER,
  bandPath,
  colourOf,
  contributionSankey,
  contributions,
  impactText,
  layoutSankey,
  lcaCsv,
  pyFixed4,
  scenarioBars,
  droppedIn,
  hasTotal,
  scenarioIds,
  total,
  verdictOf,
} from "@/lib/lca";
import lcaJson from "./fixtures/api/lca-asu.json";
import { LOW_GRID, withLowGrid } from "./helpers/lcaScenario";
import lcaCsvText from "./fixtures/api/lca-asu.csv?raw";

// `/api/lca` of the ASU: operation, construction, open background data (DESNZ 2026), no scenario;
// the scenario views are tested with a synthetic one (withLowGrid).
const report = lcaJson as unknown as LcaReport;
const scenarioReport = withLowGrid(report);
const GWP = "climate-change";

describe("lca report", () => {
  it("lists the scenarios baseline first, with their totals", () => {
    expect(scenarioIds(report)).toEqual([BASELINE]);
    expect(scenarioIds(scenarioReport)).toEqual([BASELINE, LOW_GRID]);
    expect(total(report, BASELINE, GWP)).toBeCloseTo(report.totals[GWP]!, 9);
    expect(total(scenarioReport, LOW_GRID, GWP)).toBeLessThan(total(report, BASELINE, GWP));
  });

  it("writes the CSV of cheme assess lca --csv byte for byte", () => {
    expect(lcaCsv(report)).toBe(lcaCsvText);
  });
});

describe("contributions", () => {
  it("sorts by magnitude, groups the rest as other, and the shares sum to 1", () => {
    const parts = contributions(report, BASELINE, GWP, 3);
    expect(parts.map((c) => c.key).slice(0, 2)).toEqual(["feed:POWER", "product:CW"]);
    // the rest, one "other" per phase
    const others = parts.filter((c) => c.key.startsWith(OTHER));
    expect(others.length).toBeGreaterThan(0);
    expect(parts.length).toBe(3 + others.length);
    expect(parts.reduce((s, c) => s + c.share, 0)).toBeCloseTo(1, 9);
    expect(parts.reduce((s, c) => s + c.value, 0)).toBeCloseTo(total(report, BASELINE, GWP), 9);
    expect(parts[0]!.label).toBe("Electric power (6.6 kV grid supply)");
    expect(new Set(others.map((c) => c.phase)).size).toBe(others.length);
  });

  it("keeps every contributor when there are few", () => {
    const all = contributions(report, BASELINE, GWP, 100);
    expect(all.some((c) => c.key === OTHER)).toBe(false);
    expect(all.length).toBe(new Set(report.impacts.filter((i) => i.scenario === BASELINE).map((i) => i.key)).size);
  });
});

describe("sankey", () => {
  const options = { width: 600, height: 300, nodeWidth: 10, gap: 8 };

  it("conserves the flow at every node and stays in the box", () => {
    const layout = contributionSankey(report, BASELINE, GWP, options);
    const kinds = layout.nodes.map((n) => n.kind);
    expect(kinds.filter((k) => k === "total")).toHaveLength(1);
    const phases = new Set(report.impacts.filter((i) => i.scenario === BASELINE && i.category === GWP).map((i) => i.phase));
    expect(kinds.filter((k) => k === "phase")).toHaveLength(phases.size);
    const totalNode = layout.nodes.find((n) => n.kind === "total")!;
    expect(totalNode.value).toBeCloseTo(total(report, BASELINE, GWP), 9);
    for (const node of layout.nodes) {
      expect(node.y).toBeGreaterThanOrEqual(-1e-9);
      expect(node.y + node.height).toBeLessThanOrEqual(options.height + 1e-9);
      const inWidth = layout.links.filter((l) => l.target === node.id).reduce((s, l) => s + l.width, 0);
      const outWidth = layout.links.filter((l) => l.source === node.id).reduce((s, l) => s + l.width, 0);
      expect(Math.max(inWidth, outWidth)).toBeCloseTo(node.height, 6);
    }
    expect(totalNode.x + totalNode.width).toBeCloseTo(options.width, 9);
  });

  it("stacks the bands without overlap at each node", () => {
    const layout = contributionSankey(report, BASELINE, GWP, options);
    const phase = layout.nodes.find((n) => n.id === "phase:operation")!;
    const arriving = layout.links.filter((l) => l.target === phase.id).sort((a, b) => a.y1 - b.y1);
    let edge = phase.y;
    for (const l of arriving) {
      expect(l.y1 - l.width / 2).toBeCloseTo(edge, 6);
      edge += l.width;
    }
  });

  it("draws a credit with its magnitude and marks it", () => {
    const layout = layoutSankey(
      [
        { id: "a", label: "A", column: 0, kind: "flow" },
        { id: "b", label: "B", column: 0, kind: "flow" },
        { id: "t", label: "T", column: 1, kind: "total" },
      ],
      [
        { source: "a", target: "t", value: 3, key: "a" },
        { source: "b", target: "t", value: -1, key: "b" },
      ],
      { width: 100, height: 40, gap: 0 },
    );
    const credit = layout.links.find((l) => l.key === "b")!;
    expect(credit.credit).toBe(true);
    expect(credit.width).toBeCloseTo(10, 9);
    expect(layout.nodes.find((n) => n.id === "t")!.value).toBe(2);
    expect(layout.links.map((l) => l.key)).toEqual(["a", "b"]);
  });

  it("writes a closed band path", () => {
    expect(bandPath(0, 10, 100, 20, 4)).toBe("M0,8 C50,8 50,18 100,18 L100,22 C50,22 50,12 0,12 Z");
  });
});

describe("scenario bars", () => {
  it("gives one bar per scenario with shared colours", () => {
    const bars = scenarioBars(scenarioReport, GWP, 3);
    expect(bars.bars.map((b) => b.scenario)).toEqual([BASELINE, LOW_GRID]);
    expect(bars.zero).toBe(0);
    expect(bars.keys[0]).toBe("feed:POWER");
    expect(bars.keys.at(-1)).toBe(OTHER);
    const [base, future] = bars.bars;
    expect(base!.segments.at(-1)!.to).toBeCloseTo(1, 9);
    expect(future!.segments.at(-1)!.to).toBeLessThan(0.5);
    expect(base!.segments.reduce((s, x) => s + x.value, 0)).toBeCloseTo(base!.total, 9);
    expect(colourOf("feed:POWER", bars.keys)).toBe(1);
    expect(colourOf(OTHER, bars.keys)).toBe(0);
  });

  it("puts credits left of zero", () => {
    const tiny: Pick<LcaReport, "impacts" | "inventory" | "scenarios" | "totals"> = {
      inventory: [],
      totals: { gwp: 2 },
      scenarios: { baseline: { gwp: 2 } },
      impacts: [
        { category: "gwp", key: "a", basis: "", quantity: 1, unit: "kg", factor: 3, value: 3, status: "", source: "", year: null, scenario: "baseline", phase: "operation" },
        { category: "gwp", key: "b", basis: "", quantity: 1, unit: "kg", factor: -1, value: -1, status: "", source: "", year: null, scenario: "baseline", phase: "operation" },
      ],
    };
    const bars = scenarioBars(tiny, "gwp");
    expect(bars.min).toBe(-1);
    expect(bars.zero).toBeCloseTo(0.25, 9);
    const credit = bars.bars[0]!.segments.find((s) => s.key === "b")!;
    expect([credit.from, credit.to]).toEqual([0, 0.25]);
  });
});

describe("scenario comparability (pre-release issue 172)", () => {
  const impact = (key: string, scenario: string, value: number) => ({
    category: "gwp", key, basis: "", quantity: 1, unit: "kg", factor: value, value, status: "", source: "", year: null, scenario, phase: "operation",
  });
  const report = {
    inventory: [],
    totals: { gwp: 11 },
    scenario_ids: ["baseline", "nl", "de"],
    scenarios: { baseline: { gwp: 11 }, nl: { gwp: 13 }, de: { gwp: 1 } },
    impacts: [impact("feed:POWER", "baseline", 10), impact("steel", "baseline", 1), impact("feed:POWER", "nl", 12), impact("steel", "nl", 1), impact("steel", "de", 1)],
    gaps: [{ category: "gwp", key: "feed:POWER", reason: "missing", quantity: 5, unit: "kWh", phase: "operation", scenario: "de", detail: "no DE factor" }],
  } as unknown as Pick<LcaReport, "impacts" | "inventory" | "scenarios" | "totals" | "gaps">;

  it("draws no bar for a scenario missing data the baseline has", () => {
    expect(droppedIn(report, "de", "gwp")).toEqual(["feed:POWER"]);
    expect(droppedIn(report, "nl", "gwp")).toEqual([]);
    expect(droppedIn(report, "baseline", "gwp")).toEqual([]);
    const bars = scenarioBars(report, "gwp");
    const de = bars.bars.find((b) => b.scenario === "de")!;
    expect(de.segments).toEqual([]);
    expect(de.dropped).toEqual(["feed:POWER"]);
    expect(bars.bars.find((b) => b.scenario === "nl")!.segments.length).toBeGreaterThan(0);
  });

  it("has no total where every contribution is a gap, and follows core's not_comparable", () => {
    const empty = {
      ...report,
      impacts: report.impacts.filter((i) => i.scenario !== "de"),
    };
    expect(hasTotal(empty, "de", "gwp")).toBe(false);
    expect(hasTotal(report, "nl", "gwp")).toBe(true);
    expect(scenarioBars(empty, "gwp").bars.find((b) => b.scenario === "de")!.none).toBe(true);
    const stated = { ...report, gaps: [], not_comparable: { nl: { gwp: ["feed:POWER"] } } };
    expect(droppedIn(stated, "nl", "gwp")).toEqual(["feed:POWER"]);
    expect(hasTotal(stated, "nl", "gwp")).toBe(false);
  });
});

describe("numbers", () => {
  it("formats impacts with four significant digits", () => {
    expect(impactText(132.598)).toBe("132.6");
    expect(impactText(0.000020818)).toBe("2.082e-5");
    expect(impactText(0)).toBe("0");
    expect(impactText(12345.67)).toBe("12,350");
  });
});

describe("sankey slots", () => {
  it("keeps a label slot per node and still fits the height", () => {
    const options = { width: 600, height: 800, nodeWidth: 10, gap: 6, slot: 30 };
    const layout = contributionSankey(report, BASELINE, GWP, options);
    const flows = layout.nodes.filter((n) => n.kind === "flow").sort((a, b) => a.y - b.y);
    for (let i = 1; i < flows.length; i++) {
      const prev = flows[i - 1]!;
      expect(flows[i]!.y - prev.y).toBeGreaterThanOrEqual(Math.max(prev.height, 30) + 6 - 1e-6);
    }
    const bottom = Math.max(...layout.nodes.map((n) => n.y + Math.max(n.height, 30)));
    expect(bottom).toBeLessThanOrEqual(options.height + 1e-6);
    // the largest flow still dominates
    expect(flows.find((n) => n.id === "flow:feed:POWER")!.height).toBeGreaterThan(100);
  });
});

describe("review fixes", () => {
  const impact = (scenario: string, key: string, value: number, phase = "operation") => ({
    category: "gwp", key, basis: "", quantity: 1, unit: "kg", factor: value, value, status: "", source: "", year: null, scenario, phase,
  });

  it("keeps core's scenario order for ids like 2030", () => {
    const parsed = JSON.parse('{"baseline":{},"high":{},"2030":{}}') as Record<string, Record<string, number>>;
    expect(scenarioIds({ scenarios: parsed, scenario_ids: ["baseline", "high", "2030"] })).toEqual(["baseline", "high", "2030"]);
    // older servers: the order the impacts name them in
    expect(scenarioIds({ scenarios: parsed, impacts: [impact("baseline", "a", 1), impact("high", "a", 1), impact("2030", "a", 1)] })).toEqual(["baseline", "high", "2030"]);
  });

  it("formats shares like Python: half to even, negative zero", () => {
    expect(pyFixed4(0.03125)).toBe("0.0312");
    expect(pyFixed4(1.78125)).toBe("1.7812");
    expect(pyFixed4(0.09375)).toBe("0.0938");
    expect(pyFixed4(-0)).toBe("-0.0000");
    expect(pyFixed4(-0.00001)).toBe("-0.0000");
    expect(pyFixed4(0.98765)).toBe("0.9877");
    expect(pyFixed4(1)).toBe("1.0000");
  });

  it("groups the rest per phase so the phase nodes are exact", () => {
    const impacts = Array.from({ length: 9 }, (_, i) => impact("baseline", `k${i}`, 10 - i, i % 2 ? "construction" : "operation"));
    const tiny = { impacts, inventory: [], functional_unit: "1 t X" };
    const parts = contributions(tiny, "baseline", "gwp", 3);
    expect(parts.filter((c) => c.key.startsWith("other")).map((c) => c.key).sort()).toEqual(["other:construction", "other:operation"]);
    const layout = contributionSankey(tiny, "baseline", "gwp", { width: 400, height: 300 }, 3);
    expect(layout.nodes.filter((n) => n.kind === "phase").map((n) => n.id).sort()).toEqual(["phase:construction", "phase:operation"]);
    const operation = layout.nodes.find((n) => n.id === "phase:operation")!;
    expect(operation.value).toBe(impacts.filter((i) => i.phase === "operation").reduce((s, i) => s + i.value, 0));
    expect(colourOf("other:construction", ["k0"])).toBe(0);
  });

  it("lays out tiny magnitudes at full size and filters non-finite values", () => {
    const nodes = [
      { id: "a", label: "A", column: 0, kind: "flow" },
      { id: "b", label: "B", column: 0, kind: "flow" },
      { id: "t", label: "T", column: 1, kind: "total" },
    ];
    for (const s of [1, 1e-9, 1e-15, 1e-30]) {
      const layout = layoutSankey(nodes, [{ source: "a", target: "t", value: 3 * s, key: "a" }, { source: "b", target: "t", value: s, key: "b" }], { width: 100, height: 240, gap: 0 });
      expect(layout.nodes.find((n) => n.id === "t")!.height).toBeCloseTo(240, 6);
    }
    const layout = layoutSankey(nodes, [{ source: "a", target: "t", value: Number.NaN, key: "a" }, { source: "b", target: "t", value: 1, key: "b" }], { width: 100, height: 100 });
    expect(layout.links.map((l) => l.key)).toEqual(["b"]);
  });

  it("grows when the label slots cannot fit", () => {
    const nodes = [...Array.from({ length: 10 }, (_, i) => ({ id: `n${i}`, label: "", column: 0, kind: "flow" })), { id: "t", label: "", column: 1, kind: "total" }];
    const links = nodes.slice(0, 10).map((n) => ({ source: n.id, target: "t", value: 1, key: n.id }));
    const layout = layoutSankey(nodes, links, { width: 100, height: 100, gap: 4, slot: 30 });
    expect(layout.height).toBe(10 * 30 + 9 * 4);
    expect(Math.min(...layout.nodes.map((n) => n.y))).toBeGreaterThanOrEqual(0);
  });
});

describe("allocation, uncertainty and revisions", () => {
  it("lists every allocation method relative to the one used", () => {
    const rows = allocationRows(report, GWP);
    const used = rows.find((r) => r.current)!;
    expect(used.method).toBe(report.allocation.method);
    expect(used.relative).toBe(1);
    expect(used.total).toBeCloseTo(total(report, BASELINE, GWP), 6);
    const none = rows.find((r) => r.method === "none")!;
    expect(none.share).toBe(1);
    expect(none.relative!).toBeGreaterThan(1);
    const shares = rows.find((r) => r.method === "shares")!;
    expect(shares.total).toBeNull();
    expect(shares.problem).toContain("no share");
  });

  it("places the 95 % interval, median and deterministic value on one axis", () => {
    const stats = statisticsOf(report, GWP)!;
    expect(stats.low).toBeLessThan(stats.median);
    expect(stats.median).toBeLessThan(stats.high);
    const g = intervalGeometry(stats);
    expect(g.min).toBe(0);
    expect(g.high).toBe(1);
    expect(g.low).toBeGreaterThan(0);
    expect(g.deterministic).toBeGreaterThan(g.low);
    expect(statisticsOf({ uncertainty: null }, GWP)).toBeNull();
  });

  it("names sensitivity inputs", () => {
    expect(sensitivityLabel(report, "amount:feed:POWER")).toBe("Amount: Electric power (6.6 kV grid supply)");
    expect(sensitivityLabel(report, "factor:electricity")).toBe("Factor: electricity");
  });

  it("compares two revisions by total and contributor", () => {
    const halved = {
      ...report,
      impacts: report.impacts.map((i) => (i.key === "feed:POWER" ? { ...i, value: i.value / 2 } : i)),
    } as LcaReport;
    halved.scenarios = { ...report.scenarios, baseline: { [GWP]: total(report, BASELINE, GWP) - impactsOf(report, BASELINE, GWP).filter((i) => i.key === "feed:POWER").reduce((s, i) => s + i.value / 2, 0) } };
    const totals = compareTotals(report, halved);
    expect(totals[0]!.delta).toBeGreaterThan(0);
    const contributions = compareContributions(report, halved, GWP);
    expect(contributions).toHaveLength(1);
    expect(contributions[0]!.key).toBe("feed:POWER");
    const power = contributions[0]!;
    expect(power.other).toBeCloseTo(power.value! / 2, 6);
    expect(power.delta).toBeCloseTo(power.value! / 2, 6);
  });
});

describe("revision comparison edge cases", () => {
  it("marks categories absent in one revision or in another unit", () => {
    const other = {
      ...report,
      categories: [{ id: "acid", title: "Acidification", unit: "mol H+-eq", method: "" }],
      scenarios: { baseline: { acid: 1 } },
    } as LcaReport;
    const rows = compareTotals(report, other);
    const mine = rows.find((r) => r.key === GWP)!;
    expect(mine.other).toBeNull();
    expect(mine.delta).toBeNull();
    expect(mine.note).toBe("absent in the other revision");
    const theirs = rows.find((r) => r.key === "acid")!;
    expect(theirs.value).toBeNull();
    expect(theirs.note).toBe("absent in this revision");
    const units = { ...report, categories: report.categories.map((c) => ({ ...c, unit: "t CO2-eq" })) } as LcaReport;
    expect(compareTotals(report, units)[0]!.note).toBe("unit there: t CO2-eq");
  });

  it("keeps the axis at 0 for a total below zero", () => {
    const g = intervalGeometry({ category: "x", deterministic: -5, mean: -5, median: -5, sd: 1, low: -8, high: -2, sensitivity: [] });
    expect(g.max).toBe(0);
    expect(g.low).toBe(0);
    expect(g.high).toBeLessThan(1);
  });
});

describe("coverage", () => {
  const gap = (over: Partial<import("@/api").LcaGap>) => ({
    category: "climate-change",
    key: "construction:pipe",
    reason: "missing",
    quantity: 0.0008,
    unit: "m",
    phase: "construction",
    scenario: "baseline",
    detail: "no open factor per m",
    ...over,
  });
  const report = {
    gaps: [
      gap({}),
      gap({ key: "emission:ETOH", reason: "elementary-uncharacterised", detail: "ipcc2021-gwp100" }),
      gap({ scenario: "alt", key: "feed:X", reason: "unmapped", detail: "" }),
    ],
  } as unknown as LcaReport;

  it("splits gaps from flows outside the method, per scenario", async () => {
    const { gapsOf, scenarioHasGaps } = await import("@/lib/lca");
    expect(gapsOf(report, "baseline", "climate-change").map((g) => g.key)).toEqual(["construction:pipe"]);
    expect(gapsOf(report, "baseline", "climate-change", true).map((g) => g.key)).toEqual(["emission:ETOH"]);
    expect(gapsOf(report, "alt", "climate-change").map((g) => g.key)).toEqual(["feed:X"]);
    expect(scenarioHasGaps(report, "baseline")).toBe(true);
    expect(scenarioHasGaps({ gaps: [report.gaps![1]!] } as LcaReport, "baseline")).toBe(false);
    // an older server: no gaps field
    expect(gapsOf({} as LcaReport, "baseline", "climate-change")).toEqual([]);
  });

  it("names the gaps of unknown amount", async () => {
    const { gapText } = await import("@/lib/lca");
    expect(gapText(gap({ key: "construction:cs < E-1", reason: "no-weight", quantity: null, unit: "", detail: "E-1 has no dimensions.weight" }))).toBe(
      "an equipment item of the construction has no weight: amount unknown (E-1 has no dimensions.weight)",
    );
  });

  it("says why", async () => {
    const { gapText } = await import("@/lib/lca");
    expect(gapText(report.gaps![0]!)).toBe("declared missing: no background available (no open factor per m)");
    expect(gapText(report.gaps![2]!)).toBe("no background in lca/lca.yaml");
  });

  it("the ASU fixture is a partial, publishable screening carbon footprint", () => {
    const asu = lcaJson as unknown as LcaReport;
    expect(asu.label).toBe("partial screening carbon footprint");
    expect(asu.publication?.publishable).toBe(true);
    expect(asu.sources?.map((s) => s.licence)).toEqual(["OGL-3.0"]);
  });
});

describe("sourceHref", () => {
  it("links absolute http(s) URLs only", () => {
    expect(sourceHref("https://www.gov.uk/x")).toBe("https://www.gov.uk/x");
    expect(sourceHref(" http://example.org/a b ")).toBe("http://example.org/a%20b");
    for (const unsafe of ["javascript:alert(1)", " JavaScript:alert(1)", "java\tscript:alert(1)", "java\nscript:alert(1)", "data:text/html,x", "vbscript:x", "//evil.example/x", "factors.yaml", ""]) {
      expect(sourceHref(unsafe), unsafe).toBeNull();
    }
    expect(sourceHref(undefined)).toBeNull();
  });
});

describe("statusClass", () => {
  it("flags proxies and estimates, not published values", () => {
    expect(statusClass("PROXY")).toBe("warning");
    expect(statusClass("ESTIMATE")).toBe("warning");
    expect(statusClass("PUBLISHED")).toBe("");
    expect(statusClass("")).toBe("");
  });
});

describe("comparison verdict (pre-release issue 306)", () => {
  const withVerdicts = (verdicts: Record<string, string>) =>
    ({ ...scenarioReport, comparability: Object.fromEntries(Object.entries(verdicts).map(([s, v]) => [s, { verdict: v, reasons: v === "not comparable" ? ["basis differs (direct+upstream / direct)"] : [] }])) }) as LcaReport;

  it("shows core's verdict and its reasons", () => {
    const r = withVerdicts({ baseline: "baseline", [LOW_GRID]: "not comparable" });
    expect(verdictOf(r, LOW_GRID, GWP)).toMatchObject({ kind: "not-comparable", label: "not comparable", badge: "fail", reasons: ["basis differs (direct+upstream / direct)"] });
    expect(verdictOf(r, BASELINE, GWP).kind).toBe("baseline");
    expect(verdictOf(withVerdicts({ [LOW_GRID]: "like-for-like" }), LOW_GRID, GWP).kind).toBe("like-for-like");
    expect(verdictOf(withVerdicts({ [LOW_GRID]: "proxy" }), LOW_GRID, GWP).badge).toBe("warning");
  });

  it("is never more favourable than the data allow", () => {
    // an older core gives no verdict: not assessed, never like-for-like
    expect(verdictOf(scenarioReport, LOW_GRID, GWP).kind).toBe("not-assessed");
    expect(verdictOf(withVerdicts({ [LOW_GRID]: "something-new" }), LOW_GRID, GWP).kind).toBe("not-assessed");
    // a total that does not stand (data the baseline has are missing) beats a like-for-like verdict
    const dropped = { ...withVerdicts({ [LOW_GRID]: "like-for-like" }), not_comparable: { [LOW_GRID]: { [GWP]: ["feed:POWER"] } } } as LcaReport;
    expect(verdictOf(dropped, LOW_GRID, GWP).kind).toBe("not-comparable");
  });
});
