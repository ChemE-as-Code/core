import { describe, expect, it } from "vitest";
import { createSlugger, inlineText, parseInline, parseMarkdown, safeHref } from "@/lib/markdown";
import { fragmentOf } from "@/lib/inPageLink";
import { resolveRepoPath } from "@/lib/paths";

describe("markdown", () => {
  it("parses headings, paragraphs, lists and code", () => {
    const blocks = parseMarkdown("# Title\n\nSome *text* and `code`.\n\n- a\n- b\n\n```py\nx = 1\n```\n");
    expect(blocks.map((b) => b.t)).toEqual(["heading", "paragraph", "list", "code"]);
  });

  it("keeps raw HTML as text", () => {
    const blocks = parseMarkdown("<script>alert(1)</script>");
    expect(blocks).toEqual([{ t: "paragraph", children: [{ t: "text", text: "<script>alert(1)</script>" }] }]);
  });

  it("drops unsafe link targets", () => {
    expect(safeHref("javascript:alert(1)")).toBeNull();
    expect(safeHref("https://example.org")).toBe("https://example.org");
    expect(safeHref("../pid/P-01.xml")).toBe("../pid/P-01.xml");
    expect(parseInline("[x](javascript:alert(1))")).toEqual([{ t: "text", text: "x" }, { t: "text", text: ")" }]);
  });

  it("parses tables", () => {
    const [table] = parseMarkdown("| a | b |\n|---|---|\n| 1 | 2 |\n");
    expect(table?.t).toBe("table");
  });
});

describe("resolveRepoPath", () => {
  it("resolves relative links inside the repo", () => {
    expect(resolveRepoPath("tasks/T1.md", "../pid/P-01.xml")).toBe("pid/P-01.xml");
    expect(resolveRepoPath("README.md", "./DESIGN.md#top")).toBe("DESIGN.md");
    expect(resolveRepoPath("a/b.md", "/plant.yaml")).toBe("plant.yaml");
  });
  it("refuses links leaving the repo", () => {
    expect(resolveRepoPath("README.md", "../secret")).toBeNull();
  });

  it("gives headings GitHub's ids: lower case, no punctuation, hyphens, numbered repeats", () => {
    const slug = createSlugger();
    expect(slug("Design basis")).toBe("design-basis");
    expect(slug("1. Scope & limits (draft)")).toBe("1-scope--limits-draft");
    expect(slug("Wärmeübertrager E-101")).toBe("wärmeübertrager-e-101");
    expect(slug("snake_case")).toBe("snake_case");
    expect(slug("Design basis")).toBe("design-basis-1");
    expect(slug("design-basis-1")).toBe("design-basis-1-1");
    expect(slug("Design basis")).toBe("design-basis-2");
    expect(createSlugger()("Design basis")).toBe("design-basis");
  });

  it("takes a heading's text without its markup", () => {
    expect(inlineText(parseInline("The `cheme` **design** [basis](x.md)"))).toBe("The cheme design basis");
  });

  it("reads in-page link targets", () => {
    expect(fragmentOf("#design-basis")).toBe("design-basis");
    expect(fragmentOf("#w%C3%A4rme")).toBe("wärme");
    expect(fragmentOf("#")).toBeNull();
    expect(fragmentOf("README.md#x")).toBeNull();
  });
});
