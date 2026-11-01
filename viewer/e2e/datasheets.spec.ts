import { expect, test } from "@playwright/test";
import { readFileSync } from "node:fs";
import { dirname, join, resolve } from "node:path";
import { fileURLToPath } from "node:url";
import { asuFiles } from "./asuFiles";
import { asuDatasheets, mockApi } from "./fixtures";

/**
 * The equipment datasheets of the ASU (`equipment/datasheets/<TAG>.yaml`, read through
 * `/api/tree` and `/api/yaml`): the index with its counts, filter and sort, one sheet's page, the
 * links from the header, the home page and the layout, and the same pages on a static snapshot.
 */
test.describe("equipment datasheets", () => {
  test.beforeEach(async ({ page }) => {
    await mockApi(page, { files: asuFiles });
  });

  test("the page navigation and the home page link the datasheets when the tree has them", async ({ page }) => {
    await page.goto("/");
    const nav = page.getByRole("navigation", { name: "Pages" });
    await expect(nav.getByRole("link", { name: "Datasheets" })).toBeVisible();
    await page.getByTestId("home-pages").getByRole("link", { name: "Datasheets" }).click();
    await expect(page).toHaveURL(/\/datasheets$/);
    await expect(nav.getByRole("link", { name: "Datasheets" })).toHaveClass(/router-link-active/);
  });

  test("no Datasheets link without equipment/datasheets/", async ({ page }) => {
    await mockApi(page);
    await page.goto("/");
    await expect(page.getByTestId("home-pages").getByRole("link", { name: "Validation" })).toBeVisible();
    await expect(page.getByRole("navigation", { name: "Pages" }).getByRole("link", { name: "Datasheets" })).toHaveCount(0);
    await expect(page.getByTestId("home-pages").getByRole("link", { name: "Datasheets" })).toHaveCount(0);
  });

  test("the index lists every sheet with its counts, filters and sorts", async ({ page }) => {
    await page.goto("/datasheets");
    const rows = page.locator("table[aria-label='Datasheets'] tbody tr");
    await expect(rows).toHaveCount(39);
    await expect(page.locator("[data-total='drafts']")).toHaveText("4");
    await expect(page.locator("[data-total='assumed']")).toHaveText("276");
    await expect(page.locator("[data-total='tbd']")).toHaveText("13");
    await expect(page.locator("[data-draft]")).toHaveCount(4);

    const p1101a = page.locator("tr[data-tag='P-1101A']");
    await expect(p1101a).toContainText("CentrifugalPump");
    await expect(p1101a).toContainText("DCAC cooling water pump");
    await expect(p1101a.locator("td").nth(4)).toHaveText("6");

    await page.getByRole("searchbox", { name: "Filter datasheets" }).fill("p-110");
    await expect(rows).toHaveCount(4);
    await page.getByRole("searchbox", { name: "Filter datasheets" }).fill("");
    await page.getByRole("combobox", { name: "Type" }).selectOption("ProcessColumn");
    await expect(rows.first()).toContainText("ProcessColumn");
    await page.getByRole("combobox", { name: "Type" }).selectOption("");

    await page.locator("[data-sort='tbd']").click();
    await expect(page.locator("th[aria-sort='descending']")).toContainText("TBD");
    const first = await rows.first().locator("td").nth(5).textContent();
    expect(Number(first)).toBeGreaterThan(0);
    await page.locator("[data-sort='tag']").click();
    await page.locator("[data-sort='tag']").click();
    await expect(rows.first()).toHaveAttribute("data-tag", "V-3101");

    await page.locator("tr[data-tag='C-3101']").getByRole("link", { name: "C-3101" }).click();
    await expect(page).toHaveURL(/\/datasheets\/C-3101$/);
  });

  test("a sheet: header, value tables with assumed and TBD values, nozzles, links", async ({ page }) => {
    await page.goto("/datasheets/C-3101");
    await expect(page.locator("h1")).toContainText("C-3101");
    await expect(page.locator("[data-type]")).toHaveText("ProcessColumn");
    await expect(page.locator("h1 [data-draft]")).toHaveText("draft");
    await expect(page.locator("[data-service]")).toHaveText("HP column");
    await expect(page.locator("[data-counts]")).toContainText("14 values: 6 assumed, 2 TBD");

    const operating = page.locator("[data-section='operating']");
    const inlet = operating.locator("tr[data-key='inlet_pressure']");
    await expect(inlet).toContainText("5.5");
    await expect(inlet).toContainText("bar(a)");
    await expect(inlet.locator("[data-assumed]")).toHaveAttribute("title", /^assumed: process\/flowsheet\.yaml stream S5/);

    const typeSpecific = page.locator("[data-section='type_specific']");
    await expect(typeSpecific.locator("tr.open")).toHaveCount(2);
    await expect(typeSpecific.locator("tr[data-key='number_of_stages'] [data-open='tbd']")).toHaveText("TBD");
    await expect(page.getByRole("region", { name: "Other type-specific fields" })).toContainText("process_streams");

    const nozzles = page.locator("[data-section='nozzles']");
    const n1 = nozzles.locator("tr[data-nozzle='N1']");
    await expect(n1).toContainText("500");
    await expect(n1).toContainText("side");
    await expect(n1).toContainText("5.8");
    await expect(n1.locator("[data-line='AIR-3001'] [data-link='3d']")).toHaveAttribute("href", /\/layout\?select=AIR-3001$/);
    await expect(page.locator("[data-section='sizing_basis']")).toContainText("None recorded yet.");

    await expect(page.locator("[data-action='show-3d']")).toHaveAttribute("href", /\/layout\?select=C-3101$/);
    await expect(page.locator("[data-action='yaml']")).toHaveAttribute("href", /\/yaml\/equipment\/datasheets\/C-3101\.yaml$/);
  });

  test("not applicable and supplier values say why", async ({ page }) => {
    await page.goto("/datasheets/C-1101");
    const ts = page.locator("[data-section='type_specific']");
    const reflux = ts.locator("tr[data-key='minimum_reflux_ratio']");
    await expect(reflux.locator("[data-open='not_applicable']")).toHaveText("n/a");
    await expect(reflux.locator("[data-reason]")).toContainText("no reflux in a direct contact cooler");
    await expect(ts.locator("[data-open='supplier']")).toHaveCount(3);
  });

  test("a value cheme datasheets fill calculated is a row with its origin, inputs and fingerprint", async ({ page }) => {
    // C-3101 as after a fill: values with origin, fingerprint and inputs in the
    // type-specific table, the main dimensions and the sizing basis.
    const path = "equipment/datasheets/C-3101.yaml";
    const doc = asuDatasheets[path] as { data: Record<string, unknown> };
    const filled = {
      source: "cheme datasheets fill (case design)",
      origin: "correlation",
      fingerprint: "3f9a0c1d2e4b5a69",
      inputs: ["catalyst:CAT-1", "pipe:L-12", "nozzle:C-3101/N1", "residence_time:C-3101", "datasheet:design.pressure_barg"],
    };
    const data = {
      ...doc.data,
      type_specific: { ...(doc.data.type_specific as object), volume_m3: { value: 42.5, unit: "m3", ...filled } },
      dimensions: { inside_diameter: { value: 3.2, unit: "m", ...filled, inputs: ["pipe:L-12"] } },
      sizing_basis: [{ parameter: "volume", value: { value: 42.5, unit: "m3", origin: "correlation", fingerprint: "77aa" } }],
    };
    await page.route((url) => url.pathname === "/api/yaml" && url.searchParams.get("path") === path, (route) => route.fulfill({ json: { ...doc, data } }));
    await page.goto("/datasheets/C-3101");
    const row = page.locator("[data-section='type_specific'] tr[data-key='volume_m3']");
    await expect(row).toContainText("42.5");
    await expect(row.locator("td.unit")).toHaveText("m3");
    await expect(row).toContainText("cheme datasheets fill (case design)");
    await expect(row.locator("[data-origin='correlation']")).toHaveText("correlation");
    await expect(row.locator("[data-assumed]")).toHaveCount(0);
    await expect(page.getByRole("region", { name: "Other type-specific fields" })).not.toContainText("volume_m3");

    // Compact, and the full list and the fingerprint by keyboard (the disclosure's summary).
    const summary = row.locator("[data-inputs]");
    await expect(summary).toHaveText("depends on: catalyst CAT-1, pipe L-12, nozzle C-3101/N1, +2 more");
    await expect(row.locator("[data-inputs-full]")).toBeHidden();
    await summary.focus();
    await page.keyboard.press("Enter");
    await expect(row.locator("[data-inputs-full] li")).toHaveText(["catalyst CAT-1", "pipe L-12", "nozzle C-3101/N1", "residence time C-3101", "datasheet design.pressure_barg"]);
    await expect(row.locator("[data-fingerprint]")).toBeVisible();
    await expect(row.locator("[data-fingerprint] code").first()).toHaveText("3f9a0c1d2e4b5a69");

    const diameter = page.locator("[data-section='dimensions'] tr[data-key='inside_diameter']");
    await expect(diameter.locator("[data-origin='correlation']")).toBeVisible();
    await expect(diameter.locator("[data-inputs]")).toHaveText("depends on: pipe L-12");

    // A fingerprint without inputs: the summary says so and opens on it.
    const sizing = page.locator("[data-section='sizing_basis'] li");
    await expect(sizing).toContainText("volume: 42.5");
    await expect(sizing.locator("[data-origin='correlation']")).toBeVisible();
    await sizing.locator("[data-inputs]").click();
    await expect(sizing.locator("[data-fingerprint] code").first()).toHaveText("77aa");

    // A quantity without these fields has no basis.
    await expect(page.locator("[data-section='design'] tr[data-key='pressure_barg']")).toContainText("7");
    await expect(page.locator("[data-section='design'] [data-basis]")).toHaveCount(0);
  });

  test("nozzle lines link the line list and the sheet its P&ID", async ({ page }) => {
    // The ASU tree fixture has the datasheets and the layout; add a line list. (route.fetch would
    // go past the mocks to a real server: none on CI.)
    await mockApi(page, {
      files: asuFiles,
      extraTree: [
        { path: "piping", type: "dir", kind: "other" },
        { path: "piping/line-list.yaml", type: "file", kind: "yaml" },
      ],
    });
    await page.goto("/datasheets/P-1101A");
    const n1 = page.locator("tr[data-nozzle='N1']");
    await expect(n1.locator("[data-link='pid']")).toHaveAttribute("href", /\/pid\/pid\/P-01\.xml\?select=P-1101A$/);
    await expect(n1.locator("[data-link='pid']")).toHaveText("P-01");
    const line = n1.locator("[data-line='CW-1001'] [data-link='line-list']");
    await expect(line).toHaveAttribute("href", /\/yaml\/piping\/line-list\.yaml\?filter=CW-1001$/);
  });

  test("a tag without a datasheet says so", async ({ page }) => {
    await page.goto("/datasheets/X-9999");
    await expect(page.locator("[data-missing]")).toContainText("equipment/datasheets/X-9999.yaml");
  });

  test("the layout's datasheet link opens the sheet", async ({ page }) => {
    await page.goto("/layout?select=K-4101");
    await page.getByRole("region", { name: "Selection" }).locator("[data-datasheet] a").click();
    await expect(page).toHaveURL(/\/datasheets\/K-4101$/);
    await expect(page.locator("h1")).toContainText("K-4101");
  });

  test("fits a phone", async ({ page }) => {
    await page.setViewportSize({ width: 390, height: 844 });
    for (const url of ["/datasheets", "/datasheets/C-3101"]) {
      await page.goto(url);
      await expect(page.locator("table").first()).toBeVisible();
      const overflow = await page.locator("main").evaluate((el) => el.scrollWidth - el.clientWidth);
      expect(overflow, url).toBeLessThanOrEqual(1);
    }
  });
});

