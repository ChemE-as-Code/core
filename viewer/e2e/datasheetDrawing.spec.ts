import { expect, test, type Page } from "@playwright/test";
import { readFileSync } from "node:fs";
import { dirname, join, resolve } from "node:path";
import { fileURLToPath } from "node:url";
import { asuFiles } from "./asuFiles";
import { datasheetDetails, datasheetDrawing, datasheetIndex, datasheetSnapshotKeys, mockApi } from "./fixtures";

/**
 * The datasheets from a server with `GET /api/datasheets`: the index with dimensions,
 * weights, drawing states, findings and the items without a sheet; a sheet's main dimensions,
 * weights, structured materials, nozzle schedule, findings and outline drawing (current, stale,
 * not committed); phone width and dark mode; a static snapshot with and without the endpoints.
 * The fixtures are the ASU's real answers (scripts/regen-fixtures.py --asu-datasheets).
 */
const SHOTS = process.env.LAYOUT_SHOTS ?? "";

function apiCalls(page: Page): string[] {
  const calls: string[] = [];
  page.on("request", (r) => {
    const url = new URL(r.url());
    if (url.pathname.startsWith("/api/")) calls.push(url.pathname + url.search);
  });
  return calls;
}

test.describe("datasheets from /api/datasheets", () => {
  test.beforeEach(async ({ page }) => {
    await mockApi(page, { files: asuFiles, datasheets: true });
  });

  test("the index: dimensions, weights, drawing states, findings, totals and the items without a sheet", async ({ page }) => {
    const calls = apiCalls(page);
    await page.goto("/datasheets");
    const rows = page.locator("table[aria-label='Datasheets'] tbody tr");
    // 39 sheets less P-4102B, removed so the list has an item without one.
    await expect(rows).toHaveCount(38);
    await expect(page.locator("[data-total='drafts']")).toHaveText("4");
    await expect(page.locator("[data-total='assumed']")).toHaveText("301");
    await expect(page.locator("[data-total='tbd']")).toHaveText("13");
    await expect(page.locator("[data-total='dimensions']")).toHaveText("37");
    await expect(page.locator("[data-total='weights']")).toHaveText("30");
    await expect(page.locator("[data-total='drawings-current']")).toHaveText("35");
    await expect(page.locator("[data-total='drawings-open']")).toHaveText("2 / 1");
    await expect(page.locator("[data-total='findings']")).toHaveText("0 / 6");
    await expect(page.locator("[data-total='missing']")).toHaveText("1");

    await expect(page.locator("tr[data-tag='V-2101A'] [data-drawing]")).toHaveText("current");
    await expect(page.locator("tr[data-tag='V-2101B'] [data-drawing]")).toHaveText("stale");
    await expect(page.locator("tr[data-tag='T-4102'] [data-drawing]")).toHaveText("missing");
    await expect(page.locator("tr[data-tag='V-3101'] [data-findings='warning']")).toHaveText("3 W");
    await expect(page.locator("tr[data-tag='V-2101A'] [data-has='weights']")).toBeVisible();
    await expect(page.locator("tr[data-tag='E-3103'] td[data-col='dimensions']")).toHaveText("–");

    await page.locator("[data-sort='drawing']").click();
    await expect(rows.first()).toHaveAttribute("data-tag", "T-4102");
    await page.locator("[data-sort='findings']").click();
    await expect(rows.first()).toHaveAttribute("data-tag", "V-3101");

    const missing = page.getByRole("region", { name: "Items without a datasheet" });
    await expect(missing.locator("[data-missing-tag]")).toHaveText(["P-4102B cheme datasheets draft --tag P-4102B"]);
    await expect(page.locator("[data-tree-source]")).toHaveCount(0);
    // One request for the whole index: no tree walk, no /api/yaml per sheet.
    expect(calls.filter((c) => c.startsWith("/api/yaml") || c.startsWith("/api/datasheets/"))).toEqual([]);
    expect(calls).toContain("/api/datasheets");
  });

  test("a vessel: main dimensions, weights, materials, the nozzle schedule, findings and its current drawing", async ({ page }) => {
    await page.goto("/datasheets/V-2101A");
    await expect(page.locator("h1")).toContainText("V-2101A");
    await expect(page.locator("[data-counts]")).toHaveText(/7 assumed,\s+0 TBD, 1 awaiting supplier/);

    const dims = page.getByRole("region", { name: "Main dimensions" });
    await expect(dims.locator("[data-orientation]")).toHaveText("horizontal");
    await expect(dims.locator("[data-group]")).toHaveCount(3);
    const shell = dims.locator("[data-group='shell']");
    await expect(shell.locator("tr[data-key='outside_diameter']")).toContainText("4.5");
    await expect(shell.locator("tr[data-key='outside_diameter'] .unit")).toHaveText("m");
    await expect(shell.locator("tr[data-key='tangent_length'] [data-assumed]")).toHaveAttribute("title", /^assumed: cheme datasheets fill: layout\/plant-model\.yaml/);
    await expect(shell.locator("tr[data-key='head']")).toContainText("ellipsoidal_2_1");
    await expect(shell.locator("tr[data-key='axis_deg'] .unit")).toHaveText("deg");
    await expect(dims.locator("[data-group='support'] tr[data-key='support.type']")).toContainText("saddles");
    await expect(dims.locator("[data-group='overall'] tr[data-key='overall_length']")).toContainText("18");

    const weights = page.getByRole("region", { name: "Weights" });
    await expect(weights.locator("tr[data-key='empty']")).toContainText("62");
    await expect(weights.locator("tr[data-key='empty'] .unit")).toHaveText("t");
    await expect(weights.locator("tr[data-key='empty'] [data-assumed]")).toBeVisible();
    await expect(weights.locator("tr[data-key='test'] [data-open='supplier']")).toHaveAttribute("title", "full of water, from the vessel supplier");

    const materials = page.locator("[data-section='materials']");
    await expect(materials.locator("tr[data-key='shell'] [data-material-class]")).toHaveText("low temperature carbon steel");
    await expect(materials.locator("tr[data-key='shell'] [data-standard]")).toHaveText("ASME II A");
    await expect(materials.locator("tr[data-key='heads'] [data-assumed]")).toBeVisible();
    await expect(materials.locator("tr[data-key='internals']")).toContainText("SS 304 support grid");
    await expect(materials.locator("tr[data-key='internals'] [data-material-class]")).toHaveCount(0);

    const nozzles = page.locator("[data-section='nozzles']");
    const n1 = nozzles.locator("tr[data-nozzle='N1']");
    await expect(n1).toContainText("Feed air inlet");
    await expect(n1).toContainText("PN16");
    await expect(n1.locator("[data-flange-standard]")).toHaveText("EN 1092-1");
    await expect(n1).toContainText("RF");
    await expect(n1.locator("td").nth(8)).toHaveText("0.6");
    await expect(nozzles.locator("tr[data-nozzle='M1'] [data-assumed]")).toBeVisible();
    await expect(nozzles.locator("tr[data-nozzle='M1']")).toContainText("Manway");

    const findings = page.getByRole("region", { name: "Findings on the datasheet" });
    await expect(findings.locator("li")).toHaveCount(2);
    await expect(findings.locator("li[data-rule='cheme.datasheet-nozzle-pid']")).toContainText("V-2101A nozzle M1: the P&ID draws no such nozzle");
    await expect(findings.locator("li[data-rule='cheme.datasheet-nozzle-pid']")).toContainText("cheme datasheets draft --dry-run");
    await expect(findings.locator("li[data-rule='cheme.datasheet-nozzle-pid'] .badge")).toHaveText("warning");

    const drawing = page.getByRole("region", { name: "Outline drawing" });
    await expect(drawing.locator("[data-drawing-state]")).toHaveText("committed, current");
    await expect(drawing.locator("[data-drawing-hint]")).toHaveCount(0);
    await expect(drawing.locator(".pane svg")).toBeVisible();
    await expect(drawing.locator(".pane svg text").filter({ hasText: "ELEVATION" })).toHaveCount(1);
    const download = drawing.locator("[data-action='download-drawing']");
    await expect(download).toHaveAttribute("href", "/api/datasheets/V-2101A.svg");
    await expect(download).toHaveAttribute("download", "V-2101A.svg");
    // The drawing pans and zooms like a P&ID.
    const stage = drawing.locator(".stage");
    const before = await stage.getAttribute("style");
    await drawing.getByRole("button", { name: "Zoom in" }).click();
    expect(await stage.getAttribute("style")).not.toBe(before);
  });

  test("the drawing is sanitised before it is shown", async ({ page }) => {
    await page.route("**/api/datasheets/V-2101A.svg*", (route) =>
      route.fulfill({
        status: 200,
        contentType: "image/svg+xml",
        headers: { "x-cheme-drawing": "committed", "x-cheme-drawing-current": "true" },
        body: '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 100 50"><script>window.__pwned = 1</script><rect width="10" height="10" onclick="window.__pwned = 2"/><text x="5" y="20">ELEVATION</text></svg>',
      }),
    );
    await page.goto("/datasheets/V-2101A");
    const pane = page.getByRole("region", { name: "Outline drawing" }).locator(".pane");
    await expect(pane.locator("svg text")).toHaveText("ELEVATION");
    await expect(pane.locator("script")).toHaveCount(0);
    await expect(pane.locator("rect[onclick]")).toHaveCount(0);
    expect(await page.evaluate(() => (globalThis as unknown as { __pwned?: number }).__pwned)).toBeUndefined();
  });

  test("the drawing's CSS loads nothing and styles nothing outside the drawing", async ({ page }) => {
    const external: string[] = [];
    await page.route("https://evil.example/**", (route) => {
      external.push(route.request().url());
      return route.fulfill({ status: 200, body: "" });
    });
    await page.route("**/api/datasheets/V-2101A.svg*", (route) =>
      route.fulfill({
        status: 200,
        contentType: "image/svg+xml",
        headers: { "x-cheme-drawing": "committed", "x-cheme-drawing-current": "true" },
        body:
          '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 100 50">' +
          '<rect width="5" height="5" style="fill:u\\72l(https://evil.example/a.svg#p)"/>' +
          '<rect width="5" height="5" style="background-image:image-set(&quot;https://evil.example/b.png&quot; 1x)"/>' +
          '<style>@\\69mport "https://evil.example/c.css";</style>' +
          '<style>body{background-image:image-set("https://evil.example/d.png" 1x)} h1, header, main{display:none}</style>' +
          '<rect width="5" height="5" filter="url(https://evil.example/f.svg#f)"/>' +
          '<text x="5" y="20">ELEVATION</text></svg>',
      }),
    );
    await page.goto("/datasheets/V-2101A");
    const pane = page.getByRole("region", { name: "Outline drawing" }).locator(".pane");
    await expect(pane.locator("svg text")).toHaveText("ELEVATION");
    await expect(page.getByRole("heading", { level: 1 })).toBeVisible();
    await expect(page.locator("main")).toBeVisible();
    await expect(page.locator("body")).toHaveCSS("background-image", "none");
    await page.waitForLoadState("networkidle");
    expect(external).toEqual([]);
  });

  test("core's drawing keeps its own styles and does not restyle other SVG text on the page", async ({ page }) => {
    await page.goto("/datasheets/V-2101A");
    const drawing = page.getByRole("region", { name: "Outline drawing" });
    await expect(drawing.locator(".pane svg text").filter({ hasText: "ELEVATION" })).toHaveCount(1);
    // inside: the sheet's own rules apply (dimension text is blue, `text{fill:#000}` elsewhere)
    await expect(drawing.locator(".pane svg text.dimt").first()).toHaveCSS("fill", "rgb(31, 78, 121)");
    // outside: an SVG text that inherits red stays red, and `.hidden`/`.frame` stroke nothing
    await page.evaluate(
      `document.body.insertAdjacentHTML("beforeend", '<div id="outside"><svg><g fill="rgb(255, 0, 0)"><text class="dimt">x</text></g></svg><p class="hidden frame">y</p></div>')`,
    );
    await expect(page.locator("#outside text")).toHaveCSS("fill", "rgb(255, 0, 0)");
    await expect(page.locator("#outside p")).toHaveCSS("stroke", "none");
  });

  test("a stale drawing says so, hints the command and previews the drawing the datasheet gives now", async ({ page }) => {
    const calls = apiCalls(page);
    await page.goto("/datasheets/V-2101B");
    const drawing = page.getByRole("region", { name: "Outline drawing" });
    await expect(drawing.locator("[data-drawing-state]")).toHaveText("committed, stale");
    await expect(drawing.locator("[data-drawing-hint]")).toContainText("cheme datasheets drawing --tag V-2101B --write");
    await expect(drawing.locator(".pane svg")).toBeVisible();
    await expect(page.getByRole("region", { name: "Findings on the datasheet" }).locator("li[data-rule='cheme.datasheet-drawing-stale']")).toBeVisible();
    await expect(drawing.locator("[data-drawing-preview]")).toHaveCount(0);

    await drawing.locator("[data-action='preview']").check();
    await expect(drawing.locator("[data-drawing-preview]")).toHaveText("showing the generated preview");
    await expect(drawing.locator("[data-action='download-drawing']")).toHaveAttribute("href", "/api/datasheets/V-2101B.svg?generated=true");
    await expect(drawing.locator("[data-action='download-drawing']")).toHaveAttribute("download", "V-2101B-generated.svg");
    expect(calls).toContain("/api/datasheets/V-2101B.svg?generated=true");
    // The preview is the drawing at the datasheet's new tangent length, not the committed one.
    expect(datasheetDrawing("V-2101B", true)!.body).not.toBe(datasheetDrawing("V-2101B")!.body);
  });

  test("no committed drawing: the generated preview, with the command to write it", async ({ page }) => {
    await page.goto("/datasheets/T-4102");
    const drawing = page.getByRole("region", { name: "Outline drawing" });
    await expect(drawing.locator("[data-drawing-state]")).toHaveText("generated preview");
    await expect(drawing).toContainText("equipment/datasheets/T-4102.svg is not committed");
    await expect(drawing.locator("[data-drawing-hint]")).toContainText("cheme datasheets drawing --tag T-4102 --write");
    await expect(drawing.locator(".pane svg")).toBeVisible();
    await expect(drawing.locator("[data-action='preview']")).toHaveCount(0);
  });

  test("findings that compare the dimensions with the equipment list and the layout model", async ({ page }) => {
    await page.goto("/datasheets/V-3101");
    const findings = page.getByRole("region", { name: "Findings on the datasheet" });
    await expect(findings.locator("li")).toHaveCount(3);
    const mismatch = findings.locator("li[data-rule='cheme.datasheet-dimension-mismatch']");
    await expect(mismatch).toContainText("outside_diameter 4.2 m here, diameter 2 m in the equipment list");
    await expect(mismatch.locator("a.file")).toHaveAttribute("href", /\/file\/equipment\/datasheets\/V-3101\.yaml\?line=26$/);
  });

  test("a pump and an exchanger: the overall dimensions and the machine's base", async ({ page }) => {
    await page.goto("/datasheets/P-1101A");
    const dims = page.getByRole("region", { name: "Main dimensions" });
    await expect(dims.locator("[data-group='overall'] tr")).toHaveCount(3);
    await expect(dims.locator("[data-group='support'] tr[data-key='support.type']")).toContainText("base_plate");
    await expect(page.getByRole("region", { name: "Outline drawing" }).locator(".pane svg")).toBeVisible();
    await page.goto("/datasheets/E-3101");
    await expect(page.getByRole("region", { name: "Main dimensions" }).locator("[data-group='overall'] tr[data-key='overall_width']")).toContainText("2.4");
  });

  test("fits a phone", async ({ page }) => {
    await page.setViewportSize({ width: 390, height: 844 });
    for (const url of ["/datasheets", "/datasheets/V-2101A", "/datasheets/V-2101B"]) {
      await page.goto(url);
      await expect(page.locator("table").first()).toBeVisible();
      if (url !== "/datasheets") await expect(page.getByRole("region", { name: "Outline drawing" }).locator(".pane svg")).toBeVisible();
      const overflow = await page.locator("main").evaluate((el) => el.scrollWidth - el.clientWidth);
      expect(overflow, url).toBeLessThanOrEqual(1);
      const pageOverflow = await page.evaluate(() => {
        const root = (globalThis as unknown as { document: { documentElement: { scrollWidth: number; clientWidth: number } } }).document.documentElement;
        return root.scrollWidth - root.clientWidth;
      });
      expect(pageOverflow, url).toBeLessThanOrEqual(1);
      if (SHOTS) await page.screenshot({ path: `${SHOTS}/datasheet-phone-${url.split("/").pop()}.png`, fullPage: true });
    }
  });

  test("dark mode: the page goes dark, the drawing stays on paper", async ({ page }) => {
    await page.emulateMedia({ colorScheme: "dark" });
    await page.goto("/datasheets/V-2101A");
    const drawing = page.getByRole("region", { name: "Outline drawing" });
    await expect(drawing.locator(".pane svg")).toBeVisible();
    const luminance = (rgb: string) => {
      const [r, g, b] = (rgb.match(/\d+(\.\d+)?/g) ?? []).map(Number);
      return 0.2126 * (r ?? 0) + 0.7152 * (g ?? 0) + 0.0722 * (b ?? 0);
    };
    // Computed colours, read in the page (the e2e code has no DOM types).
    type Styles = { getComputedStyle(el: unknown): { backgroundColor: string; color: string } };
    const body = await page.locator("body").evaluate((el) => (globalThis as unknown as Styles).getComputedStyle(el).backgroundColor);
    const paper = await drawing.locator(".stage").evaluate((el) => (globalThis as unknown as Styles).getComputedStyle(el).backgroundColor);
    const text = await page.locator("h1").evaluate((el) => (globalThis as unknown as Styles).getComputedStyle(el).color);
    expect(luminance(body)).toBeLessThan(60);
    expect(luminance(text)).toBeGreaterThan(160);
    expect(luminance(paper)).toBeGreaterThan(200);
    // The screenshot renders (and, with LAYOUT_SHOTS, is kept for checking by eye).
    const shot = await page.getByRole("region", { name: "Main dimensions" }).screenshot(SHOTS ? { path: `${SHOTS}/datasheet-dimensions-dark.png` } : {});
    expect(shot.byteLength).toBeGreaterThan(1000);
    const pane = await drawing.screenshot(SHOTS ? { path: `${SHOTS}/datasheet-drawing-dark.png` } : {});
    expect(pane.byteLength).toBeGreaterThan(1000);
    if (SHOTS) {
      await page.screenshot({ path: `${SHOTS}/datasheet-V-2101A-dark.png`, fullPage: true });
      await page.emulateMedia({ colorScheme: "light" });
      await page.screenshot({ path: `${SHOTS}/datasheet-V-2101A-light.png`, fullPage: true });
      await page.goto("/datasheets");
      await page.screenshot({ path: `${SHOTS}/datasheets-index-light.png`, fullPage: true });
    }
  });
});

