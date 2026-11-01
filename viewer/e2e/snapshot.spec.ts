// The viewer on a static snapshot (`?data=`), no server: e2e/snapshot/ is `cheme export-static` of
// core's examples/process-recycle. Requests to /api must not happen at all.
import { expect, test } from "@playwright/test";
import { readFileSync } from "node:fs";
import { dirname, join, resolve } from "node:path";
import { fileURLToPath } from "node:url";

const SNAPSHOT = resolve(dirname(fileURLToPath(import.meta.url)), "snapshot");
const manifest = JSON.parse(readFileSync(join(SNAPSHOT, "manifest.json"), "utf-8"));

test.beforeEach(async ({ page }) => {
  await page.route((url) => url.pathname.startsWith("/e2e-snapshot/"), async (route) => {
    const path = new URL(route.request().url()).pathname.replace(/^\/e2e-snapshot\//, "");
    try {
      await route.fulfill({ body: readFileSync(join(SNAPSHOT, path)) });
    } catch {
      await route.fulfill({ status: 404, body: "not found" });
    }
  });
  await page.route((url) => url.pathname.startsWith("/api/"), (route) => route.abort());
});

function apiCalls(page: import("@playwright/test").Page): string[] {
  const calls: string[] = [];
  page.on("request", (r) => {
    if (new URL(r.url()).pathname.startsWith("/api/")) calls.push(r.url());
  });
  return calls;
}

test("opens the snapshot: header, sheets, drawing", async ({ page }) => {
  const calls = apiCalls(page);
  await page.goto("/?data=/e2e-snapshot/#/");
  await expect(page.getByTestId("snapshot-badge")).toContainText(`Snapshot ${manifest.source.commit.slice(0, 8)}`);
  await expect(page.locator("#rev-select")).toHaveCount(0);
  await expect(page.getByRole("link", { name: "History" })).toHaveCount(0);

  await page.goto("/?data=/e2e-snapshot/#/pid/process/PFD.xml");
  await expect(page.locator(".pane[role='application'] svg").first()).toBeVisible();
  await expect(page.getByRole("link", { name: "Diff" })).toHaveCount(0);
  await expect(page.locator("main").getByRole("link", { name: "Stream table" })).toBeVisible();
  expect(calls).toEqual([]);
});

test("stream table and YAML tables come from the snapshot", async ({ page }) => {
  const calls = apiCalls(page);
  await page.goto("/?data=/e2e-snapshot/#/streams");
  await expect(page.getByRole("heading", { name: /Stream table/ })).toBeVisible();
  await expect(page.locator("table").first()).toBeVisible();
  await page.goto("/?data=/e2e-snapshot/#/yaml/process/flowsheet.yaml");
  await expect(page.locator("main")).toContainText("flowsheet");
  expect(calls).toEqual([]);
});

test("checks show the stored status without a run button", async ({ page }) => {
  await page.goto("/?data=/e2e-snapshot/#/checks");
  await expect(page.getByRole("button", { name: "Run now" })).toHaveCount(0);
  await expect(page.getByText(/running the checks needs/)).toBeVisible();
});

test("what the snapshot lacks is said plainly", async ({ page }) => {
  await page.goto("/?data=/e2e-snapshot/#/yaml/no/such.yaml");
  await expect(page.getByText(/Not included in this static snapshot/)).toBeVisible();
});

test("a missing snapshot is reported", async ({ page }) => {
  await page.goto("/?data=/no-snapshot-here/#/");
  await expect(page.getByText(/No snapshot at/)).toBeVisible();
});

test("a snapshot on another origin is refused without contacting it", async ({ page }) => {
  const foreign: string[] = [];
  await page.route("https://other.example/**", async (route) => {
    foreign.push(route.request().url());
    const path = new URL(route.request().url()).pathname.replace(/^\/snap\//, "");
    await route.fulfill({ headers: { "access-control-allow-origin": "*" }, body: readFileSync(join(SNAPSHOT, path)) });
  });
  await page.goto("/?data=https://other.example/snap/#/");
  await expect(page.getByText(/Refused to open the snapshot at https:\/\/other\.example\/snap\/: it is not on this site/)).toBeVisible();
  await expect(page.getByTestId("snapshot-badge")).toHaveCount(0);
  expect(foreign).toEqual([]);
});

test("the reviews page works without the status a snapshot does not hold", async ({ page }) => {
  const calls = apiCalls(page);
  await page.goto("/?data=/e2e-snapshot/#/reviews");
  await expect(page.getByTestId("status-note")).toContainText("static snapshot has no status");
  await expect(page.getByTestId("open-count")).toHaveText("0 open");
  await expect(page.getByText("No review records in reviews/.")).toBeVisible();
  expect(calls).toEqual([]);
});

test("a snapshot without a simulation or reactions says so", async ({ page }) => {
  const calls = apiCalls(page);
  await page.goto("/?data=/e2e-snapshot/#/streams");
  await expect(page.locator("tr[data-stream]").first()).toBeVisible();
  await expect(page.getByRole("tab")).toHaveCount(0);
  await page.goto("/?data=/e2e-snapshot/#/streams?tab=simulation");
  await expect(page.locator("[data-sim-missing]")).toContainText("No simulation");
  await page.goto("/?data=/e2e-snapshot/#/reactions");
  await expect(page.locator("[data-reactions-missing]")).toContainText("No reactions");
  await expect(page.getByRole("navigation", { name: "Pages" }).getByRole("link", { name: "Reactions" })).toHaveCount(0);
  expect(calls).toEqual([]);
});

/** Serve the snapshot with extra API answers (`key` -> body), as `cheme export-static` would write them. */
async function withEntries(page: import("@playwright/test").Page, extra: Record<string, { body: string; type: string }>): Promise<void> {
  const entries = { ...manifest.entries };
  const bodies: Record<string, string> = {};
  for (const [key, { body, type }] of Object.entries(extra)) {
    const file = `extra-${Object.keys(bodies).length}`;
    entries[key] = { file, status: 200, type };
    bodies[file] = body;
  }
  await page.route("**/e2e-snapshot/manifest.json", (route) => route.fulfill({ contentType: "application/json", body: JSON.stringify({ ...manifest, entries }) }));
  await page.route("**/e2e-snapshot/data/extra-*", (route) => {
    const file = new URL(route.request().url()).pathname.split("/").pop() ?? "";
    return route.fulfill({ body: bodies[file] ?? "" });
  });
}

test("a Markdown link to a heading scrolls there and stays on the page", async ({ page }) => {
  const filler = Array.from({ length: 60 }, (_, i) => `Paragraph ${i + 1} of the introduction.`).join("\n\n");
  await withEntries(page, {
    "file?path=README.md": { type: "text/plain", body: `# Plant\n\nSee [the design basis](#design-basis).\n\n${filler}\n\n## Design basis\n\nFeed 1000 kg/h.\n` },
  });
  await page.goto("/?data=/e2e-snapshot/#/file/README.md");
  const heading = page.getByRole("heading", { name: "Design basis" });
  await expect(heading).toHaveAttribute("id", "user-content-design-basis");
  await expect(heading).not.toBeInViewport();
  const url = page.url();
  await page.getByRole("link", { name: "the design basis" }).click();
  await expect(heading).toBeInViewport();
  await expect(heading).toBeFocused();
  expect(page.url()).toBe(url);
  await expect(page.locator("main")).not.toContainText("Not found");

  // Opened on its own (a new tab), the link's address is this page at that heading.
  const href = await page.getByRole("link", { name: "the design basis" }).getAttribute("href");
  expect(href).toBe("#/file/README.md#design-basis");
  await page.goto(`/?data=/e2e-snapshot/${href}`);
  await expect(page.getByRole("heading", { name: "Design basis" })).toBeInViewport();
  await expect(page.locator("main")).not.toContainText("Not found");
});

test("an MTO total card scrolls to its category without leaving /mto", async ({ page }) => {
  await withEntries(page, { mto: { type: "application/json", body: readFileSync(join(SNAPSHOT, "../../tests/fixtures/api/mto-asu.json"), "utf-8") } });
  await page.goto("/?data=/e2e-snapshot/#/mto");
  const section = page.locator("section#mto-valve");
  await expect(section).toBeAttached();
  await expect(section).not.toBeInViewport();
  await page.locator('.cards a[data-category="valve"]').click();
  await expect(section).toBeInViewport();
  expect(new URL(page.url()).hash).toBe("#/mto");
  await expect(page.locator("main")).not.toContainText("Not found");
});
