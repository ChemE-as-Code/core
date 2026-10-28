// Embed mode (`?embed=1`) and the forced theme (`?theme=`), as the Process Atlas frames the viewer:
// a static snapshot (e2e/snapshot/, see snapshot.spec.ts) and, for embed, a server (fixtures.ts).
import { expect, test, type Page } from "@playwright/test";
import { readFileSync } from "node:fs";
import { dirname, join, resolve } from "node:path";
import { fileURLToPath } from "node:url";
import { mockApi } from "./fixtures";

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

const DARK_BG = "rgb(20, 23, 27)"; // --bg in the dark scheme
const LIGHT_BG = "rgb(255, 255, 255)";

test.describe("embed", () => {
  test("a snapshot without header and file tree, with a link to the full viewer", async ({ page, baseURL }) => {
    await serveSnapshot(page);
    await page.goto("/?data=/e2e-snapshot/&embed=1#/pid/process/PFD.xml");
    await expect(page.locator(".pane[role='application'] svg").first()).toBeVisible();
    await expect(page.locator("header")).toHaveCount(0);
    await expect(page.getByTestId("snapshot-badge")).toHaveCount(0);
    await expect(page.getByRole("complementary", { name: "Files" })).toHaveCount(0);
    await expect(page.getByRole("button", { name: "Toggle file list" })).toHaveCount(0);
    await expect(page.getByRole("navigation", { name: "Pages" })).toHaveCount(0);

    const link = page.getByTestId("open-full-viewer");
    await expect(link).toHaveText(/Open full viewer/);
    await expect(link).toHaveAttribute("target", "_blank");
    await expect(link).toHaveAttribute("rel", "noopener");
    await expect(link).toHaveAttribute("href", `${baseURL}/?data=%2Fe2e-snapshot%2F#/pid/process/PFD.xml`);

    // The view fills the frame.
    const main = await page.locator("main").boundingBox();
    expect(main).toMatchObject({ x: 0, y: 0, width: 1280, height: 800 });

    // In-view links navigate inside the frame; embed stays and the link follows the route.
    await page.locator("main").getByRole("link", { name: "Stream table" }).click();
    await expect(page.getByRole("heading", { name: /Stream table/ })).toBeVisible();
    expect(new URL(page.url()).search).toContain("embed=1");
    await expect(page.locator("header")).toHaveCount(0);
    await expect(link).toHaveAttribute("href", `${baseURL}/?data=%2Fe2e-snapshot%2F#/streams`);
  });

  test("against a server it only hides the chrome", async ({ page, baseURL }) => {
    await mockApi(page);
    await page.goto("/checks?embed=1");
    await expect(page.getByRole("heading", { name: /Engineering-step checks/ })).toBeVisible();
    await expect(page.locator("header")).toHaveCount(0);
    await expect(page.locator("#rev-select")).toHaveCount(0);
    await expect(page.getByRole("complementary", { name: "Files" })).toHaveCount(0);
    await expect(page.getByTestId("open-full-viewer")).toHaveAttribute("href", `${baseURL}/checks`);
  });

  test("against a server embed and theme survive in-app navigation", async ({ page }) => {
    await mockApi(page);
    await page.goto("/?embed=1&theme=dark");
    await page.getByRole("link", { name: "Review findings" }).click();
    await expect(page).toHaveURL(/\/reviews\?/);
    const params = new URL(page.url()).searchParams;
    expect(params.get("embed")).toBe("1");
    expect(params.get("theme")).toBe("dark");
    await expect(page.locator("header")).toHaveCount(0);
  });

  test("without embed the full chrome is there and no link", async ({ page }) => {
    await serveSnapshot(page);
    await page.goto("/?data=/e2e-snapshot/#/");
    await expect(page.getByTestId("snapshot-badge")).toBeVisible();
    await expect(page.getByRole("complementary", { name: "Files" })).toBeVisible();
    await expect(page.getByTestId("open-full-viewer")).toHaveCount(0);
  });
});

test.describe("theme", () => {
  test("theme=dark sets data-theme and a dark background", async ({ page }) => {
    await page.emulateMedia({ colorScheme: "light" });
    await serveSnapshot(page);
    await page.goto("/?data=/e2e-snapshot/&theme=dark#/streams");
    await expect(page.getByRole("heading", { name: /Stream table/ })).toBeVisible();
    await expect(page.locator("html")).toHaveAttribute("data-theme", "dark");
    await expect(page.locator("body")).toHaveCSS("background-color", DARK_BG);
    // Kept across in-frame navigation (it lives before the hash).
    await page.goto("/?data=/e2e-snapshot/&theme=dark#/checks");
    await expect(page.locator("html")).toHaveAttribute("data-theme", "dark");
    await expect(page.locator("body")).toHaveCSS("background-color", DARK_BG);
  });

  test("theme=light overrides a dark system preference", async ({ page }) => {
    await page.emulateMedia({ colorScheme: "dark" });
    await serveSnapshot(page);
    await page.goto("/?data=/e2e-snapshot/#/streams");
    await expect(page.getByRole("heading", { name: /Stream table/ })).toBeVisible();
    await expect(page.locator("body")).toHaveCSS("background-color", DARK_BG);

    await page.goto("/?data=/e2e-snapshot/&theme=light&embed=1#/streams");
    await expect(page.getByRole("heading", { name: /Stream table/ })).toBeVisible();
    await expect(page.locator("html")).toHaveAttribute("data-theme", "light");
    await expect(page.locator("body")).toHaveCSS("background-color", LIGHT_BG);
  });

  test("theme=system follows the system preference", async ({ page }) => {
    await page.emulateMedia({ colorScheme: "dark" });
    await mockApi(page);
    await page.goto("/checks?theme=system");
    await expect(page.locator("html")).not.toHaveAttribute("data-theme", /.*/);
    await expect(page.locator("body")).toHaveCSS("background-color", DARK_BG);
  });
});
