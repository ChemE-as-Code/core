import { describe, expect, it } from "vitest";
import type { ControlFile, Finding } from "@/api";
import { countsText, fileStatus, findingsOf, statusTone, worstLevel } from "@/lib/control";

describe("control records", () => {
  it("reads a review status as a badge tone", () => {
    expect(statusTone("accepted")).toBe("pass");
    expect(statusTone("reviewed")).toBe("info");
    expect(statusTone("drafted")).toBe("warning");
  });

  it("counts findings by level, worst first", () => {
    expect(countsText({ error: 0, warning: 1, info: 3 })).toBe("1 warning, 3 info");
    expect(countsText({ error: 0, warning: 0, info: 0 })).toBe("");
    expect(worstLevel({ error: 0, warning: 1, info: 3 })).toBe("warning");
    expect(worstLevel({ error: 0, warning: 0, info: 0 })).toBeNull();
  });

  it("finds a file's status and findings", () => {
    const files: ControlFile[] = [
      { path: "control/loops.yaml", kind: "loops", status: "drafted", detail: "no review record covers it", record: null },
    ];
    expect(fileStatus(files, "control/loops.yaml")?.status).toBe("drafted");
    expect(fileStatus(files, "control/sequences.yaml")).toBeUndefined();
    const finding = { file: "control/loops.yaml", level: "info", rule: "cheme.control-incomplete" } as Finding;
    expect(findingsOf([finding], "control/loops.yaml")).toEqual([finding]);
    expect(findingsOf([finding], "process/narrative.md")).toEqual([]);
  });
});
