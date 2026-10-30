import { expect, test, type Locator, type Page } from "@playwright/test";
import { METADATA, SHEET, TITLE_BLOCK, impact, mockApi, repo } from "./fixtures";

interface Transform {
  x: number;
  y: number;
  k: number;
}

/** The pan/zoom transform of a pane's stage (`translate(Xpx, Ypx) scale(K)`). */
async function transformOf(stage: Locator): Promise<Transform> {
  const style = (await stage.getAttribute("style")) ?? "";
  const match = /translate\(([-\d.e]+)px, ([-\d.e]+)px\) scale\(([-\d.e]+)\)/.exec(style);
  if (!match) throw new Error(`no transform in ${style}`);
  return { x: Number(match[1]), y: Number(match[2]), k: Number(match[3]) };
}

async function centreOf(locator: Locator): Promise<{ x: number; y: number }> {
  const box = await locator.boundingBox();
  if (!box) throw new Error("not visible");
  return { x: box.x + box.width / 2, y: box.y + box.height / 2 };
}

async function openSheet(page: Page): Promise<{ pane: Locator; stage: Locator }> {
  await mockApi(page);
  await page.goto(`/pid/${SHEET}`);
  const pane = page.locator(".pid .pane");
  await expect(pane.locator('[id="Pump1"]')).toBeAttached();
  const stage = pane.locator(".stage");
  // Wait for the first fit.
  await expect.poll(async () => (await transformOf(stage)).k).not.toBe(1);
  return { pane, stage };
}

test.describe("P&ID pane", () => {
  test("wheel zooms around the pointer", async ({ page }) => {
    const { pane, stage } = await openSheet(page);
    const before = await transformOf(stage);
    const at = await centreOf(pane);
    await page.mouse.move(at.x, at.y);
    await page.mouse.wheel(0, -300);
    await expect.poll(async () => (await transformOf(stage)).k).toBeGreaterThan(before.k * 1.2);
    const zoomedIn = await transformOf(stage);
    // The point under the pointer stays put: (p - t) / k is unchanged.
    const box = (await pane.boundingBox())!;
    const px = at.x - box.x;
    expect((px - zoomedIn.x) / zoomedIn.k).toBeCloseTo((px - before.x) / before.k, 1);
    await page.mouse.wheel(0, 600);
    await expect.poll(async () => (await transformOf(stage)).k).toBeLessThan(zoomedIn.k);
  });

  test("drag pans without zooming", async ({ page }) => {
    const { pane, stage } = await openSheet(page);
    const before = await transformOf(stage);
    const at = await centreOf(pane);
    await page.mouse.move(at.x, at.y);
    await page.mouse.down();
    await page.mouse.move(at.x + 60, at.y + 30, { steps: 6 });
    await page.mouse.move(at.x + 120, at.y + 50, { steps: 6 });
    await page.mouse.up();
    const after = await transformOf(stage);
    expect(after.k).toBe(before.k);
    expect(after.x - before.x).toBeCloseTo(120, 0);
    expect(after.y - before.y).toBeCloseTo(50, 0);
    // A drag is not a click: nothing gets selected.
    await expect(page.locator("aside.info")).toHaveCount(0);
  });

  test("Fit resets zoom and pan", async ({ page }) => {
    const { pane, stage } = await openSheet(page);
    const fitted = await transformOf(stage);
    const at = await centreOf(pane);
    await page.mouse.move(at.x, at.y);
    await page.mouse.wheel(0, -400);
    await page.mouse.down();
    await page.mouse.move(at.x - 80, at.y + 40, { steps: 8 });
    await page.mouse.up();
    expect(await transformOf(stage)).not.toEqual(fitted);
    await pane.getByRole("button", { name: "Fit" }).click();
    const reset = await transformOf(stage);
    expect(reset.k).toBeCloseTo(fitted.k, 6);
    expect(reset.x).toBeCloseTo(fitted.x, 3);
    expect(reset.y).toBeCloseTo(fitted.y, 3);
    // So does the 0 key.
    await page.mouse.wheel(0, -200);
    await pane.focus();
    await page.keyboard.press("0");
    expect((await transformOf(stage)).k).toBeCloseTo(fitted.k, 6);
  });

  test("clicking a drawn object shows its id and labels", async ({ page }) => {
    const { pane } = await openSheet(page);
    await pane.locator('[id="Pump1"] circle').click();
    const info = page.locator("aside.info");
    await expect(info).toBeVisible();
    await expect(info.locator("dd code")).toHaveText("Pump1");
    await expect(info).toContainText("representation-group");
    await expect(info).toContainText("P-101");
    // The title block is an object too (render gives it its Label's id).
    await pane.locator(`[id="${TITLE_BLOCK}"] text`).first().click();
    await expect(info.locator("dd code")).toHaveText(TITLE_BLOCK);
    await expect(info).toContainText("Test plant");
    await page.keyboard.press("Escape");
    await expect(info).toHaveCount(0);
  });
});

