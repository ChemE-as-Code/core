import { expect, test, type Page } from "@playwright/test";
import { readFileSync } from "node:fs";
import { dirname, join, resolve } from "node:path";
import { fileURLToPath } from "node:url";
import { SHEET, mockApi, repo, simulationRun } from "./fixtures";

/**
 * The section pages (`/section/<id>`): each group of the sidebar opens a page with its intro and
 * its pages and documents as cards, the drawn sheets with a thumbnail of the drawing.
 */

const nav = (page: Page) => page.getByRole("navigation", { name: "Pages" });
const cards = (page: Page) => page.getByTestId("section-cards").locator(".card");

/** Whether the image has loaded (a broken or blocked one has no natural width). */
const loaded = (img: import("@playwright/test").Locator) =>
  img.evaluate((el) => {
    const image = el as unknown as { complete: boolean; naturalWidth: number };
    return image.complete && image.naturalWidth > 0;
  });

test.describe("section pages", () => {
  test("a sidebar heading opens its section: the P&IDs with thumbnails", async ({ page }) => {
    await mockApi(page);
    await page.goto("/");
    const heading = nav(page).locator('section[data-group="pid"] h2');
    await expect(heading).toHaveText("P&IDs");
    await heading.getByRole("link").click();
    await expect(page).toHaveURL(/\/section\/pid$/);
    await expect(page.getByRole("heading", { level: 1 })).toHaveText("P&IDs");
    await expect(page.locator(".intro")).toContainText("piping and instrumentation");
    await expect(page).toHaveTitle("P&IDs – Test plant – cheme-as-code viewer");
    await expect(heading.getByRole("link")).toHaveAttribute("aria-current", "page");
    await expect(nav(page).locator('section[data-group="process"] h2 a')).not.toHaveAttribute("aria-current", "page");
    await expect(cards(page)).toHaveCount(1);
    const card = cards(page).first();
    await expect(card).toContainText("P-01");
    await expect(card).toContainText("Feed section");
    await expect(card).toContainText(SHEET);
    const img = card.locator(".thumb img");
    await expect(img).toHaveAttribute("src", /pid\.svg\?path=pid%2FP-01\.xml/);
    await expect(img).toHaveAttribute("loading", "lazy");
    // decorative: the card's own text names the sheet (the link's name does not repeat it)
    await expect(img).toHaveAttribute("alt", "");
    await expect.poll(() => loaded(img)).toBe(true);
    // a card opens its page
    await card.click();
    await expect(page).toHaveURL(/\/pid\/pid\/P-01\.xml$/);
  });

  test("the Process section: BFD and PFD with thumbnails, then the stream table", async ({ page }) => {
    await mockApi(page);
    await page.goto("/section/process");
    await expect(page.getByRole("heading", { level: 1 })).toHaveText("Process");
    await expect(cards(page).locator("strong")).toHaveText([/BFD/, /PFD/, /Stream table/]);
    await expect(cards(page).locator(".thumb img")).toHaveCount(2);
    for (const img of await cards(page).locator(".thumb img").all()) await expect(img).toHaveAttribute("src", /pid\.svg/);
    const streams = cards(page).filter({ hasText: "Stream table" });
    await expect(streams.locator(".thumb")).toHaveCount(0);
    await expect(streams).toContainText("Stream values, provenance and balances");
    await streams.click();
    await expect(page).toHaveURL(/\/streams$/);
  });

  test("keeps the revision on its links and thumbnails", async ({ page }) => {
    await mockApi(page);
    await page.goto("/section/process?rev=abc123");
    await expect(cards(page).first().locator("img")).toHaveAttribute("src", /rev=abc123/);
    await expect(nav(page).locator('section[data-group="pid"] h2 a')).toHaveAttribute("href", /\/section\/pid\?rev=abc123$/);
    await cards(page).filter({ hasText: "Stream table" }).click();
    await expect(page).toHaveURL(/\/streams\?rev=abc123$/);
  });

  test("a card keeps its own query and the revision", async ({ page }) => {
    await mockApi(page, { simulation: simulationRun });
    await page.goto("/section/process?rev=abc123");
    const simulation = cards(page).filter({ hasText: "Simulation" });
    await expect(simulation).toHaveAttribute("href", /\/streams\?tab=simulation&rev=abc123$/);
    await simulation.click();
    await expect(page).toHaveURL(/\/streams\?tab=simulation&rev=abc123$/);
  });

  test("a planned sheet has no card", async ({ page }) => {
    await mockApi(page);
    const planned = { id: "P-02", file: "pid/P-02.xml", title: "Distillation", kind: "pid", status: "planned" };
    await page.route(/\/api\/repo(\?|$)/, (route) => route.fulfill({ json: { ...repo, sheets: [...repo.sheets, planned] } }));
    await page.goto("/section/pid");
    await expect(cards(page)).toHaveCount(1);
    await expect(page.locator('[data-item="pid/P-02.xml"]')).toHaveCount(0);
    await expect(page.locator('img[src*="P-02"]')).toHaveCount(0);
  });

  test("a thumbnail that does not load is left out, the card stays", async ({ page }) => {
    await mockApi(page);
    // as at a revision the sheet is not drawn at
    await page.route("**/api/pid.svg*", (route) => route.fulfill({ status: 404, contentType: "application/json", body: '{"error":"not found"}' }));
    await page.goto("/section/pid?rev=abc123");
    await expect(cards(page)).toHaveCount(1);
    await expect(cards(page).first()).toContainText("Feed section");
    await expect(cards(page).first().locator(".thumb")).toHaveCount(0);
  });

  test("does not call a section empty while the documents are still loading", async ({ page }) => {
    // the Equipment section holds only a document, listed once /api/tree has answered
    await mockApi(page, { extraTree: [{ path: "equipment/equipment-list.yaml", type: "file", kind: "yaml" }] });
    let release!: () => void;
    const held = new Promise<void>((resolve) => (release = resolve));
    await page.route(/\/api\/tree(\?|$)/, async (route) => {
      await held;
      await route.fallback();
    });
    await page.goto("/section/equipment");
    await expect(page.getByRole("heading", { level: 1 })).toHaveText("Equipment and lists");
    await expect(page.getByRole("status")).toHaveText("Loading…");
    await expect(page.getByTestId("section-notice")).toHaveCount(0);
    release();
    await expect(cards(page).filter({ hasText: "equipment/equipment-list.yaml" })).toHaveCount(1);
    await expect(page.getByTestId("section-notice")).toHaveCount(0);
  });

  test("an unknown or an empty section says so and links back to the overview", async ({ page }) => {
    await mockApi(page, { hasLayout: false });
    await page.goto("/section/nope");
    await expect(page.getByRole("heading", { level: 1 })).toHaveText("Section not found");
    await expect(page.getByTestId("section-notice")).toContainText('There is no section "nope"');
    await page.goto("/section/layout");
    await expect(page.getByRole("heading", { level: 1 })).toHaveText("Layout");
    await expect(page.getByTestId("section-notice")).toContainText("This plant has nothing in Layout yet.");
    await expect(page.getByTestId("section-cards")).toHaveCount(0);
    await page.getByTestId("section-notice").getByRole("link", { name: "Back to the overview" }).click();
    await expect(page).toHaveURL(/\/$/);
  });

  test("the home page's group headings link to their sections", async ({ page }) => {
    await mockApi(page);
    await page.goto("/");
    const quality = page.getByTestId("home-pages").locator('section[data-group="quality"] h3');
    await expect(quality).toHaveText("Quality");
    await quality.getByRole("link").click();
    await expect(page).toHaveURL(/\/section\/quality$/);
    await expect(cards(page).locator("strong")).toHaveText(["Checks", "Validation", "Maturity", "Reviews"]);
    // the sheet headings above lead to their sections too (the P&IDs have no group below)
    await page.goto("/");
    await page.getByRole("heading", { level: 2, name: "P&ID sheets" }).getByRole("link").click();
    await expect(page).toHaveURL(/\/section\/pid$/);
    await expect(cards(page)).toHaveCount(1);
  });

  test("under a library server's plant prefix", async ({ page }) => {
    await mockApi(page, {
      plants: { root_name: "process-library", plants: [{ id: "alpha", path: "processes/alpha", name: null, stage: "concept", sheets: 2, maturity: null, maturity_checked: null, title: null, summary: null, families: [], error: null }] },
    });
    await page.goto("/p/alpha/");
    await nav(page).locator('section[data-group="process"] h2 a').click();
    await expect(page).toHaveURL(/\/p\/alpha\/section\/process$/);
    await expect(cards(page).first().locator("img")).toHaveAttribute("src", /^\/p\/alpha\/api\/pid\.svg/);
  });
});