test.describe("datasheets on a static snapshot", () => {
  // e2e/snapshot/ (core's examples/process-recycle) with one ASU datasheet added to its tree and manifest.
  const SNAPSHOT = resolve(dirname(fileURLToPath(import.meta.url)), "snapshot");
  const PATH = "equipment/datasheets/P-1101A.yaml";

  test("lists and opens a datasheet without a server", async ({ page }) => {
    const manifest = JSON.parse(readFileSync(join(SNAPSHOT, "manifest.json"), "utf-8"));
    const tree = JSON.parse(readFileSync(join(SNAPSHOT, "data", manifest.entries.tree.file), "utf-8"));
    const extra: Record<string, unknown> = {
      "tree-ds.json": [...tree, { path: "equipment", type: "dir", kind: "other" }, { path: "equipment/datasheets", type: "dir", kind: "other" }, { path: PATH, type: "file", kind: "yaml" }],
      "yaml-ds.json": asuDatasheets[PATH],
    };
    manifest.entries.tree = { file: "tree-ds.json", status: 200, type: "application/json" };
    manifest.entries[`yaml?path=${PATH}`] = { file: "yaml-ds.json", status: 200, type: "application/json" };
    const calls: string[] = [];
    page.on("request", (r) => {
      if (new URL(r.url()).pathname.startsWith("/api/")) calls.push(r.url());
    });
    await page.route((url) => url.pathname.startsWith("/e2e-snapshot/"), async (route) => {
      const path = new URL(route.request().url()).pathname.replace(/^\/e2e-snapshot\//, "");
      if (path === "manifest.json") return route.fulfill({ json: manifest });
      const name = path.replace(/^data\//, "");
      if (extra[name]) return route.fulfill({ json: extra[name] });
      try {
        await route.fulfill({ body: readFileSync(join(SNAPSHOT, path)) });
      } catch {
        await route.fulfill({ status: 404, body: "not found" });
      }
    });
    await page.route((url) => url.pathname.startsWith("/api/"), (route) => route.abort());

    await page.goto("/?data=/e2e-snapshot/#/");
    await page.getByRole("navigation", { name: "Pages" }).getByRole("link", { name: "Datasheets" }).click();
    await expect(page.locator("table[aria-label='Datasheets'] tbody tr")).toHaveCount(1);
    await page.getByRole("link", { name: "P-1101A" }).click();
    await expect(page).toHaveURL(/#\/datasheets\/P-1101A$/);
    await expect(page.locator("[data-counts]")).toContainText("15 values: 6 assumed, 0 TBD");
    expect(calls).toEqual([]);
  });
});