test.describe("older servers", () => {
  test("without has_datasheets the viewer reads the files and asks no datasheet endpoint", async ({ page }) => {
    await mockApi(page, { files: asuFiles });
    const calls = apiCalls(page);
    await page.goto("/datasheets");
    await expect(page.locator("table[aria-label='Datasheets'] tbody tr")).toHaveCount(39);
    await expect(page.locator("[data-tree-source]")).toBeVisible();
    await expect(page.locator("th [data-sort='drawing']")).toHaveCount(0);
    await page.goto("/datasheets/C-3101");
    await expect(page.locator("[data-counts]")).toContainText("14 values: 6 assumed, 2 TBD");
    await expect(page.getByRole("region", { name: "Outline drawing" })).toHaveCount(0);
    expect(calls.filter((c) => c.startsWith("/api/datasheets"))).toEqual([]);
  });

  test("a 404 from /api/datasheets falls back to the files", async ({ page }) => {
    await mockApi(page, { files: asuFiles, datasheets: true });
    await page.route("**/api/datasheets**", (route) => route.fulfill({ status: 404, contentType: "application/json", body: '{"error":"not found"}' }));
    await page.goto("/datasheets");
    await expect(page.locator("table[aria-label='Datasheets'] tbody tr")).toHaveCount(39);
    await expect(page.locator("[data-tree-source]")).toBeVisible();
    await page.goto("/datasheets/P-1101A");
    await expect(page.locator("[data-counts]")).toContainText("15 values: 6 assumed, 0 TBD");
  });
});