test.describe("diff", () => {
  test("a metadata change highlights the title block", async ({ page }) => {
    await mockApi(page);
    await page.goto(`/diff/${SHEET}?old=HEAD`);
    const newPane = page.locator(".canvas .pane").nth(1);
    const line = newPane.locator(`[id="${TITLE_BLOCK}"] polyline`);
    await expect(line).toBeAttached();
    // modified = #e08a00, as cheme diff colours it.
    await expect(line).toHaveCSS("stroke", "rgb(224, 138, 0)");
    await expect(newPane.locator(`[id="${TITLE_BLOCK}"] text`).last()).toHaveCSS("fill", "rgb(224, 138, 0)");
    await expect(newPane.locator('[id="Pump1"] circle')).toHaveCSS("stroke", "rgb(0, 0, 0)");
    // The change row names the drawing that shows it; clicking it selects the title block.
    const row = page.locator("table.data tbody tr", { hasText: METADATA });
    await expect(row).toContainText(`in ${TITLE_BLOCK}`);
    // The domain and attribute columns show what the real server sends for it.
    await expect(row.locator("td").nth(1)).toHaveText("metadata");
    await expect(row).toContainText("approvalDateRepresentation");
    await row.click();
    await expect(row).toHaveClass(/selected/);
    // Clicking the title block lists the metadata change.
    await newPane.locator(`[id="${TITLE_BLOCK}"] text`).first().click();
    const info = page.locator("aside.info");
    await expect(info.locator("dd code")).toHaveText(TITLE_BLOCK);
    await expect(info.locator(".changes")).toContainText(METADATA);
  });
});

test.describe("file view", () => {
  test("YAML source is highlighted and markup stays text", async ({ page }) => {
    await mockApi(page);
    await page.goto("/file/lists/equipment.yaml");
    const source = page.getByRole("region", { name: "File content" });
    await expect(source.locator("pre.yaml").first()).toBeVisible();
    await expect(source.locator(".y-key", { hasText: "items" })).toBeVisible();
    await expect(source.locator(".y-string", { hasText: '"P-101"' })).toBeVisible();
    await expect(source.locator(".y-comment", { hasText: "# feed pump" })).toBeVisible();
    await expect(source.locator(".y-number", { hasText: "80" })).toBeVisible();
    await expect(source.locator(".y-string", { hasText: "key: not a key" })).toBeVisible();
    // The quoted <script> is shown as text, never parsed.
    await expect(source.locator("script")).toHaveCount(0);
    await expect(source.locator(".y-string", { hasText: "<script>alert(1)</script>" })).toBeVisible();
  });
});

test.describe("validation", () => {
  test("lists the review-needed artifacts above the findings and opens them", async ({ page }) => {
    await mockApi(page);
    await page.goto("/validate");
    const review = page.getByRole("region", { name: /Review needed/ });
    await expect(review.locator("h2 .badge")).toHaveText(String(impact.findings.length));
    await expect(review.locator("li")).toHaveCount(impact.findings.length);
    await expect(review).toContainText("process/BFD.xml");
    await expect(review).toContainText("changed since it was generated");
    // The validation findings follow, including what the flowsheet edit causes there.
    await expect(page.locator("table.data")).toContainText("cheme.generated-outdated");
    // The filter applies to both lists.
    await page.getByPlaceholder("Filter findings").fill("PFD.xml");
    await expect(review.locator("li")).toHaveCount(1);
    await review.locator("li button").click();
    await expect(page).toHaveURL(/\/pid\/process\/PFD\.xml$/);
  });

  test("an older server without /api/impact shows the findings only", async ({ page }) => {
    await mockApi(page);
    await page.route(/\/api\/impact(\?|$)/, (route) =>
      route.fulfill({ status: 404, contentType: "application/json", body: JSON.stringify({ error: "no endpoint /api/impact" }) }),
    );
    await page.goto("/validate");
    await expect(page.locator("table.data")).toContainText("cheme.generated-outdated");
    await expect(page.getByRole("region", { name: /Review needed/ })).toHaveCount(0);
    await expect(page.getByText("no endpoint")).toHaveCount(0);
  });
});

test("the About page names the group and shows the logo", async ({ page }) => {
  await mockApi(page);
  await page.goto("/");
  await expect(page.getByTestId("header-logo")).toBeVisible();
  await page.getByRole("link", { name: "About" }).click();
  await expect(page).toHaveURL(/\/about/);
  await expect(page.getByTestId("about-group")).toContainText("Process Intelligence Research");
  await expect(page.getByTestId("about-person")).toContainText("Artur M. Schweidtmann");
  await expect(page.getByTestId("about-logo")).toHaveJSProperty("complete", true);
  // Artur's photo, and the way out to the home page and the code
  await expect(page.getByTestId("about-photo")).toHaveJSProperty("complete", true);
  expect(await page.getByTestId("about-photo").evaluate((img) => (img as { naturalWidth: number }).naturalWidth)).toBeGreaterThan(0);
  await expect(page.getByTestId("about-sites").getByRole("link", { name: /Home page/ })).toHaveAttribute("href", "https://cheme-as-code.org");
  await expect(page.getByTestId("about-sites").getByRole("link", { name: "The code on GitHub" })).toHaveAttribute("href", "https://github.com/ChemE-as-Code/core");
  await expect(page.getByTestId("header-home")).toHaveAttribute("href", "https://cheme-as-code.org");
  await expect(page.getByTestId("header-code")).toHaveAttribute("href", "https://github.com/ChemE-as-Code/core");
});

test("a planned sheet is listed on the home page without a link", async ({ page }) => {
  await mockApi(page);
  const planned = { id: "P-02", file: "pid/P-02.xml", title: "Distillation", kind: "pid", status: "planned" };
  await page.route(/\/api\/repo(\?|$)/, (route) => route.fulfill({ json: { ...repo, sheets: [...repo.sheets, planned] } }));
  await page.goto("/");
  const card = page.locator('[data-sheet="P-02"]');
  await expect(card).toContainText("planned");
  await expect(card).not.toHaveAttribute("href");
  await expect(page.locator('a[data-sheet="P-01"]')).toHaveAttribute("href", /\/pid\/pid\/P-01\.xml/);
});