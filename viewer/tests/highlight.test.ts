import { describe, expect, it } from "vitest";
import { HIGHLIGHT_COLOURS, cssString, highlightCss, selectionCss } from "@/lib/highlight";

describe("cssString", () => {
  it("leaves ordinary ids alone", () => {
    expect(cssString("Tank-1_a.b")).toBe("Tank-1_a.b");
  });
  it("escapes quotes, backslashes, control characters and angle brackets", () => {
    expect(cssString('a"b')).toBe('a\\"b');
    expect(cssString("a\\b")).toBe("a\\\\b");
    expect(cssString("a\nb")).toBe("a\\a b");
    expect(cssString("</style>")).toBe("\\3c /style\\3e ");
  });
});

describe("highlightCss", () => {
  it("colours each highlighted id inside its pane, like cheme diff", () => {
    const css = highlightCss("diff-new", { Tank1: "added", Pipe2: "modified" });
    const lines = css.split("\n");
    expect(lines).toHaveLength(2);
    // Sorted by id.
    expect(lines[0]).toContain('[id="diff-new"] [id="Pipe2"] *{stroke:#e08a00!important;stroke-width:0.8!important}');
    expect(lines[0]).toContain('[id="diff-new"] [id="Pipe2"] text{fill:#e08a00!important');
    expect(lines[1]).toContain(`[id="Tank1"] *{stroke:${HIGHLIGHT_COLOURS.added}`);
  });

  it("uses the removed colour", () => {
    expect(highlightCss("old", { X: "removed" })).toContain("#d0312d");
  });

  it("ignores unknown kinds and is empty without highlights", () => {
    expect(highlightCss("p", {})).toBe("");
    expect(highlightCss("p", { X: "exploded", Y: "toString" })).toBe("");
  });

  it("cannot be broken out of with a hostile id", () => {
    const css = highlightCss("p", { '"]{}</style><script>alert(1)</script>': "added" });
    expect(css).not.toContain("</style>");
    expect(css).not.toContain("<script>");
    expect(css).toContain('[id="\\"]{}\\3c /style\\3e ');
  });
});

describe("selectionCss", () => {
  it("is empty without a selection", () => {
    expect(selectionCss("p", null)).toBe("");
  });
  it("targets the selected id in the pane", () => {
    expect(selectionCss("p", "Tank1")).toMatch(/^\[id="p"\] \[id="Tank1"\]\{/);
  });
});
