import { readFileSync } from "node:fs";
import { dirname, join, resolve } from "node:path";
import { fileURLToPath } from "node:url";
import { describe, expect, it } from "vitest";
import { MAX_PAGE_MM, drawingFileName, drawingSizeMm, pdfFont, pdfPage, pdfReadySvg } from "@/lib/pdfExport";
import { sanitizeSvg } from "@/lib/sanitize";

const SNAPSHOT = resolve(dirname(fileURLToPath(import.meta.url)), "../e2e/snapshot");
const manifest = JSON.parse(readFileSync(join(SNAPSHOT, "manifest.json"), "utf-8"));
/** The PFD of core's examples/process-recycle as `cheme export-static` wrote it (458 x 297, pyDEXPI). */
const pfd = readFileSync(join(SNAPSHOT, "data", manifest.entries["pid.svg?path=process/PFD.xml"].file), "utf-8");

const root = (attrs: Record<string, string>) => {
  const svg = document.createElementNS("http://www.w3.org/2000/svg", "svg");
  for (const [k, v] of Object.entries(attrs)) svg.setAttribute(k, v);
  return svg;
};

describe("drawingSizeMm", () => {
  it("takes a unitless size as sheet millimetres (cheme render)", () => {
    expect(drawingSizeMm(root({ width: "420.0", height: "297.0", viewBox: "0.0 0.0 420.0 297.0" }))).toEqual({ width: 420, height: 297 });
  });

  it("honours units", () => {
    expect(drawingSizeMm(root({ width: "84.1cm", height: "594mm" }))).toEqual({ width: 841, height: 594 });
    const inches = drawingSizeMm(root({ width: "11in", height: "8.5in" }))!;
    expect(inches.width).toBeCloseTo(279.4);
    expect(inches.height).toBeCloseTo(215.9);
  });

  it("falls back to the viewBox, and keeps its aspect ratio for one given side", () => {
    expect(drawingSizeMm(root({ viewBox: "0 0 594 420" }))).toEqual({ width: 594, height: 420 });
    expect(drawingSizeMm(root({ width: "100%", height: "100%", viewBox: "0 0 594 420" }))).toEqual({ width: 594, height: 420 });
    expect(drawingSizeMm(root({ width: "210mm", viewBox: "0 0 2100 1480" }))).toEqual({ width: 210, height: 148 });
  });

  it("takes a unitless size as millimetres however long the sheet (a long PFD strip)", () => {
    expect(drawingSizeMm(root({ width: "2557.0", height: "297.0", viewBox: "0 0 2557 297" }))).toEqual({ width: 2557, height: 297 });
    expect(drawingSizeMm(root({ viewBox: "0 0 4528 321" }))).toEqual({ width: 4528, height: 321 });
    expect(drawingSizeMm(root({ width: "1587px", height: "1123px" }))!.width).toBeCloseTo(419.9, 1);
  });

  it("is null without any size", () => {
    expect(drawingSizeMm(root({}))).toBeNull();
    expect(drawingSizeMm(root({ viewBox: "0 0 0 0" }))).toBeNull();
  });
});

describe("pdfPage", () => {
  it("puts an A sheet 1:1 on that sheet, in its orientation", () => {
    expect(pdfPage({ width: 420, height: 297 })).toMatchObject({ size: "A3", orientation: "landscape", width: 420, height: 297, x: 0, y: 0, scale: 1 });
    expect(pdfPage({ width: 841, height: 594 })).toMatchObject({ size: "A1", orientation: "landscape", scale: 1 });
    expect(pdfPage({ width: 594, height: 841 })).toMatchObject({ size: "A1", orientation: "portrait", width: 594, height: 841 });
    expect(pdfPage({ width: 419.6, height: 297.4 })).toMatchObject({ size: "A3", width: 420, height: 297, scale: 1 });
  });

  it("gives any other drawing a page of its own size, 1:1", () => {
    // The process-recycle PFD: 458 x 297 mm, an elongated A3.
    expect(pdfPage({ width: 458, height: 297 })).toEqual({ size: "custom", orientation: "landscape", width: 458, height: 297, x: 0, y: 0, drawingWidth: 458, drawingHeight: 297, scale: 1 });
    // The hydrogen-1 PFD strip keeps its 297 mm height: its text prints at its size.
    expect(pdfPage({ width: 2557, height: 297 })).toMatchObject({ size: "custom", width: 2557, height: 297, scale: 1 });
    expect(pdfPage({ width: 300, height: 900 })).toMatchObject({ size: "custom", orientation: "portrait", width: 300, height: 900, scale: 1 });
  });

  it("scales only a drawing longer than a PDF page can be", () => {
    const page = pdfPage({ width: 10160, height: 297 });
    expect(page.scale).toBeCloseTo(MAX_PAGE_MM / 10160);
    expect(page.width).toBeCloseTo(MAX_PAGE_MM);
    expect(page.height).toBeCloseTo(148.5);
    expect(page.drawingWidth).toBeCloseTo(page.width);
  });

  it("is A3 landscape for an unknown size", () => {
    expect(pdfPage(null)).toMatchObject({ size: "A3", orientation: "landscape", scale: 1 });
  });
});

