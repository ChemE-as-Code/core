import { describe, expect, it } from "vitest";
import type { IssuesReport } from "@/api";
import {
  blockingCurrent,
  disciplinesOf,
  filterIssues,
  groupByGate,
  newIssueButtons,
  newIssueUrl,
  NO_FILTER,
  objectTag,
  statusLabel,
  TYPE_LABEL,
} from "@/lib/issues";
// The real /api/issues of core's process-separation with issues: (scripts/regen-fixtures.py --only-issues).
import issuesJson from "./fixtures/api/issues-separation.json";

const report = issuesJson as unknown as IssuesReport;

describe("issues", () => {
  it("names the types and statuses as engineers do", () => {
    expect(TYPE_LABEL.tq).toBe("Technical query (TQ)");
    expect(TYPE_LABEL.hold).toBe("Engineering hold");
    expect(statusLabel("for-verification")).toBe("for verification");
  });

  it("groups the open items by the gate they must close before, in stage order, then no gate", () => {
    const open = filterIssues(report.issues, NO_FILTER);
    expect(open.map((i) => i.number)).toEqual([9, 8, 7, 6, 5, 3, 2, 1]);
    const groups = groupByGate(open, report.stages);
    // #9's mistyped gate:Basic is no stage: after the stages, before "no gate"
    expect(groups.map((g) => g.gate)).toEqual(["concept", "basic", "detail", "Basic", null]);
    expect(groups[0]!.issues.map((i) => i.number)).toEqual([8, 1]);
    expect(groups[1]!.issues.map((i) => i.number)).toEqual([3, 2]);
    // the closed #4 (gate concept) only with the toggle
    const all = groupByGate(filterIssues(report.issues, { ...NO_FILTER, closed: true }), report.stages);
    expect(all[0]!.issues.map((i) => i.number)).toEqual([8, 4, 1]);
  });

  it("filters by type, gate, discipline and status", () => {
    const numbers = (f: Partial<typeof NO_FILTER>) => filterIssues(report.issues, { ...NO_FILTER, ...f }).map((i) => i.number);
    expect(numbers({ type: "action" })).toEqual([8, 6, 3]);
    expect(numbers({ type: "action", closed: true })).toEqual([8, 6, 4, 3]);
    expect(numbers({ type: "untyped" })).toEqual([7]);
    expect(numbers({ gate: "none" })).toEqual([7, 6]);
    expect(numbers({ gate: "basic" })).toEqual([3, 2]);
    expect(numbers({ discipline: "process" })).toEqual([9, 5, 2, 1]);
    expect(numbers({ status: "for-verification" })).toEqual([1]);
    expect(numbers({ status: "closed", closed: true })).toEqual([4]);
    expect(disciplinesOf(report.issues)).toEqual(["control", "mechanical", "process", "safety"]);
  });

  it("counts the open items blocking the current stage's gate", () => {
    expect(blockingCurrent(report)).toEqual([9, 8, 3, 2, 1]);
    expect(blockingCurrent({ ...report, stage: null })).toBeNull();
  });

  it("links a new issue with the References field filled in", () => {
    const url = newIssueUrl(report, { refs: "P-01 PIC-104" })!;
    expect(url.startsWith(report.new.action!)).toBe(true);
    expect(url.endsWith("&refs=P-01%20PIC-104")).toBe(true);
    expect(newIssueUrl(report, { type: "tq" })).toBe(report.new.tq);
    const choose = { new: { choose: "https://github.com/o/r/issues/new/choose" } };
    expect(newIssueUrl(choose, { refs: "P-01 P-101" })).toBe("https://github.com/o/r/issues/new/choose?refs=P-01%20P-101");
    expect(newIssueUrl({ new: {} })).toBeNull();
    expect(newIssueUrl(null)).toBeNull();
    expect(newIssueButtons(report).map((b) => b.label)).toEqual([
      "New action item",
      "New engineering hold",
      "New technical query (TQ)",
      "New design change",
    ]);
    expect(newIssueButtons(choose).map((b) => b.key)).toEqual(["choose"]);
  });

  it("reads a picked object's tag", () => {
    expect(objectTag({ id: "Pump1", texts: ["P-101"] })).toBe("P-101");
    expect(objectTag({ id: "Inst_LIA4107", texts: ["LIA", "4107"] })).toBe("LIA-4107");
    expect(objectTag({ id: "Pump1", texts: ["P-101"] }, "P101")).toBe("P101");
    expect(objectTag({ id: "Line7", texts: ["feed line"] })).toBe("Line7");
  });
});