test.describe("datasheets on a static snapshot", () => {
  // e2e/snapshot/ (core's examples/process-recycle) with the ASU's datasheet answers added under
  // the keys `cheme export-static` writes for them (tests/fixtures/api/datasheets-snapshot-keys.json).
  const SNAPSHOT = resolve(dirname(fileURLToPath(import.meta.url)), "snapshot");
  const TAGS = ["V-2101A", "V-2101B"];

  async function openSnapshot(page: Page, withEndpoints: boolean): Promise<void> {
    const manifest = JSON.parse(readFileSync(join(SNAPSHOT, "manifest.json"), "utf-8"));
    const repo = JSON.parse(readFileSync(join(SNAPSHOT, "data", manifest.entries.repo.file), "utf-8"));
    const extra: Record<string, { body: string; type: string }> = {
      "repo-ds.json": { body: JSON.stringify({ ...repo, has_datasheets: true }), type: "application/json" },
    };
    manifest.entries.repo = { file: "repo-ds.json", status: 200, type: "application/json" };
    if (withEndpoints) {
      const entries: Record<string, { body: string; type: string }> = {
        datasheets: { body: JSON.stringify({ ...datasheetIndex, datasheets: datasheetIndex.datasheets.filter((s) => TAGS.includes(s.tag)) }), type: "application/json" },
      };
      for (const tag of TAGS) {
        entries[`datasheets/${tag}`] = { body: JSON.stringify({ ...datasheetDetails[tag], source: null }), type: "application/json" };
        entries[`datasheets/${tag}.svg`] = { body: datasheetDrawing(tag)!.body, type: "image/svg+xml" };
      }
      for (const [key, entry] of Object.entries(entries)) {
        // The keys and types core writes (no `generated=true` drawing: a snapshot has the committed one).
        expect(datasheetSnapshotKeys[key], key).toEqual({ status: 200, type: entry.type });
        const file = `ds-${key.replace(/[^\w.-]/g, "_")}`;
        manifest.entries[key] = { file, status: 200, type: entry.type };
        extra[file] = entry;
      }
    }
    await page.route((url) => url.pathname.startsWith("/e2e-snapshot/"), async (route) => {
      const path = new URL(route.request().url()).pathname.replace(/^\/e2e-snapshot\//, "");
      if (path === "manifest.json") return route.fulfill({ json: manifest });
      const name = path.replace(/^data\//, "");
      if (extra[name]) return route.fulfill({ body: extra[name].body, contentType: extra[name].type });
      try {
        await route.fulfill({ body: readFileSync(join(SNAPSHOT, path)) });
      } catch {
        await route.fulfill({ status: 404, body: "not found" });
      }
    });
    await page.route((url) => url.pathname.startsWith("/api/"), (route) => route.abort());
  }

  test("the index, a sheet and its drawing from the exported endpoints", async ({ page }) => {
    const calls = apiCalls(page);
    await openSnapshot(page, true);
    await page.goto("/?data=/e2e-snapshot/#/datasheets");
    await expect(page.locator("table[aria-label='Datasheets'] tbody tr")).toHaveCount(2);
    await expect(page.locator("tr[data-tag='V-2101B'] [data-drawing]")).toHaveText("stale");
    await page.getByRole("link", { name: "V-2101A" }).click();
    await expect(page).toHaveURL(/#\/datasheets\/V-2101A$/);
    const drawing = page.getByRole("region", { name: "Outline drawing" });
    // No headers in a snapshot: the state comes from the sheet's answer.
    await expect(drawing.locator("[data-drawing-state]")).toHaveText("committed, current");
    await expect(drawing.locator(".pane svg")).toBeVisible();
    await expect(drawing.locator("[data-action='download-drawing']")).toHaveAttribute("href", /\/e2e-snapshot\/data\/ds-datasheets_V-2101A\.svg$/);
    await expect(page.getByRole("region", { name: "Weights" })).toBeVisible();

    await page.goto("/?data=/e2e-snapshot/#/datasheets/V-2101B");
    await expect(drawing.locator("[data-drawing-state]")).toHaveText("committed, stale");
    await drawing.locator("[data-action='preview']").check();
    await expect(drawing.locator("[data-preview-unavailable]")).toContainText("not in this snapshot");
    expect(calls).toEqual([]);
  });

  test("a snapshot without the endpoints falls back to the files it holds", async ({ page }) => {
    const calls = apiCalls(page);
    await openSnapshot(page, false);
    await page.goto("/?data=/e2e-snapshot/#/datasheets");
    await expect(page.locator("[data-empty]")).toContainText("No datasheets");
    await page.goto("/?data=/e2e-snapshot/#/datasheets/V-2101A");
    await expect(page.locator("[data-missing]")).toContainText("equipment/datasheets/V-2101A.yaml");
    expect(calls).toEqual([]);
  });
});
