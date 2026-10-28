import { describe, expect, it } from "vitest";
import { keepStickyQuery, pageTitle } from "@/router";

describe("keepStickyQuery", () => {
  it("carries embed and theme over to a link that lacks them", () => {
    expect(keepStickyQuery({ rev: "abc" }, { embed: "1", theme: "dark", rev: "old" })).toEqual({
      rev: "abc",
      embed: "1",
      theme: "dark",
    });
  });

  it("returns null when nothing is missing, so the guard does not redirect again", () => {
    expect(keepStickyQuery({ embed: "1", theme: "dark" }, { embed: "1", theme: "dark" })).toBeNull();
    expect(keepStickyQuery({ rev: "abc" }, { rev: "old" })).toBeNull();
  });

  it("keeps a value the link sets itself", () => {
    expect(keepStickyQuery({ theme: "light" }, { theme: "dark" })).toBeNull();
  });
});

describe("pageTitle", () => {
  it("names the page, the plant and the viewer", () => {
    expect(pageTitle({ name: "streams", params: {} }, "ASU")).toBe("Stream table – ASU – cheme-as-code viewer");
    expect(pageTitle({ name: "pid", params: { path: ["pid", "P-01.xml"] } }, "ASU")).toBe("P&ID pid/P-01.xml – ASU – cheme-as-code viewer");
    expect(pageTitle({ name: "datasheet", params: { tag: "C-101" } }, "ASU")).toBe("Datasheet C-101 – ASU – cheme-as-code viewer");
    expect(pageTitle({ name: "file", params: { path: ["README.md"] } }, null)).toBe("README.md – cheme-as-code viewer");
  });
});
