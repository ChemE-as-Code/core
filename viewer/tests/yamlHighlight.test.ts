import { describe, expect, it } from "vitest";
import { highlightYaml, type YamlToken } from "@/lib/yamlHighlight";

const typed = (tokens: YamlToken[]) => tokens.filter((t) => t.text.trim()).map((t) => [t.type, t.text.trim()]);

describe("highlightYaml", () => {
  it("keeps every character: tokens join back to the line", () => {
    const text = [
      "# Equipment list",
      "---",
      "items:",
      '  - tag: "P-4711A"   # duty pump',
      "    dn: 80",
      "    spare: true",
      "    notes: |",
      "      Line one # not a comment",
      "      key: not a key",
      "    flow: {a: 1, b: [x, 'y']}",
      "    ref: *base",
      "    <<: &base !custom value",
      "it's: 'it''s'",
      "\tweird \u0000 ‮ <script>alert(1)</script>",
      "",
    ].join("\n");
    const lines = highlightYaml(text);
    expect(lines.map((tokens) => tokens.map((t) => t.text).join(""))).toEqual(text.split("\n"));
  });

  it("types keys, scalars, comments and punctuation", () => {
    const [comment, doc, items, entry, dn, spare] = highlightYaml(
      '# list\n---\nitems:\n  - tag: "P-1"  # duty\n    dn: 80\n    spare: null\n',
    );
    expect(typed(comment!)).toEqual([["comment", "# list"]]);
    expect(typed(doc!)).toEqual([["document", "---"]]);
    expect(typed(items!)).toEqual([["key", "items"], ["punct", ":"]]);
    expect(typed(entry!)).toEqual([
      ["punct", "-"],
      ["key", "tag"],
      ["punct", ":"],
      ["string", '"P-1"'],
      ["comment", "# duty"],
    ]);
    expect(typed(dn!)).toEqual([["key", "dn"], ["punct", ":"], ["number", "80"]]);
    expect(typed(spare!)).toEqual([["key", "spare"], ["punct", ":"], ["literal", "null"]]);
  });

  it("does not take a # inside a value or a quoted string for a comment", () => {
    expect(typed(highlightYaml("url: http://x/#frag")[0]!)).toEqual([
      ["key", "url"],
      ["punct", ":"],
      ["plain", "http://x/#frag"],
    ]);
    expect(typed(highlightYaml("a: 'x # y'")[0]!)).toEqual([
      ["key", "a"],
      ["punct", ":"],
      ["string", "'x # y'"],
    ]);
  });

  it("treats the more-indented lines of a block scalar as string content", () => {
    const lines = highlightYaml("note: >-\n  key: no\n  # no\n\nnext: 1\n- |\n  a: b\nlast: 2");
    expect(typed(lines[0]!)).toEqual([["key", "note"], ["punct", ":"], ["punct", ">-"]]);
    expect(lines[1]).toEqual([{ type: "string", text: "  key: no" }]);
    expect(lines[2]).toEqual([{ type: "string", text: "  # no" }]);
    expect(typed(lines[4]!)).toEqual([["key", "next"], ["punct", ":"], ["number", "1"]]);
    expect(lines[6]).toEqual([{ type: "string", text: "  a: b" }]);
    expect(typed(lines[7]!)).toEqual([["key", "last"], ["punct", ":"], ["number", "2"]]);
  });

  it("marks anchors, aliases, tags and flow collections", () => {
    expect(typed(highlightYaml("a: &x !t v")[0]!)).toEqual([
      ["key", "a"],
      ["punct", ":"],
      ["anchor", "&x"],
      ["tag", "!t"],
      ["plain", "v"],
    ]);
    expect(typed(highlightYaml("b: {k: 1, l: [*x, 2.5]}")[0]!)).toEqual([
      ["key", "b"],
      ["punct", ":"],
      ["punct", "{"],
      ["key", "k"],
      ["punct", ":"],
      ["number", "1"],
      ["punct", ","],
      ["key", "l"],
      ["punct", ":"],
      ["punct", "["],
      ["anchor", "*x"],
      ["punct", ","],
      ["number", "2.5"],
      ["punct", "]}"], // adjacent tokens of one type are merged
    ]);
  });

  it("keeps commas, brackets and colons of a block plain scalar in the scalar", () => {
    expect(typed(highlightYaml("desc: Pump, centrifugal [main]")[0]!)).toEqual([
      ["key", "desc"],
      ["punct", ":"],
      ["plain", "Pump, centrifugal [main]"],
    ]);
    expect(typed(highlightYaml("- note: a: b, {c} # see spec")[0]!)).toEqual([
      ["punct", "-"],
      ["key", "note"],
      ["punct", ":"],
      ["plain", "a: b, {c}"],
      ["comment", "# see spec"],
    ]);
    // A flow collection that closes leaves the rest of the line to block context.
    expect(typed(highlightYaml("x: [1, 2]")[0]!)).toEqual([
      ["key", "x"],
      ["punct", ":"],
      ["punct", "["],
      ["number", "1"],
      ["punct", ","],
      ["number", "2"],
      ["punct", "]"],
    ]);
  });

  it("produces only text tokens: markup stays text", () => {
    const tokens = highlightYaml('x: "<img src=x onerror=alert(1)>"').flat();
    expect(tokens.map((t) => t.text).join("")).toContain("<img src=x onerror=alert(1)>");
    for (const token of tokens) expect(Object.keys(token).sort()).toEqual(["text", "type"]);
  });
});
