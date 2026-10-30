import { readFileSync } from "node:fs";
import { dirname, join, resolve } from "node:path";
import { fileURLToPath } from "node:url";
import { expect, test, type Page } from "@playwright/test";
import { mockApi } from "./fixtures";

/**
 * A library server (`cheme serve` on a folder of plants, core's ADR 0034): the index of the
 * plants at `/`, each plant under `/p/<id>/` (its API and its routes), the switcher in the
 * header; and a snapshot's link back to the page that opened it.
 */

const entry = (id: string, over: Record<string, unknown> = {}) => ({
  id,
  path: `processes/${id}`,
  name: null,
  stage: "concept",
  sheets: 2,
  maturity: null,
  maturity_checked: null,
  title: null,
  summary: null,
  families: [],
  error: null,
  ...over,
});

const plants = {
  root_name: "process-library",
  plants: [
    entry("alpha", { name: "Alpha plant", stage: "basic", maturity: "balanced", families: ["gases"], summary: "Separates air." }),
    entry("beta", { title: "Beta process", families: ["oxygenates"] }),
    entry("gamma", { error: "plant.yaml: stage: not one of concept, basic, detail" }),
  ],
};

/** The API requests the page makes, by path. */
function apiPaths(page: Page): string[] {
  const paths: string[] = [];
  page.on("request", (r) => {
    const url = new URL(r.url());
    if (url.pathname.includes("/api/")) paths.push(url.pathname);
  });
  return paths;
}

test.describe("library", () => {
  test("the index lists the plants, filters them and opens one", async ({ page }) => {
    await mockApi(page, { plants });
    await page.goto("/?theme=dark");
    const cards = page.locator("[data-plant]");
    await expect(cards).toHaveCount(3);
    await expect(page).toHaveTitle("Plants – process-library – cheme-as-code viewer");
    await expect(page.locator('[data-plant="alpha"]')).toContainText("Balanced");
    await expect(page.locator('[data-plant="beta"]')).toContainText("Beta process");
    await expect(page.locator('[data-plant="gamma"]')).toContainText("plant.yaml: stage");
    await page.getByTestId("plants-filter").fill("air");
    await expect(cards).toHaveCount(1);
    await page.getByTestId("plants-filter").fill("");
    await page.getByLabel("Family").selectOption("oxygenates");
    await expect(cards).toHaveText([/Beta process/]);
    // a card keeps the page options
    await expect(page.locator('[data-plant="beta"]')).toHaveAttribute("href", "/p/beta/?theme=dark");
    await page.locator('[data-plant="beta"]').click();
    await expect(page).toHaveURL(/\/p\/beta\/\?theme=dark$/);
  });

  test("a plant's API and routes are under its prefix; the switcher keeps the page", async ({ page }) => {
    await mockApi(page, { plants });
    const paths = apiPaths(page);
    await page.goto("/p/alpha/");
    await expect(page.getByRole("heading", { level: 1 })).toContainText("Test plant");
    const select = page.getByTestId("plant-select");
    await expect(select).toHaveValue("alpha");
    await expect(select.locator("option")).toHaveText(["Alpha plant", "Beta process", "gamma"]);
    await expect(page.getByTestId("all-plants")).toHaveText("process-library /");
    // every request of the plant goes to its prefix; only the list asks the library
    expect(paths.filter((p) => !p.startsWith("/p/alpha/api/"))).toEqual(["/api/plants"]);
    await page.getByRole("navigation", { name: "Pages" }).getByRole("link", { name: "Stream table" }).click();
    await expect(page).toHaveURL(/\/p\/alpha\/streams$/);
    await select.selectOption("beta");
    await expect(page).toHaveURL(/\/p\/beta\/streams$/);
    await expect(page.getByTestId("plant-select")).toHaveValue("beta");
    // a sheet is not another plant's: the overview
    await page.goto("/p/beta/pid/process/BFD.xml");
    await page.getByTestId("plant-select").selectOption("alpha");
    await expect(page).toHaveURL(/\/p\/alpha\/$/);
    await page.getByTestId("all-plants").click();
    await expect(page.locator("[data-plant]")).toHaveCount(3);
  });

  test("a server of one plant has no switcher", async ({ page }) => {
    await mockApi(page);
    await page.goto("/");
    await expect(page.getByRole("heading", { level: 1 })).toContainText("Test plant");
    await expect(page.getByTestId("plant-select")).toHaveCount(0);
    await expect(page.getByTestId("all-plants")).toHaveCount(0);
  });
});

const SNAPSHOT = resolve(dirname(fileURLToPath(import.meta.url)), "snapshot");

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

test.describe("a snapshot's link back", () => {
  test("links back to the page that opened it, on this site only", async ({ page }) => {
    await serveSnapshot(page);
    await page.goto("/?data=/e2e-snapshot/&back=/processes/asu-1/&back_label=Process%20Atlas#/");
    const back = page.getByTestId("back-link");
    await expect(back).toHaveText("← Process Atlas");
    await expect(back).toHaveAttribute("href", "/processes/asu-1/");
    // it stays on other pages
    await page.getByRole("navigation", { name: "Pages" }).getByRole("link", { name: "Stream table" }).click();
    await expect(page.getByTestId("back-link")).toBeVisible();
    await page.goto("/?data=/e2e-snapshot/&back=https://evil.example/&back_label=x#/");
    await expect(page.getByRole("heading", { level: 1 })).toBeVisible();
    await expect(page.getByTestId("back-link")).toHaveCount(0);
  });
});