describe("drawingFileName", () => {
  it("is <plant>-<sheet>[-<rev>]", () => {
    expect(drawingFileName({ plant: "asu", sheet: "P-01", path: "pid/P-01.xml", rev: "3f2a9c1b", ext: "pdf" })).toBe("asu-P-01-3f2a9c1b.pdf");
    expect(drawingFileName({ plant: "asu", sheet: "PFD", path: "process/PFD.xml", rev: null, ext: "svg" })).toBe("asu-PFD.svg");
  });

  it("uses the file stem without a sheet id and cleans every part", () => {
    expect(drawingFileName({ plant: "Test plant", sheet: null, path: "pid/area 1/P-07.xml", ext: "pdf" })).toBe("Test-plant-P-07.pdf");
    expect(drawingFileName({ plant: "a/b", sheet: "P 01", path: "x.xml", rev: "feature/pdf", ext: "pdf" })).toBe("a-b-P-01-feature-pdf.pdf");
    expect(drawingFileName({ plant: "", sheet: "", path: "", ext: "pdf" })).toBe("drawing.pdf");
  });
});

describe("pdfFont", () => {
  it("maps families to the standard PDF fonts", () => {
    expect(pdfFont("'Arial', Arial")).toBe("helvetica");
    expect(pdfFont("'Calibri', Arial")).toBe("helvetica");
    expect(pdfFont('"Times New Roman", serif')).toBe("times");
    expect(pdfFont("Consolas, monospace")).toBe("courier");
    expect(pdfFont("Comic Sans MS")).toBe("helvetica");
    expect(pdfFont(null)).toBe("helvetica");
  });
});

const parse = (markup: string) => sanitizeSvg(markup).element;

describe("pdfReadySvg", () => {
  it("drops the sheet background, maps fonts, leaves the source alone", () => {
    const source = parse(pfd);
    const ready = pdfReadySvg(source);
    expect(source.querySelector(":scope > rect")).not.toBeNull();
    expect(ready.querySelector(":scope > rect")).toBeNull();
    expect(ready.getAttribute("font-family")).toBe("helvetica");
    const texts = Array.from(ready.querySelectorAll("text"));
    expect(texts.length).toBeGreaterThan(10);
    expect(texts.every((t) => !t.hasAttribute("font-family") || t.getAttribute("font-family") === "helvetica")).toBe(true);
    expect(ready.querySelectorAll("[dominant-baseline], [alignment-baseline]")).toHaveLength(0);
    expect(source.querySelector("text")?.getAttribute("font-family")).toBe("'Arial', Arial");
    expect(source.querySelector("[dominant-baseline]")).not.toBeNull();
  });

  it("centres a middle-aligned tag's capitals on y: baseline y + 0.36 em of the PDF font", () => {
    const ready = pdfReadySvg(parse('<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 420 297"><text x="10" y="18.75" font-size="3.0" font-family="Arial" dominant-baseline="middle">UY</text><text x="10" y="40" font-size="2.5" font-family="Arial" dominant-baseline="text-bottom">A</text><g dominant-baseline="hanging" font-size="10"><text y="5 6">B</text></g></svg>'));
    const [uy, a, b] = Array.from(ready.querySelectorAll("text"));
    expect(Number(uy!.getAttribute("y"))).toBeCloseTo(18.75 + 0.36 * 3);
    // Chromium draws text-bottom on the alphabetic baseline.
    expect(a!.getAttribute("y")).toBe("40");
    expect(b!.getAttribute("y")).toBe("12.2 13.2");
    expect(ready.querySelectorAll("[dominant-baseline], [alignment-baseline]")).toHaveLength(0);
  });

  it("sets Calibri text in Helvetica at 0.89 of its size", () => {
    const ready = pdfReadySvg(parse(`<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 420 297"><text x="92" y="57" text-anchor="middle" dominant-baseline="middle" font-family="'Calibri', Arial" font-size="3.0">PIC</text></svg>`));
    const text = ready.querySelector("text")!;
    expect(text.getAttribute("font-family")).toBe("helvetica");
    expect(Number(text.getAttribute("font-size"))).toBeCloseTo(2.67);
    expect(Number(text.getAttribute("y"))).toBeCloseTo(57 + 0.36 * 2.67);
  });

  it("maps fonts set in style attributes and <style> rules", () => {
    const ready = pdfReadySvg(parse('<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 100 100"><style>text { font-family: Calibri, sans-serif; } .t { font: bold 3px "Times New Roman"; }</style><text style="font-family:Calibri; font-size: 4px; dominant-baseline: middle" y="10">A</text><text class="t" style="font: 3px Consolas, monospace">B</text></svg>'));
    const [a, b] = Array.from(ready.querySelectorAll("text"));
    expect(a!.getAttribute("style")).toBe("font-family: helvetica");
    expect(Number(a!.getAttribute("font-size"))).toBeCloseTo(3.56);
    expect(Number(a!.getAttribute("y"))).toBeCloseTo(10 + 0.36 * 3.56);
    expect(b!.getAttribute("style")).toBe("font: 3px courier");
    const css = ready.querySelector("style")!.textContent!;
    expect(css).toContain("text{font-family:helvetica}");
    expect(css).toContain(".t{font:bold 3px times}");
    expect(css).not.toMatch(/calibri|consolas|new roman/i);
  });

  it("keeps a rect that does not cover the sheet", () => {
    const { element } = sanitizeSvg('<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 100 100"><rect x="10" y="10" width="20" height="20"/></svg>');
    expect(pdfReadySvg(element).querySelector("rect")).not.toBeNull();
  });
});
