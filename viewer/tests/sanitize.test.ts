import { describe, expect, it } from "vitest";
import { SCOPE_ATTR, sanitizeSvg } from "@/lib/sanitize";

const wrap = (body: string, attrs = 'width="420" height="297" viewBox="0 0 420 297"') =>
  `<svg xmlns="http://www.w3.org/2000/svg" xmlns:xlink="http://www.w3.org/1999/xlink" ${attrs}>${body}</svg>`;

describe("sanitizeSvg", () => {
  it("keeps drawing content and ids", () => {
    const { markup, width, height } = sanitizeSvg(wrap('<g id="Tank1" class="representation-group"><polyline points="0,0 1,1"/><text>T-1</text></g>'));
    expect(markup).toContain('id="Tank1"');
    expect(markup).toContain("<polyline");
    expect(markup).toContain("T-1");
    expect(width).toBe(420);
    expect(height).toBe(297);
  });

  it("removes script elements, also nested ones", () => {
    const { markup } = sanitizeSvg(wrap('<script>alert(1)</script><g id="a"><script type="text/javascript">alert(2)</script></g>'));
    expect(markup).not.toMatch(/script/i);
    expect(markup).toContain('id="a"');
  });

  it("removes on* event handler attributes", () => {
    const { markup } = sanitizeSvg(wrap('<g id="a" onclick="alert(1)" ONLOAD="x()"><rect onmouseover="y()" width="1" height="1"/></g>', 'viewBox="0 0 1 1" onload="alert(1)"'));
    expect(markup).not.toMatch(/\son\w+=/i);
    expect(markup).toContain("<rect");
  });

  it("removes foreignObject, animation and javascript: links", () => {
    const { markup } = sanitizeSvg(
      wrap(
        '<foreignObject><div xmlns="http://www.w3.org/1999/xhtml">x</div></foreignObject>' +
          '<a href="javascript:alert(1)"><text>a</text></a><a xlink:href=" JaVa\tscript:alert(1)"><text>b</text></a>' +
          '<a href="#Tank1"><text>c</text></a>' +
          '<set attributeName="onmouseover" to="alert(1)"/><animate attributeName="href" to="javascript:alert(1)"/>',
      ),
    );
    expect(markup).not.toMatch(/foreignObject|javascript|<set|<animate/i);
    expect(markup).toContain('href="#Tank1"');
  });

  it("removes external resource loads", () => {
    const { markup } = sanitizeSvg(wrap('<image href="https://evil.example/x.png"/><rect style="fill:url(https://evil.example)"/><style>@import url(x.css);</style>'));
    expect(markup).not.toContain("evil.example");
    expect(markup).not.toContain("@import");
  });

  it("derives a viewBox from width and height", () => {
    const result = sanitizeSvg(wrap("<g/>", 'width="100" height="50"'));
    expect(result.markup).toContain('viewBox="0 0 100 50"');
    expect(result.width).toBe(100);
  });

  it("rejects non-SVG input", () => {
    expect(() => sanitizeSvg("<html><body>hi</body></html>")).toThrow();
    expect(() => sanitizeSvg("not xml at all <")).toThrow();
  });

  it("returns an element that can be imported into the page", () => {
    const { element } = sanitizeSvg(wrap('<g id="x"/>'));
    const host = document.createElement("div");
    host.appendChild(document.importNode(element, true));
    expect(host.querySelector('[id="x"]')).not.toBeNull();
  });

  it("checks XLink hrefs by namespace, whatever the prefix", () => {
    const { markup } = sanitizeSvg(
      '<svg xmlns="http://www.w3.org/2000/svg" xmlns:x="http://www.w3.org/1999/xlink" viewBox="0 0 1 1">' +
        '<a x:href="javascript:alert(1)"><text>click</text></a>' +
        '<a xmlns:y="http://www.w3.org/1999/xlink" y:href="#Tank1"><text>ok</text></a>' +
        '<use xmlns:z="http://www.w3.org/1999/xlink" z:href="data:text/html,x" z:show="new"/>' +
        '<a xmlns:f="urn:foreign" f:href="#x" f:src="y"><text>f</text></a>' +
        "</svg>",
    );
    expect(markup).not.toMatch(/javascript|data:text|show=/i);
    expect(markup).toContain('href="#Tank1"');
    expect(markup).not.toMatch(/f:href|f:src/);
    expect(markup).toContain("click");
  });

  // The audit's payloads (pre-release viewer issue 40): CSS escapes and image-set() load resources, unscoped rules
  // restyle the page.
  const payloads: Record<string, string> = {
    escapedUrlInStyleAttr: '<rect style="fill:u\\72l(https://evil.example/a#p)"/>',
    imageSetInStyleAttr: '<rect style="background-image:image-set(&quot;https://evil.example/b.png&quot; 1x)"/>',
    escapedImportInStyleEl: '<style>@\\69mport "https://evil.example/c.css";</style>',
    imageSetInStyleEl: '<style>body{background-image:image-set("https://evil.example/d.png" 1x)}</style>',
    globalCssInStyleEl: "<style>body{display:none} .app-header{visibility:hidden}</style>",
  };

  for (const [name, body] of Object.entries(payloads)) {
    it(`loads nothing and styles nothing outside the drawing: ${name}`, () => {
      const { element, markup } = sanitizeSvg(wrap(`${body}<g id="kept"/>`));
      expect(markup).not.toContain("evil.example");
      expect(markup).toContain('id="kept"');
      const scope = `svg[${SCOPE_ATTR}="${element.getAttribute(SCOPE_ATTR)}"] `;
      for (const style of Array.from(element.querySelectorAll("style"))) {
        for (const rule of (style.textContent ?? "").split("\n")) {
          for (const selector of rule.slice(0, rule.indexOf("{")).split(",")) expect(selector.trim().startsWith(scope)).toBe(true);
        }
      }
    });
  }

  it("rebuilds style attributes from drawing properties with inert values", () => {
    const { markup } = sanitizeSvg(
      wrap(
        '<rect id="a" style="fill:rgb(0, 0, 0);stroke:#123;position:fixed;z-index:9;background:url(x.png);stroke-width:0.5"/>' +
          '<rect id="b" style="fill:u\\rl(x);cursor:url(https://evil.example/c),auto;fill:var(--x)"/>' +
          '<path id="c" style="marker-end:url(#arrow);font-family:\'DejaVu Sans\', Arial"/>' +
          '<path id="d" style="font-family:&quot;a;fill:red"/>',
      ),
    );
    expect(markup).toContain('id="a" style="fill:rgb(0, 0, 0);stroke:#123;stroke-width:0.5"');
    expect(markup).toMatch(/id="b"\/>/);
    expect(markup).toContain('id="c" style="marker-end:url(#arrow);font-family:\'DejaVu Sans\', Arial"');
    expect(markup).toContain('id="d" style="fill:red"');
    expect(markup).not.toContain("evil.example");
  });

  it("drops presentation attributes that load a resource, keeps fragment references and transforms", () => {
    const { markup } = sanitizeSvg(
      wrap(
        '<rect id="a" fill="url(https://evil.example/e.svg#p)" filter="url(https://evil.example/f.svg#f)" cursor="url(https://evil.example/c),auto" stroke="u\\72l(x)"/>' +
          '<g id="b" clip-path="url(#area)" fill="url(\'#hatch-zone\')" transform="rotate(90 5 5) translate(1,2)" stroke="rgb(0,0,0)"/>' +
          '<g id="P-101 (spare)" data-note="x(1)"/>',
      ),
    );
    expect(markup).not.toContain("evil.example");
    expect(markup).toContain('<rect id="a"/>');
    expect(markup).toContain('clip-path="url(#area)" fill="url(\'#hatch-zone\')" transform="rotate(90 5 5) translate(1,2)" stroke="rgb(0,0,0)"');
    expect(markup).toContain('id="P-101 (spare)" data-note="x(1)"');
  });

  it("keeps core's datasheet drawing styles, scoped to the drawing", () => {
    const style =
      ".frame{fill:none;stroke:#000;stroke-width:0.5}\n.hidden{fill:none;stroke:#000;stroke-width:0.25;stroke-dasharray:1.5 1}\n" +
      "text{font-family:'DejaVu Sans',Arial,Helvetica,sans-serif;fill:#000}\n.t2{font-size:2.2px}.t25{font-size:2.5px}\n" +
      ".draft{font-size:40px;font-weight:bold;fill:#c62828;fill-opacity:0.12}\n/* a comment */ g > .note, text.dimt{fill:#1f4e79}";
    const first = sanitizeSvg(wrap(`<style>${style}</style><text class="t25">ELEVATION</text>`));
    const second = sanitizeSvg(wrap(`<style>${style}</style>`));
    const scope = first.element.getAttribute(SCOPE_ATTR);
    expect(scope).toBeTruthy();
    expect(second.element.getAttribute(SCOPE_ATTR)).not.toBe(scope); // two drawings never share rules
    const s = `svg[${SCOPE_ATTR}="${scope}"]`;
    expect(first.element.querySelector("style")?.textContent).toBe(
      [
        `${s} .frame{fill:none;stroke:#000;stroke-width:0.5}`,
        `${s} .hidden{fill:none;stroke:#000;stroke-width:0.25;stroke-dasharray:1.5 1}`,
        `${s} text{font-family:'DejaVu Sans',Arial,Helvetica,sans-serif;fill:#000}`,
        `${s} .t2{font-size:2.2px}`,
        `${s} .t25{font-size:2.5px}`,
        `${s} .draft{font-size:40px;font-weight:bold;fill:#c62828;fill-opacity:0.12}`,
        `${s} g > .note, ${s} text.dimt{fill:#1f4e79}`,
      ].join("\n"),
    );
    expect(first.markup).toContain("ELEVATION");
  });

  it("drops at-rules and selectors that could reach outside the drawing", () => {
    const { element } = sanitizeSvg(
      wrap(
        '<style>@import "x.css"; .a{fill:red} @font-face{font-family:x;src:local(x)} .b{fill:blue}' +
          " ~ p{fill:red} + p, .c{fill:red} :root .d{fill:red} [id] .e{fill:red} .f:hover{fill:red} .g{}" +
          " .h *{stroke:red} @media print{.i{fill:red}} .j{fill:red}</style>" +
          '<g id="x" data-svg-scope="s1"/>',
      ),
    );
    const css = element.querySelector("style")?.textContent ?? "";
    expect(css).not.toMatch(/@|import|font-face|~|\+|:root|\[id\]|hover|\.g\b|\.i\b|\.j\b|\.c\b/);
    expect(css).toContain(" .b{fill:blue}");
    expect(css).toContain(" .h *{stroke:red}");
    expect(element.querySelector('[id="x"]')?.hasAttribute(SCOPE_ATTR)).toBe(false);
  });
});
