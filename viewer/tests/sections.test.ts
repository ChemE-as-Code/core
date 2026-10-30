import { describe, expect, it } from "vitest";
import { sectionId, sectionLabel } from "@/lib/sections";

describe("sectionLabel", () => {
  it("prefers the aria-label, else the heading up to its count", () => {
    expect(sectionLabel("Cost of production", "Cost of production per unit of GOXP")).toBe("Cost of production");
    expect(sectionLabel(null, "Loops 33 reviewed")).toBe("Loops");
    expect(sectionLabel("", "  Calculation maturity   levels (4) ")).toBe("Calculation maturity levels");
    expect(sectionLabel(null, "A heading that goes on and on and on, far past the width of a chip")).toHaveLength(40);
  });
});

describe("sectionId", () => {
  it("slugs the name and keeps ids unique", () => {
    expect(sectionId("Cause & effect", new Set())).toBe("sec-cause-effect");
    expect(sectionId("Findings", new Set(["sec-findings"]))).toBe("sec-findings-2");
    expect(sectionId("—", new Set())).toBe("sec-section");
  });
});