test.describe("section pages in a static snapshot", () => {
  const SNAPSHOT = resolve(dirname(fileURLToPath(import.meta.url)), "snapshot");

  test("hash routes, thumbnails from the snapshot, no server", async ({ page }) => {
    await page.route((url) => url.pathname.startsWith("/e2e-snapshot/"), async (route) => {
      const path = new URL(route.request().url()).pathname.replace(/^\/e2e-snapshot\//, "");
      try {
        // as a static host serves it: an <img> shows an SVG only with its media type
        const contentType = path.endsWith(".svg") ? "image/svg+xml" : undefined;
        await route.fulfill({ body: readFileSync(join(SNAPSHOT, path)), ...(contentType ? { contentType } : {}) });
      } catch {
        await route.fulfill({ status: 404, body: "not found" });
      }
    });
    const calls: string[] = [];
    page.on("request", (r) => {
      if (new URL(r.url()).pathname.startsWith("/api/")) calls.push(r.url());
    });
    await page.route((url) => url.pathname.startsWith("/api/"), (route) => route.abort());
    await page.goto("/?data=/e2e-snapshot/#/");
    await nav(page).locator('section[data-group="process"] h2 a').click();
    await expect(page).toHaveURL(/#\/section\/process$/);
    await expect(page.getByRole("heading", { level: 1 })).toHaveText("Process");
    const imgs = cards(page).locator(".thumb img");
    await expect(imgs).toHaveCount(2);
    await expect(imgs.first()).toHaveAttribute("src", /e2e-snapshot\//);
    await expect.poll(() => loaded(imgs.first())).toBe(true);
    await cards(page).filter({ hasText: "Stream table" }).click();
    await expect(page).toHaveURL(/#\/streams$/);
    expect(calls).toEqual([]);
  });
});
