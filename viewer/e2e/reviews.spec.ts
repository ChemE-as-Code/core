import { expect, test } from "@playwright/test";
import { mockApi, statusAsu } from "./fixtures";

/**
 * The review register and the sign-off strip: the ASU's real `/api/status` (13 records, 9 open
 * findings, none blocking) with two sign-offs, `basic` on a branch not merged into main.
 */
const open = statusAsu.reviews.open;

test.describe("reviews and sign-offs", () => {
  test("the home page shows who signed off each stage, and warns off the default branch", async ({ page }) => {
    await mockApi(page, { reviews: true });
    await page.goto("/");
    const strip = page.getByRole("region", { name: "Sign-offs" });
    const basic = strip.locator('[data-stage="basic"]');
    await expect(basic).toContainText("A. Engineer");
    await expect(basic).toContainText(statusAsu.signoffs.basic.commit.slice(0, 7));
    await expect(basic.getByTestId("not-on-default")).toHaveText("not on main");
    const concept = strip.locator('[data-stage="concept"]');
    await expect(concept).toContainText(statusAsu.signoffs.concept.commit.slice(0, 7));
    await expect(concept.getByTestId("not-on-default")).toHaveCount(0);

    await basic.getByRole("link", { name: /review/ }).click();
    await expect(page).toHaveURL(/\/file\/reviews\/2026-10-23-layout-review9\.md/);
    await expect(page.locator("article.doc")).toContainText("ninth review");
  });

  test("the register: counts, severity and record filters, links to the records", async ({ page }) => {
    await mockApi(page, { reviews: true });
    await page.goto("/");
    await page.getByRole("navigation", { name: "Pages" }).getByRole("link", { name: "Reviews" }).click();
    await expect(page).toHaveURL(/\/reviews/);
    await expect(page.getByTestId("open-count")).toHaveText(`${open.length} open`);
    await expect(page.getByTestId("blocking-count")).toHaveText("0 blocking");
    await expect(page.getByText("from cheme status of the working tree")).toBeVisible();

    const register = page.getByRole("region", { name: "Open findings" });
    await expect(register.locator("[data-finding]")).toHaveCount(open.length);
    // Markdown with the <br> lists of the record's table cell
    const first = register.locator('[data-finding="2026-10-23-layout-review9#1"]');
    await expect(first.locator("li").first()).toContainText("SP-8.9");

    await page.locator('[data-action="severity"]').selectOption("medium");
    await expect(register.locator("[data-finding]")).toHaveCount(1);
    await expect(page).toHaveURL(/severity=medium/);
    await page.locator('[data-action="severity"]').selectOption("");
    await page.locator('[data-action="record"]').selectOption("reviews/2026-10-22-layout-review3.md");
    await expect(register.locator("[data-finding]")).toHaveCount(3);

    const records = page.getByRole("region", { name: "Records" });
    await expect(records.locator("tbody tr")).toHaveCount(statusAsu.reviews.records);
    await expect(records.locator('[data-record="2026-10-23-layout-review9"] [data-col="open"]')).toContainText("5");
    await expect(records.locator('[data-record="2026-10-21-layout"] [data-col="closed"]')).not.toHaveText("0");

    const finding = register.locator('[data-finding="2026-10-22-layout-review3#2"]');
    await expect(finding).toContainText("listed open in 2026-10-23-layout-review9");
    await finding.getByRole("link", { name: "2026-10-22-layout-review3" }).click();
    await expect(page).toHaveURL(/\/file\/reviews\/2026-10-22-layout-review3\.md/);
  });

  test("a high finding is blocking", async ({ page }) => {
    const status = { ...statusAsu, reviews: { ...statusAsu.reviews, open: open.map((f, i) => (i === 0 ? { ...f, severity: "high" } : f)) } };
    await mockApi(page, { reviews: true, status });
    await page.goto("/reviews");
    await expect(page.getByTestId("blocking-count")).toHaveText("1 blocking");
    await page.locator('[data-action="severity"]').selectOption("blocking");
    const shown = page.getByRole("region", { name: "Open findings" }).locator("[data-finding]");
    await expect(shown).toHaveCount(1);
    await expect(shown.first()).toHaveAttribute("data-finding", open[0]!.id);
    await expect(shown.first().locator(".badge.fail")).toHaveText("blocking");
  });

  test("without /api/status the register is derived from the records", async ({ page }) => {
    await mockApi(page, { reviews: true, status: null });
    await page.goto("/reviews");
    await expect(page.getByTestId("status-note")).toContainText("no /api/status");
    await expect(page.getByTestId("open-count")).toHaveText(`${open.length} open`);
    // the sign-offs from checks/status.json, without knowing the default branch
    await expect(page.getByRole("region", { name: "Sign-offs" }).locator('[data-stage="basic"]')).toContainText("A. Engineer");
    await expect(page.getByTestId("not-on-default")).toHaveCount(0);
  });

  test("at another revision the records are read there", async ({ page }) => {
    const calls: string[] = [];
    page.on("request", (r) => calls.push(new URL(r.url()).pathname));
    await mockApi(page, { reviews: true });
    await page.goto("/reviews?rev=main");
    await expect(page.getByTestId("open-count")).toHaveText(`${open.length} open`);
    await expect(page.getByText("derived from the records at main")).toBeVisible();
    expect(calls).not.toContain("/api/status");
  });

  test("fits a phone", async ({ page }) => {
    await page.setViewportSize({ width: 375, height: 740 });
    await mockApi(page, { reviews: true });
    for (const url of ["/", "/reviews"]) {
      await page.goto(url);
      await expect(page.getByRole("region", { name: "Sign-offs" }).locator('[data-stage="basic"]')).toBeVisible();
      const overflow = await page.locator("main").evaluate((el) => el.scrollWidth - el.clientWidth);
      expect(overflow, url).toBeLessThanOrEqual(1);
    }
  });
});
