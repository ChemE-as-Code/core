import { expect, test } from "@playwright/test";
import { asuFiles } from "./asuFiles";
import { mockApi } from "./fixtures";

/**
 * The sidebar: the plant's pages and documents in engineering groups (src/lib/pages.ts), the raw
 * repository files folded away below them; documents as readable tables and text.
 */

const DESIGN_BASIS = {
  kind: "design_basis",
  schema: null,
  data: {
    capacity: { basis: "GOX product to pipeline", gox_t_per_d: 500 },
    products: [
      { name: "GOX", purity: "O2 >= 99.5 mol%", delivery: { pressure_barg: 30, battery_limit: "pipeline" } },
      { name: "GAN", purity: "O2 <= 10 ppm(mol)" },
    ],
    assumptions: ["ASSUMED O2 recovery ~83 %", "ASSUMED MAC discharge 5.8 bara"],
  },
};

const docTree = [
  { path: "process/design-basis.yaml", type: "file", kind: "yaml" },
  { path: "safety", type: "dir", kind: "other" },
  { path: "safety/hazop", type: "dir", kind: "other" },
  { path: "safety/hazop/H-01", type: "dir", kind: "other" },
  { path: "safety/hazop/H-01/study.yaml", type: "file", kind: "yaml" },
  { path: "README.md", type: "file", kind: "markdown" },
];

test.describe("page navigation", () => {
  test("pages in groups, the raw files folded away until opened", async ({ page }) => {
    await mockApi(page);
    await page.goto("/");
    const nav = page.getByRole("navigation", { name: "Pages" });
    await expect(nav.locator("section[data-group] h2")).toHaveText(["Process", "P&IDs", "Layout", "Cost and impact", "Quality", "Project"]);
    await expect(nav.getByRole("link", { name: "Overview" })).toHaveAttribute("class", /active/);
    const toggle = page.getByTestId("files-toggle");
    await expect(toggle).toHaveAttribute("aria-expanded", "false");
    await expect(page.locator("#tree-filter")).toBeHidden();
    await toggle.click();
    await expect(toggle).toHaveAttribute("aria-expanded", "true");
    await expect(page.getByTestId("files").getByRole("button", { name: "lists" })).toBeVisible();
    // the choice is remembered
    await page.reload();
    await expect(page.getByTestId("files-toggle")).toHaveAttribute("aria-expanded", "true");
    await page.getByTestId("files-toggle").click();
    await page.reload();
    await expect(page.getByTestId("files-toggle")).toHaveAttribute("aria-expanded", "false");
  });

  test("a raw file opens the files with its folder; a sheet does not", async ({ page }) => {
    await mockApi(page);
    await page.goto("/pid/process/BFD.xml");
    await expect(page.getByTestId("files-toggle")).toHaveAttribute("aria-expanded", "false");
    await page.goto("/file/lists/equipment.yaml");
    await expect(page.getByTestId("files-toggle")).toHaveAttribute("aria-expanded", "true");
    await expect(page.getByTestId("files").locator(".row.active")).toHaveText(/equipment\.yaml/);
  });

  test("documents in the tree are listed in their group and open as a document", async ({ page }) => {
    await mockApi(page, { extraTree: docTree });
    await page.route(/\/api\/yaml\?.*design-basis/, (route) => route.fulfill({ json: DESIGN_BASIS }));
    await page.goto("/");
    const nav = page.getByRole("navigation", { name: "Pages" });
    await expect(nav.locator("[data-group=safety] li")).toHaveText(["HAZOP H-01"]);
    await expect(nav.locator("[data-group=project] li").first()).toHaveText("README");
    await expect(page.getByTestId("home-pages").locator("[data-group=process]")).toContainText("Design basis");
    await nav.getByRole("link", { name: "Design basis" }).click();
    await expect(page).toHaveURL(/\/yaml\/process\/design-basis\.yaml$/);
    await expect(nav.getByRole("link", { name: "Design basis" })).toHaveAttribute("aria-current", "page");
    // a document, not a tree: sections, value lists, tables with nested values as text
    const doc = page.getByTestId("yaml-document");
    await expect(doc.getByRole("heading", { name: "Capacity" })).toBeVisible();
    await expect(doc.locator("[data-key=assumptions] li")).toHaveCount(2);
    await expect(doc.locator("[data-key=products] tbody tr").first()).toContainText("pressure_barg: 30; battery_limit: pipeline");
    await expect(page.getByTestId("files-toggle")).toHaveAttribute("aria-expanded", "false");
    await page.getByRole("button", { name: "Tree" }).click();
    await expect(doc).toHaveCount(0);
    await page.getByRole("button", { name: "Document" }).click();
    await expect(page.getByTestId("yaml-document")).toBeVisible();
  });

  test("on a phone the pages are in the menu", async ({ page }) => {
    await page.setViewportSize({ width: 390, height: 844 });
    await mockApi(page);
    await page.goto("/");
    const nav = page.getByRole("navigation", { name: "Pages" });
    await expect(nav).not.toBeInViewport();
    await page.getByRole("button", { name: "Toggle navigation" }).click();
    await expect(nav).toBeInViewport();
    await nav.getByRole("link", { name: "Validation" }).click();
    await expect(page).toHaveURL(/\/validate/);
    await expect(nav).not.toBeInViewport();
  });
});

test("validation shows errors and warnings, the info findings one click away", async ({ page }) => {
  await mockApi(page);
  await page.goto("/validate");
  const rows = page.locator("table.data tbody tr");
  await expect(rows).toHaveCount(2);
  await expect(rows.first()).toContainText("warning");
  await page.getByTestId("show-info").click();
  await expect(rows).toHaveCount(4);
  await expect(page.getByTestId("show-info")).toHaveCount(0);
});

test("a CSV file reads as a table, its source a click away", async ({ page }) => {
  await mockApi(page, { files: asuFiles });
  await page.goto("/file/layout/lifting-study.csv");
  const table = page.getByTestId("csv-table");
  await expect(table.locator("thead th").first()).toHaveText("tag");
  expect(await table.locator("tbody tr").count()).toBeGreaterThan(1);
  await page.getByRole("button", { name: "Source" }).click();
  await expect(table).toHaveCount(0);
  await expect(page.locator(".source")).toContainText("tag,");
  await page.getByRole("button", { name: "Table" }).click();
  await expect(page.getByTestId("csv-table")).toBeVisible();
});
