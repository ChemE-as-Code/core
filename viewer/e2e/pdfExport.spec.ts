// "PDF" and "SVG" on a drawing: a vector PDF made in the browser (jsPDF + svg2pdf.js, loaded on
// the first click) from the drawing the API served, against a server (fixtures.ts) and a static
// snapshot (e2e/snapshot/, core's examples/process-recycle).
import { expect, test, type Download, type Page } from "@playwright/test";
import { readFileSync } from "node:fs";
import { dirname, join, resolve } from "node:path";
import { fileURLToPath } from "node:url";
import { inflateSync } from "node:zlib";
import { SHEET, mockApi } from "./fixtures";

const SNAPSHOT = resolve(dirname(fileURLToPath(import.meta.url)), "snapshot");
const manifest = JSON.parse(readFileSync(join(SNAPSHOT, "manifest.json"), "utf-8"));

async function serveSnapshot(page: Page): Promise<void> {
  await page.route((url) => url.pathname.startsWith("/e2e-snapshot/"), async (route) => {
    const path = new URL(route.request().url()).pathname.replace(/^\/e2e-snapshot\//, "");
    try {
      await route.fulfill({ body: readFileSync(join(SNAPSHOT, path)) });
    } catch {
      await route.fulfill({ status: 404, body: "not found" });
    }
  });
  await page.route((url) => url.pathname.startsWith("/api/"), (route) => route.abort());
}

async function bytesOf(download: Download): Promise<Buffer> {
  const path = await download.path();
  return readFileSync(path);
}

/** The PDF's page content: every stream, inflated when it is deflated. */
function contentOf(pdf: Buffer): string {
  const text = pdf.toString("latin1");
  const out: string[] = [];
  const re = /stream\r?\n/g;
  let match: RegExpExecArray | null;
  while ((match = re.exec(text))) {
    const start = match.index + match[0].length;
    const end = text.indexOf("endstream", start);
    if (end < 0) break;
    const raw = pdf.subarray(start, end);
    try {
      out.push(inflateSync(raw).toString("latin1"));
    } catch {
      out.push(raw.toString("latin1"));
    }
    re.lastIndex = end;
  }
  return out.join("\n");
}

async function downloadPdf(page: Page): Promise<{ name: string; pdf: Buffer }> {
  const button = page.getByRole("button", { name: "Download this drawing as PDF" });
  await expect(button).toBeEnabled();
  const [download] = await Promise.all([page.waitForEvent("download"), button.click()]);
  return { name: download.suggestedFilename(), pdf: await bytesOf(download) };
}

function expectOnePagePdf(pdf: Buffer, title: string): string {
  expect(pdf.length).toBeGreaterThan(2000);
  expect(pdf.subarray(0, 5).toString("latin1")).toBe("%PDF-");
  const text = pdf.toString("latin1");
  expect(text).toMatch(/\/Type \/Pages[\s\S]*?\/Count 1\b/);
  expect(text.match(/\/Type \/Page\b/g)).toHaveLength(1);
  expect(text).toContain(`/Title (${title})`);
  expect(text).toContain("/Creator (cheme-as-code viewer)");
  // Standard fonts, nothing embedded.
  expect(text).toContain("/BaseFont /Helvetica");
  expect(text).not.toContain("/FontFile");
  return text;
}

/** The page is `width` x `height` mm (in points). */
function expectPageMm(text: string, width: number, height: number): void {
  const box = /\/MediaBox \[0 0 ([\d.]+) ([\d.]+)\]/.exec(text);
  expect(box).not.toBeNull();
  expect(Number(box![1])).toBeCloseTo((width / 25.4) * 72, 1);
  expect(Number(box![2])).toBeCloseTo((height / 25.4) * 72, 1);
}

/**
 * The drawing is there, not only its text: at least `strokes` stroked paths (` S` operators, the
 * lines, symbols, frame and title-block grid) built from at least `segments` line segments.
 */
function expectDrawn(content: string, strokes: number, segments: number): void {
  expect(content.match(/^S$|\sS$/gm)?.length ?? 0).toBeGreaterThanOrEqual(strokes);
  expect(content.match(/ l$/gm)?.length ?? 0).toBeGreaterThanOrEqual(segments);
}

/** Where a shown text's line starts (its `Td`/`Tm` origin), in points from the page's bottom left. */
function originOf(content: string, label: string): { x: number; y: number } {
  const at = content.indexOf(`(${label}) Tj`);
  expect(at).toBeGreaterThan(0);
  const before = content.slice(0, at);
  const tm = [...before.matchAll(/(-?[\d.]+) (-?[\d.]+) Td|[-\d.]+ [-\d.]+ [-\d.]+ [-\d.]+ (-?[\d.]+) (-?[\d.]+) Tm/g)].pop();
  expect(tm).toBeDefined();
  return { x: Number(tm![1] ?? tm![3]), y: Number(tm![2] ?? tm![4]) };
}

test("against a server: the sheet as an A3 vector PDF at the selected revision", async ({ page }) => {
  await mockApi(page);
  const svgRequests: string[] = [];
  const scripts: string[] = [];
  page.on("request", (r) => {
    if (new URL(r.url()).pathname === "/api/pid.svg") svgRequests.push(r.url());
    if (r.resourceType() === "script") scripts.push(new URL(r.url()).pathname.split("/").pop() ?? "");
  });
  await page.goto(`/pid/${SHEET}?rev=main&select=Pump1`);
  await expect(page.locator(".pid .pane [id='Pump1']")).toBeAttached();
  // jsPDF and svg2pdf.js are loaded by the click only; jsPDF's optional chunks never.
  expect(scripts.filter((s) => /jspdf|svg2pdf/.test(s))).toEqual([]);
  const { name, pdf } = await downloadPdf(page);
  expect(scripts.filter((s) => s.startsWith("jspdf"))).toHaveLength(1);
  expect(scripts.filter((s) => s.startsWith("svg2pdf"))).toHaveLength(1);
  expect(scripts.filter((s) => /html2canvas|purify|^index\.es/.test(s))).toEqual([]);
  expect(name).toBe("Test-plant-P-01-main.pdf");
  expect(svgRequests.length).toBeGreaterThan(0);
  expect(svgRequests.every((u) => new URL(u).searchParams.get("rev") === "main")).toBe(true);
  const text = expectOnePagePdf(pdf, "P-01 Feed section");
  // The A3 sheet it is, landscape (420 x 297 mm).
  expectPageMm(text, 420, 297);
  // Text stays text: the tags and the title block are drawn with Tj, not as outlines.
  const content = contentOf(pdf);
  for (const label of ["P-101", "T-101", "P-01 Test plant"]) expect(content).toContain(`(${label}) Tj`);
  expectDrawn(content, 2, 10);
  // Every label starts on the page.
  for (const label of ["P-101", "T-101"]) {
    const { x, y } = originOf(content, label);
    expect(x).toBeGreaterThan(0);
    expect(x).toBeLessThan((420 / 25.4) * 72);
    expect(y).toBeGreaterThan(0);
    expect(y).toBeLessThan((297 / 25.4) * 72);
  }
  await expect(page.getByRole("button", { name: "Download this drawing as PDF" })).toHaveText("PDF");
});

test("against a server: SVG downloads the clean drawing, without the selection", async ({ page }) => {
  await mockApi(page);
  await page.goto(`/pid/${SHEET}?select=Pump1`);
  await expect(page.locator(".pid .pane [id='Pump1']")).toBeAttached();
  const [download] = await Promise.all([page.waitForEvent("download"), page.getByRole("button", { name: "Download this drawing as SVG" }).click()]);
  expect(download.suggestedFilename()).toBe("Test-plant-P-01.svg");
  const svg = (await bytesOf(download)).toString("utf-8");
  expect(svg).toMatch(/^<svg[^>]*xmlns="http:\/\/www\.w3\.org\/2000\/svg"/);
  expect(svg).toContain('id="Pump1"');
  expect(svg).not.toContain("pid-layer");
});

test("a PDF that cannot be made is reported, and the button comes back", async ({ page }) => {
  await mockApi(page);
  await page.route(/\/assets\/jspdf[^/]*\.js$/, (route) => route.abort());
  await page.goto(`/pid/${SHEET}`);
  const button = page.getByRole("button", { name: "Download this drawing as PDF" });
  await expect(button).toBeEnabled();
  await button.click();
  await expect(page.getByTestId("export-error")).toContainText("Cannot make the PDF");
  await expect(button).toBeEnabled();
  await page.getByTestId("export-error").getByRole("button", { name: "Dismiss" }).click();
  await expect(page.getByTestId("export-error")).toHaveCount(0);
});

test("in a static snapshot: the PFD as a PDF, named with the snapshot's commit, no /api request", async ({ page }) => {
  await serveSnapshot(page);
  const calls: string[] = [];
  page.on("request", (r) => {
    if (new URL(r.url()).pathname.startsWith("/api/")) calls.push(r.url());
  });
  await page.goto("/?data=/e2e-snapshot/#/pid/process/PFD.xml");
  await expect(page.locator(".pane[role='application'] svg").first()).toBeVisible();
  const { name, pdf } = await downloadPdf(page);
  expect(name).toBe(`process-recycle-PFD-${manifest.source.commit.slice(0, 8)}.pdf`);
  const text = expectOnePagePdf(pdf, "PFD Process flow diagram");
  // 458 x 297 mm is no A sheet: a page of its own size, 1:1.
  expectPageMm(text, 458, 297);
  const content = contentOf(pdf);
  expect(content).toMatch(/\(FEED\) Tj/);
  expectDrawn(content, 20, 50);
  expect(calls).toEqual([]);
});

test("embedded: the drawing toolbar keeps PDF and SVG", async ({ page }) => {
  await serveSnapshot(page);
  await page.goto("/?data=/e2e-snapshot/&embed=1#/pid/process/BFD.xml");
  await expect(page.locator(".pane[role='application'] svg").first()).toBeVisible();
  await expect(page.getByRole("button", { name: "Download this drawing as SVG" })).toBeEnabled();
  const { name, pdf } = await downloadPdf(page);
  expect(name).toMatch(/^process-recycle-BFD-[0-9a-f]{8}\.pdf$/);
  expectOnePagePdf(pdf, "BFD Block flow diagram");
});
