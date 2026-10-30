import { expect, test } from "@playwright/test";
import { controlSeparation, mockApi, streams, teaAsu } from "./fixtures";

/**
 * Long pages (#67): a section bar that stays on top, loop rows clamped with "more", sequences and
 * info findings folded, stream compositions shortened to their largest fractions.
 */

test.describe("long pages", () => {
  test("the section bar links each section and marks the one in view", async ({ page }) => {
    await mockApi(page, { control: controlSeparation });
    await page.goto("/control");
    const bar = page.getByRole("navigation", { name: "Sections" });
    await expect(bar.getByRole("link")).toHaveText(["Files", "Loops", "Sequences", "Process narrative", "Control philosophy", "Findings"]);
    await bar.getByRole("link", { name: "Findings" }).click();
    const findings = page.locator("#sec-findings");
    await expect(findings).toBeInViewport();
    await expect(bar).toBeInViewport();
    await expect(bar.getByRole("link", { name: "Findings" })).toHaveAttribute("aria-current", "location");
    // the link is the page with the section's hash: it opens there in a new tab
    await expect(bar.getByRole("link", { name: "Loops" })).toHaveAttribute("href", /\/control#sec-loops$/);
    await page.goto("/control#sec-findings");
    await expect(page.locator("#sec-findings")).toBeInViewport();
  });

  test("a short page has no section bar", async ({ page }) => {
    await mockApi(page);
    await page.goto("/checks");
    await expect(page.getByRole("navigation", { name: "Sections" })).toBeHidden();
  });

  test("control: loop rows unfold one by one or all; info findings folded", async ({ page }) => {
    await mockApi(page, { control: controlSeparation });
    await page.goto("/control");
    const fic = page.locator('tr[data-loop="FIC-101"]');
    const more = fic.locator('[data-action="loop-details"]');
    await expect(more).toHaveAttribute("aria-expanded", "false");
    await more.click();
    await expect(more).toHaveAttribute("aria-expanded", "true");
    await expect(fic).toHaveClass(/open/);
    await page.locator('[data-action="all-loop-details"]').check();
    await expect(page.locator('[data-action="loop-details"]')).toHaveCount(0);
    // two sequences: both open
    await expect(page.locator("details[data-sequence]")).toHaveCount(2);
    await expect(page.locator('details[data-sequence="SEQ-START"]')).toHaveAttribute("open", "");
    // seven info findings: folded, one click away
    const infos = page.getByTestId("info-findings");
    await expect(infos.locator("summary")).toHaveText("7 info findings");
    await expect(infos.locator("li").first()).toBeHidden();
    await infos.locator("summary").click();
    await expect(infos.locator("li")).toHaveCount(7);
    await expect(infos.locator("li").first()).toBeVisible();
  });

  test("streams: a long composition shows its largest fractions, all of it on a selected row or with the toggle", async ({ page }) => {
    await mockApi(page);
    const first = streams.streams[0]!;
    const long = {
      ...streams,
      streams: [{ ...first, composition: { basis: "mole_fraction", values: { N2: 0.754593, O2: 0.202435, AR: 0.0090261, H2O: 0.03354, CO2: 0.0004059 }, provenance: "calculated", source: "" } }, ...streams.streams.slice(1)],
    };
    await page.route(/\/api\/streams(\?|$)/, (route) => route.fulfill({ json: long }));
    await page.goto("/streams");
    const row = page.locator(`tr[data-stream="${first.id}"]`);
    await expect(row.locator('[data-composition="compact"]')).toHaveText("mol: N2 0.755, O2 0.202, H2O 0.0335 +2 more");
    await row.click();
    await expect(row).toContainText("CO2 0.0004059");
    await row.click();
    await expect(row.locator('[data-composition="compact"]')).toBeVisible();
    await page.locator('[data-action="full-composition"]').check();
    await expect(row.locator('[data-composition="compact"]')).toHaveCount(0);
  });

  test("the TEA page has the bar with its sections", async ({ page }) => {
    await mockApi(page, { tea: teaAsu });
    await page.goto("/tea");
    const bar = page.getByRole("navigation", { name: "Sections" });
    await expect(bar.getByRole("link", { name: "Boundary" })).toBeVisible();
    await expect(bar.getByRole("link", { name: "Break-even" })).toBeVisible();
  });
});
